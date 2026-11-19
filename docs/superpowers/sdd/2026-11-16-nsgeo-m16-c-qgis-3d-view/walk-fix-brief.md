# Walkthrough fix round — M16 Plan C (the QGIS 3-D view)

Branch `nsgeo-m16-c`, worktree `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m16-c`, head 47de12d. The author's walkthrough (2026-11-17) found two crashes and asked for two changes. Do all four, each with a test that fails without it.

## 1. Crash: deleting a layer that has a 3-D renderer while the 3-D view is open (walkthrough L2 and C2)

**What happened:**
- **L2:** with the view open, Rebuild of a surface made QGIS hang, then crash, twice.
- **C2:** opening another site with the view open crashed QGIS.

**The evidence:**
- **The L2 core dump.** The main thread died with SIGSEGV in `QObject::disconnectImpl`, called from:
  - `Qgs3DMapScene::removeLayerEntity(QgsMapLayer*)`, from
  - `Qgs3DMapScene::onLayersChanged`, from
  - `Qgs3DMapSettings::setLayers`, from
  - `Qgs3DMapCanvasWidget::onMainCanvasLayersChanged`, from
  - `QgsLayerTreeMapCanvasBridge::setCanvasLayers` (a posted event).

  The scene keeps a raw pointer to each layer that has a 3-D entity. When such a layer is **deleted** while the view is open, the next layer update of the view touches the dangling pointer.
- **A rebuild deletes a layer.** `SurfaceLayers._put` removes the old surface layer with `project.removeMapLayer`, which deletes it.
- **Opening another site deletes layers too.** It removes the old site's surface layers and the derived "Picks at depth (3D view)" layer, which sits in the site group.

**Reproduced under xvfb (QGIS 3.44.7)** by the coordinator, with a real 3-D window, a mesh layer that has a 3-D renderer, and `removeMapLayer`:
- plain QGIS crashed 1 time in 3;
- nsgeo's flow (layers set on the view, a new layer added, the old one removed) crashed 8 times in 9.
- **With a handler on `QgsProject.layersWillBeRemoved` that calls `layer.setRenderer3D(None)` on each layer about to be removed, there were 0 crashes in 18 runs.** That covers both a single removal and `removeMapLayers` of a surface layer plus a PointZ memory layer together. No `processEvents` is needed: clearing the renderer synchronously before the deletion is enough.

**Fix (coordinator ruling R15):**
- `Scene3D` connects `project.layersWillBeRemoved` (the list-of-ids signal) in `__init__`, and disconnects it in `dispose`.
- For each id that is one of the layers Scene3D manages, and that still has a 3-D renderer, the handler calls `setRenderer3D(None)` synchronously. The managed layers are the derived picks layer and the surface layers it gives renderers (`SurfaceLayers.layers_by_feature()`).
- The handler leaves other layers alone, because a layer *taken* from the project rather than deleted must keep its renderer.
- The handler is a guarded slot that logs through `_log`.

**Tests**, in `packages/nsgeo-qgis/tests/qgis/test_plugin_scene3d.py`:
- **A surface layer about to be removed:**
  - open the view with a built surface;
  - connect a recorder to that layer's `renderer3DChanged`, noting `project.mapLayer(layer_id) is not None` and `layer.renderer3D() is None` at that moment;
  - remove the layer: rebuild the surface, or `project.removeMapLayer(id)`;
  - assert the renderer was cleared while the layer was still in the project.
- **The same for the derived picks layer** when the site closes with the view open.
- **A layer nsgeo doesn't manage** keeps its renderer when it is removed.

The real-window check is the coordinator's job, under xvfb, after you report. You can't open a real 3-D window in a test: never call `iface.createNewMapCanvas3D`.

## 2. The 3-D view's depth stretch moves to the Surfaces panel (author's decision: option 1)

The author found it "utterly unintuitive" that the QGIS 3-D view takes its stretch from the ParaView export. Their decision:
- a **Depth stretch** box in the Surfaces panel drives **only the QGIS 3-D view**, and is remembered per grid;
- ParaView keeps its own stretch in its export dialog, unchanged;
- each title states its own stretch.

