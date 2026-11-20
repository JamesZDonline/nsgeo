### Task 5: #75 Site engine, the rest: mixed CRS, test gaps, the module split

**Already gone, verified while planning (at 3104edb):**
- **`_azimuth_in`'s cross-CRS result is untested:** `_azimuth_in` was removed in 0776c4d (fine
  cells A: bilinear at the cell size).
- **F-9:** `SlicesDock._resume_grid` hands the hook back from a `finally`.

**Changed by M17a:** the site CRS is now `session.site_crs()`, the site's own CRS once set, else the
first grid's (`P/site_engine.py:_site_crs`). Check what is left of "the site CRS follows the first
grid only as of the last rebuild":
- for a site with its own CRS, nothing;
- for an older site, a removed first grid already rebuilds through `_on_grids_changed`.

Then document or fix, and record which in the report.

**Files:**
- Create: `P/site_geometry.py`
- Modify: `P/site_engine.py` (use it; remove the moved code)
- Modify: `P/site_export.py` (`world_to_frame` uses `transform_points`)
- Test: `T/qgis/test_plugin_site_geometry.py` (new), `T/qgis/test_plugin_site_engine.py`,
  `T/qgis/test_plugin_slices_engine.py`

**Interfaces:**
- **Produces, in `P/site_geometry.py`:**
  - `EDGE_POINTS = 8`, moved from `_EDGE_POINTS`.
  - `transform_points(points: np.ndarray, source: str, target: str, context: QgsCoordinateTransformContext) -> np.ndarray`.
    It takes (n, 2) points to (n, 2) and raises `RuntimeError(f"no coordinate transform from {source} to {target}")`
    when the transform isn't valid.
    - **One C++ call.** Pack the points as a little-endian WKB LineString with numpy
      (`struct.pack("<BII", 1, 2, n)` + the float64 pairs), `QgsGeometry.fromWkb`,
      `geometry.transform(ct)`, then read back with `np.frombuffer(bytes(g.asWkb()), "<f8",
      offset=9)`.
    - n = 0 returns an empty (0, 2) array, and n = 1 pads to two points.
    - Measured while planning: 200 k points took 0.92 s one at a time and 0.10 s this way, with
      identical results.
  - `extent_in(frame: CubeFrame, crs: str, context) -> tuple[float, float, float, float]`, moved
    from `SiteEngine._extent_in`.
  - `gather_footprint(frame: CubeFrame, lattice: SiteLattice, context) -> Footprint`: the body of
    `SiteEngine._gather` after its cache check, moved.
- `SiteEngine._gather` keeps its cache and calls `gather_footprint(frame, lattice,
  QgsProject.instance().transformContext())`. `SiteEngine._transform` and `_extent_in` are removed;
  their callers use the module.
- `site_export.world_to_frame` keeps its signature and thread-safety: a fresh transform on each
  call, through `transform_points`.

- [ ] **Step 1: Write the failing tests**
  - **`T/qgis/test_plugin_site_geometry.py`:**
    - `test_transform_points_matches_one_point_at_a_time`. 1,000 points, EPSG:32616 → EPSG:32617
      and → EPSG:4326, each equal to a per-point `QgsCoordinateTransform.transform` to 1e-9.
    - `test_transform_points_handles_none_and_one_point`. Shapes are (0, 2) and (1, 2), and the
      value is right.
    - `test_transform_points_refuses_a_missing_transform`. An invalid CRS string raises
      RuntimeError with "no coordinate transform from".
    - `test_transform_points_is_one_call_not_one_per_point`. Time 100 k points through
      `transform_points` and through a per-point loop in the test itself, on the same machine. The
      first is at least 3× faster. This is relative, so load slows both.
  - **`T/qgis/test_plugin_site_engine.py`:**
    - `test_a_mixed_crs_site_gathers_the_same_after_the_move`. Build a site with C in a
      neighbouring UTM zone through `site3_factory`'s `crs` option (see its docstring for the
      form). C's gather (`site._gather("C", site.lattice)`) has taps equal to
      `bilinear_taps(frame, centres)`, where the test moves the same window's pixel centres one
      point at a time with `QgsCoordinateTransform.transform`.
    - `test_a_preparation_that_reads_no_line_fails_with_the_first_error` (the asynchronous failure
      path). `Line.load` raises `OSError("disk gone")` for grid B's lines only. B reads
      `failed: …disk gone…`, and A and C are ready.
  - **`T/qgis/test_plugin_slices_engine.py`:** `test_the_hook_can_be_given_to_the_constructor`
    disposes its second engine as well, in `finally`. That's an edit, not a new test.

- [ ] **Step 2: Run them and see them fail.** The geometry tests fail with ImportError. The failure
  path test, if it passes at once, is recorded as "was untested, now pinned" (#75's test gap).

- [ ] **Step 3: Implement** the module and the moves. The rest of the engine's items:
  - **The geometry rebuild inside the `grids_changed` emission:** either document the assumption in
    `_on_grids_changed`'s docstring, or defer the rebuild with `QTimer.singleShot(0, …)` behind a
    guarded slot. Record the choice and the reason in the report. Deferring changes when
    `geometry_problem` is set, so if you defer, show that no test reads it inside the same
    emission.
  - Afterwards, `wc -l packages/nsgeo-qgis/nsgeo_qgis/site_engine.py` is smaller by the moved code.
    Record the number.

- [ ] **Step 4: Run** the geometry, engine, export and site-scope test files, `-m real_data`, and
  ruff. Expected: all pass, except a #196 flake (note it).

- [ ] **Step 5: Commit and push:** `refactor(site): CRS, outline and gather helpers in site_geometry; one-call transforms; failure-path test (#75)`.

---


**Added by the controller after Task 4's review (M2):** `site_engine.py`'s `_limit_windows_ns`
(~line 1222) still rounds levels itself, `max(1, int(round(thickness_ns / z.dz_ns)))`. Make it call
`slices_plan.window_levels` (Task 4 added it), so #75's "level rounding written twice" is fully
cleared. Behaviour must not change; `test_window_levels_rounds_and_floors_at_one` pins the rounding.
