"""Amplitude transforms: what a slice is actually made of.

A slice averages amplitude over a time window, and averaging a bipolar
wiggle over a window close to one wavelength gives roughly zero wherever
the reflection is strongest. So the signed radargram is transformed first:
absolute value is the cheap default, squared amplitude is the energy
measure the archaeological literature uses, and the Hilbert envelope is
the quality option.

These are registry steps rather than a hidden mode inside the binner so
that the transform can be put on a profile and looked at -- you can see on
a radargram exactly what the cube will be built from.

All three make the data unipolar, which the renderer must know: a colour
table centred on zero would spend half its range on values that cannot
occur. `unipolar = True` is what `render` consults, through
`base.is_unipolar`.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from nsgeo.processing._util import refuse_non_finite
from nsgeo.processing.base import ParamSpec, Radargram, register


def analytic_envelope(data: np.ndarray) -> np.ndarray:
    """Hilbert analytic-signal modulus along axis 0. numpy only, no scipy.

    The analytic signal is built by doubling the positive frequencies of a
    full FFT and zeroing the negative half; its modulus is the envelope.

    Each trace is zero-padded to a power of two at least **4x** its length
    (463 rows -> 2048). An FFT at the trace's own length treats the trace as
    one period of a repeating signal, so its top and bottom leak into each
    other, and the Hilbert kernel decays only as 1/t, so the leak reaches
    far: on a real line with no gain before the envelope, zeroing the top
    tenth moved the bottom 15% by 2.7-4.1x its own RMS (#116). This
    reverses an earlier decision not to pad, which had compared the
    unpadded result with a 17-row pad (463 -> 480). Both of those wrap, so
    the ~1.3% gap between them said nothing about which was right.

    Why 4x and not the bandpass's 2x: an FFT of M rows carries the kernel's
    tail as (2/M)cot(pi k/M) instead of 2/(pi k), and that falls to zero at
    k = M/2. With M >= 4N every row of the trace has k <= M/4, where the
    tail is at most 21.5% short; with M >= 2N the deepest rows lose most of
    it. Against a 64x pad on real lines, the bottom 15% of an un-gained
    envelope is 1-3% off at 4x and 6-13% off at 2x. With AGC before the
    envelope (the usual stack) both are within 0.05%. 4x costs about twice
    the unpadded time, ~50 ms for a 600-trace line, once per line in the
    cached tier.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError(f"expected a 2-D radargram, got shape {data.shape}")
    n = data.shape[0]
    n_fft = 1 << (4 * n - 1).bit_length()
    return np.abs(_analytic_signal(data, n_fft)[:n])


def _analytic_signal(data: np.ndarray, n_fft: int | None = None) -> np.ndarray:
    """The analytic signal of `data` zero-padded to `n_fft` rows (default: its
    own length, which treats each trace as one period of a repeating signal)."""
    n = data.shape[0] if n_fft is None else n_fft
    spectrum = np.fft.fft(data, n=n, axis=0)
    weights = np.zeros(n)
    weights[0] = 1.0
    if n % 2 == 0:
        weights[n // 2] = 1.0
        weights[1 : n // 2] = 2.0
    else:
        weights[1 : (n + 1) // 2] = 2.0
    return np.fft.ifft(spectrum * weights[:, None], axis=0)


class _NoParams:
    """Shared shape for the three transforms: no parameters, no choices."""

    unipolar = True
    group = "Amplitude"

    def __init__(self) -> None:
        pass

    @property
    def params(self) -> dict[str, Any]:
        return {}

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return ()


@register
class AmpAbs(_NoParams):
    name = "amp_abs"
    title = "Absolute value"
    order = 1

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=np.abs(rg.data))


@register
class AmpSquare(_NoParams):
    name = "amp_square"
    title = "Square of the amplitude"
    order = 3

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=rg.data * rg.data)


@register
class AmpEnvelope(_NoParams):
    name = "amp_envelope"
    title = "Envelope"
    order = 2

    def apply(self, rg: Radargram) -> Radargram:
        refuse_non_finite(rg.data, "the filter would spread each one along its whole trace")
        return rg.replace(data=analytic_envelope(rg.data))
