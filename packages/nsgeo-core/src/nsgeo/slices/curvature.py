"""Minimum curvature: the smoothest surface through the data, solved near it.

IDW and kriging blend a few neighbours. Minimum curvature instead finds the
one surface through every data cell that bends least: a Briggs-type
biharmonic solve at tension 0 (interpolation spec §5.1, §5.4). The price is a
solve per slice where the others need one gather.

The energy is the thin plate's, in cell units (plan call 1):

    Σ u_xx² + Σ u_yy² + 2 Σ u_xy²    second differences whose cells all lie in D
    + ε Σ |∇u|²                      first differences, both cells in D

with data cells held fixed. Its interior Euler-Lagrange equation is the
13-point biharmonic, and the edge of D gets its natural (zero-curvature)
conditions from the energy itself. ε = `CURVATURE_EPS` is not tension: it is
six orders below the curvature terms, there only so that collinear data (one
line, one cell), which leave a tilt across them that costs no curvature, have
one answer. A plane still satisfies the interior equation exactly.

D is the solve area, near the data (the user's call of 2026-11-05): every
cell within the max distance of a data cell, which is exactly the cells IDW
and kriging fill, grown by `SOLVE_MARGIN_CELLS`, the stencil's reach. The
spec first said the whole frame. With lines over 40% of a 50 m grid at a
0.2 m cell, that took 59 s a slice to crawl through the empty ground, against
0.65 s near the data, and inside the max distance the two differed by at most
1.2% of the data range. Beyond the max distance the output is blank, as every
method's is.

D and the operator depend only on where data is, never on its values
(interpolation spec §7), so `plan_curvature` builds them once per grid and
distance, with a multigrid hierarchy on the operator (`multigrid.py`, #111;
design and measurements in docs/superpowers/notes/2026-11-10-multigrid-spike.md).
`CurvaturePlan.solve` then runs conjugate gradients per slice (plan call 3):
matrix-free in float32 with float64 dot products, started from linear
interpolation along columns and rows weighted by span (`_start`), and stopped
at `CURVATURE_TOL` of the right-hand side. Each iteration is preconditioned by
one V-cycle: degree-2 Chebyshev smoothing, Galerkin coarse operators on
cell-doubled grids, and a dense solve once a level has few unknowns. Jacobi
took about 3.5x the iterations for each halving of the cell (41, 155, 492 at
0.2, 0.1 and 0.05 m on a 50 m grid); the V-cycle holds them near 6 to 15.
Against a float64 solve to 1e-10 on the ten real lines at 0.05 m, the largest
error inside the max distance was 3.0e-5 to 3.6e-5 of the data range (two
windows), against 4.1e-5 to 6.9e-5 for Jacobi (the spike note). On the 50 m
grids, against a float64 solve, the largest error was 3.5e-6, 1.4e-5 and
1.1e-4 of the data range at 0.2, 0.1 and 0.05 m (99th percentile 1.3e-5 at
0.05 m), within milestone B's 6.2e-6, 4.8e-5 and 4.0e-4.

numpy only, no scipy. Measured medians per slice, at max distance 0.375 m
(0.75 x the 0.5 m line spacing) with `bench.py` from the spike note: on the ten
real lines (25 x 100 cells at 0.2 m, 100 x 400 at 0.05 m), on 50 m x 50 m of
wandering lines 0.5 m apart along X, and on the same lines over the lower 40%
of the frame with one skipped. Before is Jacobi at e701f82 (load average about
2.6); after is the hierarchy (load average about 2.0, one run per case, the
plan column included):

    case                             before: plan  solve    its   after: plan  solve    its
    real lines, 0.2 m                0.001 s       0.004 s   38   0.019 s      0.009 s    7
    real lines, 0.05 m               0.005 s       0.410 s  540   0.060 s      0.105 s   15
    50 m grid, 0.2 m                 0.004 s       0.054 s   41   0.080 s      0.071 s    6
    50 m grid, 0.1 m                 0.023 s       0.892 s  155   0.270 s      0.442 s   11
    50 m grid, 0.05 m                0.132 s       14.3 s   492   1.39 s       3.29 s    15
    50 m, 40% covered, line skipped  0.003 s       0.157 s  136   0.582 s *    0.088 s    7

* A single noisy sample: re-measured at 0.10-0.22 s (0.12-0.16 s at load 3.3),
  as `eigh` on the 448-unknown coarsest level varies under BLAS thread
  contention.

The plan costs more, since it builds the hierarchy once per grid and distance.
At the frame cap (`MAX_FRAME_CELLS`, 2000 x 2000 cells at 0.05 m) building the
plan takes about 6.0 s against 0.54 s before, the plan holds about 95 B a
cell, and a solve takes about 13 s in 14 iterations.

The coarse grids are not worth it at 0.2 m, where the solve is slower: 1.4 to
2x on regular lines (median of 7, wandering 0.5 m lines: 5 x 20 m 4.8 to
9.6 ms; 30 x 30 m 20 to 31 ms; 40 x 40 m 34 to 51 ms; 50 x 50 m 51 to 72 ms;
the ten real lines 4 to 9 ms). It breaks even on the spike's irregular real
20 x 16 m grid, where Jacobi needed 144-171 iterations. Whole site adds its
grids' last solve times against the 50 ms live budget, so several mid-size
grids at 0.2 m can now show the kriging preview where they followed the depth
live before. The kriging preview's figures are in `interpolate.py`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from nsgeo.slices.interpolate import reach_mask
from nsgeo.slices.multigrid import Hierarchy, build_hierarchy

CURVATURE_TOL: float = 1e-6  # ‖r‖ ≤ tol · ‖b‖ ends the solve (plan call 3)
CURVATURE_EPS: float = 1e-6  # the slope term's weight, in cell units (plan call 1)
CURVATURE_MAX_ITERATIONS: int = 10_000
SOLVE_MARGIN_CELLS: int = 2  # D is the reach grown by this, the stencil's reach (plan call 2)

# The 13-point stencil, in the order of `CurvaturePlan.coefficients`.
_OFFSETS: tuple[tuple[int, int], ...] = tuple(
    (dy, dx) for dy in range(-2, 3) for dx in range(-2, 3) if abs(dy) + abs(dx) <= 2
)
_INDEX = {offset: k for k, offset in enumerate(_OFFSETS)}
_CENTRE = _INDEX[(0, 0)]
_PAD = 2  # the stencil's reach, padded around a vector so A·p needs no edge cases
# The energy's terms, one kind a row: the cells of a term as offsets from its
# first cell, their coefficients, and the term's weight (plan call 1).
_TERMS: tuple[tuple[tuple[tuple[int, int], ...], tuple[float, ...], float], ...] = (
    (((0, 0), (0, 1), (0, 2)), (1.0, -2.0, 1.0), 1.0),  # u_xx
    (((0, 0), (1, 0), (2, 0)), (1.0, -2.0, 1.0), 1.0),  # u_yy
    (((0, 0), (0, 1), (1, 0), (1, 1)), (1.0, -1.0, -1.0, 1.0), 2.0),  # u_xy
    (((0, 0), (0, 1)), (-1.0, 1.0), CURVATURE_EPS),  # slope along X
    (((0, 0), (1, 0)), (-1.0, 1.0), CURVATURE_EPS),  # slope along Y
)


class SolveStopped(Exception):
    """`CurvaturePlan.solve` gave up because `should_stop` asked it to."""


def _dot(a: np.ndarray, b: np.ndarray) -> float:
    """a · b accumulated in float64, in buffered chunks: no float64 copy."""
    return float(np.einsum("ij,ij->", a, b, dtype=np.float64))


@dataclass(frozen=True, eq=False)
class CurvaturePlan:
    """Where to solve and the operator to solve with. Built by `plan_curvature`;
    values never enter it, and `solve` only reads it, so a worker thread may
    solve while the GUI thread reads the same plan."""

    shape: tuple[int, int]
    populated: np.ndarray  # (ny*nx,) bool: cells that hold data
    reach: np.ndarray  # (ny*nx,) bool: finite in the output
    domain: np.ndarray  # (ny, nx) bool: the solve area D (plan call 2)
    coefficients: np.ndarray  # (13, ny, nx) float32: A's row at each unknown, by offset
    hierarchy: Hierarchy  # the multigrid preconditioner built on `coefficients` (#111)
    # Kept to re-plan around a non-finite datum (plan call 10).
    cell: float
    max_distance_m: float

    def __post_init__(self) -> None:
        # Frozen in fact, not only in name: the worker thread's safety rests on
        # nothing writing to a plan once it is built (plan call 6), so its
        # arrays refuse writes (the hierarchy froze its own). A non-finite
        # datum is solved on a new plan.
        for array in (self.populated, self.reach, self.domain, self.coefficients):
            array.flags.writeable = False

    def solve(
        self, values: np.ndarray, should_stop: Callable[[], bool] | None = None
    ) -> tuple[np.ndarray, int]:
        """(The slice, CG iterations run). Data cells as they are, the rest of
        the reach solved, NaN elsewhere.

        `should_stop`, when given, is asked once before the first V-cycle and
        then before every iteration; True raises `SolveStopped`. Neither the plan
        nor `values` is written.
        """
        values = np.asarray(values)
        if values.shape != self.shape:
            raise ValueError(f"values shape {values.shape} != plan shape {self.shape}")
        pop = self.populated.reshape(self.shape)
        finite = np.isfinite(values[pop].astype(np.float32))
        if not finite.all():
            # A non-finite datum shows as it is and is solved around, on a plan
            # for the finite data alone (plan call 10). Binned data never come here.
            # The re-plan builds a hierarchy too (Grid 1 size: 0.25 to 0.43 s a solve).
            usable = pop.copy()
            usable[pop] = finite
            plan = plan_curvature(usable, self.cell, self.max_distance_m)
            out, iterations = plan.solve(values, should_stop)
            out[pop] = values[pop]
            return out, iterations
        out = np.zeros(self.shape, dtype=np.float32)
        iterations = 0
        if (self.reach & ~self.populated).any():
            # Solved about the data mean, which changes nothing exactly
            # (A·1 = 0) but keeps float32's digits for the data's variation:
            # a constant field comes back exactly, and an offset costs nothing.
            mean = np.float32(np.mean(values[pop].astype(np.float32), dtype=np.float64))
            iterations = self._solve_into(out, values, mean, pop, should_stop)
            out += mean
        out[~self.reach.reshape(self.shape)] = np.nan
        out[pop] = values[pop]
        return out, iterations

    def _solve_into(
        self,
        x: np.ndarray,
        values: np.ndarray,
        mean: np.float32,
        pop: np.ndarray,
        should_stop: Callable[[], bool] | None,
    ) -> int:
        """Multigrid-preconditioned CG for A·x = b on the unknowns, b = −A·d with d
        the data on data cells and 0 elsewhere (plan call 3). `x` comes in as
        zeros and leaves holding the unknowns."""
        unknown = self.domain & ~pop
        # The start first: its scratch is freed before the solve's own
        # buffers exist, which keeps the peak near the plan (ruling R2).
        # The data about their mean, a copy this function frees as soon as it
        # has been used: it need not stay through the iterations.
        data = values.astype(np.float32)
        data -= mean
        np.copyto(x, _start(data, pop), where=unknown)
        # p lives inside a zero frame `_PAD` cells wide, and is 0 off the
        # unknowns, so A·p is 13 shifted multiply-adds with no edge cases.
        padded = np.zeros((self.shape[0] + 2 * _PAD, self.shape[1] + 2 * _PAD), np.float32)
        p = padded[_PAD:-_PAD, _PAD:-_PAD]
        q = np.empty(self.shape, np.float32)
        work = np.empty(self.shape, np.float32)
        np.copyto(p, data, where=pop)
        del data
        self._times(padded, q, work)
        b_norm = math.sqrt(_dot(q, q))
        if b_norm == 0.0:
            x[...] = 0.0  # every datum the stencil reaches is 0, so x = 0 is exact
            return 0
        np.copyto(p, x, where=unknown)
        self._times(padded, q, work)
        r = np.negative(q)  # r = b − A·x = −A·(d + x)
        if should_stop is not None and should_stop():
            raise SolveStopped  # before the first V-cycle, which is long at the frame cap
        z = self.hierarchy.precondition(r, (q, work))
        p[...] = z
        rz = _dot(r, z)
        del z
        iterations = 0
        while (
            iterations < CURVATURE_MAX_ITERATIONS and math.sqrt(_dot(r, r)) > CURVATURE_TOL * b_norm
        ):
            if should_stop is not None and should_stop():
                raise SolveStopped
            self._times(padded, q, work)
            pq = _dot(p, q)
            if not pq > 0.0:
                break  # float32 has run out of descent; x is as good as it gets
            alpha = rz / pq
            np.multiply(p, alpha, out=work)
            x += work
            np.multiply(q, alpha, out=work)
            r -= work
            z = self.hierarchy.precondition(r, (q, work))
            rz_next = _dot(r, z)
            p *= rz_next / rz
            p += z
            rz = rz_next
            del z  # not held across the next V-cycle
            iterations += 1
        return iterations

    def _times(self, padded: np.ndarray, out: np.ndarray, work: np.ndarray) -> np.ndarray:
        """out = A·p, where `padded` holds p inside its `_PAD`-cell frame."""
        ny, nx = self.shape
        for k, (dy, dx) in enumerate(_OFFSETS):
            shifted = padded[_PAD + dy : _PAD + dy + ny, _PAD + dx : _PAD + dx + nx]
            if k == 0:
                np.multiply(self.coefficients[k], shifted, out=out)
            else:
                np.multiply(self.coefficients[k], shifted, out=work)
                out += work
        return out

    def apply(self, values: np.ndarray) -> np.ndarray:
        """The filled slice, float32 (ny, nx): `solve(values)[0]`."""
        return self.solve(values)[0]

    def apply_at(self, values: np.ndarray, cells: np.ndarray) -> np.ndarray:
        """`apply(values).ravel()[cells]`. A solve has no shortcut to a few
        cells, so this is the whole slice, indexed."""
        return self.apply(values).ravel()[np.asarray(cells, dtype=np.intp)]

    @property
    def nbytes(self) -> int:
        return (
            self.populated.nbytes
            + self.reach.nbytes
            + self.domain.nbytes
            + self.coefficients.nbytes
            + self.hierarchy.nbytes
        )


def _grow(mask: np.ndarray, times: int) -> np.ndarray:
    """`mask` dilated `times` times by its 4-neighbours."""
    out = mask.copy()
    for _ in range(times):
        wider = out.copy()
        wider[1:] |= out[:-1]
        wider[:-1] |= out[1:]
        wider[:, 1:] |= out[:, :-1]
        wider[:, :-1] |= out[:, 1:]
        out = wider
    return out


def _stencil(domain: np.ndarray, unknown: np.ndarray) -> np.ndarray:
    """A's row at each unknown, by stencil offset: A = Σ w·c·cᵀ over the
    energy's terms, half its Hessian.

    Built term kind by term kind: for each pair of distinct cells (a, b) in a
    term, one vectorised pass adds w·c_a·c_b, wherever the whole term lies in
    D, to the coefficient at a for offset b − a. Probing an operator cell by
    cell instead cost 0.1 s at 0.2 m and 3 s at 0.05 m in the spike.

    The centre is then minus the sum of the rest, in float64, rounded once.
    Every term's coefficients sum to 0, so that is A's diagonal exactly, and
    it keeps A·1 = 0 in float32. Accumulated term by term instead, each ε
    landing on a diagonal near 20 rounded up a whole float32 step (1.9e-6), so
    every row summed to about +4e-6. That acted as a pull towards 0, which
    brought a constant 3.5 back as 3.4995.

    Last, the rows of data cells and of cells outside D are zeroed.
    """
    ny, nx = domain.shape
    out = np.zeros((len(_OFFSETS), ny, nx), dtype=np.float32)
    for cells, coefficients, weight in _TERMS:
        hy = max(dy for dy, _ in cells)
        hx = max(dx for _, dx in cells)
        if hy >= ny or hx >= nx:
            continue
        # Where the term lies wholly in D, indexed by its first cell.
        whole = np.ones((ny - hy, nx - hx), dtype=bool)
        for dy, dx in cells:
            whole &= domain[dy : dy + ny - hy, dx : dx + nx - hx]
        term = whole.astype(np.float32)
        add = np.empty_like(term)
        # zip without strict=: the core supports Python 3.9.
        for (ay, ax), ca in zip(cells, coefficients):
            for (by, bx), cb in zip(cells, coefficients):
                if (ay, ax) != (by, bx):
                    np.multiply(term, weight * ca * cb, out=add)
                    out[_INDEX[(by - ay, bx - ax)], ay : ay + ny - hy, ax : ax + nx - hx] += add
    centre = np.zeros((ny, nx), dtype=np.float64)
    for k in range(len(_OFFSETS)):
        if k != _CENTRE:
            centre -= out[k]
    out[_CENTRE] = centre
    out *= unknown
    return out


def _along_block(data: np.ndarray, pop: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per column, an estimate and its weight. The estimate is linear between
    the nearest data cells above and below, the one that exists where only
    one does, and NaN where the column has none. The weight is 1 / the span
    between the two in cells where both exist, else 0."""
    ny, nx = pop.shape
    rows = np.arange(ny, dtype=np.int32)[:, None]
    cols = np.arange(nx)
    above = np.maximum.accumulate(np.where(pop, rows, np.int32(-1)), axis=0)
    has_above = above >= 0
    lo = data[np.maximum(above, 0), cols]
    below = np.minimum.accumulate(np.where(pop, rows, np.int32(ny))[::-1], axis=0)[::-1]
    has_below = below < ny
    hi = data[np.minimum(below, ny - 1), cols]
    np.copyto(lo, hi, where=~has_above)
    np.copyto(hi, lo, where=~has_below)
    span = np.subtract(below, above, out=below)  # in place: `below` is not needed again
    del below
    weight = np.zeros(pop.shape, np.float32)
    both = has_above & has_below
    both &= span > 0
    np.divide(1.0, span, out=weight, where=both)
    del span, both
    # lo + (hi − lo) · (row − above) / span; 0 · anything where one side is missing.
    hi -= lo
    np.subtract(rows, above, out=above)
    hi *= above
    del above
    hi *= weight
    hi += lo
    hi[~has_above & ~has_below] = np.nan
    return hi, weight


