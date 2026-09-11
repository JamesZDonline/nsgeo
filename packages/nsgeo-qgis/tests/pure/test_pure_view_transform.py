from __future__ import annotations

import numpy as np
import pytest
from nsgeo_qgis.ui.view_transform import MIN_TRACE_SPAN, ViewTransform, nice_ticks

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


def test_zoom_is_clamped_to_the_data_and_a_minimum_span():
    out = FIT.zoomed(0.5, 400.0, 150.0)  # zooming out past the data extent
    assert (out.trace_lo, out.trace_hi) == (0.0, 608.0)
    z = FIT
    for _ in range(40):
        z = z.zoomed(2.0, 400.0, 150.0)
    assert z.trace_hi - z.trace_lo == pytest.approx(MIN_TRACE_SPAN)
    assert z.trace_lo >= 0.0 and z.trace_hi <= 608.0


def test_pan_is_clamped_to_the_data():
    z = FIT.with_window(100.0, 300.0, 0.0, 20.0)
    p = z.panned(-100.0, 0.0)  # drag left by 100 px = 25 traces at 4 px/trace
    assert (p.trace_lo, p.trace_hi) == pytest.approx((125.0, 325.0))
    far = z.panned(-100_000.0, 0.0)
    assert (far.trace_lo, far.trace_hi) == (408.0, 608.0)
    up = z.panned(0.0, 100_000.0)
    assert up.time_lo == pytest.approx(-11.09)


def test_resized_keeps_the_window():
    r = FIT.with_window(100.0, 300.0, 0.0, 20.0).resized(400, 150)
    assert (r.width, r.height) == (400, 150)
    assert (r.trace_lo, r.trace_hi, r.time_lo, r.time_hi) == (100.0, 300.0, 0.0, 20.0)
    assert r.x_of_trace(300.0) == 400.0


def test_nice_ticks():
    np.testing.assert_allclose(nice_ticks(0.0, 10.13), [0, 2, 4, 6, 8, 10])
    np.testing.assert_allclose(nice_ticks(-11.09, 99.8), [0, 20, 40, 60, 80])
    np.testing.assert_allclose(
        nice_ticks(0.0, 4.0, target=8), [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    )
    assert nice_ticks(5.0, 5.0).size == 0
