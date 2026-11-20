## Global Constraints

- **Run every test from the worktree root with `PYTHONPATH=packages/nsgeo-core/src`.** Below, `R=/home/jameszd/Documents/Github/archaeo_geophysics`.
  - **Core and pure:** `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`
  - **QGIS:** `PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen $R/.venv-qgis/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`. The whole tier takes about 37 minutes, so run single files while iterating.
- **Lint as CI does:** `ruff check .`, `ruff format --check .`, and the mypy command in `.github/workflows/ci.yml` (job `lint`). The new core module is already covered, because the list includes all of `packages/nsgeo-core/src/nsgeo`.
- **The core uses numpy only,** with a Python 3.9 floor: `from __future__ import annotations`, no `zip(strict=...)` and no `match`. No new dependency anywhere.
- **No ParaView code lives in a `.py` file inside `packages/`.** Scene code goes in `packages/nsgeo-qgis/nsgeo_qgis/paraview/open_scene.py.txt`.
- **Plugin boundary.** Arithmetic and message text live in the core, `surface_plan.py`, `paraview_scene.py` or `slices_plan.py`, never in widgets.
- **Qt rules as in Plan C:** fully qualified enums, guarded slots, and no orphan signals.
- **Authored data.**
  - **Picks:** a cut pick is never moved, retimed or rewritten. Joining or leaving a surface changes only its `feature_id`, as for line picks.
  - **Cuts:** `survey.nsgeo.json` is never written by this plan.
- **The export's rules hold:**
  - it states its size before writing, and the size now includes the walls;
  - it refuses when the disk is too full;
  - it writes into `<grid>.partial` and swaps it in only when complete, so a cancel or a failure leaves the previous export whole;
  - no second full copy of the cube is held.
- **No site coordinates, real survey files or site pictures are committed.**
- **Commits:**
  - every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - push each one to `origin nsgeo-m16-d` as you make it.


### Coordinator amendments (ledger rulings R1, R5)

- **Local QGIS runs (R1):** use `packages/nsgeo-qgis/scripts/qgis_tests.sh <test files> -q -p no:cacheprovider` (offscreen, .venv-qgis, `-p no:xonsh`), with `PYTHONDONTWRITEBYTECODE=1` and `PYTHONPATH=packages/nsgeo-core/src`. Run the files you touch plus `qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data`. **Never run the whole QGIS tier**: CI runs it on 3.44 and 4.2 on every push.
- **Waiting (R5):** run tests in the foreground with a timeout. Never wait with a `pgrep -f` loop (it matches itself and never ends). Leave no background shells running when you report.
- **Never** use `git stash`; never stage `.superpowers/`.
