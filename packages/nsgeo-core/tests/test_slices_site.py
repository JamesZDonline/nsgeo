"""The site view's numpy core: lattice, window mapping, seams, normalisation."""

from __future__ import annotations

import math

import numpy as np
import pytest
from nsgeo.slices import (
    NORMALISATION_METHODS,
    CubeFrame,
    Footprint,
    Seam,
    SiteLattice,
    SliceWindow,
    ZAxis,
    background_level,
    bilinear_taps,
    compose_footprints,
    edge_match_solve,
    find_seams,
    fitting_lattice,
    footprint,
    grid_axis,
    normalise,
    sample,
    sample_counts,
    seam_masks,
    site_axis,
    slice_extent,
    stretching_grids,
    window_on,
)

from tests.real_lines import (
    CELL,
    SPACING,
    WINDOWS,
    binned,
    needs_real_files,
    prepared_lines,
)

CRS = "EPSG:32616"


# --- the lattice -------------------------------------------------------------


def test_lattice_is_anchored_on_whole_multiples_of_the_pixel():
    lat = SiteLattice.covering([(500.13, 700.07, 506.0, 706.2)], 0.25, CRS)
    assert lat.x0 == 500.0 and lat.y1 == 706.25  # floor / ceil to the pixel
    assert lat.geotransform == (500.0, 0.25, 0.0, 706.25, 0.0, -0.25)
    assert (lat.width, lat.height) == (24, 25)
    assert lat.n_pixels == 24 * 25


def test_fitting_lattice_doubles_the_pitch_until_it_fits():
    lat = fitting_lattice([(0.0, 0.0, 3.0, 3.0)], 0.1, CRS, 300)
    assert lat.pixel == pytest.approx(0.2)  # 0.1 -> 900, 0.2 -> 225
    assert lat.n_pixels <= 300


def test_fitting_lattice_keeps_the_cell_when_it_fits():
    lat = fitting_lattice([(0.0, 0.0, 3.0, 3.0)], 0.1, CRS, 900)
    assert lat.pixel == 0.1
    assert lat == SiteLattice.covering([(0.0, 0.0, 3.0, 3.0)], 0.1, CRS)


def test_stretching_grids_names_the_outlier_first():
    ext = {
        "A": (0.0, 0.0, 6.0, 6.0),
        "B": (6.0, 0.0, 12.0, 6.0),
        "C": (12.0, 0.0, 18.0, 6.0),
        "D": (200.0, 0.0, 206.0, 6.0),
    }
    assert stretching_grids(ext, 0.5, CRS) == ["D"]


def test_stretching_grids_is_empty_for_one_grid():
    assert stretching_grids({"A": (0.0, 0.0, 6.0, 6.0)}, 0.5, CRS) == []


def test_lattice_covers_the_union_and_has_no_phantom_row_at_utm_scale():
    # Two extents 20 m apart at UTM scale; the exact span is a whole number of pixels.
    # Floating-point residue in the ratio must not add a row or column.
    for pixel in (0.1, 0.05, 0.2, 0.25):
        lat = SiteLattice.covering(
            [
                (500000.0, 4000000.0, 500010.0, 4000010.0),
                (500020.0, 4000015.0, 500030.0, 4000025.0),
            ],
            pixel,
            CRS,
        )
        assert lat.width == round(30.0 / pixel)
        assert lat.height == round(25.0 / pixel)
    lat = SiteLattice.covering(
        [(500000.1, 4000000.1, 500010.1, 4000010.1), (500020.1, 4000015.1, 500030.1, 4000025.1)],
        0.1,
        CRS,
    )
    assert (lat.width, lat.height) == (300, 250)


def test_lattice_refuses_an_empty_sequence_and_a_non_positive_pixel():
    with pytest.raises(ValueError):
        SiteLattice.covering([], 0.25, CRS)
    with pytest.raises(ValueError):
        SiteLattice.covering([(0.0, 0.0, 1.0, 1.0)], 0.0, CRS)


def test_pixel_centres_run_row_major_from_the_north():
    lat = SiteLattice(x0=10.0, y1=20.0, pixel=0.5, width=4, height=3, crs=CRS)
    c = lat.pixel_centres()
    assert c.shape == (12, 2)
    np.testing.assert_allclose(c[0], (10.25, 19.75))
    np.testing.assert_allclose(c[4], (10.25, 19.25))  # centres[width]
    np.testing.assert_allclose(c[1], (10.75, 19.75))


