# Task 5 report: Streaming, and the fill between lines

## Fix report (post-review round)

Review verdict: quality Needs fixes, four items. Addressed all four below.
Commit: `f3473ee fix(slices): guard stream_slice against stale plans, pin
int64 and cross-line pooling`, pushed to `origin/nsgeo-m10`.

### Important 1: plan/z mismatch silently dims a streamed slice

`resample_window` slices `plan.z_index[k0:k1]`; if a plan was built
against a shorter `ZAxis`, that slice silently comes back with fewer than
`n_levels` rows (Python/numpy slicing clips rather than raising), and
`stream_slice`'s `.sum(axis=0)` and `count[...] += plan.counts... * n_levels`
swallow the shortfall with no error -- a dimmed slice, not an exception,
where `build_cube` raises on the identical input.

**Fix** (`packages/nsgeo-core/src/nsgeo/slices/binning.py`, in
`stream_slice`, right after the existing `len(lines) != len(plans)`
check): validate every plan's level count against `z.nz` up front, before
any accumulation:

```python
for line, plan in zip(lines, plans):
    if plan.z_index.shape[0] != z.nz:
        raise ValueError(
            f"line {line.key!r}: plan has {plan.z_index.shape[0]} levels, but z has "
            f"{z.nz} -- the plan was built against a different z axis and must be "
            f"replanned before streaming against this one"
        )
```

**Test added** (`test_slices_streaming.py`):
`test_streaming_rejects_a_plan_built_for_a_different_z_axis` -- builds
plans against `ZAxis(nz=16)`, then calls `stream_slice` with
`ZAxis(nz=32)` and window `(0, 32)`; asserts `pytest.raises(ValueError,
match="different z axis")`.

**Mutant evidence** (harness:
`/tmp/claude-1000/.../scratchpad/m10_task5_fix_mutants.py`, Mutant A --
`stream_slice` with the new guard removed, everything else identical):

```
[test_streaming_rejects_a_plan_built_for_a_different_z_axis]
PASS (test correctly rejects the mutant): pytest.raises reports: DID NOT RAISE ValueError
build_cube on the same stale plans raises: operands could not be broadcast
  together with shapes (32,30) (16,30) (32,30)
build_cube raised as expected: True
stream_slice (buggy, no guard) returned finite values with no error: True
```
Confirms both halves: the test passes against shipped code (raises) and
fails against the mutant (silently returns finite, dimmed values) --
while `build_cube` on the identical stale-plan input raises its own
broadcast error, matching the divergence the review measured.

### Important 2: nothing pinned int64 count accumulation

**Test added** (`test_slices_streaming.py`):
`test_streaming_accumulates_counts_without_int32_overflow` -- builds one
real `LinePlan` via `plan_line`, then `dataclasses.replace`s its `counts`
with `np.full(plan.counts.shape, 2**29, dtype=np.int32)` and streams a
6-level window; asserts the single touched cell's coverage comes back as
exactly `2**29` (not negative, not wrapped).

**Mutant evidence** (Mutant B -- `stream_slice` with `count` accumulated
as `int32` instead of `int64`, matching the shipped guard for Important 1
so only the dtype differs):

```
[test_streaming_accumulates_counts_without_int32_overflow]
PASS (test correctly rejects the mutant): AssertionError
```
Passes against shipped code (`406 passed` includes it, see below); fails
against the int32-accumulator mutant.

### Promoted Minor: the property test's survey never puts two lines in one cell

`make_survey` in `test_slices_streaming.py` now appends a seventh line
(`key="l_repeat"`) that re-shoots line index 1's track at `y = 0.75`, but
with `n_traces - 5` traces instead of `n_traces` -- a different spacing,
so it lands a *different* number of traces than line 1 in some shared
cells, which is what actually distinguishes per-trace pooling from
per-line-mean pooling (a same-count collision would make the two
algorithms agree by coincidence).

**Mutant evidence** (Mutant C -- `stream_slice` that computes each line's
own per-cell mean first, then averages those per-line means across lines
touching a cell, instead of pooling every trace by its true count):

```
[test_streaming_a_window_equals_slicing_a_resident_cube (now with a colliding repeat-pass line)]
PASS (test correctly rejects the mutant): AssertionError
Not equal to tolerance rtol=1e-05, atol=1e-06
Mismatched elements: 11 / 480 (2.29%)
Max relative difference among violations: 0.3077767

For contrast, replaying the mutant against the OLD (pre-fix) survey shape,
where every cell is touched by at most one line:
  max relative difference on the OLD (no-collision) survey: 0
  max relative difference on the NEW (colliding) survey: 0.307777
```
Confirms the promotion's premise directly: the identical mutant is
invisible on the old single-line-per-cell survey (0 relative difference)
and clearly caught on the new one (31% relative difference, 11/480
cells). All other streaming and fill tests still pass with the new
survey shape (see full-suite run below).

