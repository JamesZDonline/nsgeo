from __future__ import annotations

import math

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
