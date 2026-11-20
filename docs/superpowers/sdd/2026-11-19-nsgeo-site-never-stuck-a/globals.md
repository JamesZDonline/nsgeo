## Global Constraints

**Paths:**
- `P` = `packages/nsgeo-qgis/nsgeo_qgis`, `T` = `packages/nsgeo-qgis/tests`,
  `C` = `packages/nsgeo-core/src/nsgeo`, `CT` = `packages/nsgeo-core/tests`.
- The worktree is `.worktrees/nsgeo-site-never-stuck`. Every command runs from its root.

**Tests:**
- **Core and pure:** use the worktree's own `.venv` (already built, nsgeo editable from this
  worktree):
  - `./.venv/bin/python -m pytest packages/nsgeo-core/tests -q -p no:xonsh`
  - `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q -p no:xonsh`

  Never use the main checkout's `.venv`: it imports main's core.
- **QGIS tier:** `packages/nsgeo-qgis/scripts/qgis_tests.sh <file or -k ...>`. It uses main's
  `.venv-qgis`, and conftest puts this tree's sources first. Before pushing, run the touched QGIS
  files and `qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data`. Never run the whole QGIS
  tier locally: CI runs it on 3.44 and 4.2.
- **Fail first:** every new test must fail before its fix. Run it and see it fail for the stated
  reason.
- **Tests that dodge the hazard are bug reports.** A test may not avoid the input that breaks the
  code.

**Code rules:**
- Every Qt slot and timer callback guards its whole body (`except Exception` → `_log` or
  `_report`), and never raises.
- No Qt off the GUI thread.
- Core stays numpy-only and Python 3.9-compatible: no `zip(strict=)`, no `match`.
- Run `ruff check .` and `ruff format --check .` with `./.venv/bin/ruff`. CI's mypy command is in
  `.github/workflows/` (the `mypy --config-file packages/nsgeo-core/pyproject.toml …` step). Run it
  the same way when a task adds a file to that list.
- User-facing strings are plain sentences in the plugin's register: no jargon, no "error code".

**Process:**
- Commit after each task with a `type(scope): … (#issue)` message, ending with the attribution line
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Implementers commit locally and do not push; the controller pushes each task
  after its review (GitHub auth is back, 2026-11-19 evening).
- Reviewers never edit files in this worktree.
- **#75 is split with session N.** Touch only the Site engine, Site export and Whole site UI
  sections. Check each item against the code before fixing it, and record items already gone
  (with the commit or file:line that shows it) in the task report. If an item turns out bigger
  than #75 makes it look, stop and report it rather than growing the task.
- **#196 is not #166.** `test_a_site_refine_for_a_window_left_behind_never_draws` and its This
  grid twin fail under load at `assert finished_late.is_set()`. Note such failures and move on.

