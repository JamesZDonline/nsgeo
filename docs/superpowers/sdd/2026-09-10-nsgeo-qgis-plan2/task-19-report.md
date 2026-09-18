# Task 19 report: difference view, presets, and the M6 checkpoint

## Summary

Implemented the difference view (a toggle button on `ProcessingDock` that
shows what the selected step removed instead of its result), named presets
(saved stacks stored in the survey JSON and applied through `SiteSession`),
and the README status update. All work followed the brief's file list. The
manual M6 checkpoint was **not** performed — see the explicit confirmation
near the end of this report.

## What was implemented

### Core (`packages/nsgeo-core`)

- `nsgeo/model/survey.py`: `Site.presets: dict[str, list[dict[str, Any]]]`,
  default `{}`, added after `stacks`.
- `nsgeo/project.py`:
  - `save_site`: `if site.presets: doc["presets"] = site.presets` (omitted
    entirely when empty, so an untouched site's JSON is unchanged).
  - `load_site`: after `site.stacks = stacks`, validates every preset via
    `StepStack.from_dicts` and raises `ProjectError(f"invalid preset
    {name!r}: {exc}")` on `KeyError`/`TypeError`/`ValueError`, then sets
    `site.presets = dict(presets)`.
- `packages/nsgeo-core/tests/test_presets.py` (new): the two brief tests,
  verbatim.

### Plugin (`packages/nsgeo-qgis`)

- `nsgeo_qgis/session.py`: `presets_changed = pyqtSignal()` and
  `preset_names()`, `save_preset(name, key)`, `apply_preset(name, key)`,
  `delete_preset(name)` — all as given in the brief.
- `nsgeo_qgis/ui/processing_dock.py`:
  - `difference_toggled = pyqtSignal(int)`, a checkable `diff_button` in
    the top row wired to a new `_emit_difference(checked)` that emits the
    current row (or `-1` when unchecked).
  - `_on_current_row` now also re-emits the difference index when the
    selection moves while the difference view is on.
  - `presets_button`/`presets_menu` in the bottom row, `_rebuild_presets_menu`
    (rebuilt on `presets_changed` and `site_opened`), `_save_preset_prompt`
    (drives `QInputDialog.getText`), `save_preset_named`, `apply_preset_named`.
  - Per-name menu-action lambdas use the same `checked=False, n=name`
    defensive shape `add_menu`'s existing lambdas use (see "Findings"
    below — confirmed not currently live, but kept for consistency and
    portability).
  - `presets_button` added to the existing `has_line` enable/disable loop
    (alongside `add_button`/`apply_button`) — a small addition beyond the
    brief's literal text; see "Deviations from the brief" below.
- `nsgeo_qgis/ui/profile_dock.py`: `difference_cleared = pyqtSignal()`,
  emitted in `current_radargram`'s `except ValueError` branch exactly when
  `_difference_index` is reverted.
- `nsgeo_qgis/plugin.py` `initGui`: wired `processing_dock.difference_toggled
  -> profile_dock.set_difference_index` and `profile_dock.difference_cleared
  -> lambda: processing_dock.diff_button.setChecked(False)`.
- `README.md`: status blockquote replaced as specified.
- `packages/nsgeo-qgis/tests/qgis/conftest.py`: added `QInputDialog.getText`
  to the `_no_unhandled_modals` forbidden list (and its docstring), since
  `_save_preset_prompt` is a new real modal in this tier — see "Deviations".
- `packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py` (new):
  the three brief tests, verbatim except for one fixture fix (see Finding 1
  below), plus one additional guard test for the preset-load-vs-form/
  gain-strip hazard the brief asked me to verify.

## Deviations from the brief (and why)

1. **`plugin` fixture teardown fixed** (Finding 1, detailed below): added
   `answer_modal` to the fixture and drove `QMessageBox.question` with
   `Discard` before `plugin.unload()`. The brief's fixture as given had no
   `answer_modal`, and the session is dirty at every test's teardown.
2. **`presets_button` added to the `has_line` enable/disable loop** in
   `rebuild()` (`processing_dock.py`). Not in the brief's text. Rationale:
   `apply_button` already gets this treatment for the same reason (it needs
   a current line); without it, clicking "Save current stack as…" with no
   line open pops a real `QInputDialog` and then silently no-ops, which is
   the same "user does something, nothing happens, no message" shape as the
   previously-found "silently bypassed confirmation" defect class. This is
   a one-line change reusing the existing loop; no test needed changing
   because every given test opens a line before touching presets.
