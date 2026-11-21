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
    return float(np.median(steps)) if steps.size else 0.0


def gap_threshold(distance: np.ndarray, gap_m: float | None = None) -> float:
    """Gap over, in metres: `gap_m` when given, else 6 usual steps (inf if no spacing)."""
    if gap_m is not None:
        if not (math.isfinite(gap_m) and gap_m > 0):
            raise ValueError(f"Gap over must be a finite length above 0, got {gap_m!r}")
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
    n = np.asarray(distance).size
    out = np.zeros(n, dtype=bool)
    if n >= 3:
        gaps = gap_steps(distance, gap_m)
        out[1:-1] = gaps[:-1] & gaps[1:]
    return out
