"""Production-shaped prototype of the #111 hierarchy (throwaway): float32 strided
probing, Gershgorin bound, per-call scratch. Checks the plan's algorithm."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

COARSEST_UNKNOWNS = 500
SMOOTHING_DEGREE = 2
SMOOTHING_RATIO = 16.0
PSEUDO_INVERSE_CUTOFF = 1e-6
_REACH = 2
_PERIOD = 2 * _REACH + 1
_COARSE_OFFSETS = tuple((dy, dx) for dy in range(-2, 3) for dx in range(-2, 3))


def apply_stencil(offsets, coefficients, x):
    ny, nx = x.shape
    pad = np.zeros((ny + 2 * _REACH, nx + 2 * _REACH), np.float32)
    pad[_REACH:-_REACH, _REACH:-_REACH] = x
    out = np.zeros((ny, nx), np.float32)
    work = np.empty((ny, nx), np.float32)
    for k, (dy, dx) in enumerate(offsets):
        np.multiply(coefficients[k], pad[_REACH + dy : _REACH + dy + ny, _REACH + dx : _REACH + dx + nx], out=work)
        out += work
    return out


def _prolong_1d(c, n_fine, axis):
    c = np.moveaxis(c, axis, 0)
    before = np.concatenate([c[:1], c[:-1]])
    after = np.concatenate([c[1:], c[-1:]])
    out = np.empty((2 * c.shape[0],) + c.shape[1:], c.dtype)
    out[0::2] = 0.75 * c + 0.25 * before
    out[1::2] = 0.75 * c + 0.25 * after
    return np.moveaxis(out[:n_fine], 0, axis)


def _restrict_1d(f, n_coarse, axis):
    f = np.moveaxis(f, axis, 0)
    g = np.zeros((2 * n_coarse,) + f.shape[1:], f.dtype)
    g[: f.shape[0]] = f
    even, odd = g[0::2], g[1::2]
    out = 0.75 * (even + odd)
    out[:-1] += 0.25 * even[1:]
    out[0] += 0.25 * even[0]
    out[1:] += 0.25 * odd[:-1]
    out[-1] += 0.25 * odd[-1]
    return np.moveaxis(out, 0, axis)


def prolong(c, fine_shape):
    return _prolong_1d(_prolong_1d(c, fine_shape[0], 0), fine_shape[1], 1)


def restrict(f, coarse_shape):
    return _restrict_1d(_restrict_1d(f, coarse_shape[0], 0), coarse_shape[1], 1)


@dataclass(frozen=True, eq=False)
class Level:
    offsets: tuple
    coefficients: np.ndarray
    active: np.ndarray
    inverse_diagonal: np.ndarray
    upper: float


def _level(offsets, coefficients, active):
    """l1-Jacobi: the scaling is 1 / the row's absolute sum, so D_l1^-1 A has every eigenvalue in (0, 1]."""
    absrow = np.abs(coefficients).sum(axis=0, dtype=np.float32)
    inv = np.zeros(active.shape, np.float32)
    np.divide(1.0, absrow, out=inv, where=active)
    return Level(tuple(offsets), coefficients, active, inv, 1.0)


def _galerkin(level, fine_shape):
    ny, nx = fine_shape
    cy, cx = (ny + 1) // 2, (nx + 1) // 2
    act = level.active.astype(np.float32)
    coef = np.zeros((len(_COARSE_OFFSETS), cy, cx), np.float32)
    for py in range(_PERIOD):
        for px in range(_PERIOD):
            e = np.zeros((cy, cx), np.float32)
            e[py::_PERIOD, px::_PERIOD] = 1.0
            y = restrict(apply_stencil(level.offsets, level.coefficients, prolong(e, fine_shape) * act) * act, (cy, cx))
            for k, (oy, ox) in enumerate(_COARSE_OFFSETS):
                sy, sx = (py - oy) % _PERIOD, (px - ox) % _PERIOD
                coef[k, sy::_PERIOD, sx::_PERIOD] = y[sy::_PERIOD, sx::_PERIOD]
    # symmetrise: row i offset o pairs with row i+o offset -o
    index = {o: k for k, o in enumerate(_COARSE_OFFSETS)}
    sym = np.empty_like(coef)
    for k, (oy, ox) in enumerate(_COARSE_OFFSETS):
        mirror = np.zeros((cy, cx), np.float32)
        ys = slice(max(0, -oy), min(cy, cy - oy))
        xs = slice(max(0, -ox), min(cx, cx - ox))
        ys2 = slice(ys.start + oy, ys.stop + oy)
        xs2 = slice(xs.start + ox, xs.stop + ox)
        mirror[ys, xs] = coef[index[(-oy, -ox)], ys2, xs2]
        sym[k] = 0.5 * (coef[k] + mirror)
    active = sym[index[(0, 0)]] > 0
    sym *= active
    return _level(_COARSE_OFFSETS, sym, active)


