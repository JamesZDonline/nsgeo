# Final-review fix wave report (nsgeo-processing-panel)

Commits (on bb1f8ff): fdd72d6 (3), e190fcf (1), 8e1fe36 (2 + spec §3.3), ecc42a6 (4). Not pushed.

## 3. Real-data guard docstring (fdd72d6)
test_plugin_gain_strip.py: the sentence claiming other strip tests catch removing `_limited` alone is replaced:
`_limited` is a backstop no gesture can reach (the `_db_range` cap and `_clamped` already bound every write); only
removing both clamps fails the test. Docstring-only; no test run needed.

## 1. Difference follows a moved step (e190fcf)
profile_dock.py: new `_difference_step` (set None in `__init__`, `set_difference_index`, `_open`, `_clear`,
`_decline_difference`); new `_follow_differenced_step(stack)` called at the top of `current_radargram`'s difference
branch. Tracked object at the index: nothing to do. Elsewhere in entries (identity): `_difference_index = j`. Not found:
index stands, tracked object becomes whatever sits at the index (None out of range). Tracker starts lazily at the first
computation after `set_difference_index`. `_on_rows_moved` re-aim untouched.
Tests (test_plugin_difference_presets.py): `test_a_dragged_step_across_time_zero_keeps_its_difference`,
`test_move_selected_across_time_zero_keeps_its_difference`.
RED (before the fix): `-k across_time_zero` -> 2 failed, `errors == ['step 2 (Time zero) changes the sample count
(512 -> 472); a difference view is undefined for it']`. GREEN after: difference_presets + profile_dock = 142 passed.
Mutation (call replaced by `pass`): both new tests fail (shown), reverted by hand.

## 2. Refusal check follows the Difference chain (8e1fe36)
processing_dock.py: `_paint_refusal` runs `stack.intermediate(row)` when `diff_button` is checked and the row is valid,
else `stack.result()`; `_emit_difference` calls `_check_refusal()` (guarded) before emitting. Spec §3.3 gains one
paragraph. Tests (test_plugin_processing_dock.py): `test_difference_on_an_early_step_checks_only_the_chain_it_shows`,
`test_difference_checks_the_chain_up_to_the_row_it_is_aimed_at`, `test_difference_on_a_row_below_a_refusal_names_that_step`.
RED (mutation `if False and ...` restoring `result()`): first two fail (`refusal()` is the Bandpass StepRefused, not None);
the third (refusal below row, ruling's last case) passes either way by design. GREEN: processing_dock + presets +
profile_dock = 206 passed. No timing test (not requested).

## 4. Gain strip behind a refusal (ecc42a6)
plugin.py: `_refusal_above(row)` (panel's `refusal()` with index below the row, no stack evaluation); `_sync_gain_strip`
hides the strip on it; `_on_gain_reset` returns on it. Tests (test_plugin_gain_strip.py):
`test_a_refusal_above_the_curve_hides_the_strip_until_it_is_fixed`,
`test_reset_writes_nothing_while_a_refusal_sits_above_the_curve`.
RED (`_refusal_above` forced False): both fail (strip visible while refusing; Reset writes the identity). Mutating only
the `_on_gain_reset` check: the Reset test fails alone. GREEN: gain_strip + slices_width = 90 passed.

## Notes / concerns
- The test with Time zero ABOVE the curve cannot show a point shift (input zero and shown zero coincide, so points are
  stored values); the wrong-clock harm there is the Reset axis, which test 2 pins. The 0.48 ns drag shift on FILE__007
  was not reproduced as a separate test.
- ruff format only on changed files; `ruff check .` clean, `ruff format --check .` clean (275 files).

## Final runs
See the reply summary; results of the full verification set are appended below by the implementer.

### Results
- difference_presets + profile_dock + processing_dock + gain_strip + slices_width: 296 passed.
- real_data (-m real_data): 46 passed.
- pure tier (packages/nsgeo-qgis/tests/pure): 370 passed, 4 skipped. The core tests were not re-run (core untouched; the
  combined core+pure run exceeded the time limit on a loaded machine).
- ruff check . clean; ruff format --check . clean.

## Residual (Ruling 16)
`ProcessingDock._on_current_row` emitted `step_selected(row)` before the refusal check re-ran, so with Difference on the
strip sync read the previous row's note. Fix: when `diff_button` is checked, `_check_refusal()` runs before the emit; the
slot body is now wrapped in try/except with `_log`.
Test: `test_selecting_a_curve_behind_a_refusal_with_difference_on_hides_the_strip` (test_plugin_gain_strip.py; stack Time
zero, Dewow, refusing bandpass, gain curve; Difference on Dewow; select row 3).
RED (`scripts/qgis_tests.sh tests/qgis/test_plugin_gain_strip.py -k behind_a_refusal_with_difference`):
`assert False  where False = GainStrip.isHidden()` (strip visible). GREEN: gain_strip + processing_dock +
difference_presets = 162 passed. `ruff check` clean, changed files formatted.
