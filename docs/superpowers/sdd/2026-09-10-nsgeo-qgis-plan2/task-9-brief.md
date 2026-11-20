### Task 9: Survey dock and the plugin's file actions

The tree of site → grids → lines, bound to the session, plus New/Open/Save on the toolbar. Dialogs the dock needs (grid, import) are requested through signals and provided by Tasks 10 and 11, so this task has no forward dependencies.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/__init__.py` (docstring only; no Qt imports, so the pure tier can import `ui.view_transform` later)
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py`

**Interfaces:**
- Consumes: `SiteSession`, `SiteLayers`
- Produces: `SurveyDock(session, parent=None)` (a `QgsDockWidget`) with `tree: QTreeWidget`, `status: QLabel`, `rebuild()`, `item_for_key(key) -> QTreeWidgetItem | None`, `grid_id_of(item) -> str | None`, `key_of(item) -> str | None`, signals `new_site_requested()`, `open_site_requested()`, `save_requested()`, `add_grid_requested()`, `edit_grid_requested(str)`, `import_requested(str)`, `grid_velocity_requested(str)`, `line_velocity_requested(str)`; `ROLE_KIND`, `ROLE_ID` item data roles. `NsgeoPlugin` gains `session`, `layers`, `survey_dock`, `save_with_prompt() -> bool`, `new_site()`, `open_site()`, and toolbar actions `act_new`, `act_open`, `act_save`, `act_add_grid`, `act_import`.

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.velocity import VelocityModel
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import Qt

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.survey_dock import ROLE_ID, ROLE_KIND, SurveyDock

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5, velocity=VelocityModel.constant(0.08))


@pytest.fixture
def dock(qgis_app, tmp_path):
    session = SiteSession()
    dock = SurveyDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT")
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1 if i % 2 == 0 else -1, p.stem)))
    session.add_lines(lines)
    return session, dock


def test_tree_mirrors_site_grids_and_lines(dock):
    session, dock = dock
    root = dock.tree.topLevelItem(0)
    assert root.text(0) == session.site_name
    grid_item = root.child(0)
    assert grid_item.data(0, ROLE_KIND) == "grid" and grid_item.data(0, ROLE_ID) == "A"
    assert "0.080" in grid_item.text(0)
    assert grid_item.childCount() == 3
    line_item = grid_item.child(1)
    assert line_item.data(0, ROLE_KIND) == "line"
    assert line_item.data(0, ROLE_ID) == "raw/FILE__002.DZT"
    assert "FILE__002" in line_item.text(0) and "0.50" in line_item.text(0) and "↓" in line_item.text(0)


def test_tree_follows_session_changes(dock):
    session, dock = dock
    session.remove_line("raw/FILE__003.DZT")
    assert dock.tree.topLevelItem(0).child(0).childCount() == 2
    session.add_grid(Grid("B", (0.0, 0.0), 0.0, 1.0, 1.0, "EPSG:32616", 0.5))
    assert dock.tree.topLevelItem(0).childCount() == 2
    assert "empty" in dock.tree.topLevelItem(0).child(1).text(0)


def test_clicking_a_line_opens_it_and_selection_follows_the_session(dock):
    session, dock = dock
    item = dock.item_for_key("raw/FILE__002.DZT")
    dock.tree.itemClicked.emit(item, 0)
    assert session.current_key == "raw/FILE__002.DZT"
    session.open_line("raw/FILE__003.DZT")
    assert dock.tree.currentItem() is dock.item_for_key("raw/FILE__003.DZT")


def test_status_shows_dirty_state(dock):
    session, dock = dock
    assert "modified" in dock.status.text()
    session.save()
    assert "modified" not in dock.status.text()
    assert "survey.nsgeo.json" in dock.status.text()


def test_line_velocity_override_is_marked(dock):
    session, dock = dock
    session.set_line_velocity("raw/FILE__001.DZT", VelocityModel.constant(0.095))
    assert "v 0.095*" in dock.item_for_key("raw/FILE__001.DZT").text(0)


def test_context_actions_remove_lines_and_grids(dock):
    session, dock = dock
    dock.remove_line_action("raw/FILE__001.DZT", confirm=False)
    assert "raw/FILE__001.DZT" not in session.keys()
    with pytest.raises(ValueError):
        dock.remove_grid_action("A", confirm=False)


def test_closing_the_site_empties_the_tree(dock):
    session, dock = dock
    session.close_site()
    assert dock.tree.topLevelItemCount() == 0
    assert dock.status.text() == "no site open"


