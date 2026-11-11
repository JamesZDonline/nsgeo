"""Shared loaders for the #111 spike (throwaway)."""

import json
from pathlib import Path

import numpy as np

CUBES = {
    "grid1_005": str(Path.home() / "nsgeo-m4-check/Sunnyside/mincurv_cube.npz"),
    "grid1_020": str(Path.home() / "nsgeo-m4-check/Sunnyside/grid1cube.npz"),
}


def load(name):
    if name == "grid1_010":
        z = np.load(CUBES["grid1_005"])
        fr = json.loads(str(z["meta"]))["frame"]
        mean, count = coarsen(z["mean"], z["count"], (fr["ny"], fr["nx"]))
        shape = (fr["ny"] // 2, fr["nx"] // 2)
        return mean, (count > 0).reshape(shape), 0.1, shape
    z = np.load(CUBES[name])
    meta = json.loads(str(z["meta"]))
    fr = meta["frame"]
    ny, nx = fr["ny"], fr["nx"]
    pop = (z["count"] > 0).reshape(ny, nx)
    return z["mean"], pop, fr["cell"], (ny, nx)


def window(mean, shape, k0, k1):
    return mean[k0:k1].mean(axis=0).reshape(shape)


WINDOWS = [(20, 25), (45, 50), (70, 75), (95, 100), (120, 125), (150, 155), (180, 185), (205, 210)]


def coarsen(mean, count, shape):
    """2x2 count-weighted block mean: an approximate binning at twice the cell."""
    ny, nx = shape
    m = mean.reshape(-1, ny, nx)
    c = count.reshape(ny, nx).astype(np.float64)
    ny2, nx2 = ny // 2, nx // 2
    m = np.nan_to_num(m[:, : 2 * ny2, : 2 * nx2])
    c = c[: 2 * ny2, : 2 * nx2]
    cw = c.reshape(ny2, 2, nx2, 2).sum(axis=(1, 3))
    mw = (m * c).reshape(m.shape[0], ny2, 2, nx2, 2).sum(axis=(2, 4))
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (mw / cw).astype(np.float32)
    return out.reshape(m.shape[0], -1), cw.ravel()
