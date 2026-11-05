# Slice Interpolation, Milestone B (Minimum Curvature) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: run the failing test and see it fail before writing any production code.

**Goal:** Add **Minimum curvature** as the fourth interpolation method, in both scopes, the exports and the saved settings. The method is solved per slice near the data. While a slow solve would make a slider drag lag, the panel holds the last slice. Exports get progress and cancel.

**Architecture:**
- **Core solver.** `nsgeo/slices/curvature.py` turns "which cells hold data" into a `CurvaturePlan`: the solve area, plus a 13-point stencil built once.
  - `CurvaturePlan.apply(values)` solves one slice by Jacobi-preconditioned conjugate gradients.
  - `plan_fill(..., "min_curvature", ...)` returns a `CurvaturePlan`, so every caller of `plan_fill` and `finish_slice` keeps working unchanged.
- **Plugin engine.** `SliceEngine.finish()` keeps the last few solved slices, keyed by the values themselves, so a smoothing edit or a scrub back never solves twice. It also records how long the last solve took.
- **Plugin UI.**
  - When that time is over budget and the user is dragging the depth slider, the dock updates only the readout. It draws the full slice when the slider is released.
  - Both exports show a cancellable progress dialog.

**Tech Stack:** Python 3, numpy (core); PyQt via `qgis.PyQt` (plugin); pytest on two tiers: core and pure in `.venv`, QGIS in `.venv-qgis`.

