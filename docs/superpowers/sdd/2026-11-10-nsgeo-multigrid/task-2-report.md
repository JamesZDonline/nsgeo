# Task 2 report
Implemented: CurvaturePlan.hierarchy (build_hierarchy in plan_curvature), V-cycle precondition replaces Jacobi in _solve_into, nbytes + hierarchy, docstring refreshed; tests per brief (incl. tight_solve, real-data test).
RED: 12 failed, 16 passed (AttributeError hierarchy; iteration bounds 540 > 30). GREEN: 28 passed.
Core + pure: 1092 passed, 5 skipped, 1 FAILED: packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py::test_the_weights_estimate_covers_building_them[min_curvature]: plan+apply peak 164 B/cell (6551566/40000) vs limit 1.5*96=144 (was ~103). Held plan 100 B/cell (hierarchy ~40), solve adds 64. Outside my file scope; needs controller decision (raise WEIGHT_BYTES_PER_CELL / test, or trim).
QGIS: 1598 passed in 867.96s. ruff + mypy clean.
Bench (load 2.0 -> 1.8) after: real 0.2: plan .019 solve .009 its 7; real 0.05: .060/.105/15; 50m 0.2: .080/.071/6; 0.1: .270/.442/11; 0.05: 1.393/3.290/15; partial: .582/.088/7.
Real-line errors vs 1e-10 float64: 0.05 m windows 10,50: 3.55e-5, 2.96e-5 (its 16, 15); 0.2 m: 4.0e-7, 2.1e-7 (its 7).
Concerns: plan build cost up (1.4 s at 50 m 0.05 m; 0.58 s on partial case, 0.2 m solves slightly slower); the memory test above.

## TDD evidence
RED: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_curvature.py -q -p no:cacheprovider` -> `12 failed, 16 passed in 6.46s` (AttributeError no `hierarchy`; `assert 540 <= 30` real-lines iterations; iteration-bound tests).
GREEN (same command, after implementing): `28 passed in 8.52s`.

## Fix report: transient memory (controller ruling)
Before: plan + one solve peaked at 164 B/cell (6551566/40000) on the pure test's frame; bound 144. After: 138.3 B/cell. Plan held ~100 B/cell unchanged; solve's peak above it 64 -> 38.
What changed (curvature.py, multigrid.py only):
- `_start`/`_along_columns`: blockwise over columns (`_along_block` is the old body, with in-place span/index planes). Start was the peak at 48 B/cell (int32 planes + intp-widened fancy indices).
- `_solve_into` takes `values` + `mean` and builds/frees the float32 data copy itself (`del data` after the first use); `solve` no longer holds a data copy (mean and finite check from `values[pop].astype(float32)`, same elements).
- CG: `del z` before each V-cycle; `precondition(r, spare=(q, work))` lends CG's idle q/work planes to level 0 (caller-local, thread-safe).
- multigrid: `_Scratch` (call-local pad/out/work), direction lives in the padded buffer, in-place Chebyshev updates, residual reuses scratch, prolong/restrict with one output + one coarse temporary and no pad copy for even lengths. The mask multiplies before A were dropped: every vector is exactly 0 off active (scale is 0 there).
Equivalence (scratch script, old modules from `git show 8363ce3` as mg_old/cv_old): five frames (200x200, 97x131, 60x45, 31x33, 250x250; 2-5 levels), `plan.solve` out + iterations, with NaN-masked values, with a NaN datum, `precondition(r)` with and without `spare`, restrict/prolong, `_start`: all `np.array_equal(..., equal_nan=True)` -> `ALL SAME True`.
Bench (load 3.1, busier than the first 2.0 run): real 0.05 m solve 0.116 s (was 0.105), 50 m 0.05 m solve 3.16 s (was 3.29), 0.1 m 0.465 s (was 0.442): within noise, docstring table left as is.
Suites: pure plan file `58 passed`; curvature `28 passed`; multigrid + core + pure: `1093 passed, 5 skipped in 37.42s`; ruff, format, mypy clean. QGIS suite not re-run (nothing outside the two modules touched).
