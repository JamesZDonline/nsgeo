"""Is the direction-dependent shift a time delay (scales with speed) or a fixed offset (does not)?"""
import sys, runpy
import numpy as np
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2], sys.argv[3] + ".tmp.npz"]
g = runpy.run_path(sys.argv[2] + "/s2_delay.py", run_name="s2")  # reruns the sweep; fine for a spike
L, u, gps_xy, profiles, shifts, peak, A, south = (g[k] for k in ["L", "u", "gps_xy", "profiles", "shifts", "peak", "A", "south"])
spd = []
for ln in L:
    d = np.hypot(np.diff(ln["e"]), np.diff(ln["n"])); dt = np.diff(ln["t"])
    spd.append(np.median(d[dt == 1.0]))
spd = np.array(spd)
C = g["curves_by_tau"][0.0]
s = np.array([peak(C[k].sum(axis=0))[0] for k in range(len(L))])
nbv = np.array([np.mean([spd[j] for j in (k - 1, k + 1) if 0 <= j < len(L)]) for k in range(len(L))])
X = spd + nbv
print(f"per-line speed: median {np.median(spd):.3f}, range {spd.min():.3f}-{spd.max():.3f} m/s")
# model 1: latency only  s = -tau * X
tau1 = -np.sum(s * X) / np.sum(X * X); r1 = s + tau1 * X
# model 2: offset only  s = -2d
d2 = -np.mean(s); r2 = s + 2 * d2
# model 3: both  s = a + b X
b, a = np.polyfit(X, s, 1); r3 = s - (a + b * X)
n = len(s)
for lab, r, k in [("latency only", r1, 1), ("offset only", r2, 1), ("both", r3, 2)]:
    print(f"  {lab:12s}: rss {np.sum(r**2)*1e4:.1f} cm^2, BIC-ish {n*np.log(np.sum(r**2)/n)+k*np.log(n):.1f}")
print(f"  latency-only fit tau = {tau1:.3f} s; offset-only fit d = {d2*100:.1f} cm; both: offset {-a/2*100:.1f} cm + tau {-b:.3f} s")
print(f"  corr(shift, speed sum) = {np.corrcoef(s, X)[0,1]:.2f}")
# shift along the line: thirds of the interior
for tau in (0.0, 0.35):
    F = profiles([gps_xy(ln, tau) @ u for ln in L])
    thirds = np.array_split(np.arange(A.size), 3)
    out = []
    for th in thirds:
        Fs = F[:, :, th]
        Ftmp = Fs
        g["A"] = A[th]
        Cs = g["shifts"](Ftmp)
        out.append(peak(Cs.sum(axis=1).mean(axis=0))[0])
    g["A"] = A
    near = np.mean([(F[k] * F[k + 1]).sum() / A.size for k in range(len(L) - 1)])
    near2 = np.mean([(F[k] * F[k + 2]).sum() / A.size for k in range(len(L) - 2)])
    print(f"tau {tau:.2f}: shift by along-third (south->north) {', '.join(f'{x*100:+.1f}' for x in out)} cm; zero-lag corr neighbours {near:.2f}, same-direction k+2 {near2:.2f}")
