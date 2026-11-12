"""Throwaway (planning, 2026-11-11): per-line values from mean-of-neighbours residuals.

Candidates are lines whose residual is clear and repeatable across independent halves; each run of
adjacent candidates is solved jointly (second-difference model), then re-measured a few times with
the candidates corrected. See the spike note, "Per-line prototype".

usage: per_line_block.py <cache.npz> <survey.nsgeo.json> <grid id> [k:d ...] [skew]
  k:d moves 0-based line k by d metres along its travel; skew adds 0.02 m x (offset rank) to every line.
  env: ONLY=unfit|fit, ITER, CLEAR, MIN_OWN, AGREE, REL, CHANGE.
"""
import sys, os
import numpy as np
P = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(P, "per_line_common.py")).read()
argv = sys.argv[:]
exec(src)
sys.argv = argv
CLEAR = float(os.environ.get("CLEAR", 0.25))
MIN_OWN = float(os.environ.get("MIN_OWN", 0.10))
AGREE = float(os.environ.get("AGREE", 0.10))
REL = float(os.environ.get("REL", 0.30))
CHANGE = float(os.environ.get("CHANGE", 0.30))
ONLY = os.environ.get("ONLY")
A, has = matrix()

def cp(c):
    lag, _, ratio = clear_peak(c)
    return lag, ratio >= CLEAR

for fit in (False, True):
    if ONLY and ONLY != ("fit" if fit else "unfit"): continue
    zero = np.zeros(len(lines))
    C = curves(placements(fit, 0.0, zero), 4, 70, 0, length)
    g = spike["peak"](np.array([C[k] for k in sorted(C)]).sum(axis=1).mean(axis=0))[0]
    d = -g / 2
    base = placements(fit, d, zero)
    subsets = {"full": (4, 70, 0, length), "sh": (4, 25, 0, length), "dp": (25, 70, 0, length),
               "fi": (4, 70, 0, length / 2), "se": (4, 70, length / 2, length)}
    R, OK = {}, {}
    for h, v in subsets.items():
        Ch = curves(base, *v)
        R[h] = np.zeros(len(lines)); OK[h] = np.zeros(len(lines), bool)
        for k, c in Ch.items():
            lag, ok = cp(c.sum(axis=0)); R[h][k] = dirs[k] * lag; OK[h][k] = ok
    n = len(lines)
    status = {}
    cand = np.zeros(n, bool)
    for k in range(n):
        if not has[k]: status[k] = "not measured"; continue
        if not OK["full"][k]: status[k] = "no clear match"; continue
        fi, se = R["fi"][k], R["se"][k]
        if OK["fi"][k] and OK["se"][k] and abs(fi - se) > CHANGE: status[k] = "changes partway"; continue
        tol = max(AGREE, REL * abs(R["full"][k]))
        agree = lambda a, b: OK[a][k] and OK[b][k] and abs(R[a][k] - R[b][k]) <= tol
        if abs(R["full"][k]) >= MIN_OWN and (agree("sh", "dp") or agree("fi", "se")):
            cand[k] = True
        status[k] = "grid"
    # block solve on runs of candidates contiguous in offset order
    x = np.zeros(n)
    pos = {k: i for i, k in enumerate(order)}
    run = []
    for k in order + [None]:
        if k is not None and cand[k]:
            run.append(k); continue
        if run:
            Asub = A[np.ix_(run, run)]
            x[run] = np.linalg.solve(Asub, R["full"][run])
            run = []
    ITER = int(os.environ.get("ITER", 3))
    def solve_runs(r):
        dx = np.zeros(n); run = []
        for k in order + [None]:
            if k is not None and cand[k]:
                run.append(k); continue
            if run:
                dx[run] = np.linalg.solve(A[np.ix_(run, run)], r[run]); run = []
        return dx
    for it in range(ITER):
        own_dir = dirs * x
        Ci = curves(placements(fit, d, own_dir), 4, 70, 0, length)
        r = np.zeros(n)
        for k, c in Ci.items():
            r[k] = dirs[k] * cp(c.sum(axis=0))[0]
        dx = solve_runs(r)
        x = np.clip(x + dx, -1.0, 1.0)
        print(f"   iter {it}: max |dx| {np.abs(dx[cand]).max()*100 if cand.any() else 0:.1f} cm")
    own = []
    for k in range(n):
        if cand[k] and abs(x[k]) >= MIN_OWN:
            status[k] = "OWN"
            own.append(f"{names[k]} res {dirs[k]*R['full'][k]*100:+.0f} -> own {dirs[k]*x[k]*100:+.0f}cm -> {d - dirs[k]*x[k]:+.3f}  (sh{dirs[k]*R['sh'][k]*100:+.0f} dp{dirs[k]*R['dp'][k]*100:+.0f} fi{dirs[k]*R['fi'][k]*100:+.0f} se{dirs[k]*R['se'][k]*100:+.0f})")
        elif cand[k]:
            status[k] = "grid (dragged)"
    cnt = {s: sum(1 for v in status.values() if v == s) for s in set(status.values())}
    print(f"\n{gid} {'FITTED' if fit else 'UNFITTED'} grid {d:+.3f} inject {inject} skew {skew}: {cnt}")
    for s in own: print("   OWN", s)
    for s in ("changes partway", "no clear match", "grid (dragged)"):
        ks = [names[k] for k in range(n) if status[k] == s]
        if ks: print(f"   {s}: {' '.join(ks)}")
