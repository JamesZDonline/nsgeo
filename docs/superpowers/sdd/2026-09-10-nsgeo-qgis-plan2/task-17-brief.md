### Task 17: Schema-driven parameter form and the add-step dialog

One generic form built from `schema()`. The same widget edits the selected step in the dock and collects `REQUIRED` values in a modal before a step enters the stack. The modal validates by building the step and applying it to a one-trace slice of the current radargram, which is how Nyquist and window errors surface before anything is added.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/add_step_dialog.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py`

**Interfaces:**
- Consumes: `get_step`, `build_step`, `ParamSpec`, `REQUIRED`, `identity_curve`, `Radargram`, `DztHeader`
- Produces: `ParamForm(parent=None)` with `set_step(name, params=None)`, `clear()`, `set_value(name, text)`, `values() -> dict`, `is_complete() -> bool`, `build()`, `commit()`, `editors: dict[str, QWidget]`, `message: QLabel`, `step_name`, signals `committed(dict)`, `error(str)`, `edited()`; `AddStepDialog(step_name, header=None, radargram=None, parent=None)` with `form`, `ok_button`, `facts: QLabel`, `result_step()`; `ProcessingDock` gains `form: ParamForm`, `build_add_dialog(name) -> AddStepDialog`, `append_from_dialog(dialog)`, `add_step_with_dialog(name)`, `time_axis() -> tuple[float, float, int]`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtWidgets import QComboBox, QLineEdit

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.add_step_dialog import AddStepDialog
from nsgeo_qgis.ui.param_form import ParamForm
from nsgeo_qgis.ui.processing_dock import ProcessingDock

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


def test_form_builds_editors_from_the_schema(qgis_app):
    f = ParamForm()
    f.set_step("time_zero")
    assert set(f.editors) == {"mode", "sample", "threshold"}
    assert isinstance(f.editors["mode"], QComboBox)
    assert isinstance(f.editors["sample"], QLineEdit)
    assert f.values() == {"mode": "first_break", "sample": 0, "threshold": 0.2}


def test_form_shows_current_values_and_commits_new_ones(qgis_app):
    f = ParamForm()
    f.set_step("gain_agc", build_step("gain_agc", window_ns=12.0).params)
    assert f.editors["window_ns"].text() == "12"  # floats are shown with :g
    got = []
    f.committed.connect(got.append)
    f.set_value("window_ns", "25")
    f.commit()
    assert got == [{"window_ns": 25.0, "target": 1.0, "eps": 1e-12}]


def test_form_reports_bad_input_instead_of_raising(qgis_app):
    f = ParamForm()
    f.set_step("dewow")
    errors = []
    f.error.connect(errors.append)
    f.set_value("window_ns", "abc")
    f.commit()
    assert errors and "window" in errors[0].lower()
    assert "window" in f.message.text().lower()


def test_required_fields_start_blank_and_block_completion(qgis_app):
    f = ParamForm()
    f.set_step("bandpass")
    assert f.editors["low_mhz"].text() == "" and f.editors["taper_frac"].text() == "0.25"
    assert not f.is_complete()
    f.set_value("low_mhz", "100")
    f.set_value("high_mhz", "600")
    assert f.is_complete()
    assert f.build().params["high_mhz"] == 600.0


def test_add_step_dialog_shows_header_facts_and_validates_against_nyquist(qgis_app, tmp_path):
    p = synthetic_dzt(tmp_path, "L.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    from nsgeo.processing import Radargram

    rg = Radargram.from_profile(line.load()[0])
    d = AddStepDialog("bandpass", header=line.header, radargram=rg)
    assert "HS350US" in d.facts.text() and "Nyquist" in d.facts.text()
    assert not d.ok_button.isEnabled()
    d.form.set_value("low_mhz", "100")
    d.form.set_value("high_mhz", "5000")  # above the ~2309 MHz Nyquist
    assert not d.ok_button.isEnabled() and "Nyquist" in d.form.message.text()
    d.form.set_value("high_mhz", "600")
    assert d.ok_button.isEnabled()
    step = d.result_step()
    assert step.name == "bandpass" and step.params["low_mhz"] == 100.0


@pytest.fixture
def opened(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProcessingDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    return session, dock, key


def test_dock_form_edits_the_selected_step_through_replace_step(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    dock.list.setCurrentRow(0)
    assert dock.form.step_name == "dewow"
    before = session.stack_for(key).entries[0][0]
    dock.form.set_value("window_ns", "7.5")
    dock.form.commit()
    after = session.stack_for(key).entries[0][0]
    assert after is not before and after.params["window_ns"] == 7.5


def test_dock_adds_required_steps_through_the_dialog(opened):
    session, dock, key = opened
    dialog = dock.build_add_dialog("bandpass")
    dialog.form.set_value("low_mhz", "100")
    dialog.form.set_value("high_mhz", "600")
    dock.append_from_dialog(dialog)
    assert [s.name for s, _ in session.stack_for(key).entries] == ["bandpass"]


def test_dock_seeds_a_curve_step_with_the_identity(opened):
    session, dock, key = opened
    dock.add_step_with_dialog("gain_curve")
    step = session.stack_for(key).entries[0][0]
    t0, dt, n = dock.time_axis()
    assert step.params["points"] == [[t0, 0.0], [t0 + dt * (n - 1), 0.0]]
    assert t0 == pytest.approx(-11.086, abs=1e-3)
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.add_step_dialog'`

