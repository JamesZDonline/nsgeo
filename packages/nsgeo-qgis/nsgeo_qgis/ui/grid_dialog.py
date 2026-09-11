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
from qgis.PyQt.QtCore import Qt, pyqtSignal
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

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.id_edit.textChanged.connect(self._validate)
        self.velocity.valueChanged.connect(self._validate)
        self.size_x.valueChanged.connect(self._validate)
        self.size_y.valueChanged.connect(self._validate)
        self.crs_widget.crsChanged.connect(self._validate)

        project_crs = QgsProject.instance().crs()
        # A brand-new QGIS project defaults to EPSG:4326, so this fallback
        # is a placeholder for the bare-application case only (this
        # project's own test harness among them) -- same spirit as
        # size_x/size_y defaulting to 10.0: a valid, non-blocking value
        # the user is expected to override, not a real answer.
        self.crs_widget.setCrs(
            project_crs if project_crs.isValid() else QgsCoordinateReferenceSystem("EPSG:4326")
        )
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
        self.corner_table.setHorizontalHeaderLabels(
            ["corner", "local x", "local y", "world E", "world N"]
        )
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
        v.addWidget(
            QLabel(
                "Click the grid origin on the map, then a point along the +Y edge. "
                "Then enter the sizes."
            )
        )
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
        # _corner_arrays() belongs inside the guard too: a hand-typed cell
        # that is not a number (a stray letter, a stray space) makes its
        # float(v) raise ValueError just as surely as a bad fit does, and
        # this method is a QPushButton.clicked slot -- an uncaught
        # exception here would be swallowed by Qt (see the module
        # docstrings in plugin.py / survey_dock.py) rather than shown.
        try:
            local, world = self._corner_arrays()
            fit = fit_grid_from_corners(local, world)
        except ValueError as exc:
            self.residual_label.setText(str(exc))
            return
        self.origin_x.setValue(fit.origin[0])
        self.origin_y.setValue(fit.origin[1])
        self.azimuth.setValue(fit.azimuth)
        # The extent of the local coordinates, not their max(): control
        # points need not be anchored at the local origin (e.g. the
        # origin stake is unreachable, so the crew surveys (100, 50) to
        # (120, 57.5) instead of (0, 0) to (20, 7.5)). max() alone reads
        # that as a 120 x 57.5 m grid -- a correct origin, a correct
        # azimuth, and a 0.000 m residual on a wildly wrong size.
        self.size_x.setValue(float(local[:, 0].max() - local[:, 0].min()))
        self.size_y.setValue(float(local[:, 1].max() - local[:, 1].min()))
        # A nonzero RMS here has two very different causes, and this label
        # cannot tell them apart: it may mean the physical corners just
        # weren't surveyed perfectly square (the ordinary case), or it may
        # mean the local/world correspondence itself is mirrored -- e.g.
        # the +X and +Y world fixes were logged in swapped rows. Both look
        # like "some residual"; fit_grid_from_corners forbids reflection,
        # so a mirrored input still returns a plausible origin and azimuth
        # rather than an obvious error. Saying only "not square" would send
        # a user with a swapped-row blunder back out to re-measure a grid
        # that was never wrong.
        self.residual_label.setText(
            f"rigid fit RMS {fit.residual_rms:.3f} m -- 0 for exact corners; a nonzero "
            "residual can mean the corners weren't surveyed perfectly square, or that "
            "the local/world correspondence is mirrored (check which corner is +X and "
            "which is +Y)"
        )

    def set_digitised(self, origin_xy: tuple[float, float], along_xy: tuple[float, float]) -> None:
        dx = along_xy[0] - origin_xy[0]
        dy = along_xy[1] - origin_xy[1]
        if math.hypot(dx, dy) == 0.0:
            # atan2(0, 0) silently returns 0.0 -- a real-looking azimuth
            # for a grid that was never actually defined. A double-click
            # registering as two canvasClicked events at the same pixel is
            # exactly the kind of "looked fine" bug this task warns about,
            # so this must fail loudly rather than seed a plausible-but-
            # meaningless frame.
            raise ValueError("the two digitised points coincide; click two distinct points")
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
        if layer.crs().isGeographic():
            # corners_from_polygon/fit_grid_from_corners treat the ring's
            # raw coordinates as metres. In a geographic CRS they are
            # degrees: size_x/size_y come out as ~1e-3 (rounds to 0.00 at
            # this dialog's 2 decimals, which is the only thing that
            # currently stops OK from enabling), and a rigid fit of the
            # ring to itself in degree units still finds a near-zero
            # residual -- "rigid fit RMS 0.000 m" -- at an azimuth that is
            # wrong by several degrees (1 degree of longitude is not 1
            # degree of latitude in metres, away from the equator). A
            # convincing success message on a wrong frame is exactly the
            # failure mode this plan has already shipped twice, so this
            # is refused outright rather than merely warned about.
            self.polygon_status.setText(
                "this layer's CRS is geographic (degrees, not metres) -- reproject it "
                "to a projected CRS before reading corners from it"
            )
            return
        geom = feature.geometry()
        try:
            polygon = geom.asPolygon() if not geom.isMultipart() else geom.asMultiPolygon()[0]
            ring = [(p.x(), p.y()) for p in polygon[0]]
        except IndexError:
            # isNull() is False for a geometry with zero rings (an empty
            # polygon), so the guard above lets it through; asPolygon()
            # then returns [] and polygon[0] raises. Same clicked-signal
            # hazard as fit_corners() above: this must not disappear into
            # stderr while the user stares at unchanged fields.
            self.polygon_status.setText("this feature has no rings to read corners from")
            return
        try:
            corners = corners_from_polygon(
                ring, self.origin_combo.currentIndex(), self.plus_y_combo.currentIndex()
            )
            fit = fit_grid_from_corners(corners.local, corners.world)
        except ValueError as exc:
            # corners_from_polygon's own message already names the fix
            # ("pick the other corner adjacent to the origin for +Y"), so
            # showing it verbatim is the actionable message -- not a
            # traceback swallowed by the clicked-signal hazard (see the
            # module docstrings in plugin.py / survey_dock.py), and not a
            # silent no-op that leaves the user staring at unchanged
            # fields with no idea why.
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
        # crs.authid() gates OK too: the spec types Grid.crs as an
        # authority string, and a CRS that is valid but has no authid
        # (a custom PROJ string, e.g. an oblique Mercator) must be
        # refused rather than silently written as crs="" -- session's
        # add_grid/replace_grid don't validate this, and layers.py builds
        # the whole GeoPackage's CRS from it.
        ok = (
            bool(self.id_edit.text().strip())
            and self.velocity.value() > 0
            and self.size_x.value() > 0
            and self.size_y.value() > 0
            and bool(self.crs_widget.crs().authid())
        )
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
