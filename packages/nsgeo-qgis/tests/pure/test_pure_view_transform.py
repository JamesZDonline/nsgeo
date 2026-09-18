from __future__ import annotations

import numpy as np
import pytest
from nsgeo_qgis.ui.view_transform import MIN_SAMPLE_SPAN, MIN_TRACE_SPAN, ViewTransform, nice_ticks

FIT = ViewTransform.fit(
    n_traces=608, n_samples=512, t0_ns=-11.09, dt_ns=0.2165, width=800, height=300
)


def test_fit_maps_the_data_extent_onto_the_widget():
    assert FIT.x_of_trace(0) == 0.0
    assert FIT.x_of_trace(608) == 800.0
    assert FIT.y_of_time(-11.09) == 0.0
    assert FIT.y_of_time(FIT.t_end) == pytest.approx(300.0)
    assert FIT.t_end == pytest.approx(-11.09 + 512 * 0.2165)


def test_round_trips():
    for x in (0.0, 123.4, 799.0):
        assert FIT.x_of_trace(FIT.trace_of_x(x)) == pytest.approx(x)
    for y in (0.0, 57.2, 300.0):
        assert FIT.y_of_time(FIT.time_of_y(y)) == pytest.approx(y)


def test_index_lookups_clamp_to_the_data():
    assert FIT.trace_index_at(-50) == 0
    assert FIT.trace_index_at(800) == 607
    assert FIT.trace_index_at(400) == 304
    assert FIT.sample_index_at(-5) == 0
    assert FIT.sample_index_at(300) == 511
    assert FIT.sample_index_at(150) in (
        255,
        256,
    )  # exactly half the record; float rounding either side


def test_index_lookups_use_the_left_edge_convention():
    """`trace_index_at`/`sample_index_at` are floor, not round or nearest.

    `test_index_lookups_clamp_to_the_data` only proves the clamps, because
    its interior probes (trace 400, sample 150) land on exact or
    half-a-hair-past-exact integers where floor/round/ceil agree. `x_of_trace`
    puts trace `i` at its LEFT edge, so a pixel anywhere in [x_of_trace(i),
    x_of_trace(i+1)) must resolve to `i` -- this is what Task 14's cursor,
    `pick_requested` and `range_selected` all rely on.
    """
    z = FIT.with_window(100.0, 110.0, 0.0, 20.0)  # 10 traces across 800 px = 80 px/trace
    assert z.trace_index_at(0.0) == 100
    assert z.trace_index_at(41.0) == 100  # round/ceil would give 101
    assert z.trace_index_at(79.9) == 100  # round/ceil would give 101
    assert z.trace_index_at(80.1) == 101
    assert z.trace_index_at(z.x_of_trace(105) + 0.1) == 105
    # Sample axis, off the sample boundary. NOT 10.5: that fraction is the one
    # point where floor and Python's banker's round agree (round(10.5) == 10),
    # so a probe there only distinguishes floor from round by ~3.5e-15 of
    # float noise and stops discriminating at all under many nearby FIT
    # parameters -- including this project's own synthetic t0 of -11.086
    # (tests/synthetic.py). 10.7 sits inside (0.5, 1.0), away from every
    # floor/round/ceil/round-half-up tie.
    assert FIT.sample_index_at(FIT.y_of_time(FIT.t0_ns + 10.7 * FIT.dt_ns)) == 10
    assert FIT.sample_index_at(FIT.y_of_time(FIT.t0_ns + 10.2 * FIT.dt_ns)) == 10


def test_index_lookups_never_go_negative_on_empty_data():
    """`n_traces - 1` (or `n_samples - 1`) is -1 when the axis is empty; used
    directly as the clamp's upper bound that makes `min(-1, max(0, ...))`
    return -1 -- a value numpy silently reads as the LAST element, not "none".
    Reachable from a header-only or truncated file where a count comes out 0.
    """
    empty_traces = ViewTransform.fit(
        n_traces=0, n_samples=512, t0_ns=-11.09, dt_ns=0.2165, width=800, height=300
    )
    assert empty_traces.trace_index_at(400.0) == 0
    empty_samples = ViewTransform.fit(
        n_traces=608, n_samples=0, t0_ns=-11.09, dt_ns=0.2165, width=800, height=300
    )
    assert empty_samples.sample_index_at(150.0) == 0


