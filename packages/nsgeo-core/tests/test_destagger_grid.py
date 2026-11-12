"""The grid-wide destagger value, measured on the real Nashville grids (#159).

Expected values are the 2026-11-11 spike's, which the user's by-eye values
agree with on Grid 1 unfitted. Real files only: a skipped test validated nothing.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import replace

import numpy as np
import pytest
from nsgeo.destagger import (
    LineStatus,
    MeasureLine,
    MeasureStopped,
    envelope_bins,
    measure_destagger,
)
from nsgeo.destagger import measure as m
from nsgeo.destagger.profiles import search_range_m
from nsgeo.io.dzt import read_header, read_samples

from tests.destagger_data import (
    GRID1_LENGTH,
    GRID2_LENGTH,
    lines_for,
    needs_grid1,
    needs_grid2,
    with_header,
)
from tests.real_data import GPS_LINES, GRID2_LINES


@pytest.fixture(scope="module")
def grid1_unfitted():
    return measure_destagger(lines_for(GPS_LINES, GRID1_LENGTH))


@pytest.fixture(scope="module")
def grid1_lines():
    return lines_for(GPS_LINES, GRID1_LENGTH)


@needs_grid1
def test_grid1_unfitted_gives_the_value_found_by_eye(grid1_unfitted):
    axis = grid1_unfitted.axes["y"]
    assert axis.destagger == pytest.approx(0.15, abs=0.02)
    assert axis.spread_m < 0.02
    assert axis.lines_used == 60


@needs_grid1
def test_grid1_fitted_gives_the_whole_grid_value():
    result = measure_destagger(lines_for(GPS_LINES, GRID1_LENGTH, fitted=True))
    assert result.axes["y"].destagger == pytest.approx(-0.065, abs=0.02)


@needs_grid2
def test_grid2_unfitted_and_fitted():
    unfitted = measure_destagger(lines_for(GRID2_LINES, GRID2_LENGTH))
    fitted = measure_destagger(lines_for(GRID2_LINES, GRID2_LENGTH, fitted=True))
    assert unfitted.axes["y"].destagger == pytest.approx(0.165, abs=0.02)
    assert fitted.axes["y"].destagger == pytest.approx(-0.059, abs=0.02)


@needs_grid1
def test_the_current_destagger_is_ignored(grid1_unfitted):
    same = measure_destagger(lines_for(GPS_LINES, GRID1_LENGTH, travel_shift=0.3))
    varied = measure_destagger(
        lines_for(GPS_LINES, GRID1_LENGTH, travel_shift=[0.05 * (k % 7) - 0.1 for k in range(60)])
    )
    assert same == grid1_unfitted
    assert varied == grid1_unfitted


@needs_grid1
def test_mirrored_lines_give_the_same_values(grid1_unfitted):
    mirrored = measure_destagger(lines_for(GPS_LINES, GRID1_LENGTH, mirrored=True))
    assert mirrored.axes["y"].destagger == pytest.approx(
        grid1_unfitted.axes["y"].destagger, abs=0.005
    )
    flipped = [
        k for k, ln in grid1_unfitted.lines.items() if mirrored.lines[k].status is not ln.status
    ]
    assert len(flipped) <= 2  # borderline lines may cross a threshold
    for key, ln in grid1_unfitted.lines.items():
        other = mirrored.lines[key]
        if ln.status is LineStatus.OWN and other.status is LineStatus.OWN:
            assert other.destagger == pytest.approx(ln.destagger, abs=0.02)


@needs_grid1
def test_the_input_order_does_not_change_the_result(grid1_unfitted):
    reverse = measure_destagger(list(reversed(lines_for(GPS_LINES, GRID1_LENGTH))))
    assert reverse.axes == grid1_unfitted.axes  # the destagger and the spread, exactly
    assert reverse.lines == grid1_unfitted.lines


def test_when_every_line_is_too_short_the_axis_says_none_could_be_measured(tmp_path):
    from nsgeo.geometry import GridPlacement

    from tests.synthetic import write_dzt

    lines = []
    for i in range(6):
        path = tmp_path / f"F{i}.DZT"
        rng = np.random.default_rng(i)
        write_dzt(path, (rng.normal(size=(512, 300)) * 1e6).astype(np.int32))  # 5 m
        header = read_header(path)
        bins = envelope_bins(read_samples(path, header)[0], header.dt_ns, header.position_ns)
        placement = GridPlacement(
            "G", "y", 0.25 + 0.5 * i, 0.0 if i % 2 == 0 else 5.0, 1 - 2 * (i % 2)
        )
        lines.append(MeasureLine(path.name, bins, placement, header))
    result = measure_destagger(lines)
    assert result.axes["y"].destagger is None
    assert result.axes["y"].reason == m.NO_LINES
    assert all(
        ln.status is LineStatus.NOT_MEASURED and ln.reason == m.TOO_SHORT
        for ln in result.lines.values()
    )


@needs_grid1
def test_measuring_twice_gives_identical_results(grid1_lines, grid1_unfitted):
    assert measure_destagger(grid1_lines) == grid1_unfitted


@needs_grid1
def test_a_line_without_a_distance_axis_is_not_measured(grid1_lines):
    lines = list(grid1_lines)
    lines[30] = with_header(lines[30], traces_per_metre=0.0)
    result = measure_destagger(lines)
    line = result.lines[lines[30].key]
    assert line.status is LineStatus.NOT_MEASURED
    assert line.reason == m.NO_DISTANCE
    assert line.destagger is None
    assert result.axes["y"].destagger == pytest.approx(0.15, abs=0.02)


@needs_grid1
def test_a_short_line_is_not_measured(grid1_lines):
    lines = list(grid1_lines)
    lines[30] = replace(lines[30], bins=replace(lines[30].bins, data=lines[30].bins.data[:, :300]))
    line = measure_destagger(lines).lines[lines[30].key]
    assert line.status is LineStatus.NOT_MEASURED
    assert line.reason == m.TOO_SHORT


@needs_grid1
def test_a_line_with_other_time_settings_is_not_measured(grid1_lines):
    lines = list(grid1_lines)
    lines[30] = replace(lines[30], bins=replace(lines[30].bins, t0_ns=lines[30].bins.t0_ns + 1.0))
    line = measure_destagger(lines).lines[lines[30].key]
    assert line.status is LineStatus.NOT_MEASURED
    assert line.reason == m.TIME_SETTINGS


@needs_grid1
def test_lines_all_walked_one_way_measure_nothing(grid1_lines):
    """Every line keeps its own exclusion reason: with no opposite neighbour that is
    NO_NEIGHBOUR, and the axis says ONE_WAY."""
    lines = [replace(ln, placement=replace(ln.placement, direction=1)) for ln in grid1_lines]
    result = measure_destagger(lines)
    assert result.axes["y"].destagger is None
    assert result.axes["y"].reason == m.ONE_WAY
    assert all(
        ln.status is LineStatus.NOT_MEASURED and ln.reason == m.NO_NEIGHBOUR
        for ln in result.lines.values()
    )


def _same_result(got, expected):
    """DestaggerResults equal field by field: a failed axis's spread is nan."""
    assert got is not None
    assert list(got.axes) == list(expected.axes)
    for axis, a in expected.axes.items():
        b = got.axes[axis]
        assert (b.destagger, b.lines_used, b.reason) == (a.destagger, a.lines_used, a.reason)
        assert np.isnan(b.spread_m) and np.isnan(a.spread_m)
    assert got.lines == expected.lines
    assert list(got.lines) == list(expected.lines)


