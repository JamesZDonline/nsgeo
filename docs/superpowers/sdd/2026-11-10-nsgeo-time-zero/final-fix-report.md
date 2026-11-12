# Final whole-branch review fixes (nsgeo-time-zero, from 42fecfc)

1. zip strict: removed `strict=True` in packages/nsgeo-core/tests/test_velocity_fit.py:190. Other `strict=` hits in core are comments only. Python 3.9 not installed locally; checked by grep.
2. Old-cube restore on the no-op path. `restore_cube` no longer calls `flush_debounce()` while a shift is owed (it stops the debounce instead); `_apply_owed_z_shift` now shifts, `_clamp_z_to_prepared()`, then `_apply_resolution()`. `_on_prepared` forces a push when it applied an owed shift. Tests: `test_a_realistic_old_record_restores_inside_the_bounds_when_the_engine_holds_its_source`, `..._when_a_preparation_runs` (banded fixture rows 40/40/41), real-data `test_a_real_data_old_record_restores_without_a_coverage_error`.
   RED at 42fecfc (scratch copy, PYTHONDONTWRITEBYTECODE=1, new tests copied in): synthetic -> "line 'raw/FILE__001.DZT' spans 0.000..101.986 ns, which does not cover the cube's -2.208..99.292 ns"; real -> "spans 0.000..100.037 ns, which does not cover the cube's -0.476..99.524 ns". The dispatched-path test passes at both (kept working).
3. Remembered range: `_shift_z_by_median_zero` now remembers the shifted t0/t1 for `_last_grid_id`. Covered by the assertions at the end of the engine-holds-source test (masked at 42fecfc by the first failure, so no independent RED).
4. Whole site early return: `owed_shift` is now consumed after the site early return. Test `test_the_owed_shift_survives_a_switch_to_whole_site_before_the_preparation_lands`. RED at 42fecfc: `assert False is True` on `_pending_z_shift`.
5. Guard pin: `test_the_owed_shift_helper_steps_aside_while_a_preparation_runs`. With the `engine.is_running` guard deleted (scratch copy): `assert False is True` on `_pending_z_shift` -> fails.
6a. `test_disabling_the_time_zero_step_keeps_a_pick_on_its_sample` (test_plugin_layers.py); passes (it pins existing behaviour). 6b: the real-data test above.
7. `first_break_ns` docstring reworded (timezero.py).
8. Stale text: `_clamp_z_to_prepared` docstring, processing_dock.py time_zero wording, `mixed_clock_note` uses `name_list` ("A and C"); pure test updated (RED at 42fecfc: test_mixed_clock_note_names_the_radar_grids fails).

## Verify
- core+pure: `1282 passed, 5 skipped in 42.89s`
- QGIS 4 files: `445 passed in 498.56s`
- ruff check: All checks passed!; ruff format --check: 182 files already formatted; mypy: Success: no issues found in 43 source files
