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

The scan scores a curve by stacking the signed amplitudes along it, after
taking each row's mean across the box away. A curve that follows one lobe of
the band adds up; one that cuts across the band's lobes, or runs along a flat
layer, cancels. Scoring |amplitude| instead (blind to phase) let a steep curve
sit in the bright apex and win on real lines (#140). The edge window on each
trace then starts just ahead of the band's own edge, found on the stack of the
traces along the curve, so the layers and clutter ahead of it are not read.
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
#: Measured on a real 1780-trace line with the coherent scan: a box of 196 000
#: cells (960 traces by 204 samples) traces in 0.5 s, 82 000 cells in 0.55 s.
#: The largest box drawn around a saved hand fit traces in 0.24 s.
MAX_BOX_CELLS = 200_000

_MIN_BOX = 8  # traces and samples
#: The best curve's stack must stand this many noise deviations above zero, or
#: the box holds nothing but noise and clutter. Noise alone tops out near 4.8
#: (120 planted boxes); the author's real hyperbolas score 9 to 60.
_DETECT_Z = 6.0
#: The scan's grid: apex times at most this many periods apart, this many
#: velocities, and at most this many traces read in the coarse round.
_T_STEP_PERIODS = 1.0 / 8.0
_N_VELOCITIES = 28
_COARSE_TRACES = 96
#: A trace's window peak must be at least this fraction of the traces nearest
#: the apex. Where a leg fades below it, the leg ends. On the author's hand fits
#: the band at the last clicked dot is 0.45 of the apex (median; quartiles 0.32
#: and 0.63), so 0.5 dropped legs they had clicked. A trace whose band does not
#: stand clear of what comes before it gives no edge anyway: its window then
#: starts at or above the level (see ``_window_edge``).
_FAINT_FRACTION = 0.25
#: Residuals beyond this many median absolute residuals are dropped.
_OUTLIER_MADS = 3.0
#: ...but never closer than this many samples, so a near-perfect fit keeps all.
_OUTLIER_FLOOR_SAMPLES = 0.5
#: The edge window on each trace: from this many periods before the band's
#: edge on the stack...
_EDGE_LEAD_PERIODS = 0.15
#: ...to this many after the band's peak. The stacked edge is looked for up to
#: one period before that peak.
_EDGE_TAIL_PERIODS = 0.25


@dataclass(frozen=True)
class TraceBox:
    first_trace: int  # inclusive; any order in, normalised by trace_hyperbola
    last_trace: int
    top_ns: float  # on the same clock as `times_ns`
    bottom_ns: float


def _window_edge(seg: np.ndarray, times: np.ndarray, fraction: float) -> tuple[float | None, float]:
    """(edge time or None, window peak) of one window's samples.

    The edge is None when the window holds no signal, or when the signal is
    already at the level on its first sample: the onset lies before the window,
    and its start is not the edge.
    """
    amp = np.abs(seg)
    peak = float(amp.max()) if amp.size else 0.0
    if peak <= 0.0 or amp.size < 2:
        return None, peak
    level = fraction * peak
    j = int(np.flatnonzero(amp >= level)[0])
    if j == 0:
        return None, peak
    a0, a1 = float(amp[j - 1]), float(amp[j])
    frac = (level - a0) / (a1 - a0)
    return float(times[j - 1] + frac * (times[j] - times[j - 1])), peak


def _too_few(n: int) -> str:
    return f"Too few points were left after cleaning ({n}); a fit needs at least {MIN_DOTS}."


def _check_fraction(fraction: float) -> None:
    if not 0.0 < fraction < 1.0:
        raise ValueError(
            f"The edge fraction must be between 0 and 1 (not including either); got {fraction}."
        )


def edge_time(
    trace: np.ndarray,
    times_ns: np.ndarray,
    start_ns: float,
    stop_ns: float,
    fraction: float,
) -> float | None:
    """First time in ``[start_ns, stop_ns]`` where |amplitude| reaches
    ``fraction`` of the window's peak, read between samples by linear
    interpolation. None when the window holds no signal, or when the signal is
    already at that level on the window's first sample (the onset is earlier).
    ``fraction`` must lie strictly between 0 and 1."""
    _check_fraction(fraction)
    times = np.asarray(times_ns, dtype=float)
    keep = (times >= start_ns) & (times <= stop_ns)
    edge, _ = _window_edge(np.asarray(trace, dtype=float)[keep], times[keep], fraction)
    return edge


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
    img: np.ndarray,
    x_m: np.ndarray,
    t_top: float,
    dt_ns: float,
    apex_x: np.ndarray,
    t0: np.ndarray,
    v: np.ndarray,
    min_valid: int,
) -> np.ndarray:
    """|Sum of the signed amplitudes| along each candidate curve over the
    square root of their count, over the box's traces where the curve lies
    inside the box; -1 where too few traces do.

    Divided by sqrt(count), noise scores the same whatever the curve's length,
    so a long curve and a short one compare fairly.
    """
    n_rows, n_tr = img.shape
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
        val = img[r0, cols] * (1.0 - w) + img[r0 + 1, cols] * w
        count = valid.sum(axis=1)
        stack = np.abs((val * valid).sum(axis=1)) / np.sqrt(np.maximum(count, 1))
        out[sl] = np.where(count >= min_valid, stack, -1.0)
    return out


