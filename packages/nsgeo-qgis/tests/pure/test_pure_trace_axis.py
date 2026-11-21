from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry import usual_step
from nsgeo_qgis.ui.trace_axis import TraceAxis


def _with_gap(n_each: int = 10, step: float = 0.02, gap: float = 0.5) -> np.ndarray:
    a = np.arange(n_each) * step
    return np.concatenate([a, a[-1] + gap + a])


def test_an_even_axis_puts_trace_units_linearly():
    ax = TraceAxis.from_distance(np.arange(20) * 0.05)
    u = np.array([0.5, 3.0, 7.25, 19.5])
    assert ax.walk_at(u) == pytest.approx((u - 0.5) * 0.05)
    assert ax.units_at_walk(ax.walk_at(u)) == pytest.approx(u)


def test_each_trace_reaches_halfway_to_its_neighbours():
    ax = TraceAxis.from_distance([0.0, 0.02, 0.05])
    lo, hi = ax.drawn()
    assert lo[1] == pytest.approx(0.01)
    assert hi[1] == pytest.approx(0.035)
    assert hi[0] == pytest.approx(lo[1])
    assert lo[2] == pytest.approx(hi[1])


def test_a_trace_reaches_half_a_usual_step_into_a_gap():
    d = _with_gap()
    ax = TraceAxis.from_distance(d)
    lo, hi = ax.drawn()
    usual = usual_step(d)
    assert hi[9] - d[9] == pytest.approx(usual / 2)
    assert d[10] - lo[10] == pytest.approx(usual / 2)


def test_left_out_traces_are_not_drawn():
    d = np.array([0.0, 0.02, 0.04, 0.06, 1.0, 1.02, 1.04, 1.06])
    d = np.insert(d, 4, 0.5)  # a lone trace in the gap: gaps both sides
    ax = TraceAxis.from_distance(d)
    lo, hi = ax.drawn()
    assert lo[4] == hi[4]
    assert ax.trace_at_walk(0.3) is None
    assert ax.trace_at_walk(0.5) is None
    assert ax.trace_at_walk(0.025) == 1


def test_runs_group_adjoining_equal_columns():
    even = TraceAxis.from_distance(np.arange(12) * 0.02)
    runs = even.runs()
    assert len(runs) == 1 and runs[0][:2] == (0, 11)
    assert runs[0][2] == pytest.approx(-0.01) and runs[0][3] == pytest.approx(0.23)
    assert len(TraceAxis.from_distance(_with_gap()).runs()) == 2
    two = np.concatenate([np.arange(6) * 0.02, 0.1 + np.arange(1, 7) * 0.03])
    runs = TraceAxis.from_distance(two).runs()
    assert [r[:2] for r in runs] == [(0, 4), (5, 5), (6, 11)]


def test_a_reversed_line_walks_the_same_way_as_its_forward_twin():
    d = np.array([0.0, 0.02, 0.05, 0.09, 0.14])
    fwd = TraceAxis.from_distance(d)
    rev = TraceAxis.from_distance(d[::-1].copy())
    assert np.all(np.diff(rev.walk_at(np.arange(5) + 0.5)) > 0)
    lo, hi = rev.drawn()
    flo, fhi = fwd.drawn()
    assert (hi - lo) == pytest.approx((fhi - flo)[::-1])


def test_repeated_distances_do_not_break_the_inverse():
    d = np.array([0.0, 0.02, 0.02, 0.02, 0.06, 0.08, 0.08])
    ax = TraceAxis.from_distance(d)
    lo, hi = ax.drawn()
    assert np.all(np.isfinite(lo)) and np.all(np.isfinite(hi))
    for w in (-1.0, 0.0, 0.02, 0.05, 0.08, 1.0):
        assert np.isfinite(ax.units_at_walk(w))
        assert np.isfinite(ax.walk_at(w))
    assert ax.trace_at_walk(0.02) in (1, 2, 3)
    assert 0 <= ax.nearest_drawn(0.02) < 7


def test_a_lift_at_the_first_step_draws_trace_0_half_a_step_wide():
    d = np.concatenate([[0.0], 1.0 + np.arange(10) * 0.02])
    ax = TraceAxis.from_distance(d)
    usual = usual_step(d)
    lo, hi = ax.drawn()
    assert hi[0] - lo[0] == pytest.approx(usual)
    assert hi[0] - d[0] == pytest.approx(usual / 2)  # inward, into the gap
    assert d[0] - lo[0] == pytest.approx(usual / 2)  # outward, capped likewise


def test_an_end_step_that_is_not_a_gap_reaches_halfway_outward_uncapped():
    d = np.concatenate([[0.0], 0.06 + np.arange(10) * 0.02])  # first step 3 usual, no gap
    ax = TraceAxis.from_distance(d)
    lo, hi = ax.drawn()
    assert d[0] - lo[0] == pytest.approx(1.5 * 0.02)
    assert hi[0] - d[0] == pytest.approx(1.5 * 0.02)


def test_a_line_with_no_length_is_refused():
    with pytest.raises(ValueError):
        TraceAxis.from_distance([1.0, 1.0, 1.0])


def test_the_axis_owns_read_only_copies():
    src = np.arange(5) * 0.1
    ax = TraceAxis(src)
    src[2] = 99.0
    assert ax.distance[2] == pytest.approx(0.2)
    lo, hi = ax.drawn()
    assert not lo.flags.writeable and not hi.flags.writeable
    assert not ax.distance.flags.writeable


def test_a_distance_that_turns_back_is_refused():
    with pytest.raises(ValueError):
        TraceAxis.from_distance([0.0, 0.1, 0.05, 0.2])
    with pytest.raises(ValueError):
        TraceAxis.from_distance([0.0])
    with pytest.raises(ValueError):
        TraceAxis.from_distance([0.0, float("nan"), 0.2])
