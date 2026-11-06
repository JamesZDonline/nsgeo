# Task 1 report: core minimum-curvature solver

**Status:** DONE_WITH_CONCERNS
**Commit:** 6357aa1 feat(slices): minimum curvature, solved near the data (interpolation spec §5.4), pushed to origin/nsgeo-slice-interpolation-b.

## What I implemented

- **`interpolate.py`**
  - `METHODS` gains `"min_curvature"`.
  - Public `reach_mask(populated, cell, max_distance_m)`. `plan_fill`'s step 1 now uses it, so `FillWeights.targets == reach_mask(...) & ~populated` by construction. A new test pins that.
  - The `SliceFill` Protocol, with properties as the brief specifies.
  - `plan_fill` dispatches `"min_curvature"` to `plan_curvature`, after all of its existing validation, with a function-level import. Its return type is `FillWeights | CurvaturePlan`, with `CurvaturePlan` imported under `TYPE_CHECKING`.
  - The module docstring has one added sentence pointing to `curvature.py`.
- **`curvature.py`** (new)
  - The constants are verbatim: `CURVATURE_TOL`, `CURVATURE_EPS`, `CURVATURE_MAX_ITERATIONS` and `SOLVE_MARGIN_CELLS`.
  - `SolveStopped`, the frozen `CurvaturePlan`, and `plan_curvature`.
  - **Stencil.** The 13 coefficient arrays are built by vectorised accumulation, term kind by term kind: one slice-add per pair of distinct cells in a term, with no probing. Rows of data cells and of cells outside D are zeroed.
  - **CG.** Matrix-free conjugate gradients in float32 over a 2-cell zero-padded `p`. Dot products are float64 (`einsum(..., dtype=float64)`, which is buffered, so there is no float64 copy). It is Jacobi-preconditioned and follows the brief's loop exactly. `should_stop` is asked before every iteration. A guard on `p·q <= 0` stops a float32 breakdown from turning into NaN.
  - **Start.** Plan call 3 as written: linear interpolation along columns and along rows (one-sided where only one side has data), averaged where both exist, otherwise the one that exists, otherwise the data mean.
  - **Non-finite data** (plan call 10). The slice is re-planned on the finite data alone, and the data cell shows its own value.
  - **No target cells.** The solve runs 0 iterations.
  - **Thread safety.** `solve` writes only its own copies. A test checks that neither `values` nor `coefficients` changes.