def _taps_over(frame, lat):
    """The frame's bilinear taps at every pixel centre of the lattice."""
    return bilinear_taps(frame, lat.pixel_centres())


def _footprint_of(frame, lat):
    return footprint(_taps_over(frame, lat), lat.height, lat.width)


def test_footprint_compose_samples_each_grid_bilinearly():
    frame = CubeFrame((3.0, 4.0), 33.0, 0.25, 30, 25, CRS)
    lat = SiteLattice.covering([slice_extent(frame), (30.0, 0.0, 31.0, 1.0)], 0.25, CRS)
    rng = np.random.default_rng(3)
    values = rng.normal(size=(25, 30))
    out = compose_footprints(lat, [(_footprint_of(frame, lat), values)])
    assert out.dtype == np.float32 and out.shape == (lat.height, lat.width)
    expected = sample(values, _taps_over(frame, lat)).reshape(lat.height, lat.width)
    np.testing.assert_allclose(out, expected, atol=1e-6)
    np.testing.assert_array_equal(np.isnan(out), np.isnan(expected))
    # Not the nearest cell: a rotated frame's pixels fall between cell centres.
    nearest = values.ravel()[np.clip(_taps_over(frame, lat).nearest, 0, None)]
    nearest = np.where(_taps_over(frame, lat).inside, nearest, np.nan).reshape(out.shape)
    assert np.nanmax(np.abs(out - nearest)) > 0.05


def test_a_footprint_is_the_tight_window_around_every_inside_point():
    frame = CubeFrame((3.0, 4.0), 33.0, 0.25, 30, 25, CRS)
    lat = SiteLattice.covering([slice_extent(frame), (30.0, 0.0, 31.0, 1.0)], 0.25, CRS)
    taps = _taps_over(frame, lat)
    where = footprint(taps, lat.height, lat.width)
    grid = taps.inside.reshape(lat.height, lat.width)
    rows, cols = where.row1 - where.row0, where.col1 - where.col0
    assert where.taps.n == rows * cols == where.n_pixels
    window = (slice(where.row0, where.row1), slice(where.col0, where.col1))
    np.testing.assert_array_equal(
        where.taps.nearest, taps.nearest.reshape(grid.shape)[window].ravel()
    )
    np.testing.assert_array_equal(
        where.taps.weights,
        taps.weights.reshape(4, *grid.shape)[(slice(None), *window)].reshape(4, -1),
    )
    outside = np.ones_like(grid)
    outside[window] = False
    assert not grid[outside].any(), "an inside point outside the window"
    inside = where.taps.inside.reshape(rows, cols)
    for edge in (inside[0], inside[-1], inside[:, 0], inside[:, -1]):
        assert edge.any()  # tight
    assert where.n_pixels < lat.n_pixels // 2  # the point of it
    nothing = bilinear_taps(frame, np.full((20, 2), 1e6))
    empty = footprint(nothing, 4, 5, 7, 9)
    assert empty.n_pixels == 0 and (empty.row0, empty.col0) == (7, 9)
    assert empty.row1 == 7 and empty.col1 == 9


def test_footprint_compose_still_averages_overlapping_layers():
    a = CubeFrame((3.0, 4.0), 20.0, 0.25, 30, 25, CRS)
    b = CubeFrame((6.0, 5.0), 50.0, 0.25, 30, 25, CRS)
    lat = SiteLattice.covering([slice_extent(a), slice_extent(b)], 0.25, CRS)
    ta, tb = _taps_over(a, lat), _taps_over(b, lat)
    rng = np.random.default_rng(12)
    va, vb = rng.normal(size=(25, 30)), rng.normal(size=(25, 30)) + 3.0
    va[3, 4] = vb[10, 11] = np.nan  # an unpopulated cell is skipped, not averaged in
    sa, sb = sample(va, ta), sample(vb, tb)
    both = np.isfinite(sa) & np.isfinite(sb)
    assert both.sum() > 100, "the frames must overlap"
    out = compose_footprints(lat, [(_footprint_of(a, lat), va), (_footprint_of(b, lat), vb)])
    expected = np.where(both, (sa + sb) / 2.0, np.where(np.isfinite(sa), sa, sb)).reshape(out.shape)
    np.testing.assert_allclose(out, expected, atol=1e-6)
    np.testing.assert_array_equal(np.isnan(out), np.isnan(expected))
    assert np.abs(sa[both] - sb[both]).max() > 1.0  # the mean is not either layer


