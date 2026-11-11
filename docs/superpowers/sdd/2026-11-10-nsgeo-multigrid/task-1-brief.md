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

