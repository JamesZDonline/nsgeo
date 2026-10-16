# Task 2 report: the slice engine — preparation, plan cache, residency, one slice per tick

## Fix round 2 (task review: Ruling O, P, Q)

All three items confirmed and fixed. Round 1's three departures were independently re-confirmed
sound by the re-reviewer (including that the "values must differ" assertion in my own
round-1-adjusted grid-move test was testing the wrong quantity — correctly identified: the defect
is georeferencing, never content, because `GridPlacement` moves the lines with the grid).

### Ruling O — `_finish_preparation()` escaped the `except` guard

This was a regression introduced by round 1's own `finally`-based fix for Important 4: moving the
`_finish_preparation()` call into `finished()`'s `finally` means it now runs OUTSIDE `finished()`'s
own `except`, so a raising `on_prepared` (Task 3's dock-rebuild slot) would propagate out of
`finished()` entirely and be swallowed with no log by `QgsTaskWrapper.finished` — the reviewer's
citation of the installed source (`.../qgstaskwrapper.py:49-55`, storing the exception on an
attribute with no re-raise or log) confirms this directly.

Fixed exactly as prescribed: `_finish_preparation()` now wraps `self.on_prepared()` in its own
`try/except`, reporting through `_report` on failure — the same shape `_emit_progress` already
uses. `_report` itself is now also non-raising (`with contextlib.suppress(Exception):
self.on_error(message)`), since `_report` is called both from `finished()`'s `except` and from
`_finish_preparation()`'s own new `except`, and a raising `on_error` in either spot would hit the
identical `QgsTaskWrapper` swallow. Updated the module docstring's second hazard bullet to state
this plainly, including a note that an earlier version of this module put the
`_finish_preparation()` call inside the `try` and that reopened the hole.

**One addition beyond the literal prescription, disclosed here:** `wait_for_preparation`'s
internal `done()` helper calls `previous()` (the caller's real `on_prepared`) and only then
`loop.quit()`. Since `_finish_preparation()`'s new guard wraps the ENTIRE call to `self.on_prepared`
(i.e. `done()`), a raising `previous()` is caught safely — but `done()`'s own `loop.quit()` line,
which sits AFTER the `previous()` call, was skipped when `previous()` raised, so
`wait_for_preparation` would only return once its own safety-net timer fired, not promptly. I
wrapped `done()`'s `previous()` call in `try/finally: loop.quit()` so the helper wakes immediately
regardless. This wasn't explicitly asked for, but without it the new test below would only
demonstrate "returns within the timeout" rather than "wakes promptly," which is what was asked;
I judged the one-line change low-risk and directly in service of the same contract.

Added `test_a_raising_on_prepared_still_reports_and_does_not_hang`: sets a raising `on_prepared`,
calls `set_source`, asserts `wait_for_preparation(5_000)` returns `True` **promptly** (observed:
~0.4s, not the full 5s bound — confirming the `done()` fix), `engine.is_prepared` is `True`, and
the error surfaces via `on_error` containing `"boom"`. The qgis-tier `_no_swallowed_slot_exceptions`
autouse fixture ran throughout and did not fail the test, confirming nothing escaped to
`sys.excepthook`/`sys.unraisablehook` either — the "belt to this test's braces" the reviewer named.

### Ruling P — `_grid_fp` was keyed to the wrong moment

**Reproduced the defect first, as asked, before fixing it.** Wrote a standalone script
(`packages/nsgeo-qgis`-rooted, same fixture shape as the test suite) that prepares a source with
NO resolution set, moves the grid 1 m east, THEN sets a resolution — the exact ordering Task 3
uses (`prepare()` then `_apply_resolution()` as separate steps). Observed, against the
round-1 code:

```
--- baseline: no grid move ---
frame.origin = (500.0, 700.0)
line 0 coords[:3] = [[501.0, 700.0], [501.0, 700.0166666666667], [501.0, 700.0333333333333]]
line 0 cell ids (first 5 traces): [4, 4, 4, 4, 4]
coverage.sum() = 240 / coverage.size = 576

--- grid moves 1 m east BEFORE any resolution exists ---
frame.origin = (501.0, 700.0)
line 0 coords[:3] = [[501.0, 700.0], [501.0, 700.0166666666667], [501.0, 700.0333333333333]]  <- UNCHANGED, stale
line 0 cell ids (first 5 traces): [0, 0, 0, 0, 0]   <- should be [4, 4, 4, 4, 4]
coverage.sum() = 240 / coverage.size = 576
errors: []
```

A uniform 4-cell shift (1 m / 0.25 m cell) — matching the shape of the reviewer's own measurement
(`[48 168 288 408 528]` vs `[52 172 292 412 532]`, also differing by exactly 4) — with **zero
errors reported** and **identical total coverage** in both cases, so nothing observable flags the
problem. `line 0 coords` staying at `501.0` (the pre-move value) after the grid moved to origin
`501.0` is the direct evidence that no re-preparation happened at all: `_grid_fp` was still `None`
(no resolution had ever run `_rebuild_geometry`), so `_on_grids_changed`'s `self._grid_fp is not
None` check skipped silently.

Also confirmed directly against the test suite: `test_a_grid_move_before_any_resolution_still_re_prepares`
**FAILED** against the round-1 code with `AssertionError: a grid move before any resolution did
not re-prepare / assert 1 == (1 + 1)` — the `prepared` counter never incremented, i.e. no
re-preparation was even attempted (consistent with the fingerprint being `None` at that point).

**Fix:** moved `_grid_fp`'s capture out of `_rebuild_geometry` and into `set_source`, right beside
the `frames = site.frames` / `trace_coords` call it actually protects (dispatch time, synchronous,
on the main thread — the same moment `_steps` is captured for Ruling K). `_rebuild_geometry` no
longer resets or re-derives `_grid_fp` at all — it is now owned entirely by `set_source`, and must
survive a `set_resolution`-only call (which also runs `_rebuild_geometry`). Re-ran the repro
script after the fix:

```
--- grid moves 1 m east BEFORE any resolution exists ---
frame.origin = (501.0, 700.0)
line 0 coords[:3] = [[502.0, 700.0], ...]   <- correctly re-computed against the NEW grid
line 0 cell ids (first 5 traces): [4, 4, 4, 4, 4]   <- correct, matches baseline's registration
coverage.sum() = 240 / coverage.size = 576
```

`test_a_grid_move_before_any_resolution_still_re_prepares` now passes.

### Ruling Q — a velocity edit left a resident cube's provenance stale

Fixed as prescribed: `_on_grids_changed` now falls through to `self._cube = None` when the
fingerprint is UNCHANGED (rather than doing nothing), on the reasoning that `grids_changed` fires
for `set_grid_velocity` too (it goes through `replace_grid`) and carries no information about
which grid or field actually changed, so this is deliberately conservative — it also drops the
cube on an unrelated grid's edit, which costs a cache-miss rebuild and nothing else. The prepared
lines and plans are left untouched, since neither depends on velocity.

Added `test_a_velocity_edit_drops_a_resident_cube_rather_than_serving_stale_provenance`: prepares,
forces a resident cube via `set_always_resident(True)` + `slice_at`, confirms `has_cube`, edits the
grid's velocity, and asserts `line_count` is unchanged (no wasted re-preparation) while `has_cube`
is now `False`.

### Full verification after fix round 2

- `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py -q -p no:xonsh`
  → **21 passed** (19 from before this round + 2 new: the raising-`on_prepared` test and the
  velocity-drops-cube test; the grid-move-before-resolution test from the "Then" instructions was
  already added and counted in the 19).
- `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`
  → **541 passed, 2 skipped** (unchanged — this round only touched `slices_engine.py` and its
  QGIS-tier test).
- `./.venv/bin/python -m ruff check .` → **All checks passed!**
- `./.venv/bin/python -m ruff format --check .` → **114 files already formatted**.
- `./.venv/bin/python -m mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
  → **Success: no issues found in 33 source files.**
- Re-confirmed Step 11's mutant 1 (delete `self._plans = None` from `_rebuild_geometry`) still
  **FAILS** `test_changing_the_cell_size_re_plans_every_line` with the identical
  `_check_plans_current` `ValueError` from `nsgeo-core/src/nsgeo/slices/binning.py:179` as in every
  prior round.
- `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh`
  (whole directory) → **501 passed** in ~146s (470 baseline + 10 pure, re-collected under this
  tree + 21 engine tests).

### Fix-round-2 commit

`fix(slices): guard on_prepared/on_error against escaping, key grid fingerprint to set_source,
drop stale cube on velocity edit` — `slices_engine.py`, `test_plugin_slices_engine.py`. Not
pushed.

## Fix round 1 (task review: Important 1–4)

All four Important findings were confirmed and fixed. Both disclosed departures from the
original submission (the `shared_limit` tail-window fix and the `contextlib.suppress` change)
were independently confirmed sound by the reviewer — no further action needed there.

### Important 1 — `provenance()` re-read the preset live (Ruling K)

Fixed as prescribed: added `self._steps: tuple[dict[str, Any], ...] = ()`, reset to `()` at the
top of `set_source` and in `clear()`, and captured `self._steps = tuple(dict(s) for s in steps)`
in `set_source` right after the preset-conflict check (dispatch time, on the main thread, exactly
where `steps` is already computed for the jobs). `provenance()` now reads `self._steps` instead
of `site.presets.get(self._choice.preset, [])`. Docstrings on the field, the capture site, and
`provenance()` itself all cross-reference the identical `line_keys` reasoning already there.

Added the prescribed test verbatim:
`test_provenance_records_the_steps_that_were_applied_not_the_preset_as_it_stands_now` — prepares,
records the applied steps, overwrites `presets["p"]` in place and emits `presets_changed`, asserts
`provenance().steps` is unchanged, then deletes `presets["p"]` and emits again, asserts it is
still unchanged. Passes.

### Important 2 — re-added the discarded mutation-check test (Ruling L)

Re-added `test_provenance_excludes_a_line_that_failed_to_prepare` **verbatim**, as it existed
during Step 11's mutant-3 verification (a fifth line whose backing file is deleted before
`set_source`, asserting the broken line's key is absent from `provenance().line_keys` and that
exactly 4 lines were prepared). It passes against the real code and was re-confirmed to fail
against the `line_keys=tuple(self._choice.line_keys)` mutant (see the re-verification below).

### Important 3 — nothing invalidated when the grid itself changed (Ruling M)

Implemented as prescribed: `_grid_fingerprint` (a static method reading `origin, azimuth, size_x,
size_y, crs` — deliberately excluding `velocity` and `default_spacing`), a `self._grid_fp`
snapshot set in `_rebuild_geometry` alongside `_frame`/`_z`, and `_on_grids_changed` connected to
`session.grids_changed` in `__init__` (and disconnected in `dispose()`, matching the
`site_closed` pattern already there). The slot: does nothing if no source is chosen; `clear()`s
and reports by name if the chosen grid no longer exists (`KeyError` from `session.grid`); calls
`set_source(self._choice)` (a full re-preparation, not merely a geometry rebuild, since the
prepared lines' own `coords` were computed from the old grid too) if the fingerprint changed;
otherwise does nothing. The `set_source` re-entry is guarded so it cannot raise past the slot.

Three tests added, with one adjustment to the prescribed suite:

- `test_moving_the_grid_re_prepares_rather_than_slicing_at_the_old_registration` — **the
  prescribed body's final assertion was wrong and I changed it.** The prescribed test asserted
  `not np.array_equal(before, after)` after moving the grid 100 m east. I traced this through
  `GridPlacement.trace_coords` (`packages/nsgeo-core/src/nsgeo/geometry/placement.py:64-71`):
  it computes `frames[self.grid_id].to_world(local)`, i.e. every line's world coordinates are
  derived FROM the grid's own origin/azimuth, and `CubeFrame.for_grid` shares that same
  origin/azimuth. A rigid translation (or rotation, at fixed size/cell) of the grid therefore
  moves the lines' world coordinates and the frame's origin by the identical transform, so
  `frame.cell_index(world)` recovers the exact same local cell ids as before — the cube's
  cell-relative content is mathematically invariant under a pure grid move; only the frame's
  absolute registration (and, downstream, the map layer) moves. Asserting the slice values differ
  is therefore not a valid expectation for this scenario, and the original assertion happened to
  pass only because the *unfixed* engine kept the stale frame outright (identical objects, not
  merely identical values) — that isn't a discriminator either. I rewrote the test to assert
  what actually distinguishes fixed from broken: `engine.frame.origin` updates to the new value,
  a re-preparation actually ran (checked via the fixture's `prepared` counter incrementing by
  exactly one), the engine stays prepared, a post-move `slice_at` does not raise, and no errors
  are reported. Passes.
- `test_a_velocity_only_grid_edit_does_not_re_prepare` — added as prescribed, using
  `VelocityModel.constant(0.09)` via `session.set_grid_velocity`. Confirms the fingerprint's
  deliberate exclusion of velocity. Passes.
- `test_removing_the_chosen_grid_is_reported_rather_than_left_stale` — **adjusted, as the
  reviewer anticipated.** `SiteSession.remove_grid` (`session.py:452-459`) raises `ValueError` if
  any line still references the grid — it does **not** remove the grid's lines for you. The
  fixture's four lines all reference grid `"A"`, so calling `session.remove_grid("A")` directly
  (as in the reviewer's draft) raises before the scenario under test even begins. I adjusted the
  test to remove all four lines via `session.remove_line(key)` first (the only reachable path to
  an empty, removable grid), then call `session.remove_grid("A")`. Also fixed the `errors`
  unpacking to match the fixture's actual shape (`list[tuple[str, str]]`, not `list[str]`) — the
  reviewer's draft `for msg in errors` would have iterated 2-tuples and checked exact membership
  of `"A"` inside each tuple rather than substring-matching the message text. Passes with the
  corrected unpacking.

### Important 4 — every terminal path must notify (Ruling N)

Restructured `finished()` inside `_start_task` around a `notify` flag set `True` only once past
the two staleness checks (stale generation / site replaced — which stay silent on purpose, since
a newer request or a different site already owns notification), with a `finally: if notify:
self._finish_preparation()` that now covers all three previously-broken exits: the whole-task
`exception is not None` branch, the outer `except Exception` (e.g. a bug in `_rebuild_geometry`),
and the already-working success path. Also added `self._finish_preparation()` to the
`addTask()`-returned-0 branch in `_start_task`, mirroring `loader.py`'s identical branch
re-emitting `loading_changed(key, False)`.

Two tests added:

- `test_an_exception_while_finishing_preparation_still_wakes_wait_for_preparation` — monkeypatches
  the instance's `_rebuild_geometry` to raise `RuntimeError("boom")`, so the real background task
  completes normally but the outer `except` in `finished()` fires. Asserts
  `wait_for_preparation(5_000)` returns `True` (previously: it would have blocked for the full
  timeout and then returned `False`, since `_finish_preparation()` was never called on this
  path). Passes.
- `test_a_task_that_cannot_be_scheduled_still_notifies` — monkeypatches
  `nsgeo_qgis.slices_engine.QgsApplication` with a fake whose `taskManager().addTask()` returns
  `0`. Asserts `prepared == [1]` (the fixture's `on_prepared` counter) immediately after
  `set_source` returns, since this branch is synchronous (`_running` is already `False` by the
  time any caller could call `wait_for_preparation`, so that helper's own short-circuit masks
  the specific defect for this branch — checking `on_prepared` fired directly is the actual
  discriminator). Passes.

I did **not** add a test forcing the literal `exception is not None` branch (a genuine
`QgsTask.fromFunction`-level failure, as opposed to one caught per-line inside `work()`). Every
line inside `work()`'s per-line loop is already wrapped in its own `try/except Exception`, so
triggering a whole-task exception deterministically would require monkeypatching something
outside that loop (e.g. `QgsTask.setProgress` at the class level, affecting every task in the
process) or forcing a `BaseException` subtype through a step's `.apply()` — both fragile enough
that I judged them not worth the risk of flaking or corrupting shared state. That branch is
covered by the *same* `notify`-flag/`finally` restructuring as the branch I did test (the code
path is identical past the `notify = True` line), so I'm confident it's fixed, but I want to be
explicit that this specific branch's fix is verified by code inspection and the shared code path,
not by a dedicated test — flagging honestly per the brief's own instruction to report "not
verified" rather than claim a check that wasn't made.

### Re-verification of Step 11's mutants against the fixed code

All three mutants applied one at a time against the fixed file, tested, reverted, diff-confirmed
clean:

1. **Delete `self._plans = None`** — `test_changing_the_cell_size_re_plans_every_line` still
   **FAILS**, with the identical message as before:
   ```
   ValueError: line 'raw/FILE__001.DZT': plan is stale (frame CubeFrame(origin=(500.0, 700.0),
   azimuth=0.0, cell=0.25, nx=24, ny=24, crs='EPSG:32616') != current CubeFrame(origin=(500.0,
   700.0), azimuth=0.0, cell=0.5, nx=12, ny=12, crs='EPSG:32616')) -- call plan_line() again
   against the current frame and z axis before binning
   ```
2. **`stack.insert(0, ...)` instead of `append`** — `test_preparation_applies_the_preset_and_appends_the_transform`
   still **FAILS**, at `set_source`, with the identical polarity-assert message as before.
3. **`provenance()` uses `self._choice.line_keys`** — the original
   `test_provenance_names_the_lines_that_were_actually_prepared` still **PASSES** against this
   mutant; the re-added `test_provenance_excludes_a_line_that_failed_to_prepare` still **FAILS**
   against it, with the identical assertion failure as before (`'raw/FILE__005.DZT'` present in
   `prov.line_keys` when it should be absent).

### Full verification after the fix round

- `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`
  → **541 passed, 2 skipped** (unchanged from before the fix round — these fixes only touched
  `slices_engine.py` and its QGIS-tier test).
- `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh`
  → **498 passed** in ~147s (470 baseline + 10 pure, re-collected + 18 engine tests: the original
  11 plus 7 new — 2 for Important 1/2, 3 for Important 3, 2 for Important 4).
- `./.venv/bin/python -m ruff check .` → **All checks passed!**
- `./.venv/bin/python -m ruff format --check .` → **114 files already formatted**.
- `./.venv/bin/python -m mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
  → **Success: no issues found in 33 source files.**

### Fix-round commit

`fix(slices): provenance steps snapshot, grid re-prep, notify every terminal path` —
`slices_engine.py`, `test_plugin_slices_engine.py`. Not pushed.

## Summary

Both files were built from the brief's exact code, with two defects found and fixed during
implementation (documented below, and in the second commit's message). All steps completed;
both mutation-check batteries (Step 5 and Step 11) are recorded with observed numbers.

## Baseline (before this task)

- `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`
  → **531 passed, 2 skipped** — matches the brief exactly.
- `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh`
  → **470 passed** in 144.73s — matches the brief exactly.

## Deviations from the brief (and why)

1. **Import order in `test_pure_slices_plan.py` (Step 1's verbatim block).** The brief's import
   block placed `STREAM_MS_PER_LINE` after `SourceChoice`, which is not isort/ruff order
   (`STREAM_MS_PER_LINE` sorts before the mixed-case names). `ruff check .` on the whole repo
   flagged exactly one error, confirming the rest of the repo was already clean. Fixed with
   `ruff check --fix` on just that file; the whole-repo checks are green after.

2. **`slices_engine.py`'s streaming `shared_limit()` disagreed with the resident/cube path by
   ~0.08%**, failing `test_the_shared_limit_agrees_between_the_two_modes` (`1.3846736323833466`
   streaming vs `1.3835003972053528` resident, outside the test's `rel=1e-4` tolerance). Root
   cause: `nsgeo.slices.display.shared_limit` (used by the resident branch through
   `cube_shared_limit`) appends a thinner tail window when `thickness_levels` doesn't evenly
   divide `z.nz` — the module's own docstring calls this out as "not weighted per level" but
   present. The brief's streaming branch called `plan_windows(z, thickness_levels,
   thickness_levels)` directly and never added that tail window, so it silently measured the
   stretch over fewer levels (50 of 57 in the test's z axis: `nz=57`, `thickness=10`, tops at
   0,10,20,30,40 — levels 50-56 excluded). Fixed by mirroring the core function's own tail-window
   logic in the streaming branch (see `shared_limit()` in the committed file). After the fix all
   11 engine tests pass, including this one.

3. **`dispose()`'s `try/except (TypeError, RuntimeError): pass`** around the signal disconnect
   tripped `ruff`'s SIM105 (`Use contextlib.suppress instead of try-except-pass`), and the
   codebase already has an established idiom for this exact "already disconnected, or the C++
   side is gone" case in `map_link.py` (`with contextlib.suppress(TypeError, RuntimeError):`).
   Switched to match, added the `contextlib` import, and added a comment cross-referencing
   `map_link.py`'s reasoning. `ruff check .` is clean across the whole repo after.

4. One line in the brief's Step 7 test file (`test_a_line_that_cannot_be_prepared_is_reported_by_name`'s
   `SourceChoice(...)` call) was reformatted by `ruff format` to fit one line — cosmetic only,
   no behavior change.

5. **Test-count arithmetic**: the brief's Step 10/12 expects "470 + 11 = 481" for the QGIS tier.
   The actual full-tier run reports **491**, because `packages/nsgeo-qgis/tests` (the directory
   passed to pytest) also collects and re-runs the 10 new *pure* tests added in Step 1 under the
   `.venv-qgis` interpreter (they need no QGIS fixture, so they collect and pass there too) —
   470 + 10 (new pure, re-collected) + 11 (new engine) = 491. This is not a regression; it is the
   brief undercounting by the 10 pure tests that live inside the same tree pytest was pointed at.
   Confirmed no other change in count.

## Step 5: pure mutation checks (`slices_plan.py`)

All three mutants applied one at a time, tested against the single named test, then reverted
(diff-confirmed clean each time).

1. **`transform_names` → hardcoded `["amp_abs", "amp_square", "amp_envelope"]`.**
   `test_transform_names_come_from_the_registry_not_a_hardcoded_list` **FAILED**, with:
   ```
   AssertionError: assert ['amp_abs', ..., 'amp_envelope'] == ['amp_abs', ..., 'amp_square']
   At index 1 diff: 'amp_square' != 'amp_envelope'
   ```
   This confirms the reasoning in the test's own docstring: `available_steps()` returns steps in
   **sorted registry order** (`amp_abs`, `amp_envelope`, `amp_square`), which differs from the
   mutant's hand-written order (`amp_abs`, `amp_square`, `amp_envelope`). The equality check
   catches the order mismatch immediately; a membership assertion (`set(names) == {...}` or
   `all(n in names for n in ...)`) would have passed against this exact mutant, since the same
   three names are present either way — it is specifically the ordering, not the membership,
   that the mutant gets wrong, and only `==` against a freshly recomputed list is sensitive to
   that.

2. **`preset_transform_conflict` → only inspect `steps[-1]`.**
   `test_a_preset_carrying_an_amplitude_transform_is_a_conflict` **FAILED**, with:
   ```
   AssertionError: assert None == 'amp_abs'
   where None = preset_transform_conflict([{'step': 'time_zero'}, {'step': 'amp_abs'}, {'step': 'gain_agc'}])
   ```
   Confirms the gain-after-transform case (transform not last) is exactly what a last-element-only
   check misses.

3. **`choose_residency` → drop the `n_lines * STREAM_MS_PER_LINE <= FRAME_BUDGET_MS` branch.**
   `test_streaming_stays_the_default_while_nobody_could_perceive_the_difference` **FAILED**, with:
   ```
   AssertionError: assert 'resident' == 'streaming'
   ```
   (24 lines, comfortably within `DEFAULT_BUDGET_BYTES`, gets promoted to resident once the
   imperceptibility short-circuit is gone — exactly the bug the test guards against.)

Pure tests re-run clean after each revert; full pure tier ends at 60/60 passed (50 pre-existing +
10 new).

## Step 11: engine mutation checks (`slices_engine.py`)

All three mutants applied one at a time against a saved-clean baseline, tested, then reverted
(diff-confirmed clean each time; final live file re-verified against the saved original).

1. **Delete `self._plans = None` from `_rebuild_geometry`.**
   `test_changing_the_cell_size_re_plans_every_line` **FAILED**, with the exact message:
   ```
   ValueError: line 'raw/FILE__001.DZT': plan is stale (frame CubeFrame(origin=(500.0, 700.0),
   azimuth=0.0, cell=0.25, nx=24, ny=24, crs='EPSG:32616') != current CubeFrame(origin=(500.0,
   700.0), azimuth=0.0, cell=0.5, nx=12, ny=12, crs='EPSG:32616')) -- call plan_line() again
   against the current frame and z axis before binning
   ```
   raised from `packages/nsgeo-core/src/nsgeo/slices/binning.py:179`
   (`_check_plans_current`), **not** from anything in `slices_engine.py`. This is the evidence
   the brief asked for: with the engine's own invalidation removed, the failure still surfaces —
   loudly, by name — because M10's core guard (`_check_plans_current`, called from both
   `build_cube` and `stream_slice`) is a second, independent line of defence, not a rephrasing of
   the engine's own bookkeeping. Before that core guard existed, per the brief and per M10's
   final review, the same missing invalidation would have silently binned every trace into the
   wrong cell with plausible-looking coverage; today, both defences would have to fail
   independently for that to happen again.

2. **`_build_stack` → `stack.insert(0, build_step(transform))` instead of `stack.append(...)`.**
   `test_preparation_applies_the_preset_and_appends_the_transform` **FAILED**, at
   `engine.set_source(...)` inside the shared `_prepare()` helper (not later, at `slice_at`), with:
   ```
   ValueError: the built stack's polarity disagrees with the chosen transform; the transform
   must be the last enabled step
   ```
   raised from `_build_stack`'s own polarity assert. Confirms hazard #5 from the task
   instructions: `_start_task` validates the stack (via `_build_stack`) synchronously on the main
   thread before scheduling the worker, so a bad transform ordering is refused immediately rather
   than surfacing later from a background thread.

3. **`provenance()` → `line_keys=tuple(self._choice.line_keys)` instead of the prepared lines.**
   First checked as specified: `test_provenance_names_the_lines_that_were_actually_prepared`
   **still PASSED** against this mutant (1 passed) — expected, since in that test all four
   requested lines do prepare successfully, so `self._choice.line_keys` and the prepared lines'
   keys are the same four values in the same order; the mutant is invisible to that test.

   Extended the test (temporarily, for verification only — not part of the committed test file,
   per the brief's framing of this as a discriminating check rather than a required permanent
   addition) with a fifth line whose backing file is deleted after `Line.open()` (header already
   read, so `line.load()` fails on the worker, same pattern as the brief's own
   `test_a_line_that_cannot_be_prepared_is_reported_by_name`). Against the **real** code the
   extended test passed (`engine.line_count == 4`, broken key correctly absent from
   `provenance().line_keys`). Against the **mutant**, the extended test **FAILED**:
   ```
   AssertionError: assert 'raw/FILE__005.DZT' not in ('raw/FILE__001.DZT', 'raw/FILE__002.DZT',
   'raw/FILE__003.DZT', 'raw/FILE__004.DZT', 'raw/FILE__005.DZT')
   ```
   i.e. the mutant's provenance falsely claims the broken fifth line was part of the cube. Mutant
   3 is **verified** (not "unverified" — the extension was straightforward: reuse the existing
   `sourced` fixture's four-line setup, add one more line via `session.add_lines`, and delete its
   file before `set_source`, exactly mirroring an existing test in the same file). The extension
   was not kept in the committed test file, since Step 11's instructions describe it as a
   verification device rather than a permanent addition, and Step 12 lists only the original file
   contents as what ships.

Both mutated files (`slices_engine.py`, and the temporarily-extended `test_plugin_slices_engine.py`)
were restored from disk-diffed backups and re-verified byte-identical to the pre-mutation state
before committing.

## Full verification (Step 12)

- `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`
  → **541 passed, 2 skipped** (531 baseline + 10 new pure tests).
- `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh`
  → **491 passed** in ~145s (470 baseline + 10 new pure, re-collected under this tree + 11 new
  engine tests — see "Deviations" item 5 above for why this is 491 rather than the brief's 481).
- `./.venv/bin/python -m ruff check .` → **All checks passed!** (after the two fixes above).
- `./.venv/bin/python -m ruff format --check .` → **114 files already formatted** (clean).
- `./.venv/bin/python -m mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
  → **Success: no issues found in 33 source files.**

`.github/workflows/ci.yml`'s mypy step was extended to include `slices_plan.py`, matching the
command run locally above.

## Commits

1. `feat(slices): the Qt-free arithmetic behind the Slices dock` —
   `slices_plan.py`, `test_pure_slices_plan.py`, `.github/workflows/ci.yml`.
2. `feat(slices): SliceEngine — preparation, plan cache, residency` —
   `slices_engine.py`, `test_plugin_slices_engine.py`.

Neither commit was pushed (per instructions, pushing is the controller's job).

## Files

- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m11/packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m11/packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m11/packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m11/packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m11/.github/workflows/ci.yml`
