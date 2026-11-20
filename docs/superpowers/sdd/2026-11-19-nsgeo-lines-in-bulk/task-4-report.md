# Task 4 report
Built: nsgeo_qgis/decimal_input.py (parse_decimal, no Qt; R3 name), ParamForm._parse_number float branch calls it (float() probe first keeps the "is not a number" message; non-finite keeps "must be a finite number"), import_dialog Offset cell uses parse_decimal, `_updating`/`_following` are int depth counters (+=1 / -=1 in try/finally).
RED: pure test failed at collection (no module); qgis: 4 offset cases (1,000 / 1,5 / nan / inf), the same-inputs test, and both re-entrancy tests failed on old code. With only import_dialog.py reverted, the two reentrant tests failed (guard cleared early), 55 deselected.
GREEN: import_dialog + param_form files 112 passed (param_form tests unchanged); pure 1 passed; core+pure 2051 passed, 9 skipped, 19 xfailed; ruff check/format clean; mypy Success (56 files).
Files: decimal_input.py, ui/param_form.py, ui/import_dialog.py, tests/pure/test_pure_decimal_input.py, tests/qgis/test_plugin_import_dialog.py.
Concerns: none. Other set/clear flag files left untouched for the PR list. Used a temporary git stash (tagged, dropped) for the RED check.
