# M16 Plan C: The QGIS 3-D View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A **3D view** button on the nsgeo toolbar opens QGIS's own 3-D view of one grid. The view shows that grid's picks at their depths and its built surfaces, stretched in depth, with the stretch in its title. It keeps up with new picks, rebuilt surfaces and the Slices panel's grid, without being reopened.

**Architecture:**
- **A pure module, `scene3d_plan.py`,** holds the arithmetic and all wording:
  - the view's name and title;
  - the scene-grid rule;
  - the stretch;
  - the camera pose.
- **`ParaViewExport.pick_depths`** gives each pick the true depth the ParaView export and the surface builder give it: on the cube's clock, through the grid's velocity. It does this without preparing any line.
- **A plugin class, `Scene3D` (`scene3d.py`),** owns the open view. It:
  - keeps a derived "Picks at depth" point layer (PointZ, Z baked);
  - puts a mesh 3-D renderer on the scene grid's surface layers, and takes it off the others;
  - sets the view's title and camera.
- **The view chooses its layers itself.** The 3-D view follows the main map's layers, and with terrain off only layers that carry a 3-D renderer draw. So the scene is decided by which layers have a 3-D renderer, not by a layer list nsgeo sets.

**Tech Stack:**
- QGIS 3.40 / 3.44 / 4.2 (`qgis._3d`), PyQt5 and PyQt6.
- pytest.
- No core change and no new dependency.

**Spec:** `docs/superpowers/specs/2026-11-11-nsgeo-m16-3d-design.md`. Read these parts first:
- §3, its "QGIS 3-D from Python" bullets;
- §4: call 11 and call 9's last paragraph;
- §5.4, the 3-D view;
- §6, the last two rows;
- §9 item 6;
- §10, "The 3D view".

