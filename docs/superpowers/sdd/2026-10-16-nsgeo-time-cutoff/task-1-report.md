# Task 1 report: time_cutoff step, "time" kind, result_bypassing

## Implemented
- `processing/timecutoff.py`: `TimeCutoff` (`time_cutoff`), `end_ns` REQUIRED, kind `"time"`, unit ns. Ruling R1: non-finite `end_ns` raises `ValueError("... must be finite ...")` in `__init__`.
- `base.py`: `"time"` added to `ParamSpec.KINDS`, docstring, and `_validate_params` numeric branch.
- `stack.py`: `StepStack.result_bypassing(index)` (cached prefix reused, later enabled steps run uncached, same IndexError message as `intermediate`).
- `processing/__init__.py` imports `timecutoff`.
- Tests: new `test_steps_timecutoff.py` (7), 5 in `test_stack.py`, registry-wide updates in `test_schema.py` and `test_steps_background.py`, 1 real-data test in `test_real_files.py`.

## TDD evidence
1. Step tests. RED: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_timecutoff.py -q` gave `7 failed`, each `KeyError: "unknown step 'time_cutoff'; available: [...]"` (expected: step missing). I first had an explicit `import nsgeo.processing.timecutoff`, which errored at collection (ModuleNotFoundError); I changed it to `import nsgeo.processing` so RED matched the brief. GREEN: same command, `7 passed`.
2. result_bypassing. RED: test_stack.py gave `4 failed, 21 passed`, `AttributeError: 'StepStack' object has no attribute 'result_bypassing'` (the round-trip test passes already because the step exists from cycle 1). GREEN: `25 passed`.
3. Registry-wide. RED: test_schema + test_steps_background gave `14 failed, 68 passed` (the new step/kind unhandled by `_placeholder`, the expected-required dict, `_STEP_PARAMS`). GREEN after edits: full suite below.
4. Real-data test added after production code existed (it exercises already-green behaviour; no separate RED). It RUNS: `test_real_files.py::test_a_cutoff_after_time_zero_keeps_the_first_rows_of_a_real_profile PASSED` (`-k cutoff -v`: 1 passed).

## Full results
- core + pure: `604 passed, 3 skipped` (588 + 16 new: 7 + 5 + 1 real + 3 parametrized registry cases for time_cutoff).
- Skips: 3, not 2. The third is `test_schema.py:51` `test_non_required_defaults_build_and_apply[time_cutoff]` ("has required parameters by design"), the same parametrized skip bandpass and gain_curve already take. The real-data tests are not skipped.
- ruff check and format: clean. mypy: no issues in 33 source files. Boundary tests green (inside the suite).

## Self-review
- NaN: `_out_of_bounds` is not consulted for finiteness; the check lives in `TimeCutoff.__init__`, reached via `build_step` and `from_dicts`.
- `result_bypassing` on index 0 with no source raises ValueError like `result()`.
- Test file import of `nsgeo.processing` is for registration (IDE hint "not accessed" is expected; noqa present).

## Concerns
- Skip count is 3 rather than the brief's 2, for the reason above.
