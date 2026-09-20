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

from nsgeo.processing.base import ParamSpec, Radargram, register


def analytic_envelope(data: np.ndarray) -> np.ndarray:
    """Hilbert analytic-signal modulus along axis 0. numpy only, no scipy.

    The analytic signal is built by doubling the positive frequencies of a
    full FFT and zeroing the negative half; its modulus is the envelope.

    The FFT is taken at the array's own length and is **never zero-padded
    to a faster one**. After `time_zero` the real files leave 463 rows,
    which is prime and therefore the worst case for an FFT -- padding to
    480 is 2.2x faster and was measured and rejected, because the Hilbert
    transform is non-local: padding shifts the result by ~1.3% through the
    interior and ~13% in the last rows. This step runs once per line in the
    cached tier, so exactness is the better trade. (Reflect-padding is
    worse than zero-padding here, at ~2.6% interior, not better.)
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError(f"expected a 2-D radargram, got shape {data.shape}")
    n = data.shape[0]
    spectrum = np.fft.fft(data, axis=0)
    weights = np.zeros(n)
    weights[0] = 1.0
    if n % 2 == 0:
        weights[n // 2] = 1.0
        weights[1 : n // 2] = 2.0
    else:
        weights[1 : (n + 1) // 2] = 2.0
    return np.abs(np.fft.ifft(spectrum * weights[:, None], axis=0))


class _NoParams:
    """Shared shape for the three transforms: no parameters, no choices."""

    unipolar = True

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

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=np.abs(rg.data))


@register
class AmpSquare(_NoParams):
    name = "amp_square"

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=rg.data * rg.data)


@register
class AmpEnvelope(_NoParams):
    name = "amp_envelope"

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=analytic_envelope(rg.data))
