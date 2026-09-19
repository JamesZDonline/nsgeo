from __future__ import annotations

import math
import warnings

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.slices.frame import CubeFrame, ZAxis
from nsgeo.velocity import VelocityModel


def frame(**kw):
    base = dict(origin=(0.0, 0.0), azimuth=0.0, cell=1.0, nx=4, ny=3, crs="EPSG:32633")
    base.update(kw)
    return CubeFrame(**base)


def test_n_cells_is_nx_times_ny():
    assert frame().n_cells == 12


def test_cell_index_is_row_major_iy_times_nx_plus_ix():
    f = frame()
    ids = f.cell_index(np.array([[0.5, 0.5], [3.5, 0.5], [0.5, 2.5]]))
    assert list(ids) == [0, 3, 8]


def test_cell_index_marks_points_outside_as_minus_one():
    """Outside is -1, never clipped: a trace that missed the frame is not
    evidence about its nearest edge cell."""
    f = frame()
    ids = f.cell_index(np.array([[-0.1, 0.5], [4.5, 0.5], [0.5, -2.0], [0.5, 3.5]]))
    assert list(ids) == [-1, -1, -1, -1]


def test_to_local_inverts_the_rotation():
    f = frame(origin=(100.0, 200.0), azimuth=30.0)
    x_hat, y_hat = f.axes()
    world = np.array([100.0, 200.0]) + 2.0 * x_hat + 5.0 * y_hat
    local = f.to_local(world[None, :])
    assert local[0, 0] == pytest.approx(2.0)
    assert local[0, 1] == pytest.approx(5.0)


def test_for_grid_covers_the_whole_grid():
    g = Grid(
        id="A",
        origin=(10.0, 20.0),
        azimuth=45.0,
        size_x=30.0,
        size_y=20.0,
        crs="EPSG:32633",
        default_spacing=0.5,
    )
    f = CubeFrame.for_grid(g, cell=0.25)
    assert (f.nx, f.ny) == (120, 80)
    assert f.origin == g.origin
    assert f.azimuth == g.azimuth
    assert f.crs == g.crs


def test_for_grid_rounds_a_ragged_extent_up_rather_than_dropping_it():
    g = Grid(
        id="A",
        origin=(0.0, 0.0),
        azimuth=0.0,
        size_x=10.1,
        size_y=10.0,
        crs="EPSG:32633",
        default_spacing=0.5,
    )
    assert CubeFrame.for_grid(g, cell=1.0).nx == 11


def test_for_points_contains_every_point_it_was_built_from():
    rng = np.random.default_rng(0)
    pts = rng.uniform(-5.0, 15.0, size=(200, 2))
    f = CubeFrame.for_points(pts, cell=0.5, crs="EPSG:32633", azimuth=17.0)
    assert (f.cell_index(pts) >= 0).all()


def test_for_points_contains_every_point_at_utm_magnitudes():
    """Regression: a boundary tolerance sized to the cell, not to the
    coordinate magnitude, is many orders of magnitude too small once
    coordinates are UTM-sized (~1e6). The round-off in for_points' own
    origin round-trip grows with that magnitude and can exceed a
    realistic GPR cell (0.05 m) outright, silently dropping the very
    points a frame was built to contain. Sweeps the seeds and azimuths
    of the toy-coordinate test above, translated to UTM magnitude, over
    three cell sizes down to 0.05 m."""
    offset = np.array([500_000.0, 4_500_000.0])
    for cell in (0.5, 0.1, 0.05):
        for seed in range(50):
            rng = np.random.default_rng(seed)
            pts = rng.uniform(-5.0, 15.0, size=(200, 2)) + offset
            for az in (0.0, 17.0, 33.3, 90.0, 123.4, -45.0):
                f = CubeFrame.for_points(pts, cell=cell, crs="EPSG:32633", azimuth=az)
                assert (f.cell_index(pts) >= 0).all(), (cell, seed, az)


def test_cell_index_keeps_a_point_a_hair_below_the_far_edge():
    """A point genuinely inside, one float ulp short of the frame's outer
    edge, must stay inside: a boundary tolerance that nudges every
    near-edge point rather than only ones that already floor outside
    would push this one across instead of rescuing it."""
    f = frame()
    ids = f.cell_index(np.array([[4.0 - 1e-12, 0.5]]))
    assert list(ids) == [3]


