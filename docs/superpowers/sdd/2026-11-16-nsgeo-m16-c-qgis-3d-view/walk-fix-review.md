# Review: walk-fix commit d70900f (base 47de12d), M16 Plan C

Reviewer: opus, read-only. All experiments ran on copies in
`/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/7ec288b0-6c3d-4401-b51d-656c73323d21/scratchpad/review-walkfix/`
(a mirror of `packages/nsgeo-qgis/tests` plus a copy of `nsgeo_qgis`). Nothing in the worktree was changed except this file.

**Verdict: changes needed** (1 Critical, 3 Important, 4 Minor).

## Runs

- QGIS files touched (`test_plugin_scene3d.py`, `test_plugin_surfaces_dock.py`, `test_plugin_session.py`, `test_plugin_slice_layer.py`): **238 passed** (152 s).
- Core `test_project.py`: **103 passed**. Pure `test_pure_scene3d_plan.py`: **7 passed**.
- Facts checked on QGIS 3.44.7 (a standalone QgsApplication script, `review-walkfix/probe/clear_order.py`):
  - `QgsProject.clear()` emits `removeAll`, then `layersWillBeRemoved(ids)`, then `cleared`. So `Scene3D._on_layers_will_be_removed` runs **before** `_on_cleared` forgets the picks layer, and before `SurfaceLayers._on_cleared` empties `_shown`. Project clear is covered.
  - Removing a layer-tree group: `QgsLayerTreeRegistryBridge` removes its layers in a **queued** call, which emits `layersWillBeRemoved`. Covered.
  - `takeMapLayer` also emits `layersWillBeRemoved` (see the note under R15).
  - The default PyQt overload of `layersWillBeRemoved` delivers `list[str]`, which is what the handler expects.
- Mutants, run in the scratch copy only:
  - Without the handler connection, the surface, rebuild and picks tests fail (3 failed). They are real RED tests.
  - With the `dispose` disconnect removed, the dispose test fails.
  - With an over-broad handler (clearing every layer being removed), the unmanaged-layer test fails.

## Spec compliance

### Part 1: crash fix (R15)

| Item | |
|---|---|
| `layersWillBeRemoved` connected in `__init__` (scene3d.py:179), once per Scene3D | ✅ |
| Disconnected in `dispose` (scene3d.py:288-289). Calling it twice, or after the project is gone, is suppressed (`TypeError`/`RuntimeError`) | ✅ |
| Clears `setRenderer3D(None)` synchronously on managed layers that still have a renderer | ✅ as written, but **❌ the managed set misses a deleted surface** (C1) |
| Managed = picks layer + `SurfaceLayers.layers_by_feature()` | ✅ as specified. That source is the cause of C1 |
| Leaves other layers alone | ✅ (test, plus an over-broad mutant caught) |
| Guarded slot that logs through `_log` | ✅ |
| Test: a surface layer about to be removed (`removeMapLayer`) | ✅ (fails without the handler) |
| Test: rebuild clears the old layer's renderer while it is in the project | ✅ (fails without the handler) |
| Test: the derived picks layer **when the site closes** with the view open | ⚠️ present, but it calls `removeMapLayer` directly and never closes the site (M1) |
| Test: an unmanaged layer keeps its renderer | ✅ |
| (extra) Test: no handler after `dispose` | ✅ |

### Part 2: storage and the view (R16)

| Item | |
|---|---|
| Per-grid key `view_stretch` in `slice_sources[grid]` | ✅ |
| `SiteSession.view_stretch` returns the stored value when finite and >0, else 3.0. bool, NaN, inf and str fall back through `scene_stretch` | ✅ |
| `set_view_stretch` validates (`ValueError`), goes through `_update_source`, marks dirty, emits `slice_sources_changed(grid)` | ✅ (a str raises `TypeError`, not `ValueError`: M4) |
| `project.py _clean_slice_source` keeps a number and drops anything else | ✅ (it also keeps a finite value ≤0: M3) |
| Core test: round trip, and a bad value dropped (str, bool) | ✅ |
| Session tests: default, set, ValueError (0, −1, NaN, inf), dirty, signal, and `volume_record` left alone | ✅ |
| `Scene3D._stretch` reads `session.view_stretch` (scene3d.py:300-301). Picks Z, vertical scale and title follow it | ✅ |
| `remember_volume` no longer moves the view; its test would fail on the old code | ✅ |
| `set_view_stretch` re-stretches the view (`slice_sources_changed` → `request_refresh`); existing tests adapted | ✅ |
| Opening, refreshing or closing the view never marks the site dirty | ✅ (Scene3D writes nothing) |

