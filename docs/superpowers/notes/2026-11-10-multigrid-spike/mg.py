"""Throwaway multigrid-preconditioned CG for nsgeo's minimum curvature (#111 spike).

Galerkin coarse operators (A_c = P'^T A P', P' = bilinear or cubic cell-centred
prolongation masked to the finer level's active cells), found by probing.
Chebyshev or damped-Jacobi smoothing, dense pseudo-inverse at the coarsest level.
"""

import math
import time

import numpy as np

from nsgeo.slices.curvature import (
    _CENTRE,
    _OFFSETS,
    CURVATURE_TOL,
    _start,
)


def _dot(a, b):
    return float(np.einsum("ij,ij->", a, b, dtype=np.float64))


# ---------------------------------------------------------------- stencils


class Stencil:
    """A spatially varying stencil operator: out[i] = sum_k coef[k, i] * x[i + off_k]."""

    def __init__(self, offsets, coef, dtype=np.float32):
        self.offsets = list(offsets)
        self.coef = coef.astype(dtype)
        self.shape = coef.shape[1:]
        self.reach = max(max(abs(dy), abs(dx)) for dy, dx in self.offsets)
        centre = self.offsets.index((0, 0))
        self.diag = self.coef[centre]
        self.active = self.diag > 0
        self.inv_diag = np.zeros(self.shape, dtype)
        np.divide(1.0, self.diag, out=self.inv_diag, where=self.active)
        r = self.reach
        self._pad = np.zeros((self.shape[0] + 2 * r, self.shape[1] + 2 * r), dtype)
        self._work = np.empty(self.shape, dtype)

    def apply(self, x, out=None):
        ny, nx = self.shape
        r = self.reach
        pad = self._pad
        inner = pad[r : r + ny, r : r + nx]
        np.multiply(x, self.active, out=inner)
        if out is None:
            out = np.empty(self.shape, self.coef.dtype)
        work = self._work
        for k, (dy, dx) in enumerate(self.offsets):
            shifted = pad[r + dy : r + dy + ny, r + dx : r + dx + nx]
            if k == 0:
                np.multiply(self.coef[k], shifted, out=out)
            else:
                np.multiply(self.coef[k], shifted, out=work)
                out += work
        return out


# ---------------------------------------------------------------- transfers


