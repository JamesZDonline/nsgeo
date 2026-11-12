"""Throwaway: are per-line shifts real? Per-line residual (after grid-wide) from independent halves."""
import sys
import numpy as np
spike = {}
exec(open(sys.argv[0].replace("perline.py", "destagger_spike.py")).read().split("def main():")[0], spike)
cache, survey, gid = sys.argv[1:4]
sys.argv = ["x", cache, survey, gid]
lines, length = spike["lines_from_args"]()
envs, spm, t_bins = spike["prepare"](lines, cache)
spm = float(spm)
ntr = [e.shape[1] for e in envs]
order = list(np.argsort([l["offset"] for l in lines], kind="stable"))
dirs = [l["direction"] for l in lines]
peak = spike["peak"]
STEP = 0.02

def per_line(alongs, t0, t1, a0, a1):
    m = spike["Measure"](envs, t_bins, length, lo=t0, hi=t1)
    m.A = np.arange(a0, a1, STEP)
    F, _ = m.profiles(alongs)
    C = m.curves(F, order, dirs)
    out = np.full(len(lines), np.nan)
    sh = np.full(len(lines), np.nan)
    for k, c in C.items():
        s, h = peak(c.sum(axis=0))
        out[k], sh[k] = s, h
    grid = peak(np.array([C[k] for k in sorted(C)]).sum(axis=1).mean(axis=0))[0]
    return out, grid

for fit in (False, True):
    kw = [spike["fitted"](l, n, spm, length) if fit else {} for l, n in zip(lines, ntr)]
    base = [spike["place"](l, n, spm, **k) for l, n, k in zip(lines, ntr, kw)]
    _, g = per_line(base, 4, 70, 0, length)
    d = -g / 2
    al = [spike["place"](l, n, spm, shift=d, **k) for l, n, k in zip(lines, ntr, kw)]
    full, _ = per_line(al, 4, 70, 0, length)
    sh_, _ = per_line(al, 4, 25, 0, length)
    dp, _ = per_line(al, 25, 70, 0, length)
    h1, _ = per_line(al, 4, 70, 0, length / 2)
    h2, _ = per_line(al, 4, 70, length / 2, length)
    def r(a, b):
        ok = np.isfinite(a) & np.isfinite(b)
        return np.corrcoef(a[ok], b[ok])[0, 1], np.median(np.abs(a[ok] - b[ok])) * 100
    print(f"{gid} {'FITTED' if fit else 'UNFITTED'}: grid-wide destagger {d:+.3f} m; per-line residual vs neighbours: "
          f"IQR {np.nanpercentile(full,25)*100:+.1f}..{np.nanpercentile(full,75)*100:+.1f} cm, p90 |.| {np.nanpercentile(np.abs(full),90)*100:.1f} cm")
    rr, md = r(sh_, dp)
    print(f"   repeatability shallow(4-25) vs deep(25-70): r={rr:.2f}, median |diff| {md:.1f} cm")
    rr, md = r(h1, h2)
    print(f"   repeatability first half vs second half of the grid: r={rr:.2f}, median |diff| {md:.1f} cm")
    big = np.argsort(-np.abs(np.nan_to_num(full)))[:6]
    print("   largest per-line residuals (cm, line: full / shallow / deep / half1 / half2):")
    for k in big:
        print(f"     {lines[k]['path'].split('/')[-1][:-4]}: {full[k]*100:+.1f} / {sh_[k]*100:+.1f} / {dp[k]*100:+.1f} / {h1[k]*100:+.1f} / {h2[k]*100:+.1f}")
