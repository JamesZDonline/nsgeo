# Slice Interpolation, Milestone A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: run the failing test and see it fail before writing any production code.

**Goal:** Replace the Slices panel's **Fill radius** with two separate steps, in both scopes, the exports and the saved settings:
- an interpolation method chosen from a dropdown (None, IDW or kriging), limited by a **max distance to data**;
- optional Gaussian smoothing, set separately along X and Y.

**Architecture:**
- **Core: interpolation.** `nsgeo/slices/interpolate.py` turns "which cells hold data" into a sparse weights table (`FillWeights`). Each slice is then one gather and one weighted sum.
- **Core: smoothing.** `nsgeo/slices/smooth.py` is a normalised, separable Gaussian.
- **Core: the finished slice.** `nsgeo/slices/finish.py` joins the two under one `FinishSettings`, expressed in metres.
- **Plugin settings.** The user's settings are a `SliceFinish`, with max distance in line spacings. They are resolved to metres per grid.
- **Plugin engine.** `SliceEngine.finish()` caches one `FillWeights` per frame, set of populated cells and setting.
- **Plugin UI.** A `FinishPanel` widget, one instance per scope, replaces the two fill-radius boxes.
- **North-up resample.** `to_north_up` adopts the site lattice's half-pitch rule for rotated frames, so no data cell is dropped.

**Tech Stack:** Python 3, numpy (core); PyQt via `qgis.PyQt` (plugin); pytest on two tiers: core and pure in `.venv`, QGIS in `.venv-qgis`.

**Spec:** `docs/superpowers/specs/2026-11-02-nsgeo-slice-interpolation-design.md`. This plan is milestone A of its §12. Minimum curvature is milestone B and is **not** in this plan. Read the spec before your task. Where the plan and the spec disagree, the plan wins, because it records the decisions listed below.

## Plan calls (decisions this plan makes where the spec leaves the builder a choice)

1. **Neighbourhood (spec §5.3).**
   - Four quadrants, with the 3 nearest data cells in each (up to 12 sources).
   - Search radius = max(2 × line spacing, 2 × max distance).
   - Quadrant boundaries: `q = floor((atan2(dy, dx) mod 2π) / (π/2))`. So for lines along X, two quadrants look up and two look down. For lines along Y, two look left and two look right. Either way every gap cell sees both of its lines.
2. **Weights are built synchronously, on first use.**
   - Spike on a 50 m grid of 0.5 m lines at the default 0.2 m cell: IDW about 60 ms, kriging about 300 ms; applying the weights costs about 4 ms per slice.
   - A 0.05 m cell takes seconds to set up. A wait cursor shows while weights are built, which is the "wait at setup" the user accepted.
   - **Escalate, rather than ship,** if Task 1 measures kriging setup above 0.5 s at the default cell on the 50 m synthetic grid.
3. **Two `FinishPanel` instances, one per scope** (`dock.grid_finish`, `dock.site_finish`), shown one at a time.
   - This is today's pattern for the two radius boxes, so each scope keeps its own remembered values without the shared-spin capture and restore machinery.
   - The user sees one Interpolation group either way. This refines the spec's §8 wording "collapses into one control".
4. **A remembered `method` lives in the same `resolution` record as the numbers,** so there is one remember path. `_merge_resolution` keeps strings as strings.
5. **A non-finite data value (a broken cube invariant) is skipped, not propagated.** `FillWeights.apply` renormalises a target's weights over its finite sources. That data cell itself shows NaN.
6. **The spec §9 stripe example is moved onto the cell lattice.** At a 0.05 m cell a 0.1 × spacing offset is one cell and leaves no stripe, so the test offsets a line by 0.2 × spacing instead (Task 1).
7. **The real-data helpers in `tests/test_slices_site.py` move to `tests/real_lines.py`** so the interpolation tests can share them.

## Global Constraints

- **The core stays numpy-only, with no Qt.**
  - `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` stay green.
  - Do not add scipy, even as an accelerator.
  - The plugin imports Qt only through `qgis.PyQt`.
- Every slot connected to a Qt signal or timer guards its own body and reports through `_log` or `dock.error`. It never raises. Read the module docstrings of `slices_dock.py` and `site_scope.py` before touching either.
- **Seeds never write.** Opening a survey, switching scope or grid, seeding, restoring and clamping never mark the survey dirty and never write a remembered value. Only a user's edit, a line choice, or picking a saved cube writes one.
- **Files stay readable both ways.**
  - `SCHEMA_VERSION` does not change.
  - Surveys and cube records from 0.2.0 keep loading. 0.2.0 must still load what this build saves.
  - Old fill settings (`radius_spacings`, `radius_m`) are ignored on load, never mapped onto the new controls.
- **Exact values from the spec:**

  | Setting | Value |
  |---|---|
  | Default method | `"kriging"` |
  | Default max distance | `0.5` × line spacing |
  | Distance comparison | inclusive, `≤ max_distance_m + 1e-9` |
  | Smoothing default | `0.0` m on both axes |
  | Smoothing kernel | Gaussian σ in metres, truncated at 4σ |
  | IDW power | `2` |
  | Kriging | ordinary, linear variogram, no nugget, isotropic |
  | Interpolation | never changes a data cell |
  | Smoothing | never fills a blank |

