"""Collect REQUIRED parameters before a step enters the stack.

Blank fields, header facts as read-only reference, OK disabled until the
core builds the step and applies it to a one-trace slice of the current
radargram without error. Nothing is guessed on the user's behalf.
"""

from __future__ import annotations

from typing import Any

from nsgeo.io.dzt import DztHeader
from nsgeo.processing import Radargram
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from nsgeo_qgis.ui.param_form import ParamForm


def header_facts(header: DztHeader) -> str:
    nyquist = 500.0 / header.dt_ns
    return (
        f"From this file's header: antenna {header.antenna or '?'} · sample interval "
        f"{header.dt_ns:.4f} ns · Nyquist {nyquist:.0f} MHz · {header.n_samples} samples"
    )


class AddStepDialog(QDialog):
    def __init__(
        self,
        step_name: str,
        header: DztHeader | None = None,
        radargram: Radargram | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Add step: {step_name}")
        self.radargram = radargram
        layout = QVBoxLayout(self)
        self.form = ParamForm(self)
        self.form.set_step(step_name)
        layout.addWidget(self.form)
        self.facts = QLabel(header_facts(header) if header is not None else "")
        self.facts.setWordWrap(True)
        layout.addWidget(self.facts)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.form.edited.connect(self._validate)
        self._validate()

    def _validate(self, *_: Any) -> None:
        if not self.form.is_complete():
            self.form.message.setText("")
            self.ok_button.setEnabled(False)
            return
        step = self.form.build()
        if step is None:
            self.ok_button.setEnabled(False)
            return
        if self.radargram is not None:
            probe = self.radargram.replace(data=self.radargram.data[:, :1])
            try:
                step.apply(probe)
            except ValueError as exc:
                self.form.message.setText(str(exc))
                self.ok_button.setEnabled(False)
                return
        self.ok_button.setEnabled(True)

    def result_step(self) -> Any:
        return self.form.build()
