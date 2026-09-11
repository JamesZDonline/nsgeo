"""Two clicks define a grid frame: the origin, then a point along +Y."""

from __future__ import annotations

from qgis.core import QgsPointXY
from qgis.gui import QgsMapCanvas, QgsMapToolEmitPoint, QgsRubberBand
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor


class DigitiseGridTool(QgsMapToolEmitPoint):
    points_picked = pyqtSignal(QgsPointXY, QgsPointXY)

    def __init__(self, canvas: QgsMapCanvas) -> None:
        super().__init__(canvas)
        self._origin: QgsPointXY | None = None
        self._band = QgsRubberBand(canvas)
        self._band.setColor(QColor(48, 140, 198))
        self._band.setWidth(2)
        self.canvasClicked.connect(self._on_click)

    def _on_click(self, point: QgsPointXY, _button: int) -> None:
        if self._origin is None:
            self._origin = QgsPointXY(point)
            self._band.reset()
            self._band.addPoint(self._origin)
            return
        origin, self._origin = self._origin, None
        self._band.reset()
        self.points_picked.emit(origin, QgsPointXY(point))

    def reset(self) -> None:
        self._origin = None
        self._band.reset()

    def deactivate(self) -> None:
        self.reset()
        super().deactivate()
