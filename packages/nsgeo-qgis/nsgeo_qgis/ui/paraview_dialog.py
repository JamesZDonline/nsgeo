"""The Export for ParaView dialog (M16 A, spec 5.2): one grid's 3-D settings, what would be
written, and the ParaView program.

It holds widgets and nothing else. The numbers and the words come from outside:
`choice_for(grid)` gives a grid's remembered `VolumeChoice`, `summary_for(grid, choice)`
gives an `ExportSummary` (raising ValueError for a cell too fine to export), and
`paraview_scene.summary_rows` says it in words. The summary is cheap, so it is refreshed on
every edit; a spin box announces only a finished edit.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from pathlib import Path

from nsgeo.slices import VolumeSettings
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.paraview_scene import (
    ExportSummary,
    cell_hint,
    disk_is_short,
    dt_hint,
    summary_rows,
)
from nsgeo_qgis.slices_plan import VolumeChoice
from nsgeo_qgis.ui.transform_combo import TransformCombo

_WARNING_STYLE = "color: #b3261e;"


def _log() -> None:
    QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)


def _hint(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setEnabled(False)  # the palette's dimmed text
    label.setWordWrap(True)
    return label


def _spin(lo: float, hi: float, decimals: int, step: float, suffix: str = "") -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(lo, hi)
    spin.setDecimals(decimals)
    spin.setSingleStep(step)
    spin.setKeyboardTracking(False)  # a typed "0.25" is not "0.2" on the way
    if suffix:
        spin.setSuffix(suffix)
    return spin


def _value_label() -> QLabel:
    label = QLabel("")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class ParaViewExportDialog(QDialog):
    def __init__(
        self,
        grid_ids: list[str],
        current_grid: str,
        choice_for: Callable[[str], VolumeChoice],
        summary_for: Callable[[str, VolumeChoice], ExportSummary],
        paraview_path: str,
        hints_for: Callable[[str], tuple[float | None, float]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export for ParaView")
        self._choice_for = choice_for
        self._summary_for = summary_for
        self._hints_for = hints_for
        self._open_after = False
        self._loading = False

        outer = QVBoxLayout(self)
        top = QFormLayout()
        self.grid_combo = QComboBox()
        self.grid_combo.addItems(grid_ids)
        top.addRow("Grid", self.grid_combo)
        outer.addLayout(top)

        resolution = QGroupBox("3-D resolution (this grid's own)")
        res_form = QFormLayout(resolution)
        self.cell_spin = _spin(0.001, 100.0, 3, 0.05, " m")
        self.cell_hint = _hint()
        self.dz_spin = _spin(0.001, 100.0, 4, 0.05, " ns")
        self.dz_hint = _hint()
        res_form.addRow("Cell", self._with_hint(self.cell_spin, self.cell_hint))
        res_form.addRow("Depth step", self._with_hint(self.dz_spin, self.dz_hint))
        outer.addWidget(resolution)

        volume = QGroupBox("The volume")
        vol_form = QFormLayout(volume)
        self.transform_combo = TransformCombo()
        self.stretch_spin = _spin(0.1, 50.0, 1, 0.5)
        self.stretch_spin.setPrefix("× ")
        self.period_spin = _spin(0.1, 100.0, 2, 0.5, " ns")
        self.blur_spin = _spin(0.0, 5.0, 2, 0.05, " m")
        self.trend_spin = _spin(0.01, 10.0, 2, 0.05, " m")
        vol_form.addRow("Transform", self.transform_combo)
        vol_form.addRow("Depth stretch", self.stretch_spin)
        vol_form.addRow(
            "Wave period",
            self._with_hint(self.period_spin, _hint("one smooth body per reflection")),
        )
        vol_form.addRow("Sideways blur", self.blur_spin)
        vol_form.addRow(
            "Depth balance",
            self._with_hint(
                self.trend_spin,
                _hint(
                    "strength = each value ÷ what is typical at its depth, "
                    "averaged over this much depth"
                ),
            ),
        )
        outer.addWidget(volume)

        written = QGroupBox("What will be written")
        written_form = QFormLayout(written)
        self.folder_label = _value_label()
        self.volume_label = _value_label()
        self.fill_label = _value_label()
        self.also_label = _value_label()
        self.size_label = _value_label()
        self.disk_label = _value_label()
        self._row_labels = {
            "Folder": self.folder_label,
            "Volume": self.volume_label,
            "Fill": self.fill_label,
            "Also": self.also_label,
            "Size": self.size_label,
            "Disk": self.disk_label,
        }
        for name, label in self._row_labels.items():
            written_form.addRow(name, label)
        outer.addWidget(written)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(paraview_path)
        self.path_edit.setPlaceholderText("the ParaView program (optional)")
        self.browse_button = QPushButton("Browse…")
        path_row.addWidget(QLabel("ParaView"))
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_button)
        outer.addLayout(path_row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.export_button = QPushButton("Export")
        self.open_button = QPushButton("Export and open")
        for b in (self.cancel_button, self.export_button, self.open_button):
            b.setAutoDefault(False)
            buttons.addWidget(b)
        outer.addLayout(buttons)

        self.cancel_button.clicked.connect(lambda: self.reject())
        self.export_button.clicked.connect(lambda: self._finish(False))
        self.open_button.clicked.connect(lambda: self._finish(True))
        self.browse_button.clicked.connect(lambda: self._browse())
        self.path_edit.textChanged.connect(lambda _t: self._refresh())
        self.grid_combo.currentTextChanged.connect(lambda _t: self._load_grid())
        for spin in (
            self.cell_spin,
            self.dz_spin,
            self.stretch_spin,
            self.period_spin,
            self.blur_spin,
            self.trend_spin,
        ):
            spin.valueChanged.connect(lambda _v: self._refresh())
        self.transform_combo.value_changed.connect(lambda _v: self._refresh())

        if current_grid in grid_ids:
            self.grid_combo.setCurrentText(current_grid)
        self._load_grid()

    @staticmethod
    def _with_hint(field: QWidget, hint: QLabel) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(field)
        row.addWidget(hint, 1)
        return box

    # ---- reading ---------------------------------------------------------------------------
    def grid_id(self) -> str:
        return self.grid_combo.currentText()

    def choice(self) -> VolumeChoice:
        return VolumeChoice(
            cell=self.cell_spin.value(),
            dz_ns=self.dz_spin.value(),
            transform=self.transform_combo.value(),
            stretch=self.stretch_spin.value(),
            settings=VolumeSettings(
                period_ns=self.period_spin.value(),
                blur_m=self.blur_spin.value(),
                trend_m=self.trend_spin.value(),
            ),
        )

    def paraview_path(self) -> str:
        return self.path_edit.text().strip()

    def open_after(self) -> bool:
        return self._open_after

    # ---- behaviour -------------------------------------------------------------------------
    def _load_grid(self) -> None:
        """Show the chosen grid's own settings (the widgets announce nothing meanwhile)."""
        try:
            grid = self.grid_id()
            if not grid:
                return
            self._loading = True
            try:
                choice = self._choice_for(grid)
                self.cell_spin.setValue(choice.cell)
                self.dz_spin.setValue(choice.dz_ns)
                self.transform_combo.set_value(choice.transform)
                self.stretch_spin.setValue(choice.stretch)
                self.period_spin.setValue(choice.settings.period_ns)
                self.blur_spin.setValue(choice.settings.blur_m)
                self.trend_spin.setValue(choice.settings.trend_m)
                if self._hints_for is not None:
                    panel_cell, native_dt = self._hints_for(grid)
                    self.cell_hint.setText(cell_hint(panel_cell))
                    self.dz_hint.setText(dt_hint(native_dt))
            finally:
                self._loading = False
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot; shown, and logged
            _log()
            self._show_problem(str(exc))

    def _refresh(self) -> None:
        """Recompute what will be written for the settings as they stand now."""
        if self._loading:
            return
        try:
            try:
                summary = self._summary_for(self.grid_id(), self.choice())
            except ValueError as exc:
                self._show_problem(str(exc))
                return
            for label, text in summary_rows(summary):
                self._row_labels[label].setText(text)
                self._row_labels[label].setStyleSheet("")
            short = disk_is_short(summary)
            self.disk_label.setStyleSheet(_WARNING_STYLE if short else "")
            self.disk_label.setProperty("warning", short)
            self._set_buttons(True)
        except Exception as exc:  # noqa: BLE001 -- a slot; shown, and logged
            _log()
            self._show_problem(str(exc))

    def _show_problem(self, text: str) -> None:
        """The settings cannot be exported: say why in the Size row, and block both buttons."""
        for name, label in self._row_labels.items():
            label.setText(text if name == "Size" else "")
            label.setStyleSheet(_WARNING_STYLE if name == "Size" else "")
        self.disk_label.setProperty("warning", False)
        self._set_buttons(False)

    def _set_buttons(self, ok: bool) -> None:
        has_path = bool(self.paraview_path())
        self.export_button.setEnabled(ok)
        self.open_button.setEnabled(ok and has_path)
        if ok and not has_path:
            self.open_button.setDefault(False)
            self.export_button.setDefault(True)
        else:
            self.export_button.setDefault(False)
            self.open_button.setDefault(True)

    def _browse(self) -> None:
        try:
            start = self.paraview_path() or str(Path.home())
            path, _ = QFileDialog.getOpenFileName(self, "ParaView program", start)
            if path:
                self.path_edit.setText(path)
        except Exception:  # noqa: BLE001 -- a slot; logged
            _log()

    def _finish(self, open_after: bool) -> None:
        try:
            self._open_after = open_after
            self.accept()
        except Exception:  # noqa: BLE001 -- a slot; logged
            _log()
