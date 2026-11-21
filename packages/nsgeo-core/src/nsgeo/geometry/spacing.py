"""Where a GPS line has gaps (M17c, #134): one rule, used everywhere.

In plain words:

- The usual step is the median step between neighbouring traces along the line.
- A gap is a step longer than Gap over. Gap over is typed per line, or, when
  automatic, 6 times the usual step.
- A trace is left out when the steps on both of its sides are gaps (a lift over
  an obstacle). The first and last traces are never left out.

Distances are metres along the line (`TrackPlacement.distance_along`); only the
size of a step matters, so a falling distance has the same gaps as its reverse.
"""

from __future__ import annotations

import math

import numpy as np

GAP_FACTOR: float = 6.0
"""Automatic Gap over, in usual steps."""


def _steps(distance: np.ndarray) -> np.ndarray:
    d = np.asarray(distance, dtype=float)
    return np.abs(np.diff(d)) if d.size >= 2 else np.empty(0)


def usual_step(distance: np.ndarray) -> float:
    """The median step between neighbouring traces; 0 for fewer than 2 traces."""
    steps = _steps(distance)
    if not steps.size:
        return 0.0
    with np.errstate(invalid="ignore"):
        return float(np.median(steps))


def check_gap_m(gap_m: float | None) -> None:
    """Raise ValueError unless Gap over is None (automatic) or finite and above 0."""
    if gap_m is not None and not (math.isfinite(gap_m) and gap_m > 0):
        raise ValueError(f"Gap over must be None or a finite length above 0, got {gap_m!r}")


def gap_threshold(distance: np.ndarray, gap_m: float | None = None) -> float:
    """Gap over, in metres: `gap_m` when given, else 6 usual steps (inf if no spacing)."""
    check_gap_m(gap_m)
    if gap_m is not None:
        return float(gap_m)
    usual = usual_step(distance)
    return GAP_FACTOR * usual if usual > 0 else math.inf


def gap_steps(distance: np.ndarray, gap_m: float | None = None) -> np.ndarray:
    """Bool per step (length n - 1): the step is longer than Gap over."""
    threshold = gap_threshold(distance, gap_m)
    steps = _steps(distance)
    with np.errstate(invalid="ignore"):
        return np.asarray(steps > threshold, dtype=bool)


def left_out(distance: np.ndarray, gap_m: float | None = None) -> np.ndarray:
    """Bool per trace: gaps on both sides. Never the first or last trace."""
    check_gap_m(gap_m)
    n = np.asarray(distance).size
    out = np.zeros(n, dtype=bool)
    if n >= 3:
        gaps = gap_steps(distance, gap_m)
        out[1:-1] = gaps[:-1] & gaps[1:]
    return out


def resample_even(
    data: np.ndarray, x_m: np.ndarray, gap_m: float | None = None
) -> tuple[np.ndarray, float, float]:
    """Put a GPS line's drawn traces on an even grid, for migration.

    Returns `(even, x0, step)`: columns at `x0 + k * step`, `step` the usual
    step, from the first drawn trace to the one past the last. Each column is
    linearly interpolated from the two nearest drawn traces; left-out traces
    never feed it. A column at least one usual step from the nearest drawn
    trace, inside a gap, is 0: nothing is invented there. A falling distance
    gives the same columns as its reverse. `ValueError` when the line has no
    usual step or fewer than 2 drawn traces.
    """
    d = np.asarray(data, dtype=float)
    x = np.asarray(x_m, dtype=float)
    step = usual_step(x)
    if not (math.isfinite(step) and step > 0):
        raise ValueError("a line with no usual step cannot be put on an even grid")
    threshold = gap_threshold(x, gap_m)
    drawn = np.flatnonzero(~left_out(x, gap_m))
    order = drawn[np.argsort(x[drawn], kind="stable")]
    xs = x[order]
    if xs.size < 2:
        raise ValueError("fewer than 2 drawn traces cannot be put on an even grid")
    ds = d[:, order]
    x0 = float(xs[0])
    n = max(int(math.ceil((xs[-1] - x0) / step - 1e-9)) + 1, 2)
    g = x0 + np.arange(n) * step
    hi = np.clip(np.searchsorted(xs, g, side="right"), 1, xs.size - 1)
    xl, xr = xs[hi - 1], xs[hi]
    span = xr - xl
    with np.errstate(divide="ignore", invalid="ignore"):
        w = np.where(span > 0, (g - xl) / np.where(span > 0, span, 1.0), 0.0)
    # Past the last trace the column carries on the last pair's slope (one
    # column at most), unless that pair straddles a gap: then it holds the end trace.
    beyond = (g > xs[-1]) & (span <= threshold)
    w = np.where(beyond, w, np.clip(w, 0.0, 1.0))
    even = ds[:, hi - 1] * (1.0 - w) + ds[:, hi] * w
    nearest = np.minimum(np.abs(g - xl), np.abs(g - xr))
    empty = (span > threshold) & (nearest >= step * (1.0 - 1e-9))
    even[:, empty] = 0.0
    return even, x0, step


def sample_back(even: np.ndarray, x0: float, step: float, x_m: np.ndarray) -> np.ndarray:
    """Each trace's column of an even grid, linearly interpolated at its own distance."""
    e = np.asarray(even, dtype=float)
    pos = (np.asarray(x_m, dtype=float) - x0) / step
    n = e.shape[1]
    if n < 2:
        return e[:, np.zeros(pos.size, dtype=int)]
    lo = np.clip(np.floor(pos), 0, n - 2).astype(int)
    w = np.clip(pos - lo, 0.0, 1.0)
    return e[:, lo] * (1.0 - w) + e[:, lo + 1] * w
