"""Check mg2 (the plan's algorithm) on Grid 1 and on the existing tests' cases."""

import math
import sys
import time

import numpy as np

sys.path.insert(0, sys.argv[1])
import mg2  # noqa: E402
from common import WINDOWS, load, window  # noqa: E402

from nsgeo.slices.curvature import _OFFSETS, CURVATURE_TOL, _start, plan_curvature  # noqa: E402


def dot(a, b):
    return float(np.einsum("ij,ij->", a, b, dtype=np.float64))


def solve(plan, H, values):
    shape = plan.shape
    pop = plan.populated.reshape(shape)
    unknown = plan.domain & ~pop
    data = np.asarray(values, np.float32).copy()
    mean = np.float32(np.mean(data[pop], dtype=np.float64))
    data -= mean
    d = np.where(pop, data, 0).astype(np.float32)
    b = -mg2.apply_stencil(_OFFSETS, plan.coefficients, d)
    bn = math.sqrt(dot(b, b))
    x = np.zeros(shape, np.float32)
    np.copyto(x, _start(data, pop), where=unknown)
    its = 0
    if bn > 0:
        r = b - mg2.apply_stencil(_OFFSETS, plan.coefficients, x * unknown)
        z = H.precondition(r)
        p = z.copy()
        rz = dot(r, z)
        while its < 10000 and math.sqrt(dot(r, r)) > CURVATURE_TOL * bn:
            q = mg2.apply_stencil(_OFFSETS, plan.coefficients, p * unknown)
            pq = dot(p, q)
            if not pq > 0:
                break
            a = rz / pq
            x += np.float32(a) * p
            r -= np.float32(a) * q
            z = H.precondition(r)
            rz1 = dot(r, z)
            p = z + np.float32(rz1 / rz) * p
            rz = rz1
            its += 1
    out = x + mean
    out[~plan.reach.reshape(shape)] = np.nan
    out[pop] = np.asarray(values)[pop]
    return out, its


def hier(plan, coarsest=None):
    unknown = plan.domain & ~plan.populated.reshape(plan.shape)
    return mg2.build_hierarchy(_OFFSETS, plan.coefficients, unknown, coarsest)



if __name__ == '__main__':
    for md in (0.25, 0.375):
        mean, pop, cell, shape = load("grid1_005")
        plan = plan_curvature(pop, cell, md)
        t = time.perf_counter()
        H = hier(plan)
        ts = time.perf_counter() - t
        sizes = [(L.active.shape, int(L.active.sum()), round(L.upper, 2)) for L in H.levels]
        res = []
        for k0, k1 in WINDOWS[:4]:
            v = window(mean, shape, k0, k1)
            t = time.perf_counter()
            out, it = solve(plan, H, v)
            dt = time.perf_counter() - t
            ref, _ = plan.solve(v)
            gap = plan.reach.reshape(shape) & ~pop
            res.append((round(dt, 3), it, float(np.abs(out - ref)[gap].max() / np.ptp(v[pop]))))
        print(f"Grid 1 0.05 md {md}: setup {ts:.2f} s levels {sizes}\n   solves {res}")

    # the existing tests' cases
    STEP = 0.05


    def lines(rows=(5, 15, 25, 35), ny=40, nx=60):
        p = np.zeros((ny, nx), bool)
        p[list(rows), :] = True
        return p


    p = lines()
    plan = plan_curvature(p, STEP, 0.25)
    v = np.random.default_rng(0).normal(size=p.shape)
    H = hier(plan)
    print("lines() 40x60: levels", [int(L.active.sum()) for L in H.levels], "its", solve(plan, H, v)[1], "today", plan.solve(v)[1])
    for c in (16, 4, 1):
        H = hier(plan, c)
        print(f"   coarsest {c}: levels", [int(L.active.sum()) for L in H.levels], "its", solve(plan, H, v)[1])

    # partial coverage case (test_partial_coverage_solves_in_few_iterations)
    cell, n = 0.2, 250
    pop = np.zeros((n, n), bool)
    rows = (np.arange(0.25, 0.4 * n * cell, 0.5) // cell).astype(int)
    pop[np.delete(rows, rows.size // 2)] = True
    yy, xx = np.indices(pop.shape)
    y, x = (yy + 0.5) * cell, (xx + 0.5) * cell
    v = np.sin(x / 1.7) * np.cos(y / 2.3) + 0.05 * x
    plan = plan_curvature(pop, cell, 0.375)
    H = hier(plan)
    print("partial coverage: its", solve(plan, H, v)[1], "today", plan.solve(v)[1])

    # cell independence on synthetic lines along X, 10 m x 10 m
    for cell in (0.2, 0.1, 0.05):
        n = int(round(10 / cell))
        pop = np.zeros((n, n), bool)
        yy = np.arange(n)
        for i in range(20):
            xline = 0.25 + 0.5 * i + 0.06 * np.sin(yy * cell / 3.0 + i)
            pop[yy, np.clip((xline / cell).astype(int), 0, n - 1)] = True
        Y, X = (np.indices(pop.shape) + 0.5) * cell
        v = np.sin(X / 1.7) * np.cos(Y / 2.3) + 0.3 * np.sin(X * 3.1 + Y * 1.3)
        plan = plan_curvature(pop, cell, 0.375)
        t = time.perf_counter()
        H = hier(plan)
        ts = time.perf_counter() - t
        t = time.perf_counter()
        _, it = solve(plan, H, v)
        t1 = time.perf_counter() - t
        t = time.perf_counter()
        _, it0 = plan.solve(v)
        t0 = time.perf_counter() - t
        print(f"10 m wandering @ {cell}: mg its {it} ({t1:.3f} s, setup {ts:.3f}) today {it0} ({t0:.3f} s)")

    # degenerate: one row, no unknowns
    one = np.zeros((1, 3000), bool)
    one[0, ::7] = True
    plan = plan_curvature(one, 0.05, 0.2)
    H = hier(plan)
    print("one row:", [L.active.shape for L in H.levels], "its", solve(plan, H, np.random.default_rng(1).normal(size=one.shape))[1])
    full = np.ones((30, 30), bool)
    plan = plan_curvature(full, 0.05, 0.2)
    H = hier(plan)
    print("no unknowns:", [int(L.active.sum()) for L in H.levels], H.coarse_inverse.shape)
