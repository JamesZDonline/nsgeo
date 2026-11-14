"""Planted diffraction hyperbolas, built to mirror the real campus lines.

The constants below describe the instrument, not a site. They were measured on
``tests/data/local/FILE__003.DZT`` (350 MHz antenna) after the stack
``time_zero`` -> ``dewow`` -> ``background_mean``:

- ``REAL_DT_NS``: the header's sample interval (range / samples).
- ``REAL_DX_M``: 1 / ``traces_per_metre`` (60 per metre).
- ``REAL_PERIOD_NS``: 1 / the frequency of the peak of the mean (over traces)
  amplitude spectrum, DC excluded.
- ``REAL_NOISE_RATIO``: the standard deviation of the deepest 150 samples (no
  reflections left) divided by the median, over traces, of each trace's peak
  |amplitude| deeper than 10 ns. A diffraction is a typical reflection, not the
  file's single strongest sample (that reference gives 0.00115).

Two more describe the ground around the author's saved hand fits (#140). They
were measured in the boxes the hand-fit tests draw, on the lines as the saved
stacks leave them:

- ``REAL_LAYER_RATIO``: the median peak of the laterally coherent energy
  beside a hyperbola (the row mean over 20 traces either side of the box),
  divided by the hyperbola's apex peak. Its peaks come about every half
  period, so layers are planted a period apart with alternating sign.
- ``REAL_LEG_FADE``: the band's peak at the last clicked dot of a leg, divided
  by its peak at the apex (median; the quartiles are 0.32 and 0.63). Plant it
  with ``Planted.leg_fade_m`` set by ``leg_fade_width``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

REAL_DT_NS = 0.2165
REAL_DX_M = 1.0 / 60.0
REAL_PERIOD_NS = 3.13
REAL_NOISE_RATIO = 0.0054
REAL_LAYER_RATIO = 0.35
REAL_LEG_FADE = 0.45

__all__ = [
    "REAL_DT_NS",
    "REAL_DX_M",
    "REAL_LAYER_RATIO",
    "REAL_LEG_FADE",
    "REAL_NOISE_RATIO",
    "REAL_PERIOD_NS",
    "Planted",
    "leg_fade_width",
    "plant",
    "real_layers",
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


def leg_fade_width(half_extent_m: float, ratio: float = REAL_LEG_FADE) -> float:
    """The ``Planted.leg_fade_m`` that leaves ``ratio`` of the apex's
    amplitude at ``half_extent_m`` from the apex."""
    return half_extent_m / float(np.sqrt(-2.0 * np.log(ratio)))


def real_layers(
    n_samples: int,
    first_ns: float,
    dt_ns: float = REAL_DT_NS,
    period_ns: float = REAL_PERIOD_NS,
    ratio: float = REAL_LAYER_RATIO,
) -> list[tuple[float, float]]:
    """Flat layers down the whole record from ``first_ns``, a period apart
    with alternating sign, each ``ratio`` of a hyperbola's apex amplitude.
    The times are the layers' onsets, as ``plant`` takes them."""
    starts = np.arange(first_ns, n_samples * dt_ns, period_ns)
    return [(float(t), ratio * (-1.0) ** k) for k, t in enumerate(starts)]


@dataclass(frozen=True)
class Planted:
    apex_trace: int
    t0_ns: float
    v_m_ns: float
    amplitude: float = 1.0
    fade_from_trace: int | None = None
    #: The amplitude falls as exp(-((x - x0) / leg_fade_m)^2 / 2) down the legs.
    leg_fade_m: float | None = None


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
    layers: list[tuple[float, float]] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(data, times_ns, distance_m): data is (n_samples, n_traces).

    Each hyperbola's wavelet is placed so its 0.2 onset lies exactly on
    t(x) = sqrt(t0^2 + 4 (x - x0)^2 / v^2). ``layers`` are flat reflectors,
    (onset time, amplitude), with the same wavelet across every trace. Noise
    is Gaussian with a standard deviation of ``noise_ratio`` times 1.0.
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
        if h.leg_fade_m is not None:
            amp = amp * np.exp(-0.5 * ((distance_m - x0) / h.leg_fade_m) ** 2)
        data += amp[None, :] * ricker(times[:, None] - centre[None, :], period_ns)
    for onset_ns, amplitude in layers or []:
        centre_ns = onset_ns + _LEAD_PERIODS * period_ns - onset
        data += amplitude * ricker(times - centre_ns, period_ns)[:, None]
    rng = np.random.default_rng(seed)
    data += rng.normal(0.0, noise_ratio, data.shape)
    return data, times, distance_m
