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
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QImage, QPainter, QPen
from qgis.PyQt.QtWidgets import QWidget

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


def _log(message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Warning) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", level)


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
        r = self.image_rect()
        self.transform = ViewTransform.fit(n_traces, n_samples, t0_ns, dt_ns, r.width(), r.height())
        self._distance = None if distance_along is None else np.asarray(distance_along, dtype=float)
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
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)
        r = self.image_rect()
        t = self.transform
        if t is None:
            painter.setPen(AXIS_COLOUR)
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._message)
            painter.end()
            return
        # Task 13 makes an empty trace or sample axis (n_traces == 0 or
        # n_samples == 0) a legal ViewTransform state, not an error -- so it
        # must be handled *before* any division, not turned into one. The
        # original shape here computed `self._image.width() / t.n_traces`
        # unconditionally, ahead of this check: a live ZeroDivisionError
        # inside paintEvent, silently swallowed by Qt on every repaint
        # (see the module docstring) with the widget just never drawing
        # again. Checking emptiness first and falling through to the same
        # "no image" message branch below keeps the empty-axis contract
        # intact while still being safe to paint.
        if self._image is not None and t.n_traces > 0 and t.n_samples > 0:
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
        painter.end()

    def _paint_cursor(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        if self._cursor < 0:
            return
        x = r.left() + t.x_of_trace(self._cursor + 0.5)
        p.setPen(QPen(CURSOR_COLOUR, 1.5))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

    def _paint_selection(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        a, b = self._selection
        if a < 0:
            return
        x0 = r.left() + t.x_of_trace(a)
        x1 = r.left() + t.x_of_trace(b + 1)
        p.fillRect(QRectF(x0, r.top(), x1 - x0, r.height()), SELECTION_COLOUR)
        p.setPen(QPen(SELECTION_EDGE, 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x0, r.top()), QPointF(x0, r.bottom()))
        p.drawLine(QPointF(x1, r.top()), QPointF(x1, r.bottom()))

    def _paint_picks(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.setBrush(PICK_COLOUR)
        for trace, time_ns in self._picks:
            x = r.left() + t.x_of_trace(trace + 0.5)
            y = r.top() + t.y_of_time(time_ns)
            p.drawPolygon(QPointF(x, y), QPointF(x - 5, y - 9), QPointF(x + 5, y - 9))

    def _paint_axes(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        p.setPen(AXIS_COLOUR)
        font = p.font()
        font.setPointSize(8)
        p.setFont(font)
        # left: two-way time
        p.drawLine(r.topLeft(), r.bottomLeft())
        for tick in nice_ticks(t.time_lo, t.time_hi):
            y = r.top() + t.y_of_time(float(tick))
            p.drawLine(QPointF(r.left() - 4, y), QPointF(r.left(), y))
            p.drawText(
                QRectF(0, y - 8, r.left() - 6, 16),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{tick:g}",
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
        unit = "m" if self._distance is not None else "trace"
        arrow = "→" if self._direction == 1 else "←"
        p.drawText(
            QRectF(r.left(), r.bottom() + 14, r.width(), 14),
            int(Qt.AlignmentFlag.AlignHCenter),
            f"{unit} along line {arrow}",
        )

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
        if self._distance is None:
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
