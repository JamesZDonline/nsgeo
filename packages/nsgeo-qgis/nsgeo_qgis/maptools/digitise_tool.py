"""Two clicks define a grid frame: the origin, then a point along +Y."""

from __future__ import annotations

from qgis.core import QgsPointXY
from qgis.gui import QgsMapCanvas, QgsMapToolEmitPoint, QgsRubberBand
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor


class DigitiseGridTool(QgsMapToolEmitPoint):
    points_picked = pyqtSignal(QgsPointXY, QgsPointXY)
    cancelled = pyqtSignal()

    def __init__(self, canvas: QgsMapCanvas) -> None:
        super().__init__(canvas)
        self._origin: QgsPointXY | None = None
        self._finished = False
        self._band = QgsRubberBand(canvas)
        self._band.setColor(QColor(48, 140, 198))
        self._band.setWidth(2)
        self.canvasClicked.connect(self._on_click)

    def _on_click(self, point: QgsPointXY, button: Qt.MouseButton) -> None:
        if button == Qt.MouseButton.RightButton:
            # The universal QGIS "abort this tool" gesture. Left
            # unhandled, a right-click was just another click: it could
            # set the origin, or -- worse -- complete the pick and
            # define the grid's +Y edge wherever the cursor happened to
            # land. unsetMapTool() triggers deactivate() below, which is
            # what actually signals the cancellation.
            self.canvas().unsetMapTool(self)
            return
        if self._origin is None:
            self._origin = QgsPointXY(point)
            self._band.reset()
            self._band.addPoint(self._origin)
            return
        origin, self._origin = self._origin, None
        self._band.reset()
        self._finished = True
        self.points_picked.emit(origin, QgsPointXY(point))

    def reset(self) -> None:
        self._origin = None
        self._band.reset()

    def deactivate(self) -> None:
        self.reset()
        super().deactivate()
        if not self._finished:
            # Deactivated without ever completing a pick -- the
            # right-click abort above, or the user switching to a
            # different map tool entirely (QgsMapCanvas.setMapTool()
            # calls the outgoing tool's deactivate() same as
            # unsetMapTool() does). Either way, nothing else notices:
            # before this, the dialog stayed hidden with its exec() loop
            # still running and the only way out was killing QGIS.
            self._finished = True  # guard against a second deactivate()
            self.cancelled.emit()
