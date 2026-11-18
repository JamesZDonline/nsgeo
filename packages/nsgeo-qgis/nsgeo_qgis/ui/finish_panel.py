"""The Interpolation group: how a slice's blank cells are filled and smoothed.

Two instances live in the Slices dock, one per scope (This grid, Whole site),
shown one at a time, so each keeps its own remembered values without any
shared-spin capture and restore (plan call 3). It owns no state beyond the
widgets and reaches nothing: the dock listens to `edited` and decides what to
remember and redraw (interpolation spec §8).

`edited` is a user's edit and nothing else. `set_value` blocks the widgets'
signals while it writes, so seeding, restoring and clamping never reach a
listener and never mark a survey dirty ("seeds never write").
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from qgis.gui import QgsCollapsibleGroupBox
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.slices_plan import METHOD_LABELS, SliceFinish

_METHOD_TIP = (
    "How cells that no line crossed are filled from the cells around them.\n"
    "Kriging: a weighted average that follows how values vary with distance; the usual choice.\n"
    "Inverse distance: a weighted average in which nearer cells count more.\n"
    "Minimum curvature: the smoothest surface through the lines. It carries the trend on past "
    "the outer lines, so grid edges and seams can show values beyond the data. It is slower, "
    "so at a fine cell you see kriging while the depth moves and minimum curvature once it "
    "rests.\n"
    "None: show only the cells a line crossed."
)
DISTANCE_TIP = (
    "Cells farther than this from any line are left blank, so the edge of the survey or a "
    "missing line is never filled in.\n"
    "Three quarters of a line spacing closes the gap between neighbouring lines, with room for "
    "a line that wandered; lower it toward half a spacing to fill less, or raise it if a line "
    "strayed and left a blank stripe."
)
_SMOOTH_TIP = (
    "Blurs the slice along the grid's {axis} axis by this distance (the standard deviation "
    "of a Gaussian), after filling. 0 is off.\n"
    "Only smoothing changes the cells a line crossed."
)


@contextmanager
def busy_cursor() -> Iterator[None]:
    """A wait cursor for the length of the block, restored even if it raises
    (building fill weights takes seconds at a fine cell)."""
    QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


def _spin(maximum: float, step: float, suffix: str, tip: str) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0.0, maximum)
    spin.setDecimals(2)
    spin.setSingleStep(step)
    spin.setSuffix(suffix)
    spin.setToolTip(tip)
    return spin


class FinishPanel(QgsCollapsibleGroupBox):
    edited = pyqtSignal(str, object)  # (field, value): only a user's edit

    def __init__(self, parent: QWidget | None = None, *, metres_label: bool) -> None:
        super().__init__("Interpolation", parent)
        self._spacing_m: float | None = None
        self.method_combo = QComboBox()
        for key, label in METHOD_LABELS.items():
            self.method_combo.addItem(label, key)
        self.method_combo.setToolTip(_METHOD_TIP)
        self.max_distance_spin = _spin(10.0, 0.25, " × line spacing", DISTANCE_TIP)
        self.smooth_x_spin = _spin(5.0, 0.05, " m", _SMOOTH_TIP.format(axis="X"))
        self.smooth_y_spin = _spin(5.0, 0.05, " m", _SMOOTH_TIP.format(axis="Y"))
        # The defaults, set before any connect so setting them announces nothing.
        self.method_combo.setCurrentIndex(self.method_combo.findData(SliceFinish().method))
        self.max_distance_spin.setValue(SliceFinish().max_distance_spacings)

        distance_row = QHBoxLayout()
        distance_row.addWidget(self.max_distance_spin)
        if metres_label:
            self.max_distance_metres = QLabel("")
            distance_row.addWidget(self.max_distance_metres)
        form = QFormLayout(self)
        # A row too wide for the panel stacks its label above its box, so the
        # row never sets the panel's minimum width (#121).
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Method", self.method_combo)
        form.addRow("Max distance to data", distance_row)
        form.addRow("Smoothing X", self.smooth_x_spin)
        form.addRow("Smoothing Y", self.smooth_y_spin)

        self.method_combo.currentIndexChanged.connect(self._on_method)
        self.max_distance_spin.valueChanged.connect(self._on_distance)
        self.smooth_x_spin.valueChanged.connect(self._on_smooth_x)
        self.smooth_y_spin.valueChanged.connect(self._on_smooth_y)
        self._sync()

    # Every slot guards its own body: `emit` runs the dock's slot
    # synchronously, and nothing raised there may escape into Qt.
    def _on_method(self, _index: int) -> None:
        try:
            self._sync()
            self.edited.emit("method", self.method_combo.currentData())
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            _log(f"could not change the interpolation method: {exc}")

    def _on_distance(self, value: float) -> None:
        try:
            self._sync()
            self.edited.emit("max_distance_spacings", value)
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            _log(f"could not change the max distance: {exc}")

    def _on_smooth_x(self, value: float) -> None:
        try:
            self.edited.emit("smooth_x_m", value)
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            _log(f"could not change the X smoothing: {exc}")

    def _on_smooth_y(self, value: float) -> None:
        try:
            self.edited.emit("smooth_y_m", value)
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            _log(f"could not change the Y smoothing: {exc}")

    def _sync(self) -> None:
        # Nothing to reach for under "none", so the distance does not apply.
        self.max_distance_spin.setEnabled(self.method_combo.currentData() != "none")
        label = getattr(self, "max_distance_metres", None)
        if label is not None:
            spacing = self._spacing_m
            label.setText(
                "" if spacing is None else f"= {self.max_distance_spin.value() * spacing:g} m"
            )

    def value(self) -> SliceFinish:
        return SliceFinish(
            str(self.method_combo.currentData()),
            self.max_distance_spin.value(),
            self.smooth_x_spin.value(),
            self.smooth_y_spin.value(),
        )

    def set_value(self, finish: SliceFinish) -> None:
        """Show `finish`, announcing nothing: a seed never writes."""
        widgets = (
            self.method_combo,
            self.max_distance_spin,
            self.smooth_x_spin,
            self.smooth_y_spin,
        )
        for w in widgets:
            w.blockSignals(True)
        try:
            index = self.method_combo.findData(finish.method)
            if index >= 0:
                self.method_combo.setCurrentIndex(index)
            self.max_distance_spin.setValue(finish.max_distance_spacings)
            self.smooth_x_spin.setValue(finish.smooth_x_m)
            self.smooth_y_spin.setValue(finish.smooth_y_m)
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._sync()

    def set_spacing(self, spacing_m: float | None) -> None:
        """The line spacing the metres label multiplies by; None blanks it."""
        self._spacing_m = spacing_m
        self._sync()
