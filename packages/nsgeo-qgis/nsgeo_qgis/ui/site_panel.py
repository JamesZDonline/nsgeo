"""The Slices dock's two Whole-site groups: the grid list and Normalisation.

Spec 4.2 and 4.6. Widgets only: they show what the dock gives them and
report what the user does, and compute nothing. The dock owns the session
and the `SiteEngine`.

Every refill runs under a guard (trap 8): filling a table or a combo emits
the same signals a user's click does, and a refill that read as a choice
would re-prepare the site. Every slot guards its body and logs, like every
other slot in this plugin (an exception escaping a slot aborts the CI
container).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.slices_plan import transform_names

#: The grid list's columns, in order (spec 4.2).
HEADERS = ("✓", "Grid", "Preset", "Lines", "State")
_INCLUDE = 0

#: Combo label to method id (`nsgeo.slices.NORMALISATION_METHODS`), in order.
METHODS = (
    ("None", "none"),
    ("Background level", "background"),
    ("Edge match", "edge"),
    ("Histogram match", "histogram"),
)


@dataclass(frozen=True)
class SiteRow:
    """One grid in the list. `lines` is already formatted (`24 / 26`)."""

    grid_id: str
    preset: str
    lines: str
    state: str
    included: bool


class SiteSourcePanel(QWidget):
    """Source in site scope: one row per grid, one transform, a line chooser."""

    #: The ticked grid ids, in row order, after the user ticks or unticks one.
    included_changed = pyqtSignal(object)
    transform_changed = pyqtSignal(str)
    #: The selected grid id, or "" when nothing is selected.
    selected_changed = pyqtSignal(str)
    #: Ask for M11's line chooser for this grid.
    choose_lines_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._updating = 0
        self._ids: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        group = QGroupBox("Source")
        outer.addWidget(group)
        layout = QVBoxLayout(group)

        form = QFormLayout()
        self.transform_combo = QComboBox()
        self.transform_combo.addItem("none")
        self.transform_combo.addItems(transform_names())
        self.transform_combo.setToolTip(
            "One transform for the whole site: every grid is drawn on one layer, "
            "so they must agree on polarity."
        )
        form.addRow("Transform", self.transform_combo)
        layout.addLayout(form)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(list(HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.table.setToolTip(
            "Tick the grids drawn in the site view. Select a row to choose its "
            "lines or set its gain. A grid's preset is chosen in This grid."
        )
        layout.addWidget(self.table)

        self.choose_button = QPushButton("Choose lines…")
        self.choose_button.setEnabled(False)
        layout.addWidget(self.choose_button)

        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.transform_combo.currentTextChanged.connect(self._on_transform_changed)
        self.choose_button.clicked.connect(lambda: self._on_choose_clicked())

    # ---- what the dock reads ------------------------------------------
    def included(self) -> tuple[str, ...]:
        out = []
        for row, grid_id in enumerate(self._ids):
            item = self.table.item(row, _INCLUDE)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                out.append(grid_id)
        return tuple(out)

    def selected_grid(self) -> str | None:
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        if len(rows) != 1:
            return None
        row = rows.pop()
        return self._ids[row] if 0 <= row < len(self._ids) else None

    def transform(self) -> str:
        """The combo's text: "none" or a transform name."""
        return self.transform_combo.currentText() or "none"

    # ---- what the dock writes -----------------------------------------
    def set_rows(self, rows: Sequence[SiteRow]) -> None:
        """Show `rows`, keeping the selection by grid id. Never reads as a choice."""
        self._updating += 1
        self.table.blockSignals(True)
        selected = self.selected_grid()
        try:
            ids = [r.grid_id for r in rows]
            if ids != self._ids:
                self.table.clearSelection()
                self.table.setRowCount(len(rows))
                self._ids = ids
            for index, row in enumerate(rows):
                tick = self.table.item(index, _INCLUDE)
                state = Qt.CheckState.Checked if row.included else Qt.CheckState.Unchecked
                if tick is None:
                    tick = QTableWidgetItem("")
                    tick.setFlags(
                        Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                    )
                    # Always set on a new item: an item never given a check
                    # state shows no checkbox at all.
                    tick.setCheckState(state)
                    self.table.setItem(index, _INCLUDE, tick)
                elif tick.checkState() != state:
                    tick.setCheckState(state)
                for column, text in (
                    (1, row.grid_id),
                    (2, row.preset),
                    (3, row.lines),
                    (4, row.state),
                ):
                    item = self.table.item(index, column)
                    if item is None:
                        self.table.setItem(index, column, QTableWidgetItem(text))
                    elif item.text() != text:
                        item.setText(text)
            if selected in self._ids and self.selected_grid() != selected:
                self.table.selectRow(self._ids.index(selected))
        finally:
            self.table.blockSignals(False)
            self._updating -= 1
        self._update_choose_button()
        if self.selected_grid() != selected:
            # The selected grid left the list: the dock's gain spin must hear.
            self.selected_changed.emit(self.selected_grid() or "")

    def select_grid(self, grid_id: str | None) -> None:
        """Select `grid_id`'s row (None clears), as a click would."""
        if grid_id in self._ids:
            self.table.selectRow(self._ids.index(grid_id))
        else:
            self.table.clearSelection()

    def set_transform(self, name: str) -> None:
        """Show `name` without it reading as a choice; an unknown name is ignored."""
        if self.transform_combo.findText(name) < 0:
            return
        self._updating += 1
        try:
            self.transform_combo.setCurrentText(name)
        finally:
            self._updating -= 1

    # ---- slots ----------------------------------------------------------
    def _update_choose_button(self) -> None:
        grid_id = self.selected_grid()
        self.choose_button.setEnabled(grid_id is not None)
        self.choose_button.setText(
            f"Choose lines for {grid_id}…" if grid_id is not None else "Choose lines…"
        )

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        try:
            if self._updating or item.column() != _INCLUDE:
                return
            self.included_changed.emit(self.included())
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            _log(f"could not change the site's grids: {exc}")

    def _on_selection_changed(self) -> None:
        try:
            self._update_choose_button()
            if self._updating:
                return
            self.selected_changed.emit(self.selected_grid() or "")
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            _log(f"could not follow the grid selection: {exc}")

    def _on_transform_changed(self, text: str) -> None:
        try:
            if self._updating:
                return
            self.transform_changed.emit(text or "none")
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            _log(f"could not change the site's transform: {exc}")

    def _on_choose_clicked(self) -> None:
        try:
            grid_id = self.selected_grid()
            if grid_id is not None:
                self.choose_lines_requested.emit(grid_id)
        except Exception as exc:  # noqa: BLE001 -- a slot on QPushButton.clicked
            _log(f"could not open the line chooser: {exc}")