**Spec:** `docs/superpowers/specs/2026-11-02-nsgeo-slice-interpolation-design.md`. This plan is milestone B of its §12; milestone A is merged (PR #110). §5.4 was changed on 2026-11-05 by the user: solve near the data, not over the whole frame. Read §5.4, §7, §9 and §10 before your task. Where the plan and the spec disagree, the plan wins, because it records the decisions below.

## Plan calls (decisions this plan makes where the spec leaves the builder a choice)

1. **The discrete problem is the thin-plate energy, with a tiny slope penalty.** Data cells are fixed, and the energy is minimised over the solve area `D`. Its interior Euler–Lagrange equation is the standard 13-point biharmonic, so this is §5.4's "Briggs-type biharmonic solve". Natural conditions at the edge of `D` come from the variational form itself. The energy:

   ```text
   E(u) =     Σ (u[i,j-1] − 2u[i,j] + u[i,j+1])²          over (i,j) with all three cells in D
          +   Σ (u[i-1,j] − 2u[i,j] + u[i+1,j])²          over (i,j) with all three cells in D
          + 2 Σ (u[i+1,j+1] − u[i+1,j] − u[i,j+1] + u[i,j])²   over 2×2 blocks wholly in D
          + ε Σ (u[i,j+1] − u[i,j])²  +  ε Σ (u[i+1,j] − u[i,j])²   over neighbour pairs in D
   ```

   with `ε = CURVATURE_EPS = 1e-6`, in cell units. `ε` is not tension: it is six orders below the curvature terms. It makes the answer unique when the data are collinear (one line, one cell), where a tilted plane would otherwise cost nothing. A plane still satisfies the interior equation exactly.
2. **The solve area (user, 2026-11-05).** `reach` is the data cells plus every cell within the max distance of one, exactly the cells IDW and kriging fill. `D` is `reach` grown by two 4-neighbour dilations, which is the 13-point stencil's footprint. The unknowns are `D & ~populated`. The output is finite on exactly `reach`.
3. **Solver.**
   - Matrix-free conjugate gradients in float32, with dot products accumulated in float64 and a Jacobi (diagonal) preconditioner.
   - The operator is 13 per-cell coefficient arrays, built once per plan.
   - Start from linear interpolation between the nearest data cells along each column (Y) and each row (X), averaged where both exist. Otherwise use the one side that exists, or the data mean.
   - Stop when `‖r‖ ≤ CURVATURE_TOL · ‖b‖`, with `CURVATURE_TOL = 1e-6`, or after `CURVATURE_MAX_ITERATIONS = 10_000`.
   - The spike measured this solver's error against a tight solve at 1e-5 of the data range at 0.2 m, 1e-4 at 0.1 m and 4e-4 at 0.05 m.
4. **Measured in the spike, recorded here as targets.** These are per slice, float32 13-point, with the linear-interpolation start and `tol 1e-6`:

   | Case | Time |
   |---|---|
   | Ten real lines, 25 × 100 cells at 0.2 m | about 5–8 ms |
   | 50 m synthetic, full coverage, 0.2 m | 40–60 ms |
   | 50 m synthetic, full coverage, 0.1 m | about 0.6 s |
   | 50 m synthetic, full coverage, 0.05 m | about 11 s |
   | 50 m, lines over 40% plus a skipped line, 0.2 m | about 0.2–0.65 s |

   **Escalate, rather than ship,** if Task 1 measures more than 0.25 s per slice at 0.2 m on the fully covered 50 m synthetic. A faster solver (multigrid) is filed as #111 (user, 2026-11-05: ship this solver and file the speed-up).
5. **Responsiveness (spec §7).**
   - **Drag budget.** `DRAG_SOLVE_BUDGET_MS = 50.0` is the slowest solve that still follows a drag live.
   - **Held drag.** When the last solve took longer and the slider is down, the panel holds the last drawn slice, shows the new window in the readout, and says to release. On release the full slice is drawn.
   - **Wheel, arrow keys and edits** solve at once, with a wait cursor when the solve is slow. The hold applies to minimum curvature only; IDW and kriging are unchanged.
6. **Shared stretch for minimum curvature** is measured over `limit_windows(z, thickness_levels)` (at most 12 windows, both ends kept), in both scopes. Whole site already does this (M12 Ruling 4). It is synchronous, with a wait cursor. That is the spec's "final limit from minimum-curvature slices" without solving every window.
7. **Solved-slice cache.**
   - `SliceEngine` keeps at most `SOLVED_SLICES_KEPT = 12` solved, unsmoothed slices. They are keyed by a BLAKE2b digest of the values' bytes, shape and dtype, and dropped whenever the plan they came from is replaced or dropped.
   - Twelve covers the shared-stretch windows, so a smoothing edit re-smooths instead of re-solving.
   - The cache counts in `weights_nbytes`, which is held memory shown in the status line. It does not count in the over-budget estimate, which keeps `WEIGHT_BYTES_PER_CELL` (96 B). Cost: the estimate can miss up to 48 B a cell at minimum curvature.
8. **Non-finite data values** follow `FillWeights`. A non-finite data cell shows NaN and is solved around: that slice is solved on a plan built for the finite data only. This is a slow path, never hit by binned data.
9. **Exports** take a `progress(done, total) -> bool` callback and raise `ExportCancelled` when it returns False.
   - The plugin drives it from a window-modal `QProgressDialog` with a 500 ms minimum duration.
   - A cancelled export, or a failed This grid export, removes the file it was writing, the same way the site export already does (Ruling T4-b). It adds no layer.
   - This benefits every method, not only minimum curvature.

## Global Constraints

- **The core stays numpy-only, with no Qt.**
  - `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` stay green.
  - Do not add scipy, even as an accelerator.
  - The plugin imports Qt only through `qgis.PyQt`.
- **Python 3.9 floor for the core:**
  - no `zip(..., strict=...)`;
  - no `match`;
  - no `X | Y` outside annotations;
  - no `dataclass(slots=..., kw_only=...)`.

  CI's 3.9 jobs caught exactly this on PR #110.
- **Slots guard their bodies.** Every slot connected to a Qt signal or timer guards its own body and reports through `_log` or `dock.error`. It never raises. Read the module docstrings of `slices_dock.py` and `site_scope.py` before touching either.
- **Seeds never write.** Opening a survey, switching scope or grid, seeding, restoring and clamping never mark the survey dirty and never write a remembered value.
- **Files stay readable both ways with 0.2.0.** `SCHEMA_VERSION` does not change. A record saved with `method: "min_curvature"` must load in this build and in 0.2.0, which ignores the method.
- **Exact values:**

  | Name | Value |
  |---|---|
  | Method key | `"min_curvature"` (appended to `METHODS`, as milestone A's plan reserved) |
  | Method label | `Minimum curvature` |
  | `CURVATURE_TOL` | `1e-6` |
  | `CURVATURE_EPS` | `1e-6` |
  | `CURVATURE_MAX_ITERATIONS` | `10_000` |
  | `SOLVE_MARGIN_CELLS` | `2` |
  | `DRAG_SOLVE_BUDGET_MS` | `50.0` |
  | `SOLVED_SLICES_KEPT` | `12` |
  | Distance comparison | inclusive, `≤ max_distance_m + DISTANCE_TOL_M` (the `interpolate.py` rule) |
  | Interpolation | never changes a data cell |
  | Smoothing | never fills a blank |

- **Comments and docstrings** follow the file they are in. They say why, and cite the spec as `(interpolation spec §5.4)`.
- **Shared-worktree safety.** Reviewers and any mutation testing never edit this worktree; they work on a scratch copy. Set `PYTHONDONTWRITEBYTECODE=1` for every test run.
- **Tool versions:** ruff 0.17.1 and mypy 2.4.0.
- **Commits:**
  - End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Push each commit to `origin nsgeo-slice-interpolation-b` as it is made.
- **`nsgeo-m14` is unmerged.** It now merges after milestone A and must update its test that imports `fill`. Do not touch that branch.

## Before Task 1 (coordinator)

Done on 2026-11-05 in `.worktrees/nsgeo-slice-interpolation-b`:
- both venvs built;
- real files copied into `packages/nsgeo-core/tests/data/local` (24 files);
- baseline core + pure: 937 passed, 3 skipped;
- QGIS: 1366 passed;
- ruff and mypy clean.

The spike lives in the session scratchpad (`mincurv/spike.py`). It is reference only and is not committed.

## Verification commands (exactly these, from the worktree root)

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh` (about 11 minutes; run single files while iterating)
- **lint:** `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- **types:** `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`

## Review Focus

These are the inputs most likely to hurt a user that the spec does not spell out. Each is pinned by a test in the task named.

1. **A grid whose lines cover only part of it.** The solve must stay near the data and not crawl through empty ground, which took 59 s a slice in the spike. Pinned by Task 1: `test_the_solve_area_is_the_reach_grown_by_two_cells` and `test_partial_coverage_solves_in_few_iterations`.
2. **One line, or one data cell.** There must be no crash. The surface continues flat across the line, not tilted. Pinned by Task 1: `test_one_line_continues_flat_across_it`.
3. **A fast drag released on a new window.** The map must end on the full minimum-curvature slice of the release window, not the last one drawn. Pinned by Task 2: `test_a_held_drag_draws_the_release_window_in_full`.
4. **A different preset or line set at the same window.** The solved-slice cache must never serve another slice's solution. Pinned by Task 2: `test_the_solved_slice_cache_never_serves_other_values`.
5. **A cancelled export.** It must leave no file, or the half-written file would read as valid zeros, and must add no layer. Pinned by Task 4: `test_a_cancelled_export_leaves_no_file_and_adds_no_layer` (both scopes).

---

### Task 1: Core minimum-curvature solver

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/curvature.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/interpolate.py`:
  - `METHODS` gains `"min_curvature"`.
  - `plan_fill` dispatches it. Import `plan_curvature` inside that branch, because a module-level import would be circular.
  - Add the `SliceFill` protocol.
  - Expose `reach_mask` so both modules share one reach rule.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/finish.py`: `finish_slice(values, weights: SliceFill, ...)`.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py`: export `CurvaturePlan`, `SliceFill` and `plan_curvature`, and add them to `__all__`.
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

  @dataclass(frozen=True, eq=False)
  class CurvaturePlan:
      shape: tuple[int, int]
      populated: np.ndarray     # (ny*nx,) bool
      reach: np.ndarray         # (ny*nx,) bool: finite in the output
      domain: np.ndarray        # (ny, nx) bool: the solve area D (plan call 2)
      coefficients: np.ndarray  # (13, ny, nx) float32: A's row at each unknown, by stencil offset; 0 elsewhere
      def solve(self, values: np.ndarray) -> tuple[np.ndarray, int]: ...  # (the slice, CG iterations run)
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

  With no target cells (max distance 0, or nothing in reach), `apply` skips the solve. `apply_at` is the full `apply`, indexed; M15 decides whether cuts use minimum curvature (spec §12).

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
  - `test_one_line_continues_flat_across_it` (Review Focus 2)
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
  - `test_plan_curvature_refuses_bad_input`
    - ValueError for a 1-D `populated`, `cell <= 0`, and a negative max distance.
    - ValueError from `apply` when `values.shape != shape`.

- [ ] **Step 3: Run them and see them fail.**
  - Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_interpolate.py packages/nsgeo-core/tests/test_slices_curvature.py -q -p no:cacheprovider`
  - Expected: FAIL. `min_curvature` is an unknown method, and `nsgeo.slices.curvature` does not exist.

- [ ] **Step 4: Implement `reach_mask`, `SliceFill`, `plan_curvature` and `CurvaturePlan`.**
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
      q = A·p                 # 13 multiply-adds over a 2-cell-padded copy of p, float32, preallocated buffers
      α = (r·z) / (p·q)       # dots in float64
      x += α·p ; r −= α·q ; z = r / diag ; β = (r·z)_new / (r·z)_old ; p = z + β·p
  ```

- [ ] **Step 5: Run the tests and see them pass**, then the whole core + pure command. Expected: everything passes, and the skip count is unchanged at 3.

- [ ] **Step 6: Measure and record** the plan call 4 timings in the module docstring. Record the 0.05 m case once; it takes about 11 s. **Escalate if the 0.2 m full-coverage case exceeds 0.25 s.**

- [ ] **Step 7: Commit and push.**
  ```bash
  git add packages/nsgeo-core
  git commit -m "feat(slices): minimum curvature, solved near the data (interpolation spec §5.4)"
  git push origin nsgeo-slice-interpolation-b
  ```

---

### Task 2: This grid — the method, held drags, the solved-slice cache, the stretch

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`:
  - `METHOD_LABELS` gains `"min_curvature": "Minimum curvature"`.
  - Add `DRAG_SOLVE_BUDGET_MS = 50.0` and `SOLVED_SLICES_KEPT = 12`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/finish_panel.py`: `_METHOD_TIP` gains the line *"Minimum curvature: the smoothest surface through the lines. It can overshoot beside a sharp change, and it is slower, so at a fine cell a dragged slider draws when you let go."*
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`: the solved-slice cache, `last_solve_ms` and `finish_is_slow`, and the shared stretch over `limit_windows` for minimum curvature.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`:
  - the held drag in `refresh_slice`;
  - a guarded `sliderReleased` slot;
  - a wait cursor around a slow solve and around an uncached minimum-curvature shared stretch.
- Test: `tests/pure/test_pure_slices_plan.py`, `tests/qgis/test_plugin_slices_engine.py`, `tests/qgis/test_plugin_slices_dock.py`, `tests/qgis/test_plugin_slice_export.py`.

**Interfaces:**
- Consumes: Task 1's `plan_fill(..., "min_curvature", ...)` → `CurvaturePlan`, and `METHODS`.
- Produces, on `SliceEngine`:
  ```python
  @property
  def last_solve_ms(self) -> float | None: ...   # the last minimum-curvature solve that ran; None after the plan is dropped
  def finish_is_slow(self, values: np.ndarray, coverage: np.ndarray, finish: SliceFinish) -> bool: ...
      # True when the method is min_curvature, these values are not in the solved-slice cache,
      # and last_solve_ms is None or > DRAG_SOLVE_BUDGET_MS; always False for other methods
  ```
  `finish()` keeps its signature.
- Produces, on `SlicesDock`: the held state `_held_window: SliceWindow | None`, cleared by every full draw.

- [ ] **Step 1: Write the failing tests.**
  - **Pure.** In `test_the_default_finish_closes_every_gap_between_binned_lines`, `test_the_default_finish_leaves_a_skipped_line_blank` and `test_the_weights_estimate_covers_building_them`, the parametrisation gains `"min_curvature"`.
    - For the estimate test, measure `plan_fill(...)` plus one `apply` together under `tracemalloc`.
    - The bound stays 1.5 × `WEIGHT_BYTES_PER_CELL`.
  - **Labels.** New pure test `test_method_labels_follow_methods`: `list(METHOD_LABELS) == list(METHODS)` and `METHOD_LABELS["min_curvature"] == "Minimum curvature"`. The panel's existing `test_the_panel_starts_at_the_defaults` then covers the combo.
  - **Engine:**
    - `test_minimum_curvature_finishes_through_the_engine`
      - On the synthetic fixture, `finish(values, coverage, SliceFinish(method="min_curvature"))` equals `plan_curvature(coverage > 0, frame.cell, settings.max_distance_m).apply(values)`, then smoothed with the same settings.
    - `test_a_repeated_solve_is_served_from_the_cache`
      - The second `finish` of the same values runs no solve: patch `CurvaturePlan.apply` with a counting wrapper, and expect 1 call.
      - A smoothing-only change also runs no solve.
    - `test_the_solved_slice_cache_never_serves_other_values` (Review Focus 4)
      - Two different value arrays at the same window and plan give two different results, each equal to a fresh solve.
    - `test_the_cache_keeps_at_most_twelve_and_drops_with_the_plan`
      - After 13 distinct solves, `len(engine._solved) == 12`.
      - After `set_source(...)` or a cell change, the cache is empty and `last_solve_ms is None`.
    - `test_finish_is_slow_follows_the_last_solve`
      - Set `engine._last_solve_ms` to 10 and then 80 (`DRAG_SOLVE_BUDGET_MS` is 50). This gives False then True for uncached values, False for cached values, and False for kriging.
    - `test_the_minimum_curvature_stretch_is_measured_over_twelve_windows_at_most`
      - With `thickness_levels = 1` on an axis of more than 12 levels, `shared_limit` finishes exactly `len(limit_windows(z, 1))` slices: count `finish` calls.
      - The result equals `limit_over_slices` over those windows' finished slices.
  - **Dock:**
    - `test_a_held_drag_draws_the_release_window_in_full` (Review Focus 3)
      - With `min_curvature` selected and `engine._last_solve_ms` forced to 500, call `slice_slider.setSliderDown(True)`.
      - Move the slider over three values. `current_values()` is unchanged, the readout names the last value's window, and `status_label` starts with `Release the slider to draw`.
      - Then call `setSliderDown(False)` and emit `sliderReleased`. `current_values()` equals the engine's `finish` of the release window, and `_held_window is None`.
    - `test_a_quick_solve_follows_the_drag_live`
      - Same, with `_last_solve_ms` 5: each move redraws.
    - `test_kriging_never_holds`
      - Same as the held case, with kriging: each move redraws.
    - `test_a_wheel_step_solves_at_once`
      - Slider not down, `_last_solve_ms` 500: `step_slice(1)` draws the new window.
  - **Saved records** (`test_plugin_slice_export.py`): parametrise `test_view_settings_round_trip_the_finish` and `test_a_record_from_this_build_still_loads_in_0_2_0` over every key in `METHODS`.

- [ ] **Step 2: Run them and see them fail.**
  - Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py -q -p no:cacheprovider`
  - Then run the three QGIS files with the QGIS command, naming the files.
  - Expected: FAIL. The label is missing, and the names `last_solve_ms`, `finish_is_slow` and `_held_window` don't exist.

- [ ] **Step 3: Implement.**
  - **The cache.** `SliceEngine._solved` is an `OrderedDict[bytes, np.ndarray]`. `_last_solve_ms` is set only when `apply` actually ran. Both are emptied wherever `self._weights` becomes None or `_weights_for` builds a new plan, and kept where the weights are kept.
  - **The digest.** `hashlib.blake2b(values.tobytes(), digest_size=16)` updated with `str(values.shape)` and `str(values.dtype)`.
  - **The stretch.** `shared_limit` picks `limit_windows(z, thickness_levels)` when `finish_settings(finish).method == "min_curvature"`, and its existing windows otherwise.
  - **The dock's held branch.** Inside `refresh_slice`, after `slice_at`, when `finish_is_slow(...)` and `slice_slider.isSliderDown()`:
    - set `_held_window = window`;
    - call `_update_readout(window)`;
    - set the status label to `Release the slider to draw: minimum curvature takes {ms:.0f} ms a slice here.`;
    - return without touching `_values` or `_window` and without emitting.
  - **Otherwise,** a slow finish runs inside `busy_cursor()`. Every full draw sets `_held_window = None`.
  - **The engine's minimum-curvature path.** It is `smooth(solved, ...)`, where `solved` is the cached or freshly applied plan output. That is equivalent to `finish_slice`, and it lets the cache hold the unsmoothed slice. The time of `apply` alone goes into `_last_solve_ms`.
  - **Release.** Connect `slice_slider.sliderReleased` to a guarded slot, `_on_slider_released`. In This grid it calls `refresh_slice()` when `_held_window` is set. Task 3 adds the Whole site branch.
  - **The stretch's wait cursor.** `display_limit` wraps an uncached shared-limit computation in `busy_cursor()` when the method is `min_curvature`.

- [ ] **Step 4: Run the tests and see them pass**, then the full core + pure command and the full QGIS command. Expected: all pass, at 1366 + the new QGIS tests.

- [ ] **Step 5: Commit and push.**
  ```bash
  git commit -m "feat(slices): minimum curvature in This grid — held drags, solved-slice cache, twelve-window stretch"
  git push origin nsgeo-slice-interpolation-b
  ```

---

### Task 3: Whole site with minimum curvature

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`: `last_tick_ms` (unsmoothed; the last full tick's time).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`:
  - the held drag in `refresh_slice`;
  - the released-slider redraw;
  - a wait cursor around a slow tick and an uncached minimum-curvature shared limit.
- Test: `tests/qgis/test_plugin_site_engine.py`, `tests/qgis/test_plugin_site_scope.py`.

**Interfaces:**
- Consumes: Task 2's `SliceEngine.finish` cache and `finish_is_slow`, `DRAG_SOLVE_BUDGET_MS`, and the dock's `sliderReleased` slot.
- Produces:
  - `SiteEngine.last_tick_ms: float | None`, set by every `slice_at` and None after `clear`.
  - `SiteScope.held_window: SliceWindow | None`.

- [ ] **Step 1: Write the failing tests.**
  - **`test_site_gains_commute_with_every_method`** gains `"min_curvature"`. For it, compare with `rtol=1e-4, atol=1e-4 * np.nanmax(np.abs(after))`.
  - **`test_a_held_site_drag_draws_the_release_window_in_full`**
    - With `min_curvature`, `site_engine._last_tick_ms` forced to 500 and the slider down, moving the slider leaves `scope.slice` unchanged.
    - `dock.readout` shows the new window's text (from `readout(z, window, thickness, step)`).
    - After release and the file's own `settle(dock)`, `scope.slice.array` equals a fresh `slice_at` of the release window, and `scope.held_window is None`.
  - **`test_a_quick_site_tick_follows_the_drag_live`**, at `_last_tick_ms` 5.
  - **`test_the_site_stretch_with_minimum_curvature_uses_twelve_windows`**
    - `shared_limit` with `min_curvature` calls each engine's `finish` at most `len(limit_windows(...))` times per grid, counted.
    - This pins the existing Ruling 4 path for the new method.
  - **`test_a_site_with_minimum_curvature_exports_and_reopens`**
    - Export the three-grid fixture with `min_curvature`.
    - The file has `NSGEO_SITE_INTERPOLATION == "min_curvature"` and every band is finite on data cells.

- [ ] **Step 2: Run them and see them fail.** Run `test_plugin_site_engine.py` and `test_plugin_site_scope.py` with the QGIS command. Expected: FAIL. `last_tick_ms` and `held_window` don't exist, and the commute test fails for `min_curvature` until Task 2's engine path is in.

- [ ] **Step 3: Implement.**
  - **The held branch.** In `site_scope.refresh_slice`, after computing `window` and before `engine.slice_at`, hold when all of these are true:
    - the method is `min_curvature`;
    - `dock.slice_slider.isSliderDown()`;
    - `engine.last_tick_ms` is not None and exceeds `DRAG_SOLVE_BUDGET_MS`.

    Holding sets `held_window`, the readout and the status text (`Release the slider to draw: …`, as in Task 2), then returns without emitting.
  - **Release.** In Whole site, the dock's `_on_slider_released` calls `self._site.schedule_refresh()` when `self._site.held_window` is set. A full tick clears `held_window`.
  - **A slow tick** runs inside `busy_cursor()` when the method is `min_curvature` and `last_tick_ms > DRAG_SOLVE_BUDGET_MS`.
  - **The stretch's wait cursor.** `display_limit` wraps an uncached shared limit in `busy_cursor()` for `min_curvature`.

- [ ] **Step 4: Run the tests and see them pass**, then the full QGIS command.

- [ ] **Step 5: Commit and push.**
  ```bash
  git commit -m "feat(site): minimum curvature in Whole site — held drags and the twelve-window stretch"
  git push origin nsgeo-slice-interpolation-b
  ```

---

### Task 4: Exports with progress and cancel; the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`: `ExportCancelled(Exception)`, and an `export_slices(..., progress=None)` parameter.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`: an `export_site(..., progress=None)` parameter.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
  - one `_export_progress(title: str, total: int)` helper that returns `(callback, dialog)`;
  - both exports use it;
  - cancel and This grid failure remove the partial file (plan call 9).
- Modify: `docs/guide/getting-started.md`, step 4, Method bullet: add **Minimum curvature**.
- Modify: `packages/nsgeo-qgis/tests/qgis/conftest.py` only if the modal guard needs to know about `QProgressDialog`. It is shown, not `exec()`'d, so it should not.
- Test: `tests/qgis/test_plugin_slice_export.py`, `tests/qgis/test_plugin_site_scope.py` (site export tests live there), and `tests/qgis/test_plugin_slice_export_dialogs.py`.

**Interfaces:**
- Produces:
  ```python
  class ExportCancelled(Exception): ...   # slice_export.py; site_export imports it

  def export_slices(engine, path, thickness_levels, step_levels, velocity, finish, *,
                    writer=None, progress: Callable[[int, int], bool] | None = None) -> ExportPlan
  def export_site(site_engine, path, thickness_levels, step_levels, *, ..., writer=None, left_out=None,
                  progress: Callable[[int, int], bool] | None = None) -> SiteExportPlan
  ```
  - `progress(done, total)` is called before each band, with `done` = bands written so far, and once more as `(total, total)` at the end.
  - A False return raises `ExportCancelled` before the next band is computed.

- [ ] **Step 1: Write the failing tests.**
  - **`test_export_reports_progress_for_every_band`**
    - A recording callback sees `(0, n), (1, n), …, (n, n)` for an n-band This grid export, and likewise for the site.
  - **`test_a_cancelled_export_leaves_no_file_and_adds_no_layer`** (Review Focus 5; This grid and Whole site)
    - Patch `plugin._export_progress` to return a callback that returns False at `done == 1`.
    - The target file does not exist afterwards, no layer is added, and the message bar says `export cancelled` at Info.
    - A file the dialog chose to replace, and that the export never reached, is left untouched (the existing mtime rule).
  - **`test_a_failed_slice_export_leaves_no_file`**
    - A writer that raises after the first band: no file, and the existing Critical message.
  - **`test_a_minimum_curvature_export_records_its_method`**
    - The This grid export with `min_curvature` has `NSGEO_INTERPOLATION == "min_curvature"`, and every band equals the engine's `finish` of that band's window after `to_north_up`.
  - **`test_the_progress_dialog_is_cancellable_and_window_modal`**
    - `_export_progress("Export GeoTIFF", 5)` returns a dialog with `windowModality() == Qt.WindowModality.WindowModal`, `minimumDuration() == 500` and a maximum of 5.
    - Calling `dialog.cancel()` makes the callback return False.

- [ ] **Step 2: Run them and see them fail.** Run the three files with the QGIS command. Expected: FAIL. The `progress` parameter, `ExportCancelled` and `_export_progress` don't exist.

- [ ] **Step 3: Implement.**
  - **The core of the exporters.** The `progress` call sits in each exporter's band generator, so the writers stay unchanged.
  - **The plugin.** It:
    - catches `ExportCancelled` separately from other exceptions;
    - removes the partial file by the site export's mtime rule, now shared by both exports;
    - reports `export cancelled` at Info;
    - always closes the dialog, in a `finally`.
  - **The guide paragraph**, in the step 4 Method bullet, after the IDW sentence: *"Pick **Minimum curvature** for the smoothest surface through the lines, the method Surfer users often know. It can overshoot a little beside a strong contrast, which shows as a faint ring of the opposite sign between lines. It is solved for each slice, so it is slower. At a fine cell, a dragged depth slider draws the slice when you let go, and an export shows its progress and can be cancelled."*

- [ ] **Step 4: Run the tests and see them pass**, then all four verification commands. Expected:
  - core + pure: passes, with 3 skipped;
  - QGIS: passes;
  - lint and types clean.

- [ ] **Step 5: Commit and push.**
  ```bash
  git commit -m "feat(export): progress and cancel for both exports; minimum curvature in the guide"
  git push origin nsgeo-slice-interpolation-b
  ```

---

## After Task 4 (coordinator)

These are the manual checkpoints from spec §10. Track them and report them; never pass them silently.

1. **Build and walkthrough.** Deploy to a fresh QGIS profile, then hold the walkthrough on the user's real grids (Sunnyside) as an Artifact with a results db. Cover:
   - minimum curvature at defaults: no holes, and a skipped line blank;
   - the overshoot ring, judged acceptable or not (tension is the first follow-up if not);
   - live dragging at 0.2 m;
   - the held drag at a fine cell, drawn in full on release;
   - Whole site;
   - an export with progress and a cancel;
   - a saved cube.
2. **Surfer comparison (spec §10.2).** The user compares nsgeo's kriging and minimum curvature, at defaults, against their Surfer grids. The question is "same ballpark". This gate is required for B.
3. **File the deferred follow-ups** from review. Note that the faster solver (multigrid) is already filed as #111.