def _scan(
    img: np.ndarray,
    x_m: np.ndarray,
    t_top: float,
    t_bottom: float,
    dt_ns: float,
    period_ns: float,
) -> tuple[float, float, float, float]:
    """Best (apex x, t0, v, score), coarse to fine.

    The apex times are a fraction of a period apart, so a curve on a lobe is
    not stepped over. The coarse round reads an even spread of at most
    ``_COARSE_TRACES`` traces, which keeps a large box quick.
    """
    n_tr = img.shape[1]
    min_valid = max(_MIN_BOX, n_tr // 4)
    # A line laid out against its grid runs to smaller distances: bound by
    # the box's least and greatest distance, never its first and last.
    x_lo, x_hi = float(x_m.min()), float(x_m.max())
    xa = np.linspace(x_lo, x_hi, min(n_tr, 24))
    n_t = int(np.ceil((t_bottom - t_top) / (_T_STEP_PERIODS * period_ns))) + 1
    ta = np.linspace(t_top, t_bottom, max(2, min(n_t, 160)))
    va = np.geomspace(V_MIN_M_NS, V_MAX_M_NS, _N_VELOCITIES)
    sub = np.unique(np.linspace(0, n_tr - 1, min(n_tr, _COARSE_TRACES)).round().astype(int))
    for round_no in range(4):
        mesh = np.meshgrid(xa, ta, va, indexing="ij")
        gx, gt, gv = (m.ravel() for m in mesh)
        if round_no == 0 and sub.size < n_tr:
            need = max(1, int(np.ceil(min_valid * sub.size / n_tr)))
            score = _score(img[:, sub], x_m[sub], t_top, dt_ns, gx, gt, gv, need)
        else:
            score = _score(img, x_m, t_top, dt_ns, gx, gt, gv, min_valid)
        k = int(np.argmax(score))
        best = (float(gx[k]), float(gt[k]), float(gv[k]), float(score[k]))
        if round_no == 3:
            break
        # Refine: seven points across the best, one old step either side.
        step_x = abs(xa[1] - xa[0]) if xa.size > 1 else x_hi - x_lo
        step_t = (ta[1] - ta[0]) if ta.size > 1 else t_bottom - t_top
        ratio = (va[1] / va[0]) if va.size > 1 else 1.0
        xa = np.clip(best[0] + np.linspace(-step_x, step_x, 7), x_lo, x_hi)
        ta = np.clip(best[1] + np.linspace(-step_t, step_t, 7), t_top, t_bottom)
        va = np.clip(best[2] * np.geomspace(1.0 / ratio, ratio, 7), V_MIN_M_NS, V_MAX_M_NS)
    return best


def _edge_window(
    box_data: np.ndarray,
    box_times: np.ndarray,
    curve: np.ndarray,
    period_ns: float,
    fraction: float,
) -> tuple[float, float]:
    """(lead, tail): each trace's edge window, as offsets from the curve.

    The box is read along the curve on every trace and averaged. That keeps
    the hyperbola's wavelet and averages away what does not follow the curve.
    The band's peak on that stack, and its edge by the same rule as each
    trace's, place every trace's window: from just before that edge to just
    after that peak, so the layers and clutter ahead of the band are not read.
    """
    dt = float(box_times[1] - box_times[0])
    tau = np.arange(-1.5 * period_ns, 1.5 * period_ns + dt / 2.0, dt)
    total = np.zeros(tau.size)
    count = np.zeros(tau.size)
    for col in range(box_data.shape[1]):
        t = curve[col] + tau
        inside = (t >= box_times[0]) & (t <= box_times[-1])
        total[inside] += np.interp(t[inside], box_times, box_data[:, col])
        count[inside] += 1.0
    stack = np.where(count > 0.0, total / np.maximum(count, 1.0), 0.0)
    near = np.flatnonzero(np.abs(tau) <= 0.5 * period_ns)
    peak = float(tau[near[int(np.argmax(np.abs(stack[near])))]])
    ahead = (tau >= peak - period_ns) & (tau <= peak)
    edge, _ = _window_edge(stack[ahead], tau[ahead], fraction)
    onset = peak - period_ns if edge is None else edge
    return onset - _EDGE_LEAD_PERIODS * period_ns, peak + _EDGE_TAIL_PERIODS * period_ns


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
    _check_fraction(fraction)
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
    # Each row's mean across the box taken away: a layer flat across the box
    # goes, a hyperbola's curve stays.
    img = box_data - box_data.mean(axis=1, keepdims=True)
    apex_x, t0, v, best = _scan(img, x_box, float(box_times[0]), float(box_times[-1]), dt, period)
    noise = 1.4826 * float(np.median(np.abs(img - np.median(img))))
    if best < _DETECT_Z * noise:
        raise ValueError("No hyperbola was found in the box.")

    # The edge on each trace, in a window placed by the band on the stack.
    curve = np.sqrt(t0**2 + 4.0 * (x_box - apex_x) ** 2 / v**2)
    lead, tail = _edge_window(box_data, box_times, curve, period, fraction)
    found: list[tuple[int, float, float]] = []  # (box column, edge, window peak)
    for col in range(n_box_tr):
        if not box_times[0] <= curve[col] <= box_times[-1]:
            continue
        lo = int(np.searchsorted(box_times, curve[col] + lead, "left"))
        hi = int(np.searchsorted(box_times, curve[col] + tail, "right"))
        edge, peak = _window_edge(box_data[lo:hi, col], box_times[lo:hi], fraction)
        if edge is not None:
            found.append((col, edge, peak))
    if not found:
        raise ValueError("The hyperbola in the box is too faint to trace.")
    cols = np.array([f[0] for f in found])
    peaks = np.array([f[2] for f in found])
    near_apex = np.argsort(np.abs(x_box[cols] - apex_x))[:5]
    floor = _FAINT_FRACTION * float(np.median(peaks[near_apex]))
    strong = peaks >= floor
    if not strong[np.argsort(np.abs(x_box[cols] - apex_x))[:3]].any():
        raise ValueError("The hyperbola in the box is too faint to trace.")
    cols = cols[strong]
    edges = np.array([f[1] for f in found])[strong]

    # Clean: fit, drop the edges that disagree, refit.
    if cols.size < MIN_DOTS:
        raise ValueError(_too_few(int(cols.size)))
    x_e = x_box[cols]
    fit = fit_hyperbola(x_e, edges, apex_x)
    resid = np.abs(edges - hyperbola_time(fit, x_e))
    limit = max(_OUTLIER_MADS * float(np.median(resid)), _OUTLIER_FLOOR_SAMPLES * dt)
    keep = resid <= limit
    if int(keep.sum()) < MIN_DOTS:
        raise ValueError(_too_few(int(keep.sum())))
    cols, edges, x_e = cols[keep], edges[keep], x_e[keep]
    fit = fit_hyperbola(x_e, edges, apex_x)

    # Thin: evenly spaced along the traced extent, each target taking the
    # nearest survivor not already taken, and keeping the apex-nearest.
    apex_i = int(np.argmin(np.abs(x_e - fit.apex_x_m)))
    chosen = set(range(cols.size))
    if cols.size > max_dots:
        picks: list[int] = []
        for target in np.linspace(x_e[0], x_e[-1], max_dots):
            free = [k for k in range(cols.size) if k not in picks]
            picks.append(min(free, key=lambda k: abs(x_e[k] - target)))
        if apex_i not in picks:
            picks.remove(min(picks, key=lambda k: abs(x_e[k] - x_e[apex_i])))
        chosen = set(picks) | {apex_i}
    rest = sorted(chosen - {apex_i})
    order = [apex_i, *rest]
    return [(int(tr0 + cols[k]), float(edges[k])) for k in order]
