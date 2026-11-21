# Profile view, Plan C: after the walkthrough (Q3, W1, W5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fold in the three walkthrough results, per spec §4.14:
- Time zero's selected view keeps the processed look, falling back to the step's input where a later step refuses;
- the band toggle becomes a **Show slice band** checkbox;
- the read-out shows the distance while a selection is dragged.

**Spec:** `docs/superpowers/specs/2026-11-20-nsgeo-profile-view-design.md` §4.14. It reuses §4.2, §4.7 and §4.11.

**Global constraints:** Plan B's apply unchanged (`docs/superpowers/sdd/2026-11-20-nsgeo-profile-view-plan-b/globals.md`):
- no edits to `plugin.py` or `slices_dock.py`;
- `test_plugin_time_cutoff.py` stays green and unedited;
- every new test fails first;
- run the core tier with `PYTHONPATH=<worktree>/packages/nsgeo-core/src`;
- run ruff;
- push after each task.

---

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

### Task 2: W1, the "Show slice band" checkbox

**Files:** `profile_dock.py` (toolbar); tests in `test_plugin_profile_dock.py`.

**What changes:**
- `slice_band_button` becomes a `QCheckBox("Show slice band")`, placed right after `colormap_combo`, before the Difference label.
- Keep the attribute name, the `QSettings` key, the greyed rule and its tooltips, and the `toggled` wiring.
- The `_FitButton`/1:1 group is untouched.

**Tests:**
- Existing band tests pass unchanged.
- New: `isinstance(dock.slice_band_button, QCheckBox)` and its text is `"Show slice band"`.
- New: it sits left of `fit_button` (`x` order) and is not in the Fit group.
- The toolbar-width test (any-font form) stays green.

### Task 3: W5, distance while dragging a selection

**Files:** `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` (`readout_text`, plus the drag path's repaint of the top strip); tests in `test_plugin_profile_view.py`.

**What changes:**
- While a range-selection drag is in progress (`self._dragging` with `self._selection != (-1, -1)`), `readout_text()` returns the selection text instead of the pointer:
  - `f"{d:.2f} m selected (trace {a}–{b})"`, with `d = abs(m(b + 0.5) − m(a + 0.5))` via `metres_at_trace_units`;
  - `f"{b - a + 1} traces selected (trace {a}–{b})"` when there are no metres.
- On release it goes back to the cursor read-out.
- The drag repaints the top strip whenever the text changes, the same way hover does.
- A selection set programmatically (`set_selection`) without a drag does not change the read-out.

**Tests:**
- On `_sampled` (60 traces/m), press-drag from trace 20 to 80 with the existing drag helpers. During the drag the read-out reads `"1.00 m selected (trace 20–80)"`; check the exact a and b the drag produces.
- After release it is the cursor read-out again.
- With no metres it reads `"61 traces selected (trace 20–80)"`.
- A mirrored line reads its own metres.
- Monkeypatching `metres_at_trace_units` changes the distance, which is the M17c road.

---

## After Plan C

- One scoped final review of Plan C's range.
- Republish the walkthrough with three re-checks, W14–W16, on the same profile and sandbox.
- Ask before merging.
