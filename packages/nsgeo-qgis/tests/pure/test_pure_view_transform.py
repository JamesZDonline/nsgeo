from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from nsgeo_qgis.ui.trace_axis import TraceAxis
from nsgeo_qgis.ui.view_transform import (
    MIN_SAMPLE_SPAN,
    MIN_TRACE_SPAN,
    ViewTransform,
    carry_time_window,
    nice_ticks,
    true_scale_window,
)

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


def test_snap_cutoff_rounds_to_the_nearest_sample_boundary():
    t = ViewTransform.fit(100, 200, -4.0, 0.5, 400, 300)
    assert t.snap_cutoff(20.3) == pytest.approx(20.5)  # (20.3 + 4) / 0.5 = 48.6 -> 49
    assert t.snap_cutoff(20.2) == pytest.approx(20.0)


def test_snap_cutoff_clamps_into_the_record():
    t = ViewTransform.fit(100, 200, -4.0, 0.5, 400, 300)
    assert t.snap_cutoff(-100.0) == pytest.approx(-3.5)  # one sample kept
    assert t.snap_cutoff(1e6) == pytest.approx(t.t_end)


def test_snap_row_lands_on_row_tops_inside_the_record():
    t = ViewTransform.fit(10, 100, -2.0, 0.25, 696, 264)
    assert t.snap_row(-2.1) == -2.0
    assert t.snap_row(-1.6) == pytest.approx(-1.5)
    assert t.snap_row(99.0) == pytest.approx(-2.0 + 99 * 0.25)


def test_snap_row_clamps_to_the_first_and_last_row_not_the_end():
    t = ViewTransform.fit(10, 100, -2.0, 0.25, 696, 264)
    assert t.snap_row(-100.0) == -2.0
    assert t.snap_row(1e6) == pytest.approx(-2.0 + 99 * 0.25)  # not t_end: one row stays


MIR = ViewTransform.fit(
    n_traces=608, n_samples=512, t0_ns=-11.09, dt_ns=0.2165, width=800, height=300, mirrored=True
)
B = ViewTransform.fit(608, 512, -11.09, 0.2165, 800, 300, bounds=(-100.0, 668.0))


def test_a_mirrored_fit_puts_the_last_trace_on_the_left():
    assert MIR.x_of_trace(608) == 0.0 and MIR.x_of_trace(0) == 800.0
    assert MIR.trace_index_at(0.0) == 607 and MIR.trace_index_at(799.9) == 0
    for x in (0.0, 123.4, 799.0):
        assert MIR.x_of_trace(MIR.trace_of_x(x)) == pytest.approx(x)


def test_mirrored_index_lookups_use_the_screen_left_edge():
    z = MIR.with_window(100.0, 110.0, 0.0, 20.0)  # 80 px per trace, trace 109 leftmost
    assert [z.trace_index_at(x) for x in (0.0, 41.0, 79.9, 80.0, 80.1)] == [109, 109, 109, 108, 108]
    assert (
        z.trace_index_at(z.x_of_trace(106) + 0.1) == 105
    )  # trace 105 spans x_of_trace(106)..x_of_trace(105)


def test_mirrored_zoom_keeps_the_point_under_the_anchor_fixed():
    before = MIR.trace_of_x(600.0)
    z = MIR.zoomed(2.0, anchor_x=600.0, anchor_y=100.0)
    assert z.trace_of_x(600.0) == pytest.approx(before)
    assert z.trace_hi - z.trace_lo == pytest.approx(304.0)


def test_mirrored_pan_moves_the_data_with_the_pointer():
    z = MIR.with_window(100.0, 300.0, 0.0, 20.0)
    p = z.panned(-100.0, 0.0)  # drag left 100 px = 25 traces at 4 px/trace
    assert (p.trace_lo, p.trace_hi) == pytest.approx((75.0, 275.0))
    assert p.x_of_trace(150.0) == pytest.approx(z.x_of_trace(150.0) - 100.0)


