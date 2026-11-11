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

Counts (coverage) are never blended: `sample_counts` takes the smallest
count among the corners, so a gap is never hidden. It can look up to one
cell wider than the nearest-cell outline.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from nsgeo.slices.frame import CubeFrame

_EPS = float(np.finfo(float).eps)
_BELOW_ONE = np.nextafter(np.float32(1.0), np.float32(0.0))


@dataclass(frozen=True, eq=False)
class Taps:
    """Where each of n world points sits among a frame's cells."""

    nearest: np.ndarray  # (n,) int32 flat cell id, -1 outside
    ix0: np.ndarray  # (n,) int32 lower corner of the 2x2 block
    iy0: np.ndarray  # (n,) int32
    tx: np.ndarray  # (n,) float32 in [0, 1)
    ty: np.ndarray  # (n,) float32 in [0, 1)
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
        return int(
            self.nearest.nbytes
            + self.ix0.nbytes
            + self.iy0.nbytes
            + self.tx.nbytes
            + self.ty.nbytes
        )

    def take(self, index: np.ndarray) -> Taps:
        """The taps of a subset of the points, in the order given."""
        return _make(
            self.nearest[index],
            self.ix0[index],
            self.iy0[index],
            self.tx[index],
            self.ty[index],
            self.nx,
            self.ny,
        )


def _make(
    nearest: np.ndarray,
    ix0: np.ndarray,
    iy0: np.ndarray,
    tx: np.ndarray,
    ty: np.ndarray,
    nx: int,
    ny: int,
) -> Taps:
    inside = nearest >= 0
    exact = bool(not (tx[inside].any() or ty[inside].any()))
    for a in (nearest, ix0, iy0, tx, ty):
        a.setflags(write=False)
    return Taps(nearest, ix0, iy0, tx, ty, nx, ny, exact)


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
    return _make(
        nearest,
        base[:, 0].astype(np.int32),
        base[:, 1].astype(np.int32),
        np.ascontiguousarray(t[:, 0]),
        np.ascontiguousarray(t[:, 1]),
        frame.nx,
        frame.ny,
    )


def _corners(values: np.ndarray, taps: Taps) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Yield (weight, value, in_frame) for the four corners of every point."""
    tx = taps.tx.astype(np.float64)
    ty = taps.ty.astype(np.float64)
    for dy in (0, 1):
        wy = ty if dy else 1.0 - ty
        iy = taps.iy0.astype(np.intp) + dy
        for dx in (0, 1):
            wx = tx if dx else 1.0 - tx
            ix = taps.ix0.astype(np.intp) + dx
            ok = taps.inside & (ix >= 0) & (ix < taps.nx) & (iy >= 0) & (iy < taps.ny)
            v = np.where(
                ok, values[np.clip(iy, 0, taps.ny - 1), np.clip(ix, 0, taps.nx - 1)], np.nan
            )
            yield wx * wy, v, ok


def sample(values: np.ndarray, taps: Taps) -> np.ndarray:
    """(ny, nx) values -> (n,) float32: the bilinear blend at each point."""
    values = np.asarray(values)
    if values.shape != (taps.ny, taps.nx):
        raise ValueError(f"expected values of shape {(taps.ny, taps.nx)}, got {values.shape}")
    flat = values.ravel()
    if taps.exact:
        out = np.full(taps.n, np.nan, dtype=np.float32)
        ids = taps.nearest
        out[taps.inside] = flat[ids[taps.inside]]
        return out
    num = np.zeros(taps.n)
    den = np.zeros(taps.n)
    for w, v, ok in _corners(values.astype(np.float64, copy=False), taps):
        use = ok & np.isfinite(v)
        num += np.where(use, w * np.where(use, v, 0.0), 0.0)
        den += np.where(use, w, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(den > 0.0, num / den, np.nan)
    nearest_value = np.where(taps.inside, flat[np.clip(taps.nearest, 0, None)], np.nan)
    out = np.where(np.isfinite(nearest_value), out, np.nan)
    return out.astype(np.float32)


def sample_counts(counts: np.ndarray, taps: Taps) -> np.ndarray:
    """(ny, nx) counts -> (n,) float32: the smallest in-frame corner count.

    NaN where the point is outside or any in-frame corner is non-finite or
    not positive, so "count 0" is never hidden by a neighbour.
    """
    counts = np.asarray(counts)
    if counts.shape != (taps.ny, taps.nx):
        raise ValueError(f"expected counts of shape {(taps.ny, taps.nx)}, got {counts.shape}")
    smallest = np.full(taps.n, np.inf)
    bad = ~taps.inside
    for _, v, ok in _corners(counts.astype(np.float64, copy=False), taps):
        bad |= ok & ~(np.isfinite(v) & (v > 0.0))
        smallest = np.where(ok, np.minimum(smallest, np.where(ok, v, np.inf)), smallest)
    return np.where(bad | ~np.isfinite(smallest), np.nan, smallest).astype(np.float32)
