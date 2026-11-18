### Task 1: The surface builder (core)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/surface.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/volume.py`: add `PreparedVolume.swing(j0, j1)`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py`, `packages/nsgeo-core/README.md`, `packages/nsgeo-core/tests/test_public_api.py`
- Modify: `packages/nsgeo-core/tests/real_lines.py`: move `_squared_volume` here from `test_slices_volume.py` as `squared_volume()`, cached the same way, and import it back there
- Test: `packages/nsgeo-core/tests/test_slices_surface.py`

**Interfaces:**
- Consumes: `PreparedVolume`, `prepare_volume`, `VolumeSettings` (`nsgeo.slices.volume`); `plan_curvature` (`nsgeo.slices.curvature`); `smooth` (`nsgeo.slices.smooth`).
- Produces, all exported from `nsgeo.slices`:
  - **Constants:**
    - `JOINS = ("min_curvature", "idw")`;
    - `HULL_MARGIN_M = 0.3`, `OFFSET_SEARCH_M = 0.05`, `JUMP_M = 0.06`, `JOIN_REACH_M = 2.0`;
    - `IDW_MIN_DISTANCE_M = 0.05`, with IDW power 2;
    - `FIT_CLOSE_M = 0.02`, `FIT_NEAR_M = 0.05`.
  - **`SurfaceSettings(join="min_curvature", window_m=0.02, strength=1.0, smoothing_m=0.0)`:**
    - frozen;
    - validated: `join` in `JOINS`, `window_m` finite and > 0, `strength` and `smoothing_m` finite and ≥ 0;
    - `to_dict()`, and `from_dict(doc)`, which lays valid fields over the defaults and ignores the rest, as `VolumeSettings.from_dict` does.
  - **`picks_span_an_area(x_m, y_m, *, tolerance_m=0.01) -> bool`:** False for fewer than 3 points, or when every point lies within `tolerance_m` of the line through the two farthest apart.
  - **`surface_volume(filled, z, velocity, cell, settings: VolumeSettings, *, slab_levels=64, progress=None) -> PreparedVolume`:** `prepare_volume` with `blur_m=0.0` (call 17).
  - **`PreparedVolume.swing(j0, j1) -> np.ndarray`:** the filled squared amplitude on the uniform depth axis, levels `j0..j1`, `(j1 - j0, ny, nx)` float32. It is interpolated between source levels as `_amplitude` does, and is NaN off `covered`.
  - **`build_surface(vol, x_m, y_m, depth_m, settings, *, max_levels=64) -> Surface`:**
    - `x_m` and `y_m` are frame-local metres; `depth_m` is on the volume's depth scale.
    - It raises ValueError when:
      - `vol.settings.blur_m != 0`;
      - the lengths differ;
      - a depth is not finite;
      - `picks_span_an_area` is False.
  - **`Surface`** (frozen):
    - `depth_m` (ny, nx) float32, NaN for a hole or outside the region;
    - `strength` (ny, nx) float32;
    - `guide_m` (ny, nx) float32, the joined picks, NaN outside the region;
    - `region` (ny, nx) bool;
    - `offset_m: float`: the median of swing minus pick, so > 0 means the picks sit above the swing;
    - `cell: float`;
    - `fit: SurfaceFit`.
  - **`SurfaceFit`** (frozen): `within_close`, `within_near`, `further`, `on_holes: int`, and `outliers: tuple[Outlier, ...]`, in input order.
  - **`Outlier(index: int, picked_m: float, surface_m: float | None)`:** `None` means the pick is on a hole.
  - **`surface_mesh(depth_m, cell, jump_m=JUMP_M) -> tuple[points (n, 3) float64 as x, y, depth; triangles (m, 3) int64; cells (n,) int64 flat ids]`**

