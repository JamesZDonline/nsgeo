### Task 1: Core — `nsgeo.slices.site`

All numpy, no I/O. It implements the spec's §4.3 window mapping, §4.6 normalisation, §4.6.1
seams and §4.7 lattice.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/site.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` (re-export every name below)
- Test: `packages/nsgeo-core/tests/test_slices_site.py`

**Interfaces:**
- Consumes: `CubeFrame` (`axes`, `to_local`, `cell_index`, `nx`, `ny`, `cell`, `crs`, `azimuth`),
  `slice_extent`, `ZAxis`, `SliceWindow`.
- Produces:
  - `NORMALISATION_METHODS = ("none", "background", "edge", "histogram")`,
    `BACKGROUND_FRACTION = 0.75`, `SEAM_WIDTH_SPACINGS = 1.5`, `MIN_SEAM_CELLS = 20`
  - `@dataclass(frozen=True) class SiteLattice: x0: float; y1: float; pixel: float; width: int;
    height: int; crs: str`. `x0` is the west edge and `y1` the north edge, both whole multiples of
    `pixel`. It provides:
    - properties `geotransform -> tuple[float, ...]`, which is `(x0, pixel, 0.0, y1, 0.0, -pixel)`,
      and `n_pixels -> int`;
    - `pixel_centres() -> np.ndarray`, shaped `(height * width, 2)`, row-major with row 0 at the
      north;
    - `@classmethod covering(extents: Sequence[tuple[float, float, float, float]], pixel: float,
      crs: str) -> SiteLattice`, where extents are `(xmin, ymin, xmax, ymax)` already in `crs`. It
      raises `ValueError` on an empty sequence or a non-positive pixel. Width and height use
      `to_north_up`'s scale-aware epsilon snapping (`display.py`), so no phantom row appears.
  - `lattice_pixel(cell: float, azimuths: Iterable[float]) -> float`, per Ruling 2. It counts an
    azimuth as a multiple of 90° within `1e-9` degrees.
  - `compose(lattice: SiteLattice, layers: Sequence[tuple[np.ndarray, np.ndarray]]) -> np.ndarray`.
    Each layer is `(ids, values)`, where:
    - `ids` is `(n_pixels,)` from `frame.cell_index(centres)`, with -1 outside the frame;
    - `values` is the frame's `(ny, nx)` array.

    It returns a `(height, width)` float32 array. Each pixel is the mean of the finite values that
    cover it, and NaN where none do.
  - `site_axis(bounds: Iterable[tuple[float, float]], t0_ns: float, t1_ns: float, dz_ns: float)
    -> ZAxis | None`. This is the union of the grids' `(start, end)` time bounds, clipped to
    `[t0_ns, t1_ns]`, built with `ZAxis.from_range`. It returns None when nothing remains.
  - `grid_axis(site_z: ZAxis, bounds: tuple[float, float]) -> ZAxis | None`. This returns the
    levels of `site_z` that lie inside `bounds`, on `site_z`'s own lattice: `t0 = site_z.t0_ns + k·dz`
    with `k = ceil((start − site_z.t0_ns)/dz − 1e-6)`, and the same tolerance on the far end.
    It returns None when no level is inside.
  - `window_on(z: ZAxis, top_ns: float, thickness_ns: float) -> SliceWindow | None`. This is
    **the one place a site window becomes a grid window**; lining up by depth after M13 replaces
    this body. It works as follows:
    - `k0 = floor((top_ns − z.t0_ns)/z.dz_ns + 1e-6)` and
      `k1 = k0 + max(1, round(thickness_ns / z.dz_ns))`.
    - It returns None when `k1 <= 0` or `k0 >= z.nz`.
    - Otherwise it returns `SliceWindow(max(0, k0), min(k1, z.nz))`.

    The `1e-6` snap matters: without it, a grid axis offset from the site axis by a whole number of
    levels floors one level low at some slider positions.
  - `@dataclass(frozen=True) class Seam: a: str; b: str; mask_a: np.ndarray; mask_b: np.ndarray`.
    The masks are boolean, shaped `(ny, nx)` for their own frame, and already restricted to
    populated cells. `a < b`.
  - `seam_masks(frame_a: CubeFrame, frame_b: CubeFrame, width_m: float) -> tuple[np.ndarray,
    np.ndarray]`. This is geometry only. It finds the cells whose centre lies within `width_m` of
    the other frame's footprint rectangle, with distance measured in the other frame's local
    coordinates (0 inside). It returns all-False when the CRSs differ.
  - `find_seams(frames: Mapping[str, CubeFrame], coverages: Mapping[str, np.ndarray],
    spacings: Mapping[str, float], *, width_spacings: float = SEAM_WIDTH_SPACINGS,
    min_cells: int = MIN_SEAM_CELLS) -> tuple[Seam, ...]`.
  - `background_level(values: np.ndarray, coverage: np.ndarray, mask: np.ndarray | None = None)
    -> float | None`. It takes `|values|` over cells where `coverage > 0` (and `mask`), keeps the
    weakest `BACKGROUND_FRACTION` of them, and returns their mean. It returns None when no cell
    qualifies or the result is not positive.
  - `edge_match_solve(levels: Mapping[str, float | None], seam_levels: Sequence[tuple[str, str,
    float, float, float]]) -> dict[str, float]`. Each seam term is `(a, b, S_ab, S_ba, weight)`. The
    function returns a gain for every key of `levels`.
  - `normalise(method: str, slices: Mapping[str, tuple[np.ndarray, np.ndarray]], seams:
    Sequence[Seam] = (), manual: Mapping[str, float] | None = None) -> dict[str, tuple[float,
    float]]`. `slices` maps grid id to `(values, coverage)`, binned and unfilled. The result is an
    affine `(a, b)` per grid, applied as `a·v + b`, with the manual multiplier `m` already folded in
    as `(m·a, m·b)`. Method `"none"` gives `(m, 0)`. An unknown method raises `ValueError`.

- [ ] **Step 1: Write the failing tests** in `test_slices_site.py`. Use synthetic frames and arrays
  unless marked real. The assertions:

```python
def test_lattice_is_anchored_on_whole_multiples_of_the_pixel():
    lat = SiteLattice.covering([(500.13, 700.07, 506.0, 706.2)], 0.25, "EPSG:32616")
    assert lat.x0 == 500.0 and lat.y1 == 706.25          # floor / ceil to the pixel
    assert lat.geotransform == (500.0, 0.25, 0.0, 706.25, 0.0, -0.25)
    assert (lat.width, lat.height) == (24, 25)