3. **`QInputDialog.getText` added to `conftest.py`'s modal guard.** Required
   because `_save_preset_prompt` is a new real modal in this tier; per the
   brief's own global instruction ("extend it for any new modal").

## Finding: the brief's `plugin` fixture (Step 4) leaves every test erroring at teardown

The brief's given fixture for `test_plugin_difference_presets.py` ends:

```python
    yield plugin, s, key
    plugin.unload()
```

`s.add_grid(GRID)` and `s.add_lines(lines)` both dirty the session, and
only `test_presets_save_apply_and_persist` ever calls `session.save()`.
`plugin.unload()` on a dirty session calls `save_with_prompt(ask_first=True,
allow_cancel=False)`, which calls `QMessageBox.question(...)` — a real modal
that `tests/qgis/conftest.py`'s `_no_unhandled_modals` autouse fixture
forbids by default (it raises `AssertionError` unless the test explicitly
overrides it with `answer_modal`). The brief's fixture requests no such
override.

**Verified directly.** I built the file with the brief's fixture verbatim
(no `answer_modal`) and ran it:

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py -q -p no:xonsh
```

Result: `4 passed, 4 errors` — every test body passed, but every one of the
four tests errored at fixture teardown with:

```
E       AssertionError: unexpected modal: QMessageBox.question(<PyQt5.QtWidgets.QMainWindow ...>,
        'Unsaved changes', 'Save the site before continuing?', <...StandardButtons...>)
packages/nsgeo-qgis/tests/qgis/conftest.py:123: AssertionError
```

**Fix:** the fixture now takes `answer_modal` and drives
`QMessageBox.question` with `Discard` right before `plugin.unload()`,
matching the pattern already established in `test_plugin_gain_strip.py`
and `test_plugin_survey_dock.py` for the identical hazard. Re-running the
same command after the fix: `4 passed` (see GREEN evidence below).

This is reported as the requested "possible fifth defect" — a real,
reproducible defect in the brief's given code (as opposed to my own
implementation), verified by actually running it rather than by inspection
alone.

## Investigated and ruled out: `QMenu.addAction(text, slot)` argument count

The brief's `_rebuild_presets_menu` connects per-name actions with
`lambda n=name: self.apply_preset_named(n)` (no `checked=False`), unlike
`add_menu`'s existing lambdas (`lambda checked=False, n=name: ...`), whose
comment explains they're defensive against `addAction`'s convenience
overload passing a positional bool through to the lambda — which, for a
lambda with only `n=name`, would silently override `n` with that bool
instead of raising, exactly the "checked=False trap" called out in this
task's hazard list. I did not want to assume either way, so I probed it
directly against this repo's installed Qt binding:

```python
menu.addAction("hello", lambda n="captured": slot(n))
action.trigger()
# calls: ['captured']   -- NOT overridden by a positional bool
```

Result: the convenience overload calls the slot with zero arguments in
this binding, so the brief's lambdas as given are not actually exploitable
here. Not a live defect. I still added `checked=False,` to my own new
lambdas (`apply_preset_named`/`delete_preset` menu actions) to match the
established defensive house style at zero cost, but did not report this as
a finding since it doesn't reproduce.

## TDD evidence

### Core presets (RED then GREEN)

RED — reverted `Site.presets` (copied `survey.py` aside, removed the field,
ran, then restored from the copy):

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_presets.py -q
...
E       AttributeError: 'Site' object has no attribute 'presets'
2 failed in 0.13s
```

Matches the brief's expected RED exactly.

GREEN (after restoring `survey.py` and with `project.py` in place):

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_presets.py -q
..
2 passed in 0.12s
```

Full core suite after: `290 passed, 2 skipped` (was 288/2 baseline — the
2 new tests).

### Plugin difference/presets tests

GREEN (final, all four tests including the guard test I added):

```
$ PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py -q -p no:xonsh
....
4 passed in 3.41s
```

RED evidence for these tests is the six reversion runs below (each ran
against the real implementation, not against a stub).

## Reversion evidence (every new test, actually run against a one-line mutation)

For each: file copied aside first, mutated in place, test run, then
restored from the copy (never `git checkout --`).

1. **`test_presets_round_trip_and_are_omitted_when_empty`** — reverted
   `save_site` to never write `doc["presets"]`. Result:
   `AssertionError: assert {} == {'campus': [...]}"` (back.presets empty).
   Confirms the test actually checks the write path, not just the read path.

