"""track_fit on synthetic zigzag surveys (GPS lines spec §16)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from nsgeo.geometry import Grid
from nsgeo.geometry.track_fit import fit_frame, main_direction, measure_spacing, metres_outside


def line(origin, bearing_deg, length, reverse, wobble, rng):
    b = math.radians(bearing_deg)
    along = np.array([math.sin(b), math.cos(b)])
    cross = np.array([math.cos(b), -math.sin(b)])
    s = np.arange(0.0, length + 1e-9, 0.1)
    if reverse:
        s = s[::-1]
    return (
        np.asarray(origin) + s[:, None] * along + (rng.normal(0.0, wobble, len(s)))[:, None] * cross
    )


def zigzag(n_lines, spacing, bearing_deg, length=30.0, wobble=0.03, seed=0):
    """Tracks walked alternately up and down at `bearing_deg`, `spacing` apart."""
    rng = np.random.default_rng(seed)
    b = math.radians(bearing_deg)
    cross = np.array([math.cos(b), -math.sin(b)])
    return [
        line(
            np.array([100.0, 200.0]) + i * spacing * cross,
            bearing_deg,
            length,
            i % 2 == 1,
            wobble,
            rng,
        )
        for i in range(n_lines)
    ]


def test_a_zigzag_survey_is_fitted_along_its_lines():
    tracks = zigzag(12, 0.5, 30.0)
    assert main_direction(tracks) == pytest.approx(30.0, abs=0.2)
    assert measure_spacing(tracks) == pytest.approx(0.5, abs=0.01)
    frame = fit_frame(tracks, 0.5)
    assert frame.lined_up and frame.azimuth == pytest.approx(30.0, abs=0.2)
    assert frame.size_x == pytest.approx(12 * 0.5, abs=0.05)  # outer means ± half a spacing
    assert frame.size_y == pytest.approx(30.0, abs=0.05)
    grid = frame.as_grid("G", "EPSG:32632", 0.5)
    local = np.vstack([grid.to_local(t) for t in tracks])
    assert local[:, 1].min() >= -1e-9 and local[:, 1].max() <= grid.size_y + 1e-9


def test_a_wandering_outer_line_grows_the_rectangle_to_hold_every_trace():
    # Walkthrough W3: the last line bulges 0.6 m outward over its middle third,
    # past the half-spacing margin; the grid grows to the bulge on that side only.
    tracks = zigzag(12, 0.5, 0.0, wobble=0.0)
    outer = tracks[-1].copy()
    middle = (outer[:, 1] > 210.0) & (outer[:, 1] < 220.0)
    outer[middle, 0] += 0.6
    tracks[-1] = outer
    frame = fit_frame(tracks, 0.5)
    assert frame.lined_up and frame.azimuth == pytest.approx(0.0, abs=0.1)
    grid = frame.as_grid("G", "EPSG:32632", 0.5)
    low_x, high_x, low_y, high_y = gaps_to_edges(grid, tracks)
    assert low_x == pytest.approx(0.25, abs=0.02)  # the straight side keeps its margin
    assert high_x == pytest.approx(0.0, abs=1e-6)  # the bulge's furthest trace is on the edge
    assert min(low_y, high_y) >= -1e-6


def test_reversed_lines_and_a_bearing_past_90_fold_to_one_azimuth():
    assert main_direction(zigzag(6, 0.5, 170.0)) == pytest.approx(170.0, abs=0.2)
    assert fit_frame(zigzag(6, 0.5, 170.0), 0.5).azimuth == pytest.approx(350.0, abs=0.2)


def test_one_line_has_no_spacing_and_a_typed_one_makes_it_one_spacing_wide():
    tracks = zigzag(1, 0.5, 10.0)
    assert measure_spacing(tracks) is None
    assert fit_frame(tracks, 0.8).size_x == pytest.approx(0.8, abs=1e-6)


def rotated(tracks, deg):
    """`tracks` turned `deg` degrees clockwise about the zigzag origin."""
    t = math.radians(deg)
    rot = np.array([[math.cos(t), math.sin(t)], [-math.sin(t), math.cos(t)]])
    o = np.array([100.0, 200.0])
    return [(p - o) @ rot.T + o for p in tracks]


def gaps_to_edges(grid, tracks):
    local = np.vstack([grid.to_local(t) for t in tracks])
    return [
        local[:, 0].min(),
        grid.size_x - local[:, 0].max(),
        local[:, 1].min(),
        grid.size_y - local[:, 1].max(),
    ]


def test_lines_in_every_direction_get_the_smallest_rectangle():
    tracks = zigzag(6, 0.5, 0.0) + zigzag(6, 0.5, 90.0)  # equal lengths, crossing
    assert main_direction(tracks) is None and measure_spacing(tracks) is None
    frame = fit_frame(tracks, 0.5)
    assert not frame.lined_up
    # every trace inside, and half a spacing in from each of the four sides
    grid = frame.as_grid("G", "EPSG:32632", 0.5)
    assert gaps_to_edges(grid, tracks) == pytest.approx([0.25] * 4, abs=1e-6)
    assert grid.size_y >= grid.size_x  # +Y along the longer side
    assert 0.0 <= frame.azimuth <= 90.0 or 270.0 <= frame.azimuth < 360.0


def test_a_turned_cross_hatch_gets_a_turned_rectangle_smaller_than_the_axis_aligned_one():
    tracks = rotated(zigzag(6, 0.5, 0.0) + zigzag(6, 0.5, 90.0), 30.0)
    frame = fit_frame(tracks, 0.5)
    assert not frame.lined_up
    assert frame.azimuth == pytest.approx(30.0, abs=0.5)
    area = frame.size_x * frame.size_y
    assert area == pytest.approx(1011.7, abs=1.0)
    pts = np.vstack(tracks)
    box = (np.ptp(pts[:, 0]) + 1.0) * (np.ptp(pts[:, 1]) + 1.0)
    assert area < 0.85 * box
    grid = frame.as_grid("G", "EPSG:32632", 0.5)
    assert gaps_to_edges(grid, tracks) == pytest.approx([0.25] * 4, abs=1e-6)


@pytest.mark.parametrize("turn", [0.0, 25.0, 90.0, 135.0, 200.0, 310.0])
def test_a_wide_cloud_gets_its_plus_y_along_the_longer_side(turn):
    # 6 lines walking east, 18 short ones walking north: even in length, so no main
    # direction; the smallest rectangle is about 30 long and 12.5 across.
    tracks = rotated(zigzag(6, 0.5, 90.0) + zigzag(18, 0.5, 0.0, length=10.0), turn)
    assert main_direction(tracks) is None
    frame = fit_frame(tracks, 0.5)
    assert not frame.lined_up
    assert frame.size_y == pytest.approx(30.5, abs=0.2)
    assert frame.size_x == pytest.approx(13.0, abs=0.2)
    grid = frame.as_grid("G", "EPSG:32632", 0.5)
    assert gaps_to_edges(grid, tracks) == pytest.approx([0.25] * 4, abs=1e-6)
    assert -90.0 < ((frame.azimuth + 90.0) % 360.0) - 90.0 <= 90.0 or frame.azimuth > 270.0


def test_short_lines_do_not_vote_and_a_cross_line_is_held_inside():
    along = zigzag(10, 0.5, 40.0)
    base = main_direction(along)
    b = math.radians(40.0)
    cross = np.array([math.cos(b), -math.sin(b)])
    rng = np.random.default_rng(1)
    away = np.array([100.0, 200.0]) + 8.0 * cross  # well past the outer along lines
    short = line(away, 100.0, 0.6, False, 0.0, rng)  # under 1 m: no vote
    crossing = line(away + [0.0, 3.0], 100.0, 1.5, False, 0.0, rng)  # 60° off: not along
    tracks = along + [short, crossing]
    assert main_direction(along + [short]) == base  # a short line leaves it exactly as it was
    assert main_direction(tracks) == pytest.approx(base, abs=0.3)
    assert measure_spacing(tracks) == pytest.approx(0.5, abs=0.01)
    frame = fit_frame(tracks, 0.5)
    assert frame.lined_up and frame.azimuth == pytest.approx(40.0, abs=0.3)
    assert frame.size_x > 8.0  # widened to reach the cross line, not 10 * 0.5
    grid = frame.as_grid("G", "EPSG:32632", 0.5)
    for t in tracks:
        local = grid.to_local(t)
        assert local[:, 0].min() >= -1e-9 and local[:, 0].max() <= grid.size_x + 1e-9
        assert local[:, 1].min() >= -1e-9 and local[:, 1].max() <= grid.size_y + 1e-9


def test_a_cross_line_beyond_the_ends_of_the_along_lines_stretches_the_rectangle_along():
    along = zigzag(10, 0.5, 40.0)
    b = math.radians(40.0)
    ahead = np.array([math.sin(b), math.cos(b)])
    cross = np.array([math.cos(b), -math.sin(b)])
    rng = np.random.default_rng(2)
    start = (
        np.array([100.0, 200.0]) + 33.0 * ahead + 2.0 * cross
    )  # past the far ends, inside across
    beyond = line(start, 100.0, 1.5, False, 0.0, rng)  # 60 degrees off: not along
    before = line(np.array([100.0, 200.0]) - 6.0 * ahead + 2.0 * cross, 100.0, 1.5, False, 0.0, rng)
    tracks = along + [beyond, before]
    frame = fit_frame(tracks, 0.5)
    assert frame.lined_up
    # far end 33 + 1.5 cos 60 = 33.75, near end -6: the along lines span only 0..30
    assert frame.size_y == pytest.approx(33.75 + 6.0, abs=0.15)
    grid = frame.as_grid("G", "EPSG:32632", 0.5)
    assert min(gaps_to_edges(grid, tracks)) >= -1e-9


def test_the_azimuth_stays_below_its_bound_for_a_line_a_hair_west_of_north():
    for dx in (-1e-15, -1e-14):
        track = np.array([[0.0, 0.0], [dx, 10.0]])  # near the origin, so dx is not absorbed
        main = main_direction([track])
        assert main is not None and 0.0 <= main < 180.0
        assert 0.0 <= fit_frame([track], 0.5).azimuth < 360.0


def test_the_same_line_twice_has_no_spacing_to_measure():
    track = zigzag(1, 0.5, 20.0)[0]
    assert measure_spacing([track, track]) is None


def two_point(x, y0, y1):
    return np.array([[x, y0], [x, y1]])


def test_an_almost_even_cross_hatch_still_has_no_main_direction():
    # 6 lines north and 6 east, the east ones longer by 2e-8 of their length: the
    # along set holds 0.5 + 5e-9 of the total, which is not more than half in any real sense.
    north = [two_point(100.0 + 0.5 * i, 200.0, 230.0) for i in range(6)]
    east = [two_point(200.0 + 0.5 * i, 0.0, 30.0 * (1.0 + 2e-8))[:, ::-1] for i in range(6)]
    assert main_direction(north + east) is None
    longer = [two_point(200.0 + 0.5 * i, 0.0, 30.0 * 1.001)[:, ::-1] for i in range(6)]
    assert main_direction(north + longer) == pytest.approx(90.0, abs=1e-6)


def test_metres_outside_counts_only_the_steps_outside():
    grid = Grid("G", (0.0, 0.0), 0.0, 10.0, 10.0, "EPSG:32632", 0.5)
    inside_then_out = np.column_stack([np.full(201, 5.0), np.linspace(0.0, 20.0, 201)])
    metres, any_in = metres_outside(grid, inside_then_out)
    assert metres == pytest.approx(10.0, abs=0.1) and any_in
    assert metres_outside(grid, inside_then_out + [30.0, 0.0]) == (
        pytest.approx(20.0, abs=0.1),
        False,
    )


def test_bad_input_is_refused():
    with pytest.raises(ValueError):
        fit_frame([], 0.5)
    with pytest.raises(ValueError):
        fit_frame([np.full((3, 2), np.nan)], 0.5)
    with pytest.raises(ValueError):
        fit_frame(zigzag(2, 0.5, 0.0), 0.0)
