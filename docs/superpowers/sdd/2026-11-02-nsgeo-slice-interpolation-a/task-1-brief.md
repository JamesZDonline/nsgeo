### Task 1: Core interpolation weights

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/interpolate.py`
- Create: `packages/nsgeo-core/tests/real_lines.py`. Move these out of `tests/test_slices_site.py`, unchanged in behaviour:
  - `DATA`, `FILES`, `needs_real_files`
  - `CELL`, `SPACING`
  - `_AXIS` → `AXIS`, `_WINDOWS` → `WINDOWS`
  - `_radargrams` → `radargrams`, `_lines` → `prepared_lines`, `_binned` → `binned`
- Modify: `packages/nsgeo-core/tests/test_slices_site.py` to import those names from `tests.real_lines`.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` to export `METHODS`, `FillWeights` and `plan_fill`, and add them to `__all__`.
- Test: `packages/nsgeo-core/tests/test_slices_interpolate.py`

**Interfaces:**
- Produces, in `nsgeo/slices/interpolate.py`:
  ```python
  METHODS: tuple[str, ...] = ("none", "idw", "kriging")
  NEIGHBOURS_PER_QUADRANT: int = 3
  DISTANCE_TOL_M: float = 1e-9

  @dataclass(frozen=True, eq=False)
  class FillWeights:
      shape: tuple[int, int]      # (ny, nx)
      populated: np.ndarray       # (ny*nx,) bool: cells that hold data
      targets: np.ndarray         # (m,) intp, ascending flat ids of empty cells to fill
      sources: np.ndarray         # (m, 4*NEIGHBOURS_PER_QUADRANT) int32 flat ids, -1 = empty slot
      weights: np.ndarray         # same shape, float32, 0.0 in empty slots
      def apply(self, values: np.ndarray) -> np.ndarray: ...            # (ny, nx) -> (ny, nx) float32
      def apply_at(self, values: np.ndarray, cells: np.ndarray) -> np.ndarray: ...  # (k,) flat ids -> (k,) float32
      @property
      def nbytes(self) -> int: ...

  def plan_fill(
      populated: np.ndarray, cell: float, method: str, max_distance_m: float, search_radius_m: float
  ) -> FillWeights: ...
  ```
- **What `apply` returns, cell by cell:**

  | Cell | Value |
  |---|---|
  | Data cell | its own value |
  | Target | `Σ wᵢvᵢ / Σ wᵢ` over its finite sources; NaN if it has none |
  | Every other cell | NaN |

  `apply_at(values, cells)` equals `apply(values).ravel()[cells]`, without building the whole slice. It is the API M15's cuts will use (spec §12).
- Produces, in `tests/real_lines.py`: the moved names above.

- [ ] **Step 1: Move the real-data helpers.** Move the helpers into `tests/real_lines.py` and update `test_slices_site.py`'s imports. Run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_site.py -q -p no:cacheprovider`. Expected: the same pass and skip counts as at baseline.

