"""Smoother bound choices for mg2 (throwaway): Gershgorin, power x1.1, l1-Jacobi."""
import math, sys, time
import numpy as np
sys.path.insert(0, sys.argv[1])
import mg2
from check2 import solve, hier  # reruns check2's prints; acceptable
from common import WINDOWS, load, window
from nsgeo.slices.curvature import _OFFSETS, plan_curvature


def power(level, its=20):
    x = np.random.default_rng(0).standard_normal(level.active.shape).astype(np.float32) * level.active
    lam = 0.0
    for _ in range(its):
        y = mg2.apply_stencil(level.offsets, level.coefficients, x * level.active) * level.inverse_diagonal
        n = math.sqrt(float(np.vdot(y, y)))
        if n == 0:
            return 1.0
        lam = n / math.sqrt(float(np.vdot(x, x)))
        x = y / n
    return lam


def l1(level):
    """Rescale the level so its diagonal is the row's absolute sum: upper = 1."""
    absrow = np.abs(level.coefficients).sum(axis=0)
    inv = np.zeros(level.active.shape, np.float32)
    np.divide(1.0, absrow, out=inv, where=level.active)
    return mg2.Level(level.offsets, level.coefficients, level.active, inv, 1.0)


def with_upper(H, mode):
    levels = []
    for L in H.levels:
        if mode == "power":
            p = power(L)
            levels.append(mg2.Level(L.offsets, L.coefficients, L.active, L.inverse_diagonal, min(L.upper, 1.1 * p)))
        elif mode == "l1":
            levels.append(l1(L))
        else:
            levels.append(L)
    return mg2.Hierarchy(tuple(levels), H.coarse_cells, H.coarse_inverse)


mean, pop, cell, shape = load("grid1_005")
for md in (0.25, 0.375):
    plan = plan_curvature(pop, cell, md)
    H0 = hier(plan)
    print(f"md {md} gershgorin {[round(L.upper, 2) for L in H0.levels]} power {[round(power(L), 2) for L in H0.levels]}")
    for mode in ("gershgorin", "power", "l1"):
        H = with_upper(H0, mode)
        res = []
        for k0, k1 in WINDOWS:
            v = window(mean, shape, k0, k1)
            t = time.perf_counter(); out, it = solve(plan, H, v); dt = time.perf_counter() - t
            res.append((it, round(dt, 2)))
        print(f"   {mode:10s} its/time {res}")
