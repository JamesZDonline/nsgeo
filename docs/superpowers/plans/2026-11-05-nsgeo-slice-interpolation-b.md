# Slice Interpolation, Milestone B (Minimum Curvature) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: run the failing test and see it fail before writing any production code.

**Goal:** Add **Minimum curvature** as the fourth interpolation method, in both scopes, the exports and the saved settings. It is solved per slice, near the data. When a solve is too slow to follow the depth live, the panel shows a kriging preview while the depth moves and refines it with minimum curvature in the background once the depth rests. Exports get progress and cancel.

**Architecture:**
- **Core solver.** `nsgeo/slices/curvature.py` turns "which cells hold data" into a `CurvaturePlan`: the solve area, plus a 13-point stencil built once.
  - `CurvaturePlan.solve(values, should_stop=...)` solves one slice by Jacobi-preconditioned conjugate gradients, and stops early when asked.
  - `plan_fill(..., "min_curvature", ...)` returns a `CurvaturePlan`, so every caller of `plan_fill` and `finish_slice` keeps working unchanged.
- **Background worker.** `nsgeo_qgis/refine.py` holds one worker thread that runs a list of solves in order and hands each result back on the GUI thread.
- **Plugin engine.** `SliceEngine` builds the curvature plan and a kriging preview together.
  - It keeps the last few solved slices, keyed by the values themselves, so a smoothing edit or a scrub back never solves twice.
  - It records how long the last solve took.
  - It hands out `PendingSolve` jobs for the worker. A job lands in the cache only if the engine still holds the plan the job was made from.
- **Plugin UI.** When the last solve was over budget, This grid and Whole site draw the preview and start a rest timer. When the timer fires, the worker solves the current slice first, then any stretch windows still unsolved. Each result redraws only if it is still what the panel shows. Both exports show a cancellable progress dialog.

**Tech Stack:** Python 3, numpy (core); PyQt via `qgis.PyQt` and `concurrent.futures` (plugin); pytest on two tiers: core and pure in `.venv`, QGIS in `.venv-qgis`.

