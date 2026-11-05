"""FFT bandpass with cosine-tapered passband edges.

scipy.signal.butter plus filtfilt is the textbook route. An FFT bandpass is
equally valid *provided* two things hold. The passband edges are tapered: a
brick-wall filter rings, and that ringing can be mistaken for real
stratigraphy. And each trace is zero-padded: an unpadded FFT convolves
circularly, wrapping the direct wave into the bottom of the trace.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from nsgeo.processing.base import REQUIRED, ParamSpec, Radargram, nyquist_mhz, register


@register
class Bandpass:
    name = "bandpass"
    title = "Bandpass"
    group = "Filters"
    order = 2

    def __init__(self, low_mhz: float, high_mhz: float, taper_frac: float = 0.25) -> None:
        self.low_mhz = low_mhz
        self.high_mhz = high_mhz
        self.taper_frac = taper_frac

    @property
    def params(self) -> dict[str, Any]:
        return {
            "low_mhz": self.low_mhz,
            "high_mhz": self.high_mhz,
            "taper_frac": self.taper_frac,
        }

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(
                name="low_mhz",
                kind="float",
                label="Low",
                default=REQUIRED,
                unit="MHz",
                min=0.0,
                help="No default: a wrong passband silently filters real data.",
            ),
            ParamSpec(
                name="high_mhz",
                kind="float",
                label="High",
                default=REQUIRED,
                unit="MHz",
                min=0.0,
                help="Must be below the Nyquist frequency of the radargram.",
            ),
            ParamSpec(
                name="taper_frac",
                kind="float",
                label="Taper",
                default=0.25,
                min=0.0,
                help="Cosine taper width as a fraction of the passband.",
            ),
        )

    def _mask(self, freqs_mhz: np.ndarray) -> np.ndarray:
        width = self.taper_frac * (self.high_mhz - self.low_mhz)
        lo_stop, lo_pass = self.low_mhz - width, self.low_mhz
        hi_pass, hi_stop = self.high_mhz, self.high_mhz + width

        mask = np.zeros_like(freqs_mhz)
        mask[(freqs_mhz >= lo_pass) & (freqs_mhz <= hi_pass)] = 1.0

        if width > 0:
            rising = (freqs_mhz > lo_stop) & (freqs_mhz < lo_pass)
            x = (freqs_mhz[rising] - lo_stop) / width
            mask[rising] = 0.5 * (1.0 - np.cos(np.pi * x))

            falling = (freqs_mhz > hi_pass) & (freqs_mhz < hi_stop)
            x = (freqs_mhz[falling] - hi_pass) / width
            mask[falling] = 0.5 * (1.0 + np.cos(np.pi * x))
        return mask

    def apply(self, rg: Radargram) -> Radargram:
        nyquist = nyquist_mhz(rg.dt_ns)
        if self.taper_frac < 0:
            raise ValueError(
                f"taper_frac must be >= 0, got {self.taper_frac}; a negative taper is a brick "
                f"wall, which is the ringing this filter exists to avoid"
            )
        if self.low_mhz < 0:
            raise ValueError(f"low_mhz must be >= 0, got {self.low_mhz}")
        if self.low_mhz >= self.high_mhz:
            raise ValueError(f"low_mhz ({self.low_mhz}) must be below high_mhz ({self.high_mhz})")
        if self.high_mhz > nyquist:
            raise ValueError(
                f"high_mhz ({self.high_mhz}) exceeds the Nyquist frequency "
                f"({nyquist:.1f} MHz) for a {rg.dt_ns} ns sample interval"
            )

        # Zero-pad to at least twice the trace. Unpadded, the FFT filters each
        # trace as one period of a repeating signal: the response to the
        # record's opening edge (time_zero crops partway up the direct wave)
        # wraps into the last rows, where late-time signal is a thousandth of
        # the direct wave and AGC gains whatever is there to full strength.
        n = rg.n_samples
        n_fft = 1 << (2 * n - 1).bit_length()
        spectrum = np.fft.rfft(rg.data, n=n_fft, axis=0)
        freqs_mhz = np.fft.rfftfreq(n_fft, d=rg.dt_ns * 1e-9) / 1e6
        filtered = spectrum * self._mask(freqs_mhz)[:, None]
        return rg.replace(data=np.fft.irfft(filtered, n=n_fft, axis=0)[:n])
