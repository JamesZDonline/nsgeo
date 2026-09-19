from __future__ import annotations

import numpy as np
import pytest
from nsgeo.processing import StepStack, build_step
from nsgeo.processing.amplitude import analytic_envelope
from nsgeo.processing.base import Radargram, is_unipolar


def make(data, dt_ns=0.2165, t0_ns=0.0):
    return Radargram(data=np.asarray(data, dtype=float), dt_ns=dt_ns, t0_ns=t0_ns)


def test_amp_abs_removes_the_negative_side():
    rg = make([[-2.0, 3.0], [1.0, -4.0]])
    out = build_step("amp_abs").apply(rg)
    np.testing.assert_allclose(out.data, [[2.0, 3.0], [1.0, 4.0]])


def test_amp_square_is_energy():
    rg = make([[-2.0, 3.0]])
    np.testing.assert_allclose(build_step("amp_square").apply(rg).data, [[4.0, 9.0]])


def test_transforms_preserve_the_time_axis():
    rg = make(np.ones((10, 4)), dt_ns=0.5, t0_ns=-3.0)
    for name in ("amp_abs", "amp_square", "amp_envelope"):
        out = build_step(name).apply(rg)
        assert out.dt_ns == 0.5
        assert out.t0_ns == -3.0
        assert out.data.shape == (10, 4)


def test_envelope_of_a_sinusoid_is_its_amplitude():
    """The defining property: the envelope rides the peaks, not the wave."""
    n = 512
    t = np.arange(n)
    wave = 3.0 * np.sin(2.0 * np.pi * t / 16.0)
    env = analytic_envelope(wave[:, None])[:, 0]
    np.testing.assert_allclose(env[32:-32], 3.0, rtol=1e-6)


def test_envelope_is_never_negative():
    rng = np.random.default_rng(0)
    env = analytic_envelope(rng.normal(size=(97, 5)))
    assert (env >= 0.0).all()


def test_envelope_handles_an_odd_and_prime_length():
    """463 rows is what time_zero leaves on the real files, and it is prime
    -- the worst case for an FFT and the one we deliberately do not pad."""
    rng = np.random.default_rng(1)
    env = analytic_envelope(rng.normal(size=(463, 3)))
    assert env.shape == (463, 3)
    assert np.isfinite(env).all()


def test_envelope_is_not_the_zero_padded_approximation():
    """Padding to a fast length is 2.2x quicker and shifts the interior by
    ~1.3%. Pin the exact transform so that optimisation cannot reappear
    silently."""
    rng = np.random.default_rng(2)
    data = rng.normal(size=(463, 2))
    exact = analytic_envelope(data)
    padded = analytic_envelope(np.pad(data, ((0, 480 - 463), (0, 0))))[:463]
    assert not np.allclose(exact, padded, rtol=1e-3)


def test_all_three_transforms_declare_themselves_unipolar():
    for name in ("amp_abs", "amp_square", "amp_envelope"):
        assert is_unipolar(build_step(name)) is True


def test_ordinary_steps_are_not_unipolar():
    assert is_unipolar(build_step("dewow")) is False


def test_stack_output_unipolar_follows_the_last_enabled_step():
    stack = StepStack()
    stack.source = make(np.ones((8, 4)))
    stack.append(build_step("dewow"))
    assert stack.output_unipolar is False
    stack.append(build_step("amp_abs"))
    assert stack.output_unipolar is True
    stack.set_enabled(1, False)
    assert stack.output_unipolar is False


def test_empty_stack_is_not_unipolar():
    assert StepStack().output_unipolar is False


def test_transforms_take_no_parameters():
    for name in ("amp_abs", "amp_square", "amp_envelope"):
        step = build_step(name)
        assert step.params == {}
        assert step.schema() == ()


def test_unknown_parameter_is_rejected():
    with pytest.raises(ValueError, match="has no parameter"):
        build_step("amp_abs", window_ns=3.0)
