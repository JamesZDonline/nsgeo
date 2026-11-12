"""The grid-wide destagger value, measured on the real Nashville grids (#159).

Expected values are the 2026-11-11 spike's, which the user's by-eye values
agree with on Grid 1 unfitted. Real files only: a skipped test validated nothing.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from nsgeo.destagger import (
    LineStatus,
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


@needs_grid1
def test_measuring_twice_gives_identical_results(grid1_lines, grid1_unfitted):
    assert measure_destagger(grid1_lines) == grid1_unfitted


@needs_grid1
def test_every_measured_line_gets_the_grid_value(grid1_unfitted):
    grid = grid1_unfitted.axes["y"].destagger
    assert len(grid1_unfitted.lines) == 60
    for line in grid1_unfitted.lines.values():
        assert line.status is LineStatus.GRID
        assert line.destagger == grid


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


# Each of the six per-line loops (no distance, time settings, too short, neighbours,
# profiles, lag curves) checks once per line, so 60 lines make 360 calls in order.
# Stopping inside each stage must raise.
@needs_grid1
@pytest.mark.parametrize("stage", range(6))
def test_should_stop_is_honoured_in_every_per_line_stage(grid1_lines, stage):
    stop_at = 30 + 60 * stage
    calls = []

    def stop() -> bool:
        calls.append(1)
        return len(calls) >= stop_at

    with pytest.raises(MeasureStopped):
        measure_destagger(grid1_lines, should_stop=stop)
    assert len(calls) == stop_at


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
