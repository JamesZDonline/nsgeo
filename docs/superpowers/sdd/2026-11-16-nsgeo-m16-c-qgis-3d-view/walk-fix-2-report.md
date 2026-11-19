# Walk-fix 2 report (M16 Plan C, on d70900f)

## Changes
- R18: scene3d.py `_on_layers_will_be_removed` also counts every id in `self._applied` as managed; surface_layers.py `_sync` drops the layer before deleting its `_shown` entry.
- R19: Slices preview folder is `mkdtemp(prefix=nsgeo-slice-<pid>-, dir=<CacheLocation>/nsgeo)` via module-level `cache_root()` (monkeypatchable); fallback to old temp mkdtemp with one log line. First folder per process sweeps dead-pid `nsgeo-slice-<pid>-*` folders (`os.kill(pid,0)`, POSIX; non-POSIX or unsure keeps the folder; never raises). Pure helpers `slice_dir_prefix`, `slice_dir_pid`, `stale_slice_dirs` in slices_plan.py. `skipMemoryLayersCheck` line and its test removed. tests/qgis/conftest.py autouse fixture points `cache_root` at tmp_path.
- R20: dock loading test rewritten (nothing stored, clean site, choose grid, refresh, switch away and back); plus a second test (grid at 2.0 to a grid with nothing stored), because with M2 the box rests at 3.0 so a first-grid load fires no valueChanged and the first test alone cannot catch the missing guard.
- R21: guide says the box turns on for grids that have a surface; grid with picks only shows at stored stretch or x3. Tooltip already did not imply otherwise.
- M1: renderer recorders (picks + each surface layer) added to `test_closing_the_site_closes_the_view`; direct-removal picks test removed.
- M2: box constructed at DEFAULT_STRETCH, disabled; All grids sets DEFAULT_STRETCH under `_loading`.
- M3: `_clean_slice_source` drops view_stretch <= 0; STRETCH_MIN/MAX already lived in scene3d_plan, `scene_stretch` now clamps to them (used by `SiteSession.view_stretch`).
- M4: `set_view_stretch` raises ValueError for non-number/bool.

## RED evidence (mutants applied then restored; never committed)
- R19 isTemporary test: with `cache_root` returning None (old temp behaviour) it FAILED (first attempt with tmp_path also showed `True is False`). The test uses Qt test mode (`~/.qttest`) because pytest tmp_path is itself under the temp folder, so isTemporary stays True there.
- R18 fix 1 reverted: `test_a_layer_only_the_view_applied_a_renderer_to_is_cleared_too` FAILED.
- R18 fix 2 reverted: `test_surface_layers_keep_a_surface_until_its_layer_is_removed` FAILED.
- The panel-path test (`test_deleting_a_surface_with_the_view_open_clears_its_renderer_first`) passes with either fix alone (the other covers it); fails only with both reverted (not run).
- R20: `self._loading or` removed: new test `test_showing_another_grids_default_never_writes_it` FAILED; the rewritten single-grid test passes with that mutant (reason above).
- M1-M4, sweep, pure helpers: new tests assert new behaviour (clamp 100 -> 50, -2.0 dropped, "x"/True/None raise ValueError, dead-pid folder removed); RED not individually run against d70900f.

## Tests
- core + pure: 1805 passed, 8 skipped, 1 xfailed.
- QGIS scene3d, surfaces_dock, session, slice_layer, loads, own_colours, slice_export_dialogs, site_scope: 499 passed; surface_layers: 16 passed.
- ruff check/format clean; mypy (core + slices_plan + scene3d_plan) clean.

## Concerns
- isTemporary test relies on Qt test mode, writes under ~/.qttest/cache/nsgeo (emptied on dispose).
- Windows: sweep keeps all folders (cannot tell).
