# M16 C final fix wave: report (commit ed9407c, pushed to origin nsgeo-m16-c)

Files: scene3d.py, scene3d_plan.py, tests/qgis/conftest.py (fake), test_plugin_scene3d.py, tests/pure/test_pure_scene3d_plan.py, docs/guide/getting-started.md.
RED = fix reverted by hand (copy restored after), single test run; all RED runs failed as expected except M3's first attempt (my sed missed after reformat; redone, then RED).

- C1 picks never update: `_fill_picks` now compares the layer's (x,y,z,depth) set with the wanted one, rewrites only on change (R13), then `layer.trigger3DUpdate()`. Test test_picks_update_in_the_open_scene_after_a_new_pick_a_stretch_and_a_grid_switch counts `request3DUpdate`: no change = 0, new pick, stretch, grid switch = +1 each, repeat = +0. RED (trigger removed): fails. GREEN.
- I1 CRS rebuild: `_frame` sets `_rebuild_layers` and starts the 0 ms layers timer; `_set_view_layers` does setLayers([]) then setLayers(checked). Test test_a_frame_rebuilds_the_views_layers_in_its_new_crs watches `layersChanged`: [[], full]. RED: fails. GREEN.
- I2 3.40: `_frame` uses `resetView(distance)` when the controller lacks `setLookingAtMapPoint`; `open()` failure branch closes the real view (`closeMapCanvas3D`) when a canvas was made. Fake: `iface.legacy_camera3d`. Tests: test_a_3_40_camera_..._reset_view, test_a_failed_frame_closes_the_real_view_and_leaves_nothing. RED both: fail. GREEN.
- I3 title on dock toggle: holder `destroyed` -> `request_refresh` (hooked once via property nsgeoHooked in `_retitle`); fake swap re-applies the ORIGINAL name. Test test_a_dock_toggle_retitles_the_new_holder_without_another_refresh (both directions). The older swap test no longer relies on a refresh. RED: fails. GREEN.
- I4 skipMemoryLayersCheck=1 set on the picks layer; test_the_picks_layer_is_marked_temporary_... RED: fails. GREEN.
- M1 `scene_grid(..., existing)` falls back to the panel's grid when `last` is gone; refresh/open pass the site's grid ids; refresh returns if the grid is not in the site. Pure test + QGIS test_removing_the_scene_grid_in_whole_site_.... RED (QGIS): fails. GREEN.
- M2 insert under `node.parent()`, `picks_layer` set straight after addMapLayer; test_a_picks_layer_in_a_subgroup_.... RED: fails. GREEN.
- M3 URI always `PointZ?field=true_depth_m:double`, CRS via `setCrs`; test_the_picks_layer_declares_its_depth_field_without_a_crs. RED: fails. GREEN.
- M4 `padded_extent` (10% of longer side, min 1 m) in scene3d_plan, used by `_frame`; pure test + test_the_scene_extent_has_a_margin_round_the_grid (RED: fails).
- M5 Identifiable flag cleared; asserted in the marked_temporary test (RED: fails).
- M6 guide: "Which picks" bullet (cuts and Choose-lines-excluded lines not shown).
- M7 `_framed_geometry` (origin, azimuth, size, crs) compared in `refresh`; test_a_moved_grid_is_framed_again (uses replace_grid).
- M8 `PICK_COLOUR` now in scene3d_plan.
- Also: look pinned (sphere shape, QgsNullSymbolRenderer) in the marked_temporary test; None mesh metadata now logs via `_log` (test_a_missing_mesh_renderer_is_logged_not_silent).

## Results
- scene3d tests: 35 passed. Pure tier: 359 passed, 4 skipped.
- Whole QGIS tier, run on ed9407c: `2694 passed, 1 warning in 2180.22s (0:36:20)` (includes panels_menu and surface_layers files).
- Lint: ruff check clean, ruff format --check clean, mypy (ci.yml list incl. scene3d_plan.py): "Success: no issues found in 60 source files" (local mypy 2.3.1; CI pins 2.4.0).

## Concerns
- Not verified in a real 3-D window (offscreen hangs): C1, I1, I3 and the 3.40 `resetView` path rest on the reviewer's disassembly plus fakes; the walkthrough should check them on 3.44.
- I1's rebuild runs on every frame (open, grid switch, grid geometry change), so the scene briefly empties then refills.
- The I3 hook assumes QGIS's new holder exists by the next event-loop turn after the old one is destroyed.
