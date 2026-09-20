# Task 4 Report: `SliceCube` and the binner

## What I implemented

- `packages/nsgeo-core/src/nsgeo/slices/cube.py` — `Provenance` (frozen dataclass with
  `to_dict`/`from_dict`) and `SliceCube` (frozen dataclass with `slice_levels(k0, k1)` and
  `coverage()`), exactly as specified in the brief.
- `packages/nsgeo-core/src/nsgeo/slices/binning.py` — `CoverageError`, `PreparedLine`,
  `LinePlan`, `plan_line`, `resample_window`, `accumulate`, `build_cube`, exactly as specified
  in the brief, **minus `slice_extent`** (dropped per the controller's ruling #2 — it has no
  caller anywhere in the plan, spec, or the task's own Interfaces block).
- `packages/nsgeo-core/src/nsgeo/slices/__init__.py` — extended (not rewritten) to re-export
  the new names from `binning` and `cube`, alongside the existing `frame` re-export.
- `packages/nsgeo-core/tests/test_slices_binning.py` — the 13 tests from the brief, verbatim.

### Rulings applied

1. **Annotations.** `cube.py` uses `tuple[str, ...]`, `dict[str, Any]`, and `dict[str, Any] |
   None` instead of the brief's `Tuple`/`Dict`/`Optional`. `Any` is the only remaining
   `typing` import. `binning.py` needed no `Tuple`/`Dict` at all once `slice_extent` was
   dropped (it was the only user of `Tuple` there). For `Sequence`, I imported it from
   `collections.abc` rather than `typing` — the brief's code block used
   `from typing import Sequence, Tuple`, but `typing.Sequence` is itself a UP035 violation on
   `target-version = "py39"`, and the codebase already follows the `collections.abc` form
   (`packages/nsgeo-core/src/nsgeo/processing/gain.py` imports it that way). I also used
   `dict[str, Any] | None` rather than `Optional[dict[str, Any]]` for `Provenance.velocity`,
   for the same reason: `Optional[X]` triggers UP007 and the codebase's existing convention
   throughout `src/` (checked ~15 call sites across `render.py`, `dzx.py`, `velocity.py`,
   `processing/base.py`, `geometry/grid.py`, etc.) is uniformly `X | None`, never `Optional`.
   These are mechanical consequences of the two named rulings, not new decisions — the code
   is otherwise verbatim.
2. **`slice_extent` omitted entirely** — not created, not exported, not tested.
3. One more mechanical fix beyond the two named rulings: `ruff format` reformatted
   `test_slices_binning.py`'s multi-line calls in `prov()` and
   `test_cube_rejects_a_mean_of_the_wrong_shape` (the brief's own snippet was not
   ruff-format-clean). This is whitespace/line-wrapping only — I diffed the reformatted file
   against the verbatim version and the only changes are argument-per-line splitting; no
   token was added, removed, or reordered. Re-ran the focused suite after reformatting to
   confirm no behavioural change (still 13 passed).

## TDD evidence

**RED** — before creating `cube.py`/`binning.py`:

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_binning.py -v
...
ImportError while importing test module '.../tests/test_slices_binning.py'.
packages/nsgeo-core/tests/test_slices_binning.py:5: in <module>
    from nsgeo.slices.binning import CoverageError, PreparedLine, build_cube, plan_line
E   ModuleNotFoundError: No module named 'nsgeo.slices.binning'
=========================== short test summary info ============================
ERROR packages/nsgeo-core/tests/test_slices_binning.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.17s ===============================
```

Expected and matched exactly: the brief's Step 2 predicted this precise error before any
implementation existed.

**GREEN** — after implementing both modules and the `__init__.py` export:

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_binning.py -v
...
13 passed in 0.10s
```

All 13 tests pass, including after the `ruff format` pass (re-verified, still `13 passed`).

**Full suite, once, before committing:**

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests -q
387 passed, 2 skipped in 1.15s
```

374 baseline + 13 new = 387. No regressions, skip count unchanged.

**Linters:**

```
$ ./.venv/bin/ruff check .
All checks passed!
$ ./.venv/bin/ruff format --check .
100 files already formatted   (after reformatting test_slices_binning.py once)
$ ./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
Success: no issues found in 27 source files
```

## Mutant discrimination evidence (the standing requirement)

For each named mutant: patched `binning.py` in place, ran the focused test file, recorded the
failure, then restored the original from a backup copy and confirmed byte-identical restoration
(`diff` produced no output).

### 1. Sum instead of averaging where two lines cross the same cell

Mutation: `mean = total` in `build_cube` (skip the `np.divide`-by-`count` step entirely).

```
FAILED test_cells_with_no_traces_are_nan_not_zero
FAILED test_two_lines_in_one_cell_average_rather_than_sum
    AssertionError: ACTUAL: array(6., dtype=float32)   DESIRED: array(3.)
2 failed, 11 passed in 0.12s
```

`test_two_lines_in_one_cell_average_rather_than_sum` (the brief's own test for exactly this
mutant) **fails** against the sum-not-mean version and **passes** against the real
implementation. Confirmed discriminating.

### 2. `reduceat` segment boundaries off by one

Mutation: in `plan_line`, changed
`np.concatenate([[True], sorted_ids[1:] != sorted_ids[:-1]])` (prepend the boundary marker) to
`np.concatenate([sorted_ids[1:] != sorted_ids[:-1], [True]])` (append it instead) — shifting
every group's start index later by one, so a trace at a group boundary is attributed to the
wrong (neighbouring) group in the `reduceat`.

```
FAILED test_count_records_traces_per_cell
    assert np.int32(1) == 2
1 failed, 12 passed in 0.12s
```

`test_count_records_traces_per_cell` catches the miscount directly. Confirmed discriminating.

### 3. Resample rounds to nearest source sample instead of interpolating linearly

Mutation: `resample_window` replaced the linear blend
`lower * (1 - weight) + upper * weight` with `np.where(weight >= 0.5, upper, lower)`.

```
FAILED test_resampling_interpolates_between_source_samples
    ACTUAL:  [ 0., 10., 10., 20., 20., 30., 30.]
    DESIRED: [ 0.,  5., 10., 15., 20., 25., 30.]
1 failed, 12 passed in 0.12s
```

Confirmed discriminating — the nearest-neighbour values are visibly stair-stepped instead of
linear.

### 4. Empty cells left as 0.0 rather than NaN

Mutation: `np.divide(total, count, out=np.zeros_like(total), where=count > 0)` instead of
`np.full_like(total, np.nan)`.

```
FAILED test_cells_with_no_traces_are_nan_not_zero
    AssertionError: assert np.False_
     +  where np.False_ = <ufunc 'isnan'>(np.float32(0.0))
1 failed, 12 passed in 0.12s
```

Confirmed discriminating. The covered cells in this test carry a nonzero value (1.0), so the
test is not fooled by a real zero — it specifically targets an *uncovered* cell, which is
exactly what makes it a valid test given the brief's own warning that 0.0 is also a legitimate
amplitude.

### 5. Count records samples rather than traces (off by exactly `nz`)

Mutation: in `accumulate`, `count[plan.cells] += plan.counts` became
`count[plan.cells] += plan.counts * block.shape[0]` (i.e. multiplied by the number of levels in
the accumulated window — `nz` when called from `build_cube`).

```
FAILED test_a_constant_line_bins_to_that_constant
FAILED test_count_records_traces_per_cell
FAILED test_two_lines_in_one_cell_average_rather_than_sum
FAILED test_traces_outside_the_frame_are_dropped_not_clipped
FAILED test_resampling_interpolates_between_source_samples
FAILED test_a_line_with_a_different_dt_lands_on_the_same_axis
FAILED test_slice_levels_averages_over_the_window
7 failed, 6 passed in 0.14s
```

Widely discriminating — most tests fail because the mean itself is now wrong (divided by an
inflated count), and `test_count_records_traces_per_cell` catches the count directly
(`cov[0, 0]` off by a factor of `nz`). Confirmed discriminating.

All five named mutants are caught by the existing suite; no new tests were needed to catch
them (the brief's tests already discriminate each one).

## Realistic-magnitude check (beyond the brief's toy coordinates)

Per the standing instruction to test at real UTM magnitudes rather than only toy ones (that is
what hid Task 1's bug), I ran an ad hoc script (not committed — it duplicates coverage already
in the test suite, just at different magnitudes) with:

- `origin = (500000.0, 4500000.0)`, `cell = 0.05`, `nx=40, ny=20`, `crs="EPSG:32617"`
- 400 traces spread linearly across the frame, with the last trace landing exactly at the far
  edge `(origin[0] + nx*cell, origin[1] + ny*cell)` — the exact case `CubeFrame.cell_index`'s
  edge tolerance exists to handle at UTM magnitudes.
- `ZAxis(t0_ns=0.0, dz_ns=0.2, nz=50)`, 120-sample synthetic line.

Result: all 400 traces landed in a cell (`coverage().sum() == 400`, including the far-edge
point — confirming the binner composes correctly with Task 1's edge-tolerance logic at real
magnitudes, not just toy ones); every covered cell's mean was non-NaN; every uncovered cell's
mean was NaN. No coordinate-scale-dependent bug analogous to Task 1's was observed.

## Files changed

- `packages/nsgeo-core/src/nsgeo/slices/cube.py` (new)
- `packages/nsgeo-core/src/nsgeo/slices/binning.py` (new)
- `packages/nsgeo-core/src/nsgeo/slices/__init__.py` (extended)
- `packages/nsgeo-core/tests/test_slices_binning.py` (new)

## Self-review findings

- Read the full diff fresh after committing. `__init__.py`'s diff is a clean 8-line addition,
  extending rather than rewriting the file as instructed.
- File sizes stayed within the brief's intent: `binning.py` 146 lines, `cube.py` 102 lines,
  test file 137 lines — close to the brief's own code-block lengths (binning.py lost ~8 lines
  by dropping `slice_extent` and its now-unused `Tuple` import).
- Verified no leftover `Tuple`/`Dict`/`Optional`/`typing` imports beyond `Any` in `cube.py`,
  and no trace of `slice_extent` anywhere in the tree (`grep -rn slice_extent
  packages/nsgeo-core/` is empty).
- `PreparedLine`, `LinePlan`, `Provenance`, `SliceCube` all follow the frozen-dataclass +
  `__post_init__`-validation pattern established in `frame.py`; docstring voice (short,
  reasons-not-just-what) matches `frame.py`'s style.
- Test output is pristine — no warnings, no stray prints, in both the focused run and the full
  suite run.
- Did not add anything beyond the brief's interfaces (no extra helper functions, no
  speculative parameters). `resample_window` and `accumulate` are exported implicitly via the
  module but not re-exported from `__init__.py`, matching the brief's Step 5 export list
  exactly (only `CoverageError, LinePlan, PreparedLine, build_cube, plan_line` from
  `binning`).

## Issues or concerns

None outstanding. The only two departures from the brief's literal text are the two
controller-mandated rulings (annotations, `slice_extent` omission) plus the incidental
`Sequence`/`Optional` import-source corrections that those rulings' own logic (ruff `UP` +
existing codebase convention) forced, and the one-time `ruff format` whitespace pass on the
test file (verified behaviourally inert). I'm confident in this implementation.

---

## Fix report (review round 1)

Commit: `fe27512` fix(slices): close binning's untested-corruption paths from review

The review found no behavioural defect in the shipped code — every finding was about tests
that failed to discriminate a plausible wrong implementation, plus one dead/dangerous
parameter pair left as a trap for Task 5. Fixed all four.

### Finding 1 — multi-trace-per-cell sum never numerically verified

**Change:** added `test_two_distinct_traces_in_one_cell_average_within_the_line` to
`test_slices_binning.py`. Two traces with DISTINCT values (2.0 and 8.0) land in the same cell
(a third trace at 100.0 lands in a different cell, confirming groups don't bleed into each
other); asserts `coverage()[0,0] == 2`, `slice_levels(0,5)[0,0] == 5.0` (their average), and
explicitly `cube.mean[0,0] * cube.count[0] == 10.0` (their sum) — the exact invariant Task 5's
fill depends on.

No source change was needed for this finding — the existing `np.add.reduceat` in `accumulate`
was already correct; only the test coverage was missing.

**Mutant evidence** (segment sum → first-column pick, `total[:, plan.cells] += block[:,
plan.starts]` instead of `np.add.reduceat(...)`):

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_binning.py -q
...
FAILED test_slices_binning.py::test_two_distinct_traces_in_one_cell_average_within_the_line
    AssertionError: ACTUAL: array(1., dtype=float32)   DESIRED: array(5.)
1 failed, 14 passed in 0.12s
```

Only the new test fails — confirming the reviewer's point that
`test_two_lines_in_one_cell_average_rather_than_sum` and `test_count_records_traces_per_cell`
do not catch this mutant, and the new test does. Against the real (restored) code: all 15
tests pass. File restored and diffed byte-identical against a pre-mutation backup.

### Finding 2 — `order`'s remap through `keep` never exercised

**Change:** added `test_a_dropped_trace_preceding_kept_ones_does_not_corrupt_the_grid`. A
4-trace line with the OUT-OF-FRAME trace FIRST (value 999.0, must never land in any cell),
followed by three kept traces with distinct values (20.0, 30.0, 40.0) landing in three
different cells of row 0. Asserts `row0[:3] == [20, 30, 40]`, `row0[3]` is NaN, and
`coverage()[0] == [1, 1, 1, 0]`.

No source change needed — `order = keep[np.argsort(ids[keep], kind="stable")]` was already
correct; only the test coverage (drop-last, never drop-first) was missing.

**Mutant evidence** (`order = np.argsort(ids[keep], kind="stable")`, dropping the `keep[...]`
remap):

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_binning.py -q
...
FAILED test_slices_binning.py::test_a_dropped_trace_preceding_kept_ones_does_not_corrupt_the_grid
    nan location mismatch:
     ACTUAL:  [20., 30., nan]
     DESIRED: [20., 30., 40.]
1 failed, 14 passed in 0.12s
```

Traced why: under the mutant, `order` (meant to be absolute column indices) instead holds
positions relative to the `keep` subset, so `sorted_ids = ids[order]` indexes the wrong entries
of the full `ids` array, producing `cells = [-1, 0, 1]`. `-1` is a valid (wrapping) numpy index,
so `total[:, -1]` — the opposite corner of the grid, flat index 11 for this `4x3` frame —
silently receives the dropped trace's value (999.0) and a bogus count of 1, while the real
trace at flat cell 2 (value 40.0) is never written and its cell reads back as NaN. This is
exactly the "pile onto one border row / opposite corner" failure the reviewer described,
confirmed by running the mutant rather than by derivation alone. Only the new test catches it;
restored and diffed byte-identical.

### Finding 3 — `accumulate`'s dead `k0`/`k1`

**Decision: removed them** (the reviewer's preferred option), rather than making them do what
their names say. Reasoning: `build_cube` is `accumulate`'s only caller and always passes the
full axis (`0, z.nz`); there is no real use case in this plan for calling `accumulate` on a
sub-window (Task 5's streaming path, per the reviewer's own note, inlines its own accumulation
with its own `count * n_levels` bookkeeping and never calls `accumulate`). Keeping a parameter
that produces a silently-wrong `count` (double-counted on a second partial call) if a future
caller used it exactly as its name and signature suggest is worse than removing it. Neither
`accumulate` nor `resample_window` appears in the task's Interfaces block or `__init__.py`'s
exports, so the signature change is invisible to every consumer that exists.

`accumulate` now takes `(total, count, line, plan)` and derives the level count from
`total.shape[0]` internally, calling `resample_window(line, plan, 0, total.shape[0])`.
`resample_window` itself keeps its explicit `(k0, k1)` — it is a real, independently useful
resampling primitive over an arbitrary window, not a dead parameter pair.

Grepped the whole `packages/nsgeo-core/` tree for `accumulate`/`resample_window` call sites
before changing the signature: `build_cube` is the only caller of `accumulate`, and
`accumulate` is the only caller of `resample_window`; no test calls either directly. No other
change required.

### Finding 4 — `cell_index` relies on an undefined float→int cast for non-finite/huge inputs

**Change:** `frame.py`'s `cell_index` now computes `position = local / self.cell` (the exact
quantity that gets floored and cast), builds `finite = (np.isfinite(position) &
(np.abs(position) < bound)).all(axis=1)` with `bound = np.iinfo(np.intp).max / 4.0`, and
substitutes `0.0` for `local` on non-finite/out-of-range rows via `safe = np.where(finite[:,
None], local, 0.0)` BEFORE the `floor().astype(np.intp)` cast — so the undefined cast is never
reached for those rows. `finite` is AND-ed into the final `inside` mask so such rows always
resolve to `-1`, regardless of what `ix`/`iy` happened to compute. Docstring extended to
explain why. Added a matching test, `test_cell_index_drops_non_finite_and_astronomically_large_
coordinates`, to `test_slices_frame.py` (Task 1's test file — explicitly authorized by the
reviewer's note, since `frame.py` is Task 1's file but "yours to touch for this"), asserting on
a UTM-scale frame with a mixed batch: one NaN row, one row with a coordinate of `1e20` (finite
but far beyond `intp` range), and two ordinary rows — wrapped in
`warnings.catch_warnings()` / `warnings.simplefilter("error")` so any warning raised during
`cell_index` fails the test outright.

**RED** (pre-fix `cell_index`, reverted from the fixed source back to the original
`floor(local[...]).astype(np.intp)` form with no guard, applied temporarily and then restored):

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py::test_cell_index_drops_non_finite_and_astronomically_large_coordinates -v
...
>       ix = np.floor(local[:, 0] / self.cell).astype(np.intp)
E       RuntimeWarning: invalid value encountered in cast
FAILED ...
1 failed in 0.12s
```

Matches the finding exactly: under `simplefilter("error")`, the previously-silent
`RuntimeWarning` becomes a hard failure — this is why the un-guarded code, though it happened
to return the right answer, was not safe to rely on. File restored and diffed byte-identical
against a pre-mutation backup.

**GREEN** (fixed `cell_index`):

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -v
...
test_cell_index_drops_non_finite_and_astronomically_large_coordinates PASSED
...
20 passed in 0.25s
```

No warning raised; the NaN row and the `1e20` row both resolve to `-1`, the two ordinary rows
resolve to valid (non-negative) ids.

### Full verification after all four fixes

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_binning.py -v
...
15 passed in 0.11s

$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -v
...
20 passed in 0.25s

$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests -q
390 passed, 2 skipped in 1.16s

$ ./.venv/bin/ruff check .
All checks passed!

$ ./.venv/bin/ruff format --check .
100 files already formatted

$ ./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
Success: no issues found in 27 source files
```

390 = 374 baseline + 13 original binning tests + 2 new binning tests (findings 1 and 2) + 1 new
frame test (finding 4). No regressions, skip count unchanged, output pristine (no warnings in
any run).

### Files changed (this round)

- `packages/nsgeo-core/src/nsgeo/slices/binning.py` — `accumulate` signature (finding 3)
- `packages/nsgeo-core/src/nsgeo/slices/frame.py` — `cell_index` finite/range guard (finding 4)
- `packages/nsgeo-core/tests/test_slices_binning.py` — 2 new tests (findings 1, 2)
- `packages/nsgeo-core/tests/test_slices_frame.py` — 1 new test (finding 4)

### Concerns

None. All four findings addressed with source fixes where warranted (3, 4) or test-only fixes
where the reviewer explicitly diagnosed the gap as test-only (1, 2), each backed by an actual
mutant/pre-fix run showing the specific failure the finding described, not just reasoning about
it.
