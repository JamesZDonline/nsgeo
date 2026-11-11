"""Draw a cut on the map: left-click to add points, right-click or Enter to finish (cut spec §4.1).

`plugin.py` builds one tool when the Cut toggle goes on and keeps it for as
long as the toggle stays on, so each finished path starts the next cut
(`drawn` fires once per cut). The tool never touches the session or the
message bar: it hands over the points, in the canvas CRS, and the plugin
decides which grid they land on (`NsgeoPlugin._on_cut_drawn`).

* **Keys.** Enter/Return finishes, Backspace drops the last point, Esc drops
  the whole path. Esc is `ignore()`d to consume it, as `PickPointTool` does:
  `QgsMapCanvas` hands a key press over already accepted and carries on with
  its own handling unless the tool ignores it (see `pick_tool.py`'s module
  docstring for the trap).
* **The drawing.** One `QgsRubberBand` holds the points clicked so far plus a
  moving last segment to the pointer. It is a `QgsMapCanvasItem`, which the
  canvas's scene owns, so `dispose()` takes it back off the scene; leaving the
  canvas (`deactivate`) only empties it, since the same tool can be set again.
* **Guarding.** Every Qt-invoked method guards its own body and reports through
  `failed`: an exception there never reaches a caller (see `pick_tool.py`).

Qt only through `qgis.PyQt`.
"""

from __future__ import annotations

from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent, QgsMapTool, QgsRubberBand
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QCursor, QKeyEvent

PATH_COLOUR = QColor("#e6550d")  # the cuts layer's own colour (cut spec §4.8)
PATH_WIDTH_PX = 2


class CutTool(QgsMapTool):
    """Collects the points of one cut at a time and emits them when it is finished."""

    #: The finished path: a list of `QgsPointXY` in the canvas CRS, at least one.
    drawn = pyqtSignal(list)
    #: A method Qt called failed; the text says how (see the module docstring).
    failed = pyqtSignal(str)

    def __init__(self, canvas: QgsMapCanvas) -> None:
        super().__init__(canvas)
        self._points: list[QgsPointXY] = []
        self._band: QgsRubberBand | None = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._band.setColor(PATH_COLOUR)
        self._band.setWidth(PATH_WIDTH_PX)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    @property
    def band(self) -> QgsRubberBand:
        """The drawn path (a test reads its vertices)."""
        assert self._band is not None, "disposed"
        return self._band

    @property
    def points(self) -> list[QgsPointXY]:
        return list(self._points)

    # ---- the drawing ------------------------------------------------------
    def _redraw(self, cursor: QgsPointXY | None = None) -> None:
        band = self._band
        if band is None:
            return  # disposed: draw nothing more
        shown = list(self._points)
        if cursor is not None and shown:
            shown.append(cursor)
        if len(shown) < 2:
            band.reset(QgsWkbTypes.LineGeometry)
            return
        band.setToGeometry(QgsGeometry.fromPolylineXY(shown), None)

    def _add_point(self, point: QgsPointXY) -> None:
        self._points.append(QgsPointXY(point))
        self._redraw()

    def _finish(self) -> None:
        points, self._points = self._points, []
        self._redraw()
        if points:
            self.drawn.emit(points)

    def _cancel(self) -> None:
        self._points = []
        self._redraw()

    # ---- Qt-invoked: each guards its own body -----------------------------
    def canvasMoveEvent(self, e: QgsMapMouseEvent) -> None:  # noqa: N802 -- Qt's name
        try:
            if self._points:
                self._redraw(QgsPointXY(e.mapPoint()))
        except Exception as exc:  # noqa: BLE001 -- Qt-invoked: see the module docstring
            self.failed.emit(f"the cut could not be drawn: {exc}")

    def canvasReleaseEvent(self, e: QgsMapMouseEvent) -> None:  # noqa: N802 -- Qt's name
        try:
            button = e.button()
            if button == Qt.MouseButton.LeftButton:
                self._add_point(QgsPointXY(e.mapPoint()))
            elif button == Qt.MouseButton.RightButton:
                self._finish()
        except Exception as exc:  # noqa: BLE001 -- Qt-invoked: see the module docstring
            self.failed.emit(f"the click could not be read: {exc}")

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802 -- Qt's name
        try:
            key = e.key()
            if key == Qt.Key.Key_Escape:
                e.ignore()  # consumed: see the module docstring
                self._cancel()
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._finish()
            elif key == Qt.Key.Key_Backspace:
                if self._points:
                    self._points.pop()
                    self._redraw()
        except Exception as exc:  # noqa: BLE001 -- Qt-invoked: see the module docstring
            self.failed.emit(f"the key could not be read: {exc}")

    def deactivate(self) -> None:
        failure = ""
        try:
            self._cancel()  # a path half drawn is dropped when another tool takes over
        except Exception as exc:  # noqa: BLE001 -- Qt-invoked: see the module docstring
            failure = f"the cut could not be cleared: {exc}"
        super().deactivate()
        if failure:
            self.failed.emit(failure)

    # ---- lifecycle ----------------------------------------------------------
    def dispose(self) -> None:
        """Take the drawing off the map, for good. Idempotent.

        Not called from `deactivate()`: that fires on every map-tool switch,
        and the same tool can be set again. The band is a canvas item owned
        by the canvas's scene, so dropping the reference would leak it; this
        removes it from whatever scene holds it, without assuming the canvas
        is still alive (as `MapLink.dispose` does).
        """
        band, self._band = self._band, None
        self._points = []
        if band is None or sip.isdeleted(band):
            return
        scene = band.scene()
        if scene is not None:
            scene.removeItem(band)
