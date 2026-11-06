from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo_qgis.ui.ruler import (
    bounds_on,
    is_reversed,
    metres_at,
    ruler_for,
    trace_units_at,
)

GRID = Grid("A", (0.0, 0.0), 0.0, 5.0, 11.0, "EPSG:32616", 0.5)
H = 1 / 120  # half a trace at 60 traces/m
# The longest forward and shortest reversed local lines, placed the way the
# import places a zigzag.
FWD = np.arange(666) / 60.0
REV = 11.0 - np.arange(606) / 60.0


def test_a_trace_sits_at_its_column_centre_in_either_direction():
    assert trace_units_at(FWD, 0.0) == pytest.approx(0.5)
    assert trace_units_at(FWD, FWD[3]) == pytest.approx(3.5)
    assert trace_units_at(REV, 11.0) == pytest.approx(0.5)
    assert trace_units_at(REV, REV[3]) == pytest.approx(3.5)
    assert metres_at(REV, 0.0) == pytest.approx(11.0 + H)  # trace 0's column edge, beyond the start


def test_the_unit_maps_extrapolate_and_round_trip():
    for d in (FWD, REV):
        for m in (-2.0, 0.3, 5.0, 12.5):
            assert metres_at(d, trace_units_at(d, m)) == pytest.approx(m)
    assert trace_units_at(REV, 12.0) == pytest.approx(0.5 - 60.0)


def test_is_reversed_reads_the_distance_not_a_flag():
    assert not is_reversed(FWD) and is_reversed(REV)


def test_the_ruler_is_the_grid_widened_to_every_line():
    r = ruler_for(GRID, "y", [FWD, REV])
    assert (r.grid_id, r.axis, r.key) == ("A", "y", ("A", "y"))
    assert r.lo_m == pytest.approx(-H)
    assert r.hi_m == pytest.approx(665 / 60.0 + H)


def test_a_ruler_with_no_lines_is_the_grid_along_that_axis():
    assert (ruler_for(GRID, "y", []).lo_m, ruler_for(GRID, "y", []).hi_m) == (0.0, 11.0)
    assert ruler_for(GRID, "x", [np.array([1.0])]).hi_m == 5.0  # a one-trace line has no spacing


def test_bounds_put_both_lines_on_the_same_metres():
    r = ruler_for(GRID, "y", [FWD, REV])
    assert bounds_on(r, FWD) == pytest.approx((0.0, 666.0))
    assert bounds_on(r, REV) == pytest.approx((-5.0, 661.0))
