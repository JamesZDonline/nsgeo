"""Time today's solver on Sunnyside Grid 1 (throwaway, #111 spike)."""

import sys
import time

import numpy as np

sys.path.insert(0, sys.argv[1])  # the spike folder
from common import WINDOWS, load, window  # noqa: E402

from nsgeo.slices.curvature import plan_curvature  # noqa: E402

name = sys.argv[2] if len(sys.argv) > 2 else "grid1_005"
mean, pop, cell, shape = load(name)
print(name, "shape", shape, "cell", cell, "populated", round(pop.mean(), 3))
for md in (0.25, 0.375):
    t = time.perf_counter()
    plan = plan_curvature(pop, cell, md)
    tp = time.perf_counter() - t
    unknowns = int((plan.domain & ~pop).sum())
    print(f"  max distance {md} m: plan {tp:.2f} s, unknowns {unknowns}")
    times, its = [], []
    for k0, k1 in WINDOWS:
        if k1 > mean.shape[0]:
            continue
        v = window(mean, shape, k0, k1)
        t = time.perf_counter()
        out, it = plan.solve(v)
        times.append(time.perf_counter() - t)
        its.append(it)
    print(f"    solve median {np.median(times):.2f} s (min {min(times):.2f}, max {max(times):.2f}),"
          f" iterations median {int(np.median(its))} ({min(its)}-{max(its)}),"
          f" per iteration {1000 * np.median(times) / np.median(its):.1f} ms")
