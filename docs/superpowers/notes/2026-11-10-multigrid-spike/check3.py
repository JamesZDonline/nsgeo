import sys, time, threading
import numpy as np
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, "packages/nsgeo-core/tests")
import mg2
from check2 import solve, hier
from test_slices_curvature import dense_solve, lines, values, STEP
from nsgeo.slices.curvature import plan_curvature
from nsgeo.slices.interpolate import reach_mask
from common import WINDOWS, load, window
for md in (0.15, 0.5):
    rng = np.random.default_rng(5)
    pop = rng.random((12, 14)) < 0.2
    v = rng.normal(size=pop.shape)
    want = dense_solve(pop, v, 0.1, md)
    plan = plan_curvature(pop, 0.1, md)
    reach = reach_mask(pop, 0.1, md)
    for c in (500, 8, 2):
        H = hier(plan, c)
        got, it = solve(plan, H, v)
        print(f"dense ref md {md} coarsest {c}: levels {[int(L.active.sum()) for L in H.levels]} its {it} err {np.abs(got - want)[reach].max() / np.ptp(v[pop]):.1e}")
# bigger dense reference: 30x34 at 0.1 with 20% random data and lines
rng = np.random.default_rng(7)
pop = rng.random((30, 34)) < 0.08
pop[[4, 12, 20, 27], :] = True
v = rng.normal(size=pop.shape)
t = time.perf_counter(); want = dense_solve(pop, v, 0.1, 0.3); print(f"dense 30x34 took {time.perf_counter()-t:.1f} s")
plan = plan_curvature(pop, 0.1, 0.3); reach = reach_mask(pop, 0.1, 0.3)
for c in (500, 30):
    H = hier(plan, c); got, it = solve(plan, H, v)
    print(f"dense 30x34 coarsest {c}: levels {[int(L.active.sum()) for L in H.levels]} its {it} err {np.abs(got - want)[reach].max() / np.ptp(v[pop]):.1e}")
# symmetry / positivity of the preconditioner
plan = plan_curvature(lines(), STEP, 0.25); H = hier(plan, 8)
unk = plan.domain & ~plan.populated.reshape(plan.shape)
r1 = (np.random.default_rng(1).normal(size=plan.shape) * unk).astype(np.float32)
r2 = (np.random.default_rng(2).normal(size=plan.shape) * unk).astype(np.float32)
a, b = float(np.vdot(H.precondition(r1), r2)), float(np.vdot(r1, H.precondition(r2)))
print(f"symmetry {abs(a-b)/abs(a):.1e}  positive {float(np.vdot(H.precondition(r1), r1)) > 0}, zero off active {np.abs(H.precondition(r1)[~unk]).max()}")
# lines() and stop test
v = values(lines())
print("lines() its", solve(plan, hier(plan), v)[1])
# threads
mean, pop, cell, shape = load("grid1_005"); plan = plan_curvature(pop, cell, 0.25); H = hier(plan)
vals = [window(mean, shape, *w) for w in WINDOWS[:4]]
serial = [solve(plan, H, v)[0] for v in vals]
outs = [None]*4
def run(i): outs[i] = solve(plan, H, vals[i])[0]
ts = [threading.Thread(target=run, args=(i,)) for i in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
print("threads identical:", all(np.array_equal(a, b, equal_nan=True) for a, b in zip(serial, outs)))