def test_compose_counts_takes_whole_counts_within_a_grid():
    frame = CubeFrame((3.0, 4.0), 33.0, 0.25, 30, 25, CRS)
    lat = SiteLattice.covering([slice_extent(frame)], 0.25, CRS)
    rng = np.random.default_rng(5)
    counts = rng.integers(1, 6, size=(25, 30)).astype(np.float32)
    counts[4:8, 6:12] = 0.0  # a hole: no pixel next to it may blend a count in
    where = _footprint_of(frame, lat)
    out = compose_footprints(lat, [(where, counts)], counts=True)
    got = out[np.isfinite(out)]
    assert got.size > 100
    assert set(np.unique(got)) <= {1.0, 2.0, 3.0, 4.0, 5.0}  # never a blend
    blended = compose_footprints(lat, [(where, counts)])
    assert not set(np.unique(blended[np.isfinite(blended)])) <= {0.0, 1.0, 2.0, 3.0, 4.0, 5.0}
    expected = sample_counts(counts, _taps_over(frame, lat)).reshape(out.shape)
    np.testing.assert_array_equal(out, expected)


def test_compose_footprints_refuses_a_window_off_the_lattice():
    lat = SiteLattice(0.0, 2.0, 1.0, 3, 2, CRS)
    frame = CubeFrame((0.0, 0.0), 0.0, 1.0, 1, 1, CRS)
    taps = bilinear_taps(frame, np.array([[0.5, 0.5], [0.5, 0.5]]))
    with pytest.raises(ValueError, match="lattice"):
        compose_footprints(lat, [(Footprint(1, 2, 2, 4, taps), np.ones((1, 1)))])
    with pytest.raises(ValueError, match="taps"):
        Footprint(0, 1, 0, 1, taps)


# --- the window mapping --------------------------------------------------------


def test_site_axis_is_the_union_clipped_to_the_requested_range():
    z = site_axis([(2.0, 10.0), (5.0, 20.0)], 3.0, 15.0, 0.5)
    assert z == ZAxis(3.0, 0.5, 25)  # 3 .. 15
    z = site_axis([(2.0, 10.0), (5.0, 20.0)], 0.0, 100.0, 0.5)
    assert z == ZAxis(2.0, 0.5, 37)  # the whole union, 2 .. 20
    assert site_axis([(0.0, 2.0)], 3.0, 15.0, 0.5) is None
    assert site_axis([], 3.0, 15.0, 0.5) is None


def test_grid_axis_shares_the_site_lattice_of_levels():
    site = ZAxis(t0_ns=-3.1, dz_ns=0.2165, nz=400)
    grid = grid_axis(site, (site.t0_ns + 7 * 0.2165, site.t0_ns + 300 * 0.2165))
    assert grid is not None
    assert grid.t0_ns == pytest.approx(site.t0_ns + 7 * site.dz_ns, abs=1e-9)
    assert grid.dz_ns == site.dz_ns and grid.nz == 294
    # Bounds in between levels keep only the levels inside.
    g2 = grid_axis(site, (site.t0_ns + 7.2 * 0.2165, site.t0_ns + 9.9 * 0.2165))
    assert g2 is not None and g2.nz == 2
    assert grid_axis(site, (site.t0_ns + 1000.0, site.t0_ns + 2000.0)) is None
    assert grid_axis(site, (site.t0_ns - 50.0, site.t0_ns - 40.0)) is None


def test_window_on_agrees_with_the_site_axis_at_every_slider_position():
    site = ZAxis(t0_ns=-3.1, dz_ns=0.2165, nz=400)
    grid = grid_axis(site, (site.t0_ns + 7 * 0.2165, site.t0_ns + 300 * 0.2165))
    assert grid is not None
    for v in range(7, 300):
        w = window_on(grid, site.t0_ns + v * site.dz_ns, 4 * site.dz_ns)
        assert w is not None and w.k0 == v - 7


