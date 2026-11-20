# Profile view, Plan B: set Time zero by dragging it (#158)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In Time zero's `sample` mode, the user drags a line on the profile to set the row that becomes 0 ns, and the form and the line always show the same row. Selecting the row shows what Time zero receives, on the line's own clock, with the cropped rows dimmed above the line. The plan also includes Plan A's carried follow-ups.

**Architecture:**
- **The schema says what can be dragged.** In nsgeo-core, a `ParamSpec` gains `when` (the modes it belongs to) and a `row` kind.
- **Panels act only on what is visible.** The Processing panel hides fields outside the current mode. The Profile panel draws a handle only for a visible `time` or `row` field.
- **The time cutoff's machinery is generalised, not copied.** A `time` handle keeps the cutoff's look and behaviour. A `row` handle dims above its line, snaps to row tops, and writes a row index.
- **While a `row` handle's step is selected,** the profile draws that step's input, relabelled onto the line's zero. Plan A's `carry_time_window` then makes selecting and deselecting behave: the top stays the top, and the middle holds still.

**Tech Stack:** Python 3, PyQt via `qgis.PyQt` (QGIS 3.44 / Qt 5 and 4.2 / Qt 6), numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-11-20-nsgeo-profile-view-design.md`. §4.9–§4.13 and §5 apply to this plan; §4.8 is reused from Plan A. Plan A's record is at `docs/superpowers/sdd/2026-11-20-nsgeo-profile-view-plan-a/progress.md`; rulings R17 and R18 there are the source of Task 1.

## Global Constraints

- **The user's Profile panel floats at about 1361 × 448.**
- **No edits to `plugin.py` or `slices_dock.py`.** H, M19a and #227 edit them.
  - Any message the Processing panel must show goes in its form's own message line, `ParamForm.message`. Ruling R19: the Processing panel has no toast path without new `plugin.py` wiring.
  - A message from the Profile panel goes through its existing `error` signal.
- **Plan A's interfaces are reused unchanged:**
  - `carry_time_window(old, new, old_zero, new_zero)`;
  - `ProfileDock._set_axes_holding(..., zero_ns=...)`;
  - `_axes_zero`;
  - `_axes_from_header`;
  - the helper pair `metres_at_trace_units` / `trace_units_at_metres`.
- **The time cutoff must behave exactly as before.** `test_plugin_time_cutoff.py` stays green with no edits to its assertions. `ProfileView.cutoff_ns`, `set_cutoff(...)` and `cutoff_dragged` keep their meaning for a `time` handle.
- **Saved sites load unchanged.** A saved `time_zero` with `sample` stays a plain int. A saved `gain_parametric` with both `alpha` and `exponent` keeps both values, even the one its mode hides.
- **Every Qt-invoked slot or override wraps its body** in `try/except Exception` and logs, as the module docstrings explain.
- **Every new test must fail before its fix,** and the task report quotes that run. A guard test that pins today's behaviour says so and may pass first.
- **Tests,** run from the worktree root `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-profile-view`:
  - core: `/home/jameszd/Documents/Github/archaeo_geophysics/.venv/bin/python -m pytest packages/nsgeo-core/tests -q`;
  - pure: `/home/jameszd/Documents/Github/archaeo_geophysics/.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q`;
  - QGIS: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/<file> -q`;
  - real data: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q`. Real survey files are linked into this worktree.
  - **Never** run `qgis_tests.sh full`.
  - CI also runs `ruff check .` and `ruff format --check .`; run both before each commit.
- **Commit and push after each task** (`git push`, branch `nsgeo-profile-view`).

## Review Focus

1. **A Time zero step that is not first.** For example: Dewow, then Time zero, then AGC. The drawn input is `intermediate(row − 1)`, its rows are the step's rows, and the seed comes from that input. Tested in Task 4.
2. **A disabled Time zero step.** Whatever the cutoff does today for a disabled step, the handle does the same. Its selected view must not show a crop that won't happen. Tested in Task 4.
3. **`first_break` mode selected.** It shows no line and no input view: the ordinary result, as today. Switching to `sample` while selected shows the line at once. Tested in Tasks 3 and 4.
4. **The samples have not loaded.** No line is drawn, and the form has no upper bound, until `line_loaded`; then both appear. Tested in Task 2.
5. **A drag to the very top or the very bottom.** The line clamps to row 0 and row n − 1. Writing either is accepted by the step: n − 1 leaves one row. Tested in Task 4.

---

### Task 1: Plan A follow-ups (rulings R17/R18), and a toolbar width pin that survives CI's fonts

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (`_take_down_picture`, the Fit button construction).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` (`set_axes` guard, and `_true_scale_inputs` / `true_scale_window_is_flat`).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py` (remove `bounds_on`).
- Test: `tests/qgis/test_plugin_profile_dock.py`, `tests/qgis/test_plugin_profile_view.py` and `tests/pure/test_pure_ruler.py`.

**Interfaces:**
- Produces `ProfileView._window_metres_per_trace_unit() -> float | None`. It is the one place that works out metres per trace unit across the current window, and both `_true_scale_inputs` and `true_scale_window_is_flat` use it.

**The five changes:**
- **The header flag on a same-line take-down that went through rule 1.**
  - Today `_take_down_picture` sets `_axes_from_header = not self._clock_carried`.
  - Change the condition, checked **before** its `_set_axes_holding` call: set the flag only when `not (self._axes_key == key and not self._axes_from_header)`. That is, only when the header axes did not come from the same line's processed picture.
  - `test_a_held_zoom_does_not_move_when_an_unloaded_lines_samples_arrive` and `test_a_same_line_take_down_then_render_keeps_the_radar_window` must stay green, unchanged.
- **The Fit button's minimum width follows font and style changes.**
  - Recompute it (the widest of the three action labels) on `QEvent.Type.FontChange` and `QEvent.Type.StyleChange`. Use a small `QToolButton` subclass in `profile_dock.py`, or an event filter.
- **`set_axes` is guarded against non-finite clocks.**
  - Extend its first guard to `math.isfinite(t0_ns) and math.isfinite(dt_ns) and dt_ns > 0`.
  - On refusal it leaves `transform`, `_distance` and `_ruler` all unchanged.
- **`bounds_on` is removed from `ruler.py`,** and so are its tests in `tests/pure/test_pure_ruler.py`. It is unused in production since Plan A's I2, and it is a second road from metres to trace units (spec §3.1). Its conversion is covered by the helper-pair tests.
- **The toolbar minimum-width pin survives other fonts.**
  - `test_the_toolbar_minimum_width_is_back_to_pre_m7` failed on CI's QGIS 3.44 at 87198d9: 723 against a local 684. Pixel bounds measured on one machine break on another.
  - Replace the absolute pin with two checks that hold in any font:
    1. Long Difference and velocity texts do not raise the row's minimum width beyond the Difference label's own growth. The velocity label (`ElidedLabel`, `Ignored`) contributes nothing.
    2. The minimum is at most 900 px, the docked width the M7 walkthrough used.
  - Update the docstring.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_same_line_take_down_through_rule_1_does_not_set_the_header_flag(opened):
    # The re-review's probe: a line with no steps, zoom mid-record, _show_steps_refused,
    # then append time_zero(mode="sample", sample=20) -> the radar window is unchanged
    # (today it moves by the new zero: (39.35, 49.35) -> (41.25, 51.25)).
    ...

def test_the_fit_button_keeps_its_widest_width_after_a_font_change(opened):
    session, dock, key, line = opened
    f = dock.fit_button.font(); f.setPointSizeF(f.pointSizeF() * 1.25); dock.fit_button.setFont(f)
    QTest.qWait(50)
    xs = set()
    for action in (dock.fit_all_action, dock.fit_width_action, dock.fit_height_action):
        action.trigger(); QTest.qWait(50); xs.add(dock.one_to_one_button.x())
    assert len(xs) == 1

def test_set_axes_refuses_a_non_finite_clock_and_changes_nothing(view):
    v, rg = view
    before = (v.transform, v._distance, v.ruler)
    v.set_axes(rg.n_traces, rg.n_samples, float("nan"), rg.dt_ns, distance_along=np.arange(rg.n_traces) / 30.0)
    assert (v.transform, v._distance, v.ruler) == before
    v.set_axes(rg.n_traces, rg.n_samples, rg.t0_ns, float("inf"))
    assert (v.transform, v._distance, v.ruler) == before
```

  The width pin's replacement is written as the two checks described above.

