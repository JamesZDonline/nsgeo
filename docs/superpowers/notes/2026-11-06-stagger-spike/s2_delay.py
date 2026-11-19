"""Spike stage 2: estimate the GPS-to-trace delay from opposite-direction neighbours."""

import sys

import numpy as np

sys.path.insert(0, sys.argv[2])
from common import fit_frame, gps_xy, load, tape_frame, tape_uv  # noqa: E402

L, t_bins, spm = load(sys.argv[1])
u, v, south = fit_frame(L)
tf = tape_frame(L, u, v, south, spm)
dirn = np.where(south, -1.0, 1.0)  # travel direction along u
speeds = []
for ln in L:
    d = np.hypot(np.diff(ln["e"]), np.diff(ln["n"]))
    dt = np.diff(ln["t"])
    speeds.extend(d[dt == 1.0])
v_med = float(np.median(speeds))

STEP = 0.02
starts_a = [gps_xy(ln).dot(u) for ln in L]
a_lo = max(min(s.min() for s in starts_a), -1e9) + 0.0
grid_lo = np.median([min(s.min(), s.max()) for s in starts_a]) + 2.0
grid_hi = np.median([max(s.min(), s.max()) for s in starts_a]) - 2.0
A = np.arange(grid_lo, grid_hi, STEP)
HP = int(round(3.0 / STEP))  # 3 m running-mean high-pass
LP = int(round(0.15 / STEP)) | 1
bins_all = np.flatnonzero((t_bins > 4) & (t_bins < 70))
MAXLAG = int(round(1.0 / STEP))


GAIN = None


