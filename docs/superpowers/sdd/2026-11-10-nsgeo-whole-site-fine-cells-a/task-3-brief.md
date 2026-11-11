### Task 3: Whole site composes with the bilinear rule; half pitch retires

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/slices/site.py`:
  - `Footprint` (~178), `footprint` (~208) and `compose_footprints` (~230);
  - delete `compose`, `lattice_pixel`, `snap_azimuth`, `AXIS_SNAP_CELLS` and
    `_RIGHT_ANGLE_TOL_DEG`;
  - update the module docstring.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` (exports).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`:
  - imports;
  - `_covering_lattice` (~711) uses `res.cell` as the pixel;
  - `_gather` (~831) builds taps;
  - `slice_at` passes `counts=coverage`;
  - the half-pitch sentence in `_rebuild_geometry`'s refusal goes. Task 4 replaces the refusal.
- Modify: `packages/nsgeo-qgis/scripts/bench_site.py`: its docstring's half-pitch sentence.
- Test: `packages/nsgeo-core/tests/test_slices_site.py`: lines ~122–245 (lattice pixel, compose,
  footprint) and ~605.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py`: ~955–1035, and the cross-zone
  test at ~915.

**Interfaces:**
- Consumes: Task 1's `Taps`, `bilinear_taps`, `sample` and `sample_counts`.
- Produces:
  - `Footprint(row0: int, row1: int, col0: int, col1: int, taps: Taps)`, where `taps.n ==
    (row1 - row0) * (col1 - col0)`, row-major over the window.
  - `footprint(taps: Taps, rows: int, cols: int, row0: int = 0, col0: int = 0) -> Footprint`: the
    tight window around the points with `taps.inside`, built with `taps.take`. Empty when there are
    none, at `(row0, col0)`.
  - `compose_footprints(lattice: SiteLattice, layers: Sequence[tuple[Footprint, np.ndarray]], *,
    counts: bool = False) -> np.ndarray`: float32 `(height, width)`. Each layer is sampled with
    `sample`, or `sample_counts` when `counts`. Overlapping grids take the mean of their finite
    values, NaN where none. Accumulate in float32 with a uint8 count (spec §5.2). Raise
    `ValueError` for a window off the lattice, as today.

- [ ] **Step 1: Rewrite the core site tests.**
  - Delete `test_lattice_pixel_is_the_cell_for_right_angles_and_half_for_anything_else` and every
    `compose(`-based test.
  - Replace them with tests built from `bilinear_taps` over `lattice.pixel_centres()`:
    - `test_footprint_compose_samples_each_grid_bilinearly`: one rotated layer equals `sample`
      over the whole lattice, reshaped, to float32 tolerance 1e-6;
    - `test_footprint_compose_still_averages_overlapping_layers`;
    - `test_compose_counts_takes_whole_counts_within_a_grid` (with `counts=True`);
    - `test_a_footprint_is_the_tight_window_around_every_inside_point`;
    - keep `test_compose_footprints_refuses_a_window_off_the_lattice`.
  - Update `test_real_halves_at_different_azimuths_compose_and_find_their_seam` (~605) to build
    its footprints with taps.
- [ ] **Step 2: Rewrite the QGIS site-engine pins.**
  - `test_a_rotated_site_composes_exactly_as_whole_lattice_gathers_would` becomes
    `test_a_rotated_site_composes_each_grid_bilinearly`. Expected = the mean, over grids, of
    `sample(shown[g], bilinear_taps(frame_g, centres))`, compared with tolerance 1e-5 and NaNs in
    the same places. Assert `lattice.pixel == RES.cell`.
  - Delete `test_a_refusal_with_a_rotated_grid_names_the_half_cell_pitch` and
    `test_a_grid_a_hair_off_north_keeps_the_full_cell_pitch`.
  - Add `test_the_site_pixel_is_the_cell_at_any_bearing`, parametrised over B's azimuth in
    `[0, 1e-6, 2.0, 30.0]`.
  - Keep `test_grids_too_far_apart_for_the_lattice_are_refused_by_pixel_count` for now. Task 4
    rewrites it.
  - Add `test_coverage_on_the_site_is_whole_counts`: a coverage tick holds only values of the
    grids' own counts, or their overlap means.
  - The cross-zone test must still pass unchanged apart from pitch numbers.
- [ ] **Step 3: Run and see them fail.**
- [ ] **Step 4: Implement** per the interfaces.
  - `_gather` computes the window as today, at the cell pitch. The centres are transformed into the
    frame's CRS when it differs, then go to `bilinear_taps` and `footprint(taps, rows, cols, row0,
    col0)`.
  - `SiteEngine` keeps its gather cache keyed as today.
  - In `slice_at`: `compose_footprints(lattice, [...], counts=coverage)`.
- [ ] **Step 5: Run** `test_slices_site.py`, `test_plugin_site_engine.py`,
  `test_plugin_site_scope.py` and `test_plugin_site_export.py`, plus lint. All pass. Run `bench_site.py --azimuths 0 30` and note one tick's time at
  each bearing in the commit body.
- [ ] **Step 6: Commit**: `feat(site): compose bilinear at the cell size; retire half pitch`.

---

