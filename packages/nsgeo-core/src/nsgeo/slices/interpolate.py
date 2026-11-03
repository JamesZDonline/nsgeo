"""Filling the space between lines by interpolation, limited by a max distance.

An empty cell is filled only when a data cell lies within the max distance;
beyond it the cell stays blank, so a skipped or wandering line shows as a
stripe instead of being papered over (interpolation spec §5.2). A data cell is
never changed.

Which cells get filled, and from which neighbours with which weights, depends
only on where data is, never on its values (interpolation spec §7). So the work is split:
`plan_fill` builds a sparse weights table once per grid, method and distance,
and `FillWeights.apply` turns it into a slice with one gather and one sum.
That is why scrubbing through slices stays cheap although kriging is dear.

Neighbours are the 3 nearest data cells in each of four quadrants (interpolation spec §5.3).
Plain nearest-N would pick all its cells from one side of a single line and
leave a step wherever the choice switched; quadrants make every cell between
two lines draw on both, and a cell beside the outermost line draw on one.

numpy only, no scipy. Measured medians for the plan and for one apply, on a
50 m x 50 m grid of lines 0.5 m apart along X (max distance 0.25 m, search
radius 1.0 m) and on the ten real lines (25 x 100 cells at 0.2 m). The 50 m
rows were re-measured once the plan ran in chunks (`_PLAN_CHUNK`); on the
same machine one pass had taken 0.67 / 0.65 s at 0.1 m and 6.5 / 6.4 s at
0.05 m, and the 0.75 x spacing default costs the same:

    case                  plan IDW   plan kriging   apply
    real lines, 0.2 m     0.006 s    0.006 s        0.1 ms
    50 m grid, 0.2 m      0.08 s     0.07 s         2 ms
    50 m grid, 0.1 m      0.59 s     0.48 s         9-10 ms
    50 m grid, 0.05 m     5.4 s      5.4 s          50-75 ms
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

METHODS: tuple[str, ...] = ("none", "idw", "kriging")
NEIGHBOURS_PER_QUADRANT: int = 3
# The limit is inclusive: a cell exactly halfway between lines must fill. The
# tolerance keeps hypot(...) * cell on the right side of the comparison.
DISTANCE_TOL_M: float = 1e-9
IDW_POWER = 2  # (interpolation spec §5.1)

_SLOTS = 4 * NEIGHBOURS_PER_QUADRANT
_PRUNE_EVERY = 32  # offsets between dropping targets whose quadrants are all full
# Targets per pass of the stages after the neighbour search, and kriging
# systems per np.linalg.solve. Both bound a working set that otherwise grows
# with the grid: one pass over every target at once peaked near 6 x the
# weights it kept (466-561 B a cell, wandering 0.5 m lines at 0.1 and 0.05 m),
# against the 96 B a cell `MemoryEstimate` counts. A pass costs about 0.5 KB
# a target and a kriging system about 7 KB, so planning stays within about
# 20 MB of the weights it returns whatever the grid: measured 4 MB over them
# on line data, 18 MB on a random mask where every pattern is new. No weight
# depends on them: a target's offsets and weights are its own, and each
# system is solved on its own (checked bit for bit against one pass).
_PLAN_CHUNK = 8192
_SOLVE_CHUNK = 2048
_EMPTY = np.iinfo(np.int32).min  # offset sentinel for an empty slot in pattern keys


@dataclass(frozen=True, eq=False)
class FillWeights:
    """Where to fill and from what. Built by `plan_fill`; values never enter it."""

    shape: tuple[int, int]
    populated: np.ndarray  # (ny*nx,) bool: cells that hold data
    targets: np.ndarray  # (m,) intp, ascending flat ids of empty cells to fill
    sources: np.ndarray  # (m, 12) int32 flat ids, -1 = empty slot
    weights: np.ndarray  # same shape, float32, 0.0 in empty slots

    def _blend(self, rows: np.ndarray | slice, flat: np.ndarray) -> np.ndarray:
        """Σ wᵢvᵢ / Σ wᵢ for the given target rows; NaN where no source is finite.

        `flat` carries one extra 0.0 at its end, so an empty slot (id -1) reads
        a zero with zero weight and the common case is one gather and one dot
        in float32. Only rows that touch a non-finite source take the slow path,
        which renormalises over their finite sources: a NaN data value shows as
        NaN itself but does not poison the cells filled from its neighbours.
        """
        w = self.weights[rows]
        out = np.einsum("ij,ij->i", w, flat[self.sources[rows]])
        bad = np.flatnonzero(~np.isfinite(out))
        if bad.size:
            src = self.sources[rows][bad]
            v = flat[src].astype(np.float64)
            ok = (src >= 0) & np.isfinite(v)
            wb = np.where(ok, w[bad], 0.0).astype(np.float64)
            den = wb.sum(axis=1)
            num = (wb * np.where(ok, v, 0.0)).sum(axis=1)
            good = ok.any(axis=1) & (den != 0.0)
            res = np.full(bad.size, np.nan)
            res[good] = num[good] / den[good]
            out[bad] = res
        return out.astype(np.float32, copy=False)

    def _flat(self, values: np.ndarray) -> np.ndarray:
        values = np.asarray(values)
        if values.shape != self.shape:
            raise ValueError(f"values shape {values.shape} != weights shape {self.shape}")
        flat = np.zeros(values.size + 1, dtype=np.float32)
        flat[:-1] = values.ravel()
        return flat

    def apply(self, values: np.ndarray) -> np.ndarray:
        """The filled slice: data cells as they are, targets interpolated, the rest NaN."""
        flat = self._flat(values)
        out = np.full(flat.size - 1, np.nan, dtype=np.float32)
        out[self.populated] = flat[:-1][self.populated]
        if self.targets.size:
            out[self.targets] = self._blend(slice(None), flat)
        return out.reshape(self.shape)

    def apply_at(self, values: np.ndarray, cells: np.ndarray) -> np.ndarray:
        """`apply(values).ravel()[cells]` without building the whole slice."""
        flat = self._flat(values)
        cells = np.asarray(cells, dtype=np.intp)
        out = np.full(cells.size, np.nan, dtype=np.float32)
        data = self.populated[cells]
        out[data] = flat[cells[data]]
        if self.targets.size:
            pos = np.minimum(np.searchsorted(self.targets, cells), self.targets.size - 1)
            hit = self.targets[pos] == cells
            out[hit] = self._blend(pos[hit], flat)
        return out

    @property
    def nbytes(self) -> int:
        return (
            self.populated.nbytes + self.targets.nbytes + self.sources.nbytes + self.weights.nbytes
        )


def _disc_offsets(radius_m: float, cell: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(dy, dx, distance in metres) of every offset with 0 < distance <= radius, nearest first."""
    r = int(math.ceil(radius_m / cell)) + 1
    dy, dx = np.mgrid[-r : r + 1, -r : r + 1]
    dy, dx = dy.ravel(), dx.ravel()
    dist = np.hypot(dy, dx) * cell
    keep = (dist > 0) & (dist <= radius_m + DISTANCE_TOL_M)
    dy, dx, dist = dy[keep], dx[keep], dist[keep]
    order = np.argsort(dist, kind="stable")
    return dy[order], dx[order], dist[order]


