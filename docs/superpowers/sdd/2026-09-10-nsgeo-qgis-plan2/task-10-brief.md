### Task 10: Grid dialog with three georeferencing tabs and the digitise map tool

GNSS corners, digitise on map, or an existing polygon: three UI paths into the same six fields (spec §5.6). Velocity is required and seeded from the header dielectric when the grid already has lines.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/maptools/__init__.py` (docstring only)
- Create: `packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`open_grid_dialog`)
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py`

**Interfaces:**
- Consumes: `fit_grid_from_corners`, `corners_from_polygon`, `VelocityModel`, `SiteSession`
- Produces: `GridDialog(session, grid=None, suggested_velocity=None, parent=None)` with `corner_table`, `fit_corners()`, `residual_label`, `layer_combo`, `feature_picker`, `origin_combo`, `plus_y_combo`, `use_polygon()`, `digitise_requested` signal, `set_digitised(origin_xy, along_xy)`, fields `id_edit`, `crs_widget`, `origin_x`, `origin_y`, `azimuth`, `size_x`, `size_y`, `spacing`, `velocity`, `ok_button`, `result_grid() -> Grid`; `DigitiseGridTool(canvas)` with signal `points_picked(QgsPointXY, QgsPointXY)` and `reset()`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.velocity import VelocityModel
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt

from nsgeo_qgis.maptools.digitise_tool import DigitiseGridTool
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.grid_dialog import GridDialog

TRUE = Grid("A", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)
LOCAL = np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 11.0], [0.0, 11.0]])


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    return s


def test_ok_is_blocked_until_id_and_velocity_are_set(session):
    d = GridDialog(session)
    assert not d.ok_button.isEnabled()
    d.id_edit.setText("A")
    assert not d.ok_button.isEnabled()  # velocity still 0 = required
    d.velocity.setValue(0.08)
    assert d.ok_button.isEnabled()


def test_corner_fit_fills_origin_azimuth_and_sizes(session):
    d = GridDialog(session, suggested_velocity=0.0801)
    world = TRUE.to_world(LOCAL)
    for row, (lo, wo) in enumerate(zip(LOCAL, world)):
        d.set_corner_row(row, lo[0], lo[1], wo[0], wo[1])
    d.fit_corners()
    assert d.origin_x.value() == pytest.approx(500.0, abs=1e-6)
    assert d.origin_y.value() == pytest.approx(700.0, abs=1e-6)
    assert d.azimuth.value() == pytest.approx(30.0, abs=1e-6)
    assert d.size_x.value() == pytest.approx(5.0) and d.size_y.value() == pytest.approx(11.0)
    assert "0.000" in d.residual_label.text()
    d.id_edit.setText("A")
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32616"))
    g = d.result_grid()
    assert g.id == "A" and g.crs == "EPSG:32616"
    assert g.velocity == VelocityModel.constant(0.0801)


def test_polygon_tab_reads_a_selected_feature(session):
    layer = QgsVectorLayer("Polygon?crs=EPSG:32616", "plan", "memory")
    ring = [QgsPointXY(*p) for p in TRUE.to_world(LOCAL)]
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromPolygonXY([ring]))
    layer.dataProvider().addFeatures([f])
    QgsProject.instance().addMapLayer(layer)
    try:
        d = GridDialog(session)
        d.layer_combo.setLayer(layer)
        d.feature_picker.setFeature(next(layer.getFeatures()).id())
        d.origin_combo.setCurrentIndex(0)
        d.plus_y_combo.setCurrentIndex(3)
        d.use_polygon()
        assert d.azimuth.value() == pytest.approx(30.0, abs=1e-6)
        assert d.size_y.value() == pytest.approx(11.0, abs=1e-6)
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_digitised_points_set_origin_and_azimuth(session):
    d = GridDialog(session)
    d.set_digitised((500.0, 700.0), (500.0 + 5.0 * np.sin(np.radians(30)), 700.0 + 5.0 * np.cos(np.radians(30))))
    assert (d.origin_x.value(), d.origin_y.value()) == (500.0, 700.0)
    assert d.azimuth.value() == pytest.approx(30.0, abs=1e-6)


def test_editing_an_existing_grid_prefills_and_keeps_its_id(session):
    session.add_grid(Grid("A", (1.0, 2.0), 45.0, 3.0, 4.0, "EPSG:32616", 0.25, velocity=VelocityModel.constant(0.1)))
    d = GridDialog(session, grid=session.grid("A"))
    assert d.id_edit.text() == "A" and not d.id_edit.isEnabled()
    assert d.velocity.value() == pytest.approx(0.1)
    d.azimuth.setValue(46.0)
    assert d.result_grid().azimuth == 46.0 and d.result_grid().default_spacing == 0.25


def test_digitise_tool_emits_after_two_clicks(qgis_app, fake_iface):
    tool = DigitiseGridTool(fake_iface.mapCanvas())
    got = []
    tool.points_picked.connect(lambda a, b: got.append((a, b)))
    tool.canvasClicked.emit(QgsPointXY(1.0, 2.0), Qt.MouseButton.LeftButton)
    assert got == []
    tool.canvasClicked.emit(QgsPointXY(1.0, 5.0), Qt.MouseButton.LeftButton)
    assert len(got) == 1 and got[0][1].y() == 5.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.maptools'`

