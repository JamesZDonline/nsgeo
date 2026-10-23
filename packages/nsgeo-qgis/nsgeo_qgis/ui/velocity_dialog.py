"""The line velocity dialog: type a number, or take one from a saved fit.

`velocity()` is the whole answer: a model to apply, or `None` for "remove the
override". `selected_fit_id()` says which saved fit that number came from, and
is `None` once the user types something else, because a typed number has no
fit behind it.

Fits are listed by t0 (shallowest first). A pair whose velocities differ by
more than sqrt(s1^2 + s2^2) is flagged. That is a passive diagnostic, not a
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
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.session import SiteSession

_HEADERS = ("t0 (ns)", "v ± σ (m/ns)", "rms (ns)", "points", "")
_FLAG_COLUMN = 4


def disagreeing_fit_ids(fits: Mapping[str, StoredFit]) -> frozenset[str]:
    """Ids of every fit that disagrees with at least one other: velocities
    further apart than the two standard errors combined in quadrature."""
    items = list(fits.items())
    flagged: set[str] = set()
    for i, (id_a, a) in enumerate(items):
        for id_b, b in items[i + 1 :]:
            combined = math.hypot(a.v_stderr_m_ns, b.v_stderr_m_ns)
            if abs(a.v_m_ns - b.v_m_ns) > combined:
                flagged.update((id_a, id_b))
    return frozenset(flagged)


class VelocityDialog(QDialog):
    def __init__(self, session: SiteSession, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.key = key
        self.setWindowTitle(f"Velocity · {key}")
        line = session.line_for_key(key)
        self._fits = dict(line.velocity_fits)
        self._ids = sorted(self._fits, key=lambda i: self._fits[i].t0_ns)
        self._flagged = disagreeing_fit_ids(self._fits)
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
        self.table = QTableWidget(len(self._ids), len(_HEADERS))
        self.table.setHorizontalHeaderLabels(list(_HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
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
        layout.addWidget(self.table)

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
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        pointer = line.velocity_from_fit
        if pointer is not None and pointer in self._fits and line.velocity is not None:
            self.select_fit(pointer)

    # ---- reading the dialog ------------------------------------------------
    def fit_id_at_row(self, row: int) -> str:
        return self._ids[row]

    def flagged_fit_ids(self) -> frozenset[str]:
        return self._flagged

    def flag_text(self, row: int) -> str:
        item = self.table.item(row, _FLAG_COLUMN)
        return item.text() if item is not None else ""

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
            if not rows:
                self._selected = None
                return
            self._selected = self._ids[rows[0].row()]
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
