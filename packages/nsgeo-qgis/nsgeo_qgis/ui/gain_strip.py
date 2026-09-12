"""Gain-curve editor sharing the profile viewer's time axis.

Control points are (two-way time ns, gain dB). Vertical position is the
viewer's own mapping, so a point sits exactly beside the sample it affects.
Drag to move, double-click to add, right-click to remove (never below two).
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

    # ---- mappings ---------------------------------------------------------
    def set_time_mapping(self, transform: ViewTransform, top_px: float) -> None:
        self._transform = transform
        self._top = float(top_px)
        self.update()

    def set_points(self, points: list[list[float]]) -> None:
        self._points = sorted([[float(t), float(db)] for t, db in points], key=lambda p: p[0])
        self.update()

    def points(self) -> list[list[float]]:
        return [list(p) for p in self._points]

    def _db_range(self) -> tuple[float, float]:
        dbs = [p[1] for p in self._points] or [0.0]
        return min(-6.0, min(dbs) - 6.0), max(24.0, max(dbs) + 6.0)

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

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802
        if self._transform is None or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event_pos(event)
        if self.handle_at(pos) is not None:
            return
        self._points.append([self.time_of_y(pos.y()), self.db_of_x(pos.x())])
        self._points.sort(key=lambda q: q[0])
        self._drag = None
        self.update()
        self.points_changed.emit(self.points())

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if self._drag is None or self._transform is None:
            return
        pos = event_pos(event)
        self._points[self._drag] = [self.time_of_y(pos.y()), self.db_of_x(pos.x())]
        self.update()
        self.points_changed.emit(self.points())  # live: one broadcast multiply per move

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self._points.sort(key=lambda q: q[0])
            self.update()
            self.points_changed.emit(self.points())