- [ ] **Step 2: Run them and check they fail.**
  - Expected: the first moves by the zero, the second gives two or three x values, and the third replaces `_distance` or raises.
  - The width checks pass on today's code; say so.
- [ ] **Step 3: Implement the five changes.**
- [ ] **Step 4: Run** `test_plugin_profile_dock.py`, `test_plugin_profile_view.py`, `test_plugin_profile_cut.py`, pure and real data. Expected: PASS.
- [ ] **Step 5: Commit and push**

```bash
git commit -am "fix(profile): Plan A follow-ups -- header flag on rule 1, Fit width on font change, finite set_axes, one metre road, a font-proof width pin"
git push
```

---

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

### Task 3: What the profile draws while Time zero's row is selected (spec §4.11, §4.13)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`:
  - `time_param_name`, renamed to `handle_spec` (only `profile_dock.py` uses it);
  - `_cutoff_row`, renamed to `_handle_row` (keep internal callers consistent);
  - `current_radargram`;
  - `_scale_reference`;
  - a relabel helper.
- Test: `tests/qgis/test_plugin_profile_dock.py`, `tests/qgis/test_plugin_difference_presets.py`, and real data.

**Interfaces:**
- Consumes:
  - Task 2's `param_visible` and the `row` kind;
  - Plan A's `_set_axes_holding(..., zero_ns=...)`.
