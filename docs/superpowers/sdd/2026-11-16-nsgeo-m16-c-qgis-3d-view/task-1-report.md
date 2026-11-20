# Task 1 report
Implemented scene3d_plan.py (constants, scene_stretch, view_title, scene_grid, stretched_z, CameraPose, camera_pose), ParaViewExport.pick_depths (+ module logger), ci.yml mypy list entry, tests.
RED: pure test file -> ModuleNotFoundError at collection; QGIS tests (with paraview_export.py at HEAD) -> 3 failed (AttributeError pick_depths).
GREEN: pure test_pure_scene3d_plan 4 passed; pure tier 356 passed 4 skipped; test_plugin_paraview_export.py 46 passed (real-data tests ran). ruff check/format clean; mypy (with scene3d_plan.py) clean.
Deviation: brief's QGIS tests pass GRID (a Grid object) as the id; tests use GRID.id (KeyError otherwise).
n_stale formatted with :g (int); a non-finite time_ns or zero probe failure -> None, probe failure logged once per key per call via logging.
Concern: used a brief `git stash` once for a RED check (popped immediately, own entry only).

## Fix round 1
I1: paraview_export.py now uses `from nsgeo_qgis.log import log as _log`; logging module removed; message "3-D view: no time zero for line {key}, its picks are left out: {exc}".
I2: synthetic test gained a valid 4th row; asserts first three None and the fourth a finite float > 0. RED against a hand-inserted `return out` stub: 1 failed (AssertionError at the new assert). Stub reverted.
GREEN: test_plugin_paraview_export.py 46 passed; pure tier 356 passed 4 skipped; ruff check, ruff format --check, mypy clean.
