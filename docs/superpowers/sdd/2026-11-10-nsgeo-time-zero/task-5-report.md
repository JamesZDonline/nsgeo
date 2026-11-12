# Task 5 report: cubes on the time-zero clock

Implemented per brief: PreparedLine.zero_ns; SliceEngine.line_zero/median_zero; SiteEngine.line_zero; SlicesDock.line_zero_in_cube; cube_record(time_base) / CubeRecipe.time_base / recipe_from_record validation; store _meta "time_base"; old_cube_note; restore_cube sets _pending_z_shift (record has no time_base and its preset sets a time zero), _on_prepared consumes it (shifts both z spins by retime_ns(v, 0.0, median), emits the note once), cleared on every pass, on a manual source change and on an engine error; ProfileDock stores the cube-clock band, set_cube_zero_lookup, _push_slice_band (called from set_slice_band and _render), clear forgets; plugin wiring (time_base_of in the save call, lookup wired).

Deviation worth a look: the brief's formula for the shift is "5.0 - median"; I used retime_ns(v, 0.0, median) = v - median, the single conversion rule.
Extra: _on_engine_error also clears the pending flag (a failed preparation never reaches _on_prepared).

## TDD evidence
- test_slices_store: new test written after the code; confirmed FAIL (KeyError "time_base") against HEAD store.py in a scratch copy.
- Dock/export/pure tests also written after the code (I wrote implementation first by mistake); against a git-archive of HEAD with the new tests copied in, test_plugin_slices_dock.py fails at collection (old_cube_note missing), so the whole set is RED on old code. Not run test-by-test.
- Existing tests: cube_record callers got time_base="radar"; record key-set assertion gained "time_base".

## Tests run
- QGIS Step 4 files + test_plugin_site_export.py: before R6 edits 511 passed, 3 failed (exactly the three R6 tests). After: those 3 pass; test_plugin_loads + test_plugin_profile_dock 133 passed.
- core + pure: 1280 passed, 5 skipped. ruff check, ruff format --check, mypy: clean.
- test_the_seeded_z_range_survives_a_preset_that_crops_the_sample_axis: passes unchanged (real data present locally); spec 4.3 "shown harmless" confirmed. Only its docstring numbers were updated.
- test_prepared_z_bounds_is_the_intersection...: starts == {0.0}, three distinct zero_ns, ends/tightness kept.
- Did not touch test_plugin_slices_engine.py:1694-1700 (no failing numbers there; whole file passes).

## R6 numbers (measured with a probe, removed)
With 128 samples C's lines now run 0.0..18.838 ns (was ending ~16.4); A/B 0..101.99.
- outside_the_window: comment "end near 18.84 ns"; bound t_end_ns < 19.0 (was 17.0); deep (30 ns) nodata and shallow (5 ns) assertions unchanged.
- one_level overlap: t0 16.0 -> 18.5 and slice_at(16.0) -> slice_at(18.5); C then holds exactly one level (18.5 only).
- site_export: same t0 18.5; docstring updated.

## Concerns
- test_plugin_slices_dock.py new tests rely on nothing-prepared via engine.clear() + renaming the DZT files.
- Real-data docstring says the line now reads "0 to about 100 ns" (derived, not measured).

## Fix round 1
Changes (ui/slices_dock.py): `_shift_z_by_median_zero` returns whether it moved; `_on_prepared` pushes via `_apply_resolution()` when the shift or the clamp moved (both evaluated, no short-circuit) [Critical 1]. `restore_cube`: when `prepare()` is a no-op and no preparation is owed, the shift is applied immediately and pushed; a pending R-P5 preparation keeps the flag [Important 2]. Removed the flag clear from `_on_engine_error` [Important 3]. `_on_source_changed` clears the flag [Minor 7]. Docstrings fixed (shift direction via retime_ns, flag, CubeRecipe) [6, 7, 9]; stale comment in test_plugin_slices_engine.py reworded.
Tests (test_plugin_slices_dock.py): restore test asserts engine.z.t0_ns; new no-op-prepare, owed-preparation, failed-line (one of three DZTs renamed), marked-record tests; nothing-prepared test asserts message_log has no "could not"; band test uses a real loaded line, radar clock case plus a time-zero-step line (band at (10,12) after a repaint). test_plugin_site_scope.py: line_zero_in_cube / SiteEngine.line_zero under Whole site.
RED: against f3264b8 sources with the new tests, restore (with clear), no-op prepare, owed preparation and failed-line tests fail. Mutants on the fixed tree (scratch copy, PYTHONDONTWRITEBYTECODE=1), each killed by exactly one test: drop `time_base is None and` (marked-record), drop `median is None` guard (nothing-prepared), remove `_push_slice_band` from `_render` (band), ignore shown zero (band), line_zero_in_cube always self.engine (site_scope).
Commands/output: QGIS covering files (slices_dock, slices_engine, slice_export, site_engine, site_scope, profile_dock): 591 passed. core+pure: 1280 passed, 5 skipped. ruff check, ruff format --check, mypy clean.

## Fix round 2
Changes (ui/slices_dock.py): new `_apply_owed_z_shift()` (no-op while a preparation runs; else clear flag, shift, `_apply_resolution()` if moved), used by `restore_cube`'s no-op branch (when nothing is owed) and by `_run_pending_grid_prepare` after `prepare()`; `rebuild_source` clears `_pending_z_shift`.
Tests: the owed test now runs `_run_pending_grid_prepare()` and asserts spins + engine.z + one note + flag cleared, then sets 20..30 and an unrelated `_on_prepared` leaves it alone; new `test_rebuilding_the_source_drops_an_owed_shift`. Both FAIL against 73651fd (scratch copy, PYTHONDONTWRITEBYTECODE=1).
Output: QGIS slices_dock + site_scope + slices_engine 370 passed; core+pure 1280 passed, 5 skipped; ruff check/format and mypy clean.
