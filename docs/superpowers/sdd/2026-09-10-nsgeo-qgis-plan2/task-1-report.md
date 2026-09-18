# Task 1 Report: Parameter schema on every step

## What was implemented

Followed the brief verbatim.

1. `packages/nsgeo-core/src/nsgeo/processing/base.py`:
   - Added `_Required` sentinel class and the `REQUIRED` singleton (`repr` is `"REQUIRED"`).
   - Added frozen `ParamSpec` dataclass with `KINDS: ClassVar[tuple[str, ...]] = ("float", "int", "choice", "curve")`, fields `name, kind, label, default, unit=None, min=None, max=None, choices=(), help=""`, a `__post_init__` that rejects unknown kinds, rejects `choice` without `choices`, rejects non-`choice` kinds that declare `choices`, and rejects a `choice` default not present in `choices` (REQUIRED exempted), plus a `.required` property (`default is REQUIRED`).
   - Extended the `Step` Protocol with `schema(cls) -> tuple[ParamSpec, ...]` as a classmethod.
   - Added `default_params(name)` and `required_params(name)` module functions built on `get_step(name).schema()`.

2. Declared `schema()` classmethods on all nine registered steps, in the exact parameter order each step's `params` property already returns (verified by the parametrized order test):
   - `timezero.py` — `TimeZero`: `mode` (choice: first_break/sample), `sample` (int, min=0), `threshold` (float, min=0/max=1, default 0.2).
   - `dewow.py` — `Dewow`: `window_ns` (float, unit ns, min=0, default 4.0).
   - `gain.py` — `GainAgc`: `window_ns`, `target`, `eps`; `GainParametric`: `mode` (choice), `alpha`, `exponent`; `GainCurve`: `points` (kind `curve`, default `REQUIRED`).
   - `bandpass.py` — `Bandpass`: `low_mhz` (REQUIRED), `high_mhz` (REQUIRED), `taper_frac` (default 0.25).
   - `background.py` — `BackgroundMean.schema() -> ()`; `BackgroundSliding`: `window_traces` (int, min=1, default 200); `BackgroundSvd`: `n_components` (int, min=0, default 1).

3. `GainCurve.__init__` now validates at construction: raises `ValueError` (match "two") for fewer than two points, and `ValueError` (match "finite") for any non-finite coordinate (via `math.isfinite`), before assigning `self.points`. The `len(self.points) < 2` guard was removed from `apply` (redundant — construction now guarantees it).

4. `processing/__init__.py` now re-exports `REQUIRED, ParamSpec, default_params, required_params` alongside the existing names.

5. `project.py::load_site`: the `"stack" in entry` branch now wraps `StepStack.from_dicts(entry["stack"])` in `try/except (KeyError, TypeError, ValueError)`, re-raising as `ProjectError(f"invalid processing stack for line {entry['path']!r}: {exc}") from exc`. Verified against the current file first — the brief's cited line numbers (150-160) were stale; the actual branch was at lines 170-171 pre-change. Content and shape of the required fix matched the brief exactly regardless of line number.

## Files changed

- `packages/nsgeo-core/src/nsgeo/processing/base.py` (modified)
- `packages/nsgeo-core/src/nsgeo/processing/timezero.py` (modified)
- `packages/nsgeo-core/src/nsgeo/processing/dewow.py` (modified)
- `packages/nsgeo-core/src/nsgeo/processing/gain.py` (modified)
- `packages/nsgeo-core/src/nsgeo/processing/bandpass.py` (modified)
- `packages/nsgeo-core/src/nsgeo/processing/background.py` (modified)
- `packages/nsgeo-core/src/nsgeo/processing/__init__.py` (modified)
- `packages/nsgeo-core/src/nsgeo/project.py` (modified)
- `packages/nsgeo-core/tests/test_schema.py` (created, verbatim from the brief)

## TDD Evidence

**RED**

Command:
```
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_schema.py -q
```
Relevant output (before any implementation, right after creating the test file verbatim from the brief):
```
ERROR collecting tests/test_schema.py
ImportError: cannot import name 'REQUIRED' from 'nsgeo.processing.base'
1 error in 0.18s
```
This is exactly the failure the brief predicted (Step 2: "Expected: FAIL — `ImportError: cannot import name 'REQUIRED'`"), confirming the test file exercises code that does not yet exist.

