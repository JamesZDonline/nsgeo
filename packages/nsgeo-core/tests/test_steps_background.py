from __future__ import annotations

import nsgeo.processing  # noqa: F401
import numpy as np
import pytest
from nsgeo.processing.base import Radargram, available_steps, build_step


def banded(n_samples=128, n_traces=300, seed=0):
    """A strong horizontal band plus random reflectors — the thing background
    removal exists to separate."""
    rng = np.random.default_rng(seed)
    band = np.linspace(5.0, 1.0, n_samples)[:, None] * np.ones((1, n_traces))
    features = rng.normal(0.0, 0.2, (n_samples, n_traces))
    return Radargram(data=band + features, dt_ns=0.2, t0_ns=0.0), band, features


def test_mean_output_has_zero_mean_along_the_trace_axis():
    rg, _, _ = banded()
    out = build_step("background_mean").apply(rg)
    np.testing.assert_allclose(out.data.mean(axis=1), 0.0, atol=1e-12)


def test_mean_removes_the_horizontal_band():
    rg, band, _ = banded()
    out = build_step("background_mean").apply(rg)
    assert np.abs(out.data).mean() < 0.25 * np.abs(rg.data).mean()


def test_mean_leaves_the_time_axis_untouched():
    rg, _, _ = banded()
    out = build_step("background_mean").apply(rg)
    assert out.t0_ns == rg.t0_ns and out.dt_ns == rg.dt_ns


def test_sliding_removes_a_band_that_drifts_along_the_line():
    """Full-line mean fails when the background changes; sliding is why the
    option exists."""
    n_s, n_t = 128, 600
    drift = np.linspace(0.0, 8.0, n_t)[None, :] * np.ones((n_s, 1))
    rng = np.random.default_rng(1)
    data = drift + rng.normal(0, 0.2, (n_s, n_t))
    rg = Radargram(data=data, dt_ns=0.2, t0_ns=0.0)
    sliding = build_step("background_sliding", window_traces=50).apply(rg)
    full = build_step("background_mean").apply(rg)
    assert np.abs(sliding.data).mean() < np.abs(full.data).mean()


def test_sliding_with_window_of_one_is_a_no_op_in_effect():
    rg, _, _ = banded()
    out = build_step("background_sliding", window_traces=1).apply(rg)
    np.testing.assert_allclose(out.data, 0.0, atol=1e-12)


def test_sliding_rejects_zero_window():
    rg, _, _ = banded()
    with pytest.raises(ValueError, match="window_traces"):
        build_step("background_sliding", window_traces=0).apply(rg)


def test_svd_with_zero_components_is_the_identity():
    rg, _, _ = banded()
    out = build_step("background_svd", n_components=0).apply(rg)
    np.testing.assert_allclose(out.data, rg.data, atol=1e-10)


def test_svd_removes_a_rank_one_band():
    rg, band, features = banded()
    out = build_step("background_svd", n_components=1).apply(rg)
    assert np.abs(out.data).mean() < 0.5 * np.abs(rg.data).mean()
    # the random reflectors survive
    assert np.corrcoef(out.data.ravel(), features.ravel())[0, 1] > 0.8


def test_svd_rejects_more_components_than_rank():
    rg, _, _ = banded(n_samples=8, n_traces=5)
    with pytest.raises(ValueError, match="n_components"):
        build_step("background_svd", n_components=99).apply(rg)


def test_svd_rejects_negative_components():
    rg, _, _ = banded()
    with pytest.raises(ValueError, match="n_components"):
        build_step("background_svd", n_components=-1).apply(rg)


_STEP_PARAMS = {
    "time_zero": {"mode": "sample", "sample": 4},
    "dewow": {"window_ns": 4.0},
    "gain_agc": {"window_ns": 4.0},
    "gain_parametric": {},
    "gain_curve": {"points": [[0, 0], [20, 6]]},
    "bandpass": {"low_mhz": 100, "high_mhz": 700},
    "background_mean": {},
    "background_sliding": {"window_traces": 20},
    "background_svd": {"n_components": 1},
}


@pytest.mark.parametrize("name", sorted(_STEP_PARAMS))
def test_none_of_the_steps_mutate_their_input(name):
    """Every registered step, not just the three background ones: a step
    that overwrote rg.data in place would corrupt every other consumer of
    the same Radargram (e.g. an earlier cached stack entry)."""
    assert set(_STEP_PARAMS) == set(available_steps())
    rng = np.random.default_rng(0)
    rg = Radargram(data=rng.normal(size=(128, 300)), dt_ns=0.2, t0_ns=0.0)
    before = rg.data.copy()
    build_step(name, **_STEP_PARAMS[name]).apply(rg)
    np.testing.assert_array_equal(rg.data, before)
