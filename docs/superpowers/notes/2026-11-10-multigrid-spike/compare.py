"""MG-PCG vs today's solver on Grid 1 (throwaway, #111 spike).

usage: compare.py SPIKE_DIR CUBE MAXDIST KIND DEGREE RATIO [NWIN]
"""

import sys
import time

import numpy as np

sys.path.insert(0, sys.argv[1])
from common import WINDOWS, load, window  # noqa: E402
from mg import Hierarchy, fine_stencil, solve_mg  # noqa: E402

from nsgeo.slices.curvature import plan_curvature  # noqa: E402

name, md, kind = sys.argv[2], float(sys.argv[3]), sys.argv[4]
degree, ratio = int(sys.argv[5]), float(sys.argv[6])
nwin = int(sys.argv[7]) if len(sys.argv) > 7 else 4
mean, pop, cell, shape = load(name)
plan = plan_curvature(pop, cell, md)
t = time.perf_counter()
H = Hierarchy(fine_stencil(plan), kind=kind, degree=degree, ratio=ratio)
print(f"{name} md={md} {kind} cheb deg {degree} ratio {ratio}: setup {time.perf_counter() - t:.2f} s")
print("  levels", H.describe())
reach = plan.reach.reshape(shape) & ~pop
for k0, k1 in WINDOWS[:nwin]:
    v = window(mean, shape, k0, k1)
    rng = float(np.ptp(v[pop]))
    t = time.perf_counter()
    ref, it0 = plan.solve(v)
    t0 = time.perf_counter() - t
    t = time.perf_counter()
    out, it1 = solve_mg(plan, H, v)
    t1 = time.perf_counter() - t
    err = np.abs(out - ref)[reach] / rng
    print(f"  levels {k0}-{k1}: today {t0:.2f} s ({it0} its)  mg {t1:.3f} s ({it1} its)"
          f"  x{t0 / t1:.1f}  |diff| max {err.max():.1e} p99 {np.percentile(err, 99):.1e}")
