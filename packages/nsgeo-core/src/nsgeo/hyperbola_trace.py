"""Trace a diffraction hyperbola from a box, as dots on its outer edge.

The author draws a box around a hyperbola. This module finds the strongest
hyperbola t(x) = sqrt(t0^2 + 4 (x - x0)^2 / v^2) inside it, marks the first
break (the outer edge of the top band) on each trace, throws away the edges
that disagree, and thins the rest to about ten dots. The dots are ordinary
picks: the caller fits them with ``fit_hyperbola`` exactly as it fits clicked
points.

The edge rule is the one the Time zero step uses for the first arrival: the
first time the signal reaches a set fraction of its peak, so the two offsets
cancel when the fraction is the same.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nsgeo.velocity_fit import fit_hyperbola, hyperbola_time

__all__ = [
    "MAX_BOX_CELLS",
    "MAX_DOTS",
    "MIN_DOTS",
    "TraceBox",
    "V_MAX_M_NS",
    "V_MIN_M_NS",
    "edge_time",
    "trace_hyperbola",
]

MAX_DOTS = 10
MIN_DOTS = 4
V_MIN_M_NS = 0.03
V_MAX_M_NS = 0.30
#: Traces times samples a box may hold. Read at call time (tests change it).
MAX_BOX_CELLS = 10**9

_MIN_BOX = 8  # traces and samples
#: The best curve's mean smoothed |amplitude| must beat the box's median by this
#: factor, or the box holds nothing but noise and clutter.
_DETECT_RATIO = 2.0
#: A trace's window peak must beat the box's median |amplitude| by this factor...
_FAINT_RATIO = 3.0
#: ...and be at least this fraction of the strongest traces' window peaks.
_FAINT_FRACTION = 0.15
#: Residuals beyond this many median absolute residuals are dropped.
_OUTLIER_MADS = 3.0
#: ...but never closer than this many samples, so a near-perfect fit keeps all.
_OUTLIER_FLOOR_SAMPLES = 0.5
_HALF = 3  # the edge is read from a polynomial through 2*_HALF - 2 samples
_PERIODS_BEFORE = 1.0  # edge window: from this many periods before the curve
_PERIODS_AFTER = 0.5  # ...to this many after it


@dataclass(frozen=True)
class TraceBox:
    first_trace: int  # inclusive; any order in, normalised by trace_hyperbola
    last_trace: int
    top_ns: float  # on the same clock as `times_ns`
    bottom_ns: float


def _cubic_crossing(amp: np.ndarray, times: np.ndarray, j: int, level: float) -> float | None:
    """Time in (times[j-1], times[j]] where a cubic through four samples
    reaches ``level``, or None when the window has no neighbours to use.

    A straight line between samples cuts the corner of a curved onset, and that
    always reads the edge early, by a few hundredths of a sample: small, but
    the same way on every trace, so it tilts the fitted velocity.
    """
    if j < _HALF - 1 or j + _HALF - 1 >= amp.size:
        return None
    ts = times[j - _HALF + 1 : j + _HALF]
    ys = amp[j - _HALF + 1 : j + _HALF] - level

    def poly(t: float) -> float:
        total = 0.0
        for k in range(2 * _HALF - 2):
            term = ys[k]
            for m in range(2 * _HALF - 2):
                if m != k:
                    term *= (t - ts[m]) / (ts[k] - ts[m])
            total += term
        return total

    lo, hi = float(times[j - 1]), float(times[j])
    if poly(lo) >= 0.0 or poly(hi) < 0.0:
        return None
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if poly(mid) < 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _refined_peak(amp: np.ndarray) -> float:
    """The window's peak, read between samples by a parabola through the top
    three. The highest sample can sit up to half a sample from the true crest,
    which would put the fraction level a little low and the edge a little early
    by the same amount on every trace."""
    k = int(np.argmax(amp))
    if k == 0 or k == amp.size - 1:
        return float(amp[k])
    left, mid, right = float(amp[k - 1]), float(amp[k]), float(amp[k + 1])
    curv = left - 2.0 * mid + right
    if curv >= 0.0:
        return mid
    return mid - (right - left) ** 2 / (8.0 * curv)


def _window_edge(seg: np.ndarray, times: np.ndarray, fraction: float) -> tuple[float | None, float]:
    """(edge time or None, window peak) of one window's samples."""
    amp = np.abs(seg)
    peak = float(amp.max()) if amp.size else 0.0
    if peak <= 0.0 or amp.size < 2:
        return None, peak
    peak = _refined_peak(amp)
    level = fraction * peak
    j = int(np.flatnonzero(amp >= level)[0])
    if j == 0:
        return float(times[0]), peak
    refined = _cubic_crossing(amp, times, j, level)
    if refined is not None:
        return refined, peak
    a0, a1 = float(amp[j - 1]), float(amp[j])
    frac = (level - a0) / (a1 - a0)
    return float(times[j - 1] + frac * (times[j] - times[j - 1])), peak