def _along_columns(data: np.ndarray, pop: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """`_along_block` over blocks of columns, which are independent: its int32
    planes, index arrays and masks would otherwise be a dozen bytes a cell on
    top of the two outputs, and this runs twice inside `_start` at the solve's
    peak (ruling R2)."""
    ny, nx = pop.shape
    estimate = np.empty(pop.shape, np.float32)
    weight = np.empty(pop.shape, np.float32)
    step = max(1, 8192 // ny)
    for c0 in range(0, nx, step):
        block = slice(c0, min(nx, c0 + step))
        estimate[:, block], weight[:, block] = _along_block(data[:, block], pop[:, block])
    return estimate, weight


def _start(data: np.ndarray, pop: np.ndarray) -> np.ndarray:
    """The first guess: linear along each column (Y) and each row (X)
    (plan call 3, amended by the controller on 2026-11-05).

    Where data bracket a cell in either direction, the bracketed estimates
    are averaged, each weighted by 1 / its span in cells, so the nearer pair
    of data counts most. A wandering line crosses a row only now and then,
    and an equal average of the two directions needed about 40% more
    iterations on such lines. Columns alone would suit lines along X only,
    and a grid may hold lines both ways. Where neither direction is
    bracketed, the one-sided estimates are averaged, or the one there is
    taken, or else the data mean. Exact, up to rounding, for a constant
    field and for a plane between lines.
    """
    start, weight = _along_columns(data, pop)
    along_x, weight_x = (a.T for a in _along_columns(data.T, pop.T))
    has_y, has_x = ~np.isnan(start), ~np.isnan(along_x)
    total = weight + weight_x
    # The weighted sum, in `weight`'s buffer. A zero weight is skipped, not
    # multiplied, because its estimate may be NaN.
    np.multiply(start, weight, out=weight, where=weight > 0)
    np.multiply(along_x, weight_x, out=weight_x, where=weight_x > 0)
    weight += weight_x
    both = has_y & has_x
    np.add(start, along_x, out=start, where=both)
    np.multiply(start, 0.5, out=start, where=both)
    np.copyto(start, along_x, where=has_x & ~has_y)
    np.copyto(start, np.float32(np.mean(data[pop], dtype=np.float64)), where=~has_x & ~has_y)
    np.divide(weight, total, out=start, where=total > 0)
    return start


def plan_curvature(populated: np.ndarray, cell: float, max_distance_m: float) -> CurvaturePlan:
    """Plan minimum curvature for one grid: the solve area and its operator.

    `populated` is the (ny, nx) mask of cells holding data. The output is
    finite within `max_distance_m` of a data cell, as IDW's and kriging's are.
    """
    pop2 = np.asarray(populated)
    if pop2.ndim != 2:
        raise ValueError(f"populated must be 2-D, got {pop2.ndim}-D")
    if not cell > 0:
        raise ValueError(f"cell must be > 0, got {cell}")
    if not max_distance_m >= 0:
        raise ValueError(f"max_distance_m must be >= 0, got {max_distance_m}")
    pop2 = pop2.astype(bool)
    reach = reach_mask(pop2, cell, max_distance_m)
    domain = _grow(reach, SOLVE_MARGIN_CELLS)
    unknown = domain & ~pop2
    coefficients = _stencil(domain, unknown)
    return CurvaturePlan(
        shape=(int(pop2.shape[0]), int(pop2.shape[1])),
        populated=pop2.ravel(),
        reach=reach.ravel(),
        domain=domain,
        coefficients=coefficients,
        hierarchy=build_hierarchy(_OFFSETS, coefficients, unknown),
        cell=float(cell),
        max_distance_m=float(max_distance_m),
    )
