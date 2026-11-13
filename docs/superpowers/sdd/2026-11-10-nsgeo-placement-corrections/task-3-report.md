# Task 3 report
Implemented: Scale and Destagger (m) columns (editable, highlighted by SAME_M), bulk rows (Scale spin/Set/Fit to grid edges; Destagger spin/Set), tooltips, set_scale/fit_to_edges/set_destagger slots (guarded), resize(1100,560), docstring; Survey panel suffixes.
Ruling P2 applied (all bad Scale cells give "... is not a scale above 0; unchanged"); fit uses `not span > 0`.
Tests: edit-lines dialog + survey dock files: 106 passed. tests/pure: 237 passed, 1 skipped. ruff check/format clean.
TDD: RED - dialog file failed at collection (ImportError COL_DESTAGGER, expected); survey test failed on missing "· ×0.954". GREEN - 106 passed.
PNG: /tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/230df20a-0ab7-4465-84c8-1dc4328fe980/scratchpad/edit-lines-task3.png - no column cut off (Note is wide, scrolls horizontally), bulk rows aligned, no overlap. Concern: with the two extra bulk rows the table shows only ~3.5 rows at 560 px height.
Files: ui/edit_lines_dialog.py, ui/survey_dock.py, the two test files.

## Fix round 1 (Ruling C1)
Changed edit_lines_dialog.py: resize(1100, 760), table added with stretch 1, comment citing Ruling C1.
Tests: edit-lines dialog file passed; test_plugin_boundary passed; ruff clean.
PNG: /tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/230df20a-0ab7-4465-84c8-1dc4328fe980/scratchpad/edit-lines-task3-fix1.png - fit on all rows, one selected: CHANGED highlight visible on Scale (all) and Start (reversed rows) of unselected rows. Fixture has only 6 rows, all visible with room for ~4 more (about 10 fit).