def test_empty_axis_forward_maps_do_not_divide_by_zero():
    """An empty axis (n_traces or n_samples == 0) is an established, valid
    ViewTransform state -- the test above pins its index lookups at 0. But
    `x_of_trace`/`y_of_time` divide by that same axis's span, which is 0.0 in
    exactly this state, and Task 14 calls both on every repaint
    (`_paint_cursor`, `_paint_axes`, the depth/time tick paths). Decision: an
    empty axis is HANDLED, not rejected at construction -- rejecting it would
    be a bigger change to fit()'s contract for a state that was just
    established as constructible (M6), and is already unreachable from a real
    DZT file (both `n_samples == 0` and a zero-trace file are refused by
    dzt.py). So the forward maps must simply not raise on it."""
    empty_traces = ViewTransform.fit(
        n_traces=0, n_samples=512, t0_ns=-11.09, dt_ns=0.2165, width=800, height=300
    )
    assert empty_traces.x_of_trace(0.0) == 0.0
    empty_samples = ViewTransform.fit(
        n_traces=608, n_samples=0, t0_ns=-11.09, dt_ns=0.2165, width=800, height=300
    )
    assert empty_samples.y_of_time(0.0) == 0.0


def test_source_rect_is_the_visible_window_in_image_pixels():
    assert FIT.source_rect() == (0.0, 0.0, 608.0, 512.0)
    z = FIT.with_window(100.0, 300.0, 0.0, 20.0)
    x, y, w, h = z.source_rect()
    assert (x, w) == (100.0, 200.0)
    assert y == pytest.approx((0.0 + 11.09) / 0.2165)
    assert h == pytest.approx(20.0 / 0.2165)


def test_zoom_keeps_the_point_under_the_anchor_fixed():
    trace_before = FIT.trace_of_x(600.0)
    time_before = FIT.time_of_y(100.0)
    z = FIT.zoomed(2.0, anchor_x=600.0, anchor_y=100.0)
    assert z.trace_of_x(600.0) == pytest.approx(trace_before)
    assert z.time_of_y(100.0) == pytest.approx(time_before)
    assert (z.trace_hi - z.trace_lo) == pytest.approx(304.0)


def test_minimum_span_constants_are_four():
    """`MIN_TRACE_SPAN`/`MIN_SAMPLE_SPAN` are in the brief's public interface
    list; pin their literal values here, not just "some minimum exists" --
    every other test compares against the imported symbol, which would still
    pass if the constant itself drifted."""
    assert MIN_TRACE_SPAN == 4.0
    assert MIN_SAMPLE_SPAN == 4.0


def test_zoom_is_clamped_to_the_data_and_a_minimum_span():
    out = FIT.zoomed(0.5, 400.0, 150.0)  # zooming out past the data extent
    assert (out.trace_lo, out.trace_hi) == (0.0, 608.0)
    assert (out.time_lo, out.time_hi) == pytest.approx((FIT.t0_ns, FIT.t_end))
    z = FIT
    for _ in range(40):
        z = z.zoomed(2.0, 400.0, 150.0)
    # Literal 4.0 / 4.0 * 0.2165, not the MIN_TRACE_SPAN/MIN_SAMPLE_SPAN
    # symbols: comparing the implementation against the very constant it
    # reads is a tautology that holds no matter what the constant's value is
    # (this was flagged on the trace axis by the original review and
    # reproduced on the time axis in the round meant to fix it -- see
    # test_minimum_span_constants_are_four for the one place the symbols'
    # own values are pinned).
    assert z.trace_hi - z.trace_lo == pytest.approx(4.0)
    assert z.trace_lo >= 0.0 and z.trace_hi <= 608.0
    assert z.time_hi - z.time_lo == pytest.approx(4.0 * 0.2165)  # 0.866 ns
    assert z.time_lo >= FIT.t0_ns and z.time_hi <= FIT.t_end