**Storage (coordinator ruling R16):**
- **Where it lives:** a new per-grid key `view_stretch` in the site's `slice_sources[grid]`.
- **Reading it:** `SiteSession.view_stretch(grid_id) -> float` returns the stored value when it is a finite number above 0, else `DEFAULT_STRETCH` (3.0).
- **Writing it:** `SiteSession.set_view_stretch(grid_id, value: float)` validates (finite, above 0, else `ValueError`) and goes through `_update_source`. That marks the site dirty and emits `slice_sources_changed(grid_id)`, as other per-grid settings do. A changed stretch is a user setting saved with the site; opening, refreshing or closing the view still never marks the site dirty.
- **The project file:** `nsgeo-core/src/nsgeo/project.py` cleans each `slice_sources` entry (`_clean_slice_source`). Keep `view_stretch` when it is a number, and drop it otherwise, as for other keys.
- **Tests:**
  - core: a round trip keeps `view_stretch`, and a bad value is dropped;
  - session: the default, set, `ValueError`, dirty, and the signal.

**`Scene3D`** reads the stretch from `session.view_stretch(grid)`, not from `session.volume_record(grid)`.
- The picks' Z, the surfaces' vertical scale and the title all follow it.
- `remember_volume`, the ParaView export's setting, no longer moves the view. Test: the export's stretch changes and the view stays the same.
- Changing `set_view_stretch` re-stretches the view. Adapt the existing stretch test, which currently uses `remember_volume`.

**The Surfaces panel (coordinator ruling R17).** The box sits in the panel's top grid, on the row below **Grid**:
- Its label: `3D view depth stretch ×`. Wording lives in `scene3d_plan.py` or `surface_plan.py`, not the widget.
- It is a `QDoubleSpinBox`: range 0.1 to 50, step 0.5, 1 decimal.
- It takes the wheel only while focused. Reuse the focus-only spin class in `ui/surface_settings_form.py`.
- **It edits the stretch of the grid chosen in the panel's own Grid filter.** With "All grids" chosen, it is disabled, with the tooltip "Choose a grid to set its 3D view depth stretch."
- **Choosing a grid** in the filter shows that grid's `view_stretch`.
- **Committing a value** (editingFinished or valueChanged with keyboard tracking off, as the other settings do) calls `session.set_view_stretch`.
- **Loading a value never writes.** Use the panel's existing `_loading` guard.

**Panel tests:**
- the box is disabled for All grids, and enabled showing 3.0 for a grid;
- setting 2.0 stores `view_stretch` 2.0 for that grid only;
- switching the filter shows each grid's own value;
- loading never marks the site dirty.

**The guide.** In `docs/guide/getting-started.md`, "The 3D view": the stretch bullet now says it is set in the Surfaces panel (**3D view depth stretch**, per grid, ×3 by default), that the ParaView export has its own, and that each title states its stretch. Remove the sentence saying the view follows the export dialog.

## 3. The slice layer no longer triggers QGIS's "temporary scratch layers" warning (author's request)

- **The cause:** `slice_layer.py` (`_create_layer`, about line 553) makes the Slices panel's raster layer from a file in a `tempfile.mkdtemp` folder. QGIS's `QgsMapLayer::isTemporary()` counts temp-folder layers, so quitting QGIS or starting a new or opened project warns that "temporary scratch layers" will be lost. That warning has been there since Slices first appeared.
- **Fix:** `layer.setCustomProperty("skipMemoryLayersCheck", 1)` on that layer, with a one-line comment, as `scene3d.py` already does for the derived picks layer.
- **Test:** the slice layer carries the property. Put it in the Slices layer's existing test file.

## Rules

- **Never** use `git stash`; it is shared with other sessions. Never call the real `createNewMapCanvas3D`, and never stage `.superpowers/`.
- **Slots and wording:** guarded slots, and wording in the pure plan modules.
- **Commits:** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, and push to `origin nsgeo-m16-c`.
- **Running tests:** use `PYTHONDONTWRITEBYTECODE=1`, from the worktree root:
  - pure: `PYTHONPATH=packages/nsgeo-core/src /home/jameszd/Documents/Github/archaeo_geophysics/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`;
  - QGIS: the same, with `QT_QPA_PLATFORM=offscreen` and `.venv-qgis/bin/python`.
- **Lint:** `ruff check .`, `ruff format --check .`, and mypy as in `.github/workflows/ci.yml`.
- **What to run:**
  - while iterating, the files you touch;
  - at the end, the core and pure suites;
  - then the whole QGIS tier once, in the foreground (about 37 minutes).
