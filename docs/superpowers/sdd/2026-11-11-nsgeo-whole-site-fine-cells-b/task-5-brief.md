### Task 5: Wiring both exports through the dialog and the task

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
  - `export_geotiff` (~919-1041) and `export_site_geotiff` (~1114-1226) build the dialog, then the
    snapshot, then the task;
  - `_export_progress`, `_bands_are_slow` and `_remove_partial` are removed.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py` and `slice_export.py`:
  - planning helpers take the export cell and pixel;
  - snapshot builders `site_export_spec(...)` and `grid_export_spec(...)` run on the GUI thread and
    read the engines and the session once.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`: the preview note's tooltip drops the
    export refusal (spec §5.3, walkthrough D2), and `export_refusal` no longer blocks
    the button.
- Test: `test_plugin_slice_export_dialogs.py`, `test_plugin_site_scope.py`,
  `test_plugin_slice_export.py` and `test_plugin_site_export.py`. Rewrite the tests that pin the
  GUI-thread export:
  - WindowModal progress (~668-681);
  - cancel through `processEvents` (~707-754);
  - the wait cursor (~806);
  - the refine-paused path (~628);
  - `_remove_partial`'s mtime rule (~506-525).

  Each becomes the task-based behaviour.

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: on success the plugin:
  1. adds the layer and its coverage companion through `_add_exported_layer`;
  2. applies `write_style` with the measured limit, the panel's colormap and unipolar;
  3. applies the temporal properties;
  4. shows `f"exported {n} bands to {path} ({cell:g} m cell, {pixel:g} m pixels)"`.

  On a replaced target, the old layer is removed before the task starts and the new one is added
  after. A cancelled export shows `"export cancelled"`, and a failed one gives its plain error at
  Critical.

- [ ] **Step 1: Write the failing tests.**
  - A site export at a finer cell (0.25 → 0.125 on site3): the file's metadata names the export
    cell and pixel, and its bands differ from a live-cell export where the data does.
  - The live view stays usable during the export: a slice tick runs while the task is held.
  - A preview site (lowered `max_covered`) now exports at full detail.
  - This grid at a finer pixel: the file is twice the width and the height.
  - Cancel from the task list: no file, no layer.
  - Closing the site during an export cancels it: `site_closed` cancels the held task, and no
    layer is added.
  - The coverage companion is written and styled.
  - A replaced target: the layer is removed, then added again.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the five files above, `test_plugin_site_engine.py`, and the full QGIS tier
  once, plus lint.
- [ ] **Step 5: Commit:** `feat(export): both exports through the dialog and the background task`.

---

