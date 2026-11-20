"""Fit a grid rectangle to GPS-placed line tracks (GPS lines spec §16).

Each track is an `(n, 2)` array of world positions in the site CRS, as
`Line.trace_coords(frames)` returns. A line's direction is an axis: a line and
its reverse point the same way, so directions are averaged on doubled angles.
Azimuths follow `Grid`: degrees clockwise from CRS north.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from nsgeo.geometry.grid import Grid

ALONG_DEG = 20.0
MIN_VOTE_M = 1.0
# "More than half" is judged with this much relative slack: a cross-hatch whose two
# halves differ in summed length by less than this (floating-point rounding, a
# millimetre of wobble) is still an even cross-hatch and has no main direction.
_HALF_SLACK = 1e-6


def _mod(value: float, modulus: float) -> float:
    """`value % modulus` in [0, modulus): Python's float % rounds a tiny negative up to modulus."""
    r = value % modulus
    return 0.0 if r >= modulus else r


def _finite(track: np.ndarray) -> np.ndarray:
    pts = np.asarray(track, dtype=float).reshape(-1, 2)
    return pts[np.isfinite(pts).all(axis=1)]


def _fold(azimuth: float) -> float:
    """Azimuth folded into (-90, 90]: +Y follows the axis, whichever way it was walked."""
    a = _mod(azimuth, 180.0)
    return a - 180.0 if a > 90.0 else a


def _votes(tracks: Sequence[np.ndarray]) -> list[tuple[int, float, float]]:
    """(track index, axis azimuth in [0, 180), chord length) for each voting track."""
    out: list[tuple[int, float, float]] = []
    for i, track in enumerate(tracks):
        pts = _finite(track)
        if len(pts) < 2:
            continue
        d = pts[-1] - pts[0]
        chord = float(math.hypot(d[0], d[1]))
        if chord < MIN_VOTE_M:
            continue
        out.append((i, _mod(math.degrees(math.atan2(d[0], d[1])), 180.0), chord))
    return out


def _axial_diff(a: float, b: float) -> float:
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _along(tracks: Sequence[np.ndarray]) -> tuple[float, list[int]] | None:
    """The main direction and the indices of the tracks running along it."""
    votes = _votes(tracks)
    if not votes:
        return None
    w = np.array([v[2] for v in votes])
    th = np.radians([2.0 * v[1] for v in votes])
    c, s = float(np.sum(w * np.cos(th))), float(np.sum(w * np.sin(th)))
    total = float(w.sum())
    if math.hypot(c, s) <= 1e-9 * total:
        return None
    main = _mod(math.degrees(math.atan2(s, c)) / 2.0, 180.0)
    along = [(i, ch) for i, az, ch in votes if _axial_diff(az, main) <= ALONG_DEG]
    if sum(ch for _, ch in along) <= 0.5 * total * (1.0 + _HALF_SLACK):
        return None
    return main, [i for i, _ in along]


def main_direction(tracks: Sequence[np.ndarray]) -> float | None:
    """The axial azimuth in [0, 180) the lines share, or None when they share none."""
    found = _along(tracks)
    return None if found is None else found[0]


def _cross_means(tracks: Sequence[np.ndarray], idx: Sequence[int], azimuth: float) -> list[float]:
    x_hat = Grid("", (0.0, 0.0), azimuth, 1.0, 1.0, "", 1.0).axes()[0]
    return [float(np.mean(_finite(tracks[i]) @ x_hat)) for i in idx]


def measure_spacing(tracks: Sequence[np.ndarray]) -> float | None:
    """The median gap between neighbouring along lines, or None if there is nothing to measure."""
    found = _along(tracks)
    if found is None or len(found[1]) < 2:
        return None
    means = np.sort(_cross_means(tracks, found[1], found[0]))
    gap = float(np.median(np.diff(means)))
    return gap if gap > 0.0 else None


@dataclass(frozen=True)
class TrackFrame:
    origin: tuple[float, float]
    azimuth: float
    size_x: float
    size_y: float
    lined_up: bool

    def as_grid(self, grid_id: str, crs: str, spacing: float) -> Grid:
        return Grid(grid_id, self.origin, self.azimuth, self.size_x, self.size_y, crs, spacing)


