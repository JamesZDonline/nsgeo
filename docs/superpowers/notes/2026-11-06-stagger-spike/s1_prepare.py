"""Spike stage 1: read the 60 lines, process to envelope, average into time bins, save with GPS fixes.

Positions are stored only as LOCAL metres (equirectangular about the first fix of FILE__001).
"""

import math
import sys
from pathlib import Path

import numpy as np

from nsgeo.io.dzt import read_header, read_samples
from nsgeo.processing.amplitude import analytic_envelope
from nsgeo.processing.base import Radargram, build_step

D = Path(sys.argv[1])
OUT = Path(sys.argv[2])
BIN = 8  # samples per time bin (~1.73 ns)
R = 6371000.0


def dm(v, h):
    d = int(float(v) / 100)
    x = d + (float(v) - d * 100) / 60
    return -x if h in "SW" else x


names, envs, fix_scan, fix_t, fix_e, fix_n, ntr = [], [], [], [], [], [], []
lat0 = lon0 = None
dewow = build_step("dewow", window_ns=4.0)
bg = build_step("background_mean")
for dzg in sorted(D.glob("*.DZG")):
    dzt = dzg.with_suffix(".DZT")
    h = read_header(dzt)
    data = read_samples(dzt, h)[0].astype(float)
    rg = Radargram(data=data, dt_ns=h.dt_ns, t0_ns=h.position_ns, dx_m=1 / h.traces_per_metre)
    rg = bg.apply(dewow.apply(rg))
    env = analytic_envelope(rg.data)
    nb = env.shape[0] // BIN
    envb = env[: nb * BIN].reshape(nb, BIN, -1).mean(axis=1).astype(np.float32)
    sc, la, lo, ti = [], [], [], []
    cur = None
    for ln in dzg.read_text().splitlines():
        f = ln.strip().split(",")
        if f[0] == "$GSSIS":
            cur = int(f[1])
        elif f[0].endswith("GGA"):
            sc.append(cur)
            la.append(dm(f[2], f[3]))
            lo.append(dm(f[4], f[5]))
            t = f[1]
            ti.append(int(t[:2]) * 3600 + int(t[2:4]) * 60 + float(t[4:]))
    la, lo = np.array(la), np.array(lo)
    if lat0 is None:
        lat0, lon0 = la[0], lo[0]
    k = math.cos(math.radians(lat0))
    e = (lo - lon0) * math.pi / 180 * R * k
    n = (la - lat0) * math.pi / 180 * R
    names.append(dzg.stem)
    envs.append(envb)
    fix_scan.append(np.array(sc))
    fix_t.append(np.array(ti))
    fix_e.append(e)
    fix_n.append(n)
    ntr.append(data.shape[1])
    print(dzg.stem, data.shape, envb.shape, flush=True)

t_bins = h.position_ns + (np.arange(nb) * BIN + (BIN - 1) / 2) * h.dt_ns
np.savez(
    OUT,
    names=np.array(names),
    t_bins=t_bins,
    spm=h.traces_per_metre,
    ntr=np.array(ntr),
    **{f"env_{i}": a for i, a in enumerate(envs)},
    **{f"scan_{i}": a for i, a in enumerate(fix_scan)},
    **{f"t_{i}": a for i, a in enumerate(fix_t)},
    **{f"e_{i}": a for i, a in enumerate(fix_e)},
    **{f"n_{i}": a for i, a in enumerate(fix_n)},
)
print("saved", OUT)
