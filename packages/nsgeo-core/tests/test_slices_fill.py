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


def test_fill_at_r1_includes_the_cells_own_value_in_its_smoothed_value():
    """Whether a cell's own value participates in its own smoothed value
    is a real, undecided question -- `test_fill_smooths_a_fully_covered_
    slice_rather_than_preserving_it` above only checks that the result
    changes, stays finite, and stays in range, all of which a
    centre-excluded kernel (`kernel[r, r] = 0.0`) satisfies just as well.
    Decided here as: the cell's own value participates, matching what
    `disc_kernel` already produces (its centre entry is 1.0, not 0.0).

    `disc_kernel(1)` is a plus-shaped 5-cell neighbourhood (the 4 diagonal
    corners are excluded, `(xx**2 + yy**2) <= 1` fails for them). With all
    five weights equal to 1 (count 1 everywhere here), the centre-included
    mean is (100 + 1 + 2 + 3 + 4) / 5 = 22.0; a centre-excluded kernel
    would instead average only the four neighbours, (1 + 2 + 3 + 4) / 4 =
    2.5 -- different enough that the two are not a rounding question."""
    values = np.zeros((3, 3), dtype=np.float32)
    counts = np.ones((3, 3), dtype=np.float32)
    values[1, 1] = 100.0  # centre
    values[0, 1] = 1.0  # up
    values[2, 1] = 2.0  # down
    values[1, 0] = 3.0  # left
    values[1, 2] = 4.0  # right
    out = fill(values, counts, radius_cells=1)
    assert out[1, 1] == pytest.approx(22.0)


def test_fill_denominator_masks_out_a_nan_value_with_a_nonzero_count():
    """A cell can carry a NaN value alongside a non-zero count if the
    documented "NaN iff count 0" invariant is ever violated upstream --
    nothing in this module enforces it. The denominator must mask that
    cell out exactly as the numerator does, or the NaN cell's real count
    dilutes the weighted mean toward zero even though it contributes no
    value: here (NaN, count 4) beside (6.0, count 1) must land on the
    unbiased 6.0, not a value dragged toward zero by the phantom weight."""
    values = np.full((3, 3), np.nan, dtype=np.float32)
    counts = np.zeros((3, 3), dtype=np.float32)
    values[1, 0], counts[1, 0] = np.nan, 4.0
    values[1, 2], counts[1, 2] = 6.0, 1.0
    out = fill(values, counts, radius_cells=1)
    assert out[1, 1] == pytest.approx(6.0)


def test_fill_rejects_a_negative_radius():
    with pytest.raises(ValueError, match="radius_cells"):
        fill(np.zeros((3, 3)), np.ones((3, 3)), radius_cells=-1)


def test_fill_rejects_mismatched_shapes():
    with pytest.raises(ValueError, match="same shape"):
        fill(np.zeros((3, 3)), np.ones((4, 4)), radius_cells=1)


def test_smooth_size_is_never_smaller_than_asked_and_is_five_smooth():
    from nsgeo.slices.fill import _smooth_size

    for n in range(1, 400):
        m = _smooth_size(n)
        assert m >= n, f"_smooth_size({n}) = {m} would WRAP the convolution"
        rest = m
        for p in (2, 3, 5):
            while rest % p == 0:
                rest //= p
        assert rest == 1, f"_smooth_size({n}) = {m} is not 5-smooth"
    assert _smooth_size(1041) == 1080


def _unpadded_fill(values, counts, radius_cells, min_count=0.5):
    """M10's exact formula, at the exact minimum FFT size. The reference
    the padded implementation must agree with -- written out here rather
    than imported, so a change to the shipped one cannot quietly change
    the thing it is checked against."""
    import numpy as np
    from nsgeo.slices.fill import disc_kernel

    values = np.asarray(values, dtype=float)
    counts = np.asarray(counts, dtype=float)
    r = int(radius_cells)
    ny, nx = values.shape
    kernel = disc_kernel(r)
    finite = np.isfinite(values)
    numerator = np.where(finite, values, 0.0) * counts
    denominator = np.where(finite, counts, 0.0)
    shape = (ny + 2 * r, nx + 2 * r)
    spectrum = np.fft.rfft2(kernel, s=shape)
    num = np.fft.irfft2(np.fft.rfft2(numerator, s=shape) * spectrum, s=shape)[
        r : r + ny, r : r + nx
    ]
    den = np.fft.irfft2(np.fft.rfft2(denominator, s=shape) * spectrum, s=shape)[
        r : r + ny, r : r + nx
    ]
    return np.divide(num, den, out=np.full((ny, nx), np.nan), where=den >= min_count).astype(
        np.float32
    )


@pytest.mark.parametrize(("ny", "nx", "radius"), [(37, 41, 3), (100, 100, 8), (213, 209, 10)])
def test_padding_to_a_smooth_size_does_not_change_the_answer(ny, nx, radius):
    """Zero-padding a linear convolution further can only add zeros past
    the end; the crop window is unmoved. If this ever fails, the crop
    offset is wrong, not the padding."""
    rng = np.random.default_rng(7)
    counts = (rng.random((ny, nx)) < 0.2).astype(float)
    values = np.where(counts > 0, rng.random((ny, nx)) * 10.0, np.nan)
    got = fill(values, counts, radius)
    want = _unpadded_fill(values, counts, radius)
    np.testing.assert_array_equal(np.isfinite(got), np.isfinite(want))  # identical nodata mask
    both = np.isfinite(got)
    np.testing.assert_allclose(got[both], want[both], rtol=1e-5, atol=1e-6)


def test_the_kernel_spectrum_cache_returns_the_same_answer_on_a_second_call():
    """A cached array handed out by reference would be corrupted by any
    caller that wrote into it. Nothing in `fill` does -- it only
    multiplies -- and this pins that: two identical fills either side of a
    different one must agree exactly."""
    rng = np.random.default_rng(11)
    counts = (rng.random((60, 60)) < 0.3).astype(float)
    values = np.where(counts > 0, rng.random((60, 60)), np.nan)
    first = fill(values, counts, 5)
    fill(values, counts, 7)  # a different radius, same shape family
    second = fill(values, counts, 5)
    np.testing.assert_array_equal(np.isfinite(first), np.isfinite(second))
    np.testing.assert_array_equal(first[np.isfinite(first)], second[np.isfinite(second)])


def test_clearing_the_kernel_cache_does_not_change_results():
    from nsgeo.slices.fill import clear_kernel_cache

    rng = np.random.default_rng(13)
    counts = (rng.random((50, 50)) < 0.3).astype(float)
    values = np.where(counts > 0, rng.random((50, 50)), np.nan)
    warm = fill(values, counts, 4)
    clear_kernel_cache()
    cold = fill(values, counts, 4)
    np.testing.assert_array_equal(warm[np.isfinite(warm)], cold[np.isfinite(cold)])
