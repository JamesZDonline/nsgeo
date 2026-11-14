"""Trace a diffraction hyperbola from a box, as dots on its outer edge.

The author draws a box around a hyperbola. This module finds the strongest
hyperbola t(x) = sqrt(t0^2 + 4 (x - x0)^2 / v^2) inside it, marks the outer
edge of its top band on each trace, throws away the edges that disagree, and
thins the rest to about ten dots. The dots are ordinary picks: the caller fits
them with ``fit_hyperbola`` exactly as it fits clicked points.

The scan scores a curve by stacking the signed amplitudes along it, after
taking each row's mean across the box away. A curve that follows one lobe of
the band adds up; one that cuts across the band's lobes, or runs along a flat
layer, cancels. Scoring |amplitude| instead (blind to phase) let a steep curve
sit in the bright apex and win on real lines (#140).

The edge is the zero crossing into the band's first strong lobe (spec §4.2,
the author's ruling after the real-data check). A faint precursor lobe runs
ahead of the band the author sees; the first version marked where the signal
first reached a fifth of its peak, which often fell on that precursor, so the
traced curve floated above the hyperbola. The lobe is chosen once per box,
from the stack of the traces along the scan's curve, so every trace follows
the same one. A zero crossing does not depend on how bright the trace is, so
the edge does not drift deeper as a leg fades.

Every dot stays on that lobe. A trace's crossing counts only within a quarter
period of where the lobe is expected, and of the fit through the dots: the
next crossing into a lobe of the same sign is a whole period away. Reading a
window that reached further below the expected crossing than above it, an
earlier draft took the next lobe down wherever a leg's crossing came early,
and dots on a leg jumped down a level (#140).

This is not the Time zero step's rule (0.2 of the direct wave's peak); the
small fixed offset between the two is a follow-up. ``trace_hyperbola`` takes
no Time zero fraction.
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
#: The first strong lobe is the earliest lobe on the stack, within a period
#: before its peak, that reaches this fraction of that peak. On the stacks of
#: the author's hand fits, the lobes ahead of the one whose crossing they
#: clicked reach 0.10-0.30 of the peak (two reach 0.48 and 0.49), and the
#: clicked lobe 0.54-1.00 (one 0.498, just under this). The measured wavelet's
#: precursor is 0.21 and its first strong lobe 0.69 (tests/planted.py,
#: REAL_WAVELET).
_STRONG_LOBE = 0.5
#: A dot lies within this many periods of where its lobe's crossing is
#: expected, and of the fit through the dots.
_LOBE_TOLERANCE_PERIODS = 0.25
#: A trace's lobe must peak at least this fraction of the lobe's peak on the
#: band's strongest traces. Where a leg fades below it, the leg ends. On the
#: author's hand fits, the lobe at the outermost clicked dots is 0.51 of that
#: (median; the 10th percentile is 0.18, the 25th 0.34): 0.2 keeps 86% of them,
#: 0.3 78% and 0.4 65%.
_FAINT_FRACTION = 0.2
#: Residuals beyond this many median absolute residuals are dropped.
_OUTLIER_MADS = 3.0
#: ...but never closer than this many samples, so a near-perfect fit keeps all.
_OUTLIER_FLOOR_SAMPLES = 0.5


@dataclass(frozen=True)
class TraceBox:
    first_trace: int  # inclusive; any order in, normalised by trace_hyperbola
    last_trace: int
    top_ns: float  # on the same clock as `times_ns`
    bottom_ns: float


def _too_few(n: int) -> str:
    return f"Too few points were left after cleaning ({n}); a fit needs at least {MIN_DOTS}."


def _too_faint() -> ValueError:
    return ValueError("The hyperbola in the box is too faint to trace.")


def _zero_at(seg: np.ndarray, times: np.ndarray, j: int) -> float:
    """Where the signal crosses zero between samples j - 1 and j, read by
    linear interpolation."""
    a0, a1 = float(seg[j - 1]), float(seg[j])
    return float(times[j - 1] + a0 / (a0 - a1) * (times[j] - times[j - 1]))


def _crossings(seg: np.ndarray, times: np.ndarray, sign: float) -> tuple[np.ndarray, np.ndarray]:
    """(times, peaks): each zero crossing into a lobe of ``sign`` in one
    trace's samples, and the peak of the lobe it starts (as a positive
    number)."""
    s = sign * np.asarray(seg, dtype=float)
    starts = np.flatnonzero((s[:-1] <= 0.0) & (s[1:] > 0.0)) + 1
    ends = np.flatnonzero((s[:-1] > 0.0) & (s[1:] <= 0.0)) + 1
    found_t, found_p = [], []
    for j in starts:
        stop = ends[ends > j]
        k = int(stop[0]) if stop.size else s.size
        found_t.append(_zero_at(seg, times, int(j)))
        found_p.append(float(s[j:k].max()))
    return np.array(found_t), np.array(found_p)


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


def _stack_along(
    img: np.ndarray, times: np.ndarray, curve: np.ndarray, period_ns: float
) -> tuple[np.ndarray, np.ndarray]:
    """(lags, stack): the box read along the curve, at each lag from it, and
    averaged over the traces. That keeps the hyperbola's wavelet and averages
    away what does not follow the curve. Lags no trace reaches are left out."""
    dt = float(times[1] - times[0])
    lags = np.arange(-1.5 * period_ns, 1.5 * period_ns + dt / 2.0, dt)
    total = np.zeros(lags.size)
    count = np.zeros(lags.size)
    for col in range(img.shape[1]):
        if not times[0] <= curve[col] <= times[-1]:
            continue
        t = curve[col] + lags
        inside = (t >= times[0]) & (t <= times[-1])
        total[inside] += np.interp(t[inside], times, img[:, col])
        count[inside] += 1.0
    reached = count > 0.0
    return lags[reached], total[reached] / count[reached]


def _first_strong_lobe(
    lags: np.ndarray, stack: np.ndarray, period_ns: float
) -> tuple[float, float] | None:
    """(lag, sign) of the zero crossing into the first strong lobe on the
    stack: the earliest lobe, within a period before the stack's peak near the
    curve, that reaches ``_STRONG_LOBE`` of that peak. None when no such lobe
    starts with a crossing."""
    near = np.flatnonzero(np.abs(lags) <= 0.5 * period_ns)
    if near.size == 0:
        return None
    top = int(near[int(np.argmax(np.abs(stack[near])))])
    sign = np.sign(stack)
    starts = np.flatnonzero((sign[1:] != sign[:-1]) & (sign[1:] != 0.0)) + 1
    ends = [*starts[1:], stack.size]
    for j, k in zip(starts, ends):
        peak = j + int(np.argmax(np.abs(stack[j:k])))
        if lags[peak] < lags[top] - period_ns:
            continue
        if lags[peak] > lags[top]:
            break
        if abs(stack[peak]) >= _STRONG_LOBE * abs(stack[top]):
            return _zero_at(stack, lags, int(j)), float(sign[peak])
    return None


def trace_hyperbola(
    data: np.ndarray,
    times_ns: np.ndarray,
    distance_m: np.ndarray,
    box: TraceBox,
    *,
    max_dots: int = MAX_DOTS,
) -> list[tuple[int, float]]:
    """Dots ``(trace, time)`` on the outer edge of the strongest hyperbola in
    ``box``, the apex-nearest first and the rest in trace order.

    The edge is the zero crossing into the band's first strong lobe, read
    between samples by linear interpolation. ``data`` is (n_samples,
    n_traces); ``times_ns`` is each row's time on the clock the fit uses;
    ``distance_m`` is each trace's distance along the line (spacing may be
    uneven). Raises ``ValueError`` with a plain reason.
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
    # Each row's mean across the box taken away: a layer flat across the box
    # goes, a hyperbola's curve stays.
    img = box_data - box_data.mean(axis=1, keepdims=True)
    apex_x, t0, v, best = _scan(img, x_box, float(box_times[0]), float(box_times[-1]), dt, period)
    noise = 1.4826 * float(np.median(np.abs(img - np.median(img))))
    if best < _DETECT_Z * noise:
        raise ValueError("No hyperbola was found in the box.")

    # The lobe to follow, chosen once on the stack along the scan's curve.
    curve = np.sqrt(t0**2 + 4.0 * (x_box - apex_x) ** 2 / v**2)
    lobe = _first_strong_lobe(*_stack_along(img, box_times, curve, period), period)
    if lobe is None:
        raise _too_faint()
    lag, sign = lobe
    tolerance = _LOBE_TOLERANCE_PERIODS * period

    # On each trace, the crossing into that lobe nearest where it is expected.
    found: list[tuple[int, float, float]] = []  # (box column, edge, lobe peak)
    for col in range(n_box_tr):
        expected = curve[col] + lag
        if not box_times[0] <= expected <= box_times[-1]:
            continue
        lo = max(0, int(np.searchsorted(box_times, expected - tolerance)) - 1)
        hi = int(np.searchsorted(box_times, expected + tolerance + 0.5 * period, "right"))
        edges, peaks = _crossings(box_data[lo:hi, col], box_times[lo:hi], sign)
        if edges.size == 0:
            continue
        k = int(np.argmin(np.abs(edges - expected)))
        if abs(edges[k] - expected) <= tolerance:
            found.append((col, float(edges[k]), float(peaks[k])))
    if not found:
        raise _too_faint()
    cols = np.array([f[0] for f in found])
    peaks = np.array([f[2] for f in found])
    # Measured against the band's strongest traces, not the ones nearest the
    # scan's apex: on a short hyperbola the scan may put a flat curve's apex
    # on noise, and then every noise crossing passed.
    strong = peaks >= _FAINT_FRACTION * float(np.median(np.sort(peaks)[-5:]))
    cols = cols[strong]
    edges = np.array([f[1] for f in found])[strong]

    # Clean: fit, drop the edges that disagree, refit. The scan's apex is the
    # fit's apex guess, moved in to the edges when it lies beyond them (a short
    # hyperbola can scan as a flat curve whose apex is at the box's side).
    if cols.size < MIN_DOTS:
        raise ValueError(_too_few(int(cols.size)))
    x_e = x_box[cols]
    apex_x = float(np.clip(apex_x, x_e.min(), x_e.max()))
    fit = fit_hyperbola(x_e, edges, apex_x)
    resid = np.abs(edges - hyperbola_time(fit, x_e))
    limit = max(_OUTLIER_MADS * float(np.median(resid)), _OUTLIER_FLOOR_SAMPLES * dt)
    keep = resid <= limit
    while True:
        if int(keep.sum()) < MIN_DOTS:
            raise ValueError(_too_few(int(keep.sum())))
        cols, edges, x_e = cols[keep], edges[keep], x_e[keep]
        fit = fit_hyperbola(x_e, edges, apex_x)
        # A dot a lobe away from the rest never stays.
        keep = np.abs(edges - hyperbola_time(fit, x_e)) <= tolerance
        if keep.all():
            break

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
