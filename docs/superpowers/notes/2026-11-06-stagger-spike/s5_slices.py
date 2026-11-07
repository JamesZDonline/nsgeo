"""Spike stage 5: slices of the grid placed by tape, by raw GPS, and by corrected GPS (same frame, fill, stretch)."""

import sys

import numpy as np

sys.path.insert(0, sys.argv[2])
from common import fit_frame, gps_xy, load, tape_frame, tape_uv  # noqa: E402

from nsgeo.slices.interpolate import plan_fill  # noqa: E402

L, t_bins, spm = load(sys.argv[1])
u, v, south = fit_frame(L)
tf = tape_frame(L, u, v, south, spm)
OFFSET = float(sys.argv[4])  # m, GPS behind the radar centre along travel
TAU = float(sys.argv[5])  # s
CELL = 0.1
WINDOWS = [(15, 20), (22, 28), (30, 40), (45, 60)]


def gps_ac(i, tau, offset):
    xy = gps_xy(L[i], tau)
    a, c = xy @ u, xy @ v
    a = a + offset * (-1.0 if south[i] else 1.0)
    return a, c


placements = {
    "tape": [tape_uv(L, i, south, tf) for i in range(len(L))],
    "gps_raw": [gps_ac(i, 0.0, 0.0) for i in range(len(L))],
    "gps_corr": [gps_ac(i, TAU, OFFSET) for i in range(len(L))],
}
allA = np.concatenate([p[0] for P in placements.values() for p in P])
allC = np.concatenate([p[1] for P in placements.values() for p in P])
a0, a1 = np.percentile(allA, 0.1) - 0.3, np.percentile(allA, 99.9) + 0.3
c0, c1 = allC.min() - 0.5, allC.max() + 0.5
na, nc = int((a1 - a0) / CELL) + 1, int((c1 - c0) / CELL) + 1
win_vals = []
for ln in L:
    win_vals.append([ln["env"][(t_bins >= lo) & (t_bins < hi)].mean(axis=0) for lo, hi in WINDOWS])
out = {}
for key, P in placements.items():
    S = np.zeros((len(WINDOWS), na, nc))
    W = np.zeros((na, nc))
    for i, (a, c) in enumerate(P):
        ia = np.clip(((a - a0) / CELL).astype(int), 0, na - 1)
        ic = np.clip(((c - c0) / CELL).astype(int), 0, nc - 1)
        np.add.at(W, (ia, ic), 1)
        for j in range(len(WINDOWS)):
            np.add.at(S[j], (ia, ic), win_vals[i][j])
    pop = W > 0
    plan = plan_fill(pop, CELL, "kriging", 0.375, 1.0)
    out[key] = np.array([plan.apply(np.where(pop, S[j] / np.maximum(W, 1), 0.0).astype(np.float32)) for j in range(len(WINDOWS))])
    print(key, "populated", pop.sum(), flush=True)

# marks to annotate (positions under each placement)
marks = {"FILE__011": [652], "FILE__016": [354, 421], "FILE__028": [836, 841, 1264, 1360]}
ann = []
for key, P in placements.items():
    for nm, scans in marks.items():
        i = [ln["name"] for ln in L].index(nm)
        a, c = P[i]
        for s_ in scans:
            ann.append((key, nm, s_, a[s_], c[s_]))
np.savez(
    sys.argv[3],
    tape=out["tape"], gps_raw=out["gps_raw"], gps_corr=out["gps_corr"],
    extent=np.array([c0, c0 + nc * CELL, a0, a0 + na * CELL]),
    windows=np.array(WINDOWS),
    ann=np.array([(x[3], x[4]) for x in ann]),
    ann_lab=np.array([f"{x[0]}|{x[1]}@{x[2]}" for x in ann]),
    line_c=np.array([[np.median(P[i][1]) for i in range(len(L))] for P in placements.values()]),
    offset=OFFSET, tau=TAU,
)
print("saved")
