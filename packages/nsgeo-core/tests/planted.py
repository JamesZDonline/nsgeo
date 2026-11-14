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

``REAL_WAVELET`` is the reflected wavelet those hyperbolas carry, as a
dimensionless shape sampled at ``REAL_DT_NS``. It was measured on the six
hand-fit hyperbolas whose traced and hand fits agreed before the zero-crossing
edge (#140), on the lines as their saved stacks leave them (Migration and the
amplitude transforms off):

1. Each line was stacked along the tracer's scan curve for its hyperbola: the
   mean, over the box's traces, of the trace read at the curve's time plus each
   lag, every row of the line read.
2. Each stack was scaled to a peak of 1, aligned to their mean by
   cross-correlation (band-limited, to 1/16 sample) and averaged.
3. The mean was scaled to a peak of 1, cut to 24 samples either side of its
   peak and tapered to zero over its outer 5 samples.

Its lobes, in order: two faint ones (0.09, -0.06), the faint precursor (0.21),
the first strong lobe (-0.69), the peak (1.00), then -0.66 and 0.26. Its
dominant period is 3.04 ns. The tracer marks the zero crossing into the first
strong lobe (spec §4.2), and ``plant`` puts that crossing on t(x).

``ricker`` stays for the tests that need an exact analytic wavelet.
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
REAL_WAVELET = np.array(
    [
        0.000, 0.018, 0.064, 0.087, 0.054, -0.010, -0.054, -0.063, -0.033, 0.030,
        0.110, 0.180, 0.208, 0.168, 0.044, -0.155, -0.392, -0.596, -0.685, -0.596,
        -0.315, 0.102, 0.541, 0.876, 1.000, 0.880, 0.566, 0.161, -0.228, -0.515,
        -0.659, -0.663, -0.561, -0.397, -0.209, -0.033, 0.111, 0.210, 0.259, 0.263,
        0.232, 0.177, 0.113, 0.053, 0.005, -0.017, -0.015, -0.005, 0.000,
    ]
)  # fmt: skip
#: A lobe is strong when its peak is at least this fraction of the wavelet's.
STRONG_LOBE = 0.5

__all__ = [
    "REAL_DT_NS",
    "REAL_DX_M",
    "REAL_LAYER_RATIO",
    "REAL_LEG_FADE",
    "REAL_NOISE_RATIO",
    "REAL_PERIOD_NS",
    "REAL_WAVELET",
    "STRONG_LOBE",
    "Planted",
    "leg_fade_width",
    "plant",
    "real_layers",
    "ricker",
    "wavelet_at",
    "wavelet_edge_ns",
    "wavelet_precursor_ns",
]


def ricker(t_ns: np.ndarray, period_ns: float) -> np.ndarray:
    """A Ricker wavelet centred on 0 whose spectrum peaks at 1/period_ns."""
    a = (np.pi * np.asarray(t_ns, dtype=float) / period_ns) ** 2
    return (1.0 - 2.0 * a) * np.exp(-a)


def wavelet_at(
    t_ns: np.ndarray, wavelet: np.ndarray = REAL_WAVELET, dt_ns: float = REAL_DT_NS
) -> np.ndarray:
    """``wavelet`` (samples ``dt_ns`` apart, its first at 0 ns) read at any
    time by band-limited (sinc) interpolation; 0 outside its samples."""
    w = np.asarray(wavelet, dtype=float)
    u = np.asarray(t_ns, dtype=float) / dt_ns
    out = np.sinc(u[..., None] - np.arange(w.size)) @ w
    return np.where((u > -1.0) & (u < w.size), out, 0.0)


def _lobe_crossings(wavelet: np.ndarray, dt_ns: float) -> tuple[list[float], list[float]]:
    """(times, |peaks|) of each lobe that starts with a zero crossing, read on a
    grid a thousandth of a sample apart."""
    t = np.arange(0.0, (len(wavelet) - 1) * dt_ns, dt_ns / 1000.0)
    w = wavelet_at(t, wavelet, dt_ns)
    sign = np.sign(w)
    starts = np.flatnonzero((sign[1:] != sign[:-1]) & (sign[1:] != 0)) + 1
    ends = [*starts[1:], w.size]
    times = [float(t[j - 1] + w[j - 1] / (w[j - 1] - w[j]) * (t[j] - t[j - 1])) for j in starts]
    peaks = [float(np.abs(w[j:k]).max()) for j, k in zip(starts, ends)]
    return times, peaks


def wavelet_edge_ns(
    wavelet: np.ndarray = REAL_WAVELET, dt_ns: float = REAL_DT_NS, strong: float = STRONG_LOBE
) -> float:
    """Time from the wavelet's first sample to its zero crossing into its first
    lobe at least ``strong`` of its peak: the edge the tracer marks."""
    times, peaks = _lobe_crossings(wavelet, dt_ns)
    top = max(peaks)
    return next(t for t, p in zip(times, peaks) if p >= strong * top)


def wavelet_precursor_ns(
    wavelet: np.ndarray = REAL_WAVELET, dt_ns: float = REAL_DT_NS, strong: float = STRONG_LOBE
) -> float:
    """Time from the wavelet's first sample to its zero crossing into the lobe
    just ahead of the first strong one (the faint precursor)."""
    times, _ = _lobe_crossings(wavelet, dt_ns)
    edge = wavelet_edge_ns(wavelet, dt_ns, strong)
    return max(t for t in times if t < edge)


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
    The times are the layers' edges, as ``plant`` takes them."""
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
    wavelet: np.ndarray = REAL_WAVELET,
    layers: list[tuple[float, float]] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(data, times_ns, distance_m): data is (n_samples, n_traces).

    ``wavelet`` is sampled ``REAL_DT_NS`` apart. Each hyperbola's wavelet is
    placed so its edge (``wavelet_edge_ns``: the zero crossing into its first
    strong lobe) lies exactly on t(x) = sqrt(t0^2 + 4 (x - x0)^2 / v^2).
    ``layers`` are flat reflectors, (edge time, amplitude), with the same
    wavelet across every trace. Noise is Gaussian with a standard deviation of
    ``noise_ratio`` times 1.0.
    """
    if distance_m is None:
        distance_m = np.arange(n_traces) * dx_m
    distance_m = np.asarray(distance_m, dtype=float)
    times = np.arange(n_samples) * dt_ns
    edge = wavelet_edge_ns(wavelet)
    data = np.zeros((n_samples, n_traces))
    for h in hyperbolas:
        x0 = distance_m[h.apex_trace]
        t_edge = np.sqrt(h.t0_ns**2 + 4.0 * (distance_m - x0) ** 2 / h.v_m_ns**2)
        amp = np.full(n_traces, h.amplitude)
        if h.fade_from_trace is not None:
            k = np.abs(np.arange(n_traces) - h.apex_trace)
            amp = amp * np.clip(1.0 - (k - h.fade_from_trace) / 10.0, 0.0, 1.0)
        if h.leg_fade_m is not None:
            amp = amp * np.exp(-0.5 * ((distance_m - x0) / h.leg_fade_m) ** 2)
        start = t_edge - edge  # the time of the wavelet's first sample
        data += amp[None, :] * wavelet_at(times[:, None] - start[None, :], wavelet)
    for edge_ns, amplitude in layers or []:
        data += amplitude * wavelet_at(times - (edge_ns - edge), wavelet)[:, None]
    rng = np.random.default_rng(seed)
    data += rng.normal(0.0, noise_ratio, data.shape)
    return data, times, distance_m