@dataclass(frozen=True, eq=False)
class Hierarchy:
    levels: tuple
    coarse_cells: np.ndarray
    coarse_inverse: np.ndarray

    def precondition(self, r):
        return self._cycle(0, r)

    def _cycle(self, k, b):
        level = self.levels[k]
        if k == len(self.levels) - 1:
            out = np.zeros(b.shape, np.float32)
            out.ravel()[self.coarse_cells] = self.coarse_inverse @ b.ravel()[self.coarse_cells]
            return out
        x = _chebyshev(level, b, None)
        r = b - apply_stencil(level.offsets, level.coefficients, x * level.active)
        coarse_shape = self.levels[k + 1].active.shape
        e = self._cycle(k + 1, restrict(r * level.active, coarse_shape))
        x += prolong(e, b.shape) * level.active
        return _chebyshev(level, b, x)


def _chebyshev(level, b, x):
    hi = level.upper
    lo = hi / SMOOTHING_RATIO
    theta, delta = 0.5 * (hi + lo), 0.5 * (hi - lo)
    sigma = theta / delta
    rho = 1.0 / sigma
    if x is None:
        x = np.zeros(b.shape, np.float32)
        r = b * level.inverse_diagonal
    else:
        r = (b - apply_stencil(level.offsets, level.coefficients, x * level.active)) * level.inverse_diagonal
    d = r / np.float32(theta)
    for _ in range(SMOOTHING_DEGREE):
        x += d
        r -= apply_stencil(level.offsets, level.coefficients, d * level.active) * level.inverse_diagonal
        rho_next = 1.0 / (2.0 * sigma - rho)
        d = np.float32(rho_next * rho) * d + np.float32(2.0 * rho_next / delta) * r
        rho = rho_next
    return x


def _dense(level):
    ny, nx = level.active.shape
    cells = np.flatnonzero(level.active.ravel())
    n = cells.size
    position = np.full(ny * nx, -1)
    position[cells] = np.arange(n)
    rows, cols = np.divmod(cells, nx)
    m = np.zeros((n, n))
    for k, (oy, ox) in enumerate(level.offsets):
        rr, cc = rows + oy, cols + ox
        inside = (rr >= 0) & (rr < ny) & (cc >= 0) & (cc < nx)
        j = np.where(inside, position[np.where(inside, rr * nx + cc, 0)], -1)
        ok = j >= 0
        m[np.arange(n)[ok], j[ok]] = level.coefficients[k].ravel()[cells][ok]
    m = 0.5 * (m + m.T)
    w, v = np.linalg.eigh(m)
    keep = w > PSEUDO_INVERSE_CUTOFF * (w.max() if n else 1.0)
    inv = np.where(keep, 1.0 / np.where(keep, w, 1.0), 0.0)
    return cells, ((v * inv) @ v.T).astype(np.float32)


def build_hierarchy(offsets, coefficients, active, coarsest=None):
    coarsest = COARSEST_UNKNOWNS if coarsest is None else coarsest
    levels = [_level(tuple(offsets), coefficients, active)]
    while int(levels[-1].active.sum()) > coarsest:
        levels.append(_galerkin(levels[-1], levels[-1].active.shape))
    cells, inverse = _dense(levels[-1])
    return Hierarchy(tuple(levels), cells, inverse)
