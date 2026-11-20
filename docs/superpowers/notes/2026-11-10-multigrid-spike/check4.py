"""Real ten lines at 0.05 m: mg2 iterations and error vs a float64 tight solve; stationary contraction."""
import math, sys, time
import numpy as np
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, "packages/nsgeo-core")
import mg2
from check2 import solve, hier
from tests.real_lines import prepared_lines, binned, WINDOWS, SPACING
from tests.test_slices_curvature import lines, values, STEP
from nsgeo.slices import CubeFrame
from nsgeo.slices.curvature import _OFFSETS, plan_curvature


def tight(plan, values):
    shape = plan.shape
    pop = plan.populated.reshape(shape)
    unknown = plan.domain & ~pop
    A = plan.coefficients.astype(np.float64)
    def times(x):
        pad = np.zeros((shape[0] + 4, shape[1] + 4)); pad[2:-2, 2:-2] = x
        return sum(A[k] * pad[2 + dy: 2 + dy + shape[0], 2 + dx: 2 + dx + shape[1]] for k, (dy, dx) in enumerate(_OFFSETS))
    v = np.asarray(values, np.float64)
    d = np.where(pop, v, 0.0)
    b = -times(d)
    x = np.zeros(shape)
    diag = A[_OFFSETS.index((0, 0))]
    inv = np.where(unknown, 1.0 / np.where(unknown, diag, 1.0), 0.0)
    r = b.copy(); z = r * inv; p = z.copy(); rz = (r * z).sum(); bn = math.sqrt((b * b).sum()); its = 0
    while math.sqrt((r * r).sum()) > 1e-10 * bn and its < 20000:
        q = times(p * unknown); a = rz / (p * q).sum(); x += a * p; r -= a * q; z = r * inv; rz1 = (r * z).sum(); p = z + rz1 / rz * p; rz = rz1; its += 1
    out = np.where(pop, v, x); out[~plan.reach.reshape(shape)] = np.nan
    return out, its


frame = CubeFrame((0.0, 0.0), 0.0, 0.05, 400, 100, "EPSG:32633")
lns = prepared_lines(range(10), lambda local: local)
for k0, k1 in WINDOWS:
    v, cov = binned(lns, frame, k0, k1)
    pop = cov > 0
    plan = plan_curvature(pop, 0.05, 0.75 * SPACING)
    H = hier(plan)
    out, it = solve(plan, H, v)
    t = time.perf_counter(); want, it_ref = tight(plan, v); tr = time.perf_counter() - t
    today, it_today = plan.solve(v)
    gap = plan.reach.reshape(plan.shape) & ~pop
    rng = np.ptp(np.asarray(v)[pop])
    print(f"window {k0}-{k1}: levels {[int(L.active.sum()) for L in H.levels]} mg its {it} err {np.abs(out - want)[gap].max() / rng:.1e}; today its {it_today} err {np.abs(today - want)[gap].max() / rng:.1e}; ref {it_ref} its {tr:.1f} s")

# stationary contraction: x <- x + M(b - A x), A-norm error ratio per cycle
plan = plan_curvature(lines(), STEP, 0.25)
unknown = plan.domain & ~plan.populated.reshape(plan.shape)
for c in (500, 8):
    H = hier(plan, c)
    rng = np.random.default_rng(3)
    xs = (rng.normal(size=plan.shape) * unknown).astype(np.float32)  # exact solution
    b = mg2.apply_stencil(_OFFSETS, plan.coefficients, xs * unknown)
    x = np.zeros(plan.shape, np.float32)
    def anorm(e): return math.sqrt(float(np.vdot(e, mg2.apply_stencil(_OFFSETS, plan.coefficients, e * unknown))))
    e0 = anorm(xs - x); ratios = []
    for _ in range(6):
        x = x + H.precondition(b - mg2.apply_stencil(_OFFSETS, plan.coefficients, x * unknown))
        e1 = anorm(xs - x); ratios.append(round(e1 / e0, 3)); e0 = e1
    print(f"stationary V-cycle on lines(), coarsest {c}: levels {len(H.levels)} A-norm error ratio per cycle {ratios}")
