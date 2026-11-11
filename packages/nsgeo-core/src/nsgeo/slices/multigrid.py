"""A multigrid V-cycle to precondition minimum curvature's conjugate gradients.

Jacobi leaves the biharmonic's smooth error to be ground out a cell at a
time, which is why the 0.05 m solve took 459 iterations (`curvature.py`). A
multigrid cycle takes that smooth error to a grid a quarter the size, where
it is rough again, and so ends it in a few. The method and the spike's
decisions are in `docs/superpowers/notes/2026-11-10-multigrid-spike.md`.

The pieces, all numpy and all float32 but the coarsest solve:

* Transfers are cell-centred linear interpolation, clamped at the edges
  (`prolong`), and its exact transpose (`restrict`), so that the coarse
  operator is symmetric whenever the fine one is.
* Each coarser operator is the Galerkin product P'ᵀ A P', where P' is
  `prolong` masked to the finer level's unknowns. It is found by probing the
  fine operator with the transfers rather than by writing the product out:
  P' spans fine cells 2I-1 … 2I+2 and A reaches ±2, so a coarse row reaches
  ±2 coarse cells (`COARSE_OFFSETS`), and probes on a lattice 5 apart never
  alias. A coarse cell is an unknown when its diagonal is positive, which is
  exactly when it reaches a fine unknown.
* The smoother is a Chebyshev polynomial of l1-Jacobi: with each row scaled
  by 1 / its absolute sum, every eigenvalue of the scaled operator is at most
  1, so the bound needs no estimate, and the polynomial damps the top
  `SMOOTHING_RATIO` of the spectrum.
* The coarsest level, once it has no more than `COARSEST_UNKNOWNS` unknowns,
  is solved densely by a pseudo-inverse.

Read-only throughout, as a `CurvaturePlan` is: a hierarchy is built once per
plan and shared between the refine worker and the GUI thread, so
`Hierarchy.precondition` writes nothing it was given and allocates its own
scratch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

COARSEST_UNKNOWNS: int = 500  # coarsening stops at this many unknowns, read at call time
SMOOTHING_DEGREE: int = 2  # Chebyshev steps a smooth
SMOOTHING_RATIO: float = 16.0  # the smoother damps the top 1 - 1/ratio of the spectrum
PSEUDO_INVERSE_CUTOFF: float = 1e-6  # eigenvalues below this × the largest are dropped

_REACH = 2  # a stencil's reach, in cells
_PERIOD = 2 * _REACH + 1  # probe lattice spacing at which coarse rows never alias
COARSE_OFFSETS: tuple[tuple[int, int], ...] = tuple(
    (dy, dx) for dy in range(-_REACH, _REACH + 1) for dx in range(-_REACH, _REACH + 1)
)
_COARSE_INDEX = {offset: k for k, offset in enumerate(COARSE_OFFSETS)}
_COARSE_CENTRE = _COARSE_INDEX[(0, 0)]


def coarse_shape(fine_shape: tuple[int, int]) -> tuple[int, int]:
    """The shape one level up: every second cell, the odd edge kept."""
    return ((fine_shape[0] + 1) // 2, (fine_shape[1] + 1) // 2)


def apply_stencil(
    offsets: Sequence[tuple[int, int]], coefficients: np.ndarray, x: np.ndarray
) -> np.ndarray:
    """out[i, j] = Σ_k coefficients[k, i, j] · x[i + dy_k, j + dx_k], with x
    taken as 0 outside the array. float32 (ny, nx). It does not mask x."""
    ny, nx = x.shape
    pad = np.zeros((ny + 2 * _REACH, nx + 2 * _REACH), np.float32)
    pad[_REACH:-_REACH, _REACH:-_REACH] = x
    out = np.zeros((ny, nx), np.float32)
    work = np.empty((ny, nx), np.float32)
    for k, (dy, dx) in enumerate(offsets):
        y0, x0 = _REACH + dy, _REACH + dx
        np.multiply(coefficients[k], pad[y0 : y0 + ny, x0 : x0 + nx], out=work)
        out += work
    return out


def _prolong_axis(c: np.ndarray, n_fine: int, axis: int) -> np.ndarray:
    # fine[2I] = ¾c[I] + ¼c[I-1], fine[2I+1] = ¾c[I] + ¼c[I+1], clamped at the
    # ends; the last row goes when the fine length is odd.
    c = np.moveaxis(c, axis, 0)
    before = np.concatenate([c[:1], c[:-1]])
    after = np.concatenate([c[1:], c[-1:]])
    out = np.empty((2 * c.shape[0],) + c.shape[1:], c.dtype)
    out[0::2] = 0.75 * c + 0.25 * before
    out[1::2] = 0.75 * c + 0.25 * after
    return np.moveaxis(out[:n_fine], 0, axis)


def _restrict_axis(f: np.ndarray, n_coarse: int, axis: int) -> np.ndarray:
    f = np.moveaxis(f, axis, 0)
    padded = np.zeros((2 * n_coarse,) + f.shape[1:], f.dtype)
    padded[: f.shape[0]] = f
    even, odd = padded[0::2], padded[1::2]
    out = 0.75 * (even + odd)
    out[:-1] += 0.25 * even[1:]
    out[0] += 0.25 * even[0]
    out[1:] += 0.25 * odd[:-1]
    out[-1] += 0.25 * odd[-1]
    return np.moveaxis(out, 0, axis)


def prolong(coarse: np.ndarray, fine_shape: tuple[int, int]) -> np.ndarray:
    """Coarse to fine, linear between cell centres. Unmasked."""
    return _prolong_axis(_prolong_axis(coarse, fine_shape[0], 0), fine_shape[1], 1)


def restrict(fine: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Fine to coarse (`shape` is the coarse shape): the exact transpose of
    `prolong`. Unmasked."""
    return _restrict_axis(_restrict_axis(fine, shape[0], 0), shape[1], 1)


