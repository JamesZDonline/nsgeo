# Task 7 report: Reproducing a saved cube

## Summary

Implemented the reader half of the cube-recipe round trip: `CubeRecipe`/`recipe_from_record` in
`slice_export.py`, the `Cube` combo and its restore path on `SlicesDock`, and refactored
`plugin.save_cube` to use the dock's own `view_settings()`/`refresh_cube_combo()` rather than a
second, independent construction of the same six values. The `Site.cubes` docstring (brief Step
5) needed no edit — Task 6 had already written the exact text the brief asks for (see Decision 1).

Files touched, matching the brief's list, plus one it didn't name:

- `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py` — `CubeRecipe`, `recipe_from_record`, and a
  small tolerance fix to `ViewSettings.from_dict` (Decision 2).
- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` — `cube_combo` (top of the Source group),
  `refresh_cube_combo`, `restore_cube`, `view_settings`, `apply_view`, `_mark_cube_unsaved`,
  `_on_cube_changed`, and a `_pending_palette` field closing a real gap (Decision 4).
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (not in the brief's file list) — `save_cube` now
  calls `dock.view_settings()` instead of rebuilding `ViewSettings` inline, and calls
  `dock.refresh_cube_combo()` after a successful save (Decision 5).
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py` — the brief's four tests, plus one
  I added (Decision 3), with two of the brief's own snippets corrected (Decision 6).
- `packages/nsgeo-core/src/nsgeo/model/survey.py` — read, not modified (Decision 1).

Task-count deviation: the brief's own text already flags this ("deliberately takes the plan to
seven tasks rather than growing Task 6... Flag the deviation when reporting") — noting it here per
that instruction, not raising a new concern.

## Decision 1: the `Site.cubes` docstring needed no edit

Step 5 asks to replace the paragraph beginning "Unlike every line path elsewhere in a Site..." and
describe the full 8-key shape with the IS/READ split. `git diff 543a30c 4633ab3 --
packages/nsgeo-core/src/nsgeo/model/survey.py` shows Task 6 already made exactly this edit: the
bullet list with `lines`/`z`/`view` and the IS-vs-READ split is already there, and the trailing
paragraph already reads "`cube_record` routes `array` through `line_key` itself... so every record
this Site ever holds is already portable by the time `save_site` sees it" — not the older "M11's
job" wording the brief's own `cube_record` docstring (in `slice_export.py`) quotes. I read the
current text, confirmed it matches the brief's ask verbatim, and made no change rather than
touching a file that was already correct.

## Decision 2: `ViewSettings.from_dict`'s `coverage` field made tolerant

The brief's Step 3 snippet for `ViewSettings.to_dict`/`from_dict` differs from what Task 6 shipped
in one place: `from_dict` used `doc["coverage"]` (a hard `KeyError` if absent); the brief's version
uses `doc.get("coverage", False)`. I applied that one-line tolerance change (leaving `to_dict`
alone, since it's the writer and already correct) — it is not exercised by any given test (the
old-format-record test has no `view` key at all, so `ViewSettings.from_dict` is never even
called), but it is a direct instance of the reader-tolerance rule the rest of this task's code
follows, at zero risk to any existing behaviour.

## Decision 3: added a test to close a real gap the brief's own prose claims is covered

