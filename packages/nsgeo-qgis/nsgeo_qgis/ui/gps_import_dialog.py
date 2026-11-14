"""Import GPS lines: DZT files with a DZG beside them, each placed along its
RTK track (M17a, #134; P10, P11).

Modeless and single-instance, shaped like ImportDialog (plugin.py's
open_gps_import_dialog is the pattern; read the module docstring there for
why every slot guards its own body). Nothing here needs a grid.

Rows are planned when files are added, and again whenever the set of files
changes, because the first readable file decides the coordinates when the
site has none (the CRS rule, `crs_rule.choose_crs`). The Destagger box applies
to every ready row at Import. Import re-checks that it is still looking at the
site it was opened against, since the toolbar and the Survey panel stay
clickable while it is open.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from nsgeo.geometry import END_LIMIT_M
from nsgeo.project import ProjectError, line_key
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsPointXY,
    QgsProject,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.crs_rule import choose_crs, usable_at
from nsgeo_qgis.gps_import import (
    ALREADY_IN_SITE,
    GpsRow,
    first_fixed_lonlat,
    import_messages,
    plan_gps_rows,
    shifted_lines,
)
from nsgeo_qgis.lookup import sort_files
from nsgeo_qgis.session import SiteSession

COL_FILE, COL_TRACES, COL_FIXES, COL_GAP, COL_ENDS, COL_STATUS = range(6)
HEADERS = ["File", "Traces", "RTK fixes", "Without RTK", "Ends", "Status"]
FILE_FILTER = "GSSI radar files (*.dzt *.DZT)"
SHIFT_TIP = (
    "Moves every trace forward along the way its line was walked, for every line in "
    "this import. Change it per line later from the Survey panel."
)
EMPTY_STATUS = "Add DZT files that have a DZG beside them."
# The mockup's cues (Checkpoint C1): amber for a ready row worth a look, red
# for a refused one.
FLAG_BG, FLAG_FG = "#fbf3df", "#8a5a00"
OUT_BG, OUT_FG = "#fbe9e7", "#a12a1e"
SITE_CHANGED = "The site changed; nothing was imported."


def lonlat_to_xy(crs: QgsCoordinateReferenceSystem) -> Any:
    """A `to_xy(lon, lat)` for the core: EPSG:4326 to `crs`, point by point.
    NaN stays NaN, and so does a point the transform cannot place."""
    xform = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:4326"), crs, QgsProject.instance()
    )

    def to_xy(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        lon = np.asarray(lon, dtype=float)
        lat = np.asarray(lat, dtype=float)
        xs = np.full(lon.shape, np.nan)
        ys = np.full(lon.shape, np.nan)
        for i, (lo, la) in enumerate(zip(lon.tolist(), lat.tolist())):
            if not (math.isfinite(lo) and math.isfinite(la)):
                continue
            try:
                p = xform.transform(QgsPointXY(lo, la))
            except QgsCsException:
                continue
            xs[i], ys[i] = p.x(), p.y()
        return xs, ys

    return to_xy


class GpsImportDialog(QDialog):
    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        # Which site accept() may write into (see the module docstring).
        self._opened_against = session.json_path
        self.paths: list[Path] = []
        self.rows: list[GpsRow] = []
        self.imported_keys: list[str] = []
        self.messages: list[str] = []
        self._crs: QgsCoordinateReferenceSystem = QgsProject.instance().crs()
        self._note = ""
        self.setWindowTitle("Import GPS lines")
        self.resize(900, 420)
        layout = QVBoxLayout(self)

        buttons_row = QHBoxLayout()
        self.add_button = QPushButton("Add files…")
        self.add_button.clicked.connect(self._choose_files)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_selected)
        buttons_row.addWidget(self.add_button)
        buttons_row.addWidget(self.remove_button)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        form = QFormLayout()
        self.shift = QDoubleSpinBox()
        self.shift.setRange(-2.0, 2.0)
        self.shift.setDecimals(2)
        self.shift.setSingleStep(0.01)
        self.shift.setValue(0.0)
        self.shift.setToolTip(SHIFT_TIP)
        shift_note = QLabel(SHIFT_TIP)
        shift_note.setStyleSheet("color: gray;")
        shift_note.setWordWrap(True)
        shift_row = QHBoxLayout()
        shift_row.addWidget(self.shift)
        shift_row.addWidget(shift_note, 1)
        form.addRow("Destagger (m)", shift_row)
        self.crs_label = QLabel("")
        self.note_label = QLabel("")
        self.note_label.setStyleSheet("color: gray;")
        crs_row = QHBoxLayout()
        crs_row.addWidget(self.crs_label)
        crs_row.addWidget(self.note_label, 1)
        form.addRow("Coordinates:", crs_row)
        layout.addLayout(form)

        self.status = QLabel(EMPTY_STATUS)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.import_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.import_button.setText("Import")
        self.import_button.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.buttons)
        layout.addLayout(footer)
        self._decide_crs()  # the coordinates the import will use, before any file
        self._refresh()

    # ---- the site -------------------------------------------------------------
    def _site_crs(self) -> str | None:
        try:
            return self.session.site_crs()
        except ProjectError:
            return None

    def _taken_keys(self) -> set[str]:
        try:
            return set(self.session.keys())
        except ProjectError:
            return set()

    def _same_site(self) -> bool:
        return self.session.is_open and self.session.json_path == self._opened_against

    # ---- rows -----------------------------------------------------------------
    def _choose_files(self) -> None:
        try:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Select DZT files", "", FILE_FILTER + ";;All files (*)"
            )
            if paths:
                self.add_files([Path(p) for p in paths])
        except Exception as exc:  # noqa: BLE001 -- a slot (clicked): see plugin.py's module docstring
            self.status.setText(f"could not add the files: {exc}")

    def add_files(self, paths: list[Path]) -> None:
        known = {p.resolve() for p in self.paths}
        fresh: list[Path] = []
        for p in paths:
            resolved = Path(p).resolve()
            if resolved not in known:
                known.add(resolved)
                fresh.append(Path(p))
        if fresh:
            self.paths = sort_files([*self.paths, *fresh])
            self._replan()

    def remove_selected(self) -> None:
        try:
            gone = {i.row() for i in self.table.selectedIndexes()}
            if gone:
                self.paths = [p for i, p in enumerate(self.paths) if i not in gone]
                self._replan()
        except Exception as exc:  # noqa: BLE001 -- a slot (clicked): see plugin.py's module docstring
            self.status.setText(f"could not remove the files: {exc}")

    def _decide_crs(self) -> None:
        """The CRS rule: the site's, else chosen at the first readable file's first RTK fix."""
        project = QgsProject.instance().crs()
        site_authid = self._site_crs()
        site = None if site_authid is None else QgsCoordinateReferenceSystem(site_authid)
        lonlat = None
        for p in self.paths:
            lonlat = first_fixed_lonlat(p)
            if lonlat is not None:
                break
        if site is not None:
            self._crs, self._note = site, ""
            if lonlat is not None:
                chosen, note = choose_crs(
                    site, project, QgsPointXY(*lonlat), site_has_grids=self._site_has_grids()
                )
                if chosen == site:
                    self._note = note
        elif lonlat is not None:
            self._crs, self._note = choose_crs(None, project, QgsPointXY(*lonlat))
        else:
            self._crs, self._note = project, ""

    def _site_has_grids(self) -> bool:
        site = self.session.site
        return bool(site and site.grids)

    def _replan(self) -> None:
        self._decide_crs()
        crs = self._crs
        taken = self._taken_keys()
        root = self.session.root if self.session.is_open else None

        def is_taken(path: Path) -> bool:
            return root is not None and line_key(path, root, allow_absolute=True) in taken

        def usable(lon: float, lat: float) -> bool:
            return usable_at(crs, QgsPointXY(lon, lat))[0] is None

        self.rows = plan_gps_rows(self.paths, lonlat_to_xy(crs), crs.authid(), is_taken, usable)
        self._refresh()

    # ---- table ----------------------------------------------------------------
    @property
    def n_ready(self) -> int:
        return sum(1 for r in self.rows if r.refusal is None)

    def _refresh(self) -> None:
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            ready = row.refusal is None
            # A refused row that was planned anyway (already in the site)
            # still shows what its file holds.
            planned = ready or row.refusal == ALREADY_IN_SITE
            long_end = max(row.end_runs) > END_LIMIT_M
            values = {
                COL_FILE: row.path.name,
                COL_TRACES: "—" if row.n_traces is None else str(row.n_traces),
                COL_FIXES: f"{row.n_fixed} of {row.n_fixes}" if row.n_fixes else "—",
                COL_GAP: f"{row.without_rtk_m:.1f} m" if planned and row.bridges else "—",
                COL_ENDS: f"{row.end_runs[0]:.2f} / {row.end_runs[1]:.2f} m" if planned else "—",
                COL_STATUS: "ready" if ready else (row.refusal or ""),
            }
            flagged = {COL_GAP: bool(row.bridges) and planned, COL_ENDS: long_end and planned}
            for col, text in values.items():
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == COL_TRACES:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if col == COL_STATUS and not ready:
                    item.setToolTip(text)
                    item.setBackground(QBrush(QColor(OUT_BG)))
                    item.setForeground(QBrush(QColor(OUT_FG)))
                elif flagged.get(col):
                    item.setBackground(QBrush(QColor(FLAG_BG)))
                    item.setForeground(QBrush(QColor(FLAG_FG)))
                self.table.setItem(r, col, item)
        self.table.resizeColumnsToContents()
        self.crs_label.setText(self._crs.authid())
        self.note_label.setText(self._note)
        n = self.n_ready
        self.import_button.setEnabled(n > 0)
        if not self.rows:
            self.status.setText(EMPTY_STATUS)
        else:
            self.status.setText(f"{n} of {len(self.rows)} file(s) ready to import.")

    # ---- accept ---------------------------------------------------------------
    def accept(self) -> None:
        # Reached from buttons.accepted (a signal) as well as called
        # directly, so every failure reports through `status` and returns.
        try:
            self._accept()
        except Exception as exc:  # noqa: BLE001 -- a slot: see plugin.py's module docstring
            self.status.setText(f"could not import: {exc}")

    def _accept(self) -> None:
        if not self._same_site():
            self.status.setText(SITE_CHANGED)
            return
        if self.n_ready == 0:
            self.status.setText("Nothing to import: no file is ready.")
            return
        in_force = self._site_crs()
        if in_force is not None and in_force != self._crs.authid():
            # A grid arrived while the dialog was open and the site now has a
            # CRS of its own: plan again in it, and let the user look.
            self._replan()
            self.status.setText(
                f"The site's coordinates are now {in_force}; the table was planned again. "
                + self.status.text()
            )
            return
        # Built from the planned rows, never re-read here: a file that went
        # unreadable since planning must not leave the site pinned with no lines.
        lines = shifted_lines(self.rows, self.shift.value())
        if in_force is None:
            self.session.set_site_crs(self._crs.authid())
        try:
            self.session.add_lines(lines)
        except ValueError as exc:  # a key already in the site, or a CRS mismatch
            self.status.setText(str(exc))
            return
        self.imported_keys = [self.session.line_key(ln) for ln in lines]
        self.messages = import_messages(self.rows, len(lines))
        super().accept()