- **Method keys and labels, in this order:** `"none"` → `None (binned only)`, `"idw"` → `Inverse distance (IDW)`, `"kriging"` → `Kriging`. Milestone B appends `"min_curvature"`.
- **Comments and docstrings** follow the file they are in. They say why, and cite the spec as `(interpolation spec §5.2)` the way existing comments cite rulings.
- **Shared-worktree safety.** Reviewers and any mutation testing never edit this worktree; they work on a scratch copy. Set `PYTHONDONTWRITEBYTECODE=1` for every test run.
- **Tool versions:** ruff 0.17.1 and mypy 2.4.0, as pinned in CI.
- **Commits:**
  - End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Push each commit to `origin nsgeo-slice-interpolation` as it is made.
- **The unmerged `nsgeo-m14` branch has a test that imports `fill` from `nsgeo.slices`.** Do not touch that branch. Whichever of the two merges second updates that test.

## Before Task 1 (coordinator)

Run these from the worktree root `.worktrees/nsgeo-slice-interpolation`:

1. Create the two virtualenvs the way the other worktrees have them:
   - `python3 -m venv .venv && .venv/bin/pip install -e "packages/nsgeo-core[dev]" ruff==0.17.1 mypy==2.4.0`
   - `python3 -m venv --system-site-packages .venv-qgis && .venv-qgis/bin/pip install -e packages/nsgeo-core pytest`
   - Match any extra test packages to `pip freeze` in `.worktrees/nsgeo-slices-cleanup/.venv-qgis`.
2. Copy the real files: `cp -r ../nsgeo-slices-cleanup/packages/nsgeo-core/tests/data/local packages/nsgeo-core/tests/data/`.
3. Run the verification commands below and record the baseline pass and skip counts in the ledger. A real-data test that skips has validated nothing, so the skip count must not rise in any task.

## Verification commands (exactly these, from the worktree root)

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`
  - This takes about 11 minutes. Run single files while iterating.
- **lint:** `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- **types:** `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`

## Review Focus

These are the inputs most likely to hurt a user that the spec does not spell out. Each is pinned by a test in the task named.

1. **A survey edge, a lone line, a lone data cell.**
   - Cells beyond the outermost line are filled from one side only, out to the max distance and no further. One line, or one data cell, must not crash.
   - Pinned by Task 1: `test_one_line_fills_both_sides_out_to_max_distance_and_no_further`.
2. **A grid's line spacing edited after its max distance was set.**
   - The metres readout and the drawn slice follow the new spacing without a grid switch.
   - Pinned by Task 4: `test_max_distance_follows_a_line_spacing_edit`.
3. **A 0.2.0 survey or cube.**
   - A 0.2.0 survey remembers `radius_spacings: 0.5`; a 0.2.0 cube record has only `radius_m`. Both open on the new defaults, with no holes, and opening them doesn't mark the survey dirty.
   - Pinned by Task 4: `test_a_0_2_0_remembered_radius_is_ignored` and `test_restoring_a_0_2_0_cube_record_shows_the_defaults`.
4. **Toggling method or max distance back and forth.**
   - For example kriging → IDW → kriging. The cache must never serve the other setting's weights.
   - Pinned by Task 4: `test_switching_method_back_gives_the_same_slice_as_from_scratch`.
5. **A fine cell on a large grid.**
   - The weights' memory counts in the estimate, so the over-budget warning fires before anything is built.
   - Pinned by Task 3: `test_the_estimate_counts_the_fill_weights`.

---

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