### Part 2: the Surfaces panel box (R17)

| Item | |
|---|---|
| Row below **Grid** in the top grid; label `3D view depth stretch ×` from `scene3d_plan.py` | ✅ |
| `QDoubleSpinBox` 0.1–50, step 0.5, 1 decimal | ✅ |
| Wheel only while focused: reuses `SteadySpinBox`, which also turns keyboard tracking off | ✅ |
| Edits the filter's grid. Disabled for All grids, with the tooltip "Choose a grid to set its 3D view depth stretch." | ✅ |
| Choosing a grid shows that grid's `view_stretch` | ✅ |
| Committing (`valueChanged`, keyboard tracking off) calls `set_view_stretch` inside `_guarded` | ✅ |
| Loading never writes (`_loading`) | ✅ in the code (a scratch probe confirms). **❌ its test cannot fail** (I2) |
| Panel tests: disabled/enabled showing 3.0; 2.0 stored for that grid only; switching shows each grid's own | ✅ |
| Panel test: loading never marks dirty | ⚠️ it dodges the hazard (I2) |
| Guide: bullet rewritten, the export-follows sentence removed | ✅ (one inaccuracy: I3) |

### Part 3: the slice layer's scratch warning

| Item | |
|---|---|
| `setCustomProperty("skipMemoryLayersCheck", 1)` with a one-line comment (slice_layer.py:555) | ✅ as specified, but **❌ it does not stop the warning** (I1) |
| Test in the Slices layer's test file | ✅ present. It pins the property, not the outcome (I1) |

## Critical

### C1. Deleting a surface while the 3-D view is open still deletes its layer with the mesh renderer on, which is the L2 crash class

- **Where:**
  - `packages/nsgeo-qgis/nsgeo_qgis/surface_layers.py:354-356`, together with
  - `packages/nsgeo-qgis/nsgeo_qgis/scene3d.py:500-508`.
- **What goes wrong:** In `SurfaceLayers._sync`, a surface that is no longer wanted is dropped with:

  ```python
  for fid in list(self._shown):
      if fid not in wanted:
          self._drop_layer(self._shown.pop(fid).layer_id)
  ```

  The argument is evaluated first, so the `_shown` entry is **popped before** `removeMapLayer` runs. When `layersWillBeRemoved` reaches Scene3D, the layer is no longer in `surface_layers.layers_by_feature()`. The handler skips it, and QGIS deletes the layer with its 3-D renderer still set. That is the mechanism the brief verified as the crash.
- **Scenario:**
  1. The view is open on Grid A.
  2. Surfaces panel → select Grid A's surface → **Delete…**.
  3. `Surfaces.delete` emits `features_changed`, and `SurfaceLayers` syncs.
  4. The fid is not in `wanted`, so pop, then drop.
  5. The layer is deleted with its renderer on.
  6. The next view layer update (the layer tree changed → `setCanvasLayers` → `Qgs3DMapScene::onLayersChanged`) touches the dangling pointer.

  Any other way a built surface leaves `wanted` takes the same path, for example a build that no longer has any cells.