Plans A (#190) and B (#202) are merged. This plan builds on their `ParaViewExport`, `Surfaces` and `SurfaceLayers`.

## What the probe settled (QGIS 3.44.7, a real window, 2026-11-16)

These were measured, not assumed. The probe scripts are not in the repo.

1. `iface.createNewMapCanvas3D(name)` (QGIS 3.36 and later) returns a `Qgs3DMapCanvas`.
   - The canvas is a **QWindow**. It has no `setMapSettings`, no `saveAsImage` and no widget methods.
   - **It never returns under `QT_QPA_PLATFORM=offscreen`.** No test may call it; tests use the fake canvas from Task 2.
2. **Configure the view through its live settings.** `canvas.mapSettings()` returns the view's own `Qgs3DMapSettings`, and you change it in place:
   - `setTerrainRenderingEnabled(False)`, `setOrigin(QgsVector3D)`, `setExtent`, `setCrs` and `setBackgroundColor` all work;
   - terrain-off survives later layer changes.
3. **The view follows the main map's layers.** Any change to the map's layer set resets `mapSettings().layers()` to the map's layers. Layers nsgeo added with `setLayers` but that are not on the map are dropped.
   - At open, the view copies the map's layers *of that moment*, so layers added in the same event-loop tick are missing.
   - With terrain off, a layer with no 3-D renderer does not draw (a plain polygon layer was invisible).
4. **Title.** The view sits in a top-level `QDialog` whose `windowTitle()` equals the name passed in.
   - Find that dialog with `QApplication.allWidgets()`; `setWindowTitle` on it works.
   - `iface.closeMapCanvas3D(name)` still closes the view by its original name.
   - `canvas.destroyed` fires when the view closes.
5. **Camera.** `canvas.cameraController().setLookingAtMapPoint(QgsVector3D(x, y, z), distance, pitch, yaw)` takes map coordinates.
6. **A surface layer draws in 3-D,** checked on a screenshot, when it has this mesh 3-D symbol:

   | Setting | Value | Why |
   |---|---|---|
   | `setVerticalDatasetGroupIndex` | 0 | "Bed Elevation" is the 2DM's Z, which is −depth |
   | `setIsVerticalMagnitudeRelative` | `False` | Z is absolute |
   | `setVerticalScale` | the stretch | stretches depth |
   | `setRenderingStyle` | `QgsMesh3DSymbol.RenderingStyle.ColorRamp2DRendering` | reuses the layer's own 2-D depth colours, so the 3-D colours match the map |

   - The symbol goes into `<renderer-3d type="mesh" layer="<id>"><symbol type="mesh">…</symbol></renderer-3d>`, written with `symbol.writeXml`.
   - `QgsApplication.renderer3DRegistry().rendererMetadata("mesh").createRenderer(element, QgsReadWriteContext())` builds the renderer, and `layer.setRenderer3D(renderer)` sets it.
7. **Picks draw as spheres.** A PointZ memory layer with Z = −depth × stretch draws on the stretched surface when it has:
   - a `QgsNullSymbolRenderer` in 2-D, so it draws nothing on the map;
   - `QgsVectorLayer3DRenderer(QgsPoint3DSymbol)` with `setAltitudeClamping(Qgis.AltitudeClamping.Absolute)`, a sphere shape, `setShapeProperties({"radius": r})` and a `QgsPhongMaterialSettings` colour.

   The default shape is a cylinder, so set the sphere explicitly.

**Not measured:** QGIS 3.40's and 4.2's real windows. CI (3.44 and 4.2) runs everything but the window. The walkthrough runs the real window on the author's 3.44.

## Global Constraints

- **Run every test from the worktree root with `PYTHONPATH=packages/nsgeo-core/src`.** Below, `R=/home/jameszd/Documents/Github/archaeo_geophysics`.
  - **Pure:** `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`
  - **QGIS:** `PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen $R/.venv-qgis/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`. The whole tier takes about 37 minutes, so run single files while iterating.
- **Lint as CI does,** with line length 100:
  - `$R/.venv/bin/ruff check .`
  - `$R/.venv/bin/ruff format --check .`
  - the mypy command in `.github/workflows/ci.yml` (job `lint`).

  `scene3d_plan.py` joins the mypy list, both in that job and in your local run.
- **Never call `iface.createNewMapCanvas3D` in a test.** It hangs offscreen; tests use the `FakeIface` canvas from Task 2.
- **Plugin boundary.** Arithmetic and message text live in `scene3d_plan.py`, never in `scene3d.py` or `plugin.py`.
- **Qt.**
  - Use fully qualified enums.
  - Every Qt-invoked slot guards its body with `try/except Exception`.
  - Every new `pyqtSignal` is connected (`tests/pure/test_no_orphan_signals.py`).
- **nsgeo writes nothing in this plan:**
  - nothing to `site.nsgeo.gpkg`, and nothing to `survey.nsgeo.json`;
  - opening or closing the view never marks the site dirty;
  - the authored `picks` and `features` tables are only read.
- **The view never changes what the Slices panel shows,** and never prepares a line. Pick depths read at most one file per line, once, through `ParaViewExport._zero_of`, and only when the preset sets time zero.
- **No site coordinates, real survey files or site pictures are committed.**
- **Commits:**
  - every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - push each one to `origin nsgeo-m16-c` as you make it.

## Before Task 1 (coordinator)

- The worktree is `.worktrees/nsgeo-m16-c` on branch `nsgeo-m16-c`, off main 6ab8f9a. The real data is already linked into `packages/nsgeo-core/tests/data/local/`.
- Record a baseline: the pure suite, then the QGIS files this plan touches (`test_plugin_paraview_export.py`, `test_plugin_surface_layers.py`, `test_plugin_panels_menu.py`, `test_plugin_slices_dock.py`).
- Before each task, run `git fetch && git merge origin/main`.

## Review Focus

These are the inputs the spec implies but none of its tests feed. Each is pinned by a test in the task named.

1. **The user closes the view with its own close button.** The view's `destroyed` fires. nsgeo removes its picks layer and the surfaces' 3-D renderers, and the button opens a fresh view. *Task 2:* `test_a_view_closed_by_hand_cleans_up_and_opens_again`.
2. **The user removes the "Picks at depth" layer, or a surface's layer, from the Layers panel while the view is open.** Nothing raises. The next refresh brings the picks layer back. *Task 2:* `test_a_picks_layer_removed_by_hand_comes_back`.
3. **A grid with nothing to show:** no picks, no built surface, its lines not in its slices, or a pick whose depth cannot be found. The view opens with its title and no error; unplaceable picks are left out. *Task 1:* `test_pick_depths_are_none_where_they_cannot_be_found`. *Task 2:* `test_an_empty_grid_opens_an_empty_scene_with_its_title`.
4. **The site closes, or another opens, while the view is open.** The view closes and the picks layer goes. A new site never shows the old site's picks. *Task 3:* `test_closing_the_site_closes_the_view`.
5. **QGIS's project is cleared** (File ▸ New) while the view is open. Nothing raises, and nsgeo forgets the layers it held. *Task 2:* `test_a_cleared_project_forgets_the_scene_layers`.

## Calls this plan makes (the spec left them to the builder, §11)

1. **The stretch is the grid's own,** the one its ParaView export uses: the `stretch` field in `session.volume_record(grid)`, default ×3 (`DEFAULT_STRETCH`). Changing it in the export dialog moves the view (`slice_sources_changed`). The view has no stretch control of its own. **Cost if wrong:** the user goes through the export dialog to change it.
2. **Surfaces are stretched by the mesh symbol's vertical scale,** not by rewriting their files. The 2-D map keeps the same layers, untouched. **Cost if wrong:** none known; it was measured.
3. **Picks are a derived memory layer, "Picks at depth (3D view)".**
   - It sits directly below `picks` in the site group, and draws nothing in 2-D.
   - It exists only while the view is open.
   - It holds one point per pick on the scene grid, at true depth through `pick_depths`.
   - Picks on cuts are left out until Plan D.

   **Cost if wrong:** one extra layer in the Layers panel while the view is open.
4. **Picks are dark grey spheres of radius 0.06 m.** The surfaces carry the depth colours. **Cost if wrong:** a constant to change after the walkthrough.
5. **"Stale surfaces are labelled":**
   - each surface's map layer already says "(stale)" in the Layers panel, and the 3-D view draws those same layers;
   - the view's title adds a count, such as "2 surfaces stale".

   **Cost if wrong:** a stale surface in the scene is named only in the Layers panel.
6. **Other layers the user has given a 3-D renderer still draw in the view.** nsgeo takes renderers off only the surface layers it manages. **Cost if wrong:** a user's own 3-D layer appears in the scene; that is QGIS's normal behaviour.
7. **The camera** frames the scene grid on open and whenever the scene grid changes, never on other refreshes:
   - it looks at the grid's centre, at the middle of its surfaces' and picks' depth range;
   - from a distance of 1.2 × the grid's longer side;
   - pitched 45°, facing north.

   **Cost if wrong:** the user re-frames by hand; QGIS has the controls.

---

### Task 1: The scene's arithmetic, and pick depths without preparing

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/scene3d_plan.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py` (a new method beside `place_picks`'s users)
- Modify: `.github/workflows/ci.yml` (mypy list)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_scene3d_plan.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py`

**Interfaces:**
- Consumes:
  - `slices_plan.DEFAULT_STRETCH` (3.0);
  - `ParaViewExport.defaults`, `source_choice` and `_zero_of`;
  - `time_base_of` and `TIME_BASE_TIME_ZERO`, and `retime_ns`, as `place_picks` imports them;
  - `session.grid_depth_velocity(grid_id)`.
- Produces, in `scene3d_plan.py`:
  - `VIEW_NAME: str = "nsgeo 3D"`;
  - `PICK_RADIUS_M: float = 0.06`;
  - `NO_GRID: str = "Add a grid first: the 3-D view shows one grid."`;
  - `BUTTON_TIP: str = "Open QGIS's 3-D view of the grid the Slices panel shows: its picks at depth and its surfaces"`;
  - `PICKS_LAYER_NAME: str = "Picks at depth (3D view)"`;
  - `def scene_stretch(record: Mapping[str, object]) -> float`: the record's `stretch` when it is a finite number above 0, else `DEFAULT_STRETCH`;
  - `def view_title(grid_name: str, stretch: float, n_stale: int) -> str`;
  - `def scene_grid(scope: str, shown: str | None, last: str | None) -> str | None`;
  - `def stretched_z(depth_m: float, stretch: float) -> float`: returns `-depth_m * stretch`;
  - `@dataclass(frozen=True) class CameraPose: x: float; y: float; z: float; distance: float; pitch: float; yaw: float`;
  - `def camera_pose(corners: Sequence[tuple[float, float]], depths: Sequence[float], stretch: float) -> CameraPose`.
- Produces, in `paraview_export.py`:
  - `def ParaViewExport.pick_depths(self, grid_id: str, rows: Sequence[tuple[str, Any]]) -> list[float | None]`: each `(line_key, pick)`'s true depth in metres, as `place_picks` gives it, or None.

- [ ] **Step 1: Write the failing pure tests** in `test_pure_scene3d_plan.py`:

```python
def test_view_title_states_grid_stretch_and_stale_count():
    assert view_title("Grid 1", 3.0, 0) == "nsgeo 3D  ·  Grid 1  ·  depth stretched ×3"
    assert view_title("Grid 1", 2.5, 1) == (
        "nsgeo 3D  ·  Grid 1  ·  depth stretched ×2.5  ·  1 surface stale"
    )
    assert view_title("Grid 1", 3.0, 2).endswith("  ·  2 surfaces stale")

def test_scene_grid_follows_this_grid_and_keeps_the_last_in_whole_site():
    assert scene_grid("grid", "Grid 2", "Grid 1") == "Grid 2"
    assert scene_grid("site", "Grid 2", "Grid 1") == "Grid 1"
    assert scene_grid("site", "Grid 2", None) == "Grid 2"
    assert scene_grid("grid", None, None) is None

def test_scene_stretch_is_the_grids_own_or_the_default():
    assert scene_stretch({"stretch": 2.0}) == 2.0
    for bad in ({}, {"stretch": 0.0}, {"stretch": float("nan")}, {"stretch": "x"}):
        assert scene_stretch(bad) == DEFAULT_STRETCH

def test_camera_frames_the_grid_at_mid_depth():
    pose = camera_pose([(0, 0), (20, 0), (20, 16), (0, 16)], [1.0, 3.0], 3.0)
    assert (pose.x, pose.y) == (10.0, 8.0)
    assert pose.z == pytest.approx(-2.0 * 3.0)
    assert pose.distance == pytest.approx(1.2 * 20.0)
    assert (pose.pitch, pose.yaw) == (45.0, 0.0)
    assert camera_pose([(0, 0), (2, 0), (2, 2), (0, 2)], [], 3.0).z == 0.0
```

- [ ] **Step 2: Run them; they fail** (`ModuleNotFoundError: nsgeo_qgis.scene3d_plan`).

- [ ] **Step 3: Implement `scene3d_plan.py`** to the signatures above.
  - The numbers in titles are formatted with `:g`.
  - `camera_pose` takes the centre of the corners and the mean of the shallowest and deepest of `depths` (0 when there are none), then applies `stretched_z`.

- [ ] **Step 4: Write the failing QGIS tests** in `test_plugin_paraview_export.py`, beside the real-data `site` fixture's tests. Copy `_pick` from `test_plugin_surface_build.py` (`_noop` is already in this file), and import `place_picks`.

```python
@needs_real_data
@pytest.mark.parametrize("steps", [STEPS_ZERO, STEPS_RADAR], ids=["time_zero", "radar_clock"])
def test_pick_depths_match_place_picks_without_preparing(site, steps, monkeypatch):
    session, _, export = site
    session.site.presets["p"] = list(steps)
    key = session.keys()[1]
    rows = [(key, _pick(key, 30, 12.0)), (key, _pick(key, 30, 9.0, zero_ns=3.0))]
    got = export.fill(GRID, export.defaults(GRID), progress=_noop)
    want = [p.depth_m for p in place_picks(rows, got.lines, got.prov, got.frame, got.velocity)]
    del got
    fresh = ParaViewExport(session, site[1])
    monkeypatch.setattr(fresh, "_prepared", lambda *a, **k: pytest.fail("prepared a line"))
    assert fresh.pick_depths(GRID, rows) == pytest.approx(want)

def test_pick_depths_are_none_where_they_cannot_be_found(synth_site):
    session, _, export = synth_site
    key = session.keys()[0]
    rows = [("raw/none.DZT", _pick(key, 5, 10.0)), ("cut:abc", _pick(key, 5, 10.0)),
            (key, _pick(key, 5, float("nan")))]
    assert export.pick_depths(GRID, rows) == [None, None, None]
```

  The real-data test pins "real files first" (spec §9). The synthetic test runs on CI.

- [ ] **Step 5: Run them; they fail** (`AttributeError: ... 'pick_depths'`).

- [ ] **Step 6: Implement `ParaViewExport.pick_depths`.**
  - Take the source with `self.source_choice(grid_id, self.defaults(grid_id))`.
  - Set `on_zero = time_base_of(steps) == TIME_BASE_TIME_ZERO`.
  - For each line pick whose key is in `source.line_keys`:
    - `target = self._zero_of(key, steps)` when `on_zero`, else 0.0;
    - `t = retime_ns(p.time_ns, p.zero_ns or 0.0, target)`.
  - Then `session.grid_depth_velocity(grid_id).depth_at(...)` over all of them in one call.
  - Return None for:
    - a cut key;
    - a key outside the source;
    - a non-finite time or depth;
    - a `_zero_of` that raises (log it once).
  - When the grid has no lines, `defaults` raises `ValueError`; return all None.

- [ ] **Step 7: Run both test files and pass.** Add `scene3d_plan.py` to the mypy list in `ci.yml` and in your local mypy command, then run the lint commands.

- [ ] **Step 8: Commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/scene3d_plan.py packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py .github/workflows/ci.yml packages/nsgeo-qgis/tests/pure/test_pure_scene3d_plan.py packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py
git commit -m "feat(3d): the 3-D view's title, scene grid, stretch and camera; pick depths without preparing (M16 C)"
git push origin nsgeo-m16-c
```

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
        sorted(-d * 3.0 for d in depths))
    settings = iface.canvases3d[VIEW_NAME].mapSettings()
    assert settings.terrainRenderingEnabled() is False
    assert iface.dialogs3d[VIEW_NAME].windowTitle() == view_title(GRID, 3.0, 0)
    assert len(iface.canvases3d[VIEW_NAME].cameraController().poses) == 1

def test_opening_again_reuses_the_view_and_brings_it_forward(scene): ...
    # one canvas created in all; the dialog is raised (isActiveWindow or a recorded raise_)

def test_a_view_closed_by_hand_cleans_up_and_opens_again(scene): ...
    # iface.closeMapCanvas3D(VIEW_NAME) -> picks layer gone from the project, no surface
    # layer has a renderer3D, is_open() False; open() makes a second canvas

def test_a_new_pick_and_a_rebuild_show_without_reopening(scene): ...
    # write a pick on the grid -> picks_changed -> spin_until a point more; rebuild a surface
    # -> its new layer has the renderer (via add_listener)

def test_the_stretch_restretches_picks_and_surfaces(scene): ...
    # session.remember_volume(GRID, stretch=2.0) -> Z values * 2/3, vertical-scale 2, title ×2

def test_the_scene_follows_this_grid_and_keeps_its_grid_in_whole_site(scene): ...
    # combo to grid B in "grid" scope -> renderers move to B's surfaces, camera framed again;
    # scope "site" then combo to A -> scene stays on B

def test_a_stale_surface_is_counted_in_the_title(scene): ...
    # change a surface's settings -> title ends "1 surface stale"

def test_an_empty_grid_opens_an_empty_scene_with_its_title(scene): ...
    # a grid with no picks and no surfaces: picks layer empty, title set, no error

def test_a_picks_layer_removed_by_hand_comes_back(scene): ...
    # project.removeMapLayer(picks layer id) then refresh -> a new picks layer, no raise

def test_a_cleared_project_forgets_the_scene_layers(scene): ...
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

### Task 3: The 3D view button, the Slices panel's grid, and the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`, which gains a `scope_changed` signal
- Modify: `docs/guide/getting-started.md`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_scene3d.py` (plugin-level tests) and `packages/nsgeo-qgis/tests/qgis/test_plugin_panels_menu.py` (the toolbar)

**Interfaces:**
- Consumes: `Scene3D` (Task 2).
- Produces:
  - `SlicesDock.scope_changed = pyqtSignal(str)`, emitted by `set_scope` only when the scope actually changes, with the new scope;
  - `NsgeoPlugin.act_view3d`, labelled "3D view";
  - `NsgeoPlugin.scene3d`;
  - `NsgeoPlugin.open_view3d(self) -> None`.

- [ ] **Step 1: Write the failing tests**, using the `surface_plugin` fixture with a `FakeIface` that has the fake canvas.

```python
def test_the_3d_view_button_greys_until_a_site_opens(fake_iface): ...
    # plugin.initGui() -> act_view3d disabled; after new_site -> enabled; after close -> disabled

def test_the_3d_view_button_opens_the_scene_of_the_slices_panels_grid(surface_plugin): ...
    # plugin.open_view3d() -> plugin.scene3d.is_open() and grid_id == the dock's grid

def test_a_scope_change_reaches_the_scene(surface_plugin): ...
    # slices_dock.set_scope("site") emits scope_changed("site") once; a second set_scope("site")
    # emits nothing

def test_closing_the_site_closes_the_view(surface_plugin): ...
    # open, then plugin.session.close_site() -> view closed, picks layer gone, no surface
    # layer keeps a renderer3D

def test_unload_closes_the_view(surface_plugin): ...
```

- [ ] **Step 2: Run them; they fail.**

- [ ] **Step 3: Implement.**
  - **The action.** `act_view3d = self._toolbar_action("3D view", self.open_view3d)` goes right after `act_surface`. Its tooltip is `scene3d_plan.BUTTON_TIP`. Add it to `_update_enabled`'s tuple.
  - **Building `scene3d`.** Construct it after `slices_dock` exists, with `export_for=self._surface_export`.
  - **`open_view3d`** calls `scene3d.open()` and turns `ValueError` and `RuntimeError` into a message-bar warning.
  - **Wiring:**
    - `session.site_closed` connects to `scene3d.close`;
    - `slices_dock.scope_changed` and `slices_dock.grid_combo.currentTextChanged` connect to `scene3d.request_refresh`;
    - `unload` calls `scene3d.dispose()` before the docks go.
  - **The signal.** Emit `scope_changed` at the end of `set_scope`'s real-change path.

- [ ] **Step 4: Write the guide.**
  - Add a toolbar row after **Surface from picks…**: "**3D view** | Opens QGIS's 3-D view of the grid the Slices panel shows: its picks at their depths and its surfaces, with depth stretched (see [The 3D view](#the-3d-view))."
  - Add **3D view** to the greyed-until-a-site-is-open sentence.
  - Add an unnumbered `### The 3D view` section after "Making a surface from picks", saying:
    - which grid it shows, and that in Whole site it keeps its last grid;
    - the stretch, where it comes from (the grid's ParaView export setting, ×3 by default), and that the title states it;
    - that it follows new picks and rebuilt surfaces, and that stale surfaces are labelled in the Layers panel and counted in the title;
    - that it shows no slices or walls, which ParaView does better;
    - that rotating, zooming and **Save as image** are QGIS's own;
    - that the "Picks at depth (3D view)" layer is temporary and goes when the view closes.

- [ ] **Step 5: Run `test_plugin_scene3d.py`, `test_plugin_panels_menu.py` and `test_plugin_slices_dock.py`, then the whole QGIS tier once, and the lint commands.** All pass.

- [ ] **Step 6: Commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/plugin.py packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py docs/guide/getting-started.md packages/nsgeo-qgis/tests/qgis/test_plugin_scene3d.py packages/nsgeo-qgis/tests/qgis/test_plugin_panels_menu.py
git commit -m "feat(3d): the 3D view button follows the Slices panel's grid; guide (M16 C)"
git push origin nsgeo-m16-c
```

## After Task 3: the walkthrough (human gate)

Deploy to a fresh profile, `ns_geo_m16c`, copied from `ns_geo` with the plugin linked to this worktree. Use a copy of the Sunnyside site that holds the Plan B walkthrough's surfaces. Write the walkthrough as an Artifact with a results database, as for Plans A and B.

1. **The button.** It is greyed with no site. Open the site, and it is enabled.
2. **Open on Grid 1.** You see the picks as spheres on the bowl surface and Feature1, and the title says "depth stretched ×3". Rotate, zoom, and use **Save as image**.
3. **Live updates.** Add a pick on a Grid 1 line, and it appears. Rebuild a surface, and it is replaced in place. Change a surface's join, and the title counts it as stale.
4. **The stretch.** Export Grid 1 for ParaView at ×2. The view flattens to ×2 and its title says so.
5. **The scene grid.** Switch the Slices panel to another grid in This grid, and the scene moves. In Whole site it stays.
6. **Closing.** Close the view with its own close button, and the "Picks at depth" layer goes. Reopen it. Close the site with the view open, and it closes.
7. **Speed.** Note how long opening takes. Build up to ten surfaces on Grid 1, or as many as the picks allow, and check the view still turns smoothly (spec §6).
