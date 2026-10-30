"""The line velocity dialog: type a number, or take one from a saved fit.

`velocity()` is the whole answer: a model to apply, or `None` for "remove the
override". `selected_fit_id()` says which saved fit that number came from, and
is `None` once the user types something else, because a typed number has no
fit behind it.

Deleting a fit is the one thing here that does not wait for Apply: Apply also
writes the spin box as the line's override, and opening the dialog only to
delete a bad fit must not set a velocity on the way.

Fits are listed by t0 (shallowest first). A pair whose velocities differ by
more than 2 * sqrt(s1^2 + s2^2) is flagged. That is a passive diagnostic, not a
refusal: it says the ground looks layered, which a later Dix conversion acts
on.
"""

from __future__ import annotations

import math
import traceback
from collections.abc import Mapping

from nsgeo.velocity import VelocityModel
from nsgeo.velocity_fit import StoredFit
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.session import SiteSession

_HEADERS = ("t0 (ns)", "v ± σ (m/ns)", "rms (ns)", "points", "")
_FLAG_COLUMN = 4

# Two fits disagree when their velocities differ by more than this many
# combined standard errors. 1 would cry wolf on about a third (31.7%) of pairs
# that are genuinely identical; 2 flags about 4.6%, the conventional line.
_DISAGREEMENT_SIGMAS = 2.0


def disagreeing_fit_ids(fits: Mapping[str, StoredFit]) -> frozenset[str]:
    """Ids of every fit that disagrees with at least one other: velocities
    further apart than `_DISAGREEMENT_SIGMAS` times the two standard errors
    combined in quadrature."""
    items = list(fits.items())
    flagged: set[str] = set()
    for i, (id_a, a) in enumerate(items):
        for id_b, b in items[i + 1 :]:
            combined = math.hypot(a.v_stderr_m_ns, b.v_stderr_m_ns)
            if abs(a.v_m_ns - b.v_m_ns) > _DISAGREEMENT_SIGMAS * combined:
                flagged.update((id_a, id_b))
    return frozenset(flagged)


class VelocityDialog(QDialog):
    # The fit selected in the table, or None: lets the profile light its curve.
    fit_highlighted = pyqtSignal(object)

    def __init__(self, session: SiteSession, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.key = key
        self.setWindowTitle(f"Velocity · {key}")
        line = session.line_for_key(key)
        self._fits: dict[str, StoredFit] = {}
        self._ids: list[str] = []
        self._flagged: frozenset[str] = frozenset()
        self._cleared = False
        self._selected: str | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.spin = QDoubleSpinBox()
        self.spin.setRange(0.0, 0.3)
        self.spin.setDecimals(4)
        self.spin.setSingleStep(0.001)
        self.spin.setSpecialValueText("required")
        self.spin.setValue(session.resolved_velocity(key).surface_velocity)
        form.addRow("Velocity (m/ns)", self.spin)
        layout.addLayout(form)

        layout.addWidget(QLabel("Saved hyperbola fits (pick one to use its velocity):"))
        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(list(_HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._fill_table()
        layout.addWidget(self.table)
        delete_row = QHBoxLayout()
        self.delete_button = QPushButton("Delete fit")
        self.delete_button.setToolTip("Remove the selected fit from this line's record.")
        self.delete_button.setEnabled(False)
        delete_row.addWidget(self.delete_button)
        delete_row.addStretch()
        layout.addLayout(delete_row)

        buttons = QDialogButtonBox()
        self.apply_button = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        self.clear_button = QPushButton("Clear override")
        buttons.addButton(self.clear_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)

        self.spin.valueChanged.connect(self._validate)
        self._validate()
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.clear_button.clicked.connect(self._on_clear)
        self.delete_button.clicked.connect(self._on_delete)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        pointer = line.velocity_from_fit
        if pointer is not None and pointer in self._fits and line.velocity is not None:
            self.select_fit(pointer)

    def _fill_table(self) -> None:
        """(Re)build the rows from the line's stored fits, shallowest first."""
        self._fits = dict(self.session.line_for_key(self.key).velocity_fits)
        self._ids = sorted(self._fits, key=lambda i: self._fits[i].t0_ns)
        self._flagged = disagreeing_fit_ids(self._fits)
        # The current index too, not just the selection: removing the current
        # row otherwise selects its neighbour, arming Delete on a fit nobody
        # chose.
        self.table.selectionModel().clear()
        self.table.setRowCount(len(self._ids))
        for row, fit_id in enumerate(self._ids):
            fit = self._fits[fit_id]
            cells = (
                f"{fit.t0_ns:.1f}",
                f"{fit.v_m_ns:.4f} ± {fit.v_stderr_m_ns:.4f}",
                f"{fit.rms_ns:.2f}",
                str(len(fit.points)),
                "disagrees with another fit" if fit_id in self._flagged else "",
            )
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))

    # ---- reading the dialog ------------------------------------------------
    def fit_id_at_row(self, row: int) -> str:
        return self._ids[row]

    def flagged_fit_ids(self) -> frozenset[str]:
        return self._flagged

    def flag_text(self, row: int) -> str:
        item = self.table.item(row, _FLAG_COLUMN)
        return item.text() if item is not None else ""

    def highlighted_fit_id(self) -> str | None:
        """The fit selected in the table, whatever the spin box now says."""
        return self._selected

    def selected_fit_id(self) -> str | None:
        """The selected fit, unless the spin box has since been moved off its
        velocity -- then the number is the user's own."""
        fit_id = self._selected
        if fit_id is None or self._cleared:
            return None
        if round(self.spin.value(), 4) != round(self._fits[fit_id].v_m_ns, 4):
            return None
        return fit_id

    def velocity(self) -> VelocityModel | None:
        if self._cleared:
            return None
        fit_id = self.selected_fit_id()
        if fit_id is not None:
            # The fit's own velocity, not the spin box's 4-dp rounding of it.
            return VelocityModel.constant(self._fits[fit_id].v_m_ns)
        return VelocityModel.constant(self.spin.value())

    # ---- driving the dialog --------------------------------------------------
    def select_fit(self, fit_id: str) -> None:
        self.table.selectRow(self._ids.index(fit_id))

    def _on_selection_changed(self) -> None:
        try:
            rows = self.table.selectionModel().selectedRows()
            self.delete_button.setEnabled(bool(rows))
            self._selected = self._ids[rows[0].row()] if rows else None
            self.fit_highlighted.emit(self._selected)
            if self._selected is not None:
                self.spin.setValue(self._fits[self._selected].v_m_ns)
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _validate(self, *_: object) -> None:
        try:
            # Zero is the "required" placeholder, and not a velocity.
            self.apply_button.setEnabled(self.spin.value() > 0)
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _on_clear(self) -> None:
        try:
            self._cleared = True
            self.accept()
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _on_delete(self) -> None:
        try:
            fit_id = self._selected
            if fit_id is None:
                return
            fit = self._fits[fit_id]
            text = (
                f"Delete the fit at {fit.t0_ns:.1f} ns "
                f"({fit.v_m_ns:.4f} ± {fit.v_stderr_m_ns:.4f} m/ns)?"
            )
            if self.session.line_for_key(self.key).velocity_from_fit == fit_id:
                text += (
                    "\n\nThis fit set the line's velocity. The velocity stays as it is "
                    "until you apply another."
                )
            answer = QMessageBox.question(self, "Delete fit", text)
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.session.remove_velocity_fit(self.key, fit_id)
            self._fill_table()
            # Selecting the fit copied its velocity into the spin box; that
            # number is gone with it.
            self.spin.setValue(self.session.resolved_velocity(self.key).surface_velocity)
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)