### Promoted Minor: `test_fill_preserves_a_fully_covered_slice` didn't test what its name said

Decision written down: keep the existing smear behaviour (an
already-observed cell IS rewritten by its neighbourhood at `r >= 1` --
that's the same trade-off GPRSLICE's oversized search box makes, not a
bug), and pin both halves honestly instead of leaving the name
implying otherwise.

**Changes** (`test_slices_fill.py`):
- Renamed `test_fill_preserves_a_fully_covered_slice` ->
  `test_fill_at_zero_radius_leaves_a_fully_covered_slice_unchanged`,
  with a docstring noting it's the `r=0` pass-through path already
  covered more generally by `test_zero_radius_is_a_no_op`.
- Added `test_fill_smooths_a_fully_covered_slice_rather_than_preserving_it`:
  same fully-covered 8x8 random fixture, `radius_cells=1`; asserts
  `not np.allclose(out, values)` (the slice IS changed), `np.isfinite(out).all()`,
  and that `out` stays within `[values.min(), values.max()]` (a disc-weighted
  mean is a convex combination of a subset of `values`, so it can't
  overshoot their global range -- pins "smoothing", not "noise" or a
  sign error).

**Mutant evidence** (Mutant D -- `fill` with an alternative,
plausible-but-undecided design: already-observed cells are left exactly
as they were, `out = np.where(counts > 0, values, smoothed)`, only NaN
cells get the smoothed value):

```
[test_fill_smooths_a_fully_covered_slice_rather_than_preserving_it]
PASS (test correctly rejects the mutant): AssertionError
```
Passes against shipped code (which smooths everywhere); fails against
the "preserve observed cells" mutant (whose output would equal `values`
everywhere on this fully-covered fixture, since `counts > 0` is `True`
throughout, violating `not np.allclose(out, values)`).

### Commands and full output after all four fixes

```
$ PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest \
    packages/nsgeo-core/tests/test_slices_streaming.py packages/nsgeo-core/tests/test_slices_fill.py -v
...
test_streaming_a_window_equals_slicing_a_resident_cube PASSED
test_streaming_coverage_equals_the_cube_coverage PASSED
test_streaming_marks_empty_cells_nan PASSED
test_streaming_rejects_an_inverted_window PASSED
test_streaming_rejects_a_plan_built_for_a_different_z_axis PASSED
test_streaming_accumulates_counts_without_int32_overflow PASSED
test_disc_kernel_is_round_and_odd_sized PASSED
test_zero_radius_is_a_no_op PASSED
test_fill_reaches_an_empty_cell_from_its_neighbours PASSED
test_fill_is_a_weighted_mean_not_a_sum PASSED
test_fill_weights_by_count_so_a_busy_cell_counts_more PASSED
test_fill_leaves_cells_beyond_every_observation_as_nodata PASSED
test_fill_at_zero_radius_leaves_a_fully_covered_slice_unchanged PASSED
test_fill_smooths_a_fully_covered_slice_rather_than_preserving_it PASSED
test_fill_rejects_a_negative_radius PASSED
test_fill_rejects_mismatched_shapes PASSED
16 passed in 0.15s

$ PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest packages/nsgeo-core/tests -q
406 passed, 2 skipped in 1.29s        # was 403 passed, 2 skipped before this round; +3 net new tests, 0 regressions

$ ./.venv/bin/ruff check .
All checks passed!

$ ./.venv/bin/ruff format --check .
103 files already formatted

$ ./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
Success: no issues found in 28 source files
```

### Files changed in this round

- `packages/nsgeo-core/src/nsgeo/slices/binning.py` -- added the
  plan/z-axis guard to `stream_slice`.
- `packages/nsgeo-core/tests/test_slices_streaming.py` -- `make_survey`
  gained a colliding repeat-pass line; two new tests added.
- `packages/nsgeo-core/tests/test_slices_fill.py` -- one test renamed,
  one new test added.

### Not addressed (explicitly out of scope this round, per the coordinator)

The `radius_cells == 0` fast path's gating condition, the unreachable
NaN-with-nonzero-count case, the untested `len(lines) != len(plans)` and
out-of-range `k0`/`k1` branches, `min_count` never exercised at a
non-default value, and the FFT's lack of next-fast-size rounding or
kernel-spectrum caching. Deferred to the final whole-branch review as
instructed.

## What I implemented