def test_the_window_may_cover_the_bounds_not_just_the_data():
    assert (B.trace_lo, B.trace_hi) == (-100.0, 668.0) and B.trace_bounds == (-100.0, 668.0)
    assert (B.zoomed(0.5, 400.0, 150.0).trace_lo, B.zoomed(0.5, 400.0, 150.0).trace_hi) == (
        -100.0,
        668.0,
    )
    far = B.with_window(200.0, 400.0, 0.0, 20.0).panned(100_000.0, 0.0)
    assert (far.trace_lo, far.trace_hi) == (-100.0, 100.0)
    assert FIT.trace_bounds == (0.0, 608.0)


def test_trace_at_is_none_past_the_data_in_either_direction():
    for t in (B, dataclasses.replace(B, mirrored=True)):
        assert t.trace_at(t.x_of_trace(-30.0)) is None
        assert t.trace_at(t.x_of_trace(0.5)) == 0
        assert t.trace_at(t.x_of_trace(607.5)) == 607
        assert t.trace_at(t.x_of_trace(608.5)) is None


def test_traces_between_clamps_into_the_data_and_misses_blank_space():
    for t in (B, dataclasses.replace(B, mirrored=True)):
        x = t.x_of_trace
        assert t.traces_between(x(-30.0), x(10.5)) == (0, 10)
        assert t.traces_between(x(10.5), x(-30.0)) == (0, 10)
        assert t.traces_between(x(600.5), x(650.0)) == (600, 607)
        assert t.traces_between(x(-50.0), x(-10.0)) is None


def test_source_rect_and_target_span_cover_only_the_data():
    assert B.source_rect()[0] == 0.0 and B.source_rect()[2] == 608.0
    assert B.target_span() == pytest.approx((100 / 768 * 800, 708 / 768 * 800))
    m = dataclasses.replace(B, mirrored=True)
    assert m.target_span() == pytest.approx((60 / 768 * 800, 668 / 768 * 800))
    assert FIT.target_span() == (0.0, 800.0)


def test_a_window_in_blank_space_has_an_empty_source():
    z = B.with_window(-100.0, -50.0, 0.0, 20.0)
    assert z.source_rect()[2] == 0.0
    assert z.trace_at(400.0) is None and z.traces_between(0.0, 799.0) is None


def test_true_scale_sets_the_time_span_to_match_metres_across():
    t = ViewTransform.fit(200, 512, 0.0, 0.2, 696, 264).with_window(50.0, 100.0, 20.0, 60.0)
    s = true_scale_window(t, 1 / 60, 20.0)  # 60 traces/m; 0.1 m/ns -> 20 ns per metre of depth
    across = 696 / (50 / 60)
    assert s.time_hi - s.time_lo == pytest.approx(264 / across * 20.0)
    assert (s.time_lo + s.time_hi) / 2 == pytest.approx(40.0)
    assert (s.trace_lo, s.trace_hi) == pytest.approx((50.0, 100.0))


def test_true_scale_keeps_the_record_and_narrows_along_a_long_line():
    t = ViewTransform.fit(1800, 512, 0.0, 0.2, 696, 264)  # 30 m at 60 traces/m, 102.4 ns
    s = true_scale_window(t, 1 / 60, 20.0)
    assert (s.time_lo, s.time_hi) == pytest.approx((0.0, 102.4))
    assert s.trace_hi - s.trace_lo == pytest.approx(696 / (264 / (102.4 / 20.0)) * 60)
    assert (s.trace_lo + s.trace_hi) / 2 == pytest.approx(900.0)


def test_true_scale_on_a_mirrored_ruler_keeps_the_mirror():
    t = ViewTransform.fit(200, 512, 0.0, 0.2, 696, 264, bounds=(-20.0, 260.0), mirrored=True)
    t = t.with_window(50.0, 100.0, 20.0, 60.0)
    s = true_scale_window(t, 1 / 60, 20.0)
    across = 696 / (50 / 60)
    assert s.time_hi - s.time_lo == pytest.approx(264 / across * 20.0)
    assert (s.time_lo + s.time_hi) / 2 == pytest.approx(40.0)
    assert (s.trace_lo, s.trace_hi) == pytest.approx((50.0, 100.0))
    assert s.mirrored and s.bounds == (-20.0, 260.0)


