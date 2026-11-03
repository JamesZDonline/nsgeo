"""The finished slice: interpolate, then smooth (interpolation spec §6)."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices import FinishSettings, finish_slice, plan_fill, smooth

CELL = 0.05


def lines():
    pop = np.zeros((40, 60), bool)
    pop[[5, 15, 25, 35], :] = True
    return pop


def test_finish_slice_interpolates_then_smooths():
    pop = lines()
    values = np.random.default_rng(0).normal(size=pop.shape)
    settings = FinishSettings("idw", 0.25, 1.0, smooth_x_m=0.1, smooth_y_m=0.2)
    w = plan_fill(pop, CELL, "idw", 0.25, 1.0)
    got = finish_slice(values, w, CELL, settings)
    want = smooth(w.apply(values), CELL, 0.1, 0.2)
    np.testing.assert_array_equal(got, want)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"method": "spline"},
        {"max_distance_m": -0.1},
        {"max_distance_m": float("nan")},
        {"search_radius_m": float("inf")},
        {"search_radius_m": -1.0},
        {"smooth_x_m": -0.1},
        {"smooth_y_m": float("nan")},
        {"max_distance_m": 0.5, "search_radius_m": 0.4},
    ],
)
def test_finish_settings_refuse_bad_values(kwargs):
    base = {"method": "idw", "max_distance_m": 0.25, "search_radius_m": 1.0}
    with pytest.raises(ValueError):
        FinishSettings(**{**base, **kwargs})


def test_finish_slice_refuses_a_shape_mismatch():
    w = plan_fill(lines(), CELL, "idw", 0.25, 1.0)
    with pytest.raises(ValueError):
        finish_slice(np.zeros((3, 3)), w, CELL, FinishSettings("idw", 0.25, 1.0))
