"""Gain-curve editor sharing the profile viewer's time axis.

Control points are (two-way time ns, gain dB). Vertical position is the
viewer's own mapping, so a point sits exactly beside the sample it affects.
Drag to move, double-click to add, right-click to remove (never below two).

Four invariants a drag gesture depends on, all enforced here rather than
by a caller at a distance:

`set_points` ignores an incoming payload while `_drag is not None`. An
external caller (this widget's own `points_changed` echoing back through
`session.replace_step` -> `stack_changed`, a line switch, a future undo)
can legitimately want to replace the point list at any time, but doing so
mid-drag is not safe: it re-sorts by time, and `mouseMoveEvent` tracks the
dragged point by a *fixed* index that is deliberately not re-sorted until
release. The instant a drag carries a point's time past a neighbour's, an
external resort remaps that fixed index onto the neighbour instead of the
point actually under the cursor -- verified directly: the neighbour's own
value was silently overwritten, not merely reordered. Refusing the payload
here, at the one place `_points` can change, closes every caller of this
kind at once instead of guarding each one individually.

The db range a drag maps against (`_db_range`) is frozen for the gesture's
duration (`_drag_db_range`, set on press, cleared on release), not
recomputed from the point currently being dragged. `db_of_x` at the
widget's right edge otherwise returns `_db_range()`'s own `hi`, which is
`max(dbs) + 6`, itself derived from the *previous* move's write -- a
feedback loop. Confirmed directly: parking the cursor one pixel past the
strip's edge and jiggling by a single pixel ran the gain from 72 dB to
over 1,000,000 dB in a few dozen moves, and `GainCurve.apply` overflows
that (10 ** (db/20)) to an all-`inf` radargram once dB gets into the
thousands. Freezing the range breaks the loop; clamping the mapped
position into the widget's own bounds (`_clamped`) is the other half --
without it, a handle dragged past `MARGIN_TOP` or the strip's edges paints
off-widget, where `handle_at` can never find it again to re-drag or
right-click-remove.

A third invariant, added after a real reproduction: nothing delivers
`mouseReleaseEvent` to a widget that is hidden mid-gesture (a line load
completing mid-drag, or an arrow-key row change stealing focus away --
this widget sets no focus policy of its own, so the processing list keeps
focus during a strip drag either way), so `hideEvent` clears `_drag` and
`_drag_db_range` itself rather than waiting for a release that is never
coming. Without it, `_drag` stays set indefinitely; `set_points`'s own
guard (the first invariant above) then keeps refusing every external
resync, permanently stuck. Worse than merely stuck: `mouseMoveEvent`
guarded only `_drag is None`, not whether a button was actually held, so
a plain, buttonless hover across the strip after this -- no click, no
drag -- silently rewrote the stranded index's point and emitted
`points_changed`, which `plugin.py` routes straight into
`session.replace_step`. `hideEvent` closes the strand; the `event.
buttons()` check at the top of `mouseMoveEvent` is a second, independent
barrier for the same failure, kept even though `hideEvent` alone would
suffice, because this specific failure is silent -- a loud one is worth
fixing once, a silent one is worth two barriers against.

A fourth invariant, and the whole reason `set_points` takes an `owner` at
all: the first invariant's refusal is right for an echo of this strip's
own edit and wrong for a payload belonging to a *different* curve, and
the strip had no way to tell the two apart. So it kept step A's points
while `plugin.py`'s `_on_gain_points` resolved its write target from
`processing_dock.current_row()` at write time -- a different source --
and a row change mid-drag (a plain `Key_Down`: this widget sets no focus
policy, so pressing it never takes the keyboard from the processing
list) sent every later move of A's gesture into step B. Reproduced
directly: B's authored `[[0.0, 0.0], [40.0, -12.0]]` came back as the
dragged A curve, with no error, no log, no undo, and the strip still
displaying A -- no visual cue at all -- while `replace_step` dirtied the
session so the corrupted curve reached `survey.json` on the next save.
The third invariant's `hideEvent` cannot cover this: a curve -> curve
change never hides the strip. An `owner` that differs from the one on
screen therefore *ends* the gesture instead of refusing the payload --
that drag belongs to a curve that is no longer displayed, nothing will
deliver its release either, and refusing would leave it live to write
somewhere it does not belong. The token is opaque here and compared only
for equality; `plugin.py` decides what makes two curves the same one,
and re-checks step identity before every write as the matching second
barrier, the same shape `ProcessingDock._show_form`/`_on_form_committed`
already use for the parameter form.

Under the curve the strip can also show how close each depth is to burning
out: a grey band for the line's amplitude envelope, a dark line for the
trace under the cursor, and dotted lines at the display limits, with
whatever lies past a limit in red (`set_headroom`, `set_trace`). Their
amplitude axis is the strip's own and is unrelated to the curve's dB axis:
zero amplitude is the strip's centre and the limits sit at 80 % of the way
to either edge. The 0 dB line is blue so it reads as part of the curve
rather than as part of that amplitude scale.

A fifth thing the strip holds to, from #49: dB never passes `DB_LIMIT`, the
core's own bound on a `gain_curve` point. `_db_range` stops at it, so the
strip's right edge is exactly +120 and a drag to the edge lands there, and
every value a move or a double-click writes is clamped to it as well. A point
outside the record's time extent (before `transform.t0_ns` or after
`transform.t_end`) cannot be drawn where its time says, because that is
outside the strip's data area, so its handle is pinned to the nearest edge of
the record (a triangle, up or down) at its own dB; `handle_at` finds it
there, so it can be dragged back inside or right-clicked away. The curve
polyline still uses the true positions, as the core applies it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from qgis.core import Qgis
from qgis.PyQt.QtCore import QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from qgis.PyQt.QtWidgets import QToolButton, QWidget

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.qtcompat import event_pos
from nsgeo_qgis.ui.view_transform import ViewTransform

# The core's own bound on a gain_curve point's dB (its `points` schema).
DB_LIMIT = 120.0
HANDLE_RADIUS = 5
CAPTION_GAP = 4
CAPTION_ROW = 14.0
CAPTION_MIN_POINT_SIZE = 5.0
RESET_MIN_HEIGHT = 14
HIT_RADIUS = 8
PAD_X = 10
CURVE_COLOUR = QColor(48, 140, 198)
ZERO_COLOUR = QColor(130, 185, 222)
ENVELOPE_COLOUR = QColor(0, 0, 0, 31)
PAST_LIMIT_COLOUR = QColor(179, 38, 62)
TRACE_COLOUR = QColor(20, 20, 20)
LIMIT_COLOUR = QColor(60, 60, 60)
# Where the display limit sits, as a fraction of the half-width inside the
# padding, and how far past it an amplitude may be drawn before it clips.
LIMIT_FRACTION = 0.8
OVERSHOOT = 1.25


@dataclass(frozen=True)
class Headroom:
    """What the strip draws under the curve."""

    limit: float  # the display limit, > 0
    t0_ns: float  # time of the first displayed row
    dt_ns: float
    envelope: np.ndarray  # one value >= 0 per displayed row
    one_sided: bool  # unipolar output: draw the band on the positive side only


class GainStrip(QWidget):
    points_changed = pyqtSignal(list)
    reset_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(96)
        self.setMouseTracking(True)
        self._points: list[list[float]] = []
        self._transform: ViewTransform | None = None
        self._top = 0.0
        self._drag: int | None = None
        # The db range at the moment the current drag started, or None
        # between gestures: see the module docstring's second invariant.
        self._drag_db_range: tuple[float, float] | None = None
        # Whose curve is on screen: an opaque token from whoever last
        # called set_points. See the module docstring's fourth invariant.
        self._owner: Any = None
        self._headroom: Headroom | None = None
        self._trace: np.ndarray | None = None
        self.reset_button = QToolButton(self)
        self.reset_button.setText("Reset")
        self.reset_button.setToolTip("Reset the gain curve to a flat 0 dB")
        # The bottom margin is only 28 px: a compact button fits it.
        small = self.reset_button.font()
        small.setPointSize(8)
        self.reset_button.setFont(small)
        self.reset_button.setStyleSheet("QToolButton { padding: 1px 6px; }")
        self.reset_button.clicked.connect(self._on_reset_clicked)
        self.reset_button.hide()

    def _on_reset_clicked(self, _checked: bool = False) -> None:
        try:
            self.reset_requested.emit()
        except Exception as exc:  # noqa: BLE001 -- a Qt slot: never raise into Qt
            _log(f"gain strip Reset failed: {exc}", Qgis.MessageLevel.Warning)

    def _place_reset_button(self) -> None:
        """Centre the button in the band below the time axis, or hide it
        when there is no transform or the band is too short for it."""
        t = self._transform
        if t is None:
            self.reset_button.hide()
            return
        # Clear of the handles: a round handle on the last sample and a
        # pinned one both reach HANDLE_RADIUS past the record's edge.
        start = self._top + t.height + HANDLE_RADIUS + 2
        avail = self.height() - start
        if avail < RESET_MIN_HEIGHT:
            self.reset_button.hide()
            return
        hint = self.reset_button.sizeHint()
        h = min(hint.height(), int(avail))
        x = max(0, round((self.width() - hint.width()) / 2))
        y = round(start + (avail - h) / 2)
        self.reset_button.setGeometry(x, y, hint.width(), h)
        self.reset_button.show()

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        try:
            self._place_reset_button()
        except Exception as exc:  # noqa: BLE001 -- a Qt override
            _log(f"could not place the gain strip's Reset: {exc}", Qgis.MessageLevel.Warning)

    # ---- headroom -----------------------------------------------------------
    @property
    def headroom(self) -> Headroom | None:
        return self._headroom

    @property
    def trace(self) -> np.ndarray | None:
        return self._trace

    def set_headroom(self, headroom: Headroom | None) -> None:
        """Show the envelope band and display limits, or `None` to draw the
        curve alone (which also clears the trace). A limit that is not a
        positive finite number cannot be drawn, so it counts as `None`."""
        if headroom is not None and not (np.isfinite(headroom.limit) and headroom.limit > 0):
            headroom = None
        self._headroom = headroom
        if headroom is None or (
            self._trace is not None and len(self._trace) != len(headroom.envelope)
        ):
            self._trace = None
        self.update()

    def set_trace(self, trace: np.ndarray | None) -> None:
        """The trace under the cursor, one value per displayed row. Ignored
        while there is no headroom, or when its length is not the band's."""
        if (
            trace is not None
            and self._headroom is not None
            and len(trace) == len(self._headroom.envelope)
        ):
            self._trace = trace
        else:
            self._trace = None
        self.update()

    def x_of_amplitude(self, a: float) -> float:
        """Strip x of amplitude `a`: the centre for 0, the dotted limit at
        `LIMIT_FRACTION` of the way to the edge, and no further than the
        edge (`w - PAD_X`) however large `a` is. Only with a headroom set."""
        assert self._headroom is not None
        half = self.width() / 2
        frac = min(max(a / self._headroom.limit, -OVERSHOOT), OVERSHOOT)
        return half + frac * LIMIT_FRACTION * (half - PAD_X)

    def _xs_of_amplitude(self, a: np.ndarray) -> np.ndarray:
        assert self._headroom is not None
        half = self.width() / 2
        frac = np.clip(np.nan_to_num(a / self._headroom.limit), -OVERSHOOT, OVERSHOOT)
        return np.asarray(half + frac * LIMIT_FRACTION * (half - PAD_X))

    # ---- mappings ---------------------------------------------------------
    def set_time_mapping(self, transform: ViewTransform, top_px: float) -> None:
        self._transform = transform
        self._top = float(top_px)
        self._place_reset_button()
        self.update()

    def set_points(self, points: list[list[float]], owner: Any) -> None:
        """Replace the displayed curve. `owner` says whose curve it is: an
        opaque token, compared only for equality, that the caller keeps
        stable for as long as the same curve is being edited.

        Required rather than defaulted, even though `ProfileDock.
        show_gain_strip` is its only production caller: the two payloads
        this widget must tell apart (see the module docstring's first and
        fourth invariants) are distinguished by nothing else, so a caller
        that forgets to say whose curve it is has no safe answer to fall
        back on.
        """
        if owner != self._owner:
            # A different curve. The gesture in progress belongs to one
            # that is no longer on screen and can no longer be delivered a
            # release, so end it here and accept the payload rather than
            # refuse it below: see the module docstring's fourth invariant.
            self._owner = owner
            self._drag = None
            self._drag_db_range = None
        elif self._drag is not None:
            # See the module docstring's first invariant: an external
            # payload arriving mid-drag would re-sort under a fixed index
            # a real drag deliberately does not re-sort until release.
            return
        self._points = sorted([[float(t), float(db)] for t, db in points], key=lambda p: p[0])
        self.update()

    def points(self) -> list[list[float]]:
        return [list(p) for p in self._points]

    def _db_range(self) -> tuple[float, float]:
        if self._drag_db_range is not None:
            return self._drag_db_range
        dbs = [p[1] for p in self._points] or [0.0]
        # Whole dB, so every caption number is at most four characters.
        return (
            max(-DB_LIMIT, min(-6.0, float(math.floor(min(dbs) - 6.0)))),
            min(DB_LIMIT, max(24.0, float(math.ceil(max(dbs) + 6.0)))),
        )

    @staticmethod
    def _limited(db: float) -> float:
        return min(max(db, -DB_LIMIT), DB_LIMIT)

    def _clamped(self, pos: Any) -> tuple[float, float]:
        """`(x, y)` of `pos`, clamped into the domain `x_of_db`/`y_of_time`
        actually cover. Qt's implicit mouse grab keeps delivering move
        events to the widget that started the drag even once the cursor
        leaves it (ordinary during a fast or wide drag on a 96 px-wide
        strip), and an unclamped position both feeds the runaway
        `db_of_x` loop the module docstring describes and can push a
        handle to a `y` outside `handle_at`'s reach.

        The `y` bound is `[self._top, self._top + self._transform.height]`
        -- the transform's *own* notion of its vertical extent -- not
        `[0, self.height()]`. `y_of_time`/`time_of_y` never reference this
        widget's actual Qt height at all, only `self._transform` and
        `self._top`; those two can disagree with a real on-screen height
        that has not been resized to match yet (confirmed directly: a
        dock added to an unshown main window sizes this widget to a
        default far short of the transform's own `height`), and clamping
        against the wrong one silently maps a legitimate drag position to
        the wrong time instead of merely bounding it."""
        assert self._transform is not None
        x = min(max(pos.x(), float(PAD_X)), float(self.width() - PAD_X))
        y_lo, y_hi = self._top, self._top + self._transform.height
        y = min(max(pos.y(), y_lo), y_hi)
        return x, y

    def x_of_db(self, db: float) -> float:
        lo, hi = self._db_range()
        return PAD_X + (db - lo) / (hi - lo) * (self.width() - 2 * PAD_X)

    def db_of_x(self, x: float) -> float:
        lo, hi = self._db_range()
        return lo + (x - PAD_X) / (self.width() - 2 * PAD_X) * (hi - lo)

    def y_of_time(self, t: float) -> float:
        assert self._transform is not None
        return self._top + self._transform.y_of_time(t)

    def time_of_y(self, y: float) -> float:
        assert self._transform is not None
        return self._transform.time_of_y(y - self._top)

    def _drawn(self, i: int) -> tuple[float, float, int]:
        """Where point `i`'s handle is drawn: `(x, y, off)`. A point before
        the record sits on its top edge (`off == -1`), one after it on its
        bottom edge (`off == 1`), each at its own dB; any other is where
        its time says (`off == 0`). An off-record handle's centre is
        `HANDLE_RADIUS` inside the record, so its triangle's tip is on the
        edge and its body clear of the Reset button below."""
        assert self._transform is not None
        t, db = self._points[i]
        off = -1 if t < self._transform.t0_ns else 1 if t > self._transform.t_end else 0
        if off < 0:
            t = self._transform.t0_ns
        elif off > 0:
            t = self._transform.t_end
        y = self.y_of_time(t) - off * HANDLE_RADIUS
        return self.x_of_db(db), y, off

    def _caption(self) -> tuple[QFont, str, str | None, str, tuple[QRectF, QRectF | None, QRectF]]:
        """The caption's font, texts and rectangles (strip coordinates).
        The two numbers are never cut: when they do not fit side by side the
        font steps down until they do. "dB" is centred in the gap between
        them and dropped when it does not fit there with a margin each side."""
        lo, hi = self._db_range()
        low, high = f"{lo:g}", f"{hi:g}"
        font = QFont(self.font())
        room = self.width() - 4
        while True:
            fm = QFontMetrics(font)
            wl, wh = fm.horizontalAdvance(low), fm.horizontalAdvance(high)
            size = font.pointSizeF()
            if wl + wh + CAPTION_GAP <= room or size <= CAPTION_MIN_POINT_SIZE:
                break
            font.setPointSizeF(max(CAPTION_MIN_POINT_SIZE, size - 1.0))
        gap = room - wl - wh
        wd = fm.horizontalAdvance("dB")
        low_r = QRectF(2.0, 0.0, wl, CAPTION_ROW)
        high_r = QRectF(self.width() - 2.0 - wh, 0.0, wh, CAPTION_ROW)
        mid_r = None
        mid = None
        if wd + 2 * CAPTION_GAP <= gap:
            mid = "dB"
            mid_r = QRectF(2.0 + wl + (gap - wd) / 2, 0.0, wd, CAPTION_ROW)
        return font, low, mid, high, (low_r, mid_r, high_r)

    def caption_texts(self) -> tuple[str, str | None, str]:
        """The (low, "dB" or None, high) texts the paint draws."""
        _font, low, mid, high, _rects = self._caption()
        return low, mid, high

    def caption_font(self) -> QFont:
        return self._caption()[0]

    def caption_rects(self) -> tuple[QRectF, QRectF | None, QRectF]:
        """Where the low, "dB" (None when dropped) and high texts are drawn."""
        return self._caption()[4]

    def handle_at(self, pos: Any) -> int | None:
        if self._transform is None:
            return None
        best, best_d = None, HIT_RADIUS + 1.0
        for i in range(len(self._points)):
            x, y, _off = self._drawn(i)
            d = ((x - pos.x()) ** 2 + (y - pos.y()) ** 2) ** 0.5
            if d < best_d:
                best, best_d = i, d
        return best

    # ---- painting ---------------------------------------------------------
    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        # Guarded like ProfileView.paintEvent: try/finally so the painter
        # always ends (a painter left bound to the widget crashes the next
        # repaint), and except so a bad payload leaves a blank strip, not
        # an exception out of a Qt-invoked override.
        p = QPainter(self)
        try:
            p.fillRect(self.rect(), QColor(250, 250, 250))
            if self._transform is None or not self._points:
                return
            self._paint_headroom(p)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            x0 = self.x_of_db(0.0)
            p.setPen(QPen(ZERO_COLOUR, 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x0, 0), QPointF(x0, self.height()))
            pts = [QPointF(self.x_of_db(db), self.y_of_time(t)) for t, db in self._points]
            # hold the end values outside the control range, like np.interp does
            ext = [QPointF(pts[0].x(), 0.0), *pts, QPointF(pts[-1].x(), self.height())]
            p.setPen(QPen(CURVE_COLOUR, 2))
            p.drawPolyline(*ext)
            p.setBrush(QColor(255, 255, 255))
            r = HANDLE_RADIUS
            for i in range(len(pts)):
                x, y, off = self._drawn(i)
                if off == 0:
                    p.drawEllipse(QPointF(x, y), r, r)
                else:
                    # A triangle with its tip on the record's edge and its body
                    # inside it: up at the top, down at the bottom.
                    p.drawPolygon(
                        QPolygonF(
                            [
                                QPointF(x, y + off * r),
                                QPointF(x - r, y - off * r),
                                QPointF(x + r, y - off * r),
                            ]
                        )
                    )
            p.setPen(QColor(90, 90, 90))
            self._paint_caption(p)
        except Exception as exc:  # noqa: BLE001 -- see the comment above
            _log(f"could not paint the gain strip: {exc}", Qgis.MessageLevel.Warning)
        finally:
            p.end()

    def _paint_caption(self, p: QPainter) -> None:
        font, low, mid, high, (low_r, mid_r, high_r) = self._caption()
        p.setFont(font)
        # TextDontClip: a tall font spills over the 14 px row rather than being cut.
        flags = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextDontClip
        p.drawText(low_r, int(flags | Qt.AlignmentFlag.AlignLeft), low)
        p.drawText(high_r, int(flags | Qt.AlignmentFlag.AlignRight), high)
        if mid is not None and mid_r is not None:
            p.drawText(mid_r, int(flags | Qt.AlignmentFlag.AlignHCenter), mid)

    def _paint_headroom(self, p: QPainter) -> None:
        """Band, trace and limits, each in its own colour inside the limits
        and red outside them. Unantialiased so a one-pixel line stays one
        solid pixel."""
        hr = self._headroom
        if hr is None:
            return
        n = len(hr.envelope)
        ys = [self.y_of_time(hr.t0_ns + i * hr.dt_ns) for i in range(n)]
        xl, xr = self.x_of_amplitude(-hr.limit), self.x_of_amplitude(hr.limit)
        h = float(self.height())
        inside = QRectF(xl, 0.0, xr - xl, h)
        outside = (QRectF(0.0, 0.0, xl, h), QRectF(xr, 0.0, self.width() - xr, h))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        past = QColor(PAST_LIMIT_COLOUR)
        past.setAlpha(184)

        def painted(draw: Any, colour: QColor, past_colour: QColor) -> None:
            for clip, c in [(inside, colour), *((r, past_colour) for r in outside)]:
                p.save()
                p.setClipRect(clip)
                draw(c)
                p.restore()

        if n >= 2:
            env = np.maximum(np.nan_to_num(hr.envelope), 0.0)
            right = self._xs_of_amplitude(env)
            left = self._xs_of_amplitude(-env) if not hr.one_sided else np.full(n, self.width() / 2)
            poly = QPolygonF(
                [QPointF(float(x), float(y)) for x, y in zip(right, ys, strict=True)]
                + [QPointF(float(x), float(y)) for x, y in zip(left[::-1], ys[::-1], strict=True)]
            )

            def draw_band(c: QColor) -> None:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawPolygon(poly)

            painted(draw_band, ENVELOPE_COLOUR, past)
            if self._trace is not None:
                tx = self._xs_of_amplitude(np.asarray(self._trace, dtype=float))
                line = QPolygonF([QPointF(float(x), float(y)) for x, y in zip(tx, ys, strict=True)])

                def draw_trace(c: QColor) -> None:
                    p.setPen(QPen(c, 1))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPolyline(line)

                painted(draw_trace, TRACE_COLOUR, PAST_LIMIT_COLOUR)
        p.setPen(QPen(LIMIT_COLOUR, 1, Qt.PenStyle.DotLine))
        for x in (xl, xr):
            p.drawLine(QPointF(x, 0.0), QPointF(x, h))

    # ---- lifecycle ----------------------------------------------------------
    def hideEvent(self, event: Any) -> None:  # noqa: N802
        """Nothing delivers a matching `mouseReleaseEvent` to a widget
        hidden mid-drag: see the module docstring's third invariant. Ends
        the gesture here instead of leaving `_drag` stranded."""
        super().hideEvent(event)
        self._drag = None
        self._drag_db_range = None

    # ---- mouse ------------------------------------------------------------
    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if self._transform is None:
            return
        pos = event_pos(event)
        hit = self.handle_at(pos)
        if event.button() == Qt.MouseButton.RightButton:
            if hit is not None and len(self._points) > 2:
                del self._points[hit]
                self.update()
                self.points_changed.emit(self.points())
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = hit
            # Frozen for the whole gesture: see the module docstring's
            # second invariant. None (no freeze) when this press did not
            # hit a handle -- there is no gesture to freeze a range for.
            self._drag_db_range = self._db_range() if hit is not None else None

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802
        try:
            self._double_click(event)
        except Exception as exc:  # noqa: BLE001 -- a Qt override: never raise into Qt
            _log(f"could not add a gain point: {exc}", Qgis.MessageLevel.Warning)

    def _double_click(self, event: Any) -> None:
        if self._transform is None or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event_pos(event)
        if self.handle_at(pos) is not None:
            return
        x, y = self._clamped(pos)
        self._points.append([self.time_of_y(y), self._limited(self.db_of_x(x))])
        self._points.sort(key=lambda q: q[0])
        self._drag = None
        self._drag_db_range = None
        self.update()
        self.points_changed.emit(self.points())

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        try:
            self._move(event)
        except Exception as exc:  # noqa: BLE001 -- a Qt override: never raise into Qt
            _log(f"could not move a gain point: {exc}", Qgis.MessageLevel.Warning)

    def _move(self, event: Any) -> None:
        if not event.buttons():
            # A move with no button held is a hover, not a drag
            # continuation: see the module docstring's third invariant.
            # Independent of hideEvent's own fix for the same failure --
            # kept as a second barrier because a stranded _drag silently
            # rewriting a point on a plain hover is silent, not loud.
            return
        if self._drag is None or self._transform is None:
            return
        if self._drag >= len(self._points):
            # An external set_points during a drag is refused (see
            # set_points), but a drag started before that guard existed is
            # not the only route here -- a future caller with access to
            # _points directly should not turn into an IndexError in a
            # slot nothing sees fail. Defensive, matching this widget's own
            # policy of enforcing its invariants locally rather than
            # trusting every caller.
            self._drag = None
            self._drag_db_range = None
            return
        pos = event_pos(event)
        x, y = self._clamped(pos)
        self._points[self._drag] = [self.time_of_y(y), self._limited(self.db_of_x(x))]
        self.update()
        self.points_changed.emit(self.points())  # live: one broadcast multiply per move

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self._drag_db_range = None
            self._points.sort(key=lambda q: q[0])
            self.update()
            self.points_changed.emit(self.points())