- Produces:
  - **`handle_spec(step) -> ParamSpec | None`** (module function in `profile_dock.py`). It returns the first spec of kind `time` or `row` that is visible for `step.params`.
  - **`ProfileDock._handle_row(row: int | None = None) -> int`.** It is today's `_cutoff_row` rule, with the `handle_spec` test in place of `time_param_name`.
  - **`relabel_onto(rg: Radargram, zero_ns: float) -> Radargram`** (module function). It returns `rg.replace(t0_ns=rg.t0_ns + (rg.zero_ns - zero_ns), zero_ns=zero_ns)`: same data, same rows, the line's clock.
  - **`current_radargram`'s handle branch:**
    - for a `time` handle: `stack.result_bypassing(row)`, as today;
    - for a `row` handle: `relabel_onto(input, stack.zero_ns())`, where `input` is `stack.intermediate(row − 1)` for row > 0, or `stack.source` for row 0.
  - **`_scale_reference`** returns `shown` when a `row` handle is selected.

**The spec fixes these values:**
- Selecting `FILE__007`'s Time zero row in `sample` mode, seeded at 49:
  - the drawn record starts 49 rows (10.6 ns) above the line;
  - its `t0_ns` is `-11.086 - (-0.476) ≈ -10.61` on the line's clock;
  - the line's row is 49.
- The GPS line `with-dzg/FILE__010`, seeded at 44:
  - the record starts at about -9.53 ns;
  - the line's zero on the record clock is -1.559 ns.

- [ ] **Step 1: Write the failing tests**