2. **`test_invalid_preset_is_a_project_error`** — reverted `load_site` to
   `site.presets = dict(presets)` with no validation loop. Result:
   `Failed: DID NOT RAISE ProjectError`. Confirms the test catches a
   missing-validation regression specifically (isolated from finding 1's
   mutation — round-trip test still passed unaffected).

3. **`test_difference_view_shows_what_a_step_removed`** — reverted
   `_emit_difference` to `self.difference_toggled.emit(self.list.currentRow())`
   (dropped the `if checked else -1`). Result:
   `AssertionError: assert 'Difference: background_mean' == ''` (unchecking
   the button no longer clears the difference view).

4. **`test_difference_view_declines_sample_count_changing_steps`** —
   reverted `profile_dock.py`'s new `self.difference_cleared.emit()` line
   (removed it). Result: `AssertionError: assert not True` (`isChecked()`
   stayed `True` — the button never unchecks itself on the declined step).

5. **`test_presets_save_apply_and_persist`** — reverted `apply_preset` to
   drop `site.stacks[key] = fresh` (kept building `fresh` but never
   installed it). Result: `AssertionError: assert [] == ['dewow', 'gain_agc']`
   (the other line's stack never actually changed).

6. **`test_applying_a_preset_updates_the_form_and_gain_strip_for_the_selected_row`**
   (the guard test) — reverted `_show_form`'s echo guard from
   `if shown == self._shown and step is self._shown_step:` back to
   `if shown == self._shown:` (the pre-Task-17 shape). Result:
   `AssertionError: assert 'gain_curve' == 'gain_agc'` — the form stayed on
   the stale `gain_curve` fields after the preset swapped row 0 to
   `gain_agc`, reproducing exactly the Task 17 failure mode the brief
   described. This confirms the identity check is load-bearing for a
   preset load, not just for the single-step-edit case it was written for.

Every reversion above was restored from a copy-aside file (not
`git checkout --`), and the full new-test file was re-run green after each
restore.

## The preset-vs-guards test (as requested)

`test_applying_a_preset_updates_the_form_and_gain_strip_for_the_selected_row`
in `packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py`:

- Selects row 0 on one line, showing a `gain_curve` step's form and its
  gain strip (both visible/populated).
- Applies a preset (saved from a different line) that puts a plain
  `gain_agc` step at that same row 0 on this line.
- Asserts the form now shows `gain_agc` (not stale `gain_curve` fields) and
  the gain strip is hidden (row 0 has no curve parameter any more).

**Result: both guards hold.** `ProcessingDock._show_form`'s identity check
(`step is self._shown_step`) correctly distinguishes "same row, brand-new
step object from a preset load" from an echo, and
`NsgeoPlugin._sync_gain_strip`'s unconditional resync on every real
`step_selected` correctly re-derives the strip's visibility from whatever
is now actually in the stack. Reversion #6 above confirms the form-guard
check specifically catches a regression of the Task 17 kind; I did not
find a way to break the gain-strip half through a targeted one-line
mutation because it has no analogous guard to break — it recomputes from
scratch unconditionally by design (Task 18), which is exactly what makes it
safe here.

## Full verification (final, in order)

```
$ PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
282 passed in 66.06s
```
(baseline 278; +4 new tests, no regressions)

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
336 passed, 2 skipped
```
(baseline 334/2; +2 new core tests, no regressions)

```
$ .venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
All checks passed!
92 files already formatted
```
(baseline 90 files; +2 new files)

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
6 passed
```

```
$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

**Report exactly as printed, never summed across tiers, as instructed:**
qgis tier 282 passed; pure+core tier 336 passed / 2 skipped; boundary 6
passed; ruff clean, 92 files formatted; mypy clean on the scoped set.

## `ALLOWED_FROM_PROCESSING` — not touched

No new name from `nsgeo.processing` was needed. `StepStack` (used for
`from_dicts`/`to_dicts`) was already in `session.py`'s existing imports and
already on the allowlist. The boundary guard was not widened.

## Files changed

- `packages/nsgeo-core/src/nsgeo/model/survey.py`
- `packages/nsgeo-core/src/nsgeo/project.py`
- `packages/nsgeo-core/tests/test_presets.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/session.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- `packages/nsgeo-qgis/tests/qgis/conftest.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py` (new)
- `README.md`

## Manual M6 checkpoint

**Not performed, not simulated, not marked done.** The brief's "M6
checkpoint (manual, 15 minutes)" section (starting around its line 303,
"Reload the plugin, open the M4 site, click FILE__001...") is explicitly a
human's job per my instructions. I implemented everything else in the
brief, including the README change, and I am leaving the checkpoint itself
entirely for the human reviewer to run. I did not read anything into the
plan file the brief was extracted from.

