"""Turn one channel of raw samples into the binned envelope the measurement compares.

The processing is fixed and is not the user's display stack: migration or a
gain would move energy around, and the measurement must not depend on what the
user chose to look at (design call C2). Dewow, background removal and the
analytic envelope are the `nsgeo.processing` steps; averaging 8 samples into
each time bin keeps the later resampling cheap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nsgeo.processing.amplitude import analytic_envelope
from nsgeo.processing.base import Radargram, build_step

DEWOW_NS = 4.0
BIN_SAMPLES = 8


@dataclass(frozen=True, eq=False)
class EnvelopeBins:
    """Envelope averaged into time bins. Equality is identity: it holds arrays."""

    data: np.ndarray  # (n_bins, n_traces) float32
    t0_ns: float  # centre time of bin 0, header clock
    dt_ns: float  # time between bin centres

    @property
    def t_ns(self) -> np.ndarray:
        return self.t0_ns + self.dt_ns * np.arange(self.data.shape[0])


def envelope_bins(samples: np.ndarray, dt_ns: float, t0_ns: float) -> EnvelopeBins:
    """One channel's raw samples (n_samples, n_traces) as binned envelope.

    Dewow `DEWOW_NS`, background mean removal, analytic envelope, then the mean
    of each `BIN_SAMPLES` rows. A partial last bin is dropped. `t0_ns` is the
    time of the first sample; the result's own `t0_ns` is the centre of bin 0.
    """
    rg = Radargram(data=np.asarray(samples, dtype=float), dt_ns=dt_ns, t0_ns=t0_ns)
    rg = build_step("background_mean").apply(build_step("dewow", window_ns=DEWOW_NS).apply(rg))
    env = analytic_envelope(rg.data)
    n_bins = env.shape[0] // BIN_SAMPLES
    binned = env[: n_bins * BIN_SAMPLES].reshape(n_bins, BIN_SAMPLES, -1).mean(axis=1)
    return EnvelopeBins(
        data=binned.astype(np.float32),
        t0_ns=t0_ns + (BIN_SAMPLES - 1) / 2 * dt_ns,
        dt_ns=BIN_SAMPLES * dt_ns,
    )
