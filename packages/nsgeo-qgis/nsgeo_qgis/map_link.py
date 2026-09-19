"""MapLink: the map <-> profile link.

Deliberately NOT a QgsMapTool, which is why this module does not live in
`maptools/`. A map tool claims the canvas: while it is active the user
loses pan, identify and select, which is the wrong trade for an always-on
feature. `QgsMapCanvas.xyCoordinates` fires on mouse move regardless of
the active tool (verified against QGIS 3.44 with no tool set and with
QgsMapToolPan active), and a QgsVertexMarker attaches to the canvas scene
without owning the tool -- so the whole link coexists with whatever the
user is already doing.

Clicks are deliberately not intercepted. Catching one ambiently means an
event filter on the canvas viewport adjudicating every click in QGIS
against the active tool -- the same shape as the Plan 2 bug where a
right-click committed a left-drag selection in the profile. Selection
gives us a deliberate gesture for free instead (see `_on_selection`).

Every slot here catches its own exceptions: PyQt cannot propagate an
exception out of a slot invoked from C++, this build prints it and carries
on, and the CI container routes it to qFatal(). See `session.py`.
"""

from __future__ import annotations

from typing import Any

from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapCanvas, QgsRubberBand, QgsVertexMarker
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtGui import QColor

from .layers import SiteLayers
from .session import SiteSession

MARKER_COLOUR = QColor("#e67e22")
BAND_COLOUR = QColor("#e67e22")
MARKER_SIZE_PX = 9
BAND_WIDTH_PX = 3


def _log(message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Warning) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", level)


