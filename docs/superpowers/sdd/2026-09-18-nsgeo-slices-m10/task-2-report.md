# Task 2 report: Amplitude transform steps

## What I implemented

Exactly the brief's five moving pieces, plus one unbriefed fix discovered in Step 8:

1. **`packages/nsgeo-core/src/nsgeo/processing/amplitude.py`** (new) — three registry
   steps (`amp_abs`, `amp_square`, `amp_envelope`), each taking no parameters and
   each carrying `unipolar = True`; and `analytic_envelope(data: np.ndarray) -> np.ndarray`,
   an FFT-based Hilbert analytic-signal modulus taken at the array's own length
   (never zero-padded).
2. **`packages/nsgeo-core/src/nsgeo/processing/base.py`** — added `is_unipolar(step: Any) -> bool`
   immediately after the `Step` protocol class.
3. **`packages/nsgeo-core/src/nsgeo/processing/stack.py`** — added `is_unipolar` to
   the import line and `StepStack.output_unipolar` property in the `# ---- inspection ----`
   section, right after `cache_size`.
4. **`packages/nsgeo-core/src/nsgeo/processing/__init__.py`** — added `amplitude` to
   the first import block (alphabetically first) and `is_unipolar` to the `base` import
   block (alphabetically after `get_step`).
5. **`packages/nsgeo-core/tests/test_steps_amplitude.py`** (new) — the brief's 13 tests,
   copied verbatim.
6. **`packages/nsgeo-core/tests/test_steps_background.py`** (modified, not in the brief's
   file list — see "Issue found and fixed" below) — added `"amp_abs": {}`,
   `"amp_square": {}`, `"amp_envelope": {}` to `_STEP_PARAMS`.

### The `Dict`/`Tuple` ruling

Applied as instructed: the brief's code sample used `from typing import Any, Dict, Tuple`
and annotated `Dict[str, Any]` / `Tuple[ParamSpec, ...]`. I wrote `from typing import Any`
only, and used `dict[str, Any]` / `tuple[ParamSpec, ...]` in `_NoParams.params` and
`_NoParams.schema()`. Everything else in the code block is verbatim from the brief,
including the module docstring, the envelope algorithm, and all three step classes.

## Issue found and fixed (not in the brief)

Step 8 of the brief says the whole core suite should pass and calls out two
`test_schema.py` tests as the only pre-existing tests that iterate every registered
step. Running the full suite after implementation surfaced a **third** such test that
the brief didn't mention: `test_steps_background.py::test_none_of_the_steps_mutate_their_input`
is parametrized over a hardcoded `_STEP_PARAMS` dict and asserts
`set(_STEP_PARAMS) == set(available_steps())` inside the test body — so registering
`amp_abs`/`amp_square`/`amp_envelope` broke all nine of its existing parametrized
cases (each failed the `set(...) == set(...)` assertion before even reaching its own
logic).

This is a real invariant, not a test to route around: it exists specifically to catch
a step that mutates its input array in place (which would corrupt every other consumer
of the same cached `Radargram`). The correct fix was to extend `_STEP_PARAMS` with the
three new steps (`{}` for all three, since they take no parameters), giving them the
same mutation-safety coverage as every other step. I verified by hand that none of the
three steps mutates in place (`np.abs`, `x * x`, and the FFT/ifft/abs chain in
`analytic_envelope` all allocate new arrays), and the now-passing parametrized cases
for `amp_abs`, `amp_square`, `amp_envelope` confirm it.

