"""The one gap rule for GPS lines (M17c, #134)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from nsgeo.geometry.spacing import (
    gap_steps,
    gap_threshold,
    left_out,
    resample_even,
    sample_back,
    usual_step,
)
from nsgeo.geometry.track import TrackFix, TrackPlacement


def test_the_usual_step_is_the_median_step():
    assert usual_step(np.array([0.0, 0.02, 0.04, 0.06, 1.0, 1.02])) == pytest.approx(0.02)


def test_a_step_over_six_usual_steps_is_a_gap():
    d = np.concatenate([np.arange(10) * 0.02, 0.18 + 0.5 + np.arange(10) * 0.02])
    assert gap_steps(d).tolist() == [False] * 9 + [True] + [False] * 9


def test_the_threshold_is_strictly_longer_than_six_usual_steps():
    base = np.arange(20) * 0.02
    assert not gap_steps(np.append(base, base[-1] + 0.119)).any()
    assert gap_steps(np.append(base, base[-1] + 0.121))[-1]
    assert not gap_steps(np.array([0.0, 0.5]), gap_m=0.5).any()


def test_a_typed_gap_over_replaces_the_automatic_threshold():
    d = np.array([0.0, 0.02, 0.04, 0.10, 0.12, 0.62, 0.64])
    assert gap_steps(d, gap_m=0.05).tolist() == [False, False, True, False, True, False]
    assert not gap_steps(d, gap_m=1.0).any()
    assert gap_threshold(d, 0.3) == 0.3


def test_traces_between_two_gap_steps_are_left_out():
    d = np.array([0.0, 0.02, 0.04, 0.5, 1.0, 1.5, 1.52, 1.54])
    assert left_out(d).tolist() == [False, False, False, True, True, False, False, False]


def test_a_single_gap_step_leaves_both_its_traces_drawn():
    d = np.array([0.0, 0.02, 0.04, 1.5, 1.52, 1.54])
    assert not left_out(d).any()


def test_a_falling_distance_has_the_same_gaps_as_its_reverse():
    d = np.array([0.0, 0.02, 0.04, 0.5, 1.0, 1.5, 1.52, 1.54])
    assert gap_steps(-d).tolist() == gap_steps(d).tolist()
    assert left_out(-d).tolist() == left_out(d).tolist()


@pytest.mark.filterwarnings("error")
def test_a_line_with_no_spacing_has_no_gaps():
    d = np.full(10, 3.0)
    assert usual_step(d) == 0.0
    assert gap_threshold(d) == math.inf
    assert not gap_steps(d).any()
    assert not left_out(d).any()


def test_fewer_than_two_traces():
    one = np.array([1.0])
    assert gap_steps(one).tolist() == [] and left_out(one).tolist() == [False]
    none = np.array([])
    assert gap_steps(none).size == 0 and left_out(none).size == 0
    assert usual_step(one) == 0.0 and usual_step(none) == 0.0


def test_a_lift_at_either_end_leaves_the_end_trace_drawn():
    d = np.concatenate([[0.0], 1.0 + np.arange(10) * 0.02, [2.0]])
    assert gap_steps(d)[0] and gap_steps(d)[-1]
    out = left_out(d)
    assert not out[0] and not out[-1]


def test_a_tiny_gap_over_leaves_out_everything_but_the_ends():
    d = np.arange(12) * 0.02
    out = left_out(d, gap_m=0.001)
    assert out[1:-1].all() and not out[0] and not out[-1]


def _placement(**kw):
    fixes = (TrackFix(0, 0.0, 0.0, 45.2, 10.5), TrackFix(10, 1.0, 0.0, 45.2, 10.5))
    return TrackPlacement(fixes=fixes, crs="EPSG:32632", **kw)


@pytest.mark.parametrize("v", [0, -1, math.nan, math.inf])
def test_gap_over_must_be_finite_and_positive(v):
    d = np.arange(5) * 0.02
    with pytest.raises(ValueError):
        gap_steps(d, gap_m=v)
    with pytest.raises(ValueError):
        left_out(np.array([1.0]), gap_m=v)
    with pytest.raises(ValueError):
        _placement(gap_m=v)


def test_the_placement_keeps_a_typed_gap_over():
    assert _placement().gap_m is None
    assert _placement(gap_m=0.25).gap_m == 0.25


def _with_gap():
    """1.0 m of 0.02 m steps, a 1.0 m gap, 1.0 m more; and a lift (two gap steps)."""
    left = np.arange(0.0, 1.0001, 0.02)
    right = left + 2.0
    return np.concatenate([left, right])


def test_nothing_is_invented_inside_a_gap():
    x = _with_gap()
    data = np.ones((4, x.size))
    even, x0, step = resample_even(data, x)
    cols = x0 + np.arange(even.shape[1]) * step
    edge_l, edge_r = 1.0, 2.0
    far = (np.abs(cols - edge_l) >= step - 1e-9) & (np.abs(cols - edge_r) >= step - 1e-9)
    inside = (cols > edge_l) & (cols < edge_r) & far
    assert inside.sum() > 40
    assert not even[:, inside].any()
    near = (cols > edge_l) & (cols < edge_r) & ~far
    assert (even[:, near] > 0).all()


def test_left_out_traces_do_not_feed_the_resample():
    x = _with_gap()
    x = np.insert(x, 51, 1.5)  # a lift in the middle of the gap: gaps on both sides
    data = np.ones((3, x.size))
    data[:, 51] = 1e6
    assert left_out(x)[51]
    even, _, _ = resample_even(data, x)
    assert even.max() <= 1.0


def test_sample_back_returns_each_trace_at_its_own_distance():
    x = _with_gap()
    x = np.insert(x, 51, 1.5)  # a left-out trace as well
    x = np.insert(x, 10, x[10])  # and a repeated distance: the cart stood still
    rows = np.array([[1.0], [3.0]])
    data = rows + 0.7 * x[None, :]
    even, x0, step = resample_even(data, x)
    back = sample_back(even, x0, step, x)
    drawn = ~left_out(x)
    np.testing.assert_allclose(back[:, drawn], data[:, drawn], atol=1e-9)
    assert np.isfinite(back).all()


def test_a_falling_distance_resamples_like_its_reverse():
    x = _with_gap()
    data = np.random.default_rng(0).normal(size=(3, x.size))
    a, a0, astep = resample_even(data, x)
    b, b0, bstep = resample_even(data[:, ::-1], x[::-1])
    np.testing.assert_allclose(a, b, atol=1e-12)
    assert (a0, astep) == (b0, bstep)


def test_a_line_with_no_usual_step_cannot_be_resampled():
    with pytest.raises(ValueError):
        resample_even(np.ones((2, 5)), np.full(5, 3.0))