```python
def test_selecting_time_zero_in_sample_mode_draws_its_input_on_the_lines_clock(...):
    # synthetic line; stack [time_zero(sample=20), dewow]; select row 0 ->
    # dock.image.rg.data equals the source's data, dock.shown_zero_ns() == stack.zero_ns(),
    # and dock.view.transform.t0_ns == source.t0_ns + (source.zero_ns - stack.zero_ns())
    ...

def test_first_break_mode_selected_draws_the_ordinary_result(...):   # Review Focus 3
    ...

def test_a_time_zero_that_is_not_first_draws_what_it_receives(...):  # Review Focus 1
    # [dewow, time_zero(sample=20), gain_agc]; select row 1 -> data == intermediate(0).data
    ...

def test_selecting_time_zero_at_the_top_brings_the_cropped_rows_in(...):
    # zoom to (0, 10) ns on the processed line; select the row -> the window starts at the
    # drawn record's top with the same 10 ns span; deselect -> back to (0, 10)
    ...

def test_selecting_time_zero_mid_record_holds_the_picture_still(...):
    # zoom mid-record; select and deselect -> the radar window (shown_zero + t) is unchanged
    ...

def test_a_migrated_line_still_draws_time_zeros_input(...):           # §4.11 Q6
    # stack [time_zero(sample=k), migrate_fk(...)] on a line whose record starts far from
    # zero (t0 <= -2.5 ns): selecting row 0 draws the input; no error emitted
    ...
```

**Re-pin `test_selecting_time_zero_with_difference_on_shows_the_result`** (`test_plugin_difference_presets.py:90`).
- Its step is `time_zero(mode="sample", sample=40)`. In `sample` mode, the profile now shows Time zero's input, per spec §4.13 and Q6.
- Change its final assert to compare `prd.image.rg.data` against the stack's source data.
- Keep the toast, unchecked-button and empty-label asserts.
- Add a sibling with `mode="first_break"` that keeps the old `result()` assert.
- Add the §4.13 pin on a line with `migrate_fk` after Time zero: exactly one `error` emission (the decline), the button is off, and the input is drawn.

- [ ] **Step 2: Run them and check they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `test_plugin_profile_dock.py`, `test_plugin_time_cutoff.py` (unchanged and green), `test_plugin_difference_presets.py`, `test_plugin_gain_strip.py`, `test_plugin_velocity_fit.py`, pure and real data. Expected: PASS.
- [ ] **Step 5: Commit and push**

```bash
git commit -am "feat(profile): Time zero's row shows what it receives, on the line's clock (#158)"
git push
```

---

