"""Which lines go into the cube, and which of them carry their own stack.

Spec 9.1 kept exactly one dialog out of the dock: the contributing lines,
because they need a table and a table does not fit a narrow panel. Grid,
preset and transform are combo boxes in the dock instead -- an earlier
draft put all four behind one `Edit...` button, and review rejected it
because a control named for the act of editing rather than for what it
edits leaves the user to guess its scope.

Modeless, like every dialog in this plugin: `show()` plus `finished`,
never `exec()`. See `plugin.py`'s module docstring for why.
"""

from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

HEADERS = ("", "Line", "Traces", "Length (m)", "Own stack")


class LineChoiceDialog(QDialog):
    INCLUDE_COLUMN = 0
    STACK_COLUMN = 4

    def __init__(self, session: Any, included: tuple[str, ...], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Lines in this cube")
        self.setModal(False)
        self.session = session
        self._keys: list[str] = list(session.keys()) if session.is_open else []
        self._included: set[str] = {k for k in included if k in set(self._keys)}

        layout = QVBoxLayout(self)
        note = QLabel(
            "Every line contributes through the same preset. A line with its own saved "
            "stack is listed here so the substitution is visible: amplitudes from mixed "
            "recipes are not comparable, which is the whole premise of a slice."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(list(HEADERS))
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        row = QHBoxLayout()
        self.all_button = QPushButton("Select all")
        self.none_button = QPushButton("Select none")
        row.addWidget(self.all_button)
        row.addWidget(self.none_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.all_button.clicked.connect(lambda: self.select_all())
        self.none_button.clicked.connect(lambda: self.select_none())
        self.table.itemChanged.connect(self._on_item_changed)
        self._refresh()

    # ---- state ------------------------------------------------------------
    def included_keys(self) -> tuple[str, ...]:
        """The included subset, in survey order -- never in click order.

        Order matters downstream only for readability (provenance,
        progress), but an order that changes when a user unticks and
        re-ticks a row makes two otherwise identical cubes look different
        in their own records."""
        return tuple(k for k in self._keys if k in self._included)

    def set_included(self, key: str, flag: bool) -> None:
        if flag:
            self._included.add(key)
        else:
            self._included.discard(key)
        self._refresh()

    def select_all(self) -> None:
        self._included = set(self._keys)
        self._refresh()

    def select_none(self) -> None:
        self._included = set()
        self._refresh()

    # ---- table ------------------------------------------------------------
    def _refresh(self) -> None:
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self._keys))
            for row, key in enumerate(self._keys):
                line = self.session.line_for_key(key)
                tick = QTableWidgetItem("")
                tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                tick.setCheckState(
                    Qt.CheckState.Checked if key in self._included else Qt.CheckState.Unchecked
                )
                tick.setData(Qt.ItemDataRole.UserRole, key)
                self.table.setItem(row, self.INCLUDE_COLUMN, tick)
                label = line.placement.label or key
                length = line.n_traces / max(1e-9, line.header.traces_per_metre)
                has_stack = bool(self.session.site.stacks.get(key))
                for column, text in (
                    (1, str(label)),
                    (2, str(line.n_traces)),
                    (3, f"{length:.1f}"),
                    (4, "using the preset instead" if has_stack else ""),
                ):
                    self.table.setItem(row, column, QTableWidgetItem(text))
        finally:
            self.table.blockSignals(False)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        # A slot on a Qt signal: an exception here is swallowed by PyQt
        # locally and turns into qFatal() in the CI container.
        try:
            if item.column() != self.INCLUDE_COLUMN:
                return
            key = item.data(Qt.ItemDataRole.UserRole)
            if not key:
                return
            self.set_included(str(key), item.checkState() == Qt.CheckState.Checked)
        except Exception:  # noqa: BLE001 -- see above
            from nsgeo_qgis.log import log

            log("could not update the line selection")
