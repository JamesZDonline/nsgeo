"""Import Grad601 files onto magnetometer grids.

Modeless, like `ImportDialog` (`plugin.open_mag_import_dialog` is the owner):
the toolbar and the Survey panel stay clickable, so the site can be closed or
replaced while this dialog is open. `accept()` therefore checks it is still the
same `Site` object before it writes anything, and every slot guards its own
body and reports on the status line instead of raising (Qt swallows a slot's
exception).

The setup (walking pattern) applies to every file in the list. The Missing and
Fits columns, and the picture beside the form, redraw as it changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from nsgeo.mag import MagFile, MagFileError, MagSetup, fit_problems, missing_summary
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.mag_setup_picture import MagSetupPicture

FILE_FILTER = "Grad601 grid (*.dat *.DAT)"
COL_FILE, COL_GRID, COL_SIZE, COL_MISSING, COL_FITS = range(5)
_NONE = "—"
#: Each corner's item data is `far_x + 2 * far_y`.
_CORNERS = (
    ("At the origin", 0),
    ("At the far end of X", 1),
    ("At the far end of Y", 2),
    ("At the far corner", 3),
)


@dataclass
class _Row:
    path: Path
    n_rows: int
    n_readings: int


class MagImportDialog(QDialog):
    new_grid_requested = pyqtSignal()
    imported = pyqtSignal(list)  # [(key, grid_id, summary)] after a successful import

    def __init__(
        self, session: SiteSession, grid_id: str | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._site = session.site
        self._prefer = grid_id
        self._rows: list[_Row] = []
        self._combos: list[QComboBox] = []
        self._updating = False
        self.setWindowTitle("Import magnetometer files")
        self.resize(900, 640)
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["File", "Grid", "Size", "Missing", "Fits"])
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        row_buttons = QHBoxLayout()
        self.add_button = QPushButton("Add files…")
        self.add_button.clicked.connect(self._pick_files)
        self.new_grid_button = QPushButton("New mag grid…")
        self.new_grid_button.setToolTip(
            "Opens the grid dialog with Instrument set to Magnetometer, 30 × 30 m"
        )
        self.new_grid_button.clicked.connect(self._request_new_grid)
        row_buttons.addWidget(self.add_button)
        row_buttons.addWidget(self.new_grid_button)
        row_buttons.addStretch(1)
        layout.addLayout(row_buttons)

        group = QGroupBox("Setup (remembered for this site)")
        group_layout = QHBoxLayout(group)
        form = QFormLayout()
        self.axis_combo = QComboBox()
        self.axis_combo.addItem("X", "x")
        self.axis_combo.addItem("Y", "y")
        form.addRow("Traverses run along", self.axis_combo)
        self.corner_combo = QComboBox()
        for text, data in _CORNERS:
            self.corner_combo.addItem(text, data)
        form.addRow("First traverse starts", self.corner_combo)
        self.spacing_spin = self._double(0.01, 100.0, 0.05)
        form.addRow("Traverse spacing (m)", self.spacing_spin)
        self.offset_spin = self._double(0.0, 100.0, 0.05)
        form.addRow("First traverse offset (m)", self.offset_spin)
        self.rpm_spin = self._double(0.1, 1000.0, 1.0)
        form.addRow("Readings per metre", self.rpm_spin)
        self.sensors_spin = QSpinBox()
        self.sensors_spin.setRange(1, 4)
        form.addRow("Sensors", self.sensors_spin)
        self.separation_spin = self._double(0.01, 100.0, 0.5)
        form.addRow("Sensor separation (m)", self.separation_spin)
        self.walked_combo = QComboBox()
        self.walked_combo.addItem("Zigzag", True)
        self.walked_combo.addItem("Parallel", False)
        form.addRow("Walked", self.walked_combo)
        self.flipped_box = QCheckBox("Return traverses already flipped by the download")
        form.addRow(self.flipped_box)
        run_row = QHBoxLayout()
        self.missing_spin = QSpinBox()
        self.missing_spin.setRange(1, 50)
        run_row.addWidget(QLabel("Missing data: runs of"))
        run_row.addWidget(self.missing_spin)
        run_row.addWidget(QLabel("or more zeros"))
        run_row.addStretch(1)
        form.addRow(run_row)
        group_layout.addLayout(form, 1)
        self.picture = MagSetupPicture()
        self.picture.setMinimumWidth(280)
        group_layout.addWidget(self.picture, 1)
        layout.addWidget(group)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox()
        self.import_button = buttons.addButton("Import", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.set_setup(session.mag_setup() or MagSetup())
        for signal in (
            self.axis_combo.currentIndexChanged,
            self.corner_combo.currentIndexChanged,
            self.spacing_spin.valueChanged,
            self.offset_spin.valueChanged,
            self.rpm_spin.valueChanged,
            self.sensors_spin.valueChanged,
            self.separation_spin.valueChanged,
            self.walked_combo.currentIndexChanged,
            self.flipped_box.toggled,
            self.missing_spin.valueChanged,
        ):
            signal.connect(self._on_setup_changed)
        session.grids_changed.connect(self._on_grids_changed)

    @staticmethod
    def _double(low: float, high: float, step: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(3)
        spin.setSingleStep(step)
        return spin

    # ---- the setup ---------------------------------------------------------
    def setup(self) -> MagSetup:
        """The setup the form holds. A `ValueError` carries `MagSetup`'s own message."""
        corner = self.corner_combo.currentData()
        return MagSetup(
            axis=self.axis_combo.currentData(),
            far_x=bool(corner & 1),
            far_y=bool(corner & 2),
            spacing_m=self.spacing_spin.value(),
            first_offset_m=self.offset_spin.value(),
            readings_per_metre=self.rpm_spin.value(),
            sensors=self.sensors_spin.value(),
            sensor_separation_m=self.separation_spin.value(),
            zigzag=bool(self.walked_combo.currentData()),
            flipped=self.flipped_box.isChecked(),
            missing_run=self.missing_spin.value(),
        )

    def set_setup(self, setup: MagSetup) -> None:
        was, self._updating = self._updating, True
        try:
            self.axis_combo.setCurrentIndex(self.axis_combo.findData(setup.axis))
            self.corner_combo.setCurrentIndex(
                self.corner_combo.findData(int(setup.far_x) + 2 * int(setup.far_y))
            )
            self.spacing_spin.setValue(setup.spacing_m)
            self.offset_spin.setValue(setup.first_offset_m)
            self.rpm_spin.setValue(setup.readings_per_metre)
            self.sensors_spin.setValue(setup.sensors)
            self.separation_spin.setValue(setup.sensor_separation_m)
            self.walked_combo.setCurrentIndex(self.walked_combo.findData(setup.zigzag))
            self.flipped_box.setChecked(setup.flipped)
            self.missing_spin.setValue(setup.missing_run)
        finally:
            self._updating = was
        self._on_setup_changed()

    def _on_setup_changed(self, *_: Any) -> None:
        if self._updating:
            return
        try:
            self.flipped_box.setEnabled(bool(self.walked_combo.currentData()))
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise; the status line reports
            self.status.setText(f"could not update the setup: {exc}")

    # ---- the rows ----------------------------------------------------------
    def add_files(self, paths: list[Path]) -> None:
        """Add files to the table. An unreadable one goes to the status line instead."""
        error = ""
        for path in paths:
            path = Path(path)
            if any(r.path == path for r in self._rows):
                continue
            try:
                probe = MagFile.open(path, "", MagSetup())
            except (MagFileError, OSError) as exc:
                error = f"Could not read {path.name}: {exc}"
                continue
            self._rows.append(_Row(path, probe.n_rows, probe.n_readings))
            self._append_table_row()
        self._take_free_grids()
        self._refresh()
        if error:
            self.status.setText(error)

    def _append_table_row(self) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        for col in (COL_FILE, COL_SIZE, COL_MISSING, COL_FITS):
            self.table.setItem(r, col, QTableWidgetItem(""))
        combo = QComboBox()
        self._fill_combo(combo, None)
        combo.currentIndexChanged.connect(lambda _i, c=combo: self._on_row_grid_changed(c))
        self._combos.append(combo)
        self.table.setCellWidget(r, COL_GRID, combo)

    def _grids(self) -> list[str]:
        """The mag grid ids, in site order; none once the site has changed."""
        if not self._same_site():
            return []
        return [g.id for g in self.session.mag_grids()]

    def _same_site(self) -> bool:
        return self.session.is_open and self.session.site is self._site

    def _fill_combo(self, combo: QComboBox, keep: str | None) -> None:
        was = combo.blockSignals(True)
        combo.clear()
        combo.addItem(_NONE, None)
        for gid in self._grids():
            combo.addItem(gid, gid)
        combo.setCurrentIndex(max(0, combo.findData(keep)))
        combo.blockSignals(was)

    def row_grid(self, row: int) -> str | None:
        return self._combos[row].currentData()

    def set_row_grid(self, row: int, grid_id: str | None) -> None:
        combo = self._combos[row]
        combo.setCurrentIndex(max(0, combo.findData(grid_id)))

    def _on_row_grid_changed(self, _combo: QComboBox) -> None:
        try:
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise; the status line reports
            self.status.setText(f"could not update the table: {exc}")

    def _on_grids_changed(self) -> None:
        try:
            for combo in self._combos:
                self._fill_combo(combo, combo.currentData())
            self._take_free_grids()
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise; the status line reports
            self.status.setText(f"could not refresh the grids: {exc}")

    def _take_free_grids(self) -> None:
        """Each row without a grid takes the next free one: the one the dialog was pointed
        at, then the first in site order that holds no file and is not another row's."""
        grids = self._grids()
        for i, combo in enumerate(self._combos):
            if combo.currentData() is not None:
                continue
            taken = {c.currentData() for c in self._combos}
            free = [g for g in grids if g not in taken and self.session.mag_file_on(g) is None]
            if self._prefer in grids and self._prefer not in taken:
                free.insert(0, self._prefer)
            if free:
                self.set_row_grid(i, free[0])

    def retarget(self, grid_id: str | None) -> None:
        """Point the dialog at `grid_id` for files added next; a half-built list is never moved."""
        if not self._rows:
            self._prefer = grid_id

    # ---- the table ---------------------------------------------------------
    def _setup_or_none(self) -> tuple[MagSetup | None, str]:
        try:
            return self.setup(), ""
        except ValueError as exc:
            return None, str(exc)

    def _refresh(self) -> None:
        setup, error = self._setup_or_none()
        if setup is None:
            self.picture.set_error(error)
        else:
            self.picture.set_setup(setup)
        grid_ids = self._grids()
        for i, row in enumerate(self._rows):
            self.table.item(i, COL_FILE).setText(row.path.name)
            self.table.item(i, COL_SIZE).setText(f"{row.n_rows} × {row.n_readings}")
            missing = self.table.item(i, COL_MISSING)
            fits = self.table.item(i, COL_FITS)
            if setup is None:
                missing.setText(_NONE)
                fits.setText(_NONE)
                fits.setToolTip("")
                continue
            try:
                n_missing = int(np.isnan(MagFile.open(row.path, "", setup).readings()).sum())
                missing.setText(str(n_missing))
            except (MagFileError, OSError):
                missing.setText(_NONE)
            problems = self._problems(i, setup) if self.row_grid(i) in grid_ids else None
            if problems is None:
                fits.setText(_NONE)
                fits.setToolTip("")
            else:
                fits.setText(problems[0] if problems else "yes")
                fits.setToolTip("\n".join(problems))
        self.status.setText(error or self._duplicate_grid() or "")

    def _problems(self, i: int, setup: MagSetup) -> list[str]:
        row = self._rows[i]
        grid = self.session.grid(self.row_grid(i))
        return fit_problems(setup, row.n_rows, row.n_readings, grid)

    def _duplicate_grid(self) -> str:
        seen: dict[str, str] = {}
        for i, row in enumerate(self._rows):
            gid = self.row_grid(i)
            if gid is None:
                continue
            if gid in seen:
                return (
                    f"{seen[gid]} and {row.path.name} are both on grid {gid}; "
                    "a mag grid holds one file."
                )
            seen[gid] = row.path.name
        return ""

    # ---- buttons -----------------------------------------------------------
    def _pick_files(self) -> None:
        try:
            start = str(self.session.root) if self._same_site() else ""
            names, _ = QFileDialog.getOpenFileNames(
                self, "Add magnetometer files", start, FILE_FILTER
            )
            if names:
                self.add_files([Path(n) for n in names])
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise; the status line reports
            self.status.setText(f"could not add the files: {exc}")

    def _request_new_grid(self) -> None:
        try:
            self.new_grid_requested.emit()
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise; the status line reports
            self.status.setText(f"could not open the grid dialog: {exc}")

    # ---- accept ------------------------------------------------------------
    def accept(self) -> None:
        try:
            self._import()
        except Exception as exc:  # noqa: BLE001 -- accept is reached from a button signal; report
            self.status.setText(f"could not import: {exc}")

    def _import(self) -> None:
        if not self._same_site():
            self.status.setText("The site changed; nothing was imported.")
            return
        setup, error = self._setup_or_none()
        if setup is None:
            self.status.setText(error)
            return
        for i, row in enumerate(self._rows):
            if self.row_grid(i) is None:
                self.status.setText(f"Choose a mag grid for {row.path.name}.")
                return
        duplicate = self._duplicate_grid()
        if duplicate:
            self.status.setText(duplicate)
            return
        if not self._rows:
            self.status.setText("Add a file to import.")
            return
        misfits = []
        for i, row in enumerate(self._rows):
            misfits += [f"{row.path.name}: {p}" for p in self._problems(i, setup)]
        if misfits:
            n_files = len({line.split(": ", 1)[0] for line in misfits})
            text = (
                f"{n_files} file(s) do not fit their grids:\n"
                + "\n".join(misfits)
                + "\nImport anyway? Nothing is cropped or stretched."
            )
            if not self._ask("Files do not fit their grids", text):
                return
        replaced = []
        for i, row in enumerate(self._rows):
            old = self.session.mag_file_on(self.row_grid(i))
            if old is not None:
                replaced.append(f"{old.grid_id}: {old.path.name} → {row.path.name}")
        if replaced:
            text = "Replace the files already on these grids?\n" + "\n".join(replaced)
            if not self._ask("Replace files", text):
                return
        try:
            mags = [MagFile.open(r.path, self.row_grid(i), setup) for i, r in enumerate(self._rows)]
            self.session.remember_mag_setup(setup)
            done = []
            for mag in mags:
                self.session.set_mag_file(mag)
                done.append(
                    (self.session.mag_key(mag), mag.grid_id, missing_summary(mag.readings()))
                )
        except (MagFileError, OSError, ValueError) as exc:
            self.status.setText(str(exc))
            return
        self.imported.emit(done)
        super().accept()

    def _ask(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
