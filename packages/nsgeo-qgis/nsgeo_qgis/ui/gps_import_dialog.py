"""The GPS page of Add data: DZT files with a DZG beside them, each placed along
its RTK track (M17a, #134; P10, P11) and put into a grid (M17b): an existing
one, or a new one the page fits around the tracks and names (the Target grid
combo's first entry). AddDataDialog owns the window, the switch, the buttons
and the map preview of a new grid; read plugin.py's module docstring for why
every slot guards its own body.

Rows are planned when files are added, and again whenever the set of files
changes, because the first readable file decides the coordinates when the
site has none (the CRS rule, `crs_rule.choose_crs`). The Destagger box applies
to every ready row at Import. Import re-checks that it is still looking at the
site it was opened against, and that its target grid (or a grid of the typed
name) is still what it was, since the toolbar and the Survey panel stay
clickable while it is open. Import makes the new grid and adds the lines in
one step, and takes the grid away again if adding the lines fails.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any

import numpy as np
from nsgeo.geometry import (
    END_LIMIT_M,
    Grid,
    fit_frame,
    main_direction,
    measure_spacing,
    metres_outside,
)
from nsgeo.project import ProjectError, line_key
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsPointXY,
    QgsProject,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.crs_rule import choose_crs, usable_at
from nsgeo_qgis.gps_import import (
    ALREADY_IN_SITE,
    OUTSIDE,
    OUTSIDE_NOTE_M,
    GpsImportResult,
    GpsRow,
    first_fixed_lonlat,
    import_messages,
    plan_gps_rows,
    shifted_lines,
    with_grid,
)
from nsgeo_qgis.lookup import sort_files
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.preset_box import PRESET_GONE, PresetBox

COL_FILE, COL_TRACES, COL_FIXES, COL_GAP, COL_ENDS, COL_STATUS = range(6)
HEADERS = ["File", "Traces", "RTK fixes", "Without RTK", "Ends", "Status"]
#: With an existing target grid the Outside column sits before Status.
COL_OUTSIDE, COL_STATUS_OUTSIDE = 5, 6
OUTSIDE_HEADER = "Outside {gid}"
NEW_GRID = "New grid"
OUTSIDE_CRS_PREFIX = "outside what "  # gps_import: "outside what {crs} can place"
NAME_FIRST = "Name the new grid."
NAME_TAKEN = "A grid named {name} already exists."
SPACING_FIRST = "Give the new grid a spacing."
SPACING_MEASURED = "measured from the tracks; type over it if it is wrong"
SPACING_ONE = "type one: one line gives nothing to measure it from"
SPACING_NO_DIRECTION = "type one: these lines share no direction to measure it along"
FITTED_LINED_UP = (
    "{w:.1f} × {l:.1f} m, azimuth {a:.1f}°, lined up with the lines, holding every trace"
)
FITTED_TIP = (
    "Lined up: turned to the direction the lines share, its sides half a spacing outside the "
    "outer lines (further where a line wanders past that) and its ends at the furthest traces, "
    "so every trace is inside. Lines that share no direction get the smallest rectangle around "
    "every trace, half a spacing outside it."
)
FITTED_SMALLEST = (
    "{w:.1f} × {l:.1f} m, azimuth {a:.1f}°, the smallest rectangle around them; "
    "these lines share no direction"
)
GRID_LOST = "grid {gid!r} no longer exists; nothing was imported"

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


class GpsImportPage(QWidget):
    #: The title, the Import button's text or its enabled state may have moved.
    changed = pyqtSignal()

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        # Which site accept() may write into (see the module docstring).
        self._opened_against = session.json_path
        self._paths: list[Path] = []
        self._planned: list[GpsRow] = []  # every file, planned in the CRS, before the target
        self.rows: list[GpsRow] = []  # the planned rows judged against the target grid
        self.imported_keys: list[str] = []
        #: What the last import_lines() did, for the hand-on to the Grid page.
        self.last_import: GpsImportResult | None = None
        self._lost: str | None = None  # the chosen grid, removed under the page
        self._spacing_own = False  # the user typed a spacing: stop following the tracks
        self._measured: float | None = None
        self._proposal: Grid | None = None
        self._outside: dict[Path, float] = {}  # metres outside the target, ready rows
        self._outside_all: dict[Path, float] = {}  # the same for every placed row
        self._frame_lined_up = False
        self._refilling = 0
        #: What the last import_lines() has to say: (text, is_warning).
        self.messages: list[tuple[str, bool]] = []
        self._crs: QgsCoordinateReferenceSystem = QgsProject.instance().crs()
        self._note = ""
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

        form = self._form = QFormLayout()
        self.target_combo = QComboBox()
        self._fill_target_combo()
        form.addRow("Target grid", self.target_combo)
        self.name_edit = QLineEdit()
        form.addRow("Name", self.name_edit)
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(0.0, 100.0)
        self.spacing.setDecimals(3)
        self.spacing.setSingleStep(0.05)
        self.spacing.setSpecialValueText("—")
        self.spacing_note = QLabel("")
        self.spacing_note.setStyleSheet("color: gray;")
        self.spacing_note.setWordWrap(True)
        self._spacing_box = QWidget()
        spacing_row = QHBoxLayout(self._spacing_box)
        spacing_row.setContentsMargins(0, 0, 0, 0)
        spacing_row.addWidget(self.spacing)
        spacing_row.addWidget(self.spacing_note, 1)
        form.addRow("Spacing (m)", self._spacing_box)
        self.fitted = QLabel("—")
        self.fitted.setWordWrap(True)
        self.fitted.setToolTip(FITTED_TIP)
        form.addRow("Fitted", self.fitted)
        # QFormLayout.setRowVisible does not exist on Qt 5: hide label and field together.
        self._new_grid_fields = (self.name_edit, self._spacing_box, self.fitted)
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
        self.preset_box = PresetBox(session)  # #129
        self.preset_box.set_grid(None, new=True)
        form.addRow("Processing preset", self.preset_box)
        self.crs_label = QLabel("")
        self.note_label = QLabel("")
        self.note_label.setStyleSheet("color: gray;")
        crs_row = QHBoxLayout()
        crs_row.addWidget(self.crs_label)
        crs_row.addWidget(self.note_label, 1)
        form.addRow("Coordinates:", crs_row)
        layout.addLayout(form)

        self.status = QLabel(EMPTY_STATUS)
        layout.addWidget(self.status)
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        self.target_combo.activated.connect(self._picked)
        self.name_edit.textChanged.connect(self._name_changed)
        self.spacing.valueChanged.connect(self._spacing_typed)
        session.grids_changed.connect(self._on_grids_changed)
        self._decide_crs()  # the coordinates the import will use, before any file
        self._apply_target()
        self._refresh()

    # ---- the page's face to the dialog ----------------------------------------
    def target(self) -> str | None:
        """The existing grid the lines go into; None for New grid."""
        return self.target_combo.currentData() or None

    def proposal(self) -> Grid | None:
        """The grid Import would make (None for an existing target, or while it cannot)."""
        return self._proposal if self.target() is None else None

    def _name(self) -> str:
        return self.name_edit.text().strip()

    def _where(self) -> str:
        """The target in the title and button: `{gid}`, `new grid {name}`, `a new grid`."""
        gid = self.target()
        if gid is not None:
            return gid
        name = self._name()
        return f"new grid {name}" if name else "a new grid"

    def title(self) -> str:
        return f"Add GPR data into {self._where()}"

    def import_text(self) -> str:
        return f"Import {self.n_ready} line(s) into {self._where()}"

    def _grid_ids(self) -> list[str]:
        try:
            return [g.id for g in self.session.site.grids] if self.session.site else []
        except ProjectError:
            return []

    def _name_problem(self) -> str | None:
        """Why the typed name will not do (New grid only), or None."""
        name = self._name()
        if not name:
            return NAME_FIRST
        if name in self._grid_ids():
            return NAME_TAKEN.format(name=name)
        return None

    def can_import(self) -> bool:
        if self.n_ready == 0:
            return False
        if self.target() is None:
            return self._name_problem() is None and self._proposal is not None
        return True

    def paths(self) -> list[Path]:
        return list(self._paths)

    def set_files(self, paths: list[Path]) -> None:
        """Make the page hold exactly `paths` (rows are planned afresh, they hold
        no edits). No-op when the same files are here already."""
        if {Path(p).resolve() for p in paths} == {p.resolve() for p in self._paths}:
            return
        self._paths = sort_files(list(paths))
        self._replan()

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
        known = {p.resolve() for p in self._paths}
        fresh: list[Path] = []
        for p in paths:
            resolved = Path(p).resolve()
            if resolved not in known:
                known.add(resolved)
                fresh.append(Path(p))
        if fresh:
            self._paths = sort_files([*self._paths, *fresh])
            self._replan()

    def remove_selected(self) -> None:
        try:
            gone = {i.row() for i in self.table.selectedIndexes()}
            if gone:
                self._paths = [p for i, p in enumerate(self._paths) if i not in gone]
                self._replan()
        except Exception as exc:  # noqa: BLE001 -- a slot (clicked): see plugin.py's module docstring
            self.status.setText(f"could not remove the files: {exc}")

    def _decide_crs(self) -> None:
        """The CRS rule: the site's, else chosen at the first readable file's first RTK fix."""
        project = QgsProject.instance().crs()
        site_authid = self._site_crs()
        site = None if site_authid is None else QgsCoordinateReferenceSystem(site_authid)
        lonlat = None
        for p in self._paths:
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

        self._planned = plan_gps_rows(
            self._paths, lonlat_to_xy(crs), crs.authid(), is_taken, usable
        )
        self._apply_target()
        self._refresh()

    # ---- the target grid ------------------------------------------------------
    def _fill_target_combo(self) -> None:
        self.target_combo.clear()
        self.target_combo.addItem(NEW_GRID, "")
        for gid in self._grid_ids():
            self.target_combo.addItem(gid, gid)

    def retarget(self, grid_id: str) -> None:
        """Point the page at an existing grid (a no-op if it is not in the list)."""
        index = self.target_combo.findData(grid_id)
        if index >= 0:
            self._lost = None
            self.target_combo.setCurrentIndex(index)

    def _picked(self, *_: Any) -> None:
        # A slot (activated): the user chose, so a lost grid is forgotten.
        try:
            self._lost = None
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot (activated): see plugin.py's module docstring
            self.status.setText(f"could not change the target: {exc}")

    def _target_changed(self, *_: Any) -> None:
        # A slot (currentIndexChanged): guarded, see plugin.py's module docstring.
        try:
            if self._refilling:
                return
            gid = self.target()
            if gid is None:
                self.preset_box.set_grid(self._name() or None, new=True)
            else:
                self.preset_box.set_grid(gid)
            self._apply_target()
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot
            self.status.setText(f"could not change the target: {exc}")

    def _name_changed(self, *_: Any) -> None:
        try:
            # Typing a name is choosing New grid: a target grid that went is
            # forgotten, and Import goes into the new grid.
            self._lost = None
            self.preset_box.rename_new_grid(self._name() or None)
            # Only the name changed: the tracks, spacing and fit stand, so the
            # proposal is renamed and nothing is measured or fitted again.
            if self._proposal is not None:
                self._proposal = dataclasses.replace(self._proposal, id=self._name() or "_")
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot
            self.status.setText(f"could not use the name: {exc}")

    def _spacing_typed(self, *_: Any) -> None:
        # valueChanged is only ever emitted by the user: _apply_target sets the
        # measured value with the signals blocked.
        try:
            self._spacing_own = True
            self._apply_target()
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot
            self.status.setText(f"could not use the spacing: {exc}")

    def _on_grids_changed(self) -> None:
        # A slot (session.grids_changed): the list follows the site; a chosen
        # grid that went is remembered in `_lost` so Import refuses.
        try:
            before = self.target()
            self._refilling += 1
            try:
                self._fill_target_combo()
                index = self.target_combo.findData(before) if before else 0
                self.target_combo.setCurrentIndex(max(index, 0))
            finally:
                self._refilling -= 1
            if before and self.target() != before:
                self._lost = before
            if self.target() != before:
                self.preset_box.set_grid(self._name() or None, new=True)
            self._apply_target()
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot
            self.status.setText(f"could not refresh the grids: {exc}")

    def _target_grid(self) -> Grid | None:
        gid = self.target()
        if gid is None:
            return None
        try:
            return self.session.grid(gid)
        except (KeyError, ProjectError):
            return None

    def _judged(self) -> tuple[list[GpsRow], dict[Path, float], dict[Path, float]]:
        """The planned rows against the target grid: (rows, outside for the
        ready ones, outside for every placed one). New grid: the rows as planned."""
        grid = self._target_grid()
        if grid is None:
            return list(self._planned), {}, {}
        every: dict[Path, float] = {}
        any_inside: dict[Path, bool] = {}
        for r in self._planned:
            if r.line is not None:
                every[r.path], any_inside[r.path] = metres_outside(grid, r.line.trace_coords({}))
        rows, outside = with_grid(self._planned, grid, measured=(every, any_inside))
        return rows, outside, every

    def _apply_target(self) -> None:
        """Judge the rows against the target, and for New grid measure, fit and
        propose. Draws nothing: `_refresh` does."""
        self.rows, self._outside, self._outside_all = self._judged()
        self._proposal = None
        new = self.target() is None
        for w in self._new_grid_fields:
            w.setVisible(new)
            label = self._form.labelForField(w)
            if label is not None:
                label.setVisible(new)
        if not new:
            return
        tracks = [r.line.trace_coords({}) for r in self.rows if r.line is not None]
        self._measured = measure_spacing(tracks) if tracks else None
        if not self._spacing_own:
            self.spacing.blockSignals(True)
            try:
                self.spacing.setValue(0.0 if self._measured is None else self._measured)
            finally:
                self.spacing.blockSignals(False)
        if self._spacing_own or not tracks:
            note = ""
        elif self._measured is not None:
            note = SPACING_MEASURED
        elif main_direction(tracks) is None:
            note = SPACING_NO_DIRECTION
        else:
            note = SPACING_ONE
        self.spacing_note.setText(note)
        spacing = self.spacing.value()
        if tracks and spacing > 0.0:
            try:
                frame = fit_frame(tracks, spacing)
                self._proposal = frame.as_grid(self._name() or "_", self._crs.authid(), spacing)
                fmt = FITTED_LINED_UP if frame.lined_up else FITTED_SMALLEST
                self.fitted.setText(fmt.format(w=frame.size_x, l=frame.size_y, a=frame.azimuth))
                return
            except ValueError:
                pass
        self.fitted.setText("—")

    # ---- table ----------------------------------------------------------------
    @property
    def n_ready(self) -> int:
        return sum(1 for r in self.rows if r.refusal is None)

    def _refresh(self) -> None:
        existing = self.target()
        status_col = COL_STATUS_OUTSIDE if existing else COL_STATUS
        headers = list(HEADERS)
        if existing:
            headers.insert(COL_OUTSIDE, OUTSIDE_HEADER.format(gid=existing))
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            ready = row.refusal is None
            # A refused row that was planned anyway (already in the site, or
            # outside the grid) still shows what its file holds.
            outside_refusal = existing is not None and row.refusal == OUTSIDE.format(gid=existing)
            planned = ready or row.refusal == ALREADY_IN_SITE or outside_refusal
            long_end = max(row.end_runs) > END_LIMIT_M
            values = {
                COL_FILE: row.path.name,
                COL_TRACES: "—" if row.n_traces is None else str(row.n_traces),
                COL_FIXES: f"{row.n_fixed} of {row.n_fixes}" if row.n_fixes else "—",
                COL_GAP: f"{row.without_rtk_m:.1f} m" if planned and row.bridges else "—",
                COL_ENDS: f"{row.end_runs[0]:.2f} / {row.end_runs[1]:.2f} m" if planned else "—",
                status_col: "ready" if ready else (row.refusal or ""),
            }
            flagged = {COL_GAP: bool(row.bridges) and planned, COL_ENDS: long_end and planned}
            if existing:
                metres = self._outside.get(row.path, 0.0)
                if outside_refusal:
                    values[COL_OUTSIDE] = f"all {self._outside_all.get(row.path, 0.0):.1f} m"
                elif metres >= OUTSIDE_NOTE_M:
                    values[COL_OUTSIDE] = f"{metres:.1f} m"
                    flagged[COL_OUTSIDE] = True
                else:
                    values[COL_OUTSIDE] = "—"
            for col, text in values.items():
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == COL_TRACES:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if (col == status_col and not ready) or (col == COL_OUTSIDE and outside_refusal):
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
        if not self.rows:
            self.status.setText(EMPTY_STATUS)
        elif n and existing is None and (problem := self._name_problem()) is not None:
            self.status.setText(problem)
        elif n and existing is None and self._proposal is None and self.spacing.value() <= 0.0:
            self.status.setText(SPACING_FIRST)
        else:
            self.status.setText(f"{n} of {len(self.rows)} file(s) ready to import.")
        self.changed.emit()

    # ---- import ---------------------------------------------------------------
    def import_lines(self) -> bool:
        """The old accept(): True once the lines were added. Every failure
        reports through `status` and returns False."""
        try:
            return self._import()
        except Exception as exc:  # noqa: BLE001 -- AddDataDialog.accept() is a slot: see plugin.py's module docstring
            self.status.setText(f"could not import: {exc}")
            return False

    def _import(self) -> bool:
        if not self._same_site():
            self.status.setText(SITE_CHANGED)
            return False
        gid = self.target()
        if self._lost is not None:
            self.status.setText(GRID_LOST.format(gid=self._lost))
            return False
        existing = self._target_grid()
        if gid is not None and existing is None:
            self.status.setText(GRID_LOST.format(gid=gid))
            return False
        in_force = self._site_crs()
        if in_force is not None and in_force != self._crs.authid():
            # A grid arrived while the dialog was open and the site now has a
            # CRS of its own: plan again in it, and let the user look.
            self._replan()
            self.status.setText(
                f"The site's coordinates are now {in_force}; the table was planned again. "
                + self.status.text()
            )
            return False
        # The grid may have been edited or the typed name taken since the table
        # was drawn: judge the planned rows again, right now.
        self._apply_target()
        self._refresh()
        if self.n_ready == 0:
            self.status.setText("Nothing to import: no file is ready.")
            return False
        new_grid: Grid | None = None
        if gid is None:
            problem = self._name_problem()
            if problem is not None:
                self.status.setText(problem)
                return False
            if self._proposal is None:
                self.status.setText(
                    SPACING_FIRST
                    if self.spacing.value() <= 0.0
                    else "Could not fit a grid around these tracks."
                )
                return False
            new_grid = dataclasses.replace(self._proposal, id=self._name())
            target_id = new_grid.id
        else:
            target_id = gid
        # Built from the planned rows, never re-read here: a file that went
        # unreadable since planning must not leave the site pinned with no lines.
        lines = shifted_lines(self.rows, self.shift.value(), grid_id=target_id)
        chosen = self.preset_box.chosen()
        if chosen is not None and chosen not in self.session.preset_names():
            self.status.setText(PRESET_GONE.format(name=chosen))
            return False
        new_keys = [self.session.line_key(ln) for ln in lines]
        taken = set(self.session.keys())
        clash = [k for k in new_keys if k in taken]
        if clash:
            self.status.setText(f"line {clash[0]!r} is already in the site")
            return False
        # No set_site_crs here: a new grid gives the site its CRS (add_grid) and
        # add_lines pins site.crs itself, so a rollback leaves nothing pinned.
        if new_grid is not None:
            try:
                self.session.add_grid(new_grid)
            except ValueError as exc:  # a grid of that id arrived meanwhile
                self.status.setText(str(exc))
                return False
        # §2.4: a grid's first lines also set its Slices preset, written
        # before the lines so they are prepared once.
        sets_slices = False
        try:
            sets_slices = chosen is not None and self.session.import_sets_slice_preset(target_id)
            if sets_slices:
                self.session.set_slice_preset(target_id, chosen)
            self.session.add_lines(lines)
        except Exception as exc:  # noqa: BLE001 -- undo what this import did, then say why
            self._undo(target_id, sets_slices, new_grid is not None)
            self.status.setText(str(exc))
            return False
        self.imported_keys = new_keys  # the lines are in the site whatever follows
        into = target_id
        if new_grid is not None:
            into = (
                f"new grid {target_id} ({new_grid.size_x:.1f} × {new_grid.size_y:.1f} m, "
                f"spacing {new_grid.default_spacing:.2f} m)"
            )
        leftovers = [
            r.path
            for r in self.rows
            if r.refusal is not None
            and r.refusal != ALREADY_IN_SITE
            and r.refusal != OUTSIDE.format(gid=target_id)
            # decision 15: only files GPS cannot place are handed on; a position
            # the site's CRS cannot place stays "not imported"
            and not r.refusal.startswith(OUTSIDE_CRS_PREFIX)
            # a DZT that could not be read has no trace count: a Grid-mode row
            # could never import it, so it stays in the summary as "not imported"
            and r.n_traces is not None
        ]
        self.messages = [
            (t, i > 0)
            for i, t in enumerate(
                import_messages(
                    self.rows,
                    len(lines),
                    into=into,
                    gid=target_id,
                    outside=self._outside,
                    handed_on=leftovers,
                )
            )
        ]
        self.last_import = GpsImportResult(
            grid_id=target_id,
            order=list(self._paths),
            placed={ln.path: ln.trace_coords({}) for ln in lines},
            leftovers=leftovers,
        )
        try:
            if chosen is not None:
                self.session.apply_preset_to(chosen, new_keys)
            if self.preset_box.is_choice():
                self.session.remember_import_preset(target_id, chosen)
        except Exception as exc:  # noqa: BLE001 -- the import happened; say what did not
            notice = f"the lines were imported, but the preset could not be applied: {exc}"
            self.messages.append((notice, True))
            self.status.setText(notice)
        return True

    def _undo(self, gid: str, sets_slices: bool, grid_added: bool) -> None:
        """Put back what a failed import wrote: the Slices preset, the new grid."""
        try:
            if sets_slices:
                self.session.set_slice_preset(gid, None)
        finally:
            if grid_added:
                self.session.remove_grid(gid)