def test_window_on_is_none_only_when_no_level_overlaps():
    z = ZAxis(t0_ns=10.0, dz_ns=0.5, nz=20)  # 10.0 .. 19.5 ns
    assert window_on(z, 7.0, 2.0) is None  # ends before 10.0
    assert window_on(z, 9.0, 2.0) == SliceWindow(0, 2)  # overhangs the start: thinner
    assert window_on(z, 19.5, 2.0) == SliceWindow(19, 20)
    assert window_on(z, 20.0, 2.0) is None


# --- seams ---------------------------------------------------------------------


def _frame(x, y, az=0.0, n=20, crs=CRS):
    return CubeFrame((x, y), az, 0.25, n, n, crs)


def test_seam_masks_find_the_strips_either_side_of_a_shared_edge():
    a, b = _frame(0.0, 0.0), _frame(5.0, 0.0)
    ma, mb = seam_masks(a, b, 0.75)
    assert ma.shape == (20, 20) and mb.shape == (20, 20)
    expect_a = np.zeros((20, 20), dtype=bool)
    expect_a[:, 17:20] = True
    expect_b = np.zeros((20, 20), dtype=bool)
    expect_b[:, 0:3] = True
    np.testing.assert_array_equal(ma, expect_a)
    np.testing.assert_array_equal(mb, expect_b)


def test_seam_masks_still_find_a_seam_two_degrees_off_parallel():
    a, b = _frame(0.0, 0.0), _frame(5.0, 0.0, az=2.0)
    ma, mb = seam_masks(a, b, 0.75)
    assert ma.sum() > 40 and mb.sum() > 40
    assert not ma[:, :15].any() and not mb[:, 6:].any()


def test_seam_masks_are_empty_for_frames_in_different_crs():
    ma, mb = seam_masks(_frame(0.0, 0.0), _frame(5.0, 0.0, crs="EPSG:32617"), 0.75)
    assert not ma.any() and not mb.any()
    assert ma.shape == (20, 20) and mb.shape == (20, 20)


def test_find_seams_needs_min_cells_on_both_sides():
    frames = {"A": _frame(0.0, 0.0), "B": _frame(5.0, 0.0)}
    spacings = {"A": 0.5, "B": 0.5}  # width 0.75: three columns each side

    def coverage(n_strip):
        c = np.zeros((20, 20), dtype=int)
        c[:, 10:] = 1  # plenty away from the seam
        return c, n_strip

    full = np.ones((20, 20), dtype=int)
    cb = np.zeros((20, 20), dtype=int)
    cb.ravel()[[r * 20 + c for r in range(10) for c in range(2)][:19]] = 1  # 19 in B's strip
    assert find_seams(frames, {"A": full, "B": cb}, spacings) == ()
    assert find_seams(frames, {"B": full, "A": cb}, spacings) == ()  # either side counts
    cb.ravel()[[r * 20 + c for r in range(10) for c in range(2)][:20]] = 1  # 20
    (seam,) = find_seams(frames, {"A": full, "B": cb}, spacings)
    assert isinstance(seam, Seam) and (seam.a, seam.b) == ("A", "B")
    assert seam.mask_b.sum() == 20 and seam.mask_a.sum() == 60  # restricted to populated
    assert not (seam.mask_b & (cb == 0)).any()


def test_find_seams_skips_distant_grids_and_other_crs():
    frames = {"A": _frame(0.0, 0.0), "B": _frame(50.0, 0.0), "C": _frame(5.0, 0.0, crs="EPSG:1")}
    cov = {k: np.ones((20, 20), dtype=int) for k in frames}
    assert find_seams(frames, cov, dict.fromkeys(frames, 0.5)) == ()


# --- background level ----------------------------------------------------------


def test_background_level_is_the_mean_of_the_weakest_three_quarters():
    v = np.arange(1, 9, dtype=float).reshape(2, 4)
    c = np.ones_like(v, dtype=int)
    assert background_level(v, c) == pytest.approx(np.mean([1, 2, 3, 4, 5, 6]))


def test_background_level_ignores_unpopulated_cells_and_is_none_when_empty():
    v = np.array([[1.0, 2.0, 3.0, 4.0, 1000.0, np.nan]])
    c = np.array([[1, 1, 1, 1, 0, 0]])
    assert background_level(v, c) == pytest.approx(2.0)  # ceil(3) of 1..4: mean(1, 2, 3)
    mask = np.array([[True, True, False, False, True, True]])
    assert background_level(v, c, mask) == pytest.approx(1.5)  # {1, 2}: keeps ceil(1.5) = 2
    assert background_level(v, np.zeros_like(c)) is None
    assert background_level(np.zeros((2, 2)), np.ones((2, 2), dtype=int)) is None


