# Task 2 report: one corner table and Fit

Status: DONE_WITH_CONCERNS (see concerns).

Implemented: GridDialog now has one Corners group (corners_crs, 4x6 table, Pick buttons, Pick all/Rotate/Clear/Fit, fit_status), typed-size tracking, size_hint + Use these, live off-by. Tabs, digitise/polygon paths, set_corner_row etc. removed. plugin.py: removed digitise_requested.connect and _start_digitise only.
Tests: deleted the 24 obsolete tests (R1, R2 applied) and route 2 of the CRS guard test; added 18 new tests plus SITE/UTM16/WGS84 constants and project_crs fixture.

Results:
- qgis file: 43 passed. qgis tier: 923 passed (426 s).
- core+pure: 752 passed, 3 skipped. ruff check/format clean. mypy clean.
- RED: tests run against HEAD's grid_dialog.py failed at collection (ImportError: cannot import name 'COL_A'). GREEN: 43 passed after implementing.
- excepthook/unraisablehook check (temp plugin outside repo, verified it catches a raising slot): 43 passed, nothing fired.

Extra change (needed): packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py failed twice after the change (removed digitise connects orphaned points_picked/cancelled; new signals unconnected until Task 5; GridDialog is a 3rd pick_requested declaration). Added pick_all_requested, corners_changed, points_picked, cancelled to KNOWN_UNCONSUMED and set pick_requested to declared 3 / connects 2, with comments saying Task 5 wires/removes them.

Concerns / notes:
- Row changes (cell edit, set_corner, Rotate, Clear, Corners-in change) clear fit_status and the measured size (hint hides).
- Every user cell edit emits corners_changed (typing A then B = two emissions).
- Corners-in change that fails to convert reverts the widget and reports in fit_status.
- Removed unused `_select_sole_feature` test helper; kept _memory_layer and _pump for Task 3.
- Files: ui/grid_dialog.py, plugin.py, tests/qgis/test_plugin_grid_dialog.py, tests/pure/test_no_orphan_signals.py.

## Fix round 1

Changes (grid_dialog.py): R6 `_fit_line` holds the last Fit's line (RMS or refusal); row changes restore it over transient errors; only Clear clears it and `_measured`; Rotate swaps `_measured`; Corners-in change clears nothing. R7 half-filled row reads empty with "{role}: needs both coordinates"; Fit refuses with "{role} has only one coordinate: fill both or clear it" (first in role order), nothing changed. R8 suffix " · not quite square: see off by" when RMS does not display as 0.000.
Tests: Rotate test types only size_x -> sizes (10, 30), typed (False, True); typed-corners test asserts (False, False) after Fit and after Use these + second Fit with 30x25 corners overwrites both; existing-grid test uses a 10x10 grid; new tests for R6 (line survives edit/Rotate/Corners-in, measured swapped, error then good edit restores, Clear clears), refusal line survives, R7, R8 (corner nudged 5 cm).
Mutants (applied to grid_dialog.py, then restored): (a) `_size_edited` ignores `_sizing` -> test_typed_corners_fit_the_grid and test_rotate_... fail; (b) Rotate does not swap `_typed` -> test_rotate_... fails; (c) `_typed = [True, True]` removed from the existing-grid path -> test_an_existing_grid_opens_with_both_sizes_typed fails. Clean code: 47 passed.
Results: qgis file 47 passed with excepthook check (clean); qgis tier 927 passed; core+pure 752 passed, 3 skipped; ruff and mypy clean.
