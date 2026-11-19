# Walk-fix round 2: M16 Plan C review findings on d70900f

- **Branch:** `nsgeo-m16-c`
- **Worktree:** `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m16-c`
- **Head:** d70900f

d70900f is the fix commit for the author's walkthrough. Its requirements are in `walk-fix-brief.md`, in this folder; read that first for context. An independent review of d70900f is in `walk-fix-review.md`, also in this folder; read it in full, because it has file:line references, scenarios and probes.

Fix everything below in one pass. Each fix needs a test that fails without it: show the RED in your report.

## R18: deleting a surface with the 3-D view open (review C1, Critical)

`SurfaceLayers._sync` pops the `_shown` entry before `_drop_layer` removes the layer. As a result, Scene3D's `layersWillBeRemoved` handler doesn't see the layer as managed, and the layer is deleted with its mesh 3-D renderer still set. That is the walkthrough L2 crash class again.

Make **both** fixes:
1. In `scene3d.py` `_on_layers_will_be_removed`, also count every layer id in `self._applied` as managed. These are the layers Scene3D gave a renderer to. Scene3D must not depend on SurfaceLayers' bookkeeping order.
2. In `surface_layers.py` (about line 356), drop the layer **before** forgetting its `_shown` entry.

**Test:**
1. Open the view with a built surface.
2. Attach the `renderer3DChanged` recorder (`project.mapLayer(id) is not None`, `renderer3D() is None`) to that surface's layer.
3. Delete the surface the way the panel does (`Surfaces.delete(fid)`, then let `SurfaceLayers` sync).
4. Assert the renderer was cleared while the layer was still in the project.

The test must fail with **either** fix alone reverted. If one test cannot do that, write two: one that drives the handler directly with a layer that is only in `_applied`, and one through the panel delete path.

## R19: the Slices layer still triggers the "temporary layers" warning (review I1)

`skipMemoryLayersCheck` only works for memory-provider layers. The reviewer checked this in real QGIS 3.44.7: a GDAL raster under the platform temp folder counts through `QgsMapLayer::isTemporary()`, and the property makes no difference.

**Fix:** write the Slices preview files outside the temp folder.
- **Where the preview folder goes:** `tempfile.mkdtemp(prefix=f"nsgeo-slice-{os.getpid()}-", dir=<cache root>)`.
- **The cache root:** `QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)` + `/nsgeo`, created if missing.
  - The enum spelling must work on both PyQt5 and PyQt6 (QGIS 3.x and 4.2). Check how the repo already spells scoped enums.
  - If the location is empty or not writable, fall back to the old `tempfile.mkdtemp()`, and log one line through the module's existing log path.
- **Keep the existing `rmtree` cleanup.**
- **Sweep stale folders.** A cache folder isn't emptied on reboot, so when the first preview folder is made in a process, remove the `nsgeo-slice-<pid>-*` folders whose `<pid>` is not a running process.
  - Use `os.kill(pid, 0)` on POSIX (ProcessLookupError means it's gone; PermissionError means it's alive). On Windows, use `QgsApplication`-free stdlib only. If you can't tell, keep the folder.
  - Leave folders without a parseable pid alone, and never touch anything not named `nsgeo-slice-*`.
  - The sweep is best-effort and must never raise.
  - Keep the reasoning and the folder name in the pure plan module if the slices code has one (`slices_plan.py` or similar). The pid parsing is a pure function: test it in `tests/pure`.
- **Remove** the now-useless `skipMemoryLayersCheck` line from the slice layer, and the test that pins it.
- **Tests:**
  - `assert slice_layer.layer.isTemporary() is False`. This pins the outcome QGIS checks. Show it RED on d70900f.
  - The sweep removes a dead-pid folder, keeps a live-pid one (use `os.getpid()`), and keeps an unrelated folder.
  - Point the cache root at `tmp_path` in tests through a monkeypatchable module-level function, so tests never write into the real `~/.cache`.

## R20: the panel's "loading never writes" test (review I2)

Rewrite the test so it can fail:
1. With nothing stored for the grid, set the site clean.
2. Choose the grid in the Grid filter.
3. Refresh the panel.
4. Switch away and back.
5. Assert `"view_stretch"` is not in that grid's slice source, and the site is not dirty.

Show it RED with `self._loading or` removed from `_save_stretch`. Put the mutant only in a scratch copy, or revert it in the same breath; never commit it.

## R21: grids without a surface (review I3)

Keep the R17 ruling: the box edits the Grid filter's grid, and the filter lists grids that have surfaces. Fix the guide to match: the box turns on for a grid that has a surface. A grid with picks but no surface shows in the 3-D view at its stored stretch, or ×3 by default. Fix the panel tooltip wording too if it implies otherwise.

## Minors (review M1 to M4)

- **M1. Test the real site-close path.**
  - Add the renderer recorders, for the picks layer and a surface layer, to the existing `test_closing_the_site_closes_the_view` in `test_plugin_scene3d.py`, so it drives the real site-close path.
  - Remove or rename the direct-`removeMapLayer` picks test so that no test's name claims a path it doesn't drive.
- **M2. The box's resting value.**
  - At construction the box shows `DEFAULT_STRETCH` (3.0), not 0.1.
  - With "All grids" chosen, it shows `DEFAULT_STRETCH`, disabled. Set it under `_loading`.
- **M3. Stored values the box can't show.**
  - `project.py` `_clean_slice_source` drops a `view_stretch` that is ≤0 or not finite, as `gain` does. Add a core test.
  - Move the box's range (0.1, 50) into the plan module as constants. The box and `SiteSession.view_stretch()` both use them, and `view_stretch()` clamps to that range, so the view and the box always agree.
- **M4. Wrong exception for a non-number.** `set_view_stretch` raises `ValueError` for a non-number or a bool, not `TypeError`.

## Rules

- **Never** use `git stash`; never call the real `iface.createNewMapCanvas3D`; never stage `.superpowers/`.
- **Wording and slots:** guarded slots, and wording in the pure plan modules.
- **Commit:** one commit, ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push it to `origin nsgeo-m16-c`.
- **Running tests:** use `PYTHONDONTWRITEBYTECODE=1`, from the worktree root.
  - **pure:** `PYTHONPATH=packages/nsgeo-core/src /home/jameszd/Documents/Github/archaeo_geophysics/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`
  - **QGIS:** the same with `QT_QPA_PLATFORM=offscreen` and `.venv-qgis/bin/python`.
- **Lint:** `ruff check .`, `ruff format --check .`, and mypy as in `.github/workflows/ci.yml`.
- **What to run:**
  - while iterating, the files you touch;
  - at the end, the core and pure suites, then the QGIS files for scene3d, surfaces_dock, session, slice_layer and surface_layers, plus any other QGIS test file that greps for `mkdtemp`, `slice_layer` or `skipMemoryLayersCheck`.
  - **Do NOT run the whole QGIS tier**: CI runs it.
- **Waiting on background commands:** never wait with a `pgrep -f` loop. Its own command line matches the pattern, so it never ends (that cost 9 hours last round). Run tests in the foreground with a timeout.
- **Report:** write it to `walk-fix-2-report.md` in this folder. Return only the status, the commit, a one-line test summary and any concerns.
