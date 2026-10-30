"""The profile viewer: a QWidget that paints a cached radargram image
through a ViewTransform, with axes, a cursor, a selection band, picks, a
slice band and the draggable time-cutoff line.

Measured: drawing a sub-rectangle of the cached image costs about 3 ms per
frame at any zoom, so pan and zoom never touch numpy.

Signal/slot hazard: an exception raised inside a slot connected via
`connect()`, or inside a Qt-invoked virtual method override (`paintEvent`,
`wheelEvent`, `mouseMoveEvent`, ...), never reaches whatever emitted the
signal or dispatched the event -- PyQt reports it to `sys.excepthook` and
the call that triggered it (`emit()`, `QApplication.sendEvent`, the real
event loop) returns as if nothing had gone wrong (see `nsgeo_qgis.plugin`'s
module docstring for the general note, and `nsgeo_qgis.ui.survey_dock` for
the `_log`-and-guard pattern this file copies). `ViewTransform.zoomed`/
`panned` route through `with_window`, which raises `ValueError` on a
non-finite window; a degenerate wheel or drag delta can also blow up the
arithmetic *before* that guard is even reached (`OverflowError` from
`1.25 ** steps` on an extreme `angleDelta`, `ZeroDivisionError` from a zoom
factor that underflows to exactly `0.0` -- both verified directly, neither
is a `ValueError`). `wheelEvent` and `mouseMoveEvent` are the two places a
raw mouse/wheel event feeds such a value straight into the transform, so
both guard their own bodies broadly (`except Exception`, not just
`ValueError`) and fall back to leaving `self.transform` at its last good
value rather than let the widget silently stop responding to input.
`mousePressEvent` and `mouseReleaseEvent` feed nothing into the transform,
but they carry the cutoff grab and the selection commit, so they guard
their bodies the same way.

A line on a grid ruler (`set_axes(..., ruler=...)`) is fitted to the ruler's
extent in that line's own trace units, and drawn mirrored when it was walked
toward the grid's low end, so every line on a grid reads low-to-high left to
right. The ruler can be wider than the data, so the window may show blank
space, hatched and inert (`trace_at` is None there). The trace index never
changes meaning: only the picture flips, and every signal, pick and selection
still counts traces in recorded order. Mirroring is a painter transform around
the one `drawImage`, never a mirrored copy of the image.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from nsgeo.velocity import VelocityModel
from qgis.core import Qgis
from qgis.PyQt.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor, QImage, QPainter, QPen
from qgis.PyQt.QtWidgets import QWidget

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.qtcompat import event_pos
from nsgeo_qgis.ui.ruler import (
    Ruler,
    bounds_on,
    is_reversed,
    metres_at,
    trace_units_at,
)
from nsgeo_qgis.ui.view_transform import ViewTransform, nice_ticks

# The axis captions ("ns" / "m") get a row of their own above the image,
# CAPTION_ROW tall; a tick label is a 16-px rect centred on its tick, so the
# topmost one overhangs the image by 8 px. MARGIN_TOP holds both, which is
# what keeps a "0" tick at the very top (an active `time_zero` step) off the
# caption without hiding the label (issue #7).
CAPTION_ROW = 14
MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM = 56, 48, CAPTION_ROW + 8, 28
BACKGROUND = QColor(250, 250, 250)
AXIS_COLOUR = QColor(60, 60, 60)
# Ruler space with no trace under it: a light hatch over the background, so it
# cannot be read as data in any colour table.
NO_DATA_HATCH = QColor(200, 200, 200)
CURSOR_COLOUR = QColor(255, 159, 26)
SELECTION_COLOUR = QColor(48, 140, 198, 60)
SELECTION_EDGE = QColor(48, 140, 198)
PICK_COLOUR = QColor(224, 66, 27)
# How close (pixels) a right-click must land to a fit point to discard it.
VELOCITY_DISCARD_PX = 12.0
DRAG_THRESHOLD_PX = 3

# Spec 9.3's one overlay. Distinct from SELECTION_COLOUR, which is a
# vertical trace range: these two can be on screen together and must not
# read as the same thing.
SLICE_BAND_COLOUR = QColor(80, 200, 255, 48)
SLICE_BAND_EDGE = QColor(80, 200, 255, 170)
MIN_BAND_PX = 2.0

# The time-cutoff line (late-time clip). Magenta, so it reads as neither the
# cyan slice band, the blue selection nor the orange cursor; the dim veil
# over everything below it says "this part is hidden", not just "a line".
CUTOFF_COLOUR = QColor(214, 39, 140)
CUTOFF_DIM = QColor(250, 250, 250, 170)
CUTOFF_GRAB_PX = 5
CUTOFF_TAG_PAD_X = 5
CUTOFF_TAG_PAD_Y = 2


def cutoff_label(end_ns: float, velocity: VelocityModel | None) -> str:
    """The line's caption: its time, and its depth when a velocity is known."""
    label = f"{end_ns:.1f} ns"
    if velocity is not None:
        depth = float(velocity.depth_at(np.array([end_ns]))[0])
        label += f" \u00b7 {depth:.2f} m"
    return label


