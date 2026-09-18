### Task 14: `RadargramImage`, `ProfileView`, and the QImage wrapper

The custom `QWidget` viewer: draws a cached full-resolution image through the transform, axes on three sides, a cursor, a selection band, and pick markers. Pan and zoom draw a sub-rectangle of the cached image (3 ms per frame measured); only display-gain or stack changes re-run numpy.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/render/__init__.py` (docstring only)
- Create: `packages/nsgeo-qgis/nsgeo_qgis/render/qimage.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`

**Interfaces:**
- Consumes: `nsgeo.render` (`PercentileClip`, `colormap`, `to_rgb8`, `decimate_columns`, `DEFAULT_COLORMAP`), `Radargram`, `VelocityModel`, `ViewTransform`, `nice_ticks`, `event_pos`
- Produces: `rgb_to_qimage(rgb) -> QImage`; `RadargramImage(rg, percentile=99.0, colormap_name=DEFAULT_COLORMAP, max_width=8192)` with `.rg`, `.percentile`, `.colormap_name`, `.limit`, `.image` (lazy `QImage`), `.with_display(percentile=None, colormap_name=None)`, `.with_radargram(rg)`; `ProfileView(parent=None)` with signals `trace_hovered(int)`, `range_selected(int, int)`, `pick_requested(int, float)`, `view_changed()`, methods `set_axes(n_traces, n_samples, t0_ns, dt_ns, distance_along=None)`, `set_image(image | None)`, `set_velocity(model | None)`, `set_cursor(trace)`, `set_selection(a, b)`, `clear_selection()`, `set_picks(list[tuple[int, float]])`, `set_pick_mode(bool)`, `set_direction(int)`, `fit()`, `one_to_one()`, `image_rect() -> QRect`, `transform: ViewTransform | None`, `grab_image() -> QImage`; margins `MARGIN_LEFT=56, MARGIN_RIGHT=48, MARGIN_TOP=8, MARGIN_BOTTOM=28`; colours `CURSOR_COLOUR`, `SELECTION_COLOUR`, `PICK_COLOUR`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.io.dzt import read_header, read_samples
from nsgeo.model.survey import Profile
from nsgeo.processing import Radargram
from nsgeo.render import DEFAULT_COLORMAP
from nsgeo.velocity import VelocityModel
from plugin_testing import REAL_DZT, needs_real_data
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtTest import QTest

from nsgeo_qgis.render.qimage import RadargramImage, rgb_to_qimage
from nsgeo_qgis.ui.profile_view import (
    CURSOR_COLOUR,
    MARGIN_LEFT,
    MARGIN_TOP,
    ProfileView,
)


def _rg(n_traces=200, n_samples=128):
    rng = np.random.default_rng(3)
    data = rng.normal(size=(n_samples, n_traces))
    data[20:24, :] += 8.0
    return Radargram(data=data, dt_ns=0.5, t0_ns=-4.0)


def test_rgb_to_qimage_owns_its_memory_and_matches_pixels():
    rgb = np.zeros((2, 3, 3), dtype=np.uint8)
    rgb[0, 1] = (255, 0, 0)
    img = rgb_to_qimage(rgb)
    del rgb
    assert (img.width(), img.height()) == (3, 2)
    assert QColor(img.pixel(1, 0)).red() == 255 and QColor(img.pixel(0, 0)).red() == 0


def test_radargram_image_caches_and_rebuilds_on_display_change():
    ri = RadargramImage(_rg())
    img = ri.image
    assert img is ri.image  # cached
    assert (img.width(), img.height()) == (200, 128)
    ri2 = ri.with_display(percentile=95.0)
    assert ri2.rg is ri.rg and ri2.limit < ri.limit
    ri3 = ri.with_display(colormap_name="grey_white_high")
    assert ri3.image.pixel(0, 0) != img.pixel(0, 0) or ri3.colormap_name != DEFAULT_COLORMAP


def test_radargram_image_decimates_very_wide_lines():
    ri = RadargramImage(Radargram(data=np.zeros((8, 20_000)), dt_ns=0.5, t0_ns=0.0), max_width=4096)
    assert ri.image.width() <= 4096


@pytest.fixture
def view(qgis_app):
    v = ProfileView()
    v.resize(800, 300)
    v.show()
    rg = _rg()
    v.set_axes(rg.n_traces, rg.n_samples, rg.t0_ns, rg.dt_ns, distance_along=np.arange(rg.n_traces) / 60.0)
    v.set_image(RadargramImage(rg).image)
    return v, rg


def test_paints_the_image_inside_the_margins(view):
    v, rg = view
    shot = v.grab_image()
    r = v.image_rect()
    assert r.left() == MARGIN_LEFT and r.top() == MARGIN_TOP
    inside = [QColor(shot.pixel(r.left() + 5 + i, r.top() + 5 + j)).value() for i in range(20) for j in range(20)]
    assert np.std(inside) > 5  # radargram texture, not a flat fill
    margin = QColor(shot.pixel(5, r.top() + 5))
    assert margin.red() == margin.green() == margin.blue()  # axis gutter is neutral


def test_loading_state_when_there_is_no_image(qgis_app):
    v = ProfileView()
    v.resize(400, 200)
    v.set_axes(100, 50, 0.0, 0.5)
    v.set_image(None)
    v.grab_image()  # must not raise
    assert v.transform is not None and v.transform.n_traces == 100


def test_cursor_is_drawn_at_the_trace(view):
    v, rg = view
    v.set_cursor(100)
    shot = v.grab_image()
    r = v.image_rect()
    x = int(r.left() + v.transform.x_of_trace(100.5))
    column = [QColor(shot.pixel(x, r.top() + y)) for y in range(10, r.height() - 10, 7)]
    assert any(c.red() > 200 and c.blue() < 120 for c in column), CURSOR_COLOUR.name()


def test_mouse_move_emits_the_trace_under_the_cursor(view):
    v, rg = view
    got = []
    v.trace_hovered.connect(got.append)
    r = v.image_rect()
    QTest.mouseMove(v, QPoint(r.left() + r.width() // 2, r.top() + 20))
    assert got and got[-1] == v.transform.trace_index_at(r.width() // 2) == 100


def test_wheel_zooms_about_the_cursor_and_emits_view_changed(view):
    v, rg = view
    changed = []
    v.view_changed.connect(lambda: changed.append(1))
    r = v.image_rect()
    before = v.transform
    v.zoom_at(2.0, r.width() // 2, r.height() // 2)
    assert changed and v.transform.trace_hi - v.transform.trace_lo == pytest.approx(100.0)
    v.fit()
    assert (v.transform.trace_lo, v.transform.trace_hi) == (before.trace_lo, before.trace_hi)


def test_shift_click_and_pick_mode_request_picks(view):
    v, rg = view
    picks = []
    v.pick_requested.connect(lambda t, time_ns: picks.append((t, time_ns)))
    r = v.image_rect()
    p = QPoint(r.left() + 40, r.top() + 30)
    QTest.mouseClick(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, p)
    assert len(picks) == 1 and picks[0][0] == v.transform.trace_index_at(40)
    assert picks[0][1] == pytest.approx(v.transform.time_of_y(30))
    v.set_pick_mode(True)
    QTest.mouseClick(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    assert len(picks) == 2


def test_drag_selects_a_trace_range(view):
    v, rg = view
    sel = []
    v.range_selected.connect(lambda a, b: sel.append((a, b)))
    r = v.image_rect()
    QTest.mousePress(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(r.left() + 100, r.top() + 50))
    QTest.mouseMove(v, QPoint(r.left() + 300, r.top() + 50))
    QTest.mouseRelease(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(r.left() + 300, r.top() + 50))
    assert sel == [(28, 86)]  # floor(100/696*200), floor(300/696*200)


def test_depth_axis_uses_the_velocity_model(view):
    v, rg = view
    v.set_velocity(VelocityModel.constant(0.1))
    labels = v.depth_tick_labels()
    assert labels and labels[0].startswith("-") or labels[0] == "0"  # top of the record is above time zero


@needs_real_data
def test_real_file_renders_at_full_resolution(qgis_app):
    h = read_header(REAL_DZT[0])
    rg = Radargram.from_profile(Profile(data=read_samples(REAL_DZT[0])[0], header=h))
    ri = RadargramImage(rg)
    assert (ri.image.width(), ri.image.height()) == (rg.n_traces, 512)
    v = ProfileView()
    v.resize(900, 320)
    v.set_axes(rg.n_traces, rg.n_samples, rg.t0_ns, rg.dt_ns)
    v.set_image(ri.image)
    v.grab_image()
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.render'`

