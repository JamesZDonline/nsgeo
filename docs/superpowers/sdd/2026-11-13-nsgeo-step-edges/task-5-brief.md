### Task 5: Trace stack (#114, spec §6)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/trace_stack.py`
- Modify: `processing/__init__.py` (add `trace_stack` to the registering import),
  `tests/test_step_titles.py`, `tests/test_schema.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py` (the pinned Filters list,
  around line 57)
- Test: `packages/nsgeo-core/tests/test_steps_trace_stack.py` (new)

**Interfaces:**
- Consumes: `running_mean` (Task 2), `real_radargram` (Task 1).
- Produces: a registered step `TraceStack` with:
  - `name = "trace_stack"`, `title = "Trace stack"`, `group = "Filters"`, `order = 3`;
  - schema `(ParamSpec(name="window_traces", kind="int", label="Window", default=3, unit="traces", min=1, help="Averages each trace with its neighbours: this many traces in all, centred on it. 1 leaves the line unchanged."),)`;
  - `params == {"window_traces": ...}`;
  - `apply(rg) = rg.replace(data=running_mean(rg.data, self.window_traces, axis=1))`.

- [ ] **Step 1: Write the failing tests** in `test_steps_trace_stack.py`:

  - `test_window_one_leaves_the_line_unchanged` (FILE__007, exact equality).
  - `test_a_constant_section_is_unchanged`.
  - `test_trace_count_and_time_axis_are_unchanged`, on FILE__007 after `time_zero`: shape,
    `dt_ns`, `t0_ns`, `zero_ns`, `zero_set` and `dx_m` all equal.
  - `test_the_line_ends_average_what_is_there`: at window 3, `out[:, 0] == data[:, :2].mean(1)`
    and `out[:, -1] == data[:, -2:].mean(1)`. This is sliding background's edge rule.
  - `test_stacking_lowers_trace_to_trace_noise_on_real_lines`, on FILE__007 and Grid 2
    FILE__033, after `time_zero` and `dewow`:
    - `var(diff(out, axis=1)) / var(diff(data, axis=1)) < 0.75` at window 3. Measured 0.655 and
      0.614.
    - Each trace's strongest row in 8–40 ns doesn't move: the median absolute shift is 0 rows.
      Measured: 0.
  - `test_a_bad_sample_takes_its_neighbours_mean`: FILE__007 with a NaN at `[100, 300]`, window 3:
    - `out[100, 300] == mean(data[100, 299], data[100, 301])`;
    - no NaN anywhere in the output.
  - `test_the_difference_view_works_across_it`: a `StepStack` holding `trace_stack(5)` on
    FILE__007. `difference(0)` has the input's shape and equals input minus output.
  - `test_a_window_longer_than_the_line_is_capped_at_its_length`: on FILE__007, `trace_stack`
    at window 10000 gives exactly what it gives at window 635 (the line's trace count), and
    doesn't raise.
  - Registration:
    - `TITLES["trace_stack"] = "Trace stack"`, and the Filters list
      `["dewow", "bandpass", "trace_stack"]` in `test_step_titles.py`;
    - `trace_stack.window_traces` in the bounded set in `test_schema.py`;
    - `("Filters", ["dewow", "bandpass", "trace_stack"])` in
      `test_add_menu_is_grouped_in_processing_order`.

- [ ] **Step 2: Run them and confirm they fail** (unknown step).

- [ ] **Step 3: Implement** `trace_stack.py` and the import.

- [ ] **Step 4: Run the core suite, `test_plugin_processing_dock.py` and the rest of the QGIS
  processing set, lint and mypy.** Expected: all pass, with no new mypy errors.

- [ ] **Step 5: Commit and push**

  `feat(processing): Trace stack averages each trace with its neighbours (#114)`

---

## After the tasks

These are the controller's steps, not a task:
- the whole-branch review;
- deploy to its own QGIS profile, then the user's walkthrough (spec §9):
  - Trace stack on a real line, with the Difference view;
  - opening a project copy that holds AGC epsilon 0 on a line and sliding background 1 in a preset;
- the PR, listing the settings changes for the help pages (spec §10) and the tracer rerun note;
- the README roadmap entry moves from "Being designed" to "Being built", and later to Done.

Merging asks the user first.
