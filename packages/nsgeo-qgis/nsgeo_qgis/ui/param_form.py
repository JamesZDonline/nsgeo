"""One generic parameter form, built from a step's schema().

No step name appears here. `kind` picks the editor: float and int are line
edits (so a REQUIRED field can be blank), time is a bounded number spinbox
(`TimeSpinBox`), row is a bounded whole-number spinbox (`RowSpinBox`), choice
is a combo box, curve is a label pointing at the gain strip. Commit builds the
step through the core, so the core's validation is the only validation.

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

from nsgeo.processing import (
    REQUIRED,
    ParamSpec,
    Step,
    build_step,
    get_step,
    param_visible,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QValidator, QWheelEvent
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.decimal_input import parse_decimal
from nsgeo_qgis.log import log as _log

REQUIRED_STYLE = "QLineEdit { border: 1px solid #d1702f; background: #fff8f2; }"

# What a number can look like while it is still being typed.
_PARTIAL_NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d*)?([eE][+-]?\d*)?")
UNBOUNDED_NS = 1e9


class _CommitRules:
    """What `TimeSpinBox` and `RowSpinBox` share, so the wheel rule (a
    recorded user preference) and the commit rules live once: the wheel
    scrolls the panel unless the field has focus; an arrow or wheel step is a
    finished edit (`editingFinished` does not follow one), announced on the
    class's own signal named by `_step_signal`; a typed number past the range
    is clamped to the nearest limit; and `touched` (R10, R12) says whether
    the user changed the value since the form built this field, so an
    untouched field reports the value it was built from. Qt interprets the
    display text on Return and on focus-out whether or not anything was
    typed, and reverts a cleared or partial entry without calling
    `valueFromText` at all; none of those is an edit.

    A plain mixin placed before the Qt spinbox in the bases, so `super()`
    reaches the spinbox's own `wheelEvent`, `stepBy` and `valueFromText`."""

    _step_signal = "stepped"
    touched: bool

    def _init_commit_rules(self) -> None:
        self.touched = False
        self.setKeyboardTracking(False)  # type: ignore[attr-defined]
        # The wheel scrolls the panel unless the field is the one in use.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # type: ignore[attr-defined]

    def _number(self, text: str) -> Any:
        raise NotImplementedError

    def edit_text(self, text: str) -> None:
        """Set the text as if typed, and interpret it."""
        self.lineEdit().setText(text)  # type: ignore[attr-defined]
        self.interpretText()  # type: ignore[attr-defined]

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        try:
            if event is not None and not self.hasFocus():  # type: ignore[attr-defined]
                event.ignore()  # let the panel scroll
                return
            super().wheelEvent(event)  # type: ignore[misc]
        except Exception as exc:  # a Qt override: never let it escape
            _log(f"{type(self).__name__}.wheelEvent: {exc!r}")

    def stepBy(self, steps: int) -> None:
        try:
            super().stepBy(steps)  # type: ignore[misc]  # interprets typed text first, if any
            self.touched = True
            getattr(self, self._step_signal).emit()
        except Exception as exc:  # a Qt override: never let it escape
            _log(f"{type(self).__name__}.stepBy: {exc!r}")

    def valueFromText(self, text: str) -> Any:
        try:
            if text.strip() == self.textFromValue(self.value()):  # type: ignore[attr-defined]
                return self.value()  # type: ignore[attr-defined]  # the display, not an edit (R12)
            value = self._number(text.strip())
            self.touched = True
            return min(max(value, self.minimum()), self.maximum())  # type: ignore[attr-defined]
        except Exception as exc:
            _log(f"{type(self).__name__}.valueFromText: {exc!r}")
            return self.value()  # type: ignore[attr-defined]


class TimeSpinBox(_CommitRules, QDoubleSpinBox):
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
        self._init_commit_rules()
        self._exact_range: tuple[float, float] | None = None

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

    def _number(self, text: str) -> float:
        return float(text)

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

    def textFromValue(self, value: float) -> str:
        try:
            return f"{value:g}"
        except Exception as exc:
            _log(f"TimeSpinBox.textFromValue: {exc!r}")
            return str(value)