- [ ] **Step 2: Write the failing tests** in `test_slices_interpolate.py`. Unless a test says otherwise, use the geometry these tests call "lines":
  - cell 0.05 m, `ny = 40`, `nx = 60`;
  - populated rows 5, 15, 25 and 35, every column (lines along X, 0.5 m apart);
  - `max_distance_m = 0.25`, `search_radius_m = 1.0`;
  - parametrize the tests below over `"idw"` and `"kriging"` where they say so.

  **Behaviour tests:**
  - `test_none_keeps_data_cells_and_blanks_the_rest`
    - `plan_fill(..., "none", 0.25, 1.0)` has `targets.size == 0`.
    - `apply(v)` equals `v` on populated cells and is NaN elsewhere.
  - `test_data_cells_come_back_exactly` (idw, kriging)
    - `out[pop] == v.astype(np.float32)[pop]`, exactly (`np.array_equal`), for random `v`.
  - `test_a_constant_field_is_reproduced` (idw, kriging)
    - Every finite output is `3.5` within `rtol=1e-6`.
  - `test_interpolation_is_affine_equivariant` (idw, kriging)
    - `apply(-2.5 * v + 7)` is allclose to `-2.5 * apply(v) + 7` (`rtol=1e-5, atol=1e-5`), with identical NaN masks.
  - `test_cells_beyond_max_distance_are_blank_and_within_it_are_finite` (idw, kriging)
    - One data cell at the centre of 21 × 21, cell 0.1 m, max 0.35 m, search 0.7 m.
    - A cell is finite exactly when `hypot(dy, dx) * 0.1 <= 0.35 + 1e-9`.
  - `test_the_limit_is_inclusive_so_the_midpoint_between_lines_fills` (idw, kriging)
    - Odd case: cell 0.125 m, data rows 0 and 4, max 0.25 m. Row 2 is finite.
    - Even case: cell 0.1 m, data rows 0 and 5, max 0.25 m. Rows 1–4 are all finite.
  - `test_no_holes_between_lines_at_nominal_spacing` (idw, kriging)
    - "lines": every cell from row 5 to row 35 is finite.
  - `test_a_line_that_wanders_leaves_a_stripe_that_a_larger_max_distance_closes` (idw, kriging)
    - Move the row-25 line to row 27 (0.2 × spacing).
    - At max 0.25 m, row 21 is all NaN.
    - At max 0.30 m (0.6 × spacing) and search 1.0 m, rows 5–35 are all finite.
  - `test_a_skipped_line_leaves_a_blank_stripe` (idw, kriging)
    - Drop the row-25 line.
    - At max 0.25 m, row 25 is NaN.
    - At max 0.5 m and search 1.0 m, it is finite.
  - `test_every_filled_cell_between_two_lines_draws_on_both` (idw, kriging)
    - For every target in rows 6–14, the source rows (`sources // nx`, ignoring −1) include both 5 and 15.
  - `test_no_step_from_neighbourhood_switching` (idw, kriging)
    - "lines" geometry with `nx = 200`. The field is `f(x, y) = sin(x / 1.5) + 0.4 * y` at cell centres, in metres.
    - For every pair of finite neighbours along each axis: `|Δ| <= 2.5 * hypot(1 / 1.5, 0.4) * 0.05 + 1e-6`.
    - **Do not loosen this bound to pass.** Report instead.
  - `test_one_line_fills_both_sides_out_to_max_distance_and_no_further` (idw, kriging; Review Focus 1)
    - One populated row, 10, in 21 × 30 at cell 0.05 m, max 0.25 m: rows 5–15 are finite and all others NaN.
    - A single populated cell gives a finite disc of radius 0.25 m and no exception.
  - `test_a_cross_hatched_grid_fills_without_holes` (idw, kriging)
    - Rows 5, 15, 25, 35 and columns 5, 15, …, 55 populated: everything inside rows and columns 5–55 is finite.

  **Method-specific tests:**
  - `test_idw_halfway_between_two_cells_is_their_mean`
    - Data at row 0, columns 0 and 4, cell 0.1 m, max 0.2 m: column 2 equals the mean of the two values.
  - `test_kriging_weights_sum_to_one`
    - On "lines", every row of `weights` sums to 1 within `1e-5`.
  - `test_kriging_matches_a_direct_solve_for_one_cell`
    - Use `np.random.default_rng(3)` with 15% of a 30 × 30 grid populated, cell 0.1 m, max 0.3 m, search 0.6 m.
    - For one target, rebuild the ordinary-kriging system in the test from that row's sources: `γ(h) = h`, unknowns `[w; μ]`.
    - Solve it with `np.linalg.solve`. The weights match `FillWeights.weights` for that row within `1e-5`.

  **Robustness and API tests:**
  - `test_a_nan_data_value_does_not_poison_targets_with_other_sources` (idw, kriging)
    - Set one data cell's value to NaN.
    - That cell is NaN in the output. Every target that lists it among its finite sources is still finite.
  - `test_apply_at_matches_apply` (idw, kriging)
    - For 200 random flat ids covering data, target and blank cells: `apply_at(v, ids) == apply(v).ravel()[ids]`, NaN-aware.
  - `test_nbytes_counts_the_tables`
    - `nbytes == populated.nbytes + targets.nbytes + sources.nbytes + weights.nbytes`.
  - `test_plan_fill_refuses_bad_input`
    - `ValueError` for each of: an unknown method; a negative `max_distance_m`; `search_radius_m < max_distance_m`; a 1-D `populated`; `cell <= 0`.
    - `ValueError` from `apply` when `values.shape != shape`.

  **Real data:**
  - `test_real_lines_keep_their_data_and_fill_every_gap` (`@needs_real_files`, idw, kriging)
    - Ten real lines through `real_lines.prepared_lines(range(10), lambda local: local)` in `CubeFrame((0.0, 0.0), 0.0, CELL, 100, 25, "EPSG:32633")`.
    - Each of `WINDOWS` binned with `binned`.
    - `plan_fill(coverage > 0, CELL, method, 0.5 * SPACING, 2 * SPACING)`.
    - Data cells come back unchanged, and every cell between the first and last line's rows is finite.

