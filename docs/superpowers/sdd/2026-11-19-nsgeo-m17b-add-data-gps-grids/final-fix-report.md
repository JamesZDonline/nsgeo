# M17b final-review fixes

Commits: first batch (F1, F2, F9, T-b), second batch (F3, F4, F5, F7, F8, F10, T-a, T-c, T-d). Both pushed to origin/nsgeo-m17b.

- F1: `slices_engine._without_label` strips the label from a TrackPlacement too. Test `test_a_label_only_edit_to_a_gps_line_does_not_re_prepare` (slices_engine file). Fails without the fix (checked).
- F2: GridImportPage gains `_chosen` (set by the opening grid, user pick, retarget; cleared when the combo falls back). `_lost` is set only if the lost grid was chosen; a combo that fills itself from an empty site clears `_lost`. Four tests in test_plugin_import_dialog.py (rollback, last-removed-then-added, user pick, retarget). The first two fail without the fix (checked).
- F3: `_name_changed` clears `_lost` (a typed name is choosing New grid). `test_a_grid_removed_under_the_page...` updated: refuses before a name is typed (`import_lines()` returns False, status names A), imports into G1 after. Fails without the fix (checked).
- F4: `_add_move_menu` disables `sub.menuAction()` when the site has no grids; the next fill sets it again. Test `test_move_to_grid_is_greyed_on_a_site_with_no_grid_and_wakes_with_one`.
- F5: guide edits (a)-(d) in docs/guide/getting-started.md.
- F7: `_name_changed` renames the proposal (`dataclasses.replace(id=...)`) and refreshes the table; no `_apply_target`, so no `fit_frame`. Test `test_a_name_change_does_not_fit_the_grid_again` counts `fit_frame` calls (0) and checks id, Import text. Fails without the fix (checked).
- F8: `OUTSIDE_CRS_PREFIX` ("outside what ") excluded from `leftovers`. Test `test_a_file_outside_what_the_crs_can_place_is_not_handed_on` (summary shows "not imported: FILE__002.DZT (outside what EPSG:32632 can place)", dialog closes). Fails without the fix (checked).
- F9: `edit_lines` skips a TrackEdit whose new grid crs differs from the line's, with the ruling's reason text. Test via `move_lines` in test_plugin_session_gps_grids.py. Two existing survey-dock tests moved GPS lines into a grid in another CRS; they now use grids in the site CRS (the mixed-selection test builds its own grid S).
- F10: `GridImportPage.end_hand_on()` (hides banner, shows rows); `AddDataDialog.set_mode` calls it on any mode change, and the Grid page's Import calls it after a successful import. Test `test_switching_mode_ends_the_hand_on_on_the_grid_page_too`. Fails without the fix (checked).
- T-a: grid spacing 0.8 in `test_a_gps_line_in_a_grid_hides_by_the_grids_default_spacing`.
- T-b: asserts `[IN_A, TAPE]` exactly (passes).
- T-c: `test_a_gps_line_in_a_grid_sits_under_that_grids_item` (survey dock).
- T-d: comment above `HIDE_LINES_BEYOND_SCALE_PER_M`, `edit_lines` and `move_lines` docstrings updated.

## Verification
- core + pure: 2098 passed, 9 skipped, 19 xfailed.
- qgis files (all pass): add_data_dialog 35, import_dialog 62, gps_import_dialog 50, edit_lines_gps 19, survey_dock 124, layers_gps 24, session_gps_grids 12, slices_engine 88, edit_lines_dialog 54, session 153.
- real-data tier: 52 passed, no skips.
- ruff check + format --check (.venv-tools): clean. mypy (CI line): no issues in 65 files.
- Not run: test_plugin_slices_dock.py (slices tests touched only in slices_engine file).