def edge_time(
    trace: np.ndarray,
    times_ns: np.ndarray,
    start_ns: float,
    stop_ns: float,
    fraction: float,
) -> float | None:
    """First time in ``[start_ns, stop_ns]`` where |amplitude| reaches
    ``fraction`` of the window's peak, read between samples (cubic through
    the four nearest, linear at a window's end). None when the window holds no signal."""
    times = np.asarray(times_ns, dtype=float)
    keep = (times >= start_ns) & (times <= stop_ns)
    edge, _ = _window_edge(np.asarray(trace, dtype=float)[keep], times[keep], fraction)
    return edge


def _smooth_abs(box: np.ndarray, width: int) -> np.ndarray:
    """|box| averaged over ``width`` samples down each trace."""
    amp = np.abs(box)
    if width <= 1:
        return amp
    pad_lo, pad_hi = width // 2, width - 1 - width // 2
    padded = np.pad(amp, ((pad_lo, pad_hi), (0, 0)), mode="edge")
    csum = np.cumsum(np.vstack([np.zeros((1, amp.shape[1])), padded]), axis=0)
    return (csum[width:] - csum[:-width]) / width


def _dominant_period_ns(box: np.ndarray, dt_ns: float) -> float:
    """Period at the peak of the box's mean amplitude spectrum (DC excluded)."""
    seg = box - box.mean(axis=0, keepdims=True)
    seg = seg * np.hanning(seg.shape[0])[:, None]
    n_fft = 4 * seg.shape[0]
    spectrum = np.abs(np.fft.rfft(seg, n=n_fft, axis=0)).mean(axis=1)
    freq = np.fft.rfftfreq(n_fft, dt_ns)
    lo, hi = 1.0 / (40.0 * dt_ns), 1.0 / (4.0 * dt_ns)
    band = (freq >= lo) & (freq <= hi)
    if not band.any() or spectrum[band].max() <= 0.0:
        return 10.0 * dt_ns
    return float(1.0 / freq[band][int(np.argmax(spectrum[band]))])


