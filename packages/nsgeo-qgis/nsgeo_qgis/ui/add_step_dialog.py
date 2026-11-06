"""Collect REQUIRED parameters before a step enters the stack.

Blank fields unless the caller seeds one, header facts as read-only
reference, OK disabled until the core builds the step and applies it to a
one-trace slice of the current radargram without error. Nothing is guessed
on the user's behalf -- a seed is a number the user can see and overwrite,
and it comes from the line itself, not from this dialog.
"""

from __future__ import annotations

from typing import Any

from nsgeo.io import DztHeader
from nsgeo.processing import Radargram, Step, nyquist_mhz, step_title
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from nsgeo_qgis.ui.param_form import ParamForm


def header_facts(header: DztHeader) -> str:
    nyquist = nyquist_mhz(header.dt_ns)
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
        params: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Add step: {step_title(step_name)}")
        self.radargram = radargram
        layout = QVBoxLayout(self)
        self.form = ParamForm(self)
        # A seed, not a guess: the caller passes a value the user can see
        # and overwrite, and `ParamForm.set_step` has always taken one.
        self.form.set_step(step_name, params)
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
            except Exception as exc:
                # Broad on purpose: this is a Qt slot (`edited` -> `_validate`),
                # and a step's `apply` is arbitrary third-party-shaped code we
                # do not control the exception types of. Catching only
                # ValueError would let anything else propagate out of a slot,
                # where PyQt swallows it to stderr and leaves `ok_button`
                # exactly as it was before -- possibly enabled, on a step that
                # cannot actually run.
                self.form.message.setText(str(exc))
                self.ok_button.setEnabled(False)
                return
        self.ok_button.setEnabled(True)

    def result_step(self) -> Step | None:
        return self.form.build()
