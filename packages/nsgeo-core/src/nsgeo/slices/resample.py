"""Resampling a slice from its own cell frame onto north-up pixels.

The rule: each output pixel blends the four cells around it with bilinear
weights, and is blank exactly where the nearest cell is blank (or outside
the frame). The outline therefore never moves from today's nearest-cell
rule; only the values inside it are smoothed. Blank neighbours are dropped
and the remaining weights re-normalised, so a gap's edge is not dragged
towards zero. Amplitudes are compared relatively, not absolutely (author,
2026-11-06), which is what makes a blend acceptable here.

This replaces drawing rotated grids at half the cell pitch. Measured in
the design spec: nearest-cell at the cell size drops 2.7% of cells at a
10.5 degree azimuth (no pixel centre falls in them), and at half pitch 23%
of zoomed-in pixels show a neighbouring cell's value. Bilinear at the cell
pitch drops no cell's influence and shows no stair-stepped neighbour.

Counts (coverage) are never blended: `sample_counts` takes the largest
count among the corners, so a line one cell wide stays visible. A gap of
about a cell or less beside data can close.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nsgeo.slices.frame import CubeFrame

_EPS = float(np.finfo(float).eps)
_BELOW_ONE = np.nextafter(np.float32(1.0), np.float32(0.0))


@dataclass(frozen=True, eq=False)
class Taps:
    """Where each of n world points sits among a frame's cells.

    The four corners of the 2x2 block around each point are precomputed:
    `ids` (4, n) intp flat cell ids, clipped in-bounds, and `weights`
    (4, n) float32 bilinear weights, exactly 0 for a corner outside the
    frame and for every corner of a point outside it. Corner order is
    (dy, dx) = (0, 0), (0, 1), (1, 0), (1, 1). 52 bytes a point (was 20):
    `ids` is intp because numpy gathers 2x faster with it than with int32,
    which it would otherwise convert on every call.
    """

    nearest: np.ndarray  # (n,) int32 flat cell id, -1 outside
    ids: np.ndarray  # (4, n) intp, safe to gather with
    weights: np.ndarray  # (4, n) float32, 0 where not in the frame
    nx: int
    ny: int
    exact: bool  # every inside point sits on a cell centre

    @property
    def inside(self) -> np.ndarray:
        return self.nearest >= 0

    @property
    def n(self) -> int:
        return int(self.nearest.shape[0])

    @property
    def nbytes(self) -> int:
        return int(self.nearest.nbytes + self.ids.nbytes + self.weights.nbytes)

    def take(self, index: np.ndarray) -> Taps:
        """The taps of a subset of the points, in the order given."""
        return _make(
            self.nearest[index], self.ids[:, index], self.weights[:, index], self.nx, self.ny
        )


def _make(nearest: np.ndarray, ids: np.ndarray, weights: np.ndarray, nx: int, ny: int) -> Taps:
    inside = nearest >= 0
    # Exact: each inside point's whole weight sits on its first corner.
    exact = bool((weights[0][inside] == 1.0).all())
    for a in (nearest, ids, weights):
        a.setflags(write=False)
    return Taps(nearest, ids, weights, nx, ny, exact)


def bilinear_taps(frame: CubeFrame, world: np.ndarray) -> Taps:
    """Taps for (n, 2) world points in the frame's CRS."""
    world = np.asarray(world, dtype=float)
    nearest = frame.cell_index(world).astype(np.int32)
    inside = nearest >= 0
    f = frame.to_local(world) / frame.cell - 0.5
    f = np.where(inside[:, None], f, 0.0)
    # Snap to a whole cell within cell_index's scale-aware margin, so a cell
    # centre gives tx == 0 rather than 0.9999999 one cell over.
    tol = 64.0 * _EPS * np.maximum(1.0, np.abs(world).max(axis=1)) / frame.cell
    rounded = np.round(f)
    f = np.where(np.abs(f - rounded) <= tol[:, None], rounded, f)
    base = np.floor(f)
    t = np.minimum((f - base).astype(np.float32), _BELOW_ONE)
    tx, ty = t[:, 0], t[:, 1]
    ix0 = base[:, 0].astype(np.int64)
    iy0 = base[:, 1].astype(np.int64)
    n = world.shape[0]
    ids = np.empty((4, n), dtype=np.intp)
    weights = np.empty((4, n), dtype=np.float32)
    k = 0
    for dy in (0, 1):
        wy = ty if dy else np.float32(1.0) - ty
        iy = iy0 + dy
        for dx in (0, 1):
            wx = tx if dx else np.float32(1.0) - tx
            ix = ix0 + dx
            ok = inside & (ix >= 0) & (ix < frame.nx) & (iy >= 0) & (iy < frame.ny)
            ids[k] = np.where(ok, iy * frame.nx + ix, 0)
            weights[k] = np.where(ok, wx * wy, np.float32(0.0))
            k += 1
    return _make(nearest, ids, weights, frame.nx, frame.ny)


def _flat32(values: np.ndarray, taps: Taps) -> np.ndarray:
    values = np.asarray(values)
    if values.shape != (taps.ny, taps.nx):
        raise ValueError(f"expected values of shape {(taps.ny, taps.nx)}, got {values.shape}")
    return np.ascontiguousarray(values, dtype=np.float32).ravel()


def sample(values: np.ndarray, taps: Taps) -> np.ndarray:
    """(ny, nx) values -> (n,) float32: the bilinear blend at each point."""
    flat = _flat32(values, taps)
    nearest_value = flat[np.maximum(taps.nearest, 0)]
    # blank where outside (nearest < 0) or the nearest cell is not finite
    blank = ~np.isfinite(nearest_value)
    blank |= taps.nearest < 0
    if taps.exact:
        # inf in a nearest cell is blank, as on the slow path.
        nearest_value[blank] = np.nan
        return nearest_value
    # One gather; blank neighbours are dropped by weighting. The blend is of
    # offsets from the nearest value, added back at the end: in float32 a
    # plain num/den is an ulp off, so a constant field would not resample to
    # itself and a plateau at the maximum could leave the input's range.
    base = np.where(blank, np.float32(0.0), nearest_value)
    v = flat[taps.ids]
    finite = np.isfinite(v)
    v -= base
    v[~finite] = 0.0
    num = np.einsum("kn,kn->n", taps.weights, v)
    den = np.einsum("kn,kn->n", taps.weights, finite.astype(np.float32))
    blank |= ~(den > 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        np.divide(num, den, out=num)
    num += base
    num[blank] = np.nan
    return num


def sample_counts(counts: np.ndarray, taps: Taps) -> np.ndarray:
    """(ny, nx) counts -> (n,) float32: the largest in-frame corner count.

    Only corners with positive weight are looked at. NaN where the point is
    outside the frame or every such corner is non-finite or not positive,
    so a line one cell wide stays visible, and a pixel is blank only where
    all the cells it would blend are empty.
    """
    flat = _flat32(counts, taps)
    v = flat[taps.ids]
    good = (taps.weights > 0.0) & np.isfinite(v) & (v > 0.0)
    largest = np.where(good, v, np.float32(-np.inf)).max(axis=0)
    blank = ~good.any(axis=0) | ~taps.inside
    return np.where(blank, np.float32(np.nan), largest).astype(np.float32, copy=False)
