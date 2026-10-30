"""One click on the map: a grid corner, snapped, or a polygon feature (#63).

`plugin.py` builds a fresh tool for each pick and listens to its signals;
the tool itself never touches the grid dialog or the message bar.

Snapping (spec C2) is the tool's own. It owns a `QgsMapCanvasSnappingUtils`
with its own `QgsSnappingConfig` (enabled, all layers, vertices,
`SNAP_TOLERANCE_PX` pixels), so the project's snapping settings are neither
read nor changed, and only layers in `canvas.layers()` are considered: the
utils take their layers from the canvas's map settings and follow them as
they change. Point features beat vertices in two passes -- the first
accepts only point layers, the second, used only when the first finds
nothing, every layer -- so a GPS fix wins over a drawn polygon's corner
whenever both are in range.

The marker and the label. A `QgsSnapIndicator` shows the match as the cursor
moves; its marker is a `QgsMapCanvasItem`, which belongs to the canvas's
`QGraphicsScene` and is not freed by dropping the tool (the hazard the
two-click tool this replaced had with its rubber band -- see `plugin.py`'s
`_finish_with_pick_tool`).
The indicator creates the marker on a match and deletes it again on an empty
match, so `deactivate()` (the tool leaving the canvas) clears it, and
`dispose()` (the tool finished for good) clears it and drops the indicator.
The label naming the target is a `QToolTip` beside the marker, not a canvas
item, so the marker is the only thing this tool ever puts in the scene. The
click uses the match the indicator showed when it lands on the same pixel as
the last move, over the same view, so what the label named is what the row
gets; after a pan or a CRS change with the cursor still (the same pixel,
different ground) it snaps afresh.

Verified traps (QGIS 3.44):

- QgsMapCanvas hands a key press to the map tool already *accepted*, and
  carries on with its own handling (arrow keys pan, and so on) unless the
  tool *ignores* it -- the reverse of Qt's usual convention. A tool that
  accept()s Esc still sees the canvas emit `keyPressed`; one that
  ignore()s it does not. So Esc is ignore()d to consume it, and every other
  key is left alone for the canvas.
- `cancelled` is emitted from inside `deactivate()`, while the canvas is
  part-way through switching tools (`canvas.mapTool()` is still this tool
  there when the switch came from `setMapTool()`): a handler must not call
  `unsetMapTool()` again.
- An exception raised inside a method Qt calls (`canvasMoveEvent`,
  `canvasReleaseEvent`, `keyPressEvent`, `deactivate`) never reaches the
  caller -- this build prints it and carries on, CI's aborts (see
  `plugin.py`'s module docstring). Each of those guards its own body and
  reports through `failed`, which `plugin.py` turns into a message and the
  end of the pick.
- `polygon_picked` carries the feature id as a qint64: a `pyqtSignal`
  declared `int` is a C++ int, and a feature id past 2**31 arrived
  silently wrapped (2**31 + 7 came through as -2147483641) -- a different
  feature.
"""

from __future__ import annotations

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsFeatureRequest,
    QgsGeometry,
    QgsMapToPixel,
    QgsPointLocator,
    QgsPointXY,
    QgsRectangle,
    QgsSnappingConfig,
    QgsVectorLayer,
    QgsVectorLayerUtils,
)
from qgis.gui import (
    QgsMapCanvas,
    QgsMapCanvasSnappingUtils,
    QgsMapMouseEvent,
    QgsMapTool,
    QgsSnapIndicator,
)
from qgis.PyQt.QtCore import QPoint, Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QKeyEvent
from qgis.PyQt.QtWidgets import QToolTip

#: The snap radius, in screen pixels whatever the zoom (spec C2: QGIS's
#: usual default; a constant so the walkthrough can tune it).
SNAP_TOLERANCE_PX = 12

#: The label of a click with nothing in range.
FREE_CLICK = "free click"

MODES = ("point", "polygon")

#: A canvas view, as `PickPointTool._view` reads it: the map-to-pixel
#: transform (extent, scale, rotation) and the CRS.
_View = tuple[QgsMapToPixel, QgsCoordinateReferenceSystem]


class _PointLayersOnly(QgsPointLocator.MatchFilter):
    """The first snapping pass: matches on point layers only (C2)."""

    def acceptMatch(self, match: QgsPointLocator.Match) -> bool:  # noqa: N802 -- Qt's name
        layer = match.layer()
        return layer is not None and layer.geometryType() == Qgis.GeometryType.Point