@needs_grid1
@pytest.mark.parametrize("direction", [1, -1])
def test_a_one_way_grid_is_known_from_its_placements_alone(grid1_lines, direction):
    """`one_way_result` gives what reading and measuring every line gives, so a grid
    walked one way need not be read (walkthrough D1)."""
    lines = [
        replace(ln, placement=replace(ln.placement, direction=direction)) for ln in grid1_lines
    ]
    got = m.one_way_result({ln.key: ln.placement for ln in lines})
    _same_result(got, measure_destagger(lines))


@needs_grid1
def test_a_lone_line_is_known_from_its_placement_alone(grid1_lines):
    got = m.one_way_result({grid1_lines[0].key: grid1_lines[0].placement})
    _same_result(got, measure_destagger(grid1_lines[:1]))


@needs_grid1
def test_a_grid_walked_both_ways_must_be_read(grid1_lines):
    assert m.one_way_result({ln.key: ln.placement for ln in grid1_lines}) is None
    # One axis walked both ways is enough, even beside an axis walked one way.
    x = [
        replace(ln, key=f"x{k}", placement=replace(ln.placement, axis="x", direction=1))
        for k, ln in enumerate(grid1_lines[:4])
    ]
    assert m.one_way_result({ln.key: ln.placement for ln in grid1_lines + x}) is None


@needs_grid1
def test_a_line_with_no_opposite_neighbour_is_not_measured(grid1_lines):
    lines = list(grid1_lines)
    lines[0] = replace(lines[0], placement=replace(lines[0].placement, direction=-1))
    result = measure_destagger(lines)
    line = result.lines[lines[0].key]
    assert line.status is LineStatus.NOT_MEASURED
    assert line.reason == m.NO_NEIGHBOUR
    assert result.axes["y"].lines_used == 59  # line 2 still has line 3


@needs_grid1
@needs_grid2
def test_unrelated_lines_have_no_clear_match():
    """Alternate Grid 1 and Grid 2 lines: real lines from different surveys, so nothing
    in one matches the other. They still peak at the same lag, a faint hump about a tenth
    of a real grid's, so the peak is clear in shape and fails on strength."""
    a = lines_for(GPS_LINES, GRID1_LENGTH)
    b = lines_for(GRID2_LINES, GRID2_LENGTH)
    lines = [a[k] if k % 2 == 0 else b[k] for k in range(60)]
    result = measure_destagger(lines)
    assert result.axes["y"].destagger is None
    assert result.axes["y"].reason == m.UNCLEAR
    assert all(ln.reason == m.AXIS_FAILED for ln in result.lines.values())


