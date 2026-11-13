### Task 1: The export pipeline, without Qt, plus the memory budget

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/export_pipeline.py`.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/display.py`. Add
  `frame_lattice(frame: CubeFrame, pixel: float) -> SiteLattice`: the north-up lattice anchored on
  the frame's own extent at any pixel, so This grid at `pixel == cell` stays exact. Make
  `_build_north_up_plan` use it. Export it from `nsgeo.slices` and add a README row.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`. Add `EXPORT_BUDGET_BYTES` and
  `export_refusal(...)` copy.
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_export_pipeline.py` (new) and
  `packages/nsgeo-core/tests/test_slices_display.py` (`frame_lattice` only).

**Interfaces (produces):**
- `@dataclass(frozen=True) ExportGrid`:
  - `grid_id: str`
  - `lines: tuple[PreparedLine, ...]`
  - `frame: CubeFrame` (at the export cell)
  - `z: ZAxis` (the grid's own axis)
  - `finish: FinishSettings` (in metres)
  - `spacing_m: float`
  - `gain: float`
  - `world_to_frame: Callable[[np.ndarray], np.ndarray] | None` (None when the frame shares the
    output CRS)
- `@dataclass(frozen=True) ExportSpec`:
  - `grids: tuple[ExportGrid, ...]`
  - `lattice: SiteLattice` (the output at the export pixel)
  - `windows: tuple[tuple[float, float], ...]` (each band's `(top_ns, thickness_ns)` on the site
    axis)
  - `method: str` (normalisation; `"none"` for This grid)
  - `coverage: bool`
- `estimate_export(spec) -> ExportEstimate`:
  - fields `held_bytes`, `file_bytes` (uncompressed, overviews included) and `per_band` (a dict of
    the parts);
  - all through `estimate_memory` and `covered_cells`, plus fill weights at `WEIGHT_BYTES_PER_CELL`,
    taps at 52 B per covered output pixel (`covered_pixels`) and one band's accumulators;
  - binning picks stream or packed cube per grid by `choose_residency` on that estimate.
- `run_export(spec, *, should_stop: Callable[[], bool], progress: Callable[[int, int, str], None]) -> Iterator[ExportBand]`:
  - `ExportBand` holds `array: np.ndarray` (float32 on `spec.lattice`) and
    `factors: dict[str, tuple[float, float]]`.
  - Order of work: band by band. Seams are found once at the export frames. Each band is binned for
    every grid, `normalise(method, binned, seams, gains)` runs on the BINNED values, then each grid
    is finished (kriging or IDW through `plan_fill`/`finish_slice`, minimum curvature through
    `CurvaturePlan.solve(values, should_stop)` and `smooth`) and the result is composed with
    `compose_footprints(spec.lattice, …, counts=spec.coverage)`.
  - `should_stop` is checked between grids and inside the curvature solve, raising
    `ExportCancelled` (re-export the existing one from `slice_export`, or move it here).
  - `progress(band_index, n_bands, grid_id)` is called before each grid of each band.
- `export_refusal(held_bytes: int, budget: int, finest_cell: float | None, finest_pixel: float | None) -> str`
  in `slices_plan.py`. Exact copy:
  `f"This export would hold about {format_bytes(held_bytes)} in memory, more than the {format_bytes(budget)} it is allowed."`
  then `f" A {finest_cell:g} m export cell would fit."` when a cell is given, then
  `f" A {finest_pixel:g} m export pixel would fit."` when a pixel is given.

- [ ] **Step 1: Write the failing tests.**
  - `test_frame_lattice_at_the_cell_reproduces_an_axis_aligned_grid`.
  - `test_frame_lattice_at_half_the_cell_doubles_the_pixels`.
  - `test_export_at_the_live_cell_equals_the_live_composition`: a synthetic two-grid site (one
    rotated, edge match) built with the same core calls as `SiteEngine.slice_at`. Values to 1e-5,
    NaN in the same places, factors equal.
  - `test_export_at_a_finer_cell_measures_normalisation_again`: factors at the export cell differ
    from the live ones where the binned data differs. Pins decision 3.
  - `test_manual_gains_are_carried_as_typed` (decision 11).
  - `test_coverage_export_holds_whole_counts`.
  - `test_should_stop_cancels_within_one_grid`: progress is called with `(k, n, grid)`, and
    `ExportCancelled` is raised before the next grid runs.
  - `test_a_grid_in_another_crs_is_transformed_before_sampling`: a fake `world_to_frame` shifts by a
    known offset.
  - `test_the_estimate_counts_weights_taps_and_one_band` and
    `test_an_export_over_budget_is_refused_with_the_finest_fit` (exact copy).
  - `test_the_pipeline_never_reads_cube_mean` (a contract test: a `SliceCube` subclass whose `mean`
    raises).
  - Real data first: where the local DZT files are present, one test exports the ten local lines'
    grid at 0.05 m and at 0.025 m and checks finite coverage. Skip when they are absent.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement** to the interfaces. `run_export` composes through the existing core
  functions only; no new numerics.
- [ ] **Step 4: Measure, then set `EXPORT_BUDGET_BYTES`.**
  - Extend `packages/nsgeo-qgis/scripts/bench_site.py` with `--export CELL PIXEL`.
  - On the walkthrough site's geometry (ten grids, 4–10° and near 90°; synthetic lines laid like
    real ones), at cell 0.025 m with pixel 0.025 and 0.0125, and at cell 0.05 m with pixel 0.05,
    record:
    - peak memory (tracemalloc plus array sizes);
    - time per band, for kriging and for minimum curvature;
    - the estimate against the measured value.
  - Choose band by band if, at those settings, it fits `DEFAULT_BUDGET_BYTES` (1.5 GB). Set
    `EXPORT_BUDGET_BYTES` to that. Otherwise report: grid by grid needs an accumulate-on-disk
    design that is not in this plan.
  - Write the table and the decision in the module docstring (spec §6.2: "measured, then chosen").
- [ ] **Step 5: Run** the pure, core and display tests, plus lint. All pass.
- [ ] **Step 6: Commit:** `feat(export): a Qt-free export pipeline at any cell and pixel, with a memory budget`.

---