def test_true_scale_at_the_clamps_hits_both_minimum_spans():
    t = ViewTransform.fit(200, 512, 0.0, 0.2, 696, 264).with_window(0.0, 4.0, 0.0, 0.8)
    s = true_scale_window(t, 1 / 60, 20.0)  # asks for 0.506 ns: the minimum time span wins
    assert s.time_hi - s.time_lo == pytest.approx(4 * 0.2)
    s = true_scale_window(ViewTransform.fit(200, 512, 0.0, 0.2, 696, 264), 1 / 60, 20000.0)
    assert s.trace_hi - s.trace_lo == pytest.approx(4.0)  # asks for 0.81 traces


def test_resized_keeps_the_mirror_and_the_bounds():
    r = dataclasses.replace(B, mirrored=True).resized(400, 150)
    assert r.mirrored and r.bounds == (-100.0, 668.0)


def test_bounds_must_be_finite_and_ordered():
    for bad in ((5.0, 5.0), (10.0, 0.0), (float("nan"), 10.0), (0.0, float("inf"))):
        with pytest.raises(ValueError, match="bounds"):
            ViewTransform.fit(608, 512, -11.09, 0.2165, 800, 300, bounds=bad)


def test_traces_between_agrees_with_trace_at_on_column_boundaries():
    w = ViewTransform.fit(2000, 512, -11.09, 0.2165, 800, 300)
    for t in (w, dataclasses.replace(w, mirrored=True)):
        for px in (0, 10, 11, 799):
            c = t.trace_at(float(px))
            assert t.traces_between(float(px), float(px)) == (c, c)
    assert FIT.traces_between(0.0, FIT.x_of_trace(19)) == (0, 19)


def _w():
    return ViewTransform.fit(200, 128, 0.0, 0.25, 696, 264).with_window(50.0, 100.0, 4.0, 12.0)


def test_fit_width_shows_every_trace_and_keeps_the_time_window():
    t = _w().fit_width()
    assert (t.trace_lo, t.trace_hi) == (0.0, 200.0)
    assert (t.time_lo, t.time_hi) == pytest.approx((4.0, 12.0))


def test_fit_height_shows_the_whole_record_and_keeps_the_trace_window():
    t = _w().fit_height()
    assert (t.trace_lo, t.trace_hi) == pytest.approx((50.0, 100.0))
    assert (t.time_lo, t.time_hi) == pytest.approx((0.0, 32.0))


def test_fit_width_on_a_mirrored_ruler_shows_the_ruler():
    w = ViewTransform.fit(200, 128, 0.0, 0.25, 696, 264, bounds=(-20.0, 260.0), mirrored=True)
    t = w.with_window(40.0, 90.0, 4.0, 12.0).fit_width()
    assert (t.trace_lo, t.trace_hi) == (-20.0, 260.0) and t.mirrored
    assert (t.time_lo, t.time_hi) == pytest.approx((4.0, 12.0))


# ---- a time window carried across a clock change (spec §4.8) -------------------


def _old():
    return ViewTransform.fit(200, 512, -11.0, 0.2, 696, 264)  # -11 .. 91.4 ns, radar clock


def test_a_whole_record_stays_whole():
    new = ViewTransform.fit(200, 460, 0.0, 0.2, 696, 264)
    c = carry_time_window(_old(), new, 0.0, -0.6)
    assert (c.time_lo, c.time_hi) == pytest.approx((0.0, 92.0))


def test_the_top_stays_the_top():
    old = _old().with_window(0.0, 200.0, -11.0, 4.0)
    new = ViewTransform.fit(200, 460, 0.0, 0.2, 696, 264)
    c = carry_time_window(old, new, 0.0, -0.6)
    assert (c.time_lo, c.time_hi) == pytest.approx((0.0, 15.0))


def test_a_window_in_the_middle_keeps_its_radar_times():
    old = _old().with_window(20.0, 120.0, 30.0, 45.0)
    new = ViewTransform.fit(200, 460, 0.0, 0.2, 696, 264)
    c = carry_time_window(old, new, 0.0, -0.6)
    assert (c.time_lo - 0.6, c.time_hi - 0.6) == pytest.approx((30.0, 45.0))  # radar = zero + t
    assert (c.trace_lo, c.trace_hi) == pytest.approx((20.0, 120.0))