@dataclass(frozen=True, eq=False)
class Level:
    """One grid of the hierarchy: its operator and where it has unknowns."""

    offsets: tuple[tuple[int, int], ...]
    coefficients: np.ndarray  # (len(offsets), ny, nx) float32; rows off `active` are 0
    active: np.ndarray  # (ny, nx) bool: this level's unknowns
    scale: np.ndarray  # (ny, nx) float32: 1 / the row's absolute sum on active, else 0


def _level(
    offsets: Sequence[tuple[int, int]], coefficients: np.ndarray, active: np.ndarray
) -> Level:
    # l1-Jacobi: every eigenvalue of scale · A is at most 1, with no estimate.
    absolute_sum = np.abs(coefficients).sum(axis=0, dtype=np.float32)
    scale = np.zeros(active.shape, np.float32)
    np.divide(1.0, absolute_sum, out=scale, where=active)
    return Level(tuple(offsets), coefficients, active, scale)


def _coarsen(level: Level) -> Level:
    """The Galerkin coarse level of `level`, found by probing it."""
    shape = level.active.shape
    cs = coarse_shape(shape)
    mask = level.active.astype(np.float32)
    coef = np.zeros((len(COARSE_OFFSETS), cs[0], cs[1]), np.float32)
    for py in range(_PERIOD):
        for px in range(_PERIOD):
            probe = np.zeros(cs, np.float32)
            probe[py::_PERIOD, px::_PERIOD] = 1.0
            image = apply_stencil(level.offsets, level.coefficients, prolong(probe, shape) * mask)
            column = restrict(image * mask, cs)
            for k, (oy, ox) in enumerate(COARSE_OFFSETS):
                sy, sx = (py - oy) % _PERIOD, (px - ox) % _PERIOD
                coef[k, sy::_PERIOD, sx::_PERIOD] = column[sy::_PERIOD, sx::_PERIOD]
    # Symmetrise: row i at offset o pairs with row i + o at offset -o.
    sym = np.empty_like(coef)
    for k, (oy, ox) in enumerate(COARSE_OFFSETS):
        mirror = np.zeros(cs, np.float32)
        ys = slice(max(0, -oy), min(cs[0], cs[0] - oy))
        xs = slice(max(0, -ox), min(cs[1], cs[1] - ox))
        mirror[ys, xs] = coef[
            _COARSE_INDEX[(-oy, -ox)],
            ys.start + oy : ys.stop + oy,
            xs.start + ox : xs.stop + ox,
        ]
        sym[k] = 0.5 * (coef[k] + mirror)
    active = sym[_COARSE_CENTRE] > 0
    sym *= active
    return _level(COARSE_OFFSETS, sym, active)