def _extents(pts: np.ndarray, azimuth: float) -> tuple[float, float, float, float]:
    x_hat, y_hat = Grid("", (0.0, 0.0), azimuth, 1.0, 1.0, "", 1.0).axes()
    c, s = pts @ x_hat, pts @ y_hat
    return float(c.min()), float(c.max()), float(s.min()), float(s.max())


def _build(
    azimuth: float, cmin: float, cmax: float, smin: float, smax: float, lined: bool
) -> TrackFrame:
    x_hat, y_hat = Grid("", (0.0, 0.0), azimuth, 1.0, 1.0, "", 1.0).axes()
    origin = cmin * x_hat + smin * y_hat
    return TrackFrame(
        (float(origin[0]), float(origin[1])), _mod(azimuth, 360.0), cmax - cmin, smax - smin, lined
    )


def _hull(pts: np.ndarray) -> np.ndarray:
    """Convex hull by monotone chain, counter-clockwise, without repeated end point."""
    p = np.unique(pts, axis=0)
    if len(p) < 3:
        return p
    seq = p.tolist()  # Python floats: the loop below is far slower over numpy scalars

    def half(points: list[list[float]]) -> list[list[float]]:
        out: list[list[float]] = []
        for q in points:
            while len(out) >= 2:
                a, b = out[-2], out[-1]
                if (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0]) <= 0.0:
                    out.pop()
                else:
                    break
            out.append(q)
        return out

    lower, upper = half(seq), half(seq[::-1])
    return np.array(lower[:-1] + upper[:-1])


def fit_frame(tracks: Sequence[np.ndarray], spacing: float) -> TrackFrame:
    """The grid rectangle around `tracks`, lined up with their main direction if they have one."""
    if len(tracks) == 0:
        raise ValueError("no tracks to fit")
    if not spacing > 0.0:
        raise ValueError(f"spacing must be positive, got {spacing}")
    clean = []
    for i, t in enumerate(tracks):
        pts = _finite(t)
        if len(pts) == 0:
            raise ValueError(f"track {i} has no finite point")
        clean.append(pts)
    allpts = np.vstack(clean)
    found = _along(clean)
    half = spacing / 2.0
    if found is not None:
        main, idx = found
        az = _fold(main)
        c0, c1, smin, smax = _extents(allpts, az)
        means = _cross_means(clean, idx, az)
        # Half a spacing outside the outer along lines, further where any trace
        # lies beyond that (a wandering outer line, a cross line): every trace
        # is inside, none is left out of the slices (walkthrough W3).
        cmin, cmax = min(min(means) - half, c0), max(max(means) + half, c1)
        return _build(az, cmin, cmax, smin, smax, True)
    hull = _hull(allpts)
    angles = [0.0]
    if len(hull) >= 2:
        edges = np.roll(hull, -1, axis=0) - hull
        angles = [math.degrees(math.atan2(e[0], e[1])) for e in edges if np.any(e)] or [0.0]
    best_az, best_area = 0.0, math.inf
    for a in angles:
        a = _fold(a)
        c0, c1, s0, s1 = _extents(hull, a)
        area = (c1 - c0) * (s1 - s0)
        if area < best_area - 1e-12:
            best_az, best_area = a, area
    c0, c1, s0, s1 = _extents(hull, best_az)
    if c1 - c0 > s1 - s0:
        best_az = _fold(best_az + 90.0)
        c0, c1, s0, s1 = _extents(hull, best_az)
    return _build(best_az, c0 - half, c1 + half, s0 - half, s1 + half, False)


def metres_outside(grid: Grid, xy: np.ndarray) -> tuple[float, bool]:
    """Metres of steps whose midpoint is outside `grid`, and whether any trace is inside."""
    local = grid.to_local(np.asarray(xy, dtype=float).reshape(-1, 2))

    def inside(p: np.ndarray) -> np.ndarray:
        return (
            (p[:, 0] >= 0.0)
            & (p[:, 0] <= grid.size_x)
            & (p[:, 1] >= 0.0)
            & (p[:, 1] <= grid.size_y)
        )

    any_in = bool(inside(local).any())
    if len(local) < 2:
        return 0.0, any_in
    a, b = local[:-1], local[1:]
    step = np.hypot(*(b - a).T)
    ok = np.isfinite(step)
    outside = ~inside((a + b) / 2.0) & ok
    return float(step[outside].sum()), any_in
