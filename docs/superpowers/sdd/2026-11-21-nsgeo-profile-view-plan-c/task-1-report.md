# Plan C Task 1 (Q3) report
Change (ui/profile_dock.py): the row-handle branch of current_radargram draws relabel_onto(stack.result_bypassing(row), zero); falls back to the input (relabelled, or raw when zero_ns raises) when the bypass raises ValueError (no error emitted) or its (n_samples, t0_ns) differ from the input's. New flag _row_view_is_bypass records which was drawn; _scale_reference then uses result_bypassing(*curve_rows, row) for the bypass and `shown` for the fallback.
RED: qgis_tests.sh test_plugin_profile_dock.py test_plugin_difference_presets.py -> 6 failed (assertion mismatches: input data vs bypass data, limit mismatch). GREEN: all five files pass (176/20/8/13/80), pure 434 passed, real_data 57 passed, ruff check+format clean.
Re-pinned (before -> after):
- test_selecting_time_zero_in_sample_mode_draws_its_input_on_the_lines_clock -> ..._draws_the_bypass_on_the_lines_clock: data == source.data -> == result_bypassing(0).data
- test_a_time_zero_that_is_not_first_draws_what_it_receives -> ..._draws_the_bypass: intermediate(0) -> result_bypassing(1)
- test_a_time_zero_that_is_not_first_draws_its_line_on_its_input_rows: data intermediate(0) -> result_bypassing(1) (line row assertion unchanged)
- test_a_row_handles_input_view_is_its_own_scale -> test_a_row_handles_fallback_input_view_is_its_own_scale: stack now [time_zero, migrate_fk] (fallback), asserts input drawn, limit from input
- test_selecting_time_zero_with_difference_on_shows_the_result (difference_presets): source.data -> result_bypassing(0).data
Unchanged and still green: migration tests (fallback, one error, line up), refuse-sample test, drag/row tests, time_cutoff file (unedited).
New: test_selecting_time_zero_keeps_the_processed_look, test_a_later_step_that_refuses_falls_back_to_the_input, test_a_bypass_with_other_rows_falls_back.
Concerns: none.
