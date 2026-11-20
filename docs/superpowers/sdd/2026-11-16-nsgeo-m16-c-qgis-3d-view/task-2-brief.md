### Task 2: `Scene3D`, the view and what it shows

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/scene3d.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/surface_layers.py`, which gains two small public methods
- Modify: `packages/nsgeo-qgis/tests/qgis/conftest.py`, where `FakeIface` gains a fake 3-D canvas
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_scene3d.py`

**Interfaces:**
- Consumes:
  - Task 1's `scene3d_plan` and `ParaViewExport.pick_depths`;
  - `Surfaces.records()`, `Surfaces.state(fid)` and `SiteLayers` (the site group, the `picks` layer and `pick_rows`, or a read of all picks);
  - `surface_layers.depth_ramp` is not needed, because the 3-D symbol reuses the 2-D style.
- Produces:
  - In `surface_layers.py`:
    - `SurfaceLayers.layers_by_feature(self) -> dict[str, Any]`: feature id to the live `QgsMeshLayer` on the map;
    - `SurfaceLayers.add_listener(self, callback: Callable[[], None]) -> None`: called at the end of every `sync`.
  - In `scene3d.py`, `class Scene3D`:
    - `__init__(self, session, layers, surfaces, surface_layers, export_for: Callable[[], ParaViewExport], dock, iface, project=None)`;
    - `open(self) -> None`;
    - `refresh(self) -> None`;
    - `request_refresh(self, *_: Any) -> None`, coalesced through a 0 ms single-shot `QTimer`, like `SurfaceLayers.request_sync`;
    - `close(self) -> None`;
    - `dispose(self) -> None`;
    - `is_open(self) -> bool`;
    - `grid_id: str | None`, the current scene grid;
    - `picks_layer: QgsVectorLayer | None`.
  - In `conftest.py`, `FakeIface` gains:
    - `createNewMapCanvas3D(name)`: it makes a `FakeCanvas3D` (a `QObject`) and a top-level `QDialog` with that window title, records them, and returns the canvas;
    - `closeMapCanvas3D(name)`: it deletes both, so `destroyed` fires;
    - `mapCanvases3D()`;
    - `canvases3d: dict[str, FakeCanvas3D]` and `dialogs3d: dict[str, QDialog]`, keyed by name, holding what is open;
    - `created3d: int`, which counts every canvas ever made.

    `FakeCanvas3D` has:
    - `mapSettings()`, which returns a real `Qgs3DMapSettings` it owns;
    - `cameraController()`, which returns a recorder whose `setLookingAtMapPoint(*args)` call lands in a `.poses` list.

    Like QGIS, the fake copies `mapCanvas().layers()` into its settings at creation, and again whenever `QgsProject.instance().layersAdded` or `layersRemoved` fires.

- [ ] **Step 1: Write the failing tests** in `test_plugin_scene3d.py`.
  - The fixture `scene` is `built_site` (from `conftest.py`) plus a second grid with one built surface, a `FakeIface`, and `Scene3D(...)` whose `dock` stand-in has `scope()` and `grid_combo.currentText()`.
  - Read the 3-D symbol back from `layer.renderer3D()` by writing it to XML. A helper `_vertical_scale(layer)` returns the `vertical-scale` attribute, or None when the layer has no renderer.

```python
def test_open_shows_the_scene_grids_picks_and_surfaces(scene):
    s3d, session, surfaces, surface_layers, iface = scene
    s3d.open()
    assert s3d.is_open() and s3d.grid_id == GRID
    shown = surface_layers.layers_by_feature()
    for rec in surfaces.records():
        expect = 3.0 if rec.grid_id == GRID else None
        assert _vertical_scale(shown[rec.feature_id]) == expect
    pts = list(s3d.picks_layer.getFeatures())
    depths = _depths_of(scene, GRID)  # pick_depths for the grid's line picks, Nones dropped
    assert sorted(f.geometry().constGet().z() for f in pts) == pytest.approx(
        sorted(-d * 3.0 for d in depths)
    )
    settings = iface.canvases3d[VIEW_NAME].mapSettings()
    assert settings.terrainRenderingEnabled() is False
    assert iface.dialogs3d[VIEW_NAME].windowTitle() == view_title(GRID, 3.0, 0)
    assert len(iface.canvases3d[VIEW_NAME].cameraController().poses) == 1


def test_opening_again_reuses_the_view_and_brings_it_forward(scene):
    ...
    # one canvas created in all; the dialog is raised (isActiveWindow or a recorded raise_)


def test_a_view_closed_by_hand_cleans_up_and_opens_again(scene):
    ...
    # iface.closeMapCanvas3D(VIEW_NAME) -> picks layer gone from the project, no surface
    # layer has a renderer3D, is_open() False; open() makes a second canvas


def test_a_new_pick_and_a_rebuild_show_without_reopening(scene):
    ...
    # write a pick on the grid -> picks_changed -> spin_until a point more; rebuild a surface
    # -> its new layer has the renderer (via add_listener)


def test_the_stretch_restretches_picks_and_surfaces(scene):
    ...
    # session.remember_volume(GRID, stretch=2.0) -> Z values * 2/3, vertical-scale 2, title ×2


def test_the_scene_follows_this_grid_and_keeps_its_grid_in_whole_site(scene):
    ...
    # combo to grid B in "grid" scope -> renderers move to B's surfaces, camera framed again;
    # scope "site" then combo to A -> scene stays on B


def test_a_stale_surface_is_counted_in_the_title(scene):
    ...
    # change a surface's settings -> title ends "1 surface stale"


def test_an_empty_grid_opens_an_empty_scene_with_its_title(scene):
    ...
    # a grid with no picks and no surfaces: picks layer empty, title set, no error


def test_a_picks_layer_removed_by_hand_comes_back(scene):
    ...
    # project.removeMapLayer(picks layer id) then refresh -> a new picks layer, no raise


def test_a_cleared_project_forgets_the_scene_layers(scene):
    ...
    # QgsProject.instance().clear() -> no raise; picks_layer None; open() again works
```

  Spell each test out in full, with the asserts its comment names. Use `spin_until` from `plugin_testing` for anything a 0 ms timer delivers.

