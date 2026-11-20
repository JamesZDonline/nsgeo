# Final fix wave report (nsgeo-lines-in-bulk)

## Changes
- F1: `SurveyDock.selected_line_keys` returns [] when `not session.is_open`. `_capture_line_keys` only calls it, so covered; `_line_keys_only` (new) has the same guard. Tests (parametrised new_site / close_site): select two lines with nothing open, switch site, assert message_log == [] and no "survey tree error".
- F2: new `_line_keys_only(keys)` (keys in session.keys(), site-open guard). In the selection menu, `only_lines = _line_keys_only(keys) == keys` gates the GPS-destagger, Edit/Move and bulk items (the review named only bulk, but `_is_gps`/`_grid_of_key` on a non-line key would also have raised and broken the whole menu). `_lines_going` (feeds `_fits_would_go` and the "Also removed" text) counts only known lines. Test: monkeypatched `_selected_targets` returning a mag key -> menu is exactly ["Remove 1 line from site"], `_fits_would_go` False, `_lines_going` [], no log.
- F3: in both dialogs `imported_keys` is set right after add_lines, then apply_preset_to / remember_import_preset are in try/except Exception. Failure: ImportDialog sets `preset_notice` (plugin.py `finished` reports it as a Warning, which also logs it); GpsImportDialog appends it to `messages` (already reported as warnings); both put it in `status`; dialog still closes accepted. GPS `messages` is now set before the guarded block. Tests: one per dialog, monkeypatching `session.apply_preset_to` to raise.
- F4: `_restore_selection` and `_follow_current` comments corrected. The comment in `_select_only_announcing` is left: that function really does make two calls, so "Twice on purpose" is accurate there (the finding's "repeated" copy was the one in `_follow_current`).

## RED (fix sources reverted to HEAD, new tests kept)
- `qgis_tests.sh test_plugin_survey_dock.py -q -k "site_switch or not_lines"`: 3 failed; `assert ['could not rebuild the survey tree: no site is open'] == []` (x2), `assert [] == ['Remove 1 line from site']`.
- Dialog tests: RuntimeError "no disk" propagated out of accept (import), `result() == 0` (GPS).
## GREEN
- Four files (survey_dock, line_selection, import_dialog, gps_import_dialog): 215 passed, 1 failed: `test_plugin_import_dialog.py::test_remove_and_reorder`, which fails identically at HEAD (verified via uniquely-tagged stash, dropped) when run after test_plugin_survey_dock/line_selection in one process, and passes when its file runs alone (58 passed). Pre-existing cross-file order dependence, not caused here.
- ruff check: All checks passed; ruff format --check: 294 files already formatted.
- core+pure: see commit message/final reply.

## Files
plugin.py, ui/survey_dock.py, ui/import_dialog.py, ui/gps_import_dialog.py, tests/qgis/test_plugin_{survey_dock,import_dialog,gps_import_dialog}.py

## Concerns
- test_remove_and_reorder order dependence (above) should be filed.
- A mag-only selection still says "Remove N line(s)" in the count phrase; the magnetometer merge will need its own wording.
