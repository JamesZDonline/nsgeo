# Task 4 report: dialog, Slices button, launching ParaView, guide

## Implemented
- `ui/paraview_dialog.py` `ParaViewExportDialog` (layout B): Grid; "3-D resolution (this grid's own)" (cell_spin, dz_spin, hints); "The volume" (transform, stretch, period, blur, "Depth balance" with the verdict's hint); "What will be written" rows (folder/volume/fill/also/size_label/disk_label); ParaView path + Browse; Cancel / Export / Export and open (default). Empty path: only Export enabled. Any ValueError (too fine, no preset...) shows in size_label and disables both. Spins use keyboardTracking off; summary refreshes on every finished edit (no debounce needed: summary is cheap).
- `paraview_scene.py`: `ExportSummary` dataclass, `summary_rows`, `size_text`, `disk_text`, `disk_is_short` (R14: free < export + cache + 0.5 GB), hints, success / how-to-open (open.sh/open.bat) / launch-failed / cancelled messages. Pure tests added.
- `paraview_export.py`: `ParaViewExport.summary` (R11, cheap, prepares nothing) and `panel_values` (hint data).
- BUG FIX in Task 3 code: `defaults()` read `transform_combo.currentText()` (a title like "Envelope" on the real TransformCombo) -> now `.value()` (the id). The fake Dock in test_plugin_paraview_export.py now provides `value`.
- `slices_dock.py`: `paraview_button` + `paraview_requested`, on whenever a site is open (set in __init__ and rebuild_source).
- `plugin.py`: `_PARAVIEW_KEY`, signal connected, `export_paraview()`, module-level `launch_paraview()`. Progress dialog shows at once titled "Exporting for ParaView", label "Preparing lines..." until the first real progress call. Cancelled / RuntimeError / ValueError handled as ruled. Unload needs nothing extra: the button lives on the dock that unload deletes.
- Guide: new Step 9 "Export for ParaView" (old Step 9 is now Step 10), plus a `paraview` row in "Where your data lives". Covers the folder, opening, stretch/legend, size/kept fill/disk warning, preset+gain, balance after gain, AGC double squeeze, calibration at iso 2.5.

## Tests
- tests/qgis/test_plugin_paraview_dialog.py: 17 tests (button both scopes, opens on panel grid, size refresh, rows, too fine, no path, disk warning via monkeypatched shutil.disk_usage, remembers record + path, reject writes nothing, launch spy args, plain export no launch, failed launch message, launch_paraview refusals, no path how-to message, cancel writes nothing and no .partial, progress dialog shown at once + labels, busy warning).
- export tests +3 (summary), pure scene tests +5.
- Runs: pure + core 1508 passed 6 skipped; the four qgis files (dialog, plugin_loads, slices_dock, paraview_export) 218 passed; ruff check, format --check, mypy clean. No_orphan_signals is in the pure suite (passed).
- TDD: the dialog tests were written with the code in one pass per file; recorded RED for real: pure wording test first run failed (800 MB vs 0.8 GB expectation), the dialog suite first failed on the transform bug above (found by the test, fixed), and the busy test first failed on a property setter. I did not stage a separate all-red run before writing the dialog, which is a process deviation.

## Files
nsgeo_qgis/{paraview_scene,paraview_export,plugin}.py, ui/{paraview_dialog,slices_dock}.py; tests/pure/test_paraview_scene.py, tests/qgis/{test_plugin_paraview_dialog,test_plugin_paraview_export}.py; docs/guide/getting-started.md.

## Concerns
- Cancel is not heard during "Preparing lines" (accepted).
- Fill row shows the method label only (e.g. "Kriging"), not the mockup's ", from this grid's slice settings".
- launch_paraview also requires the file to be executable (os.access X_OK), so on Windows an .exe passes; tested only on Linux.
- Screenshot: /tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/7ec288b0-6c3d-4401-b51d-656c73323d21/scratchpad/task4-dialog.png

## Fix round 1
1. Transform None (Critical): `choice()` maps the combo value with `site_scope.transform_value` (None -> ""); `_load_grid` maps "" -> "none" before `set_value` (so switching grids shows each grid's own transform); `volume_choice` reads a stored "none" back as "" so poisoned records heal. Tests: None in the dialog exports with real lines and records ""; panel on None gives a dialog default of None that exports; a record holding "none" heals; switching grids; dialog transform equals the panel's for every combo option; pure test for the stored "none".
2. Enter in a spin (Important): an event filter on the six spins and the path field swallows Return/Enter; for a spin it first calls interpretText(), so the value commits and the summary refreshes, and the dialog stays open. Test: typing 0.1 then Return leaves the dialog open, open_after False, size changed; Return in the path field keeps it open.
Results: dialog file 23 passed; export + loads + slices_dock 201 passed; pure 285 passed; core 1224 passed; ruff check/format and mypy clean.
