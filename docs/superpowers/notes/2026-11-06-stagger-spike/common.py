"""Shared spike helpers: load prepared data, GPS positions with a delay, tape positions, grid frame."""

import numpy as np

P = None


def load(path):
    global P
    z = np.load(path)
    names = list(z["names"])
    L = []
    for i, nm in enumerate(names):
        L.append(
            dict(
                name=str(nm),
                env=z[f"env_{i}"],
                scan=z[f"scan_{i}"].astype(float),
                t=z[f"t_{i}"],
                e=z[f"e_{i}"],
                n=z[f"n_{i}"],
                ntr=int(z["ntr"][i]),
            )
        )
    return L, z["t_bins"], float(z["spm"])


def interp_extrap(x, xp, fp):
    """np.interp with linear extrapolation from the end segments."""
    y = np.interp(x, xp, fp)
    lo = x < xp[0]
    hi = x > xp[-1]
    if lo.any():
        s = (fp[1] - fp[0]) / (xp[1] - xp[0])
        y[lo] = fp[0] + (x[lo] - xp[0]) * s
    if hi.any():
        s = (fp[-1] - fp[-2]) / (xp[-1] - xp[-2])
        y[hi] = fp[-1] + (x[hi] - xp[-1]) * s
    return y


def restamp(line, tau, max_dt=1.5):
    """Scan at each fix's epoch if the controller stamped it tau seconds late.

    Uses the local scan rate: the segment behind the fix for tau > 0 (moving back
    in time), ahead for tau < 0, falling back to the other side across a pause.
    """
    s, t = line["scan"], line["t"]
    if tau == 0:
        return s.copy()
    n = len(s)
    dt = np.diff(t)
    rate = np.diff(s) / dt
    back = np.full(n, np.nan)
    fwd = np.full(n, np.nan)
    ok = dt <= max_dt
    back[1:][ok] = rate[ok]
    fwd[:-1][ok] = rate[ok]
    first, second = (back, fwd) if tau > 0 else (fwd, back)
    r = np.where(np.isfinite(first), first, second)
    r = np.where(np.isfinite(r), r, np.nanmedian(rate[ok]))
    return s - tau * r


def gps_xy(line, tau=0.0):
    sc = restamp(line, tau)
    idx = np.arange(line["ntr"], dtype=float)
    order = np.argsort(sc, kind="stable")
    sc = sc[order]
    return np.column_stack(
        [interp_extrap(idx, sc, line["e"][order]), interp_extrap(idx, sc, line["n"][order])]
    )


def fit_frame(L):
    """Along axis u (northward mean line direction), cross axis v (eastward)."""
    dirs = []
    for ln in L:
        d = np.array([ln["e"][-1] - ln["e"][0], ln["n"][-1] - ln["n"][0]])
        d /= np.linalg.norm(d)
        dirs.append(d if d[1] > 0 else -d)
    u = np.mean(dirs, axis=0)
    u /= np.linalg.norm(u)
    v = np.array([u[1], -u[0]])
    south = np.array([(ln["n"][-1] - ln["n"][0]) < 0 for ln in L])
    return u, v, south


def tape_frame(L, u, v, south, spm, spacing=0.5, length=30.0):
    """Nominal tape grid fitted to the tracks: lines every `spacing` (cross decreasing with
    line index, as walked), a `length` m grid, edges chosen so the median start error is 0."""
    k = np.arange(len(L))
    cm = np.array([gps_xy(ln).dot(v).mean() for ln in L])
    c0 = np.mean(cm + spacing * k)
    starts = np.array([gps_xy(ln)[0].dot(u) for ln in L])
    north_edge = np.median(np.where(south, starts, starts + length))
    return dict(c0=c0, north_edge=north_edge, spacing=spacing, length=length, spm=spm)


def tape_uv(L, i, south, tf):
    ln = L[i]
    idx = np.arange(ln["ntr"], dtype=float)
    if south[i]:
        a = tf["north_edge"] - idx / tf["spm"]
    else:
        a = tf["north_edge"] - tf["length"] + idx / tf["spm"]
    c = np.full_like(a, tf["c0"] - tf["spacing"] * i)
    return a, c
