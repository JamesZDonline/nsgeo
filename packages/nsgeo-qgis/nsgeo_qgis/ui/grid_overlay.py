"""The grid dialog's marks on the map: corner tags, the chosen polygon, the grid.

One `QgsMapCanvasItem` draws everything, so there is a single thing in the
canvas's scene to take back when the dialog finishes (spec 4.8). Nothing is
added to the project or the layer tree. Every point handed in is already in
the canvas CRS, and each corner comes with its tag text; `GridDialog` does the transforming.

The item covers the whole canvas and draws in canvas pixels
(`toCanvasCoordinates`), so a pan, zoom or rotation needs no more than the
repaint the canvas already asks for. `paint` is called by Qt, so it guards
its own body: a bad payload logs once and leaves the map unmarked.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from qgis.core import Qgis, QgsMessageLog, QgsPointXY
from qgis.gui import QgsMapCanvas, QgsMapCanvasItem
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPen, QPolygonF

from nsgeo_qgis.lookup import CORNER_ROLES

TAG_COLOUR = QColor(255, 0, 255)  # magenta, as in the mock-up
TAG_TEXT = QColor(255, 255, 255)
GRID_COLOUR = QColor(0, 80, 255)
POLYGON_COLOUR = QColor(255, 0, 255)
ARROW_FRACTION = 0.6  # the arrow runs this far along the origin-to-+Y edge

Corners = Sequence["tuple[QgsPointXY, str] | None"]


def tag_text(role: str, source: str) -> str:
    """The tag on a corner: the role, and the polygon vertex it came from."""
    if source.startswith("v") and source[1:2].isdigit():
        return f"{role} · {source}"
    return role


class _OverlayItem(QgsMapCanvasItem):
    def __init__(self, canvas: QgsMapCanvas) -> None:
        super().__init__(canvas)
        self._canvas = canvas
        self.corners: list[tuple[QgsPointXY, str] | None] = [None] * len(CORNER_ROLES)
        self.polygon: list[QgsPointXY] | None = None
        self.grid: list[QgsPointXY] | None = None
        self._logged = False
        self.setZValue(1000)

    # ---- geometry: the whole canvas, in pixels -----------------------------
    def boundingRect(self) -> QRectF:  # noqa: N802 -- Qt's name
        try:
            return QRectF(0, 0, self._canvas.width(), self._canvas.height())
        except RuntimeError:
            return QRectF()

    def updatePosition(self) -> None:  # noqa: N802 -- Qt's name
        try:
            self.prepareGeometryChange()
            self.setPos(0, 0)
        except RuntimeError:
            pass

    # ---- painting ----------------------------------------------------------
    def _px(self, point: QgsPointXY) -> QPointF:
        p = self.toCanvasCoordinates(point)
        return QPointF(p.x(), p.y())

    def paint(self, painter: QPainter, _option: Any = None, _widget: Any = None) -> None:
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self.polygon:
                painter.setPen(QPen(POLYGON_COLOUR, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolygon(QPolygonF([self._px(p) for p in self.polygon]))
            if self.grid:
                painter.setPen(QPen(GRID_COLOUR, 2, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolygon(QPolygonF([self._px(p) for p in self.grid]))
                self._paint_arrow(painter)
            self._paint_tags(painter)
        except Exception as exc:  # noqa: BLE001 -- Qt-invoked: log, never raise
            if not self._logged:
                self._logged = True
                QgsMessageLog.logMessage(
                    f"grid overlay could not paint: {exc}", "nsgeo", Qgis.MessageLevel.Warning
                )

    def _paint_arrow(self, painter: QPainter) -> None:
        assert self.grid is not None
        start, end = self._px(self.grid[0]), self._px(self.grid[3])
        tip = QPointF(
            start.x() + (end.x() - start.x()) * ARROW_FRACTION,
            start.y() + (end.y() - start.y()) * ARROW_FRACTION,
        )
        dx, dy = tip.x() - start.x(), tip.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 1.0:
            return
        painter.setPen(QPen(TAG_COLOUR, 2))
        painter.drawLine(start, tip)
        ux, uy = dx / length, dy / length
        head = min(12.0, length / 2)
        for sign in (1, -1):
            wing = QPointF(
                tip.x() - head * (ux * math.cos(0.5) - sign * uy * math.sin(0.5)),
                tip.y() - head * (uy * math.cos(0.5) + sign * ux * math.sin(0.5)),
            )
            painter.drawLine(tip, wing)

    def _paint_tags(self, painter: QPainter) -> None:
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        for entry in self.corners:
            if entry is None:
                continue
            point, text = entry
            at = self._px(point)
            painter.setPen(QPen(TAG_COLOUR, 1))
            painter.setBrush(TAG_COLOUR)
            painter.drawEllipse(at, 4.0, 4.0)
            box = QRectF(
                at.x() + 7, at.y() - 18, metrics.horizontalAdvance(text) + 8, metrics.height() + 2
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(TAG_TEXT)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


class GridOverlay:
    """What the grid dialog shows on the map; `GridDialog` owns one.

    `corners`, `polygon` and `grid` hold the last values set, in the canvas
    CRS. After `dispose()` the setters do nothing.
    """

    def __init__(self, canvas: QgsMapCanvas) -> None:
        self.item: _OverlayItem | None = _OverlayItem(canvas)
        self.corners: list[tuple[QgsPointXY, str] | None] = [None] * len(CORNER_ROLES)
        self.polygon: list[QgsPointXY] | None = None
        self.grid: list[QgsPointXY] | None = None

    @property
    def disposed(self) -> bool:
        return self.item is None

    def _redraw(self) -> None:
        item = self.item
        if item is None or sip.isdeleted(item):
            return
        item.corners, item.polygon, item.grid = self.corners, self.polygon, self.grid
        item.update()

    def set_corners(self, corners: Corners) -> None:
        if self.item is None:
            return
        self.corners = list(corners)
        self._redraw()

    def set_polygon(self, ring: Sequence[QgsPointXY] | None) -> None:
        if self.item is None:
            return
        self.polygon = None if ring is None else list(ring)
        self._redraw()

    def set_grid(self, corners: Sequence[QgsPointXY] | None) -> None:
        if self.item is None:
            return
        self.grid = None if corners is None else list(corners)
        self._redraw()

    def dispose(self) -> None:
        """Take the item off the map for good. Idempotent.

        Goes through `item.scene()`, not `canvas.scene()`, so it does not
        assume the canvas is still alive.
        """
        item, self.item = self.item, None
        if item is None or sip.isdeleted(item):
            return
        try:
            scene = item.scene()
            if scene is not None:
                scene.removeItem(item)
        except RuntimeError:
            pass
        sip.delete(item)
