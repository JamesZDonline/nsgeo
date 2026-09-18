"""One generic parameter form, built from a step's schema().

No step name appears here. `kind` picks the editor: float and int are line
edits (so a REQUIRED field can be blank), choice is a combo box, curve is a
label pointing at the gain strip. Commit builds the step through the core,
so the core's validation is the only validation.

`message` lives in its own outer layout, never as a row inside the
`QFormLayout` that `clear()` tears down. `QFormLayout.removeRow()` genuinely
deletes the row's widgets (verified directly against a live QFormLayout, not
assumed), so a `message` label added as a *row* would be destroyed the first
time `clear()` runs against a form that already has rows -- and the very next
`set_step()` or `commit()` on that same instance (every subsequent row
selection or edit against `ProcessingDock`'s one persistent form) would raise
`RuntimeError: wrapped C/C++ object of type QLabel has been deleted` the
moment it touches `self.message` again.
"""

from __future__ import annotations

import math
from typing import Any

from nsgeo.processing import REQUIRED, ParamSpec, Step, build_step, get_step
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

REQUIRED_STYLE = "QLineEdit { border: 1px solid #d1702f; background: #fff8f2; }"


class ParamForm(QWidget):
    committed = pyqtSignal(dict)
    error = pyqtSignal(str)
    edited = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        # A separate, never-cleared layout: see the module docstring for why
        # `message` cannot be a row of `self._layout`.
        self._layout = QFormLayout()
        outer.addLayout(self._layout)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #b35c00;")
        outer.addWidget(self.message)
        self.editors: dict[str, QWidget] = {}
        self._specs: tuple[ParamSpec, ...] = ()
        # Keyed by param name, not one shared slot: a step with two
        # curve-kind params (none exist yet, but the schema allows it)
        # would otherwise silently overwrite one's value with the other's.
        self._curve_values: dict[str, Any] = {}
        self.step_name: str | None = None
        # A depth counter, not a bool (matching ProcessingDock._updating, for
        # the same reason): set_step() calls clear() before taking its own
        # guard, so the two are already nested in one call today, and a
        # plain set/clear flag would let clear()'s own `finally` drop the
        # guard while set_step()'s surrounding frame still expects it up --
        # only harmless right now because clear() runs *before* set_step()
        # takes its guard, not after or during. A counter only reaches zero
        # when the outermost caller finishes, regardless of ordering.
        self._updating = 0

    # ---- building ---------------------------------------------------------
    def clear(self) -> None:
        # Guarded like set_step()'s own build loop: removeRow() destroying a
        # combo box mid-teardown can fire currentIndexChanged, which is
        # wired to _on_edited/commit -- without this guard those would run
        # against a half-cleared self.editors/self._specs.
        self._updating += 1
        try:
            while self._layout.rowCount():
                self._layout.removeRow(0)
            self.editors = {}
            self._specs = ()
            self._curve_values = {}
            self.step_name = None
            self.message.setText("")
        finally:
            self._updating -= 1

    def set_step(self, name: str, params: dict[str, Any] | None = None) -> None:
        self.clear()
        self.step_name = name
        self._specs = get_step(name).schema()
        self._updating += 1
        try:
            for spec in self._specs:
                value = params[spec.name] if params and spec.name in params else spec.default
                editor = self._make_editor(spec, value)
                self.editors[spec.name] = editor
                label = f"{spec.label} ({spec.unit})" if spec.unit else spec.label
                editor.setToolTip(spec.help)
                self._layout.addRow(label, editor)
        finally:
            self._updating -= 1

    def _make_editor(self, spec: ParamSpec, value: Any) -> QWidget:
        if spec.kind == "choice":
            combo = QComboBox()
            for choice in spec.choices:
                combo.addItem(choice, choice)
            if value is not REQUIRED:
                combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.currentIndexChanged.connect(self._on_edited)
            combo.currentIndexChanged.connect(self.commit)
            return combo
        if spec.kind == "curve":
            self._curve_values[spec.name] = None if value is REQUIRED else value
            return QLabel("edited in the profile viewer's gain strip")
        edit = QLineEdit()
        if value is REQUIRED:
            edit.setPlaceholderText("required")
            edit.setStyleSheet(REQUIRED_STYLE)
        else:
            edit.setText(f"{value:g}" if isinstance(value, float) else str(value))
        edit.textChanged.connect(self._on_edited)
        edit.editingFinished.connect(self.commit)
        return edit

    def _on_edited(self, *_: Any) -> None:
        if not self._updating:
            self.edited.emit()

    # ---- values -------------------------------------------------------
    def set_value(self, name: str, text: str) -> None:
        editor = self.editors[name]
        if isinstance(editor, QComboBox):
            index = editor.findData(text)
            if index < 0:
                raise ValueError(f"{text!r} is not one of this field's choices")
            editor.setCurrentIndex(index)
        elif isinstance(editor, QLineEdit):
            editor.setText(text)

    def is_complete(self) -> bool:
        for spec in self._specs:
            editor = self.editors[spec.name]
            if isinstance(editor, QLineEdit) and not editor.text().strip():
                return False
            if spec.kind == "curve" and self._curve_values.get(spec.name) is None:
                return False
        return True

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for spec in self._specs:
            editor = self.editors[spec.name]
            if spec.kind == "choice":
                assert isinstance(editor, QComboBox)
                out[spec.name] = editor.currentData()
            elif spec.kind == "curve":
                curve_value = self._curve_values.get(spec.name)
                if curve_value is None:
                    raise ValueError(f"{spec.label}: no control points yet")
                out[spec.name] = curve_value
            else:
                assert isinstance(editor, QLineEdit)
                text = editor.text().strip()
                if not text:
                    raise ValueError(f"{spec.label} is required")
                out[spec.name] = self._parse_number(spec, text)
        return out

    def _parse_number(self, spec: ParamSpec, text: str) -> int | float:
        # No comma-as-decimal-point guessing: "1,000" and "1,5" cannot be
        # told apart from the text alone (thousands separator vs. a
        # European decimal comma), and silently picking one reading is
        # exactly the kind of guess this form otherwise never makes. A
        # comma is reported as bad input, same as any other non-numeral.
        if spec.kind == "int":
            try:
                return int(text)
            except ValueError:
                pass
            try:
                probe = float(text)
            except ValueError:
                pass
            else:
                if not math.isfinite(probe):
                    # nan/inf/-inf all parse as a "number" via float() but
                    # are not whole numbers either -- report the more
                    # useful reason, not "must be a whole number".
                    raise ValueError(
                        f"{spec.label} must be a finite number, got {text!r}"
                    ) from None
                # A real number, just not a whole one -- "is not a number"
                # would be actively wrong here.
                raise ValueError(f"{spec.label} must be a whole number, got {text!r}") from None
            raise ValueError(f"{spec.label}: {text!r} is not a number") from None
        try:
            value = float(text)
        except ValueError:
            raise ValueError(f"{spec.label}: {text!r} is not a number") from None
        if not math.isfinite(value):
            # `float("nan")`/`float("inf")` succeed in Python but are not
            # valid values for a physical parameter: nan silently slips
            # past a step's own validation entirely (confirmed directly
            # against Bandpass: low_mhz=nan raises nothing, and produces
            # different, finite, arbitrary output rather than an error) --
            # the parser is the right place to refuse it instead.
            raise ValueError(f"{spec.label} must be a finite number, got {text!r}") from None
        return value

    def build(self) -> Step | None:
        """The step, or None with `message` and `error` set."""
        if self.step_name is None:
            return None
        try:
            step = build_step(self.step_name, **self.values())
        except (ValueError, TypeError) as exc:
            self.message.setText(str(exc))
            self.error.emit(str(exc))
            return None
        self.message.setText("")
        return step

    def commit(self, *_: Any) -> None:
        if self._updating:
            return
        step = self.build()
        if step is not None:
            self.committed.emit(step.params)
