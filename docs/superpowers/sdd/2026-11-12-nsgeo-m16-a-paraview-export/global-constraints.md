## Global Constraints

- **Run every test from the worktree root with `PYTHONPATH=packages/nsgeo-core/src`.** Below, `R=/home/jameszd/Documents/Github/archaeo_geophysics`.
  - **Core and pure:** `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`
  - **QGIS:** `PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen $R/.venv-qgis/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`. The whole suite takes about 12 minutes, so run single files while iterating.
- **Lint as CI does,** with line length 100:
  - `$R/.venv/bin/ruff check .`
  - `$R/.venv/bin/ruff format --check .`
  - `$R/.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`

  mypy checks the whole core.
- **The core uses numpy only.** It has a Python 3.9 floor: `from __future__ import annotations`, no `zip(strict=...)` and no `match`. No new dependency anywhere. The CI pure tier runs 3.9.
- **No ParaView code lives in a `.py` file inside `packages/`.** ruff (F403), mypy and three AST-scanning tests would all reject it. Scene files ship as `.txt` templates in `packages/nsgeo-qgis/nsgeo_qgis/paraview/`. `build_zip.py` only ships tracked `.py`, `.txt` and `.md` files.
- **Plugin boundary.** Arithmetic and message text live in the core, in `slices_plan.py` or in `paraview_scene.py`, never in widgets.
- **Qt.**
  - Use fully qualified enums.
  - Every Qt-invoked slot guards its body with `try/except Exception`.
  - Every new `pyqtSignal` is connected (`tests/pure/test_no_orphan_signals.py`).
  - Modal dialogs in tests go through `drive_dialog` / `answer_modal` (`tests/qgis/conftest.py`).
- **Never two line preparations at once:** they segfault (`slices_engine.py` docstring, lines 86–111). A standalone engine starts only when `dock.engine.has_live_task` and `dock.site_engine.has_live_task` are both False.
- **Exporting never changes what the Slices panel shows** (spec call 2).
- **No site coordinates, real survey files or site pictures are committed.** Sunnyside's origin and the trial prototypes stay outside the repo.
- **Commits:**
  - every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - push each one to `origin nsgeo-m16` as you make it;
  - the sandbox cannot resolve github.com, so pushes need it turned off.
- **Other open branches touch the same files:**
  - `nsgeo-m15-cut-anywhere` (`slices_dock.py`, `plugin.py`, `layers.py`);
  - `nsgeo-fine-cells-export` (`site_export.py`, `plugin.py`);
  - `nsgeo-auto-destagger` (placement, Edit lines).

  Before Task 3, run `git fetch && git merge origin/main`.
## Review Focus

These are the inputs the spec implies, but none of its tests feed. Each is pinned by a test in the task named.

1. **A preset with no `time_zero`** (radar clock): the picks must still land on their reflections. Each pick time moves from its row's `zero_ns` to the cube's clock. *Task 3:* `test_picks_land_on_the_cube_clock_with_and_without_time_zero`.
2. **A grid with no picks:** `picks.vtp` is still a valid file, and the scene still opens. *Task 2:* `test_an_empty_point_set_is_a_valid_file`. *Task 2 pvpython test:* run on an export with no picks.
3. **Cancelling halfway, or failing:** the previous export of that grid stays intact, and no half-written folder looks complete. *Task 3:* `test_a_cancelled_export_leaves_the_previous_one_intact`.
4. **A grid velocity with two layers:** the volume's depth axis is uniform, and picks use the same depth conversion. *Task 1:* `test_layered_velocity_gives_a_uniform_depth_axis`. *Task 3:* `test_pick_depths_use_the_volume_velocity`.
5. **A 3-D cell size so fine the frame exceeds `MAX_FRAME_CELLS` (4,000,000)**: the dialog refuses it and says why, the way the Slices panel does. Nothing is written. *Task 4:* `test_a_too_fine_cell_is_refused_before_export`.