- [ ] **Step 3: Run them and see them fail.** Run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_interpolate.py -q -p no:cacheprovider`. Expected: FAIL at import, because `nsgeo.slices.interpolate` does not exist.

- [ ] **Step 4: Implement `plan_fill` and `FillWeights`** in `interpolate.py`. The module docstring says what the module is for (spec §5) and why the weights depend only on where data is, not on its values.

  The algorithm, which the signature and tests don't determine:

  ```text
  1. Reach. Take offsets (dy, dx) with 0 < hypot(dy, dx)·cell <= max_distance_m + DISTANCE_TOL_M.
     reach = populated OR'd with populated shifted by each offset (out of frame reads False).
     targets = flatnonzero(reach & ~populated)                       # ascending

  2. Neighbourhood. Take offsets with 0 < hypot·cell <= search_radius_m + DISTANCE_TOL_M,
     sorted by distance (stable), each tagged q = floor((atan2(dy, dx) mod 2π) / (π/2)).
     Walk them nearest first. A target accepts the data cell at target + offset into quadrant q
     while it holds fewer than NEIGHBOURS_PER_QUADRANT there; slots are q*K .. q*K+K-1.
     Work on an active index set, and every 32 offsets drop the targets whose four quadrants are full.
     Without this, a 0.1 m cell on a 50 m grid takes 1.1 s instead of 0.4 s (spike).

  3a. idw: w = d**-2 over a row's filled slots, normalised to sum 1.

  3b. kriging: for each row, with source positions p_i relative to the target, in metres:
        [[G, 1], [1ᵀ, 0]] [w; μ] = [g0; 1],   G_ij = |p_i − p_j|,   g0_i = |p_i|
      An empty slot j gets G row and column 0, G_jj = 1, g0_j = 0, and 0 in the ones row and column,
      so w_j = 0. Solve once per distinct relative-offset pattern: np.unique over a void view of the
      int offset rows, with return_inverse. Regular line geometry repeats a few dozen patterns.
      Chunk at most 50 000 systems per np.linalg.solve.
  ```

  Store sources as int32 and weights as float32.

- [ ] **Step 5: Run the tests and see them pass.** Run the Step 3 command. Expected: PASS, and the real-data test runs rather than skips.

- [ ] **Step 6: Measure, and record the numbers.**
  - Time `plan_fill` (idw and kriging) and one `apply` with a throwaway script in the scratch directory. Do not commit the script. Cases:
    - the real-lines frame;
    - a 50 m × 50 m synthetic grid with lines every 0.5 m along X, at cells 0.2, 0.1 and 0.05 m.
  - Put a short table of the medians in the module docstring and in your report.
  - **Escalate** (stop and report as BLOCKED) if kriging at 0.2 m on the 50 m grid takes more than 0.5 s.

- [ ] **Step 7: Run the full core + pure suite, ruff and mypy, then commit.**

  ```bash
  git add packages/nsgeo-core/src/nsgeo/slices/interpolate.py packages/nsgeo-core/src/nsgeo/slices/__init__.py \
          packages/nsgeo-core/tests/test_slices_interpolate.py packages/nsgeo-core/tests/real_lines.py \
          packages/nsgeo-core/tests/test_slices_site.py
  git commit -m "feat(slices): interpolation weights — none, IDW and kriging with a max distance (interpolation spec §5)"
  git push
  ```

---

