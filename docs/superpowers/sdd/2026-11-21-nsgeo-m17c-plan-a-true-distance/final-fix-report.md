# M17c Plan A final-fix report

## I1 paint speed
- ViewTransform: walk window computed once in __post_init__ into `_wwin` (field init=False, compare=False, repr=False; equality/hash unchanged; replace()/with_window rerun __post_init__ so values are fresh). New `x_of_traces(array)` does one interpolation. TraceAxis stores `_sign` once.
- profile_view: `_centres()` helper (axis case: one array pass; axis=None: the old per-point code verbatim) used by `_pick_positions`, `_velocity_positions` and the curve `_draw`.
- Tests: pure `test_an_axis_transform_interpolates_once_per_trace_lookup_not_three_times`, `test_the_walk_window_follows_replace_and_with_window`; qgis `test_painting_a_gps_profile_interpolates_a_handful_of_times` (metres_at call-count spy, <=15 per paint).
- Timings (offscreen grab, 1400x520, mean of 10 paints), FILE__016: before 19 / +30 picks 21 / +3 fits 63 ms; after 7.6 / 7.7 / 9.5 ms. FILE__002 +3 fits: before 71, after 11.3 ms. (script: scratchpad/m17c/paint.py)
## M1 restored `test_an_even_trace_axis_migrates_exactly_as_dx` (test_steps_migration.py).
## M2 `_reattach_gps_sources` now only for lines whose travel_shift or gap_m changed AND stack.source is not None (set_travel_shift: stack-source filter). Tests in test_plugin_session_gps_grids.py: label-only and grid-only edits emit nothing; Gap over edit re-attaches; source-less stack untouched.
## M3 `_trace_box` drops left-out columns for a GPS line (left_out with its gap_m), maps box ends and returned dots back to original indices; tape/cuts unchanged. Test `test_a_velocity_box_across_a_lift_traces_nothing_on_a_left_out_trace` (test_plugin_profile_dock.py).
## M4 re-attach now runs after _set_dirty(True) and before lines_changed.emit(); stack_changed emitted per re-attached key after it. Test `test_the_source_is_reattached_before_lines_changed`. No existing test's asserted order changed (existing dirty-at-emit tests pass unmodified).
## R12 another EPSG code -> 32632 in test_a_tape_lines_profile_gets_no_axis (this branch's test).
## Extras (a) test_fit_and_one_to_one now asserts can_true_scale() (passed without fixture change). (b) MigrateFk.apply takes the plain path when the even grid would exceed MAX_EVEN_GROWTH=4 x trace count; test `test_a_huge_jump_takes_the_plain_path_not_a_giant_even_grid`.
## Existing tests changed: only the one assertion in (a) and the EPSG string in R12.
## Results
- core+pure: 2235 passed, 9 skipped, 19 xfailed
- QGIS: session_gps_grids/edit_lines_gps/true_distance 55 passed; profile_view/dock/cut/velocity_box/processing_dock 452 passed; -m real_data on profile files 11 passed
- ruff check + format --check clean; mypy clean