def test_lattice_covers_the_union_and_has_no_phantom_row_at_utm_scale(): ...
    # two extents 20 m apart at x ~ 5e5: width == exact span / pixel, no +1

def test_pixel_centres_run_row_major_from_the_north(): ...
    # centres[0] == (x0 + p/2, y1 - p/2); centres[width] == (x0 + p/2, y1 - 3p/2)

def test_an_axis_aligned_frame_loses_no_cell_at_pixel_equal_to_cell():
    # frame offset by (0.37 cell, 0.81 cell); every cell id appears in cell_index(centres)
def test_a_rotated_frame_loses_cells_at_pixel_equal_to_cell():
    # azimuth 33 deg: some ids missing -- documents why Ruling 2 exists
def test_a_rotated_frame_loses_no_cell_at_half_pitch():
    # azimuths 7, 33, 45, 78 deg: every id appears with lattice_pixel(cell, [az]) == cell / 2

def test_lattice_pixel_is_the_cell_for_right_angles_and_half_for_anything_else():
    assert lattice_pixel(0.25, [0.0, 90.0, 270.0]) == 0.25
    assert lattice_pixel(0.25, [0.0, 2.0]) == 0.125

def test_compose_averages_overlaps_and_leaves_uncovered_pixels_nodata(): ...
def test_compose_of_one_layer_is_that_layer_resampled(): ...

def test_site_axis_is_the_union_clipped_to_the_requested_range(): ...
def test_grid_axis_shares_the_site_lattice_of_levels(): ...
    # grid bounds start 7 levels in: grid_z.t0_ns == site_z.t0_ns + 7 * dz (to 1e-9)

