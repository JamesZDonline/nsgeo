"""Add data ▸ GPR…: one modeless dialog, two pages (M17b, #134, decision 15).

The Grid page places DZT files by a grid's tapes (what Import DZT… did), the
GPS page by their RTK tracks (what Import GPS lines… did). A "Place lines by:
Grid | GPS" switch swaps the pages; the files carry across, so choosing the
other way never means adding them again. Each page keeps its own `status`
line; this dialog owns the switch, the GPS-available note and the button box,
and takes the Import button's text and enabled state from the current page.

Modeless like GridDialog (plugin.py's open_add_data_dialog is the pattern; its
module docstring says why every slot guards its own body): the toolbar and the
Survey panel stay clickable while it is open, so each page re-checks the site
before it writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from nsgeo.project import ProjectError
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsPointXY,
    QgsProject,
    QgsSettings,
)
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.gps_import import count_with_gps
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.gps_import_dialog import GpsImportPage
from nsgeo_qgis.ui.grid_overlay import GridOverlay
from nsgeo_qgis.ui.import_dialog import GridImportPage

if TYPE_CHECKING:
    from qgis.gui import QgsMapCanvas

GRID, GPS = "grid", "gps"
MODE_KEY = "nsgeo/addDataMode"  # QgsSettings; absent means GRID (decision 15)
GPS_NOTE_MANY = "{n} of {m} files have a GPS log beside them."
GPS_NOTE_ONE = "This file has a GPS log beside it."


def remembered_mode() -> str:
    value = QgsSettings().value(MODE_KEY, GRID)
    return value if value in (GRID, GPS) else GRID


def opening_mode(session: SiteSession, grid_id: str | None) -> str:
    """Decision 15: a grid whose lines are all GPS opens on GPS, all tape on
    Grid; a grid with no lines, a mix, no grid at all: the remembered mode."""
    if grid_id:
        try:
            keys = session.keys_on_grid(grid_id)
            kinds = {session.is_gps_line(k) for k in keys}
        except (KeyError, ProjectError):
            kinds = set()
        if kinds == {True}:
            return GPS
        if kinds == {False}:
            return GRID
    return remembered_mode()


class AddDataDialog(QDialog):
    #: One batch per Import: (text, is_warning). The first is plain news.
    imported = pyqtSignal(list)

    def __init__(
        self,
        session: SiteSession,
        *,
        grid_id: str | None = None,
        mode: str | None = None,
        canvas: QgsMapCanvas | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.canvas = canvas
        #: The new grid the GPS page would make, dashed on the map while this
        #: dialog is open (disposed whenever it finishes).
        self.overlay: GridOverlay | None = None if canvas is None else GridOverlay(canvas)
        self._gps_key: tuple[Path, ...] | None = None
        self._gps_count = 0
        self.resize(900, 560)
        layout = QVBoxLayout(self)

        switch = QHBoxLayout()
        switch.addWidget(QLabel("Place lines by"))
        self.grid_button = QPushButton("Grid")
        self.gps_button = QPushButton("GPS")
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for b in (self.grid_button, self.gps_button):
            b.setCheckable(True)
            self._group.addButton(b)
            switch.addWidget(b)
        self.gps_note = QLabel("")
        self.gps_note.setStyleSheet("color: gray;")
        self.gps_note.setVisible(False)
        switch.addWidget(self.gps_note, 1)
        layout.addLayout(switch)

        self.grid_page = GridImportPage(session, grid_id=grid_id)
        self.gps_page = GpsImportPage(session)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.grid_page)
        self.stack.addWidget(self.gps_page)
        layout.addWidget(self.stack, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert ok is not None
        self.import_button: QPushButton = ok
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.grid_button.clicked.connect(lambda: self._switch(GRID))
        self.gps_button.clicked.connect(lambda: self._switch(GPS))
        if grid_id:
            self.gps_page.retarget(grid_id)
        self.grid_page.changed.connect(self._page_changed)
        self.gps_page.changed.connect(self._page_changed)
        if canvas is not None:
            canvas.destinationCrsChanged.connect(self._update_preview)
        self.finished.connect(self.dispose_overlay)
        self._mode = mode if mode in (GRID, GPS) else remembered_mode()
        self._show_mode()

    # ---- the switch -----------------------------------------------------------
    def mode(self) -> str:
        return self._mode

    def _page(self) -> Any:
        return self.grid_page if self._mode == GRID else self.gps_page

    def _switch(self, mode: str) -> None:
        # A slot (clicked): see plugin.py's module docstring.
        try:
            self.set_mode(mode)
        except Exception as exc:  # noqa: BLE001 -- a slot (clicked)
            self._page().status.setText(f"could not switch: {exc}")

    def set_mode(self, mode: str) -> None:
        """Show the page for `mode`, carrying the file list across."""
        if mode not in (GRID, GPS):
            raise ValueError(f"unknown mode {mode!r}")
        if mode != self._mode:
            src = self._page()
            self._mode = mode
            self._page().set_files(src.paths())
        self._show_mode()

    def _show_mode(self) -> None:
        grid = self._mode == GRID
        self.stack.setCurrentWidget(self.grid_page if grid else self.gps_page)
        self.grid_button.setChecked(grid)
        self.gps_button.setChecked(not grid)
        self._page_changed()

    def _page_changed(self) -> None:
        # A slot (the pages' `changed`): a failure here must not stop the page.
        try:
            page = self._page()
            self.setWindowTitle(page.title())
            self.import_button.setText(page.import_text())
            self.import_button.setEnabled(page.can_import())
            self._update_note()
            self._update_preview()
        except Exception as exc:  # noqa: BLE001 -- a slot: see plugin.py's module docstring
            self._page().status.setText(f"could not update the dialog: {exc}")

    # ---- the preview -----------------------------------------------------------
    def _update_preview(self, *_: Any) -> None:
        """Draw the grid the GPS page would make, or nothing. A slot
        (`destinationCrsChanged`, the pages' `changed`): never raises."""
        overlay = self.overlay
        if overlay is None or overlay.disposed:
            return
        try:
            outline = None
            if self._mode == GPS and self.gps_page.target() is None:
                outline = self._outline(self.gps_page.proposal())
            overlay.set_grid(outline)
        except Exception as exc:  # noqa: BLE001 -- a slot: see plugin.py's module docstring
            overlay.set_grid(None)
            self.gps_page.status.setText(f"could not draw the preview: {exc}")

    def _outline(self, grid: Any) -> list[QgsPointXY] | None:
        """`grid`'s four corners in the canvas CRS, None when it cannot be placed there."""
        if grid is None or self.canvas is None:
            return None
        world = grid.to_world(
            np.array(
                [[0, 0], [grid.size_x, 0], [grid.size_x, grid.size_y], [0, grid.size_y]],
                dtype=float,
            )
        )
        points = [QgsPointXY(float(x), float(y)) for x, y in world]
        target = self.canvas.mapSettings().destinationCrs()
        source = QgsCoordinateReferenceSystem(grid.crs)
        if source != target:
            try:
                xform = QgsCoordinateTransform(source, target, QgsProject.instance())
                points = [xform.transform(p) for p in points]
            except QgsCsException:
                return None
        return points

    def dispose_overlay(self, *_: Any) -> None:
        """Take the preview off the map (idempotent). Also a slot on `finished`."""
        try:
            if self.overlay is not None:
                self.overlay.dispose()
        except Exception:  # noqa: BLE001 -- a slot (finished): nothing to report to
            pass

    def _update_note(self) -> None:
        """The GPS-available note: Grid mode only, from the Grid page's paths."""
        paths = tuple(self.grid_page.paths())
        if paths != self._gps_key:  # reading each DZG is not free: only when the list moved
            self._gps_key = paths
            self._gps_count = count_with_gps(paths)
        n, m = self._gps_count, len(paths)
        text = ""
        if n:
            text = GPS_NOTE_ONE if m == 1 else GPS_NOTE_MANY.format(n=n, m=m)
        self.gps_note.setText(text)
        self.gps_note.setVisible(self._mode == GRID and bool(text))

    # ---- files and target --------------------------------------------------------
    def add_files(self, paths: list[Path]) -> None:
        self._page().add_files(paths)

    def retarget(self, grid_id: str) -> None:
        """Point the dialog at `grid_id`, but only while it has no files (or no
        grid yet: the files then wait for one)."""
        if self._page().paths() and self.grid_page.grid_combo.currentData():
            return
        self.grid_page.retarget(grid_id)
        if not self.gps_page.paths():
            self.gps_page.retarget(grid_id)

    # ---- import ------------------------------------------------------------------
    def accept(self) -> None:
        # Reached from buttons.accepted (a signal) as well as called
        # directly, so every failure reports through the page's status line.
        page = self._page()
        try:
            if not page.import_lines():
                return
            QgsSettings().setValue(MODE_KEY, self._mode)
            self.imported.emit(list(page.messages))
        except Exception as exc:  # noqa: BLE001 -- a slot: see plugin.py's module docstring
            page.status.setText(f"could not import: {exc}")
            return
        super().accept()
