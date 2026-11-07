"""Throwaway recon: fit a grid to the 60 GPS tracks; how far does a grid placement put traces from GPS?"""

import math
import sys
from pathlib import Path

import numpy as np

from nsgeo.io.dzt import read_header, trace_count

D = Path(sys.argv[1])
R = 6371000.0


def dm(v, h):
    d = int(float(v) / 100)
    x = d + (float(v) - d * 100) / 60
    return -x if h in "SW" else x


tracks = []
for dzg in sorted(D.glob("*.DZG")):
    dzt = dzg.with_suffix(".DZT")
    h = read_header(dzt)
    n = trace_count(dzt, h)
    scans, lat, lon, tim = [], [], [], []
    cur = None
    for ln in dzg.read_text().splitlines():
        f = ln.strip().split(",")
        if f[0] == "$GSSIS":
            cur = int(f[1])
        elif f[0].endswith("GGA"):
            scans.append(cur)
            lat.append(dm(f[2], f[3]))
            lon.append(dm(f[4], f[5]))
            t = f[1]
            tim.append(int(t[:2]) * 3600 + int(t[2:4]) * 60 + float(t[4:]))
    tracks.append((dzg.stem, n, h.traces_per_metre, np.array(scans), np.array(lat), np.array(lon), np.array(tim)))

lat0, lon0 = tracks[0][4][0], tracks[0][5][0]
k = math.cos(math.radians(lat0))


def en(lat, lon):
    return np.column_stack([(lon - lon0) * math.pi / 180 * R * k, (lat - lat0) * math.pi / 180 * R])


# per-trace positions by linear interpolation in scan; linear extrapolation outside the fixes
per_trace = []
for name, n, spm, sc, la, lo, ti in tracks:
    p = en(la, lo)
    idx = np.arange(n)
    x = np.interp(idx, sc, p[:, 0])
    y = np.interp(idx, sc, p[:, 1])
    per_trace.append((name, n, spm, idx, np.column_stack([x, y]), sc, p, ti))

# grid axis: mean direction of all lines (southbound flipped)
dirs = []
for name, n, spm, idx, xy, sc, p, ti in per_trace:
    d = p[-1] - p[0]
    d /= np.linalg.norm(d)
    if d[1] < 0:
        d = -d
    dirs.append(d)
u = np.mean(dirs, axis=0)
u /= np.linalg.norm(u)  # along (northward)
v = np.array([u[1], -u[0]])  # cross (eastward-ish)
print(f"along axis bearing {math.degrees(math.atan2(u[0], u[1])):.2f} deg; per-line bearings spread "
      f"{np.ptp([math.degrees(math.atan2(d[0], d[1])) for d in dirs]):.2f} deg")

cross_mean, starts_along, ends_along = [], [], []
for name, n, spm, idx, xy, sc, p, ti in per_trace:
    c = xy @ v
    a = xy @ u
    cross_mean.append(c.mean())
    starts_along.append(a[0])
    ends_along.append(a[-1])
cross_mean = np.array(cross_mean)
i = np.arange(len(per_trace))
A = np.column_stack([np.ones_like(i), i])
coef, *_ = np.linalg.lstsq(A, cross_mean, rcond=None)
resid = cross_mean - A @ coef
print(f"line spacing from GPS: {coef[1]:.4f} m/line; mean-position residual from even spacing: "
      f"rms {resid.std():.3f} m, max {np.abs(resid).max():.3f} m")
print("residual per line (m):", " ".join(f"{r:+.2f}" for r in resid))

# within-line cross-track wander about each line's own mean
wander = []
for (name, n, spm, idx, xy, sc, p, ti), cm in zip(per_trace, cross_mean):
    wander.append(np.abs(xy @ v - cm).max())
print(f"within-line wander (max |cross - line mean|): median {np.median(wander):.2f} m, max {np.max(wander):.2f} m")

# the full error of a nominal grid placement: cross = fitted offset, along = start edge + trace/spm*direction
sa = np.array(starts_along)
ea = np.array(ends_along)
south = sa > ea
north_edge = np.median(np.where(south, sa, ea))
south_edge = np.median(np.where(south, ea, sa))
print(f"north edge {north_edge:.2f}, south edge {south_edge:.2f}, grid length {north_edge - south_edge:.2f} m")
print("start stagger (start along minus its edge), m:")
print("  southbound:", " ".join(f"{s - north_edge:+.2f}" for s, so in zip(sa, south) if so))
print("  northbound:", " ".join(f"{s - south_edge:+.2f}" for s, so in zip(sa, south) if not so))

