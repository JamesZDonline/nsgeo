# Final review: nsgeo-multigrid (#111), code commits a8b6e4b..d982eb7

I found no correctness defects. There is one Important finding: at the default 0.2 m cell the solver is slower in more cases than the ruling assumed, and the walkthrough does not check the case where that matters most. The rest are doc and polish items.

### Strengths
- **Plan alignment.** The module follows the plan's interface exactly. The one extra is the optional `spare` argument on `precondition`, which is documented and backward compatible. `CurvaturePlan` gains only the new `hierarchy` field, and `plan_curvature` is its only constructor.
- **The numerics are sound.** I re-derived each step:
  - `restrict` is the exact transpose of `prolong`, including the odd-length padding and the clamped ends.
  - The coarse operator reaches ±2 cells, so probes 5 cells apart recover it exactly. A probe on an inactive coarse cell gives exact zeros.
  - The in-place symmetrisation is correct: `mirror2` is taken before `coef[k]` is overwritten.
  - The l1 bound holds even though the row sums include the columns to data cells (it is just looser).
  - Using the same Chebyshev polynomial before and after the coarse correction keeps the V-cycle symmetric and positive definite.
- **Thread safety holds.** Four threads solving one 500×500 plan, overlapping in time, matched the serial results exactly in 3 of 3 runs. `precondition(r, spare)` gives exactly the same output as without `spare`, and leaves `r` untouched. Repeated solves, and solves on a rebuilt plan, are identical.
- **The memory trim changed nothing.** `_start` matches the base revision (e701f82) exactly on 27 shape and density combinations, including ny > 8192 and one-cell-wide frames.
- **Edge inputs all converge.** I tried frames from 1×1 to 5×1, one row, one column, two rows, diagonal lines, L-shaped coverage, a disc, two clusters, and sparse points. They took 7–28 iterations, or 91–92 for a single line with a 5 m max distance. The output is finite everywhere within reach.
- **At the 4 M-cell cap** (2000×2000 cells at 0.05 m): the plan holds 95 B a cell, of which the hierarchy is about 0.77× the coefficients. Building peaks at 112 B a cell, and a solve at 35 B a cell. A solve takes 13 s and 14 iterations.
- **Tests.** They check the algebra itself (Galerkin product against a dense one, the active-cell rule, the smoother bound, symmetry and positivity) plus every Review Focus input. The real-data test compares against a float64 reference solve.

### Issues

#### Critical (Must Fix)
None.

#### Important (Should Fix)
1. **The 0.2 m slowdown is general, and Whole site adds up the cost** (`curvature.py:63-64`, the ruling, the walkthrough page).
   - **What I measured.** Median of 7 solves on wandering 0.5 m lines at 0.2 m, before → after:

     | Grid size | Before | After |
     |---|---|---|
     | 5×20 m | 4.8 ms | 9.6 ms |
     | 10×10 m | 4.0 ms | 8.5 ms |
     | 16×20 m | 8.7 ms | 14.0 ms |
     | 30×30 m | 20.0 ms | 30.7 ms |
     | 40×40 m | 33.5 ms | 50.7 ms (crosses the 50 ms budget) |
     | 50×50 m | 51.3 ms | 71.6 ms |

     The spike found that the real Grid 1 breaks even, because Jacobi needed 144–171 iterations there. The ten real lines are 2.2× slower (4 → 9 ms).
   - **Why Whole site matters.** Whole site adds up the last solve times of all its unsolved grids and checks the total against `LIVE_SOLVE_BUDGET_MS` (`site_engine.py` ~940-952, and `plugin._bands_are_slow`). So four 16×20 m grids go from 35 ms (follows the depth live) to 56 ms (kriging preview, then refine).
   - **Effect on the user.** At the default cell, Whole site and single grids of 40–50 m may now show the preview and "Refining…" where main followed the depth live.
   - **The walkthrough misses it.** D2 checks only Grid 1 at 0.2 m, and E1 checks Whole site at Grid 1's 0.05 m.
   - **Fix:**
     - Add a check E2: Whole site at 0.2 m, drag the depth, and compare with `ns_geo` for the preview note.
     - Change the docstring's "no faster" to the measured slowdown.
     - If E2 flips, let the user decide on a follow-up, such as skipping the hierarchy when it has few unknowns.

#### Minor (Nice to Have)
- **M1 `multigrid.py:4`:** "took 459 iterations (`curvature.py`)" is stale. `curvature.py`'s table now says 492 (50 m grid) and 540 (real lines).
- **M2 `multigrid.py:28-31`:** "`Hierarchy.precondition` writes nothing it was given" contradicts `spare`, which it overwrites. Add "except the planes a caller lends it".
- **M3 Cancellation is slower to respond** (`curvature.py:206/214`). `should_stop` is still asked once per iteration, but an iteration is now a whole V-cycle:

  | | Branch | Base |
  |---|---|---|
  | Grid 1 size, between checks | 24 ms | 3 ms |
  | 4 M cells, before the first check | 1.45 s | 0.6 s |
  | 4 M cells, between checks | 0.85 s | 0.12 s |

  This is negligible on Grid 1. At the cap, the refine worker can keep solving a depth the user has already left for about 1.5 s. Optional fix: also ask `should_stop` once just before the first V-cycle.
