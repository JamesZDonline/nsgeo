# Task 5 report

Implemented: SurveyDock signals edit_lines_requested(str, list) and move_lines_requested(list, str); reused `move_menu` submenu (made once, refilled per right-click, added via addMenu; __init__ comment corrected); grid menu "Edit lines…" (greyed when empty); line menu "Edit line…" and "Move to grid"; selection menus "Edit N lines…" (one grid only), "Move N lines to grid", Remove. Plugin: both connections in initGui, new `move_lines` (Critical on KeyError/ProjectError/other, Warning if skipped else Info). Guide: Survey bullet and new "Fixing lines after import" subsection before Step 4.

TDD: RED = survey dock + edit-lines test files: 6 failed (menus lacked entries, no edit_lines_requested, plugin had no move_lines), 75 passed. GREEN after implementation; two further existing tests needed updating (below).

Existing tests changed: the context-menu-per-kind test (grid and line lists), test_the_menu_on_a_selection_offers_one_removal_for_all_of_it, test_right_clicking_outside_the_selection_gets_that_items_own_menu: menu lists now include the new entries.

Results: dock + edit-lines files 81 passed; full qgis tier 1558 passed, 1 failed (test_plugin_grid_dialog.py::test_the_feature_list_follows_the_layer_list_not_its_signal: layer_combo currentLayer was 'grids' not 'plan'; passes alone, file alone 133 passed; looks order-dependent and unrelated, not re-run on base). core+pure 1015 passed, 3 skipped. ruff and mypy clean.

Concerns: the grid-dialog failure above. "the leaves nothing behind" test passes before implementation too (it pins a property, no RED). Selection with one line plus a grid row reads "Edit 1 line…" (via _count_phrase).

## Fix report: full-tier failure was this task's test
- Reproduced: `pytest tests/qgis/test_plugin_edit_lines_dialog.py tests/qgis/test_plugin_grid_dialog.py` -> 1 failed, 161 passed. With only `test_move_lines_moves_them_and_reports_on_the_bar::` in front of the grid-dialog file -> same failure (133 passed, 1 failed). So the coordinator's hypothesis was right: my plugin test opened a site and never called `plugin.unload()`, leaving the site's layers in QgsProject.instance().
- Fix (test only): wrapped the body in try/finally; finally does `answer_modal(QMessageBox, "question", Discard)` then `plugin.unload()` (unload prompts about the dirty site; first attempt without the answer failed on the forbidden modal). Production code is not at fault.
- After: both files together 162 passed. Whole QGIS tier: 1559 passed, 0 failed. ruff clean. Commit: test(ui): the move-lines plugin test leaves the project clean (#64).
- Note: I started a premature full run, killed it by its exact PID (111918, mine) and re-ran to /tmp/.../scratchpad/t5-qgis3.log. Nothing of mine is running.

## Fix round 1
1. "Edit line…" works out its grid at menu-build time (inside the guard).
2. Selection menu: separator before Remove (asserted in the selection-menu test).
3. "Move N lines to grid" uses _count_phrase; new test for grid row + one line (Edit 1 line…, Move 1 line to grid, Remove 1 line from site).
4. plugin.open_edit_lines_dialog is now a guarded wrapper over _open_edit_lines_dialog, reporting Critical on the message bar.
5. Guide: Edit lines… in the grid list, Set velocity override… in the line list, Delete removes while right-click gives the rest, "type a start and press Set", bold column names (Label, Offset (m), Dir, Start (m), Grid, Note), Shift/Flip/Move described per the dialog's controls.
6. New test for any/all greying of the submenu.
Covering: survey_dock + edit_lines_dialog files together: 83 passed. core+pure 1015 passed, 3 skipped; ruff and mypy clean.
Commands: QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest tests/qgis/test_plugin_survey_dock.py tests/qgis/test_plugin_edit_lines_dialog.py -q -p no:cacheprovider -p no:xonsh
