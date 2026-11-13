from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.mag.setup import MagSetup, fit_problems


def grid(x=30.0, y=30.0):
    return Grid("M", (0.0, 0.0), 0.0, x, y, "EPSG:32616", 0.5)


def test_the_default_setup_is_the_authors():
    s = MagSetup()
    assert (s.axis, s.far_x, s.far_y) == ("y", False, False)
    assert (s.spacing_m, s.first_offset_m, s.readings_per_metre) == (0.5, 0.25, 8.0)
    assert (s.sensors, s.sensor_separation_m) == (2, 1.0)
    assert (s.zigzag, s.flipped, s.missing_run) == (True, True, 4)
    assert s.passes_apart() == 2
    assert MagSetup(sensors=1).passes_apart() == 1


def test_a_sensor_separation_off_the_traverse_spacing_is_refused():
    with pytest.raises(ValueError, match="whole number of traverse spacings"):
        MagSetup(sensor_separation_m=0.7)


@pytest.mark.parametrize(
    "kw",
    [
        {"axis": "z"},
        {"spacing_m": 0.0},
        {"first_offset_m": -1.0},
        {"readings_per_metre": float("nan")},
        {"sensors": 0},
        {"missing_run": 0},
    ],
)
def test_other_fields_are_checked(kw):
    with pytest.raises(ValueError, match="must be"):
        MagSetup(**kw)


def test_setup_round_trips_through_a_dict():
    s = MagSetup(axis="x", far_x=True, spacing_m=1.0, sensors=3, zigzag=False, missing_run=6)
    assert MagSetup.from_dict(s.to_dict()) == s
    assert MagSetup.from_dict({}) == MagSetup()
    with pytest.raises(TypeError):
        MagSetup.from_dict({"zigzag": "yes"})
    with pytest.raises(ValueError):
        MagSetup.from_dict({"axis": "q"})


def test_fit_problems_say_what_does_not_fit():
    s = MagSetup()
    assert fit_problems(s, 60, 240, grid()) == []
    assert fit_problems(s, 60, 240, grid(y=40.0)) == [
        "240 readings at 8 per metre make 30 m, but the grid is 40 m along Y."
    ]
    assert fit_problems(s, 60, 240, grid(x=20.0)) == [
        "60 traverses 0.5 m apart make 30 m, but the grid is 20 m across X."
    ]
