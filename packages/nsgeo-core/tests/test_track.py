from __future__ import annotations

import warnings

import numpy as np
import pytest
from nsgeo.geometry.track import (
    END_LIMIT_M,
    HEADING_BASE_M,
    Bridge,
    TrackFix,
    TrackPlacement,
    track_from_log,
)
from nsgeo.io import DzgFix, DzgLog
from nsgeo.io.dzt import read_header

from tests.synthetic import write_dzt


def _header(tmp_path, traces_per_metre=10.0):
    p = tmp_path / "h.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32), traces_per_metre=traces_per_metre)
    return read_header(p)


@pytest.fixture
def header(tmp_path):
    return _header(tmp_path)


def _fix(trace, x, y, quality=4):
    return TrackFix(trace=trace, x=x, y=y, lat=45.2, lon=10.5, quality=quality)


def _track(points, **kw):
    """`points` are (trace, x, y) anchors or (trace, x, y, quality)."""
    return TrackPlacement(fixes=tuple(_fix(*p) for p in points), crs="LOCAL", **kw)


L_SHAPE = [(10, 0.0, 0.0), (40, 3.0, 0.0), (70, 3.0, 4.0)]


def test_constants():
    assert END_LIMIT_M == 2.0
    assert HEADING_BASE_M == 1.0


def test_traces_between_fixes_are_spaced_evenly_by_trace(header):
    pos = _track(L_SHAPE).positions(81, header)
    np.testing.assert_allclose(pos[25], (1.5, 0.0), atol=1e-9)
    np.testing.assert_allclose(pos[55], (3.0, 2.0), atol=1e-9)
    np.testing.assert_allclose(pos[10], (0.0, 0.0), atol=1e-9)
    np.testing.assert_allclose(pos[70], (3.0, 4.0), atol=1e-9)


def test_distance_along_is_the_walked_path(header):
    d = _track(L_SHAPE).distance_along(81, header)
    assert d.shape == (81,)
    assert d[70] - d[10] == pytest.approx(7.0)
    assert (np.diff(d) >= 0).all()


def test_the_start_runs_on_by_wheel_along_the_heading(header):
    pos = _track([(5, 0.0, 0.0), (25, 2.0, 0.0)]).positions(31, header)
    np.testing.assert_allclose(pos[0], (-0.5, 0.0), atol=1e-9)
    np.testing.assert_allclose(pos[30], (2.5, 0.0), atol=1e-9)


def test_the_end_runs_on_along_the_last_segments_heading(header):
    pos = _track([(5, 0.0, 0.0), (25, 0.0, 2.0)]).positions(31, header)
    np.testing.assert_allclose(pos[30], (0.0, 2.5), atol=1e-9)
    np.testing.assert_allclose(pos[0], (0.0, -0.5), atol=1e-9)


def test_the_heading_uses_an_anchor_at_least_a_metre_away(header):
    pos = _track([(5, 0.0, 0.0), (7, 0.1, 0.15), (25, 2.0, 0.0)]).positions(31, header)
    assert pos[0, 1] == pytest.approx(0.0, abs=1e-9)
    np.testing.assert_allclose(pos[0, 0], -0.5, atol=1e-9)


def test_the_end_heading_skips_a_jittery_anchor_too(header):
    pts = [(5, 0.0, 0.0), (23, 1.9, 0.0), (25, 2.0, 0.1)]
    pos = _track(pts).positions(31, header)
    # (1.9, 0) is within a metre of the end anchor: the heading comes from (0, 0)
    heading = np.array([2.0, 0.1]) / np.hypot(2.0, 0.1)
    np.testing.assert_allclose(pos[30], np.array([2.0, 0.1]) + 0.5 * heading, atol=1e-9)


def test_when_no_anchor_is_a_metre_away_the_farthest_is_used(header):
    pos = _track([(5, 0.0, 0.0), (7, 0.1, 0.0), (10, 0.5, 0.2)]).positions(15, header)
    # farthest anchor from the start is (0.5, 0.2): the run goes straight back from it
    d = np.array([0.5, 0.2]) / np.hypot(0.5, 0.2)
    np.testing.assert_allclose(pos[0], -0.5 * d, atol=1e-9)