**GREEN**

Command:
```
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_schema.py -q
```
Output after implementing Steps 3-5:
```
............s..s...................
33 passed, 2 skipped in 0.13s
```
(The 2 skips are `test_non_required_defaults_build_and_apply` for `bandpass` and `gain_curve` — both have required params by design, so the test's own `pytest.skip` fires, which is the expected/intended behaviour, not a gap.)

Full core suite:
```
.venv/bin/python -m pytest packages/nsgeo-core/tests -q
```
```
229 passed, 2 skipped in 0.54s
```
(196 baseline + 33 new = 229; the 2 skips are the same two above — no change to the pre-existing skip count, which was itself 0 in the 196-baseline before this task, since those two skips are new tests skipping, not baseline tests newly skipping.)

## Verification

- `.venv/bin/python -m pytest packages/nsgeo-core/tests -q` → `229 passed, 2 skipped in 0.54s`. Pristine output, no warnings.
- `.venv/bin/ruff check .` → initially 4 `E501` (line too long) in `base.py`, `gain.py`, `bandpass.py` from the brief's suggested inline formatting; ran `.venv/bin/ruff format .` per the brief's explicit instruction ("If ruff wants ... reflows the ParamSpec(...) calls, accept its autofix"), which reformatted 6 files. Re-ran `ruff check .` → `All checks passed!`.
- `.venv/bin/ruff format --check .` → `40 files already formatted` (clean after the autofix).
- `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo` → `Success: no issues found in 19 source files`.
- `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py -q` → `2 passed` (no forbidden imports introduced).
- Re-ran the full suite once more after the ruff-format autofix touched 6 files, to make sure formatting didn't change behaviour: still `229 passed, 2 skipped`.

## Self-review findings

- Diffed every changed file against the brief's specified code blocks. All nine `schema()` classmethods, `ParamSpec`, `REQUIRED`, `default_params`/`required_params`, the `GainCurve` constructor rewrite, the `processing/__init__.py` export list, and the `project.py` try/except match the brief's content; the only difference anywhere is ruff's own line-wrapping of the `ParamSpec(...)` calls and the `__post_init__` `if` in `base.py`, which the brief explicitly pre-authorized.
- Checked that every step's `params` property key order matches its `schema()` tuple order (this is exactly what `test_schema_names_match_params_keys_in_order` verifies per step, and it passes for all nine).
- Confirmed `StepStack.from_dicts` (`packages/nsgeo-core/src/nsgeo/processing/stack.py`) can raise `KeyError` (unknown step, via `get_step`), `TypeError`, or `ValueError` (e.g. `GainCurve`'s own validation) — all three are exactly what `load_site`'s new `except` clause catches, so the wrapping is not accidentally too broad or too narrow.
- Confirmed pre-existing tests that exercise `StepStack.from_dicts` directly (`test_stack.py`, `test_project.py`) are unaffected — the new try/except lives only inside `load_site`, not in `StepStack` itself, so direct callers of `from_dicts` still see the original exception types.
- Checked for YAGNI: no extra fields, no extra helper functions beyond what the brief's Interfaces section lists (`ParamSpec`, `REQUIRED`, `default_params`, `required_params`, `Step.schema`). Did not add validation, defaults, or fields the brief didn't ask for.
- The new test file is byte-for-byte the brief's Step 1 content — it tests behaviour (schema/params consistency, required-param enforcement, bounds/choices sanity, sentinel semantics, construction-time validation, and the `ProjectError` wrapping), not implementation details.
- Test output is pristine: no warnings, no deprecation notices, no stderr noise across all runs.
- `.venv-qgis/` is untracked and unrelated to this task; left alone, not staged.

## Concerns

None. The implementation, tests, lint, and type-check all match the brief's expectations exactly, and the one line-number discrepancy called out in advance (project.py:150-160 vs. the actual 170-171) was verified by reading the file rather than trusted blindly, per the task's explicit instruction.

## Commit

`3c8619f` — "feat: declare a parameter schema on every processing step" (message taken verbatim from the brief's Step 8, no Co-Authored-By line added per this task's explicit instruction not to mandate one).