**The algorithm** follows spec §5.3 and the trial's `build_features.py`. These are the details the signatures leave open:
- **A pick's cell** is `(floor(y / cell), floor(x / cell))`. A pick outside the frame takes no part in the guide or the offset, and the fit counts it on a hole.
- **The region** is the counter-clockwise convex hull of the in-frame picks, grown by `HULL_MARGIN_M`, intersected with `vol.covered`. A cell is inside when its signed distance to every hull edge is at least −0.3 m (the trial's `inside_hull`).
- **The guide:**
  - For `min_curvature`: the mean pick depth per cell, then `plan_curvature(populated, cell, JOIN_REACH_M).apply(values)`. Where that is NaN, the mean pick depth is used.
  - For `idw`: weights of `1 / max(distance, IDW_MIN_DISTANCE_M)**2` over every in-frame pick, at the cell centres.
- **The offset** is measured on the swing (squared amplitude). In each pick's own covered cell, take the levels within `OFFSET_SEARCH_M` of the pick, take the refined argmax, and subtract the pick depth. The offset is the median of these. A pick with no level in reach is left out, and with none at all the offset is 0.0.
- **Tracking, in each region cell:**
  1. The target is the guide plus the offset.
  2. Among the levels within `window_m` of the target, take the swing's argmax (NaN counts as −inf).
  3. Refine that depth, and clamp it to the target ± window.
  4. Keep the cell when `strength[k] >= settings.strength` at the integer level `k`; otherwise it is a hole. A cell with no level in its window is a hole.
- **The 3×3 median:** a `nanmedian` over the kept cells only, written only to kept cells. Then subtract the offset. Then, if `smoothing_m > 0`, apply `smooth(depth, cell, s, s)`.
- **Memory.** Read the volume in slabs of at most `max_levels` levels, covering only the depths the offsets and windows touch plus one level either side. Keep only the region's columns. Never hold a whole cube.
- **The fit** compares each pick with the surface in its cell: on a hole; within 2 cm; within 5 cm; or further. Outliers are picks on a hole or more than `window_m` away.
- **The mesh** has a vertex at every kept cell centre, `((ix + 0.5) * cell, (iy + 0.5) * cell, depth)`. Each quad gives two triangles, as the trial's `mesh`: (dy, dx) offsets (0,0),(0,1),(1,1) and (0,0),(1,1),(1,0). A triangle is dropped when a vertex is missing or its depth spread exceeds `jump_m`.

- [ ] **Step 1: Write the failing synthetic tests** in `test_slices_surface.py`. The fixture `_dipping()` has these parts:
  - **The frame:** 40 × 30 cells at 0.1 m, `ZAxis.from_range(0.0, 40.0, 0.1)`, and `VelocityModel.constant(0.1)`, so depth is 0.05 × t.
  - **The reflector:** squared amplitude of a Ricker wavelet with a 2.5 ns period, centred at depth `0.5 + 0.01 * x`, on a floor of 1e-4.
  - **A weak patch:** cells x 2.0–2.5 m, y 1.0–1.5 m, at 0.02 × the amplitude.
  - **An uncovered strip:** the last 3 columns, all NaN.

  The volume is `surface_volume(...)`. Picks sit 2 cm above the swing at 12 cells spread over x 0.5–3.5 m and y 0.5–2.5 m.

  The tests:
  - `test_settings_defaults_validation_and_round_trip`: the defaults are `("min_curvature", 0.02, 1.0, 0.0)`; `join="kriging"` raises; `from_dict({"window_m": -1, "strength": 2})` gives window 0.02 and strength 2.0.
  - `test_build_refuses_a_blurred_volume`: a `prepare_volume` with `blur_m=0.1` raises ValueError.
  - `test_fewer_than_three_or_collinear_picks_are_refused`: 2 picks raise, 5 picks on one line raise, and `picks_span_an_area` agrees.
  - `test_surface_follows_a_dipping_reflector_and_returns_to_the_picks`: `abs(offset_m - 0.02) <= 0.005`. Every kept cell outside the weak patch is within 0.005 m of `0.5 + 0.01 * x - 0.02`. `fit.within_close == 12`.
  - `test_weak_patch_is_a_hole_and_the_median_never_fills_it`: every cell of the patch is NaN. A single weak cell surrounded by kept cells also stays NaN.
  - `test_uncovered_cells_are_outside_the_region`
  - `test_tracking_never_leaves_its_window`: add a reflector 3× stronger, 4 cm below. The surface stays within `window_m + one depth step` of `guide_m` everywhere.
  - `test_refinement_finds_a_peak_between_levels`: centre the wavelet halfway between two levels. Kept depths are within 0.1 × the step of the truth.
  - `test_a_pick_outside_the_depth_range_or_frame_is_reported_not_fatal`: add one pick at depth −0.01, one 0.5 m below the last level and one at x = −1. The build succeeds, all three are outliers with `surface_m is None`, and the other picks are unchanged.
  - `test_a_surface_with_no_cell_passing_is_empty_not_an_error`: with `strength=1e9`, `depth_m` is all NaN, `on_holes == 12`, and `surface_mesh` returns 0 points and 0 triangles.
  - `test_mesh_never_joins_cells_more_than_6_cm_apart`: a hand-made 3×3 depth grid with one step of 0.07 m.
  - `test_smoothing_is_off_by_default_and_never_fills_holes`

- [ ] **Step 2: Write the failing real-data tests** (`@needs_real_files`). Use `squared_volume()` from `tests/real_lines.py`, made into a surface volume with `surface_volume`.

  The fixture `_reflector_picks(vol)`:
  1. Take the depth level below 0.3 m where the largest share of covered cells on the data rows (`y = 0.25 + 0.5 i`) have strength ≥ 1.5.
  2. Then, at 15 cells on those rows between x = 4 and x = 16 m, take the refined swing peak within ±0.05 m of that level.

  These 15 points are "picks on a real reflector".

  The tests:
  - `test_real_picks_on_a_reflector_land_within_2_cm`: every pick whose cell is kept is within 2 cm, and at least 12 of 15 are kept.
  - `test_real_holes_are_where_strength_fails`: every kept cell has `strength >= settings.strength`. Raising the test to 2.0 leaves no fewer holes.
  - `test_real_surface_never_leaves_its_window`: as in the synthetic test.
  - `test_real_one_ns_shift_is_recovered_as_the_offset`: shift every pick 0.0355 m up (1 ns at 0.071 m/ns). The offset grows by 0.0355 ± 0.005, and the kept depths at the pick cells move with the picks.
  - `test_real_pick_on_another_reflection_is_reported`: one pick moved 0.15 m deeper is listed in `fit.outliers`.
  - `test_real_joins_differ_as_described`:
    - the `min_curvature` guide equals the binned pick depth at every populated cell (±1e-6);
    - the `idw` guide's sum of squared second differences over the region exceeds the `min_curvature` guide's (it spikes at each pick).

- [ ] **Step 3: Run them and see them fail.** Run `test_slices_surface.py` with the core command. Expect `ImportError` on `nsgeo.slices.surface`.
- [ ] **Step 4: Implement** `surface.py` and `PreparedVolume.swing`. Update the exports, the core README tables and `EXPECTED_PUBLIC`.
- [ ] **Step 5: Run the tests, `test_slices_volume.py`, `test_public_api.py`, ruff and mypy.** All pass.
- [ ] **Step 6: The parity check on the trial's data.** Do not commit any of it. Write `~/nsgeo-m4-check/m16-paraview-trial/core_parity.py`:
  - **Input:** it loads `filled_hq.npy` (455 × 320 × 400, `t0 = -0.476` ns, `dz = 0.1` ns, 0.071 m/ns, 0.05 m cells) and the 88 bowl picks, exactly as `build_features.py` reads them.
  - **The build:** `build_surface` with `min_curvature`.
  - **The output:** the fit, the offset, and whether the south-west picks (lines 23–24) sit on holes.

  Its acceptance is spec §7: **at least 82 of 88 within 2 cm**, and the offset about 3.6 cm. If it misses, call 17 rules: change the recipe until it meets the trial's numbers, and record what changed in the report. Put the printed numbers in the report, not in the repo.
- [ ] **Step 7: Commit and push.** `feat(core): the surface builder from picks (M16 B)`.

---