def test_background_level_measures_magnitude_on_signed_data():
    v = np.array([[-8.0, 1.0, -2.0, 3.0]])
    c = np.ones_like(v, dtype=int)
    assert background_level(v, c) == pytest.approx(2.0)  # weakest 3 of |v| = 1, 2, 3


# --- normalisation -------------------------------------------------------------


def _base(seed, shape=(20, 20)):
    return np.random.default_rng(seed).uniform(0.5, 2.0, shape)


def test_background_gains_have_geometric_mean_one_and_recover_a_known_gain():
    base = _base(1)
    ones = np.ones_like(base, dtype=int)
    true = {"A": 1.0, "B": 3.0, "C": 0.2}
    slices = {k: (base * g, ones) for k, g in true.items()}
    gains = {k: a for k, (a, b) in normalise("background", slices).items()}
    assert math.prod(gains.values()) == pytest.approx(1.0)
    # Each corrected grid has the same background: a_i * true_i is the same constant.
    corrected = [gains[k] * true[k] for k in true]
    np.testing.assert_allclose(corrected, corrected[0])
    assert gains["B"] / gains["A"] == pytest.approx(1.0 / 3.0)
    assert all(b == 0.0 for _, b in normalise("background", slices).values())


def _chain():
    """Three 5 m grids side by side in one continuous field, with known gains."""
    # Constant along x, so the strips either side of a seam hold the same cells' worth of
    # values and a gain is the only difference between them.
    field = np.tile(_base(2, (20, 1)), (1, 60))
    frames = {"A": _frame(0.0, 0.0), "B": _frame(5.0, 0.0), "C": _frame(10.0, 0.0)}
    true = {"A": 1.0, "B": 2.0, "C": 0.5}
    ones = np.ones((20, 20), dtype=int)
    slices = {k: (field[:, i * 20 : (i + 1) * 20] * true[k], ones) for i, k in enumerate(frames)}
    seams = find_seams(frames, {k: ones for k in frames}, dict.fromkeys(frames, 0.5))
    return slices, seams, true


def test_edge_match_recovers_known_gains_along_a_chain_and_agrees_with_pairwise():
    slices, seams, true = _chain()
    assert [(s.a, s.b) for s in seams] == [("A", "B"), ("B", "C")]
    gains = {k: a for k, (a, _) in normalise("edge", slices, seams).items()}
    corrected = [gains[k] * true[k] for k in true]
    np.testing.assert_allclose(corrected, corrected[0], rtol=1e-9)
    assert math.prod(gains.values()) == pytest.approx(1.0)
    # On a chain the global solve IS the pairwise match: each ratio is the seam ratio.
    for s in seams:
        s_ab = background_level(*slices[s.a], s.mask_a)
        s_ba = background_level(*slices[s.b], s.mask_b)
        assert gains[s.b] / gains[s.a] == pytest.approx(s_ab / s_ba)


def test_edge_match_spreads_a_loop_closure_error_that_pairwise_dumps_on_the_last_seam():
    # 2 x 2 block, loop A-B, B-D, D-C, C-A; the seam ratios multiply to 1.21 round the loop.
    levels = {g: 1.0 for g in "ABCD"}
    seams = [
        ("A", "B", 1.1, 1.0, 10.0),
        ("B", "D", 1.1, 1.0, 10.0),
        ("D", "C", 1.0, 1.0, 10.0),
        ("C", "A", 1.0, 1.0, 10.0),
    ]

    def residuals(x):
        return [abs(x[a] + math.log(s_ab) - x[b] - math.log(s_ba)) for a, b, s_ab, s_ba, _ in seams]

    # The sequential chain, in the test: walk the loop fixing each grid from the last.
    chain = {"A": 0.0}
    for a, b, s_ab, s_ba, _ in seams[:-1]:
        chain[b] = chain[a] + math.log(s_ab) - math.log(s_ba)
    chain_closing = residuals(chain)[-1]
    assert chain_closing == pytest.approx(math.log(1.21))

    gains = edge_match_solve(levels, seams)
    x = {g: math.log(v) for g, v in gains.items()}
    assert max(residuals(x)) < 0.6 * chain_closing
    assert max(residuals(x)) == pytest.approx(math.log(1.21) / 4)  # spread evenly


