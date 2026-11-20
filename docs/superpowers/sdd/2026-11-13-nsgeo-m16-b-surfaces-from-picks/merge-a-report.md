# Merge of origin/nsgeo-m16 (5d1338b) into nsgeo-m16-b

Merge commit 27b64b5 (pushed). Parent 12371a6 + 5d1338b.

## Conflicts
- paraview_export.py (_fill_grid): kept B's structure (announce/step callbacks, FilledGrid); dropped A's inline
  window/slab/step/tick_trend block (that logic lives in B's run/_fill) and took A's rule:
  `velocity = session.grid_depth_velocity(grid_id)`. summary() already auto-merged to the grid rule.
  FilledGrid.velocity feeds the volume, place_picks and picks.vtp (run, _write_picks), so all conversions use it.
  No resolved_velocity call remains in paraview_export.py.
- test_plugin_paraview_export.py: kept both sides (B's surface tests, A's
  test_depths_follow_the_grids_velocity_not_a_lines_override).
- Auto-merged files (plugin.py, session.py, conftest.py, plugin_testing.py, docs): compile, ruff/mypy clean.

## Surfaces
- surfaces.py Surfaces.inputs()["velocity"] now hashes session.grid_depth_velocity(record.grid_id).
- New test test_a_surface_follows_the_grid_velocity_not_a_lines_override in test_plugin_surface_build.py
  (line override changes neither depths nor staleness; grid velocity changes both; depth doubles at 2x velocity).

## Tests
See reply for counts; full QGIS tier result appended below.

Counts: core+pure 1670 passed, 8 skipped, 1 xfailed; test_slices_surface -W error 39 passed, 1 xfailed;
paraview export/dialog + surface build/layers/dock/membership/new-surface (pvpython) 183 passed; pure test_paraview_scene
(pvpython) 24 passed; whole QGIS tier 2578 passed (1 warning, 29:16); ruff check, ruff format --check, CI mypy all clean.