## Self-review

**Completeness:** every brief step implemented except the manual
checkpoint. Edge cases considered:
- A preset name that already exists: `save_preset` overwrites
  unconditionally (dict assignment), matching the brief's given code; no
  confirmation was specified and none seemed warranted (it's a named save,
  analogous to overwriting a file — the menu still shows the old contents
  until the new save completes, and nothing is lost silently).
- An empty stack saved as a preset: `to_dicts()` on an empty `StepStack`
  is `[]`; round-trips fine, applies as an empty stack.
- A difference on a sample-count-changing step: covered by
  `test_difference_view_declines_sample_count_changing_steps`.
- A preset saved from one line applied to a line with a different sample
  count: not specifically guarded, and not asked for — a step whose fixed
  parameters no longer fit the new axis (e.g., a `time_zero` sample index
  past the new line's length) would surface through the existing
  broad-except-and-log path already in `profile_dock.py`'s render slots,
  the same as any other bad-step-after-a-stack-change case already handled
  before this task.

**Quality:** matched existing house patterns throughout (banner comments,
defensive lambda signatures, `has_line`-style enable/disable, `_log`
guarded slots left untouched since I didn't need to touch them).

**Discipline:** stayed inside the brief's file list. The one addition
beyond the literal brief text (`presets_button` joining the `has_line`
loop) is called out explicitly above rather than folded in silently.

**Testing:** every new test's single-line-reversion was actually run (not
just reasoned about), with output pasted above. The qgis-tier run of the
new test file showed no warnings (`-rw` passed clean).

## Concerns

None blocking. Two things worth the reviewer's attention, both already
flagged above rather than buried: the fixture-teardown defect in the
brief's Step 4 code (Finding 1), and the one small addition beyond the
brief's literal text (`presets_button` disabling).

---

# Fix round 1

Review came back: spec-compliant item for item, 0 Critical, 1 Important
(three sites), 6 Minor (one already fixed pre-emptively in the original
pass -- `presets_button` in the `has_line` loop -- so 5 in scope here).
All six addressed below.

## Important 1 -- `_difference_index` drifts out of sync with `diff_button`

**(a) Line switch never told `diff_button` the difference view had ended**
(`profile_dock.py`, `_open`). Fixed: `_open` now captures whether a
difference view was active *before* resetting `_difference_index`, and
emits `difference_cleared` when it was -- before `self._key` is
reassigned, so the button's own uncheck (routed back through
`difference_toggled` -> `set_difference_index`) still resolves against
the line that was actually showing the difference, not the one about to
replace it.

**(b) `current_radargram` only caught `ValueError`**, so `StepStack.
difference`'s `IndexError` (out-of-range index -- exactly what removing
the differenced step, or applying a shorter preset, produces) escaped
into the render slots' broad `except Exception`: logged Critical, image
frozen stale, button still checked, label still naming a gone step.
Fixed: widened to `except (ValueError, IndexError) as exc:` -- the
existing reset-and-emit branch then runs for both.

**(c) `diff_button` was never in the `has_line` enable/disable loop**
(`processing_dock.py`, `rebuild`), unlike `add_button`/`apply_button`/
`presets_button`. Fixed: added to the same tuple.

## Minors

- **m2**: `test_presets_save_apply_and_persist` rewrote its apply/delete
  steps to `.trigger()` the real `QAction`s from `pd.presets_menu`
  (via a small `_menu_action(menu, text)` helper) instead of calling
  `apply_preset_named`/`session.delete_preset` directly.
- **m3**: new `test_save_preset_prompt_rejects_blank_names_and_cancel`
  drives the real "Save current stack as..." action with
  `answer_modal(QInputDialog, "getText", ...)` across Cancel, blank, and
  whitespace-only names, then a real name.