Exactly what the brief specified, in its step order:

1. `stream_slice(lines, plans, frame, z, k0, k1) -> tuple[np.ndarray, np.ndarray]`,
   appended to `packages/nsgeo-core/src/nsgeo/slices/binning.py`. Bins only the
   levels inside `[k0, k1)` straight from the lines, holding no cube -- the same
   algorithm as `build_cube` restricted to a window. Accumulates `count` as
   `int64` and narrows to `int32` only on return, per the standing constraint.
   Rejects `len(lines) != len(plans)` and an invalid/inverted window.

2. `packages/nsgeo-core/src/nsgeo/slices/fill.py` (new file):
   - `disc_kernel(radius_cells) -> np.ndarray` -- a flat round disc, `(2r+1, 2r+1)`.
   - `fill(values, counts, radius_cells, min_count=0.5) -> np.ndarray` -- convolves
     `value * count` and `count` with the same disc kernel via `numpy.fft.rfft2`/
     `irfft2` (no scipy), then divides; cells whose weighted count stays below
     `min_count` stay NaN. `radius_cells == 0` is a fast no-op path (no FFT).

3. `packages/nsgeo-core/src/nsgeo/slices/__init__.py` extended (not rewritten):
   added `stream_slice` to the existing `binning` import block, and a new
   alphabetically-placed `from nsgeo.slices.fill import disc_kernel, fill` line.

4. Tests: `packages/nsgeo-core/tests/test_slices_streaming.py` and
   `packages/nsgeo-core/tests/test_slices_fill.py`, copied verbatim from the brief.

## Deviations from the brief, and why

- **`Tuple` -> `tuple`** in `stream_slice`'s return annotation, per the ruling in
  the task instructions (ruff `UP` would reject `typing.Tuple`; `binning.py`
  already has `from __future__ import annotations`). No `typing.Tuple` import
  was ever added.
- **Reformatted `test_slices_streaming.py`'s `prov()` helper.** The brief's own
  code block writes it as two lines with multiple keyword arguments packed per
  line:
  ```python
  return Provenance(
      line_keys=(), preset_name="p", steps=(), transform="amp_abs",
      velocity=None, built_utc="2026-09-18T00:00:00Z", core_version="0.1.0.dev0",
  )
  ```
  `ruff format --check .` flagged this file as needing reformatting (one
  argument per line, since the call doesn't fit ruff's line-length in the
  packed form). I ran `ruff format` on just that file to match the project's
  enforced style; the code is otherwise identical. This is exactly the
  "brief verbatim would fail ruff" case the task instructions call out --
  fixed and reported rather than silently diverged from, and rather than
  loosening ruff's formatting check.
- **Commit trailer.** The brief's own example commit message ends with
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. The
  conversation's attribution system-reminder explicitly states it *replaces*
  earlier attribution guidance -- including, by its own wording, "a previous
  copy of this reminder" -- and is overridden only by the user's own
  CLAUDE.md/memory instructions, not by a plan document. I used the
  reminder's trailer, `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`,
  which also matches the actual implementer model per the project's own
  "implementers sonnet" convention (MEMORY.md: subagent-model-tiers).

No other deviations. `stream_slice` and `fill.py` are otherwise byte-for-byte
the brief's code blocks.

## TDD evidence

**RED** -- ran before any implementation existed:

```
cd .worktrees/nsgeo-m10 && PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest \
  packages/nsgeo-core/tests/test_slices_streaming.py packages/nsgeo-core/tests/test_slices_fill.py -v
```
```
ERROR collecting tests/test_slices_streaming.py
ImportError: cannot import name 'stream_slice' from 'nsgeo.slices.binning' (.../binning.py)
ERROR collecting tests/test_slices_fill.py
ModuleNotFoundError: No module named 'nsgeo.slices.fill'
2 errors in 0.18s
```
This is exactly the failure the brief predicted (Step 2) -- both new symbols
did not exist yet, so both test modules failed at collection, before any
test logic could run.

**GREEN** -- after implementing `stream_slice`, `fill.py`, and the `__init__.py`
export:

```
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest \
  packages/nsgeo-core/tests/test_slices_streaming.py packages/nsgeo-core/tests/test_slices_fill.py -v
```
```
test_streaming_a_window_equals_slicing_a_resident_cube PASSED
test_streaming_coverage_equals_the_cube_coverage PASSED
test_streaming_marks_empty_cells_nan PASSED
test_streaming_rejects_an_inverted_window PASSED
test_disc_kernel_is_round_and_odd_sized PASSED
test_zero_radius_is_a_no_op PASSED
test_fill_reaches_an_empty_cell_from_its_neighbours PASSED
test_fill_is_a_weighted_mean_not_a_sum PASSED
test_fill_weights_by_count_so_a_busy_cell_counts_more PASSED
test_fill_leaves_cells_beyond_every_observation_as_nodata PASSED
test_fill_preserves_a_fully_covered_slice PASSED
test_fill_rejects_a_negative_radius PASSED
test_fill_rejects_mismatched_shapes PASSED
13 passed in 0.13s
```

