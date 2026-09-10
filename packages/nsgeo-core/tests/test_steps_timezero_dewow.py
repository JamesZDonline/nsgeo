from __future__ import annotations

import nsgeo.processing.dewow  # noqa: F401  (registers the step)
import nsgeo.processing.timezero  # noqa: F401
import numpy as np
import pytest
from nsgeo.processing.base import Radargram, build_step


def make(n_samples=100, n_traces=20, dt_ns=0.2, t0_ns=0.0, fill=0.0):
    return Radargram(
        data=np.full((n_samples, n_traces), fill, dtype=float), dt_ns=dt_ns, t0_ns=t0_ns
    )


def test_time_zero_by_sample_crops_rows():
    rg = make(n_samples=100)
    out = build_step("time_zero", mode="sample", sample=17).apply(rg)
    assert out.n_samples == 83


def test_time_zero_updates_t0_consistently_with_dropped_rows():
    """The invariant that makes returning a whole Radargram worthwhile."""
    rg = make(n_samples=100, dt_ns=0.25, t0_ns=1.0)
    out = build_step("time_zero", mode="sample", sample=8).apply(rg)
    assert out.t0_ns == pytest.approx(1.0 + 8 * 0.25)
    assert out.times_ns()[0] == pytest.approx(3.0)


def test_time_zero_first_break_finds_the_onset():
    rg = make(n_samples=200)
    data = rg.data.copy()
    data[40:, :] = 100.0  # signal starts at row 40
    out = build_step("time_zero", mode="first_break", threshold=0.5).apply(rg.replace(data=data))
    assert out.n_samples == 160


def test_time_zero_first_break_ignores_leading_zero_traces():
    """Leading all-zero traces are normal and must not confuse the pick."""
    rg = make(n_samples=200, n_traces=20)
    data = rg.data.copy()
    data[40:, 4:] = 100.0
    data[:, :4] = 0.0
    out = build_step("time_zero", mode="first_break", threshold=0.5).apply(rg.replace(data=data))
    assert out.n_samples == 160


def test_time_zero_sample_zero_is_a_no_op():
    rg = make(n_samples=50, t0_ns=2.0)
    out = build_step("time_zero", mode="sample", sample=0).apply(rg)
    assert out.n_samples == 50
    assert out.t0_ns == pytest.approx(2.0)


def test_time_zero_rejects_cropping_everything():
    with pytest.raises(ValueError, match="would leave no samples"):
        build_step("time_zero", mode="sample", sample=100).apply(make(n_samples=100))


def test_time_zero_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode"):
        build_step("time_zero", mode="vibes").apply(make())


def test_time_zero_does_not_mutate_input():
    rg = make(n_samples=50, fill=3.0)
    before = rg.data.copy()
    build_step("time_zero", mode="sample", sample=5).apply(rg)
    np.testing.assert_array_equal(rg.data, before)


def test_dewow_removes_a_constant_offset():
    rg = make(n_samples=200, fill=7.0)
    out = build_step("dewow", window_ns=4.0).apply(rg)
    np.testing.assert_allclose(out.data, 0.0, atol=1e-9)


def test_dewow_preserves_high_frequency_content():
    n = 400
    t = np.arange(n)
    fast = np.sin(2 * np.pi * t / 4.0)[:, None] * np.ones((1, 5))
    slow = 10.0 * np.sin(2 * np.pi * t / 400.0)[:, None] * np.ones((1, 5))
    rg = Radargram(data=fast + slow, dt_ns=0.2, t0_ns=0.0)
    out = build_step("dewow", window_ns=8.0).apply(rg)
    mid = slice(50, 350)
    assert np.std(out.data[mid]) > 0.5 * np.std(fast[mid])
    assert np.abs(out.data[mid].mean()) < 0.5


def test_dewow_leaves_time_axis_untouched():
    rg = make(n_samples=100, dt_ns=0.2, t0_ns=1.5)
    out = build_step("dewow", window_ns=4.0).apply(rg)
    assert out.t0_ns == pytest.approx(1.5)
    assert out.n_samples == 100


def test_dewow_rejects_window_shorter_than_one_sample():
    with pytest.raises(ValueError, match="window_ns"):
        build_step("dewow", window_ns=0.0).apply(make(dt_ns=0.2))


def test_step_params_are_declared_for_the_ui():
    step = build_step("dewow", window_ns=6.0)
    assert step.params == {"window_ns": 6.0}
