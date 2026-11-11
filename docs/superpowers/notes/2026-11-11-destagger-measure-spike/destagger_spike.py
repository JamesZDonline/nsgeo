"""Throwaway spike for #159: measure the destagger on grid-placed lines, unfitted and fitted.

usage: destagger_spike.py <cache.npz> <survey.json> <grid_id>      (lines from a survey file)
       destagger_spike.py <cache.npz> --dir <dzt dir> <length m>    (zigzag, line 1 forward, 0.5 m)
"""

import json
import sys
from pathlib import Path

import numpy as np

from nsgeo.io.dzt import read_header, read_samples
from nsgeo.processing.amplitude import analytic_envelope
from nsgeo.processing.base import Radargram, build_step

BIN = 8
STEP = 0.02
HP_M, LP_M, END_M, MAXLAG_M = 3.0, 0.15, 2.0, 1.0


def lines_from_args():
    if sys.argv[2] == "--dir":
        d = Path(sys.argv[3])
        length = float(sys.argv[4])
        out = []
        for k, p in enumerate(sorted(d.glob("*.DZT"))):
            fwd = k % 2 == 0
            out.append(dict(path=str(p), offset=0.25 + 0.5 * k, direction=1 if fwd else -1,
                            start=0.0 if fwd else length, scale=1.0, shift=0.0))
        return out, length
    doc = json.loads(Path(sys.argv[2]).read_text())
    gid = sys.argv[3]
    g = next(g for g in doc["grids"] if g["id"] == gid)
    out = []
    for ln in doc["lines"]:
        pl = ln["placement"]
        if pl.get("grid_id") != gid:
            continue
        out.append(dict(path=ln["path"], offset=pl["offset"], direction=pl["direction"],
                        start=pl["start_along"], scale=pl.get("scale", 1.0),
                        shift=pl.get("travel_shift", 0.0), axis=pl["axis"]))
    length = g["size_y"] if out[0].get("axis", "y") == "y" else g["size_x"]
    return out, length


def prepare(lines, cache):
    if Path(cache).exists():
        z = np.load(cache)
        return [z[f"env_{i}"] for i in range(len(lines))], z["spm"], z["t_bins"]
    dewow = build_step("dewow", window_ns=4.0)
    bg = build_step("background_mean")
    envs = []
    for ln in lines:
        h = read_header(ln["path"])
        data = read_samples(ln["path"], h)[0].astype(float)
        rg = Radargram(data=data, dt_ns=h.dt_ns, t0_ns=h.position_ns, dx_m=1 / h.traces_per_metre)
        env = analytic_envelope(bg.apply(dewow.apply(rg)).data)
        nb = env.shape[0] // BIN
        envs.append(env[: nb * BIN].reshape(nb, BIN, -1).mean(axis=1).astype(np.float32))
        print(Path(ln["path"]).stem, data.shape, flush=True)
    t_bins = h.position_ns + (np.arange(nb) * BIN + (BIN - 1) / 2) * h.dt_ns
    np.savez(cache, spm=h.traces_per_metre, t_bins=t_bins, **{f"env_{i}": e for i, e in enumerate(envs)})
    return envs, h.traces_per_metre, t_bins


def place(ln, ntr, spm, scale=None, shift=None, start=None):
    sc = ln["scale"] if scale is None else scale
    sh = ln["shift"] if shift is None else shift
    st = ln["start"] if start is None else start
    return st + ln["direction"] * (sc * np.arange(ntr) / spm + sh)


def fitted(ln, ntr, spm, length):
    span = (ntr - 1) / spm
    return dict(scale=length / span, start=0.0 if ln["direction"] == 1 else length)