### Task 4: The Time zero line: drawn, dragged and written (spec §4.11, §4.12)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py` (add `snap_row`).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` (the handle kind, dimming side, snap and tag).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (`_show_cutoff` and `_on_cutoff_dragged` for a `row` handle).
- Test:
  - `tests/pure/test_pure_view_transform.py`
  - `tests/qgis/test_plugin_profile_view.py`
  - `tests/qgis/test_plugin_profile_dock.py`
  - a new `tests/qgis/test_plugin_time_zero_drag.py` (plugin-level, built like `test_plugin_time_cutoff.py`'s `_plugin_with_line`)

**Interfaces:**
- Consumes:
  - Task 3's `handle_spec`, `_handle_row` and the relabelled input.
- Produces:
  - **`ViewTransform.snap_row(time_ns: float) -> float`:** `t0 + clamp(round((t − t0)/dt), 0, n − 1)·dt`. These are the row tops, inside the record.
  - **`ProfileView.set_cutoff(time_ns: float | None, kind: str = "end") -> None`,** where `kind` is `"end"` (today's cutoff) or `"start"` (a row handle):
    - `"start"` dims from the image top down to the line.
    - `"start"` snaps with `snap_row`.
    - `"start"` tags `f"Time zero · sample {k}"` at rest and `f"sample {k} · {t:.2f} ns"` while dragging. Here `k = round((t − t0)/dt)` on the drawn record, and `t` is the line's time on the shown clock, which is the offset from the line's current zero, because the view is on that clock.
    - `cutoff_dragged` still emits the snapped time.
    - `"end"` is byte-for-byte today's behaviour.
  - **`ProfileDock._show_cutoff`** for a `row` handle calls `view.set_cutoff(shown.t0_ns + sample·dt, kind="start")`, where `shown` is the relabelled input.
  - **`ProfileDock._on_cutoff_dragged(t)`** for a `row` handle works out `row = round((t − shown.t0_ns)/shown.dt_ns)`.
    - It writes nothing when `row == step.params["sample"]`.
    - Otherwise it does `build_step(step.name, **{**step.params, "sample": row})` and `replace_step`, with the identity check against the step the line was drawn from, as for the cutoff.

- [ ] **Step 1: Write the failing tests**

```python
def test_snap_row_lands_on_row_tops_inside_the_record():              # pure
    t = ViewTransform.fit(10, 100, -2.0, 0.25, 696, 264)
    assert t.snap_row(-2.1) == -2.0
    assert t.snap_row(-1.6) == pytest.approx(-1.5)
    assert t.snap_row(99.0) == pytest.approx(-2.0 + 99 * 0.25)

def test_a_start_handle_dims_above_and_tags_its_row(view):            # view
    ...set_cutoff(t, kind="start"); grab; pixels above the line are dimmed, below are not;
    the tag text is "Time zero · sample k"...

def test_the_line_shows_only_in_sample_mode_while_selected(...):      # dock, Review Focus 3
    ...

def test_dragging_time_zeros_line_writes_its_row(...):                # plugin-level
    # select time_zero(sample=20); view.cutoff_dragged.emit(shown.t0 + 26*dt) ->
    # step.params["sample"] == 26; the form's row editor shows 26; an unmoved emit writes nothing
    ...

def test_a_typed_row_moves_the_line(...):
    # form row editor -> 30, commit -> view.cutoff_ns == shown.t0 + 30*dt
    ...

def test_after_a_drag_the_line_reads_zero_again_and_the_picture_holds(...):
    # mid-record zoom, drag from 20 to 26 -> the line sits at 0 ns on the new clock
    # (view.cutoff_ns == pytest.approx(0.0)); the radar window is unchanged
    ...

def test_a_drag_to_either_end_clamps_and_is_accepted(...):            # Review Focus 5
    ...

def test_a_disabled_time_zero_handle_matches_the_cutoffs_rule(...):   # Review Focus 2
    # read what `_cutoff_row` does today for a disabled step and pin the same for the handle
    ...

@needs_real_data
def test_time_zero_by_eye_on_the_campus_line(...):
    # FILE__007: switching first_break -> sample seeds 49; selecting shows the line at 0 ns
    # with 49 rows above; dragging two rows up writes 47
    ...

@pytest.mark.skipif(not GPS_LINES, reason="needs the with-dzg lines in tests/data/local")
def test_time_zero_by_eye_on_a_gps_line(...):
    # with-dzg FILE__010 (seed 44), the same three checks
    ...
```

  E's rule needs one more check: the drag path must not undo the decline. Selecting Time zero with Difference on, then dragging, leaves the Difference button off and writes the row.

- [ ] **Step 2: Run them and check they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `test_plugin_profile_view.py`, `test_plugin_profile_dock.py`, `test_plugin_time_cutoff.py` (unchanged and green), `test_plugin_time_zero_drag.py`, `test_plugin_difference_presets.py`, pure and real data. Expected: PASS.
- [ ] **Step 5: Commit and push**

```bash
git commit -am "feat(profile): drag Time zero's line on the profile; the form and the line share one row (#158)"
git push
```

---

## After Plan B

1. A whole-branch review of Plans A and B.
2. Deploy to its own QGIS profile.
3. A walkthrough artifact on a floating Profile panel at about 1361 × 448. It covers:
   - the band hidden and shown;
   - Fit width and Fit height;
   - 1:1;
   - each axis unit and the read-out;
   - a time zoom held across a Time zero edit;
   - dragging Time zero by eye, with Difference on and off;
   - R18's question: the velocity label shortened at 1361 px in the worst case.
4. Ask before merging.
