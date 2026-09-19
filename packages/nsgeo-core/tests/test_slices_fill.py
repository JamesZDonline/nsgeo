from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices.fill import disc_kernel, fill


def test_disc_kernel_is_round_and_odd_sized():
    k = disc_kernel(2)
    assert k.shape == (5, 5)
    assert k[2, 2] == 1.0
    assert k[0, 0] == 0.0  # the corner is outside the disc
    assert k[0, 2] == 1.0


def test_zero_radius_is_a_no_op():
    values = np.array([[1.0, np.nan], [3.0, 4.0]], dtype=np.float32)
    counts = np.array([[1, 0], [1, 1]], dtype=np.float32)
    out = fill(values, counts, radius_cells=0)
    np.testing.assert_array_equal(np.isnan(out), np.isnan(values))
    np.testing.assert_allclose(out[~np.isnan(out)], values[~np.isnan(values)])


def test_fill_reaches_an_empty_cell_from_its_neighbours():
    values = np.full((5, 5), np.nan, dtype=np.float32)
    counts = np.zeros((5, 5), dtype=np.float32)
    values[2, 0] = 10.0
    counts[2, 0] = 1.0
    out = fill(values, counts, radius_cells=2)
    assert out[2, 1] == pytest.approx(10.0)
    assert np.isnan(out[2, 4])  # still beyond the radius


def test_fill_is_a_weighted_mean_not_a_sum():
    values = np.full((3, 3), np.nan, dtype=np.float32)
    counts = np.zeros((3, 3), dtype=np.float32)
    values[1, 0], counts[1, 0] = 2.0, 1.0
    values[1, 2], counts[1, 2] = 4.0, 1.0
    out = fill(values, counts, radius_cells=1)
    assert out[1, 1] == pytest.approx(3.0)


def test_fill_weights_by_count_so_a_busy_cell_counts_more():
    values = np.full((3, 3), np.nan, dtype=np.float32)
    counts = np.zeros((3, 3), dtype=np.float32)
    values[1, 0], counts[1, 0] = 2.0, 3.0
    values[1, 2], counts[1, 2] = 6.0, 1.0
    out = fill(values, counts, radius_cells=1)
    assert out[1, 1] == pytest.approx((2.0 * 3 + 6.0 * 1) / 4.0)


def test_fill_leaves_cells_beyond_every_observation_as_nodata():
    values = np.full((9, 9), np.nan, dtype=np.float32)
    counts = np.zeros((9, 9), dtype=np.float32)
    values[0, 0], counts[0, 0] = 1.0, 1.0
    out = fill(values, counts, radius_cells=1)
    assert np.isnan(out[8, 8])


def test_fill_preserves_a_fully_covered_slice():
    rng = np.random.default_rng(0)
    values = rng.random((8, 8)).astype(np.float32)
    counts = np.ones((8, 8), dtype=np.float32)
    out = fill(values, counts, radius_cells=0)
    np.testing.assert_allclose(out, values)


def test_fill_rejects_a_negative_radius():
    with pytest.raises(ValueError, match="radius_cells"):
        fill(np.zeros((3, 3)), np.ones((3, 3)), radius_cells=-1)


def test_fill_rejects_mismatched_shapes():
    with pytest.raises(ValueError, match="same shape"):
        fill(np.zeros((3, 3)), np.ones((4, 4)), radius_cells=1)
