"""The 3-D export's remembered choice, its size and its refusal text (Qt-free)."""

from __future__ import annotations

import pytest
from nsgeo.slices import VolumeSettings
from nsgeo.vtkxml import image_data_bytes
from nsgeo_qgis.slices_plan import (
    VolumeChoice,
    export_size_bytes,
    too_fine_for_export,
    volume_choice,
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
