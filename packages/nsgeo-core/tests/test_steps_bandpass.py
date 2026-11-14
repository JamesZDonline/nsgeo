from __future__ import annotations

import nsgeo.processing.bandpass  # noqa: F401
import numpy as np
import pytest
from nsgeo.processing.bandpass import Bandpass
from nsgeo.processing.base import Radargram, build_step

from tests.real_data import DATA, real_radargram

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


def test_rejects_negative_taper_frac():
    with pytest.raises(ValueError, match="taper_frac"):
        build_step("bandpass", low_mhz=150.0, high_mhz=600.0, taper_frac=-0.1).apply(tone(300.0))


def test_mask_has_hard_edges_at_zero_taper_and_ramps_otherwise():
    freqs = np.linspace(0, 1000, 10001)

    brick = Bandpass(low_mhz=200.0, high_mhz=600.0, taper_frac=0.0)
    mask = brick._mask(freqs)
    assert set(np.unique(mask)) == {0.0, 1.0}

    tapered = Bandpass(low_mhz=200.0, high_mhz=600.0, taper_frac=0.25)
    mask = tapered._mask(freqs)
    width = 0.25 * (600.0 - 200.0)

    def at(freq_mhz):
        idx = np.where(freqs == freq_mhz)[0][0]
        return mask[idx]

    assert at(200.0) == pytest.approx(1.0)
    assert at(600.0) == pytest.approx(1.0)
    assert at(200.0 - width) == pytest.approx(0.0)
    assert at(600.0 + width) == pytest.approx(0.0)

    ramp_idx = (freqs > 200.0 - width) & (freqs < 200.0)
    ramp = mask[ramp_idx]
    assert np.all(np.diff(ramp) > 0)


@pytest.mark.parametrize("low", [100.0, 50.0])
def test_a_low_edge_below_the_taper_width_still_removes_dc(low):
    """#117. At 100-600 the taper is 125 MHz wide, so a ramp of full width
    would start at -25 MHz and still pass 9.5% at DC (71% at 50-600). The
    ramp is narrowed to run from 0 MHz up to Low instead."""
    freqs = np.linspace(0, 1000, 10001)
    mask = Bandpass(low_mhz=low, high_mhz=600.0, taper_frac=0.25)._mask(freqs)
    assert mask[0] == 0.0
    ramp = mask[(freqs > 0.0) & (freqs < low)]
    assert np.all(np.diff(ramp) > 0) and ramp[0] > 0.0 and ramp[-1] < 1.0
    assert mask[freqs == low][0] == pytest.approx(1.0)


def test_a_constant_offset_does_not_survive_a_low_edge_below_the_taper_width():
    """What #117 looked like: real files sit about -300 counts off zero, and
    with Low at 100 MHz a tenth of that offset came through (a constant 1000
    came out at ~108), a grey cast in the quiet rows once AGC gains them."""
    rg = Radargram(data=np.full((463, 3), 1000.0), dt_ns=0.2165, t0_ns=0.0)
    out = build_step("bandpass", low_mhz=100.0, high_mhz=600.0).apply(rg).data
    middle = out[rg.n_samples // 4 : 3 * rg.n_samples // 4]
    assert np.abs(middle).max() < 1.0


def cropped_direct_wave(n_samples=463, dt_ns=0.2165, freq_mhz=350.0, peak_ns=1.5):
    """What time_zero leaves on a real HS350 line: a record that opens partway
    up a direct wave of ~1e6 counts and is otherwise quiet. Real late-time
    signal is ~2e3 counts, so 1e-3 of the peak is the level it lives at."""
    t = np.arange(n_samples) * dt_ns - peak_ns
    a = (np.pi * freq_mhz * 1e-3 * t) ** 2
    wave = 1e6 * (1.0 - 2.0 * a) * np.exp(-a)  # Ricker
    return Radargram(data=np.tile(wave[:, None], (1, 3)), dt_ns=dt_ns, t0_ns=0.0)


@pytest.mark.parametrize(("low", "high"), [(250.0, 750.0), (200.0, 600.0), (100.0, 600.0)])
def test_the_direct_wave_does_not_wrap_into_the_bottom_of_the_trace(low, high):
    """An unpadded FFT filters each trace as one period of a repeating
    signal, so the response to the record's opening edge lands half at the
    top and half at the bottom. On real lines that put 2-3% of the direct
    wave into the last 15% of the record, over ten times the real signal
    there, and AGC then gained it to full strength."""
    out = build_step("bandpass", low_mhz=low, high_mhz=high).apply(cropped_direct_wave()).data
    n = out.shape[0]
    bottom = out[n - (15 * n) // 100 :]
    assert np.sqrt((bottom**2).mean()) < 1e-4 * np.abs(out).max()


def test_refuses_a_real_line_holding_a_nan():
    """An FFT spreads one NaN along its whole trace."""
    rg = real_radargram(DATA / "FILE__007.DZT")
    data = rg.data.copy()
    data[100, 300] = np.nan
    with pytest.raises(
        ValueError,
        match=(
            "1 of 635 traces hold samples that are not finite; "
            "the filter would spread each one along its whole trace"
        ),
    ):
        build_step("bandpass", low_mhz=250.0, high_mhz=750.0).apply(rg.replace(data=data))