class NormalisationPanel(QWidget):
    """Spec 4.6: a method for the site, and a manual gain for the selected grid."""

    #: A method id, after the user picks one.
    method_changed = pyqtSignal(str)
    #: (grid id, gain), after the user changes the selected grid's gain.
    gain_changed = pyqtSignal(str, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._updating = 0
        self._grid: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        group = QGroupBox("Normalisation")
        outer.addWidget(group)
        form = QFormLayout(group)

        self.method_combo = QComboBox()
        for label, method in METHODS:
            self.method_combo.addItem(label, method)
        self.method_combo.setToolTip(
            "Evens out brightness between grids, slice by slice. Off by default: "
            "None shows each grid as recorded."
        )
        form.addRow("Method", self.method_combo)

        gain_row = QHBoxLayout()
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setPrefix("×")
        self.gain_spin.setDecimals(2)
        self.gain_spin.setRange(0.10, 10.00)
        # Trap 7: Qt's default step of 1.0 would jump x1.00 to x2.00 in one
        # click, past any adjustment made by eye.
        self.gain_spin.setSingleStep(0.05)
        self.gain_spin.setValue(1.00)
        # One change per finished edit, not per keystroke: each change
        # re-measures the site's shared stretch.
        self.gain_spin.setKeyboardTracking(False)
        self.gain_spin.setEnabled(False)
        self.gain_spin.setToolTip(
            "Brightness multiplier for the selected grid, applied on top of the "
            "method's factor and constant with depth. Saved with the survey."
        )
        self.reset_button = QPushButton("Reset")
        self.reset_button.setEnabled(False)
        gain_row.addWidget(self.gain_spin, 1)
        gain_row.addWidget(self.reset_button)
        self.gain_label = QLabel("Gain")
        form.addRow(self.gain_label, gain_row)

        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        self.gain_spin.valueChanged.connect(self._on_gain_changed)
        self.reset_button.clicked.connect(lambda: self._on_reset())

    def method(self) -> str:
        return str(self.method_combo.currentData())

    def set_method(self, method: str) -> None:
        """Show `method` without it reading as a choice; an unknown id is ignored."""
        index = self.method_combo.findData(method)
        if index < 0:
            return
        self._updating += 1
        try:
            self.method_combo.setCurrentIndex(index)
        finally:
            self._updating -= 1

    def set_grid(self, grid_id: str | None, gain: float) -> None:
        """The grid the gain spin acts on (None disables it), showing `gain`."""
        self._grid = grid_id
        self._updating += 1
        try:
            self.gain_spin.setValue(gain if grid_id is not None else 1.0)
        finally:
            self._updating -= 1
        self.gain_spin.setEnabled(grid_id is not None)
        self.reset_button.setEnabled(grid_id is not None)
        self.gain_label.setText(f"Gain for {grid_id}" if grid_id is not None else "Gain")

    def _on_method_changed(self, _index: int) -> None:
        try:
            if self._updating:
                return
            self.method_changed.emit(self.method())
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            _log(f"could not change the normalisation: {exc}")

    def _on_gain_changed(self, value: float) -> None:
        try:
            if self._updating or self._grid is None:
                return
            self.gain_changed.emit(self._grid, float(value))
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            _log(f"could not change the grid's gain: {exc}")

    def _on_reset(self) -> None:
        try:
            if self._grid is not None:
                self.gain_spin.setValue(1.00)
        except Exception as exc:  # noqa: BLE001 -- a slot on QPushButton.clicked
            _log(f"could not reset the grid's gain: {exc}")
