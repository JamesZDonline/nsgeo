### Task 1: Core minimum-curvature solver

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/curvature.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/interpolate.py`:
  - `METHODS` gains `"min_curvature"`.
  - `plan_fill` dispatches it. Import `plan_curvature` inside that branch, because a module-level import would be circular.
  - Add the `SliceFill` protocol.
  - Expose `reach_mask` so both modules share one reach rule.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/finish.py`: `finish_slice(values, weights: SliceFill, ...)`.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py`: export `CurvaturePlan`, `SliceFill`, `SolveStopped` and `plan_curvature`, and add them to `__all__`.
- Test: `packages/nsgeo-core/tests/test_slices_interpolate.py`, extended.
- Test: `packages/nsgeo-core/tests/test_slices_curvature.py`, new, for the method-specific tests.

**Interfaces:**
- Produces, in `interpolate.py`:
  ```python
  METHODS: tuple[str, ...] = ("none", "idw", "kriging", "min_curvature")

  class SliceFill(Protocol):          # typing.Protocol; FillWeights and CurvaturePlan both satisfy it
      @property
      def shape(self) -> tuple[int, int]: ...   # properties, not attributes: mypy reads a frozen
      @property                                 # dataclass's fields as read-only
      def populated(self) -> np.ndarray: ...    # (ny*nx,) bool
      def apply(self, values: np.ndarray) -> np.ndarray: ...
      def apply_at(self, values: np.ndarray, cells: np.ndarray) -> np.ndarray: ...
      @property
      def nbytes(self) -> int: ...

  def reach_mask(populated: np.ndarray, cell: float, max_distance_m: float) -> np.ndarray: ...
      # (ny, nx) bool: populated, or within max_distance_m (+ DISTANCE_TOL_M) of a populated cell
  def plan_fill(...) -> FillWeights | CurvaturePlan   # signature otherwise unchanged; CurvaturePlan
                                                      # imported under TYPE_CHECKING for the annotation
  ```
  `FillWeights`' own targets must equal `reach_mask(...) & ~populated`. Refactor `plan_fill`'s step 1 onto `reach_mask`, so the two can never drift.
- Produces, in `curvature.py`:
  ```python
  CURVATURE_TOL: float = 1e-6
  CURVATURE_EPS: float = 1e-6
  CURVATURE_MAX_ITERATIONS: int = 10_000
  SOLVE_MARGIN_CELLS: int = 2

  class SolveStopped(Exception): ...   # raised by solve() when should_stop() returns True

  @dataclass(frozen=True, eq=False)
  class CurvaturePlan:
      shape: tuple[int, int]
      populated: np.ndarray     # (ny*nx,) bool
      reach: np.ndarray         # (ny*nx,) bool: finite in the output
      domain: np.ndarray        # (ny, nx) bool: the solve area D (plan call 2)
      coefficients: np.ndarray  # (13, ny, nx) float32: A's row at each unknown, by stencil offset; 0 elsewhere
      def solve(
          self, values: np.ndarray, should_stop: Callable[[], bool] | None = None
      ) -> tuple[np.ndarray, int]: ...                                  # (the slice, CG iterations run)
      def apply(self, values: np.ndarray) -> np.ndarray: ...            # solve(values)[0]: (ny, nx) float32
      def apply_at(self, values: np.ndarray, cells: np.ndarray) -> np.ndarray: ...  # apply(values).ravel()[cells]
      @property
      def nbytes(self) -> int: ...  # sum of the array fields' nbytes

  def plan_curvature(populated: np.ndarray, cell: float, max_distance_m: float) -> CurvaturePlan: ...
  ```
  `apply` returns, cell by cell:

  | Cell | Value |
  |---|---|
  | Data cell | its own value, exactly (float32 of the input) |
  | Other cell in `reach` | the solved value |
  | Everything else | NaN |

  With no target cells (max distance 0, or nothing in reach), `solve` skips the iterations and returns 0 iterations. `apply_at` is the full `apply`, indexed; M15 decides whether cuts use minimum curvature (spec §12). `solve` never mutates the plan or `values`: Task 2 runs it on a worker thread.

- [ ] **Step 1: Extend the shared tests in `test_slices_interpolate.py`.**
  - Add `ALL = pytest.mark.parametrize("method", ["idw", "kriging", "min_curvature"])`.
  - Switch these tests from `BOTH` to `ALL`:
    - `test_data_cells_come_back_exactly`
    - `test_a_constant_field_is_reproduced`
    - `test_cells_beyond_max_distance_are_blank_and_within_it_are_finite`
    - `test_the_limit_is_inclusive_so_the_midpoint_between_lines_fills`
    - `test_no_holes_between_lines_at_nominal_spacing`
    - `test_a_line_that_wanders_leaves_a_stripe_that_a_larger_max_distance_closes`
    - `test_a_skipped_line_leaves_a_blank_stripe`
    - `test_binned_lines_fill_at_three_quarters_of_a_spacing`
    - `test_half_a_spacing_stripes_binned_lines`
    - `test_a_skipped_binned_line_leaves_a_blank_stripe_at_three_quarters_of_a_spacing`
    - `test_no_step_from_neighbourhood_switching` (**do not loosen its bound to pass; report instead**)
    - `test_one_line_fills_both_sides_out_to_max_distance_and_no_further`
    - `test_a_cross_hatched_grid_fills_without_holes`
    - `test_all_blank_input_gives_all_blank_output`
    - `test_apply_at_matches_apply`
    - `test_real_lines_keep_their_data_and_fill_every_gap`
  - `test_interpolation_is_affine_equivariant` goes to `ALL`. For `min_curvature` only, compare with `rtol=0, atol=1e-4 * 2.5 * np.ptp(v[pop])`, with identical NaN masks.
  - `test_methods_are_in_order` asserts the four-key tuple.
  - `test_plan_fill_refuses_bad_input` adds `plan_fill(pop, 0.05, "min_curvature", -0.1, 1.0)` to its ValueError cases.
  - Leave the tests that read `sources` or `weights` on `BOTH`.

- [ ] **Step 2: Write the method-specific tests** in `test_slices_curvature.py`. "lines" means the `test_slices_interpolate.py` geometry: cell 0.05 m, 40 × 60, rows 5/15/25/35 populated, max 0.25 m.
  - `test_min_curvature_reproduces_a_plane`
    - Data `0.3 + 0.8·x − 0.5·y`, in metres at cell centres, on "lines".
    - Every finite output is within `1e-4 · ptp(data)` of the plane.
  - `test_min_curvature_matches_a_dense_solve`
    - Two cases: 12 × 14 cells, cell 0.1 m, `np.random.default_rng(5)` with 20% populated, and max distance 0.15 m and 0.5 m (a partial area and the whole frame).
    - In the test, build `D` from `reach_mask` and two 4-neighbour dilations. Assemble each energy term of plan call 1 as a row of a dense matrix `B`, with weight `√2` on the cross terms and `√ε` on the slope terms. Solve `min ‖B u‖` with the data fixed, by `np.linalg.lstsq` on the unknown columns.
    - `apply` matches it on every reach cell within `1e-4 · ptp(data)`.
  - `test_min_curvature_blanks_exactly_where_idw_does`
    - On "lines", "lines" with row 25 moved to 27, and "lines" with row 25 dropped, each at max 0.25 and 0.30 m.
    - `np.isnan(curvature.apply(v)) == np.isnan(idw.apply(v))`.
  - `test_the_solve_area_is_the_reach_grown_by_two_cells` (Review Focus 1)
    - `plan.domain` equals `reach_mask(...)` dilated twice, 4-neighbour.
    - `plan.coefficients` is 0 outside `domain & ~populated`.
  - `test_partial_coverage_solves_in_few_iterations` (Review Focus 1)
    - A 250 × 250 frame at 0.2 m. Lines 0.5 m apart along X cover only the lower 40%; drop one line.
    - `plan.solve(v)[1]`, the iteration count, is ≤ 400. The whole-frame solve took 14,593.
  - `test_one_line_continues_flat_across_it`
    - One populated row 10 in 21 × 30 at 0.05 m, with values `sin(x)` along the row and max 0.25 m.
    - Every finite cell in column `j` is within `1e-4` of row 10's value in column `j`.
    - A single populated cell gives that value on its whole disc.
  - `test_a_nan_data_value_does_not_poison_the_cells_around_it`
    - On "lines", set one data cell's value to NaN.
    - That cell is NaN.
    - Every other reach cell within the max distance of another, finite data cell is finite.
    - For a constant field with that NaN, every finite output equals the constant within `1e-5`.
  - `test_max_distance_zero_returns_the_data_alone`
    - `plan_curvature(pop, 0.05, 0.0).apply(v)` equals `v` on data cells and is NaN elsewhere.
  - `test_a_solve_stops_when_asked`
    - On "lines" with a field that needs more than 5 iterations, `should_stop` returns True on its 4th call.
    - `solve` raises `SolveStopped`, and `should_stop` was called exactly 4 times.
    - A `should_stop` that always returns False gives the same slice as `should_stop=None`.
    - `values` is unchanged afterwards (compare against a copy).
  - `test_plan_curvature_refuses_bad_input`
    - ValueError for a 1-D `populated`, `cell <= 0`, and a negative max distance.
    - ValueError from `apply` when `values.shape != shape`.

- [ ] **Step 3: Run them and see them fail.**
  - Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_interpolate.py packages/nsgeo-core/tests/test_slices_curvature.py -q -p no:cacheprovider`
  - Expected: FAIL. `min_curvature` is an unknown method, and `nsgeo.slices.curvature` does not exist.

