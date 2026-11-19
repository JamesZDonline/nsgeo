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


def test_a_long_cut_wall_is_capped_at_300_columns():
    frame = CubeFrame((0.0, 0.0), 0.0, 0.05, 2000, 4, "EPSG:32633")
    filled = _ramp_cube(2, 4, 2000)
    # 100 m on a 0.05 m cell would be 4001 columns uncapped
    wall = cut_wall(filled, frame, np.array([[0.5, 0.1], [100.5, 0.1]]))
    assert wall.values.shape[1] == 300 and wall.local.shape == (300, 2)


def _column(nz: int = 40) -> np.ndarray:
    rng = np.random.default_rng(3)
    return (rng.normal(size=nz) * np.hanning(nz) * 5.0).astype(np.float32)


def test_a_wall_is_put_on_the_volumes_amplitude_scale():
    from nsgeo.slices.volume import _rms_levels
    from nsgeo.slices.walls import Wall, wall_amplitude

    nz, w = 40, 5
    squared = _column(nz) ** 2
    wall = Wall(local=np.zeros((2, 2)), values=np.stack([squared, 2.0 * squared], axis=1))
    out = wall_amplitude(wall, w, squared=True)
    # the volume's own helper, on a cube whose every cell holds the first column
    cube = np.broadcast_to(squared[:, None, None], (nz, 2, 2)).astype(np.float32)
    want = _rms_levels(cube, np.ones((2, 2), bool), w, 0, nz - 1, nz)[:, 0, 0]
    np.testing.assert_allclose(out.values[:, 0], want, rtol=1e-5)
    # and the plain formula: sqrt of the mean over the window, the edge level repeated
    padded = np.pad(squared.astype(np.float64), (w // 2, w - w // 2 - 1), mode="edge")
    by_hand = np.sqrt(np.array([padded[i : i + w].mean() for i in range(nz)]))
    np.testing.assert_allclose(out.values[:, 0], by_hand, rtol=1e-5)
    np.testing.assert_allclose(out.values[:, 1], np.sqrt(2.0) * by_hand, rtol=1e-5)
    assert out.values.dtype == np.float32 and out.local is wall.local


def test_wall_amplitude_squares_what_is_not_squared_keeps_nan_and_drops_levels_above_first():
    from nsgeo.slices.walls import Wall, wall_amplitude

    nz = 20
    env = np.abs(_column(nz)) + 0.1  # an envelope, not squared
    values = np.stack([env, env], axis=1).copy()
    values[:3, 1] = np.nan
    wall = Wall(local=np.zeros((2, 2)), values=values)
    out = wall_amplitude(wall, 3, squared=False, first=4)
    same = wall_amplitude(Wall(wall.local, values[:, :1] ** 2), 3, squared=True)
    assert out.values.shape == (nz - 4, 2)
    np.testing.assert_allclose(out.values[:, 0], same.values[4:, 0], rtol=1e-5)
    # the NaN rows were dropped with `first`; a NaN left below it would stay NaN
    values2 = values.copy()
    values2[10, 1] = np.nan
    out2 = wall_amplitude(Wall(wall.local, values2), 3, squared=False, first=4)
    assert np.isnan(out2.values[10 - 4, 1]) and np.isfinite(out2.values[:, 0]).all()


def test_the_cut_column_rule_is_one_function():
    from nsgeo.slices.walls import cut_wall_columns

    frame = CubeFrame((0.0, 0.0), 0.0, 1.0, 20, 4, "EPSG:32633")
    path = np.array([[2.5, 2.0], [17.5, 2.0]])
    assert cut_wall_columns(path, 1.0) == cut_wall(_ramp_cube(), frame, path).values.shape[1] == 31
    with pytest.raises(ValueError):
        cut_wall_columns(np.array([[1.0, 1.0], [1.0, 1.0]]), 1.0)
    with pytest.raises(OverflowError):
        cut_wall_columns(np.array([[0.0, 0.0], [np.inf, 0.0]]), 1.0)