def test_window_on_agrees_with_the_site_axis_at_every_slider_position():
    site = ZAxis(t0_ns=-3.1, dz_ns=0.2165, nz=400)
    grid = grid_axis(site, (site.t0_ns + 7 * 0.2165, site.t0_ns + 300 * 0.2165))
    for v in range(7, 300):
        w = window_on(grid, site.t0_ns + v * site.dz_ns, 4 * site.dz_ns)
        assert w is not None and w.k0 == v - 7

def test_window_on_is_none_only_when_no_level_overlaps():
    z = ZAxis(t0_ns=10.0, dz_ns=0.5, nz=20)                  # 10.0 .. 19.5 ns
    assert window_on(z, 7.0, 2.0) is None                   # ends before 10.0
    assert window_on(z, 9.0, 2.0) == SliceWindow(0, 2)      # overhangs the start: thinner
    assert window_on(z, 19.5, 2.0) == SliceWindow(19, 20)
    assert window_on(z, 20.0, 2.0) is None

def test_seam_masks_find_the_strips_either_side_of_a_shared_edge(): ...
    # A = [0,5]x[0,5], B = [5,10]x[0,5], cell 0.25, width 0.75: mask_a is exactly columns 17..19
def test_seam_masks_still_find_a_seam_two_degrees_off_parallel(): ...
def test_seam_masks_are_empty_for_frames_in_different_crs(): ...
def test_find_seams_needs_min_cells_on_both_sides(): ...
    # populate only 19 cells on B's side -> no seam; 20 -> one Seam("A", "B", ...)

def test_background_level_is_the_mean_of_the_weakest_three_quarters():
    v = np.arange(1, 9, dtype=float).reshape(2, 4); c = np.ones_like(v, dtype=int)
    assert background_level(v, c) == pytest.approx(np.mean([1, 2, 3, 4, 5, 6]))
def test_background_level_ignores_unpopulated_cells_and_is_none_when_empty(): ...
def test_background_level_measures_magnitude_on_signed_data():
    v = np.array([[-8.0, 1.0, -2.0, 3.0]]); c = np.ones_like(v, dtype=int)
    assert background_level(v, c) == pytest.approx(2.0)      # weakest 3 of |v| = 1, 2, 3

def test_background_gains_have_geometric_mean_one_and_recover_a_known_gain(): ...
def test_edge_match_recovers_known_gains_along_a_chain_and_agrees_with_pairwise(): ...
def test_edge_match_spreads_a_loop_closure_error_that_pairwise_dumps_on_the_last_seam():
    # 2x2 block A-B, B-D, D-C, C-A with seam ratios multiplying to 1.21 around the loop.
    # Global: max |residual| < 0.6 * the sequential chain's residual on the closing seam.
    # The sequential chain is written in the TEST (helper), not in production code.
def test_each_connected_group_is_anchored_to_the_site_background(): ...
def test_an_isolated_grid_takes_its_background_gain(): ...
def test_histogram_match_gives_every_grid_the_pooled_mean_and_std(): ...
def test_the_manual_multiplier_composes_with_every_method(): ...
    # for m in NORMALISATION_METHODS: normalise(m, s, seams, {"A": 2.0})["A"] == 2 x the m=1 result
def test_normalise_refuses_an_unknown_method(): ...

@needs_real_files
def test_real_split_background_and_edge_recover_a_depth_dependent_gain_exactly(): ...
@needs_real_files
def test_real_split_histogram_hits_the_pooled_moments(): ...
@needs_real_files
def test_real_halves_at_different_azimuths_compose_and_find_their_seam(): ...
    # spec §9 "mixed azimuths": B's frame and its lines rotated 2 deg about the shared corner
    # (real data, invented placement). find_seams still finds Seam("A", "B");
    # lattice_pixel(...) == cell / 2; compose places every populated cell of both frames.