def _score(
    smooth: np.ndarray,
    x_m: np.ndarray,
    t_top: float,
    dt_ns: float,
    apex_x: np.ndarray,
    t0: np.ndarray,
    v: np.ndarray,
    min_valid: int,
) -> np.ndarray:
    """Mean smoothed |amplitude| along each candidate curve, over the box's
    traces where the curve lies inside the box. -1 where too few traces do."""
    n_rows, n_tr = smooth.shape
    out = np.empty(apex_x.size)
    cols = np.arange(n_tr)[None, :]
    chunk = max(1, 2_000_000 // n_tr)
    for lo in range(0, apex_x.size, chunk):
        sl = slice(lo, lo + chunk)
        dx = x_m[None, :] - apex_x[sl, None]
        t = np.sqrt(t0[sl, None] ** 2 + 4.0 * dx**2 / v[sl, None] ** 2)
        row = (t - t_top) / dt_ns
        valid = (row >= 0.0) & (row <= n_rows - 1)
        r0 = np.clip(np.floor(row).astype(int), 0, n_rows - 2)
        w = np.clip(row - r0, 0.0, 1.0)
        val = smooth[r0, cols] * (1.0 - w) + smooth[r0 + 1, cols] * w
        count = valid.sum(axis=1)
        mean = (val * valid).sum(axis=1) / np.maximum(count, 1)
        out[sl] = np.where(count >= min_valid, mean, -1.0)
    return out


def _scan(
    smooth: np.ndarray,
    x_m: np.ndarray,
    t_top: float,
    t_bottom: float,
    dt_ns: float,
) -> tuple[float, float, float, float]:
    """Best (apex x, t0, v, mean score), coarse to fine."""
    n_tr = smooth.shape[1]
    min_valid = max(_MIN_BOX, n_tr // 4)
    xa = np.linspace(x_m[0], x_m[-1], min(n_tr, 24))
    ta = np.linspace(t_top, t_bottom, min(smooth.shape[0], 30))
    va = np.geomspace(V_MIN_M_NS, V_MAX_M_NS, 14)
    for round_no in range(4):
        mesh = np.meshgrid(xa, ta, va, indexing="ij")
        gx, gt, gv = (m.ravel() for m in mesh)
        score = _score(smooth, x_m, t_top, dt_ns, gx, gt, gv, min_valid)
        k = int(np.argmax(score))
        best = (float(gx[k]), float(gt[k]), float(gv[k]), float(score[k]))
        if round_no == 3:
            break
        # Refine: five points either side of the best, one old step wide.
        step_x = (xa[1] - xa[0]) if xa.size > 1 else x_m[-1] - x_m[0]
        step_t = (ta[1] - ta[0]) if ta.size > 1 else t_bottom - t_top
        ratio = (va[1] / va[0]) if va.size > 1 else 1.0
        xa = np.clip(best[0] + np.linspace(-step_x, step_x, 7), x_m[0], x_m[-1])
        ta = np.clip(best[1] + np.linspace(-step_t, step_t, 7), t_top, t_bottom)
        va = np.clip(best[2] * np.geomspace(1.0 / ratio, ratio, 7), V_MIN_M_NS, V_MAX_M_NS)
    return best


def trace_hyperbola(
    data: np.ndarray,
    times_ns: np.ndarray,
    distance_m: np.ndarray,
    box: TraceBox,
    *,
    fraction: float = 0.2,
    max_dots: int = MAX_DOTS,
) -> list[tuple[int, float]]:
    """Dots ``(trace, time)`` on the outer edge of the strongest hyperbola in
    ``box``, the apex-nearest first and the rest in trace order.

    ``data`` is (n_samples, n_traces); ``times_ns`` is each row's time on the
    clock the fit uses; ``distance_m`` is each trace's distance along the line
    (spacing may be uneven). Raises ``ValueError`` with a plain reason.
    """
    data = np.asarray(data, dtype=float)
    times = np.asarray(times_ns, dtype=float)
    dist = np.asarray(distance_m, dtype=float)
    n_samples, n_traces = data.shape
    tr0 = int(np.clip(min(box.first_trace, box.last_trace), 0, n_traces - 1))
    tr1 = int(np.clip(max(box.first_trace, box.last_trace), 0, n_traces - 1))
    top, bottom = sorted((float(box.top_ns), float(box.bottom_ns)))
    rows = np.flatnonzero((times >= top) & (times <= bottom))
    n_box_tr = tr1 - tr0 + 1
    if n_box_tr < _MIN_BOX or rows.size < _MIN_BOX:
        raise ValueError(
            "The box is too small to hold a hyperbola: draw it around the apex "
            "and at least part of a leg."
        )
    if n_box_tr * rows.size > MAX_BOX_CELLS:
        raise ValueError(
            f"The box is too big to trace quickly ({n_box_tr} traces by "
            f"{bottom - top:.0f} ns). Draw it closer around one hyperbola."
        )
    r0, r1 = int(rows[0]), int(rows[-1])
    box_data = data[r0 : r1 + 1, tr0 : tr1 + 1]
    box_times = times[r0 : r1 + 1]
    x_box = dist[tr0 : tr1 + 1]
    dt = float(np.median(np.diff(box_times)))

    period = _dominant_period_ns(box_data, dt)
    smooth = _smooth_abs(box_data, max(1, int(round(period / (2.0 * dt)))))
    apex_x, t0, v, best = _scan(smooth, x_box, float(box_times[0]), float(box_times[-1]), dt)
    if best < _DETECT_RATIO * float(np.median(smooth)):
        raise ValueError("No hyperbola was found in the box.")

    # The edge on each trace, in a window around the best curve.
    curve = np.sqrt(t0**2 + 4.0 * (x_box - apex_x) ** 2 / v**2)
    median_amp = float(np.median(np.abs(box_data)))
    found: list[tuple[int, float, float]] = []  # (box column, edge, window peak)
    for col in range(n_box_tr):
        if not box_times[0] <= curve[col] <= box_times[-1]:
            continue
        lo = int(np.searchsorted(box_times, curve[col] - _PERIODS_BEFORE * period, "left"))
        hi = int(np.searchsorted(box_times, curve[col] + _PERIODS_AFTER * period, "right"))
        edge, peak = _window_edge(box_data[lo:hi, col], box_times[lo:hi], fraction)
        if edge is not None:
            found.append((col, edge, peak))
    if not found:
        raise ValueError("The hyperbola in the box is too faint to trace.")
    cols = np.array([f[0] for f in found])
    peaks = np.array([f[2] for f in found])
    near_apex = np.argsort(np.abs(x_box[cols] - apex_x))[:5]
    floor = max(_FAINT_RATIO * median_amp, _FAINT_FRACTION * float(np.median(peaks[near_apex])))
    strong = peaks >= floor
    if not strong[np.argsort(np.abs(x_box[cols] - apex_x))[:3]].any():
        raise ValueError("The hyperbola in the box is too faint to trace.")
    cols = cols[strong]
    edges = np.array([f[1] for f in found])[strong]

    # Clean: fit, drop the edges that disagree, refit.
    x_e = x_box[cols]
    fit = fit_hyperbola(x_e, edges, apex_x)
    resid = np.abs(edges - hyperbola_time(fit, x_e))
    limit = max(_OUTLIER_MADS * float(np.median(resid)), _OUTLIER_FLOOR_SAMPLES * dt)
    keep = resid <= limit
    if int(keep.sum()) < MIN_DOTS:
        raise ValueError(
            f"Too few points were left after cleaning ({int(keep.sum())}); a fit needs "
            f"at least {MIN_DOTS}."
        )
    cols, edges, x_e = cols[keep], edges[keep], x_e[keep]
    fit = fit_hyperbola(x_e, edges, apex_x)

    # Thin: evenly spaced along the traced extent, keeping the apex-nearest.
    apex_i = int(np.argmin(np.abs(x_e - fit.apex_x_m)))
    chosen = {apex_i}
    if cols.size > max_dots:
        targets = np.linspace(x_e[0], x_e[-1], max_dots)
        picks = sorted({int(np.argmin(np.abs(x_e - t))) for t in targets})
        if apex_i not in picks:
            nearest = min(picks, key=lambda k: abs(x_e[k] - x_e[apex_i]))
            picks.remove(nearest)
        chosen = set(picks) | {apex_i}
    rest = sorted(chosen - {apex_i})
    order = [apex_i, *rest]
    return [(int(tr0 + cols[k]), float(edges[k])) for k in order]