def _reach(pop2: np.ndarray, dy: np.ndarray, dx: np.ndarray) -> np.ndarray:
    """Cells with a data cell within the offsets (data cells included)."""
    ny, nx = pop2.shape
    reach = pop2.copy()
    for oy, ox in zip(dy.tolist(), dx.tolist(), strict=True):
        # reach[y, x] |= pop[y + oy, x + ox], reading False outside the frame
        ys, ye = max(0, -oy), min(ny, ny - oy)
        xs, xe = max(0, -ox), min(nx, nx - ox)
        if ys < ye and xs < xe:
            reach[ys:ye, xs:xe] |= pop2[ys + oy : ye + oy, xs + ox : xe + ox]
    return reach


def _neighbourhoods(
    pop2: np.ndarray, targets: np.ndarray, dy: np.ndarray, dx: np.ndarray
) -> np.ndarray:
    """Per target, the K nearest data cells in each quadrant as flat ids (-1 = empty)."""
    ny, nx = pop2.shape
    k = NEIGHBOURS_PER_QUADRANT
    # int32 throughout, as `sources` already is: half the working set of intp.
    ty, tx = np.divmod(targets.astype(np.int32), nx)
    angle = np.mod(np.arctan2(dy, dx), 2 * math.pi)
    quad = np.minimum((angle / (math.pi / 2)).astype(np.intp), 3)
    sources = np.full((targets.size, _SLOTS), -1, dtype=np.int32)
    count = np.zeros((targets.size, 4), dtype=np.int8)
    active = np.arange(targets.size, dtype=np.int32)
    for i, (oy, ox, q) in enumerate(zip(dy.tolist(), dx.tolist(), quad.tolist(), strict=True)):
        if i % _PRUNE_EVERY == 0 and i:
            active = active[(count[active] < k).any(axis=1)]
            if not active.size:
                break
        sy, sx = ty[active] + oy, tx[active] + ox
        inside = (sy >= 0) & (sy < ny) & (sx >= 0) & (sx < nx)
        sel = active[inside]
        sy, sx = sy[inside], sx[inside]
        ok = pop2[sy, sx] & (count[sel, q] < k)
        sel, sy, sx = sel[ok], sy[ok], sx[ok]
        sources[sel, q * k + count[sel, q]] = sy * nx + sx
        count[sel, q] += 1
    return sources


