### Task 2: Minimum curvature solves with the hierarchy

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/slices/curvature.py`:
  - the module docstring, lines 1–59;
  - `CurvaturePlan`, lines 103–123;
  - `_solve_into`, lines 163–218;
  - `nbytes`, lines 241–248;
  - `plan_curvature`, lines 368–392.
- Modify: `packages/nsgeo-core/tests/test_slices_curvature.py`

**Interfaces:**
- Consumes: from Task 1, `build_hierarchy`, `Hierarchy.precondition`, `Hierarchy.nbytes` and `multigrid.COARSEST_UNKNOWNS`.
- Produces: `CurvaturePlan.hierarchy: Hierarchy`, a new field placed after `coefficients`. Nothing else in `CurvaturePlan`'s public surface changes. `solve`, `apply`, `apply_at`, `nbytes`, `SolveStopped` and the constants keep their signatures.

- [ ] **Step 1: Write the failing tests** in `test_slices_curvature.py`.
  - **Change** `test_min_curvature_matches_a_dense_solve`: also parametrize it over `coarsest` in `[500, 2]` with `monkeypatch.setattr(multigrid, "COARSEST_UNKNOWNS", coarsest)`, and assert `(len(plan.hierarchy.levels) > 1) == (coarsest == 2)`. The tolerance stays as it is.
  - **New** `test_min_curvature_matches_a_dense_solve_across_levels`. A `(30, 34)` frame at 0.1 m: `rng(7).random(...) < 0.08`, plus rows 4, 12, 20 and 27 full, with max distance 0.3 and the default coarsest. Assert at least 2 levels. Compare with `dense_solve` to `atol=1e-4 * np.ptp(v[pop])`. The dense solve takes about 1.3 s.
  - **Tighten** `test_partial_coverage_solves_in_few_iterations` from `<= 400` to `<= 20`. The spike took 4 iterations; Jacobi took 95. Update its docstring's numbers.
  - **New** `test_iterations_barely_grow_as_cells_shrink`.
    - The frame is 10 m × 10 m at 0.2, 0.1 and 0.05 m. Lines run along X at `y = 0.25 + 0.5 i + 0.06 sin(x / 3 + i)`, plus full columns at x = 2.1, 5.3 and 8.6 m. Values are `sin(x / 1.7) cos(y / 2.3) + 0.3 sin(3.1 x + 1.3 y)`, and max distance is 0.375.
    - Every solve takes `≤ 30` iterations, and `its(0.05) ≤ 3 × its(0.2)`. The spike took 6, 10 and 14; Jacobi took 39, 152 and 549.
  - **New** `test_the_hierarchy_shares_the_plans_operator`: `plan.hierarchy.levels[0].coefficients is plan.coefficients`, and `levels[0].active` equals `plan.domain & ~pop`.
  - **New** `test_the_hierarchy_costs_less_memory_than_the_operator`: a `(400, 400)` frame at 0.05 m with a line every 10th row and max distance 0.375 gives `plan.hierarchy.nbytes < plan.coefficients.nbytes`. The spike measured 0.78×.
  - **New** `test_two_threads_solve_one_plan_as_one`: four threads call `plan.solve` with four different value fields on one plan (`lines(ny=80, nx=120)` at 0.05 m, max distance 0.25). Each `(out, iterations)` equals the serial result, with `np.array_equal(..., equal_nan=True)`.
  - **Change** `test_a_plan_is_read_only` so it also loops over every hierarchy array, and `test_nbytes_counts_the_arrays` so the expected sum adds `plan.hierarchy.nbytes`.
  - **New, real data** (`@needs_real_files`) `test_real_lines_at_a_fine_cell_match_a_tight_solve`.
    - Use `prepared_lines(range(10), lambda local: local)` and `CubeFrame((0.0, 0.0), 0.0, 0.05, 400, 100, "EPSG:32633")`, with max distance `0.75 * SPACING`.
    - For `WINDOWS[0]` and `WINDOWS[2]`: `v, cov = binned(...)`, then `plan.solve(v)`.
    - Assert `iterations <= 30`. Assert the largest `|out − tight|` over `reach & ~pop` is `<= 4e-4 * np.ptp(v[pop])` (B's 0.05 m figure). The spike gave 15–16 iterations and 2.8–3.5e-5.
    - `tight_solve(plan, values)` is a test helper: float64 Jacobi-preconditioned CG on `plan.coefficients`, starting at 0, run to `‖r‖ ≤ 1e-10 ‖b‖`, with `b = −A·d` as `_solve_into` builds it. It returns the slice with the data in place and NaN off `plan.reach`. In the spike it took about 1,100 iterations, 1.8 s a window. Its body is the spike's `tight` in `check4.py`.

- [ ] **Step 2: Run them to see them fail**

  Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_curvature.py -q -p no:cacheprovider`
  Expected: the new and changed tests fail on `AttributeError: 'CurvaturePlan' object has no attribute 'hierarchy'`. The iteration tests fail on their bounds.

