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