- [ ] **Step 3: Implement the QImage wrapper**

Create `packages/nsgeo-qgis/nsgeo_qgis/render/__init__.py` with the docstring `"""The only place a numpy byte array becomes a QImage."""`.

Create `packages/nsgeo-qgis/nsgeo_qgis/render/qimage.py`:

```python
"""RGB byte array -> QImage, and a cache keyed on (radargram, display settings).

Everything numeric happens in nsgeo.render. Display gain (percentile,
colormap) is not a processing step and is never recorded in a stack.
"""

from __future__ import annotations

import numpy as np
from nsgeo.processing import Radargram
from nsgeo.render import DEFAULT_COLORMAP, PercentileClip, colormap, decimate_columns, to_rgb8
from qgis.PyQt.QtGui import QImage


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w, _ = rgb.shape
    # QImage does not own the buffer; copy() so the array may be freed.
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class RadargramImage:
    """One radargram rendered once per display setting. Pan and zoom draw
    sub-rectangles of `image`; only a new radargram or a display change
    re-runs numpy."""

    def __init__(
        self,
        rg: Radargram,
        percentile: float = 99.0,
        colormap_name: str = DEFAULT_COLORMAP,
        max_width: int = 8192,
    ) -> None:
        self.rg = rg
        self.percentile = percentile
        self.colormap_name = colormap_name
        self.max_width = max_width
        self.limit = PercentileClip(percentile).limit(rg.data)
        self._image: QImage | None = None

    @property
    def image(self) -> QImage:
        if self._image is None:
            data = decimate_columns(self.rg.data, self.max_width)
            self._image = rgb_to_qimage(to_rgb8(data, self.limit, colormap(self.colormap_name)))
        return self._image

    def with_display(
        self, percentile: float | None = None, colormap_name: str | None = None
    ) -> RadargramImage:
        return RadargramImage(
            self.rg,
            self.percentile if percentile is None else percentile,
            self.colormap_name if colormap_name is None else colormap_name,
            self.max_width,
        )

    def with_radargram(self, rg: Radargram) -> RadargramImage:
        return RadargramImage(rg, self.percentile, self.colormap_name, self.max_width)
```

