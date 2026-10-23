"""Fit a diffraction hyperbola to picked points, giving velocity and its error.

A point reflector at depth d seen from antenna offset x has two-way time
t = sqrt(t0^2 + (4/v^2)(x - x0)^2). Squared, that is linear in t0^2 and 1/v^2,
so one least-squares solve replaces an iterative fitter (the core may not use
scipy). The apex position x0 is the only nonlinear unknown; it is found by
scanning a small window around the user's guess.

The standard error on v is returned because the residual alone cannot be
trusted: points clustered near the apex fit almost any velocity well, and only
the error says the velocity is unconstrained.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nsgeo.velocity import C_M_PER_NS

__all__ = ["HyperbolaFit", "fit_hyperbola"]

_SEARCH_STEPS = 101


@dataclass(frozen=True)
class HyperbolaFit:
    apex_x_m: float
    t0_ns: float
    v_m_ns: float
    v_stderr_m_ns: float
    rms_ns: float
    n_points: int


def _solve(x_m: np.ndarray, t_ns: np.ndarray, apex_m: float) -> HyperbolaFit | None:
    """Solve at a fixed apex; None when this apex gives no physical hyperbola."""
    n = x_m.size
    dx2 = (x_m - apex_m) ** 2
    design = np.column_stack([np.ones_like(dx2), dx2])
    y = t_ns**2
    coef, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    intercept, slope = float(coef[0]), float(coef[1])
    if rank < 2 or intercept <= 0.0 or slope <= 0.0:
        return None
    t0 = np.sqrt(intercept)
    v = 2.0 / np.sqrt(slope)
    s2 = float(np.sum((y - design @ coef) ** 2)) / (n - 2)
    cov = s2 * np.linalg.inv(design.T @ design)
    sigma_v = float(np.sqrt(cov[1, 1])) / slope**1.5
    rms = float(np.sqrt(np.mean((t_ns - np.sqrt(t0**2 + slope * dx2)) ** 2)))
    return HyperbolaFit(apex_m, float(t0), float(v), sigma_v, rms, n)


def fit_hyperbola(
    x_m: np.ndarray, t_ns: np.ndarray, apex_guess_m: float, *, search_m: float = 0.25
) -> HyperbolaFit:
    """Fit t(x) to points; scan the apex within ``search_m`` of the guess."""
    x_m = np.asarray(x_m, dtype=float)
    t_ns = np.asarray(t_ns, dtype=float)
    if x_m.shape != t_ns.shape or x_m.ndim != 1:
        raise ValueError("Positions and times must be two lists of the same length.")
    if x_m.size < 3:
        raise ValueError(
            f"A velocity fit needs at least 3 points; got {x_m.size}. "
            "Click more points along the hyperbola."
        )
    if not (np.all(np.isfinite(x_m)) and np.all(np.isfinite(t_ns))):
        raise ValueError("Every point must have a finite position and time.")
    if np.any(t_ns <= 0.0):
        raise ValueError(
            "Every point's time must be positive; a hyperbola is fitted to "
            "two-way times measured from the surface."
        )
    if np.ptp(x_m) == 0.0:
        raise ValueError(
            "All points are at the same position along the profile, so there is "
            "no hyperbola shape to fit. Click points either side of the apex."
        )

    if search_m > 0.0:
        apexes = np.linspace(apex_guess_m - search_m, apex_guess_m + search_m, _SEARCH_STEPS)
    else:
        apexes = np.array([apex_guess_m])
    fits = [f for a in apexes if (f := _solve(x_m, t_ns, float(a))) is not None]
    if not fits:
        raise ValueError(
            "These points open upward (time falls away from the apex) or give a "
            "non-physical hyperbola, so no velocity can be fitted. Check that "
            "the points follow a diffraction, not a flat reflector."
        )
    best = min(fits, key=lambda f: f.rms_ns)
    if best.v_m_ns > C_M_PER_NS:
        raise ValueError(
            f"The fitted velocity, {best.v_m_ns:.3f} m/ns, exceeds the speed of "
            f"light in air (C_M_PER_NS = {C_M_PER_NS:.3f} m/ns); the points are "
            "too flat to be a diffraction hyperbola."
        )
    return best
