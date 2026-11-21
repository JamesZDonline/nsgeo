"""The one gap rule for GPS lines (M17c, #134)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from nsgeo.geometry.spacing import gap_steps, gap_threshold, left_out, usual_step
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
