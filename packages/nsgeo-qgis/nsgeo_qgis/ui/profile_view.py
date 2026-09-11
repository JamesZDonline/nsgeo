"""The profile viewer: a QWidget that paints a cached radargram image
through a ViewTransform, with axes, a cursor, a selection band and picks.

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
"""

from __future__ import annotations

from typing import Any

import numpy as np
from nsgeo.velocity import VelocityModel
from qgis.core import Qgis
from qgis.PyQt.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QImage, QPainter, QPen
from qgis.PyQt.QtWidgets import QWidget

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.qtcompat import event_pos
from nsgeo_qgis.ui.view_transform import ViewTransform, nice_ticks

MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM = 56, 48, 8, 28
BACKGROUND = QColor(250, 250, 250)
AXIS_COLOUR = QColor(60, 60, 60)
CURSOR_COLOUR = QColor(255, 159, 26)
SELECTION_COLOUR = QColor(48, 140, 198, 60)
SELECTION_EDGE = QColor(48, 140, 198)
PICK_COLOUR = QColor(224, 66, 27)
DRAG_THRESHOLD_PX = 3


class ProfileView(QWidget):
    trace_hovered = pyqtSignal(int)
    range_selected = pyqtSignal(int, int)
    pick_requested = pyqtSignal(int, float)  # trace index, two-way time (ns)
    view_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(240, 120)
        self.transform: ViewTransform | None = None
        self._image: QImage | None = None
        self._distance: np.ndarray | None = None
        self._velocity: VelocityModel | None = None
        self._direction = 1
        self._cursor = -1
        self._selection = (-1, -1)
        self._picks: list[tuple[int, float]] = []
        self._pick_mode = False
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
        self.transform = ViewTransform.fit(n_traces, n_samples, t0_ns, dt_ns, r.width(), r.height())
        self._distance = distance_along
        self._message = "loading…"
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

    def set_picks(self, picks: list[tuple[int, float]]) -> None:
        self._picks = list(picks)
        self.update()

    def set_pick_mode(self, flag: bool) -> None:
        self._pick_mode = flag
        self.setCursor(Qt.CursorShape.CrossCursor if flag else Qt.CursorShape.ArrowCursor)

    def clear(self) -> None:
        self.transform = None
        self._image = None
        self._cursor = -1
        self._selection = (-1, -1)
        self._picks = []
        self._message = "no line open"
        self.update()

    # ---- view changes -----------------------------------------------------
    def fit(self) -> None:
        if self.transform is None:
            return
        t = self.transform
        r = self.image_rect()
        self.transform = ViewTransform.fit(
            t.n_traces, t.n_samples, t.t0_ns, t.dt_ns, r.width(), r.height()
        )
        self.view_changed.emit()
        self.update()

    def one_to_one(self) -> None:
        """One trace per pixel column, anchored at the current window's left."""
        if self.transform is None:
            return
        t = self.transform
        self.transform = t.with_window(t.trace_lo, t.trace_lo + t.width, t.time_lo, t.time_hi)
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
                x, y, w, h = t.source_rect()
                painter.drawImage(QRectF(r), self._image, QRectF(x * sx, y * sy, w * sx, h * sy))
            else:
                painter.setPen(AXIS_COLOUR)
                painter.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self._message)
            painter.setClipRect(r)
            self._paint_selection(painter, r, t)
            self._paint_picks(painter, r, t)
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

    def _selection_bounds(self, t: ViewTransform) -> tuple[float, float] | None:
        """Local (unoffset by `r.left()`) x-bounds of the selection band, or
        `None` when there is no selection. `b + 1`, not `b`: the selection
        is inclusive of trace `b`, so its right edge is the *start* of the
        next trace -- factored out so this is a plain value comparable in a
        test without rendering a pixel."""
        a, b = self._selection
        if a < 0:
            return None
        return t.x_of_trace(a), t.x_of_trace(b + 1)

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
        p.drawText(
            QRectF(0, 0, r.left() - 6, MARGIN_TOP + 10), int(Qt.AlignmentFlag.AlignRight), "ns"
        )
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
                QRectF(r.right() + 6, 0, MARGIN_RIGHT - 8, MARGIN_TOP + 10),
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
            f"{self._distance_unit_label()} along line {self._direction_arrow()}",
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
        idx = np.arange(t.n_traces, dtype=float)
        d = self._distance
        d_lo, d_hi = np.interp([lo, min(hi, t.n_traces - 1)], idx, d)
        order = np.argsort(d)
        out = []
        for tick in nice_ticks(min(d_lo, d_hi), max(d_lo, d_hi)):
            trace = float(np.interp(tick, d[order], idx[order]))
            out.append((f"{tick:g}", t.x_of_trace(trace)))
        return out

    # ---- mouse ------------------------------------------------------------
    def _local(self, event: Any) -> tuple[float, float]:
        pos = event_pos(event)
        r = self.image_rect()
        return pos.x() - r.left(), pos.y() - r.top()

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if self.transform is None:
            return
        x, y = self._local(event)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event_pos(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self._pick_mode or shift:
                self.pick_requested.emit(
                    self.transform.trace_index_at(x), self.transform.time_of_y(y)
                )
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
        if self._press is not None:
            if abs(pos.x() - self._press.x()) > DRAG_THRESHOLD_PX:
                self._dragging = True
                a = self.transform.trace_index_at(self._press.x() - self.image_rect().left())
                b = self.transform.trace_index_at(x)
                self.set_selection(a, b)
            return
        if 0 <= x < self.transform.width:
            self.trace_hovered.emit(self.transform.trace_index_at(x))

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
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
        if self._press is not None and self.transform is not None:
            if self._dragging:
                a, b = self._selection
                self.range_selected.emit(a, b)
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
