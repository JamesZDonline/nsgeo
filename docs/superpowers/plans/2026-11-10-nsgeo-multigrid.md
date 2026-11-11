# Minimum Curvature Multigrid (#111) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make minimum curvature about 5× faster at a 0.05 m cell, giving the same answer, by preconditioning its conjugate gradients with a multigrid V-cycle.

**Architecture:** A new core module, `nsgeo.slices.multigrid`, builds a hierarchy from the plan's 13-point operator. The coarse operators are Galerkin products found by probing, the smoother is l1-Jacobi Chebyshev, and the coarsest level is solved by a dense pseudo-inverse. The hierarchy is built once per plan, like the operator, because it depends only on where the data is. `CurvaturePlan` holds it, and `_solve_into` calls one V-cycle per iteration where it now divides by the diagonal. Nothing outside `curvature.py` changes.

**Tech Stack:** Python ≥ 3.9 and numpy only (nsgeo-core), with pytest.

**Spec:** issue #111 (with its comment of 2026-11-06), and the description the user approved in chat on 2026-11-10. That description, the spike's measurements and the calls it settled are recorded in `docs/superpowers/notes/2026-11-10-multigrid-spike.md`; read it first. `docs/superpowers/notes/2026-11-10-multigrid-spike/mg2.py` is the reference prototype. Port it to project style rather than copying it: the prototype has no docstrings, no read-only arrays and no input checks.

## Global Constraints

- **numpy only** in `nsgeo-core`: no scipy.
- **Python 3.9 floor:** `from __future__ import annotations`; no `zip(strict=...)`, no `match`, no `X | Y` outside annotations.
- **Same answer.** The largest error inside the max distance against a float64 solve stays within milestone B's recorded figures: 6.2e-6 of the data range at 0.2 m, 4.8e-5 at 0.1 m and 4.0e-4 at 0.05 m. `test_min_curvature_matches_a_dense_solve` keeps `atol=1e-4 * np.ptp(v[pop])`.
- **The same stopping rule.** Stop when `‖r‖ ≤ CURVATURE_TOL · ‖b‖`, with `CURVATURE_TOL = 1e-6` and `CURVATURE_MAX_ITERATIONS = 10_000`. `should_stop` is asked before every iteration and raises `SolveStopped`. The start is `_start`. Arithmetic is float32 with float64 dot products (`_dot`). Solving about the data mean stays.
- **Plans are immutable and shared between threads.** Every array a plan or hierarchy holds is read-only. `solve` writes nothing it was given and allocates its own scratch, because the refine worker and the GUI thread solve on one plan at once.
- **No change outside `curvature.py` and the new module** except tests and docs. That excludes `nsgeo_qgis`, the panel, settings and saved files. `LIVE_SOLVE_BUDGET_MS`, `REFINE_REST_MS` and the kriging preview stay as they are.
- **Commits:** every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push each commit to `origin nsgeo-multigrid` as it is made.
- **Real survey files are never committed.**

## Before Task 1 (coordinator)

Done on 2026-11-10 in `.worktrees/nsgeo-multigrid` (branch `nsgeo-multigrid`, off main `e701f82`):
- both venvs are built;
- the top-level real files are symlinked into `packages/nsgeo-core/tests/data/local`. `with-dzg/` is left out on purpose, because of #141, which another session is fixing;
- core + pure baseline: 1072 passed, 5 skipped. QGIS: 1598 passed (13.6 min);
- ruff and mypy are clean.

## Verification commands (exactly these, from the worktree root)

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`. It takes about 11 minutes; while iterating, run single files.
- **lint:** `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- **types:** `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`

## Review Focus

These are the inputs most likely to hurt a user that the description does not spell out. Each is pinned by a test in the task named.

1. **Two threads solving on one plan at once.** This happens when the refine worker runs while an export solves on the GUI thread. Both must get exactly what they would get alone. A shared scratch buffer would corrupt both silently. Pinned in Task 1 (`test_two_threads_precondition_as_one`) and Task 2 (`test_two_threads_solve_one_plan_as_one`).
2. **A frame with nothing to solve**, because every cell within reach holds data. The hierarchy must build empty and the solve must return the data. Pinned in Task 1 (`test_no_unknowns_build_an_empty_hierarchy`). The existing `test_max_distance_zero_returns_the_data_alone` covers max distance 0.
3. **A frame one cell high:** a single line in a narrow frame, or a crop. Coarsening must halve only the long axis and stop. Pinned in Task 1 (`test_a_one_row_frame_coarsens_along_its_row`).
4. **Lines in both directions, and a skipped line.** Iterations must stay low when lines cross or leave a 1 m gap. Pinned in Task 2 (`test_iterations_barely_grow_as_cells_shrink` uses crossing lines; `test_partial_coverage_solves_in_few_iterations` is tightened).
5. **Memory at the largest frames.** At 4 million cells (`MAX_FRAME_CELLS`) the plan's coefficients already take 208 MB. The hierarchy must stay below that again. Pinned in Task 2 (`test_the_hierarchy_costs_less_memory_than_the_operator`).

