### Task 2: Per-mode parameters and the `row` kind (nsgeo-core), and a form that follows the mode (spec §4.9, §4.10)

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/processing/base.py`:
  - `ParamSpec`: the `when` field, `KINDS`, and `__post_init__`;
  - `_problem`;
  - `register` (the schema check);
  - a new `param_visible`.
- Modify: `packages/nsgeo-core/src/nsgeo/processing/timezero.py` and `gain.py` (their schemas).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py`:
  - hide fields outside the mode;
  - add a row editor;
  - add a `row_range`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`:
  - `_show_form`: the row range;
  - `_form_axis_unknown` for `row` forms;
  - `_on_form_committed`: the seed on switching into `sample`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/step_inputs.py`: add `time_zero_seed`.
- Test:
  - `packages/nsgeo-core/tests/` (the existing processing schema test file, or a new `test_param_when.py`);
  - `tests/qgis/test_plugin_param_form.py`;
  - `tests/qgis/test_plugin_processing_dock.py`.

**Interfaces:**
- Produces:
  - **`ParamSpec.when: tuple[str, tuple[str, ...]] | None = None`.** This is the name of a sibling `choice` parameter, and the values of it under which this parameter applies. None means every mode.
  - **`KINDS` gains `"row"`.** A row is an int row of the step's **input** record, counted from its first row. It is validated exactly like `int`: an `Integral` that is not a bool, plus `min` and `max`.
  - **`param_visible(spec: ParamSpec, params: Mapping[str, Any]) -> bool`** in `nsgeo.processing.base`, exported from `nsgeo.processing`. It returns True when `spec.when` is None or `params[when[0]] in when[1]`.
  - **The schema check runs in `register`.** For every spec with `when`: the named sibling exists in the same schema, is `kind="choice"`, and every listed value is in its `choices`. Otherwise it raises `ValueError` naming the step and the parameter.
  - **`TimeZero.schema()`:**
    - `sample` becomes `kind="row"`, `min=0`, `when=("mode", ("sample",))`;
    - its help is "The row that becomes 0 ns. Drag its line on the profile, or type it.";
    - `threshold` gets `when=("mode", ("first_break",))`.
  - **`gain_parametric` (gain.py):** `alpha` gets `when=("mode", ("exponential",))` and `exponent` gets `when=("mode", ("power",))`. Their help text drops "used when mode is …".
  - **`ParamForm.set_step(name, params=None, time_range=None, time_step=None, row_range: tuple[int, int] | None = None)`.**
    - A `row` field is a `RowSpinBox(QSpinBox)`. Its commit rules mirror `TimeSpinBox`: `editingFinished` and arrow steps commit, and the wheel is ignored without focus. It is bounded by `row_range` when given; with no range it is bounded only by `min`.
    - Every field whose `when` doesn't match the current mode combo is hidden, label and editor both, and shown again when the combo changes. Use `QFormLayout.labelForField(editor).setVisible(...)` and `editor.setVisible(...)`. This works on Qt 5, which has no `setRowVisible`.
    - `values()` still returns every parameter, hidden ones included, so the saved hidden values survive.
  - **`step_inputs.time_zero_seed(session, key: str, row: int, threshold: float) -> int | None`.** It returns the first-break row of the step's input: `stack.intermediate(row − 1)`, or the source for row 0. It returns None when there is no source, no arrival (`_first_break_or_none` is None), or the stack above refuses.
  - **`ProcessingDock`:**
    - `_show_form` passes `row_range=(0, n − 1)` from `input_axis(row)` for a step with a `row` field, and sets `_form_axis_unknown` when the axis is unknown, as it does for `time`.
    - `_on_form_committed` seeds the row on a switch into `sample`. When the committed params have `mode == "sample"` and the step on screen had another mode, it replaces `params["sample"]` with `time_zero_seed(...)`, using the step's current threshold. When the seed is None, it keeps the stored `sample` and sets `self.form.message` to "Couldn't find the first break, so Time zero starts at row {sample}. Drag its line or type the row."
    - It seeds on every switch into `sample`. That is spec §4.10, the controller's call.

- [ ] **Step 1: Write the failing core tests**

