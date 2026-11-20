"""Plot the spike slices (system python with matplotlib)."""

import sys

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

z = np.load(sys.argv[1])
out_dir = sys.argv[2]
ext = z["extent"]
x0, y0 = ext[0], ext[2]
extent = [0, ext[1] - x0, 0, ext[3] - y0]
W = z["windows"]
cols = [("tape", "Tape grid (wheel, 0.5 m lines)"), ("gps_raw", "GPS as logged"),
        ("gps_corr", f"GPS corrected ({z['offset']*100:.0f} cm + {z['tau']:.2f} s)")]
ann, lab = z["ann"], z["ann_lab"]


def panel(ax, img, lim, key, xlim=None, ylim=None, marks=True):
    ax.imshow(img, origin="lower", extent=extent, cmap="gray", vmin=lim[0], vmax=lim[1], interpolation="nearest")
    if marks:
        for (a, c), l in zip(ann, lab):
            if l.startswith(key + "|"):
                ax.plot(c - x0, a - y0, "o", ms=5, mfc="none", mec="red", mew=1)
        # FILE__011 is line index 10
        lc = z["line_c"][[k for k, _ in cols].index(key)][10] - x0
        ax.annotate("FILE__011", xy=(lc, extent[3] - 0.3), xytext=(lc + 1.5, extent[3] + 0.8), color="tab:orange",
                    fontsize=7, arrowprops=dict(arrowstyle="-", color="tab:orange", lw=0.8), annotation_clip=False)
    if xlim:
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=7)


fig, axs = plt.subplots(len(W), 3, figsize=(13, 4.3 * len(W)))
for r, (lo, hi) in enumerate(W):
    stack = np.concatenate([z[k][r][np.isfinite(z[k][r])] for k, _ in cols])
    lim = np.percentile(stack, [1, 99.5])
    for cidx, (k, title) in enumerate(cols):
        panel(axs[r, cidx], z[k][r], lim, k)
        axs[r, cidx].set_title(f"{title}\n{lo}-{hi} ns", fontsize=9)
fig.suptitle("Same 60 lines, same cell (0.1 m), same kriging fill, same stretch per row. Local metres in the grid's frame "
             "(x across lines, y along). Red circles: user marks on FILE__016 / FILE__028.", fontsize=9)
fig.tight_layout(rect=[0, 0, 1, 0.985])
fig.savefig(f"{out_dir}/slices_tape_vs_gps.png", dpi=90)

# zoom: the strongest compact feature in the 22-28 ns window (GPS corrected), 8 m square
r = 1
img = z["gps_corr"][r].copy()
img[~np.isfinite(img)] = np.nan
ny, nx = img.shape
cell = (extent[1]) / nx
# smooth crude to find a blob away from the line ends
k = 9
pad = np.nan_to_num(img)
from numpy.lib.stride_tricks import sliding_window_view as swv  # noqa: E402

sm = swv(np.pad(pad, k // 2), (k, k)).mean(axis=(2, 3))
margin = int(2.5 / cell)
sm[:margin] = 0
sm[-margin:] = 0
iy, ix = np.unravel_index(np.argmax(sm), sm.shape)
cy, cx = (iy + 0.5) * cell, (ix + 0.5) * cell
half = 4.0
fig, axs = plt.subplots(2, 3, figsize=(13, 9))
for rr, r in enumerate((1, 2)):
    stack = np.concatenate([z[k][r][np.isfinite(z[k][r])] for k, _ in cols])
    lim = np.percentile(stack, [1, 99.5])
    for cidx, (k, title) in enumerate(cols):
        panel(axs[rr, cidx], z[k][r], lim, k, xlim=(cx - half, cx + half), ylim=(cy - half, cy + half), marks=False)
        axs[rr, cidx].set_title(f"{title}\n{W[r][0]}-{W[r][1]} ns (8 m zoom)", fontsize=9)
fig.suptitle("Zoom on the strongest compact feature: look for the comb / sawtooth between alternate lines", fontsize=9)
fig.tight_layout(rect=[0, 0, 1, 0.98])
fig.savefig(f"{out_dir}/slices_zoom.png", dpi=90)
print("zoom centre (local m):", round(cx, 1), round(cy, 1))
