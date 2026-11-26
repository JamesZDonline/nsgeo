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
from nsgeo.io import QUALITY_UNKNOWN, DzgFix, DzgLog
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

    # Fewer than two RTK fixes anchor on every positioned fix (§16): with one
    # fix, or none positioned, there is nothing to place, and nothing is projected.
    one = DzgLog((DzgFix(10, None, 45.2, 10.5, 4, None, None, None, None),), 0, 0)
    with pytest.raises(ValueError, match="^only one GPS position$"):
        track_from_log(one, to_xy, "X")
    nopos = DzgLog((DzgFix(10, None, float("nan"), float("nan"), 4, None, None, None, None),), 0, 0)
    with pytest.raises(ValueError, match="^no GPS position$"):
        track_from_log(nopos, to_xy, "X")


def test_one_rtk_fix_among_float_fixes_now_anchors_on_all_of_them():
    fixes = (
        DzgFix(10, None, 45.2, 10.5, 5, None, None, None, None),
        DzgFix(20, None, 45.2001, 10.5, 4, None, None, None, None),
        DzgFix(30, None, 45.2002, 10.5, 5, None, None, None, None),
    )
    t = track_from_log(DzgLog(fixes, 0, 0), _to_xy, "X", smooth_m=3.0)
    assert t.anchor_on == "all" and t.smooth_m == 3.0 and len(t.anchors()) == 3
    assert t.bridges() == ()


def test_frames_are_not_needed(header):
    c = _track(L_SHAPE).trace_coords(81, header, {})
    assert c.shape == (81, 2)


# ---- M21d: tracks without RTK, and smoothing (spec §16) -----------------------


def _to_xy(lon, lat):
    """A flat local projection about the made-up origin: metres per degree."""
    m = 111_320.0
    return (np.asarray(lon) - 10.5) * m * np.cos(np.radians(45.2)), (np.asarray(lat) - 45.2) * m


def _log(qualities, step_deg=0.00001):
    return DzgLog(
        tuple(
            DzgFix(10 * i, None, 45.2 + i * step_deg, 10.5, q, None, None, None, None)
            for i, q in enumerate(qualities)
        ),
        0,
        0,
    )


@pytest.mark.parametrize("n_rtk, anchor_on", [(0, "all"), (1, "all"), (2, "rtk"), (5, "rtk")])
def test_track_from_log_anchors_on_rtk_only_when_it_has_two(n_rtk, anchor_on):
    qualities = [4] * n_rtk + [2] * (20 - n_rtk)
    t = track_from_log(_log(qualities), _to_xy, "X", smooth_m=4.0)
    assert t.anchor_on == anchor_on
    assert t.smooth_m == (4.0 if anchor_on == "all" else 0.0)
    assert len(t.anchors()) == (20 if anchor_on == "all" else n_rtk)


def test_an_all_track_places_traces_on_every_positioned_fix(header):
    nan = float("nan")
    fixes = (
        _fix(0, 0.0, 0.0, 2),
        TrackFix(trace=5, x=nan, y=nan, lat=nan, lon=nan, quality=0),
        _fix(10, 1.0, 0.0, QUALITY_UNKNOWN),
        _fix(20, 1.0, 2.0, 1),
    )
    t = TrackPlacement(fixes=fixes, crs="LOCAL", anchor_on="all")
    pos = t.positions(21, header)
    np.testing.assert_allclose(pos[5], (0.5, 0.0), atol=1e-9)
    np.testing.assert_allclose(pos[15], (1.0, 1.0), atol=1e-9)
    assert t.bridges() == ()


def test_all_track_errors():
    with pytest.raises(ValueError, match="^no GPS position$"):
        _track([(1, float("nan"), float("nan"), 2)], anchor_on="all")
    with pytest.raises(ValueError, match="^only one GPS position$"):
        _track([(1, 0.0, 0.0, 2)], anchor_on="all")
    with pytest.raises(ValueError, match="^the GPS positions all lie at one point$"):
        _track([(1, 2.0, 3.0, 2), (2, 2.0, 3.0, 1)], anchor_on="all")
    with pytest.raises(ValueError, match=r"^smooth_m must be 0 or more, got -1\.0$"):
        _track([(1, 0.0, 0.0, 2), (2, 1.0, 0.0, 2)], anchor_on="all", smooth_m=-1.0)
    with pytest.raises(ValueError, match="^smoothing is for tracks without RTK$"):
        _track(L_SHAPE, smooth_m=2.0)
    with pytest.raises(ValueError, match="anchor_on must be"):
        _track(L_SHAPE, anchor_on="some")


def _jittered(smooth_m):
    """A straight east-going track, a fix every metre, alternating 1 m north and south."""
    points = [(10 * i, float(i), 1.0 if i % 2 else -1.0, 2) for i in range(61)]
    return _track(points, anchor_on="all", smooth_m=smooth_m)


def test_smoothing_evens_out_jitter_and_zero_changes_nothing(header):
    raw = _jittered(0.0)
    assert raw.placed_anchors() is raw.anchors() or raw.placed_anchors() == raw.anchors()
    assert all(a is b for a, b in zip(raw.placed_anchors(), raw.anchors()))
    pos = raw.positions(601, header)
    assert np.abs(pos[::10, 1]).min() == pytest.approx(1.0)

    smooth = _jittered(12.0)
    inner = [a.y for a in smooth.placed_anchors()[6:-6]]
    assert max(abs(y) for y in inner) < 0.1
    # The raw fixes are kept: only the placed anchors move.
    assert [f.y for f in smooth.fixes] == [f.y for f in raw.fixes]


def test_the_smoothing_window_is_in_metres_and_shrinks_at_the_ends():
    # Eleven fixes 1 m apart, ten traces apart; then the same line at twice the
    # fix density. A ±1 m window holds 3 fixes in the first and 5 in the second,
    # and the means come out the same: the window is in metres, not fixes.
    sparse = _track([(10 * i, float(i), 0.0, 2) for i in range(11)], anchor_on="all", smooth_m=2.0)
    dense = _track([(5 * i, 0.5 * i, 0.0, 2) for i in range(21)], anchor_on="all", smooth_m=2.0)
    xs = [a.x for a in sparse.placed_anchors()]
    assert xs[0] == pytest.approx(0.5) and xs[5] == pytest.approx(5.0)
    assert xs[10] == pytest.approx(9.5)
    xd = [a.x for a in dense.placed_anchors()]
    assert xd[0] == pytest.approx(0.5) and xd[10] == pytest.approx(5.0)
    assert xd[20] == pytest.approx(9.5)


def test_thinned_length_ignores_jitter_but_keeps_the_end():
    from nsgeo.geometry.track import thinned_length

    xy = np.array([(float(i), 1.0 if i % 2 else -1.0) for i in range(101)])
    raw = float(np.hypot(*np.diff(xy, axis=0).T).sum())
    assert raw > 200
    # 2 m of peak-to-peak jitter still adds about 8 % at a 5 m step, against 124 % raw.
    assert 100.0 < thinned_length(xy) < 110.0
    assert thinned_length(xy[:1]) == 0.0


def test_ends_and_heading_use_the_smoothed_anchors(header):
    smooth = _jittered(12.0)
    pos = smooth.positions(611, header)
    # Past the last anchor the line runs on at the smoothed heading: east, not
    # zig-zagging north or south by the last fix's jitter.
    assert abs(pos[610, 1] - pos[600, 1]) < 0.2
    start, end = smooth.end_runs(611, header)
    assert start == 0.0 and end == pytest.approx(10 * (1 / header.traces_per_metre))
