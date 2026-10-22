"""One generic parameter form, built from a step's schema().

No step name appears here. `kind` picks the editor: float and int are line
edits (so a REQUIRED field can be blank), time is a bounded number spinbox
(`TimeSpinBox`), choice is a combo box, curve is a label pointing at the gain
strip. Commit builds the step through the core,
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
import re
from typing import Any

from nsgeo.processing import REQUIRED, ParamSpec, Step, build_step, get_step
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QValidator
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.log import log as _log

REQUIRED_STYLE = "QLineEdit { border: 1px solid #d1702f; background: #fff8f2; }"

# What a number can look like while it is still being typed.
_PARTIAL_NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d*)?([eE][+-]?\d*)?")
UNBOUNDED_NS = 1e9


class TimeSpinBox(QDoubleSpinBox):
    """A number field bounded to a range that still lets any number be typed.

    A stock `QDoubleSpinBox` refuses keystrokes that would leave the range
    and reverts a committed out-of-range value to the old one. Here every
    finite number is accepted as text and clamped to the nearest limit when
    committed, so `-20` or `500` can be typed and end at a limit. The text is
    shown the way the form's other number fields are (`:g`); `decimals` is
    high so a value typed inside the range is kept as typed, not rounded to
    a sample or to a few places.
    """

    # An arrow or wheel step is a finished edit: `editingFinished` does not
    # follow one.
    stepped = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDecimals(10)
        self.setRange(-UNBOUNDED_NS, UNBOUNDED_NS)
        self.setKeyboardTracking(False)
        # `touched`: the user typed or stepped since the form built this
        # field (R10); an untouched field reports the value it was built
        # from, whatever the range or the display rounding say.
        self.touched = False
        # Text typed and not yet interpreted. Qt interprets the display text
        # on Return and on focus-out whether or not anything was typed, and
        # the display is a 6-digit rounding: only typed text may replace
        # the value.
        self._text_dirty = False
        self._exact_range: tuple[float, float] | None = None
        self.lineEdit().textEdited.connect(self._on_text_edited)
        self.editingFinished.connect(self._on_finished)

    def set_exact_range(self, low: float, high: float) -> None:
        """`setRange` rounds the limits to `decimals()`; the exact ones are
        kept so a snap reports them, not their rounding."""
        self.setRange(low, high)
        self._exact_range = (low, high)

    def exact_value(self) -> float:
        value = self.value()
        if self._exact_range is not None:
            low, high = self._exact_range
            if value == self.minimum():
                return low
            if value == self.maximum():
                return high
        return value

    def edit_text(self, text: str) -> None:
        """Set the text as if typed, and interpret it."""
        self.lineEdit().setText(text)
        self.touched = self._text_dirty = True
        self.interpretText()

    def _on_text_edited(self, _text: str) -> None:
        self.touched = self._text_dirty = True

    def _on_finished(self) -> None:
        self._text_dirty = False

    def validate(self, text: str, pos: int) -> tuple[QValidator.State, str, int]:
        try:
            probe = text.strip()
            try:
                finite = math.isfinite(float(probe))
            except ValueError:
                state = (
                    QValidator.State.Intermediate
                    if _PARTIAL_NUMBER.fullmatch(probe)
                    else QValidator.State.Invalid
                )
            else:
                state = QValidator.State.Acceptable if finite else QValidator.State.Invalid
            return state, text, pos
        except Exception as exc:  # a Qt override: never let it escape
            _log(f"TimeSpinBox.validate: {exc!r}")
            return QValidator.State.Invalid, text, pos

    def stepBy(self, steps: int) -> None:
        try:
            super().stepBy(steps)  # interprets typed text first, if any
            self.touched = True
            self._text_dirty = False
            self.stepped.emit()
        except Exception as exc:  # a Qt override: never let it escape
            _log(f"TimeSpinBox.stepBy: {exc!r}")

    def valueFromText(self, text: str) -> float:
        try:
            if not self._text_dirty:
                return self.value()
            value = float(text.strip())
            return min(max(value, self.minimum()), self.maximum())
        except Exception as exc:
            _log(f"TimeSpinBox.valueFromText: {exc!r}")
            return self.value()

    def textFromValue(self, value: float) -> str:
        try:
            return f"{value:g}"
        except Exception as exc:
            _log(f"TimeSpinBox.textFromValue: {exc!r}")
            return str(value)


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
        # name -> (text shown, value it was built from) for numeric editors.
        # The text is rounded (`:g`); an editor left alone must report the
        # exact value, not its rounding (see `values`).
        self._shown: dict[str, tuple[Any, Any]] = {}
        self._time_range: tuple[float, float] | None = None
        self._time_step = 1.0
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
            self._shown = {}
            self.step_name = None
            self.message.setText("")
        finally:
            self._updating -= 1

    def set_step(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        time_range: tuple[float, float] | None = None,
        time_step: float | None = None,
    ) -> None:
        """Show `name`'s editors. `time_range` bounds a time field and
        `time_step` is its arrow step; neither means unbounded and 1 ns."""
        self.clear()
        self._time_range = time_range
        self._time_step = time_step if time_step else 1.0
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
        if spec.kind == "time":
            return self._make_time_editor(spec, value)
        edit = QLineEdit()
        if value is REQUIRED:
            edit.setPlaceholderText("required")
            edit.setStyleSheet(REQUIRED_STYLE)
        else:
            edit.setText(f"{value:g}" if isinstance(value, float) else str(value))
            self._shown[spec.name] = (edit.text(), value)
        edit.textChanged.connect(self._on_edited)
        edit.editingFinished.connect(self.commit)
        return edit

    def _make_time_editor(self, spec: ParamSpec, value: Any) -> QWidget:
        spin = TimeSpinBox()
        if self._time_range is not None:
            spin.set_exact_range(*self._time_range)
        spin.setSingleStep(self._time_step)
        if value is not REQUIRED:
            spin.setValue(float(value))
            # `setValue` rounds to `decimals()` and clamps to the range, and
            # the text is 6 digits; an untouched editor reports the exact
            # value it was built from, in or out of the range (R3, R10).
            self._shown[spec.name] = (None, value)
        spin.valueChanged.connect(self._on_edited)
        spin.editingFinished.connect(self.commit)
        spin.stepped.connect(self.commit)
        return spin

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
        elif isinstance(editor, QDoubleSpinBox):
            editor.edit_text(text)
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
            elif isinstance(editor, QDoubleSpinBox):
                shown = self._shown.get(spec.name)
                assert isinstance(editor, TimeSpinBox)
                out[spec.name] = shown[1] if shown and not editor.touched else editor.exact_value()
            else:
                assert isinstance(editor, QLineEdit)
                text = editor.text().strip()
                if not text:
                    raise ValueError(f"{spec.label} is required")
                shown = self._shown.get(spec.name)
                # Unchanged text keeps the exact value it displays a
                # rounding of: committing on focus-out must not move a
                # dragged cutoff by a sample.
                out[spec.name] = (
                    shown[1] if shown and text == shown[0] else self._parse_number(spec, text)
                )
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
