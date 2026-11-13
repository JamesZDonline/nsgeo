"""Planted diffraction hyperbolas, built to mirror the real campus lines.

The constants below describe the instrument, not a site. They were measured on
``tests/data/local/FILE__003.DZT`` (350 MHz antenna) after the stack
``time_zero`` -> ``dewow`` -> ``background_mean``:

- ``REAL_DT_NS``: the header's sample interval (range / samples).
- ``REAL_DX_M``: 1 / ``traces_per_metre`` (60 per metre).
- ``REAL_PERIOD_NS``: 1 / the frequency of the peak of the mean (over traces)
  amplitude spectrum, DC excluded.
- ``REAL_NOISE_RATIO``: the standard deviation of the deepest 150 samples (no
  reflections left) divided by the peak |amplitude| deeper than 10 ns
  (the reflections, not the ground wave).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

REAL_DT_NS = 0.2165
REAL_DX_M = 1.0 / 60.0
REAL_PERIOD_NS = 3.13
REAL_NOISE_RATIO = 0.00115

__all__ = [
    "REAL_DT_NS",
    "REAL_DX_M",
    "REAL_NOISE_RATIO",
    "REAL_PERIOD_NS",
    "Planted",
    "plant",
    "ricker",
    "wavelet_onset_ns",
]

# A wavelet is drawn from this many periods before its centre.
_LEAD_PERIODS = 2.0


def ricker(t_ns: np.ndarray, period_ns: float) -> np.ndarray:
    """A Ricker wavelet centred on 0 whose spectrum peaks at 1/period_ns."""
    a = (np.pi * np.asarray(t_ns, dtype=float) / period_ns) ** 2
    return (1.0 - 2.0 * a) * np.exp(-a)


def wavelet_onset_ns(period_ns: float, fraction: float = 0.2) -> float:
    """Time from a Ricker wavelet's start to where |amplitude| first reaches
    ``fraction`` of its peak. The start is two periods before the centre."""
    t = np.arange(-_LEAD_PERIODS * period_ns, 0.0, period_ns / 20000.0)
    w = np.abs(ricker(t, period_ns))
    # The Ricker's peak is 1.0, at the centre.
    k = int(np.flatnonzero(w >= fraction)[0])
    return float(t[k] + _LEAD_PERIODS * period_ns)


@dataclass(frozen=True)
class Planted:
    apex_trace: int
    t0_ns: float
    v_m_ns: float
    amplitude: float = 1.0
    fade_from_trace: int | None = None


def plant(
    n_traces: int,
    n_samples: int,
    hyperbolas: list[Planted],
    *,
    noise_ratio: float,
    seed: int,
    dx_m: float = REAL_DX_M,
    dt_ns: float = REAL_DT_NS,
    distance_m: np.ndarray | None = None,
    period_ns: float = REAL_PERIOD_NS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(data, times_ns, distance_m): data is (n_samples, n_traces).

    Each hyperbola's wavelet is placed so its 0.2 onset lies exactly on
    t(x) = sqrt(t0^2 + 4 (x - x0)^2 / v^2). Noise is Gaussian with a standard
    deviation of ``noise_ratio`` times 1.0.
    """
    if distance_m is None:
        distance_m = np.arange(n_traces) * dx_m
    distance_m = np.asarray(distance_m, dtype=float)
    times = np.arange(n_samples) * dt_ns
    onset = wavelet_onset_ns(period_ns, 0.2)
    data = np.zeros((n_samples, n_traces))
    for h in hyperbolas:
        x0 = distance_m[h.apex_trace]
        t_edge = np.sqrt(h.t0_ns**2 + 4.0 * (distance_m - x0) ** 2 / h.v_m_ns**2)
        centre = t_edge + _LEAD_PERIODS * period_ns - onset
        amp = np.full(n_traces, h.amplitude)
        if h.fade_from_trace is not None:
            k = np.abs(np.arange(n_traces) - h.apex_trace)
            amp = amp * np.clip(1.0 - (k - h.fade_from_trace) / 10.0, 0.0, 1.0)
        data += amp[None, :] * ricker(times[:, None] - centre[None, :], period_ns)
    rng = np.random.default_rng(seed)
    data += rng.normal(0.0, noise_ratio, data.shape)
    return data, times, distance_m