def test_a_time_triggered_line_runs_on_at_its_end_segments_spacing(tmp_path):
    h = _header(tmp_path, traces_per_metre=0.0)
    assert not h.traces_per_metre > 0
    pos = _track([(5, 0.0, 0.0), (25, 2.0, 0.0)]).positions(31, h)
    np.testing.assert_allclose(pos[0], (-0.5, 0.0), atol=1e-9)
    # the end uses the last segment, not the first
    pos = _track([(5, 0.0, 0.0), (15, 2.0, 0.0), (25, 2.0, 1.0)]).positions(31, h)
    np.testing.assert_allclose(pos[0], (-1.0, 0.0), atol=1e-9)
    np.testing.assert_allclose(pos[30], (2.0, 1.5), atol=1e-9)


def test_float_and_plain_fixes_are_bridged_not_used(header):
    t = _track([(10, 0.0, 0.0), (30, 2.0, 0.5, 5), (50, 4.0, 0.0)])
    np.testing.assert_allclose(t.positions(60, header)[30], (2.0, 0.0), atol=1e-9)
    assert t.bridges() == (Bridge(10, 50, 4.0),)
    assert [a.trace for a in t.anchors()] == [10, 50]


def test_a_fix_with_no_position_still_marks_a_bridge(header):
    t = _track([(10, 0.0, 0.0), (30, float("nan"), float("nan"), 0), (50, 4.0, 0.0)])
    np.testing.assert_allclose(t.positions(60, header)[30], (2.0, 0.0), atol=1e-9)
    assert t.bridges() == (Bridge(10, 50, 4.0),)


def test_a_quality_4_fix_without_a_position_is_not_an_anchor():
    t = _track([(10, 0.0, 0.0), (30, float("nan"), float("nan"), 4), (50, 4.0, 0.0)])
    assert [a.trace for a in t.anchors()] == [10, 50]
    assert len(t.bridges()) == 1


def test_consecutive_anchors_make_no_bridge():
    assert _track(L_SHAPE).bridges() == ()


def test_bridges_come_in_trace_order():
    t = _track(
        [(0, 0.0, 0.0), (5, 0.5, 0.0, 2), (10, 1.0, 0.0), (20, 2.0, 0.0), (22, 2.0, 0.0, 1),
         (30, 3.0, 4.0)]
    )  # fmt: skip
    assert t.bridges() == (Bridge(0, 10, 1.0), Bridge(20, 30, np.hypot(1.0, 4.0)))


def test_travel_shift_moves_every_trace_forward_along_the_path(header):
    straight = [(10, 0.0, 0.0), (40, 3.0, 0.0)]
    base = _track(straight).positions(81, header)
    moved = _track(straight, travel_shift=0.24).trace_coords(81, header, {})
    np.testing.assert_allclose(moved[:, 0], base[:, 0] + 0.24, atol=1e-9)
    np.testing.assert_allclose(moved[:, 1], base[:, 1], atol=1e-9)

    corner = _track(L_SHAPE, travel_shift=0.24).trace_coords(81, header, {})
    # trace 38 is 0.2 m before the corner: 0.04 m past it, up the +y leg
    np.testing.assert_allclose(corner[38], (3.0, 0.04), atol=1e-9)

    plain = _track(L_SHAPE).distance_along(81, header)
    shifted = _track(L_SHAPE, travel_shift=0.24).distance_along(81, header)
    np.testing.assert_allclose(shifted - plain, 0.24, atol=1e-12)


def test_a_shift_past_the_end_continues_along_the_last_heading(header):
    t = _track([(10, 0.0, 0.0), (40, 3.0, 0.0), (70, 3.0, 4.0)], travel_shift=0.5)
    c = t.trace_coords(71, header, {})
    np.testing.assert_allclose(c[70], (3.0, 4.5), atol=1e-9)


def test_a_negative_shift_runs_back_past_the_start_in_a_straight_line(header):
    t = _track([(0, 0.0, 0.0), (30, 0.0, 3.0)], travel_shift=-0.3)
    c = t.trace_coords(31, header, {})
    np.testing.assert_allclose(c[0], (0.0, -0.3), atol=1e-9)
    np.testing.assert_allclose(c[1], (0.0, -0.2), atol=1e-9)
    np.testing.assert_allclose(c[30], (0.0, 2.7), atol=1e-9)
    d = t.distance_along(31, header)
    assert d[0] == pytest.approx(-0.3)


