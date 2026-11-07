"""Independent check of the spike's claim, written separately from it.

Idea: a small buried object sits at one place. Every line that crosses it should see its
strongest echo at the same position along the grid. If GPS positions lag the radar, lines
walked north see it too far south and lines walked south see it too far north.
So: find compact bright features, and for each line that crosses one, find where along
the grid its echo peaks. Compare the north-going lines' peaks with the south-going lines'.
"""

import math
import sys
from pathlib import Path

import numpy as np

from nsgeo.io.dzt import read_header, read_samples
from nsgeo.processing.amplitude import analytic_envelope
from nsgeo.processing.base import Radargram, build_step

D = Path(sys.argv[1])
R = 6371000.0
WINDOWS = [(15, 20), (22, 28), (30, 40)]


def dm(v, h):
    d = int(float(v) / 100)
    x = d + (float(v) - d * 100) / 60
    return -x if h in "SW" else x


dewow = build_step("dewow", window_ns=4.0)
bg = build_step("background_mean")
lines = []
for dzg in sorted(D.glob("*.DZG")):
    dzt = dzg.with_suffix(".DZT")
    h = read_header(dzt)
    data = read_samples(dzt, h)[0].astype(float)
    rg = bg.apply(dewow.apply(Radargram(data=data, dt_ns=h.dt_ns, t0_ns=h.position_ns, dx_m=1 / 60)))
    env = analytic_envelope(rg.data)
    t = h.position_ns + np.arange(h.n_samples) * h.dt_ns
    win = {w: env[(t >= w[0]) & (t < w[1])].mean(axis=0) for w in WINDOWS}
    sc, la, lo = [], [], []
    cur = None
    for ln in dzg.read_text().splitlines():
        f = ln.strip().split(",")
        if f[0] == "$GSSIS":
            cur = int(f[1])
        elif f[0].endswith("GGA"):
            sc.append(cur)
            la.append(dm(f[2], f[3]))
            lo.append(dm(f[4], f[5]))
    lines.append((dzg.stem, np.array(sc), np.array(la), np.array(lo), win, data.shape[1]))

lat0, lon0 = lines[0][2][0], lines[0][3][0]
k = math.cos(math.radians(lat0))
placed = []
for name, sc, la, lo, win, n in lines:
    e = (lo - lon0) * math.pi / 180 * R * k
    nn = (la - lat0) * math.pi / 180 * R
    idx = np.arange(n)
    # only traces between the first and last fix: no extrapolation in this check
    ok = (idx >= sc[0]) & (idx <= sc[-1])
    xy = np.column_stack([np.interp(idx, sc, e), np.interp(idx, sc, nn)])
    placed.append((name, xy, ok, win))

# grid axes from the tracks
dirs = []
for name, xy, ok, win in placed:
    d = xy[ok][-1] - xy[ok][0]
    d /= np.linalg.norm(d)
    dirs.append(d if d[1] > 0 else -d)
u_hat = np.mean(dirs, axis=0)
u_hat /= np.linalg.norm(u_hat)
v_hat = np.array([u_hat[1], -u_hat[0]])

rows = []
for li, (name, xy, ok, win) in enumerate(placed):
    u = xy @ u_hat
    north = (u[ok][-1] - u[ok][0]) > 0
    rows.append((name, u, ok, win, north))

DU = 0.1
u_all = np.concatenate([r[1][r[2]] for r in rows])
edges = np.arange(u_all.min(), u_all.max() + DU, DU)
for w in WINDOWS:
    img = np.full((len(rows), len(edges) - 1), np.nan)
    for li, (name, u, ok, win, north) in enumerate(rows):
        val = np.convolve(win[w], np.ones(7) / 7, mode="same")
        b = np.digitize(u[ok], edges) - 1
        good = (b >= 0) & (b < img.shape[1])
        s = np.bincount(b[good], weights=val[ok][good], minlength=img.shape[1])
        c = np.bincount(b[good], minlength=img.shape[1])
        with np.errstate(invalid="ignore"):
            img[li] = np.where(c > 0, s / c, np.nan)
    # stay 2.5 m inside the ends (both ends are bright on every line)
    inner = (edges[:-1] > u_all.min() + 2.5) & (edges[:-1] < u_all.max() - 2.5)
    work = np.where(inner[None, :], img, np.nan)
    print(f"\n=== window {w[0]}-{w[1]} ns ===")
    used = np.zeros_like(work, dtype=bool)
    found = 0
    while found < 5:
        flat = np.where(used, np.nan, work)
        if np.all(np.isnan(flat)):
            break
        li0, bi0 = np.unravel_index(np.nanargmax(flat), flat.shape)
        u0 = edges[bi0]
        # block this neighbourhood for later picks
        used[max(0, li0 - 4): li0 + 5, max(0, bi0 - 25): bi0 + 26] = True
        peaks_n, peaks_s = [], []
        for lj in range(max(0, li0 - 3), min(len(rows), li0 + 4)):
            name, u, ok, win, north = rows[lj]
            seg = ok & (np.abs(u - u0) < 1.5)
            if seg.sum() < 30:
                continue
            val = np.convolve(win[w], np.ones(7) / 7, mode="same")
            vv = np.where(seg, val, -np.inf)
            i = int(np.argmax(vv))
            # a compact feature: the peak must stand well above the line's local median
            if vv[i] < 3 * np.median(val[seg]):
                continue
            (peaks_n if north else peaks_s).append(u[i])
        if len(peaks_n) >= 2 and len(peaks_s) >= 2:
            found += 1
            dn, ds = np.mean(peaks_n), np.mean(peaks_s)
            print(f"feature at line {rows[li0][0]}, {u0 - u_all.min():5.1f} m along: "
                  f"north-going peaks {np.round(np.array(peaks_n) - u0, 2)}  "
                  f"south-going peaks {np.round(np.array(peaks_s) - u0, 2)}  "
                  f"south minus north = {ds - dn:+.2f} m")
