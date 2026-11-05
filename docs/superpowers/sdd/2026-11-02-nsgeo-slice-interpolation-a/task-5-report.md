# Task 5 report: commit 5a4d54e (pushed to origin nsgeo-slice-interpolation)

## Implemented
Whole site through FinishPanel (dock.site_finish, metres_label=False); site engine/scope/export/plugin on `finish=`; disc fill retired (core fill.py, test_slices_fill.py, exports, clear_kernel_cache call); slices_plan DEFAULT_RADIUS_SPACINGS/radius_cells_for gone, Resolution docstring rewritten; project.py drops radius_spacings; session kwargs removed; bench_site.py uses SliceFinish(); guide step 3 rewritten, new step 4 Interpolation, later steps renumbered. core README rows for the removed names deleted.
`DISTANCE_TIP` in finish_panel.py was made public (renamed from `_DISTANCE_TIP`) so site_scope reuses the string.

## Carry-ins
- A1: rewrote test_plugin_site_engine (TICK/FINISH/NONE, expected_shown via engine.finish, radius 0 -> NONE), test_plugin_site_export (KW finish, new metadata asserts), test_plugin_site_scope (site_finish, export metadata, held_bytes), test_plugin_session (max_distance_spacings kwargs), test_project (keys). Removed test_the_fill_radius_follows_each_grids_own_line_spacing (pure; subject deleted).
- A2: test_a_0_2_0_remembered_radius_is_ignored kept green (comment updated). A3: "Fill radius" now absent and no radius_spacing_spin. A4: test_no_orphan_signals "edited" connects 2 -> 3.
- B8: `_on_finish_edited` guarded with try/except -> _log.
- C9: held_bytes adds each engine's `weights_nbytes` (new SliceEngine property = held FillWeights.nbytes). Chose actual held weights over the estimate's worst-case weights_bytes because the status line names what is held. Two tests that pinned held bytes updated.
- C10: "five Resolution widgets" -> "four" (3 places); "five session signals" left (really five). `_on_radius_changed` comment updated. C11 went with the function. D12: nsgeo-m14 untouched.
- `set_row_visible` removed (only user was the radius row); `dock._resolution_form` kept (a dock test reads it).

## New tests
Engine: finished_slice_times_gain, gains_commute (none/idw/kriging), shared_limit_measures_finished_slices, weights_cached, held_bytes_count_weights. Scope: each_scope_shows_its_own_panel, edit_remembered_for_site_not_grid, entering_restores_quietly (not dirty), edit_redraws, max_distance_tooltip exact text, different_survey_starts_site_finish_from_default. Export: carries_interpolation_metadata, coverage_companion_has_no_interpolation_metadata. Core: test_an_old_radius_spacings_is_dropped_on_load.

## Grep sweep
`grep -rnE "radius_spacings|radius_cells|Fill radius|DEFAULT_RADIUS|disc_kernel|clear_kernel_cache|fill\(|FILL_RADIUS" packages docs/guide`: remaining hits are all kept on purpose: plan_fill( (new interpolation API); QImage.fill, _refill/_prefill (unrelated); tests deliberately naming the old key (test_project drop test, test_a_0_2_0..., test_pure updated() ignore test, slices_dock.py comment about 0.2.0 records, a historical walkthrough quote in a test docstring); NSGEO_FILL_RADIUS_CELLS asserts in per-grid slice_export tests (asserting absence; Task 4's). docs/releases/0.2.0.md still describes 0.2.0 (historical).

## TDD
Honest deviation: I made the core deletions and project.py change before the core test edit, so core RED was reconstructed: project.py from HEAD in a /tmp copy on PYTHONPATH -> `test_an_old_radius_spacings_is_dropped_on_load` failed with `{'cell': 0.2, 'radius_spacings': 0.5} != {'cell': 0.2}`; GREEN with the change. Site engine tests: RED was the ImportError (`fill` gone from nsgeo.slices) at collection, then after implementing 45 passed. Site export: tests written first, 18 failed (unexpected `finish` kwarg), then 19 passed. Site scope tests were written before the production edit but not run individually before it; first run was after implementation. No mutants tried.

## Results
core+pure: 903 passed, 3 skipped (baseline ~921; the drop is test_slices_fill.py and the radius_cells test removed). Full QGIS: 1362 passed, 0 skipped (~11 min; run before commit with the held_bytes test fix included). ruff check + format --check clean; mypy clean (38 files).

## Self-review / concerns
- Slider drags in site scope call refresh_slice directly, so a slice-slider move that is first to need weights has no wait cursor; only the tick (edits, scope entry) does. Weights are normally built on the first tick.
- Site `_on_finish_edited` schedules the tick directly rather than via the 120 ms debounce; the tick coalesces per event-loop pass.
- Manual checkpoints (spec §10 walkthrough on ns-geo, early kriging offer) remain for the coordinator.