class ProfileView(QWidget):
    trace_hovered = pyqtSignal(int)
    range_selected = pyqtSignal(int, int)
    selection_cleared = pyqtSignal()
    pick_requested = pyqtSignal(int, float)  # trace index, two-way time (ns)
    velocity_point_requested = pyqtSignal(int, float)  # trace index, two-way time (ns)
    velocity_point_discarded = pyqtSignal(int)  # index into the last points list
    view_changed = pyqtSignal()
    # Emitted once, on the release that ends a drag of the cutoff line, with
    # the snapped end time (ns). Always emitted, even for an unmoved line:
    # the no-op guard lives with the consumer.
    cutoff_dragged = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(240, 120)
        self.transform: ViewTransform | None = None
        self._image: QImage | None = None
        self._distance: np.ndarray | None = None
        self._ruler: Ruler | None = None
        self._velocity: VelocityModel | None = None
        self._direction = 1
        self._cursor = -1
        self._selection = (-1, -1)
        self._picks: list[tuple[int, float]] = []
        self._slice_band: tuple[float, float] | None = None
        self._cutoff_ns: float | None = None
        # The value the line had when a drag of it began; not None means a
        # drag is in progress. Kept so a drag whose release never arrives
        # (see `_handle_mouse_move`) can put the line back.
        self._cutoff_grab: float | None = None
        # Where that drag's press landed, and the line's offset from it (both
        # local y). Read only while `_cutoff_grab` is set.
        self._cutoff_press_y = 0.0
        self._cutoff_offset = 0.0
        self._pick_mode = False
        self._velocity_mode = False
        # The working hyperbola fit, in VIEW units (trace index, ns). The
        # view only paints it: converting to metres and fitting are the
        # dock's business, never this widget's.
        self._velocity_points: list[tuple[int, float]] = []
        self._velocity_curve: list[tuple[float, float]] = []
        self._saved_velocity_curves: list[list[tuple[float, float]]] = []
        self._press: QPointF | None = None
        self._pan_last: QPointF | None = None
        self._dragging = False
        self._message = "no line open"

    # ---- state ------------------------------------------------------------
    def image_rect(self) -> QRect:
        return QRect(
            MARGIN_LEFT,
            MARGIN_TOP,
            max(1, self.width() - MARGIN_LEFT - MARGIN_RIGHT),
            max(1, self.height() - MARGIN_TOP - MARGIN_BOTTOM),
        )

    def set_axes(
        self,
        n_traces: int,
        n_samples: int,
        t0_ns: float,
        dt_ns: float,
        distance_along: np.ndarray | None = None,
        ruler: Ruler | None = None,
    ) -> None:
        # C1c: `ViewTransform.__post_init__` checks `dt_ns` for finiteness only,
        # not positivity -- `dt_ns == 0.0` is finite and constructs a transform
        # that only explodes later, inside `source_rect()` (`(time_lo - t0_ns) /
        # dt_ns`), which paintEvent's own guard below cannot see coming since it
        # only checks n_traces/n_samples, not dt_ns. Not reachable from real
        # data today (`nsgeo.io.dzt.parse_header` and `Radargram.__post_init__`
        # both already reject `dt_ns <= 0`), but `set_axes` is a public entry
        # point with no caller between it and a header value, so it enforces
        # its own contract rather than trust every future caller to.
        if not dt_ns > 0:
            _log(f"set_axes: dt_ns must be positive, got {dt_ns}; axes left unchanged")
            return
        # C1a: a `distance_along` of the wrong length reaches `_distance_ticks`
        # unvalidated and raises `ValueError: fp and xp are not of the same
        # length` from `np.interp` -- inside `paintEvent`, where an escaping
        # exception is the hard-segfault hazard `paintEvent`'s own try/finally
        # below exists to catch. Rejecting the mismatch here, before it is ever
        # stored, means a caller's bug shows up as a logged warning at the
        # call site instead of a crash on the next repaint.
        if distance_along is not None:
            distance_along = np.asarray(distance_along, dtype=float)
            if distance_along.ndim != 1 or distance_along.shape[0] != n_traces:
                _log(
                    f"set_axes: distance_along has shape {distance_along.shape}, "
                    f"expected ({n_traces},); ignoring it"
                )
                distance_along = None
        r = self.image_rect()
        # A ruler needs a distance axis of at least two traces to place
        # anything on it; without one the view is today's.
        if ruler is not None and (distance_along is None or n_traces < 2):
            ruler = None
        if ruler is not None and distance_along is not None:
            self.transform = ViewTransform.fit(
                n_traces,
                n_samples,
                t0_ns,
                dt_ns,
                r.width(),
                r.height(),
                bounds=bounds_on(ruler, distance_along),
                mirrored=is_reversed(distance_along),
            )
        else:
            self.transform = ViewTransform.fit(
                n_traces, n_samples, t0_ns, dt_ns, r.width(), r.height()
            )
        self._ruler = ruler
        self._distance = distance_along
        self._message = "loading…"
        self.view_changed.emit()
        self.update()

    @property
    def ruler(self) -> Ruler | None:
        return self._ruler

    def window_m(self) -> tuple[float, float] | None:
        """The window's two ends in metres along the grid, ascending; None
        without a ruler."""
        if self._ruler is None or self._distance is None or self.transform is None:
            return None
        t = self.transform
        a = float(metres_at(self._distance, t.trace_lo))
        b = float(metres_at(self._distance, t.trace_hi))
        return (min(a, b), max(a, b))

    def set_window_m(self, lo_m: float, hi_m: float, time_lo: float, time_hi: float) -> None:
        """Set the window from metres along the grid (and a time window);
        `with_window` clamps it. Does nothing without a ruler."""
        if self._ruler is None or self._distance is None or self.transform is None:
            return
        a = float(trace_units_at(self._distance, lo_m))
        b = float(trace_units_at(self._distance, hi_m))
        self.transform = self.transform.with_window(min(a, b), max(a, b), time_lo, time_hi)
        self.view_changed.emit()
        self.update()

    def set_image(self, image: QImage | None) -> None:
        self._image = image
        self.update()

    def set_velocity(self, model: VelocityModel | None) -> None:
        self._velocity = model
        self.update()

    def set_direction(self, direction: int) -> None:
        self._direction = direction
        self.update()

    def set_cursor(self, trace: int) -> None:
        if trace != self._cursor:
            self._cursor = trace
            self.update()

    def set_selection(self, a: int, b: int) -> None:
        self._selection = (min(a, b), max(a, b)) if a >= 0 and b >= 0 else (-1, -1)
        self.update()

    def clear_selection(self) -> None:
        self.set_selection(-1, -1)

    def set_slice_band(self, lo_ns: float, hi_ns: float) -> None:
        """Draw the active slice's time window across this radargram.

        Spec 9.3: the only new thing the slice adds to the profile view.
        It answers "is this anomaly real, or is the fill inventing a
        feature between two lines?" by pointing at the depths the slice
        averaged, on data that was never filled.
        """
        if not all(math.isfinite(v) for v in (lo_ns, hi_ns)):
            # Cheap cluster (M11 final review): logged, not silent -- a
            # degenerate window (a NaN/inf `lo_ns`/`hi_ns`, e.g. from a
            # zero-thickness or off-axis slice) is exactly the kind of
            # input this guard's own analysis argues should leave a trace
            # rather than just vanish.
            _log(f"set_slice_band: non-finite window {lo_ns}..{hi_ns}; band cleared instead")
            self._slice_band = None
        else:
            self._slice_band = (min(lo_ns, hi_ns), max(lo_ns, hi_ns))
        self.update()

    def clear_slice_band(self) -> None:
        self._slice_band = None
        self.update()

    @property
    def cutoff_ns(self) -> float | None:
        """The end time drawn now, live during a drag; None when hidden."""
        return self._cutoff_ns

    def set_cutoff(self, end_ns: float | None) -> None:
        """Show the cutoff line at `end_ns`, or hide it with None.

        A drag in progress is abandoned (no emit): the caller has just
        said where the line is, and the release that follows must not
        overwrite that with a stale gesture.
        """
        self._cutoff_grab = None
        if end_ns is not None and not math.isfinite(end_ns):
            _log(f"set_cutoff: non-finite end time {end_ns}; line hidden instead")
            end_ns = None
        self._cutoff_ns = end_ns
        self.update()

    def set_picks(self, picks: list[tuple[int, float]]) -> None:
        self._picks = list(picks)
        self.update()

    def set_pick_mode(self, flag: bool) -> None:
        self._pick_mode = flag
        self.setCursor(Qt.CursorShape.CrossCursor if flag else Qt.CursorShape.ArrowCursor)

    def set_velocity_fit_mode(self, flag: bool) -> None:
        self._velocity_mode = bool(flag)
        self.setCursor(Qt.CursorShape.CrossCursor if flag else Qt.CursorShape.ArrowCursor)

    def set_velocity_fit(
        self, points: list[tuple[int, float]], curve: list[tuple[float, float]]
    ) -> None:
        self._velocity_points = list(points)
        self._velocity_curve = list(curve)
        self.update()

    def set_saved_velocity_fits(self, curves: list[list[tuple[float, float]]]) -> None:
        """The line's already-measured fits as (trace, ns) curves, drawn faint
        beneath the working fit, which `set_velocity_fit` carries."""
        self._saved_velocity_curves = [list(c) for c in curves]
        self.update()

    def clear(self) -> None:
        self.transform = None
        self._ruler = None
        self._image = None
        self._cursor = -1
        self._selection = (-1, -1)
        self._picks = []
        self._velocity_points = []
        self._velocity_curve = []
        self._saved_velocity_curves = []
        self._slice_band = None
        self._cutoff_ns = None
        self._cutoff_grab = None
        self._message = "no line open"
        # A hover over the line left the resize cursor up, and only the next
        # hover over the image would reset it; with no line open there is
        # no image to hover.
        self.setCursor(
            Qt.CursorShape.CrossCursor
            if self._pick_mode or self._velocity_mode
            else Qt.CursorShape.ArrowCursor
        )
        self.update()

    # ---- view changes -----------------------------------------------------
    def fit(self) -> None:
        if self.transform is None:
            return
        t = self.transform
        r = self.image_rect()
        self.transform = ViewTransform.fit(
            t.n_traces,
            t.n_samples,
            t.t0_ns,
            t.dt_ns,
            r.width(),
            r.height(),
            bounds=t.bounds,
            mirrored=t.mirrored,
        )
        self.view_changed.emit()
        self.update()

    def one_to_one(self) -> None:
        """One trace per pixel column, anchored at the current window's left."""
        if self.transform is None:
            return
        t = self.transform
        self.transform = t.one_to_one()
        self.view_changed.emit()
        self.update()

    def zoom_at(self, factor: float, x: float, y: float) -> None:
        if self.transform is None:
            return
        self.transform = self.transform.zoomed(factor, x, y)
        self.view_changed.emit()
        self.update()

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.transform is not None:
            r = self.image_rect()
            self.transform = self.transform.resized(r.width(), r.height())
            self.view_changed.emit()

    def grab_image(self) -> QImage:
        return self.grab().toImage()

    # ---- painting ---------------------------------------------------------
    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        # C1: paintEvent is a Qt-invoked virtual method override -- the one
        # where an escaping exception is not merely invisible (see the module
        # docstring), it is a live process hazard. `QPainter(self)` binds the
        # painter to this widget; if anything below raises before
        # `painter.end()` runs, the painter stays bound (Qt's own words:
        # "Cannot destroy paint device that is being painted") and the
        # *next* repaint segfaults the process -- measured directly, not
        # theorised: the first escaped exception only warns, the second
        # crashes. `try/finally` is what turns a crash into a blank widget;
        # `except Exception` alone (as wheelEvent/mouseMoveEvent use) is not
        # enough here, because it does not guarantee `painter.end()` runs.
        # Three concrete inputs reach this from the public `set_axes`
        # signature alone -- a `distance_along` of the wrong length, the
        # empty-trace-axis state defect (a) exists to make safe, and (were
        # `dt_ns <= 0` ever able to reach this far) `source_rect()` dividing
        # by a zero `dt_ns` -- all three now also rejected earlier, in
        # `set_axes` itself (C1a/C1c) and `_distance_ticks` (C1b), so this is
        # defence in depth, not the only guard.
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), BACKGROUND)
            r = self.image_rect()
            t = self.transform
            if t is None:
                painter.setPen(AXIS_COLOUR)
                painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._message)
                return
            # Task 13 makes an empty trace or sample axis (n_traces == 0 or
            # n_samples == 0) a legal ViewTransform state, not an error -- so
            # it must be handled *before* any division, not turned into one.
            # The original shape here computed
            # `self._image.width() / t.n_traces` unconditionally, ahead of
            # this check: a live ZeroDivisionError inside paintEvent.
            # Checking emptiness first and falling through to the same
            # "no image" message branch below keeps the empty-axis contract
            # intact while still being safe to paint.
            if self._image is not None and t.n_traces > 0 and t.n_samples > 0:
                # m4: `sx` is the *average* traces-per-decimated-column
                # (`n_traces / image.width()`, inverted). `decimate_columns`
                # bins a ragged tail (when `n_traces` is not an exact
                # multiple of its block size) into a narrower last column,
                # so the true per-column trace count is not perfectly
                # uniform whenever a line is wide enough to decimate at all
                # (`max_width`, default 8192). The resulting few-tenths-of-a-
                # pixel error is invisible at a fit zoom and only reaches a
                # couple of image columns' worth of misregistration zoomed
                # in near the tail -- and is unreachable with real data
                # today regardless (lines here are 606-666 traces, nowhere
                # near `max_width`). Not fixed exactly here: doing so needs
                # `decimate_columns`'s own block size, which `paintEvent`
                # does not otherwise need to know.
                sx = self._image.width() / t.n_traces
                sy = self._image.height() / t.n_samples
                # The ruler can be wider than the data: hatch the whole image
                # rect, then draw only the part of the window that has traces.
                painter.fillRect(r, QBrush(NO_DATA_HATCH, Qt.BrushStyle.BDiagPattern))
                x, y, w, h = t.source_rect()
                if w > 0:
                    x0, x1 = t.target_span()
                    target = QRectF(r.left() + x0, r.top(), x1 - x0, r.height())
                    src = QRectF(x * sx, y * sy, w * sx, h * sy)
                    if t.mirrored:
                        # Flip about the target's centre: the image keeps its
                        # recorded order, only the picture reverses.
                        painter.save()
                        painter.translate(target.left() + target.right(), 0)
                        painter.scale(-1, 1)
                        painter.drawImage(target, self._image, src)
                        painter.restore()
                    else:
                        painter.drawImage(target, self._image, src)
            else:
                painter.setPen(AXIS_COLOUR)
                painter.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self._message)
            painter.setClipRect(r)
            self._paint_slice_band(painter, r, t)
            self._paint_cutoff(painter, r, t)
            self._paint_selection(painter, r, t)
            self._paint_picks(painter, r, t)
            self._paint_velocity_fit(painter, r, t)
            self._paint_cursor(painter, r, t)
            painter.setClipping(False)
            self._paint_axes(painter, r, t)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring and C1 above
            _log(f"could not paint the profile view: {exc}")
        finally:
            painter.end()

    def _paint_cursor(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        if self._cursor < 0:
            return
        x = r.left() + t.x_of_trace(self._cursor + 0.5)
        p.setPen(QPen(CURSOR_COLOUR, 1.5))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

    # Cheap cluster (M11 final review): `_slice_band_bounds`/`_paint_
    # slice_band` moved ahead of `_selection_bounds`/`_paint_selection` --
    # `paintEvent` calls them in exactly this order (slice band, then
    # selection, then picks), and reading order matching paint order is
    # worth keeping now that there are three layers to keep straight, not
    # one accidental reason to prefer either ordering over the other.
    def _slice_band_bounds(self, t: ViewTransform) -> tuple[float, float] | None:
        """Local (unoffset) y-bounds of the band, or None when there is
        none. Factored out the same way `_selection_bounds` is, and for
        the same reason: a plain pair a test can assert on without
        rendering a pixel.

        A one-level window has zero time extent -- it averages a single
        sample, and saying otherwise would overstate what was averaged --
        so the floor is applied HERE, in pixels, rather than by widening
        the window the readout reports.
        """
        if self._slice_band is None:
            return None
        y0 = t.y_of_time(self._slice_band[0])
        y1 = t.y_of_time(self._slice_band[1])
        if y1 - y0 < MIN_BAND_PX:
            centre = (y0 + y1) / 2.0
            y0, y1 = centre - MIN_BAND_PX / 2.0, centre + MIN_BAND_PX / 2.0
        return y0, y1

    def _paint_slice_band(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        bounds = self._slice_band_bounds(t)
        if bounds is None:
            return
        y0, y1 = r.top() + bounds[0], r.top() + bounds[1]
        p.fillRect(QRectF(r.left(), y0, r.width(), y1 - y0), SLICE_BAND_COLOUR)
        p.setPen(QPen(SLICE_BAND_EDGE, 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(r.left(), y0), QPointF(r.right(), y0))
        p.drawLine(QPointF(r.left(), y1), QPointF(r.right(), y1))

    def _cutoff_y(self, t: ViewTransform) -> float | None:
        """Local (unoffset) y of the cutoff line, or None when hidden.
        Clamped into the record, so a cutoff past it (or a line carried
        over onto a shorter one) sits on the bottom edge rather than off
        the widget."""
        if self._cutoff_ns is None:
            return None
        return t.y_of_time(min(max(self._cutoff_ns, t.t0_ns), t.t_end))

    def _cutoff_label_rect(self, r: QRect, t: ViewTransform) -> QRectF | None:
        """The label's tag, or None when the line is hidden. Sized to the
        text plus padding, right-aligned. Factored out the same way
        `_selection_bounds` is, and for the same reason: a plain rect a
        test can assert on without rendering a pixel."""
        y = self._cutoff_y(t)
        if self._cutoff_ns is None or y is None:
            return None
        text = cutoff_label(self._cutoff_ns, self._velocity)
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(text) + 2 * CUTOFF_TAG_PAD_X
        h = fm.height() + 2 * CUTOFF_TAG_PAD_Y
        yy = r.top() + y
        # Above the line, unless that would put it above the image, where
        # the paint clip hides it: a line dragged up to keep one sample
        # sits within a tag's height of the top.
        top = yy - h - 2 if yy - h - 2 >= r.top() else yy + 2
        return QRectF(max(r.left(), r.right() + 1 - 3 - w), top, w, h)

    def _paint_cutoff(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        y = self._cutoff_y(t)
        tag = self._cutoff_label_rect(r, t)
        if y is None or tag is None or self._cutoff_ns is None:
            return
        yy = r.top() + y
        p.fillRect(QRectF(r.left(), yy, r.width(), r.bottom() + 1 - yy), CUTOFF_DIM)
        p.setPen(QPen(CUTOFF_COLOUR, 2))
        p.drawLine(QPointF(r.left(), yy), QPointF(r.right(), yy))
        # White on a magenta tag: magenta text straight onto the radargram
        # was hard to read.
        p.fillRect(tag, CUTOFF_COLOUR)
        p.setPen(QColor(255, 255, 255))
        p.drawText(
            tag,
            int(Qt.AlignmentFlag.AlignCenter),
            cutoff_label(self._cutoff_ns, self._velocity),
        )

    def _near_cutoff(self, x: float, y: float) -> bool:
        """True when a local point is inside the image and within the grab
        distance of the line. The image bound matters for the same reason
        as the pick gesture's: the handlers run for the axis margins too."""
        if self.transform is None:
            return False
        line = self._cutoff_y(self.transform)
        if line is None:
            return False
        inside = 0 <= x < self.transform.width and 0 <= y < self.transform.height
        return inside and abs(y - line) <= CUTOFF_GRAB_PX

    def _selection_bounds(self, t: ViewTransform) -> tuple[float, float] | None:
        """Local (unoffset by `r.left()`) x-bounds of the selection band, or
        `None` when there is no selection. `b + 1`, not `b`: the selection
        is inclusive of trace `b`, so its right edge is the *start* of the
        next trace -- factored out so this is a plain value comparable in a
        test without rendering a pixel."""
        a, b = self._selection
        if a < 0:
            return None
        x0, x1 = t.x_of_trace(a), t.x_of_trace(b + 1)
        return (min(x0, x1), max(x0, x1))

    def _paint_selection(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        bounds = self._selection_bounds(t)
        if bounds is None:
            return
        x0, x1 = r.left() + bounds[0], r.left() + bounds[1]
        p.fillRect(QRectF(x0, r.top(), x1 - x0, r.height()), SELECTION_COLOUR)
        p.setPen(QPen(SELECTION_EDGE, 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x0, r.top()), QPointF(x0, r.bottom()))
        p.drawLine(QPointF(x1, r.top()), QPointF(x1, r.bottom()))

    def _pick_positions(self, t: ViewTransform) -> list[tuple[float, float]]:
        """Local (unoffset) (x, y) of each pick marker's centre. Factored
        out the same way `_selection_bounds` is, and for the same reason:
        a plain list of coordinates a test can assert on directly."""
        return [(t.x_of_trace(trace + 0.5), t.y_of_time(time_ns)) for trace, time_ns in self._picks]

    def _paint_picks(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.setBrush(PICK_COLOUR)
        for x, y in self._pick_positions(t):
            xx, yy = r.left() + x, r.top() + y
            p.drawPolygon(QPointF(xx, yy), QPointF(xx - 5, yy - 9), QPointF(xx + 5, yy - 9))

    def _velocity_positions(self, t: ViewTransform) -> list[tuple[float, float]]:
        """Local (x, y) of each working fit point, in list order, so an
        index into this list is the index `velocity_point_discarded` emits."""
        return [
            (t.x_of_trace(trace + 0.5), t.y_of_time(time_ns))
            for trace, time_ns in self._velocity_points
        ]

    def _paint_velocity_fit(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        faint = QColor(CURSOR_COLOUR)
        faint.setAlpha(90)
        for saved in self._saved_velocity_curves:
            if len(saved) >= 2:
                p.setPen(QPen(faint, 1))
                spts = [
                    QPointF(r.left() + t.x_of_trace(trace + 0.5), r.top() + t.y_of_time(time_ns))
                    for trace, time_ns in saved
                ]
                for a, b in zip(spts, spts[1:], strict=False):
                    p.drawLine(a, b)
        if len(self._velocity_curve) >= 2:
            p.setPen(QPen(CURSOR_COLOUR, 2))
            pts = [
                QPointF(r.left() + t.x_of_trace(trace + 0.5), r.top() + t.y_of_time(time_ns))
                for trace, time_ns in self._velocity_curve
            ]
            for a, b in zip(pts, pts[1:], strict=False):
                p.drawLine(a, b)
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.setBrush(SELECTION_EDGE)
        for x, y in self._velocity_positions(t):
            p.drawEllipse(QPointF(r.left() + x, r.top() + y), 4.0, 4.0)

    def _paint_axes(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        p.setPen(AXIS_COLOUR)
        font = p.font()
        font.setPointSize(8)
        p.setFont(font)
        # left: two-way time
        p.drawLine(r.topLeft(), r.bottomLeft())
        for tick, y in self._time_ticks(t):
            yy = r.top() + y
            p.drawLine(QPointF(r.left() - 4, yy), QPointF(r.left(), yy))
            p.drawText(
                QRectF(0, yy - 8, r.left() - 6, 16),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                tick,
            )
        p.drawText(QRectF(0, 0, r.left() - 6, CAPTION_ROW), int(Qt.AlignmentFlag.AlignRight), "ns")
        # right: depth
        p.drawLine(r.topRight(), r.bottomRight())
        if self._velocity is not None:
            for label, y in self._depth_ticks(t):
                yy = r.top() + y
                p.drawLine(QPointF(r.right(), yy), QPointF(r.right() + 4, yy))
                p.drawText(
                    QRectF(r.right() + 6, yy - 8, MARGIN_RIGHT - 8, 16),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    label,
                )
            p.drawText(
                QRectF(r.right() + 6, 0, MARGIN_RIGHT - 8, CAPTION_ROW),
                int(Qt.AlignmentFlag.AlignLeft),
                "m",
            )
        # bottom: distance along the line, or trace index
        p.drawLine(r.bottomLeft(), r.bottomRight())
        for label, x in self._distance_ticks(t):
            xx = r.left() + x
            p.drawLine(QPointF(xx, r.bottom()), QPointF(xx, r.bottom() + 4))
            p.drawText(
                QRectF(xx - 30, r.bottom() + 6, 60, 14), int(Qt.AlignmentFlag.AlignHCenter), label
            )
        p.drawText(
            QRectF(r.left(), r.bottom() + 14, r.width(), 14),
            int(Qt.AlignmentFlag.AlignHCenter),
            self._distance_caption(),
        )

    def _time_ticks(self, t: ViewTransform) -> list[tuple[str, float]]:
        """Left-axis (two-way time) tick labels and pixel y-positions.

        Factored out of `_paint_axes` alongside `_depth_ticks`/
        `_distance_ticks` so the value computation -- which tick values, at
        which y -- is unit-testable directly, the same way those two
        already were, rather than only provable by rendering pixels."""
        return [
            (f"{tick:g}", t.y_of_time(float(tick))) for tick in nice_ticks(t.time_lo, t.time_hi)
        ]

    def _distance_unit_label(self) -> str:
        return "m" if self._distance is not None else "trace"

    def _distance_caption(self) -> str:
        if self._ruler is not None:
            return f"m along grid \u00b7 walked {self._direction_arrow()}"
        return f"{self._distance_unit_label()} along line {self._direction_arrow()}"

    def _direction_arrow(self) -> str:
        return "→" if self._direction == 1 else "←"

    def _depth_ticks(self, t: ViewTransform) -> list[tuple[str, float]]:
        assert self._velocity is not None
        times = np.linspace(t.time_lo, t.time_hi, 512)
        depths = self._velocity.depth_at(times)
        out = []
        for d in nice_ticks(float(depths[0]), float(depths[-1])):
            time_ns = float(np.interp(d, depths, times))
            out.append((f"{d:g}", t.y_of_time(time_ns)))
        return out

    def depth_tick_labels(self) -> list[str]:
        if self.transform is None or self._velocity is None:
            return []
        return [label for label, _ in self._depth_ticks(self.transform)]

    def _distance_ticks(self, t: ViewTransform) -> list[tuple[str, float]]:
        lo, hi = t.trace_lo, t.trace_hi
        # C1b: n_traces == 0 is a legal, empty-axis ViewTransform (Task 13;
        # also defect (a)). `set_axes` already rejects a `distance_along`
        # whose length disagrees with `n_traces` (C1a), but a *correctly*
        # zero-length array for a zero-trace axis passes that check and
        # still reaches `np.interp` below with an empty `xp`, raising
        # `ValueError: array of sample points is empty`. Falling back to the
        # same trace-tick branch as "no distance set" is correct either way:
        # there is nothing to tick in metres along zero traces.
        if self._distance is None or t.n_traces == 0:
            return [(f"{tick:g}", t.x_of_trace(float(tick))) for tick in nice_ticks(lo, hi)]
        d = self._distance
        # The window's ends in metres, read off the extrapolating map so the
        # ticks run on across blank space; each tick sits on its column centre.
        m_lo, m_hi = (float(metres_at(d, v)) for v in (lo, hi))
        return [
            (f"{tick:g}", t.x_of_trace(float(trace_units_at(d, float(tick)))))
            for tick in nice_ticks(min(m_lo, m_hi), max(m_lo, m_hi))
        ]

    # ---- mouse ------------------------------------------------------------
    def _local(self, event: Any) -> tuple[float, float]:
        pos = event_pos(event)
        r = self.image_rect()
        return pos.x() - r.left(), pos.y() - r.top()

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if self.transform is None:
            return
        try:
            self._handle_mouse_press(event)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring:
            # a Qt-invoked virtual method, guarded for the reason
            # mouseMoveEvent's own comment gives.
            _log(f"could not handle the mouse press: {exc}", Qgis.MessageLevel.Warning)

    def _abandon_stale_cutoff_grab(self) -> None:
        if self._cutoff_grab is not None:
            self._cutoff_ns = self._cutoff_grab
            self._cutoff_grab = None
            self.update()

    def _handle_mouse_press(self, event: Any) -> None:
        assert self.transform is not None  # only called from mousePressEvent's own guard
        x, y = self._local(event)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event_pos(event)
            return
        if event.button() == Qt.MouseButton.RightButton and self._velocity_mode:
            self._abandon_stale_cutoff_grab()
            # Nearest in SCREEN space: the points live in trace/ns, whose
            # scales differ, so only pixels say which one the user meant.
            nearest = None
            for i, (px, py) in enumerate(self._velocity_positions(self.transform)):
                d = math.hypot(px - x, py - y)
                if d <= VELOCITY_DISCARD_PX and (nearest is None or d < nearest[0]):
                    nearest = (d, i)
            if nearest is not None:
                self.velocity_point_discarded.emit(nearest[1])
            return
        if event.button() == Qt.MouseButton.LeftButton:
            # A grab still set here lost its release (focus stolen mid-
            # drag) and no button-less move has cleaned it up yet. Abandon
            # it before deciding what this press is, or its stale state
            # would follow the next gesture and emit from the wrong one.
            self._abandon_stale_cutoff_grab()
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self._pick_mode or shift:
                # Only inside the radargram itself. This handler runs for
                # the whole widget, axis margins included, and
                # `time_of_y` does not clamp -- a shift click on the
                # depth-axis label reaches here with a negative local y
                # and would author a pick at a time before the record
                # starts. `add_pick` clamps such a time into the record,
                # which is precisely what makes the bad pick look
                # plausible once written. Hover already applies the same
                # bound (`_handle_mouse_move`'s `0 <= x < width`); this
                # is that rule for the other axis and the other gesture.
                if not (0 <= x < self.transform.width and 0 <= y < self.transform.height):
                    return
                trace = self.transform.trace_at(x)
                if trace is not None:  # blank space on the ruler is inert
                    self.pick_requested.emit(trace, self.transform.time_of_y(y))
                return
            if self._velocity_mode:
                # Same bounds guard as the pick branch above, for the same
                # reason: `time_of_y` does not clamp, so a click on the
                # axis margin would author a point before the record starts.
                if not (0 <= x < self.transform.width and 0 <= y < self.transform.height):
                    return
                trace = self.transform.trace_at(x)
                if trace is not None:
                    self.velocity_point_requested.emit(trace, self.transform.time_of_y(y))
                return
            line = self._cutoff_y(self.transform)
            if line is not None and self._near_cutoff(x, y):
                # Not `_press`: its release would commit or clear a
                # selection, which a drag of this line must never do.
                self._cutoff_grab = self._cutoff_ns
                self._cutoff_press_y = y
                self._cutoff_offset = line - y
                return
            self._press = event_pos(event)
            self._dragging = False

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if self.transform is None:
            return
        try:
            self._handle_mouse_move(event)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring:
            # mouseMoveEvent is a Qt-invoked virtual method, not an ordinary
            # Python call; an exception escaping it never reaches anything
            # outside PyQt's own exception hook, and the widget would look
            # like it silently stopped tracking the mouse (panned()/hover
            # both stop firing, with no visible error). Catching here keeps
            # self.transform at its last good value and the pointer state
            # usable instead.
            _log(f"could not update the view while dragging: {exc}", Qgis.MessageLevel.Warning)

    def _handle_mouse_move(self, event: Any) -> None:
        assert self.transform is not None  # only called from mouseMoveEvent's own guard
        pos = event_pos(event)
        x, y = self._local(event)
        if self._pan_last is not None:
            # I3: `_pan_last` was only ever cleared by a *middle-button*
            # mouseReleaseEvent. A middle-press followed by an unrelated
            # left-press/release (or any release path other than a middle
            # one) left it set, and this check ran before any button state
            # was consulted -- so the very next mouse move, with no button
            # held at all, was read as an in-progress pan and moved the
            # view. Measured: middle-press, left-press, left-release, one
            # button-less move -- panned 14.4 traces. Checking the event's
            # *actual current* buttons() here (rather than trusting
            # `_pan_last`'s own bookkeeping to have been cleared by every
            # path that should clear it) is authoritative regardless of
            # which release path got there, including one this file cannot
            # see coming (focus lost mid-drag, no release event at all).
            if not (event.buttons() & Qt.MouseButton.MiddleButton):
                self._pan_last = None
            else:
                d = pos - self._pan_last
                self._pan_last = pos
                self.transform = self.transform.panned(d.x(), d.y())
                self.view_changed.emit()
                self.update()
                return
        if self._cutoff_grab is not None:
            # Same lesson as `_pan_last` above: trust the event's actual
            # buttons, not the bookkeeping. A release lost mid-drag (focus
            # change) would otherwise leave the line glued to the pointer.
            if not (event.buttons() & Qt.MouseButton.LeftButton):
                self._cutoff_ns = self._cutoff_grab
                self._cutoff_grab = None
                self.update()
            else:
                # The grab zone is +-CUTOFF_GRAB_PX, so most presses land off
                # the line's own pixel. Snapping the line to the pointer
                # moved it on the first move, and a press, a wobble and a
                # release where it began wrote an edit nobody made. So the
                # line holds its exact start value until the pointer has
                # travelled past the drag threshold, and from then on moves
                # by the pointer's travel, keeping the press-to-line offset.
                if abs(y - self._cutoff_press_y) <= DRAG_THRESHOLD_PX:
                    self._cutoff_ns = self._cutoff_grab
                else:
                    self._cutoff_ns = self.transform.snap_cutoff(
                        self.transform.time_of_y(y + self._cutoff_offset)
                    )
                self.update()
                return
        if self._press is not None:
            if abs(pos.x() - self._press.x()) > DRAG_THRESHOLD_PX:
                self._dragging = True
                span = self.transform.traces_between(self._press.x() - self.image_rect().left(), x)
                if span is None:  # the drag has only crossed blank space
                    self.clear_selection()
                else:
                    self.set_selection(*span)
            return
        # Pick wins the press over the grab, so in pick mode the line must
        # not advertise a drag.
        if self._near_cutoff(x, y) and not (self._pick_mode or self._velocity_mode):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(
                Qt.CursorShape.CrossCursor
                if (self._pick_mode or self._velocity_mode)
                else Qt.CursorShape.ArrowCursor
            )
        if 0 <= x < self.transform.width:
            trace = self.transform.trace_at(x)
            if trace is not None:
                self.trace_hovered.emit(trace)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        try:
            self._handle_mouse_release(event)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring:
            # a Qt-invoked virtual method, guarded for the reason
            # mouseMoveEvent's own comment gives.
            _log(f"could not handle the mouse release: {exc}", Qgis.MessageLevel.Warning)

    def _handle_mouse_release(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = None
            return
        # I4: this branch used to run for *any* released button, not just
        # the left one that starts a drag in mousePressEvent -- so a right
        # click landing anywhere while a left-drag was in progress (`_press`
        # still set from the left press) ended and committed that drag as
        # if it were the left button's own release. Measured: left-press at
        # x=100, drag to x=300, then press-and-release the *right* button --
        # `range_selected` fired `(28, 86)` from a button the user never
        # used to start the selection. Left is the only button
        # mousePressEvent ever arms `_press`/`_dragging` for, so it is the
        # only one release should act on here.
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._cutoff_grab is not None:
            self._cutoff_grab = None
            if self._cutoff_ns is not None:
                self.cutoff_dragged.emit(self._cutoff_ns)
            return
        if self._press is not None and self.transform is not None:
            if self._dragging and self._selection != (-1, -1):
                a, b = self._selection
                self.range_selected.emit(a, b)
            elif self._dragging:
                # A drag that only crossed blank space counts as a click.
                self.clear_selection()
                self.selection_cleared.emit()
            elif not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                # A plain click -- press and release with no drag in
                # between -- clears the selection. The conventional
                # gesture in a viewer like this one, and the author's own
                # walkthrough finding: nothing in the UI called
                # `SiteSession.clear_selection()`, so once a range was
                # dragged its band was permanent for the life of the
                # line. `range_selected` cannot express this itself:
                # `SiteSession.set_selection` clamps both ends into range
                # and can never produce the `(-1, -1)` cleared sentinel,
                # precisely so a caller cannot forge it by dragging off an
                # edge -- clearing gets its own signal instead.
                #
                # Finding 4 (M7 walkthrough re-review): Shift is pick
                # territory (`mousePressEvent`'s own `_pick_mode or shift`
                # guard), but that guard only ever looks at the modifier
                # at PRESS time -- a plain press (no modifier, so `_press`
                # got armed) followed by a release with Shift now held
                # used to fall straight into this branch and clear the
                # selection anyway. Checking the modifier here too keeps
                # the release path consistent with the press path: a
                # Shift held at the moment of release is declined the
                # same way a Shift held at the moment of press is, rather
                # than let releasing it a moment too late turn an
                # accidental modifier into data loss. No pick is fired
                # here either -- `mousePressEvent` already decided this
                # gesture was not a pick when it armed `_press`, and nothing
                # about the release should relitigate that.
                self.clear_selection()
                self.selection_cleared.emit()
            self._press = None
            self._dragging = False

    def wheelEvent(self, event: Any) -> None:  # noqa: N802
        if self.transform is None:
            return
        try:
            x, y = self._local(event)
            steps = event.angleDelta().y() / 120.0
            if steps:
                self.zoom_at(1.25**steps, x, y)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring:
            # wheelEvent is a Qt-invoked virtual method; an uncaught
            # exception here never reaches anything outside PyQt's own
            # exception hook, and the widget would silently stop responding
            # to the wheel from then on. An extreme angleDelta (a fast
            # trackpad fling, or a synthetic event) can raise here two
            # different ways before ViewTransform's own ValueError guard is
            # even reached: `1.25 ** steps` overflows (OverflowError) for a
            # huge positive delta, or underflows to exactly 0.0 for a huge
            # negative one, which then divides a span by zero
            # (ZeroDivisionError) inside zoomed() -- both verified directly.
            # `except Exception`, not just `ValueError`, is why.
            _log(f"could not zoom: {exc}", Qgis.MessageLevel.Warning)