**Spec:** `docs/superpowers/specs/2026-11-02-nsgeo-slice-interpolation-design.md`. This plan is milestone B of its §12; milestone A is merged (PR #110). The user changed two things on 2026-11-05:
- §5.4: solve near the data, not over the whole frame;
- §7: bridge slow solves with a kriging preview, refined in the background when the depth rests.

Read §5.4, §7, §9 and §10 before your task. Where the plan and the spec disagree, the plan wins, because it records the decisions below.

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
   - `should_stop()`, when given, is called once before every iteration. If it returns True, the solve raises `SolveStopped`. One iteration takes about 25 ms at 0.05 m on a 50 m grid, so that bounds how long a cancel takes.
   - The spike measured this solver's error against a tight solve at 1e-5 of the data range at 0.2 m, 1e-4 at 0.1 m and 4e-4 at 0.05 m.
4. **Measured in the spike, recorded here as targets.** These are per slice, float32 13-point, with the linear-interpolation start and `tol 1e-6`:

   | Case | Minimum curvature | Kriging preview |
   |---|---|---|
   | Ten real lines, 25 × 100 cells at 0.2 m | about 5–8 ms | |
   | 50 m synthetic, full coverage, 0.2 m | 40–60 ms | |
   | 50 m synthetic, full coverage, 0.1 m | about 0.55 s | 12 ms, after 0.6 s and 21 MB of setup |
   | 50 m synthetic, full coverage, 0.05 m | about 10 s | 62 ms, after 5.9 s and 95 MB of setup |
   | 50 m, lines over 40% plus a skipped line, 0.2 m | about 0.2–0.65 s | |

   - In the filled gaps the kriging preview was within 0.5% of the data range of the final result in 99% of cells.
   - **Escalate, rather than ship,** if Task 1 measures more than 0.25 s per slice at 0.2 m on the fully covered 50 m synthetic.
   - A faster solver (multigrid) is filed as #111 (user, 2026-11-05: ship this solver and file the speed-up).
5. **Responsiveness: preview, rest, refine (spec §7, user 2026-11-05).**
   - **Live budget.** `LIVE_SOLVE_BUDGET_MS = 50.0`. A slice is **slow** when the method is minimum curvature, its values are not in the solved-slice cache, and the last solve took longer than the budget or no solve has run on this plan yet.
   - **Fast slices** are solved at once on the GUI thread, exactly as kriging is applied today.
   - **A slow slice** is drawn as its **preview**: kriging at the same max distance, search radius and smoothing, so its blanks are the same. Drawing it cancels any running refine and starts the rest timer.
   - **The rest timer.** `REFINE_REST_MS = 300`, single-shot, restarted by every preview draw. Dragging, the wheel, arrow keys and edits all go through the same path, so there is no special case for any of them.
   - **When the depth rests,** the worker solves the current slice, then any stretch windows still unsolved (call 7). Each result lands in the cache as it finishes, so a cancel loses at most the solve in progress.
   - **A landed result redraws** only when it is the slice the panel is showing. The redraw is then a cache hit, so it is drawn at once.
   - **Draws that leave the worker alone.** A full draw, which is a cache hit or a fast solve, does not cancel a running list. Only a preview draw (a new slow window) or a draw by another method cancels it.
   - **Status line.** It shows `PREVIEW_STATUS` while a preview is drawn and `REFINING_STATUS` while the worker runs. It shows today's text otherwise.
   - **The first draw on a new plan** is always a preview (no solve has been timed yet). The curvature plan and the kriging preview are built together, once, under the wait cursor, as milestone A builds kriging today.
6. **The background worker** is one thread from `concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="nsgeo-refine")`. It is not a `QgsTask`, for three reasons:
   - A refine is pure numpy on arrays it owns: no Qt, no file reads, no session. None of the `QgsTask` hazards in `slices_engine.py`'s docstring apply, and a task should not flash in QGIS's task list at every pause.
   - One worker means two solves never run at once.
   - Results reach the GUI thread through a `QTimer` that polls a queue every `REFINE_POLL_MS = 20` ms. Nothing Qt is touched off the GUI thread, and no cross-thread signal is used.

   numpy releases the GIL inside its array operations, so the panel keeps running during a solve. Task 2 pins that with a test.

   The worker touches only its job:
   - a private copy of the values;
   - the plan, which is frozen and never mutated;
   - the job's own result fields.

   The engine's cache is written only on the GUI thread, by `PendingSolve.land()`. Plugin unload shuts the worker down, which cancels and joins it, before any engine is disposed.
7. **Shared stretch for minimum curvature** is measured over `limit_windows(z, thickness_levels)` (at most 12 windows, both ends kept), in both scopes. Whole site already does this (M12 Ruling 4).
   - Until every one of those windows is in the solved-slice cache, the stretch is **provisional**: the same measurement over the windows' kriging previews.
   - The unsolved windows are queued behind the current slice when the depth rests.
   - When the worker finishes its list, the provisional stretch is dropped and the slice is redrawn with the final one. That is the spec's "final limit from minimum-curvature slices".
8. **Solved-slice cache.**
   - `SliceEngine` keeps at most `SOLVED_SLICES_KEPT = 16` solved, unsmoothed slices: the 12 stretch windows plus a few recently viewed.
   - Entries are keyed by a BLAKE2b digest of the values' bytes, shape and dtype. They are dropped whenever the plan they came from is replaced or dropped.
   - Least recently used goes first.
9. **Memory.**
   - Under minimum curvature, `weights_nbytes` (held memory, in the status line) counts the curvature plan, the kriging preview and the cache.
   - The over-budget estimate keeps `WEIGHT_BYTES_PER_CELL` (96 B), because it also drives residency, and that must not move with the method.
   - Cost: under minimum curvature the estimate's interpolation figure can be low by about 120 B a cell (plan about 55 B, cache up to 64 B; the preview is the 96 B the estimate already counts). That is about 0.5 GB at the 4-million-cell cap. The status line names the real figure.
10. **Non-finite data values** follow `FillWeights`. A non-finite data cell shows NaN and is solved around: that slice is solved on a plan built for the finite data only. This is a slow path, never hit by binned data.
11. **Exports** take a `progress(done, total) -> bool` callback and raise `ExportCancelled` when it returns False.
    - The plugin drives it from a window-modal `QProgressDialog` with a 500 ms minimum duration.
    - Every band is the full result (`engine.finish`), solved on the GUI thread; an export never writes a preview.
    - The export cancels the worker first, so the two do not compete.
    - Cancel takes effect between bands, so at most one band's solve late: about 10 s at 0.05 m on a 50 m grid.
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
- **Slots guard their bodies.** Every slot connected to a Qt signal or timer guards its own body and reports through `_log` or `dock.error`. It never raises. Read the module docstrings of `slices_dock.py`, `site_scope.py` and `slices_engine.py` before touching them.
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
  | `LIVE_SOLVE_BUDGET_MS` | `50.0` |
  | `REFINE_REST_MS` | `300` |
  | `REFINE_POLL_MS` | `20` |
  | `SOLVED_SLICES_KEPT` | `16` |
  | `PREVIEW_METHOD` | `"kriging"` |
  | Worker thread name prefix | `"nsgeo-refine"` |
  | `PREVIEW_STATUS` | `Kriging preview: minimum curvature follows when the depth rests.` |
  | `REFINING_STATUS` | `Refining with minimum curvature ({done} of {total})…` |
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

The spike lives in the session scratchpad (`mincurv/spike.py`, `mincurv/preview.py`). It is reference only and is not committed.

## Verification commands (exactly these, from the worktree root)

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh` (about 11 minutes; run single files while iterating)
- **lint:** `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- **types:** `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`

## Review Focus

These are the inputs most likely to hurt a user that the spec does not spell out. Each is pinned by a test in the task named.

1. **A grid whose lines cover only part of it.** The solve must stay near the data and not crawl through empty ground, which took 59 s a slice in the spike. Pinned by Task 1: `test_the_solve_area_is_the_reach_grown_by_two_cells` and `test_partial_coverage_solves_in_few_iterations`.
2. **A refine that finishes after the user has moved on.** It must never draw over the newer window, in either scope. Pinned by Task 3: `test_a_refine_for_a_window_left_behind_never_draws`, and Task 4: `test_a_site_refine_for_a_window_left_behind_never_draws`.
3. **Closing QGIS, or changing the source, mid-refine.** The worker must stop and join, with no crash and no stale result landing. Pinned by Task 3: `test_unloading_mid_refine_stops_the_worker` and `test_a_solve_for_a_dropped_plan_does_not_land`.
4. **A different preset or line set at the same window.** The solved-slice cache must never serve another slice's solution. Pinned by Task 3: `test_the_solved_slice_cache_never_serves_other_values`.
5. **A cancelled export.** It must leave no file, or the half-written file would read as valid zeros, and must add no layer. Pinned by Task 5: `test_a_cancelled_export_leaves_no_file_and_adds_no_layer` (both scopes).

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

### Task 2: The background worker

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/refine.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`: add `REFINE_POLL_MS = 20`.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_refine.py`, new. It is in the QGIS tier because `QTimer` needs a Qt event loop.

**Interfaces:**
- Consumes: Task 1's `SolveStopped`, and `plan_curvature` for the responsiveness test.
- Produces, in `refine.py`:
  ```python
  class RefineJob(Protocol):
      def run(self, should_stop: Callable[[], bool]) -> None: ...   # worker thread; keeps its own result

  class Refiner:
      def __init__(self, parent: QObject) -> None: ...   # the poll QTimer is parented to `parent`
      def start(
          self,
          jobs: Sequence[RefineJob],
          on_landed: Callable[[RefineJob], None],
          on_error: Callable[[str], None],
      ) -> None: ...
          # cancels whatever is running, then runs `jobs` in order on the worker thread;
          # on_landed(job) runs on the GUI thread after each job finishes, in order
      def cancel(self) -> None: ...    # the running job stops at its next iteration; nothing more of that list lands
      @property
      def busy(self) -> bool: ...      # a started list has jobs that have not landed; False before the LAST job's on_landed runs
      def shutdown(self) -> None: ...  # cancel, then join the worker; safe to call twice
  ```

- [ ] **Step 1: Write the failing tests** in `test_plugin_refine.py`. They use small fake jobs: a `threading.Event`-driven job, a job that records `threading.get_ident()`, a job that raises, and a job that loops until `should_stop()`. Add one helper, `_pump_until(predicate, timeout_s)`, which calls `QCoreApplication.processEvents()` until the predicate holds and fails the test at the timeout.
  - `test_jobs_land_in_order_on_the_gui_thread`
    - Three jobs land in list order.
    - Each `run` ran on a thread whose name starts with `nsgeo-refine`.
    - Each `on_landed` ran on `threading.main_thread()`.
  - `test_busy_is_false_when_the_last_job_lands`
    - `busy` is True right after `start`.
    - Inside the last `on_landed`, `busy` is already False.
  - `test_cancel_stops_the_running_job_and_drops_the_rest`
    - A list of a looping job then a recording job.
    - After `cancel()`, the looping job returns within 1 s, `busy` is False, nothing lands, and the recording job never ran.
  - `test_a_new_start_supersedes_the_old_one`
    - Start list A with a job that blocks on an Event, then start list B. Release A's Event.
    - Only B's jobs land.
  - `test_only_one_job_runs_at_a_time`
    - Five rapid `start` calls of jobs that increment and decrement a shared counter under a lock, recording the maximum.
    - The maximum is 1.
  - `test_a_job_error_is_reported_not_raised`
    - A list of a raising job then a recording job.
    - `on_error` receives the exception's message, the recording job never runs, and `busy` ends False.
    - No `sys.excepthook` or `sys.unraisablehook` call is recorded.
  - `test_a_raising_on_landed_is_contained`
    - `on_landed` raises. The next job still lands.
    - The error goes to `_log`, not to `sys.excepthook`.
  - `test_shutdown_joins_the_worker`
    - Shut down while a looping job runs.
    - Afterwards, within 2 s, no thread named `nsgeo-refine*` is alive, and a second `shutdown()` is harmless.
  - `test_the_gui_thread_keeps_running_during_a_solve`
    - Run a real solve as a job: `plan_curvature` on a 500 × 500 synthetic at 0.1 m (lines 0.5 m apart), taking about 0.5 s.
    - A 10 ms `QTimer` on the GUI thread fires at least 10 times before the job lands.
    - **If this is flaky, report it. Do not loosen it silently.**

- [ ] **Step 2: Run it and see it fail.** Run `test_plugin_refine.py` with the QGIS command. Expected: FAIL, because `nsgeo_qgis.refine` does not exist.

- [ ] **Step 3: Implement `Refiner`** (plan call 6).
  - The module docstring says why this is a thread and not a `QgsTask`, and that the worker touches only its job.
  - The poll slot guards its body. `on_landed` and `on_error` exceptions go to `_log` (`from nsgeo_qgis.log import log as _log`, as `slice_layer.py` does).

  The parts the tests don't fully determine:

  ```text
  start(jobs, on_landed, on_error):
      cancel(); generation += 1; stop = threading.Event(); remaining = len(jobs)
      executor.submit(run_list, generation, jobs, stop)   # one worker: a cancelled list ends its iteration first
      poll.start(REFINE_POLL_MS)
  run_list (worker):
      for job in jobs:
          if stop.is_set(): return
          try: job.run(stop.is_set)
          except SolveStopped: return
          except Exception as exc: done.put((generation, None, str(exc))); return
          done.put((generation, job, None))
  poll (GUI thread):
      drain `done` (a queue.SimpleQueue); skip entries from an older generation
      error → remaining = 0, on_error(message);  job → remaining -= 1, then on_landed(job)
      stop the timer once nothing is running and the queue is empty
  cancel(): stop.set(); generation += 1; remaining = 0
  shutdown(): cancel(); executor.shutdown(wait=True, cancel_futures=True); poll.stop()
  ```

- [ ] **Step 4: Run the tests and see them pass**, then the full QGIS command and lint. Expected: all pass.

- [ ] **Step 5: Commit and push.**
  ```bash
  git commit -m "feat(slices): a background worker for minimum-curvature solves (interpolation spec §7)"
  git push origin nsgeo-slice-interpolation-b
  ```

---

### Task 3: This grid — the method, the preview, refining, the cache, the stretch

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`:
  - `METHOD_LABELS` gains `"min_curvature": "Minimum curvature"`.
  - Add `LIVE_SOLVE_BUDGET_MS`, `REFINE_REST_MS`, `SOLVED_SLICES_KEPT`, `PREVIEW_METHOD`, `PREVIEW_STATUS` and `REFINING_STATUS`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/finish_panel.py`: `_METHOD_TIP` gains the line *"Minimum curvature: the smoothest surface through the lines. It can overshoot beside a sharp change. It is slower, so at a fine cell you see kriging while the depth moves and minimum curvature once it rests."*
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`:
  - `PendingSolve`;
  - the plan and preview built together;
  - the solved-slice cache;
  - `last_solve_ms`, `finish_is_slow`, `preview`, `pending_solve` and `stretch_solves`;
  - `shared_limit(..., preview=)`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`:
  - `self.refiner = Refiner(self)`, the rest timer, and the provisional state in `refresh_slice`;
  - `_on_rest` and `_on_landed`;
  - the provisional stretch in `display_limit`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: `unload()` calls `self.slices_dock.refiner.shutdown()` before `dispose_site()`.
- Test: `tests/pure/test_pure_slices_plan.py`, `tests/qgis/test_plugin_slices_engine.py`, `tests/qgis/test_plugin_slices_dock.py`, `tests/qgis/test_plugin_slice_export.py`.

**Interfaces:**
- Consumes: Task 1's `plan_fill(..., "min_curvature", ...)` → `CurvaturePlan`, `SolveStopped` and `METHODS`; Task 2's `Refiner`.
- Produces, in `slices_engine.py`:
  ```python
  class PendingSolve:                 # a RefineJob
      key: bytes                      # the solved-slice cache key of its values
      solved: np.ndarray | None       # set by run(): the unsmoothed slice
      ms: float | None                # set by run(): the solve's own time
      def run(self, should_stop: Callable[[], bool]) -> None: ...   # worker thread
      def land(self) -> bool: ...     # GUI thread: into the engine's cache (and last_solve_ms) only if that
                                      # engine still holds the plan this job was made from; whether it did
  ```
- Produces, on `SliceEngine`:
  ```python
  @property
  def last_solve_ms(self) -> float | None: ...   # the last solve that ran on this plan; None after the plan is dropped
  def finish_is_slow(self, values, coverage, finish: SliceFinish) -> bool: ...   # plan call 5's "slow"; False for other methods
  def preview(self, values, coverage, finish: SliceFinish) -> np.ndarray: ...
      # min_curvature: kriging at the same distances and smoothing; any other method: finish(...)
  def pending_solve(self, values, coverage, finish: SliceFinish) -> PendingSolve | None: ...
      # None unless min_curvature and these values are uncached
  def stretch_solves(self, thickness_levels: int, finish: SliceFinish) -> list[PendingSolve]: ...
      # the uncached limit_windows; [] for other methods
  def shared_limit(self, thickness_levels, clip, finish, *, preview: bool = False) -> float: ...
      # min_curvature: over limit_windows, through finish() or, with preview=True, preview()
  ```
  - `finish()` keeps its signature and always returns the full result.
  - For `min_curvature`, `weights_cached(finish)` means the plan and the preview are both built.
  - `weights_nbytes` counts plan + preview + cache (plan call 9).
- Produces, on `SlicesDock`: `refiner: Refiner`, and `provisional: bool` (what is drawn is a preview).

- [ ] **Step 1: Write the failing tests.**
  - **Pure.** In `test_the_default_finish_closes_every_gap_between_binned_lines`, `test_the_default_finish_leaves_a_skipped_line_blank` and `test_the_weights_estimate_covers_building_them`, the parametrisation gains `"min_curvature"`.
    - For the estimate test, measure `plan_fill(...)` plus one `apply` together under `tracemalloc`.
    - The bound stays 1.5 × `WEIGHT_BYTES_PER_CELL`.
  - **Labels.** New pure test `test_method_labels_follow_methods`: `list(METHOD_LABELS) == list(METHODS)` and `METHOD_LABELS["min_curvature"] == "Minimum curvature"`. The panel's existing `test_the_panel_starts_at_the_defaults` then covers the combo.
  - **Engine.** "mc" is `SliceFinish(method="min_curvature")` on the synthetic fixture.
    - `test_minimum_curvature_finishes_through_the_engine`
      - `finish(values, coverage, mc)` equals `plan_curvature(coverage > 0, frame.cell, settings.max_distance_m).apply(values)`, then smoothed with the same settings.
    - `test_the_preview_is_kriging_at_the_same_max_distance`
      - `preview(v, cov, mc)` equals `finish(v, cov, SliceFinish(method="kriging"))` at the same distances and smoothing.
      - Its NaN mask equals that of `finish(v, cov, mc)`.
    - `test_a_repeated_solve_is_served_from_the_cache`
      - The second `finish` of the same values runs no solve: patch `CurvaturePlan.solve` with a counting wrapper, and expect 1 call.
      - A smoothing-only change also runs no solve.
    - `test_the_solved_slice_cache_never_serves_other_values` (Review Focus 4)
      - Two different value arrays at the same window and plan give two different results, each equal to a fresh solve.
    - `test_the_cache_keeps_at_most_sixteen_and_drops_with_the_plan`
      - After 17 distinct solves, `len(engine._solved) == 16`, and the first values solve again.
      - After `set_source(...)` or a cell change, the cache is empty and `last_solve_ms is None`.
    - `test_finish_is_slow_follows_the_last_solve`
      - Setting `engine._last_solve_ms` gives these results for uncached values:

        | `_last_solve_ms` | `finish_is_slow` |
        |---|---|
        | None | True |
        | 10 | False |
        | 80 | True |

      - Cached values give False, and kriging gives False.
    - `test_a_pending_solve_lands_in_the_cache`
      - Run `job = pending_solve(...)`, then `job.run(lambda: False)`; `job.land()` is True.
      - A following `finish` of those values runs no solve, and `last_solve_ms == job.ms`.
      - `pending_solve` of the same values is now None, and it is None for kriging.
    - `test_a_solve_for_a_dropped_plan_does_not_land` (Review Focus 3)
      - Make a job, then call `set_source(...)` or change the cell, then run the job.
      - `job.land()` is False, and the new plan's cache stays empty.
    - `test_the_minimum_curvature_stretch_is_measured_over_twelve_windows_at_most`
      - With `thickness_levels = 1` on an axis of more than 12 levels, `stretch_solves` returns `len(limit_windows(z, 1))` jobs.
      - After running and landing them, `shared_limit` runs no solve and equals `limit_over_slices` over those windows' finished slices.
      - `shared_limit(..., preview=True)` equals `limit_over_slices` over their previews.
    - `test_weights_nbytes_counts_the_plan_the_preview_and_the_cache`
      - After one solve it equals `plan.nbytes + preview.nbytes + solved.nbytes`.
  - **Dock.** Each dock test selects `min_curvature`, forces `engine._last_solve_ms` as named, and sets the stretch combo to `this slice` unless it says otherwise. `_wait_for_refine(dock)` pumps events for `REFINE_REST_MS` plus margin, then until `not dock.refiner.busy`, failing after 30 s.
    - `test_a_slow_slice_shows_the_preview_then_refines`
      - Parametrised over a slider move and `step_slice(1)`, at 500 ms.
      - Right after the move, `current_values()` equals `engine.preview(...)` of the new window, `dock.provisional` is True, and `status_label.text() == PREVIEW_STATUS`.
      - After `_wait_for_refine`, `current_values()` equals `engine.finish(...)` of that window, `dock.provisional` is False, and the status is the normal text.
    - `test_the_refine_waits_for_the_depth_to_rest`
      - At 500 ms, three moves 100 ms apart.
      - After each move, `dock.refiner.busy` is False and the rest timer is active.
      - The refiner starts only after the last move plus `REFINE_REST_MS`.
    - `test_a_quick_solve_draws_minimum_curvature_at_once`
      - At 5 ms, a move draws `engine.finish(...)` at once, the rest timer is not active, and the refiner never starts.
    - `test_kriging_never_previews`
      - Kriging: a move draws `finish`, the rest timer is not active, and the refiner never starts.
    - `test_a_refine_for_a_window_left_behind_never_draws` (Review Focus 2)
      - At 500 ms, rest on window A. Patch `engine.pending_solve` so A's job runs the real solve only after a `threading.Event` the test sets, and ignores `should_stop`, so it lands late on purpose.
      - Move to window B, then set the Event, then `_wait_for_refine`.
      - `dock.current_window() == B`, and `current_values()` equals B's full solve.
      - At no point after the move did `current_values()` equal A's solve. Record every array from `slice_changed` to check this.
    - `test_the_shared_stretch_is_provisional_until_its_windows_are_solved`
      - Stretch combo `shared`, at 500 ms.
      - After a move, `display_limit()` equals `engine.shared_limit(n, clip, mc, preview=True)`.
      - After `_wait_for_refine`, it equals `engine.shared_limit(n, clip, mc)`, `engine.stretch_solves(n, mc) == []`, and the slice was redrawn.
    - `test_a_landed_slice_does_not_cancel_the_stretch_solves`
      - Stretch `shared`. After the current slice lands and redraws, `dock.refiner.busy` is still True until the stretch windows land.
    - `test_unloading_mid_refine_stops_the_worker` (Review Focus 3)
      - Patch `engine.pending_solve` to return a job that loops until `should_stop()`, then rest.
      - `plugin.unload()` returns.
      - Within 2 s no `nsgeo-refine*` thread is alive, and nothing was logged to `sys.excepthook` or `sys.unraisablehook`.
  - **Saved records** (`test_plugin_slice_export.py`): parametrise `test_view_settings_round_trip_the_finish` and `test_a_record_from_this_build_still_loads_in_0_2_0` over every key in `METHODS`.

- [ ] **Step 2: Run them and see them fail.**
  - Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py -q -p no:cacheprovider`
  - Then run the three QGIS files with the QGIS command, naming the files.
  - Expected: FAIL. The label is missing, and `PendingSolve`, `preview`, `finish_is_slow` and `refiner` don't exist.

- [ ] **Step 3: Implement the engine.**
  - **The plan and the preview.** For `min_curvature`, `_weights_for` builds the `CurvaturePlan` and a `PREVIEW_METHOD` `FillWeights` at the same max distance and search radius together, under the one key. Both are dropped wherever `_weights` is dropped today.
  - **The cache.** `_solved` is an `OrderedDict[bytes, np.ndarray]` used least-recently-used first. It and `_last_solve_ms` are emptied wherever the plan is dropped or rebuilt, and kept where it is kept.
  - **The digest.** `hashlib.blake2b(values.tobytes(), digest_size=16)` updated with `str(values.shape)` and `str(values.dtype)`.
  - **The `finish` path for `min_curvature`.** It is `smooth(solved, ...)`, where `solved` is the cached slice or a fresh `plan.solve(values)[0]`. That is equivalent to `finish_slice`, and it lets the cache hold the unsmoothed slice. A fresh solve's own time goes into `_last_solve_ms`.
  - **`PendingSolve`.** It holds:
    - the engine;
    - the plan it was made from (its identity is what `land()` checks);
    - a private `values.copy()`;
    - the key.

    `run` calls `plan.solve(values, should_stop)` and times it. `land` stores into `_solved` and `_last_solve_ms` only when `engine._weights` still holds that same plan object.

- [ ] **Step 4: Implement the dock** (plan calls 5 and 7). These are the parts the tests don't fully determine:

  ```text
  refresh_slice, This grid, a finish draw (not the coverage view):
      method min_curvature and engine.finish_is_slow(values, coverage, finish):
          refiner.cancel(); shown = engine.preview(...); provisional = True    # busy_cursor() if not weights_cached
          remember (values, coverage) and the current job key; status = PREVIEW_STATUS; rest.start()
      otherwise:
          shown = engine.finish(...); provisional = False                     # as today
          any method other than min_curvature: refiner.cancel(); rest.stop()
  _on_rest (guarded QTimer slot):
      jobs = [engine.pending_solve(remembered values, coverage, finish)] if provisional
      jobs += engine.stretch_solves(n_levels, finish) if the stretch combo is "shared"
      drop Nones; if jobs: refiner.start(jobs, _on_landed, report); status = REFINING_STATUS.format(done=0, total=len(jobs))
  _on_landed(job) (guarded):
      landed = job.land(); update REFINING_STATUS's count
      landed and provisional and job.key is the current job key → refresh_slice()   # a cache hit: the full slice
      not refiner.busy → if the stored stretch is provisional, drop it; refresh_slice()
  display_limit, shared branch, min_curvature:
      _shared_limit_cache becomes (key, value, final). A stored entry for the key is returned as today.
      engine.stretch_solves(...) non-empty → value = engine.shared_limit(..., preview=True), final = False,
          and rest.start() if the refiner is idle; otherwise value = engine.shared_limit(...), final = True
  ```

  - The early-return and `except` branches of `refresh_slice` also cancel the refiner and stop the rest timer.
  - An `on_error` from the refiner emits `error` with `minimum curvature failed: {message}`. It restores the normal status and leaves the preview on screen.
  - `plugin.unload()` calls `self.slices_dock.refiner.shutdown()` before `dispose_site()`.

- [ ] **Step 5: Run the tests and see them pass**, then the full core + pure command and the full QGIS command. Expected: all pass, at 1366 + the new QGIS tests.

- [ ] **Step 6: Commit and push.**
  ```bash
  git commit -m "feat(slices): minimum curvature in This grid — kriging preview, background refine, solved-slice cache"
  git push origin nsgeo-slice-interpolation-b
  ```

---

### Task 4: Whole site with minimum curvature

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`:
  - `SiteSlice.provisional: bool = False`, as the last field;
  - `slice_at(..., preview: bool = False)`;
  - `pending_solves`;
  - `stretch_solves`;
  - `shared_limit(..., preview: bool = False)`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`: the same preview, rest and refine flow as Task 3's dock, using `dock.refiner`.
- Test: `tests/qgis/test_plugin_site_engine.py`, `tests/qgis/test_plugin_site_scope.py`.

**Interfaces:**
- Consumes: Task 3's `SliceEngine.finish_is_slow`, `preview`, `pending_solve`, `stretch_solves`, `shared_limit(..., preview=)` and `PendingSolve`; Task 2's `Refiner` through `dock.refiner`.
- Produces, on `SiteEngine`:
  ```python
  def slice_at(self, top_ns, thickness_ns, *, finish, method, manual, coverage=False,
               preview: bool = False) -> SiteSlice: ...
      # preview=True: each grid whose finish_is_slow shows engine.preview(...); provisional = any grid did
  def pending_solves(self, top_ns: float, thickness_ns: float, finish: SliceFinish) -> list[PendingSolve]: ...
      # every ready grid's uncached slice at this window, in ready_grids order
  def stretch_solves(self, thickness_ns: float, finish: SliceFinish) -> list[PendingSolve]: ...
      # every ready grid's uncached limit_windows
  def shared_limit(self, thickness_ns, clip, *, finish, method, manual, preview: bool = False) -> float: ...
  ```
  `SiteScope` gains `provisional: bool`.

- [ ] **Step 1: Write the failing tests.** `_wait_for_refine` is as in Task 3, copied into this file.
  - **`test_site_gains_commute_with_every_method`** gains `"min_curvature"`. For it, compare with `rtol=1e-4, atol=1e-4 * np.nanmax(np.abs(after))`.
  - **`test_a_slow_site_tick_previews_then_refines`**
    - With `min_curvature` and every grid engine's `_last_solve_ms` forced to 500, a slider move gives `scope.slice.provisional is True`.
    - `scope.slice.array` equals `slice_at(..., preview=True)` of that window.
    - After `_wait_for_refine`, `scope.slice.provisional is False` and the array equals a fresh `slice_at(...)`.
  - **`test_a_quick_site_tick_draws_minimum_curvature_at_once`**
    - At 5 ms on every engine, the first tick is final and the refiner never starts.
  - **`test_a_site_refine_for_a_window_left_behind_never_draws`** (Review Focus 2)
    - As Task 3's test, through `site_engine.pending_solves`.
  - **`test_the_site_stretch_with_minimum_curvature_uses_twelve_windows`**
    - `shared_limit` with `min_curvature` calls each engine's `finish` at most `len(limit_windows(...))` times per grid, counted.
    - The scope's limit is provisional, equal to `shared_limit(..., preview=True)`, until `stretch_solves` is empty. After that it equals `shared_limit(...)`.
  - **`test_a_site_with_minimum_curvature_exports_and_reopens`**
    - Export the three-grid fixture with `min_curvature`.
    - The file has `NSGEO_SITE_INTERPOLATION == "min_curvature"` and every band is finite on data cells.

- [ ] **Step 2: Run them and see them fail.** Run `test_plugin_site_engine.py` and `test_plugin_site_scope.py` with the QGIS command. Expected: FAIL. `preview=`, `provisional` and `pending_solves` don't exist.

- [ ] **Step 3: Implement.**
  - **`SiteEngine._shown`** takes `preview`. Per grid it uses `engine.preview(...)` when `preview and engine.finish_is_slow(...)`, and `engine.finish(...)` otherwise. It reports whether any grid previewed.
  - **`SiteScope`'s tick** calls `slice_at(..., preview=True)` when the method is `min_curvature`.
  - **The scope's state machine** is Task 3's, with these substitutions:
    - `pending_solves` for `pending_solve`;
    - the scope's own rest timer;
    - `dock.refiner`;
    - a redraw through `schedule_refresh()`.

    A landed job redraws when its key is among the current tick's job keys. A tick that is not `min_curvature` cancels the refiner and stops the scope's rest timer.
  - **`SiteScope.display_limit`** carries the provisional stretch exactly as the dock's `display_limit` does.

- [ ] **Step 4: Run the tests and see them pass**, then the full QGIS command.

- [ ] **Step 5: Commit and push.**
  ```bash
  git commit -m "feat(site): minimum curvature in Whole site — kriging preview and background refine"
  git push origin nsgeo-slice-interpolation-b
  ```

---

### Task 5: Exports with progress and cancel; the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`: `ExportCancelled(Exception)`, and an `export_slices(..., progress=None)` parameter.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`: an `export_site(..., progress=None)` parameter.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
  - one `_export_progress(title: str, total: int)` helper that returns `(callback, dialog)`;
  - both exports use it;
  - both exports call `self.slices_dock.refiner.cancel()` first;
  - cancel and This grid failure remove the partial file (plan call 11).
- Modify: `docs/guide/getting-started.md`, step 4, Method bullet: add **Minimum curvature**.
- Modify: `packages/nsgeo-qgis/tests/qgis/conftest.py` only if the modal guard needs to know about `QProgressDialog`. It is shown, not `exec()`'d, so it should not.
- Test: `tests/qgis/test_plugin_slice_export.py`, `tests/qgis/test_plugin_site_export.py`, `tests/qgis/test_plugin_site_scope.py` (the plugin-level site export tests live there) and `tests/qgis/test_plugin_slice_export_dialogs.py`.

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
  - **`test_a_minimum_curvature_export_records_its_method_and_never_writes_a_preview`**
    - With `min_curvature` and `engine._last_solve_ms` forced to 500, the This grid export has `NSGEO_INTERPOLATION == "min_curvature"`.
    - Every band equals the engine's `finish` of that band's window after `to_north_up`, not its `preview`.
  - **`test_an_export_cancels_a_running_refine`**
    - With a looping job running in `dock.refiner`, starting an export leaves `dock.refiner.busy` False before the first band.
  - **`test_the_progress_dialog_is_cancellable_and_window_modal`**
    - `_export_progress("Export GeoTIFF", 5)` returns a dialog with `windowModality() == Qt.WindowModality.WindowModal`, `minimumDuration() == 500` and a maximum of 5.
    - Calling `dialog.cancel()` makes the callback return False.

- [ ] **Step 2: Run them and see them fail.** Run the four files with the QGIS command. Expected: FAIL. The `progress` parameter, `ExportCancelled` and `_export_progress` don't exist.

- [ ] **Step 3: Implement.**
  - **The core of the exporters.** The `progress` call sits in each exporter's band generator, so the writers stay unchanged.
  - **The plugin.** It:
    - cancels the refiner;
    - catches `ExportCancelled` separately from other exceptions;
    - removes the partial file by the site export's mtime rule, now shared by both exports;
    - reports `export cancelled` at Info;
    - always closes the dialog, in a `finally`.
  - **The guide paragraph**, in the step 4 Method bullet, after the IDW sentence: *"Pick **Minimum curvature** for the smoothest surface through the lines, the method Surfer users often know. It can overshoot a little beside a strong contrast, which shows as a faint ring of the opposite sign between lines. It is solved for each slice, so it is slower. At a fine cell you see kriging while the depth moves, and minimum curvature replaces it a moment after the depth rests. The colour stretch can shift once more when minimum curvature has measured it. An export always uses minimum curvature, shows its progress, and can be cancelled."*

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

## After Task 5 (coordinator)

These are the manual checkpoints from spec §10. Track them and report them; never pass them silently.

1. **Build and walkthrough.** Deploy to a fresh QGIS profile, then hold the walkthrough on the user's real grids (Sunnyside) as an Artifact with a results db. Cover:
   - minimum curvature at defaults: no holes, and a skipped line blank;
   - the overshoot ring, judged acceptable or not (tension is the first follow-up if not);
   - live dragging at 0.2 m;
   - at a fine cell (0.05 m):
     - the kriging preview while dragging;
     - the refine landing after a pause;
     - moving on mid-refine;
     - the stretch settling;
   - Whole site, the same at a fine cell;
   - an export with progress and a cancel;
   - closing QGIS mid-refine;
   - a saved cube.
2. **Surfer comparison (spec §10.2).** The user compares nsgeo's kriging and minimum curvature, at defaults, against their Surfer grids. The question is "same ballpark". This gate is required for B.
3. **File the deferred follow-ups** from review. Note that the faster solver (multigrid) is already filed as #111.
