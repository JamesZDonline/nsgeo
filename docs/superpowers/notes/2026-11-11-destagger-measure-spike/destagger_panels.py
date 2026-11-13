"""Throwaway: line-strip slices (each line one 0.5 m strip) at a time window, for several placements.

usage: destagger_panels.py <cache.npz> <survey.json> <grid_id> <t_lo> <t_hi> <out.png> <label:fit:shift> ...
  fit = 0|1 (fit to grid edges), shift = destagger metres
"""

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.argv = [sys.argv[0], *sys.argv[1:]]
spike = {}
exec(open(sys.argv[0].replace("destagger_panels.py", "destagger_spike.py")).read().split("def main():")[0], spike)

cache, survey, gid, t_lo, t_hi, out = sys.argv[1:7]
specs = [s.split(":") for s in sys.argv[7:]]
sys.argv = ["x", cache, survey, gid]
lines, length = spike["lines_from_args"]()
envs, spm, t_bins = spike["prepare"](lines, cache)
spm = float(spm)
sel = np.flatnonzero((t_bins >= float(t_lo)) & (t_bins < float(t_hi)))
order = np.argsort([ln["offset"] for ln in lines], kind="stable")
PX = 0.05
A = np.arange(0, length, PX)
ncol = 3
nrow = -(-len(specs) // ncol)
fig, axes = plt.subplots(nrow, ncol, figsize=(5.2 * ncol, 5.4 * nrow), squeeze=False)
for ax, (label, fit, shift) in zip(axes.ravel(), specs):
    img = np.full((len(lines), A.size), np.nan)
    for row, k in enumerate(order):
        ln, e = lines[k], envs[k]
        kw = spike["fitted"](ln, e.shape[1], spm, length) if fit == "1" else {}
        a = spike["place"](ln, e.shape[1], spm, shift=float(shift), **kw)
        v = e[sel].astype(float).mean(axis=0)
        o = np.argsort(a)
        prof = np.interp(A, a[o], v[o], left=np.nan, right=np.nan)
        img[row] = prof
    lim = np.nanpercentile(img, 99.5)
    # along axis horizontal, lines stacked vertically, 0.5 m per strip
    ax.imshow(img, aspect=PX / 0.5 * 0.5 / PX * (0.5 / PX) / 10, cmap="gray_r", vmin=0, vmax=lim,
              extent=(0, length, len(lines) * 0.5, 0), interpolation="nearest")
    ax.set_title(f"{label}\nfit={'yes' if fit == '1' else 'no'}, destagger {float(shift):+.3f} m", fontsize=9)
    ax.set_xlabel("along line (m)")
    ax.set_ylabel("across (m)")
    ax.set_aspect("equal")
    import os
    if os.environ.get("CROP"):
        a0, a1, c0, c1 = map(float, os.environ["CROP"].split(","))
        ax.set_xlim(a0, a1)
        ax.set_ylim(c1, c0)
fig.suptitle(f"{gid}, {t_lo}-{t_hi} ns, dewow + background removal + envelope", fontsize=10)
fig.tight_layout()
fig.savefig(out, dpi=110)
print("wrote", out)
