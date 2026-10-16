"""The site view's numpy core: lattice, window mapping, seams, normalisation."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from nsgeo.io.dzt import read_header, read_samples
from nsgeo.processing import build_step
from nsgeo.processing.base import Radargram
from nsgeo.slices import (
    NORMALISATION_METHODS,
    CubeFrame,
    Footprint,
    PreparedLine,
    Seam,
    SiteLattice,
    SliceWindow,
    ZAxis,
    background_level,
    compose,
    compose_footprints,
    edge_match_solve,
    find_seams,
    footprint,
    grid_axis,
    lattice_pixel,
    normalise,
    plan_line,
    seam_masks,
    site_axis,
    slice_extent,
    stream_slice,
    to_north_up,
    window_on,
)

DATA = Path(__file__).parent / "data" / "local"
FILES = sorted(p for p in DATA.rglob("*") if p.suffix.lower() == ".dzt") if DATA.exists() else []
needs_real_files = pytest.mark.skipif(
    len(FILES) < 10, reason="needs the ten real DZT files in tests/data/local"
)

CRS = "EPSG:32616"


# --- the lattice -------------------------------------------------------------


def test_lattice_is_anchored_on_whole_multiples_of_the_pixel():
    lat = SiteLattice.covering([(500.13, 700.07, 506.0, 706.2)], 0.25, CRS)
    assert lat.x0 == 500.0 and lat.y1 == 706.25  # floor / ceil to the pixel
    assert lat.geotransform == (500.0, 0.25, 0.0, 706.25, 0.0, -0.25)
    assert (lat.width, lat.height) == (24, 25)
    assert lat.n_pixels == 24 * 25


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


def _ids_for(frame, pixel):
    lat = SiteLattice.covering([slice_extent(frame)], pixel, frame.crs)
    return frame.cell_index(lat.pixel_centres())


def test_an_axis_aligned_frame_loses_no_cell_at_pixel_equal_to_cell():
    cell = 0.25
    frame = CubeFrame((0.37 * cell, 0.81 * cell), 0.0, cell, 30, 25, CRS)
    ids = _ids_for(frame, lattice_pixel(cell, [0.0]))
    assert set(np.unique(ids[ids >= 0])) == set(range(frame.n_cells))


def test_a_rotated_frame_loses_cells_at_pixel_equal_to_cell():
    frame = CubeFrame((3.0, 4.0), 33.0, 0.25, 30, 25, CRS)
    ids = _ids_for(frame, frame.cell)
    assert len(np.unique(ids[ids >= 0])) < frame.n_cells  # why Ruling 2 exists


@pytest.mark.parametrize("azimuth", [7.0, 33.0, 45.0, 78.0])
def test_a_rotated_frame_loses_no_cell_at_half_pitch(azimuth):
    frame = CubeFrame((3.0, 4.0), azimuth, 0.25, 30, 25, CRS)
    pixel = lattice_pixel(frame.cell, [azimuth])
    assert pixel == frame.cell / 2
    ids = _ids_for(frame, pixel)
    assert set(np.unique(ids[ids >= 0])) == set(range(frame.n_cells))


def test_lattice_pixel_is_the_cell_for_right_angles_and_half_for_anything_else():
    assert lattice_pixel(0.25, [0.0, 90.0, 270.0]) == 0.25
    assert lattice_pixel(0.25, [0.0, 2.0]) == 0.125
    assert lattice_pixel(0.25, [90.0 + 5e-10]) == 0.25
    assert lattice_pixel(0.25, [90.0 + 1e-8]) == 0.125


def test_compose_averages_overlaps_and_leaves_uncovered_pixels_nodata():
    lat = SiteLattice(0.0, 2.0, 1.0, 3, 2, CRS)  # 6 pixels
    ids_a = np.array([0, 1, 2, -1, -1, -1])
    ids_b = np.array([-1, 0, 1, 2, -1, -1])
    va = np.array([[2.0, 4.0, 6.0]])
    vb = np.array([[10.0, np.nan, 20.0]])
    out = compose(lat, [(ids_a, va), (ids_b, vb)])
    assert out.dtype == np.float32 and out.shape == (2, 3)
    # px0: A only; px1: mean(4, 10); px2: A=6 and B=nan -> 6; px3: B=20; px4-5: none
    np.testing.assert_allclose(out.ravel()[:4], [2.0, 7.0, 6.0, 20.0])
    assert np.isnan(out.ravel()[4:]).all()


def test_compose_of_one_layer_is_that_layer_resampled():
    frame = CubeFrame((0.0, 0.0), 0.0, 1.0, 4, 3, CRS)
    values = np.arange(12.0).reshape(3, 4)
    lat = SiteLattice.covering([slice_extent(frame)], 1.0, CRS)
    out = compose(lat, [(frame.cell_index(lat.pixel_centres()), values)])
    expected, _ = to_north_up(values, frame)
    np.testing.assert_array_equal(out, expected)
    assert out[0, 0] == 8.0  # row 0 is north: the frame's top row


# --- footprints (final review I1) ------------------------------------------------


def _gathers(lat, frames):
    """Each frame's whole-lattice gather and its footprint, as compose and
    compose_footprints take them."""
    full = [frame.cell_index(lat.pixel_centres()) for frame in frames]
    return full, [footprint(ids.reshape(lat.height, lat.width)) for ids in full]


def test_a_footprint_is_the_tight_window_around_every_placed_pixel():
    frame = CubeFrame((3.0, 4.0), 33.0, 0.25, 30, 25, CRS)
    lat = SiteLattice.covering(
        [slice_extent(frame), (30.0, 0.0, 31.0, 1.0)], lattice_pixel(0.25, [33.0]), CRS
    )
    (ids,), (where,) = _gathers(lat, [frame])
    grid = ids.reshape(lat.height, lat.width)
    assert where.ids.shape == (where.row1 - where.row0, where.col1 - where.col0)
    np.testing.assert_array_equal(where.ids, grid[where.row0 : where.row1, where.col0 : where.col1])
    outside = np.ones_like(grid, dtype=bool)
    outside[where.row0 : where.row1, where.col0 : where.col1] = False
    assert (grid[outside] == -1).all(), "a placed pixel outside the window"
    # Tight: every edge row and column of the window places a pixel.
    for edge in (where.ids[0], where.ids[-1], where.ids[:, 0], where.ids[:, -1]):
        assert (edge >= 0).any()
    assert where.n_pixels < lat.n_pixels // 2  # the point of it
    empty = footprint(np.full((4, 5), -1))
    assert empty.n_pixels == 0 and empty.ids.shape == (0, 0)


def test_footprint_compose_equals_full_compose_on_a_rotated_frame():
    frame = CubeFrame((3.0, 4.0), 33.0, 0.25, 30, 25, CRS)
    other = CubeFrame((12.0, 4.0), 0.0, 0.25, 8, 8, CRS)  # apart: the windows do not meet
    lat = SiteLattice.covering(
        [slice_extent(frame), slice_extent(other)], lattice_pixel(0.25, [33.0, 0.0]), CRS
    )
    full, fps = _gathers(lat, [frame, other])
    values = [np.arange(30 * 25, dtype=float).reshape(25, 30) + 1.0, np.full((8, 8), -2.5)]
    out = compose_footprints(lat, list(zip(fps, values)))
    assert out.dtype == np.float32 and out.shape == (lat.height, lat.width)
    assert np.array_equal(out, compose(lat, list(zip(full, values))), equal_nan=True)


def test_footprint_compose_still_averages_overlapping_layers():
    a = CubeFrame((3.0, 4.0), 20.0, 0.25, 30, 25, CRS)
    b = CubeFrame((6.0, 5.0), 50.0, 0.25, 30, 25, CRS)
    lat = SiteLattice.covering(
        [slice_extent(a), slice_extent(b)], lattice_pixel(0.25, [20.0, 50.0]), CRS
    )
    full, fps = _gathers(lat, [a, b])
    rng = np.random.default_rng(12)
    va, vb = rng.normal(size=(25, 30)), rng.normal(size=(25, 30)) + 3.0
    va[3, 4] = vb[10, 11] = np.nan  # an unpopulated cell is skipped, not averaged in
    both = (full[0] >= 0) & (full[1] >= 0)
    assert both.sum() > 100, "the frames must overlap"
    out = compose_footprints(lat, [(fps[0], va), (fps[1], vb)])
    assert np.array_equal(out, compose(lat, [(full[0], va), (full[1], vb)]), equal_nan=True)
    pixel = np.flatnonzero(
        both & np.isfinite(va.ravel()[full[0]]) & np.isfinite(vb.ravel()[full[1]])
    )[0]
    mean = (va.ravel()[full[0][pixel]] + vb.ravel()[full[1][pixel]]) / 2.0
    assert out.ravel()[pixel] == np.float32(mean)


def test_compose_footprints_refuses_a_window_off_the_lattice():
    lat = SiteLattice(0.0, 2.0, 1.0, 3, 2, CRS)
    ids = np.zeros((1, 2), dtype=np.intp)
    with pytest.raises(ValueError, match="lattice"):
        compose_footprints(lat, [(Footprint(1, 2, 2, 4, ids), np.ones((1, 1)))])
    with pytest.raises(ValueError, match="ids"):
        Footprint(0, 1, 0, 1, ids)


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

CELL = 0.2
SPACING = 0.5
_AXIS = ZAxis.from_range(1.0, 40.0, 0.2165)
_WINDOWS = [(10 + 20 * k, 28 + 20 * k) for k in range(5)]
_RADARGRAMS: list = []


def _radargrams():
    if not _RADARGRAMS:
        for path in FILES[:10]:
            header = read_header(path)
            rg = Radargram(
                data=np.asarray(read_samples(path, header)[0], dtype=float),
                dt_ns=header.dt_ns,
                t0_ns=header.position_ns,
            )
            for name in ("time_zero", "dewow", "background_mean", "gain_agc", "amp_envelope"):
                rg = build_step(name).apply(rg)
            _RADARGRAMS.append((path.name, rg))
    return _RADARGRAMS


def _lines(indices, to_world):
    out = []
    for i in indices:
        name, rg = _radargrams()[i]
        n = rg.data.shape[1]
        local = np.column_stack([np.linspace(0.0, 19.99, n), np.full(n, 0.25 + i * SPACING)])
        out.append(
            PreparedLine(
                key=name,
                data=rg.data.astype(np.float32),
                dt_ns=rg.dt_ns,
                t0_ns=rg.t0_ns,
                coords=to_world(local),
            )
        )
    return out


def _binned(lines, frame, k0, k1):
    plans = [plan_line(p, frame, _AXIS) for p in lines]
    return stream_slice(lines, plans, frame, _AXIS, k0, k1)


def _real_split():
    """Frame A holds lines 0-4; frame B (origin y = 2.6) holds 5-9 at B-local y 0.15..2.15."""
    frame_a = CubeFrame((0.0, 0.0), 0.0, CELL, 100, 13, "EPSG:32633")
    frame_b = CubeFrame((0.0, 2.6), 0.0, CELL, 100, 13, "EPSG:32633")
    world = lambda local: local  # noqa: E731 - lines keep their natural world positions
    return frame_a, frame_b, _lines(range(0, 5), world), _lines(range(5, 10), world)


def _split_slices(k, gain):
    frame_a, frame_b, lines_a, lines_b = _real_split()
    k0, k1 = _WINDOWS[k]
    va, ca = _binned(lines_a, frame_a, k0, k1)
    vb, cb = _binned(lines_b, frame_b, k0, k1)
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

    lines_a = _lines(range(0, 5), lambda local: local)
    lines_b = _lines(range(5, 10), rotate)
    k0, k1 = _WINDOWS[1]
    va, ca = _binned(lines_a, frame_a, k0, k1)
    vb, cb = _binned(lines_b, frame_b, k0, k1)

    seams = find_seams({"A": frame_a, "B": frame_b}, {"A": ca, "B": cb}, dict(A=SPACING, B=SPACING))
    assert [(s.a, s.b) for s in seams] == [("A", "B")]

    pixel = lattice_pixel(CELL, [frame_a.azimuth, frame_b.azimuth])
    assert pixel == CELL / 2
    lat = SiteLattice.covering([slice_extent(frame_a), slice_extent(frame_b)], pixel, crs)
    centres = lat.pixel_centres()
    layers = []
    covered = np.zeros(lat.n_pixels, dtype=bool)
    for frame, v, c in ((frame_a, va, ca), (frame_b, vb, cb)):
        ids = frame.cell_index(centres)
        populated = np.flatnonzero(c.ravel() > 0)
        assert np.isin(populated, ids).all()  # every populated cell is placed
        layers.append((ids, v))
        covered |= (ids >= 0) & np.isfinite(v.ravel()[np.clip(ids, 0, None)])
    out = compose(lat, layers)
    np.testing.assert_array_equal(np.isfinite(out).ravel(), covered)
    # Final review I1: composing each half over its own window gives the same bits.
    windows = [(footprint(ids.reshape(lat.height, lat.width)), v) for ids, v in layers]
    assert np.array_equal(compose_footprints(lat, windows), out, equal_nan=True)


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
    k0, k1 = _WINDOWS[k]
    slices, covs = {}, {}
    for g, frame in frames.items():
        v, c = _binned(_lines(members[g], lambda local: local), frame, k0, k1)
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
