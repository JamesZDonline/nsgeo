### Task 1: Q3, the processed look while Time zero is selected

**Files:** `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (the row-handle branch of `current_radargram`, and `_scale_reference`); tests in `tests/qgis/test_plugin_profile_dock.py`, `test_plugin_difference_presets.py` and `test_plugin_time_zero_drag.py`.

**What changes:**
- **The row-handle branch draws the bypass.**
  - It draws `relabel_onto(stack.result_bypassing(row), stack.zero_ns())`.
  - It falls back to today's input view (`relabel_onto(input, zero)`, or the unrelabelled input when `zero_ns()` raises) when either:
    - the bypass raises `ValueError`; or
    - the bypass's `(n_samples, t0_ns)` differ from the input's.
  - The fallback emits no error.
- **`_scale_reference` matches the ordinary view.**
  - While the bypass is drawn, it returns the ordinary view's reference with the Time zero row also bypassed: `stack.result_bypassing(row, *curve_rows)`.
  - While the fallback is drawn, it returns `shown`, as today.
  - Record which of the two was drawn, so the scale follows the drawn record.

**Re-pin these Task 3 / Task 4 tests and name each in the report:**
- the "draws its input" tests now expect the bypass data on stacks where it runs;
- the migration tests still expect the input (the fallback), one error and the line up;
- `test_a_row_handles_input_view_is_its_own_scale` becomes the fallback's pin;
- the drag and row tests still pass, because the bypass rows equal the input rows when nothing after Time zero crops the top.

**New tests:**
- `test_selecting_time_zero_keeps_the_processed_look`. Stack `[time_zero(sample=20), dewow, gain_agc]`: the drawn data equals `relabel_onto(result_bypassing(0), zero)` data, and `dock.image.limit` is within 5% of the not-selected view's limit.
- `test_a_later_step_that_refuses_falls_back_to_the_input`. Stack with `migrate_fk` after Time zero: the input is drawn and no error is emitted.
- `test_a_bypass_with_other_rows_falls_back`. A second time_zero after the first changes the rows, so the input is drawn and the line's row is the step's `sample`.

