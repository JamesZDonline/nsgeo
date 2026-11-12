# Task 1 report: the clock in the core

Commit f4c9449 "feat(processing): time_zero relabels the clock, so its row reads 0 ns (#97)", pushed.

## Implemented
- base.py: Radargram.zero_ns / zero_set, to_radar_ns / from_radar_ns, retime_ns, module docstring.
- timezero.py: first_break_row, TIME_BASE_*, sets_time_zero, time_base_of; apply always relabels (k=0 included), "no samples" refusal kept; schema help; module docstring.
- stack.py: StepStack.sets_time_zero(), zero_ns() (runs only to last enabled time_zero).
- Docstrings/comments: timecutoff.py, velocity.py, migration.py MAX_T0_NS comment; test_steps_migration.py docstring, test_velocity.py docstring.
- Tests: the brief's tests in four files (plus a stack test for zero_ns with no source).

## TDD
RED: pytest on the four files -> collection ImportError "cannot import name 'retime_ns'" (and first_break_row), as expected.
GREEN: core + pure suite: 1227 passed, 5 skipped (baseline 1194 + 33 new). Real-data campus and GPS zero tests ran and passed.
No existing core test pinned the old crop-only clock beyond the two replaced.

## Lint
ruff check, ruff format --check, mypy: all clean.

## Self-review
Brief followed verbatim. StepStack.sets_time_zero delegates to timezero.sets_time_zero (stack imports timezero; no cycle). Pass-through test also asserts coverage of all registered steps.

## QGIS tests likely depending on old behaviour (by grep, not run)
packages/nsgeo-qgis/tests/qgis/: test_plugin_profile_view, test_plugin_profile_dock, test_plugin_processing_dock, test_plugin_time_cutoff, test_plugin_velocity_fit, test_plugin_session, test_plugin_slices_engine, test_plugin_slices_dock, test_plugin_slice_export(_dialogs), test_plugin_param_form, test_plugin_difference_presets, conftest.py; pure/test_pure_slices_plan.py (pure suite passed).

## Concerns
None.

## Fix round 1
1. Radar-time test now t0_ns=-2.0; added test_radar_clock_conversions_are_asymmetric_and_round_trip.
2. Added test_zero_ns_is_the_last_enabled_time_zeros (two time_zero, asserts zero_ns() == result().zero_ns == t0 + 8*dt).
3. Renamed migration test to test_accepts_a_small_start_offset, reworded docstring; dropped residual from MAX_T0_NS rationale.
4. sets_time_zero() = bool(self._time_zero_indices()); removed the timezero import from stack.py.
5. Removed k = max(k, 0).
6. to_radar_ns/from_radar_ns go through retime_ns.
Tests: core command on the four files: 130 passed. ruff check, ruff format --check, mypy clean.