def test_the_search_range_grows_with_the_lines():
    assert search_range_m(30.0) == 1.0
    assert search_range_m(60.0) == pytest.approx(1.8)


@needs_grid1
def test_too_few_lines_measure_nothing(grid1_lines):
    result = measure_destagger(grid1_lines[:3])
    assert result.axes["y"].destagger is None
    assert result.axes["y"].reason == m.TOO_FEW
    assert all(ln.reason == m.AXIS_FAILED for ln in result.lines.values())


@needs_grid1
@needs_grid2
def test_each_axis_is_measured_on_its_own():
    y = lines_for(GPS_LINES, GRID1_LENGTH, axis="y")
    x = lines_for(GRID2_LINES, GRID2_LENGTH, axis="x")
    result = measure_destagger(y + x)
    assert set(result.axes) == {"x", "y"}
    assert result.axes["y"].destagger == pytest.approx(0.152, abs=0.02)
    assert result.axes["x"].destagger == pytest.approx(0.165, abs=0.02)
    assert len(result.lines) == 120


# Every loop over the lines calls should_stop once per line. The four exclusion stages are
# loops in `_measure_axis` itself, 60 calls each on Grid 1, in this order.
EXCLUSION_STAGES = ["no distance", "time settings", "too short", "neighbours"]
# Every later loop is its own function and calls should_stop through `check`, so the
# function that called `check` names the loop. In order of first use:
PER_LINE_LOOPS = [
    "pair_curves",  # profiles and pair curves
    "line_curves",  # each line against its neighbours, for the grid value
    "_depth_split",  # where shallow ends and deep begins
    "_cache_curves",  # each pair's curves for the per-line readings
    "classify_all",  # reading every line: first, then after each pass
    "runs",  # grouping candidates into runs of neighbours
    "solve_run",  # the search along a run
    "refine",  # moving each own value to its line's peak
]


def _loop_of_caller() -> str:
    """Called from a should_stop function: the function whose loop called it, past
    `_check` and `check`."""
    frame = sys._getframe(2)
    while frame.f_code.co_name in ("_check", "check"):
        frame = frame.f_back
    return frame.f_code.co_name


def _stopper(stop_at):
    calls = []

    def stop() -> bool:
        calls.append(_loop_of_caller())
        return len(calls) >= stop_at

    return stop, calls


@pytest.fixture(scope="module")
def check_calls(grid1_lines):
    """The loop behind each should_stop call of one whole Grid 1 measurement."""
    stop, calls = _stopper(10**9)
    measure_destagger(grid1_lines, should_stop=stop)
    return calls


@needs_grid1
@pytest.mark.parametrize("stage", range(len(EXCLUSION_STAGES)), ids=EXCLUSION_STAGES)
def test_should_stop_is_honoured_in_every_exclusion_stage(grid1_lines, stage):
    stop, calls = _stopper(30 + 60 * stage)
    with pytest.raises(MeasureStopped):
        measure_destagger(grid1_lines, should_stop=stop)
    assert len(calls) == 30 + 60 * stage
    assert calls[-1] == "_measure_axis"


@needs_grid1
def test_every_loop_checks_once_per_line_in_order(check_calls):
    """60 lines: 60 checks per loop that runs once, then each pass of the per-line solve
    groups and re-reads every line, and checks once per line it solves or refines."""
    once = ["pair_curves", "line_curves", "_depth_split", "_cache_curves", "classify_all"]
    assert check_calls[:240] == ["_measure_axis"] * 240
    assert check_calls[240:540] == [loop for loop in once for _ in range(60)]
    passes = Counter(check_calls[540:])
    assert set(passes) == {"runs", "solve_run", "refine", "classify_all"}
    assert passes["runs"] == passes["classify_all"] > 0
    assert passes["runs"] % 60 == 0
    assert passes["refine"] >= 4  # Grid 1 unfitted has 4 own values


@needs_grid1
@pytest.mark.parametrize("loop", PER_LINE_LOOPS)
def test_should_stop_is_honoured_in_every_per_line_loop(grid1_lines, check_calls, loop):
    """Stopping at a loop's first check raises there. A loop that lost its check is
    missing from `check_calls`, and this fails."""
    stop_at = check_calls.index(loop) + 1
    stop, calls = _stopper(stop_at)
    with pytest.raises(MeasureStopped):
        measure_destagger(grid1_lines, should_stop=stop)
    assert len(calls) == stop_at
    assert calls[-1] == loop


@needs_grid1
def test_envelope_bins_shape_and_clock():
    path = GPS_LINES[0]
    header = read_header(path)
    samples = read_samples(path, header)[0]
    bins = envelope_bins(samples, header.dt_ns, header.position_ns)
    assert bins.data.shape == (samples.shape[0] // 8, samples.shape[1])
    assert bins.data.dtype == np.float32
    assert bins.t0_ns == pytest.approx(header.position_ns + 3.5 * header.dt_ns)
    assert bins.dt_ns == pytest.approx(8 * header.dt_ns)
    assert bins.t_ns[1] - bins.t_ns[0] == pytest.approx(bins.dt_ns)
