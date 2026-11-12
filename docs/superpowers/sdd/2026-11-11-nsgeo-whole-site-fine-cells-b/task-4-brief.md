### Task 4: The export dialog (option B)

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/export_dialog.py`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`, adding the summary text helpers.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_export_dialog.py` (new; driven with
  `drive_dialog`).

**Interfaces:**
- Produces:
  - `class ExportDialog(QDialog)`, modal and opened with `exec()`, with fields:
    - **Save to:** a path field plus a "…" button opening `QFileDialog.getSaveFileName`;
    - **Export cell:** a spin box with three decimals, floored at the largest included grid's
      `smallest_safe_cell` (decision A), defaulting to the live cell;
    - **Export pixel:** a spin box, defaulting to and never above the export cell.
  - A read-only **What will be written** group, recomputed when either spin box changes (debounced
    150 ms):
    - Bands, Picture, Grids (site only), Slices, Normalisation (site only), File and Disk, as in
      the mock-up;
    - Disk is `shutil.disk_usage` of the target's directory.
  - **Export is disabled** with the reason in the group when either:
    - the estimate is over `EXPORT_BUDGET_BYTES` (`export_refusal` copy);
    - or free space is under 1.2 × the file estimate:
      `f"Not enough free disk space: about {need} needed, {free} free."`
  - `result_settings() -> ExportChoice(path, cell, pixel)`.
  - `targets_in_use(project, paths) -> list[QgsMapLayer]`. On Export, when any target, its `.qml`
    or its coverage companion is a project layer, ask (decision 17):
    `"<name> is open in this project. Replace it? The layer is removed and added again when the export finishes."`
    with Replace and Cancel. Use an in-dialog confirmation strip, not a nested modal.
- `summary_lines(spec_preview) -> list[tuple[str, str]]` in `slices_plan.py` holds the summary text,
  so it can be tested in the pure tier.

- [ ] **Step 1: Write the failing tests.**
  - Defaults: the cell and pixel are the live cell.
  - The pixel spin's maximum follows the cell.
  - The cell floor is the largest included grid's safe cell.
  - The summary text is exact for a two-grid site.
  - The site rows are absent in This grid.
  - Over budget: Export is disabled and the exact copy shows the finest fit.
  - Low disk (monkeypatch `disk_usage`): disabled with the exact copy.
  - A target open as a layer: the confirmation strip appears, and Replace accepts while Cancel
    stays.
  - The debounce: rapid spin changes compute the estimate once.
  - The dialog never widens past the QGIS minimum, matching the panel's width rule.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement**, following `VelocityDialog`'s modal pattern (`plugin.py:1951`, with
  `deleteLater` in a `finally`).
- [ ] **Step 4: Run** and lint.
- [ ] **Step 5: Commit:** `feat(export): the export dialog, with a summary, a memory check and a disk check`.

---

