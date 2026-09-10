from __future__ import annotations

import nsgeo.processing.bandpass  # noqa: F401
import numpy as np
import pytest
from nsgeo.processing.base import Radargram, build_step

DT_NS = 0.2  # 5 GHz sampling -> 2500 MHz Nyquist


def tone(freq_mhz, n_samples=1024, n_traces=4, dt_ns=DT_NS):
    t_ns = np.arange(n_samples) * dt_ns
    sig = np.sin(2 * np.pi * freq_mhz * 1e6 * t_ns * 1e-9)
    return Radargram(data=np.tile(sig[:, None], (1, n_traces)), dt_ns=dt_ns, t0_ns=0.0)


def amplitude(rg):
    mid = slice(rg.n_samples // 4, 3 * rg.n_samples // 4)
    return float(np.abs(rg.data[mid]).max())


def test_passes_an_in_band_tone():
    rg = tone(350.0)
    out = build_step("bandpass", low_mhz=150.0, high_mhz=600.0).apply(rg)
    assert amplitude(out) > 0.8 * amplitude(rg)


def test_attenuates_a_tone_below_the_band():
    rg = tone(30.0)
    out = build_step("bandpass", low_mhz=150.0, high_mhz=600.0).apply(rg)
    assert amplitude(out) < 0.1 * amplitude(rg)


def test_attenuates_a_tone_above_the_band():
    rg = tone(1500.0)
    out = build_step("bandpass", low_mhz=150.0, high_mhz=600.0).apply(rg)
    assert amplitude(out) < 0.1 * amplitude(rg)


def test_tapering_reduces_ringing_versus_a_brick_wall():
    """The reason the taper exists: brick-wall ringing looks like stratigraphy."""
    data = np.zeros((1024, 1))
    data[512, 0] = 1.0  # impulse
    rg = Radargram(data=data, dt_ns=DT_NS, t0_ns=0.0)
    brick = build_step("bandpass", low_mhz=150.0, high_mhz=600.0, taper_frac=0.0).apply(rg)
    tapered = build_step("bandpass", low_mhz=150.0, high_mhz=600.0, taper_frac=0.5).apply(rg)
    far = np.r_[0:400, 624:1024]  # away from the main lobe
    assert np.abs(tapered.data[far, 0]).sum() < np.abs(brick.data[far, 0]).sum()


def test_preserves_shape_and_time_axis():
    rg = tone(350.0, n_samples=512, n_traces=7)
    out = build_step("bandpass", low_mhz=150.0, high_mhz=600.0).apply(rg)
    assert out.data.shape == rg.data.shape
    assert out.dt_ns == rg.dt_ns and out.t0_ns == rg.t0_ns


def test_rejects_low_above_high():
    with pytest.raises(ValueError, match="low_mhz"):
        build_step("bandpass", low_mhz=600.0, high_mhz=150.0).apply(tone(300.0))


def test_rejects_high_above_nyquist():
    """Nyquist here is 2500 MHz; asking for more is a user error worth naming."""
    with pytest.raises(ValueError, match="Nyquist"):
        build_step("bandpass", low_mhz=150.0, high_mhz=9000.0).apply(tone(300.0))


def test_rejects_negative_low():
    with pytest.raises(ValueError, match="low_mhz"):
        build_step("bandpass", low_mhz=-5.0, high_mhz=600.0).apply(tone(300.0))


def test_output_is_real_valued():
    out = build_step("bandpass", low_mhz=150.0, high_mhz=600.0).apply(tone(350.0))
    assert np.isrealobj(out.data)