class MapLink(QObject):
    def __init__(
        self,
        session: SiteSession,
        layers: SiteLayers,
        canvas: QgsMapCanvas,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.layers = layers
        self.canvas = canvas

        self._marker: QgsVertexMarker | None = QgsVertexMarker(canvas)
        self._marker.setIconType(QgsVertexMarker.ICON_CROSS)
        self._marker.setColor(MARKER_COLOUR)
        self._marker.setIconSize(MARKER_SIZE_PX)
        self._marker.setPenWidth(2)
        self._marker.setVisible(False)

        self._band: QgsRubberBand | None = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._band.setColor(BAND_COLOUR)
        self._band.setWidth(BAND_WIDTH_PX)

        # None means "not built". Holds every line's geometry already
        # transformed into the CANVAS's CRS, so neither the marker nor the
        # hit test has to transform anything per mouse move, and the hover
        # tolerance -- which is a pixel count times mapUnitsPerPixel -- is
        # in the same units as the distances it is compared against.
        self._geoms: dict[str, QgsGeometry] | None = None

        for signal in (
            session.trace_changed,
            session.selection_changed,
            session.preview_changed,
            session.line_opened,
        ):
            signal.connect(self._on_session_changed)
        for signal in (session.lines_changed, session.grids_changed, session.site_opened):
            signal.connect(self._on_lines_changed)
        session.site_closed.connect(self._on_lines_changed)
        canvas.destinationCrsChanged.connect(self._on_lines_changed)

    # ---- cache ------------------------------------------------------------
    def _invalidate(self) -> None:
        self._geoms = None

    def _geometries(self) -> dict[str, QgsGeometry]:
        if self._geoms is not None:
            return self._geoms
        geoms: dict[str, QgsGeometry] = {}
        layer = self._lines_layer()
        if layer is not None:
            tr = self._transform(layer)
            for feature in layer.getFeatures():
                # A copy: the QgsFeature the iterator yields is reused, so
                # its geometry must not be held by reference.
                geom = QgsGeometry(feature.geometry())
                if tr is not None:
                    geom.transform(tr)
                geoms[str(feature["line_key"])] = geom
        self._geoms = geoms
        return geoms

    def _lines_layer(self) -> QgsVectorLayer | None:
        layer = self.layers.layers.get("lines")
        if layer is None or sip.isdeleted(layer):
            return None
        return layer

    def _transform(self, layer: QgsVectorLayer) -> QgsCoordinateTransform | None:
        dest = self.canvas.mapSettings().destinationCrs()
        source = layer.crs()
        if not dest.isValid() or not source.isValid() or source == dest:
            return None
        return QgsCoordinateTransform(source, dest, QgsProject.instance())

    # ---- drawing ----------------------------------------------------------
    def _on_lines_changed(self, *_: Any) -> None:
        try:
            self._invalidate()
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not rebuild the map link: {exc}", Qgis.MessageLevel.Critical)

    def _on_session_changed(self, *_: Any) -> None:
        try:
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not update the map link: {exc}", Qgis.MessageLevel.Critical)

    def _refresh(self) -> None:
        """Redraw both items from the session, whatever changed.

        Every signal lands here rather than each one updating its own item:
        the marker and the band both depend on which line is displayed AND
        on whether that line is a preview, so per-signal updates would have
        to re-derive the same answer in four places and could disagree.
        """
        if self._marker is None or self._band is None:
            return  # disposed
        key = self.session.display_key if self.session.is_open else None
        if key is None:
            self._marker.setVisible(False)
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        # `preview_key == current_key` is reachable -- the session allows
        # it and emits for it -- and it means the pointer is over the line
        # already being worked on, which is not a preview at all. Testing
        # `preview_key is not None` alone would blank that line's own
        # selection band the moment the pointer crossed it. ProfileDock
        # draws the same distinction in `_on_preview_changed`; the two must
        # agree or the map and the profile disagree about what is showing.
        previewing = self.session.preview_key not in (None, self.session.current_key)
        if previewing:
            self._set_marker(key, self.session.preview_trace)
            # A preview has no selection of its own, and the working
            # line's selection belongs to a line that is not on screen.
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        # Not a preview, but the pointer can still be sitting on the
        # working line itself (preview_key == current_key == key): that is
        # a live mouse position, strictly fresher than whatever trace
        # navigation last set, so prefer it for the marker. When there is
        # no hover at all `preview_key` is None and this falls back to
        # `current_trace`, same as before. The band is unaffected either
        # way -- it is always the working line's own selection here.
        trace = (
            self.session.preview_trace
            if self.session.preview_key == key
            else self.session.current_trace
        )
        self._set_marker(key, trace)
        self._set_band(key, *self.session.selection)

    def _set_marker(self, key: str, trace: int) -> None:
        assert self._marker is not None
        geom = self._geometries().get(key)
        if geom is None or trace < 0 or trace >= self._n_vertices(geom):
            self._marker.setVisible(False)
            return
        self._marker.setCenter(QgsPointXY(geom.vertexAt(trace)))
        self._marker.setVisible(True)

    def _set_band(self, key: str, start: int, end: int) -> None:
        assert self._band is not None
        geom = self._geometries().get(key)
        if geom is None or start < 0 or end < 0:
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        n = self._n_vertices(geom)
        lo = max(0, min(start, end))
        hi = min(n - 1, max(start, end))
        if lo > hi:
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        points = [QgsPointXY(geom.vertexAt(i)) for i in range(lo, hi + 1)]
        # layer=None: the cache is already in canvas CRS, so asking for a
        # transform here would apply one twice.
        self._band.setToGeometry(QgsGeometry.fromPolylineXY(points), None)

    @staticmethod
    def _n_vertices(geom: QgsGeometry) -> int:
        part = geom.constGet()
        return 0 if part is None else int(part.numPoints())

    # ---- teardown ---------------------------------------------------------
    def dispose(self) -> None:
        """Take both canvas items back off the scene, for good.

        Item I4 in Plan 2's final fix round: a QgsMapCanvasItem is owned by
        the canvas's QGraphicsScene, not by the Python wrapper, so dropping
        the reference leaks the item for the life of the QGIS session --
        the objects implicated in a shutdown segfault "once enough of them
        pile up alongside a QgsMapCanvas".

        Idempotent, because more than one finaliser can reach the same
        link. `item.scene()` rather than `self.canvas.scene()`: it removes
        the item from whatever scene actually holds it, and does not
        assume the canvas is still alive.
        """
        items, self._marker, self._band = (self._marker, self._band), None, None
        for item in items:
            if item is None or sip.isdeleted(item):
                continue
            scene = item.scene()
            if scene is not None:
                # removeItem() hands ownership back to us, so dropping the
                # last reference (done above) is what actually frees it.
                scene.removeItem(item)
