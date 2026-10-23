"""Grid dialog: one corner table, one Fit, one set of numbers.

Corners are typed (or, in later tasks, picked on the map or read from a
polygon) into a single table in any CRS; Fit places the grid from them and
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
    QgsPointXY,
    QgsProject,
    QgsUnitTypes,
)
from qgis.gui import QgsProjectionSelectionWidget
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

from nsgeo_qgis.lookup import CORNER_ROLES, corner_frame, rotate_roles
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
        self.crs_widget.crsChanged.connect(self._validate)
        # The local-scale-factor check below depends on where the grid
        # actually is, so a change to the origin can flip its own
        # verdict (round 3, Finding 1) -- unlike id/velocity/size, this
        # was not wired at all before this round.
        self.origin_x.valueChanged.connect(self._validate)
        self.origin_y.valueChanged.connect(self._validate)
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
            self.crs_widget.setCrs(project_crs)
        if grid is not None:
            self._prefill(grid)
            self._typed = [True, True]
        elif suggested_velocity is not None:
            self.velocity.setValue(suggested_velocity)
            self.velocity_hint.setText("from the header dielectric")
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
            grid_crs = self.crs_widget.crs()
            if not grid_crs.authid() or grid_crs.mapUnits() != Qgis.DistanceUnit.Meters:
                self._set_fit_line("set a metric CRS for the grid first")
                return
            half = self._half_filled_row()
            if half is not None:
                self._set_fit_line(
                    f"{CORNER_ROLES[half]} has only one coordinate: fill both or clear it"
                )
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
            self.origin_x.setValue(fit.origin[0])
            self.origin_y.setValue(fit.origin[1])
            self.azimuth.setValue(fit.azimuth)
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
        if grid_crs.authid() and not (ox == 0.0 and oy == 0.0) and sx > 0 and sy > 0:
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
