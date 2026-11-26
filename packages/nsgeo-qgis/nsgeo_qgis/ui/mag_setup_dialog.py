"""Change setup… on a magnetometer file, from the Mag panel or the Survey panel.

Modal: a short, single decision. The file keeps its typed corrections; only its
walking setup changes (`SiteSession.change_mag_setup` holds the logic). `accept()`
checks it is still the same `Site` before it writes anything, and every slot
guards its own body and reports on the status line instead of raising.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from nsgeo.mag import MagSetup, fit_problems, missing_summary
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.mag_setup_form import MagSetupForm


class MagSetupDialog(QDialog):
    def __init__(self, session: SiteSession, grid_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._site = session.site
        self.grid_id = grid_id
        mag = session.mag_file_on(grid_id)
        if mag is None:
            raise KeyError(f"grid {grid_id!r} has no magnetometer file")
        self._mag = mag
        #: The grids whose file changed; filled on a successful Apply.
        self.changed_grids: list[str] = []
        #: Whether the last Apply used the every-file checkbox.
        self.every_file = False
        self.setWindowTitle(f"Change setup · {mag.path.name}")
        layout = QVBoxLayout(self)
        self.form = MagSetupForm("Setup")
        layout.addWidget(self.form)
        self.every_box = QCheckBox("Use this setup for every magnetometer file on the site")
        layout.addWidget(self.every_box)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox()
        self.apply_button = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.form.set_setup(mag.setup)
        self._refresh()
        self.form.changed.connect(self._on_setup_changed)
        self.every_box.toggled.connect(self._on_setup_changed)

    def _same_site(self) -> bool:
        return self.session.is_open and self.session.site is self._site

    def _setup_or_none(self) -> tuple[MagSetup | None, str]:
        try:
            return self.form.setup(), ""
        except ValueError as exc:
            return None, str(exc)

    def _problems(self, setup: MagSetup) -> list[str]:
        mag = self._mag
        return fit_problems(setup, mag.n_rows, mag.n_readings, self.session.grid(self.grid_id))

    def _other_misfits(self, setup: MagSetup) -> list[str]:
        """With the every-file box ticked, each OTHER file's problems against its own
        grid, prefixed by the file name; [] otherwise."""
        if not self.every_box.isChecked():
            return []
        lines: list[str] = []
        for other in self.session.mag_files():
            if other.grid_id == self.grid_id:
                continue
            grid = self.session.grid(other.grid_id)
            lines += [
                f"{other.path.name}: {p}"
                for p in fit_problems(setup, other.n_rows, other.n_readings, grid)
            ]
        return lines

    def _on_setup_changed(self, *_: Any) -> None:
        try:
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise; the status line reports
            self.status.setText(f"could not update the setup: {exc}")

    def _refresh(self) -> None:
        setup, error = self._setup_or_none()
        if setup is None:
            self.status.setText(error)
            return
        lines = [missing_summary(dataclasses.replace(self._mag, setup=setup).readings())]
        if self._same_site():
            lines += self._problems(setup)
            n_other = len({m.split(": ", 1)[0] for m in self._other_misfits(setup)})
            if n_other:
                lines.append(f"{n_other} other file(s) would not fit with this setup.")
        self.status.setText("\n".join(lines))

    def accept(self) -> None:
        try:
            self._apply()
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise; the status line reports
            self.status.setText(f"could not change the setup: {exc}")

    def _apply(self) -> None:
        if not self._same_site() or self.session.mag_file_on(self.grid_id) is None:
            self.status.setText("The site changed; nothing was changed.")
            return
        setup, error = self._setup_or_none()
        if setup is None:
            self.status.setText(error)
            return
        problems = self._problems(setup)
        others = self._other_misfits(setup)
        if others:
            misfits = [f"{self._mag.path.name}: {p}" for p in problems] + others
            n_files = len({m.split(": ", 1)[0] for m in misfits})
            text = (
                f"{n_files} file(s) do not fit their grids:\n"
                + "\n".join(misfits)
                + "\nApply anyway? Nothing is cropped or stretched."
            )
        elif problems:
            text = (
                f"{self._mag.path.name} does not fit grid {self.grid_id} with this setup:\n"
                + "\n".join(problems)
                + "\nApply anyway? Nothing is cropped or stretched."
            )
        else:
            text = ""
        if text:
            answer = QMessageBox.question(
                self,
                "File does not fit its grid",
                text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.every_file = self.every_box.isChecked()
        self.changed_grids = self.session.change_mag_setup(
            self.grid_id, setup, every_file=self.every_file
        )
        super().accept()