The brief's Step 3 note says the `"none"` ↔ `NO_TRANSFORM` (`""`) mapping "must round-trip -- the
first round-trip test above covers it through `recipe.view == view` and the identical-slice
assertion." It doesn't: `exportable_with_session`'s engine is prepared with
`transform="amp_envelope"`, and every one of the four given tests' records carries `"amp_envelope"`
as `transform`, never `"none"`. The ternary that does the mapping is never exercised on its `"" `
branch by any given test — confirmed empirically in Mutant 3 below (mutating that branch changed
no test's outcome). I added `test_a_recipe_with_no_transform_restores_the_bipolar_choice`, which
explicitly builds a `NO_TRANSFORM` `SourceChoice`, round-trips it through `cube_record` →
`recipe_from_record`, and asserts `recipe.choice.transform == NO_TRANSFORM`. Verified it fails
against Mutant 3 and passes against real code (both shown below). This is squarely within Task
7's own scope — it tests `recipe_from_record`, the function this task exists to add — and closes a
gap the brief itself asserts (incorrectly) is already closed.

## Decision 4: `_pending_palette` — a fix the brief's prose doesn't mention

`restore_cube` applies `recipe.view` (via `apply_view`) *before* it sets the three Source combos
and calls `prepare()`, because Position/Display widgets need blocked signals and the brief places
that step first. But `SliceEngine.set_source` dispatches preparation as an async `QgsTask`, and
`SlicesDock._on_prepared` — which only runs once that task finishes — unconditionally calls
`_refill_palette_combo()`, which resets `palette_combo` to a polarity-computed default regardless
of what was selected before (that method's own docstring: "defaulting to the one named for that
polarity rather than preserving whatever the combo happened to show"). Applying `view.palette`
before `prepare()` would therefore be silently overwritten the moment the async preparation
finishes — every other restored control survives, but the palette specifically would not, which
is exactly the kind of partial-restore failure the manual walkthrough's item 11 ("every control
comes back where it was") is designed to catch.

Fix: `restore_cube` stashes `recipe.view.palette` in a new `self._pending_palette` field.
`_on_prepared` consumes and clears it every time it runs (restore-triggered or not) — if the
stashed name is currently offered (correct polarity), it applies it with signals blocked; either
way the field is cleared, so a value can never outlive the one preparation it was stashed for.
`_on_source_changed` and `set_included` — the two entry points for a *manual*, non-restore change
— clear `_pending_palette` early, so a manual combo/line-set change made while a restore's own
preparation is still in flight cannot inherit a palette that has nothing to do with it. I verified
this by reading `SliceEngine.set_source`/`_finish_preparation` directly rather than assuming: the
task's own `finished()` callback re-derives `self._frame`/`self._z` from `self._choice`/
`self._resolution` at completion time (not at dispatch time), which is also why calling
`flush_debounce()` before `prepare()` — exactly the brief's prescribed order — is safe despite
`self._choice` still naming the *previous* source at the moment `flush_debounce` runs: the
transient mismatch self-heals when the task's own `finished()` callback rebuilds geometry against
the final state.

## Decision 5: `_mark_cube_unsaved` fires on Resolution's four geometry spins, not the fill radius

The brief says `cube_combo` should fall back to `"(unsaved)"` "whenever any Source or Resolution
widget moves away from the restored values." Read literally against the UI's own "Resolution"
`QGroupBox`, that group has five spin boxes (cell, dz, z0, z1, radius) — but `radius_m` is a
`ViewSettings` field, not a `Resolution` field: the engine's `Resolution` dataclass explicitly
excludes it ("The fill radius is NOT here: it is a display parameter applied after binning...")
and it changes no pixel of the array. I wired `_mark_cube_unsaved` to the four fields that *do*
decide what the cube is (`cell_spin`, `dz_spin`, `z0_spin`, `z1_spin`) and left `radius_spin` out,
matching the IS/READ split `cube_record`'s own docstring draws everywhere else in this task. This
also resolved an apparent contradiction in the brief's own restore-ordering prose, which lists
`view` (all six fields, radius included) as applied "to the Display and Position widgets" — i.e.
the brief's own text already treats `radius_m` as belonging with `view`, not with "the Resolution
widgets" step that follows it; my reading of the fallback rule is consistent with that.

## Decision 6: two of the brief's own test snippets didn't run as given

Both `test_a_restored_recipe_reproduces_the_identical_slice` and
`test_a_recipe_restores_the_exact_line_set_not_the_whole_grid`, as written in the brief, call
`cube_record(session, engine.choice, engine.frame, engine.z, view, npz)` — six positional
arguments. `cube_record`'s actual signature (Task 6) requires `line_keys` as a required,
keyword-only seventh argument (Ruling AF: "a caller MUST pass `engine.provenance().line_keys`
here, not `choice.line_keys`"). As given, both tests would raise
`TypeError: cube_record() missing 1 required keyword-only argument: 'line_keys'` on the first line
that calls it. I added `line_keys=engine.provenance().line_keys` to both calls, matching the
pattern every other `cube_record` call in this file already uses (e.g.
`test_the_record_lines_are_what_was_actually_binned_not_what_was_asked_for`). Also ran
`ruff format` on the appended test code, since the brief's compact multi-statement-per-line style
(e.g. `window = SliceWindow(6, 18)` blocks and the dict literals in the two negative tests) is not
this project's format — `ruff format --check .` is part of the CI gate and would otherwise fail.

## Step 6: the four mutants, run for real

Each mutant was applied by hand, the named test(s) run, then reverted; `git diff --stat` confirmed
a clean revert before the next mutant. All four (plus my own added test, run against Mutant 3)
were executed against `.venv-qgis` with `QT_QPA_PLATFORM=offscreen`, `-p no:xonsh`.

**Mutant 1 — `cube_record`: drop the `"lines"` key.**

Brief's prediction: `test_a_recipe_restores_the_exact_line_set_not_the_whole_grid` FAILs; the
identical-slice test should NOT catch it, "since that fixture includes every line."

Observed: **both tests fail**, but for different reasons, and the brief's stated reason for the
identical-slice test's expected pass is not how `recipe_from_record` actually behaves.

- `test_a_recipe_restores_the_exact_line_set_not_the_whole_grid`: `AssertionError: assert () ==
  ('raw/FILE__001.DZT', 'raw/FILE__002.DZT')` — the predicted failure.
- `test_a_restored_recipe_reproduces_the_identical_slice`: `RuntimeError: no lines are prepared`,
  raised from `engine.slice_at(window)` → `SliceEngine._slice`.

The mechanism: `recipe_from_record` reads `record.get("lines", ())`, so a record with no `"lines"`
key restores as `line_keys == ()` — an explicit *zero-line* selection, not "unspecified, use the
whole grid." This is the exact, deliberate behaviour `test_a_record_written_by_an_older_build_
still_loads` demands (`recipe.choice.line_keys == ()  # unknown, not invented`). Since the
identical-slice fixture's engine is prepared over all four lines, dropping `"lines"` from *that*
record restores it with zero lines too — `engine.set_source(recipe.choice)` then binds nothing,
and `slice_at` raises before any numeric comparison is even reached. The brief's assumption
("the fixture includes every line" ⇒ "restoring without a line list would restore that same full
set") does not hold, because nothing in `recipe_from_record` or the engine ever falls back to "the
whole grid" for a missing line list — the reader's own contract is "unknown, not invented," applied
uniformly regardless of what the original selection happened to be. So: Mutant 1 is a *stronger*
discriminator than the brief predicted (it now fails two tests, by two different mechanisms), not
a weaker one — but the brief's specific reasoning about *why* the identical-slice test would stay
green is incorrect for this reader's actual design, and I'm reporting that rather than the brief's
prediction as stated.

**Mutant 2 — `cube_record`: drop the `"z"` key.**

Brief's prediction: identical-slice test FAILs ("the restored engine gets no resolution, so
`slice_at` raises").

Observed: matches exactly. `test_a_restored_recipe_reproduces_the_identical_slice` fails with
`RuntimeError: no slice geometry: choose a source and a resolution first`, raised from
`engine.slice_at` → `SliceEngine._require_geometry`, after `engine.set_resolution(recipe.resolution)`
silently no-ops on `recipe.resolution is None`.

**Mutant 3 — `recipe_from_record`: map `"none"` to `"none"` rather than `""`.**

Brief's prediction: identical-slice test FAILs ("the restored source would append a step named
`none`, which is not in the registry").

Observed: **no given test fails.** All 20 tests in the file (16 pre-existing + the brief's 4) still
pass. Reason, confirmed by direct code reading and then by the empirical result: the identical-
slice fixture's `engine.choice.transform` is `"amp_envelope"`, so `cube_record` writes
`"transform": "amp_envelope"` — the mutated branch (`record.get("transform", "none") == "none"`)
is never true for this record, so the mutation is inert against it. No test in the brief's given
four ever restores a `NO_TRANSFORM` (`transform=""`) choice. I then ran my own added test,
`test_a_recipe_with_no_transform_restores_the_bipolar_choice` (Decision 3), against this same
mutant: it fails, as expected — `AssertionError: assert 'none' == ''` — and passes once the mutant
is reverted. Reported per the brief's own instruction: "if the identical-slice test *does* catch
it, say so" — it does not, and the reason is that the fixture never exercises the branch the
mutant changes, not that the fixture "is not what the brief thinks it is" (the fixture is exactly
what the brief describes; the brief's claim about what it covers is what's wrong).

**Mutant 4 — `recipe_from_record`: wrap the z read in a bare `except: pass`.**

Brief's prediction: `test_a_record_with_a_broken_field_is_refused_by_name` FAILs.

Observed: matches exactly. `Failed: DID NOT RAISE ValueError` — the reversed `t0_ns`/`t1_ns` still
raises inside `Resolution.__post_init__`, but the bare `except Exception: pass` swallows it instead
of re-raising as `ValueError`, so `recipe_from_record` returns silently with `resolution=None`
where the record's own (broken) `z` gets quietly discarded rather than refused.

Every mutant was reverted immediately after its run; `git diff --stat` on `slice_export.py` was
checked after each revert to confirm no residue, and the full `test_plugin_slice_export.py` file
(21 tests, post Decision 3) was re-run green after the last revert.

## Both tiers, and the identical-slice test's tolerance

- **Core + pure (`.venv`)**: `543 passed, 2 skipped` — identical to the stated baseline (this
  task touched no core or pure code besides reading, not editing, `survey.py`).
- **QGIS (`.venv-qgis`, `QT_QPA_PLATFORM=offscreen`, `-p no:xonsh`)**: `599 passed`, **0
  warnings** — the 594-test baseline plus the brief's 4 new tests plus my 1 added test
  (Decision 3). Ran twice: once right after the reader/tests were in place (598, before the dock
  work), and once as the final full-repo run after every change in this task (599).
- `ruff check .`, `ruff format --check .`, and
  `mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
  (the exact CI invocation) are all clean.

**`test_a_restored_recipe_reproduces_the_identical_slice` compares within a tolerance
(`rtol=1e-6, atol=1e-7`), not bit-for-bit — as the brief itself specifies, unmodified.** I did not
loosen, tighten, or otherwise touch that tolerance.

**Correction (fix round 1, Ruling AM):** my original explanation here claimed the tolerance was
needed because the two preparations `before`/`after` come from "are not guaranteed to sum in
bit-identical order" across two independent async runs. That claim does not hold up and I should
not have written it without reading `SliceEngine._start_task`'s `work()` first: `work()` is a
single sequential `for index, (key, line, coords) in enumerate(jobs)` loop with no threading or
reordering inside it, `self._lines = list(result or [])` preserves that order, `provenance()`'s
`line_keys` is `tuple(line.key for line in self._lines)` in that same order, and the restored
`engine.set_source(recipe.choice)` uses exactly those `line_keys` — so both preparations process
lines in identical order, and there is no reordering hazard between them for the tolerance to be
guarding against. The correct account is simpler: `rtol=1e-6, atol=1e-7` is slack the brief's own
test carries as a matter of course for a floating-point comparison across two independently
computed arrays — belt-and-braces, not a guard against a real, named hazard. I verified the test
passes at the tolerance exactly as given, and did not touch it in either direction, which is the
part of the original claim that was actually correct.

## Fix round 1 (coordinator review)

Spec ✅. Two Importants, both in the widget layer this report's own "Notes on the manual
walkthrough gate" (below, now updated) had flagged as untested by anything in the original
submission. One tolerance-rationale correction (Ruling AM, folded into the section above rather
than duplicated here). Four Minors folded in; two deferred by the coordinator (the `view: {}`
asymmetry, the loose `match="z"`) and left untouched.

### Important 1 (Ruling AJ) — `z1_spin` needed 4 decimals, not 3

**Root cause, verified directly rather than assumed:** `QDoubleSpinBox.setValue()` rounds to the
box's own `decimals()`, not merely the display —

```
value after setValue(12.34565) with decimals=3: 12.346
value after setValue(12.3456789) with decimals=3: 12.346
value after setValue(12.3456789) with decimals=4: 12.3457
```

— so `z1_spin.setDecimals(3)` genuinely truncated precision on every `restore_cube` call, not just
on display. The record's `t1_ns` is `z.t_end_ns = t0_ns + (nz - 1) * dz_ns` (Task 6's own choice,
so the record round-trips `nz` exactly), and with `z0_ns` at 3 dp and `dz_ns` at 4 dp that sum is a
genuine 4-dp quantity roughly half the time over plausible GSSI headers (the coordinator's sweep:
43 of 90). `z0_spin` stays at 3 dp: every `t0_ns` this dock ever produces passed through
`z0_spin.setValue()` itself first (seeded from a header or typed by hand), so a record's `t0_ns`
is always already a 3-dp-exact number by construction — there is no fourth decimal for `z0_spin`
to lose, confirming the coordinator's own reasoning. `z1_spin` has no such origin story (its value
is *derived*, never sourced from that widget), which is exactly why it alone needed the extra
digit.

**Fix:** `self.z1_spin.setDecimals(4)` (`slices_dock.py`).

**Before/after, via `test_restore_cube_brings_every_control_back_ruling_al`** (new, in
`test_plugin_slices_dock.py`, built with `dz=0.2165, z0=2.0, z1(requested)=30.0`, giving
`t_end_ns = 29.9285`, a genuine 4th-decimal value):

- Before (`setDecimals(3)`, temporarily reverted to confirm): `assert 29.928 == 29.9285` — fails,
  reported as `AssertionError`.
- After (`setDecimals(4)`, the fix): passes.

### Important 2 (Ruling AK) — a missing grid/preset/transform now refuses loudly

**Fix:** `restore_cube` now checks `combo.findText(text) < 0` for `grid_combo`/`preset_combo`/
`transform_combo` together, *before* any widget is touched, and raises `ValueError` naming every
field that is missing at once (`cube {cube_id!r} refers to {joined}, no longer present in this
site`) rather than partially restoring. The existing `except` block already routes this to
`source_status`/`error`, and now also resets `cube_combo` to `"(unsaved)"` (this round's Minor,
below) so a refused selection can be retried without picking something else first.

**Before/after, via the three new `test_restore_cube_refuses_a_missing_*` tests** (`grid`,
`preset`, `transform`), each building a valid record then corrupting exactly one field to a name
that exists nowhere in the site, then driving the restore through `cube_combo.setCurrentText`
(the real signal path, not a direct method call) so the "resets to (unsaved)" assertion is
actually exercising the except handler rather than a value the combo already held:

- Before (`missing` computation disabled, temporarily, to reproduce the silent no-op): all three
  tests fail — `AssertionError: []` against `assert any("preset" in m and "does-not-exist" in m
  for m in seen)` (and the same shape for `grid`/`transform`) — confirming no error is ever
  emitted and the dock would have gone on to report `prepared · N lines` over the wrong source,
  exactly the "different picture under a saved cube's name" failure Ruling AK named.
- After (the fix restored): all three pass — a `ValueError` naming the missing field is raised
  before any widget is touched, reported through both `error` and `source_status`, and
  `cube_combo` falls back to `"(unsaved)"`.

### Ruling AL — the dock-UI test

Added `test_restore_cube_brings_every_control_back_ruling_al` to `test_plugin_slices_dock.py` on
the existing `docked` fixture, per the coordinator's own costed shape: builds a record with
`cube_record` from `dock.engine`'s own (already-prepared) state, `dock.refresh_cube_combo()`,
perturbs every restorable control (a second preset, a narrower inclusion set, different
Resolution/view values -- so the restore is not a no-op tautology), `dock.restore_cube(cube_id)`,
then asserts the three source combos, `dock.included_keys()`, `dock.z1_spin.value()` against the
record's own `t1_ns` (this is also the Important 1 regression test -- see above), and
`dock.view_settings()` against the saved `ViewSettings`. No second preparation beyond what the
fixture and the perturbation step already need; no new fixture. ~85 lines including the shared
`_save_cube` helper (used by all five new dock tests in this round), somewhat more than the
coordinator's ~20-line estimate because the perturbation step (needed to make the restore
assertions meaningful rather than trivially true) and the helper were not separately costed.

### Four Minors folded in

1. **`_pending_palette` could outlive its preparation.** `restore_cube` now clears it itself,
   right after its own `prepare()` call, when `not self.engine.is_running` (i.e. `prepare()`'s own
   no-op guard skipped dispatch, so `_on_prepared` will never run to consume it). Covered by new
   test `test_restoring_the_same_cube_after_a_no_op_prepare_does_not_leave_a_stale_palette`:
   restores a cube once (real preparation, `_on_prepared` consumes the stash), then restores the
   *same* cube again (a no-op `prepare()`, nothing dispatched) and asserts the field is `None`
   immediately rather than left stashed for some later, unrelated preparation to apply.
2. **A refused restore now resets `cube_combo` to `"(unsaved)"`** in the `except` block, under
   `_updating`. Covered by the same before/after evidence as Important 2 above (the three refusal
   tests all assert this).
3. **`plugin.save_cube` now selects the just-written cube id** in the combo. `refresh_cube_combo`
   gained an optional `select: str | None` parameter, applied inside the same `_updating` guard as
   the refill itself (not a plain `setCurrentText` afterwards, which -- outside the guard -- would
   read as the user picking that cube and dispatch a whole redundant `restore_cube`). Not covered
   by a new automated test (no test in this codebase drives `plugin.save_cube` and then reads
   `dock.cube_combo` — `test_plugin_slice_export_dialogs.py` is the file that exercises
   `save_cube` end to end, and adding this assertion there was judged out of proportion to a
   one-line UI-consistency fix); it is, however, exactly what manual walkthrough item 11 ("Pick
   the cube from the Cube combo") will show immediately after a save.
4. **`apply_view` now membership-checks `stretch_combo` too**, mirroring the existing `palette`
   check, for the same `setCurrentText`-on-a-non-editable-combo failure class Important 2 fixes
   for the Source combos. Not separately tested: `stretch_combo`'s two items are fixed today, so
   there is no reachable path to a `view.stretch` value that is not among them without calling
   `apply_view` directly with a fabricated `ViewSettings` — a defensive parity fix for a class of
   bug, not a live one, and the coordinator's framing ("same no-op class as Important 2, one combo
   over") reads as asking for the fix, not a dedicated regression test the way Important 1/2 were.

### Verification for this round

- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`: 41 passed (36 existing + 5 new),
  `-p no:xonsh`, `QT_QPA_PLATFORM=offscreen`.
- `ruff check .`, `ruff format --check .`, and the exact CI `mypy` invocation: all clean.
- Core + pure: `543 passed, 2 skipped` (unchanged from Task 7's own baseline; this round touched
  no core or pure code).
- Full QGIS tier and warning count: see the status contract for this round's numbers.

## Notes on the manual walkthrough gate

Still not run as part of this task (it is explicitly a human checkpoint per the brief's own "After
Task 7" section, not something a task report can discharge). Fix round 1 narrowed, but did not
close, the gap the first version of this note flagged: `test_plugin_slices_dock.py` now covers
`restore_cube`/`view_settings`/`apply_view`/`_pending_palette` and the three missing-field
refusals directly against the real widgets, so item 11 of the walkthrough ("every control comes
back where it was") is now backed by an automated equivalent rather than resting solely on a human
pass. What remains genuinely untested by anything in this codebase: the actual `Cube` combo
*click* end to end through `plugin.py` (a real `QComboBox` selection via the UI, not
`setCurrentText` called from a test), and whether the restored picture is what a person looking at
the map actually recognises as "the one I saved" -- which is what item 11 is for, and is not
something any unit test can stand in for.
