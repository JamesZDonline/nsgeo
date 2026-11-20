"""The survey tree: site -> grids -> lines.

A view of the session: it rebuilds on site/grids/lines signals and never
mutates the site except through SiteSession's own add_grid/remove_grid/
remove_lines/open_line. Removing lines or grids is one session call so it
lives here; anything that needs a dialog (grid editor, import, velocity) is
only requested through a signal and answered by the plugin object.

Several items can be selected at once (#31): Ctrl- or Shift-click builds a
selection without opening anything, and Delete -- or the context menu on
the selection -- removes it after one confirmation. A grid goes with its
lines, and only when nothing but grids is selected (see _selected_targets).

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

from nsgeo.geometry import TrackPlacement
from nsgeo.model import is_cut_key
from qgis.core import Qgis
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import QEvent, QItemSelection, QItemSelectionModel, QObject, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.line_edit import SAME_M
from nsgeo_qgis.log import log as _log
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.preset_box import migration_note
from nsgeo_qgis.velocity_records import line_label

ROLE_KIND = int(Qt.ItemDataRole.UserRole)
ROLE_ID = int(Qt.ItemDataRole.UserRole) + 1

# Backspace too: it is what a Mac keyboard's "delete" key sends.
_DELETE_KEYS = (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
_CHORD_MODIFIERS = (
    Qt.KeyboardModifier.ControlModifier,
    Qt.KeyboardModifier.AltModifier,
    Qt.KeyboardModifier.MetaModifier,
    Qt.KeyboardModifier.ShiftModifier,
)
# The cut prompts (cut spec §4.8). One constant each, so the tests quote them.
DELETE_CUT_TEXT = "Delete {name}?"
CUT_ONE_PICK_TEXT = " Its 1 pick stays on the map."
CUT_PICKS_TEXT = " Its {n} picks stay on the map."
CUTS_ONLY_PICKS_TEXT = "Picks on a cut stay on the map."
# Grid removal: `{its}` is "Its" for one grid and "Their" for several; the tail
# says what becomes of the cuts' picks (`{they}` is "its" for one cut, else "their").
GRID_CUTS_ONE_TEXT = "{its} 1 cut is deleted too"
GRID_CUTS_TEXT = "{its} {n} cuts are deleted too"
GRID_CUT_PICK_TAIL = "; {they} 1 pick stays on the map."
GRID_CUT_PICKS_TAIL = "; {they} {m} picks stay on the map."
# Remove: what goes with the lines (#221). Each part appears only when true.
ALSO_REMOVED_TEXT = "Also removed: {parts}."
# Bulk actions on a selection of lines (#58). One constant each, so the tests quote them.
APPLY_PRESET_MENU = "Apply preset to {lines}"
APPLY_STEPS_MENU = "Apply steps from {open} to {lines}…"
APPLY_STEPS_MENU_GREY = "Apply steps from the open line…"
SET_VELOCITY_MENU = "Set velocity for {lines}…"
CLEAR_VELOCITY_MENU = "Clear velocity override on {lines}"
APPLY_PRESET_TITLE = "Apply preset"
APPLY_PRESET_TEXT = "Replace the processing of {lines} with preset {name}?"
APPLY_PRESET_REPORT = "preset {name} applied to {lines}"
APPLY_STEPS_TITLE = "Apply steps"
APPLY_STEPS_TEXT = "Replace the processing of {lines} with the steps on {open}?"
APPLY_STEPS_LEFT_TEXT = "{open} itself is left as it is."
APPLY_STEPS_REPORT = "steps from {open} applied to {lines}"
CLEAR_VELOCITY_TITLE = "Clear velocity override"
CLEAR_VELOCITY_TEXT = (
    "Clear the velocity override on {n} of these {lines}? "
    "They go back to their grid's velocity, or the one in the file's header."
)
CLEAR_VELOCITY_FITS_ONE_TEXT = "1 of them has a velocity from its saved fits; the fits stay saved."
CLEAR_VELOCITY_FITS_TEXT = "{n} of them have a velocity from their saved fits; the fits stay saved."
CLEAR_VELOCITY_REPORT = "velocity override cleared on {lines}"
# How many line keys a removal prompt lists before it summarises the rest.
_LISTED_KEYS = 10
# Moving the current item to a line must select just that line. A bare
# setCurrentItem() takes its selection command from whatever modifier keys
# are held at that moment, so with Ctrl down it TOGGLES the line -- out of
# the selection, if it was already in it.
_SELECT_ONLY = QItemSelectionModel.SelectionFlag.ClearAndSelect


class SurveyDock(QgsDockWidget):
    new_site_requested = pyqtSignal()
    open_site_requested = pyqtSignal()
    save_requested = pyqtSignal()
    add_grid_requested = pyqtSignal()
    edit_grid_requested = pyqtSignal(str)
    import_requested = pyqtSignal(str)
    fit_tracks_requested = pyqtSignal(list)  # keys of the GPS lines (M17b)
    grid_velocity_requested = pyqtSignal(str)
    line_velocity_requested = pyqtSignal(str)
    # (grid id, line keys to select); keys may be empty (line editing spec §3 call 7).
    edit_lines_requested = pyqtSignal(str, list)
    # (line keys, target grid id) (line editing spec §3 call 7).
    move_lines_requested = pyqtSignal(list, str)
    # GPS line keys whose destagger is to be set (M17a P13).
    destagger_requested = pyqtSignal(list)
    # Line keys whose velocity is to be set in one go: the plugin asks for the number (#58).
    bulk_velocity_requested = pyqtSignal(list)
    # One message-bar line, answered by the plugin (#58).
    report = pyqtSignal(str)
    #: The selected line keys, tree order, whenever the selection changed by the
    #: user's hand, an open, or a finished rebuild; never for `select_lines` (#57).
    line_selection_changed = pyqtSignal(list)

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__("nsgeo Survey", parent)
        self.setObjectName("nsgeoSurveyDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.session = session
        # Depth counter: >0 while the tree's selection is being changed by us
        # (`select_lines`, a rebuild, an open), so it is not announced half-done.
        self._selection_quiet = 0
        self._captured_line_keys: list[str] = []

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        self.tree = QTreeWidget(body)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.installEventFilter(self)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        # One menu, repopulated per right-click, rather than a fresh
        # QMenu(self) each time -- the same shape ProcessingDock's
        # `presets_menu` uses, and for both of its reasons. It is what
        # makes the menu assertable at all: QMenu.exec() runs a nested
        # event loop and is forbidden outright in the qgis test tier (it
        # blocks forever offscreen), so without a handle on the built menu
        # nothing could check which actions appear for a site, a grid or a
        # line, or fire one without going through exec. It also stops a
        # QMenu accumulating per right-click: the old local menu was
        # parented to this dock and nothing ever deleted it, so one leaked
        # on every right-click for the dock's whole life. QMenu.clear()
        # deletes the actions it owns, but it does NOT delete a submenu
        # added with addMenu(): that stays a child of its parent. So the
        # one submenu ("Move to grid") is made once, here, parented to the
        # dock, and refilled on every right-click; clear() only detaches
        # its action, and the reuse leaves nothing behind (line editing
        # spec §3 call 7).
        self.context_menu = QMenu(self)
        self.move_menu = QMenu("Move to grid", self)
        # Made once, like move_menu: clear() would not delete a submenu per click.
        self.preset_menu = QMenu("Apply preset", self)
        layout.addWidget(self.tree)
        self.status = QLabel(body)
        layout.addWidget(self.status)
        self.setWidget(body)

        session.site_opened.connect(self.rebuild)
        session.site_closed.connect(self.rebuild)
        session.grids_changed.connect(self.rebuild)
        session.lines_changed.connect(self.rebuild)
        session.cuts_changed.connect(self.rebuild)
        session.dirty_changed.connect(self._update_status)
        session.line_opened.connect(self._follow_current)
        self.rebuild()

    # ---- building ---------------------------------------------------------
    def rebuild(self) -> None:
        try:
            self._rebuild_announcing()
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
            v = ""
            if grid.velocity is not None:
                v = f" · v {grid.velocity.surface_velocity:.3f}"
                if grid.velocity_source is not None:
                    # Where the number came from (grid velocity spec §7.5).
                    v += f" ({grid.velocity_source.summary()})"
            lines = by_grid[grid.id]
            text = (
                f"{grid.id} · {grid.size_x:g} × {grid.size_y:g} m · {grid.default_spacing:g} m{v}"
            )
            if not lines:
                text += " · empty"
            n_fits = sum(len(line.velocity_fits) for _, line in lines)
            if n_fits:
                n_lines = sum(1 for _, line in lines if line.velocity_fits)
                text += (
                    f" · {n_fits} fit{'' if n_fits == 1 else 's'}"
                    f" on {n_lines} line{'' if n_lines == 1 else 's'}"
                )
            g_item = QTreeWidgetItem([text])
            g_item.setData(0, ROLE_KIND, "grid")
            g_item.setData(0, ROLE_ID, grid.id)
            root.addChild(g_item)
            # Cut spec plan call 12: a Cuts item before the lines, one child
            # per cut in drawing order. A grid with no cuts has none.
            cut_keys = self.session.cut_keys_on_grid(grid.id)
            if cut_keys:
                cuts_item = QTreeWidgetItem(["Cuts"])
                cuts_item.setData(0, ROLE_KIND, "cuts")
                cuts_item.setData(0, ROLE_ID, grid.id)
                g_item.addChild(cuts_item)
                for cut_key in cut_keys:
                    cuts_item.addChild(self._cut_item(cut_key))
                cuts_item.setExpanded(True)
            # A grid not seen on the previous build -- every grid, when a
            # site opens -- starts collapsed (#133), so a site with many
            # grids opens as a short list of grids, not one long list of
            # lines. A grid the user opened stays open across an unrelated
            # rebuild instead of snapping shut. Opening a line unfolds its
            # grid (_follow_current).
            g_item.setExpanded(known_grids.get(grid.id, False))
            for key, line in lines:
                g_item.addChild(self._line_item(key, line))
        for key, line in loose:
            root.addChild(self._line_item(key, line))
        self._restore_selection(selected)
        self._update_status()

    def _line_item(self, key: str, line: Any) -> QTreeWidgetItem:
        p = line.placement
        if isinstance(p, TrackPlacement):
            text = self._gps_row_text(line)
        else:
            arrow = "↑" if getattr(p, "direction", 1) == 1 else "↓"
            cross = "x" if getattr(p, "axis", "y") == "y" else "y"
            text = f"{line_label(line)} · {cross} {p.offset:.2f} · {arrow}"
            try:
                line.distance_along()
            except ValueError:
                # A time-triggered acquisition (traces_per_metre <= 0): the
                # placement has no geometry to offer. SiteLayers already leaves
                # a line like this off the map for the same reason; this tree
                # is the one place it must still show up, clearly marked, since
                # a user has no other way to discover it is even in the site.
                text += " · ⚠ unplaced (time-triggered)"
        scale = getattr(p, "scale", 1.0)
        shift = getattr(p, "travel_shift", 0.0)
        if abs(scale - 1) > SAME_M:
            text += f" · ×{scale:.3f}"
        if abs(shift) > SAME_M:
            text += f" · destagger {shift:+.2f} m"
        if line.velocity is not None:
            text += f" · v {line.velocity.surface_velocity:.3f}*"
        tip = str(line.path)
        fits = sorted(line.velocity_fits.values(), key=lambda f: f.t0_ns)
        if fits:
            # #126: the saved hyperbola fits, shallowest first, with the
            # numbers they were stored with. The velocity dialog shows them
            # measured from the line's current time zero, which needs the
            # line read; a tree rebuild must not read every line, so the
            # tooltip says which numbers these are.
            text += f" · {len(fits)} fit{'' if len(fits) == 1 else 's'}"
            tip += (
                f"\n{len(fits)} saved fit{'' if len(fits) == 1 else 's'}, as measured when saved:"
            )
            for f in fits:
                tip += f"\n  {f.t0_ns:.1f} ns · {f.v_m_ns:.4f} ± {f.v_stderr_m_ns:.4f} m/ns"
        item = QTreeWidgetItem([text])
        item.setData(0, ROLE_KIND, "line")
        item.setData(0, ROLE_ID, key)
        item.setToolTip(0, tip)
        return item

    @staticmethod
    def _gps_row_text(line: Any) -> str:
        """`{label} · GPS · {walked} m`, plus the metres without RTK when there are any."""
        distance = line.distance_along()
        walked = float(distance[-1] - distance[0]) if len(distance) else 0.0
        text = f"{line_label(line)} · GPS · {walked:.1f} m"
        gap = sum(b.metres for b in line.placement.bridges())
        if gap > 0:
            text += f" · {gap:.1f} m without RTK"
        return text

    def _cut_item(self, key: str) -> QTreeWidgetItem:
        cut = self.session.cut_for_key(key)
        item = QTreeWidgetItem([cut.name])
        item.setData(0, ROLE_KIND, "cut")
        item.setData(0, ROLE_ID, key)
        item.setToolTip(0, f"{cut.length_m:.1f} m on grid {cut.grid_id}")
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
        self._capture_line_keys()
        return root_expanded, known_grids, self._identity(self.tree.currentItem())

    def _identity(self, item: QTreeWidgetItem | None) -> tuple[str, str | None] | None:
        kind = self.kind_of(item)
        if kind == "site":
            return ("site", None)
        if kind == "grid":
            return ("grid", self.grid_id_of(item))
        if kind == "line":
            return ("line", self.key_of(item))
        if kind == "cut":
            return ("cut", self.cut_key_of(item))
        return None

    def _item_for_identity(self, ident: tuple[str, str | None]) -> QTreeWidgetItem | None:
        kind, ident_id = ident
        if kind == "site":
            return self.tree.topLevelItem(0)
        if kind in ("line", "cut"):
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
        # Order of claims: the lines that were selected before the rebuild
        # (spec 3.4), then the session's current line, then whatever the user
        # last clicked: each is a weaker claim than the one before it.
        if self._restore_line_selection():
            return
        key = self.session.current_key
        if key:
            self.tree.setCurrentItem(self.item_for_key(key), 0, _SELECT_ONLY)
            return
        item = self._item_for_identity(previous) if previous is not None else None
        self.tree.setCurrentItem(item, 0, _SELECT_ONLY)

    # ---- lookups ----------------------------------------------------------
    def kind_of(self, item: QTreeWidgetItem | None) -> str | None:
        return item.data(0, ROLE_KIND) if item is not None else None

    def key_of(self, item: QTreeWidgetItem | None) -> str | None:
        return item.data(0, ROLE_ID) if self.kind_of(item) == "line" else None

    def cut_key_of(self, item: QTreeWidgetItem | None) -> str | None:
        return item.data(0, ROLE_ID) if self.kind_of(item) == "cut" else None

    def grid_id_of(self, item: QTreeWidgetItem | None) -> str | None:
        return item.data(0, ROLE_ID) if self.kind_of(item) == "grid" else None

    def target_grid_id(self) -> str | None:
        """The grid this panel points at, for the toolbar's Import DZT (#61).

        In #61's order: the selected grid row; else the grid the selected
        lines share; else the open line's grid; else None. Grid rows or
        lines spread over several grids name none, rather than have one
        picked for them.
        """
        try:
            grid_rows, line_grids = set(), set()
            for item in self.tree.selectedItems():
                key = self.key_of(item)
                if key is not None:
                    line_grids.add(self._grid_of_line(key))
                elif self.kind_of(item) == "grid":
                    grid_rows.add(self.grid_id_of(item))
            line_grids.discard(None)  # a line placed on no grid names none
            for named in (grid_rows, line_grids):
                if len(named) == 1:
                    return named.pop()
            key = self.session.current_key
            if key and is_cut_key(key):
                # An open cut sits on a grid, and importing there is what
                # the same fallback does for an open line.
                return self.session.cut_for_key(key).grid_id
            return self._grid_of_line(key) if key else None
        except Exception as exc:  # noqa: BLE001 -- see the module docstring:
            # reached from a toolbar action's slot. No target is the safe
            # answer: the import dialog falls back to the first grid.
            _log(f"could not read the selected grid: {exc}", Qgis.MessageLevel.Critical)
            return None

    def _grid_of_line(self, key: str) -> str | None:
        line = self.session.line_for_key(key)
        return getattr(line.placement, "grid_id", None)

    def item_for_key(self, key: str) -> QTreeWidgetItem | None:
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            if (self.key_of(item) or self.cut_key_of(item)) == key:
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
        # Open a line only on a plain click. A Ctrl- or Shift-click is
        # building a selection, and opening every line it touches would
        # read each DZT file in turn and keep switching the profile. The
        # selection check alone is not enough: a Ctrl-click with nothing
        # else selected also leaves the line the only thing selected.
        held = QApplication.keyboardModifiers()
        if held & Qt.KeyboardModifier.ControlModifier or held & Qt.KeyboardModifier.ShiftModifier:
            return
        key = self.key_of(item) or self.cut_key_of(item)
        if key is not None and item.isSelected() and len(self.tree.selectedItems()) == 1:
            self._open_line(key)

    def _follow_current(self, key: str) -> None:
        try:
            item = self.item_for_key(key) if key else None
            # Makes `item` the only selected row, moves Qt's Shift anchor to
            # it and announces the selection (see _select_only_announcing).
            self._select_only_announcing(item)
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
            menu = self.context_menu
            menu.clear()
            kind = self.kind_of(item)
            grid_ids, keys = self._selected_targets()
            if (
                kind in ("grid", "line", "cut")
                and item.isSelected()
                and len(self.tree.selectedItems()) > 1
                and (grid_ids or keys)
            ):
                # Right-clicking a grid or line inside a selection acts on
                # the selection. Right-clicking outside one is handled by
                # Qt before this runs: the press selects just that item.
                # Editing and moving are for recorded lines; a selection that
                # holds a cut offers removal only.
                # Only keys the session knows as lines get line items: a
                # selection may carry other kinds of file (magnetometer).
                only_lines = self._line_keys_only(keys) == keys
                gps = [k for k in keys if only_lines and self._is_gps(k)]
                if keys and gps and len(gps) == len(keys):
                    phrase = self._count_phrase(grid_ids, keys)
                    menu.addAction(
                        f"Set destagger for {len(keys)} GPS lines…",
                        lambda: self._request_destagger(keys),
                    )
                    self._add_move_menu(menu, keys, f"Move {phrase} to grid")
                    menu.addAction(
                        f"Fit a grid to these {len(keys)} tracks…",
                        lambda: self._request_fit(keys),
                    )
                elif keys and only_lines:
                    # Tape lines, or tape and GPS lines together.
                    grids = {self._grid_of_line(k) for k in keys}
                    if len(grids) == 1 and None not in grids:
                        grid = str(grids.pop())
                        menu.addAction(
                            f"Edit {self._count_phrase(grid_ids, keys)}…",
                            lambda: self._request_edit(grid, keys),
                        )
                    self._add_move_menu(
                        menu, keys, f"Move {self._count_phrase(grid_ids, keys)} to grid"
                    )
                if keys and only_lines:
                    self._add_bulk_items(menu, keys)
                menu.addSeparator()
                menu.addAction(
                    f"Remove {self._count_phrase(grid_ids, keys)} from site",
                    lambda: self.remove_selected_action(),
                )
            elif kind == "site" or item is None:
                menu.addAction("Add grid…", self.add_grid_requested.emit)
            elif kind == "grid":
                gid = self.grid_id_of(item) or ""
                menu.addAction("Edit grid…", lambda: self.edit_grid_requested.emit(gid))
                edit_lines = menu.addAction("Edit lines…", lambda: self._request_edit(gid, []))
                edit_lines.setEnabled(bool(self.session.keys_on_grid(gid)))
                menu.addAction("Add GPR data…", lambda: self.import_requested.emit(gid))
                menu.addAction("Set velocity…", lambda: self.grid_velocity_requested.emit(gid))
                menu.addSeparator()
                menu.addAction("Remove grid", lambda: self.remove_grid_action(gid))
            elif kind == "cut":
                cut_key = self.cut_key_of(item) or ""
                menu.addAction("Open", lambda: self._open_line(cut_key))
                menu.addAction("Rename cut…", lambda: self.rename_cut_action(cut_key))
                menu.addSeparator()
                menu.addAction("Delete cut", lambda: self.remove_cut_action(cut_key))
            elif kind == "line":
                key = self.key_of(item) or ""
                menu.addAction("Open", lambda: self._open_line(key))
                if self._is_gps(key):
                    # Edit line… is tape-only until M17c.
                    menu.addAction(
                        "Set velocity override…", lambda: self.line_velocity_requested.emit(key)
                    )
                    menu.addAction("Set destagger…", lambda: self._request_destagger([key]))
                    self._add_move_menu(menu, [key], "Move to grid")
                    menu.addAction("Fit a grid to this track…", lambda: self._request_fit([key]))
                else:
                    # Worked out here, inside the guard, not when the action fires.
                    grid = self._grid_of_key(key)
                    menu.addAction("Edit line…", lambda: self._request_edit(grid, [key]))
                    menu.addAction(
                        "Set velocity override…", lambda: self.line_velocity_requested.emit(key)
                    )
                    self._add_move_menu(menu, [key], "Move to grid")
                menu.addSeparator()
                menu.addAction("Remove line from site", lambda: self.remove_line_action(key))
            menu.exec(self.tree.viewport().mapToGlobal(pos))
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not build the survey tree context menu: {exc}", Qgis.MessageLevel.Critical)

    def _grid_of_key(self, key: str) -> str:
        """The grid a line is on, "" for a GPS line in none."""
        return str(getattr(self.session.line_for_key(key).placement, "grid_id", None) or "")

    def _is_gps(self, key: str) -> bool:
        return not is_cut_key(key) and self.session.is_gps_line(key)

    def _request_destagger(self, keys: list[str]) -> None:
        # A menu action's slot: guarded, as _on_context_menu's comment asks.
        try:
            self.destagger_requested.emit(list(keys))
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not open the destagger dialog: {exc}", Qgis.MessageLevel.Critical)

    def _request_fit(self, keys: list[str]) -> None:
        # A menu action's slot: guarded, as _on_context_menu's comment asks.
        try:
            self.fit_tracks_requested.emit(list(keys))
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not start Fit to these tracks: {exc}", Qgis.MessageLevel.Critical)

    def _request_edit(self, grid_id: str, keys: list[str]) -> None:
        # A menu action's slot: guarded, as _on_context_menu's comment asks.
        try:
            self.edit_lines_requested.emit(grid_id, list(keys))
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not open the Edit lines table: {exc}", Qgis.MessageLevel.Critical)

    def _request_move(self, keys: list[str], grid_id: str) -> None:
        try:
            self.move_lines_requested.emit(list(keys), grid_id)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not move the lines: {exc}", Qgis.MessageLevel.Critical)

    def _add_move_menu(self, menu: QMenu, keys: list[str], title: str) -> None:
        """Refill the one reused submenu with every grid, in site order.

        A grid is greyed when every line in `keys` is already on it.
        """
        sub = self.move_menu
        sub.clear()
        sub.setTitle(title)
        on = {k: self._grid_of_key(k) for k in keys}
        site = self.session.site
        for grid in site.grids if site is not None else []:
            action = sub.addAction(grid.id, lambda g=grid.id: self._request_move(keys, g))
            action.setEnabled(any(g != grid.id for g in on.values()))
        # The submenu object is reused, so a gridless site greys it and the
        # next fill (with a grid) wakes it again.
        sub.menuAction().setEnabled(bool(site is not None and site.grids))
        menu.addMenu(sub)

    # ---- one line selection with the map (#57) -----------------------------------
    def _on_selection_changed(self) -> None:
        try:
            if not self._selection_quiet:
                self.line_selection_changed.emit(self.selected_line_keys())
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not announce the line selection: {exc}", Qgis.MessageLevel.Critical)

    def _announce_line_selection(self) -> None:
        self.line_selection_changed.emit(self.selected_line_keys())

    def _rebuild_announcing(self) -> None:
        """`_rebuild` with the tree's selection quiet, then one announcement of
        the selection it ended with, for the map to follow."""
        self._selection_quiet += 1
        try:
            self._rebuild()
        finally:
            self._selection_quiet -= 1
        self._announce_line_selection()

    def _select_only_announcing(self, item: QTreeWidgetItem | None) -> None:
        """Make `item` the current item and the only selected one (an open),
        announcing the result once."""
        self._selection_quiet += 1
        try:
            # Twice on purpose. The bare call is the only one that moves
            # Qt's Shift anchor (a later Shift-click must range from this
            # line); the explicit command then undoes the toggle a held
            # Ctrl would have made of it (see _SELECT_ONLY).
            self.tree.setCurrentItem(item)
            self.tree.setCurrentItem(item, 0, _SELECT_ONLY)
        finally:
            self._selection_quiet -= 1
        self._announce_line_selection()

    def _capture_line_keys(self) -> None:
        self._captured_line_keys = self.selected_line_keys()

    def _restore_line_selection(self) -> bool:
        """Re-select the lines that were selected before a rebuild and are still
        in the site; False (nothing done) when there were none."""
        keys = [k for k in self._captured_line_keys if self.item_for_key(k) is not None]
        self._captured_line_keys = []
        if not keys:
            return False
        open_key = self.session.current_key
        self._select_rows(keys, open_key if open_key in keys else keys[0], unfold=False)
        return True

    def select_lines(self, keys: list[str]) -> None:
        """Make exactly the line rows in `keys` the selection, as the map's
        selection arrives (#57). Opens nothing, announces nothing, and unfolds
        the grids that hold them. Keys that are not line rows are ignored."""
        try:
            self._selection_quiet += 1
            try:
                present = [k for k in keys if self.key_of(self.item_for_key(k)) is not None]
                self._select_rows(present, present[0] if present else None, unfold=True)
            finally:
                self._selection_quiet -= 1
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not select the lines in the tree: {exc}", Qgis.MessageLevel.Critical)

    def _select_rows(self, keys: list[str], current: str | None, *, unfold: bool) -> None:
        """Select exactly the rows of `keys`, with the current item (and so the
        Shift anchor) on `current`. The selection is set through the model with
        explicit flags, so a modifier key held down cannot toggle a row."""
        self._selection_quiet += 1
        try:
            items = [it for it in (self.item_for_key(k) for k in keys) if it is not None]
            for item in items if unfold else []:  # only a selection from the map unfolds
                parent = item.parent()
                if parent is not None:
                    parent.setExpanded(True)
            cur = self.item_for_key(current) if current else None
            if cur is not None:
                self.tree.setCurrentItem(cur)  # moves the anchor; may toggle: fixed below
            chosen = QItemSelection()
            for item in items:
                index = self.tree.indexFromItem(item)
                chosen.select(index, index)
            self.tree.selectionModel().select(
                chosen,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        finally:
            self._selection_quiet -= 1

    # ---- bulk actions on a selection of lines (#58) ----------------------------
    def selected_line_keys(self) -> list[str]:
        """The keys of the selected line rows, in tree order. Grid, cut and site
        rows, and rows already gone from the session, are left out."""
        if not self.session.is_open:  # a site closing: the rows are about to go
            return []
        keys: list[str] = []
        it = QTreeWidgetItemIterator(self.tree, QTreeWidgetItemIterator.IteratorFlag.Selected)
        while it.value():
            key = self.key_of(it.value())
            if key is not None:
                try:
                    self.session.line_for_key(key)
                except KeyError:
                    key = None
                if key is not None:
                    keys.append(key)
            it += 1
        return keys

    @staticmethod
    def _lines_phrase(n: int) -> str:
        return f"{n} line{'s' if n != 1 else ''}"

    def _open_line_key(self) -> str | None:
        """The open line's key; None when nothing, or a cut, is open."""
        key = self.session.current_key
        if not key or is_cut_key(key):
            return None
        try:
            self.session.line_for_key(key)
        except KeyError:
            return None
        return key

    def _add_bulk_items(self, menu: QMenu, keys: list[str]) -> None:
        """Apply preset, Apply steps, Set velocity and Clear velocity override for
        a selection of lines (spec §4.1). Built inside `_on_context_menu`'s guard."""
        lines = self._lines_phrase(len(keys))
        if menu.actions():
            menu.addSeparator()
        sub = self.preset_menu
        sub.clear()
        sub.setTitle(APPLY_PRESET_MENU.format(lines=lines))
        names = self.session.preset_names()
        for name in names:
            sub.addAction(name, lambda n=name: self.apply_preset_action(keys, n))
        menu.addMenu(sub).setEnabled(bool(names))
        open_key = self._open_line_key()
        others = [k for k in keys if k != open_key]
        if open_key is None or not others:
            menu.addAction(APPLY_STEPS_MENU_GREY).setEnabled(False)
        else:
            label = line_label(self.session.line_for_key(open_key))
            menu.addAction(
                APPLY_STEPS_MENU.format(open=label, lines=self._lines_phrase(len(others))),
                lambda: self.apply_steps_action(keys),
            )
        menu.addSeparator()
        menu.addAction(
            SET_VELOCITY_MENU.format(lines=lines), lambda: self._request_bulk_velocity(keys)
        )
        clear = menu.addAction(
            CLEAR_VELOCITY_MENU.format(lines=lines), lambda: self.clear_velocity_action(keys)
        )
        clear.setEnabled(any(self.session.line_for_key(k).velocity is not None for k in keys))

    def _request_bulk_velocity(self, keys: list[str]) -> None:
        try:
            self.bulk_velocity_requested.emit(list(keys))
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not open the velocity dialog: {exc}", Qgis.MessageLevel.Critical)

    def _ask(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(self, title, text)
        return bool(answer == QMessageBox.StandardButton.Yes)

    def apply_preset_action(self, keys: list[str], name: str, *, confirm: bool = True) -> list[str]:
        """Replace the processing of `keys` with preset `name`, after one question.
        A menu action's slot, so guarded. Returns the keys changed."""
        try:
            lines = self._lines_phrase(len(keys))
            if confirm:
                text = APPLY_PRESET_TEXT.format(lines=lines, name=name)
                note = migration_note(self.session.site.presets[name], saved=True)  # type: ignore[union-attr]
                if note:
                    text += "\n\n" + note
                if not self._ask(APPLY_PRESET_TITLE, text):
                    return []
            changed = self.session.apply_preset_to(name, keys)
            self.report.emit(APPLY_PRESET_REPORT.format(name=name, lines=lines))
            return changed
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not apply the preset: {exc}", Qgis.MessageLevel.Critical)
            return []

    def apply_steps_action(self, keys: list[str], *, confirm: bool = True) -> list[str]:
        """Copy the open line's steps onto the rest of `keys`, after one question.
        The open line is left as it is. A menu action's slot, so guarded."""
        try:
            open_key = self._open_line_key()
            if open_key is None:
                return []
            others = [k for k in keys if k != open_key]
            if not others:
                return []
            label = line_label(self.session.line_for_key(open_key))
            if confirm:
                text = APPLY_STEPS_TEXT.format(lines=self._lines_phrase(len(others)), open=label)
                if open_key in keys:
                    text += "\n\n" + APPLY_STEPS_LEFT_TEXT.format(open=label)
                note = migration_note(
                    self.session.stack_for(open_key, insert=False).to_dicts(), saved=False
                )
                if note:
                    text += "\n\n" + note
                if not self._ask(APPLY_STEPS_TITLE, text):
                    return []
            changed = self.session.apply_stack_to(open_key, others)
            self.report.emit(
                APPLY_STEPS_REPORT.format(open=label, lines=self._lines_phrase(len(others)))
            )
            return changed
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not apply the steps: {exc}", Qgis.MessageLevel.Critical)
            return []

    def clear_velocity_action(self, keys: list[str], *, confirm: bool = True) -> list[str]:
        """Clear the velocity override of the lines in `keys` that have one, after
        one question. Saved fits stay. A menu action's slot, so guarded."""
        try:
            having = [k for k in keys if self.session.line_for_key(k).velocity is not None]
            if not having:
                return []
            if confirm:
                text = CLEAR_VELOCITY_TEXT.format(
                    n=len(having), lines=self._lines_phrase(len(keys))
                )
                n_src = sum(
                    1 for k in having if self.session.line_for_key(k).velocity_source is not None
                )
                if n_src == 1:
                    text += "\n\n" + CLEAR_VELOCITY_FITS_ONE_TEXT
                elif n_src:
                    text += "\n\n" + CLEAR_VELOCITY_FITS_TEXT.format(n=n_src)
                if not self._ask(CLEAR_VELOCITY_TITLE, text):
                    return []
            changed = self.session.set_lines_velocity(having, None)
            self.report.emit(CLEAR_VELOCITY_REPORT.format(lines=self._lines_phrase(len(changed))))
            return changed
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not clear the velocity override: {exc}", Qgis.MessageLevel.Critical)
            return []

    def remove_line_action(self, key: str, *, confirm: bool = True) -> None:
        self._remove([], [key], confirm=confirm, title="Remove line")

    def remove_cut_action(self, key: str, *, confirm: bool = True) -> None:
        self._remove([], [key], confirm=confirm, title="Delete cut")

    def rename_cut_action(self, key: str) -> None:
        """Ask for a new name and apply it. A menu action's slot, so guarded."""
        try:
            current = self.session.cut_for_key(key).name
            name, accepted = QInputDialog.getText(self, "Rename cut", "Name", text=current)
            if accepted and name.strip():
                self.session.rename_cut(key, name)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not rename the cut: {exc}", Qgis.MessageLevel.Critical)

    def remove_grid_action(self, grid_id: str, *, confirm: bool = True) -> None:
        self._remove([grid_id], [], confirm=confirm, title="Remove grid")

    def remove_selected_action(self, *, confirm: bool = True) -> None:
        """Remove everything selected in the tree, after one confirmation."""
        grid_ids, keys = self._selected_targets()
        self._remove(grid_ids, keys, confirm=confirm, title="Remove from site")

    def _remove(self, grid_ids: list[str], keys: list[str], *, confirm: bool, title: str) -> None:
        """Remove `grid_ids` (each with its lines) and the lines `keys`.

        Nothing is written to disk here: the session is only marked
        modified, so closing without saving is the undo.
        """
        if not grid_ids and not keys:
            return
        try:
            if confirm:
                buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                # No is the default only when a saved fit would go with the lines (#221).
                default = (
                    QMessageBox.StandardButton.No
                    if self._fits_would_go(grid_ids, keys)
                    else QMessageBox.StandardButton.Yes
                )
                answer = QMessageBox.question(
                    self, title, self._removal_text(grid_ids, keys), buttons, default
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            line_keys = [k for k in keys if not is_cut_key(k)]
            if line_keys:
                self.session.remove_lines(line_keys)
            for cut_key in (k for k in keys if is_cut_key(k)):
                self.session.remove_cut(cut_key)
            for grid_id in grid_ids:
                self.session.remove_grid(grid_id, with_lines=True)
        except (KeyError, ValueError) as exc:
            if confirm:
                QMessageBox.warning(self, title, str(exc))
            else:
                raise

    def _selected_targets(self) -> tuple[list[str], list[str]]:
        """(grid ids, line or cut keys) to remove for the current selection,
        in tree order.

        A selection holding any line removes lines only, every selected
        line whatever its grid. Cuts go only when no line is selected, and
        grids -- each with all its lines and cuts -- only when nothing but
        grids is selected. A Shift-range across grids sweeps up the grid
        and Cuts rows it passes, and removing a grid deletes its geometry as
        well as its lines, so a grid or cut row caught in a range of lines
        must not turn "remove these lines" into "remove that grid or cut".
        """
        # Walked in tree order: selectedItems() is in the order the items
        # were selected, and the prompt lists what goes in tree order.
        items = []
        it = QTreeWidgetItemIterator(self.tree, QTreeWidgetItemIterator.IteratorFlag.Selected)
        while it.value():
            items.append(it.value())
            it += 1
        keys = []
        cut_keys = []
        for item in items:
            key = self.key_of(item)
            cut_key = self.cut_key_of(item)
            try:
                if key is not None:
                    self.session.line_for_key(key)
                    keys.append(key)
                elif cut_key is not None:
                    self.session.cut_for_key(cut_key)
                    cut_keys.append(cut_key)
            except KeyError:
                continue  # already gone from the session: nothing left to remove
        if keys:
            return [], keys
        if cut_keys:
            return [], cut_keys
        return [g for g in (self.grid_id_of(i) for i in items) if g is not None], []

    @staticmethod
    def _count_phrase(grid_ids: list[str], keys: list[str]) -> str:
        if grid_ids:
            if len(grid_ids) == 1:
                return "1 grid and its lines"
            return f"{len(grid_ids)} grids and their lines"
        n_cuts = sum(1 for k in keys if is_cut_key(k))
        n_lines = len(keys) - n_cuts
        phrases = []
        if n_lines:
            phrases.append(f"{n_lines} line{'s' if n_lines != 1 else ''}")
        if n_cuts:
            phrases.append(f"{n_cuts} cut{'s' if n_cuts != 1 else ''}")
        return " and ".join(phrases)

    def _cut_removal_text(self, key: str) -> str:
        """`Delete {name}?`, then what happens to the cut's picks: they stay."""
        text = DELETE_CUT_TEXT.format(name=self.session.cut_for_key(key).name)
        try:
            n = len(self.session.picks_for(key))
        except Exception as exc:  # noqa: BLE001 -- the count is only a courtesy
            _log(f"could not count the cut's picks: {exc}", Qgis.MessageLevel.Warning)
            n = 0
        if n == 1:
            text += CUT_ONE_PICK_TEXT
        elif n:
            text += CUT_PICKS_TEXT.format(n=n)
        return text

    def _grid_cuts_text(self, cut_keys: list[str], *, several: bool) -> str:
        """What a grid removal says about the cuts it takes: how many, and how
        many picks on them stay (cut spec §4.8). Leads with a space, or is
        empty when there are no cuts."""
        n = len(cut_keys)
        if not n:
            return ""
        its = "Their" if several else "Its"
        text = " " + (
            GRID_CUTS_ONE_TEXT.format(its=its) if n == 1 else GRID_CUTS_TEXT.format(its=its, n=n)
        )
        try:
            m = sum(len(self.session.picks_for(k)) for k in cut_keys)
        except Exception as exc:  # noqa: BLE001 -- the count is only a courtesy
            _log(f"could not count the cuts' picks: {exc}", Qgis.MessageLevel.Warning)
            m = 0
        they = "its" if n == 1 else "their"
        if m == 0:
            return text + "."
        if m == 1:
            return text + GRID_CUT_PICK_TAIL.format(they=they)
        return text + GRID_CUT_PICKS_TAIL.format(they=they, m=m)

    def _line_keys_only(self, keys: list[str]) -> list[str]:
        """`keys` that are lines the session knows (not cuts, nor any other
        kind of file a selection may carry), in order."""
        if not self.session.is_open:
            return []
        known = set(self.session.keys())
        return [k for k in keys if k in known]

    def _lines_going(self, grid_ids: list[str], keys: list[str]) -> list[str]:
        """Every line a removal takes: the selected lines and the grids' lines."""
        going = self._line_keys_only(keys)
        for grid_id in grid_ids:
            going += self.session.keys_on_grid(grid_id)
        return going

    def _fits_would_go(self, grid_ids: list[str], keys: list[str]) -> bool:
        try:
            return any(
                self.session.line_for_key(k).velocity_fits
                for k in self._lines_going(grid_ids, keys)
            )
        except Exception as exc:  # noqa: BLE001 -- only picks the default button
            _log(f"could not look for saved fits: {exc}", Qgis.MessageLevel.Warning)
            return False

    def _lost_with_lines_text(self, keys: list[str], *, grid: bool = False) -> str:
        """ "Also removed: ..." -- what goes with `keys` beyond the lines themselves
        (#221). Empty when there is nothing to lose. One line (not a grid's) is
        told in the singular, several as counts."""
        site = self.session.site
        if site is None or not keys:
            return ""
        lines = [self.session.line_for_key(k) for k in keys]
        n_steps = sum(1 for k in keys if len(getattr(site.stacks.get(k), "entries", ())) > 0)
        n_overrides = sum(1 for line in lines if line.velocity is not None)
        fit_counts = [len(line.velocity_fits) for line in lines]
        n_fits, n_fit_lines = sum(fit_counts), sum(1 for n in fit_counts if n)
        parts: list[str] = []
        if len(keys) == 1 and not grid:
            if n_steps:
                parts.append("its processing steps")
            if n_overrides:
                parts.append("its velocity override")
            if n_fits:
                parts.append(f"its {n_fits} saved velocity fit{'s' if n_fits != 1 else ''}")
        else:
            if n_steps:
                parts.append(f"processing steps on {n_steps} of them")
            if n_overrides:
                parts.append(f"velocity override{'s' if n_overrides != 1 else ''} on {n_overrides}")
            if n_fits:
                parts.append(
                    f"{n_fits} saved velocity fit{'s' if n_fits != 1 else ''} on {n_fit_lines}"
                )
        if not parts:
            return ""
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        if len(parts) == 3 and not (len(keys) == 1 and not grid):
            joined = ", ".join(parts[:-1]) + ", and " + parts[-1]
        return ALSO_REMOVED_TEXT.format(parts=joined)

    def _removal_text(self, grid_ids: list[str], keys: list[str]) -> str:
        """The confirmation for a removal: exactly what goes, and what
        does not (#31)."""
        cut_keys = [k for k in keys if is_cut_key(k)]
        keys = [k for k in keys if not is_cut_key(k)]
        if len(cut_keys) == 1 and not keys and not grid_ids:
            return self._cut_removal_text(cut_keys[0])
        things = []
        n_lines = len(keys)
        grid_cut_keys: list[str] = []
        for grid_id in grid_ids:
            grid_cut_keys += self.session.cut_keys_on_grid(grid_id)
            n = len(self.session.keys_on_grid(grid_id))
            n_lines += n
            if n:
                things.append(f"grid {grid_id} and its {n} line{'s' if n != 1 else ''}")
            else:
                things.append(f"grid {grid_id}")
        if len(keys) == 1:
            things.append(keys[0])
        elif keys:
            things.append(f"{len(keys)} lines")
        if len(cut_keys) == 1:
            things.append(self.session.cut_for_key(cut_keys[0]).name)
        elif cut_keys:
            things.append(f"{len(cut_keys)} cuts")
        grid_cuts_text = self._grid_cuts_text(grid_cut_keys, several=len(grid_ids) > 1)
        if len(things) == 1:
            # Appended to the question itself, so "Its" is the grid's.
            parts = [f"Remove {things[0]} from the site?{grid_cuts_text}"]
            grid_cuts_text = ""
        else:
            parts = ["Remove these from the site?\n" + "\n".join(f"• {t}" for t in things)]
        if len(keys) > 1:
            listed = "\n".join(keys[:_LISTED_KEYS])
            if len(keys) > _LISTED_KEYS:
                listed += f"\n… and {len(keys) - _LISTED_KEYS} more"
            parts.append(listed)
        lost = self._lost_with_lines_text(self._lines_going(grid_ids, keys), grid=bool(grid_ids))
        if lost:
            parts.append(lost)
        if n_lines == 1:
            parts.append(
                "The DZT file on disk is not touched, and picks on this line "
                "stay in the picks layer."
            )
        elif n_lines:
            parts.append(
                "The DZT files on disk are not touched, and picks on these lines "
                "stay in the picks layer."
            )
        if grid_cuts_text:
            parts.append(grid_cuts_text.strip())
        elif cut_keys:
            parts.append(CUTS_ONLY_PICKS_TEXT)
        parts.append("Nothing is saved to the site file until you choose Save site.")
        return "\n\n".join(parts)

    # ---- keyboard ----------------------------------------------------------
    def eventFilter(self, obj: QObject, event: Any) -> bool:  # noqa: N802 -- Qt's own name
        """Delete (or Backspace) on the tree removes the selection.

        Claims the bare key in `ShortcutOverride` as well as acting on
        `KeyPress`: QGIS binds keys of its own application-wide, and a
        shortcut is matched before the focused widget ever sees the key
        press. Accepting the override is how a focused widget says "this
        key is mine" (QLineEdit does the same for its editing keys), so
        while the tree has focus Delete removes from the tree and nothing
        else. With a modifier held the key is left alone.

        A Qt-invoked virtual: an exception escaping it is swallowed
        locally and reaches `qFatal()` in the CI container (see the
        module docstring), so the body is guarded.
        """
        try:
            kind = event.type()
            if (
                obj is self.tree
                and kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)
                and event.key() in _DELETE_KEYS
                and not any(event.modifiers() & m for m in _CHORD_MODIFIERS)
            ):
                if kind == QEvent.Type.ShortcutOverride:
                    event.accept()
                else:
                    self.remove_selected_action()
                return True
        except Exception as exc:  # noqa: BLE001 -- see the docstring
            _log(f"could not remove the selection: {exc}", Qgis.MessageLevel.Critical)
            return False
        return super().eventFilter(obj, event)