I'm flagging this per the brief's own instruction ("If you hit any other place where
following the brief verbatim would fail ruff, mypy or a test, fix it and say so").

## TDD evidence

### RED

Command:
```
cd /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10
export PYTHONDONTWRITEBYTECODE=1
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_amplitude.py -v
```

Output (relevant part):
```
ERROR collecting tests/test_steps_amplitude.py
ImportError while importing test module '.../tests/test_steps_amplitude.py'.
Traceback:
  packages/nsgeo-core/tests/test_steps_amplitude.py:6: in <module>
    from nsgeo.processing.amplitude import analytic_envelope
E   ModuleNotFoundError: No module named 'nsgeo.processing.amplitude'
=========================== short test summary info ============================
ERROR packages/nsgeo-core/tests/test_steps_amplitude.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.18s ===============================
```

This is exactly the failure the brief predicted (Step 2): the test file existed but
`nsgeo.processing.amplitude` did not, so collection failed on import before any test
body ran.

### GREEN

Command:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_amplitude.py -v
```

Output:
```
collected 13 items

test_amp_abs_removes_the_negative_side PASSED
test_amp_square_is_energy PASSED
test_transforms_preserve_the_time_axis PASSED
test_envelope_of_a_sinusoid_is_its_amplitude PASSED
test_envelope_is_never_negative PASSED
test_envelope_handles_an_odd_and_prime_length PASSED
test_envelope_is_not_the_zero_padded_approximation PASSED
test_all_three_transforms_declare_themselves_unipolar PASSED
test_ordinary_steps_are_not_unipolar PASSED
test_stack_output_unipolar_follows_the_last_enabled_step PASSED
test_empty_stack_is_not_unipolar PASSED
test_transforms_take_no_parameters PASSED
test_unknown_parameter_is_rejected PASSED

============================== 13 passed in 0.12s ==============================
```

## Full suite, lint, mypy

After discovering and fixing the `test_steps_background.py` gap:

```
./.venv/bin/python -m pytest packages/nsgeo-core/tests -q
361 passed, 2 skipped in 1.23s
```

Baseline was 336 passed, 2 skipped. The +25 breaks down exactly: +13 from the new
`test_steps_amplitude.py`, and +12 from four pre-existing tests that enumerate
`available_steps()` and are parametrized per step name, each gaining the three new
names (`amp_abs`, `amp_envelope`, `amp_square`) — `test_schema.py`'s
`test_schema_names_match_params_keys_in_order`, `test_non_required_defaults_build_and_apply`,
and `test_defaults_respect_declared_bounds_and_choices` (3 x 3 = 9), plus
`test_steps_background.py`'s `test_none_of_the_steps_mutate_their_input` (3). Confirmed
by `pytest --collect-only` grepped for the three new step names. All deltas are
additions; no pre-existing test was removed or had its behaviour changed.

Specifically re-checked, per the brief's Step 8 callout:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_schema.py -v \
  -k "schema_names_match or only_the_two_known"
13 passed, 47 deselected in 0.13s
```
`test_schema_names_match_params_keys_in_order` now runs for `amp_abs`, `amp_envelope`,
`amp_square` too (trivially true for empty schema/params) and
`test_only_the_two_known_steps_have_required_params` still holds (none of the three
declares a `REQUIRED` default).

Lint:
```
./.venv/bin/ruff check .
All checks passed!
./.venv/bin/ruff format --check .
97 files already formatted
```

Mypy:
```
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
Success: no issues found in 25 source files
```

Also re-ran `test_boundary.py` explicitly (the test that fails if `qgis`/`PyQt` is
importable under `src/nsgeo/`): `2 passed in 0.03s`.

Checked for stray bytecode under the touched package (`find . -path
"*processing/__pycache__*"`): none found. `PYTHONDONTWRITEBYTECODE=1` was exported for
every test run in this task.

## Files changed

- `packages/nsgeo-core/src/nsgeo/processing/amplitude.py` (new)
- `packages/nsgeo-core/src/nsgeo/processing/base.py` (added `is_unipolar`)
- `packages/nsgeo-core/src/nsgeo/processing/stack.py` (added `output_unipolar`, import)
- `packages/nsgeo-core/src/nsgeo/processing/__init__.py` (import/export wiring)
- `packages/nsgeo-core/tests/test_steps_amplitude.py` (new, brief's tests verbatim)
- `packages/nsgeo-core/tests/test_steps_background.py` (extended `_STEP_PARAMS`; see
  "Issue found and fixed" above)

## Self-review findings

- Verified every one of the brief's code blocks was copied verbatim except for the
  `Dict`/`Tuple` -> `dict`/`tuple` ruling (docstrings, algorithm, class bodies, method
  bodies all unchanged).
- Checked the analytic-signal weighting matches the standard construction (Marple
  1999 / the same one `scipy.signal.hilbert` uses): `h[0]=1`; even `n`:
  `h[n/2]=1`, `h[1:n/2]=2`; odd `n`: `h[1:(n+1)/2]=2`, rest zero. Confirmed by the
  passing sinusoid, non-negativity, prime-length, and anti-zero-padding tests — none
  of these were satisfiable by a convenient-but-wrong implementation (the prime-length
  test in particular can't be gamed the way Task 1's first attempt was, since 463 has
  no non-trivial factors to hide a padding bug behind).
- Confirmed by hand (and by the extended mutation test) that none of the three steps
  mutates `rg.data` in place — each operation (`np.abs`, `x * x`, FFT/ifft/abs) returns
  a freshly allocated array.
- `output_unipolar` placement matches the brief exactly: right after `cache_size`, still
  before `__len__`, inside the `# ---- inspection ----` section.
- No overbuilding: did not add anything beyond the brief's three steps, one helper, one
  property, and the required registry/export wiring. The one addition beyond the brief's
  file list (`test_steps_background.py`) is a minimal, necessary fix to a pre-existing
  invariant test, not new functionality.
- Test output is pristine: no warnings, no deprecation noise, in any of the runs above.

## Concerns

None. TDD was followed honestly — the RED failure was the real
`ModuleNotFoundError`, not a contrived one, and the envelope's correctness rests on
tests (sinusoid amplitude, prime length, anti-zero-padding) that a wrong-but-convenient
implementation could not pass, per the brief's own warning about Task 1's mistake.

---

## Fix report: review finding — odd branch and Nyquist bin were unpinned

### What the review found

All 13 original tests in `test_steps_amplitude.py` pass against a plausible odd-branch
off-by-one (`weights[1 : n // 2] = 2.0` instead of `weights[1 : (n + 1) // 2] = 2.0`),
because the only test pinning an actual envelope *value* used `n=512` (the even branch).
`weights[1 : (n + 1) // 2] = 2.0` — the line `amplitude.py:112`, the one 463-sample
production data actually executes — was numerically unpinned by shape/finiteness/
non-negativity/not-equal assertions alone.

### A correction to the reviewer's own proposed fix, found before writing anything

The coordinator's message flagged that the reviewer's first proposed test (a k=37
sinusoid on n=463) does not discriminate the bug, and gave a corrected three-test plan.
Before implementing test 2 of that plan (the broadband energy identity), I verified it
independently, as instructed, and found the *even-length* half of it was itself
mathematically wrong as literally stated:

The claimed identity `mean(|z|**2) == 2*mean(x**2) - mean(x)**2` (z the analytic
signal of real x) is exact for odd n (no Nyquist bin), but **not** exact for even n.
Derivation via Parseval: for even n the Nyquist bin (k = n/2) is real and unpaired,
like DC, and contributes a term the odd-only formula omits. The corrected identity for
even n is:

    mean(|z|**2) == 2*mean(x**2) - mean(x)**2 - mean(x * (-1)**arange(n))**2

Verified numerically (`/tmp/.../scratchpad/verify2.py`, `verify3.py` — session scratchpad,
not committed): on the *correct, committed* implementation, the uncorrected identity is
off by ~3.5e-3 (n=512) to ~8.2e-2 (n=8, n=10), while the corrected identity matches to
~1e-15 for every n tested (7, 8, 9, 10, 463, 512). Applying the coordinator's proposed
test unmodified at n=512 would therefore have failed against the **correct**
implementation — exactly the class of defect this whole review round exists to close,
just introduced from the opposite direction. I did not add that test as literally
specified; I added the corrected version instead, and said so in the test's own
docstring so a future reader doesn't reintroduce the simpler-but-wrong form.

### What I added

Three tests in `packages/nsgeo-core/tests/test_steps_amplitude.py`, inserted after
`test_envelope_is_not_the_zero_padded_approximation`:

1. `test_envelope_of_an_odd_length_sinusoid_is_its_amplitude` — sinusoid at
   `k = (n - 1) // 2` on `n = 463`, the top positive bin and the only bin where the
   odd branch's upper slice bound sits. Added verbatim as specified.
2. `test_envelope_energy_identity_pins_every_bin_weight` — the energy identity above,
   corrected for the even-n Nyquist term, checked over both `n=463` and `n=512` on
   broadband `default_rng(2)` noise, computed per-column (the correction terms are
   nonlinear in the mean, so they must be computed per column and then averaged, not
   computed once on the flattened array).
3. `test_envelope_even_length_nyquist_bin_is_not_doubled` — `cos(pi * arange(64))`
   must map to a flat envelope of 1.0. Added verbatim as specified.

### Discipline: each test verified against its wrong variant, by hand

For each of the three tests, I constructed the wrong variant, edited it into
`amplitude.py` in place, ran the targeted tests, confirmed the expected pass/fail
pattern, then restored the file and confirmed it was byte-identical to the committed
version (`diff` against a backup copy, and `git diff --stat` showing no changes) before
re-running the full suite.

**Variant A — odd off-by-one** (`weights[1 : n // 2] = 2.0` for odd n, dropping the top
positive bin):

Command:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_amplitude.py -v \
  -k "odd_length_sinusoid or energy_identity"
```
Result: **both FAIL**, as intended —
- `test_envelope_of_an_odd_length_sinusoid_is_its_amplitude`: envelope collapses to
  ~0 where it should be 3.0 (mismatch shown in raw pytest output, consistent with the
  coordinator's measured 3.0 deviation).
- `test_envelope_energy_identity_pins_every_bin_weight`: `Max absolute difference among
  violations: 0.01795734` (n=463 case) against `atol=1e-9`.

Cross-check — `test_envelope_even_length_nyquist_bin_is_not_doubled` (even-branch-only)
against this odd-only bug:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_amplitude.py -v -k "nyquist"
```
Result: **PASSES** — confirms the Nyquist test doesn't accidentally react to an
unrelated odd-branch bug (i.e. it isn't a vacuous assertion).

**Variant B — doubled Nyquist bin** (`weights[n // 2] = 2.0` for even n instead of `1.0`):

Command:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_amplitude.py -v \
  -k "nyquist or energy_identity"
```
Result: **both FAIL**, as intended —
- `test_envelope_even_length_nyquist_bin_is_not_doubled`: `ACTUAL: 2.0` vs
  `DESIRED: 1.0` for all 64 samples — matches the coordinator's predicted 2.0.
- `test_envelope_energy_identity_pins_every_bin_weight`: `Max absolute difference
  among violations: 0.02727109` (n=512 case) against `atol=1e-9`.

Cross-check — `test_envelope_of_an_odd_length_sinusoid_is_its_amplitude` (odd-branch-only)
against this even-only bug:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_amplitude.py -v -k "odd_length_sinusoid"
```
Result: **PASSES** — confirms it doesn't react to an unrelated even-branch bug.

**Restoration check** after each variant:
```
diff <backup> packages/nsgeo-core/src/nsgeo/processing/amplitude.py   # empty
git diff --stat packages/nsgeo-core/src/nsgeo/processing/amplitude.py  # empty
```
Both empty, confirming `amplitude.py` was returned to exactly the committed state
before final verification and commit.

### Final verification against the committed (correct) implementation

```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_amplitude.py -v
```
```
16 passed in 0.17s
```
(13 original + 3 new; all pass, including the three new ones.)

```
./.venv/bin/python -m pytest packages/nsgeo-core/tests -q
```
```
364 passed, 2 skipped in 1.31s
```
(361 from the first commit + 3 for the three new tests; no parametrized-by-step-name
test picks these up since they aren't step-registry tests.)

```
./.venv/bin/ruff check .
```
```
All checks passed!
```
```
./.venv/bin/ruff format --check .
```
```
97 files already formatted
```
```
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
```
```
Success: no issues found in 25 source files
```

### Files changed in this fix

- `packages/nsgeo-core/tests/test_steps_amplitude.py` (+48 lines, three new tests;
  `amplitude.py` itself untouched — the review confirmed the implementation was already
  correct, only the tests were missing).

### Commit

`7d43e01` — test(processing): pin the odd branch and Nyquist bin of analytic_envelope

### Concerns

None remaining on the reviewed finding. One thing worth flagging explicitly: the
"energy identity" as stated in the review brief was itself a near-miss of the exact
defect this round targets (a test that would pass on a wrong implementation is bad;
a test that fails on a correct implementation is arguably worse, since it blocks
merges or invites "fixing" correct code). I verified independently rather than trusting
the stated formula, per the instruction to check before writing anything — worth noting
since it means even a plan's own worked example needs the same scrutiny as an
implementer's first attempt. The three Minor findings (docstring benchmark figures,
zero-row guard, `output_unipolar`'s conservatism) remain deliberately unaddressed, as
instructed, for the final whole-branch review.