def test_each_connected_group_is_anchored_to_the_site_background():
    levels = {"A": 1.0, "B": 1.0, "C": 4.0, "D": 4.0}
    seams = [("A", "B", 1.0, 1.0, 5.0), ("C", "D", 1.0, 1.0, 5.0)]
    g = edge_match_solve(levels, seams)
    gm = {k: g[k] * levels[k] for k in levels}
    # Both groups' corrected backgrounds are the same constant, the site's geometric mean
    # (2) up to the final renormalisation: they agree with each other and across a group.
    assert gm["A"] == pytest.approx(gm["B"]) and gm["C"] == pytest.approx(gm["D"])
    assert gm["A"] == pytest.approx(gm["C"])
    assert math.prod(g.values()) == pytest.approx(1.0)


def test_an_isolated_grid_takes_its_background_gain():
    levels = {"A": 1.0, "B": 2.0, "C": 4.0}
    g = edge_match_solve(levels, [("A", "B", 1.0, 1.0, 5.0)])
    assert g["C"] == pytest.approx(0.5)  # B_site (2) / B_C (4)
    assert g["A"] == pytest.approx(math.sqrt(2.0)) and g["B"] == pytest.approx(math.sqrt(2.0))
    # With no known level anywhere, every gain stays 1.
    assert edge_match_solve({"A": None, "B": None}, []) == {"A": 1.0, "B": 1.0}
    # A grid with no level and no seam keeps gain 1 beside grids that have levels.
    g = edge_match_solve({"A": 1.0, "B": 4.0, "C": None}, [])
    assert g["C"] == pytest.approx(1.0) and g["A"] == pytest.approx(2.0)


def test_histogram_match_gives_every_grid_the_pooled_mean_and_std():
    rng = np.random.default_rng(3)
    slices = {}
    for k, (mu, sd) in {"A": (1.0, 0.5), "B": (4.0, 2.0), "C": (-1.0, 0.1)}.items():
        v = rng.normal(mu, sd, (20, 20))
        c = np.ones((20, 20), dtype=int)
        c[:5] = 0
        v[:5] = np.nan
        slices[k] = (v, c)
    pooled = np.concatenate([v[c > 0] for v, c in slices.values()])
    out = normalise("histogram", slices)
    for k, (v, c) in slices.items():
        a, b = out[k]
        adjusted = a * v[c > 0] + b
        assert adjusted.mean() == pytest.approx(pooled.mean(), rel=1e-9)
        assert adjusted.std() == pytest.approx(pooled.std(), rel=1e-9)


def test_histogram_leaves_a_flat_or_empty_grid_alone():
    slices = {
        "A": (_base(4), np.ones((20, 20), dtype=int)),
        "B": (np.full((20, 20), 3.0), np.ones((20, 20), dtype=int)),
        "C": (np.full((20, 20), np.nan), np.zeros((20, 20), dtype=int)),
    }
    out = normalise("histogram", slices)
    assert out["B"] == (1.0, 0.0) and out["C"] == (1.0, 0.0)


def _two_grid_input():
    frames = {"A": _frame(0.0, 0.0), "B": _frame(5.0, 0.0)}
    ones = np.ones((20, 20), dtype=int)
    slices = {"A": (_base(5), ones), "B": (_base(6) * 3.0, ones)}
    seams = find_seams(frames, {k: ones for k in frames}, dict.fromkeys(frames, 0.5))
    assert len(seams) == 1
    return slices, seams


def test_the_manual_multiplier_composes_with_every_method():
    slices, seams = _two_grid_input()
    for method in NORMALISATION_METHODS:
        base = normalise(method, slices, seams)
        adj = normalise(method, slices, seams, {"A": 2.0})
        assert adj["A"] == pytest.approx((2.0 * base["A"][0], 2.0 * base["A"][1]))
        assert adj["B"] == pytest.approx(base["B"])
    assert normalise("none", slices, seams, {"A": 2.0}) == {"A": (2.0, 0.0), "B": (1.0, 0.0)}


def test_edge_normalise_drops_a_seam_whose_strip_has_no_level():
    slices, seams = _two_grid_input()
    zero = {"A": (np.zeros((20, 20)), slices["A"][1]), "B": slices["B"]}
    out = normalise("edge", zero, seams)  # A has no level; seam dropped; B alone
    assert out["A"] == (1.0, 0.0)
    assert out["B"][0] == pytest.approx(1.0)


