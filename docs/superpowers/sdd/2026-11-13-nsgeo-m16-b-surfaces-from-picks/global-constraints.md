## Global Constraints

- **Run every test from the worktree root with `PYTHONPATH=packages/nsgeo-core/src`.** Below, `R=/home/jameszd/Documents/Github/archaeo_geophysics`.
  - **Core and pure:** `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`
  - **QGIS:** `PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen $R/.venv-qgis/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`. The whole tier takes about 22 minutes, so run single files while iterating.
- **Lint as CI does,** with line length 100:
  - `$R/.venv/bin/ruff check .`
  - `$R/.venv/bin/ruff format --check .`
  - `$R/.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py packages/nsgeo-qgis/nsgeo_qgis/surface_plan.py`

  `surface_plan.py` joins the mypy list. Add it to `.github/workflows/ci.yml` too.
- **The core uses numpy only.** It has a Python 3.9 floor: `from __future__ import annotations`, no `zip(strict=...)` and no `match`. No new dependency anywhere. The pure tier runs 3.9 in CI.
- **No ParaView code lives in a `.py` file inside `packages/`.** Scene code goes in the `.txt` templates in `packages/nsgeo-qgis/nsgeo_qgis/paraview/`.
- **Plugin boundary.** Arithmetic and message text live in the core, `surface_plan.py`, `slices_plan.py` or `paraview_scene.py`, never in widgets.
- **Qt.**
  - Use fully qualified enums.
  - Every Qt-invoked slot guards its body with `try/except Exception`.
  - Every new `pyqtSignal` is connected (`tests/pure/test_no_orphan_signals.py`).
  - Modal dialogs in tests go through `drive_dialog` / `answer_modal` (`tests/qgis/conftest.py`).
- **The site GeoPackage's rules hold for the new table** (`layers.py`, module docstring):
  - **Every write goes through a loaded layer's data provider,** never a second OGR handle.
  - **`picks` and `features` are authored:**
    - nothing ever drops or recreates either of them;
    - a CRS change leaves `features` alone;
    - feature edits go straight to the package, like picks, and never mark the site dirty.
- **Never two line preparations at once:** they segfault. A build gets its lines only through `ParaViewExport`, which already refuses while anything else prepares.
- **Surfaces never change what the Slices panel shows**, and nothing the Slices panel shows makes a surface stale (spec call 9).
- **No site coordinates, real survey files or site pictures are committed.** The parity check in Task 1 runs outside the repo.
- **Commits:**
  - every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - push each one to `origin nsgeo-m16-b` as you make it, with the sandbox turned off (it cannot resolve github.com).
- **Keep up with Plan A.** Before each task, run `git fetch && git merge origin/nsgeo-m16`; Plan A's walkthrough fixes land there. Once Plan A merges, merge `origin/main` instead.
- **Other open branches touch the same files:**
  - `nsgeo-grid-velocity`: where slices get their velocity (`session.py`, `slices_engine.py`, `ui/site_scope.py`). Surfaces take their velocity from the same place the export does (`ParaViewExport`), so that fix reaches both.
  - `nsgeo-own-colours`: `slices_dock.py`, `slice_layer.py`.

## Review Focus

These are the inputs the spec implies but none of its tests feed. Each is pinned by a test in the task named.

1. **No cell passes the strength test** (a faded patch, or a strength test set high). The build succeeds with an empty surface and says so. There is no map layer and no error, and the export still writes a valid file. *Task 1:* `test_a_surface_with_no_cell_passing_is_empty_not_an_error`. *Task 4:* `test_an_empty_surface_has_no_layer_and_exports_cleanly`.
2. **Picks edited in QGIS's own editing mode.**
   - Unsaved picks are refused, with a message saying to save the picks layer first.
   - A member deleted by hand makes its surface stale; it never causes an error.

   *Task 2:* `test_unsaved_picks_are_refused_until_saved`. *Task 3:* `test_a_member_deleted_by_hand_marks_the_surface_stale`.
