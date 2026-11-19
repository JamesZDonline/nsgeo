# M16 Plan C — final review findings to fix (one fix wave)

Branch nsgeo-m16-c, worktree /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m16-c, reviewed range b27b61a..7e97a4a. The reviewer verified QGIS behaviour by disassembling libqgis_3d/core/gui/app for 3.44.7 and 3.40.3 (both in /usr/lib) and with a scratch probe test. Fix every item below in one pass, with tests that can fail.

## Critical

**C1. Picks never update in a real 3-D window after it opens.** `scene3d.py:316-320` (`_fill_picks`) rewrites the picks layer through `dataProvider().truncate()/addFeatures()` and then calls `triggerRepaint()`.
- In 3.44.7, `Qgs3DMapScene::addLayerEntity` connects only to these signals: `request3DUpdate`, `renderer3DChanged`, `layerModified`, `rendererChanged`, `selectionChanged` and `subsetStringChanged`.
- `triggerRepaint` emits `repaintRequested`, which the scene ignores. `onLayersChanged` only adds and removes layers by difference, so the existing picks entity is kept.
- The probe showed 0 emissions of `request3DUpdate`, `layerModified` and `renderer3DChanged`, against 3 of `repaintRequested`, over a stretch change, a new pick and a grid switch.
- **What the user sees:**
  - a new pick does not appear;
  - after a stretch change the picks float off the re-stretched surfaces;
  - after a grid switch, grid A's spheres stay on screen with grid B's surfaces.
- **Fix:** call `layer.trigger3DUpdate()` after a rewrite (it exists in 3.40+). Ruling R13: rewrite and update only when the layer's (x, y, z) list actually changed, because refresh runs on many signals and an unconditional rebuild would flicker.
- **Test:** count the picks layer's `request3DUpdate` emissions after each of:
  - a new pick;
  - a stretch change;
  - a grid switch.

  Each must emit. A refresh with nothing changed must not.

## Important

**I1. The view is wrong when the QGIS project's CRS differs from the grid's.** `scene3d.py:349-353` (`_frame`).
- `Qgs3DMapSettings::setCrs` only assigns the CRS. Neither 3.40 nor 3.44 has a crs-changed signal, and the scene does not react.
- `createNewMapCanvas3D` builds the scene in the project CRS, so the surface layers' existing entities are built in that CRS.
- nsgeo then sets the CRS, origin and camera in the grid's CRS. The picks layer joins later through the 0 ms re-set, so it is built in the grid's CRS.
- With the project in EPSG:3857 (for example a satellite basemap loaded first), the surfaces are misplaced or missing and don't line up with the picks.
- **Fix (ruling R12):** after every frame, rebuild the view's layers on the 0 ms layers timer: `setLayers([])` then `setLayers(<checked layers>)`, so every entity is rebuilt in the view's CRS and origin. "Every frame" means open, a grid change, and a grid geometry change (M7).
- **Test:** watch the view settings' `layersChanged` signal (or an equivalent the fake can observe). After a frame, the layers go to empty and back to the full set.

