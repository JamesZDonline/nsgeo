"""Grid dialog: one corner table, one Fit, one set of numbers.

Corners are typed, picked on the map (plugin.py runs the pick, through
`pick_requested`/`pick_all_requested` and `set_corner`) or read from a
polygon into a single table in any CRS; Fit places the grid from them and
fills the form, which the user can still edit.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from nsgeo.geometry import Grid, fit_grid_from_corners
from nsgeo.velocity import VelocityModel
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsDistanceArea,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsPointXY,
    QgsProject,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.gui import (
    QgsFeaturePickerWidget,
    QgsMapCanvas,
    QgsMapLayerComboBox,
    QgsProjectionSelectionWidget,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.lookup import (
    CORNER_ROLES,
    compass_label,
    corner_frame,
    roles_from_ring,
    rotate_roles,
    utm_epsg,
)
from nsgeo_qgis.session import SiteSession

COL_ROLE, COL_A, COL_B, COL_FROM, COL_PICK, COL_OFF = range(6)

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
    pick_requested = pyqtSignal(int)
    pick_all_requested = pyqtSignal()
    corners_changed = pyqtSignal()
    pick_polygon_requested = pyqtSignal()

    def __init__(
        self,
        session: SiteSession,
        grid: Grid | None = None,
        suggested_velocity: float | None = None,
        parent: QWidget | None = None,
        canvas: QgsMapCanvas | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.existing = grid
        self.canvas = canvas
        # The grid CRS is automatic until the user picks one by hand, and
        # never for an existing grid (C4). Every write the dialog itself
        # makes to crs_widget happens under _setting_crs, because crsChanged
        # fires on a programmatic setCrs too.
        self._crs_auto = grid is None
        self._setting_crs = False
        self._grid_crs = QgsCoordinateReferenceSystem()  # the CRS the form's numbers are in
        self._auto_note = ""  # why the dialog picked the CRS, when it did
        self._crs_message = ""  # a hand pick that could not be honoured
        # Full-precision ground anchor (R10): (CRS, E, N, azimuth) in the last
        # metric CRS the grid was in. A spin box rounds to 3 decimals, which in
        # degrees is ~100 m, so a hand pick converts from here, not from the
        # boxes; a hand edit of the numbers while the CRS is not metric drops it.
        self._anchor: tuple[QgsCoordinateReferenceSystem, float, float, float] | None = None
        self._setting_numbers = False  # the dialog is writing origin/azimuth
        self.setWindowTitle(f"Grid · {grid.id}" if grid else "New grid")
        layout = QVBoxLayout(self)

        # Row state: (point in corners_crs, source) or None, in CORNER_ROLES
        # order. Full precision lives here; the cells show a rounded copy.
        self._corners: list[tuple[QgsPointXY, str] | None] = [None] * 4
        self._filling = False  # the dialog is writing cells: not a user edit
        self._sizing = False  # the dialog is writing a size box: not "typed"
        self._typed = [False, False]
        self._measured: tuple[float | None, float | None] | None = None
        self._fit_line = ""  # the last Fit's message; errors only cover it
        self._offsets: list[float | None] = [None] * 4
        layout.addWidget(self._build_corner_group())

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
        self.size_hint = QLabel("")
        self.size_hint.setWordWrap(True)
        self.use_measured_button = QPushButton("Use these")
        self.use_measured_button.clicked.connect(self.use_measured_size)
        hint_row = QHBoxLayout()
        hint_row.addWidget(self.size_hint, 1)
        hint_row.addWidget(self.use_measured_button)
        self.size_hint.hide()
        self.use_measured_button.hide()
        form_bottom.addRow(_label("", label_width), hint_row)
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
        self.crs_widget.crsChanged.connect(self._on_grid_crs_changed)
        self.crs_widget.crsChanged.connect(self._validate)
        # The local-scale-factor check below depends on where the grid
        # actually is, so a change to the origin can flip its own
        # verdict (round 3, Finding 1) -- unlike id/velocity/size, this
        # was not wired at all before this round.
        self.origin_x.valueChanged.connect(self._validate)
        self.origin_y.valueChanged.connect(self._validate)
        for w, part in ((self.origin_x, "origin"), (self.origin_y, "origin"), (self.azimuth, "az")):
            w.valueChanged.connect(lambda _v, part=part: self._on_numbers_edited(part))
        self.size_x.valueChanged.connect(lambda _v: self._size_edited(0))
        self.size_y.valueChanged.connect(lambda _v: self._size_edited(1))
        for w in (self.origin_x, self.origin_y, self.azimuth, self.size_x, self.size_y):
            w.valueChanged.connect(self._refresh_derived)
        self.crs_widget.crsChanged.connect(self._refresh_derived)

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
            self._write_crs(project_crs)
        if grid is not None:
            self._prefill(grid)
            self._typed = [True, True]
        else:
            if suggested_velocity is not None:
                self.velocity.setValue(suggested_velocity)
                self.velocity_hint.setText("from the header dielectric")
            self._settle_crs_at_open()
        self._validate()
        self._refresh_derived()

    # ---- corner table -----------------------------------------------------
    def _build_corner_group(self) -> QGroupBox:
        box = QGroupBox("Corners")
        v = QVBoxLayout(box)
        project_crs = QgsProject.instance().crs()
        self.corners_crs = QgsProjectionSelectionWidget()
        self.corners_crs.setCrs(
            project_crs if project_crs.isValid() else QgsCoordinateReferenceSystem("EPSG:4326")
        )
        self._prev_corners_crs = self.corners_crs.crs()
        crs_row = QHBoxLayout()
        crs_row.addWidget(QLabel("Corners in"))
        crs_row.addWidget(self.corners_crs, 1)
        v.addLayout(crs_row)

        self.corner_table = QTableWidget(4, 6)
        self.corner_table.verticalHeader().hide()
        self.pick_buttons: list[QPushButton] = []
        self._filling = True
        for row, name in enumerate(CORNER_ROLES):
            role = QTableWidgetItem(name)
            role.setFlags(role.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.corner_table.setItem(row, COL_ROLE, role)
            for col in (COL_A, COL_B):
                self.corner_table.setItem(row, col, QTableWidgetItem(""))
            for col in (COL_FROM, COL_OFF):
                cell = QTableWidgetItem("")
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.corner_table.setItem(row, col, cell)
            button = QPushButton("Pick")
            button.clicked.connect(lambda _checked=False, r=row: self.pick_requested.emit(r))
            self.corner_table.setCellWidget(row, COL_PICK, button)
            self.pick_buttons.append(button)
        self._filling = False
        self._set_headers()
        self.corner_table.itemChanged.connect(self._on_cell_edited)
        self.corners_crs.crsChanged.connect(self._on_corners_crs_changed)
        v.addWidget(self.corner_table)

        buttons = QHBoxLayout()
        self.pick_all_button = QPushButton("Pick all")
        self.pick_all_button.clicked.connect(lambda _checked=False: self.pick_all_requested.emit())
        self.rotate_button = QPushButton("⟳ Rotate")
        self.rotate_button.clicked.connect(self.rotate_corners)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_corners)
        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self.fit_corners)
        for b in (self.pick_all_button, self.rotate_button, self.clear_button, self.fit_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        v.addLayout(buttons)
        self.fit_status = QLabel("")
        self.fit_status.setWordWrap(True)
        v.addWidget(self.fit_status)

        divider = QLabel("or fill all four from a polygon")
        divider.setStyleSheet("color: gray; border-top: 1px solid gray; padding-top: 4px;")
        v.addWidget(divider)
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)
        self.feature_picker = QgsFeaturePickerWidget()
        self.layer_combo.layerChanged.connect(self.feature_picker.setLayer)
        self.feature_picker.setLayer(self.layer_combo.currentLayer())
        polygon_row = QHBoxLayout()
        polygon_row.addWidget(self.layer_combo, 1)
        polygon_row.addWidget(self.feature_picker, 1)
        self.pick_polygon_button = QPushButton("Pick on map")
        self.pick_polygon_button.clicked.connect(
            lambda _checked=False: self.pick_polygon_requested.emit()
        )
        self.fill_button = QPushButton("Fill")
        self.fill_button.clicked.connect(self.fill_from_polygon)
        polygon_row.addWidget(self.pick_polygon_button)
        polygon_row.addWidget(self.fill_button)
        v.addLayout(polygon_row)
        return box

    def _geographic(self) -> bool:
        return self.corners_crs.crs().isGeographic()

    def _set_headers(self) -> None:
        a, b = ("lon", "lat") if self._geographic() else ("E", "N")
        self.corner_table.setHorizontalHeaderLabels(["corner", a, b, "from", "", "off by"])

    def _fmt(self, value: float) -> str:
        return f"{value:.8f}" if self._geographic() else f"{value:.3f}"

    def _write_row(self, row: int) -> None:
        entry = self._corners[row]
        cells = (
            ("", "", "")
            if entry is None
            else (
                self._fmt(entry[0].x()),
                self._fmt(entry[0].y()),
                entry[1],
            )
        )
        self._filling = True
        try:
            for col, text in zip((COL_A, COL_B, COL_FROM), cells):
                self.corner_table.item(row, col).setText(text)
        finally:
            self._filling = False

    def _set_fit_line(self, text: str) -> None:
        self._fit_line = text
        self.fit_status.setText(text)

    def _rows_changed(self) -> None:
        # A good row change brings the last Fit's line back over any error.
        self.fit_status.setText(self._fit_line)
        self._refresh_derived()
        self.corners_changed.emit()

    def corner_point(self, row: int) -> QgsPointXY | None:
        entry = self._corners[row]
        return None if entry is None else QgsPointXY(entry[0])

    def corner_source(self, row: int) -> str:
        entry = self._corners[row]
        return "" if entry is None else entry[1]

    def corner_offsets(self) -> list[float | None]:
        return list(self._offsets)

    def set_corner(
        self, row: int, point: QgsPointXY, crs: QgsCoordinateReferenceSystem, source: str
    ) -> bool:
        target = self.corners_crs.crs()
        converted = QgsPointXY(point)
        if crs != target:
            try:
                xform = QgsCoordinateTransform(crs, target, QgsProject.instance())
                converted = xform.transform(point)
            except QgsCsException:
                self.fit_status.setText(f"could not convert that point into {target.authid()}")
                return False
        self._corners[row] = (converted, source)
        self._write_row(row)
        self._rows_changed()
        return True

    def _on_cell_edited(self, item: QTableWidgetItem) -> None:
        # itemChanged slot: report, never raise (Qt would swallow it).
        if self._filling or item.column() not in (COL_A, COL_B):
            return
        try:
            row = item.row()
            prev = self._corners[row]
            vals: list[float | None] = []
            bad: str | None = None
            for col, comp in ((COL_A, 0), (COL_B, 1)):
                text = self.corner_table.item(row, col).text().strip()
                if not text:
                    vals.append(None)
                    continue
                kept = None if prev is None else (prev[0].x(), prev[0].y())[comp]
                if kept is not None and text == self._fmt(kept):
                    vals.append(kept)  # untouched cell: keep full precision
                    continue
                try:
                    num = float(text)
                    if not math.isfinite(num):
                        raise ValueError(text)
                    vals.append(num)
                except ValueError:
                    vals.append(None)
                    bad = text
            x, y = vals
            if bad is None and x is not None and y is not None:
                self._corners[row] = (QgsPointXY(x, y), "typed")
            else:
                self._corners[row] = None
            self._filling = True
            try:
                self.corner_table.item(row, COL_FROM).setText("typed" if self._corners[row] else "")
            finally:
                self._filling = False
            self._rows_changed()
            if bad is not None:
                self.fit_status.setText(f"{CORNER_ROLES[row]}: '{bad}' is not a number")
            elif self._corners[row] is None and (vals[0] is None) != (vals[1] is None):
                self.fit_status.setText(f"{CORNER_ROLES[row]}: needs both coordinates")
        except Exception as exc:  # noqa: BLE001 -- slot: show, don't raise
            self.fit_status.setText(f"could not read that cell: {exc}")

    def _on_corners_crs_changed(self, *_: Any) -> None:
        try:
            old, new = self._prev_corners_crs, self.corners_crs.crs()
            if old == new:
                return
            if not new.isValid():
                return
            converted: list[tuple[QgsPointXY, str] | None] = []
            try:
                xform = QgsCoordinateTransform(old, new, QgsProject.instance())
                for entry in self._corners:
                    converted.append(
                        None if entry is None else (xform.transform(entry[0]), entry[1])
                    )
            except QgsCsException:
                self.fit_status.setText(f"could not convert the corners into {new.authid()}")
                self.corners_crs.blockSignals(True)
                self.corners_crs.setCrs(old)
                self.corners_crs.blockSignals(False)
                return
            self._prev_corners_crs = new
            self._corners = converted
            self._set_headers()
            for row in range(4):
                self._write_row(row)
            self._rows_changed()
        except Exception as exc:  # noqa: BLE001 -- slot: show, don't raise
            self.fit_status.setText(f"could not change the corners' CRS: {exc}")

    def clear_corners(self) -> None:
        try:
            self._corners = [None] * 4
            self._measured = None
            self._fit_line = ""
            for row in range(4):
                self._write_row(row)
            self._rows_changed()
        except Exception as exc:  # noqa: BLE001 -- slot: show, don't raise
            self.fit_status.setText(f"could not clear the corners: {exc}")

    def rotate_corners(self) -> None:
        try:
            self._corners = rotate_roles(self._corners)
            # The old +Y edge is the new +X edge, so the sizes swap with it.
            sx, sy = self.size_x.value(), self.size_y.value()
            self._sizing = True
            try:
                self.size_x.setValue(sy)
                self.size_y.setValue(sx)
            finally:
                self._sizing = False
            self._typed = [self._typed[1], self._typed[0]]
            if self._measured is not None:
                self._measured = (self._measured[1], self._measured[0])
            for row in range(4):
                self._write_row(row)
            self._rows_changed()
        except Exception as exc:  # noqa: BLE001 -- slot: show, don't raise
            self.fit_status.setText(f"could not rotate the corners: {exc}")

    # ---- fill from a polygon ----------------------------------------------
    def set_polygon_feature(self, layer: QgsVectorLayer, fid: int) -> bool:
        """Select a polygon in both lists (the map pick's way in).

        The layer list offers only this project's polygon layers, and its
        setLayer() answers any other layer by quietly dropping the current
        choice, while the feature picker would take the fid regardless --
        the two lists would then name different layers. A layer the list
        does not offer therefore changes neither, and the status line says
        why. Returns whether the polygon was selected.
        """
        offered = any(self.layer_combo.layer(i) is layer for i in range(self.layer_combo.count()))
        if not offered:
            self.fit_status.setText(
                f"{layer.name()} is not a polygon layer of this project, so it cannot be chosen"
            )
            return False
        self.layer_combo.setLayer(layer)
        self.feature_picker.setLayer(layer)
        self.feature_picker.setFeature(fid)
        return True

    def chosen_polygon(self) -> tuple[QgsVectorLayer, QgsGeometry] | None:
        """The layer and geometry the lists name, or None.

        Layer and fid both come from the feature picker, so they can never
        belong to two different layers.
        """
        layer = self.feature_picker.layer()
        if not isinstance(layer, QgsVectorLayer):
            return None
        picked = self.feature_picker.feature()
        if not picked.isValid():
            return None
        feature = layer.getFeature(picked.id())
        if not feature.isValid() or feature.geometry().isNull():
            return None
        return layer, feature.geometry()

    def fill_from_polygon(self) -> None:
        """Fill all four rows from the chosen polygon's first ring. Never fits."""
        try:
            self._fill_from_polygon()
        except Exception as exc:  # noqa: BLE001 -- slot: show, don't raise
            self.fit_status.setText(f"could not fill from the polygon: {exc}")

    def _fill_from_polygon(self) -> None:
        layer = self.feature_picker.layer()  # with its fid: see chosen_polygon
        picked = self.feature_picker.feature()
        if not isinstance(layer, QgsVectorLayer) or not picked.isValid():
            self.fit_status.setText("select a polygon feature first")
            return
        geometry = layer.getFeature(picked.id()).geometry()
        ring: list[QgsPointXY] = []
        if not geometry.isNull():
            if geometry.isMultipart():
                parts = geometry.asMultiPolygon()
                ring = parts[0][0] if parts and parts[0] else []
            else:
                rings = geometry.asPolygon()
                ring = rings[0] if rings else []
        if not ring:
            self.fit_status.setText("this feature has no rings to read corners from")
            return
        target = self.corners_crs.crs()
        try:
            xform = QgsCoordinateTransform(layer.crs(), target, QgsProject.instance())
            points = [xform.transform(QgsPointXY(p)) for p in ring]
        except QgsCsException:
            self.fit_status.setText(f"could not convert the polygon into {target.authid()}")
            return
        # In degrees, a step in longitude is shorter than one in latitude by
        # cos(mean latitude); roles and compass work in that corrected plane.
        scale = 1.0
        if target.isGeographic():
            scale = math.cos(math.radians(sum(p.y() for p in points) / len(points)))
        plane = [(p.x() * scale, p.y()) for p in points]
        try:
            ordered, idx = roles_from_ring(plane)
        except ValueError as exc:
            self.fit_status.setText(str(exc))
            return
        centre = (sum(p[0] for p in ordered) / 4, sum(p[1] for p in ordered) / 4)
        by_plane = {pl: pt for pl, pt in zip(plane, points)}
        rows = [
            (
                QgsPointXY(by_plane[xy]),
                f"v{i} {compass_label(xy, centre)}",
            )
            for xy, i in zip(ordered, idx)
        ]
        for row, (point, source) in enumerate(rows):
            self.set_corner(row, point, target, source)

    # ---- fit --------------------------------------------------------------
    def _corners_in_grid_crs(
        self, grid_crs: QgsCoordinateReferenceSystem
    ) -> list[tuple[float, float] | None]:
        source = self.corners_crs.crs()
        xform = (
            None
            if source == grid_crs
            else QgsCoordinateTransform(source, grid_crs, QgsProject.instance())
        )
        out: list[tuple[float, float] | None] = []
        for entry in self._corners:
            if entry is None:
                out.append(None)
                continue
            p = entry[0] if xform is None else xform.transform(entry[0])
            out.append((p.x(), p.y()))
        return out

    def fit_corners(self) -> None:
        # clicked slot: every failure becomes a message in fit_status.
        try:
            half = self._half_filled_row()
            if half is not None:
                self._set_fit_line(
                    f"{CORNER_ROLES[half]} has only one coordinate: fill both or clear it"
                )
                return
            if self._crs_auto:
                self._settle_crs_from_corners()
            grid_crs = self.crs_widget.crs()
            if not grid_crs.authid() or grid_crs.mapUnits() != Qgis.DistanceUnit.Meters:
                self._set_fit_line("set a metric CRS for the grid first")
                return
            try:
                points = self._corners_in_grid_crs(grid_crs)
            except QgsCsException:
                self._set_fit_line(f"could not convert the corners into {grid_crs.authid()}")
                return
            try:
                frame = corner_frame(points)
                fit = fit_grid_from_corners(frame.local, frame.world)
            except ValueError as exc:
                self._set_fit_line(str(exc))
                return
            self._write_numbers(grid_crs, fit.origin[0], fit.origin[1], fit.azimuth)
            self._sizing = True
            try:
                for axis, box, measured in (
                    (0, self.size_x, frame.size_x),
                    (1, self.size_y, frame.size_y),
                ):
                    if measured is not None and not self._typed[axis]:
                        box.setValue(measured)
            finally:
                self._sizing = False
            self._measured = (frame.size_x, frame.size_y)
            rms = f"{fit.residual_rms:.3f}"
            line = f"rigid fit RMS {rms} m from {len(frame.rows)} corners"
            if rms != "0.000":
                line += " · not quite square: see off by"
            self._set_fit_line(line)
            self._refresh_derived()
        except Exception as exc:  # noqa: BLE001 -- slot: show, don't raise
            self._set_fit_line(f"fit failed: {exc}")

    def _half_filled_row(self) -> int | None:
        for row in range(4):
            if self._corners[row] is None:
                texts = [self.corner_table.item(row, c).text().strip() for c in (COL_A, COL_B)]
                if sum(bool(t) for t in texts) == 1:
                    return row
        return None

    # ---- typed sizes ------------------------------------------------------
    def _size_edited(self, axis: int) -> None:
        if not self._sizing:
            self._typed[axis] = True

    def sizes_typed(self) -> tuple[bool, bool]:
        return (self._typed[0], self._typed[1])

    def measured_size(self) -> tuple[float | None, float | None] | None:
        return self._measured

    def use_measured_size(self) -> None:
        try:
            if self._measured is None:
                return
            self._sizing = True
            try:
                for box, measured in zip((self.size_x, self.size_y), self._measured):
                    if measured is not None:
                        box.setValue(measured)
            finally:
                self._sizing = False
            self._typed = [False, False]
            self._refresh_derived()
        except Exception as exc:  # noqa: BLE001 -- slot: show, don't raise
            self.fit_status.setText(f"could not use the measured size: {exc}")

    # ---- off-by and the size hint -----------------------------------------
    def _refresh_derived(self, *_: Any) -> None:
        try:
            self._refresh_off_by()
            self._refresh_size_hint()
        except Exception as exc:  # noqa: BLE001 -- slot: show, don't raise
            self.fit_status.setText(f"could not update the corner offsets: {exc}")

    def _refresh_off_by(self) -> None:
        offsets: list[float | None] = [None] * 4
        grid_crs = self.crs_widget.crs()
        ox, oy = self.origin_x.value(), self.origin_y.value()
        sx, sy = self.size_x.value(), self.size_y.value()
        if (
            not (ox == 0.0 and oy == 0.0)
            and sx > 0
            and sy > 0
            and self._crs_check(grid_crs, QgsPointXY(ox, oy))[0] is None
        ):
            try:
                points = self._corners_in_grid_crs(grid_crs)
                grid = Grid("_", (ox, oy), self.azimuth.value(), sx, sy, grid_crs.authid(), 0.5)
                expect = grid.to_world(np.array([[0, 0], [sx, 0], [sx, sy], [0, sy]], dtype=float))
                for i, p in enumerate(points):
                    if p is not None:
                        offsets[i] = float(np.hypot(p[0] - expect[i, 0], p[1] - expect[i, 1]))
            except (QgsCsException, ValueError):
                offsets = [None] * 4
        self._offsets = offsets
        self._filling = True
        try:
            for row, off in enumerate(offsets):
                self.corner_table.item(row, COL_OFF).setText("" if off is None else f"{off:.2f} m")
        finally:
            self._filling = False

    def _refresh_size_hint(self) -> None:
        show = False
        if self._measured is not None:
            mx, my = self._measured
            for axis, measured, box in ((0, mx, self.size_x), (1, my, self.size_y)):
                if (
                    measured is not None
                    and self._typed[axis]
                    and abs(measured - box.value()) >= 0.005
                ):
                    show = True
            if show:
                fx = "?" if mx is None else f"{mx:.2f}"
                fy = "?" if my is None else f"{my:.2f}"
                self.size_hint.setText(f"the corners measure {fx} × {fy} m · your size is kept")
        self.size_hint.setVisible(show)
        self.use_measured_button.setVisible(show)

    # ---- result -----------------------------------------------------------
    def _prefill(self, grid: Grid) -> None:
        self.id_edit.setText(grid.id)
        self.id_edit.setEnabled(False)  # lines reference the id; renaming is a different feature
        self._write_crs(QgsCoordinateReferenceSystem(grid.crs))
        self._write_numbers(self.crs_widget.crs(), grid.origin[0], grid.origin[1], grid.azimuth)
        self.size_x.setValue(grid.size_x)
        self.size_y.setValue(grid.size_y)
        self.spacing.setValue(grid.default_spacing)
        if grid.velocity is not None:
            self.velocity.setValue(grid.velocity.surface_velocity)

    def _crs_scale_error(
        self, crs: QgsCoordinateReferenceSystem, point: QgsPointXY | None = None
    ) -> float | None:
        """max|k - 1| of `crs`'s local linear scale at `point` (in
        `crs` coordinates; the form's origin when not given), where
        k = ground (ellipsoidal) distance / declared (crs-unit) distance --
        or None if it can't be measured.

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
        if point is None:
            ox, oy = self.origin_x.value(), self.origin_y.value()
            if ox == 0.0 and oy == 0.0:
                return None
        else:
            ox, oy = point.x(), point.y()
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

    def _crs_check(
        self, crs: QgsCoordinateReferenceSystem, point: QgsPointXY | None
    ) -> tuple[str | None, float | None]:
        """`_validate`'s three checks for `crs` at `point` (in `crs`
        coordinates; the form's origin when None): (the failed check, the
        scale error). The check is "authid", "units" or "scale", or None
        when `crs` is usable there. A CRS that only draws the warning is
        usable."""
        if not crs.authid():
            return "authid", None
        if crs.mapUnits() != Qgis.DistanceUnit.Meters:
            return "units", None
        scale_error = self._crs_scale_error(crs, point)
        if scale_error is not None and scale_error > CRS_SCALE_REFUSE:
            return "scale", scale_error
        return None, scale_error

    def _usable_at(
        self, crs: QgsCoordinateReferenceSystem, lonlat: QgsPointXY
    ) -> tuple[str | None, float | None]:
        """`_crs_check` for `crs` at a lon/lat. A CRS that cannot even place
        the location ("outside", "none") is not usable there."""
        if not crs.isValid():
            return "none", None
        try:
            xform = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem("EPSG:4326"), crs, QgsProject.instance()
            )
            point = xform.transform(lonlat)
        except QgsCsException:
            return "outside", None
        if not (math.isfinite(point.x()) and math.isfinite(point.y())):
            return "outside", None
        return self._crs_check(crs, point)

    # ---- the grid's CRS: automatic, or the user's ---------------------------
    def crs_is_auto(self) -> bool:
        return self._crs_auto

    def _write_crs(self, crs: QgsCoordinateReferenceSystem) -> None:
        """Put `crs` in the widget as the dialog's own write, not a pick."""
        self._setting_crs = True
        try:
            self.crs_widget.setCrs(crs)
        finally:
            self._setting_crs = False
        self._grid_crs = crs

    def _lonlat(self, point: QgsPointXY, crs: QgsCoordinateReferenceSystem) -> QgsPointXY | None:
        if not crs.isValid():
            return None
        try:
            out = QgsCoordinateTransform(
                crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
            ).transform(point)
        except QgsCsException:
            return None
        return out if math.isfinite(out.x()) and math.isfinite(out.y()) else None

    def _canvas_centre(self) -> QgsPointXY | None:
        """The map canvas's centre as lon/lat, or None when there is none to use."""
        if self.canvas is None:
            return None
        extent = self.canvas.extent()
        if extent.isNull() or extent.isEmpty():
            return None
        return self._lonlat(extent.center(), self.canvas.mapSettings().destinationCrs())

    def _site_crs(self) -> QgsCoordinateReferenceSystem | None:
        site = self.session.site
        if site is None or not site.grids:
            return None
        return QgsCoordinateReferenceSystem(site.grids[0].crs)

    def _project_reason(
        self, crs: QgsCoordinateReferenceSystem, kind: str | None, scale_error: float | None
    ) -> str:
        if not crs.isValid():
            return "the project has no CRS"
        if kind == "authid":
            return "the project CRS has no authority code"
        if kind == "units":
            return f"the project CRS ({crs.authid()}) is in {QgsUnitTypes.toString(crs.mapUnits())}"
        return f"the project CRS ({crs.authid()}) is off by {(scale_error or 0.0) * 100:.1f}% here"

    def _choose_crs(self, lonlat: QgsPointXY) -> tuple[QgsCoordinateReferenceSystem, str]:
        """The grid CRS for a grid at `lonlat`, and the note saying why (C10):
        the site's CRS, else the project's, else that spot's UTM zone, taking
        the first that is usable there."""
        project = QgsProject.instance().crs()
        site = self._site_crs()
        if site is not None and self._usable_at(site, lonlat)[0] is None:
            return site, "picked for you: the CRS the site's other grids use"
        kind, scale_error = self._usable_at(project, lonlat)
        if kind is None:
            return project, ""
        epsg = utm_epsg(lonlat.x(), lonlat.y())
        if epsg is None:
            return project, "no UTM zone covers this latitude"
        reason = self._project_reason(project, kind, scale_error)
        return QgsCoordinateReferenceSystem(f"EPSG:{epsg}"), f"picked for you: {reason}"

    def _apply_auto_crs(self, crs: QgsCoordinateReferenceSystem, note: str) -> None:
        if crs != self.crs_widget.crs():
            old = self._grid_crs
            self._write_crs(crs)
            # The grid stays where it is on the ground; a failed conversion
            # is left to the Fit that follows, which rewrites both numbers.
            self._convert_grid(old, crs)
        self._auto_note = note
        self._validate()
        self._refresh_derived()

    def _settle_crs_at_open(self) -> None:
        centre = self._canvas_centre()
        if centre is not None:
            self._apply_auto_crs(*self._choose_crs(centre))
            return
        project = self.crs_widget.crs()
        if self._crs_check(project, None)[0] is not None:
            self._auto_note = "a UTM zone will be picked when you fit corners"

    def _settle_crs_from_corners(self) -> None:
        points = [e[0] for e in self._corners if e is not None]
        if not points:
            return
        centroid = QgsPointXY(
            sum(p.x() for p in points) / len(points), sum(p.y() for p in points) / len(points)
        )
        lonlat = self._lonlat(centroid, self.corners_crs.crs())
        if lonlat is not None:
            self._apply_auto_crs(*self._choose_crs(lonlat))

    def _convert_grid(
        self, old: QgsCoordinateReferenceSystem, new: QgsCoordinateReferenceSystem
    ) -> str | None:
        """Move Origin E/N and Azimuth from `old` to `new`, keeping the grid
        where it is on the ground (C11); the azimuth is the bearing from the
        origin to a point 100 m along +Y. Nothing happens while the origin is
        still (0, 0). Returns a message when it could not, and then changes
        nothing."""
        if (
            (self.origin_x.value() == 0.0 and self.origin_y.value() == 0.0)
            or not old.isValid()
            or not new.isValid()
        ):
            self._anchor = None
            return None
        # From the anchor when there is one (full precision, always metric);
        # otherwise best effort from the boxes, in `old`.
        if self._anchor is not None:
            src, ox, oy, az = self._anchor
        else:
            src, ox, oy, az = (
                old,
                self.origin_x.value(),
                self.origin_y.value(),
                self.azimuth.value(),
            )
        try:
            p0, new_az = self._chord(src, new, ox, oy, az)
        except QgsCsException:
            return f"could not convert the grid into {new.authid()}; kept {old.authid()}"
        self._write_numbers(new, p0.x(), p0.y(), new_az, keep_anchor=True)
        return None

    def _write_numbers(
        self,
        crs: QgsCoordinateReferenceSystem,
        x: float,
        y: float,
        az: float,
        keep_anchor: bool = False,
    ) -> None:
        """The dialog's own write of Origin E/N and Azimuth, in `crs`. A metric
        `crs` makes (x, y, az) the anchor at full precision; a non-metric one
        leaves the anchor as it was when `keep_anchor`, else drops it."""
        self._setting_numbers = True
        try:
            for box, value in ((self.origin_x, x), (self.origin_y, y), (self.azimuth, az)):
                box.setValue(value)
        finally:
            self._setting_numbers = False
        if crs.isValid() and crs.mapUnits() == Qgis.DistanceUnit.Meters:
            self._anchor = (crs, x, y, az)
        elif not keep_anchor:
            self._anchor = None

    def _chord(
        self,
        src: QgsCoordinateReferenceSystem,
        dst: QgsCoordinateReferenceSystem,
        ox: float,
        oy: float,
        az: float,
    ) -> tuple[QgsPointXY, float]:
        """The origin and azimuth (cw from N) of the same grid in `dst`. The
        azimuth is the bearing, in `dst`'s axes, from the transformed origin to
        the transformed point one step along +Y in `src`'s axes: 100 units for
        a projected CRS, 0.001 degrees for a geographic one. Raises
        QgsCsException when it cannot."""
        xform = QgsCoordinateTransform(src, dst, QgsProject.instance())
        step = 1e-3 if src.isGeographic() else 100.0
        a = math.radians(az)
        p0 = xform.transform(QgsPointXY(ox, oy))
        p1 = xform.transform(QgsPointXY(ox + step * math.sin(a), oy + step * math.cos(a)))
        new_az = math.degrees(math.atan2(p1.x() - p0.x(), p1.y() - p0.y())) % 360.0
        if not all(math.isfinite(v) for v in (p0.x(), p0.y(), new_az)):
            raise QgsCsException("not finite")
        return p0, new_az

    def _on_numbers_edited(self, part: str) -> None:
        # valueChanged slot: a hand edit (the dialog's own writes are guarded).
        if self._setting_numbers:
            return
        try:
            crs = self.crs_widget.crs()
            ox, oy, az = self.origin_x.value(), self.origin_y.value(), self.azimuth.value()
            if crs.isValid() and crs.mapUnits() == Qgis.DistanceUnit.Meters:
                self._anchor = (crs, ox, oy, az)
            elif self._anchor is not None and crs.isValid():
                # Not metric: re-derive only the part that was edited, so a
                # nudge-and-undo or an azimuth-only change keeps the rest of
                # the anchor at full precision.
                acrs, ax, ay, aaz = self._anchor
                try:
                    p0, new_az = self._chord(crs, acrs, ox, oy, az)
                except QgsCsException:
                    self._anchor = None
                    return
                if part == "origin":
                    self._anchor = (acrs, p0.x(), p0.y(), aaz)
                else:
                    self._anchor = (acrs, ax, ay, new_az)
            else:
                self._anchor = None
        except Exception as exc:  # noqa: BLE001 -- slot: show, don't raise
            self._anchor = None
            self._crs_message = f"could not read the grid numbers: {exc}"

    def _on_grid_crs_changed(self, *_: Any) -> None:
        # crsChanged slot: a change outside _setting_crs is the user's pick.
        if self._setting_crs:
            return
        was = (self._crs_auto, self._auto_note, self._crs_message)
        try:
            old, new = self._grid_crs, self.crs_widget.crs()
            self._crs_auto, self._auto_note, self._crs_message = False, "", ""
            error = self._convert_grid(old, new)
            if error is None:
                self._grid_crs = new
                return
            self._crs_auto, self._auto_note = was[0], was[1]
            self._crs_message = error
            self._write_crs(old)
        except Exception as exc:  # noqa: BLE001 -- slot: show, don't raise
            self._crs_message = f"could not change the grid CRS: {exc}"

    def _validate(self, *_: Any) -> None:
        # One CRS guard, not one per path in: the project's own CRS, the
        # one picked automatically (_choose_crs), an existing grid's, and
        # a hand-picked CRS in this widget all flow through crs_widget, so
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
        kind, scale_error = self._crs_check(crs, None)
        problem = ""
        if kind == "authid":
            problem = "needs an authority code (e.g. EPSG) -- pick a registered CRS"
        elif kind == "units":
            problem = f"must use metres, not {QgsUnitTypes.toString(crs.mapUnits())}"
        elif kind == "scale" and scale_error is not None:
            problem = (
                f"off by {scale_error * 100:.1f}% here -- ground distances would be "
                "wrong; pick a CRS accurate at this location"
            )
        elif scale_error is not None and scale_error > CRS_SCALE_WARN:
            problem = (
                f"off by {scale_error * 100:.2f}% at this origin -- distances will be "
                "slightly distorted"
            )
        self.crs_hint.setText(
            " · ".join(t for t in (problem, self._crs_message, self._auto_note) if t)
        )
        crs_ok = kind is None
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