- [ ] **Step 2: Run them; they fail** (`ModuleNotFoundError: nsgeo_qgis.scene3d`).

- [ ] **Step 3: Add `layers_by_feature` and `add_listener` to `SurfaceLayers`.** `layers_by_feature` reads `_shown`, skipping layers no longer in the project. Listeners run at the end of `sync`, each inside `try/except Exception` with a log line.

- [ ] **Step 4: Implement `Scene3D`.**
  - **Connections.** `__init__` connects `session.picks_changed`, `features_changed`, `slice_sources_changed`, `grids_changed`, `lines_changed` and `presets_changed` to `request_refresh`. It also calls `surface_layers.add_listener(self.request_refresh)` and connects `project.cleared` to forget the scene layers.
  - **Doing nothing while closed.** `refresh` does nothing while the view is closed.
  - **`open()`, when the view is already open,** raises and activates its dialog, then refreshes.
  - **`open()`, when the view is not open:**
    - with no grid, it raises `ValueError(NO_GRID)`, where `NO_GRID` is wording in `scene3d_plan`;
    - it makes the export with `export_for()` and keeps it while open (it holds the zero probes);
    - it builds the picks layer `PICKS_LAYER_NAME`: PointZ in the site's CRS, with a `true_depth_m` double field, inserted directly below `picks` in `layers.group`, with a null 2-D renderer and the sphere symbol from probe fact 7;
    - it applies the surface renderers;
    - it creates the canvas with `iface.createNewMapCanvas3D(VIEW_NAME)` and finds its dialog by title;
    - it sets terrain off, a white background, and the CRS, origin and extent of the grid's corners;
    - it connects `canvas.destroyed` to `_on_closed`;
    - it sets the layers to `iface.mapCanvas().layers()` on a 0 ms timer (probe fact 3);
    - it frames the camera with `camera_pose`;
    - it sets the title.
  - **`refresh()`:**
    - it re-reads the scene grid with `scene_grid(dock.scope(), dock.grid_combo.currentText() or None, self.grid_id)`;
    - it rewrites the picks layer's features (truncate, then add) through `pick_depths`;
    - it puts renderers on the scene grid's surface layers and takes them off every other managed surface layer;
    - it re-titles, counting `surfaces.state(fid).stale` on the scene grid;
    - it re-frames only when the grid changed.
  - **The renderer** follows probe fact 6, with `setVerticalScale(scene_stretch(session.volume_record(grid)))`.
  - **`_on_closed` and `close()`:**
    - remove the picks layer;
    - set `setRenderer3D(None)` on every managed surface layer;
    - drop the references.

    `close()` calls `iface.closeMapCanvas3D(VIEW_NAME)` first when the view is open. `dispose()` calls `close()` and disconnects everything.
  - **Guards.** Every slot is guarded. When a layer or the dialog has gone, the step skips it.

- [ ] **Step 5: Run `test_plugin_scene3d.py` and `test_plugin_surface_layers.py`; they pass.** Then run the lint commands.

- [ ] **Step 6: Commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/scene3d.py packages/nsgeo-qgis/nsgeo_qgis/surface_layers.py packages/nsgeo-qgis/tests/qgis/conftest.py packages/nsgeo-qgis/tests/qgis/test_plugin_scene3d.py
git commit -m "feat(3d): Scene3D shows a grid's picks at depth and its surfaces in QGIS's 3-D view (M16 C)"
git push origin nsgeo-m16-c
```