def test_cell_index_drops_non_finite_and_astronomically_large_coordinates():
    """A GPS dropout (NaN) or a corrupt, astronomically large coordinate
    must resolve to -1 deterministically, never through the undefined
    float->int cast that would otherwise decide the answer -- and never
    with a warning, so a future regression back to relying on the cast is
    caught by simplefilter('error') rather than silently reappearing.
    """
    f = CubeFrame(
        origin=(500_000.0, 4_500_000.0), azimuth=0.0, cell=0.05, nx=40, ny=20, crs="EPSG:32617"
    )
    world = np.array(
        [
            [500_000.5, 4_500_000.5],  # ordinary, inside
            [np.nan, 4_500_000.5],  # GPS dropout
            [1e20, 4_500_000.5],  # astronomically large, still finite
            [500_000.7, 4_500_000.7],  # ordinary, inside
        ]
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ids = f.cell_index(world)
    assert ids[1] == -1
    assert ids[2] == -1
    assert ids[0] >= 0
    assert ids[3] >= 0


def test_for_points_rejects_an_empty_array():
    with pytest.raises(ValueError, match="non-empty"):
        CubeFrame.for_points(np.empty((0, 2)), cell=0.5, crs="EPSG:32633")


def test_frame_rejects_a_non_positive_cell():
    with pytest.raises(ValueError, match="cell must be positive"):
        frame(cell=0.0)


def test_z_axis_times_start_at_t0_and_step_by_dz():
    z = ZAxis(t0_ns=2.0, dz_ns=0.5, nz=4)
    np.testing.assert_allclose(z.times_ns(), [2.0, 2.5, 3.0, 3.5])
    assert z.t_end_ns == pytest.approx(3.5)


def test_z_axis_from_range_includes_the_end():
    z = ZAxis.from_range(0.0, 50.0, 0.5)
    assert z.nz == 101
    assert z.t_end_ns == pytest.approx(50.0)


def test_z_axis_from_range_includes_the_end_when_the_division_is_not_exact_in_float():
    """Regression: 0.3 / 0.1 is a hair below 3.0 in double precision, so a
    plain floor() on an exactly-divisible (t1 - t0, dz) pair silently drops
    the final level that from_range's own name promises to include."""
    z = ZAxis.from_range(0.0, 0.3, 0.1)
    assert z.nz == 4
    assert z.t_end_ns == pytest.approx(0.3)


def test_z_axis_depths_use_the_velocity_model():
    z = ZAxis(t0_ns=0.0, dz_ns=1.0, nz=3)
    v = VelocityModel.constant(0.08)
    np.testing.assert_allclose(z.depths_m(v), [0.0, 0.04, 0.08])


def test_level_range_is_half_open_and_covers_the_window():
    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=101)
    k0, k1 = z.level_range(top_ns=12.0, thickness_ns=4.0)
    assert (k0, k1) == (24, 32)
    assert z.times_ns()[k0] == pytest.approx(12.0)
    assert z.times_ns()[k1 - 1] == pytest.approx(15.5)


def test_level_range_clamps_to_the_axis_and_never_empties():
    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=10)
    assert z.level_range(top_ns=-99.0, thickness_ns=1.0)[0] == 0
    k0, k1 = z.level_range(top_ns=100.0, thickness_ns=4.0)
    assert k1 == 10 and k1 > k0


def test_z_axis_rejects_a_non_positive_dz():
    with pytest.raises(ValueError, match="dz_ns must be positive"):
        ZAxis(t0_ns=0.0, dz_ns=0.0, nz=5)


def test_azimuth_convention_matches_grid():
    """CubeFrame must turn the same way as Grid or cubes land rotated."""
    g = Grid(
        id="A",
        origin=(0.0, 0.0),
        azimuth=37.0,
        size_x=10.0,
        size_y=10.0,
        crs="EPSG:32633",
        default_spacing=0.5,
    )
    f = CubeFrame.for_grid(g, cell=1.0)
    gx, gy = g.axes()
    fx, fy = f.axes()
    np.testing.assert_allclose(gx, fx)
    np.testing.assert_allclose(gy, fy)
    assert math.isclose(f.azimuth, 37.0)
