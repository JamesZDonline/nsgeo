# Task 3 report: the export (M16 A)

## Implemented
- core `project.py`: `_clean_volume` (cell, dz_ns, transform, stretch, period_ns, blur_m, trend_m; positives checked, blur >= 0, unknown keys dropped); `_clean_slice_source` keeps `"volume"`.
- `session.py`: `volume_record`, `remember_volume` (dirty only on change, via `_update_source`).
- `slices_plan.py`: `VolumeChoice`, `volume_choice`, `export_size_bytes`, `too_fine_for_export` (R3), `DEFAULT_STRETCH`.
- `paraview_scene.py`: `scene_title(grid, stretch)` (wording lives there).
- `paraview_export.py`: `ParaViewExport` (`defaults`, `estimate`, `run(..., paraview_path="")`), `ParaViewExportCancelled`, `paraview_folder`.
  - Lines: the dock engine's when `same_source` + prepared + no live task (read only); else refuse with "Slices are still preparing" if either dock engine has a live task; else a standalone `SliceEngine`, disposed in `finally`.
  - Fill cache `.cache/<grid>-<key>.npy` written as `.part` then renamed (a cancel never leaves a half cache), key = sha1 of nsgeo version, per-line key/shape/dt/t0/zero/coords hash, steps, transform, cell, dz, t0, t1, finish, frame. On a hit no cube is binned and no weights planned. Other cache files of the grid deleted.
  - Progress = fill levels + trend slabs + written slabs (strength pass); `VolumeStopped` -> `ParaViewExportCancelled`. Slab size adapts to frame cells.
  - `cube.vti`: strength pass also stores amplitude in a scratch memmap (so the slab is computed once for the two arrays); p99 from a per-slab sample; deepest slab first, flipped per slab. `picks.vtp` (`true_depth_m` f32, `line` i32, per R2), `lines.vtp` (<=200 pts/line + outline), scene via `scene_record` (R9 slices; all plain Python types).
  - `.partial` swap with `.old`; any exception removes `.partial`.
  - `estimate` (R4): dock engine's `prepared_z_bounds()` when matching, else line headers; for a time_zero preset a one-file probe of the first line's zero under the preset (cached). Prepares nothing.

## Tests
- core test_project.py: 73 passed. pure: 279 passed, 2 skipped. core suite: 1125 passed, 4 skipped.
- QGIS: test_plugin_paraview_export.py (9), test_plugin_slices_engine.py (70 in the 79 with it), test_plugin_slices_dock.py 165 passed.
- ruff check, ruff format --check, mypy (CI command): clean.
- Mutation check: forcing the pick target clock to 0.0 fails `test_picks_land_on_the_cube_clock_with_and_without_time_zero`; restored.

## TDD
- RED (core): `test_slice_sources_and_site_view_round_trip` and the new volume-entry test failed (volume dropped by the loader) before `_clean_volume`. Pure/QGIS tests were written ahead of the code but their pre-implementation RED run was not captured (the modules did not exist: ImportError).
- GREEN: as above.
- The picks test finds the cube's own strength peak over a line, stores a pick there on a different clock (radar clock with time_zero; pick zero 7 ns without), re-exports, asserts the pick is within 2 levels of the peak.
- Site folder in the fixture is `my site` (space), so the rename/swap paths are exercised with spaces.

## Measured
One real export (4 real lines, 3 x 12 m grid at 0.25 m, native dt, ~460 depth levels): ~1.4 s test wall time; process peak RSS 267 MB (whole pytest + QGIS process). Estimate within 5% of cube.vti size (asserted).

## Concerns
- The estimate's time_zero case assumes the cropped start is at or before time zero; accurate to <5% on the real lines but another preset (e.g. one that crops the sample axis at the end) could drift further. Documented in code.
- A hit of the fill cache assumes the key captures everything: edits to raw line files outside nsgeo are not detected.
- `run` blocks in `wait_for_preparation` (nested event loop) when it must prepare lines itself; Task 4 should call it from the GUI thread with a progress dialog.
- `Pick` for lines not in the prepared set are skipped.

# Fix round 1

Base: 64002c1 (M15 merged), confirmed with `git log -1`.

## F1: two tests on synthetic lines
`test_a_second_preparation_is_refused_while_the_dock_is_preparing` and `test_a_too_fine_cell_is_refused_before_anything_is_prepared_or_written` now use a `synth_site` fixture (two `synthetic_dzt` lines), no `needs_real_data`. Proof with `REAL_DZT` emptied (`tests.real_data.CAMPUS_LINES[:] = []` before `pytest.main`): `2 passed, 10 skipped`.

