from __future__ import annotations

import nsgeo.processing.gain  # noqa: F401
import numpy as np
import pytest
from nsgeo.processing.base import Radargram, build_step


def decaying(n_samples=400, n_traces=10, dt_ns=0.25):
    t = np.arange(n_samples)[:, None]
    sig = np.sin(2 * np.pi * t / 8.0) * np.exp(-t / 80.0)
    return Radargram(data=np.tile(sig, (1, n_traces)), dt_ns=dt_ns, t0_ns=0.0)


def test_agc_equalises_amplitude_with_depth():
    rg = decaying()
    out = build_step("gain_agc", window_ns=20.0).apply(rg)
    early = np.abs(out.data[20:60]).mean()
    late = np.abs(out.data[300:340]).mean()
    assert late / early > 0.5  # was orders of magnitude smaller before


def test_agc_handles_all_zero_traces_without_dividing_by_zero():
    rg = Radargram(data=np.zeros((100, 5)), dt_ns=0.2, t0_ns=0.0)
    out = build_step("gain_agc", window_ns=10.0).apply(rg)
    assert np.isfinite(out.data).all()


def test_agc_leaves_the_time_axis_untouched():
    rg = decaying()
    out = build_step("gain_agc", window_ns=20.0).apply(rg)
    assert out.t0_ns == rg.t0_ns and out.n_samples == rg.n_samples


def test_exponential_gain_increases_with_time():
    rg = Radargram(data=np.ones((100, 3)), dt_ns=0.2, t0_ns=0.0)
    out = build_step("gain_parametric", mode="exponential", alpha=0.1).apply(rg)
    assert out.data[99, 0] > out.data[0, 0]


def test_power_gain_is_one_at_the_first_sample():
    rg = Radargram(data=np.ones((100, 3)), dt_ns=0.2, t0_ns=0.0)
    out = build_step("gain_parametric", mode="power", exponent=2.0).apply(rg)
    assert out.data[0, 0] == pytest.approx(1.0)
    assert out.data[99, 0] > 1.0


def test_parametric_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode"):
        build_step("gain_parametric", mode="wishful").apply(
            Radargram(data=np.ones((10, 2)), dt_ns=0.2, t0_ns=0.0)
        )


def test_curve_applies_decibels_as_a_linear_multiplier():
    rg = Radargram(data=np.ones((100, 3)), dt_ns=0.2, t0_ns=0.0)
    out = build_step("gain_curve", points=[[0.0, 0.0], [19.8, 20.0]]).apply(rg)
    assert out.data[0, 0] == pytest.approx(1.0)  # 0 dB
    assert out.data[99, 0] == pytest.approx(10.0)  # 20 dB


def test_curve_interpolates_linearly_in_decibels():
    rg = Radargram(data=np.ones((3, 1)), dt_ns=10.0, t0_ns=0.0)
    out = build_step("gain_curve", points=[[0.0, 0.0], [20.0, 20.0]]).apply(rg)
    assert out.data[1, 0] == pytest.approx(10 ** (10.0 / 20.0))


def test_curve_holds_end_values_outside_the_control_range():
    rg = Radargram(data=np.ones((100, 1)), dt_ns=1.0, t0_ns=0.0)
    out = build_step("gain_curve", points=[[10.0, 6.0], [20.0, 6.0]]).apply(rg)
    assert out.data[0, 0] == pytest.approx(10 ** (6.0 / 20.0))
    assert out.data[99, 0] == pytest.approx(10 ** (6.0 / 20.0))


def test_curve_sorts_unordered_control_points():
    rg = Radargram(data=np.ones((3, 1)), dt_ns=10.0, t0_ns=0.0)
    a = build_step("gain_curve", points=[[20.0, 20.0], [0.0, 0.0]]).apply(rg)
    b = build_step("gain_curve", points=[[0.0, 0.0], [20.0, 20.0]]).apply(rg)
    np.testing.assert_allclose(a.data, b.data)


def test_curve_requires_at_least_two_points():
    with pytest.raises(ValueError, match="two"):
        build_step("gain_curve", points=[[0.0, 0.0]]).apply(
            Radargram(data=np.ones((10, 2)), dt_ns=0.2, t0_ns=0.0)
        )


def test_curve_is_fast_enough_to_drag():
    """One broadcast multiply over a realistic radargram. The cached stack
    makes dragging recompute only this when gain is the last step."""
    import time

    rg = Radargram(data=np.ones((512, 3000)), dt_ns=0.2, t0_ns=0.0)
    step = build_step("gain_curve", points=[[0.0, 0.0], [100.0, 30.0]])
    start = time.perf_counter()
    step.apply(rg)
    assert time.perf_counter() - start < 0.1
