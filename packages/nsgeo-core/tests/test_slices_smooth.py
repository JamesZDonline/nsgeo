"""Directional Gaussian smoothing (interpolation spec §6)."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices import smooth

CELL = 0.1


def spike():
    field = np.zeros((21, 21))
    field[10, 10] = 1.0
    return field


def test_zero_sigma_is_the_identity():
    rng = np.random.default_rng(0)
    values = rng.normal(size=(15, 20))
    values[3, 4] = np.nan
    out = smooth(values, CELL, 0.0, 0.0)
    assert out.dtype == np.float32
    np.testing.assert_array_equal(out, values.astype(np.float32))


def test_sigma_x_alone_spreads_a_spike_only_along_x():
    out = smooth(spike(), CELL, 0.3, 0.0)
    assert set(np.nonzero(out)[0]) == {10}
    assert np.count_nonzero(out[10]) > 1


def test_sigma_y_alone_spreads_a_spike_only_along_y():
    out = smooth(spike(), CELL, 0.0, 0.3)
    assert set(np.nonzero(out)[1]) == {10}
    assert np.count_nonzero(out[:, 10]) > 1


def test_a_spike_spreads_as_a_gaussian_of_the_given_sigma():
    # A field wider than 2 x 4 sigma either side of the spike: nearer an edge
    # the renormalising divide sees a truncated kernel, so the ratio is only
    # a Gaussian's where the whole kernel fits.
    field = np.zeros((41, 41))
    field[20, 20] = 1.0
    out = smooth(field, CELL, 0.3, 0.0).astype(float)
    for k in range(4):
        want = np.exp(-((CELL * k) ** 2) / (2 * 0.3**2))
        np.testing.assert_allclose(out[20, 20 + k] / out[20, 20], want, rtol=1e-6)


def test_blanks_stay_blank_and_nothing_new_is_filled():
    rng = np.random.default_rng(1)
    values = rng.normal(size=(30, 30))
    values[rng.random(values.shape) < 0.4] = np.nan
    out = smooth(values, CELL, 0.5, 0.5)
    np.testing.assert_array_equal(np.isnan(out), np.isnan(values))


def test_an_edge_beside_a_blank_is_not_pulled_toward_zero():
    values = np.full((20, 20), 5.0)
    values[:, 10:] = np.nan
    out = smooth(values, CELL, 0.3, 0.3)
    np.testing.assert_allclose(out[np.isfinite(out)], 5.0, rtol=1e-6)


def test_smoothing_is_affine_equivariant():
    rng = np.random.default_rng(2)
    values = rng.normal(size=(25, 25))
    values[5:9, 5:9] = np.nan
    a, b = 3.5, -7.0
    got = smooth(a * values + b, CELL, 0.2, 0.4).astype(float)
    want = a * smooth(values, CELL, 0.2, 0.4).astype(float) + b
    np.testing.assert_allclose(got, want, rtol=1e-4, atol=1e-4)


def test_smooth_refuses_a_negative_sigma():
    with pytest.raises(ValueError):
        smooth(spike(), CELL, -0.1, 0.0)
    with pytest.raises(ValueError):
        smooth(spike(), CELL, 0.0, -0.1)
