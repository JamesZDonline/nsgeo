"""Walls: curtains of amplitude standing under a line or a cut (M16 D).

A wall is a (levels x columns) sheet sampled on the cube's own time levels,
coloured like the slices: a line's values are its prepared (processed and
transformed) data, a cut's are the filled cube's. Numpy only; the ParaView
export turns a wall into a StructuredGrid with `wall_points`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from nsgeo.slices.binning import PreparedLine
from nsgeo.slices.frame import CubeFrame, ZAxis
from nsgeo.slices.resample import bilinear_taps, sample
from nsgeo.slices.volume import _rms_levels

__all__ = [
    "MAX_WALL_COLUMNS",
    "Wall",
    "cut_wall",
    "cut_wall_columns",
    "line_wall",
    "wall_amplitude",
    "wall_columns",
    "wall_points",
]

MAX_WALL_COLUMNS = 300


@dataclass(frozen=True, eq=False)
class Wall:
    """`local` is (n, 2) frame-local metres along the wall; `values` is (nz, n) float32,
    NaN where nothing was recorded."""

    local: np.ndarray
    values: np.ndarray


def wall_columns(n: int) -> int:
    """How many columns a wall of `n` candidate columns keeps."""
    if n < 2:
        raise ValueError(f"a wall needs at least 2 columns, got {n}")
    return min(n, MAX_WALL_COLUMNS)


def line_wall(line: PreparedLine, frame: CubeFrame, z: ZAxis) -> Wall:
    """The line's prepared data at the cube's levels, on up to 300 evenly spaced traces.

    The line's time axis is the cube's clock, as in `plan_line`; levels outside
    the line's recorded range are NaN.
    """
    n_samples, n_traces = line.data.shape
    if n_samples < 2:
        raise ValueError(f"line {line.key!r} has {n_samples} samples; need at least 2")
    traces = np.unique(
        np.round(np.linspace(0, n_traces - 1, wall_columns(n_traces))).astype(np.intp)
    )
    position = (z.times_ns() - line.t0_ns) / line.dt_ns
    tol = 1e-9
    inside = (position >= -tol) & (position <= n_samples - 1 + tol)
    index = np.clip(np.floor(position).astype(np.intp), 0, n_samples - 2)
    weight = np.clip(position - index, 0.0, 1.0).astype(np.float32)[:, None]
    cols = line.data[:, traces]
    values = cols[index] * (1.0 - weight) + cols[index + 1] * weight
    values = values.astype(np.float32, copy=False)
    values[~inside] = np.nan
    return Wall(local=frame.to_local(line.coords[traces]), values=values)


def _path(path_local: np.ndarray) -> np.ndarray:
    path = np.asarray(path_local, dtype=float)
    if path.ndim != 2 or path.shape[1] != 2 or path.shape[0] < 2:
        raise ValueError(f"expected an (m >= 2, 2) path, got {path.shape}")
    return path


def cut_wall_columns(path_local: np.ndarray, cell: float) -> int:
    """How many columns a wall along this path (frame-local metres) has: about two a cell,
    at most 300. ValueError for a path with no length (or a bad shape), OverflowError for
    one that is not finite."""
    path = _path(path_local)
    length = float(np.hypot(*np.diff(path, axis=0).T).sum())
    return wall_columns(math.ceil(length / (cell / 2.0)) + 1)


def cut_wall(filled: np.ndarray, frame: CubeFrame, path_local: np.ndarray) -> Wall:
    """The filled (nz, ny, nx) cube sampled along a cut's polyline (frame-local metres).

    Columns are evenly spaced by distance, about two a cell, up to 300.
    """
    path = _path(path_local)
    along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(path, axis=0).T))])
    length = float(along[-1])
    n = cut_wall_columns(path, frame.cell)
    at = np.linspace(0.0, length, n)
    local = np.column_stack([np.interp(at, along, path[:, 0]), np.interp(at, along, path[:, 1])])
    x_hat, y_hat = frame.axes()
    world = np.asarray(frame.origin, dtype=float) + local[:, :1] * x_hat + local[:, 1:] * y_hat
    taps = bilinear_taps(frame, world)
    values = np.stack([sample(filled[k], taps) for k in range(filled.shape[0])])
    return Wall(local=local, values=values.astype(np.float32, copy=False))


def wall_amplitude(wall: Wall, window: int, *, squared: bool, first: int = 0) -> Wall:
    """The wall on the volume's amplitude scale, so it agrees with a slice through the cube.

    The cube's `amplitude` is the square root of the mean of the squared amplitude over
    `window` levels (`volume._rms_levels`, with its edge padding), blurred sideways. This
    does the same down each column and leaves the blur out. `squared` says whether the
    values already are squared amplitude (a cut's always are; a line's are under
    `amp_square`); otherwise they are squared first. NaN stays NaN. `first` drops the
    levels above it afterwards (the cube keeps only the levels from time zero), after the
    window has looked at them as the volume's does.
    """
    values = wall.values.astype(np.float64)
    nothing = np.isnan(values)
    values[nothing] = 0.0
    if not squared:
        values = values * values
    nz, n = values.shape
    cover = np.ones((1, n), dtype=bool)
    rms = _rms_levels(values[:, None, :], cover, window, 0, nz - 1, nz)[:, 0, :]
    rms[nothing] = np.nan
    return Wall(local=wall.local, values=rms[first:].astype(np.float32))


def wall_points(wall: Wall, depth_m: np.ndarray, stretch: float) -> np.ndarray:
    """(nz, n, 3) points: the wall's x, y and z = -depth * stretch per level."""
    depth = np.asarray(depth_m, dtype=float)
    nz, n = wall.values.shape
    if depth.shape != (nz,):
        raise ValueError(f"expected {nz} depths, got {depth.shape}")
    out = np.empty((nz, n, 3))
    out[:, :, :2] = wall.local[None, :, :]
    out[:, :, 2] = (-depth * stretch)[:, None]
    return out
