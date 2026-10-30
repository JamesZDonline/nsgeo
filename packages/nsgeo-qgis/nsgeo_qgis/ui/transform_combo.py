"""The Transform combo: step titles on screen, step ids underneath.

Both the Slices dock and the site panel offer one. Everything they read or
store -- a cube recipe, the site view's remembered transform -- is the
value, "none" or a step id, so showing titles (#82) changes nothing saved.
"""

from __future__ import annotations

from nsgeo.processing import step_title
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QComboBox, QWidget

from nsgeo_qgis.slices_plan import transform_names

NONE = "none"


class TransformCombo(QComboBox):
    value_changed = pyqtSignal(str)  # "none" or a step id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Filled before the connect, so filling announces nothing.
        self.addItem("None", NONE)
        for name in transform_names():
            self.addItem(step_title(name), name)
        self.currentIndexChanged.connect(lambda _i: self.value_changed.emit(self.value()))

    def value(self) -> str:
        return str(self.currentData() or NONE)

    def values(self) -> list[str]:
        return [str(self.itemData(i)) for i in range(self.count())]

    def set_value(self, value: str) -> bool:
        """Select `value`; False, and the selection left alone, when it is
        not offered (Qt's own `setCurrentText` would do the same silently)."""
        index = self.findData(value)
        if index < 0:
            return False
        self.setCurrentIndex(index)
        return True