def test_pan_is_clamped_to_the_data():
    z = FIT.with_window(100.0, 300.0, 0.0, 20.0)
    p = z.panned(-100.0, 0.0)  # drag left by 100 px = 25 traces at 4 px/trace
    assert (p.trace_lo, p.trace_hi) == pytest.approx((125.0, 325.0))
    far = z.panned(-100_000.0, 0.0)
    assert (far.trace_lo, far.trace_hi) == (408.0, 608.0)
    up = z.panned(0.0, 100_000.0)
    assert up.time_lo == pytest.approx(-11.09)
    down = z.panned(0.0, -100_000.0)  # opposite drag: window moves toward later time
    assert down.time_hi == pytest.approx(FIT.t_end)


def test_resized_keeps_the_window():
    r = FIT.with_window(100.0, 300.0, 0.0, 20.0).resized(400, 150)
    assert (r.width, r.height) == (400, 150)
    assert (r.trace_lo, r.trace_hi, r.time_lo, r.time_hi) == (100.0, 300.0, 0.0, 20.0)
    assert r.x_of_trace(300.0) == 400.0


def test_degenerate_widget_sizes_are_floored_to_one_pixel():
    """A dock narrower than the axis margins (Task 14's `image_rect()`
    subtracts ~104 px) must not divide by zero on the next mouse move."""
    assert (FIT.resized(0, 0).width, FIT.resized(0, 0).height) == (1, 1)
    z = ViewTransform.fit(
        n_traces=608, n_samples=512, t0_ns=-11.09, dt_ns=0.2165, width=0, height=-5
    )
    assert (z.width, z.height) == (1, 1)
    z.trace_index_at(0.0)  # would raise ZeroDivisionError if width stayed 0


def test_nan_inputs_raise_instead_of_silently_poisoning_the_window():
    """A NaN factor/delta must not leave a partially-NaN transform that fails
    later, at an unrelated call site, with a confusing stack trace. Chosen
    behaviour: raise immediately, in `with_window`, where every window change
    (`zoomed`, `panned`, and direct calls) converges."""
    with pytest.raises(ValueError):
        FIT.zoomed(float("nan"), 400.0, 150.0)
    with pytest.raises(ValueError):
        FIT.panned(float("nan"), 0.0)
    with pytest.raises(ValueError):
        FIT.with_window(float("nan"), 110.0, 0.0, 20.0)


def test_construction_rejects_non_finite_axes_not_just_window_changes():
    """`with_window`'s guard covers the mutators (`zoomed`/`panned`/direct
    calls), but `fit()` is the choke point that receives floats straight off
    a DZT header, and it built a NaN window silently before this guard
    existed. `__post_init__` runs for every construction path -- `fit()`, a
    direct call, and the `replace()` `with_window`/`resized` use internally
    -- so putting the check there closes all three at once."""
    with pytest.raises(ValueError):
        ViewTransform.fit(
            n_traces=608, n_samples=512, t0_ns=float("nan"), dt_ns=0.2165, width=800, height=300
        )
    with pytest.raises(ValueError):
        ViewTransform.fit(
            n_traces=608, n_samples=512, t0_ns=-11.09, dt_ns=float("nan"), width=800, height=300
        )
    with pytest.raises(ValueError):
        ViewTransform(
            n_traces=608,
            n_samples=512,
            t0_ns=float("nan"),
            dt_ns=0.2165,
            width=800,
            height=300,
            trace_lo=0.0,
            trace_hi=608.0,
            time_lo=-11.09,
            time_hi=99.758,
        )


def test_nice_ticks():
    np.testing.assert_allclose(nice_ticks(0.0, 10.13), [0, 2, 4, 6, 8, 10])
    np.testing.assert_allclose(nice_ticks(-11.09, 99.8), [0, 20, 40, 60, 80])
    np.testing.assert_allclose(
        nice_ticks(0.0, 4.0, target=8), [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    )
    assert nice_ticks(5.0, 5.0).size == 0