- **`finish.py`**: `finish_slice(values, weights: SliceFill, ...)`.
- **`__init__.py`**: exports `CurvaturePlan`, `SliceFill`, `SolveStopped` and `plan_curvature`, added to `__all__` in sorted order.
- **`README.md`** (core): five rows (four new names, plus `METHODS`' description). The existing `test_the_readme_names_every_public_name` requires them. The brief's file list missed this, but it sits under `packages/nsgeo-core`, which the commit adds.

### Two numerical fixes the tests forced, both beyond the brief's pseudo-code

My first green attempt failed five tests: a constant 3.5 came back as 3.4995, and the plane, affine and NaN-constant cases failed too.

**1. The diagonal is minus the float64 sum of the row's off-diagonals, rounded once.**
- The cause: ε = 1e-6 lies below float32 resolution at a diagonal near 20, where a step is 1.9e-6. Each `+ε` rounded up a whole step, so the diagonal came out as 20.000008 against an exact 20.000004, and every row summed to +3.8e-6 instead of 0.
- That acted as a pull toward 0.
- Every term's coefficients sum to 0, so this is the exact diagonal, and it restores A·1 = 0 in float32. The interior rows come out exactly zero-sum.

**2. The solve runs about the data mean** (`data -= mean`, then `out += mean`).
- In exact arithmetic this changes nothing, because A·1 = 0.
- In float32 it makes a constant field exact (b = 0, so 0 iterations).
- It also stops an offset from eating float32 precision. Without it, `v + 1000` moved the result by 3.8% of the data range; with it, by 5.3e-5.
- I added `test_a_large_offset_costs_no_precision` to pin this. Without centring it fails with a max absolute difference of 0.240; with centring it passes.

What each fix does alone (the error is a fraction of ptp):

| Variant | Constant | Plane | Affine |
|---|---|---|---|
| Both fixes | exact | 5.2e-5 | 5.2e-5 |
| Old diagonal, with centring | exact | 1.9e-4 (fails 1e-4) | 4.7e-5 |
| New diagonal, no centring | exact | 4.3e-5 | 5.9e-5 |

The plane's 5e-5 is a float32 floor, not the tolerance: it is 4.8e-5 at tol 1e-7 and at tol 1e-8.

## Tests and results

- **Core + pure:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider` gives **981 passed, 3 skipped**.
  - The baseline was 937 passed and 3 skipped.
  - The skips are unchanged: the three by-design `test_schema.py` skips.
  - The real-data tests ran, including `test_real_lines_keep_their_data_and_fill_every_gap[min_curvature]`.
- **Lint:** `.venv/bin/ruff check . && .venv/bin/ruff format --check .` gives "All checks passed!" and "166 files already formatted".
- **Types:** the plan-context mypy command gives "Success: no issues found in 39 source files".
- **`SliceFill` conformance**, a scratch mypy check, not committed:
  - `a: SliceFill = plan_curvature(...)`, `b: SliceFill = plan_fill(...)` and `finish_slice(..., plan_fill(...), ...)` all type-check.
  - The only error is the deliberate one: the union is not assignable to `FillWeights`.
- **QGIS tier:** not run. The brief asks for core + pure, ruff and mypy. Nothing in the plugin is touched.

### Margins on the min-curvature tolerances (measured, not just passing)

| Test | Measured | Bound |
|---|---|---|
| plane | 5.2e-5 · ptp | 1e-4 · ptp |
| affine | 5.2e-5 · 2.5·ptp | 1e-4 · 2.5·ptp |
| dense, max 0.15 | 1.5e-6 · ptp | 1e-4 · ptp |
| dense, max 0.5 | 5.0e-6 · ptp | 1e-4 · ptp |
| offset 1000 | 5.3e-5 · ptp | 1e-4 · ptp |
| partial coverage | 95 iterations | ≤ 400 |
| no step (bound **not** loosened) | 0.34 of the bound | ≤ 1 |
| one line, sin x vs dense | 3.6e-5 | n/a |
| one line, sin x symmetry | 4.4e-6 | 1e-4 |

## TDD evidence

**RED 1** (tests written first; same command as Step 3):
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_interpolate.py packages/nsgeo-core/tests/test_slices_curvature.py -q -p no:cacheprovider`

```
E   ImportError: cannot import name 'reach_mask' from 'nsgeo.slices.interpolate'
E   ImportError: cannot import name 'CurvaturePlan' from 'nsgeo.slices'
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
```

Expected: neither `reach_mask` nor `nsgeo.slices.curvature` existed yet.

**RED 2.** I added only `reach_mask` and the `plan_fill` refactor, to get a behavioural failure. The command was the same, on `test_slices_interpolate.py`:

```
     20 E           ValueError: unknown interpolation method 'min_curvature'; expected one of ('none', 'idw', 'kriging')
      1 E       AssertionError: assert ('none', 'idw', 'kriging') == ('none', 'idw...in_curvature')
21 failed, 62 passed
```

Expected: `min_curvature` was an unknown method. The 62 that passed include every IDW and kriging test after the `reach_mask` refactor, plus the new `test_the_targets_are_the_reach_less_the_data`.

**First implementation:** 6 failed. Five were float32 accuracy (diagnosed and fixed above); the sixth was the README test.

**GREEN:** the same command plus `test_public_api.py` gives `113 passed`; later, the two files alone give `101 passed`.

**Offset test.** RED with centring disabled (`Max absolute difference among violations: 0.24017686`, `1 failed`). GREEN with it (`1 passed`).

## Timings (plan call 4), as recorded in curvature.py's docstring

Measured on this machine, alone, at max distance 0.375 m. The 0.2 m and 0.1 m rows are the median of 3 slices; the 0.05 m row is one slice.

| Case | Plan | Solve | Iterations | Spike target |
|---|---|---|---|---|
| Ten real lines, 25 × 100 at 0.2 m | 0.001 s | 4.2 ms | 38 | 5–8 ms |
| 50 m synthetic, full coverage, 0.2 m | 0.004 s | **69 ms** | 56 | 40–60 ms (escalate > 0.25 s) |
| 50 m synthetic, full coverage, 0.1 m | 0.02 s | 0.90 s | 184 | about 0.55 s |
| 50 m synthetic, full coverage, 0.05 m | 0.11 s | 14.6 s | 544 | about 10 s |
| 50 m, lines over 40% + a skipped line, 0.2 m | 0.004 s | 0.16 s | 150 | 0.2–0.65 s |

- The kriging preview on the same grids: plan 0.59 s and apply 10 ms at 0.1 m; plan 5.71 s and apply 73 ms at 0.05 m.
- **No escalation.** The 0.2 m full-coverage case is 69 ms, well under 0.25 s.
- **Accuracy** against a float64 CG to 1e-12 on the same operator, as a max over the reach (fraction of the data range):

| Cell | Max error | 99th percentile | Spike |
|---|---|---|---|
| 0.2 m | 2.6e-6 | 6.4e-7 | 1e-5 |
| 0.1 m | 3.3e-5 | 2.9e-6 | 1e-4 |
| 0.05 m | 2.8e-4 | 1.8e-5 | 4e-4 |

## tracemalloc peak per cell (ruling R2)

The setup mirrors Task 3's test: `_binned_rows(0.5, 0.05, nx=200)` (40,000 cells), then `plan_fill(pop, 0.05, "min_curvature", 0.375, 1.0)` and one solve, under tracemalloc. The script is `/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/ac13f161-32cb-4b27-9f12-2ce0f0d8a39b/scratchpad/task1/memory.py`.

| Values | Built before tracing | Copied inside the traced block |
|---|---|---|
| Smooth field (427 iterations) | **104.4 B/cell** | 112.3 B/cell |
| Random normal (438 iterations) | 104.3 B/cell | 112.3 B/cell |
| Constant (0 iterations) | 104.3 B/cell | 112.3 B/cell |

- The bound is 144 B/cell, so the margin is about 28%.
- The plan holds 55 B/cell: 52 for coefficients and 3 for masks.
- The peak is the start guess's scratch, about 40 B/cell, on top of the plan, the float32 data and `x`. I moved the start ahead of the CG buffers to get there; before that move the peak was 116.6 and 124.5 B/cell.

## Files changed

- `packages/nsgeo-core/src/nsgeo/slices/curvature.py` (new)
- `packages/nsgeo-core/src/nsgeo/slices/interpolate.py`
- `packages/nsgeo-core/src/nsgeo/slices/finish.py`
- `packages/nsgeo-core/src/nsgeo/slices/__init__.py`
- `packages/nsgeo-core/README.md`
- `packages/nsgeo-core/tests/test_slices_curvature.py` (new)
- `packages/nsgeo-core/tests/test_slices_interpolate.py`

## Self-review findings

- **Completeness.**
  - Every Step 1 switch to `ALL` was made, including the affine tolerance, the four-key `METHODS`, and the bad-input case.
  - `test_apply_at_matches_apply` read `fw.targets`, which `CurvaturePlan` does not have. It now derives the targets from `reach_mask(pop, STEP, 0.25) & ~pop`, which is the same set for IDW and kriging.
  - Every Step 2 test exists, with one deviation (Concern 1).
- **Added beyond the brief.** Each is small and pins a stated requirement or a hazard found while building:
  - `test_a_large_offset_costs_no_precision`
  - `test_nbytes_counts_the_arrays`, which also checks that `plan_fill` returns a `CurvaturePlan` with float32 (13, ny, nx) coefficients
  - `test_the_targets_are_the_reach_less_the_data` (BOTH), the brief's "must equal" interface rule
  - the stop test also checks that the plan's coefficients are unchanged (worker-thread safety)
  - the max-distance-zero test also asserts 0 iterations
- **Python 3.9.** No `zip(strict=)`, no `match`, and `X | Y` only in annotations under `from __future__ import annotations`. numpy ≥ 1.20 covers `einsum(dtype=)`, `copyto(where=)` and `array_equal(equal_nan=)`, and other tests already use `equal_nan`.
- **Values off the data cells** affect neither the output nor the solve. The start guess reads a clipped row for columns with no data, but those cells are always overwritten with NaN.

## Concerns (for the controller)

1. **`test_one_line_continues_flat_across_it`: the brief's expectation contradicts plan call 1's energy.**
   - The brief puts `sin(x)` along row 10 (21 × 30 at 0.05 m, max 0.25 m) and asks every finite cell in column j to be within 1e-4 of row 10's value.
   - The thin-plate minimiser is not flat across a line carrying a curved profile: Δ²(sin kx) ≠ 0, so it bends away from the line.
   - A dense least-squares solve of exactly plan call 1's energy deviates from flat by up to **1.1e-2**: 1.1e-2 at 5 cells from the line, 1.7e-3 at 1 cell. A correct solver therefore cannot pass that test.
   - What I committed instead keeps the test's intent, which is that collinear data leave no tilt:
     - a profile linear along the row (`0.3 + 0.8·x`) continues flat within 1e-4 (measured 0.0);
     - `sin(x)` is mirror-symmetric about the line within 1e-4 (measured 4.4e-6, against 3.6e-5 from the dense solve);
     - a single cell gives its value on its whole disc, as the brief asks.
   - Please confirm, or say what you want instead.
2. **`CurvaturePlan` has two scalar fields the interface does not list:** `cell: float` and `max_distance_m: float`, after the five listed fields.
   - Plan call 10 re-plans a slice with a non-finite datum on the finite data alone. That needs the cell and the max distance, and the listed fields cannot recover them.
   - `nbytes` still sums only the array fields, and nothing constructs `CurvaturePlan` except `plan_curvature`.
3. **The full-coverage timings sit above the spike's targets** (69 ms / 0.90 s / 14.6 s against 40–60 ms / 0.55 s / 10 s), though under the escalation line. Per iteration it matches the spike (26.8 ms at 0.05 m against about 25). The extra comes from:
   - **The start (plan call 3).** The equal average of rows and columns costs about 40% more iterations on wandering lines. A wandering line crosses rows only occasionally, so the row estimate spans metres. Measured alternatives, at 0.2 m and 0.1 m:

     | Start | Lines along X | Lines along Y |
     |---|---|---|
     | Equal average (shipped) | 56 / 184 | 56 / 184 |
     | 1/span-weighted average | 42 / 158 (57 ms / 0.81 s) | the same |
     | Columns only (the spike) | 39 / 131 (47 ms / 0.63 s) | 61 / 207 |

     Columns-only is not an option, because lines can run along Y or cross-hatch in a grid's own frame. I kept plan call 3 as written; the 1/span weighting is a one-function change if you want it.
   - **float64 dots.** These add about 15–20% per iteration: `einsum` float64 takes 75 µs per dot against BLAS float32 `vdot`'s 12 µs at 250², three per iteration.
   - **Consequence for Task 3.** At 0.2 m on a 50 m grid, no orientation-agnostic start brings the solve under `LIVE_SOLVE_BUDGET_MS = 50`, so such grids will take the preview-then-refine path. #111 (multigrid) is the real fix.
4. **For Task 3's implementer:**
   - `nsgeo_qgis/slices_engine.py` still annotates the result of `plan_fill` as `FillWeights` (lines 237 and 1032). It needs widening to `SliceFill` or the union. mypy's file list does not include that module, so nothing fails today.
   - `METHODS` now admits `"min_curvature"`, so `SliceFinish.updated` and the project loader accept it. `METHOD_LABELS` in `slices_plan.py` has no label for it yet; that is the plugin wiring task's job.

---

## Fix report: controller rulings (2026-11-05)

Rulings 1, 2, 4 and 5 were accepted with no code change, except ruling 1's docstring. Ruling 3 was implemented.

**What changed**
- **Ruling 3: the start is weighted by span** (`curvature.py`; it amends plan call 3).
  - `_along_columns` now returns `(estimate, weight)`. The weight is 1 / span in cells where data bracket the cell, else 0. It replaces the old `t` buffer: `t = (row − above) · weight`.
  - `_start` takes a 1/span-weighted average of the bracketed column and row estimates. Where neither direction is bracketed, it averages the one-sided estimates, or takes the one there is, or else the data mean.
  - A zero weight is skipped rather than multiplied, because its estimate may be NaN.
  - Dot products stay float64.
  - The docstrings for `_start` and the module (start description, timing table, accuracy) are updated.
- **New test** `test_the_start_weights_each_direction_by_its_span`. It tests the private `_start` directly, as `test_survey.py` does with `_load_profiles`, on three cases:
  - a cell bracketed both ways, with spans 4 and 20, gets the 1/span-weighted average;
  - a bracketed row beats a one-sided column;
  - two one-sided estimates are averaged.
- **Ruling 1:** `test_one_line_continues_flat_across_it`'s docstring now says why sin x is checked for symmetry and not, as the plan first asked, for flatness within 1e-4: the exact solution bends by up to 0.011, so a correct solve would fail that check.

**TDD**
- RED: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_curvature.py -q -p no:cacheprovider -k start_weights`

  ```
  E       assert np.float32(-0.04157673) == 0.07911237329244614 ± 1.0e-06
  1 failed, 18 deselected
  ```

  Expected: the equal average gave −0.0416 where 1/span weighting gives 0.0791.
- GREEN: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_curvature.py packages/nsgeo-core/tests/test_slices_interpolate.py -q -p no:cacheprovider` gives `102 passed`.

**Verification**
- Core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider` gives `982 passed, 3 skipped` (the same three schema skips).
- Lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .` is clean.
- Types: the plan-context mypy command reports `Success: no issues found in 39 source files`.

**Margins after the change**

| Test | Measured | Bound |
|---|---|---|
| plane | 5.1e-5 · ptp | 1e-4 · ptp |
| affine | 6.7e-5 | 1e-4 |
| dense, max 0.15 | 1.6e-6 | 1e-4 |
| dense, max 0.5 | 2.9e-6 | 1e-4 |
| partial coverage | 95 iterations | ≤ 400 |
| no step | 0.34 of the bound | ≤ 1 |
| one line, sin x symmetry | 4.4e-6 | 1e-4 |

**New timings** (re-measured alone; the 0.05 m case once)

| Case | Plan | Solve | Iterations | Before (equal average) |
|---|---|---|---|---|
| Ten real lines, 0.2 m | 0.001 s | 4.2 ms | 38 | 4.2 ms / 38 |
| 50 m full coverage, 0.2 m | 0.004 s | **49 ms** | 42 | 69 ms / 56 |
| 50 m full coverage, 0.1 m | 0.02 s | 0.79 s | 158 | 0.90 s / 184 |
| 50 m full coverage, 0.05 m | 0.11 s | 12.2 s | 459 | 14.6 s / 544 |
| 50 m, 40% covered, line skipped, 0.2 m | 0.003 s | 0.16 s | 141 | 0.16 s / 150 |

- The 0.2 m full-coverage case is back inside the spike's 40–60 ms, and only just under `LIVE_SOLVE_BUDGET_MS` (50 ms). Machine noise could push it either side of the live/preview line.
- The kriging preview: plan 0.60 s and apply 10 ms at 0.1 m; plan 5.74 s and apply 47 ms at 0.05 m.

**Accuracy** against a float64 solve to 1e-12, re-measured:

| Cell | Max error | 99th percentile |
|---|---|---|
| 0.2 m | 6.2e-6 of the data range | 7.9e-7 |
| 0.1 m | 4.8e-5 | 2.9e-6 |
| 0.05 m | 4.0e-4 | 2.2e-5 |

These are slightly above the equal-average start's 2.6e-6, 3.3e-5 and 2.8e-4. They are within the spike's 1e-5 and 1e-4 at 0.2 and 0.1 m, and equal to its 4e-4 at 0.05 m.

**New ruling R2 peak:** **103.3 B/cell**, or 111.2 B/cell with the values built inside the traced block, against the 144 bound. It was 104.4 and 112.3 before the change; dropping the `t` buffer pays for the weight arrays.

**Commit:** 24f99c6 perf(slices): weight the minimum-curvature start by span, pushed to origin/nsgeo-slice-interpolation-b.
