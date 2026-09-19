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


def test_fill_at_zero_radius_leaves_a_fully_covered_slice_unchanged():
    """Renamed from `..._preserves_a_fully_covered_slice`: at r=0 this is
    the same pass-through path `test_zero_radius_is_a_no_op` already pins,
    just on a dense fixture with no NaNs -- it does NOT mean fill acts as
    an identity in general. See the r=1 case below, where it manifestly
    does not: the smear rewrites already-observed cells too."""
    rng = np.random.default_rng(0)
    values = rng.random((8, 8)).astype(np.float32)
    counts = np.ones((8, 8), dtype=np.float32)
    out = fill(values, counts, radius_cells=0)
    np.testing.assert_allclose(out, values)


def test_fill_smooths_a_fully_covered_slice_rather_than_preserving_it():
    """At any radius >= 1, fill is a genuine neighbourhood smear, not an
    identity: an already-observed cell is rewritten by the disc-weighted
    mean of its neighbourhood, itself included. That is a deliberate
    trade-off -- it is what GPRSLICE's oversized search box does too --
    not an oversight, so it is pinned here rather than left for M11's
    radius slider to rediscover by surprise.
    """
    rng = np.random.default_rng(0)
    values = rng.random((8, 8)).astype(np.float32)
    counts = np.ones((8, 8), dtype=np.float32)
    out = fill(values, counts, radius_cells=1)
    assert not np.allclose(out, values)
    assert np.isfinite(out).all()
    # A disc-weighted mean over a subset of `values` is a convex
    # combination of them, so it can never land outside their global range.
    assert out.min() >= values.min() - 1e-6
    assert out.max() <= values.max() + 1e-6


def test_fill_rejects_a_negative_radius():
    with pytest.raises(ValueError, match="radius_cells"):
        fill(np.zeros((3, 3)), np.ones((3, 3)), radius_cells=-1)


def test_fill_rejects_mismatched_shapes():
    with pytest.raises(ValueError, match="same shape"):
        fill(np.zeros((3, 3)), np.ones((4, 4)), radius_cells=1)
