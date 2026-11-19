"""Latency vs fixed offset, using speed variation WITHIN lines (5 m windows)."""
import sys, runpy
import numpy as np
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2], sys.argv[3] + ".tmp.npz"]
g = runpy.run_path(sys.argv[2] + "/s2_delay.py", run_name="s2")
L, u, gps_xy, profiles, peak, A, south = (g[k] for k in ["L", "u", "gps_xy", "profiles", "peak", "A", "south"])
F = profiles([gps_xy(ln, 0.0) @ u for ln in L])
WIN = 5.0
edges = np.arange(A[0], A[-1] + 1e-9, WIN)
pts = []
for w0 in edges[:-1]:
    idx = np.flatnonzero((A >= w0) & (A < w0 + WIN))
    g["A"] = A[idx]
    C = g["shifts"](F[:, :, idx])
    g["A"] = A
    for k, ln in enumerate(L):
        sh, h = peak(C[k].sum(axis=0))
        def lspeed(j):
            ln2 = L[j]
            fa = np.column_stack([ln2["e"], ln2["n"]]) @ u
            d = np.hypot(np.diff(ln2["e"]), np.diff(ln2["n"])); dt = np.diff(ln2["t"])
            mid = 0.5 * (fa[1:] + fa[:-1])
            m = (dt == 1.0) & (mid >= w0) & (mid < w0 + WIN)
            return np.median(d[m]) if m.sum() >= 2 else np.nan
        nb = [j for j in (k - 1, k + 1) if 0 <= j < len(L)]
        x = lspeed(k) + np.nanmean([lspeed(j) for j in nb])
        if np.isfinite(x) and abs(sh) < 0.95:
            pts.append((x, sh, h))
pts = np.array(pts)
X, s, h = pts[:, 0], pts[:, 1], pts[:, 2]
n = len(s)
# robust-ish: drop the worst 5% residuals of the joint fit, refit
b, a = np.polyfit(X, s, 1)
r = s - (a + b * X)
keep = np.abs(r) < np.percentile(np.abs(r), 95)
b, a = np.polyfit(X[keep], s[keep], 1)
tau_only = -np.sum(s[keep] * X[keep]) / np.sum(X[keep] ** 2)
rss_lat = np.sum((s[keep] + tau_only * X[keep]) ** 2)
rss_off = np.sum((s[keep] - s[keep].mean()) ** 2)
rss_both = np.sum((s[keep] - (a + b * X[keep])) ** 2)
m = keep.sum()
print(f"{n} window-points, kept {m}; speed-sum range {X.min():.2f}-{X.max():.2f} m/s (per-line speed ~half)")
print(f"corr(shift, speed sum) = {np.corrcoef(X[keep], s[keep])[0,1]:.2f}")
for lab, rss, k in [("latency only", rss_lat, 1), ("offset only", rss_off, 1), ("both", rss_both, 2)]:
    print(f"  {lab:12s}: rms {np.sqrt(rss/m)*100:.1f} cm, BIC {m*np.log(rss/m)+k*np.log(m):.1f}")
print(f"  latency only: tau {tau_only:.3f} s | both: offset {-a/2*100:.1f} cm (GPS behind centre if +) + tau {-b:.3f} s")
# bootstrap the joint split
rng = np.random.default_rng(1)
bs = []
Xk, sk = X[keep], s[keep]
for _ in range(1000):
    i = rng.integers(0, m, m)
    bb, aa = np.polyfit(Xk[i], sk[i], 1)
    bs.append((-aa / 2, -bb))
bs = np.array(bs)
print(f"  bootstrap 95%: offset [{np.percentile(bs[:,0],2.5)*100:.1f}, {np.percentile(bs[:,0],97.5)*100:.1f}] cm, tau [{np.percentile(bs[:,1],2.5):.3f}, {np.percentile(bs[:,1],97.5):.3f}] s")
# binned view
qs = np.percentile(Xk, [0, 20, 40, 60, 80, 100])
for lo, hi in zip(qs[:-1], qs[1:]):
    mm = (Xk >= lo) & (Xk <= hi)
    print(f"   speed sum {lo:.2f}-{hi:.2f}: median shift {np.median(sk[mm])*100:+.1f} cm (n={mm.sum()}) -> one-way {-np.median(sk[mm])/2*100:.1f} cm at ~{(lo+hi)/4:.2f} m/s")
