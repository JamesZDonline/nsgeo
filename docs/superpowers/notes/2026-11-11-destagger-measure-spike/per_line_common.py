"""Throwaway (planning, 2026-11-11): shared helpers for per_line_block.py. Not run on its own."""
import sys, os
import numpy as np
S = os.path.dirname(os.path.abspath(__file__))
spike = {}
exec(open(os.path.join(S, "destagger_spike.py")).read().split("def main():")[0], spike)
cache, survey, gid = sys.argv[1:4]
extra = sys.argv[4:]
sys.argv = ["x", cache, survey, gid]
lines, length = spike["lines_from_args"]()
envs, spm, t_bins = spike["prepare"](lines, cache)
spm = float(spm)
ntr = [e.shape[1] for e in envs]
order = list(np.argsort([l["offset"] for l in lines], kind="stable"))
dirs = np.array([l["direction"] for l in lines])
names = [l["path"].split("/")[-1][:-4] for l in lines]
STEP = 0.02
inject = {}
skew = False
for e in extra:
    if e == "skew":
        skew = True
    else:
        k, d = e.split(":"); inject[int(k)] = float(d)

def clear_peak(c):
    """lag, clear?  clear = argmax not at edge and peak exceeds next local max by margin."""
    i = int(np.argmax(c))
    n = c.size
    lag, h = spike["peak"](c)
    if i == 0 or i == n - 1:
        return lag, False, 0.0
    # local maxima
    lm = [j for j in range(1, n - 1) if c[j] >= c[j - 1] and c[j] >= c[j + 1] and abs(j - i) > 5]
    second = max([c[j] for j in lm], default=c.min())
    lo = np.median(c)
    ratio = (c[i] - second) / (c[i] - lo) if c[i] > lo else 0.0
    return lag, ratio > 0.25, ratio

def curves(alongs, t0, t1, a0, a1):
    m = spike["Measure"](envs, t_bins, length, lo=t0, hi=t1)
    m.A = np.arange(a0, a1, STEP)
    F, _ = m.profiles(alongs)
    return m.curves(F, order, list(dirs))

def placements(fit, d, x_own):
    out = []
    for i, (l, n) in enumerate(zip(lines, ntr)):
        kw = spike["fitted"](l, n, spm, length) if fit else {}
        a = spike["place"](l, n, spm, shift=d - x_own[i], **kw)
        a = a + l["direction"] * inject.get(i, 0.0)  # injected error: moved d along its travel
        if skew:
            a = a + 0.02 * order.index(i)
        out.append(a)
    return out

def matrix():
    n = len(lines)
    A = np.zeros((n, n))
    has = np.zeros(n, bool)
    for pos, k in enumerate(order):
        nb = [order[q] for q in (pos - 1, pos + 1) if 0 <= q < n and dirs[order[q]] != dirs[k]]
        if not nb:
            continue
        has[k] = True
        A[k, k] = 1
        for j in nb:
            A[k, j] = -1 / len(nb)
    return A, has

