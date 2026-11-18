"""The Surfaces panel (M16 B Task 5; spec §5.3; the approved mockup's layout A).

Every grid's surfaces in one table (a Grid filter narrows it), and under it the selected
surface: why it is stale, its picks, its settings (saved at once), the fit of its last build
and the picks that sit away from it. The panel only shows and asks: building, the New surface
dialog and the map selection belong to the plugin, which listens to its three signals.
"""

from __future__ import annotations

import contextlib
import traceback
from typing import Any

from nsgeo.slices import SurfaceSettings
from qgis.core import Qgis, QgsMessageLog
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QShowEvent
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.surface_plan import (
    DELETE_BUTTON,
    DELETE_TITLE,
    NO_LONGER_MEMBER,
    NOTHING_TO_REMOVE,
    also_note,
    delete_question,
    fit_rows,
    fit_short,
    not_built_text,
    outlier_header,
    outlier_line,
    stale_text,
    state_text,
    write_failure_text,
)
from nsgeo_qgis.surfaces import Surfaces
from nsgeo_qgis.ui.surface_settings_form import SteadyComboBox, SurfaceSettingsForm

ALL_GRIDS = "All grids"
COLUMNS = ("Name", "Grid", "Picks", "Fit", "State")
_ROLE_ID = Qt.ItemDataRole.UserRole


def _log() -> None:
    QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Warning)