- **m4**: `project.py`'s `load_site` now checks `isinstance(presets, dict)`
  before `.items()` and raises `ProjectError` naming the file and the
  `presets` key; new core test
  `test_malformed_top_level_presets_is_a_project_error`.
- **m5**: `ProcessingDock.save_preset_named` gained a `confirm: bool =
  True` parameter mirroring `apply_to_grid`'s own shape -- prompts via
  `QMessageBox.question` before overwriting an existing preset name; new
  test `test_saving_over_an_existing_preset_name_asks_first`.
- **m6**: same one-line fix as Important 1(c).

## New/changed tests and their reversions (all actually run)

Method as before: copy the target file aside, mutate one line, run the
single test, confirm it fails for the stated reason, restore from the
copy (never `git checkout --`).

1. **`test_presets_save_apply_and_persist`** (rewritten for m2) -- reverted
   the "campus" apply lambda to `lambda checked=False, n=name: None`.
   Result: `AssertionError: assert [] == ['dewow', 'gain_agc']` (list
   stayed empty -- the trigger genuinely exercises the wiring the old
   direct-call version didn't).

2. **`test_save_preset_prompt_rejects_blank_names_and_cancel`** (m3) --
   removed the `if ok and name.strip():` guard in `_save_preset_prompt`
   (called `save_preset_named(name)` unconditionally). Result:
   `AssertionError: assert ['campus'] == []` on the very first
   (Cancel) case -- a name got saved despite Cancel being pressed.

3. **`test_saving_over_an_existing_preset_name_asks_first`** (m5) --
   short-circuited the confirm block (`if False and confirm and ...`).
   Result: `AssertionError: assert []` on `assert calls` -- no question
   was ever asked, and the preset silently overwrote.

4. **`test_difference_view_clears_when_switching_lines`** (Important a) --
   short-circuited the new emit in `_open` (`if False and was_diff:`).
   Result: `AssertionError: assert not True` -- `diff_button` stayed
   checked after switching lines (the label still cleared correctly,
   since that reset was already unconditional before this fix -- only
   the button's state was wrong, which is exactly the drift the review
   described).

5. **`test_difference_view_recovers_when_the_differenced_step_disappears`**
   (Important b) -- narrowed `except (ValueError, IndexError)` back to
   `except ValueError`. Result: `AssertionError: assert ([])` on
   `messages and ...` -- the `IndexError` escaped `current_radargram`
   entirely; `error` never fired.

6. **`test_diff_button_is_disabled_with_no_line_open`** (Important c/m6)
   -- removed `self.diff_button` from the `has_line` tuple. Result:
   `AssertionError: assert not True` -- the button stayed enabled with
   no site open.

7. **`test_malformed_top_level_presets_is_a_project_error`** (m4) --
   removed the `isinstance` check in `load_site`. Result:
   `AttributeError: 'list' object has no attribute 'items'` at
   `project.py:205` -- the exact raw traceback the review quoted.

Every reversion above was restored from its copy before moving to the
next, and the covering test re-confirmed green after restoring.

## Full verification (post-fix)

```
$ PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
287 passed in 67.96s
```
(prior baseline for this task: 282; +5 new tests, no regressions)

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
337 passed, 2 skipped
```
(prior baseline for this task: 336/2; +1 new core test, no regressions)

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
6 passed
```

```
$ .venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
All checks passed!
92 files already formatted
```

```
$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

**Counts per tier, exactly as printed, never summed:** qgis 287 passed;
pure+core 337 passed / 2 skipped; boundary 6 passed; ruff clean, 92 files
formatted; mypy clean on the scoped set.

## Files changed (this round)

- `packages/nsgeo-core/src/nsgeo/project.py`
- `packages/nsgeo-core/tests/test_presets.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py`

## Manual M6 checkpoint

Still not run, not simulated, not ticked. Left entirely for the human.

## Self-review (round 1 fixes)

Stayed inside the parked boundary the review named:
`processing_dock.py` was not restructured, only had the one already-
justified confirm block added and one tuple entry extended -- matching
its house style (banner comments, `confirm: bool = True` mirroring
`apply_to_grid` exactly). No new names needed from `nsgeo.processing`;
`ALLOWED_FROM_PROCESSING` untouched; boundary still 6 passed.

---

# Fix round 2

Re-review: all 8 round-1 findings addressed, no new Critical/Important
breakage, 5 small items (3 new Minors plus 2 the reviewer folded in while
already in the file). All five addressed below. This closes Task 19 --
no further review round.

## 1. `set_difference_index` needed an early-out

`_open` and `current_radargram`'s except branch both already set
`_difference_index = -1` themselves *before* emitting
`difference_cleared`, which routes back into `set_difference_index` via
`diff_button` unchecking itself. That re-entrant call therefore always
carries the index unchanged -- but without an early-out it re-rendered
anyway: wasted work on an ordinary line switch (re-rendering the line
that's about to be replaced), and a logged Critical on `close_site`
specifically, since the session has already dropped `_site` by the time
`line_opened("")` fires (`SiteSession.close_site` clears `_site` before
emitting it -- confirmed parked, not touched).

Fixed: `set_difference_index` now returns immediately when `index ==
self._difference_index`.

## 2. `diff_button` checked state and `_difference_index` could disagree

`_emit_difference` used to emit `difference_toggled.emit(-1)` for both
"unchecked" and "checked with nothing selected" (`self.list.currentRow()
if checked else -1`, with `currentRow()` already `-1`) -- the same
payload for two different button states. `_open`'s `was_diff` guard is
keyed on the index, not the button, so it missed the second case:
checking Difference with nothing selected left the button checked (and
armed against whatever row got selected next) across a line switch,
unlike checking it *with* a row selected, which correctly cleared.

Picked one rule instead of two: `diff_button` cannot be usefully checked
with nothing selected at all.

- `_update_row_buttons` now also does `self.diff_button.setEnabled(row >=
  0)` (same condition as `remove_button`), so an ordinary click can't
  reach the inconsistent state. This narrows `rebuild()`'s existing
  `has_line`-based enabling rather than conflicting with it: `row` is
  always `-1` whenever no line is open (`list.clear()` leaves it there),
  so the two conditions never disagree.
- `_emit_difference` also self-corrects: `setEnabled(False)` never blocks
  a direct `setChecked(True)` (only real clicks), so if `checked and row
  < 0` it calls `self.diff_button.setChecked(False)` and returns without
  emitting -- belt and suspenders, matching this file's own established
  pattern of a loud guard plus a silent one (see `gain_strip.py`'s two
  independent barriers against the same class of drift).

## 3. `IndexError`'s raw text reached the user

Widening the catch in round 1 routed `IndexError`'s own message ("step
index 1 out of range (0..0)") into `error.emit(...)` verbatim -- developer
wording, unlike the `ValueError` sibling which is already human-facing.

Fixed: split the two exceptions into separate `except` clauses and added
a shared `_decline_difference(message)` helper (report + revert, used by
both) so the reset-clear-emit sequence can't drift between them.
`IndexError`'s branch now reports `"the differenced step no longer exists
in this stack"` instead of `str(exc)`. Updated
`test_difference_view_recovers_when_the_differenced_step_disappears` to
assert on `"no longer exists"` instead of the raw `"out of range"` wording
it was pinning.

## 4. `_rebuild_presets_menu` leaked an orphaned "Delete" `QMenu` per rebuild

Verified directly before fixing (see `probe_menu_leak.py` output below):
`QMenu.clear()` removes `presets_menu`'s actions -- including whichever
one last opened a "Delete" submenu -- but does not delete the submenu
object itself; it stays alive, parented to `presets_menu`, just
unreachable from `actions()`. A fresh `presets_menu.addMenu("Delete")`
every rebuild (on every `presets_changed` and every `site_opened`) leaked
one more every time.

```
$ .venv-qgis/bin/python probe_menu_leak.py   # 5 clear()+addMenu("Delete") cycles
orphaned Delete submenus: 5
```

Fixed: `self._delete_presets_menu = QMenu("Delete", self.presets_menu)`
built once in `__init__`, cleared and re-added
(`self.presets_menu.addMenu(self._delete_presets_menu)`) on every rebuild
instead of recreated. Verified the fix directly too:

```
$ .venv-qgis/bin/python probe_menu_fix.py   # same 5 cycles, persistent menu
Delete submenus after 5 rebuilds: 1
delete_menu still has the action: ['x']
Delete action present in top: ['Save…', 'Delete']
```

New test `test_presets_menu_delete_submenu_is_reused_not_leaked` pins this
at the dock level (5 real `presets_changed` rebuilds via
`save_preset_named`, then `findChildren(QMenu)` for "Delete" == 1).

## 5. `ProfileDock._clear` didn't reset `_difference_index`

`_open` resets `_difference_index`/`difference_label`/`difference_cleared`
on every line change; `_clear` (the `site_closed` teardown path) reset
neither, relying entirely on `close_site()` also emitting `line_opened("")`
first -- true today, but an implicit dependency on session-internal
ordering the review explicitly parked rather than asked me to fix at the
session level.

Fixed: `_clear` now resets the same three pieces of bookkeeping `_open`
does, in the same conditional-emit shape. No new test: I could not
construct a *reachable* scenario where `_clear` runs today with
`_difference_index >= 0` and `_open("")` has not already cleared it first
(every path that reaches `site_closed` with a difference view active
first passes through `close_site`'s own `had_current_line` check, which
is exactly when `line_opened("")` -- and therefore `_open`'s own reset --
also fires). Writing a test would mean directly setting
`profile_dock._difference_index` by hand and calling `_clear()` in
isolation, which builds its own precondition too directly to resemble a
failure this guards against -- the anti-pattern this task's own
instructions name. This mirrors the file's existing `_refresh_velocity`
(I4) precedent: a defensive guard kept explicitly "even though nothing in
today's call graph reaches it," documented as such rather than tested.

## Reversions run (all six numbered items, each restored before the next)

1. **Item 1** -- `test_closing_the_site_while_differencing_logs_nothing`
   (new test). Short-circuited the early-out (`if False and index ==
   ...`). Result: `message_log == ['could not render the difference
   view: no site is open']` -- the exact Critical-log symptom described,
   reproduced on an ordinary `close_site()` while differencing.

2. **Item 2a** -- `test_diff_button_disabled_and_self_corrects_with_nothing_selected`
   (new test). Disabled the `_update_row_buttons` line (commented out).
   Result: `assert not pd.diff_button.isEnabled()` failed -- button
   stayed enabled with nothing selected.

3. **Item 2b** -- same test. Restored 2a, then removed the
   `self.diff_button.setChecked(False)` self-correction (kept the early
   `return`). Result: `assert not pd.diff_button.isChecked()` failed
   after a forced `setChecked(True)` with nothing selected -- confirms
   the disabling and the self-correction are two independent fixes, not
   one disguised as two.

4. **Item 3** -- `test_difference_view_recovers_when_the_differenced_step_disappears`
   (existing test, updated assertion). Reverted the `IndexError` branch
   back to `self._decline_difference(str(exc))`. Result: `messages ==
   ['step index 1 out of range (0..0)']`, `"no longer exists" in
   messages[0]` is `False` -- the raw developer string, exactly what the
   review flagged.

5. **Item 4** -- `test_presets_menu_delete_submenu_is_reused_not_leaked`
   (new test). Reverted to the original `delete =
   self.presets_menu.addMenu("Delete")` per-rebuild construction.
   Result: `assert len(submenus) == 1` failed with `6 == 1` -- one
   orphan per save (5 saves -> 5 rebuilds -> 6 total, including the live
   one), matching the leak shape exactly.

Every reversion above was restored from a copy-aside file before the
next, and the full new-test file re-confirmed green after each restore.

## Full verification (post-fix, round 2)

```
$ PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
290 passed in 68.99s
```
(prior baseline for this task: 287; +3 new tests, no regressions)

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
337 passed, 2 skipped
```
(unchanged from prior baseline: no core files touched this round)

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
6 passed
```

```
$ .venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
All checks passed!
92 files already formatted
```

```
$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

**Counts per tier, exactly as printed, never summed:** qgis 290 passed;
pure+core 337 passed / 2 skipped; boundary 6 passed; ruff clean, 92 files
formatted; mypy clean on the scoped set.

## Files changed (this round)

- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py`

## Manual M6 checkpoint

Still not run, not simulated, not ticked. Confirmed untouched by the
re-review's own grep; left entirely for the human, who takes over after
the whole-branch review.

## Self-review (round 2 fixes)

No files outside the three above touched. The parked item (`SiteSession.
close_site`'s teardown ordering) was left alone as instructed --
`ProfileDock._clear`/`_open` were made to agree with each other, not with
a change to the session. No new names from `nsgeo.processing`; boundary
still 6.
