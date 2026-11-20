"""Sweep MG settings on Grid 1 (throwaway). usage: sweep.py SPIKE CUBE MAXDIST"""
import sys, time
import numpy as np
sys.path.insert(0, sys.argv[1])
from common import WINDOWS, load, window
from mg import Hierarchy, fine_stencil, solve_mg
from nsgeo.slices.curvature import plan_curvature
name, md = sys.argv[2], float(sys.argv[3])
mean, pop, cell, shape = load(name)
plan = plan_curvature(pop, cell, md)
wins = [WINDOWS[i] for i in (0, 2, 4, 6) if WINDOWS[i][1] <= mean.shape[0]]
vals = [window(mean, shape, *w) for w in wins]
rngs = [float(np.ptp(v[pop])) for v in vals]
gap = plan.reach.reshape(shape) & ~pop
H64 = Hierarchy(fine_stencil(plan, np.float64), kind="linear", degree=3, ratio=8)
refs = [solve_mg(plan, H64, v, tol=1e-11, maxit=2000, dtype=np.float64)[0] for v in vals]
def errs(outs):
    e = np.concatenate([np.abs(o - r)[gap] / g for o, r, g in zip(outs, refs, rngs)])
    return f"max {e.max():.1e} p99 {np.percentile(e, 99):.1e}"
t = time.perf_counter(); today = [plan.solve(v) for v in vals]; tt = (time.perf_counter() - t) / len(vals)
print(f"{name} md {md}: today {tt:.2f} s/slice, its {[i for _, i in today]}, err {errs([o for o, _ in today])}")
for kind, deg, ratio in [("linear",2,16)]:
    t = time.perf_counter()
    H = Hierarchy(fine_stencil(plan), kind=kind, degree=deg, ratio=ratio)
    ts = time.perf_counter() - t
    times, its, outs = [], [], []
    for v in vals:
        t = time.perf_counter(); o, i = solve_mg(plan, H, v); times.append(time.perf_counter() - t); its.append(i); outs.append(o)
    print(f"  {kind:6s} deg {deg} ratio {ratio:4.0f}: setup {ts:.2f} s, solve {np.median(times):.3f} s, its {its}, x{tt/np.median(times):.1f}, err {errs(outs)}")