```

  How the real-data tests are built:
  - Prepare all ten real lines the way `test_real_files.py::test_a_cube_binned_from_real_files_is_covered_and_finite`
    does: same five steps, lines along x, `y = 0.25 + i·0.5`.
  - Lines 0–4 go in frame A, `origin (0, 0)`, `ny = 13` at cell 0.2. Lines 5–9 go in frame B,
    `origin (0, 2.6)`, with their `y` shifted by 2.6.
  - Use one axis, `ZAxis.from_range(1.0, 40.0, 0.2165)`. For each of five windows `k`, bin both
    frames with `stream_slice`.
  - Multiply B's values by `g_k = 0.5 · exp(−k/4)` and find seams with `find_seams`.
  - For `"background"` and `"edge"`, assert
    `(a_B/a_A)_perturbed == (a_B/a_A)_unperturbed / g_k` with `rtol=1e-5`. A multiplicative
    perturbation scales every background statistic exactly, so the natural difference between the
    halves cancels.
  - For `"histogram"`, assert that each grid's populated mean and std after `a·v + b` equal the
    pooled values (`rtol=1e-5`).
  - `needs_real_files` is `pytest.mark.skipif(not FILES, ...)`, exactly as `test_real_files.py`
    defines it.

- [ ] **Step 2: Run them; every test fails on import.**
  Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_site.py -q`

- [ ] **Step 3: Implement `site.py`** to the Interfaces above. Most of the module follows directly
  from the signatures and tests. Two parts do not, and are spelled out here:

```python
# edge_match_solve: weighted least squares in log space, then per-group anchoring
ids = sorted(levels)
x = dict.fromkeys(ids, 0.0)
for group in connected_components(ids, seam_levels):        # singletons included
    terms = [s for s in seam_levels if s[0] in group]
    if terms:
        A, rhs, w = [], [], []
        for a, b, s_ab, s_ba, weight in terms:              # x_a + ln s_ab = x_b + ln s_ba
            row = {a: 1.0, b: -1.0}
            A.append([row.get(g, 0.0) for g in group]); rhs.append(log(s_ba) - log(s_ab))
            w.append(sqrt(weight))
        sol = lstsq(A * w[:, None], rhs * w)                # minimum-norm, gauge-free
        x.update(zip(group, sol))
    # anchor: the group's corrected backgrounds match the site's in the geometric mean
    known = [g for g in group if levels[g]]
    if known:
        shift = ln_b_site - mean(x[g] + log(levels[g]) for g in known)
        for g in group: x[g] += shift
# finally: renormalise so mean(x) over ids is 0 -> geometric mean gain 1
```

  Here `ln_b_site` is the mean of `log(level)` over grids whose level is known. A grid whose level
  is None, and which sits in a group with no known level, keeps gain 1.0. For `normalise("edge")`:
  - `levels` holds each grid's `background_level`;
  - each seam term holds the two strips' `background_level(values, coverage, mask)` and the weight
    `min(mask_a.sum(), mask_b.sum())`;
  - a seam whose strip level is None is dropped.

  Histogram: pool the values of every grid's populated cells, so the pooled mean and std are taken
  over all populated cells. Then `a_i = σ_p/σ_i` and `b_i = μ_p − a_i·μ_i`. A grid with `σ_i == 0`
  or no populated cells gets `(1, 0)`.

- [ ] **Step 4: Run the file, then the whole core and pure tier; all pass, and the two real-data
  tests run, not skip.**

- [ ] **Step 5: Prove discrimination.** Each test must fail against these mutants and pass again
  once the mutant is reverted:
  1. background over **all** populated cells (not the weakest 75%);
  2. `values` instead of `|values|`;
  3. arithmetic instead of geometric site mean;
  4. edge-solve sign flipped (`ln s_ab − ln s_ba`);
  5. group anchoring removed;
  6. `lattice_pixel` always returns `cell`;
  7. `covering` anchored at `min xmin` instead of a multiple of the pixel;
  8. `window_on` without the `1e-6` snap;
  9. `compose` keeps the first layer instead of averaging.

  Record each in the report.

- [ ] **Step 6: ruff, format and mypy clean; commit and push.**
  `feat(core): site lattice, window mapping, seams and normalisation`

---

