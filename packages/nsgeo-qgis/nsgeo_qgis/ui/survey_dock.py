"""The survey tree: site -> grids -> lines.

A view of the session: it rebuilds on site/grids/lines signals and never
mutates the site except through SiteSession's own add_grid/remove_grid/
remove_line/open_line. Removing a line or grid is one session call so it
lives here; anything that needs a dialog (grid editor, import, velocity) is
only requested through a signal and answered by the plugin object.

Signal/slot hazard: an exception raised inside a slot connected via
`connect()` never reaches whatever emitted the signal -- PyQt prints the
traceback to stderr and `emit()` returns as if the slot had succeeded (see
`nsgeo_qgis.plugin`'s module docstring for the same note). Every slot here
that does real work -- rebuild() above all -- guards its own body and logs
through `QgsMessageLog` rather than assume a caller will notice. rebuild()
in particular falls back to an emptied tree with a visible error status
rather than risk a half-built tree that looks complete but silently isn't.
"""

from __future__ import annotations

from typing import Any

from qgis.core import Qgis
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

from nsgeo_qgis.log import log as _log
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
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
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
        try:
            self._rebuild()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring:
            # a slot's exception never reaches whatever emitted the signal,
            # so this is the only chance to tell the user the tree could not
            # be rebuilt. An emptied tree with a visible error is an honest
            # failure; a half-built one would look complete and be wrong.
            _log(f"could not rebuild the survey tree: {exc}", Qgis.MessageLevel.Critical)
            self.tree.clear()
            self.status.setText("survey tree error — see the nsgeo log")

    def _rebuild(self) -> None:
        root_expanded, known_grids, selected = self._capture_state()
        self.tree.clear()
        if not self.session.is_open:
            self._update_status()
            return
        site = self.session.site
        assert site is not None  # is_open just confirmed this
        root = QTreeWidgetItem([self.session.site_name])
        root.setData(0, ROLE_KIND, "site")
        self.tree.addTopLevelItem(root)
        root.setExpanded(root_expanded)
        # Grouped by (key, line) pairs from the session's own keys() /
        # line_for_key(), not by walking site.lines and recomputing each
        # key: keys() reads the authoritative _lines_by_key map (Task 6),
        # so this can never compute a key that disagrees with the one
        # open_line()/item_for_key() use for the same line. There is no
        # equivalent per-grid accessor on SiteSession (grid ids are not
        # derived the way a line's key is, so nothing can drift), so
        # site.grids is still read directly here, matching SiteLayers'
        # own established pattern for the same reason.
        by_grid: dict[str, list[tuple[str, Any]]] = {g.id: [] for g in site.grids}
        loose: list[tuple[str, Any]] = []
        for key in self.session.keys():  # noqa: SIM118 -- SiteSession.keys(), not a dict
            line = self.session.line_for_key(key)
            grid_id = getattr(line.placement, "grid_id", None)
            by_grid.get(grid_id, loose).append((key, line))
        for grid in site.grids:
            v = f" · v {grid.velocity.surface_velocity:.3f}" if grid.velocity else ""
            lines = by_grid[grid.id]
            text = (
                f"{grid.id} · {grid.size_x:g} × {grid.size_y:g} m · {grid.default_spacing:g} m{v}"
            )
            if not lines:
                text += " · empty"
            g_item = QTreeWidgetItem([text])
            g_item.setData(0, ROLE_KIND, "grid")
            g_item.setData(0, ROLE_ID, grid.id)
            root.addChild(g_item)
            # Brand-new grids (not seen on the previous build) default to
            # expanded; a grid the user explicitly collapsed stays collapsed
            # across an unrelated rebuild instead of snapping back open.
            g_item.setExpanded(known_grids.get(grid.id, True))
            for key, line in lines:
                g_item.addChild(self._line_item(key, line))
        for key, line in loose:
            root.addChild(self._line_item(key, line))
        self._restore_selection(selected)
        self._update_status()

    def _line_item(self, key: str, line: Any) -> QTreeWidgetItem:
        p = line.placement
        arrow = "↑" if getattr(p, "direction", 1) == 1 else "↓"
        cross = "x" if getattr(p, "axis", "y") == "y" else "y"
        text = f"{p.label or line.path.stem} · {cross} {p.offset:.2f} · {arrow}"
        try:
            line.distance_along()
        except ValueError:
            # A time-triggered acquisition (traces_per_metre <= 0): the
            # placement has no geometry to offer. SiteLayers already leaves
            # a line like this off the map for the same reason; this tree
            # is the one place it must still show up, clearly marked, since
            # a user has no other way to discover it is even in the site.
            text += " · ⚠ unplaced (time-triggered)"
        if line.velocity is not None:
            text += f" · v {line.velocity.surface_velocity:.3f}*"
        item = QTreeWidgetItem([text])
        item.setData(0, ROLE_KIND, "line")
        item.setData(0, ROLE_ID, key)
        item.setToolTip(0, str(line.path))
        return item

    def _update_status(self, *_: Any) -> None:
        try:
            if not self.session.is_open:
                self.status.setText("no site open")
                return
            name = self.session.json_path.name if self.session.json_path else ""
            self.status.setText(f"{name} · ● modified" if self.session.dirty else name)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not update the survey status label: {exc}", Qgis.MessageLevel.Critical)

    # ---- expansion/selection preservation ----------------------------------
    def _capture_state(self) -> tuple[bool, dict[str, bool], tuple[str, str | None] | None]:
        """(root expanded, {grid id: expanded}, identity of the current
        item) as the tree stood just before rebuild() clears it, so a
        rebuild triggered by an unrelated change (adding grid B) does not
        silently collapse or deselect whatever the user had open in grid A.
        """
        root = self.tree.topLevelItem(0)
        root_expanded = root.isExpanded() if root is not None else True
        known_grids: dict[str, bool] = {}
        if root is not None:
            for i in range(root.childCount()):
                child = root.child(i)
                if self.kind_of(child) == "grid":
                    grid_id = self.grid_id_of(child)
                    if grid_id is not None:
                        known_grids[grid_id] = child.isExpanded()
        return root_expanded, known_grids, self._identity(self.tree.currentItem())

    def _identity(self, item: QTreeWidgetItem | None) -> tuple[str, str | None] | None:
        kind = self.kind_of(item)
        if kind == "site":
            return ("site", None)
        if kind == "grid":
            return ("grid", self.grid_id_of(item))
        if kind == "line":
            return ("line", self.key_of(item))
        return None

    def _item_for_identity(self, ident: tuple[str, str | None]) -> QTreeWidgetItem | None:
        kind, ident_id = ident
        if kind == "site":
            return self.tree.topLevelItem(0)
        if kind == "line":
            return self.item_for_key(ident_id) if ident_id else None
        if kind == "grid":
            it = QTreeWidgetItemIterator(self.tree)
            while it.value():
                item = it.value()
                if self.kind_of(item) == "grid" and self.grid_id_of(item) == ident_id:
                    return item
                it += 1
        return None

    def _restore_selection(self, previous: tuple[str, str | None] | None) -> None:
        # The session's current line always wins: whatever the user last
        # clicked in the tree before an unrelated rebuild is a weaker claim
        # than "this is the line open in the profile view right now".
        key = self.session.current_key
        if key:
            self.tree.setCurrentItem(self.item_for_key(key))
            return
        item = self._item_for_identity(previous) if previous is not None else None
        self.tree.setCurrentItem(item)

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
    def _open_line(self, key: str) -> None:
        try:
            self.session.open_line(key)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring:
            # a click or a menu selection is a triggered/itemClicked slot;
            # an unguarded KeyError here (a stale tree item) would vanish
            # into stderr and the user would just see nothing happen.
            _log(f"could not open line {key!r}: {exc}", Qgis.MessageLevel.Critical)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        key = self.key_of(item)
        if key is not None:
            self._open_line(key)

    def _follow_current(self, key: str) -> None:
        try:
            item = self.item_for_key(key) if key else None
            self.tree.setCurrentItem(item)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(
                f"could not follow the current line in the tree: {exc}", Qgis.MessageLevel.Critical
            )

    def _on_context_menu(self, pos: Any) -> None:
        # Only the synchronous menu-building below is inside this guard.
        # QMenu.exec() runs its own nested event loop, and the action the
        # user picks fires through a normal pyqtSignal -- so each lambda
        # below is itself a slot subject to the same swallowed-exception
        # hazard and must guard its own work (remove_line_action and
        # remove_grid_action already do; _open_line already does).
        try:
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
                menu.addAction("Open", lambda: self._open_line(key))
                menu.addAction(
                    "Set velocity override…", lambda: self.line_velocity_requested.emit(key)
                )
                menu.addSeparator()
                menu.addAction("Remove line from site", lambda: self.remove_line_action(key))
            menu.exec(self.tree.viewport().mapToGlobal(pos))
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not build the survey tree context menu: {exc}", Qgis.MessageLevel.Critical)

    def remove_line_action(self, key: str, *, confirm: bool = True) -> None:
        if confirm:
            answer = QMessageBox.question(
                self,
                "Remove line",
                f"Remove {key} from the site?\nIts picks stay in the picks layer.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.session.remove_line(key)
        except KeyError as exc:
            if confirm:
                QMessageBox.warning(self, "Remove line", str(exc))
            else:
                raise

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
