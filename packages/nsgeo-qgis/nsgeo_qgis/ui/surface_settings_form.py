"""A surface's settings as a small form: the join, the window (cm), the strength test and the
smoothing (m). Shared by the New surface dialog and the Surfaces panel (M16 B Task 5).

Return in a spin box commits what was typed and never reaches a default button (the pattern of
the ParaView dialog), and the wheel changes a spin box only while it has focus, so scrolling a
panel past it never edits a setting (#177).
"""

from __future__ import annotations

import traceback

from nsgeo.slices import JOINS, SurfaceSettings
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QEvent, QObject, Qt, pyqtSignal
from qgis.PyQt.QtGui import QKeyEvent, QWheelEvent
from qgis.PyQt.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QWidget

from nsgeo_qgis.surface_plan import join_name

_JOIN_LABELS = {
    "min_curvature": "Smooth (minimum curvature)",
    "idw": "Inverse distance (follows picks closely)",
}


def _log() -> None:
    QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Warning)


class SteadySpinBox(QDoubleSpinBox):
    """A spin box the wheel changes only while it has focus; it takes focus by click or Tab."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setKeyboardTracking(False)  # a typed value counts on Enter or leaving the box

    def wheelEvent(self, event: QWheelEvent | None) -> None:  # noqa: N802
        try:
            if event is not None and not self.hasFocus():
                event.ignore()  # let the panel scroll
                return
            super().wheelEvent(event)
        except Exception:  # noqa: BLE001 -- a Qt override: never let it escape
            _log()


class SteadyComboBox(QComboBox):
    """A combo box the wheel changes only while it has focus (StrongFocus alone does not stop
    an unfocused combo taking the wheel, so scrolling a panel would edit it)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event: QWheelEvent | None) -> None:  # noqa: N802
        try:
            if event is not None and not self.hasFocus():
                event.ignore()  # let the panel scroll
                return
            super().wheelEvent(event)
        except Exception:  # noqa: BLE001 -- a Qt override: never let it escape
            _log()


class SurfaceSettingsForm(QWidget):
    #: A setting was committed (a typed value on Enter or leaving the box, a click, a choice).
    settings_edited = pyqtSignal()

    def __init__(self, settings: SurfaceSettings | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        settings = settings or SurfaceSettings()
        self.join_combo = SteadyComboBox()
        for join in JOINS:
            self.join_combo.addItem(_JOIN_LABELS.get(join, join_name(join)), join)
        self.join_combo.setToolTip(
            "How the surface is drawn between your picks: smooth minimum curvature, or an "
            "inverse-distance blend that stays close to every pick."
        )
        self.window_spin = SteadySpinBox()
        self.window_spin.setRange(0.1, 50.0)
        self.window_spin.setDecimals(1)
        self.window_spin.setSingleStep(0.5)
        self.window_spin.setPrefix("± ")
        self.window_spin.setSuffix(" cm")
        self.window_spin.setToolTip(
            "How far the surface may follow the reflection from your picks."
        )
        self.strength_spin = SteadySpinBox()
        self.strength_spin.setRange(0.0, 100.0)
        self.strength_spin.setDecimals(1)
        self.strength_spin.setSingleStep(0.1)
        self.strength_spin.setSuffix(" ×")
        self.strength_spin.setToolTip(
            "The strength test, as a multiple of what is typical for the cell's depth; "
            "weaker cells are left as holes."
        )
        self.smoothing_spin = SteadySpinBox()
        self.smoothing_spin.setRange(0.0, 20.0)
        self.smoothing_spin.setDecimals(2)
        self.smoothing_spin.setSingleStep(0.05)
        self.smoothing_spin.setSuffix(" m")
        self.smoothing_spin.setToolTip("Off (0) keeps every detail.")
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.addRow("Join", self.join_combo)
        form.addRow("Window", self.window_spin)
        form.addRow("Strength test", self.strength_spin)
        form.addRow("Smoothing", self.smoothing_spin)
        self.set_settings(settings)
        self.join_combo.currentIndexChanged.connect(lambda _i: self.settings_edited.emit())
        for spin in self.spins():
            spin.valueChanged.connect(lambda _v: self.settings_edited.emit())
            spin.installEventFilter(self)

    def spins(self) -> tuple[SteadySpinBox, ...]:
        return (self.window_spin, self.strength_spin, self.smoothing_spin)

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:  # noqa: N802
        try:
            if (
                isinstance(event, QKeyEvent)
                and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and obj in self.spins()
            ):
                if isinstance(obj, QDoubleSpinBox):
                    obj.interpretText()  # commits the typed value; never accepts a dialog
                return True
        except Exception:  # noqa: BLE001 -- an event filter; logged
            _log()
        return super().eventFilter(obj, event)

    def settings(self) -> SurfaceSettings:
        return SurfaceSettings(
            join=str(self.join_combo.currentData()),
            window_m=self.window_spin.value() / 100.0,
            strength=self.strength_spin.value(),
            smoothing_m=self.smoothing_spin.value(),
        )

    def set_settings(self, settings: SurfaceSettings) -> None:
        """Show `settings` without announcing a change."""
        widgets = (self.join_combo, *self.spins())
        for w in widgets:
            w.blockSignals(True)
        try:
            self.join_combo.setCurrentIndex(max(0, self.join_combo.findData(settings.join)))
            self.window_spin.setValue(settings.window_m * 100.0)
            self.strength_spin.setValue(settings.strength)
            self.smoothing_spin.setValue(settings.smoothing_m)
        finally:
            for w in widgets:
                w.blockSignals(False)