def test_normalise_refuses_an_unknown_method():
    slices, seams = _two_grid_input()
    with pytest.raises(ValueError):
        normalise("magic", slices, seams)


# --- real data -----------------------------------------------------------------


def _real_split():
    """Frame A holds lines 0-4; frame B (origin y = 2.6) holds 5-9 at B-local y 0.15..2.15."""
    frame_a = CubeFrame((0.0, 0.0), 0.0, CELL, 100, 13, "EPSG:32633")
    frame_b = CubeFrame((0.0, 2.6), 0.0, CELL, 100, 13, "EPSG:32633")
    world = lambda local: local  # noqa: E731 - lines keep their natural world positions
    return frame_a, frame_b, prepared_lines(range(0, 5), world), prepared_lines(range(5, 10), world)


def _split_slices(k, gain):
    frame_a, frame_b, lines_a, lines_b = _real_split()
    k0, k1 = WINDOWS[k]
    va, ca = binned(lines_a, frame_a, k0, k1)
    vb, cb = binned(lines_b, frame_b, k0, k1)
    frames = {"A": frame_a, "B": frame_b}
    seams = find_seams(frames, {"A": ca, "B": cb}, {"A": SPACING, "B": SPACING})
    return {"A": (va, ca), "B": (vb * gain, cb)}, seams


def _strip_ratio(slices, seam):
    """S_ab / S_ba for a seam, measured in the test from its masks."""

    # Written out here, not via background_level, so a bug there cannot cancel out.
    def level(grid, mask):
        values, coverage = slices[grid]
        mag = np.sort(np.abs(values[mask & (coverage > 0)]))
        return float(mag[: math.ceil(0.75 * mag.size - 1e-9)].mean())

    return level(seam.a, seam.mask_a) / level(seam.b, seam.mask_b)


def test_a_seam_compares_and_hashes_without_raising():
    m = np.zeros((2, 2), dtype=bool)
    s1, s2 = Seam("A", "B", m, m), Seam("A", "B", m.copy(), m.copy())
    assert s1 == s1 and (s1 == s2) is False  # identity, not array equality
    assert len({s1, s2}) == 2


@needs_real_files
@pytest.mark.parametrize("method", ["background", "edge"])
def test_real_split_background_and_edge_recover_a_depth_dependent_gain_exactly(method):
    ratios = []
    for k in range(5):
        g_k = 0.5 * math.exp(-k / 4.0)
        plain, seams = _split_slices(k, 1.0)
        perturbed, seams_p = _split_slices(k, g_k)
        assert [(s.a, s.b) for s in seams] == [("A", "B")] == [(s.a, s.b) for s in seams_p]
        n0 = normalise(method, plain, seams)
        n1 = normalise(method, perturbed, seams_p)
        r0 = n0["B"][0] / n0["A"][0]
        r1 = n1["B"][0] / n1["A"][0]
        assert r1 == pytest.approx(r0 / g_k, rel=1e-5)
        if method == "edge":
            # Edge match reads the seam strips only: the ratio is the strips' ratio, and
            # differs from the whole-grid (background) ratio on real halves.
            assert r0 == pytest.approx(_strip_ratio(plain, seams[0]), rel=1e-5)
            bg = normalise("background", plain)
            assert r0 != pytest.approx(bg["B"][0] / bg["A"][0], rel=1e-4)
        ratios.append(r0)
    assert len({round(r, 6) for r in ratios}) > 1  # the halves genuinely differ with depth


@needs_real_files
def test_real_split_histogram_hits_the_pooled_moments():
    for k in range(5):
        slices, _ = _split_slices(k, 0.5 * math.exp(-k / 4.0))
        pooled = np.concatenate([v[c > 0] for v, c in slices.values()]).astype(float)
        out = normalise("histogram", slices)
        for g, (v, c) in slices.items():
            a, b = out[g]
            adjusted = a * v[c > 0].astype(float) + b
            assert adjusted.mean() == pytest.approx(pooled.mean(), rel=1e-5)
            assert adjusted.std() == pytest.approx(pooled.std(), rel=1e-5)