def profiles(along_per_line):
    """(lines, bins, A): envelope / global per-bin median (time gain), 0.15 m low-pass,
    3 m high-pass along track; each line normalised jointly over all bins (2-D patch)."""
    global GAIN
    if GAIN is None:
        GAIN = np.array([np.median(np.concatenate([ln["env"][b] for ln in L])) for b in bins_all])
    out = np.zeros((len(L), len(bins_all), A.size))
    ker = np.ones(HP) / HP
    lp = np.ones(LP) / LP
    for k, (ln, a) in enumerate(zip(L, along_per_line)):
        o = np.argsort(a, kind="stable")
        for j, b in enumerate(bins_all):
            f = np.interp(A, a[o], ln["env"][b][o].astype(float) / GAIN[j])
            f = np.convolve(np.pad(f, LP // 2, mode="edge"), lp, mode="valid")[: A.size]
            f = f - np.convolve(np.pad(f, HP // 2, mode="edge"), ker, mode="valid")[: A.size]
            out[k, j] = f
        sd = out[k].std()
        out[k] = (out[k] - out[k].mean(axis=1, keepdims=True)) / sd if sd > 0 else 0
    return out


def shifts(F):
    """Per line, per bin: correlation curve of line k against the mean of its neighbours,
    expressed as shift of line k IN ITS DIRECTION OF TRAVEL (metres)."""
    nl = F.shape[0]
    nfft = 1 << int(np.ceil(np.log2(2 * A.size)))
    curves = np.zeros((nl, F.shape[1], 2 * MAXLAG + 1))
    for k in range(nl):
        nb = [j for j in (k - 1, k + 1) if 0 <= j < nl]
        G = np.mean([F[j] for j in nb], axis=0)
        X = np.fft.irfft(np.fft.rfft(F[k], nfft) * np.conj(np.fft.rfft(G, nfft)), nfft)
        # X[m] = sum f[n+m] g[n]: f shifted by +m*STEP relative to g
        c = np.concatenate([X[:, -MAXLAG:], X[:, : MAXLAG + 1]], axis=1) / A.size
        if dirn[k] < 0:
            c = c[:, ::-1]
        curves[k] = c
    return curves


lags = np.arange(-MAXLAG, MAXLAG + 1) * STEP


def peak(c):
    i = int(np.argmax(c))
    y1 = c[i]
    if 0 < i < c.size - 1:
        y0, y1, y2 = c[i - 1], c[i], c[i + 1]
        den = y0 - 2 * y1 + y2
        off = 0.5 * (y0 - y2) / den if den != 0 else 0.0
        return lags[i] + off * STEP, y1
    return lags[i], y1


# per-bin coherence at tau=0 to see where features are
F0 = profiles([gps_xy(ln).dot(u) for ln in L])
C0 = shifts(F0)
coh = C0[:, :, MAXLAG].mean(axis=0)
far = []
for k in range(len(L) - 10):
    far.append((F0[k] * F0[k + 10]).sum() / A.size)
near = [(F0[k] * F0[k + 1]).sum() / A.size for k in range(len(L) - 1)]
near2 = [(F0[k] * F0[k + 2]).sum() / A.size for k in range(len(L) - 2)]
print(f"zero-lag patch corr: neighbours k,k+1 {np.mean(near):.3f}; same-direction k,k+2 {np.mean(near2):.3f}; far k,k+10 {np.mean(far):.3f}")
print(f"walking speed median {v_med:.3f} m/s")
print("time bin (ns) : neighbour correlation at zero lag, tau=0")
print(" ".join(f"{t_bins[b]:.0f}:{c:.2f}" for b, c in zip(bins_all, coh)))

WINDOWS = [(4, 15), (15, 25), (25, 40), (40, 70)]


def est_shift(curves, sel_lines=None, sel_bins=None):
    c = curves
    if sel_lines is not None:
        c = c[sel_lines]
    if sel_bins is not None:
        c = c[:, sel_bins]
    return peak(c.sum(axis=1).mean(axis=0))


taus = np.round(np.arange(-0.5, 1.0001, 0.05), 3)
res = []
curves_by_tau = {}
for tau in taus:
    F = profiles([gps_xy(ln, tau).dot(u) for ln in L])
    C = shifts(F)
    curves_by_tau[tau] = C
    s, h = est_shift(C)
    res.append((tau, s, h))
print("\ntau sweep: tau(s)  shift-in-travel-direction vs neighbours (cm)  peak corr")
for tau, s, h in res:
    print(f"  {tau:+.2f}  {s*100:+6.2f}  {h:.3f}")
ts = np.array([r[0] for r in res])
ss = np.array([r[1] for r in res])
hs = np.array([r[2] for r in res])
# zero crossing of the shift
i = np.flatnonzero(np.diff(np.sign(ss)) != 0)
tau_zero = None
if i.size:
    j = i[0]
    tau_zero = ts[j] - ss[j] * (ts[j + 1] - ts[j]) / (ss[j + 1] - ss[j])
tau_peak = ts[int(np.argmax(hs))]
print(f"\nshift crosses zero at tau = {tau_zero}; max zero... peak corr at tau = {tau_peak}")
s0 = res[int(np.flatnonzero(ts == 0)[0])][1]
print(f"at tau=0: shift {s0*100:+.2f} cm => tau ~ {-s0/(2*v_med):+.3f} s (one-way {abs(s0)/2*100:.1f} cm)")

# uncertainty: per window, halves, bootstrap over lines -- all from the tau=0 curves (shift -> tau via 2v)
C = curves_by_tau[0.0]
print("\nper time window (tau=0 curves): shift cm -> tau s")
for lo, hi in WINDOWS:
    sel = np.flatnonzero((t_bins[bins_all] >= lo) & (t_bins[bins_all] < hi))
    s, h = est_shift(C, sel_bins=sel)
    print(f"  {lo:>2}-{hi:<2} ns: {s*100:+6.2f} cm  tau {-s/(2*v_med):+.3f} s  (peak corr {h:.3f})")
for lab, sel in [("lines 1-30", np.arange(30)), ("lines 31-60", np.arange(30, 60)),
                 ("southbound only", np.flatnonzero(south)), ("northbound only", np.flatnonzero(~south))]:
    s, h = est_shift(C, sel_lines=sel)
    print(f"  {lab:16s}: {s*100:+6.2f} cm  tau {-s/(2*v_med):+.3f} s")
rng = np.random.default_rng(0)
boots = []
for _ in range(500):
    sel = rng.integers(0, len(L), len(L))
    boots.append(est_shift(C, sel_lines=sel)[0])
boots = np.array(boots)
print(f"  bootstrap over lines (500): shift {np.mean(boots)*100:+.2f} cm, 95% [{np.percentile(boots,2.5)*100:+.2f}, {np.percentile(boots,97.5)*100:+.2f}] cm"
      f" -> tau 95% [{-np.percentile(boots,97.5)/(2*v_med):+.3f}, {-np.percentile(boots,2.5)/(2*v_med):+.3f}] s")
per_line = np.array([peak(C[k].mean(axis=0))[0] for k in range(len(L))])
print(f"  per-line shifts: median {np.median(per_line)*100:+.2f} cm, IQR [{np.percentile(per_line,25)*100:+.2f}, {np.percentile(per_line,75)*100:+.2f}] cm")

# control: tape placement
Ft = profiles([tape_uv(L, i, south, tf)[0] for i in range(len(L))])
Ct = shifts(Ft)
s, h = est_shift(Ct)
per_line_t = np.array([peak(Ct[k].mean(axis=0))[0] for k in range(len(L))])
print(f"\nCONTROL tape placement: mean-curve shift {s*100:+.2f} cm (peak corr {h:.3f}); per-line shifts median {np.median(per_line_t)*100:+.2f} cm, "
      f"IQR [{np.percentile(per_line_t,25)*100:+.2f}, {np.percentile(per_line_t,75)*100:+.2f}], |shift| p90 {np.percentile(np.abs(per_line_t),90)*100:.1f} cm")
print(f"GPS tau=0 per-line |shift| p90 {np.percentile(np.abs(per_line),90)*100:.1f} cm; zero-lag corr GPS {C[:, :, MAXLAG].mean():.3f} vs tape {Ct[:, :, MAXLAG].mean():.3f}")
np.savez(sys.argv[3], taus=ts, shifts=ss, peaks=hs, per_line=per_line, per_line_tape=per_line_t, coh=coh, bins=bins_all)
