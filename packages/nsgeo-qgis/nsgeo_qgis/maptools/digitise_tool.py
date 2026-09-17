"""Two clicks define a grid frame: the origin, then a point along +Y.

The rubber band is not the tool's to keep. `QgsRubberBand(canvas)` is a
`QgsMapCanvasItem`, and its constructor hands it to the canvas's
`QGraphicsScene`, which owns it from then on -- dropping every Python
reference to the tool and collecting does not free it. Since `plugin.py`
builds a fresh tool per digitise attempt, the tool needs an explicit
`dispose()` that takes the band back off the scene, and `plugin.py` has to
call it from every path that finishes with a tool. See `dispose()` for why
that is not `deactivate()`.
"""

from __future__ import annotations

from qgis.core import QgsPointXY
from qgis.gui import QgsMapCanvas, QgsMapToolEmitPoint, QgsRubberBand
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor


class DigitiseGridTool(QgsMapToolEmitPoint):
    points_picked = pyqtSignal(QgsPointXY, QgsPointXY)
    cancelled = pyqtSignal()

    def __init__(self, canvas: QgsMapCanvas) -> None:
        super().__init__(canvas)
        self._origin: QgsPointXY | None = None
        self._finished = False
        self._band: QgsRubberBand | None = QgsRubberBand(canvas)
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
            # Every self._band access is guarded: dispose() can have run
            # already (see it for why), and an AttributeError raised out
            # of a canvasClicked slot is swallowed by Qt -- the tool
            # would simply stop responding to clicks with no message.
            if self._band is not None:
                self._band.reset()
                self._band.addPoint(self._origin)
            return
        origin, self._origin = self._origin, None
        if self._band is not None:
            self._band.reset()
        self._finished = True
        self.points_picked.emit(origin, QgsPointXY(point))

    def reset(self) -> None:
        self._origin = None
        if self._band is not None:
            self._band.reset()

    def dispose(self) -> None:
        """Take the rubber band back off the canvas's scene, for good.

        Final review, I4: nothing ever did, so every "Digitise on map"
        click left one more invisible `QgsRubberBand` (reset() clears the
        geometry, not the item) parked in the scene for the life of the
        QGIS session -- the very object `plugin.py`'s round-1 note
        implicates in a shutdown segfault "once enough of them pile up
        alongside a QgsMapCanvas".

        Deliberately NOT called from `deactivate()`: that fires on every
        map-tool switch, after which the same tool can legitimately be
        set on the canvas again, and a tool that threw its band away on
        the way out would come back with nothing to draw with. Disposal
        means "this tool is finished", which only `plugin.py`'s
        finalisers know.

        Idempotent, because more than one finaliser can reach the same
        tool. `band.scene()` rather than `self.canvas().scene()`: it
        removes the band from whatever scene actually holds it, and does
        not assume the canvas is still alive.
        """
        band, self._band = self._band, None
        if band is None or sip.isdeleted(band):
            return
        scene = band.scene()
        if scene is not None:
            # removeItem() hands ownership back to us, so dropping the
            # last reference (done above) is what actually frees it.
            scene.removeItem(band)

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