---

### Task 1: The multigrid hierarchy

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/multigrid.py`
- Create: `packages/nsgeo-core/tests/test_slices_multigrid.py`

**Interfaces:**
- Consumes: nothing new. The tests build realistic operators with `plan_curvature(pop, cell, max_distance)` and take `plan.coefficients` with `active = plan.domain & ~plan.populated.reshape(plan.shape)`. They import `_OFFSETS` from `nsgeo.slices.curvature`, as the curvature tests already import `_start`.
- Produces (all in `nsgeo.slices.multigrid`):
  - `COARSEST_UNKNOWNS: int = 500`, `SMOOTHING_DEGREE: int = 2`, `SMOOTHING_RATIO: float = 16.0`, `PSEUDO_INVERSE_CUTOFF: float = 1e-6`.
  - `COARSE_OFFSETS: tuple[tuple[int, int], ...]`: all 25 `(dy, dx)` with `|dy|, |dx| ≤ 2`, in row-major order.
  - `coarse_shape(fine_shape: tuple[int, int]) -> tuple[int, int]`, returning `((ny + 1) // 2, (nx + 1) // 2)`.
  - `apply_stencil(offsets: Sequence[tuple[int, int]], coefficients: np.ndarray, x: np.ndarray) -> np.ndarray`. It computes `out[i, j] = Σ_k coefficients[k, i, j] · x[i + dy_k, j + dx_k]`, with `x` taken as 0 outside the array and offsets within ±2. The result is float32 `(ny, nx)`. It does not mask `x`, and it allocates its own padded copy and output.
  - `prolong(coarse: np.ndarray, fine_shape: tuple[int, int]) -> np.ndarray` and `restrict(fine: np.ndarray, shape: tuple[int, int]) -> np.ndarray` (`shape` is the coarse shape). They are unmasked, and `restrict` is the exact transpose of `prolong`.
  - `@dataclass(frozen=True, eq=False) class Level` with these fields:
    - `offsets: tuple[tuple[int, int], ...]`;
    - `coefficients: np.ndarray`, float32 `(len(offsets), ny, nx)`, whose rows off `active` are 0;
    - `active: np.ndarray`, bool `(ny, nx)`, this level's unknowns;
    - `scale: np.ndarray`, float32 `(ny, nx)`, 1 / the row's absolute sum on `active` and 0 elsewhere.
  - `@dataclass(frozen=True, eq=False) class Hierarchy` with these fields:
    - `levels: tuple[Level, ...]`;
    - `coarse_cells: np.ndarray`, intp, the flat indices of the last level's active cells;
    - `coarse_inverse: np.ndarray`, float32 `(n, n)`.

    It has two members:
    - `precondition(self, r: np.ndarray) -> np.ndarray`: one V-cycle from zero. It returns float32 `(ny, nx)`, zero off `levels[0].active`, does not write `r`, and allocates all of its own scratch.
    - `nbytes` (a property): every array the hierarchy holds except `levels[0].coefficients`.
  - `build_hierarchy(offsets: Sequence[tuple[int, int]], coefficients: np.ndarray, active: np.ndarray) -> Hierarchy`. It keeps `coefficients` itself as level 0's, with no copy, and marks it read-only. It copies `active`.

- [ ] **Step 1: Write the failing tests** in `test_slices_multigrid.py`.

  Helpers in the test file:
  - `operator(pop, cell, md)` returns `(plan.coefficients, active)` from `plan_curvature`.
  - `dense(level)` builds the level's matrix on its active cells by applying `apply_stencil` to unit vectors. Use it only on small grids.
  - `prolongation(fine_active, fine_shape)` is the dense `P'`. Its columns are `prolong(unit, fine_shape) * fine_active` for every coarse cell.
  - `lines(rows=(5, 15, 25, 35), ny=40, nx=60)` is the curvature tests' helper, imported from `tests.test_slices_curvature`.

  The tests (`monkeypatch.setattr(multigrid, "COARSEST_UNKNOWNS", n)` forces extra levels on small grids):
  - `test_restrict_is_the_transpose_of_prolong`. Fine shapes `(17, 9)`, `(16, 10)`, `(1, 7)`, `(2, 2)` and `(1, 1)`, with random float32 `c` and `f`: `abs(vdot(prolong(c, s), f) - vdot(c, restrict(f, coarse_shape(s)))) <= 1e-5 * norm(c) * norm(f)`.
  - `test_prolong_keeps_constants_and_lines`.
    - A constant 2.5 stays 2.5 everywhere (`atol=1e-6`).
    - For `c[I, :] = I`, the fine rows `1 ≤ i ≤ ny − 2` equal `(i + 0.5) / 2 − 0.5`; the same holds along X.
  - `test_the_coarse_operator_is_the_galerkin_product`. A `(11, 13)` frame at 0.1 m, `rng(5).random(...) < 0.2` plus row 6 full, max distance 0.3 and `COARSEST_UNKNOWNS = 1`. Assert at least 3 levels. For every `k ≥ 1`, `dense(levels[k])` equals `P'ᵀ · dense(levels[k−1]) · P'` within `1e-5 * abs(...).max()`.
  - `test_a_coarse_cell_is_active_exactly_when_it_reaches_a_fine_unknown`, on the same frame: `levels[k].active == (restrict(levels[k−1].active.astype(np.float32), shape) > 0)`.
  - `test_every_level_is_smoothed_within_its_bound`, on the same frame: for every level, the eigenvalues of `S^½ · dense · S^½` (with `S = diag(scale[active])`) lie in `(0, 1 + 1e-5]`.
  - `test_the_preconditioner_is_symmetric_and_positive`. `lines()` at 0.05 m, max distance 0.25 and `COARSEST_UNKNOWNS = 8`; assert at least 4 levels. For 10 seeds, with `r1` and `r2` random and masked to active:
    - `abs(vdot(M r1, r2) − vdot(r1, M r2)) ≤ 1e-5 · abs(vdot(M r1, r2))`;
    - `vdot(M r1, r1) > 0`;
    - `M r1` is exactly 0 off active;
    - `r1` is unchanged.
  - `test_one_level_inverts_exactly`. A `(12, 14)` frame at 0.1 m, `rng(5).random(...) < 0.2` and max distance 0.15, which gives 135 unknowns. Assert `len(levels) == 1`. `apply_stencil(..., M r)` equals `r` on active within `1e-4 * abs(r).max()`.
  - `test_no_unknowns_build_an_empty_hierarchy`. A frame that is all data, `(20, 20)` at 0.05 m with max distance 0.2:
    - one level;
    - `coarse_inverse.shape == (0, 0)` and `coarse_cells.size == 0`;
    - `precondition(zeros)` is all zeros.
  - `test_a_one_row_frame_coarsens_along_its_row`. Shape `(1, 3000)`, data every 7th cell, 0.05 m, max distance 0.2:
    - the level shapes are `(1, 3000)`, `(1, 1500)`, `(1, 750)`, `(1, 375)`;
    - the last level has at most 500 active cells;
    - `vdot(M r, r) > 0` for a random `r`.
  - `test_a_hierarchy_is_read_only`.
    - Every array in `levels` (`coefficients`, `active`, `scale`), `coarse_cells` and `coarse_inverse` has `flags.writeable == False`.
    - Writing to `levels[1].coefficients` raises `ValueError`.
    - Flipping the caller's `active` after the build leaves `levels[0].active` unchanged.
  - `test_nbytes_counts_every_array_but_the_fine_coefficients`: the explicit sum of the arrays named above, minus `levels[0].coefficients.nbytes`.
  - `test_two_threads_precondition_as_one`. A `(200, 200)` frame with a line every 10th row, 0.05 m and max distance 0.375. Four threads each precondition a different random `r` on one hierarchy; each result is `np.array_equal` to the serial result.

- [ ] **Step 2: Run them to see them fail**

  Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_multigrid.py -q -p no:cacheprovider`
  Expected: collection fails with `ModuleNotFoundError: No module named 'nsgeo.slices.multigrid'`.

- [ ] **Step 3: Implement `multigrid.py`.** The module docstring explains the method in the voice of `curvature.py`'s, and cites the spike note. The algorithms below are the ones the tests pin. `mg2.py` holds them as running code; its `Level.inverse_diagonal` is this plan's `scale`, and its `upper` field goes away (l1 makes it always 1). Every Task 1 assertion above was checked against `mg2.py` before this plan was handed over.

  **Prolongation along one axis** (cell-centred linear, clamped at the edges, then along Y and then X for 2-D):
  `fine[2I] = ¾·c[I] + ¼·c[I−1]` and `fine[2I+1] = ¾·c[I] + ¼·c[I+1]`, with `c[−1] := c[0]` and `c[n_c] := c[n_c−1]`. The last row is dropped when the fine length is odd.

  **A level** from `(offsets, coefficients, active)`: `scale = 1 / Σ_k |coefficients[k]|` on `active` and 0 elsewhere, in float32. That is l1-Jacobi: every eigenvalue of `scale · A` is at most 1, with no estimate needed (spike note, call 3).

  **The next coarser level** of level `L` with shape `s`, `cs = coarse_shape(s)` and `m = L.active` as float32. Bilinear `P'` spans fine cells `2I−1 … 2I+2` and `A` reaches ±2, so a coarse row reaches ±2 coarse cells. Colours 5 apart therefore never alias.
  ```
  for (py, px) in product(range(5), range(5)):
      e = zeros(cs); e[py::5, px::5] = 1
      y = restrict(apply_stencil(L.offsets, L.coefficients, prolong(e, s) * m) * m, cs)
      for k, (oy, ox) in enumerate(COARSE_OFFSETS):
          sy, sx = (py - oy) % 5, (px - ox) % 5
          coef[k, sy::5, sx::5] = y[sy::5, sx::5]
  symmetrise: coef[k][i] = ½ (coef[k][i] + coef[k′][i + o_k]) where o_k′ = −o_k (0 where i + o_k is outside)
  active_c = coef[centre] > 0;  coef *= active_c
  ```
  Probe in float32: a float64 copy of level 0 would take 416 MB at `MAX_FRAME_CELLS`.

  **Coarsening** reads `COARSEST_UNKNOWNS` at call time, so tests can monkeypatch it; it is not a default argument. Keep appending coarser levels while the last level has more active cells than that and its shape is not `(1, 1)`.

  **The coarsest level** is a dense float64 matrix over its active cells, in flat-index order and symmetrised as `½(M + Mᵀ)`. Take `eigh` and keep eigenvalues `> PSEUDO_INVERSE_CUTOFF × the largest`. Store the pseudo-inverse in float32. With no active cells the shape is `(0, 0)`.

  **`precondition(r)`** runs `cycle(0, r)`. Every vector a level handles is zero off its active cells.
  ```
  cycle(k, b):
      if k is the last level: x = 0; x.flat[coarse_cells] = coarse_inverse @ b.flat[coarse_cells]; return x
      x = chebyshev(L_k, b, x=None)
      r = b − A_k x
      e = cycle(k + 1, restrict(r · m_k, cs))
      x += prolong(e, s) · m_k
      return chebyshev(L_k, b, x)

  chebyshev(L, b, x):            # on scale·A, interval [lo, hi] = [1/SMOOTHING_RATIO, 1]
      θ = (hi + lo)/2;  δ = (hi − lo)/2;  σ = θ/δ;  ρ = 1/σ
      x = 0 and r = scale·b  if x is None,  else  r = scale·(b − A x)
      d = r / θ
      repeat SMOOTHING_DEGREE times:
          x += d;  r −= scale·(A d)
          ρ′ = 1/(2σ − ρ);  d = ρ′ρ·d + (2ρ′/δ)·r;  ρ = ρ′
      return x
  ```
  `Hierarchy.__post_init__` sets `writeable = False` on every array, as `CurvaturePlan.__post_init__` does, and says why in a comment.

- [ ] **Step 4: Run the tests and the lint and type checks**

  Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_multigrid.py -q -p no:cacheprovider`, then the **lint** and **types** commands.
  Expected: all pass, ruff and mypy clean.

- [ ] **Step 5: Commit and push**

  ```bash
  git add packages/nsgeo-core/src/nsgeo/slices/multigrid.py packages/nsgeo-core/tests/test_slices_multigrid.py
  git commit -m "feat(slices): multigrid hierarchy for minimum curvature (#111)"
  git push origin nsgeo-multigrid
  ```

---

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