def _chebyshev(level: Level, b: np.ndarray, x: np.ndarray | None) -> np.ndarray:
    """SMOOTHING_DEGREE Chebyshev steps on scale·A over [1/ratio, 1], from x
    (zero if None). Returns a new array; `x` is advanced in place."""
    hi = 1.0
    lo = hi / SMOOTHING_RATIO
    theta, delta = 0.5 * (hi + lo), 0.5 * (hi - lo)
    sigma = theta / delta
    rho = 1.0 / sigma
    if x is None:
        x = np.zeros(b.shape, np.float32)
        r = b * level.scale
    else:
        r = (b - apply_stencil(level.offsets, level.coefficients, x * level.active)) * level.scale
    d = r / np.float32(theta)
    for _ in range(SMOOTHING_DEGREE):
        x += d
        r -= apply_stencil(level.offsets, level.coefficients, d * level.active) * level.scale
        rho_next = 1.0 / (2.0 * sigma - rho)
        d = np.float32(rho_next * rho) * d + np.float32(2.0 * rho_next / delta) * r
        rho = rho_next
    return x


@dataclass(frozen=True, eq=False)
class Hierarchy:
    """The levels, finest first, and the dense solve of the last."""

    levels: tuple[Level, ...]
    coarse_cells: np.ndarray  # intp: flat indices of the last level's unknowns
    coarse_inverse: np.ndarray  # (n, n) float32: their pseudo-inverse

    def __post_init__(self) -> None:
        # Shared between the refine worker and the GUI thread, which
        # precondition on one hierarchy at once: nothing may write to it.
        for level in self.levels:
            for array in (level.coefficients, level.active, level.scale):
                array.flags.writeable = False
        self.coarse_cells.flags.writeable = False
        self.coarse_inverse.flags.writeable = False

    @property
    def nbytes(self) -> int:
        """Every array held but the finest coefficients, which the plan owns."""
        total = self.coarse_cells.nbytes + self.coarse_inverse.nbytes
        for level in self.levels:
            total += level.coefficients.nbytes + level.active.nbytes + level.scale.nbytes
        return total - self.levels[0].coefficients.nbytes

    def precondition(self, r: np.ndarray) -> np.ndarray:
        """One V-cycle from zero: float32 (ny, nx), zero off the finest
        unknowns. `r` is not written; the scratch is this call's own."""
        return self._cycle(0, r)

    def _cycle(self, k: int, b: np.ndarray) -> np.ndarray:
        level = self.levels[k]
        if k == len(self.levels) - 1:
            out = np.zeros(b.shape, np.float32)
            out.flat[self.coarse_cells] = self.coarse_inverse @ b.flat[self.coarse_cells]
            return out
        x = _chebyshev(level, b, None)
        residual = b - apply_stencil(level.offsets, level.coefficients, x * level.active)
        shape = self.levels[k + 1].active.shape
        e = self._cycle(k + 1, restrict(residual * level.active, shape))
        x += prolong(e, b.shape) * level.active
        return _chebyshev(level, b, x)


def _coarsest_inverse(level: Level) -> tuple[np.ndarray, np.ndarray]:
    ny, nx = level.active.shape
    cells = np.flatnonzero(level.active.ravel())
    n = cells.size
    position = np.full(ny * nx, -1)
    position[cells] = np.arange(n)
    rows, cols = np.divmod(cells, nx)
    matrix = np.zeros((n, n))
    for k, (dy, dx) in enumerate(level.offsets):
        rr, cc = rows + dy, cols + dx
        inside = (rr >= 0) & (rr < ny) & (cc >= 0) & (cc < nx)
        j = np.where(inside, position[np.where(inside, rr * nx + cc, 0)], -1)
        ok = j >= 0
        matrix[np.arange(n)[ok], j[ok]] = level.coefficients[k].ravel()[cells][ok]
    matrix = 0.5 * (matrix + matrix.T)
    values, vectors = np.linalg.eigh(matrix)
    keep = values > PSEUDO_INVERSE_CUTOFF * (values.max() if n else 1.0)
    inverse = np.where(keep, 1.0 / np.where(keep, values, 1.0), 0.0)
    return cells.astype(np.intp), ((vectors * inverse) @ vectors.T).astype(np.float32)


def build_hierarchy(
    offsets: Sequence[tuple[int, int]], coefficients: np.ndarray, active: np.ndarray
) -> Hierarchy:
    """Coarsen the operator until `COARSEST_UNKNOWNS` remain, then invert that.

    `coefficients` itself becomes level 0's, with no copy, and goes read-only;
    `active` is copied.
    """
    levels = [_level(offsets, coefficients, active.copy())]
    while int(levels[-1].active.sum()) > COARSEST_UNKNOWNS and levels[-1].active.shape != (1, 1):
        levels.append(_coarsen(levels[-1]))
    cells, inverse = _coarsest_inverse(levels[-1])
    return Hierarchy(tuple(levels), cells, inverse)
