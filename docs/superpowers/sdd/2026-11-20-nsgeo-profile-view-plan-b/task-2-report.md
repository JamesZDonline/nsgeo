# Task 2 report: per-mode parameters, the `row` kind, a form that follows the mode

Commit 7f85468 on nsgeo-profile-view, pushed (DNS failed once, second try went through).

## Implemented
- Core (`base.py`): `ParamSpec.when`, `"row"` in `KINDS`, `_problem` treats `row` like `int`, `param_visible` (exported from `nsgeo.processing`, README row added), `_when_problem` run from `register` (ValueError naming step and parameter).
- `timezero.py`: `sample` is `row`, min 0, `when=("mode",("sample",))`, new help; `threshold` `when first_break`. `gain.py`: `alpha`/`exponent` `when`, help text trimmed.
- ADDED (not in the brief): public `first_break_row_or_none(rg, threshold)` in `timezero.py`, exported and in the README. `test_plugin_boundary.py` forbids the plugin importing `_first_break_or_none` (private), so `time_zero_seed` needed a public name.
- Form: `RowSpinBox` (QSpinBox; touched flag, validate accepts digits and clamps on commit, wheel ignored without focus, arrow step commits through `row_stepped`). The signal is `row_stepped`, not `stepped`: `test_no_orphan_signals` refuses a second class with the same signal name. `set_step(..., row_range=)`, `_apply_visibility` (label + editor, connected before commit on every combo), `set_value` for rows, `values()` returns an int and every parameter, `show_row()` (shows a panel-written value without committing).
- `step_inputs.time_zero_seed`. Dock: `_show_form` row range `(0, n-1)`, `_seed_sample_row` + message in `_on_form_committed`, `needs_dialog` counts `row` like `time`.
- A row field also waits for the samples: with `stack.source is None` the form is left unbounded and `_form_axis_unknown` is set (so `line_loaded` rebuilds it), even for a first step whose header n would be known. That is what the brief's Review Focus 4 test needs.
- Real bug found by a test: after seeding, the committed step is an echo so the form is not rebuilt; the spin kept showing the old row. `show_row` fixes it.

## Sites that switch on `spec.kind`
- base.py `__post_init__` (KINDS check; choices rules): `row` needs nothing special.
- base.py `_problem` (two sites): `row` joins `int` for type check and bounds.
- base.py `_validate_params` (`curve` message only): unaffected.
- param_form `_make_editor`: new `row` branch. `values`: new RowSpinBox branch. `set_value`: RowSpinBox branch. `is_complete`: unaffected (spin never blank). `_parse_number`: `("int","row")` (kept for consistency; no line edit is built for row now).
- processing_dock `needs_dialog`: `row` joins curve/time. `_show_form`: row range. `add_step_with_dialog` seed (`curve` else time): a required row would get time seed, but no step has a required row; not changed.
- profile_dock `time_param_name` / `curve_param_name`: kind-specific, unaffected.
- test_schema.py (three sites) treated `int` only: now `int`/`row` (otherwise time_zero.sample lost its bound coverage).

## TDD
RED, core: `pytest packages/nsgeo-core/tests/test_param_when.py` with stubs (`when` field, `param_visible` returning True): 5 failed, 2 passed
(`unknown param kind 'row'`; `assert not True where True = param_visible(...sample..., {'mode': 'first_break'})`; three `DID NOT RAISE ValueError` for the bad `when`). The two that passed first are guards (a good `when` registers; saved time_zero/gain load unchanged).
RED, QGIS (stub `RowSpinBox`): param_form 6 failed (`isinstance(QLineEdit, RowSpinBox)`, `assert not True` on isVisibleTo of editor and label, `set_step() got an unexpected keyword argument 'row_range'`, `'QLineEdit' object has no attribute 'minimum'`); processing_dock 7 failed (no `maximum`, `sample and 0 == 37`, `0 == 60`, message `''` not starting with "Couldn't find the first break", no `stepBy`). Several fail by AttributeError/TypeError rather than a pure assert, because the old editor is a QLineEdit.
GREEN: core `1729 passed, 5 skipped, 19 xfailed` (before the last test-only fix; the fixed file and test_public_api then re-run 25 passed); pure `432 passed, 4 skipped`; param_form 60 passed; processing_dock 72 passed; difference_presets 18; preset_box 12; `-m real_data` 54 passed; time_cutoff + profile_dock + gain_strip 252 passed; `ruff check .` and `ruff format --check .` clean.

New tests: `packages/nsgeo-core/tests/test_param_when.py`; additions in test_plugin_param_form.py and test_plugin_processing_dock.py (including threshold-aware seed and "stays in sample is not reseeded"). Two existing param_form tests used `time_zero.sample` as the int-field example; retargeted to `trace_stack.window_traces`; the first-test assertion now expects `RowSpinBox`.

## Notes / concerns
- Env trap: the core venv imports `nsgeo` from the MAIN checkout. Core tests from the worktree need `PYTHONPATH=<worktree>/packages/nsgeo-core/src`; the QGIS tier uses the worktree correctly. Reviewers should know.
- Public-API additions beyond the brief: `first_break_row_or_none`.
- `plugin.py`, `slices_dock.py` untouched. Message text is set after `replace_step` (a successful build clears it).

## Fix round 1
Changes:
1. `ParamSpec.__post_init__` validates `when` (pair of str and non-empty tuple of str; not itself), ValueError names the parameter. The `register` test for "sibling not a choice" now uses a separate float `y` as the sibling.
2. Threshold test: weak arrival 300_000 (0.2 -> row 30, 0.5 -> row 60); asserts both. RED with processing_dock.py threshold temporarily hard-coded to 0.2: `assert 30 == 60` (test_switching_to_sample_uses_the_steps_threshold failed), then restored.
3. New `_CommitRules` mixin (wheel rule, arrow-step commit, valueFromText clamp, touched, edit_text); `TimeSpinBox`/`RowSpinBox` keep own signals (`stepped`, `row_stepped`); `set_value` one branch.
4. `_seed_entered_row` finds the `row` spec visible now and not for the step on screen (`param_visible`); returns a new dict.
5. `_on_form_committed` wraps `_commit_form` in try/except + log.
6. `values()` falls back to the built value (else default) for a hidden field that fails to read; visible fields raise as before (`_value_of`, `_modes`).
7. `step_inputs._input_record` shared by `input_axis` and `time_zero_seed`.
8. `show_row` logs and returns instead of asserting; `_stepped_line` lost `qgis_app`.
9. New tests: switch before samples load, behind a refusing step (bandpass above Nyquist), threshold edit in first_break mode (no seed, no message). These three pass first (guards for existing behaviour).

RED (new tests, before the fix):
- core `pytest packages/nsgeo-core/tests/test_param_when.py`: 8 failed, `Failed: DID NOT RAISE ValueError` for each malformed `when` (empty values, one item, three items, bare string, values a string, name not str, value not str, names itself).
- `test_plugin_param_form.py`: `test_a_cleared_hidden_field_does_not_block_a_mode_switch` failed (`assert ([])`: nothing committed). `test_a_cleared_visible_field_still_errors` passed first (guard).
GREEN: core test_param_when 17 passed; core whole 1738 passed (one stale failure from a test edited mid-run, re-run green); pure 432+ passed; param_form 62, processing_dock 75, difference_presets 18, preset_box 12; real_data 54; ruff check and format clean; mypy on nsgeo-core clean.
