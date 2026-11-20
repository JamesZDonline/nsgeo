"""Throwaway recon: how do the with-dzg DZT/DZG/DZX files fit together?"""

import collections
import math
import sys
from pathlib import Path

import numpy as np

from nsgeo.io.dzt import read_header, trace_count
from nsgeo.io.dzx import read_dzx

D = Path(sys.argv[1])


def nmea_ok(line):
    if "*" not in line:
        return None
    body, cs = line[1:].split("*", 1)
    c = 0
    for ch in body:
        c ^= ord(ch)
    try:
        return c == int(cs.strip()[:2], 16)
    except ValueError:
        return None


def dm(v, h):
    d = int(float(v) / 100)
    m = float(v) - d * 100
    x = d + m / 60
    return -x if h in "SW" else x


sentence_kinds = collections.Counter()
quality_all = collections.Counter()
rows = []
for dzg in sorted(D.glob("*.DZG")):
    dzt = dzg.with_suffix(".DZT")
    h = read_header(dzt)
    n = trace_count(dzt, h)
    info = read_dzx(dzg.with_suffix(".DZX"))
    lines = dzg.read_text(errors="replace").splitlines()
    pairs = []  # (scan, gssis_field2, gga_fields)
    cur = None
    bad_cs = 0
    order = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        kind = ln.split(",", 1)[0]
        sentence_kinds[kind] += 1
        order.append(kind)
        if nmea_ok(ln) is False:
            bad_cs += 1
        f = ln.split(",")
        if kind == "$GSSIS":
            cur = (int(f[1]), f[2])
        elif kind.endswith("GGA"):
            pairs.append((cur, f))
            cur = None
    scans = np.array([p[0][0] for p in pairs if p[0]])
    g2 = collections.Counter(p[0][1] for p in pairs if p[0])
    q = collections.Counter(p[1][6] for p in pairs)
    quality_all.update(q)
    times = []
    for _, f in pairs:
        t = f[1]
        times.append(int(t[0:2]) * 3600 + int(t[2:4]) * 60 + float(t[4:]))
    times = np.array(times)
    lat = np.array([dm(f[2], f[3]) for _, f in pairs])
    lon = np.array([dm(f[4], f[5]) for _, f in pairs])
    alt = np.array([float(f[9]) for _, f in pairs])
    hdop = np.array([float(f[8]) for _, f in pairs])
    # local metres (equirectangular, fine over 100 m)
    R = 6371000.0
    y = (lat - lat[0]) * math.pi / 180 * R
    x = (lon - lon[0]) * math.pi / 180 * R * math.cos(math.radians(lat[0]))
    seg = np.hypot(np.diff(x), np.diff(y))
    path = seg.sum()
    chord = math.hypot(x[-1] - x[0], y[-1] - y[0])
    wheel = n / h.traces_per_metre if h.traces_per_metre > 0 else float("nan")
    heading = math.degrees(math.atan2(x[-1] - x[0], y[-1] - y[0])) % 360
    # straightness: max perpendicular deviation from chord
    if chord > 0:
        ux, uy = (x[-1] - x[0]) / chord, (y[-1] - y[0]) / chord
        perp = np.abs((x - x[0]) * uy - (y - y[0]) * ux)
        dev = perp.max()
    else:
        dev = float("nan")
    marks = [m.scan for m in info.marks] if info and getattr(info, "marks", None) else []
    rows.append(
        dict(
            name=dzg.stem,
            n=n,
            spm=h.traces_per_metre,
            nfix=len(pairs),
            first_scan=int(scans.min()) if scans.size else None,
            last_scan=int(scans.max()) if scans.size else None,
            mono=bool(np.all(np.diff(scans) >= 0)) if scans.size else None,
            dscan=np.median(np.diff(scans)) if scans.size > 1 else None,
            dt=np.median(np.diff(times)) if times.size > 1 else None,
            dt_max=np.diff(times).max() if times.size > 1 else None,
            q=dict(q),
            g2=dict(g2),
            bad_cs=bad_cs,
            path=path,
            chord=chord,
            wheel=wheel,
            heading=heading,
            dev=dev,
            alt=(alt.min(), alt.max()),
            hdop=(hdop.min(), hdop.max()),
            t0=times[0],
            t1=times[-1],
            x0=x[0],
            lat0=lat[0],
            lon0=lon[0],
            latN=lat[-1],
            lonN=lon[-1],
            marks=marks,
            order_head=order[:4],
            dup_scan=int((np.diff(scans) == 0).sum()) if scans.size > 1 else 0,
        )
    )

print("sentence kinds:", dict(sentence_kinds))
print("fix quality over all files:", dict(quality_all))
print()
hdr = "name        n   spm nfix  scan0 scanN mono dscan  dt  dtmax  path  chord wheel  hdg  dev  q"
print(hdr)
for r in rows:
    print(
        f"{r['name']:10s} {r['n']:5d} {r['spm']:4.0f} {r['nfix']:4d} {r['first_scan']:5d} {r['last_scan']:5d} "
        f"{'Y' if r['mono'] else 'N':>4s} {r['dscan']:5.0f} {r['dt']:4.1f} {r['dt_max']:5.1f} "
        f"{r['path']:5.1f} {r['chord']:5.1f} {r['wheel']:5.1f} {r['heading']:5.0f} {r['dev']:4.2f} {r['q']} g2={r['g2']} cs={r['bad_cs']} dup={r['dup_scan']} marks={r['marks']}"
    )

# relative layout of line starts/ends in a common local frame
lat_ref = rows[0]["lat0"]
lon_ref = rows[0]["lon0"]
R = 6371000.0
print("\nstart/end in common local metres (E, N) relative to FILE__001 start; times UTC s-of-day")
for r in rows:
    def loc(la, lo):
        return (
            (lo - lon_ref) * math.pi / 180 * R * math.cos(math.radians(lat_ref)),
            (la - lat_ref) * math.pi / 180 * R,
        )
    s = loc(r["lat0"], r["lon0"])
    e = loc(r["latN"], r["lonN"])
    print(f"{r['name']}  start ({s[0]:7.2f},{s[1]:7.2f})  end ({e[0]:7.2f},{e[1]:7.2f})  t {r['t0']:.1f}-{r['t1']:.1f}  alt {r['alt'][0]:.2f}-{r['alt'][1]:.2f} hdop {r['hdop'][0]}-{r['hdop'][1]}")