def _p1d(nf, kind):
    """Dense 1-D cell-centred prolongation, (nf, nc)."""
    nc = (nf + 1) // 2
    P = np.zeros((nf, nc))
    for i in range(nf):
        # fine centre in coarse-index units: (i + 0.5) / 2 - 0.5
        xf = (i + 0.5) / 2 - 0.5
        if kind == "linear":
            nodes = [math.floor(xf), math.floor(xf) + 1]
        elif kind == "cubic":
            f = math.floor(xf)
            nodes = [f - 1, f, f + 1, f + 2]
        elif kind == "constant":
            P[i, min(i // 2, nc - 1)] = 1.0
            continue
        else:
            raise ValueError(kind)
        # Lagrange weights at xf through `nodes`
        for a in nodes:
            w = 1.0
            for b in nodes:
                if b != a:
                    w *= (xf - b) / (a - b)
            j = min(max(a, 0), nc - 1)  # clamp at the edges
            P[i, j] += w
    return P


class Transfer:
    def __init__(self, fine_shape, fine_active, kind, dtype=np.float32):
        ny, nx = fine_shape
        self.Py = _p1d(ny, kind).astype(dtype)
        self.Px = _p1d(nx, kind).astype(dtype)
        self.fine_active = fine_active.astype(dtype)
        self.kind = kind
        self.coarse_shape = (self.Py.shape[1], self.Px.shape[1])

    def prolong(self, c):
        if self.kind == "linear":
            return _lin_prolong(c, self.fine_active.shape) * self.fine_active
        return (self.Py @ c @ self.Px.T) * self.fine_active

    def restrict(self, f):
        if self.kind == "linear":
            return _lin_restrict(f * self.fine_active, self.coarse_shape)
        return self.Py.T @ (f * self.fine_active) @ self.Px


def _lin_prolong_1d(c, nf, axis):
    """Cell-centred linear, clamped edges: fine 2I <- .75 c[I] + .25 c[I-1], 2I+1 <- .75 c[I] + .25 c[I+1]."""
    c = np.moveaxis(c, axis, 0)
    nc = c.shape[0]
    up = np.concatenate([c[:1], c[:-1]])  # c[I-1], clamped
    dn = np.concatenate([c[1:], c[-1:]])  # c[I+1], clamped
    out = np.empty((2 * nc,) + c.shape[1:], c.dtype)
    out[0::2] = 0.75 * c + 0.25 * up
    out[1::2] = 0.75 * c + 0.25 * dn
    return np.moveaxis(out[:nf], 0, axis)


def _lin_restrict_1d(f, nc, axis):
    """Transpose of _lin_prolong_1d."""
    f = np.moveaxis(f, axis, 0)
    nf = f.shape[0]
    g = np.zeros((2 * nc,) + f.shape[1:], f.dtype)
    g[:nf] = f
    ev, od = g[0::2], g[1::2]
    out = 0.75 * (ev + od)
    out[1:] += 0.25 * ev[1:]  # fine 2I (I>=1) gives .25 to I-1  -> wait: handled below
    out = 0.75 * (ev + od)
    out[:-1] += 0.25 * ev[1:]  # fine 2(I+1) contributes .25 to coarse I
    out[0] += 0.25 * ev[0]  # clamped: fine 0 -> c[-1] = c[0]
    out[1:] += 0.25 * od[:-1]  # fine 2(I-1)+1 contributes .25 to coarse I
    out[-1] += 0.25 * od[-1]  # clamped: fine 2(nc-1)+1 -> c[nc] = c[nc-1]
    return np.moveaxis(out, 0, axis)


def _lin_prolong(c, fine_shape):
    return _lin_prolong_1d(_lin_prolong_1d(c, fine_shape[0], 0), fine_shape[1], 1)


def _lin_restrict(f, coarse_shape):
    return _lin_restrict_1d(_lin_restrict_1d(f, coarse_shape[0], 0), coarse_shape[1], 1)


def galerkin(A, T, reach=3):
    """A_c = R A P by probing with period 2*reach+1."""
    period = 2 * reach + 1
    nyc, nxc = T.coarse_shape
    offsets = [(dy, dx) for dy in range(-reach, reach + 1) for dx in range(-reach, reach + 1)]
    coef = np.zeros((len(offsets), nyc, nxc))
    I = np.arange(nyc)[:, None]
    J = np.arange(nxc)[None, :]
    # promote to float64 for the probes
    Py = T.Py.astype(np.float64)
    Px = T.Px.astype(np.float64)
    act = T.fine_active
    Acoef = A.coef.astype(np.float64)
    A64 = Stencil(A.offsets, Acoef, np.float64)
    for cy in range(period):
        for cx in range(period):
            e = (((I - cy) % period == 0) & ((J - cx) % period == 0)).astype(np.float64)
            if T.kind == 'linear':
                y = T.restrict(A64.apply(T.prolong(e)))
            else:
                y = Py.T @ (A64.apply((Py @ e @ Px.T) * act) * act) @ Px
            # row (i, j) picks the source at (i+dy, j+dx) with colour (cy, cx)
            dy = ((cy - I) + reach) % period - reach
            dx = ((cx - J) + reach) % period - reach
            for k, (oy, ox) in enumerate(offsets):
                m = (dy == oy) & (dx == ox)
                coef[k][m] = y[m]
    # drop all-zero offsets
    keep = [k for k in range(len(offsets)) if np.abs(coef[k]).max() > 1e-12 * np.abs(coef).max()]
    offsets = [offsets[k] for k in keep]
    coef = coef[keep]
    # symmetrise: c[k](i) and c[-k](i+off)
    sym = coef.copy()
    idx = {o: k for k, o in enumerate(offsets)}
    ny, nx = nyc, nxc
    for k, (oy, ox) in enumerate(offsets):
        kk = idx[(-oy, -ox)]
        # value at row i for offset o should equal value at row i+o for offset -o
        shifted = np.zeros((ny, nx))
        ys0, ys1 = max(0, -oy), min(ny, ny - oy)
        xs0, xs1 = max(0, -ox), min(nx, nx - ox)
        shifted[ys0:ys1, xs0:xs1] = coef[kk, ys0 + oy : ys1 + oy, xs0 + ox : xs1 + ox]
        sym[k] = 0.5 * (coef[k] + shifted)
    # rows/cols of inactive coarse cells are 0 already (zero columns of P')
    return Stencil(offsets, sym, A.coef.dtype)


# ---------------------------------------------------------------- smoothing


def lam_max(A, its=20, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(A.shape).astype(A.coef.dtype) * A.active
    lam = 0.0
    for _ in range(its):
        y = A.apply(x) * A.inv_diag
        n = math.sqrt(_dot(y, y))
        if n == 0:
            return 1.0
        lam = n / math.sqrt(_dot(x, x))
        x = y / n
    return lam


def chebyshev(A, b, x, lmax, ratio, degree):
    lo, hi = lmax / ratio, 1.1 * lmax
    theta = 0.5 * (hi + lo)
    delta = 0.5 * (hi - lo)
    sigma = theta / delta
    rho = 1.0 / sigma
    if x is None:
        x = np.zeros(A.shape, A.coef.dtype)
        r = b * A.inv_diag
    else:
        r = (b - A.apply(x)) * A.inv_diag
    d = r / theta
    for _ in range(degree):
        x += d
        r -= A.apply(d) * A.inv_diag
        rho1 = 1.0 / (2.0 * sigma - rho)
        d = (rho1 * rho) * d + (2.0 * rho1 / delta) * r
        rho = rho1
    return x


class Hierarchy:
    def __init__(self, A0, kind="linear", coarsest=1500, degree=2, ratio=8.0, max_levels=8):
        t = time.perf_counter()
        self.levels = [A0]
        self.transfers = []
        self.degree = degree
        self.ratio = ratio
        A = A0
        while A.active.sum() > coarsest and min(A.shape) > 6 and len(self.levels) < max_levels:
            T = Transfer(A.shape, A.active, kind, A.coef.dtype)
            Ac = galerkin(A, T, reach=3 if kind == "cubic" else 2)
            self.transfers.append(T)
            self.levels.append(Ac)
            A = Ac
        self.lmax = [lam_max(L, its=10) for L in self.levels[:-1]]
        # dense coarsest
        Ac = self.levels[-1]
        act = np.flatnonzero(Ac.active.ravel())
        n = act.size
        M = np.zeros((n, n))
        pos = -np.ones(Ac.shape[0] * Ac.shape[1], int)
        pos[act] = np.arange(n)
        ny, nx = Ac.shape
        rows, cols = np.divmod(act, nx)
        for k, (oy, ox) in enumerate(Ac.offsets):
            rr, cc = rows + oy, cols + ox
            ok = (rr >= 0) & (rr < ny) & (cc >= 0) & (cc < nx)
            src = np.where(ok, rr * nx + cc, 0)
            j = np.where(ok, pos[src], -1)
            good = j >= 0
            M[np.arange(n)[good], j[good]] += Ac.coef[k].ravel()[act][good]
        M = 0.5 * (M + M.T)
        w, V = np.linalg.eigh(M)
        inv = np.where(w > 1e-10 * w.max(), 1.0 / w, 0.0)
        self.coarse_inv = ((V * inv) @ V.T).astype(A0.coef.dtype)
        self.coarse_act = act
        self.setup_s = time.perf_counter() - t

    def describe(self):
        return " -> ".join(f"{L.shape[1]}x{L.shape[0]}({int(L.active.sum())},{len(L.offsets)}pt)" for L in self.levels)

    def vcycle(self, b, level=0):
        A = self.levels[level]
        if level == len(self.levels) - 1:
            out = np.zeros(A.shape, A.coef.dtype)
            out.ravel()[self.coarse_act] = self.coarse_inv @ b.ravel()[self.coarse_act]
            return out
        x = chebyshev(A, b, None, self.lmax[level], self.ratio, self.degree)
        r = b - A.apply(x)
        T = self.transfers[level]
        ec = self.vcycle(T.restrict(r), level + 1)
        x += T.prolong(ec)
        x = chebyshev(A, b, x, self.lmax[level], self.ratio, self.degree)
        return x


def fine_stencil(plan, dtype=np.float32):
    return Stencil(_OFFSETS, np.asarray(plan.coefficients), dtype)


def solve_mg(plan, H, values, tol=CURVATURE_TOL, maxit=500, dtype=np.float32):
    """Same problem as CurvaturePlan.solve, PCG with H's V-cycle. Returns (out, its)."""
    shape = plan.shape
    pop = plan.populated.reshape(shape)
    unknown = plan.domain & ~pop
    A = H.levels[0]
    data = np.asarray(values, dtype).copy()
    mean = dtype(np.mean(data[pop], dtype=np.float64))
    data -= mean
    d = np.where(pop, data, 0).astype(dtype)
    # b = -A d, with A's columns at data cells: use the raw coefficient apply
    # (Stencil.apply masks the input to active cells, so do it by hand)
    b = -_apply_unmasked(plan, d, dtype)
    b_norm = math.sqrt(_dot(b, b))
    x = np.zeros(shape, dtype)
    np.copyto(x, _start(data.astype(np.float32), pop), where=unknown)
    if b_norm == 0:
        x[...] = 0
        its = 0
    else:
        r = b - A.apply(x)
        z = H.vcycle(r)
        p = z.copy()
        rz = _dot(r, z)
        its = 0
        while its < maxit and math.sqrt(_dot(r, r)) > tol * b_norm:
            q = A.apply(p)
            pq = _dot(p, q)
            if not pq > 0:
                break
            alpha = rz / pq
            x += alpha * p
            r -= alpha * q
            z = H.vcycle(r)
            rz1 = _dot(r, z)
            p = z + (rz1 / rz) * p
            rz = rz1
            its += 1
    out = x + mean
    out[~plan.reach.reshape(shape)] = np.nan
    out[pop] = np.asarray(values)[pop]
    return out, its


def _apply_unmasked(plan, d, dtype=np.float32):
    ny, nx = plan.shape
    pad = np.zeros((ny + 4, nx + 4), dtype)
    pad[2:-2, 2:-2] = d
    out = np.zeros(plan.shape, dtype)
    for k, (dy, dx) in enumerate(_OFFSETS):
        out += plan.coefficients[k].astype(dtype) * pad[2 + dy : 2 + dy + ny, 2 + dx : 2 + dx + nx]
    return out


assert _CENTRE == _OFFSETS.index((0, 0))