## Full suite, lint, types

```
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest packages/nsgeo-core/tests -q
403 passed, 2 skipped in 1.26s        # baseline was 390 passed, 2 skipped; +13 new tests, 0 regressions

./.venv/bin/ruff check .
All checks passed!

./.venv/bin/ruff format --check .
103 files already formatted           # after the one reformat noted above

./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
Success: no issues found in 28 source files
```
Output is pristine -- no warnings, no deprecation notices, no stray stderr.

## Wrong-implementation discrimination evidence

Per the standing requirement, I built each of the six named "plausible wrong
implementations" (the brief's fifth bullet names two mutants), ran the
brief's own pinned tests against each, and confirmed PASS-against-correct /
FAIL-against-wrong for both halves. Harness:
`/tmp/claude-1000/.../scratchpad/m10_task5_mutants.py` (scratch-only, not
committed -- monkeypatches each mutant into a freshly-loaded copy of the test
module and calls the relevant test function directly).

Command: `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python m10_task5_mutants.py`

### 1. `stream_slice` window off by one (treats `k1` as inclusive)

Mutated to sample `k0..k1` inclusive (`bug_k1 = min(k1+1, z.nz)`), everything
else identical (still `int64` counts).

- At the **interior** window `(4, 12)` (not the full axis, not at either
  edge): `test_streaming_a_window_equals_slicing_a_resident_cube` **FAILS**
  -- 180/480 cells mismatch, up to 61% relative difference. Caught.
- I additionally checked the **edge** window `(30, 64)` (`nz=64`) in
  isolation: there, `min(k1+1, z.nz)` clamps back to `z.nz`, so the bug
  degrades to a no-op and streamed == resident **even with the bug present**.
  This confirms the brief's warning that a property test using only an
  edge-flush or full-axis window would have let this exact mutant through
  silently -- the interior window `(4, 12)` in the given test is what
  actually exercises it, and it does.

### 2. Counts accumulated as `int32` instead of `int64`

The given pinned tests (`make_survey`: 6 lines, 40 traces, nz=64) never come
close to `int32` overflow -- `plan.counts * n_levels` tops out at a few
hundred there, so this mutant would pass every test in
`test_slices_streaming.py` unchanged. This matches the brief's framing: the
`int64` requirement is a structural safeguard, not something its own tests
exercise at that scale.

I reproduced the actual accumulation mechanism the constraints note
describes ("a 230-level cube") directly: the real code's
`count[plan.cells] += plan.counts.astype(...) * n_levels` is an in-place
accumulation inside the `for line, plan in zip(...)` loop, so I replayed
that same in-place-add pattern 9,340 times (1000 traces/cell x 230 levels
per line, one busy cell) with `int32` vs. `int64` accumulators:

```
9340 lines x 1000 traces/cell x 230 levels
int64 accumulator (correct): 2148200000
int32 accumulator (mutant):  -2146767296   <-- wrapped negative, no exception raised
```

This is exactly the symptom the constraints warn about: silent negative
coverage, no exception. `stream_slice` as implemented accumulates `count` as
`int64` throughout and narrows to `int32` only on the final `.astype()` at
return, so it does not exhibit this.

### 3. Fill sums instead of taking a weighted mean

Mutant returns the convolved numerator directly (masked by `min_count`) with
no division by the convolved denominator.

- `test_fill_is_a_weighted_mean_not_a_sum` **FAILS**: expected `3.0`
  (`(2+4)/2`), mutant returns `6.0` (`2+4`).
- `test_fill_weights_by_count_so_a_busy_cell_counts_more` **FAILS**:
  expected `3.0` (`(2*3+6*1)/4`), mutant returns `12.0` (`2*3+6*1`).

Both caught.

### 4. Fill weights every cell equally instead of by count

Mutant drops the `* counts` weighting from the numerator and convolves a
0/1 presence mask instead of `counts` for the denominator.

- `test_fill_weights_by_count_so_a_busy_cell_counts_more` **FAILS**:
  expected `3.0` (count-weighted: `(2*3+6*1)/4`), mutant returns `4.0`
  (unweighted: `(2+6)/2`). Caught.
