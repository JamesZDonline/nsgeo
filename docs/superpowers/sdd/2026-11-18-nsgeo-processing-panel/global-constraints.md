# Global constraints (verbatim from the plan; binding on every task)

- Run from the worktree root /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-processing-panel; shares the main checkout's venvs (M=/home/jameszd/Documents/Github/archaeo_geophysics).
  - One QGIS file: `PYTHONDONTWRITEBYTECODE=1 packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/<file> -q -p no:cacheprovider`
  - Real data: `PYTHONDONTWRITEBYTECODE=1 packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q -p no:cacheprovider`
  - Core and pure: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src $M/.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh -p no:cacheprovider` (PYTHONPATH required)
  - Lint: `$M/.venv/bin/ruff check . && $M/.venv/bin/ruff format --check .`
- Before reporting done: own test files; test_plugin_processing_dock.py, test_plugin_profile_dock.py, test_plugin_gain_strip.py, test_plugin_difference_presets.py; core+pure; lint. Not the whole QGIS tier.
- Each test that pins a bug must fail before its fix (report how). A guard test says so in its docstring and names the mutation that makes it fail.
- Temporary mutations reverted by hand; `git diff` shows only intended changes before commit. Never `git stash`.
- Every Qt slot and override guards its own body (try/except Exception/_log in UI files; self.message(...) in plugin.py).
- The Processing panel must not get wider: every new label word-wraps with QSizePolicy.Policy.Ignored horizontally (test_plugin_slices_width.py pins Slices to ProcessingDock(session).minimumSizeHint().width()).
- Leave alone: velocity strip / velocity-fit code in profile_dock.py; param_form.py; every plugin.py slot except the gain slots and unload().
- The toast (ProfileDock.error → plugin.message) still announces each refusal; the note is added to it (spec §3.1).
- Real data via plugin_testing.REAL_DZT + needs_real_data, FILE__007.DZT by name (Δt 0.2165 ns). Never read/write the author's own projects.
- Commits: feat(processing)/fix(gain-strip)/test(…)/docs(guide) …, ending with the implementer's own Co-Authored-By line. Coordinator pushes.
- Spec texts (verbatim): REFUSAL_TEXT "{title} (step {n}) can't run on this line: {reason} The profile won't update until this is fixed."; REFUSAL_COLOUR QColor(163, 18, 44); STEPS_REFUSED_TEXT "This line's steps can't run. See the Processing panel."; PREVIEW_STEPS_REFUSED_TEXT "{name}'s steps can't run. Select it to see why in the Processing panel."; RESET_QUESTION "Reset the gain curve to a flat 0 dB? Its {n} points will be lost."; RESET_TITLE "Reset gain curve"; DB_LIMIT 120.0; PREVIEW_SUFFIX " · the profile is previewing {name}".