- [ ] **Step 3: Implement the map tool**

Create `packages/nsgeo-qgis/nsgeo_qgis/maptools/__init__.py` with a one-line docstring: `"""Canvas tools. Each is a QgsMapTool that talks to the session or a dialog."""`

Create `packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py`:

```python
"""Two clicks define a grid frame: the origin, then a point along +Y."""

from __future__ import annotations

from qgis.core import QgsPointXY
from qgis.gui import QgsMapCanvas, QgsMapToolEmitPoint, QgsRubberBand
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor


class DigitiseGridTool(QgsMapToolEmitPoint):
    points_picked = pyqtSignal(QgsPointXY, QgsPointXY)

    def __init__(self, canvas: QgsMapCanvas) -> None:
        super().__init__(canvas)
        self._origin: QgsPointXY | None = None
        self._band = QgsRubberBand(canvas)
        self._band.setColor(QColor(48, 140, 198))
        self._band.setWidth(2)
        self.canvasClicked.connect(self._on_click)

    def _on_click(self, point: QgsPointXY, _button: int) -> None:
        if self._origin is None:
            self._origin = QgsPointXY(point)
            self._band.reset()
            self._band.addPoint(self._origin)
            return
        origin, self._origin = self._origin, None
        self._band.reset()
        self.points_picked.emit(origin, QgsPointXY(point))

    def reset(self) -> None:
        self._origin = None
        self._band.reset()

    def deactivate(self) -> None:
        self.reset()
        super().deactivate()
```