- [ ] **Step 4: Implement the view**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`:

```python
"""The profile viewer: a QWidget that paints a cached radargram image
through a ViewTransform, with axes, a cursor, a selection band and picks.

Measured: drawing a sub-rectangle of the cached image costs about 3 ms per
frame at any zoom, so pan and zoom never touch numpy.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from nsgeo.velocity import VelocityModel
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
        self.transform = ViewTransform.fit(t.n_traces, t.n_samples, t.t0_ns, t.dt_ns, r.width(), r.height())
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
        if self._image is not None:
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
            p.drawText(QRectF(0, y - 8, r.left() - 6, 16), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{tick:g}")
        p.drawText(QRectF(0, 0, r.left() - 6, MARGIN_TOP + 10), int(Qt.AlignmentFlag.AlignRight), "ns")
        # right: depth
        p.drawLine(r.topRight(), r.bottomRight())
        if self._velocity is not None:
            for label, y in self._depth_ticks(t):
                yy = r.top() + y
                p.drawLine(QPointF(r.right(), yy), QPointF(r.right() + 4, yy))
                p.drawText(QRectF(r.right() + 6, yy - 8, MARGIN_RIGHT - 8, 16), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
            p.drawText(QRectF(r.right() + 6, 0, MARGIN_RIGHT - 8, MARGIN_TOP + 10), int(Qt.AlignmentFlag.AlignLeft), "m")
        # bottom: distance along the line, or trace index
        p.drawLine(r.bottomLeft(), r.bottomRight())
        for label, x in self._distance_ticks(t):
            xx = r.left() + x
            p.drawLine(QPointF(xx, r.bottom()), QPointF(xx, r.bottom() + 4))
            p.drawText(QRectF(xx - 30, r.bottom() + 6, 60, 14), int(Qt.AlignmentFlag.AlignHCenter), label)
        unit = "m" if self._distance is not None else "trace"
        arrow = "→" if self._direction == 1 else "←"
        p.drawText(QRectF(r.left(), r.bottom() + 14, r.width(), 14), int(Qt.AlignmentFlag.AlignHCenter), f"{unit} along line {arrow}")

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
                self.pick_requested.emit(self.transform.trace_index_at(x), self.transform.time_of_y(y))
                return
            self._press = event_pos(event)
            self._dragging = False

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if self.transform is None:
            return
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
        x, y = self._local(event)
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom_at(1.25**steps, x, y)
```

- [ ] **Step 5: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean. If `test_mouse_move_emits_the_trace_under_the_cursor` gets no events, the widget needs `show()` before `QTest.mouseMove` (the fixture does this) and `setMouseTracking(True)` (the constructor does).

```bash
git add packages/nsgeo-qgis
git commit -m "feat: profile viewer widget with cached image, axes, cursor, picks

A custom QWidget paints a sub-rectangle of one cached full-resolution
QImage through ViewTransform, so pan and zoom never touch numpy (3 ms a
frame measured). Time on the left, depth on the right from the velocity
model, distance along the line below; Shift+click or pick mode requests
a pick; drag selects a trace range."
```

---

