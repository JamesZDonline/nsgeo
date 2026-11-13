"""A small picture of a magnetometer setup: where the first traverse starts and
which way each of the first eight was walked.

The arrows come from the core (`nsgeo.mag.traverses` on a nominal square grid,
`walked_direction` for the colour), so the picture and the import agree by
construction. Traverses are drawn three times further apart than the spacing so
the first eight can be read.
"""

from __future__ import annotations

import contextlib

from nsgeo.geometry import Grid
from nsgeo.mag import MagSetup, traverses, walked_direction
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QPainter, QPen, QPolygonF
from qgis.PyQt.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

SIZE = 30.0  # the nominal grid, metres
COUNT = 8  # traverses drawn
SPREAD = 3.0  # drawn this many times further apart than the spacing
NOTE = (
    "Traverses 1–8 only, drawn three times further apart than the spacing so they can be "
    "read. Numbers are traverse numbers, as in the missing-data summary."
)
OUT = QColor("#c0392b")
BACK = QColor("#2f6db5")

#: (row, start (x, y), end (x, y), walked): grid-local metres; walked is +1 the
#: first traverse's way and -1 the other way.
Arrow = tuple[int, tuple[float, float], tuple[float, float], int]


class _Canvas(QWidget):
    def __init__(self, owner: MagSetupPicture) -> None:
        super().__init__(owner)
        self._owner = owner
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def heightForWidth(self, width: int) -> int:
        return width

    def paintEvent(self, event: object) -> None:  # noqa: N802 -- Qt's name
        with contextlib.suppress(Exception):  # a paint handler must never raise
            self._paint()

    def _paint(self) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        pad = side * 0.11
        span = side - 2 * pad
        left = (self.width() - side) / 2 + pad
        top = (self.height() - side) / 2 + pad

        def pt(x: float, y: float) -> QPointF:
            return QPointF(left + x / SIZE * span, top + span - y / SIZE * span)

        p.fillRect(QRectF(left, top, span, span), QColor("#fafaf8"))
        p.setPen(QPen(QColor("#666666"), 1))
        p.drawRect(QRectF(left, top, span, span))
        p.setPen(QColor("#333333"))
        p.drawText(pt(0, 0) + QPointF(0, 16), "origin (0, 0)")
        p.drawText(pt(SIZE, 0) + QPointF(-28, 16), "X →")
        p.drawText(pt(0, SIZE) + QPointF(-pad + 2, 4), "Y ↑")
        setup = self._owner.current_setup
        if setup is None:
            p.setPen(QColor("#8a5a00"))
            p.drawText(
                QRectF(left, top, span, span),
                int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                self._owner.error_text,
            )
            return
        cx = SIZE if setup.far_x else 0.0
        cy = SIZE if setup.far_y else 0.0
        p.setPen(QPen(QColor("#8a5a00"), 1))
        p.setBrush(QColor("#f2c94c"))
        p.drawEllipse(pt(cx, cy), 6.0, 6.0)
        p.drawText(pt(cx, cy) + QPointF(-38 if setup.far_x else 10, -10), "start")
        for row, a, b, walked in self._owner.arrows():
            colour = OUT if walked > 0 else BACK
            p.setPen(QPen(colour, 2))
            p.drawLine(pt(*a), pt(*b))
            p.setBrush(colour)
            tip, tail = pt(*b), pt(*a)
            dx, dy = tip.x() - tail.x(), tip.y() - tail.y()
            length = (dx * dx + dy * dy) ** 0.5 or 1.0
            ux, uy = dx / length, dy / length
            head = QPolygonF(
                [
                    tip,
                    QPointF(tip.x() - 7 * ux + 3.5 * uy, tip.y() - 7 * uy - 3.5 * ux),
                    QPointF(tip.x() - 7 * ux - 3.5 * uy, tip.y() - 7 * uy + 3.5 * ux),
                ]
            )
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(head)
            p.setPen(QColor("#333333"))
            p.drawText(tail + QPointF(-3 - 10 * ux, 4 - 10 * uy), str(row + 1))


class MagSetupPicture(QWidget):
    """The picture, its legend and its note. `set_setup` or `set_error` redraws it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_setup: MagSetup | None = None
        self.error_text = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = _Canvas(self)
        layout.addWidget(self.canvas, 1)
        legend = QLabel(
            '<span style="color:#c0392b">&#9473;</span> walked the first traverse\'s way &nbsp; '
            '<span style="color:#2f6db5">&#9473;</span> walked back'
        )
        legend.setWordWrap(True)
        layout.addWidget(legend)
        self.note = QLabel(NOTE)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

    def set_setup(self, setup: MagSetup) -> None:
        self.current_setup = setup
        self.error_text = ""
        self.note.setText(NOTE)
        self.canvas.update()

    def set_error(self, message: str) -> None:
        self.current_setup = None
        self.error_text = message
        self.note.setText(message)
        self.canvas.update()

    def arrows(self) -> list[Arrow]:
        """The first eight traverses as (row, start, end, walked), in grid-local metres."""
        setup = self.current_setup
        if setup is None:
            return []
        grid = Grid("picture", (0.0, 0.0), 0.0, SIZE, SIZE, "EPSG:3857", setup.spacing_m)
        n_readings = max(1, round(SIZE * setup.readings_per_metre))
        placed = traverses(setup, grid, COUNT, n_readings)
        first = placed[0].placement.offset
        out: list[Arrow] = []
        for t in placed:
            pl = t.placement
            across = first + (pl.offset - first) * SPREAD
            start = pl.start_along
            end = start + pl.direction * (n_readings - 1) / setup.readings_per_metre
            a, b = (across, start), (across, end)
            if setup.axis == "x":
                a, b = (start, across), (end, across)
            out.append((t.row, a, b, walked_direction(setup, t.row)))
        return out
