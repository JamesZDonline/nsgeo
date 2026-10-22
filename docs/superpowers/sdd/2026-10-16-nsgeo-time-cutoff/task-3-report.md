# Task 3 report

Status: DONE.

## Implemented
- `profile_dock.py`: `time_param_name`; `set_selected_step`; `_cutoff_row` (live, never cached); `_show_cutoff`; `_on_cutoff_dragged` (identity + differs checks, record-before-replace, ValueError to `error`, guarded); `current_radargram` uses `result_bypassing(row)`; `_render` ends with `set_cutoff`; module docstring paragraph. `cutoff_dragged` connected; `KNOWN_UNCONSUMED` entry removed.
- `processing_dock.py`: seeding branch covers "curve" and "time" (`t0 + n*dt`).
- `param_form.py` (R3): numeric editors remember (shown text, exact value); `values()` returns the exact value when the text is unchanged.
- `plugin.py`: `step_selected -> profile_dock.set_selected_step`.
- README: R2 wording added to the "The steps are..." sentence.

## TDD evidence
- Dock tests (8): RED `AttributeError: 'ProfileDock' object has no attribute 'set_selected_step'` (8 failed); GREEN after impl (one test bug fixed: `set_preview(None)` to clear). profile_dock file: 71 passed.
- Seeding test: RED (IndexError; the unseeded path opened the dialog); GREEN.
- Form R3 test: RED (committed the `:g`-rounded value); GREEN. `test_a_time_param...` confirmed non-vacuous: with "time" removed from KINDS it fails (ValueError at base.py:108); restored via git checkout.
- Whole-plugin (3, incl. real data `test_a_real_line_clips_where_the_line_is_dropped`, RAN not skipped): RED (no connection: 463 != 300 etc.), GREEN after the plugin.py connection.

## Counts
- pure+core: 606 passed, 3 skipped. qgis tier: 694 passed. ruff check/format clean, mypy clean.
- `-s` run of the full qgis tier: no Traceback in output.

## Files
packages/nsgeo-qgis/nsgeo_qgis/{plugin.py,ui/profile_dock.py,ui/processing_dock.py,ui/param_form.py}; tests: tests/pure/test_no_orphan_signals.py, tests/qgis/{test_plugin_profile_dock,test_plugin_processing_dock,test_plugin_param_form,test_plugin_time_cutoff}.py; README.md.

## Concerns / notes
- `_render` with `rg is None` now also hides the line (cheap safety).
- A `ProcessingDock.step_selected` echo with the row unchanged does not re-render, per the brief; `_on_cutoff_dragged` skips writes for a preview or a stale step object.
- No mutation testing done on the dock tests beyond the KINDS check.