def test_coincident_positions_do_not_divide_by_zero(header):
    t = _track([(10, 0.0, 0.0), (20, 0.0, 0.0), (30, 2.0, 0.0)], travel_shift=0.1)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        c = t.trace_coords(41, header, {})
    assert np.isfinite(c).all()
    np.testing.assert_allclose(c[30], (2.1, 0.0), atol=1e-9)


def _no_warnings_coords(t, n, header):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return t.trace_coords(n, header, {})


@pytest.mark.parametrize("shift", [0.0, 0.3])
def test_a_path_ending_in_coincident_positions_extends_along_its_last_real_segment(header, shift):
    # traces 30-40 all sit at one point: the last segments have no length
    t = _track([(20, 0.0, 0.0), (30, 2.0, 0.0), (40, 2.0, 0.0)], travel_shift=shift)
    c = _no_warnings_coords(t, 41, header)
    assert np.isfinite(c).all()
    np.testing.assert_allclose(c[40], (2.0 + shift, 0.0), atol=1e-9)
    np.testing.assert_allclose(c[30], (2.0 + shift, 0.0), atol=1e-9)


@pytest.mark.parametrize("shift", [0.0, -0.3])
def test_a_path_starting_in_coincident_positions_extends_along_its_first_real_segment(
    header, shift
):
    # traces 0-10 all sit at one point: the first segments have no length
    t = _track([(0, 0.0, 0.0), (10, 0.0, 0.0), (20, 2.0, 0.0)], travel_shift=shift)
    c = _no_warnings_coords(t, 21, header)
    assert np.isfinite(c).all()
    np.testing.assert_allclose(c[0], (shift, 0.0), atol=1e-9)
    np.testing.assert_allclose(c[20], (2.0 + shift, 0.0), atol=1e-9)


def test_the_start_heading_takes_the_first_anchor_in_trace_order_not_the_nearest(header):
    # the track turns back: (0, 1.2) is nearer than (3, 0) but comes later
    pos = _track([(5, 0.0, 0.0), (15, 3.0, 0.0), (25, 0.0, 1.2)]).positions(31, header)
    np.testing.assert_allclose(pos[0], (-0.5, 0.0), atol=1e-9)


def test_the_end_heading_takes_the_first_anchor_in_reverse_order_not_the_nearest(header):
    pos = _track([(5, 0.0, 1.2), (15, 3.0, 0.0), (25, 0.0, 0.0)]).positions(31, header)
    np.testing.assert_allclose(pos[30], (-0.5, 0.0), atol=1e-9)


def test_fewer_than_two_anchors_or_one_point_is_refused():
    with pytest.raises(ValueError, match="no RTK-fixed position"):
        _track([(1, 0.0, 0.0, 5), (2, 1.0, 0.0, 0)])
    with pytest.raises(ValueError, match="only one RTK-fixed position"):
        _track([(1, 0.0, 0.0), (2, 1.0, 0.0, 5)])
    with pytest.raises(ValueError, match="all lie at one point"):
        _track([(1, 2.0, 3.0), (2, 2.0, 3.0)])
    with pytest.raises(ValueError, match="trace numbers must rise along a GPS track"):
        _track([(5, 0.0, 0.0), (5, 1.0, 0.0)])
    with pytest.raises(ValueError, match="trace numbers must rise along a GPS track"):
        _track([(5, 0.0, 0.0), (9, 1.0, 0.0), (7, 2.0, 0.0, 5)])
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="travel_shift must be finite"):
            _track(L_SHAPE, travel_shift=bad)


def test_end_runs_are_the_metres_beyond_the_first_and_last_anchor(header):
    t = _track([(5, 0.0, 0.0), (25, 2.0, 0.0)])
    assert t.end_runs(31, header) == pytest.approx((0.5, 0.5))
    assert t.end_runs(26, header) == pytest.approx((0.5, 0.0))
    assert _track([(0, 0.0, 0.0), (25, 2.0, 0.0)]).end_runs(26, header) == (0.0, 0.0)


def test_a_track_is_hashable_and_compares_by_value():
    a, b = _track(L_SHAPE), _track(L_SHAPE)
    assert a == b and hash(a) == hash(b)
    assert a != _track(L_SHAPE, travel_shift=0.1)