- `test_fill_is_a_weighted_mean_not_a_sum` passes trivially against this same
  mutant (both source cells there have `count=1`, so equal-weighting and
  count-weighting coincide) -- confirming why the brief's dedicated
  busy-cell test, not the weighted-mean test, is the one that actually
  distinguishes this mutant.

### 5. Fill invents values beyond every observation

Mutant replaces `np.divide(num, den, out=nan, where=den>=min_count)` with
plain `num / (den + 1e-9)` -- no NaN mask. Far from any observation, both
`num` and `den` are `0` from zero-padding, so this mutant returns `0.0`
there instead of `NaN`.

- `test_fill_leaves_cells_beyond_every_observation_as_nodata` **FAILS**:
  `out[8, 8]` is `0.0`, not NaN. Caught.

### 6. `disc_kernel` square instead of round / off by one in radius

- **Square** (`np.ones((2r+1, 2r+1))`): `test_disc_kernel_is_round_and_odd_sized`
  **FAILS** at `k[0, 0] == 0.0` (mutant gives `1.0`, the corner is included).
  Caught.
- **Off by one** (`< r*r` instead of `<= r*r`): same test **FAILS** at
  `k[0, 2] == 1.0` (mutant gives `0.0`, the boundary point is excluded).
  Caught.

All six named mutants are discriminated by the brief's own pinned tests
(mutant 2's safeguard is structural / demonstrated by direct repro rather
than by the given tests, as explained above and as the brief anticipates).

### A note on the mutant harness itself

While building the harness I hit a real Python gotcha worth recording:
`import nsgeo.slices.fill as fillmod` silently bound `fillmod` to the `fill`
*function* (not the submodule), because `nsgeo/slices/__init__.py`'s own
`from nsgeo.slices.fill import disc_kernel, fill` line rebinds the package's
`fill` attribute from the auto-set submodule reference to the function of
the same name -- a classic submodule/re-export name collision. This is
**not a bug in the shipped code**: `nsgeo.slices.fill` resolving to the
function is exactly the intended flat public API (mirroring `build_cube`,
`plan_line`, etc.), and every actual caller in this codebase and its tests
uses `from nsgeo.slices.fill import ...` (which resolves via `sys.modules`
and is unaffected) or `from nsgeo.slices import fill` (which is meant to
get the function). It only bit my own throwaway debugging script, fixed
there by pulling the submodule out of `sys.modules` directly. Flagging it
here in case it's useful context, not as an issue with the deliverable.

## Files changed

- `packages/nsgeo-core/src/nsgeo/slices/binning.py` -- added `stream_slice`.
- `packages/nsgeo-core/src/nsgeo/slices/fill.py` -- new file: `disc_kernel`, `fill`.
- `packages/nsgeo-core/src/nsgeo/slices/__init__.py` -- exports extended.
- `packages/nsgeo-core/tests/test_slices_streaming.py` -- new.
- `packages/nsgeo-core/tests/test_slices_fill.py` -- new.

Commit: `184049f feat(slices): streaming slices and the fill between lines`,
pushed to `origin/nsgeo-m10`.

## Self-review

- **Completeness**: all three interfaces from the brief (`stream_slice`,
  `disc_kernel`, `fill`) are implemented with the exact specified signatures;
  both test files are present and passing; `__init__.py` exports both new
  public names, alphabetically placed among the existing ones.
- **Quality**: docstrings match the existing voice in `binning.py`/`frame.py`/
  `cube.py` (explain the *why*, not just the *what*); no dead code; the
  `radius_cells == 0` fast path in `fill` avoids doing an FFT for the common
  "fill off" case.
- **Discipline**: nothing added beyond the brief's two functions and one
  module-level docstring; did not split `fill.py`, did not add extra
  parameters, did not touch `accumulate`/`build_cube`/`resample_window`.
- **Testing**: the property test genuinely exercises a non-trivial case --
  6 lines, 40 traces each (`n_traces=40` over `nx=30` guarantees some cells
  get 0, 1, or 2+ traces), 3 windows including one strictly interior
  `(4, 12)` and one at each axis edge/boundary shape; I additionally
  verified by direct experiment (mutant 1) that the interior window is
  necessary to catch an off-by-one and the edge window alone would not have
  been. Ran the exact commands specified throughout, no ad hoc substitutes
  in the delivered test files.
- Nothing found that needed further fixing beyond the two brief-verbatim
  deviations already noted (both already applied and re-verified green).

## Issues or concerns

None outstanding. The two deviations from brief-verbatim text (annotation
style, one file's formatting, and the commit trailer identity) are each
required by an explicit, higher-precedence instruction in this task's
setup, and are called out above rather than silently applied.