- [ ] **Step 3: Implement.**
  - **`plan_curvature`:** `unknown = domain & ~pop2`. Pass `coefficients=_stencil(domain, unknown)` and `hierarchy=build_hierarchy(_OFFSETS, coefficients, unknown)`.
  - **`_solve_into`:** drop the `inverse` array. `z = self.hierarchy.precondition(r)` replaces `z = r * inverse` and `np.multiply(r, inverse, out=z)`. Everything else in the loop stays as it is, including `_times` and the `pq > 0` guard.
  - **`nbytes`:** add `self.hierarchy.nbytes`.
  - **`__post_init__`:** the hierarchy freezes itself, so add only a line to the comment.
  - **Module docstring:**
    - Replace "Jacobi preconditioned" (and the iteration/time paragraph that explains it) with the multigrid description, about 5–8 lines that cite #111 and the spike note.
    - Replace the table with the output of `docs/superpowers/notes/2026-11-10-multigrid-spike/bench.py`, run on a quiet machine, with the Jacobi figures below as a "before" column. Drop the paragraph about the spike's start and the 61/207 iterations; that tuning now matters little.
    - Replace the "Against a float64 solve…" sentence with the real-lines errors the new real-data test measures (print them once while writing it), next to Jacobi's figures from the spike note.

  Jacobi ("before") figures from `bench.py` at `e701f82`:

  | case | plan | solve | iterations |
  |---|---|---|---|
  | real lines, 0.2 m | 0.001 s | 0.004 s | 38 |
  | real lines, 0.05 m | 0.005 s | 0.410 s | 540 |
  | 50 m grid, 0.2 m | 0.004 s | 0.054 s | 41 |
  | 50 m grid, 0.1 m | 0.023 s | 0.892 s | 155 |
  | 50 m grid, 0.05 m | 0.132 s | 14.3 s | 492 |
  | 50 m, 40% covered, line skipped | 0.003 s | 0.157 s | 136 |

  (Load average about 2.6 while it ran, because other sessions were busy. Run the "after" figures under similar or lighter load, and say which in the docstring.)

- [ ] **Step 4: Run the full verification**

  Run all four **Verification commands**, including the qgis suite.
  Expected: core + pure pass with no new skips (1072 + the new tests). The qgis suite matches the baseline. ruff and mypy are clean.

- [ ] **Step 5: Commit and push**

  ```bash
  git add packages/nsgeo-core/src/nsgeo/slices/curvature.py packages/nsgeo-core/tests/test_slices_curvature.py
  git commit -m "perf(slices): minimum curvature solves with a multigrid preconditioner (#111)"
  git push origin nsgeo-multigrid
  ```

---

## After Task 2 (coordinator)

1. **Whole-branch review** (opus), with the spike note and this plan in hand.
2. **Deploy** to a new QGIS profile `ns_geo_multigrid`: a copy of `ns_geo`, linked with `.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo_multigrid`. Run a headless smoke load.
3. **Walkthrough** (a human gate, never passed silently) on an Artifact page with a `db` collection `results`. Every check is on the user's Grid 1 with minimum curvature:
   1. At 0.05 m, drag the depth and let go. The sharp slice replaces the kriging preview in under a second, against about 3 s on `ns_geo`.
   2. The slice looks the same as on `ns_geo` at the same depth, compared side by side.
   3. **Colour stretch…** clears within several seconds of choosing minimum curvature, where it took 25–35 s before.
   4. An export at 0.05 m finishes and reopens as before, and faster.
   5. 0.1 m and 0.2 m still feel as they did.
   6. Whole site with Grid 1 included still draws and refines.
4. **PR on the user's go.** It closes #111 and moves the README roadmap row to Done ("next release").
