# Task 2 report

Implemented: RadargramImage.reference (with_display keeps, with_radargram takes optional), curve_param_name in profile_dock.py (plugin._curve_param_name delegates), ProfileDock._scale_reference (difference view -> shown; else stack.result_bypassing(enabled curve rows); ValueError -> shown + Warning log; never bypasses cutoff), _render passes reference on both paths, slider tooltip, module docstring paragraph.

Tests: 2 RadargramImage tests, 10 dock tests (cutoff parametrised x2) plus the real-data test (ran, not skipped; limit equals clip(intermediate(2))).
RED: 13 failed, 3 passed (the 3 passes were existing tests plus the difference-view test, which already held); failures were TypeError unexpected keyword 'reference' / AttributeError reference / missing tooltip.
GREEN: profile_view + profile_dock files 173 passed. Full qgis tier 791 passed. core+pure 634 passed, 3 skipped (pre-existing). ruff clean, mypy clean.
No existing test broke.
Note: test 9 key2 lookup uses set difference because ruff SIM118 misfires on session.keys() (a method).

## Fix round 1
Change: test_two_gain_curves_are_both_left_out_of_the_scale now gives row 0 a real 12 dB gain (FLAT was a no-op) and asserts bypass(0,2) != bypass(2).
Mutation: `_scale_reference` temporarily changed to `result_bypassing(*rows[-1:])` -> test FAILED (1 failed). Restored via git checkout -> profile_dock tests 89 passed. ruff check and format clean.
Command: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -p no:xonsh