class SurfacesDock(QgsDockWidget):
    #: The New from selected picks… button: the plugin opens the New surface dialog.
    new_requested = pyqtSignal()
    #: Rebuild: the feature ids of every selected surface (the plugin groups them by grid).
    build_requested = pyqtSignal(list)
    #: Select these picks-layer fids on the map.
    select_picks_requested = pyqtSignal(list)
    #: Something the user must be told (a refused change); the plugin shows it.
    problem = pyqtSignal(str)
    #: Something done that the user should know of (picks moved out of other surfaces).
    notice = pyqtSignal(str)

    def __init__(self, session: SiteSession, surfaces: Surfaces, parent: QWidget | None = None):
        super().__init__("nsgeo Surfaces", parent)
        self.setObjectName("nsgeoSurfacesDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.session = session
        self.surfaces = surfaces
        self._disposed = False
        self._loading = False
        #: A refresh was asked for while the panel was closed; made when it is shown.
        self._stale_view = False
        #: The outliers listed in the details, in the list's order.
        self._outliers: list[dict[str, Any]] = []

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 6, 6, 6)

        top = QGridLayout()
        top.addWidget(QLabel("Grid"), 0, 0)
        self.grid_combo = SteadyComboBox()
        self.grid_combo.addItem(ALL_GRIDS)
        top.addWidget(self.grid_combo, 0, 1)
        top.setColumnStretch(1, 1)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(110)
        layout.addWidget(self.table)

        buttons = QGridLayout()
        self.new_button = QPushButton("New from selected picks…")
        self.rebuild_button = QPushButton("Rebuild")
        self.rename_button = QPushButton("Rename…")
        self.delete_button = QPushButton("Delete…")
        self.new_button.setToolTip(
            "Select picks on the map first (the picks layer current, QGIS's Select tool)."
        )
        self.rebuild_button.setToolTip("Build every selected surface again from its picks.")
        buttons.addWidget(self.new_button, 0, 0, 1, 2)
        buttons.addWidget(self.rebuild_button, 1, 0)
        buttons.addWidget(self.rename_button, 1, 1)
        buttons.addWidget(self.delete_button, 2, 0, 1, 2)
        layout.addLayout(buttons)

        self.details = QGroupBox("Surface")
        details = QVBoxLayout(self.details)
        self.stale_label = QLabel()
        self.stale_label.setWordWrap(True)
        self.stale_label.setTextFormat(Qt.TextFormat.PlainText)
        details.addWidget(self.stale_label)
        picks = QGridLayout()
        self.select_button = QPushButton("Select its picks")
        self.add_button = QPushButton("Add selected picks")
        self.remove_button = QPushButton("Remove selected picks")
        self.add_button.setToolTip("Add the picks selected on the map to this surface.")
        self.remove_button.setToolTip("Take the picks selected on the map out of this surface.")
        picks.addWidget(self.select_button, 0, 0, 1, 2)
        picks.addWidget(self.add_button, 1, 0)
        picks.addWidget(self.remove_button, 1, 1)
        details.addLayout(picks)
        self.settings_box = QGroupBox("Settings")
        box = QVBoxLayout(self.settings_box)
        self.form = SurfaceSettingsForm()
        box.addWidget(self.form)
        details.addWidget(self.settings_box)
        self.fit_box = QGroupBox("Fit, last build")
        self.fit_form = QFormLayout(self.fit_box)
        self.fit_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        details.addWidget(self.fit_box)
        self.outlier_header = QLabel()
        self.outlier_header.setWordWrap(True)
        self.outlier_header.setTextFormat(Qt.TextFormat.PlainText)
        details.addWidget(self.outlier_header)
        self.outlier_list = QListWidget()
        self.outlier_list.setMinimumHeight(90)
        self.outlier_list.setToolTip(
            "Click one to select that pick on the map and open its line in the Profile panel."
        )
        details.addWidget(self.outlier_list)
        layout.addWidget(self.details)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.setWidget(scroll)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.refresh)
        self._signals = (
            session.features_changed,
            session.picks_changed,
            session.slice_sources_changed,
            session.lines_changed,
            session.grids_changed,
            session.presets_changed,
            session.site_opened,
            session.site_closed,
        )
        for signal in self._signals:
            signal.connect(self.request_refresh)

        self.grid_combo.currentIndexChanged.connect(lambda _i: self._guarded(self.refresh))
        self.table.itemSelectionChanged.connect(lambda: self._guarded(self._show_details))
        self.new_button.clicked.connect(lambda: self._guarded(self.new_requested.emit))
        self.rebuild_button.clicked.connect(lambda: self._guarded(self._rebuild))
        self.rename_button.clicked.connect(lambda: self._guarded(self._rename))
        self.delete_button.clicked.connect(lambda: self._guarded(self._delete))
        self.select_button.clicked.connect(lambda: self._guarded(self._select_picks))
        self.add_button.clicked.connect(lambda: self._guarded(self._add_picks))
        self.remove_button.clicked.connect(lambda: self._guarded(self._remove_picks))
        self.form.settings_edited.connect(lambda: self._guarded(self._save_settings))
        self.outlier_list.itemClicked.connect(
            lambda item: self._guarded(lambda: self._open_outlier(item))
        )
        self.refresh()

    # ---- plumbing -----------------------------------------------------------
    def _guarded(self, body: Any) -> None:
        """Run a slot's body; a failure is reported, never raised into Qt."""
        try:
            body()
        except Exception as exc:  # noqa: BLE001 -- a Qt slot
            _log()
            self.problem.emit(f"the Surfaces panel failed: {exc}")

    def request_refresh(self, *_: Any) -> None:
        """Ask for a `refresh` at the next turn of the event loop; many asks make one."""
        try:
            if self._disposed:
                return
            if self.isHidden():
                self._stale_view = True  # closed: nothing to draw until it is shown again
                return
            if not self._timer.isActive():
                self._timer.start()
        except Exception:  # noqa: BLE001 -- a slot on session signals
            _log()

    def showEvent(self, event: QShowEvent | None) -> None:  # noqa: N802
        try:
            super().showEvent(event)
            if self._stale_view:
                self._stale_view = False
                self.request_refresh()
        except Exception:  # noqa: BLE001 -- a Qt override
            _log()

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._timer.stop()
        for signal in self._signals:
            with contextlib.suppress(TypeError, RuntimeError):
                signal.disconnect(self.request_refresh)

    # ---- the table ------------------------------------------------------------
    def selected_ids(self) -> list[str]:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        out = []
        for row in rows:
            item = self.table.item(row, 0)
            if item is not None:
                out.append(str(item.data(_ROLE_ID)))
        return out

    def refresh(self) -> None:
        """Rebuild the table (keeping the selection) and the details from the records."""
        if self._disposed:
            return
        try:
            self._refresh_table()
        except Exception as exc:  # noqa: BLE001 -- also reached from a timer
            _log()
            self.problem.emit(f"could not list the surfaces: {exc}")

    def _refresh_table(self) -> None:
        records = self.surfaces.records() if self.session.is_open else []
        grids = sorted({r.grid_id for r in records})
        keep_ids = set(self.selected_ids())
        self._loading = True
        try:
            wanted = self.grid_combo.currentText()
            self.grid_combo.blockSignals(True)
            self.grid_combo.clear()
            self.grid_combo.addItem(ALL_GRIDS)
            self.grid_combo.addItems(grids)
            index = self.grid_combo.findText(wanted)
            self.grid_combo.setCurrentIndex(index if index >= 0 else 0)
            self.grid_combo.blockSignals(False)
            chosen = self.grid_combo.currentText()
            shown = [r for r in records if chosen == ALL_GRIDS or r.grid_id == chosen]
            members = self.surfaces.layers.members_by_feature()  # once for the whole refresh
            self.table.blockSignals(True)
            self.table.clearContents()
            self.table.setRowCount(len(shown))
            for row, record in enumerate(shown):
                try:
                    state = self.surfaces.state(record.feature_id, members)
                    state_label = state_text(state.built, state.stale)
                    fit = fit_short(state.report)
                except Exception:  # noqa: BLE001 -- one surface's trouble never hides the rest
                    _log()
                    state_label, fit = "unreadable", ""
                cells = (
                    record.name,
                    record.grid_id,
                    str(len(members.get(record.feature_id, []))),
                    fit,
                    state_label,
                )
                for col, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    item.setData(_ROLE_ID, record.feature_id)
                    if col in (2, 3):
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    self.table.setItem(row, col, item)
                if record.feature_id in keep_ids:
                    for col in range(len(COLUMNS)):
                        item = self.table.item(row, col)
                        if item is not None:
                            item.setSelected(True)
            self.table.blockSignals(False)
        finally:
            self.table.blockSignals(False)
            self._loading = False
        self._show_details(members)

    # ---- the selected surface -------------------------------------------------
    def _current(self) -> str | None:
        ids = self.selected_ids()
        return ids[0] if len(ids) == 1 else None

    def _show_details(self, members: dict[str, list[Any]] | None = None) -> None:
        ids = self.selected_ids()
        fid = ids[0] if len(ids) == 1 else None
        self.rebuild_button.setEnabled(bool(ids))
        self.rename_button.setEnabled(fid is not None)
        self.delete_button.setEnabled(fid is not None)
        self.details.setVisible(fid is not None)
        self.outlier_list.clear()
        self._outliers = []
        if fid is None:
            return
        record = next((r for r in self.surfaces.records() if r.feature_id == fid), None)
        if record is None:
            self.details.setVisible(False)
            return
        self.details.setTitle(record.name)
        self.details.setToolTip("")
        if members is None:
            members = self.surfaces.layers.members_by_feature()
        n = len(members.get(fid, []))
        state = self.surfaces.state(fid, members)
        text = stale_text(state.stale)
        if not state.built:
            text = not_built_text(n)
        self.stale_label.setText(text)
        self.stale_label.setVisible(bool(text))
        # The form shows what is saved, never echoing back its own edit (the spin boxes round).
        if self.form.settings() != record.settings:
            self.form.set_settings(record.settings)
        while self.fit_form.rowCount():
            self.fit_form.removeRow(0)
        report = state.report
        self.fit_box.setVisible(report is not None)
        self.outlier_header.setVisible(False)
        self.outlier_list.setVisible(False)
        if report is None:
            return
        for label, value in fit_rows(report):
            text_label = QLabel(value)
            text_label.setWordWrap(True)
            text_label.setTextFormat(Qt.TextFormat.PlainText)
            self.fit_form.addRow(label, text_label)
        outliers = [o for o in report.get("outliers", []) if isinstance(o, dict)]
        self._outliers = outliers
        window_m = float(report.get("settings", {}).get("window_m", record.settings.window_m))
        self.outlier_header.setText(outlier_header(window_m, len(outliers)))
        for outlier in outliers:
            item = QListWidgetItem(outlier_line(outlier))
            item.setToolTip(outlier_line(outlier))
            self.outlier_list.addItem(item)
        self.outlier_header.setVisible(True)
        self.outlier_list.setVisible(bool(outliers))

    # ---- actions --------------------------------------------------------------
    def _rebuild(self) -> None:
        ids = self.selected_ids()
        if ids:
            self.build_requested.emit(ids)

    def _rename(self) -> None:
        fid = self._current()
        if fid is None:
            return
        record = next(r for r in self.surfaces.records() if r.feature_id == fid)
        text, ok = QInputDialog.getText(
            self, "Rename surface", "Name", QLineEdit.EchoMode.Normal, record.name
        )
        if not ok:
            return
        try:
            self.surfaces.rename(fid, text)
        except (ValueError, RuntimeError) as exc:
            self.problem.emit(write_failure_text(str(exc)))

    def _delete(self) -> None:
        fid = self._current()
        if fid is None:
            return
        record = next(r for r in self.surfaces.records() if r.feature_id == fid)
        box = QMessageBox(
            QMessageBox.Icon.Question,
            DELETE_TITLE,
            delete_question(record.name, len(self.surfaces.members(fid))),
            QMessageBox.StandardButton.Cancel,
            self,
        )
        delete = box.addButton(DELETE_BUTTON, QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        try:
            box.exec()
            chosen = box.clickedButton()
        finally:
            box.deleteLater()
        if chosen is not delete:
            return
        try:
            self.surfaces.delete(fid)
        except (ValueError, RuntimeError, KeyError) as exc:
            self.problem.emit(write_failure_text(str(exc)))

    def _select_picks(self) -> None:
        fid = self._current()
        if fid is not None:
            self.select_picks_requested.emit([r.fid for r in self.surfaces.members(fid)])

    def _add_picks(self) -> None:
        fid = self._current()
        if fid is None:
            return
        try:
            fids = self.surfaces.layers.selected_pick_ids()
            found = self.surfaces.check(fids, into=fid)
            self.surfaces.add_picks(fid, fids)
            note = also_note(found.also, found.n)
            if note and not found.refusal:
                self.notice.emit(note)
        except (ValueError, RuntimeError) as exc:
            self.problem.emit(write_failure_text(str(exc)))

    def _remove_picks(self) -> None:
        fid = self._current()
        if fid is None:
            return
        try:
            removed = self.surfaces.remove_picks(fid, self.surfaces.layers.selected_pick_ids())
            if not removed:
                self.notice.emit(NOTHING_TO_REMOVE)
        except (ValueError, RuntimeError) as exc:
            self.problem.emit(write_failure_text(str(exc)))

    def _save_settings(self) -> None:
        fid = self._current()
        if fid is None or self._loading:
            return
        try:
            settings: SurfaceSettings = self.form.settings()
            self.surfaces.set_settings(fid, settings)
        except (ValueError, RuntimeError) as exc:
            self.problem.emit(write_failure_text(str(exc)))

    def _open_outlier(self, item: QListWidgetItem) -> None:
        row = self.outlier_list.row(item)
        fid = self._current()
        if fid is None or not 0 <= row < len(self._outliers):
            return
        outlier = self._outliers[row]
        key = str(outlier.get("line_key", ""))
        pick = self._pick_of(fid, outlier)
        if pick is None:
            self.problem.emit(NO_LONGER_MEMBER)
            return
        self.select_picks_requested.emit([pick.fid])
        # A line that left the site is only selected; there is nothing to open.
        if key in set(self.session.keys()):
            self.session.open_line(key)
            self.session.set_trace(key, pick.pick.trace)

    def _pick_of(self, feature_id: str, outlier: dict[str, Any]) -> Any:
        """The member the outlier names: its line and trace (an older build has the distance)."""
        key = str(outlier.get("line_key", ""))
        rows = [r for r in self.surfaces.members(feature_id) if r.pick.line_key == key]
        trace, time_ns = outlier.get("trace"), outlier.get("time_ns")
        if trace is not None:
            rows = [r for r in rows if r.pick.trace == int(trace)]
            if time_ns is not None:
                rows = [r for r in rows if abs(r.pick.time_ns - float(time_ns)) < 1e-9]
        elif outlier.get("distance_m") is not None:
            rows = [
                r
                for r in rows
                if r.pick.distance_m is not None
                and abs(r.pick.distance_m - float(outlier["distance_m"])) < 1e-6
            ]
        return rows[0] if rows else None