def test_no_position_fixes_compare_and_hash_by_value(header):
    def fixes(nan):
        return (
            _fix(10, 0.0, 0.0),
            TrackFix(30, nan, nan, nan, nan, None, None, 0),
            _fix(50, 4.0, 0.0),
        )

    nans = [float("nan"), float("nan"), float("nan"), np.nan, np.float64("nan")]
    placements = [TrackPlacement(fixes=fixes(n), crs="LOCAL") for n in nans]
    for other in placements[1:]:
        assert other == placements[0] and hash(other) == hash(placements[0])
    changed = TrackPlacement(
        fixes=(
            _fix(10, 0.0, 0.0),
            TrackFix(30, np.nan, np.nan, np.nan, np.nan, 1.0, None, 0),
            _fix(50, 4.0, 0.0),
        ),
        crs="LOCAL",
    )
    assert changed != placements[0]
    # a real value that differs from the NaN stays unequal, and None is not NaN
    assert TrackFix(1, 0.0, 0.0, 0.0, 0.0) != TrackFix(1, np.nan, 0.0, 0.0, 0.0)
    assert TrackFix(1, 0.0, 0.0, 0.0, 0.0, None) != TrackFix(1, 0.0, 0.0, 0.0, 0.0, np.nan)
    assert TrackFix(1, 0.0, 0.0, 0.0, 0.0) != "not a fix"


def test_two_placements_from_the_same_log_are_equal():
    def to_xy(lon, lat):
        return lon * 100.0, lat * 100.0

    nan = float("nan")
    log = DzgLog(
        (
            DzgFix(10, 1.0, 45.20, 10.50, 4, 20, 0.6, 120.0, 47.5),
            DzgFix(20, 2.0, nan, nan, 0, None, None, None, None),
            DzgFix(30, 3.0, 45.21, 10.51, 4, 20, 0.6, 121.0, 47.5),
        ),
        0,
        0,
    )
    a, b = track_from_log(log, to_xy, "X"), track_from_log(log, to_xy, "X")
    assert a == b and hash(a) == hash(b)


def test_track_from_log_projects_with_the_given_function_and_keeps_lat_lon():
    def to_xy(lon, lat):
        return lon * 100.0, lat * 100.0

    nan = float("nan")
    fixes = (
        DzgFix(10, 1.0, 45.20, 10.50, 4, 20, 0.6, 120.0, 47.5),
        DzgFix(20, 2.0, nan, nan, 0, None, None, None, None),
        DzgFix(30, 3.0, 45.21, 10.51, 4, 20, 0.6, 121.0, 47.5),
        DzgFix(40, 4.0, 45.22, 10.52, 5, 20, 0.6, 122.0, 47.5),
    )
    t = track_from_log(DzgLog(fixes, 0, 0), to_xy, "EPSG:32632", label="L1")
    assert t.crs == "EPSG:32632" and t.label == "L1"
    assert [f.trace for f in t.fixes] == [10, 20, 30, 40]
    assert (t.fixes[0].x, t.fixes[0].y) == (1050.0, 4520.0)
    assert (t.fixes[0].lat, t.fixes[0].lon) == (45.20, 10.50)
    assert (t.fixes[0].alt_m, t.fixes[0].geoid_m, t.fixes[0].quality) == (120.0, 47.5, 4)
    assert np.isnan(t.fixes[1].x) and np.isnan(t.fixes[1].lat) and t.fixes[1].quality == 0
    assert (t.fixes[3].x, t.fixes[3].quality) == (1052.0, 5)
    assert t.bridges() == (Bridge(10, 30, pytest.approx(np.hypot(1.0, 1.0))),)


def test_track_from_log_refuses_before_building():
    def to_xy(lon, lat):
        raise AssertionError("must not project")

    one = DzgLog((DzgFix(10, None, 45.2, 10.5, 4, None, None, None, None),), 0, 0)
    with pytest.raises(ValueError, match="^only one RTK-fixed position$"):
        track_from_log(one, to_xy, "X")
    none = DzgLog((DzgFix(10, None, 45.2, 10.5, 5, None, None, None, None),), 0, 0)
    with pytest.raises(ValueError, match="^no RTK-fixed position$"):
        track_from_log(none, to_xy, "X")
    nopos = DzgLog((DzgFix(10, None, float("nan"), float("nan"), 4, None, None, None, None),), 0, 0)
    with pytest.raises(ValueError, match="^no RTK-fixed position$"):
        track_from_log(nopos, to_xy, "X")


def test_frames_are_not_needed(header):
    c = _track(L_SHAPE).trace_coords(81, header, {})
    assert c.shape == (81, 2)