errs = []
for k_, ((name, n, spm, idx, xy, sc, p, ti), so) in enumerate(zip(per_trace, south)):
    if so:
        along = north_edge - idx / spm
    else:
        along = south_edge + idx / spm
    cross = coef[0] + coef[1] * k_
    nominal = np.outer(along, u) + np.outer(np.full(n, cross), v)
    e = np.linalg.norm(nominal - xy, axis=1)
    errs.append(e)
allerr = np.concatenate(errs)
print(f"nominal grid placement vs GPS, every trace: median {np.median(allerr):.2f} m, p95 {np.percentile(allerr, 95):.2f} m, max {allerr.max():.2f} m")
worst = sorted(((e.max(), t[0]) for e, t in zip(errs, per_trace)), reverse=True)[:6]
print("worst lines:", ", ".join(f"{nm} {m:.2f} m" for m, nm in worst))

# wheel scale vs GPS along-track distance
ratios = []
for name, n, spm, idx, xy, sc, p, ti in per_trace:
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1).sum()
    ratios.append(seg / ((sc[-1] - sc[0]) / spm))
print(f"GPS path / wheel distance over the fixed span: median {np.median(ratios):.4f}, range {min(ratios):.4f}-{max(ratios):.4f}")

# speed and fix spacing
sp = []
gap = []
for name, n, spm, idx, xy, sc, p, ti in per_trace:
    d = np.linalg.norm(np.diff(p, axis=0), axis=1)
    dt = np.diff(ti)
    sp.extend(d[dt == 1])
    gap.extend(np.diff(sc) / spm)
print(f"walking speed (1 s fixes): median {np.median(sp):.2f} m/s; distance between fixes median {np.median(gap):.2f} m, p95 {np.percentile(gap, 95):.2f} m, max {max(gap):.2f} m")
print(f"first fix at scan: median {np.median([t[3][0] for t in tracks])}, max {max(t[3][0] for t in tracks)} ({max(t[3][0] for t in tracks)/60:.2f} m)")

# --- decomposition: cross vs along error, and how much a skewed baseline explains
print("\n--- decomposition ---")
cross_err, along_err, along_err_deskew, wander_err, scale_err = [], [], [], [], []
st = np.array([s - (north_edge if so else south_edge) for s, so in zip(sa, south)])
sk = np.polyfit(i, st, 1)  # linear trend of start stagger with line index
print(f"start stagger trend: {sk[0]*len(i):+.2f} m across the grid = {math.degrees(math.atan2(sk[0], abs(coef[1]))):.2f} deg skew; "
      f"residual stagger rms {np.std(st - np.polyval(sk, i)):.2f} m, max {np.abs(st - np.polyval(sk, i)).max():.2f} m")
for k_, ((name, n, spm, idx, xy, sc, p, ti), so) in enumerate(zip(per_trace, south)):
    edge = north_edge if so else south_edge
    sgn = -1 if so else 1
    along_nom = edge + sgn * idx / spm
    along_gps = xy @ u
    cross_nom = coef[0] + coef[1] * k_
    cross_gps = xy @ v
    cross_err.append(np.abs(cross_gps - cross_nom))
    along_err.append(np.abs(along_gps - along_nom))
    along_nom2 = edge + np.polyval(sk, k_) + sgn * idx / spm
    along_err_deskew.append(np.abs(along_gps - along_nom2))
    # scale only: start pinned at the GPS start, wheel distance
    along_nom3 = along_gps[0] + sgn * idx / spm
    scale_err.append(np.abs(along_gps - along_nom3))
for lab, arr in [("cross-line (offset + wander)", cross_err), ("along-line, square grid", along_err),
                 ("along-line, skewed baseline allowed", along_err_deskew), ("along-line, start pinned (wheel scale/slip only)", scale_err)]:
    a = np.concatenate(arr)
    print(f"{lab:48s} median {np.median(a):.2f}  p95 {np.percentile(a, 95):.2f}  max {a.max():.2f}")
print(f"grid edge to first line centre (cross): fitted intercept is free, so a constant 0.25 m offset is absorbed; "
      f"outer lines at {coef[0]:.2f} and {coef[0]+coef[1]*(len(i)-1):.2f} m on the cross axis")
