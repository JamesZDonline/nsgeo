# Merge origin/main into nsgeo-m16

Commits: b7a678f (merge), 5d1338b (velocity change).

## Conflicts
- README.md: main's version taken whole (roadmap). This branch's only README changes were roadmap text (Plan A under Done-ish "being built", M16 entry); main's M16 "In progress" entry stands.
- packages/nsgeo-core/README.md: kept both sections (`nsgeo.velocity_source` and `nsgeo.vtkxml`).
- packages/nsgeo-core/tests/test_public_api.py: both names, sorted (velocity_fit, velocity_source, vtkxml).
- ui/slices_dock.py: both signals kept (`paraview_requested`, `symbology_requested`). No other hunk in the file conflicted.
- Auto-merged files compile (compileall); no conflict markers remain.

## Velocity change
`paraview_export.py`: `summary` and `run` now use `session.grid_depth_velocity(grid_id)` (was `resolved_velocity` of the first line). `run` passes that model to the volume writer and to `_write_picks`, so depth axis, `max_depth_m` and pick depths share it. Existing tests that computed expectations with `resolved_velocity` now use `grid_depth_velocity("Grid A")`. New test `test_depths_follow_the_grids_velocity_not_a_lines_override` (line override moves nothing; grid velocity moves max_depth_m and the cube's depth axis); verified it fails on the old code.

## Tests
- core: 1285 passed, 4 skipped
- pure: 329 passed, 3 skipped
- QGIS, whole tier one process: 2470 passed, 1 warning (25 min; includes paraview_export 39, dialog, slices_dock, panels_menu)
- ruff check clean; ruff format --check 237 files clean; mypy: no issues in 54 files
