## Approved behaviour

1. **#74, one reading of the line record.** The line chooser, which both scopes share, greys out OK while no line is ticked *(call: greyed out, with the tooltip "Tick at least one line.")*. A remembered line choice that filters to nothing on the grid means *every line*, in both scopes. *Whole site* never shows such a grid as `no lines`. Only the site list's tick boxes take a grid out of the site. An old cube record with no `lines` key restores every line.
2. **#70 and #75 F-9.** If a row is selected in the site list and it names a grid other than *This grid*'s, switching to *This grid* opens that grid at the same window time, with that grid's remembered preset, lines and (after Task 4) resolution. With no such selection, *This grid* comes back exactly as it was left, as it does today. *(Call: the switch is not a source choice, so nothing is remembered and the survey is not marked dirty by it.)* The hand-back of This grid's grid-move hook runs from a `finally`.
3. **#72.** *This grid*'s Fill radius is set as `× line spacing`, like *Whole site*: range 0–10, 2 decimals, step 0.25, seeded at 0.5. The radius in metres is shown in a label beside the box *(call: beside it, not in a tooltip, since there is one grid)*. Saved cube records keep `radius_m` in metres. Opening an old record converts it to spacings, so the picture comes back the same. The GeoTIFF still records the radius in cells.
4. **#71.** Each grid remembers its cell size, dz, z0, z1 and fill radius (in spacings), saved in the survey. *Whole site* remembers its own set. A value is remembered only when the user changes it, so seeds, restores and clamps never write anything, and opening a survey never marks it dirty. Each field is remembered on its own *(call)*: changing the cell does not freeze a z range that was only seeded. Opening a saved cube counts as a choice: its settings become that grid's remembered ones *(call, matching how a cube's preset and lines are already remembered)*. A remembered z range is still clamped to what the prepared lines cover, and a remembered cell still respects the grid's size floor. Slice thickness and step are not included.
5. **Tidy-ups.** From #75: the unguarded `_note_z_edit` slot (removed in Task 5), the stale `_remember_source` docstring, the missing "opening a survey that has saved cubes stays clean" test, the import pick-up test that dodges the save → reopen → import path, the self-comparing velocity assertion, the `ds = None` pattern in M11's export tests, and the untested site seeding rules (pinned in Task 5). From #54's slice-preview section: the two wrong docstrings and the persistent-failure test that fakes its failure.

Out of scope: #73 (slider lag; the user deferred it), #47, #50, and every other #75 item.

## Global Constraints

- Every slot connected to a Qt signal or timer guards its own body and reports through `_log` or `dock.error`, never raises (an exception escaping a slot aborts the CI container). Read the module docstrings of `slices_dock.py` and `site_scope.py` before touching either.
- R-P5 stands: This grid's engine never starts a preparation while a site task is live. Every This-grid preparation goes through `SlicesDock.prepare()` or `_run_pending_grid_prepare()`, never `engine.set_source` directly.
- Opening a survey, switching scope, seeding, restoring and clamping never mark the survey dirty and never write a remembered value. Only a user's edit, a line choice, or picking a saved cube writes one.
- Old surveys and old cube records keep loading. `SCHEMA_VERSION` does not change. The loader stays tolerant: a remembered value of the wrong type or out of range reads as unset and never blocks opening.
- Core stays numpy-only, with no Qt imports. `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` stay green. The plugin imports Qt only through `qgis.PyQt`.
- Remembered resolution keys are exactly `cell`, `dz_ns`, `t0_ns`, `t1_ns`, `radius_spacings`. The first four are the names a cube record and `Resolution` already use.
- Comments and docstrings follow the file they are in: they say why, and cite the issue (`#74`) the way the existing ones cite rulings.
- ruff 0.17.1 and mypy 2.4.0, as pinned in CI.
- End every commit message with the `Co-Authored-By` trailer the coordinator gives you. Push each commit to `origin nsgeo-slices-cleanup` as it is made.

## Verification commands (exactly these, from the worktree root)

- core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- qgis: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh` (about 11 minutes; run single files while iterating)
- lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- types: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`

Baseline at `7069959`, with the real DZT files copied into `packages/nsgeo-core/tests/data/local/`: core+pure **808 passed, 3 skipped**; qgis **1320 passed**. A real-data test that skips has validated nothing, so check the skip count stays at 3.

## Review Focus

These are the inputs most likely to hurt a user that the issues don't name. Each is pinned by a test in the task named.

1. **A remembered z range wholly outside what the lines now cover.** For example, z0 = 80 ns is remembered, then a time cutoff crops the lines at 50 ns. Clamping each end on its own gives z1 < z0, and every slice then fails with a `Resolution` error. Expected: fall back to the prepared range and keep the remembered values (Task 4: `test_a_remembered_z_range_wholly_outside_the_data_falls_back_to_the_prepared_range`; Task 5: the site's twin).
2. **A hand-edited or damaged survey file.** Examples: `resolution` is a list, a cell given as a string, a zero or negative cell or dz, NaN, a negative radius, `t1_ns <= t0_ns`, a boolean. Expected: each bad value reads as unset, and the survey opens (Task 4: `test_a_bad_remembered_resolution_value_reads_as_unset`).
3. **A grid's line spacing edited after its radius was set.** The radius is in spacings, so the metres label and `radius_cells()` must follow the new spacing without a grid switch (Task 3: `test_the_radius_follows_a_line_spacing_edit`).
4. **The selected site row's grid removed while Whole site shows.** Expected: switching to *This grid* falls back to today's behaviour and never raises (Task 2: `test_a_selected_grid_removed_meanwhile_falls_back_to_this_grids_own`).
5. **A cube saved on a grid whose spacing has changed since.** The record's `radius_m` is metres and the box is spacings, so the conversion must use the grid's spacing at restore time, keeping the metres (Task 3: `test_a_cube_saved_before_a_spacing_edit_keeps_its_radius_in_metres`).

## Process rules for every task

- Commit trailer (last line of every commit message): `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` — or your own model's name; either is fine.
- Push each commit with `git push origin nsgeo-slices-cleanup` as soon as it is made.
- Work only in /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-slices-cleanup. Never `cd` to the main checkout, never switch branches, never use bare `git stash`.
- Do not dispatch subagents.
- The real DZT files are already in packages/nsgeo-core/tests/data/local/; the core+pure skip count must stay at 3.
- `ruff format` the files you touch before committing; lint must be clean.