- [ ] **Step 4: Implement `reach_mask`, `SliceFill`, `SolveStopped`, `plan_curvature` and `CurvaturePlan`.**
  - Build the 13 coefficient arrays by accumulating each energy term's contribution in vectorised passes, one per term kind. Do not probe them through an operator: probing cost 0.1 s at 0.2 m and 3 s at 0.05 m in the spike.
  - Zero the rows of data cells and of cells outside `D`.
  - The right-hand side is `b = −(A · d)` on the unknowns, where `d` is the data on data cells and 0 elsewhere.
  - The module docstring:
    - says what the method is for (spec §5.4);
    - records the user's near-the-data decision;
    - carries a timing table like `interpolate.py`'s, re-measured on the plan call 4 cases.

  The solve, which the tests don't fully determine:

  ```text
  x = start (plan call 3) on the unknowns; r = b − A·x; z = r / diag(A); p = z
  repeat until ‖r‖ ≤ CURVATURE_TOL·‖b‖ (‖b‖ = 0 → x = 0 is exact) or CURVATURE_MAX_ITERATIONS:
      if should_stop is not None and should_stop(): raise SolveStopped
      q = A·p                 # 13 multiply-adds over a 2-cell-padded copy of p, float32, preallocated buffers
      α = (r·z) / (p·q)       # dots in float64
      x += α·p ; r −= α·q ; z = r / diag ; β = (r·z)_new / (r·z)_old ; p = z + β·p
  ```

- [ ] **Step 5: Run the tests and see them pass**, then the whole core + pure command. Expected: everything passes, and the skip count is unchanged at 3.

- [ ] **Step 6: Measure and record** the plan call 4 timings in the module docstring. Record the 0.05 m case once; it takes about 10 s. **Escalate if the 0.2 m full-coverage case exceeds 0.25 s.**

- [ ] **Step 7: Commit and push.**
  ```bash
  git add packages/nsgeo-core
  git commit -m "feat(slices): minimum curvature, solved near the data (interpolation spec §5.4)"
  git push origin nsgeo-slice-interpolation-b
  ```

---