3. **Cancelling a build, or rebuilding while the surface's layer has its files open** (Windows locks them). The previous build stays whole and on the map. *Task 3:* `test_a_cancelled_build_keeps_the_previous_one`. *Task 4:* `test_a_rebuild_writes_new_files_and_swaps_the_layer`.
4. **A pick above time zero, below the last level, or outside the grid's frame.** The pick is reported as on a hole, never fatal. *Task 1:* `test_a_pick_outside_the_depth_range_or_frame_is_reported_not_fatal`.
5. **Names with quotes, slashes, accents, surrounding spaces, or a name already taken.**
   - Names are trimmed and unique within the site.
   - Files are named by feature id, never by name.
   - The ParaView scene still opens.

   *Task 2:* `test_names_are_unique_trimmed_and_never_used_in_paths`. *Task 4:* `test_scene_opens_with_a_surface_whose_name_has_quotes`.

## Calls this plan makes (the spec left them to the builder, §11)

1. **Built geometry.** Every build is saved in `<site>/surfaces/<safe grid>/` as four files:
   - `<id>-<build>.npz`: the depth grid, the build's own record;
   - `<id>-<build>.2dm`: the mesh, in the grid's CRS, with Z = −depth;
   - `<id>-<build>.dat`: a "depth (m)" dataset, so the map's legend reads in positive metres;
   - `<id>.json`: the provenance and the fit.

   `<build>` is the first 8 characters of the build's key. A rebuild therefore never overwrites a file a map layer has open.

   A 2DM mesh draws in both 2-D and 3-D, so Plan C reuses it. A probe on 3.44 confirmed that QGIS loads a 2DM with an ASCII DAT, an empty one included.
2. **The `features` table** has these columns: `feature_id`, `name`, `grid_id`, `kind`, `settings_json` and `created`.
   - `SiteLayers` holds it as a layer, but never adds it to the project or the Layers panel. Surfaces are edited only through nsgeo.
   - `seq` on the picks stays null; a surface needs no order.
3. **Picks already in another surface move** when they are added to a new one. The New surface dialog says so before anything changes.
4. **Picks on cuts are refused** until Plan D.
5. **Building remembers the grid's 3-D choice,** as exporting does (`session.remember_volume`). After that, changing the Slices panel's transform or cell can never change a surface's inputs.
6. **"The volume parameters" in staleness are the wave period and the depth-balance window.** The sideways blur is left out, because a surface never uses it (call 17).
7. **Sub-sample peak:** a parabola through the peak and its two neighbours, clamped to half a step and to the window. It is used for the offset and for tracking alike.
8. **Outliers** are picks more than the window away from the surface, or on a hole.
9. **The feature list** is a Surfaces dock, tabbed with Slices, as in the mockup's option A, which the user chose (Task 5).

## Calls this plan makes (the spec left them to the builder, §11)

1. **Built geometry.** Every build is saved in `<site>/surfaces/<safe grid>/` as four files:
   - `<id>-<build>.npz`: the depth grid, the build's own record;
   - `<id>-<build>.2dm`: the mesh, in the grid's CRS, with Z = −depth;
   - `<id>-<build>.dat`: a "depth (m)" dataset, so the map's legend reads in positive metres;
   - `<id>.json`: the provenance and the fit.

   `<build>` is the first 8 characters of the build's key. A rebuild therefore never overwrites a file a map layer has open.

   A 2DM mesh draws in both 2-D and 3-D, so Plan C reuses it. A probe on 3.44 confirmed that QGIS loads a 2DM with an ASCII DAT, an empty one included.
2. **The `features` table** has these columns: `feature_id`, `name`, `grid_id`, `kind`, `settings_json` and `created`.
   - `SiteLayers` holds it as a layer, but never adds it to the project or the Layers panel. Surfaces are edited only through nsgeo.
   - `seq` on the picks stays null; a surface needs no order.
3. **Picks already in another surface move** when they are added to a new one. The New surface dialog says so before anything changes.
4. **Picks on cuts are refused** until Plan D.
5. **Building remembers the grid's 3-D choice,** as exporting does (`session.remember_volume`). After that, changing the Slices panel's transform or cell can never change a surface's inputs.
6. **"The volume parameters" in staleness are the wave period and the depth-balance window.** The sideways blur is left out, because a surface never uses it (call 17).
7. **Sub-sample peak:** a parabola through the peak and its two neighbours, clamped to half a step and to the window. It is used for the offset and for tracking alike.
8. **Outliers** are picks more than the window away from the surface, or on a hole.
9. **The feature list** is a Surfaces dock, tabbed with Slices, as in the mockup's option A, which the user chose (Task 5).

