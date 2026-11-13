"""The New surface dialog (M16 B Task 5; spec §5.3; the approved mockup's step 2).

It names a surface from the picks selected on the map. The selection's refusal and the note
about picks that will move out of other surfaces come from `Surfaces.check` and `surface_plan`;
Create and build stays disabled while a refusal or a name problem stands, and the name is
checked as it is typed. Settings are folded away and show their values.
"""

from __future__ import annotations

import traceback
from collections.abc import Iterable

from nsgeo.slices import SurfaceSettings
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.surface_plan import move_note, name_refusal, resolution_hint, settings_summary
from nsgeo_qgis.surfaces import SelectionCheck
from nsgeo_qgis.ui.surface_settings_form import SurfaceSettingsForm

_RED = "color: #b22222;"


class NewSurfaceDialog(QDialog):
    def __init__(
        self,
        check: SelectionCheck,
        n_label: str,
        parent: QWidget | None = None,
        *,
        taken: Iterable[str] = (),
        default_name: str = "",
        hint: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("New surface")
        self.check = check
        self._taken = list(taken)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Name"))
        self.name_edit = QLineEdit(default_name)
        self.name_edit.setMaxLength(200)
        layout.addWidget(self.name_edit)
        self.name_problem = _wrapped(_RED)
        layout.addWidget(self.name_problem)
        self.count_label = _wrapped()
        self.count_label.setText(n_label)
        layout.addWidget(self.count_label)
        self.refusal_label = _wrapped(_RED)
        self.refusal_label.setText(check.refusal)
        self.refusal_label.setVisible(bool(check.refusal))
        layout.addWidget(self.refusal_label)
        note = "" if check.refusal else move_note(check.moving, check.n, check.left)
        self.note_label = _wrapped()
        self.note_label.setText(note)
        self.note_label.setVisible(bool(note))
        layout.addWidget(self.note_label)

        self.settings_button = QToolButton()
        self.settings_button.setCheckable(True)
        self.settings_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.settings_button.setArrowType(Qt.ArrowType.RightArrow)
        self.settings_button.setText("Settings")
        self.settings_button.setAutoRaise(True)
        layout.addWidget(self.settings_button)
        self.summary_label = _wrapped()
        layout.addWidget(self.summary_label)
        self.form = SurfaceSettingsForm()
        self.form.setVisible(False)
        layout.addWidget(self.form)
        self.hint_label = hint_label = _wrapped()
        hint_label.setText(hint or resolution_hint(None))
        layout.addWidget(hint_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.create_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.create_button.setText("Create and build")
        self.create_button.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.settings_button.toggled.connect(self._on_settings_toggled)
        self.form.settings_edited.connect(self._refresh)
        self.name_edit.textChanged.connect(lambda _t: self._refresh())
        self._refresh()

    def _on_settings_toggled(self, shown: bool) -> None:
        try:
            self.settings_button.setArrowType(
                Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow
            )
            self.form.setVisible(shown)
            self.summary_label.setVisible(not shown)
        except Exception:  # noqa: BLE001 -- a Qt slot
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Warning)

    def _refresh(self) -> None:
        try:
            self.summary_label.setText(settings_summary(self.form.settings()))
            typed = self.name_edit.text()
            # An empty box is not scolded until something is typed; Create stays off either way.
            problem = name_refusal(typed, self._taken)
            self.name_problem.setText(problem if typed else "")
            self.name_problem.setVisible(bool(typed) and bool(problem))
            self.create_button.setEnabled(not self.check.refusal and not problem)
        except Exception:  # noqa: BLE001 -- a Qt slot
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Warning)

    def name(self) -> str:
        return self.name_edit.text()

    def settings(self) -> SurfaceSettings:
        return self.form.settings()


def _wrapped(style: str = "") -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if style:
        label.setStyleSheet(style)
    return label
