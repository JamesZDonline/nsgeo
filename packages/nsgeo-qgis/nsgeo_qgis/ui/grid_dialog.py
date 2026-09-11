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
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsMapLayerProxyModel,
    QgsPointXY,
    QgsProject,
    QgsUnitTypes,
)
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

# Local scale-factor thresholds for _validate()'s CRS check (round 3,
# Finding 1): |k - 1| where k is ground distance / declared distance at
# the grid's own origin. Calibrated against real CRSs used as intended
# (UTM mid-zone/edge, British National Grid, a metres state plane: all
# comfortably under 0.1%; CONUS Albers/ETRS89 LAEA, both anisotropic
# equal-area projections: up to ~1.26% away from their centre) against
# CRSs that are not fit for a metric grid frame at all (EPSG:3857 well
# above both thresholds everywhere off the equator; a UTM zone abused
# three zones over, ~1.4-3%). Warn, but do not block, in between --
# refusing at 1% would false-refuse legitimate Albers/LAEA work.
CRS_SCALE_WARN = 0.001  # 0.1%
CRS_SCALE_REFUSE = 0.02  # ~2%


def _spin(lo: float, hi: float, decimals: int, step: float, value: float = 0.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    return s


# Round 4's fix for Finding 2 (crs_hint clipped to one line) split the
# dialog's single QFormLayout into form_top/form_bottom around crs_hint,
# a real QVBoxLayout sibling rather than a nested-form row. Two separate
# QFormLayouts each size their own label column independently, though,
# so without this the top two rows (round 5, Finding 4: measured
# id_edit.x() == crs_widget.x() == 48 against origin_x.x() ==
# azimuth.x() == 236) sat well left of, and wider than, every row below.
# Building every row's label from this one shared width keeps both
# layouts' label columns aligned regardless of which form a given row
# ends up in.
_FORM_LABELS = (
    "Id",
    "CRS",
    "Origin E, N",
    "Azimuth (° cw from N to +Y)",
    "Size X, Y (m)",
    "Default spacing (m)",
    "Velocity (m/ns)",
)


def _label(text: str, width: int) -> QLabel:
    label = QLabel(text)
    label.setMinimumWidth(width)
    return label


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

        # Round 4, Finding 2: crs_hint needs to be a real sibling in the
        # *outer* QVBoxLayout, not a row inside a QFormLayout nested in
        # it via addLayout() -- QFormLayout rows added that way do not
        # participate in Qt's height-for-width layout pass (verified
        # directly: the identical QLabel, added straight to a QVBoxLayout
        # instead, sizes correctly; nested inside the form it was locked
        # to a single-line row height regardless of heightForWidth()).
        # The form is split in two around it so it still reads Id, CRS,
        # [hint], Origin, ... top to bottom.
        form_top = QFormLayout()
        form_bottom = QFormLayout()
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
        self.crs_hint = QLabel("")
        self.crs_hint.setWordWrap(True)
        origin_row = QHBoxLayout()
        origin_row.addWidget(self.origin_x)
        origin_row.addWidget(self.origin_y)
        size_row = QHBoxLayout()
        size_row.addWidget(self.size_x)
        size_row.addWidget(self.size_y)
        vel_row = QHBoxLayout()
        vel_row.addWidget(self.velocity)
        vel_row.addWidget(self.velocity_hint)
        label_width = max(QLabel(text).sizeHint().width() for text in _FORM_LABELS)
        form_top.addRow(_label("Id", label_width), self.id_edit)
        form_top.addRow(_label("CRS", label_width), self.crs_widget)
        form_bottom.addRow(_label("Origin E, N", label_width), origin_row)
        form_bottom.addRow(_label("Azimuth (° cw from N to +Y)", label_width), self.azimuth)
        form_bottom.addRow(_label("Size X, Y (m)", label_width), size_row)
        form_bottom.addRow(_label("Default spacing (m)", label_width), self.spacing)
        form_bottom.addRow(_label("Velocity (m/ns)", label_width), vel_row)
        layout.addLayout(form_top)
        # Round 3, Finding 2: crs_hint sharing a row with crs_widget (in
        # a QHBoxLayout, the way velocity_hint shares with velocity)
        # squeezed crs_widget down to an unreadable few px whenever the
        # hint had anything to say -- exactly the moment F3 added it to
        # be seen. velocity_hint's text is always short ("from the
        # header dielectric"); crs_hint's can run to a full sentence, so
        # it was moved to its own row -- which round 4's Finding 2 then
        # found was silently clipped to one line's height regardless
        # (see the comment above form_top/form_bottom): added directly
        # to this outer layout instead, it sizes to its real content.
        layout.addWidget(self.crs_hint)
        layout.addLayout(form_bottom)

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
        # The local-scale-factor check below depends on where the grid
        # actually is, so a change to the origin can flip its own
        # verdict (round 3, Finding 1) -- unlike id/velocity/size, this
        # was not wired at all before this round.
        self.origin_x.valueChanged.connect(self._validate)
        self.origin_y.valueChanged.connect(self._validate)

        project_crs = QgsProject.instance().crs()
        # Round 1 and 2 fell back to a placeholder CRS (first EPSG:4326,
        # then EPSG:3857) when the project had none, reasoning it was
        # harmless because a real QGIS project's own CRS is (almost)
        # never invalid. Round 3: EPSG:3857 itself turned out to be
        # exactly the failure this dialog exists to prevent (a CRS that
        # merely *passes* the guard, chosen only because it does) -- the
        # next placeholder would only repeat that pattern with a
        # different CRS. No fallback: an unset CRS is refused by the
        # authid() check below like any other unusable one, with the
        # same visible, actionable hint.
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
                "Right-click to cancel the pick. Then enter the sizes."
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
        # fit.origin is the world position of local (0, 0) *in the
        # control points' own local frame* -- but a Grid's canonical
        # rectangle spans local [0, size_x] x [0, size_y], and control
        # points need not be anchored at that local origin (e.g. the
        # origin stake is unreachable, so the crew surveys local
        # (100, 50) to (137.5, 62.25) instead of (0, 0) to
        # (37.5, 12.25)). Round 1 fixed size_x/size_y to the extent
        # (max - min) but left fit.origin as-is, which put the *origin*
        # 111.8 m from every one of the surveyed corners it was fitted
        # to -- a correct azimuth and a 0.000 m residual on a grid whose
        # own outline no longer contains the ground it was measured
        # from. The true origin is the world position of local
        # (min_x, min_y), i.e. fit.origin translated by that offset
        # along the fitted axes.
        mins = local.min(axis=0)
        a = math.radians(fit.azimuth)
        y_hat = np.array([math.sin(a), math.cos(a)])
        x_hat = np.array([math.cos(a), -math.sin(a)])
        origin = np.asarray(fit.origin) + mins[0] * x_hat + mins[1] * y_hat
        self.origin_x.setValue(float(origin[0]))
        self.origin_y.setValue(float(origin[1]))
        self.azimuth.setValue(fit.azimuth)
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
            #
            # _validate()'s crs.isGeographic() check would also catch
            # this (round 2, Finding 2) and keep OK disabled either way
            # -- but only by disabling a button, silently, after this
            # method has already gone on to compute and display exactly
            # that convincing-but-wrong fit. Kept deliberately: refusing
            # here means azimuth/size_x/size_y and polygon_status never
            # show a plausible answer for this layer at all, rather than
            # showing one that then can't be saved.
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

    def _crs_scale_error(self, crs: QgsCoordinateReferenceSystem) -> float | None:
        """max|k - 1| of `crs`'s local linear scale at the current
        origin, where k = ground (ellipsoidal) distance / declared
        (crs-unit) distance -- or None if it can't be measured.

        A CRS whose stated unit is metres is not the same thing as a
        CRS whose metres are ground metres here: EPSG:3857 (Web
        Mercator) reports Meters and is not geographic, yet its scale
        factor grows without bound away from the equator (round 3,
        Finding 1). Measuring at (0, 0) specifically would be worse
        than not checking at all -- that is the origin of the *CRS*,
        which for something like EPSG:5070 or EPSG:3035 sits far
        outside the CRS's own area of use and gives a spuriously large
        error -- so this measures at the grid's own origin instead, and
        answers None (skip, don't refuse) before that origin has been
        set to anything, or if the transform/measurement itself fails
        (e.g. the origin lies outside the CRS's area of use).
        """
        ox, oy = self.origin_x.value(), self.origin_y.value()
        if ox == 0.0 and oy == 0.0:
            return None
        try:
            xform = QgsCoordinateTransform(
                crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
            )
            da = QgsDistanceArea()
            da.setEllipsoid("WGS84")
            baseline = 1000.0
            worst = 0.0
            for dx, dy in ((baseline, 0.0), (-baseline, 0.0), (0.0, baseline), (0.0, -baseline)):
                g0 = xform.transform(QgsPointXY(ox, oy))
                g1 = xform.transform(QgsPointXY(ox + dx, oy + dy))
                ground = da.measureLine(g0, g1)
                worst = max(worst, abs(ground / baseline - 1.0))
        except Exception:  # noqa: BLE001 -- see the docstring: skip, don't refuse
            return None
        return worst

    def _validate(self, *_: Any) -> None:
        # One CRS guard, not one per path in: the project's own CRS,
        # the digitise flow's canvas CRS (plugin.py's done()), and a
        # hand-picked CRS in this widget all flow through crs_widget, so
        # checking it here once covers all of them (round 2, Finding 2)
        # -- rather than teaching every path that can set a CRS to
        # separately refuse a bad one.
        #
        # Three ways a CRS is unusable for a metric grid frame:
        # - crs.authid() empty: valid CRS (e.g. a custom oblique
        #   Mercator), but Grid.crs is spec'd as an authority string,
        #   and session.add_grid/layers.py both trust it blindly, so it
        #   must be refused rather than silently written as crs="".
        # - crs.mapUnits() != Meters: not just geographic (degrees) --
        #   also catches a CRS in US survey feet (e.g. many state-plane
        #   ftUS zones sit right next to their metre sibling in the
        #   picker), which is not geographic and has an authid, but
        #   still not ground metres (round 3, Finding 1).
        # - the local scale factor: a CRS can report Meters and still
        #   not mean *ground* metres here -- EPSG:3857 is the sharpest
        #   example, off by double digits of percent away from the
        #   equator. Warn between CRS_SCALE_WARN and CRS_SCALE_REFUSE
        #   (real anisotropic equal-area CRSs like EPSG:5070/3035 land
        #   here when used away from their own centre) rather than
        #   blocking OK outright; only refuse past CRS_SCALE_REFUSE.
        crs = self.crs_widget.crs()
        scale_error = None
        if not crs.authid():
            self.crs_hint.setText("needs an authority code (e.g. EPSG) -- pick a registered CRS")
        elif crs.mapUnits() != Qgis.DistanceUnit.Meters:
            self.crs_hint.setText(f"must use metres, not {QgsUnitTypes.toString(crs.mapUnits())}")
        else:
            scale_error = self._crs_scale_error(crs)
            if scale_error is not None and scale_error > CRS_SCALE_REFUSE:
                self.crs_hint.setText(
                    f"off by {scale_error * 100:.1f}% here -- ground distances would be "
                    "wrong; pick a CRS accurate at this location"
                )
            elif scale_error is not None and scale_error > CRS_SCALE_WARN:
                self.crs_hint.setText(
                    f"off by {scale_error * 100:.2f}% at this origin -- distances will be "
                    "slightly distorted"
                )
            else:
                self.crs_hint.setText("")
        crs_ok = (
            bool(crs.authid())
            and crs.mapUnits() == Qgis.DistanceUnit.Meters
            and not (scale_error is not None and scale_error > CRS_SCALE_REFUSE)
        )
        ok = (
            bool(self.id_edit.text().strip())
            and self.velocity.value() > 0
            and self.size_x.value() > 0
            and self.size_y.value() > 0
            and crs_ok
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