@needs_real_files
def test_real_halves_at_different_azimuths_compose_and_find_their_seam():
    # Spec 9 "mixed azimuths": B's frame and lines rotated 2 deg about the shared corner.
    # Real data, invented placement.
    crs = "EPSG:32633"
    frame_a = CubeFrame((0.0, 0.0), 0.0, CELL, 100, 13, crs)
    frame_b = CubeFrame((0.0, 2.6), 2.0, CELL, 100, 13, crs)
    x_hat, y_hat = frame_b.axes()
    origin = np.asarray(frame_b.origin)

    def rotate(local):
        # lines 5-9 sit at B-local y 0.15..2.15; the shared corner is B's origin
        return origin + local[:, :1] * x_hat + (local[:, 1:] - 2.6) * y_hat

    lines_a = prepared_lines(range(0, 5), lambda local: local)
    lines_b = prepared_lines(range(5, 10), rotate)
    k0, k1 = WINDOWS[1]
    va, ca = binned(lines_a, frame_a, k0, k1)
    vb, cb = binned(lines_b, frame_b, k0, k1)

    seams = find_seams({"A": frame_a, "B": frame_b}, {"A": ca, "B": cb}, dict(A=SPACING, B=SPACING))
    assert [(s.a, s.b) for s in seams] == [("A", "B")]

    lat = SiteLattice.covering([slice_extent(frame_a), slice_extent(frame_b)], CELL, crs)
    centres = lat.pixel_centres()
    layers = []
    covered = np.zeros(lat.n_pixels, dtype=bool)
    for frame, v, c in ((frame_a, va, ca), (frame_b, vb, cb)):
        taps = bilinear_taps(frame, centres)
        populated = np.flatnonzero(c.ravel() > 0)
        assert np.isin(populated, taps.nearest).all()  # every populated cell is placed
        layers.append((footprint(taps, lat.height, lat.width), v))
        covered |= np.isfinite(sample(v, taps))
    out = compose_footprints(lat, layers)
    np.testing.assert_array_equal(np.isfinite(out).ravel(), covered)
    assert covered.any()


def _chain_slices(k, g_b, g_c):
    """Three real grids in a row: A lines 0-2, B lines 3-5, C lines 6-9, natural world y."""
    crs = "EPSG:32633"
    frames = {
        "A": CubeFrame((0.0, 0.0), 0.0, CELL, 100, 8, crs),
        "B": CubeFrame((0.0, 1.6), 0.0, CELL, 100, 7, crs),
        "C": CubeFrame((0.0, 3.0), 0.0, CELL, 100, 11, crs),
    }
    members = {"A": range(0, 3), "B": range(3, 6), "C": range(6, 10)}
    gain = {"A": 1.0, "B": g_b, "C": g_c}
    k0, k1 = WINDOWS[k]
    slices, covs = {}, {}
    for g, frame in frames.items():
        v, c = binned(prepared_lines(members[g], lambda local: local), frame, k0, k1)
        slices[g], covs[g] = (v * gain[g], c), c
    seams = find_seams(frames, covs, dict.fromkeys(frames, SPACING))
    return slices, seams


@needs_real_files
def test_real_chain_edge_match_recovers_gains_and_equals_the_pairwise_solve():
    for k in range(5):
        g_b, g_c = 0.5 * math.exp(-k / 4.0), 1.6 * math.exp(-k / 3.0)
        plain, seams = _chain_slices(k, 1.0, 1.0)
        perturbed, seams_p = _chain_slices(k, g_b, g_c)
        for ss in (seams, seams_p):
            assert [(s.a, s.b) for s in ss] == [("A", "B"), ("B", "C")]  # no A-C
        n0 = {g: a for g, (a, _) in normalise("edge", plain, seams).items()}
        n1 = {g: a for g, (a, _) in normalise("edge", perturbed, seams_p).items()}
        # (a) both gains recovered
        assert n1["B"] / n1["A"] == pytest.approx(n0["B"] / n0["A"] / g_b, rel=1e-5)
        assert n1["C"] / n1["A"] == pytest.approx(n0["C"] / n0["A"] / g_c, rel=1e-5)
        # (b) global == pairwise: one equation per seam, strips measured in the test
        assert n1["B"] / n1["A"] == pytest.approx(_strip_ratio(perturbed, seams_p[0]), rel=1e-5)
        assert n1["C"] / n1["B"] == pytest.approx(_strip_ratio(perturbed, seams_p[1]), rel=1e-5)
