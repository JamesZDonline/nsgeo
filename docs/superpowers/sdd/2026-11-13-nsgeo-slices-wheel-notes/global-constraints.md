## Global Constraints

- **Both Qt versions.** QGIS 3.44 (Qt 5) and 4.2 (Qt 6) must both pass. Import Qt only through
  `qgis.PyQt`, and spell enums out in full (`Qt.FocusPolicy.StrongFocus`).
- **Guard every Qt entry point.** Every Qt override, event filter and slot guards its own body with
  `except Exception`, reporting through `_log` or the dock's existing path. Nothing raises into Qt.
- **Wheel rule scope.** It applies to `cell_spin`, `dz_spin`, `z0_spin`, `z1_spin` and the Edit
  lines per-row Grid combos only. No other widget's wheel behaviour changes.
- **One place per message.** A refusal shown in Warnings is never also emitted on `error` (the
  toast). `Resolution.__post_init__`'s own refusals ("t1_ns must exceed t0_ns", "dz_ns must be
  positive") stay toasts.
- **Records stay as saved.** A floor raise changes the box only, never a remembered resolution, a
  site resolution or a cube record.
- **Exact copy:**
  - the level-limit message: *"Too many levels: dz 0.2165 ns from 0 to 100,000 ns makes 461,894
    levels; this cube allows 1,024 (twice the 512 samples in each line). Narrow z0–z1 or raise
    dz."*;
  - the preview note (Task 2);
  - the coverage tooltip (Task 4).
- **Settings.** Tests never read or write a real QGIS settings file. Fold state goes through
  `nsgeo_qgis.ui.folds.fold_settings()`, which the test conftest replaces (Task 4).
- **Local data stays local.** Never `git add` anything under `packages/nsgeo-core/tests/data/local/`
  except its README (its entries in this worktree are symlinks).
- **Commits.** Push each commit as it is made: `git push origin nsgeo-slices-wheel-notes`. End
  commit messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **How to run tests.** Run from the worktree root
  (`<repo>/.worktrees/nsgeo-slices-wheel-notes`):
  - QGIS tests:
    `QT_QPA_PLATFORM=offscreen ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/<file> -q`
  - pure tests: `../../.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q`

**Setup, done by the controller before Task 1:** link the real data into this worktree as the other
worktrees do (`for f in ../../packages/nsgeo-core/tests/data/local/*; do [ "$(basename "$f")" = README.md ] || ln -s "$(realpath "$f")" packages/nsgeo-core/tests/data/local/; done`),
so the `needs_real_data` tests run.