# ---- a trace axis (M17c): screen x linear in metres along the line ------------
def _axis_vt(distance, *, width=800, height=300, mirrored=False, gap_m=None):
    n = len(distance)
    ax = TraceAxis.from_distance(distance, gap_m)
    return ViewTransform.fit(n, 512, 0.0, 0.2, width, height, mirrored=mirrored, axis=ax), ax


def _wspan(ax, t):
    return float(ax.walk_at(t.trace_hi) - ax.walk_at(t.trace_lo))


_UNEVEN = np.concatenate(
    [np.arange(15) * 0.02, 0.28 + np.arange(1, 16) * 0.05, 0.28 + 0.75 + 1.0 + np.arange(15) * 0.02]
)


def test_an_even_axis_matches_the_linear_transform():
    d = np.arange(20) * 0.05
    plain = ViewTransform.fit(20, 512, 0.0, 0.2, 800, 300)
    vt, _ = _axis_vt(d)
    for i in np.linspace(0.0, 20.0, 20):
        assert vt.x_of_trace(i) == pytest.approx(plain.x_of_trace(i), abs=1e-9)
    for x in np.linspace(0.0, 800.0, 20):
        assert vt.trace_of_x(x) == pytest.approx(plain.trace_of_x(x), abs=1e-9)


def test_x_is_linear_in_metres_along_the_line():
    vt, ax = _axis_vt(_UNEVEN)
    w0 = float(ax.walk_at(vt.trace_lo))
    xs = np.array([vt.x_of_trace(i + 0.5) for i in range(len(_UNEVEN))])
    m = _UNEVEN - w0
    k = xs[-1] / m[-1]
    assert xs == pytest.approx(m * k, abs=1e-6)
    assert vt.trace_of_x(vt.x_of_trace(7.3)) == pytest.approx(7.3)


def test_hover_in_a_gap_finds_no_trace():
    vt, ax = _axis_vt(_UNEVEN)
    mid = (_UNEVEN[14] + _UNEVEN[15]) / 2  # the first step is not a gap; use the real one
    gaps = np.flatnonzero(np.diff(_UNEVEN) > 6 * 0.02 * 1.01)
    assert gaps.size
    g = gaps[0]
    mid = (_UNEVEN[g] + _UNEVEN[g + 1]) / 2
    x = vt.x_of_trace(float(ax.units_at_walk(mid)))
    assert vt.trace_at(x) is None
    assert vt.trace_index_at(x) in (g, g + 1)
    assert vt.trace_at(vt.x_of_trace(3.5)) == 3


def test_zoom_keeps_the_metre_under_the_pointer():
    vt, ax = _axis_vt(_UNEVEN)
    for mirrored in (False, True):
        vt, ax = _axis_vt(_UNEVEN, mirrored=mirrored)
        before = float(ax.walk_at(vt.trace_of_x(300.0)))
        z = vt.zoomed(2.0, 300.0, 100.0)
        assert float(ax.walk_at(z.trace_of_x(300.0))) == pytest.approx(before, abs=1e-9)
        assert _wspan(ax, z) == pytest.approx(_wspan(ax, vt) / 2)


def test_pan_moves_by_metres():
    vt, ax = _axis_vt(_UNEVEN)
    z = vt.zoomed(3.0, 400.0, 100.0)
    p = z.panned(40.0, 0.0)
    wl = lambda t: float(ax.walk_at(t.trace_lo))  # noqa: E731
    wh = lambda t: float(ax.walk_at(t.trace_hi))  # noqa: E731
    assert wl(z) - wl(p) == pytest.approx(40.0 / 800 * (wh(z) - wl(z)), abs=1e-9)


