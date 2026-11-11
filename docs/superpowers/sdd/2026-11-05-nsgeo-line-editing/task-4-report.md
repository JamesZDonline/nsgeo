# Task 4 report
Implemented ui/edit_lines_dialog.py (EditLinesDialog, constants, bulk panel, status, guards, accept branches) and plugin.open_edit_lines_dialog (+ _edit_lines_dialogs, unload() reject).
Tests: 18 in tests/qgis/test_plugin_edit_lines_dialog.py (brief's list + a different-site-opened test). QGIS tier 1543 passed; core+pure 1015 passed, 3 skipped; ruff + mypy clean.
TDD: RED confirmed (re-run with module moved aside): ModuleNotFoundError: No module named 'nsgeo_qgis.ui.edit_lines_dialog'. Honest note: the dialog was written before the first RED run; RED was demonstrated afterwards by removing the module. GREEN: 18 passed.
Files changed: the 3 above; no existing tests changed.
Calls/notes:
- Typing Dir after Start recomputes Start (a flip keeps the line's inset); the test types Dir first. Typed Start after Dir sticks.
- Bulk title is "Change the N selected lines" for every N (brief verbatim, no singular).
- Dialog file ~400 lines, single file.
- Mock-up .lavish/edit-lines.html is not present in the worktree; layout follows the brief/spec.
- Full QGIS run started before ruff format touched my 3 files (whitespace only); my test file re-run after.

## Fix round 1
Changed (edit_lines_dialog.py): `_changes`/`_live`/`_target_gone` make a row whose target grid left the site readable and actionable: OK counts it as changed so `edit_lines` skips and names it (dialog Accepted, rest applied); acting on such a row drops the dead move and says "grid 'B' no longer exists; line 6 stays on Grid5"; the row shows the target in the Grid column and Note. `_unavailable(exc)` names the grid actually missing. Offset/Start reject non-finite values (`math.isfinite`) with the "is not a number; unchanged" status. `_refresh` stores a blank LineEdit for any edit that no longer changes (double flip), so no false "changed elsewhere". Bulk title and header pluralise ("1 selected line", "1 line").
Tests added (10 cases): singular title/header, nan/abc Offset, inf/1e999/abc Start, removed target skipped + rest applied, move back from removed grid, choosing a removed grid blames it, double flip + length change gives skipped == ().
Results: edit-lines file 28 passed; QGIS tier 1553 passed (log scratchpad/t4fix-qgis.log); ruff check/format and mypy clean.