```python
def test_a_row_param_is_validated_like_an_int():
    spec = ParamSpec("sample", "row", "Sample", 0, min=0)
    assert param_problem(spec, 3) is None
    assert param_problem(spec, 3.0) == "must be a whole number"
    assert param_problem(spec, True) == "must be a whole number"
    assert param_problem(spec, -1) is not None

def test_param_visible_follows_its_mode():
    s = {spec.name: spec for spec in TimeZero.schema()}
    assert param_visible(s["sample"], {"mode": "sample"}) and not param_visible(s["sample"], {"mode": "first_break"})
    assert param_visible(s["threshold"], {"mode": "first_break"}) and not param_visible(s["threshold"], {"mode": "sample"})
    assert param_visible(s["mode"], {"mode": "sample"})

def test_register_refuses_a_when_that_names_no_choice():
    # a throwaway class whose ParamSpec says when=("nope", ("x",)) -> ValueError naming it;
    # and one naming a real choice but an unknown value -> ValueError
    ...

def test_a_saved_time_zero_and_gain_load_unchanged():
    tz = build_step("time_zero", mode="sample", sample=44, threshold=0.3)
    assert tz.params == {"mode": "sample", "sample": 44, "threshold": 0.3}
    g = build_step("gain_parametric", mode="power", alpha=0.07, exponent=2.0)
    assert g.params["alpha"] == 0.07 and g.params["exponent"] == 2.0
```


- [ ] **Step 2: Run them and check they fail.** Expected: the `"row"` kind is unknown, `param_visible` doesn't exist, and `register` accepts the bad `when`.

- [ ] **Step 3: Implement the core part.**
  - Every place in nsgeo-core and nsgeo-qgis that switches on `spec.kind == "int"` must treat `"row"` the same way.
    - `grep -rn 'kind == "int"\|kind in (' packages/` and list each site in the report.
    - Known sites: `base.py` `_problem`, and `param_form._parse_number`.
  - `processing_dock.py:~108` (`_has_required_fields_without_editor`, or whatever its name is) must not count `row` as needing a dialog.

- [ ] **Step 4: Write the failing form and panel tests**

```python
def test_the_form_hides_fields_outside_the_mode(qgis_app):           # test_plugin_param_form.py
    form = ParamForm(); form.set_step("time_zero", {"mode": "first_break", "sample": 0, "threshold": 0.2})
    assert form.editors["threshold"].isVisible() is not False and not form.editors["sample"].isVisibleTo(form)
    form.set_value("mode", "sample")
    assert form.editors["sample"].isVisibleTo(form) and not form.editors["threshold"].isVisibleTo(form)
    assert set(form.values()) == {"mode", "sample", "threshold"}      # hidden values kept
    # and the same for gain_parametric's alpha / exponent

def test_the_row_field_is_bounded_by_the_input(...):                 # test_plugin_processing_dock.py
    # a synthetic line of 512 samples with time_zero(mode="sample") first: the row editor's
    # maximum() == 511, minimum() == 0
    ...

def test_switching_to_sample_starts_at_the_first_break(...):
    # time_zero(first_break) on a synthetic line with a known first break k (see
    # test_timezero's synthetic records, or build one with a step at row k); switch the
    # mode combo to "sample" -> the stack's step has sample == k and the line's zero is
    # unchanged (stack.zero_ns() before == after)
    ...

def test_switching_to_sample_with_no_arrival_keeps_the_row_and_says_so(...):
    # an all-zero record: the switch commits mode="sample" with the stored sample, and
    # form.message.text() starts with "Couldn't find the first break"
    ...

def test_the_row_form_gets_its_bound_when_the_samples_arrive(...):   # Review Focus 4
    # open the line without samples, select time_zero(sample): no upper bound; set_profiles ->
    # line_loaded -> the row editor's maximum() == n - 1
    ...
```

- [ ] **Step 5: Run them and check they fail.** Then implement the form and panel parts.

- [ ] **Step 6: Run the core tier, pure, `test_plugin_param_form.py`, `test_plugin_processing_dock.py`, `test_plugin_difference_presets.py`, `test_plugin_preset_box.py` and real data.** Expected: PASS.

- [ ] **Step 7: Commit and push**

```bash
git commit -am "feat(processing): parameters belong to modes, a row kind, and Time zero's row starts at the first break (#158, #210 plumbing)"
git push
```

---

