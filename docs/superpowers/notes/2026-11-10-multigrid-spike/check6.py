"""Pre-check the plan's Task 1 test assertions against mg2 (throwaway)."""
import sys
import numpy as np
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, "packages/nsgeo-core")
import mg2
from nsgeo.slices.curvature import _OFFSETS, plan_curvature


def operator(pop, cell, md):
    plan = plan_curvature(pop, cell, md)
    return plan.coefficients, plan.domain & ~plan.populated.reshape(plan.shape)


def dense(level):
    ny, nx = level.active.shape
    cells = np.flatnonzero(level.active.ravel())
    m = np.zeros((cells.size, cells.size))
    for j, c in enumerate(cells):
        e = np.zeros(ny * nx, np.float32); e[c] = 1
        m[:, j] = mg2.apply_stencil(level.offsets, level.coefficients, e.reshape(ny, nx)).ravel()[cells]
    return m, cells


def prolongation(fine_active, coarse_active):
    fs, cs = fine_active.shape, coarse_active.shape
    fcells = np.flatnonzero(fine_active.ravel()); ccells = np.flatnonzero(coarse_active.ravel())
    p = np.zeros((fcells.size, ccells.size))
    for j, c in enumerate(ccells):
        e = np.zeros(cs[0] * cs[1], np.float32); e[c] = 1
        p[:, j] = (mg2.prolong(e.reshape(cs), fs) * fine_active).ravel()[fcells]
    return p

# transpose
rng = np.random.default_rng(0)
for s in [(17, 9), (16, 10), (1, 7), (2, 2), (1, 1)]:
    cs = ((s[0] + 1) // 2, (s[1] + 1) // 2)
    c = rng.normal(size=cs).astype(np.float32); f = rng.normal(size=s).astype(np.float32)
    a, b = float(np.vdot(mg2.prolong(c, s), f)), float(np.vdot(c, mg2.restrict(f, cs)))
    assert abs(a - b) <= 1e-5 * np.linalg.norm(c) * np.linalg.norm(f), (s, a, b)
# constants / lines
for s in [(17, 9), (16, 10)]:
    cs = ((s[0] + 1) // 2, (s[1] + 1) // 2)
    assert np.allclose(mg2.prolong(np.full(cs, 2.5, np.float32), s), 2.5, atol=1e-6)
    c = np.repeat(np.arange(cs[0], dtype=np.float32)[:, None], cs[1], 1)
    f = mg2.prolong(c, s); i = np.arange(1, s[0] - 1)
    assert np.allclose(f[1:-1, :], ((i + 0.5) / 2 - 0.5)[:, None], atol=1e-6)
print("transfers ok")
# galerkin
pop = np.random.default_rng(5).random((11, 13)) < 0.2; pop[6] = True
coef, act = operator(pop, 0.1, 0.3)
mg2_c = mg2.COARSEST_UNKNOWNS
H = mg2.build_hierarchy(_OFFSETS, coef, act, coarsest=1)
print("levels", [int(L.active.sum()) for L in H.levels])
for k in range(1, len(H.levels)):
    ac, _ = dense(H.levels[k]); af, _ = dense(H.levels[k - 1])
    P = prolongation(H.levels[k - 1].active, H.levels[k].active)
    want = P.T @ af @ P
    assert np.abs(ac - want).max() <= 1e-5 * np.abs(want).max(), (k, np.abs(ac - want).max(), np.abs(want).max())
    cs = H.levels[k].active.shape
    assert np.array_equal(H.levels[k].active, mg2.restrict(H.levels[k - 1].active.astype(np.float32), cs) > 0), k
print("galerkin + active ok")
for L in H.levels:
    m, cells = dense(L)
    s = np.sqrt(L.inverse_diagonal.ravel()[cells])
    w = np.linalg.eigvalsh(0.5 * ((s[:, None] * m * s[None, :]) + (s[:, None] * m * s[None, :]).T))
    print("  bound: min", w.min(), "max", w.max())
    assert w.min() > 0 and w.max() <= 1 + 1e-5
# one level inverts
pop = np.random.default_rng(5).random((12, 14)) < 0.2
coef, act = operator(pop, 0.1, 0.15)
H = mg2.build_hierarchy(_OFFSETS, coef, act)
assert len(H.levels) == 1
r = (np.random.default_rng(1).normal(size=act.shape) * act).astype(np.float32)
back = mg2.apply_stencil(_OFFSETS, coef, H.precondition(r))
print("one level: max |A M r - r| / max|r| =", np.abs(back - r)[act].max() / np.abs(r).max())