- [ ] **Step 4: Implement the dialog**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`:

```python
"""Grid dialog: three ways in, one set of numbers.

GNSS corners (rigid least-squares fit with a residual shown as QC),
digitising two points on the map, or reading a selected polygon feature.
All three fill the same fields; the user can still edit any of them.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from nsgeo.geometry.fit import fit_grid_from_corners
from nsgeo.geometry.grid import Grid
from nsgeo.velocity import VelocityModel
from qgis.core import QgsCoordinateReferenceSystem, QgsMapLayerProxyModel, QgsProject
from qgis.gui import QgsFeaturePickerWidget, QgsMapLayerComboBox, QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.lookup import corners_from_polygon
from nsgeo_qgis.session import SiteSession

CORNER_NAMES = ("origin", "+X", "+X+Y", "+Y")


def _spin(lo: float, hi: float, decimals: int, step: float, value: float = 0.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    return s


class GridDialog(QDialog):
    digitise_requested = pyqtSignal()

    def __init__(
        self,
        session: SiteSession,
        grid: Grid | None = None,
        suggested_velocity: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.existing = grid
        self.setWindowTitle(f"Grid · {grid.id}" if grid else "New grid")
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_corner_tab(), "GNSS corners")
        self.tabs.addTab(self._build_digitise_tab(), "Digitise on map")
        self.tabs.addTab(self._build_polygon_tab(), "From polygon")
        layout.addWidget(self.tabs)

        form = QFormLayout()
        self.id_edit = QLineEdit()
        self.crs_widget = QgsProjectionSelectionWidget()
        self.origin_x = _spin(-1e8, 1e8, 3, 0.1)
        self.origin_y = _spin(-1e8, 1e8, 3, 0.1)
        self.azimuth = _spin(0.0, 360.0, 3, 0.5)
        self.azimuth.setWrapping(True)
        self.size_x = _spin(0.0, 1e5, 2, 0.5, 10.0)
        self.size_y = _spin(0.0, 1e5, 2, 0.5, 10.0)
        self.spacing = _spin(0.01, 100.0, 3, 0.05, 0.5)
        self.velocity = _spin(0.0, 0.3, 4, 0.001)
        self.velocity.setSpecialValueText("required")
        self.velocity_hint = QLabel("")
        origin_row = QHBoxLayout()
        origin_row.addWidget(self.origin_x)
        origin_row.addWidget(self.origin_y)
        size_row = QHBoxLayout()
        size_row.addWidget(self.size_x)
        size_row.addWidget(self.size_y)
        vel_row = QHBoxLayout()
        vel_row.addWidget(self.velocity)
        vel_row.addWidget(self.velocity_hint)
        form.addRow("Id", self.id_edit)
        form.addRow("CRS", self.crs_widget)
        form.addRow("Origin E, N", origin_row)
        form.addRow("Azimuth (° cw from N to +Y)", self.azimuth)
        form.addRow("Size X, Y (m)", size_row)
        form.addRow("Default spacing (m)", self.spacing)
        form.addRow("Velocity (m/ns)", vel_row)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.id_edit.textChanged.connect(self._validate)
        self.velocity.valueChanged.connect(self._validate)
        self.size_x.valueChanged.connect(self._validate)
        self.size_y.valueChanged.connect(self._validate)

        project_crs = QgsProject.instance().crs()
        if project_crs.isValid():
            self.crs_widget.setCrs(project_crs)
        if grid is not None:
            self._prefill(grid)
        elif suggested_velocity is not None:
            self.velocity.setValue(suggested_velocity)
            self.velocity_hint.setText("from the header dielectric")
        self._validate()

    # ---- tabs -------------------------------------------------------------
    def _build_corner_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.corner_table = QTableWidget(4, 5)
        self.corner_table.setHorizontalHeaderLabels(["corner", "local x", "local y", "world E", "world N"])
        for row, name in enumerate(CORNER_NAMES):
            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.corner_table.setItem(row, 0, item)
            for col in range(1, 5):
                self.corner_table.setItem(row, col, QTableWidgetItem(""))
        v.addWidget(self.corner_table)
        row = QHBoxLayout()
        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self.fit_corners)
        self.residual_label = QLabel("rigid fit: rotation + translation, no scale")
        row.addWidget(self.fit_button)
        row.addWidget(self.residual_label)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _build_digitise_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Click the grid origin on the map, then a point along the +Y edge. Then enter the sizes."))
        self.digitise_button = QPushButton("Pick on map")
        self.digitise_button.clicked.connect(self.digitise_requested.emit)
        v.addWidget(self.digitise_button)
        v.addStretch(1)
        return w

    def _build_polygon_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)
        self.feature_picker = QgsFeaturePickerWidget()
        self.layer_combo.layerChanged.connect(self.feature_picker.setLayer)
        self.feature_picker.setLayer(self.layer_combo.currentLayer())
        self.origin_combo = QComboBox()
        self.plus_y_combo = QComboBox()
        for i in range(4):
            self.origin_combo.addItem(f"vertex {i}")
            self.plus_y_combo.addItem(f"vertex {i}")
        self.plus_y_combo.setCurrentIndex(3)
        self.use_polygon_button = QPushButton("Use polygon")
        self.use_polygon_button.clicked.connect(self.use_polygon)
        form.addRow("Layer", self.layer_combo)
        form.addRow("Feature", self.feature_picker)
        form.addRow("Origin corner", self.origin_combo)
        form.addRow("+Y corner", self.plus_y_combo)
        form.addRow(self.use_polygon_button)
        self.polygon_status = QLabel("")
        form.addRow(self.polygon_status)
        return w

    # ---- the three paths --------------------------------------------------
    def set_corner_row(self, row: int, lx: float, ly: float, wx: float, wy: float) -> None:
        for col, val in zip((1, 2, 3, 4), (lx, ly, wx, wy)):
            self.corner_table.item(row, col).setText(f"{val:.6f}")

    def _corner_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        local, world = [], []
        for row in range(self.corner_table.rowCount()):
            vals = [self.corner_table.item(row, c).text().strip() for c in range(1, 5)]
            if not all(vals):
                continue
            nums = [float(v) for v in vals]
            local.append(nums[:2])
            world.append(nums[2:])
        return np.array(local, dtype=float), np.array(world, dtype=float)

    def fit_corners(self) -> None:
        local, world = self._corner_arrays()
        try:
            fit = fit_grid_from_corners(local, world)
        except ValueError as exc:
            self.residual_label.setText(str(exc))
            return
        self.origin_x.setValue(fit.origin[0])
        self.origin_y.setValue(fit.origin[1])
        self.azimuth.setValue(fit.azimuth)
        self.size_x.setValue(float(local[:, 0].max()))
        self.size_y.setValue(float(local[:, 1].max()))
        self.residual_label.setText(f"rigid fit RMS {fit.residual_rms:.3f} m (nonzero = grid not square)")

    def set_digitised(self, origin_xy: tuple[float, float], along_xy: tuple[float, float]) -> None:
        dx = along_xy[0] - origin_xy[0]
        dy = along_xy[1] - origin_xy[1]
        self.origin_x.setValue(origin_xy[0])
        self.origin_y.setValue(origin_xy[1])
        self.azimuth.setValue(math.degrees(math.atan2(dx, dy)) % 360.0)
        self.tabs.setCurrentIndex(1)

    def use_polygon(self) -> None:
        feature = self.feature_picker.feature()
        layer = self.layer_combo.currentLayer()
        if layer is None or not feature.isValid() or feature.geometry().isNull():
            self.polygon_status.setText("select a polygon feature first")
            return
        geom = feature.geometry()
        polygon = geom.asPolygon() if not geom.isMultipart() else geom.asMultiPolygon()[0]
        ring = [(p.x(), p.y()) for p in polygon[0]]
        try:
            corners = corners_from_polygon(ring, self.origin_combo.currentIndex(), self.plus_y_combo.currentIndex())
            fit = fit_grid_from_corners(corners.local, corners.world)
        except ValueError as exc:
            self.polygon_status.setText(str(exc))
            return
        self.origin_x.setValue(fit.origin[0])
        self.origin_y.setValue(fit.origin[1])
        self.azimuth.setValue(fit.azimuth)
        self.size_x.setValue(corners.size_x)
        self.size_y.setValue(corners.size_y)
        self.crs_widget.setCrs(layer.crs())
        self.polygon_status.setText(f"rigid fit RMS {fit.residual_rms:.3f} m")

    # ---- result -----------------------------------------------------------
    def _prefill(self, grid: Grid) -> None:
        self.id_edit.setText(grid.id)
        self.id_edit.setEnabled(False)  # lines reference the id; renaming is a different feature
        self.crs_widget.setCrs(QgsCoordinateReferenceSystem(grid.crs))
        self.origin_x.setValue(grid.origin[0])
        self.origin_y.setValue(grid.origin[1])
        self.azimuth.setValue(grid.azimuth)
        self.size_x.setValue(grid.size_x)
        self.size_y.setValue(grid.size_y)
        self.spacing.setValue(grid.default_spacing)
        if grid.velocity is not None:
            self.velocity.setValue(grid.velocity.surface_velocity)

    def _validate(self, *_: Any) -> None:
        ok = bool(self.id_edit.text().strip()) and self.velocity.value() > 0 and self.size_x.value() > 0 and self.size_y.value() > 0
        self.ok_button.setEnabled(ok)

    def result_grid(self) -> Grid:
        return Grid(
            id=self.id_edit.text().strip(),
            origin=(self.origin_x.value(), self.origin_y.value()),
            azimuth=self.azimuth.value(),
            size_x=self.size_x.value(),
            size_y=self.size_y.value(),
            crs=self.crs_widget.crs().authid(),
            default_spacing=self.spacing.value(),
            velocity=VelocityModel.constant(self.velocity.value()),
        )
```

Import `Qt` alongside `pyqtSignal`: `from qgis.PyQt.QtCore import Qt, pyqtSignal`. If `QgsMapLayerProxyModel.Filter.PolygonLayer` is reported missing on your QGIS build, use `Qgis.LayerFilter.PolygonLayer` from `qgis.core` instead; both exist on 3.40+.

- [ ] **Step 5: Wire it into the plugin**

In `plugin.py`, replace the `open_grid_dialog` stub:

```python
    def open_grid_dialog(self, grid_id: str | None) -> None:
        assert self.session is not None
        if not self.session.is_open:
            return
        grid = self.session.grid(grid_id) if grid_id else None
        suggestion = None
        if grid is None:
            lines = self.session.site.lines if self.session.site else []
            if lines:
                suggestion = VelocityModel.from_dielectric(lines[0].header.epsr).surface_velocity
        dialog = GridDialog(self.session, grid=grid, suggested_velocity=suggestion, parent=self.iface.mainWindow())
        dialog.digitise_requested.connect(lambda: self._start_digitise(dialog))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = dialog.result_grid()
        try:
            if grid is None:
                self.session.add_grid(result)
            else:
                self.session.replace_grid(result)
        except (ValueError, KeyError) as exc:
            self.message(str(exc), Qgis.MessageLevel.Critical)

    def _start_digitise(self, dialog: GridDialog) -> None:
        canvas = self.iface.mapCanvas()
        tool = DigitiseGridTool(canvas)

        def done(origin: Any, along: Any) -> None:
            dialog.set_digitised((origin.x(), origin.y()), (along.x(), along.y()))
            dialog.crs_widget.setCrs(canvas.mapSettings().destinationCrs())
            canvas.unsetMapTool(tool)
            dialog.show()
            dialog.raise_()

        tool.points_picked.connect(done)
        dialog.hide()
        canvas.setMapTool(tool)
```

Add the imports `from qgis.PyQt.QtWidgets import QDialog`, `from nsgeo.velocity import VelocityModel`, `from nsgeo_qgis.ui.grid_dialog import GridDialog`, `from nsgeo_qgis.maptools.digitise_tool import DigitiseGridTool`.

- [ ] **Step 6: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: grid dialog with corner fit, map digitising, and polygon import

Three UI paths into the same six fields. The corner fit is the core's
rigid least-squares and its residual is shown as a QC number; the
polygon path goes through the pure corners_from_polygon; digitising is
two clicks on a QgsMapToolEmitPoint. Velocity is required and seeded
from the header dielectric when the site already has lines."
```

---