### Task 2: Smoothing, the finished slice, and a north-up resample that drops nothing

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/smooth.py`
- Create: `packages/nsgeo-core/src/nsgeo/slices/finish.py`
- Modify, in `packages/nsgeo-core/src/nsgeo/slices/display.py`:
  - `to_north_up` gets the half-pitch rule.
  - Rewrite the docstring's "Nearest neighbour, not bilinear" paragraph, which names `fill`, so it names interpolation and smoothing as the user's visible choices.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/frame.py:10-13`. The docstring says directional smoothing (interpolation spec §6) now covers the X/Y need, so cells stay square. Drop "the fill radius".
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`, the module docstring's Ruling AE paragraphs (lines 36–70). The rotated-frame loss is gone, because the export pitch now follows Ruling 2. Keep a one-line history note.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` to export `smooth`, `FinishSettings` and `finish_slice`.
- Test: `packages/nsgeo-core/tests/test_slices_smooth.py`, `packages/nsgeo-core/tests/test_slices_finish.py`, `packages/nsgeo-core/tests/test_slices_display.py`
- Test, adjust only: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`, `test_plugin_slice_layer.py`. Change only expectations that assumed pitch = cell on a **rotated** frame.

**Interfaces:**
- Consumes: `FillWeights`, `METHODS` (Task 1); `lattice_pixel` and `snap_azimuth` from `nsgeo.slices.site`. Import them inside `to_north_up`, because `site.py` imports `display.py`.
- Produces:
  ```python
  # smooth.py
  SMOOTH_TRUNCATE_SIGMAS: float = 4.0
  def smooth(values: np.ndarray, cell: float, sigma_x_m: float, sigma_y_m: float) -> np.ndarray: ...
      # (ny, nx) -> (ny, nx) float32; axis 1 is frame X, axis 0 is frame Y

  # finish.py
  @dataclass(frozen=True)
  class FinishSettings:
      method: str
      max_distance_m: float
      search_radius_m: float
      smooth_x_m: float = 0.0
      smooth_y_m: float = 0.0
  def finish_slice(values: np.ndarray, weights: FillWeights, cell: float, settings: FinishSettings) -> np.ndarray: ...
      # = smooth(weights.apply(values), cell, settings.smooth_x_m, settings.smooth_y_m)
  ```
- **`FinishSettings.__post_init__` raises `ValueError` for:**
  - a method not in `METHODS`;
  - any of the four distances non-finite or negative;
  - `search_radius_m < max_distance_m`.
- **How `smooth` works:**
  - It smooths `value × finite-mask` and the mask with the same truncated 1-D Gaussians, one per axis, then divides.
  - Cells that were NaN stay NaN.
  - A σ of 0 leaves that axis untouched.
- **`to_north_up`'s new pitch:**
  - `pixel = lattice_pixel(frame.cell, [snap_azimuth(frame.azimuth, hypot(frame.nx, frame.ny) * frame.cell, frame.cell)])`.
  - The pixel centres, width, height, epsilon and geotransform all use `pixel`.
  - An axis-aligned frame is unchanged.

- [ ] **Step 1: Write the failing tests.**

  `test_slices_smooth.py`:
  - `test_zero_sigma_is_the_identity`: equal arrays, including NaN positions.
  - `test_sigma_x_alone_spreads_a_spike_only_along_x`: spike `1.0` at (10, 10) in a 21 × 21 zero field, cell 0.1, σx 0.3. Only row 10 is non-zero.
  - `test_sigma_y_alone_spreads_a_spike_only_along_y`: the mirror image.
  - `test_a_spike_spreads_as_a_gaussian_of_the_given_sigma`: for `k` in 0–3, `out[10, 10 + k] / out[10, 10] ≈ exp(-(0.1 k)² / (2 · 0.3²))`, `rtol=1e-6`.
  - `test_blanks_stay_blank_and_nothing_new_is_filled`: same NaN mask before and after, σ 0.5 on both axes.
  - `test_an_edge_beside_a_blank_is_not_pulled_toward_zero`: a field of 5.0 whose right half is NaN. Every finite output ≈ 5.0.
  - `test_smoothing_is_affine_equivariant`.
  - `test_smooth_refuses_a_negative_sigma` (`ValueError`).

  `test_slices_finish.py`:
  - `test_finish_slice_interpolates_then_smooths`: equals `smooth(w.apply(v), cell, σx, σy)`.
  - `test_finish_settings_refuse_bad_values`: each `ValueError` case above.
  - `test_finish_slice_refuses_a_shape_mismatch`.

  `test_slices_display.py`:
  - `test_a_rotated_frame_is_resampled_at_half_the_cell`: azimuth 10.497, cell 0.2. `gt[1] == 0.1` and `gt[5] == -0.1`.
  - `test_no_cell_is_dropped_on_a_rotated_frame`, parametrized over azimuths 10.497, 33, 45 and 77.3:
    - `values = np.arange(nx * ny).reshape(ny, nx)` on a 25 × 40 frame;
    - the set of finite output values equals `set(range(nx * ny))`.
  - `test_an_axis_aligned_frame_keeps_the_full_pitch`: azimuths 0, 90 and 180 give `gt[1] == cell`, and azimuth 0 keeps today's exact shape.
  - `test_a_hair_off_axis_frame_keeps_the_full_pitch`: azimuth `1e-7` on a 20 m frame.

- [ ] **Step 2: Run them and see them fail.** Run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_smooth.py packages/nsgeo-core/tests/test_slices_finish.py packages/nsgeo-core/tests/test_slices_display.py -q -p no:cacheprovider`. Expected: FAIL. The modules are missing, and a rotated frame comes back at `gt[1] == cell`.

- [ ] **Step 3: Implement** `smooth`, `FinishSettings`, `finish_slice` and the `to_north_up` pitch, and make the docstring edits listed under Files.

- [ ] **Step 4: Run the tests and see them pass.** Run the Step 2 command. Then run the full core + pure suite.

- [ ] **Step 5: Run the affected QGIS files.** Run `test_plugin_slice_export.py`, `test_plugin_slice_layer.py`, `test_plugin_site_export.py` and `test_plugin_slices_dock.py`. Fix only expectations that assumed pitch = cell on a rotated frame, and list each one in your report. Any other failure is a bug in this task.

- [ ] **Step 6: Run ruff and mypy, then commit.**

  ```bash
  git commit -m "feat(slices): Gaussian X/Y smoothing, the finished slice, and a north-up resample that keeps every cell (interpolation spec §6, §8)"
  git push
  ```

---

### Task 3: Plugin settings, saved settings, and the Interpolation panel