**I2. On QGIS 3.40 (`metadata.txt`'s `qgisMinimumVersion`), the button always fails and leaves an orphan window.**
- `QgsCameraController::setLookingAtMapPoint` does not exist in 3.40.3. Only `setLookingAtPoint` exists, and it takes world coordinates.
- 3.40 also lacks `originChanged`.
- So `_frame` raises `AttributeError` after the canvas exists. `open()` tears down, but never closes the real view, and the user is left with an empty window plus a message.
- **Fix (ruling R11):**
  - when the camera controller has no `setLookingAtMapPoint`, frame with `cameraController().resetView(distance)` (top-down, no tilt);
  - origin moves are covered by I1's rebuild;
  - in `open()`'s failure branch, also close the real view: `iface.closeMapCanvas3D(VIEW_NAME)` when a canvas was created. This is the ledger's T2 "orphan view on failed open" item.
- **Tests:**
  - a fake camera controller without `setLookingAtMapPoint` makes open() use `resetView(distance)`, and the open succeeds;
  - a failure in `_frame` after the canvas exists leaves no open canvas (`iface.canvases3d` empty), no picks layer, and no surface renderer.

**I3. The title loses the stretch when the user docks or undocks the view.**
- `QgsDockableWidgetHelper::setWindowTitle` stores its own title, and `toggleDockMode` applies that stored title to the new dock or dialog. The stored title is the creation name, "nsgeo 3D", because nsgeo retitles the holder widget directly.
- So after a dock toggle the title reads "nsgeo 3D", with no stretch, until some unrelated refresh. That hits the anti-goal "stretched depth shown without saying so".
- The fake's `swap_holder3d` carries the *current* title across, which contradicts QGIS.
- **Fix:**
  - connect each holder you find (dialog or dock) `destroyed` → `request_refresh`, so a toggle re-titles straight away;
  - make the fake's swap re-apply the ORIGINAL name, as QGIS does;
  - test that after a swap the new holder gets the full title without any other refresh trigger.

**I4. QGIS warns that data will be lost while the view is open.**
- "Picks at depth (3D view)" is a memory layer. While it holds features, QGIS's exit, File > New, File > Open and File > Close all run `checkMemoryLayers` and ask: "This project includes one or more temporary scratch layers… their contents will be permanently lost." A user will read that as their picks being lost.
- **Fix:** `layer.setCustomProperty("skipMemoryLayersCheck", 1)`, a property QGIS 3.44.7 reads.
- **Test:** the picks layer carries it.

## Minor (fix in this wave)

- **M1. In Whole site, removing the scene grid breaks the view.** Every refresh raises `KeyError` from `defaults` → `session.grid`, and the view keeps the removed grid's title and picks. Fix: `scene_grid` (pure, in scene3d_plan) falls back to the panel's grid when `last` no longer exists; pass it the existing grid ids. Tests: one pure, and one QGIS test removing the scene grid while in Whole site.
- **M2. `_ensure_picks_layer` fails if `picks` sits in a subgroup.** `group.findLayer` searches recursively, but `group.children().index(node)` does not, so a `picks` layer dragged into a subgroup raises `ValueError`. The layer registered by `addMapLayer(layer, False)` then leaks, because `self.picks_layer` is not set yet. Fix: insert under `node.parent()`, and set `self.picks_layer` straight after `addMapLayer`. Test: move `picks` into a subgroup, then open.
- **M3. The no-CRS fallback URI lacks `true_depth_m`.** Always declare the field, and set the CRS with `layer.setCrs`.
- **M4. The scene extent is exactly the grid's bounding box,** so picks on a line that runs past the grid edge may be culled. Add a margin in `scene3d_plan`: 10% of the longer side, at least 1 m. Pure test.
- **M5. The derived layer shows in the Identify tool beside the real picks.** Clear its Identifiable flag. Test.
- **M6. The guide's "The 3D view" section** should say that picks on cuts, and picks on lines left out of the grid's slices (Choose lines…), are not shown.
- **M7. Moving a grid (Edit grid) while the view is open** does not re-frame the origin, extent or camera. Re-frame when the scene grid's geometry (origin, azimuth, size, CRS) changed since the last frame, not only on a grid switch. Test.
- **M8. `_PICK_COLOUR` lives in `scene3d.py`.** Move it to `scene3d_plan.py` beside `PICK_RADIUS_M`.

## Also (from the ledger's triage)

- Pin the spec'd picks-layer look in a test: the 3-D symbol is a **sphere** (QGIS's default is a cylinder) and the 2-D renderer is a `QgsNullSymbolRenderer`.
- When the mesh 3-D renderer metadata is None, `_apply_renderers` skips the surface silently. Log one line through `_log` instead.