- **Evidence:** a scratch test (`test_review_deleting_a_surface_with_the_view_open_clears_its_renderer_first`, in the mirror's `test_plugin_scene3d.py`) has a slot connected to `layersWillBeRemoved` **after** Scene3D's. At removal it saw `renderer3D() is None == False`, and the `renderer3DChanged` recorder stayed empty.
  - Not reproduced in a real 3-D window: that is the coordinator's xvfb check. The coordinator's e2e run (rebuild, stretch, open another site, close) did not delete a surface, which is why it passed.
- **Suggested fix** (either one; both is safest):
  1. Make Scene3D independent of SurfaceLayers' bookkeeping. In `_on_layers_will_be_removed`, also treat every id in `self._applied` as managed: these are exactly the surface layers Scene3D gave a renderer to.

     ```python
     managed += [self.project.mapLayer(i) for i in self._applied if i in wanted]
     ```

     With this one line in the scratch copy, the delete probe passes and all 43 scene3d tests still pass.
  2. In `surface_layers.py:356`, drop the layer before forgetting it:

     ```python
     self._drop_layer(self._shown[fid].layer_id)
     del self._shown[fid]
     ```

  Add a test: open the view, attach the renderer recorder to Grid A's surface layer, run `surfaces.delete(fid)` then `surface_layers.sync()`, and assert `(True, True) in log`.

## Important

### I1. `skipMemoryLayersCheck` does not silence QGIS's warning for the slice layer; the fix is a no-op

- **Where:** `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py:554-555` and its test, `tests/qgis/test_plugin_slice_layer.py:868-871`.
- **Why it has no effect:** QGIS reads that property only for **memory-provider** layers. A GDAL raster in a temp folder counts through `QgsMapLayer::isTemporary()`, which compares the file path with the platform temp locations, and that check ignores the property.
- **Evidence:** real QGIS 3.44.7 under xvfb, with my own copy of an initialised profile and `--noplugins`. The script is `review-walkfix/qgisprobe/probe.py`. It makes a GeoTIFF in `tempfile.mkdtemp(prefix="nsgeo-slice-")`, adds it, and calls `iface.newProject(True)`.
  - **Without** the property: the modal says "This project includes one or more temporary layers. These layers are not permanently saved and their contents will be lost. Are you sure you want to proceed?"
  - **With** `skipMemoryLayersCheck=1`: the **same modal**, and `layer.isTemporary()` is still True.

  So walkthrough X2 ("there's always that warning because slices is a temporary layer") will still happen. The test passes because it checks that the property is set, not that QGIS stops treating the layer as temporary.
- **Suggested fix:**
  - Make the preview folder somewhere outside `QStandardPaths.TempLocation`. For example, `tempfile.mkdtemp(prefix="nsgeo-slice-", dir=<QStandardPaths.writableLocation(CacheLocation)/nsgeo>)`, keeping the existing `rmtree` cleanup at slice_layer.py:603.
    - Since a cache folder is not emptied on reboot, sweep stale `nsgeo-slice-*` folders at start.
    - Alternatively, use a `/vsimem/` path, but check that repointing still works.
  - Change the test to `assert sl.layer.isTemporary() is False`, which pins the outcome.
  - The picks memory layer's own `skipMemoryLayersCheck` (Plan C I4) is a different branch and is fine.

### I2. The "loading never marks the site dirty" test dodges its hazard

- **Where:** `tests/qgis/test_plugin_surfaces_dock.py:597-608`, which covers the guard in `ui/surfaces_dock.py:490`.
- **Why the test cannot fail:** it stores 4.0 first and then loads 4.0. Writing the loaded value back is a no-op in `_update_source` (`new == old`), so the test passes with no guard at all. The real hazard is a grid with **no** stored stretch. Loading shows 3.0, and a write-back would store `view_stretch: 3.0` and mark the site dirty just because the user chose a grid.
- **Evidence:** in the scratch copy, with `self._loading or` removed from `_save_stretch`:
  - both new dock tests still pass (2 passed);
  - a probe that chooses Grid A with nothing stored failed with `{'volume': {...}, 'view_stretch': 3.0}` and dirty True.

  On the real code the same probe passes, so the guard itself is correct.
- The brief asks for "each with a test that fails without it".
- **Suggested fix:** in the test:
  1. call `_set_dirty(False)` without storing a value;
  2. choose "Grid A";
  3. assert `"view_stretch" not in (session.slice_source("Grid A") or {})` and `not session.dirty`;
  4. then also refresh and switch away and back.

### I3. A grid with no surface cannot have its 3-D view stretch set, and the guide says otherwise

This is a gap in the spec, not in the implementation, so it is the coordinator's call.

- **Where:**
  - `ui/surfaces_dock.py:285`: `grids = sorted({r.grid_id for r in records})`, so the panel's Grid filter lists only grids that have surfaces;
  - `docs/guide/getting-started.md:848-849`.
- **Scenario:** the 3-D view opens on whichever grid the Slices panel shows and draws that grid's picks, whether or not it has a surface. On a grid with picks but no surface yet, the stretch is stuck at ×3, or at whatever was set while it had a surface. The new box can never be enabled for it.
- The guide says "choose a grid in the panel's grid list and the box turns on", which is untrue for such a grid.
- **Suggested fix:** either
  - list every site grid in the box's own scope, for example by filling the filter from `session.site.grids` (a grid with no surfaces then shows an empty table); or
  - keep R17 as ruled and say in the guide that the box appears for grids with a surface.

## Minor

### M1. The picks-layer test is named for site close but doesn't close the site

- **Where:** `tests/qgis/test_plugin_scene3d.py:231-236`.
- **What it does instead:** it removes the layer with `removeMapLayer`. The brief asked for "when the site closes with the view open". The real site-close order is not exercised by the new tests:
  1. `SiteLayers.detach` removes the group, which queues the picks removal;
  2. `SurfaceLayers._on_site_closed` removes the surfaces while `_shown` is populated;
  3. `_close_view3d` runs `_teardown`, which removes the picks layer.
- That path does work: a scratch probe through `plugin.session.close_site()` on `surface_plugin` recorded `(True, True)` for both the picks and the surface layer.
- **Suggested fix:** add the two recorders to the existing `test_closing_the_site_closes_the_view` (scene3d tests, about line 663), and rename or replace the direct-removal test.

### M2. The disabled box shows a misleading number

- **Where:** `ui/surfaces_dock.py:113-117` and `473-486`.
- **What happens:** before any grid is chosen, the disabled box reads **0.1**, because `setRange` clamps the default 0 up to the minimum (seen in the probe). After you go back to All grids, it keeps the last grid's value, greyed out.
- **Suggested fix:** `setValue(DEFAULT_STRETCH)` at construction. For All grids, use `setSpecialValueText("")` at the minimum, or leave the value alone.

### M3. Stored values the box cannot show

- **Where:** `packages/nsgeo-core/src/nsgeo/project.py:398-400` and `ui/surfaces_dock.py:484`.
- **What happens:**
  - The loader keeps a finite `view_stretch` that is ≤0. The reader falls back to 3.0, but the bad value persists through saves. By contrast, `gain` drops ≤0 at line 392.
  - A hand-edited 100 or 2.25 is used by the view (title "×100") but shown as 50.0 or 2.2 in the box. Nothing is written back, so there is no damage.
- **Suggested fix:** drop ≤0 in `_clean_slice_source`, like `gain`. Optionally, clamp `view_stretch()` to [0.1, 50] so the view and the box agree.

### M4. `set_view_stretch` with a non-number raises `TypeError`, not `ValueError`

- **Where:** `session.py:1302`.
- **What happens:** `math.isfinite("x")` raises `TypeError`. Only programmatic misuse can reach this; the dock passes floats.
- **Suggested fix:** add `not isinstance(value, (int, float))` to the refusal.

## Notes (not findings)

- **R15 and `takeMapLayer`:** `takeMapLayer` emits `layersWillBeRemoved` (verified), so a **managed** layer taken from the project would lose its renderer too. No nsgeo code takes those layers, and `_apply_renderers` puts the renderer back on the next refresh (`renderer3D() is None`). Unmanaged layers are untouched, as the brief requires.
- **QGIS's own New/Open/Exit:** these go through `QgsProject.clear()`, which emits `layersWillBeRemoved` before `cleared` (verified), so the handler sees the managed layers first. I believe `QgisApp::closeProject` also closes 3-D canvases before clearing, but **I did not verify that** (no QGIS app source is available here). The handler covers it either way.
- **No Plan C regressions found:** picks refresh, retitle, `request_refresh` wiring (`slice_sources_changed` re-stretches the view), dock-toggle retitle, and close/teardown. All Plan C tests in the four files pass. The progress file says CI on d70900f is green, including 4.2.
- **Layering:** `session.py` now imports `scene3d_plan.scene_stretch`. It is pure, so this is fine, but a session-level helper (or `slices_plan`) would be a more natural home. Cosmetic.
