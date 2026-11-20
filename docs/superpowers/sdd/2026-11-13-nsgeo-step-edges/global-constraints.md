## Global Constraints

- **Core:** numpy only, runtime Python 3.9: no `match`, no `zip(strict=)`, no PEP 604 unions
  outside annotations. Every new file starts with `from __future__ import annotations`.
- **Leave alone:**
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py`;
  - the `nsgeo-help-pages` branch;
  - `first_break_row`'s signature and its 0-for-no-signal return.
- **Running things.** Run everything from the worktree root
  `.worktrees/nsgeo-step-edges`. It has its own
  `.venv` and `.venv-qgis`, and the real data linked under `packages/nsgeo-core/tests/data/local/`.
  - Core: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests -q -p no:cacheprovider`
  - One QGIS file: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/<file> -q -p no:xonsh -p no:cacheprovider`
  - **The QGIS processing set**, which the user asked for. Tighter validation can break QGIS tests
    that build steps with odd values. Run each of these files with the command above:
    - `test_plugin_processing_dock.py`, `test_plugin_param_form.py`,
      `test_plugin_difference_presets.py`, `test_plugin_session.py`;
    - `test_plugin_profile_dock.py`, `test_plugin_time_cutoff.py`, `test_plugin_gain_strip.py`,
      `test_plugin_survey_dock.py`;
    - `test_plugin_site_scope.py`, `test_plugin_slices_engine.py`, `test_plugin_layers.py`,
      `test_plugin_grid_velocity_dialog.py`, `test_plugin_velocity_dialog.py`.

    Don't run the whole QGIS tier; CI does.
  - Lint: `.venv/bin/ruff check packages && .venv/bin/ruff format --check packages`
  - mypy, as CI runs it: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
- **Real lines first.** Every fix gets a test on campus `FILE__007.DZT` or a Grid 2 line, as well
  as any synthetic test.
  - Load real lines with `tests.real_data.real_radargram(path)` (Task 1). It skips when the file is
    missing, as on CI.
  - Key files by path (`DATA / "FILE__007.DZT"`, `DATA / "grid2" / "FILE__033.DZT"`), never by stem
    (#141).
  - FILE__007 facts: 512 samples × 635 traces, `dt_ns` 0.21653, position −11.09 ns. The default
    Time zero crops 49 rows.
- **Messages** are plain words, with no issue numbers. Where this plan gives a message, tests pin it.
- **Commits:** one or more per task, pushed to `origin nsgeo-step-edges` as made. End each message
  with a `Co-Authored-By:` line naming your own model.
- **Mutation testing**, where a task asks for it: `PYTHONDONTWRITEBYTECODE=1`, in a throwaway copy
  of the tree (`git worktree add` under the scratchpad), **never** in this worktree.

