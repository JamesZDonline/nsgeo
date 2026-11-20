### Task 4: The Add data dialog: one dialog, two pages, the switch

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/add_data_dialog.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py` (`ImportDialog(QDialog)` becomes `GridImportPage(QWidget)`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/gps_import_dialog.py` (`GpsImportDialog(QDialog)` becomes `GpsImportPage(QWidget)`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/gps_import.py` (`count_with_gps`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (toolbar button, `open_add_data_dialog`, the Survey shortcut, messages; remove `open_import_dialog`, `open_gps_import_dialog`, `_import_from_toolbar`'s old target, `act_import`, `act_import_gps`)
- Modify: `docs/guide/getting-started.md` and any other doc that names `Import DZT…` or `Import GPS lines…` (grep `docs/` and both package READMEs)
- Test: migrate `tests/qgis/test_plugin_import_dialog.py` and `tests/qgis/test_plugin_gps_import_dialog.py` to the new classes; new `tests/qgis/test_plugin_add_data_dialog.py`; `tests/pure/test_pure_gps_import.py`; `tests/qgis/test_plugin_panels_menu.py` (its tuple of toolbar actions).

**Interfaces:**
- Produces, in `ui/add_data_dialog.py`:

```python
GRID, GPS = "grid", "gps"
MODE_KEY = "nsgeo/addDataMode"   # QgsSettings; absent means GRID (decision 15: Grid the first time)

class AddDataDialog(QDialog):
    imported = pyqtSignal(list)   # list[tuple[str, bool]]: (text, is_warning), one batch per Import
    def __init__(self, session: SiteSession, *, grid_id: str | None = None, mode: str | None = None,
                 canvas: QgsMapCanvas | None = None, parent: QWidget | None = None) -> None: ...
    grid_page: GridImportPage
    gps_page: GpsImportPage
    grid_button: QPushButton; gps_button: QPushButton; gps_note: QLabel
    import_button: QPushButton
    def mode(self) -> str: ...
    def set_mode(self, mode: str) -> None: ...         # carries the file list across (below)
    def add_files(self, paths: list[Path]) -> None: ... # to the current page
    def retarget(self, grid_id: str) -> None: ...      # the current page's target, only while it has no files
    def accept(self) -> None: ...                       # current page's import_lines(); closes when it returns True

def opening_mode(session: SiteSession, grid_id: str | None) -> str: ...
    # decision 15: a grid whose lines are all GPS → GPS, all tape → GRID; else (no grid, empty, mixed) the remembered mode
```

- Each page is a `QWidget` with: `changed = pyqtSignal()` (title, button text or enabled state may have moved); `title() -> str`; `import_text() -> str`; `can_import() -> bool`; `paths() -> list[Path]`; `set_files(paths: list[Path]) -> None` (keeps the rows of paths it already has, with their edits; drops the others; plans the new ones; no-op when equal); `import_lines() -> bool` (the old `accept` body; True once lines were added); `messages: list[tuple[str, bool]]` (what the last `import_lines` has to say); `status: QLabel`; `preset_box`. Every existing public attribute and method of the two dialogs keeps its name on its page (`grid_combo`, `rows`, `table`, `add_files`, `set_offset`, `shift`, `crs_label`, …).
- `gps_import.count_with_gps(paths: Sequence[Path]) -> int` — files whose DZG holds at least one RTK fix with a position (`first_fixed_lonlat(p) is not None`).
- `plugin.open_add_data_dialog(grid_id: str | None = None, mode: str | None = None) -> None` — single-instance and modeless, `open_grid_dialog`'s shape (`finished` cleans up, `destroyed` guard). The toolbar's `GPR…` opens it on the Survey panel's `target_grid_id()` in the remembered mode; the Survey shortcut opens it on that grid in `opening_mode(session, gid)`; an open dialog is raised, retargeted (only while its current page has no files) and switched to the asked mode. `imported` batches go to `self.message`, the first of each batch Info, the rest Warning when flagged.
- `AddDataDialog.accept` writes `MODE_KEY` = the mode Import succeeded in.

- [ ] **Step 1: Migrate the two dialog test files first** so they drive the pages through an `AddDataDialog` (helpers `grid_dialog(session, grid_id="A")` and `gps_dialog(session)` returning the dialog; tests reach `d.grid_page` / `d.gps_page` and call `d.accept()`). Their assertions stay as they are, except the window title and the button texts, which follow the copy. Run them to see them fail (the classes do not exist yet).
- [ ] **Step 2: Write the new tests** in `test_plugin_add_data_dialog.py` and `test_pure_gps_import.py`:
  - The switch: Grid checked first with no `MODE_KEY`; `set_mode(GPS)` shows the GPS page, hides `gps_note`, retitles; the `Grid` / `GPS` buttons are exclusive.
  - Carrying files: three files added in Grid mode with one offset typed and one direction flipped → switch to GPS → the GPS page lists the same three paths → switch back → the typed offset and flipped direction are still there (Review Focus 4). Removing one file in GPS mode and switching back drops it from the Grid page and keeps the other rows' edits.
  - The note: two of three files with a usable DZG → `"2 of 3 files have a GPS log beside them."`; a DZG with no RTK fix does not count; none → hidden; one file with one → `"This file has a GPS log beside it."`; never shown in GPS mode. `count_with_gps` pinned in the pure tier.
  - No grid: in Grid mode on a grid-free site the status reads the copy and Import is disabled; GPS mode is still offered.
  - Mode memory: a successful Grid import writes `grid`; a GPS import writes `gps`; Cancel writes nothing. `opening_mode` for an all-GPS grid, an all-tape grid, an empty grid and a mixed grid (the last two take the remembered mode). Restore `MODE_KEY` after each test.
  - Plugin: the toolbar has an `Add data` button whose menu holds `GPR…`, in the place of the two import actions, greyed until a site opens; `GPR…` opens one dialog and a second press raises it; the Survey panel's `Add GPR data…` opens it on that grid; `imported` batches reach the message bar; the dialog finishing clears `plugin._add_data_dialog`; a dialog destroyed without `finished` is cleared too (port the two lifecycle tests the old dialogs had).
- [ ] **Step 3: Run them to see them fail.**
- [ ] **Step 4: Implement.** Move each dialog's body into its page unchanged apart from: no title of its own (`title()`), no button box (`import_text()`, `can_import()`, `changed`), `accept` → `import_lines()`, and `messages` filled where the plugin used to read `imported_keys`/`preset_notice`/`messages`. The dialog stacks the pages in a `QStackedWidget` under the switch row, puts the shared footer (the current page's `status` stays inside the page; the dialog's button box at the bottom) and forwards `changed` to its title and button. `GpsImportPage` keeps M17a's behaviour exactly in this task (no grid yet; Task 5 adds it). The toolbar button copies the Panels ▾ pattern (`QToolButton`, `InstantPopup`, `toolbar.addWidget`) at the old actions' position; put its action into `_update_enabled`'s site-open tuple in their place. Update the guide's toolbar table and Step 3 / Step 3a.
- [ ] **Step 5: Run** the three dialog test files, `test_plugin_panels_menu.py`, `test_plugin_survey_dock.py`, the pure tier (boundary and orphan-signal tests included), lint and types.
- [ ] **Step 6: Commit and push** (`feat(m17b): Add data ▾ ▸ GPR…, one dialog with a Grid / GPS switch (#134)`).

---

