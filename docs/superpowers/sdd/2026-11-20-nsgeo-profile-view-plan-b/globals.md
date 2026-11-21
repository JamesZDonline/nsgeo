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