Everything in this task is **additive**. The dock still uses Fill radius until Task 4, so `radius_spacings` stays accepted everywhere for now.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`. Add the constants, `SliceFinish` and `FINISH_FIELDS`. Add `MemoryEstimate.weights_bytes` and count it in `total_bytes`. `estimate_memory` fills it in.
- Modify: `packages/nsgeo-core/src/nsgeo/project.py`, in `_RESOLUTION_KEYS` and `_clean_resolution`:
  - add `max_distance_spacings`, `smooth_x_m` and `smooth_y_m` as numbers, each dropped if negative;
  - add `method` as a string, kept only if it is in `METHODS`;
  - the return type becomes `dict[str, float | str]`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`:
  - `_merge_resolution` keeps a `str` value as is, and floats as now.
  - `remember_slice_resolution` and `remember_site_resolution` gain the keyword arguments `method: str | None`, `max_distance_spacings`, `smooth_x_m` and `smooth_y_m`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`, on `ViewSettings`:
  - new fields, each with its default;
  - a `finish` property;
  - `to_dict` / `from_dict` compatibility both ways.
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/finish_panel.py` with `FinishPanel` and `busy_cursor`.
- Test:
  - `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`
  - `packages/nsgeo-core/tests/test_project.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`
  - Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_finish_panel.py`

**Interfaces:**
- Consumes: `METHODS`, `NEIGHBOURS_PER_QUADRANT` (Task 1); `FinishSettings` (Task 2).
- Produces, in `slices_plan.py`:
  ```python
  DEFAULT_METHOD = "kriging"
  DEFAULT_MAX_DISTANCE_SPACINGS = 0.5
  SEARCH_RADIUS_SPACINGS = 2.0
  METHOD_LABELS: dict[str, str]          # ordered as METHODS, labels from Global Constraints
  WEIGHT_BYTES_PER_CELL = 4 * NEIGHBOURS_PER_QUADRANT * 8   # int32 source + float32 weight
  FINISH_FIELDS = ("method", "max_distance_spacings", "smooth_x_m", "smooth_y_m")

  @dataclass(frozen=True)
  class SliceFinish:
      method: str = DEFAULT_METHOD
      max_distance_spacings: float = DEFAULT_MAX_DISTANCE_SPACINGS
      smooth_x_m: float = 0.0
      smooth_y_m: float = 0.0
      def in_metres(self, spacing_m: float) -> FinishSettings: ...
          # max_distance_m = max_distance_spacings * spacing_m
          # search_radius_m = max(SEARCH_RADIUS_SPACINGS * spacing_m, 2 * max_distance_m)
          # ValueError if spacing_m <= 0
      def updated(self, fields: Mapping[str, object]) -> SliceFinish: ...
          # lays FINISH_FIELDS from `fields` over self; a bad method or a negative or
          # non-finite number is ignored, as is every other key
  ```
- Produces, in `ViewSettings`:
  - New fields: `method: str = DEFAULT_METHOD`, `max_distance_spacings: float = DEFAULT_MAX_DISTANCE_SPACINGS`, `smooth_x_m: float = 0.0`, `smooth_y_m: float = 0.0`.
  - `radius_m` stays.
  - `finish` property → `SliceFinish`.
  - `to_dict` writes all ten keys.
  - `from_dict` reads `radius_m` with `.get(..., 0.0)`. It reads the four new keys only when `"method"` is present, through `SliceFinish().updated(doc)`; otherwise it uses the defaults.
- Produces, in `ui/finish_panel.py`:
  ```python
  @contextmanager
  def busy_cursor() -> Iterator[None]: ...     # wait cursor; always restored, even on an exception

  class FinishPanel(QGroupBox):                 # title "Interpolation"
      edited = pyqtSignal(str, object)          # (field, value): only a user's edit
      def __init__(self, parent: QWidget | None = None, *, metres_label: bool) -> None: ...
      method_combo: QComboBox                   # labels from METHOD_LABELS, itemData = key
      max_distance_spin: QDoubleSpinBox         # 0–10, 2 dp, step 0.25, suffix " × line spacing"
      max_distance_metres: QLabel               # "= 0.25 m"; exists only when metres_label
      smooth_x_spin: QDoubleSpinBox             # 0–5, 2 dp, step 0.05, suffix " m"
      smooth_y_spin: QDoubleSpinBox             # same
      def value(self) -> SliceFinish: ...
      def set_value(self, finish: SliceFinish) -> None: ...   # quiet: emits nothing
      def set_spacing(self, spacing_m: float | None) -> None: ...  # refreshes the metres label; "" for None
  ```
- **Panel rows:** `Method`, `Max distance to data` (with the metres label beside it, when present), `Smoothing X`, `Smoothing Y`.
- **Panel behaviour:** `max_distance_spin` is disabled while the method is `"none"`.
- **Tooltip copy, verbatim:**
  - **Method:** `"How cells that no line crossed are filled from the cells around them.\nKriging: a weighted average that follows how values vary with distance; the usual choice.\nInverse distance: a weighted average in which nearer cells count more.\nNone: show only the cells a line crossed."`
  - **Max distance to data:** `"Cells farther than this from any line are left blank, so the edge of the survey or a missing line is never filled in.\nHalf a line spacing just closes the gap between neighbouring lines; raise it if a line strayed and left a blank stripe."`
  - **Smoothing X:** `"Blurs the slice along the grid's X axis by this distance (the standard deviation of a Gaussian), after filling. 0 is off.\nOnly smoothing changes the cells a line crossed."`
  - **Smoothing Y:** the same with `Y`.

- [ ] **Step 1: Write the failing tests.**

  Pure (`test_pure_slices_plan.py`):
  - `test_slice_finish_defaults`: `SliceFinish() == SliceFinish("kriging", 0.5, 0.0, 0.0)`.
  - `test_in_metres_scales_by_the_spacing_and_sets_the_search_radius`:
    - spacing 0.5 → `max_distance_m == 0.25` and `search_radius_m == 1.0`;
    - `max_distance_spacings=3.0` → `search_radius_m == 3.0`.
  - `test_in_metres_refuses_a_spacing_that_is_not_positive`.
  - `test_updated_lays_known_fields_over_and_ignores_the_rest`:
    - `{"method": "idw", "radius_spacings": 0.5, "cell": 0.2}` → only `method` changes.
  - `test_updated_ignores_a_bad_method_or_number`: `"bogus"`, `3`, `-1.0`, `nan` and `True`.
  - `test_the_estimate_counts_the_fill_weights` (Review Focus 5):
    - `estimate_memory(0, 1000, 10).weights_bytes == 1000 * WEIGHT_BYTES_PER_CELL`;
    - `total_bytes` includes it.

  Core (`test_project.py`):
  - `test_remembered_finish_fields_are_kept_and_cleaned`:
    - kept: `"kriging"`, `0.75`, `0.3`;
    - dropped: `"bogus"`, `3`, `-1`, `nan`.
  - `test_an_old_radius_spacings_still_loads`. Task 5 flips this test.

  QGIS:
  - `test_plugin_session.py`:
    - `test_remembering_a_method_keeps_it_a_string_and_marks_dirty_once`;
    - `test_remembering_the_same_method_again_does_not_mark_dirty`.
  - `test_plugin_slice_export.py`:
    - `test_view_settings_round_trip_the_finish`;
    - `test_a_0_2_0_view_record_loads_with_the_new_defaults` (a record with only the six 0.2.0 keys, `radius_m: 0.25`);
    - `test_a_view_record_with_a_bad_method_falls_back_to_the_defaults`;
    - `test_a_record_from_this_build_still_loads_in_0_2_0`. Its fixture is a verbatim copy of 0.2.0's `ViewSettings.from_dict` body, `git show v0.2.0:packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`, as a local function. It must not raise on `ViewSettings(...).to_dict()`.
  - `test_plugin_finish_panel.py`:
    - `test_the_panel_starts_at_the_defaults`: `value() == SliceFinish()`, and the combo's labels match `METHOD_LABELS` in order.
    - `test_the_spins_have_the_pinned_ranges_steps_and_suffixes`.
    - `test_set_value_is_quiet_and_round_trips`.
    - `test_a_user_edit_emits_the_field_and_value`: picking IDW emits `("method", "idw")`; setting the spin to 0.75 emits `("max_distance_spacings", 0.75)`; likewise for both smoothing spins.
    - `test_max_distance_is_disabled_for_none`.
    - `test_the_metres_label_follows_the_spacing`: `"= 0.25 m"` at spacing 0.5; `""` for None.
    - `test_the_tooltips_are_the_pinned_copy`.
    - `test_busy_cursor_is_restored_after_an_exception`: `QApplication.overrideCursor()` is None afterwards.

- [ ] **Step 2: Run them and see them fail.** Run each file with its tier's command. Expected: FAIL on missing names.

- [ ] **Step 3: Implement**, as specified in the Interfaces block.

- [ ] **Step 4: Run the new tests, then every suite, and see them pass.** Then run ruff and mypy. `slices_plan.py` is in the mypy set.

- [ ] **Step 5: Commit.**

  ```bash
  git commit -m "feat(slices): SliceFinish settings, saved both ways with 0.2.0, and the Interpolation panel (interpolation spec §8)"
  git push
  ```

---

### Task 4: This grid draws, exports and remembers through the panel (closes #104)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`:
  - add `finish_settings`, `weights_cached`, `finish` and the weights cache;
  - `shared_limit` takes a `SliceFinish`;
  - drop the cache in `_rebuild_geometry`, `set_source` and `clear`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`:
  - **Remove:** `grid_radius_spin`, `grid_radius_metres`, `grid_radius_row`, `_update_radius_metres`, `radius_cells` and `_filled_radius_cells`.
  - **Add:** `self.grid_finish = FinishPanel(metres_label=True)` directly after `resolution_group` in `outer`.
  - **Add:** `self._finish_debounce`, a single-shot QTimer with the same interval as `_debounce`, whose timeout calls `refresh_slice()`.
  - **Add:** `slice_finish() -> SliceFinish`.
  - **Rewire to the panel:** `refresh_slice`, `rebuild_source`'s stale-redraw check, `display_limit`'s cache key, the seed and restore paths, `_on_resolution_edited`, `view_settings`, `apply_view` and `restore_cube`'s remembered fields. Grep every `grid_radius` and `radius_cells`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`. `show_scope_widgets` toggles `dock.grid_finish`'s visibility in place of `grid_radius_row`. The site's `radius_spacing_spin` stays until Task 5.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`:
  - `ExportPlan.radius_cells` becomes `finish: FinishSettings | None`, resolved to metres;
  - `plan_export(..., finish: FinishSettings | None = None)`;
  - `export_slices(engine, path, thickness_levels, step_levels, velocity, finish: SliceFinish, *, writer=None)` hands `engine.finish_settings(finish)` to `plan_export` and yields `engine.finish(*engine.slice_at(band.window), finish)` per band;
  - the writer's metadata;
  - `write_coverage` passes `finish=None`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`, in `export_geotiff`:
  - pass `dock.slice_finish()`;
  - **delete** the radius-0 warning branch, so the message is always plain;
  - rewrite the Ruling AE docstring bullets near line 911.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`, `test_plugin_slices_dock.py`, `test_plugin_slice_export.py`. Update the existing fill and radius tests in these files to the new API rather than deleting their intent. For example, `test_shared_limit_measures_the_filled_array_actually_displayed` now measures the finished array.

**Interfaces:**
- Consumes:
  - `SliceFinish`, `FinishPanel` and `busy_cursor` (Task 3);
  - `FinishSettings` and `finish_slice` (Task 2);
  - `plan_fill` and `FillWeights` (Task 1).
- Produces, on `SliceEngine`:
  ```python
  def finish_settings(self, finish: SliceFinish) -> FinishSettings: ...
      # finish.in_metres(<chosen grid's default_spacing>); RuntimeError with no source
  def weights_cached(self, finish: SliceFinish) -> bool: ...
  def finish(self, values: np.ndarray, coverage: np.ndarray, finish: SliceFinish) -> np.ndarray: ...
      # finish_slice(values, <cached or new plan_fill(coverage > 0, frame.cell, ...)>, frame.cell, settings)
  def shared_limit(self, thickness_levels: int, clip: Any, finish: SliceFinish) -> float: ...
  ```
- **Cache rule.** The cache holds one `(key, FillWeights)` with `key = (frame, settings)`.
  - **Hit** only when the key matches **and** `np.array_equal(weights.populated, (coverage > 0).ravel())`.
  - `weights_cached` compares the key only, because lines changing goes through `set_source`, which clears the cache.
  - The cell always comes from `self.frame.cell`, never from a widget. That is #104's fix.
- **Metadata keys** on a values GeoTIFF:
  - `NSGEO_INTERPOLATION` (method key);
  - `NSGEO_MAX_DISTANCE_M`, `NSGEO_SMOOTH_X_M`, `NSGEO_SMOOTH_Y_M` (`str(float)`);
  - `NSGEO_FRAME_AZIMUTH_DEG`, as before.
  - The coverage companion carries none of the four. `NSGEO_FILL_RADIUS_CELLS` is gone.
- **Dock behaviour:**
  - **Redraw:** `refresh_slice` wraps `engine.finish(...)` in `busy_cursor()` when `not engine.weights_cached(finish)`. It records `self._drawn_finish = engine.finish_settings(finish)`.
  - **Stale redraw:** `rebuild_source` redraws when `engine.finish_settings(self.grid_finish.value()) != self._drawn_finish`. This happens when a spacing edit moved the metres.
  - **Metres label:** every place that called `_update_radius_metres()` now calls `self.grid_finish.set_spacing(self._grid_spacing())`. Those are the seed, a cube restore and `rebuild_source` on session signals.
  - **Edits:** `grid_finish.edited(field, value)` leads to: remember `{field: value}` for the grid, unless the dock is `_updating` or `_seeding`; refresh the metres label; start `_finish_debounce`.
  - **Seed:** a grid change sets `grid_finish` to `SliceFinish()` quietly, then lays the grid's remembered fields over it with `SliceFinish().updated(remembered)`, then calls `set_spacing(grid spacing)`.
  - **Saving a cube:** `view_settings()` writes the panel's four fields and `radius_m = max_distance_spacings × spacing`.
  - **Restoring a cube:** `apply_view` sets the panel from `view.finish`, and `restore_cube` remembers those four fields for the grid.

- [ ] **Step 1: Write the failing tests.**

  Engine (`test_plugin_slices_engine.py`):
  - `test_finish_matches_the_core_pipeline`: equals `finish_slice(v, plan_fill(c > 0, frame.cell, ...), frame.cell, engine.finish_settings(f))`.
  - `test_weights_are_built_once_and_reused_across_windows`: monkeypatch `plan_fill` with a counter; three windows give one call.
  - `test_a_new_cell_or_setting_rebuilds_the_weights`.
  - `test_switching_method_back_gives_the_same_slice_as_from_scratch` (Review Focus 4): kriging → IDW → kriging equals a fresh engine's kriging slice.
  - `test_shared_limit_measures_the_finished_slices`.

  Dock (`test_plugin_slices_dock.py`):
  - `test_the_interpolation_group_replaces_fill_radius`: there is no `"Fill radius"` label in the Resolution form; `grid_finish` is visible in This grid and starts at `SliceFinish()` after a grid seed.
  - `test_a_finish_edit_redraws_and_is_remembered_for_the_grid`: pick IDW and flush `_finish_debounce`. Then `current_values()` equals `engine.finish(*engine.slice_at(window), SliceFinish(method="idw"))`, and `session.slice_resolution("A")["method"] == "idw"`.
  - `test_seeding_a_grid_resets_the_panel_and_remembers_nothing`: not dirty.
  - `test_a_remembered_finish_is_restored_on_a_grid_switch`.
  - `test_max_distance_follows_a_line_spacing_edit` (Review Focus 2): edit grid A's spacing from 0.5 to 1.0. The label reads `"= 0.5 m"` and the drawn slice equals one finished at 0.5 m, with no grid switch.
  - `test_a_0_2_0_remembered_radius_is_ignored` (Review Focus 3): remember only `radius_spacings=0.5` for A, switch to A. The panel is at `SliceFinish()` and the survey is not dirty.
  - `test_restoring_a_0_2_0_cube_record_shows_the_defaults` (Review Focus 3): a cube record whose `view` has only the six 0.2.0 keys. The panel is at the defaults after `cube_combo` picks it.
  - `test_saving_a_cube_records_the_finish_and_radius_m`.
  - `test_restoring_a_cube_restores_the_finish_and_remembers_it`.
  - `test_the_shared_stretch_follows_a_finish_change`.

  Export (`test_plugin_slice_export.py`):
  - `test_the_geotiff_carries_interpolation_metadata`. It replaces `test_the_geotiff_carries_fill_radius_and_azimuth_metadata` and checks the exact keys and values for the defaults at spacing 0.5: `"kriging"`, `"0.25"`, `"0.0"`, `"0.0"`, and no `NSGEO_FILL_RADIUS_CELLS`.
  - `test_the_coverage_companion_carries_no_interpolation_metadata`.
  - `test_export_bands_equal_the_finished_slices`.
  - `test_an_export_after_a_refused_resolution_uses_the_frames_cell` (#104):
    - Set the cell spin to a different value, then make z1 ≤ z0 so `_apply_resolution` refuses.
    - Export: every band equals `engine.finish(*engine.slice_at(w), dock.slice_finish())` at `engine.frame.cell`, and `NSGEO_MAX_DISTANCE_M` equals `0.5 × spacing`.
  - `test_exporting_a_rotated_grid_reports_no_fill_warning`: the message bar gets an Info-level message, not a Warning.

- [ ] **Step 2: Run them and see them fail.** Run the three files with the QGIS command. Expected: FAIL. `finish` and `slice_finish` are missing, and the metadata is the old metadata.

- [ ] **Step 3: Implement.** Grep this task's files for `radius` and `fill(`. Every hit in This grid's path goes, except the site's `radius_spacing_spin` and its uses, which are Task 5's.

- [ ] **Step 4: Run the three files, then the whole QGIS suite, core + pure, ruff and mypy.**

- [ ] **Step 5: Measure, and record before and after.**
  - Real data, four real lines at the dock's defaults (the setup `test_shared_limit_measures_…` uses).
  - Before: the median per-window cost of `fill(v, c, radius_cells_for(0.5, 0.5, cell))`, measured on `main`'s code in a scratch checkout.
  - After: the median per-window cost of `engine.finish(v, c, SliceFinish())` and of `SliceFinish(method="idw")`, with weights cached.
  - Spec §7 requires the cached cost to be no slower than the old fill. Report the numbers. If it is slower, stop and report.

- [ ] **Step 6: Commit.**

  ```bash
  git commit -m "feat(slices): This grid interpolates, smooths and exports through the Interpolation panel; Fill radius goes (interpolation spec §7, §8; closes #104)"
  git push
  ```

---

### Task 5: Whole site through the panel; retire the disc fill; the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`:
  - `_shown(top_ns, thickness_ns, finish, method, manual, coverage)` computes `a * self._engines[g].finish(values, cov, finish) + b`;
  - `slice_at(..., *, finish: SliceFinish, method, manual, coverage=False)`;
  - `shared_limit(..., *, finish, method, manual)`;
  - add `weights_cached(finish) -> bool`, true when every ready engine's weights are cached.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`:
  - remove `radius_spacing_spin`;
  - add `self.site_finish = FinishPanel(metres_label=False)` beside `grid_finish`;
  - drop the `radius_spacings` branch in `_on_resolution_edited`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`:
  - `show_scope_widgets` shows `site_finish` in Whole site and `grid_finish` in This grid;
  - `enter` restores the site's remembered finish quietly;
  - `site_finish.edited` leads to `remember_site_resolution(**{field: value})` (user edits only), `refresh_rows()` and `schedule_refresh()`;
  - `radius_tooltip` is replaced by `max_distance_tooltip`, set on `site_finish.max_distance_spin`;
  - the `limit_cache` key holds `site_finish.value()`;
  - every `slice_at` / `shared_limit` call passes `finish=`;
  - the tick wraps a refresh in `busy_cursor()` while `not engine.weights_cached(finish)`;
  - remove `set_radius_quietly` and `_on_radius_changed`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`:
  - `SiteExportPlan.radius_spacings` becomes `finish: SliceFinish | None`;
  - `plan_site_export` and `export_site` take `finish=`;
  - metadata;
  - `write_site_coverage` replaces with `finish=None`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`. `export_site_geotiff` passes `finish=dock.site_finish.value()`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`. Delete `DEFAULT_RADIUS_SPACINGS` and `radius_cells_for`. Rewrite the `Resolution` docstring line about the fill radius.
- Modify: `packages/nsgeo-core/src/nsgeo/project.py`. Remove `radius_spacings` from `_RESOLUTION_KEYS`, so an old one is dropped on load.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`. Remove the `radius_spacings` keyword arguments.
- **Delete:**
  - `packages/nsgeo-core/src/nsgeo/slices/fill.py` and `packages/nsgeo-core/tests/test_slices_fill.py`;
  - `fill`, `disc_kernel` and `clear_kernel_cache` from `nsgeo.slices` and `__all__`;
  - the `clear_kernel_cache()` call and import in `slices_engine.py`.
- Modify: `packages/nsgeo-qgis/scripts/bench_site.py` to use `finish=SliceFinish()` in place of `radius_spacings`.
- Modify: `docs/guide/getting-started.md`.
  - Rewrite step 3 so it no longer mentions Fill radius.
  - Add an **Interpolation** step after it covering Method, Max distance to data, and Smoothing X and Y, in the guide's existing plain style for archaeologists, with one sentence on when to pick each method. Renumber the steps that follow.
- Test:
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py`
  - `test_plugin_site_scope.py`
  - `test_plugin_site_export.py`
  - `packages/nsgeo-core/tests/test_project.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces:
  ```python
  # site_scope.py
  def max_distance_tooltip(session: Any, included: Iterable[str], spacings: float) -> str: ...
  ```
  The tooltip returns the Max distance copy from Task 3, then `" (in each grid's own line spacings, so grids with different spacings are treated alike)"`, then a new line, then `"A 0.25 m · B 0.50 m"`-style metres per included grid.
- **Site metadata keys:**
  - `NSGEO_SITE_INTERPOLATION`;
  - `NSGEO_SITE_MAX_DISTANCE_SPACINGS`, `NSGEO_SITE_SMOOTH_X_M`, `NSGEO_SITE_SMOOTH_Y_M` (`str(float)`).
  - The coverage companion carries none of them. `NSGEO_SITE_FILL_RADIUS_SPACINGS` is gone.

- [ ] **Step 1: Write the failing tests.**

  Site engine:
  - `test_site_slices_are_each_grids_finished_slice_times_its_gain`.
  - `test_site_gains_commute_with_every_method`: for `none`, `idw` and `kriging`, `a * engine.finish(v) + b` is allclose to `engine.finish(a * v + b)`, with `a=1.7`, `b=-0.3`.
  - `test_site_shared_limit_measures_finished_slices`.

  Site scope:
  - `test_each_scope_shows_its_own_interpolation_panel`.
  - `test_a_site_finish_edit_is_remembered_for_the_site_not_the_grid`.
  - `test_entering_the_site_restores_its_remembered_finish_quietly`: not dirty.
  - `test_a_site_finish_edit_redraws`.
  - `test_the_max_distance_tooltip_gives_each_grids_metres`: exact text for `site3`.

  Site export:
  - `test_the_site_geotiff_carries_interpolation_metadata`.
  - `test_the_site_coverage_companion_has_no_interpolation_metadata`.

  Core: flip `test_an_old_radius_spacings_still_loads` to `test_an_old_radius_spacings_is_dropped_on_load`.

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement**, then make the deletions.

- [ ] **Step 4: Sweep for leftovers.**
  - Run `grep -rnE "radius_spacings|radius_cells|Fill radius|DEFAULT_RADIUS|disc_kernel|clear_kernel_cache|fill\(|FILL_RADIUS" packages docs/guide`.
  - Expected: no hits, apart from `map_link.py`'s unrelated hit radius. List anything else you kept, and why, in your report.

- [ ] **Step 5: Run every suite, ruff and mypy.** The skip count must equal the baseline.

- [ ] **Step 6: Commit.**

  ```bash
  git commit -m "feat(slices): Whole site through the Interpolation panel; retire the disc fill; guide (interpolation spec §8)"
  git push
  ```

---

## After Task 5 (coordinator)

These are the manual checkpoints from spec §10. Track them and report them; never pass them silently.

1. **Build and deploy.** Deploy to a fresh QGIS profile on ns-geo, then hold the §10.1 walkthrough on the user's real grids. Leave out the minimum-curvature item. Confirm:
   - no polka dots and no holes at defaults;
   - a skipped line shows as blank;
   - Smoothing X and Y each act along the expected axis;
   - depth scrubbing is live;
   - site scope, saved cubes and exports all carry the settings.
2. **Offer the early kriging read.** Offer the user an early look at kriging against their Surfer grids (spec §12). The formal comparison waits for milestone B.