def test_plugin_wires_the_dock_and_file_actions(fake_iface, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    assert plugin.survey_dock in fake_iface.docks
    assert plugin.survey_dock.allowedAreas() & Qt.DockWidgetArea.LeftDockWidgetArea
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)
    assert plugin.save_with_prompt() is True
    assert not plugin.session.dirty
    plugin.unload()
    assert plugin.survey_dock is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui'`

- [ ] **Step 3: Implement the dock**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/__init__.py`:

```python
"""Docks, dialogs, and the profile viewer. Widgets read from SiteSession
and never hold survey state. This file imports nothing so that the pure
test tier can import `nsgeo_qgis.ui.view_transform` without Qt."""
```

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`:

```python
"""The survey tree: site -> grids -> lines.

A view of the session. Removing lines and grids is handled here because it
is one session call; anything that needs a dialog (grid editor, import,
velocity) is requested through a signal and provided by the plugin object.
"""

from __future__ import annotations

from typing import Any

from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.session import SiteSession

ROLE_KIND = int(Qt.ItemDataRole.UserRole)
ROLE_ID = int(Qt.ItemDataRole.UserRole) + 1


class SurveyDock(QgsDockWidget):
    new_site_requested = pyqtSignal()
    open_site_requested = pyqtSignal()
    save_requested = pyqtSignal()
    add_grid_requested = pyqtSignal()
    edit_grid_requested = pyqtSignal(str)
    import_requested = pyqtSignal(str)
    grid_velocity_requested = pyqtSignal(str)
    line_velocity_requested = pyqtSignal(str)

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__("nsgeo Survey", parent)
        self.setObjectName("nsgeoSurveyDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.session = session

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        self.tree = QTreeWidget(body)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.tree)
        self.status = QLabel(body)
        layout.addWidget(self.status)
        self.setWidget(body)

        session.site_opened.connect(self.rebuild)
        session.site_closed.connect(self.rebuild)
        session.grids_changed.connect(self.rebuild)
        session.lines_changed.connect(self.rebuild)
        session.dirty_changed.connect(self._update_status)
        session.line_opened.connect(self._follow_current)
        self.rebuild()

    # ---- building ---------------------------------------------------------
    def rebuild(self) -> None:
        self.tree.clear()
        site = self.session.site
        if site is None:
            self._update_status()
            return
        root = QTreeWidgetItem([self.session.site_name])
        root.setData(0, ROLE_KIND, "site")
        self.tree.addTopLevelItem(root)
        by_grid: dict[str, list[Any]] = {g.id: [] for g in site.grids}
        loose = []
        for line in site.lines:
            grid_id = getattr(line.placement, "grid_id", None)
            (by_grid[grid_id] if grid_id in by_grid else loose).append(line)
        for grid in site.grids:
            v = f" · v {grid.velocity.surface_velocity:.3f}" if grid.velocity else ""
            lines = by_grid[grid.id]
            text = f"{grid.id} · {grid.size_x:g} × {grid.size_y:g} m · {grid.default_spacing:g} m{v}"
            if not lines:
                text += " · empty"
            g_item = QTreeWidgetItem([text])
            g_item.setData(0, ROLE_KIND, "grid")
            g_item.setData(0, ROLE_ID, grid.id)
            root.addChild(g_item)
            for line in lines:
                g_item.addChild(self._line_item(line))
        for line in loose:
            root.addChild(self._line_item(line))
        self.tree.expandAll()
        self._follow_current(self.session.current_key or "")
        self._update_status()

    def _line_item(self, line: Any) -> QTreeWidgetItem:
        p = line.placement
        arrow = "↑" if getattr(p, "direction", 1) == 1 else "↓"
        cross = "x" if getattr(p, "axis", "y") == "y" else "y"
        text = f"{p.label or line.path.stem} · {cross} {p.offset:.2f} · {arrow}"
        if line.velocity is not None:
            text += f" · v {line.velocity.surface_velocity:.3f}*"
        item = QTreeWidgetItem([text])
        item.setData(0, ROLE_KIND, "line")
        item.setData(0, ROLE_ID, self.session.line_key(line))
        item.setToolTip(0, str(line.path))
        return item

    def _update_status(self, *_: Any) -> None:
        if not self.session.is_open:
            self.status.setText("no site open")
            return
        name = self.session.json_path.name if self.session.json_path else ""
        self.status.setText(f"{name} · ● modified" if self.session.dirty else name)

    # ---- lookups ----------------------------------------------------------
    def kind_of(self, item: QTreeWidgetItem | None) -> str | None:
        return item.data(0, ROLE_KIND) if item is not None else None

    def key_of(self, item: QTreeWidgetItem | None) -> str | None:
        return item.data(0, ROLE_ID) if self.kind_of(item) == "line" else None

    def grid_id_of(self, item: QTreeWidgetItem | None) -> str | None:
        return item.data(0, ROLE_ID) if self.kind_of(item) == "grid" else None

    def item_for_key(self, key: str) -> QTreeWidgetItem | None:
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            if self.key_of(item) == key:
                return item
            it += 1
        return None

    # ---- interaction ------------------------------------------------------
    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        key = self.key_of(item)
        if key is not None:
            self.session.open_line(key)

    def _follow_current(self, key: str) -> None:
        item = self.item_for_key(key) if key else None
        self.tree.setCurrentItem(item)

    def _on_context_menu(self, pos: Any) -> None:
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        kind = self.kind_of(item)
        if kind == "site" or item is None:
            menu.addAction("Add grid…", self.add_grid_requested.emit)
        elif kind == "grid":
            gid = self.grid_id_of(item) or ""
            menu.addAction("Edit grid…", lambda: self.edit_grid_requested.emit(gid))
            menu.addAction("Import DZT files…", lambda: self.import_requested.emit(gid))
            menu.addAction("Set velocity…", lambda: self.grid_velocity_requested.emit(gid))
            menu.addSeparator()
            menu.addAction("Remove grid", lambda: self.remove_grid_action(gid))
        elif kind == "line":
            key = self.key_of(item) or ""
            menu.addAction("Open", lambda: self.session.open_line(key))
            menu.addAction("Set velocity override…", lambda: self.line_velocity_requested.emit(key))
            menu.addSeparator()
            menu.addAction("Remove line from site", lambda: self.remove_line_action(key))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def remove_line_action(self, key: str, *, confirm: bool = True) -> None:
        if confirm:
            answer = QMessageBox.question(
                self,
                "Remove line",
                f"Remove {key} from the site?\nIts picks stay in the picks layer.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.session.remove_line(key)

    def remove_grid_action(self, grid_id: str, *, confirm: bool = True) -> None:
        if confirm:
            answer = QMessageBox.question(self, "Remove grid", f"Remove grid {grid_id}?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.session.remove_grid(grid_id)
        except ValueError as exc:
            if confirm:
                QMessageBox.warning(self, "Remove grid", str(exc))
            else:
                raise
```

