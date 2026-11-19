"""The 3-D export's remembered choice, its size and its refusal text (Qt-free)."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices import VolumeSettings
from nsgeo.vtkxml import image_data_bytes, structured_grid_bytes
from nsgeo_qgis.slices_plan import (
    VolumeChoice,
    export_size_bytes,
    too_fine_for_export,
    volume_choice,
    walls_size,
)


def test_first_use_takes_the_panel_defaults_then_the_record_wins():
    c = volume_choice(None, cell_default=0.05, dz_default=0.2165, transform_default="amp_square")
    assert (c.cell, c.dz_ns, c.transform, c.stretch) == (0.05, 0.2165, "amp_square", 3.0)
    r = volume_choice(
        {"dz_ns": 0.1, "stretch": "bad"},
        cell_default=0.2,
        dz_default=0.2165,
        transform_default="amp_square",
    )
    assert (r.cell, r.dz_ns, r.stretch) == (0.2, 0.1, 3.0)


def test_volume_choice_round_trips_through_its_record():
    c = VolumeChoice(0.05, 0.1, "amp_square", 4.0, VolumeSettings(period_ns=3.0))
    assert volume_choice(c.to_record(), cell_default=1, dz_default=1, transform_default="") == c


def test_a_remembered_empty_transform_is_kept():
    c = VolumeChoice(0.05, 0.1, "", 3.0)
    back = volume_choice(
        c.to_record(), cell_default=1, dz_default=1, transform_default="amp_square"
    )
    assert back.transform == ""


def test_a_choice_refuses_nonsense():
    for bad in ({"cell": 0.0}, {"dz_ns": -1.0}, {"stretch": float("nan")}):
        with pytest.raises(ValueError):
            VolumeChoice(**{"cell": 0.1, "dz_ns": 0.1, "transform": "amp_square", **bad})


def test_export_size_matches_three_float32_arrays():
    assert export_size_bytes(400, 320, 450) == image_data_bytes((400, 320, 450), 3)


def test_the_too_fine_message_names_the_cell_the_grid_and_the_safe_cell():
    text = too_fine_for_export(0.01, "Grid 1", 9_000_000, 0.02)
    assert "too fine" in text and "0.01 m" in text and "Grid 1" in text
    assert "9,000,000" in text and "0.02 m" in text


def test_a_stored_none_reads_back_as_no_transform():
    c = volume_choice(
        {"transform": "none"}, cell_default=1, dz_default=1, transform_default="amp_square"
    )
    assert c.transform == ""


def test_the_deepest_time_takes_the_panels_at_first_use_then_the_record_wins():
    kw = {"cell_default": 0.1, "dz_default": 0.2, "transform_default": ""}
    assert volume_choice(None, **kw).t1_ns is None
    assert volume_choice(None, t1_default=40.0, **kw).t1_ns == 40.0
    assert volume_choice({"t1_ns": 25.0}, t1_default=40.0, **kw).t1_ns == 25.0
    assert volume_choice({"t1_ns": "bad"}, t1_default=40.0, **kw).t1_ns == 40.0
    assert volume_choice({"t1_ns": -3.0}, t1_default=None, **kw).t1_ns is None


def test_an_unset_deepest_time_is_absent_from_the_record_and_round_trips():
    kw = {"cell_default": 1, "dz_default": 1, "transform_default": ""}
    unset = VolumeChoice(0.1, 0.1, "amp_square")
    assert "t1_ns" not in unset.to_record()
    assert volume_choice(unset.to_record(), **kw).t1_ns is None
    deep = VolumeChoice(0.1, 0.1, "amp_square", t1_ns=40.0)
    assert deep.to_record()["t1_ns"] == 40.0
    assert volume_choice(deep.to_record(), **kw) == deep


def test_a_choice_refuses_a_bad_deepest_time():
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            VolumeChoice(0.1, 0.1, "amp_square", t1_ns=bad)


def _path(length):
    return np.array([[1.0, 1.0], [1.0 + length, 1.0]])


def test_walls_size_counts_each_walls_columns_and_levels():
    # two lines (40 and 5000 traces), a cut of 3 m on a 0.5 m cell: 3 / 0.25 + 1 = 13 columns
    n, size = walls_size(30, [40, 5000], [_path(3.0)], 0.5)
    assert n == 3
    assert size == (
        structured_grid_bytes(40 * 30, 1)
        + structured_grid_bytes(300 * 30, 1)
        + structured_grid_bytes(13 * 30, 1)
    )


def test_walls_size_leaves_out_the_walls_that_cannot_be_made():
    # a 1-trace line, a zero-length cut and a cut that is not finite make no wall
    assert walls_size(30, [1], [_path(0.0), _path(float("inf")), _path(float("nan"))], 0.5) == (
        0,
        0,
    )
    n, size = walls_size(10, [1, 2], [], 0.5)
    assert (n, size) == (1, structured_grid_bytes(2 * 10, 1))
    assert walls_size(10, [], [], 0.5) == (0, 0)