def test_a_window_edge_inside_a_gap_survives_zoom_and_pan():
    vt, ax = _axis_vt(_UNEVEN)
    g = int(np.flatnonzero(np.diff(_UNEVEN) > 0.12)[0])
    mid = (_UNEVEN[g] + _UNEVEN[g + 1]) / 2
    centre = float(ax.units_at_walk(mid))
    t = vt.with_window(centre - 6, centre + 20, vt.time_lo, vt.time_hi)
    for out in (t.zoomed(1.5, 200.0, 10.0), t.zoomed(0.8, 600.0, 10.0), t.fit_width()):
        assert out.trace_hi > out.trace_lo
    p = t.panned(1.0, 0.0)
    span = float(ax.walk_at(t.trace_hi) - ax.walk_at(t.trace_lo))
    moved = float(ax.walk_at(t.trace_lo) - ax.walk_at(p.trace_lo))
    assert moved == pytest.approx(span / 800, abs=1e-9)


def test_true_scale_is_exact_on_an_uneven_axis():
    vt, ax = _axis_vt(_UNEVEN)
    vt = vt.zoomed(3.0, 400.0, 100.0)
    npm = 20.0  # ns per metre
    ts = true_scale_window(vt, 0.02, npm)
    wspan = float(ax.walk_at(ts.trace_hi) - ax.walk_at(ts.trace_lo))
    across = ts.width / wspan
    down = ts.height / ((ts.time_hi - ts.time_lo) / npm)
    assert across == pytest.approx(down, rel=0.01)


def test_true_scale_narrows_a_long_line_about_its_middle_metre():
    vt, ax = _axis_vt(_UNEVEN, height=3000)
    ts = true_scale_window(vt, 0.02, 20.0)
    assert (ts.time_lo, ts.time_hi) == (vt.t0_ns, vt.t_end)
    mid = (float(ax.walk_at(vt.trace_lo)) + float(ax.walk_at(vt.trace_hi))) / 2
    got = (float(ax.walk_at(ts.trace_lo)) + float(ax.walk_at(ts.trace_hi))) / 2
    assert got == pytest.approx(mid, abs=1e-6)


def test_paint_spans_cover_the_drawn_traces_and_skip_gaps():
    vt, ax = _axis_vt(_UNEVEN)
    spans = vt.paint_spans()
    assert len(spans) >= 3
    g = int(np.flatnonzero(np.diff(_UNEVEN) > 0.12)[0])
    gx = vt.x_of_trace(float(ax.units_at_walk((_UNEVEN[g] + _UNEVEN[g + 1]) / 2)))
    assert all(not (x0 < gx < x1) for x0, x1, _, _ in spans)
    assert all(x0 < x1 for x0, x1, _, _ in spans)
    lo, hi = ax.drawn()
    px_per_m = vt.width / float(ax.walk_at(vt.trace_hi) - ax.walk_at(vt.trace_lo))
    assert sum(x1 - x0 for x0, x1, _, _ in spans) == pytest.approx(
        float((hi - lo).sum()) * px_per_m, abs=1.0
    )


def test_a_mirrored_axis_puts_the_last_trace_on_the_left():
    vt, _ = _axis_vt(_UNEVEN, mirrored=True)
    assert vt.x_of_trace(len(_UNEVEN) - 0.5) < vt.x_of_trace(0.5)
    assert vt.trace_at(5.0) == len(_UNEVEN) - 1
    spans = vt.paint_spans()
    assert spans[0][0] < spans[-1][0]
    assert all(x0 < x1 for x0, x1, _, _ in spans)


def test_repeated_distances_give_finite_transforms():
    d = np.array([0.0, 0.02, 0.02, 0.02, 0.06, 0.08, 0.08, 0.1, 0.12, 0.14, 0.16, 0.18])
    vt, _ = _axis_vt(d)
    for x in (0.0, 100.0, 799.0):
        assert np.isfinite(vt.trace_of_x(x))
        assert np.isfinite(vt.x_of_trace(vt.trace_of_x(x)))
        vt.trace_index_at(x)
        vt.trace_at(x)
    for out in (vt.zoomed(2.0, 300.0, 5.0), vt.panned(10.0, 0.0), vt.fit_width()):
        assert np.isfinite(out.trace_lo) and np.isfinite(out.trace_hi)
    assert all(np.isfinite(v) for s in vt.paint_spans() for v in s[:2])