def _snapping_config() -> QgsSnappingConfig:
    config = QgsSnappingConfig()
    config.setEnabled(True)
    config.setMode(Qgis.SnappingMode.AllLayers)
    config.setTypeFlag(Qgis.SnappingType.Vertex)
    config.setTolerance(SNAP_TOLERANCE_PX)
    config.setUnits(Qgis.MapToolUnit.Pixels)
    return config


class PickPointTool(QgsMapTool):
    """A map tool for one click: a corner (mode "point") or a polygon
    feature (mode "polygon").

    Point mode snaps (see the module docstring) and emits `picked` with the
    point in the canvas CRS and a label naming what it snapped to
    (`"G4 · gps"`) or `"free click"`. Polygon mode emits `polygon_picked`
    with the topmost polygon feature under the click; a click on no polygon
    emits nothing. In both modes a right-click emits `skipped` and Esc
    `stopped`; what those mean is the caller's to decide. Leaving the canvas
    before `finish()` emits `cancelled`, once.
    """

    picked = pyqtSignal(QgsPointXY, str)
    polygon_picked = pyqtSignal(object, "qint64")
    skipped = pyqtSignal()
    stopped = pyqtSignal()
    cancelled = pyqtSignal()
    #: A method Qt called failed; the text says how (see the module docstring).
    failed = pyqtSignal(str)

    def __init__(self, canvas: QgsMapCanvas, mode: str = "point") -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        super().__init__(canvas)
        self.mode = mode
        #: The target under the cursor, as the label names it, or "".
        self.snap_label = ""
        self._finished = False
        # The last move: its pixel and view, and the point and label it
        # snapped to.
        self._hover: tuple[QPoint, _View, QgsPointXY, str] | None = None
        self._tip: QgsPointXY | None = None  # where the label is showing
        self._points_only = _PointLayersOnly()  # kept: C++ holds it by pointer
        self._snapping = QgsMapCanvasSnappingUtils(canvas, self)
        self._snapping.setConfig(_snapping_config())
        self._indicator: QgsSnapIndicator | None = QgsSnapIndicator(canvas)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    # ---- snapping ---------------------------------------------------------
    def _snap(self, map_point: QgsPointXY) -> tuple[QgsPointLocator.Match, QgsPointXY, str]:
        match = self._snapping.snapToMap(map_point, self._points_only, False)
        if not match.isValid():
            match = self._snapping.snapToMap(map_point, None, False)
        if not match.isValid():
            return match, QgsPointXY(map_point), FREE_CLICK
        layer = match.layer()
        feature = layer.getFeature(match.featureId())
        name = QgsVectorLayerUtils.getFeatureDisplayString(layer, feature)
        name = name or f"#{match.featureId()}"
        return match, QgsPointXY(match.point()), f"{name} · {layer.name()}"

    def snap(self, map_point: QgsPointXY) -> tuple[QgsPointXY, str]:
        """The point a click at `map_point` (canvas CRS) picks, and its label."""
        _match, point, label = self._snap(map_point)
        return point, label

    def _view(self) -> _View:
        """Everything that decides which ground a canvas pixel shows."""
        settings = self.canvas().mapSettings()
        return QgsMapToPixel(settings.mapToPixel()), settings.destinationCrs()

    # ---- polygon mode -----------------------------------------------------
    def _polygon_at(self, map_point: QgsPointXY) -> tuple[QgsVectorLayer, int] | None:
        """The topmost polygon feature under `map_point`, or None.

        Layers are searched in `canvas.layers()` order, whose first is drawn
        on top; within a layer, the last feature drawn is on top. Only the
        canvas's own polygon layers count.
        """
        canvas = self.canvas()
        settings = canvas.mapSettings()
        half = canvas.mapUnitsPerPixel()
        box = QgsRectangle(
            map_point.x() - half, map_point.y() - half, map_point.x() + half, map_point.y() + half
        )
        for layer in canvas.layers(True):
            if not isinstance(layer, QgsVectorLayer):
                continue
            if layer.geometryType() != Qgis.GeometryType.Polygon:
                continue
            try:
                xform = QgsCoordinateTransform(
                    settings.destinationCrs(), layer.crs(), settings.transformContext()
                )
                here = QgsGeometry.fromPointXY(xform.transform(map_point))
                near = xform.transformBoundingBox(box)
            except QgsCsException:
                continue  # the click is outside where this layer's CRS works
            hit: int | None = None
            request = QgsFeatureRequest().setFilterRect(near).setNoAttributes()
            for feature in layer.getFeatures(request):
                if feature.hasGeometry() and feature.geometry().intersects(here):
                    hit = feature.id()
            if hit is not None:
                return layer, hit
        return None

    # ---- the marker and its label -----------------------------------------
    def _show(self, match: QgsPointLocator.Match, point: QgsPointXY, label: str) -> None:
        if self._indicator is None:
            return  # disposed: draw nothing more
        self._indicator.setMatch(match)
        if not match.isValid():
            self._hide_label()
            return
        if self._tip is not None and self._tip != point:
            # Qt leaves a tip whose text is unchanged where it is; a new
            # target with the same name must move it.
            QToolTip.hideText()
        canvas = self.canvas()
        QToolTip.showText(canvas.mapToGlobal(self.toCanvasCoordinates(point)), label, canvas)
        self._tip = QgsPointXY(point)

    def _hide_label(self) -> None:
        if self._tip is not None:
            QToolTip.hideText()
            self._tip = None

    def _clear(self) -> None:
        self._hover = None
        self.snap_label = ""
        self._hide_label()
        if self._indicator is not None:
            self._indicator.setMatch(QgsPointLocator.Match())

    # ---- Qt-invoked: each guards its own body -----------------------------
    def canvasMoveEvent(self, e: QgsMapMouseEvent) -> None:  # noqa: N802 -- Qt's name
        try:
            if self.mode != "point":
                return
            match, point, label = self._snap(e.mapPoint())
            self._hover = (QPoint(e.pixelPoint()), self._view(), point, label)
            self.snap_label = label if match.isValid() else ""
            self._show(match, point, label)
        except Exception as exc:  # noqa: BLE001 -- Qt-invoked: see the module docstring
            self.failed.emit(f"snapping failed: {exc}")

    def canvasReleaseEvent(self, e: QgsMapMouseEvent) -> None:  # noqa: N802 -- Qt's name
        try:
            button = e.button()
            if button == Qt.MouseButton.RightButton:
                self.skipped.emit()
                return
            if button != Qt.MouseButton.LeftButton:
                return
            if self.mode == "polygon":
                hit = self._polygon_at(e.mapPoint())
                if hit is not None:
                    self.polygon_picked.emit(hit[0], hit[1])
                return
            hover = self._hover
            if hover is not None and hover[:2] == (e.pixelPoint(), self._view()):
                point, label = hover[2], hover[3]  # what the label named
            else:
                point, label = self.snap(e.mapPoint())
            self.picked.emit(QgsPointXY(point), label)
        except Exception as exc:  # noqa: BLE001 -- Qt-invoked: see the module docstring
            self.failed.emit(f"the click could not be read: {exc}")

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802 -- Qt's name
        try:
            if e.key() == Qt.Key.Key_Escape:
                e.ignore()  # consumed: see the module docstring
                self.stopped.emit()
        except Exception as exc:  # noqa: BLE001 -- Qt-invoked: see the module docstring
            self.failed.emit(f"the key could not be read: {exc}")

    def deactivate(self) -> None:
        failure = ""
        try:
            self._clear()
        except Exception as exc:  # noqa: BLE001 -- Qt-invoked: see the module docstring
            failure = f"the snap marker could not be cleared: {exc}"
        super().deactivate()
        if not self._finished:
            # Deactivated without the caller finishing the pick: the user
            # switched to another map tool (QgsMapCanvas.setMapTool() calls
            # the outgoing tool's deactivate(), as unsetMapTool() does).
            # Nothing else would notice, and the dialog would stay hidden.
            self._finished = True  # once: a second deactivate() is not a second cancel
            self.cancelled.emit()
        if failure:
            self.failed.emit(failure)

    # ---- lifecycle ----------------------------------------------------------
    def finish(self) -> None:
        """The pick is over: leaving the canvas from now on is not a cancel."""
        self._finished = True

    def dispose(self) -> None:
        """Take this tool's marks off the map, for good.

        The snap marker lives in the canvas's scene, which owns it; the
        indicator deletes it on an empty match, which is what takes it back
        out of whatever scene holds it -- this never reaches for
        `canvas.scene()`, so it does not assume the canvas is still alive.
        The indicator is then dropped, so a tool used after this snaps and
        clicks as before but draws nothing more. The label is a tooltip, so
        hiding it is all it needs.

        Deliberately NOT called from `deactivate()`: that fires on every
        map-tool switch, after which the same tool can legitimately be set
        on the canvas again. Disposal means "this tool is finished", which
        only `plugin.py`'s finalisers know. Idempotent, because more than
        one finaliser can reach the same tool.
        """
        indicator, self._indicator = self._indicator, None
        self._hide_label()
        if indicator is not None:
            indicator.setMatch(QgsPointLocator.Match())
