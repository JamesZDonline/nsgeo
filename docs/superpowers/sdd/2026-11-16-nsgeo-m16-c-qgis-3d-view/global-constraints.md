# Global constraints for M16 Plan C (copied verbatim from the plan)

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

