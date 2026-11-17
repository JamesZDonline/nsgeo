# Task 5 report: Trace stack (#114)

Commit df6dc4a, pushed to origin nsgeo-step-edges.

## Implemented
- New `processing/trace_stack.py`: `TraceStack` (name trace_stack, group Filters, order 3, window_traces int min=1 default 3, help text verbatim). apply = `rg.replace(data=running_mean(rg.data, window_traces, axis=1))`. Registered in `processing/__init__.py`.
- Tests: new `test_steps_trace_stack.py` (8 tests, real FILE__007 and Grid 2 FILE__033); updated `test_step_titles.py`, `test_schema.py`, `test_plugin_processing_dock.py` as in the brief.
- Two tests not in the brief also enumerate every step and broke: added trace_stack to `_STEP_PARAMS` in `test_steps_background.py` and to `_PASS_THROUGH` in `test_processing_base.py`.

## TDD
RED: I wrote the implementation before running the tests, so I removed the `trace_stack` import line and ran
`.venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_trace_stack.py -q` -> `8 failed` (unknown step). GREEN with the import restored: `8 passed`.

## Measured (window 3, after time_zero + dewow)
- FILE__007: variance ratio 0.6549, median strongest-row shift 0 rows
- Grid 2 FILE__033: ratio 0.6137, median shift 0 rows

## Results
- Core: 1367 passed, 4 skipped.
- QGIS (per file): processing_dock 31, param_form 55, difference_presets 12, session 126, profile_dock 119, time_cutoff 13, gain_strip 44, survey_dock 81, site_scope 162, slices_engine 74, layers 110, grid_velocity_dialog 29, velocity_dialog 84; all passed.
- ruff check and format: clean. mypy (CI line): no issues in 52 files.

## Files changed
trace_stack.py (new), processing/__init__.py, tests: test_steps_trace_stack.py (new), test_step_titles.py, test_schema.py, test_steps_background.py, test_processing_base.py, qgis test_plugin_processing_dock.py.

## Self-review / concerns
- The QGIS set ran before I added the two enumeration-test entries (core-only files), so it is unaffected; core was rerun in full after.
- Strongest-row helper uses `abs` of amplitude in 8-40 ns on the stepped radargram's own time axis.
- No concerns.
