### Task 18: Gain-curve strip beside the profile

A vertical panel sharing the viewer's time mapping, visible while a curve-kind step is selected. Drag points, watch the image update; the change goes through `replace_step`. Control points are in absolute two-way time, the same axis the viewer draws.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py`

**Interfaces:**
- Consumes: `ViewTransform`, `MARGIN_TOP`, `event_pos`
- Produces: `GainStrip(parent=None)` with `set_time_mapping(transform, top_px)`, `set_points(points)`, `points() -> list[list[float]]`, `x_of_db`, `db_of_x`, `y_of_time`, `time_of_y`, `handle_at(pos) -> int | None`, signal `points_changed(list)`; `ProfileDock` gains `gain_strip: GainStrip`, `show_gain_strip(points | None)`, signal `gain_points_changed(list)`; `NsgeoPlugin` gains `_sync_gain_strip(row)`, `_curve_param_name(step) -> str | None`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtTest import QTest

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.gain_strip import GainStrip
from nsgeo_qgis.ui.profile_dock import ProfileDock
from nsgeo_qgis.ui.profile_view import MARGIN_TOP
from nsgeo_qgis.ui.view_transform import ViewTransform

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def strip(qgis_app):
    s = GainStrip()
    s.resize(96, 300 + MARGIN_TOP + 28)
    s.show()
    t = ViewTransform.fit(100, 200, 0.0, 0.5, 600, 300)
    s.set_time_mapping(t, MARGIN_TOP)
    s.set_points([[0.0, 0.0], [100.0, 20.0]])
    return s


def test_mappings_round_trip(strip):
    assert strip.time_of_y(strip.y_of_time(37.0)) == pytest.approx(37.0)
    assert strip.db_of_x(strip.x_of_db(12.0)) == pytest.approx(12.0)
    assert strip.y_of_time(0.0) == MARGIN_TOP


def test_dragging_a_handle_moves_its_point_and_emits(strip):
    got = []
    strip.points_changed.connect(got.append)
    x0, y0 = strip.x_of_db(20.0), strip.y_of_time(100.0)
    assert strip.handle_at(QPoint(int(x0), int(y0))) == 1
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(x0), int(y0)))
    QTest.mouseMove(strip, QPoint(int(strip.x_of_db(30.0)), int(y0)))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(strip.x_of_db(30.0)), int(y0)))
    assert got and got[-1][1][1] == pytest.approx(30.0, abs=0.5)
    assert strip.points()[1][0] == pytest.approx(100.0, abs=0.5)


def test_double_click_adds_and_right_click_removes(strip):
    got = []
    strip.points_changed.connect(got.append)
    mid = QPoint(int(strip.x_of_db(10.0)), int(strip.y_of_time(50.0)))
    QTest.mouseDClick(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, mid)
    assert len(strip.points()) == 3 and got[-1][1][0] == pytest.approx(50.0, abs=0.5)
    QTest.mouseClick(strip, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, mid)
    assert len(strip.points()) == 2
    QTest.mouseClick(strip, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, QPoint(int(strip.x_of_db(0.0)), int(strip.y_of_time(0.0))))
    assert len(strip.points()) == 2  # never below two


