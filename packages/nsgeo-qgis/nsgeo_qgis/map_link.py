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

import contextlib
from typing import Any

from qgis.core import (
    NULL,
    Qgis,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsMessageLog,
    QgsPointXY,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapCanvas, QgsRubberBand, QgsVertexMarker
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QObject, QTimer
from qgis.PyQt.QtGui import QColor

from .layers import SiteLayers
from .session import SiteSession

MARKER_COLOUR = QColor("#e67e22")
BAND_COLOUR = QColor("#e67e22")
MARKER_SIZE_PX = 9
BAND_WIDTH_PX = 3

# Sweeping the map must not thrash the renderer: a preview commits only
# once the pointer has settled for this long. Halved from 100 ms after a
# hands-on pass called that "too slow... about half that might be right" --
# 100 ms was a guess, this is a measurement of one person's hand. The
# renderer-thrash risk it guards against is much lower than it was: moving
# ALONG a displayed line no longer waits for this at all (see
# _track_displayed_line), so the dwell now governs only the switch to a
# different line, which is the one case that costs a load and a render.
HOVER_DWELL_MS = 50
# How close the pointer must come to a line before it counts as hovering
# it, in SCREEN pixels -- converted to map units per event, so the feel
# does not change with zoom.
HOVER_TOLERANCE_PX = 12


def _log(message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Warning) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", level)


class MapLink(QObject):
    HOVER_DWELL_MS = HOVER_DWELL_MS
    HOVER_TOLERANCE_PX = HOVER_TOLERANCE_PX

    # Selecting a feature in any of these is a deliberate gesture that
    # navigates (spec §3.4). `lines` promotes; `picks` and `marks` jump to
    # a line AND a trace. QGIS's own Select tool, no tool slot of ours, no
    # stolen clicks.
    SELECTABLE = ("lines", "picks", "marks")

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

        self._last_point: QgsPointXY | None = None
        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.timeout.connect(self._on_dwell)
        canvas.xyCoordinates.connect(self._on_xy)
        # See eventFilter()'s own docstring for why this watches the
        # VIEWPORT, not the canvas widget itself, and why that is not the
        # click interception the module docstring rules out.
        canvas.viewport().installEventFilter(self)

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

        # None means "not yet bound"; tracked per layer, and separately
        # from each `layers.layers[...]` lookup, for the reason
        # _rebind_layer gives. One NAMED slot per layer rather than a
        # lambda or `self.sender()`: a bound method is what
        # `disconnect()` can reliably take back off, and dispose() has to
        # be able to.
        self._bound: dict[str, QgsVectorLayer | None] = dict.fromkeys(self.SELECTABLE)
        self._selection_slots = {
            "lines": self._on_selection,
            "picks": self._on_pick_selection,
            "marks": self._on_mark_selection,
        }
        self._rebind_layer()

    # ---- cache ------------------------------------------------------------
    def _invalidate(self) -> None:
        self._geoms = None

    def _geometries(self) -> dict[str, QgsGeometry]:
        if self._geoms is not None:
            return self._geoms
        geoms: dict[str, QgsGeometry] = {}
        layer = self._lines_layer()
        if layer is not None:
            try:
                tr = self._transform(layer)
            except RuntimeError as exc:
                # Cache empty rather than half-built: a mix of transformed
                # and (because we bailed partway through the loop)
                # untransformed geometries would be worse than none, since
                # nothing downstream could tell the two apart. An empty
                # cache reads as "line not found" everywhere it is
                # consulted, which hides the marker and empties the band
                # instead of drawing either at the wrong scale.
                _log(
                    f"could not build the map link's geometry cache: {exc}",
                    Qgis.MessageLevel.Critical,
                )
                self._geoms = geoms
                return geoms
            for feature in layer.getFeatures():
                # A copy: the QgsFeature the iterator yields is reused, so
                # its geometry must not be held by reference.
                geom = QgsGeometry(feature.geometry())
                if tr is not None:
                    geom.transform(tr)
                geoms[str(feature["line_key"])] = geom
        self._geoms = geoms
        return geoms

    def _selectable_layer(self, name: str) -> QgsVectorLayer | None:
        layer = self.layers.layers.get(name)
        if layer is None or sip.isdeleted(layer):
            return None
        return layer

    def _lines_layer(self) -> QgsVectorLayer | None:
        return self._selectable_layer("lines")

    def _transform(self, layer: QgsVectorLayer) -> QgsCoordinateTransform | None:
        """`None` means "already in the canvas CRS, do not transform" --
        never "could not transform". `QgsCoordinateTransform.transform()`
        does not raise on an invalid transform (no PROJ path between the
        two CRSs): it reports success and leaves the geometry unchanged,
        which would relabel raw layer-CRS coordinates as canvas-CRS ones
        with nothing downstream able to tell. `SiteLayers._require_transform`
        hit this same defect class first; this follows its shape.

        `self.layers.project`, not `QgsProject.instance()`: `SiteLayers`
        was constructed with a specific (possibly non-default) project,
        and a transform built against the global singleton instead would
        silently disagree with it under any test or embedding that passes
        one in.
        """
        dest = self.canvas.mapSettings().destinationCrs()
        source = layer.crs()
        if not dest.isValid() or not source.isValid() or source == dest:
            return None
        transform = QgsCoordinateTransform(source, dest, self.layers.project)
        if not transform.isValid():
            raise RuntimeError(
                f"no coordinate transform from {source.authid() or source.toWkt()} to "
                f"{dest.authid() or dest.toWkt()}; refusing to draw untransformed geometry"
            )
        return transform

    # ---- ambient hover ------------------------------------------------------
    def _on_xy(self, point: QgsPointXY) -> None:
        """Fired on every mouse move over the canvas, whatever tool is
        active -- that is the whole reason this feature needs no tool slot.
        Records a position, restarts the dwell (which still governs
        switching to a DIFFERENT line -- see `_track_displayed_line`), and
        moves the cursor along whichever line is already on screen, which
        is free and must not wait for the dwell."""
        try:
            self._last_point = QgsPointXY(point)
            self._dwell.start(self.HOVER_DWELL_MS)
            self._track_displayed_line(self._last_point)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not track the pointer: {exc}", Qgis.MessageLevel.Critical)

    def _track_displayed_line(self, point: QgsPointXY) -> None:
        """Move the cursor along the line already on screen, without
        waiting for the dwell.

        The dwell exists to stop a sweep across the map loading line after
        line (spec §3.5). Moving along a line that is already displayed
        costs nothing -- its samples are loaded and its geometry is
        cached -- so making that wait for the dwell just made the cursor
        lurch. Only switching to a DIFFERENT line still pays the dwell,
        which is what the dwell was for.

        Leaving the dwell running (see `_on_xy`) is deliberate even though
        this method itself never clears anything: moving OFF the displayed
        line must still clear the preview on the dwell, not immediately,
        so that crossing a gap between two lines does not flicker the
        profile back to the working line and out again -- exactly the
        reason `_on_dwell` already routes its own "nothing hit" case
        through `clear_preview()` rather than clearing on every miss.
        """
        if self._marker is None or not self.session.is_open:
            return
        key = self.session.display_key
        if key is None:
            return
        geom = self._geometries().get(key)
        if geom is None or geom.isEmpty():
            return
        sq_dist, index = geom.closestVertexWithContext(point)
        tolerance = self.canvas.mapUnitsPerPixel() * self.HOVER_TOLERANCE_PX
        if index < 0 or sq_dist > tolerance * tolerance:
            return  # off this line; the dwell decides what happens next
        if key == self.session.current_key:
            self.session.set_trace(key, index)
        else:
            self.session.set_preview(key, index)

    def _on_dwell(self) -> None:
        try:
            # dispose()'s signal disconnect stops new xyCoordinates
            # emissions from reaching _on_xy, but a QTimer.timeout queued
            # before dispose() ran can still land after it -- the same
            # disposal sentinel _refresh() checks, since the canvas item
            # this slot's session writes would otherwise drive may already
            # be gone by the time it fires.
            if self._marker is None or self._band is None:
                return  # disposed
            point = self._last_point
            if point is None or not self.session.is_open:
                return
            hit = self._hit_test(point)
            if hit is None:
                # Clearing goes through the same dwell as previewing, so
                # crossing a gap between two lines does not flicker the
                # profile back to the working line and out again.
                self.session.clear_preview()
                return
            key, trace = hit
            if key == self.session.current_key:
                # The pointer is over the line already being worked on,
                # which is NOT a preview. The working line's cursor is
                # `current_trace`; routing it through `set_preview` would
                # give one line two sources of truth for one cursor, and
                # the map marker would then stop following a drag in the
                # profile. Any preview in progress ends here.
                self.session.clear_preview()
                self.session.set_trace(key, trace)
            else:
                self.session.set_preview(key, trace)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not preview the hovered line: {exc}", Qgis.MessageLevel.Critical)

    def eventFilter(self, _obj: QObject, event: Any) -> bool:  # noqa: N802 -- Qt's own name
        """Clear a stuck preview when the pointer leaves the canvas.

        Without this, nothing responds to the pointer leaving: a preview
        started near the canvas edge and then carried onto, say, the
        processing dock left the profile showing that line -- gain strip
        hidden, channel combo greyed -- until the pointer happened to come
        back over the map and a fresh dwell overwrote it. No wrong WRITE
        happens meanwhile (the banner stays up, which is the cue the spec
        asks for), but the view is stuck on a line nobody is pointing at
        any more.

        This is NOT the click interception the module docstring rules
        out. That prohibition is about adjudicating mouse BUTTON events
        against whatever map tool happens to be active -- one gesture,
        two claimants. `QEvent.Type.Leave` is not a click, is not a
        button event at all, and nothing else on the canvas is contesting
        it, so there is no adjudication to lose here.

        Installed on `canvas.viewport()`, not `canvas` itself (see the
        `installEventFilter` call in `__init__`). Verified by experiment
        against this Qt build (a QgsMapCanvas is a QGraphicsView, hence a
        QAbstractScrollArea): both the canvas widget and its viewport
        actually receive a real Enter/Leave pair when the pointer moves
        from inside the canvas to an entirely different dock -- Qt sends
        Enter/Leave to every widget between the old and new "under the
        pointer" leaf, ancestors included, not just the leaf itself. The
        viewport is still the right object to watch: it is inset from the
        canvas's own rect by that widget's 1px frame, and it is the
        viewport's own mouse tracking that `xyCoordinates` is built on, so
        a Leave here fires in the same instant `xyCoordinates` stops
        producing new positions -- filtering on `canvas` instead would
        leave a hairline gap (the pointer sitting in that 1px frame,
        still "in" the canvas, already producing no coordinates) where
        the preview would stay wrongly alive a moment longer.

        Stops the dwell too, not just clears the preview: a dwell already
        queued when the pointer left would otherwise fire right after and
        re-establish the very preview this just cleared.

        Returns `False` unconditionally: this only watches, it never
        consumes, so the event still reaches its ordinary handler.
        """
        try:
            if event.type() == QEvent.Type.Leave:
                self._dwell.stop()
                self._last_point = None
                self.session.clear_preview()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not clear the preview on pointer leave: {exc}", Qgis.MessageLevel.Critical)
        return False

    def _hit_test(self, point: QgsPointXY) -> tuple[str, int] | None:
        """The (line_key, trace) under `point`, or None if nothing is close
        enough. `point` is in canvas CRS, and so is the geometry cache.

        `closestVertexWithContext` returns a SQUARED distance, so the
        tolerance is squared to match rather than the distance rooted --
        getting this backwards silently widens the hit radius by 12x and
        is invisible to any test that hovers exactly on a line.

        Nearest *vertex* rather than nearest point on the segment: the
        vertex index is the trace index, which is the answer being asked
        for, and traces are centimetres apart, so the two differ by less
        than the pointer's own precision.
        """
        tolerance = self.canvas.mapUnitsPerPixel() * self.HOVER_TOLERANCE_PX
        limit = tolerance * tolerance
        best: tuple[float, str, int] | None = None
        for key, geom in self._geometries().items():
            if geom.isEmpty():
                continue
            sq_dist, index = geom.closestVertexWithContext(point)
            if index < 0 or sq_dist > limit:
                continue
            if best is None or sq_dist < best[0]:
                best = (sq_dist, key, index)
        return None if best is None else (best[1], best[2])

    def _rebind_layer(self) -> None:
        """Follow the selectable layers across rebuilds.

        A site reopen (`SiteLayers.detach()` clearing its registry, then
        `refresh()` rebuilding it -- the sequence `_on_site_opened` runs on
        every `site_closed`/`site_opened` pair) replaces the layer object
        outright: `ensure_tables()` only reuses `self.layers[name]` when
        the name is already present, and `detach()` empties that dict
        first. A plain `refresh()` on its own does not -- it truncates and
        refills the existing table in place -- so that path alone would
        not have caught a connection gone stale. A connection made once at
        construction and never renewed would point at a dead wrapper after
        such a reopen and promotion would silently stop working -- with no
        error, which is the worst kind of stop.

        M8: three layers, not one. `picks` and `marks` are rebound on the
        same signals and released by the same `dispose()`, because a
        reopen replaces all four layer objects together -- binding only
        `lines` across a reopen while leaving pick and mark navigation
        pointing at dead wrappers would fail exactly the way this method
        exists to prevent, just less visibly.
        """
        # Iterates `_selection_slots` itself, not `SELECTABLE`: a name
        # `SELECTABLE` lists but `_selection_slots` does not would raise
        # `KeyError` looking the slot up separately, and `dispose()` runs
        # this same shape of loop with a promise that nothing here may
        # abort before its scene-removal loop -- a `KeyError` would be
        # exactly that failure, just reached a different way than Item I4.
        for name, slot in self._selection_slots.items():
            old = self._bound.get(name)
            if old is not None and not sip.isdeleted(old):
                # Same two exceptions dispose() suppresses around this
                # same disconnect call, and for the same reason: a
                # RuntimeError from a wrapper that reports as not-deleted
                # but whose underlying C++ object is gone regardless must
                # not abort this method before the remaining layers are
                # bound below.
                with contextlib.suppress(TypeError, RuntimeError):
                    old.selectionChanged.disconnect(slot)
            layer = self._selectable_layer(name)
            self._bound[name] = layer
            if layer is not None:
                layer.selectionChanged.connect(slot)

    def _on_selection(self, *_: Any) -> None:
        """A preview becomes the working line when the user selects the
        line feature with QGIS's ordinary Select tool.

        No event filter, no tool of our own, no stolen clicks, and it
        composes with everything else QGIS does with selection. Promotion
        goes through `session.open_line` -- the same path the survey tree
        uses -- so opening from the map and opening from the tree cannot
        diverge.
        """
        try:
            layer = self._lines_layer()
            if layer is None or not self.session.is_open:
                return
            ids = layer.selectedFeatureIds()
            if len(ids) != 1:
                # A multi-selection has no single answer, and guessing one
                # is worse than doing nothing (spec §3.4). An empty
                # selection is the ordinary result of clicking empty map
                # and must not close the line the user is working on.
                return
            key = str(layer.getFeature(ids[0])["line_key"])
            if key in self.session.keys():  # noqa: SIM118 -- SiteSession.keys(), not a dict
                self.session.open_line(key)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not open the selected line: {exc}", Qgis.MessageLevel.Critical)

    def _on_pick_selection(self, *_: Any) -> None:
        try:
            self._jump_to_feature("picks", "trace")
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not jump to the selected pick: {exc}", Qgis.MessageLevel.Critical)

    def _on_mark_selection(self, *_: Any) -> None:
        try:
            self._jump_to_feature("marks", "scan")
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not jump to the selected mark: {exc}", Qgis.MessageLevel.Critical)

    def _jump_to_feature(self, name: str, trace_field: str) -> None:
        """Open the selected feature's line and put the cursor on its
        trace (spec §3.4's closing promise, and §4.4 for marks).

        `open_line` first, `set_trace` second, and not the other way
        round: `set_trace` structurally ignores a key that is not
        `current_key`, so a trace set before the promotion would be
        silently dropped. That ordering is the whole reason this is one
        method rather than two call sites.

        Promotion goes through `session.open_line`, the same path the
        survey tree and the `lines` layer already use, so no two ways of
        opening a line can diverge.
        """
        layer = self._selectable_layer(name)
        if layer is None or not self.session.is_open:
            return
        ids = layer.selectedFeatureIds()
        if len(ids) != 1:
            # A multi-selection has no single answer, and guessing one is
            # worse than doing nothing (spec §3.4). An empty selection is
            # the ordinary result of clicking empty map and must not
            # close the line the user is working on.
            return
        feature = layer.getFeature(ids[0])
        key = str(feature["line_key"])
        if key not in self.session.keys():  # noqa: SIM118 -- SiteSession.keys(), not a dict
            return
        self.session.open_line(key)
        trace = feature[trace_field]
        if trace == NULL:
            # `picks` is editable, so a hand-digitised row can carry a
            # line_key and nothing else. Opening its line is still the
            # right answer; `int(NULL)` raises, and this runs in a slot.
            return
        self.session.set_trace(key, int(trace))

    # ---- drawing ----------------------------------------------------------
    def _on_lines_changed(self, *_: Any) -> None:
        try:
            if self._marker is None or self._band is None:
                # disposed. Without this, a lines/grids/site signal landing
                # after dispose() would call _rebind_layer() again and
                # reconnect selectionChanged, silently undoing dispose()'s
                # own unbind and letting a disposed link start promoting
                # again -- the same class of leak _on_dwell and _refresh
                # already guard against below.
                return
            self._rebind_layer()
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
        # already being worked on, which is not a preview at all. This
        # module's own `_on_dwell` never produces that state (it routes a
        # hover over the working line through `clear_preview` + `set_trace`
        # instead, per Ruling 12), but `set_preview` is public and any
        # other caller can still reach it, so this stays defensive rather
        # than dead: testing `preview_key is not None` alone would blank
        # that line's own selection band the moment such a call landed.
        # ProfileDock reaches the same `preview_key == current_key` case in
        # its own `_on_preview_changed` (it takes the `_exit_preview()`
        # branch there, since a preview only ever ENTERS when
        # `key != self._working_key`) -- but the two do NOT agree on what
        # to show, deliberately: `_exit_preview()` leaves the cursor at
        # `current_trace`, not the fresher `preview_trace` this method
        # draws the marker at (verified directly: `set_preview(current_key,
        # 30)` on a line whose `current_trace` was 5 puts the map marker on
        # trace 30 and leaves the profile's cursor on trace 5). That is not
        # a bug to fix here: nothing on the hover path that drives this in
        # practice (`_on_dwell` above) ever calls `set_preview` with
        # `key == current_key` -- it always routes that case through
        # `clear_preview()` + `set_trace()` instead -- so this divergence
        # is reachable only by a caller that invokes
        # `session.set_preview(current_key, ...)` directly, which nothing
        # in this plugin does today.
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
        # navigation last set, so prefer it for the marker. session.py
        # guarantees preview_trace == -1 whenever preview_key is None, so
        # this one fallback also covers "no hover at all" -> current_trace,
        # same as before. The band is unaffected either way -- it is
        # always the working line's own selection here.
        trace = self.session.preview_trace
        if trace < 0:
            # set_preview(key) defaults trace to -1. On the working line
            # current_trace is still a real answer, so fall back to it
            # rather than hiding a cursor we know the position of.
            trace = self.session.current_trace
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

        Stopping the dwell timer is not enough on its own: the
        `canvas.xyCoordinates` connection made in `__init__` outlives
        disposal and would otherwise restart the timer on the very next
        mouse move, so it is disconnected here too. `disconnect()` raises
        `TypeError` rather than no-op on a connection that is already
        gone (a second `dispose()` call, or one made after the canvas
        itself tore its signals down) -- idempotency needs that caught,
        the same way the item removal below tolerates being called twice.
        Each selectable layer's `selectionChanged` connection (see
        `_rebind_layer`) is released the same way, so disposal stops the
        link promoting as well as drawing. The Leave-event filter
        installed on `canvas.viewport()` (see `eventFilter`) is removed
        the same way too: left in place, it would go on calling
        `session.clear_preview()` after disposal -- `session` is not
        something this method tears down, so that call would still land
        and could clear a preview that some other, still-live part of the
        plugin has since taken an interest in.

        That disconnect is itself guarded, in layers, because this
        method's own promise above -- it "does not assume the canvas is
        still alive" -- has to hold for `self.canvas` too, not just for
        the items: `sip.isdeleted` catches the cheap common case, a
        `TypeError` from `sip.isdeleted` itself means `self.canvas` is
        not even a sip-wrapped object any more (treated the same as
        "gone" -- this is the shape a test double standing in for an
        unreachable canvas takes), and `RuntimeError` is suppressed
        around the disconnect call for a wrapper that reports as
        not-deleted but whose underlying C++ object is gone regardless.
        In every case, a canvas that cannot be reached must never abort
        this method before the scene-removal loop below runs -- that
        would leave `_marker` and `_band` on the scene forever, which is
        exactly the Item I4 leak this method exists to prevent.
        """
        self._dwell.stop()
        try:
            canvas_gone = sip.isdeleted(self.canvas)
        except TypeError:
            canvas_gone = True
        if not canvas_gone:
            with contextlib.suppress(TypeError, RuntimeError):
                self.canvas.xyCoordinates.disconnect(self._on_xy)
            with contextlib.suppress(TypeError, RuntimeError):
                self.canvas.viewport().removeEventFilter(self)
        # The selectable layers are rebound across every site reopen (see
        # _rebind_layer), so disposal has to release whichever instances
        # are currently bound -- guarded the same way as the canvas above,
        # and for the same reason: nothing here may abort before the
        # scene-removal loop below. Iterates `_selection_slots` itself,
        # not `SELECTABLE`, for that same reason: looking a slot up
        # separately by name could raise `KeyError` for a name
        # `SELECTABLE` lists but `_selection_slots` does not, which would
        # abort this method before `_marker`/`_band` come off the scene --
        # the Item I4 leak this method exists to prevent.
        for name, slot in self._selection_slots.items():
            layer = self._bound.get(name)
            self._bound[name] = None
            if layer is not None and not sip.isdeleted(layer):
                with contextlib.suppress(TypeError, RuntimeError):
                    layer.selectionChanged.disconnect(slot)
        items, self._marker, self._band = (self._marker, self._band), None, None
        for item in items:
            if item is None or sip.isdeleted(item):
                continue
            scene = item.scene()
            if scene is not None:
                # removeItem() hands ownership back to us, so dropping the
                # last reference (done above) is what actually frees it.
                scene.removeItem(item)