- [ ] **Step 3: Implement the form**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py`:

```python
"""One generic parameter form, built from a step's schema().

No step name appears here. `kind` picks the editor: float and int are line
edits (so a REQUIRED field can be blank), choice is a combo box, curve is a
label pointing at the gain strip. Commit builds the step through the core,
so the core's validation is the only validation.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing import REQUIRED, ParamSpec, build_step, get_step
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QWidget

REQUIRED_STYLE = "QLineEdit { border: 1px solid #d1702f; background: #fff8f2; }"


class ParamForm(QWidget):
    committed = pyqtSignal(dict)
    error = pyqtSignal(str)
    edited = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 0)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #b35c00;")
        self.editors: dict[str, QWidget] = {}
        self._specs: tuple[ParamSpec, ...] = ()
        self._curve_value: Any = None
        self.step_name: str | None = None
        self._updating = False

    # ---- building ---------------------------------------------------------
    def clear(self) -> None:
        while self._layout.rowCount():
            self._layout.removeRow(0)
        self.editors = {}
        self._specs = ()
        self._curve_value = None
        self.step_name = None
        self.message.setText("")

    def set_step(self, name: str, params: dict[str, Any] | None = None) -> None:
        self.clear()
        self.step_name = name
        self._specs = get_step(name).schema()
        self._updating = True
        try:
            for spec in self._specs:
                value = params[spec.name] if params and spec.name in params else spec.default
                editor = self._make_editor(spec, value)
                self.editors[spec.name] = editor
                label = f"{spec.label} ({spec.unit})" if spec.unit else spec.label
                editor.setToolTip(spec.help)
                self._layout.addRow(label, editor)
            self._layout.addRow(self.message)
        finally:
            self._updating = False

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
            self._curve_value = None if value is REQUIRED else value
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

    # ---- values -----------------------------------------------------------
    def set_value(self, name: str, text: str) -> None:
        editor = self.editors[name]
        if isinstance(editor, QComboBox):
            editor.setCurrentIndex(max(0, editor.findData(text)))
        elif isinstance(editor, QLineEdit):
            editor.setText(text)

    def is_complete(self) -> bool:
        for spec in self._specs:
            editor = self.editors[spec.name]
            if isinstance(editor, QLineEdit) and not editor.text().strip():
                return False
            if spec.kind == "curve" and self._curve_value is None:
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
                if self._curve_value is None:
                    raise ValueError(f"{spec.label}: no control points yet")
                out[spec.name] = self._curve_value
            else:
                assert isinstance(editor, QLineEdit)
                text = editor.text().strip().replace(",", ".")
                if not text:
                    raise ValueError(f"{spec.label} is required")
                try:
                    out[spec.name] = int(text) if spec.kind == "int" else float(text)
                except ValueError:
                    raise ValueError(f"{spec.label}: {text!r} is not a number") from None
        return out

    def build(self) -> Any:
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
```

- [ ] **Step 4: Implement the dialog**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/add_step_dialog.py`:

```python
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
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
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
```

- [ ] **Step 5: Put the form in the dock and route required steps**

In `processing_dock.py`, add imports `from nsgeo.processing import Radargram, get_step` (extend the existing line) and `from nsgeo_qgis.lookup import identity_curve`, `from nsgeo_qgis.ui.add_step_dialog import AddStepDialog`, `from nsgeo_qgis.ui.param_form import ParamForm`. In `__init__`, after `self.form_area`:

```python
        self.form = ParamForm(body)
        self.form_area.addWidget(self.form)
        self.form.committed.connect(self._on_form_committed)
        self.step_selected.connect(self._show_form)
        self.add_step_requested.connect(self.add_step_with_dialog)
```

and add these methods:

```python
    def _show_form(self, row: int) -> None:
        key = self.key()
        if key is None or row < 0:
            self.form.clear()
            return
        step, _ = self.session.stack_for(key).entries[row]
        self.form.set_step(step.name, step.params)

    def _on_form_committed(self, params: dict[str, Any]) -> None:
        key = self.key()
        row = self.list.currentRow()
        if key is None or row < 0 or self.form.step_name is None:
            return
        current = self.session.stack_for(key).entries[row][0]
        if current.params == params:
            return
        self.session.replace_step(key, row, build_step(self.form.step_name, **params))

    def time_axis(self) -> tuple[float, float, int]:
        """(t0_ns, dt_ns, n_samples) of the current line: the stack's source
        when loaded, else the header."""
        key = self.key()
        assert key is not None
        source = self.session.stack_for(key).source
        if source is not None:
            return source.t0_ns, source.dt_ns, source.n_samples
        h = self.session.line_for_key(key).header
        return h.position_ns, h.dt_ns, h.n_samples

    def build_add_dialog(self, name: str) -> AddStepDialog:
        key = self.key()
        assert key is not None
        line = self.session.line_for_key(key)
        return AddStepDialog(name, header=line.header, radargram=self.session.stack_for(key).source, parent=self)

    def append_from_dialog(self, dialog: AddStepDialog) -> None:
        key = self.key()
        step = dialog.result_step()
        if key is None or step is None:
            return
        self.session.append_step(key, step)
        self.list.setCurrentRow(self.list.count() - 1)

    def add_step_with_dialog(self, name: str) -> None:
        key = self.key()
        if key is None:
            return
        specs = get_step(name).schema()
        required = [s for s in specs if s.required]
        if required and all(s.kind == "curve" for s in required):
            # The identity curve is not a guess: seed it and let the strip edit it.
            t0, dt, n = self.time_axis()
            params = {s.name: identity_curve(t0, dt, n) for s in required}
            params.update(default_params(name))
            self.session.append_step(key, build_step(name, **params))
            self.list.setCurrentRow(self.list.count() - 1)
            return
        dialog = self.build_add_dialog(name)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.append_from_dialog(dialog)
```

(`QDialog` joins the `qgis.PyQt.QtWidgets` import; `Radargram` is only needed for the type of `source`, drop it if ruff flags it unused.)

- [ ] **Step 6: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: schema-driven parameter form and add-step dialog

One generic form built from schema(); no step name appears in plugin
code. Required parameters start blank with the header's antenna and
Nyquist shown as reference, and OK stays disabled until the core builds
the step and applies it to a one-trace probe. Curve-kind steps are
seeded with the identity instead of a dialog."
```

---

