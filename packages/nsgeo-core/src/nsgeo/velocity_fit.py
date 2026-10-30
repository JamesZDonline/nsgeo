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
from typing import Any

import numpy as np

from nsgeo.velocity import C_M_PER_NS

__all__ = ["HyperbolaFit", "StoredFit", "fit_hyperbola", "hyperbola_time"]

_SEARCH_STEPS = 101


@dataclass(frozen=True)
class HyperbolaFit:
    apex_x_m: float
    t0_ns: float
    v_m_ns: float
    v_stderr_m_ns: float
    rms_ns: float
    n_points: int


@dataclass(frozen=True)
class StoredFit:
    """A fit as persisted: trace indices, not metres, and the clicked points.

    A fitted hyperbola measures the RMS velocity down to its own reflector, so
    several fits at several depths are the raw input to a later Dix conversion.
    The (t0, v) pair and the points are kept for that, not just a velocity.
    """

    t0_ns: float
    v_m_ns: float
    v_stderr_m_ns: float
    rms_ns: float
    apex_trace: int
    points: tuple[tuple[int, float], ...]  # (trace index, two-way time ns)
    fitted_at: str  # ISO-8601 UTC

    def to_dict(self) -> dict[str, Any]:
        return {
            "t0_ns": self.t0_ns,
            "v_m_ns": self.v_m_ns,
            "v_stderr_m_ns": self.v_stderr_m_ns,
            "rms_ns": self.rms_ns,
            "apex_trace": self.apex_trace,
            "points": [[trace, t_ns] for trace, t_ns in self.points],
            "fitted_at": self.fitted_at,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> StoredFit:
        return cls(
            t0_ns=float(doc["t0_ns"]),
            v_m_ns=float(doc["v_m_ns"]),
            v_stderr_m_ns=float(doc["v_stderr_m_ns"]),
            rms_ns=float(doc["rms_ns"]),
            apex_trace=int(doc["apex_trace"]),
            points=tuple((int(trace), float(t_ns)) for trace, t_ns in doc["points"]),
            fitted_at=str(doc["fitted_at"]),
        )


def hyperbola_time(fit: HyperbolaFit, x_m: Any) -> np.ndarray:
    """Two-way time in ns of the fitted hyperbola at positions ``x_m``.

    The one statement of the model outside the solver, so a drawn curve
    cannot drift from the fit it draws.
    """
    dx = np.asarray(x_m, dtype=float) - fit.apex_x_m
    return np.sqrt(fit.t0_ns**2 + (4.0 / fit.v_m_ns**2) * dx**2)


def _solve(x_m: np.ndarray, t_ns: np.ndarray, apex_m: float, dof: int) -> HyperbolaFit | str:
    """Solve at a fixed apex; a reason string when no physical hyperbola results.

    Squaring a time with constant error gives var(t^2) ~ (2 t sigma_t)^2, so
    rows are weighted by 1/(2t) to make the errors in y = t^2 even. Without
    that, the covariance below would understate sigma on late (high-leverage)
    points.
    """
    n = x_m.size
    dx2 = (x_m - apex_m) ** 2
    design = np.column_stack([np.ones_like(dx2), dx2])
    y = t_ns**2
    sqrt_w = 1.0 / (2.0 * t_ns)
    design_w = design * sqrt_w[:, None]
    y_w = y * sqrt_w
    coef, _, rank, _ = np.linalg.lstsq(design_w, y_w, rcond=None)
    if rank < 2:
        return "singular"
    intercept, slope = float(coef[0]), float(coef[1])
    if not (np.isfinite(intercept) and np.isfinite(slope)):
        return "nonphysical"
    if intercept <= 0.0 or slope <= 0.0:
        return "nonphysical"
    t0 = np.sqrt(intercept)
    v = 2.0 / np.sqrt(slope)
    s2 = float(np.sum((y_w - design_w @ coef) ** 2)) / dof
    cov = s2 * np.linalg.inv(design_w.T @ design_w)
    sigma_v = float(np.sqrt(cov[1, 1])) / slope**1.5
    rms = float(np.sqrt(np.mean((t_ns - np.sqrt(t0**2 + slope * dx2)) ** 2)))
    if not all(np.isfinite([t0, v, sigma_v, rms])):
        return "nonphysical"
    return HyperbolaFit(apex_m, float(t0), float(v), sigma_v, rms, n)


def fit_hyperbola(
    x_m: np.ndarray, t_ns: np.ndarray, apex_guess_m: float, *, search_m: float = 0.25
) -> HyperbolaFit:
    """Fit t(x) to points; scan the apex within ``search_m`` of the guess."""
    x_m = np.asarray(x_m, dtype=float)
    t_ns = np.asarray(t_ns, dtype=float)
    if x_m.ndim != 1 or t_ns.ndim != 1:
        raise ValueError("Positions and times must each be a one-dimensional list.")
    if x_m.shape != t_ns.shape:
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
    if not np.isfinite(apex_guess_m):
        raise ValueError("The apex guess must be a finite position along the profile.")
    if not np.isfinite(search_m) or search_m < 0.0:
        raise ValueError(
            f"The apex search distance must be zero or a positive length; got {search_m}."
        )
    if np.ptp(x_m) == 0.0:
        raise ValueError(
            "All points are at the same position along the profile, so there is "
            "no hyperbola shape to fit. Click points either side of the apex."
        )

    searched = search_m > 0.0
    if searched:
        if x_m.size < 4:
            raise ValueError(
                "Searching for the apex fits three unknowns, so it needs at least "
                f"4 points; got {x_m.size}. Click another point."
            )
        apexes = np.linspace(apex_guess_m - search_m, apex_guess_m + search_m, _SEARCH_STEPS)
    else:
        apexes = np.array([apex_guess_m])
    dof = x_m.size - (3 if searched else 2)
    results = [_solve(x_m, t_ns, float(a), dof) for a in apexes]
    fits = [r for r in results if isinstance(r, HyperbolaFit)]
    if not fits:
        if "singular" in results:
            raise ValueError(
                "These points are all the same distance from the apex, so they "
                "give no lever arm to measure the hyperbola's curvature. Click "
                "points at a range of distances from the apex."
            )
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