- [ ] **Step 4: Wire the plugin object**

Rewrite `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:

```python
"""The QGIS plugin object: builds the toolbar and docks, tears them down.

Holds no survey state; that is SiteSession. Owns the file dialogs and the
save-with-prompt flow, and hands dialog requests from the docks to the
dialog classes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import nsgeo
from nsgeo.project import ProjectError
from qgis.core import Qgis
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox

from nsgeo_qgis import plugin_version
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SURVEY_FILE, SiteSession
from nsgeo_qgis.ui.survey_dock import SurveyDock

MENU = "&nsgeo"


class NsgeoPlugin:
    def __init__(self, iface: Any) -> None:
        self.iface = iface
        self.toolbar: Any = None
        self.actions: list[QAction] = []
        self.docks: list[Any] = []
        self.session: SiteSession | None = None
        self.layers: SiteLayers | None = None
        self.survey_dock: SurveyDock | None = None

    # ---- QGIS entry points ------------------------------------------------
    def initGui(self) -> None:  # noqa: N802
        self.session = SiteSession()
        self.layers = SiteLayers(self.session)
        main = self.iface.mainWindow()

        self.toolbar = self.iface.addToolBar("nsgeo")
        self.toolbar.setObjectName("nsgeoToolBar")
        self.act_new = self._action("New site…", self.new_site)
        self.act_open = self._action("Open site…", self.open_site)
        self.act_save = self._action("Save site", self.save_with_prompt)
        self.toolbar.addSeparator()
        self.act_add_grid = self._action("Add grid…", lambda: self.open_grid_dialog(None))
        self.act_import = self._action("Import DZT…", lambda: self.open_import_dialog(None))

        about = QAction("About nsgeo", main)
        about.triggered.connect(self.show_about)
        self.iface.addPluginToMenu(MENU, about)
        self.actions.append(about)

        self.survey_dock = SurveyDock(self.session, main)
        self.survey_dock.add_grid_requested.connect(lambda: self.open_grid_dialog(None))
        self.survey_dock.edit_grid_requested.connect(self.open_grid_dialog)
        self.survey_dock.import_requested.connect(self.open_import_dialog)
        self.survey_dock.grid_velocity_requested.connect(self.open_grid_dialog)
        self.iface.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.survey_dock)
        self.docks.append(self.survey_dock)
        self._update_enabled()
        self.session.site_opened.connect(self._update_enabled)
        self.session.site_closed.connect(self._update_enabled)

    def unload(self) -> None:
        if self.session is not None and self.session.dirty:
            self.save_with_prompt(ask_first=True)
        for dock in self.docks:
            self.iface.removeDockWidget(dock)
            dock.deleteLater()
        self.docks.clear()
        self.survey_dock = None
        for action in self.actions:
            self.iface.removePluginMenu(MENU, action)
        self.actions.clear()
        if self.toolbar is not None:
            self.toolbar.setParent(None)
            self.toolbar.deleteLater()
            self.toolbar = None
        if self.layers is not None:
            self.layers.detach()
            self.layers = None
        self.session = None

    # ---- helpers ----------------------------------------------------------
    def _action(self, text: str, slot: Any) -> QAction:
        action = QAction(text, self.iface.mainWindow())
        action.triggered.connect(slot)
        self.toolbar.addAction(action)
        return action

    def _update_enabled(self) -> None:
        is_open = self.session is not None and self.session.is_open
        for act in (self.act_save, self.act_add_grid, self.act_import):
            act.setEnabled(is_open)

    def message(self, text: str, level: Any = None, title: str = "nsgeo") -> None:
        self.iface.messageBar().pushMessage(
            title, text, level if level is not None else Qgis.MessageLevel.Info, 6
        )

    def show_about(self) -> None:
        self.message(f"plugin {plugin_version()} · core {nsgeo.__version__}")

    # ---- site files -------------------------------------------------------
    def new_site(self) -> None:
        assert self.session is not None
        if self.session.dirty and not self.save_with_prompt(ask_first=True):
            return
        folder = QFileDialog.getExistingDirectory(self.iface.mainWindow(), "Choose an empty folder for the site")
        if not folder:
            return
        try:
            self.session.new_site(Path(folder))
        except ProjectError as exc:
            self.message(str(exc), Qgis.MessageLevel.Critical)

    def open_site(self) -> None:
        assert self.session is not None
        if self.session.dirty and not self.save_with_prompt(ask_first=True):
            return
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(), "Open a survey file", "", f"nsgeo survey ({SURVEY_FILE});;All files (*)"
        )
        if not path:
            return
        try:
            self.session.open_site(Path(path))
        except ProjectError as exc:
            self.message(str(exc), Qgis.MessageLevel.Critical)

    def save_with_prompt(self, *, ask_first: bool = False) -> bool:
        """Save the site. Returns True when the caller may proceed (saved, or
        the user chose to discard). Handles the out-of-tree opt-in."""
        assert self.session is not None
        if not self.session.is_open:
            return True
        if ask_first:
            answer = QMessageBox.question(
                self.iface.mainWindow(),
                "Unsaved changes",
                "Save the site before continuing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Discard:
                return True
        try:
            self.session.save()
            return True
        except ProjectError as exc:
            if "allow_absolute" not in str(exc):
                self.message(str(exc), Qgis.MessageLevel.Critical)
                return False
            answer = QMessageBox.question(
                self.iface.mainWindow(),
                "Files outside the site folder",
                "Some survey files live outside the site folder. Record them by absolute path?\n"
                "The survey file will then only open on machines with the same mount points.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
            self.session.save(allow_absolute=True)
            return True

    # ---- dialogs (provided by later tasks) --------------------------------
    def open_grid_dialog(self, grid_id: str | None) -> None:
        self.message("Grid dialog arrives in the next task.", Qgis.MessageLevel.Warning)

    def open_import_dialog(self, grid_id: str | None) -> None:
        self.message("Import dialog arrives in a later task.", Qgis.MessageLevel.Warning)
```

- [ ] **Step 5: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: survey dock and site file actions

The tree is a view of the session: it rebuilds on every grids/lines
signal, selects the current line, and shows the dirty flag. Removing a
line or grid is one session call so it lives here; grid editing, import
and velocity dialogs are requested through signals. Save handles the
out-of-tree opt-in with a prompt rather than a silent fallback."
```

---