class Measure:
    def __init__(self, envs, t_bins, length, lo=4.0, hi=70.0):
        self.envs = envs
        self.bins = np.flatnonzero((t_bins > lo) & (t_bins < hi))
        self.t = t_bins
        self.A = np.arange(0.0, length + 1e-9, STEP)
        self.gain = np.array([np.median(np.concatenate([e[b] for e in envs])) for b in self.bins])

    def profiles(self, alongs):
        A = self.A
        hp = int(round(HP_M / STEP))
        lp = int(round(LP_M / STEP)) | 1
        F = np.zeros((len(self.envs), self.bins.size, A.size))
        M = np.zeros((len(self.envs), A.size), bool)
        for k, (e, a) in enumerate(zip(self.envs, alongs)):
            o = np.argsort(a, kind="stable")
            valid = (A >= a.min() + END_M) & (A <= a.max() - END_M)
            M[k] = valid
            for j, b in enumerate(self.bins):
                f = np.interp(A, a[o], e[b][o].astype(float) / self.gain[j])
                f = np.convolve(np.pad(f, lp // 2, mode="edge"), np.ones(lp) / lp, mode="valid")[: A.size]
                f = f - np.convolve(np.pad(f, hp // 2, mode="edge"), np.ones(hp) / hp, mode="valid")[: A.size]
                F[k, j] = np.where(valid, f, 0.0)
            v = F[k][:, valid]
            sd = v.std()
            F[k][:, valid] = (v - v.mean(axis=1, keepdims=True)) / sd if sd > 0 else 0
        return F, M

    def curves(self, F, order, dirs):
        """Per line: curve over lags of line k vs its opposite-direction neighbours (by offset
        order), as a shift of line k in its own direction of travel; None when no neighbour."""
        maxlag = int(round(MAXLAG_M / STEP))
        n = self.A.size
        nfft = 1 << int(np.ceil(np.log2(2 * n)))
        out = {}
        for pos, k in enumerate(order):
            nb = [order[q] for q in (pos - 1, pos + 1) if 0 <= q < len(order) and dirs[order[q]] != dirs[k]]
            if not nb:
                continue
            G = np.mean([F[j] for j in nb], axis=0)
            X = np.fft.irfft(np.fft.rfft(F[k], nfft) * np.conj(np.fft.rfft(G, nfft)), nfft)
            c = np.concatenate([X[:, -maxlag:], X[:, : maxlag + 1]], axis=1) / n
            out[k] = c[:, ::-1] if dirs[k] < 0 else c
        return out


def peak(c):
    maxlag = (c.size - 1) // 2
    lags = np.arange(-maxlag, maxlag + 1) * STEP
    i = int(np.argmax(c))
    if 0 < i < c.size - 1:
        y0, y1, y2 = c[i - 1], c[i], c[i + 1]
        den = y0 - 2 * y1 + y2
        return lags[i] + (0.5 * (y0 - y2) / den if den else 0.0) * STEP, y1
    return lags[i], c[i]


def report(label, m, lines, alongs, windows):
    order = list(np.argsort([ln["offset"] for ln in lines], kind="stable"))
    dirs = [ln["direction"] for ln in lines]
    F, _ = m.profiles(alongs)
    C = m.curves(F, order, dirs)
    ks = sorted(C)
    allc = np.array([C[k] for k in ks])  # lines, bins, lags
    s, h = peak(allc.sum(axis=1).mean(axis=0))
    rng = np.random.default_rng(0)
    boots = [peak(allc[rng.integers(0, len(ks), len(ks))].sum(axis=1).mean(axis=0))[0] for _ in range(300)]
    per = np.array([peak(allc[i].sum(axis=0))[0] for i in range(len(ks))])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"\n[{label}] neighbour shift {s*100:+.1f} cm (95% {lo*100:+.1f}..{hi*100:+.1f}); "
          f"=> destagger {-s/2:+.3f} m; peak {h:.3f}; per-line shift IQR "
          f"{np.percentile(per,25)*100:+.1f}..{np.percentile(per,75)*100:+.1f} cm")
    for wlo, whi in windows:
        sel = np.flatnonzero((m.t[m.bins] >= wlo) & (m.t[m.bins] < whi))
        if sel.size:
            sw, hw = peak(allc[:, sel].sum(axis=1).mean(axis=0))
            print(f"    {wlo:>5.1f}-{whi:<5.1f} ns: shift {sw*100:+6.1f} cm => destagger {-sw/2:+.3f} m (peak {hw:.3f})")
    return s


def main():
    cache = sys.argv[1]
    lines, length = lines_from_args()
    envs, spm, t_bins = prepare(lines, cache)
    spm = float(spm)
    ntr = [e.shape[1] for e in envs]
    hi = min(70.0, float(t_bins[-1]))
    print(f"{len(lines)} lines, length {length} m, spm {spm}, bins {t_bins[0]:.1f}..{t_bins[-1]:.1f} ns")
    m = Measure(envs, t_bins, length, hi=hi)
    windows = [(4, 15), (15, 25), (25, 40), (40, 70), (14.9, 19.7)]
    spans = np.array([(n - 1) / spm for n in ntr])
    print(f"recorded spans: median {np.median(spans):.2f} m, min {spans.min():.2f}, max {spans.max():.2f} "
          f"(grid {length} m) => fit scale median {np.median(length/spans):.4f}")

    unf = [place(ln, n, spm) for ln, n in zip(lines, ntr)]
    s_u = report("as placed (unfitted)", m, lines, unf, windows)
    d_u = -s_u / 2
    unf_d = [place(ln, n, spm, shift=d_u) for ln, n in zip(lines, ntr)]
    report(f"as placed + destagger {d_u:+.3f}", m, lines, unf_d, windows[:0])

    fit = [place(ln, n, spm, **fitted(ln, n, spm, length)) for ln, n in zip(lines, ntr)]
    s_f = report("fitted to grid edges", m, lines, fit, windows)
    d_f = -s_f / 2
    fit_d = [place(ln, n, spm, shift=d_f, **fitted(ln, n, spm, length)) for ln, n in zip(lines, ntr)]
    report(f"fitted + destagger {d_f:+.3f}", m, lines, fit_d, windows[:0])
    for d in (-0.15, 0.15):
        report(f"fitted + destagger {d:+.2f}", m, lines,
               [place(ln, n, spm, shift=d, **fitted(ln, n, spm, length)) for ln, n in zip(lines, ntr)], [])
        report(f"unfitted + destagger {d:+.2f}", m, lines,
               [place(ln, n, spm, shift=d) for ln, n in zip(lines, ntr)], [])


if __name__ == "__main__":
    main()
