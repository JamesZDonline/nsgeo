"""Throwaway: measure in a box (along a0..a1, across c0..c1, t window), fitted or not, with/without per-line normalisation."""
import sys
import numpy as np
spike = {}
exec(open(sys.argv[0].replace("grid_measure.py", "destagger_spike.py")).read().split("def main():")[0], spike)
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


import itertools
L=length
segs=[(2,10),(10,20),(20,L-2)]
wins=[(4,15),(15,25),(25,40),(40,70)]
for fit in (False, True):
    print(gid, "FITTED" if fit else "UNFITTED", " rows: depth window, cols: along-line third (m)")
    print("            " + "".join(f"{a0:>4.0f}-{a1:<4.0f}  " for a0,a1 in segs) + "  all")
    for t0,t1 in wins+[(4,70)]:
        row=[]
        for a0,a1 in segs+[(0,L)]:
            s_,h=measure(fit,0.0,t0,t1,a0,a1,0,30,True,end_m=0.0 if (a0,a1)!=(0,L) else 2.0)
            row.append(-s_/2)
        print(f"  {t0:>3}-{t1:<3} ns " + "".join(f"{v:+.3f}    " for v in row))