def test_profile_dock_shows_the_strip_only_when_asked(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    assert dock.gain_strip.isHidden()
    dock.show_gain_strip([[-11.0, 0.0], [99.0, 0.0]])
    assert not dock.gain_strip.isHidden()
    assert dock.gain_strip.y_of_time(-11.0) == pytest.approx(MARGIN_TOP + dock.view.transform.y_of_time(-11.0))
    changed = []
    dock.gain_points_changed.connect(changed.append)
    dock.gain_strip.set_points([[-11.0, 0.0], [99.0, 12.0]])
    dock.gain_strip.points_changed.emit(dock.gain_strip.points())
    assert changed and changed[0][1][1] == 12.0
    dock.show_gain_strip(None)
    assert dock.gain_strip.isHidden()


def test_plugin_routes_strip_edits_through_replace_step(fake_iface, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    plugin.processing_dock.add_step("dewow")
    plugin.processing_dock.add_step_with_dialog("gain_curve")
    plugin.processing_dock.list.setCurrentRow(1)
    assert not plugin.profile_dock.gain_strip.isHidden()
    plugin.profile_dock.gain_strip.set_points([[-11.0, 0.0], [50.0, 6.0], [99.0, 0.0]])
    plugin.profile_dock.gain_strip.points_changed.emit(plugin.profile_dock.gain_strip.points())
    assert s.stack_for(key).entries[1][0].params["points"][1] == [50.0, 6.0]
    plugin.processing_dock.list.setCurrentRow(0)
    assert plugin.profile_dock.gain_strip.isHidden()
    plugin.unload()
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.gain_strip'`

- [ ] **Step 3: Implement the strip**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py`:

```python
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
        p.fillRect(self.rect(), QColor(250, 250, 250))
        if self._transform is None or not self._points:
            p.end()
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
```

- [ ] **Step 4: Add the strip to the profile dock**

In `profile_dock.py`: import `GainStrip` and `MARGIN_TOP`; add `gain_points_changed = pyqtSignal(list)` to the signals; replace `layout.addWidget(self.view, 1)` with

```python
        viewer_row = QHBoxLayout()
        viewer_row.setSpacing(0)
        self.view = ProfileView(body)
        viewer_row.addWidget(self.view, 1)
        self.gain_strip = GainStrip(body)
        self.gain_strip.hide()
        viewer_row.addWidget(self.gain_strip)
        layout.addLayout(viewer_row, 1)
```

(and delete the earlier `self.view = ProfileView(body)` line), then connect in `__init__`:

```python
        self.view.view_changed.connect(self._sync_strip_mapping)
        self.gain_strip.points_changed.connect(self.gain_points_changed.emit)
```

and add:

```python
    def _sync_strip_mapping(self) -> None:
        if self.view.transform is not None:
            self.gain_strip.set_time_mapping(self.view.transform, MARGIN_TOP)

    def show_gain_strip(self, points: list[list[float]] | None) -> None:
        if points is None or self.view.transform is None:
            self.gain_strip.hide()
            return
        self._sync_strip_mapping()
        self.gain_strip.set_points(points)
        self.gain_strip.show()
```

Also call `self._sync_strip_mapping()` at the end of `_render()` so the strip follows axis changes.

- [ ] **Step 5: Route it in the plugin**

In `plugin.py` `initGui`, after both docks exist:

```python
        self.processing_dock.step_selected.connect(self._sync_gain_strip)
        self.profile_dock.gain_points_changed.connect(self._on_gain_points)
```

and add:

```python
    @staticmethod
    def _curve_param_name(step: Any) -> str | None:
        """The name of a step's curve-kind parameter, if it has one. Decided
        by the schema's kind, never by the step's name."""
        for spec in type(step).schema():
            if spec.kind == "curve":
                return str(spec.name)
        return None

    def _sync_gain_strip(self, row: int) -> None:
        assert self.session is not None and self.profile_dock is not None
        key = self.session.current_key
        if key is None or row < 0:
            self.profile_dock.show_gain_strip(None)
            return
        entries = self.session.stack_for(key).entries
        if row >= len(entries):
            self.profile_dock.show_gain_strip(None)
            return
        step = entries[row][0]
        name = self._curve_param_name(step)
        self.profile_dock.show_gain_strip(step.params[name] if name else None)

    def _on_gain_points(self, points: list) -> None:
        assert self.session is not None and self.processing_dock is not None
        key = self.session.current_key
        row = self.processing_dock.current_row()
        if key is None or row < 0:
            return
        step = self.session.stack_for(key).entries[row][0]
        name = self._curve_param_name(step)
        if name is None:
            return
        params = dict(step.params)
        params[name] = points
        try:
            self.session.replace_step(key, row, build_step(step.name, **params))
        except ValueError as exc:
            self.message(str(exc), Qgis.MessageLevel.Warning)
```

with `from nsgeo.processing import build_step`.

- [ ] **Step 6: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: gain-curve strip beside the profile, sharing its time axis

Control points are in absolute two-way time, so the strip borrows the
viewer's ViewTransform and a point sits beside the sample it affects.
Drags go through replace_step on every move (one broadcast multiply
when gain is last). Which step has a curve is decided by schema kind,
never by name."
```

---

