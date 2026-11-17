# Task 3 report: settings that cannot work (#44, #40, #46)

Commit 01535a4 "fix(processing): refuse settings that cannot work, by name (#44, #40, #46)", pushed to origin nsgeo-step-edges.

## Implemented
- base.py: `ParamSpec.min_exclusive`; `param_problem(spec, value)` (not in `__all__`) with the exact phrases; `_validate_params` built on it (same message format; curve keeps "every <name> value ..., got <entry> dB"; curve also refuses <2 points "must have at least two points" and non-finite pairs "must be pairs of finite numbers"; malformed shapes still left to the constructor). bool / np.bool_ refused for int and float/time. Huge ints that overflow float count as non-finite.
- _util.py: `window_samples`. dewow.py, gain.py (AGC) use it; titles "Dewow" and "AGC".
- Schema: background_sliding.window_traces min 2; gain_agc eps and target min 0.0 exclusive; gain_parametric alpha [-1,1], exponent [-10,10]; background_svd n_components max 20.
- background.py apply guard `< 2`; bandpass.py `mask.any()` guard with the specified message.

## TDD
RED (src reverted via saved patch, tests kept): `pytest test_schema.py test_steps_gain.py test_steps_bandpass.py test_steps_timezero_dewow.py` -> 53 failed, 108 passed (new refusal cases, bound enforcement, param_problem, the three real-line window/band tests; many via missing `min_exclusive`/`param_problem`).
GREEN: core suite 1322 passed, 4 skipped (553 s).

## QGIS processing set (file by file), all pass
processing_dock 31, param_form 55, difference_presets 12, session 126, profile_dock 119, time_cutoff 13, gain_strip 44, survey_dock 80, site_scope 162, slices_engine 74, layers 110, grid_velocity_dialog 29, velocity_dialog 84. No QGIS test needed a changed value.

Lint: ruff check and format clean. mypy (CI line): no issues in 51 files.

## Mutation probes (throwaway worktree, removed afterwards)
- `count >= 2` -> `>= 1` in window_samples: killed by the dewow and AGC real-line one-sample tests.
- min_exclusive `<=` -> `<`: killed by 5 tests (bound enforcement for eps/target, refused cases, param_problem phrases).
- bool exclusion for int: killed by `time_zero sample=True`.
- bool exclusion for float: SURVIVED at first; added cases `gain_parametric alpha=True` (and np.bool_ for exponent, time_zero sample); now killed by the alpha=True case.
- `mask.any()` removed: killed by the 300-302 MHz real-line test.
- np.bool_ in the exclusion tuples: survives (equivalent; np.bool_ is not a numbers.Real/Integral, kept as a defence).

## Existing tests changed
- test_steps_timezero_dewow.py::test_dewow_rejects_window_shorter_than_one_sample: match now "is shorter than one sample".
- test_steps_background.py::test_sliding_with_window_of_one_is_a_no_op_in_effect: replaced by `test_sliding_refuses_a_window_of_one_trace...` (window 1 is now refused by the brief's min 2; build refuses, and `BackgroundSliding(1).apply` raises "window_traces must be >= 2, got 1").
- test_schema.py: `_in_bounds` helper nudges above an exclusive min (placeholder); bounds-covered list and bound enforcement test updated as the brief says.

## Files
processing/{base,_util,dewow,gain,background,bandpass}.py; tests/{test_schema,test_steps_gain,test_steps_background,test_steps_bandpass,test_steps_timezero_dewow}.py (under packages/nsgeo-core).

## Self-review / concerns
- Core run finished before the last added bool test cases; those were run with the 5 affected files in the mutation tree (196 passed) but not in a full-suite run.
- Review Focus 4 test (all-zero line) is in test_steps_bandpass.py and passes.
- Dewow/AGC window_ns min stays 0.0 (inclusive): 0.0 builds and is refused at apply, as the existing test expects.

## Fix round 1
Changed `_curve_problem` in processing/base.py: a non-iterable value, any point whose length is not 2, or entries that are not real numbers (strings, bool) now give the reason "must be (time, dB) pairs of numbers"; fewer than two points, non-finite ("must be pairs of finite numbers") and dB-bound reasons unchanged. `build_step` therefore raises `ValueError` naming `points`, and `param_problem` returns a reason, for `[[0,0],[10]]`, `[[0,0,1],[10,3,1]]` and `5` (plus string and bool entries).
Test added: `test_curve_points_that_are_not_pairs_of_numbers_are_refused` (5 cases) in tests/test_schema.py.
Commands and output:
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_schema.py packages/nsgeo-core/tests/test_steps_gain.py -q -p no:cacheprovider` -> 123 passed, 4 skipped
- `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py -q -p no:xonsh -p no:cacheprovider` -> 44 passed
- ruff check/format clean; mypy (nsgeo src) no issues.

## Fix round 2
`_curve_problem` now builds `pairs` inside the `try` and catches `(TypeError, KeyError, IndexError)`, returning "must be (time, dB) pairs of numbers"; dict-point and set-point curves are refused rather than raising out. The test gained dict and set cases and now asserts the exact phrase from `param_problem` and the phrase in the `build_step` ValueError.
Commands: core `test_schema.py` + `test_steps_gain.py` -> 125 passed, 4 skipped; QGIS `test_plugin_gain_strip.py` -> 44 passed; ruff clean; mypy (nsgeo src) no issues.
