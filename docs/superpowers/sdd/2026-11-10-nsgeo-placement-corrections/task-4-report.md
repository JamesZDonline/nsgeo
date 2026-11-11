# Task 4 report
Commit 2045e43 (pushed). Implemented ImportOptions.fit_to_grid, ImportRow.scale, recompute_offsets fit logic (markers "exceeds grid size along", "fitted to the grid's", "cannot be fitted"; fit on clears exceeds, off clears both fitted components; rows not placeable or with span not > 0 keep scale 1), rows_to_lines passes scale, import checkbox on "Line length" row with tooltip, options() passes it, toggled -> _replan. Guide: Step 3 sentence + two paragraphs under "Fixing lines after import".
Tests: core+pure 1178 passed, 5 skipped (baseline skip count unchanged; the real-data campus tests ran, not skipped); QGIS test_plugin_import_dialog.py 40 passed. ruff, format, mypy clean.
TDD: pure tests RED (4 failed: unexpected fit_to_grid / missing scale) before implementation; GREEN after. The QGIS test was written with the pure ones but I did not run it separately in RED state (it would fail on missing fit_to_grid attribute); first run was after implementation.
Added a 4th pure test (toggle on/off leaves no stale note).
Self-review: copy strings match globals; no site names in guide. Concern: the 5 skipped include a pre-existing "no Sunnyside survey" skip, unchanged.

## Fix round 1 (ruling C2)
Changes: recompute_offsets places a fitted row at start 0 (forward) or grid length (reversed); unfitted rows keep the old Start rule. Dialog: _fit_toggled greys out Start along with a tooltip, then replans. Guide Step 3 says Start along is greyed out.
Tests (both RED first, then GREEN): pure test_fit_at_import_ignores_start_along_and_lands_on_both_edges; QGIS test_ticking_fit_greys_out_start_along_and_fits_the_rows.
Results: core+pure 1179 passed, 5 skipped; import dialog file 41 passed; ruff, format, mypy clean.
