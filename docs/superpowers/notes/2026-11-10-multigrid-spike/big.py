"""50 m synthetic wandering lines at 0.05 m, and kriging plan time on Grid 1 (throwaway)."""
import sys, time
import numpy as np
sys.path.insert(0, sys.argv[1])
from common import load
from mg import Hierarchy, fine_stencil, solve_mg
from nsgeo.slices.curvature import plan_curvature
from nsgeo.slices.interpolate import plan_fill
mean, pop, cell, shape = load("grid1_005")

cell, n = 0.05, 1000
pop = np.zeros((n, n), bool)
yy = np.arange(n) * cell + cell / 2
for i in range(100):
    x = 0.25 + 0.5 * i + 0.06 * np.sin(yy / 3.0 + i)
    pop[np.arange(n), np.clip((x / cell).astype(int), 0, n - 1)] = True
rng = np.random.default_rng(0)
Y, X = np.mgrid[0:n, 0:n] * cell
field = (np.sin(X / 1.7) * np.cos(Y / 2.3) + 0.3 * np.sin(X * 3.1 + Y * 1.3)).astype(np.float32)
vals = np.where(pop, field, np.nan)
plan = plan_curvature(pop, cell, 0.375)
t = time.perf_counter(); H = Hierarchy(fine_stencil(plan), kind="linear", degree=2, ratio=16.0); ts = time.perf_counter() - t
print("levels", H.describe())
t = time.perf_counter(); o1, i1 = solve_mg(plan, H, vals); t1 = time.perf_counter() - t
t = time.perf_counter(); o0, i0 = plan.solve(vals); t0 = time.perf_counter() - t
gap = plan.reach.reshape(pop.shape) & ~pop
print(f"50 m @ 0.05: today {t0:.1f} s ({i0} its); mg setup {ts:.2f} s, solve {t1:.2f} s ({i1} its); |diff| max {np.abs(o1-o0)[gap].max()/np.ptp(field[pop]):.1e}")
