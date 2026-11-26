"""The magnetometer setup form: the widgets for a `MagSetup` and the picture beside them.

Shared by the import dialog and Change setup…. The form owns no files and no
session; it holds a setup and says when it changed (`changed`).
"""

from __future__ import annotations

from typing import Any

from nsgeo.mag import MagSetup
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

from nsgeo_qgis.ui.mag_setup_picture import MagSetupPicture

#: Each corner's item data is `far_x + 2 * far_y`.
_CORNERS = (
    ("At the origin", 0),
    ("At the far end of X", 1),
    ("At the far end of Y", 2),
    ("At the far corner", 3),
)


class MagSetupForm(QGroupBox):
    #: A field was edited by the user. `set_setup` emits nothing.
    changed = pyqtSignal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self._updating = False
        group_layout = QHBoxLayout(self)
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

        self.set_setup(MagSetup())
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
            signal.connect(self._on_edited)

    @staticmethod
    def _double(low: float, high: float, step: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(3)
        spin.setSingleStep(step)
        return spin

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
        """Fill the fields and the picture; emits nothing."""
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
        self._refresh()

    def _refresh(self) -> None:
        """The flipped box and the picture follow the fields."""
        self.flipped_box.setEnabled(bool(self.walked_combo.currentData()))
        try:
            self.picture.set_setup(self.setup())
        except ValueError as exc:
            self.picture.set_error(str(exc))

    def _on_edited(self, *_: Any) -> None:
        if self._updating:
            return
        try:
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise; the picture reports
            self.picture.set_error(f"could not update the setup: {exc}")
        self.changed.emit()