## F2 (R12): the never-two-preparations guard
- `SiteEngine.add_exclusive` / `remove_exclusive` (site_engine.py); `_anything_live` already read `_exclusive_with`. `remove_exclusive` restarts the retry timer when grids are queued.
- `SlicesDock.foreign_preparation(engine)` context manager (slices_dock.py): registers the engine with the site engine and in `_foreign`; `prepare()` and `_run_pending_grid_prepare` treat a live foreign engine like `site_engine.has_live_task` (pending flag + the existing 50 ms retry timer); on exit unregisters and restarts the grid retry if work is owed.
- `ParaViewExport._prepared`: refuses also while `site_engine.is_running`; wraps set_source / wait / dispose in `dock.foreign_preparation(own)`; waits with `ExcludeUserInputEvents`.
- Test `test_the_standalone_engine_holds_both_dock_engines_back` (real lines, real SlicesDock): while the export's engine is live a grid-engine `prepare()` and a site-engine `set_source` start nothing (only one `_start_task` began), the grid prepare is pending; afterwards both complete (no deadlock). Mutation checks: removing the dock's `_foreign_live()` gate fails it; making `add_exclusive` a no-op fails it.

## F3 (R14): no scratch file
`amplitude.tmp` removed; the amplitude pass recomputes each slab and the p99 sample is taken there. Progress total is now fill levels + 3 x slabs (trend, strength, amplitude). New `ParaViewExport.cache_bytes(grid_id, choice)`: bytes the fill cache adds (npy header 128 + 4*nz*ny*nx), 0 when the cache exists (exact key when the panel's lines match; otherwise any cache file of the grid with the needed shape). Test `test_cache_bytes_states_what_the_cache_adds_then_zero`: within 1% of the real cache file, 0 after the export, nonzero for another dz, 0 with the panel unprepared.

## R13: cancel in the write pass
`test_a_cancel_during_the_write_pass_leaves_the_previous_export_intact`: cancels on the last slab of the amplitude pass, asserts `.partial` existed at that moment, the previous export is byte-identical, no `.partial` / `.old` remain.

## Commands
- ruff check / ruff format --check / mypy (CI command): clean.
- pure: 279 passed, 2 skipped.
- test_plugin_paraview_export.py: 12 passed.
- core: 1224 passed, 4 skipped.
- QGIS (paraview_export, slices_dock, slices_engine, cut_sections, site_export, site_engine, site_scope): 509 passed. test_no_orphan_signals is in the pure run (279 passed): no new signals.

# Fix round 2 (R15)

1. cache_bytes (Important): cache files are now `<safe>-<settings key>-<full key>.npy`. The settings key (line keys and placements, preset steps, transform, cell, dz, finish, frame) needs no prepared line. `cache_bytes` returns 0 only for an exact name (panel's lines) or a file with this settings key and this shape; otherwise the full size. Cleanup and lookup use an exact regex `<safe>-<16 hex>-<16 hex>.npy`, so grid "A" never touches "A-2". Tests: `test_cache_bytes_states_what_the_cache_adds_then_zero` (after an export, a different transform with the panel unprepared states the full size, within 1% of the file the run then writes); `test_one_grids_cache_cleanup_leaves_another_grids_alone`.
2. Retiring engines: `foreign_preparation` keeps the engine registered (grid gate and site peer) when its task is still live on exit; a 50 ms `_foreign_reaper` timer (slot guarded) unregisters it once `has_live_task` is False. Test `test_an_engine_whose_task_outlives_its_span_still_holds_both_dock_engines_back`.
3. Wiring tests: `test_the_export_registers_its_engine_and_waits_without_user_input` (fake Dock's `registered` list captured during the wait, and the flags spied) and `test_a_site_engine_with_grids_queued_refuses_the_export` (synthetic, runs on CI).
4. Hygiene: `own.dispose()` in a `finally`; the `running` dict replaced by a `started_tasks` list.

Mutation checks (PYTHONDONTWRITEBYTECODE=1, code restored each time), each killed by the named test: no `with foreign_preparation`, no ExcludeUserInputEvents flag (wiring test); no `site_engine.is_running` refusal (queued-grids test); glob cleanup (neighbour test); no retiring (outlive test); any-shape cache hit (cache_bytes test).

Runs: ruff check, ruff format --check, mypy clean; pure 279 passed, 2 skipped (includes test_no_orphan_signals, no new signals); core 1224 passed, 4 skipped; QGIS paraview_export (16), slices_dock, slices_engine, cut_sections, site_export, site_engine, site_scope: 513 passed.

# Fix round 3

1. Version in the cache name: `_settings_key` now includes the nsgeo version; a comment lists what `_cache_key` adds (only prepared-line data and t0/t1). Test `test_a_version_bump_states_the_full_cache_then_writes_it` (version monkeypatched: full size stated within 1%, then written). Mutation (version removed from the settings key) is killed.
2. R16: `SlicesDock.foreign_preparing` (any registered foreign engine live, retiring ones included); `_prepared` refuses with the "Slices are still preparing" message when it is true; the fake Dock has `foreign_preparing = False`. Test `test_a_second_export_is_refused_while_the_first_exports_engine_is_live` (real SlicesDock, first engine kept live past its span, second `run()` refused before any `set_source`). Mutation (refusal clause removed) is killed.

Runs: ruff check, ruff format --check, mypy clean; pure 279 passed, 2 skipped; core 1224 passed, 4 skipped; QGIS paraview_export (18), slices_dock, slices_engine, site_export, site_engine, site_scope: 483 passed.
