"""Walls: curtains under a line and under a cut, on the cube's own levels (M16 D)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from nsgeo.slices import CubeFrame, PreparedLine, ZAxis
from nsgeo.slices.walls import (
    MAX_WALL_COLUMNS,
    Wall,
    cut_wall,
    line_wall,
    wall_columns,
    wall_points,
)

from tests.real_lines import AXIS, CELL, needs_real_files, prepared_lines


def _frame() -> CubeFrame:
    return CubeFrame((0.0, 0.0), 0.0, CELL, 100, 25, "EPSG:32633")


@needs_real_files
def test_a_line_wall_follows_the_line_at_the_cubes_levels():
    line = prepared_lines([0], lambda local: local)[0]
    frame = _frame()
    z = AXIS
    wall = line_wall(line, frame, z)
    assert wall.values.shape == (z.nz, wall_columns(line.data.shape[1]))
    assert wall.values.dtype == np.float32
    k = z.nz // 2
    t = z.times_ns()[k]
    i = int(round((t - line.t0_ns) / line.dt_ns))
    assert wall.values[k, 0] == pytest.approx(line.data[i, 0], rel=0.05)  # near a sample
    # a wrong clock would land on another sample: compare the whole column at level k
    last = wall.values.shape[1] - 1
    assert wall.values[k, last] == pytest.approx(line.data[i, line.data.shape[1] - 1], rel=0.05)
    assert np.allclose(wall.local[0], frame.to_local(line.coords[:1])[0])
    assert np.allclose(wall.local[-1], frame.to_local(line.coords[-1:])[0])


def test_a_line_wall_interpolates_between_samples_on_the_cube_clock():
    # data[i, j] = 10 * i + j, so a level at sample position p reads 10 * p + j
    n_samples, n_traces = 20, 5
    data = (10.0 * np.arange(n_samples)[:, None] + np.arange(n_traces)[None, :]).astype(np.float32)
    coords = np.column_stack([np.arange(n_traces) * 0.1, np.zeros(n_traces)])
    line = PreparedLine("a", data, dt_ns=0.5, t0_ns=2.0, coords=coords)
    z = ZAxis(3.25, 0.5, 4)  # sample positions 2.5, 3.5, 4.5, 5.5
    wall = line_wall(line, CubeFrame((0.0, 0.0), 0.0, 0.1, 10, 3, "EPSG:32633"), z)
    expect = 10.0 * (2.5 + np.arange(4))[:, None] + np.arange(n_traces)[None, :]
    assert np.allclose(wall.values, expect)
    assert np.allclose(wall.local, coords)


def test_a_line_wall_is_nan_outside_the_lines_time_range():
    data = np.ones((10, 4), dtype=np.float32)  # samples at 5.0 .. 9.5 ns
    coords = np.column_stack([np.arange(4) * 0.1, np.zeros(4)])
    line = PreparedLine("a", data, dt_ns=0.5, t0_ns=5.0, coords=coords)
    z = ZAxis(4.0, 1.0, 8)  # 4 .. 11 ns
    wall = line_wall(line, CubeFrame((0.0, 0.0), 0.0, 0.1, 10, 3, "EPSG:32633"), z)
    inside = (z.times_ns() >= 5.0) & (z.times_ns() <= 9.5)
    assert inside.sum() == 5
    assert np.isnan(wall.values[~inside]).all()
    assert np.allclose(wall.values[inside], 1.0)


def test_a_long_line_wall_is_capped_at_300_columns():
    n = 1000
    data = np.tile(np.arange(n, dtype=np.float32), (6, 1))
    coords = np.column_stack([np.linspace(0, 9.99, n), np.zeros(n)])
    line = PreparedLine("a", data, dt_ns=1.0, t0_ns=0.0, coords=coords)
    z = ZAxis(0.0, 1.0, 4)
    wall = line_wall(line, CubeFrame((0.0, 0.0), 0.0, 0.1, 100, 3, "EPSG:32633"), z)
    assert MAX_WALL_COLUMNS == 300
    assert wall.values.shape == (4, 300) and wall.local.shape == (300, 2)
    cols = wall.values[0]
    assert cols[0] == 0 and cols[-1] == n - 1  # both ends kept
    assert (np.diff(cols) > 0).all()  # evenly spaced, in order, no repeats
    assert wall_columns(40) == 40 and wall_columns(2) == 2 and wall_columns(5000) == 300
    for bad in (0, 1):
        with pytest.raises(ValueError):
            wall_columns(bad)


def _ramp_cube(nz: int = 3, ny: int = 4, nx: int = 20) -> np.ndarray:
    # value = cell column index + 100 * level
    ramp = np.broadcast_to(np.arange(nx, dtype=np.float32), (ny, nx))
    return np.stack([ramp + 100.0 * k for k in range(nz)])


def test_a_cut_wall_samples_the_filled_cube_along_the_cut():
    frame = CubeFrame((0.0, 0.0), 0.0, 1.0, 20, 4, "EPSG:32633")
    filled = _ramp_cube()
    # a cut along x at y = 2, from the centre of column 2 to the centre of column 17
    path = np.array([[2.5, 2.0], [17.5, 2.0]])
    wall = cut_wall(filled, frame, path)
    length = 15.0
    n = wall_columns(math.ceil(length / (frame.cell / 2)) + 1)
    assert wall.values.shape == (3, n) and wall.values.dtype == np.float32
    assert np.allclose(wall.local[:, 0], np.linspace(2.5, 17.5, n))
    assert np.allclose(wall.local[:, 1], 2.0)
    for k in range(3):
        assert np.allclose(wall.values[k], np.linspace(2.0, 17.0, n) + 100.0 * k, atol=1e-3)


def test_a_cut_wall_follows_a_bent_path_and_a_rotated_frame():
    frame = CubeFrame((50.0, 70.0), 30.0, 1.0, 20, 20, "EPSG:32633")
    filled = _ramp_cube(2, 20, 20)
    path = np.array([[2.5, 5.0], [2.5, 10.0], [12.5, 10.0]])  # up 5 m, then along x 10 m
    wall = cut_wall(filled, frame, path)
    n = wall.values.shape[1]
    assert np.allclose(wall.local[0], path[0]) and np.allclose(wall.local[-1], path[-1])
    # the path's x is what the ramp reads, wherever on the polyline the column is
    assert np.allclose(wall.values[0], wall.local[:, 0] - 0.5, atol=1e-3)
    assert n == wall_columns(math.ceil(15.0 / 0.5) + 1)
    # evenly spaced by distance
    step = np.hypot(*np.diff(wall.local, axis=0).T)
    assert step.max() <= 15.0 / (n - 1) + 1e-9


def test_a_cut_wall_is_nan_where_the_cube_has_no_data():
    frame = CubeFrame((0.0, 0.0), 0.0, 1.0, 20, 4, "EPSG:32633")
    filled = _ramp_cube()
    filled[:, :, 8:12] = np.nan  # a hole in the middle
    path = np.array([[0.5, 2.0], [19.5, 2.0]])
    wall = cut_wall(filled, frame, path)
    x = wall.local[:, 0]
    deep_in = (x > 8.5 + 1e-6) & (x < 10.5)  # both bilinear neighbours blank or nearest is
    assert deep_in.any()
    assert np.isnan(wall.values[:, deep_in]).all()
    assert np.isfinite(wall.values[:, x < 7.0]).all()
    assert np.isfinite(wall.values[:, x > 13.0]).all()
    # and past the frame's edge there is nothing either
    off = cut_wall(filled, frame, np.array([[18.0, 2.0], [26.0, 2.0]]))
    assert np.isnan(off.values[:, off.local[:, 0] > 20.0]).all()


def test_wall_points_stand_at_stretched_depth():
    wall = Wall(
        local=np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]),
        values=np.zeros((2, 3), dtype=np.float32),
    )
    pts = wall_points(wall, np.array([0.5, 1.5]), 2.0)
    assert pts.shape == (2, 3, 3)
    assert np.allclose(pts[0, :, :2], wall.local) and np.allclose(pts[1, :, :2], wall.local)
    assert np.allclose(pts[0, :, 2], -1.0) and np.allclose(pts[1, :, 2], -3.0)
    with pytest.raises(ValueError):
        wall_points(wall, np.array([0.5]), 1.0)
