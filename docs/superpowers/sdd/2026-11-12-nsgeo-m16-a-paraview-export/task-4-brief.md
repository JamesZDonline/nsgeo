### Task 4: The dialog, the Slices panel button, launching ParaView, and the guide

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/paraview_dialog.py`
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`: `paraview_button` ("ParaView…") in `button_row`, plus signal `paraview_requested = pyqtSignal()`. It is enabled whenever a site is open, in either scope.
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
    - `_PARAVIEW_KEY = "nsgeo/paraviewPath"`;
    - connect `paraview_requested` to `export_paraview`;
    - `export_paraview()` and `launch_paraview()`.
  - `docs/guide/getting-started.md`: a new step, "Export for ParaView" (spec §10).
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_dialog.py`

**Interfaces:**
- Consumes: Task 3's `ParaViewExport`, `VolumeChoice`, `export_size_bytes`, `paraview_folder`, `ParaViewExportCancelled`; `MAX_FRAME_CELLS`; `NsgeoPlugin._export_progress`, `message`.
- Produces:
  - `ParaViewExportDialog(QDialog)`, constructed with `(grid_ids, current_grid, choice_for: Callable[[str], VolumeChoice], size_for: Callable[[str, VolumeChoice], int], paraview_path: str, parent=None)`. Its methods: `grid_id() -> str`, `choice() -> VolumeChoice`, `paraview_path() -> str`, `open_after() -> bool`. It has a `size_label`, refreshed on every edit, and an Export button that is disabled with a reason in `size_label` while the frame would exceed `MAX_FRAME_CELLS`.
  - `launch_paraview(paraview: str, folder: Path) -> bool`: `QProcess.startDetached(paraview, [f"--script={folder / 'open_scene.py'}"], str(folder))`. It returns False when `paraview` is empty or not executable.

- [ ] **Step 1 (coordinator, human checkpoint): get the dialog's layout approved with a lavish mockup before any code.** The fields:
  - **Grid.**
  - **3-D cell (m) and depth step (ns),** with the note "This grid's own; the Slices panel keeps its settings".
  - **Amplitude transform.**
  - **Depth stretch.**
  - **An "Advanced" group:** wave period (ns), sideways blur (m), depth-trend window (m).
  - **The size on disk.**
  - **The ParaView program,** with Browse.
  - **Buttons:** Export, Export and open, Cancel.

  Record the user's verdict in the ledger, and apply any layout changes to this task's widget list before Step 2.

- [ ] **Step 2: Write the failing tests.**

```python
def test_the_button_opens_the_dialog_on_the_panels_grid(plugin_with_site, drive_dialog):
    # clicking paraview_button opens ParaViewExportDialog; dialog.grid_id() equals the
    # Slices panel's grid_combo text; the cell spin shows ParaViewExport.defaults(grid).cell
def test_editing_the_cell_refreshes_the_size(dialog):
    before = dialog.size_label.text(); dialog.cell_spin.setValue(dialog.cell_spin.value() / 2)
    assert dialog.size_label.text() != before
def test_a_too_fine_cell_is_refused_before_export(dialog):
    dialog.cell_spin.setValue(0.002)
    assert not dialog.export_button.isEnabled() and "too fine" in dialog.size_label.text()
def test_accepting_remembers_the_grids_volume_record_and_the_paraview_path(...):
    # session.volume_record("A")["dz_ns"] == the edited value;
    # QgsSettings().value(_PARAVIEW_KEY) == the path; reset the key in teardown.
def test_export_and_open_launches_paraview_with_the_folder(monkeypatch, ...):
    # QProcess.startDetached is spied: args == (path, ["--script=<folder>/open_scene.py"], "<folder>").
def test_with_no_paraview_path_it_writes_and_says_how_to_open(message_log, ...):
    # the message names the folder and open.sh.
def test_a_cancelled_export_reports_cancelled_and_writes_nothing(...):
    # the progress dialog is cancelled at its first update: message_log has "ParaView export
    # cancelled"; <site>/paraview/<grid> does not exist; no "*.partial" remains
```

- [ ] **Step 3: Run them and see them fail.** Run the QGIS command on the test file. Expected: FAIL.

- [ ] **Step 4: Implement** the dialog, the button and signal, `export_paraview()` and `launch_paraview()`.
  - **`export_paraview()`:**
    - builds `ParaViewExport(session, slices_dock)`;
    - runs the dialog;
    - remembers the choice (`session.remember_volume`) and the path (`QgsSettings`);
    - runs `run(...)` inside `busy_cursor()`, `dock.refining_paused()` and `_export_progress("Exporting for ParaView", total)`;
    - on success calls `message("Exported Grid A for ParaView to <folder>")` and launches ParaView if asked;
    - on `ParaViewExportCancelled` calls `message("ParaView export cancelled")`.
  - **The guide:** add the getting-started step:
    - what the folder holds;
    - how to open it, through the button or `open.sh`;
    - the stretch, and that legends show true depth;
    - the size warning.

- [ ] **Step 5: Run the tests and see them pass.** Then run `tests/pure/test_no_orphan_signals.py`, `test_plugin_loads.py` (unload must not leave the button connected) and `test_plugin_slices_dock.py`, then ruff.

- [ ] **Step 6: Commit**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui/paraview_dialog.py packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py packages/nsgeo-qgis/nsgeo_qgis/plugin.py packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_dialog.py docs/guide/getting-started.md
git commit -m "feat: Export for ParaView from the Slices panel, with a launch setting (M16 A)"
```

---

