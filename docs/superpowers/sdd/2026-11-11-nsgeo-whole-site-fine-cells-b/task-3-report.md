# Task 3 report: the background export task

Status: DONE (with notes). Commit: see `git log` (feat(export): run exports in QGIS's background-task list). Not pushed.

Files: packages/nsgeo-qgis/nsgeo_qgis/export_task.py (new), packages/nsgeo-qgis/tests/qgis/test_plugin_export_task.py (new, 17 tests).

Implemented: WriterPlan (R5), ExportResult with coverage_limit (R6), running_export (R8), start_export, ExportTask. Both partials written (values + overviews, then companion + overviews) before either is committed; any cancel/failure discards both (R17). Progress via setProgress across both files; a progressChanged slot on the GUI thread sets the description (R18); setDescription is never called from run(). should_stop = isCanceled. finished/_deliver is guarded, clears the hold before on_done, logs a raising on_done through QgsMessageLog.

Decisions to know:
- start_export returns False only when another export is held (on_done not called). If addTask() returns 0 it calls on_done with an error and returns True ("on_done will be called exactly once").
- ExportTask takes an extra optional kwarg `what` (the noun in "Exporting {what}: ..."), defaulting to the description. The coverage phase uses "coverage".
- QgsTask.setProgress dedups equal values (verified), and the description follows emission, so each announced grid nudges progress by 0.01 band (under half a band; band_done then passes it). Documented in code.
- If the second commit (os.replace of the companion) fails after the first succeeded, the values file is already replaced; the error is reported. Unavoidable with two renames.
- Tests replace run_export and build_overviews with fakes (task behaviour, not pixels). Engine test spies every method of SliceEngine and SiteEngine and asserts none ran off the GUI thread, plus a real slice_at redraw while the worker is mid-band.
- Queued-cancel test saturates QThreadPool.globalInstance() with blocker tasks (events, not status(), since the manager deletes finished tasks' C++ objects; an earlier status() version was flaky).

Tests: new file 17 passed; with test_plugin_slice_export + test_plugin_site_export 108 passed (repeated 6x for the task + site file, stable); pure tier 255 passed 1 skipped; ruff check, ruff format --check, CI mypy line clean.
RED evidence: written after the module, so verified by mutation: removing discard_partial in run()'s finally fails 7 tests (cancel/failure/later-phase cases). Earlier, the first run's failures exposed the queued-cancel and progress/description behaviours above.

## Fix round 1

1. Description: removed the 0.01-band nudge and the stashed-latest/progressChanged slot. `ExportTask.describe = pyqtSignal(str)` is emitted from the worker in `progress()` (band k, grid) and from `band_done` (next band, "binning"); it is connected in `__init__` to a GUI-thread slot that calls `setDescription`. `setProgress` stays for the bar only. New test: 60 bands x 3 grids, stalls at band 31 grid g2, waits for the description to equal "Exporting site slices: band 31 of 60 · g2".
2. Enums: `QgsTask.Flag.CanCancel`, `QgsTask.TaskStatus.Queued`; grep finds no other unscoped QgsTask/Qgis enum in either file.
3. Real stack: the vacuous spy test is replaced by `test_a_cancel_mid_band_over_the_real_stack_...`: pure-tier two-grid site builder (loaded by path), minimum curvature, cell 0.05, real `run_export` + `GeoTiffSiteWriter.write_bands` + real `build_overviews`, values + coverage companion; cancelled at band 1 grid A. Asserts cancelled, no partial, both existing targets byte-identical, a live `SliceEngine.slice_at` redraw works mid-run, and a `__getattribute__` recorder on SliceEngine/SiteEngine classes saw no off-GUI-thread access. Caveat: the spec holds no engine, so the spy is a guard, not proof; Task 5 should spy on the real snapshot.

Run: QGIS test_plugin_export_task.py 18 passed (3 repeats); pure tier (incl. test_no_orphan_signals) 255 passed, 1 skipped; ruff check, format --check, CI mypy clean.