class RowSpinBox(_CommitRules, QSpinBox):
    """A whole-number row of a step's input record, with the commit and wheel
    rules of `TimeSpinBox` (`_CommitRules`). A typed number past the range is
    clamped to the nearest limit."""

    row_stepped = pyqtSignal()
    _step_signal = "row_stepped"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRange(0, 2**31 - 1)
        self._init_commit_rules()

    def _number(self, text: str) -> int:
        return int(text)

    def validate(self, text: str, pos: int) -> tuple[QValidator.State, str, int]:
        # Any run of digits can be typed; a number past the range is clamped
        # when committed, not refused keystroke by keystroke.
        try:
            probe = text.strip()
            if probe.isascii() and probe.isdigit():
                return QValidator.State.Acceptable, text, pos
            state = QValidator.State.Intermediate if probe == "" else QValidator.State.Invalid
            return state, text, pos
        except Exception as exc:  # a Qt override: never let it escape
            _log(f"RowSpinBox.validate: {exc!r}")
            return QValidator.State.Invalid, text, pos


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
        self._row_range: tuple[int, int] | None = None
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
        row_range: tuple[int, int] | None = None,
    ) -> None:
        """Show `name`'s editors. `time_range` bounds a time field and
        `time_step` is its arrow step; neither means unbounded and 1 ns.
        `row_range` is the first and last row a row field can take; none
        means bounded only by the field's own minimum. A field tied to a
        mode (`ParamSpec.when`) is shown only while the mode is that one."""
        self.clear()
        self._row_range = row_range
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
            self._apply_visibility()
        finally:
            self._updating -= 1

    def _apply_visibility(self, *_: Any) -> None:
        """Show each field whose `when` matches the mode combo, hide the rest,
        label and editor together. Their values stay: `values()` reports every
        field. `QFormLayout.setRowVisible` is Qt 6 only."""
        try:
            modes = self._modes()
            for spec in self._specs:
                editor = self.editors.get(spec.name)
                if editor is None:
                    continue
                shown = param_visible(spec, modes)
                label = self._layout.labelForField(editor)
                if label is not None:
                    label.setVisible(shown)
                editor.setVisible(shown)
        except Exception as exc:  # a Qt slot: never let it escape
            _log(f"ParamForm._apply_visibility: {exc!r}")

    def _make_editor(self, spec: ParamSpec, value: Any) -> QWidget:
        if spec.kind == "choice":
            combo = QComboBox()
            for choice in spec.choices:
                combo.addItem(choice, choice)
            if value is not REQUIRED:
                combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.currentIndexChanged.connect(self._apply_visibility)
            combo.currentIndexChanged.connect(self._on_edited)
            combo.currentIndexChanged.connect(self.commit)
            return combo
        if spec.kind == "curve":
            self._curve_values[spec.name] = None if value is REQUIRED else value
            return QLabel("edited in the profile viewer's gain strip")
        if spec.kind == "time":
            return self._make_time_editor(spec, value)
        if spec.kind == "row":
            return self._make_row_editor(spec, value)
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

    def _make_row_editor(self, spec: ParamSpec, value: Any) -> QWidget:
        spin = RowSpinBox()
        low = int(spec.min) if spec.min is not None else 0
        high = spin.maximum()
        if self._row_range is not None:
            low, high = max(low, self._row_range[0]), self._row_range[1]
        spin.setRange(low, max(low, high))
        if value is not REQUIRED:
            spin.setValue(int(value))
            # The range may have clamped it; an untouched editor reports the
            # value it was built from.
            self._shown[spec.name] = (None, value)
        spin.valueChanged.connect(self._on_edited)
        spin.editingFinished.connect(self.commit)
        spin.row_stepped.connect(self.commit)
        return spin

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
        elif isinstance(editor, _CommitRules):
            editor.edit_text(text)
        elif isinstance(editor, QLineEdit):
            editor.setText(text)

    def show_row(self, name: str, value: int) -> None:
        """Show `value` in the row field `name` as if the form had been built
        with it: no edit, no commit. For a value the panel itself wrote."""
        editor = self.editors.get(name)
        if not isinstance(editor, RowSpinBox):
            _log(f"ParamForm.show_row: {name!r} is not a row field of {self.step_name!r}")
            return
        self._updating += 1
        try:
            editor.setValue(value)
            editor.touched = False
            self._shown[name] = (None, value)
        finally:
            self._updating -= 1

    def is_complete(self) -> bool:
        for spec in self._specs:
            editor = self.editors[spec.name]
            if isinstance(editor, QLineEdit) and not editor.text().strip():
                return False
            if spec.kind == "curve" and self._curve_values.get(spec.name) is None:
                return False
        return True

    def values(self) -> dict[str, Any]:
        """Every parameter's value, hidden ones included. A hidden field the
        user cannot see (outside the mode) that fails to read, a cleared
        box say, falls back to the value it was built with, so it cannot
        block a mode switch; a visible one raises as ever."""
        modes = self._modes()
        out: dict[str, Any] = {}
        for spec in self._specs:
            try:
                out[spec.name] = self._value_of(spec)
            except ValueError:
                if param_visible(spec, modes):
                    raise
                shown = self._shown.get(spec.name)
                if shown is not None:
                    out[spec.name] = shown[1]
                elif spec.default is not REQUIRED:
                    out[spec.name] = spec.default
                else:
                    raise
        return out

    def _modes(self) -> dict[str, Any]:
        """The value of every choice field, by name."""
        modes: dict[str, Any] = {}
        for spec in self._specs:
            editor = self.editors.get(spec.name)
            if spec.kind == "choice" and isinstance(editor, QComboBox):
                modes[spec.name] = editor.currentData()
        return modes

    def _value_of(self, spec: ParamSpec) -> Any:
        editor = self.editors[spec.name]
        if spec.kind == "choice":
            assert isinstance(editor, QComboBox)
            return editor.currentData()
        if spec.kind == "curve":
            curve_value = self._curve_values.get(spec.name)
            if curve_value is None:
                raise ValueError(f"{spec.label}: no control points yet")
            return curve_value
        if isinstance(editor, TimeSpinBox):
            shown = self._shown.get(spec.name)
            return shown[1] if shown and not editor.touched else editor.exact_value()
        if isinstance(editor, RowSpinBox):
            shown = self._shown.get(spec.name)
            return shown[1] if shown and not editor.touched else editor.value()
        assert isinstance(editor, QLineEdit)
        text = editor.text().strip()
        if not text:
            raise ValueError(f"{spec.label} is required")
        shown = self._shown.get(spec.name)
        # Unchanged text keeps the exact value it displays a rounding of:
        # committing on focus-out must not move a dragged cutoff by a sample.
        return shown[1] if shown and text == shown[0] else self._parse_number(spec, text)

    def _parse_number(self, spec: ParamSpec, text: str) -> int | float:
        # No comma-as-decimal-point guessing: "1,000" and "1,5" cannot be
        # told apart from the text alone (thousands separator vs. a
        # European decimal comma), and silently picking one reading is
        # exactly the kind of guess this form otherwise never makes. A
        # comma is reported as bad input, same as any other non-numeral.
        if spec.kind in ("int", "row"):
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
            float(text)
        except ValueError:
            raise ValueError(f"{spec.label}: {text!r} is not a number") from None
        try:
            return parse_decimal(text)
        except ValueError:
            # float() read it, so parse_decimal refused a finite-ness rule
            # (nan/inf: silently slips past a step's own validation, e.g.
            # Bandpass low_mhz=nan raises nothing) -- the message is ours.
            raise ValueError(f"{spec.label} must be a finite number, got {text!r}") from None

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
