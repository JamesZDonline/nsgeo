"""Gain-curve editor sharing the profile viewer's time axis.

Control points are (two-way time ns, gain dB). Vertical position is the
viewer's own mapping, so a point sits exactly beside the sample it affects.
Drag to move, double-click to add, right-click to remove (never below two).

Two invariants a drag gesture depends on, both enforced here rather than by
a caller at a distance:

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
"""

from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import QPointF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPen
from qgis.PyQt.QtWidgets import QWidget

from nsgeo_qgis.qtcompat import event_pos
from nsgeo_qgis.ui.view_transform import ViewTransform

HANDLE_RADIUS = 5
HIT_RADIUS = 8
PAD_X = 10
CURVE_COLOUR = QColor(48, 140, 198)
ZERO_COLOUR = QColor(160, 160, 160)


class GainStrip(QWidget):
    points_changed = pyqtSignal(list)

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

    # ---- mappings ---------------------------------------------------------
    def set_time_mapping(self, transform: ViewTransform, top_px: float) -> None:
        self._transform = transform
        self._top = float(top_px)
        self.update()

    def set_points(self, points: list[list[float]]) -> None:
        if self._drag is not None:
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
        return min(-6.0, min(dbs) - 6.0), max(24.0, max(dbs) + 6.0)

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

    def handle_at(self, pos: Any) -> int | None:
        if self._transform is None:
            return None
        best, best_d = None, HIT_RADIUS + 1.0
        for i, (t, db) in enumerate(self._points):
            d = ((self.x_of_db(db) - pos.x()) ** 2 + (self.y_of_time(t) - pos.y()) ** 2) ** 0.5
            if d < best_d:
                best, best_d = i, d
        return best

    # ---- painting ---------------------------------------------------------
    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        p = QPainter(self)
        try:
            p.fillRect(self.rect(), QColor(250, 250, 250))
            if self._transform is None or not self._points:
                return
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
            for q in pts:
                p.drawEllipse(q, HANDLE_RADIUS, HANDLE_RADIUS)
            p.setPen(QColor(90, 90, 90))
            lo, hi = self._db_range()
            p.drawText(2, 12, f"{lo:g}")
            p.drawText(self.width() - 26, 12, f"{hi:g} dB")
        finally:
            p.end()

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
        if self._transform is None or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event_pos(event)
        if self.handle_at(pos) is not None:
            return
        x, y = self._clamped(pos)
        self._points.append([self.time_of_y(y), self.db_of_x(x)])
        self._points.sort(key=lambda q: q[0])
        self._drag = None
        self._drag_db_range = None
        self.update()
        self.points_changed.emit(self.points())

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
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
        self._points[self._drag] = [self.time_of_y(y), self.db_of_x(x)]
        self.update()
        self.points_changed.emit(self.points())  # live: one broadcast multiply per move

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self._drag_db_range = None
            self._points.sort(key=lambda q: q[0])
            self.update()
            self.points_changed.emit(self.points())