def _offsets(sources: np.ndarray, targets: np.ndarray, nx: int) -> tuple[np.ndarray, np.ndarray]:
    """Each source's (dy, dx) from its target in cells, int32 with (0, 0) in an
    empty slot, and which slots hold a source."""
    valid = sources >= 0
    ty, tx = np.divmod(targets.astype(np.int32), nx)
    safe = np.where(valid, sources, 0)
    rel = np.stack([safe // nx - ty[:, None], safe % nx - tx[:, None]], axis=-1).astype(np.int32)
    rel[~valid] = 0
    return rel, valid


def _idw_weights(rel: np.ndarray, valid: np.ndarray, cell: float) -> np.ndarray:
    d = np.hypot(rel[..., 0], rel[..., 1]) * cell
    w = np.where(valid, np.where(valid, d, 1.0) ** -float(IDW_POWER), 0.0)
    return w / w.sum(axis=1, keepdims=True)


def _kriging_weights(rel: np.ndarray, valid: np.ndarray, cell: float) -> np.ndarray:
    """Ordinary kriging, linear variogram, no nugget, isotropic (interpolation spec §5.1).

    Weights depend only on the sources' offsets from the target, and regular
    line geometry repeats a few dozen offset patterns across thousands of
    targets, so each distinct pattern is solved once.
    """
    m = rel.shape[0]
    key = np.where(valid[..., None], rel, _EMPTY).astype(np.int32).reshape(m, -1)
    key = np.ascontiguousarray(key)
    void = key.view(np.dtype((np.void, key.dtype.itemsize * key.shape[1]))).ravel()
    _, first, inverse = np.unique(void, return_index=True, return_inverse=True)
    rel_u, valid_u = rel[first], valid[first]
    out = np.zeros((first.size, _SLOTS))
    for lo in range(0, first.size, _SOLVE_CHUNK):
        p = rel_u[lo : lo + _SOLVE_CHUNK] * cell  # (c, 12, 2) metres from the target
        ok = valid_u[lo : lo + _SOLVE_CHUNK]
        c = p.shape[0]
        diff = p[:, :, None, :] - p[:, None, :, :]
        both = ok[:, :, None] & ok[:, None, :]
        a = np.zeros((c, _SLOTS + 1, _SLOTS + 1))
        a[:, :_SLOTS, :_SLOTS] = np.where(both, np.hypot(diff[..., 0], diff[..., 1]), 0.0)
        idx = np.arange(_SLOTS)
        a[:, idx, idx] = np.where(ok, 0.0, 1.0)  # an empty slot solves to w = 0
        a[:, :_SLOTS, _SLOTS] = a[:, _SLOTS, :_SLOTS] = ok
        rhs = np.zeros((c, _SLOTS + 1, 1))
        rhs[:, :_SLOTS, 0] = np.where(ok, np.hypot(p[..., 0], p[..., 1]), 0.0)
        rhs[:, _SLOTS, 0] = 1.0
        out[lo : lo + c] = np.linalg.solve(a, rhs)[:, :_SLOTS, 0]
    return out[inverse.ravel()]


def plan_fill(
    populated: np.ndarray, cell: float, method: str, max_distance_m: float, search_radius_m: float
) -> FillWeights:
    """Plan which empty cells get filled and from which neighbours with which weights.

    `populated` is the (ny, nx) mask of cells holding data. An empty cell is a
    target when a data cell lies within `max_distance_m`; its sources are drawn
    from within `search_radius_m`.
    """
    pop2 = np.asarray(populated)
    if pop2.ndim != 2:
        raise ValueError(f"populated must be 2-D, got {pop2.ndim}-D")
    if method not in METHODS:
        raise ValueError(f"unknown interpolation method {method!r}; expected one of {METHODS}")
    if not cell > 0:
        raise ValueError(f"cell must be > 0, got {cell}")
    if max_distance_m < 0:
        raise ValueError(f"max_distance_m must be >= 0, got {max_distance_m}")
    if search_radius_m < max_distance_m:
        raise ValueError("search_radius_m must be >= max_distance_m")
    pop2 = pop2.astype(bool)
    shape = (int(pop2.shape[0]), int(pop2.shape[1]))
    nx = shape[1]
    flat_pop = pop2.ravel().copy()
    empty = FillWeights(
        shape,
        flat_pop,
        np.empty(0, dtype=np.intp),
        np.empty((0, _SLOTS), dtype=np.int32),
        np.empty((0, _SLOTS), dtype=np.float32),
    )
    if method == "none":
        return empty
    ry, rx, _ = _disc_offsets(max_distance_m, cell)
    targets = np.flatnonzero((_reach(pop2, ry, rx) & ~pop2).ravel())
    if not targets.size:
        return empty
    sy, sx, _ = _disc_offsets(search_radius_m, cell)
    sources = _neighbourhoods(pop2, targets, sy, sx)
    build = _idw_weights if method == "idw" else _kriging_weights
    weights = np.empty(sources.shape, dtype=np.float32)
    for lo in range(0, targets.size, _PLAN_CHUNK):
        rows = slice(lo, lo + _PLAN_CHUNK)
        rel, valid = _offsets(sources[rows], targets[rows], nx)
        weights[rows] = build(rel, valid, cell)
    return FillWeights(shape, flat_pop, targets, sources, weights)