- **M4 float32 accuracy floor when the max distance is large** (outside the recorded cases). Maximum error as a fraction of the data range:

  | Case | Branch | Base (Jacobi) |
  |---|---|---|
  | Single line, max distance 2 m | 6.7e-2 | 2.9e-2 |
  | 0.2% points, max distance 1 m | 2.9e-3 | 1.7e-3 |
  | Lines with a 2 m gap, max distance 1.2 m | 1.5e-3 | 2.2e-3 |

  Tightening `CURVATURE_TOL` to 1e-7 leaves the error at 6.5e-2, so this is float32's attainable accuracy, not the stopping rule. Not a blocker. File a follow-up: mixed-precision iterative refinement (a float64 residual and one more ~15-iteration solve) is now cheap. No test covers this kind of input.
- **M5 The memory estimate undercounts more.** A minimum-curvature plan now holds about 95 B a cell (was about 55), and it is held next to its kriging preview (about 95 B a cell). The over-budget warning counts 96 B a cell (`WEIGHT_BYTES_PER_CELL`), and the `MAX_FRAME_CELLS` comment's "about 0.4 GB of weights" is further off for minimum curvature. This needs a plugin change, which the plan forbids here, so file a follow-up.
- **M6 The two-thread solve test** (`test_slices_curvature.py:234`) uses an 80×120 frame where each solve takes milliseconds, so the threads may not actually overlap. Enlarge the frame or assert overlap. I confirmed real overlap at 500×500.
- **M7 A non-finite datum re-plans on every solve, and that now includes building the hierarchy.** At Grid 1 size a solve goes from 0.25 to 0.43 s; at the cap the re-plan is about 6 s and cannot be cancelled. Binned data never take this path and processing guards against non-finite values, so leave it, perhaps with a comment.

### Deferred minors triage
1. T1 symmetry-test comment "0.3 to 200": fix in the wave (one line).
2. T1 `multigrid.py:151` "one plane-sized temporary": fix in the wave. Either correct the comment or use `coef[k] += mirror; coef[k] *= 0.5`, which gives exactly the same result.
3. T1 task-1-report.md missing test output: leave. It is ledger text and changes no code.
4. T2 `curvature.py:39` "38" should be 41, and "~4x" should be ~3.5x: fix in the wave. A maintainer would rely on these figures.
5. T2 `curvature.py:43-46` borrows milestone B's 99th-percentile figure: fix in the wave with the measured 3.5e-6, 1.4e-5 and 1.1e-4 (99th percentile 1.3e-5).
6. T2 `curvature.py:64` "no faster": fix in the wave. This is the most important doc fix (see Important 1).
7. T2 `curvature.py:61` 0.582 s from one noisy run: fix in the wave. Say it is a single run, or use a median.
8. T2 `curvature.py:52` "nothing else of mine running": fix in the wave (trivial).
9. T2 `_along_block` in-place juggling: leave. I verified it matches the base exactly, and restoring the old body is churn.
10. T2 `tight_solve` can hit its 20,000 cap silently: fix in the wave with one `assert its < 20000`, so the reference is known to have converged.
11. T2 `test_pure_slices_plan.py:501-503` stale figures (should be ~95 B a cell for the plan and ~138 for plan plus solve): fix in the wave. Test docstrings are allowed under the plan.
12. T2 the 4% memory margin and the unchecked `spare`: leave. The tight margin is the test doing its job, and `spare` has one private caller.
13. T2 three copies of the 13-point product: leave and file a follow-up if wanted. Merging them risks the speed and exact results for little gain.

### Rulings I disagree with
- **The 0.2 m ruling, in part.** Its premise, "both sides mostly sit on the same side of the 50 ms budget", holds for one Grid 1-sized grid. It does not hold for 40–50 m grids, or for Whole site, which adds the grids' times together. The slowdown is also 1.4–2× at every size on regular lines, not only on big grids. I accept that a dual Jacobi/multigrid path was rejected. What I disagree with is accepting this without walkthrough evidence: add E2 and fix the docstring.
- **The plan build-time ruling.** I agree with the outcome, but its figures stop at 1 M cells. At `MAX_FRAME_CELLS` the build takes 6.0 s against 0.54 s before, on the GUI thread (`SliceEngine._fill_for` is called from `finish` and `preview`). Record the cap figure in the docstring.
- I agree with all other rulings, including trimming memory rather than loosening the estimate test.

### Declined to judge
- **Large-offset precision** (1e6 plus O(1) variation; 1e4 plus 1e-3): the errors are identical on base and branch. They come from rounding the values to float32 before the mean is subtracted, which predates this branch.
- **Changing the stopping rule:** the plan fixes it, and M4 shows a tighter tolerance would not help.
- **Plan builds and exports running on the GUI thread:** that is #108, out of scope by agreement.
- **Max distance 0 builds an unused hierarchy over the 2-cell margin ring:** an edge setting that only costs time.
- **BLAS thread safety, and determinism across machines or thread counts:** out of scope. Determinism on one machine is verified.
- **Plan time across many grids in Whole site:** accepted by the ruling, and E1 covers it.
- **Kriging preview build time:** its code is unchanged.
- **Quality of the throwaway spike scripts:** they are kept only as a record.
- **Python 3.9, ruff and mypy:** CI run 42938092348 is green; I did not re-run them.
- **Speed of prolong's transposed-layout output:** polish, not correctness.

### Verdict
**Ready to merge after walkthrough: With fixes.** The code is correct, safe across threads and meets the plan. The fix wave is the doc minors (4–8, 11, M1, M2) plus the `tight_solve` convergence assert. Before the merge decision, the walkthrough page should gain an E2 check for Whole site at 0.2 m.
