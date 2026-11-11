# Final fix wave report
1. session.py replace_grid: `count += direction == -1 and not fitted`; docstring re-wrapped (6). Tests: test_a_grid_length_change_keeps_fitted_lines_fitted (updated, whole-placement check), new test_a_grid_length_change_names_both_kinds_when_an_unfitted_reversed_line_moves. TDD: with the fix reverted both failed (counts 1 vs 2 reversed); green after.
2. lookup.py recompute_offsets: stretch/compress clause after `abs(scale-1) > SCALE_NOTE`. Test test_a_big_stretch_or_squeeze_is_named_in_the_fitted_note (pure; replan twice, 11% fit no clause, fit off clears). Red: NameError (SCALE_NOTE unimported) then green.
3. docs/guide/getting-started.md: known-limits paragraph; Scale-back-to-1 wording.
4. edit_lines_dialog.py: height clamped to 0.9 x available screen height. Test test_the_dialog_opens_no_taller_than_the_screen_allows. Red: 760 <= 540 failed (offscreen screen 800x600); green after.
5. test_a_pending_fit_on_every_row_skips_the_reversed_ones_the_grid_edit_moved (skipped = line 2/4/6, CHANGED_ELSEWHERE; forward rows end 14.0). Pins existing behaviour, passed first run.
6. line_edit.placement_note docstring; lookup docstring/comments/grid_size_along comment; project.py load_site catches AttributeError, test_a_null_placement_in_the_file_is_a_project_error_naming_the_line (red: AttributeError 'NoneType' has no attribute 'get'; green after).
Verification: core+pure 1181 passed, 5 skipped; QGIS 3 files 197 passed; ruff check/format clean; mypy clean.
