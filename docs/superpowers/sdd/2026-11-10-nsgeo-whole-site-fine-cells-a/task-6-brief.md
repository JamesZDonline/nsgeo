### Task 6: Drawn smooth, plus the docs

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py`. Add `apply_smooth_resampling(layer:
  QgsRasterLayer) -> None` and call it from `_apply_renderer` (~394), so it is re-applied after
  every repoint.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: `_add_exported_layer` (~1765) calls it, so it
  covers both exports and their coverage companions.
- Modify: `docs/guide/` wherever Slices or Whole site drawing is described (grep "Whole site",
  "Cell"). Add one short paragraph: pictures blend the cells around each pixel and are drawn
  smooth; past a size, Whole site draws a preview and says so.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/metadata.txt` changelog, under the next release, if that
  is where earlier changes were noted. Check the file first.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py` and an export test file.

**Interfaces:**
- Produces: `apply_smooth_resampling(layer)`, which sets the zoomed-in resampler to
  `QgsBilinearRasterResampler()` on `layer.resampleFilter()` and leaves zoomed-out as QGIS has it.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_slice_layer_is_drawn_smooth_after_every_repoint`: two `update` calls, then
    `layer.resampleFilter().zoomedInResampler().type() == "bilinear"`.
  - The same assertion for the site layer (`update_north_up`), and for an exported layer added
    through `_add_exported_layer`.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement**, then update the guide and changelog.
- [ ] **Step 4: Run the whole QGIS tier and the core tier once**, plus lint. All pass, apart from
  known skips and the Qt 6 dock-width xfail (#50).
- [ ] **Step 5: Commit**: `feat(slices): draw slice layers smooth when zoomed in; guide`.

---

## After the tasks (coordinator)

- **Review.** A whole-branch review (opus), then the fix wave.
- **Build and walkthrough before merge.** Deploy to a new QGIS profile and walk through spec §8.1
  on the real walkthrough site:
  - all ten grids at 0.05 m draw live;
  - zoomed in, edges are smooth;
  - a forced preview note is readable;
  - a refusal reads plainly;
  - This grid matches.

  This is a human gate: track it and report it, never pass it silently.
- **README roadmap**, in the PR: "Whole site at fine cells" moves to milestone A done (next release),
  and B stays in progress.
