# Task 2 report: Scene3D

Status: DONE. Files: nsgeo_qgis/scene3d.py (new), surface_layers.py (layers_by_feature, add_listener; sync now wraps _sync and notifies), tests/qgis/conftest.py (FakeCanvas3D, FakeIface 3-D methods, R1 layer copy), tests/qgis/test_plugin_scene3d.py (10 tests).

Tests: scene3d 10 pass; with surface_layers + surface_build 61 pass; pure tier 356 passed 4 skipped; ruff check/format and mypy clean.

TDD evidence (honest): I wrote scene3d.py before the tests, then the tests; the first run failed at import (QgsPhongMaterialSettings lives in qgis._3d, not qgis.core), then one test failed because layers.write_pick does not emit picks_changed (the test now emits it as the layer's edit hooks do). No clean RED on a missing module was captured.

Notes / concerns:
- A bare QgsApplication (tests) has no "mesh" 3-D renderer metadata until Qgs3D.initialize(); _mesh_renderer calls it when metadata is None (no-op in real QGIS).
- Picks are read via layers.pick_rows(all provider fids) (committed rows only), true depth from export.pick_depths.
- Stale count uses surfaces.state(...).stale truthiness (includes "unavailable").
- Layer set for the view is set once on open (and again after the picks layer is recreated), from checkedLayers on a 0 ms timer.
- R3 asserted in open/closed-by-hand/new-pick tests via session.dirty.
- Fake close deletes canvas and dialog with sip.delete; Scene3D ignores a late destroyed from an older view via a generation counter.

# Fix round 1

F1: scene3d_plan.py gained local_corners, scene_extent, scene_centre (camera_pose now uses them); scene3d.py only calls them; pure test added (test_local_corners_scene_extent_and_centre).
F2: open test empties `settings.setLayers([])` after open() then spin_until the picks layer is back; the removed-by-hand test connects a handler after the fake's own copy (empties layers on layersAdded), first waits for open()'s own timer to fire (`not s3d._layers_timer.isActive()`), then asserts the recreated picks layer reaches settings.layers() only after a spin. RED by hand: deleting `self._layers_timer.start()` in open() fails test_open_shows_... (line 115); deleting it in refresh() fails test_a_picks_layer_removed_by_hand_comes_back (line 237). (My first version of the refresh test passed with the start deleted because open()'s still-pending timer served it; fixed as above.) Both restored (cmp-verified).
F3: open() is split into _open_on, wrapped in try/except BaseException -> _teardown(); re-raise. Before creating it calls iface.closeMapCanvas3D(VIEW_NAME); a None canvas raises RuntimeError(VIEW_REFUSED) (wording in scene3d_plan). FakeIface createNewMapCanvas3D returns None when the name is open or `refuse3d` is set. Tests: leftover view closed and a fresh one opens; refused view raises, no picks layer or 3-D renderer remains, later open works. RED (None check and cleanup removed): test_a_refused_view... fails (AttributeError on None canvas).
F4: _find_dialog replaced by _holder(), re-found on every retitle/raise, any QDialog or QDockWidget titled VIEW_NAME or the last title set; no cached reference. FakeIface: `dock3d` hosts the view in a QDockWidget; `swap_holder3d(name)` swaps dialog/dock carrying the title. Test: docked view retitled and raised; after a swap the next refresh retitles. RED (holder looked up by VIEW_NAME only): test_a_docked_view... fails (line 291).
Checks: ruff check/format clean, mypy clean, pure tier 357 passed 4 skipped.

Final: test_plugin_scene3d.py 13 passed; pure tier 357 passed 4 skipped; ruff, format, mypy clean. test_plugin_surface_layers.py was not rerun this round (surface_layers.py untouched since the 61-pass run; a rerun under heavy machine load was cut short after 22 tests passing).
