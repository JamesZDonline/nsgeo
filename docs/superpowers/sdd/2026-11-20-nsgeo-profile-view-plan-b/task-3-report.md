# Task 3 report

Implemented in profile_dock.py: `handle_spec` (replaces `time_param_name`, uses `param_visible`), `relabel_onto`, `_cutoff_row` -> `_handle_row`, `_shows_row_handle`, row-handle branch in `current_radargram` (`relabel_onto(source | intermediate(row-1), stack.zero_ns())`), `_scale_reference` returns `shown` for a row handle.
Row handle line: `_show_cutoff` leaves it HIDDEN (Task 4 draws it); `_on_cutoff_dragged` returns for non-`time` specs. Time cutoff path unchanged.

RED (before fix): `qgis_tests.sh test_plugin_profile_dock.py -k "time_zero or first_break_mode or migrated"` -> 4 failed, 8 passed. Shape mismatches e.g. "(shapes (492, 240), (512, 240) mismatch)" (drew the result, not the input); first_break test failed on missing `_handle_row` (AttributeError; its behaviour is a guard). Difference file: 2 failed (re-pinned test and migration pin; "(472, 60), (512, 60) mismatch").
Mid-record and top-of-record window tests passed first (they pin Plan A's holding with the new view; they pass vacuously before the fix only because the view was unchanged).
GREEN: profile_dock 165 passed (+1 real-data test later), difference_presets 20, time_cutoff 13 (no edits), gain_strip 80, velocity_fit 78, pure 432 passed, real_data 54 passed + new real test passed. ruff check/format clean.

Re-pinned: test_selecting_time_zero_with_difference_on_shows_the_result: final assert result().data -> stack.source.data. Added first_break twin (keeps result()), migration-after-Time-zero pin (one error, button off, input drawn).
New tests: 6 in test_plugin_profile_dock.py per brief + real FILE__007 seed-49 test (t0 = -11.086+0.476, n = kept+49). GPS FILE__010 value not pinned.
Only a comment in test_plugin_profile_dock.py mentioning `_cutoff_row` renamed. plugin.py/slices_dock.py untouched.
Concerns: none. Core venv not needed (no core changes).

## Fix round 1
1. New test_a_row_handles_input_view_is_its_own_scale ([time_zero, gain_agc], reference is rg, limit from the source). 2. Mid-record test also asserts time_lo/time_hi unchanged on select; top-of-record test docstring labels it a guard. 3. current_radargram draws the unrelabelled input when stack.zero_ns() raises; test_a_time_zero_that_refuses_still_draws_its_input (sample=600, no error). 4. Module and _scale_reference docstrings updated. 5. handle_spec -> ParamSpec | None. 6. `_handle_spec_at(row)` used in current_radargram, _shows_row_handle, _show_cutoff.
Mutants (applied together, reverted): `_shows_row_handle` branch disabled, relabel removed, try/except disabled. Run: qgis_tests.sh test_plugin_profile_dock.py -k "own_scale or refuses_still or mid_record" -> 3 failed (mid-record: labels (41.51, 51.51) vs expected (48.27, 58.27); own_scale: reference is not rg; refuses: error 'time_zero at sample 600 would leave no samples (radargram has 512)'). Without mutants: 3 passed.
Covering: profile_dock 168, difference_presets 20, time_cutoff 13, gain_strip 80, pure 432, real_data 55 pass; ruff clean.
