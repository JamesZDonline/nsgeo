### Task 5: Split the step-input queries out of `processing_dock.py` (#21)

The user chose a split on 2026-11-19. There is no behaviour change. The queries that say what a
step receives move to their own module. The "Time zero clock not known yet" rule, which Task 3
copied into `plugin.py`, gets one home.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/step_inputs.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`. `input_axis`, `time_axis`,
  `probe_radargram` and `seed_params` become one-line delegates, with short docstrings that point
  to `step_inputs`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`. `_sync_gain_strip`'s inline clock check
  becomes `step_inputs.clock_unknown(stack, row)`. Nothing else in this file changes.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py` (one new test). Every
  existing test stays unchanged.

**Interfaces:**
- Produces, in `nsgeo_qgis.step_inputs`:
  - `clock_unknown(stack: StepStack, row: int) -> bool`. True when `stack.source is None` and an
    enabled `time_zero` sits in `stack.entries[:row]`.
  - `input_axis(session: SiteSession, key: str, row: int) -> tuple[float, float, int] | None`.
  - `time_axis(session: SiteSession, key: str) -> tuple[float, float, int]`.
  - `probe_radargram(session: SiteSession, key: str) -> Radargram | None`.
  - `seed_params(session: SiteSession, name: str, key: str) -> dict[str, Any] | None`.

  Each body, its log messages (the `"input_axis: …"`, `"probe_radargram: …"` and
  `"seed_params: …"` texts) and its long docstring move verbatim.
  `input_axis` uses `clock_unknown`.
- Consumes: nothing new.
- The `ProcessingDock` methods keep their names and signatures, so callers in `plugin.py` and the
  tests don't change.

- [ ] **Step 1: Write the guard test.** In `test_plugin_processing_dock.py`, add
  `test_the_clock_rule_has_one_answer` (a guard test; its docstring names the mutation).
  - It is parametrized over all eight cases: samples loaded or not × Time zero enabled or not ×
    the curve's row above or below the Time zero.
  - In every case, `step_inputs.clock_unknown(stack, row)` must be True exactly when
    `dock.input_axis(row) is None`.
  - It fails if `input_axis` keeps a private copy of the rule that differs, for example by
    ignoring `enabled`.
- [ ] **Step 2: Move the code.** No logic edits. Run `git diff --stat`: it should show about 150
  lines leaving `processing_dock.py` and arriving in `step_inputs.py`.
- [ ] **Step 3: Run the tests.** Run:
  - every QGIS file that calls these methods: `test_plugin_processing_dock.py`,
    `test_plugin_param_form.py` and `test_plugin_gain_strip.py`;
  - the four whole files;
  - the real-data run;
  - the pure tier (`packages/nsgeo-qgis/tests/pure`, with the core and pure command's
    `PYTHONPATH`);
  - lint (`ruff check .`, and `ruff format --check` on the changed files only).

  Expected: every one passes, and no existing test was edited.
- [ ] **Step 4: Commit** `refactor(processing): the step-input queries move to step_inputs.py (#21)`.

### After Task 5: #21

Comment on #21 with the split. Close it when the branch merges.
