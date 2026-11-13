"""Throwaway: measure in a box (along a0..a1, across c0..c1, t window), fitted or not, with/without per-line normalisation."""
import sys
import numpy as np
spike = {}
exec(open(sys.argv[0].replace("local_measure.py", "destagger_spike.py")).read().split("def main():")[0], spike)
cache, survey, gid = sys.argv[1:4]
sys.argv = ["x", cache, survey, gid]
lines, length = spike["lines_from_args"]()
envs, spm, t_bins = spike["prepare"](lines, cache)
spm = float(spm)
STEP = 0.02
lagsN = 50

def measure(fit, shift, t0, t1, a0, a1, c0, c1, norm, end_m=2.0):
    bins = np.flatnonzero((t_bins >= t0) & (t_bins < t1))
    A = np.arange(a0, a1, STEP)
    idx = [k for k in np.argsort([l["offset"] for l in lines], kind="stable") if c0 <= lines[k]["offset"] <= c1]
    gain = np.array([np.median(np.concatenate([envs[k][b] for k in range(len(lines))])) for b in bins])
    F = {}
    for k in idx:
        ln, e = lines[k], envs[k]
        kw = spike["fitted"](ln, e.shape[1], spm, length) if fit else {}
        a = spike["place"](ln, e.shape[1], spm, shift=shift, **kw)
        o = np.argsort(a)
        valid = (A >= a.min() + end_m) & (A <= a.max() - end_m)
        P = np.array([np.interp(A, a[o], e[b][o].astype(float) / g) for b, g in zip(bins, gain)])
        hp = int(round(3.0 / STEP))
        P = P - np.array([np.convolve(np.pad(p, hp // 2, mode="edge"), np.ones(hp) / hp, mode="valid")[: A.size] for p in P])
        P[:, ~valid] = 0
        if norm:
            sd = P[:, valid].std()
            P = P / sd if sd > 0 else P * 0
        F[k] = P
    curves = []
    for pos, k in enumerate(idx):
        nb = [idx[q] for q in (pos - 1, pos + 1) if 0 <= q < len(idx) and lines[idx[q]]["direction"] != lines[k]["direction"]]
        if not nb:
            continue
        G = np.mean([F[j] for j in nb], axis=0)
        c = np.array([[(F[k][b, max(0, m):A.size + min(0, m)] * G[b, max(0, -m):A.size - max(0, m)]).sum() for m in range(-lagsN, lagsN + 1)] for b in range(len(bins))])
        curves.append(c[:, ::-1] if lines[k]["direction"] < 0 else c)
    s, h = spike["peak"](np.array(curves).sum(axis=1).mean(axis=0))
    return s, h

cases = [
    ("whole grid, all depths, normalised (spike)", (4, 70, 0, length, 0, 30, True)),
    ("whole grid, all depths, raw amplitude", (4, 70, 0, length, 0, 30, False)),
    ("whole grid, 14.9-19.7, normalised", (14.9, 19.7, 0, length, 0, 30, True)),
    ("whole grid, 14.9-19.7, raw amplitude", (14.9, 19.7, 0, length, 0, 30, False)),
    ("blob box 21-28 x 21.5-25, 14.9-19.7", (14.9, 19.7, 21, 28, 21.5, 25, False)),
    ("blob box 21-28 x 21.5-25, 4-70", (4, 70, 21, 28, 21.5, 25, False)),
    ("middle 5-25 m only, all depths, normalised", (4, 70, 5, 25, 0, 30, True)),
]
for fit in (False, True):
    print("FITTED" if fit else "UNFITTED")
    for lab, (t0, t1, a0, a1, c0, c1, norm) in cases:
        s, h = measure(fit, 0.0, t0, t1, a0, a1, c0, c1, norm)
        print(f"  {lab:46s} neighbour shift {s*100:+6.1f} cm => destagger {-s/2:+.3f} m")
