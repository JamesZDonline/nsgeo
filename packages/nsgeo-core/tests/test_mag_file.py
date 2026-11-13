from __future__ import annotations

import dataclasses
import os

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.mag import MagFile, MagSetup, clear_mag_cache, traverses

from tests.mag_data import write_grad601


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_mag_cache()
    yield
    clear_mag_cache()


def test_open_reads_the_shape_and_starts_uncorrected(tmp_path):
    path = write_grad601(tmp_path / "a.dat", np.ones((4, 16)))
    mag = MagFile.open(path, "M", MagSetup())
    assert (mag.n_rows, mag.n_readings) == (4, 16)
    assert mag.scales == (1.0,) * 4
    assert mag.shifts == (0.0,) * 4
    assert mag.grid_id == "M"


def test_points_skip_missing_readings_and_follow_the_placement(tmp_path):
    values = np.full((4, 16), 5.0)
    values[2, 3:7] = 0.0
    path = write_grad601(tmp_path / "a.dat", values)
    setup = MagSetup(readings_per_metre=4.0)
    grid = Grid("M", (100.0, 200.0), 30.0, 2.0, 4.0, "EPSG:32616", 0.5, instrument="mag")
    mag = MagFile.open(path, "M", setup)
    xy, v = mag.points(grid)
    assert xy.shape == (60, 2)
    assert v.shape == (60,)
    assert np.all(v == 5.0)
    expected = grid.to_world(traverses(setup, grid, 4, 16)[0].placement.local(16, 4.0))
    np.testing.assert_allclose(xy[:16], expected)


def test_readings_are_read_only_and_reread_when_the_file_changes(tmp_path):
    path = write_grad601(tmp_path / "a.dat", np.full((2, 8), 1.0))
    mag = MagFile.open(path, "M", MagSetup())
    assert not mag.readings().flags.writeable
    assert not mag.raw().flags.writeable
    assert np.all(mag.readings() == 1.0)
    before = path.stat().st_mtime_ns
    write_grad601(path, np.full((2, 8), 2.0))
    os.utime(path, ns=(before + 10**9, before + 10**9))
    assert np.all(mag.readings() == 2.0)
    assert np.all(mag.raw() == 2.0)


def test_readings_mark_missing_runs_but_raw_keeps_zeros(tmp_path):
    values = np.full((2, 8), 1.0)
    values[0, :4] = 0.0
    mag = MagFile.open(write_grad601(tmp_path / "a.dat", values), "M", MagSetup())
    assert np.isnan(mag.readings()[0, :4]).all()
    assert (mag.raw()[0, :4] == 0.0).all()


def test_corrections_must_match_the_traverses(tmp_path):
    mag = MagFile.open(write_grad601(tmp_path / "a.dat", np.ones((4, 16))), "M", MagSetup())
    with pytest.raises(ValueError, match="scales"):
        dataclasses.replace(mag, scales=(1.0,))
    with pytest.raises(ValueError, match="shifts"):
        dataclasses.replace(mag, shifts=(0.0,) * 5)
    with pytest.raises(ValueError, match="scales"):
        dataclasses.replace(mag, scales=(1.0, 1.0, 0.0, 1.0))
    with pytest.raises(ValueError, match="shifts"):
        dataclasses.replace(mag, shifts=(0.0, float("nan"), 0.0, 0.0))


def _identity_grid():
    return Grid("M", (0.0, 0.0), 0.0, 2.0, 4.0, "EPSG:32616", 0.5, instrument="mag")


def _counted_file(tmp_path, setup):
    values = np.tile(np.arange(1.0, 17.0), (4, 1))  # stored index + 1
    return MagFile.open(write_grad601(tmp_path / "a.dat", values), "M", setup)


@pytest.mark.parametrize("flipped", [True, False])
def test_every_reading_lands_where_it_was_walked(tmp_path, flipped):
    setup = MagSetup(readings_per_metre=4.0, sensors=1, flipped=flipped)
    xy, v = _counted_file(tmp_path, setup).points(_identity_grid())
    for row in range(4):
        y = xy[row * 16 : (row + 1) * 16, 1]
        stored_index = v[row * 16 : (row + 1) * 16] - 1
        if flipped or row % 2 == 0:
            expected = (stored_index + 0.5) / 4.0
        else:  # walked back, and stored in the order walked
            expected = 4.0 - (stored_index + 0.5) / 4.0
        np.testing.assert_allclose(y, expected, err_msg=f"row {row}")


def test_a_traverse_correction_moves_only_that_traverse(tmp_path):
    setup = MagSetup(readings_per_metre=4.0, sensors=1, flipped=False)
    grid = _identity_grid()
    plain = _counted_file(tmp_path, setup)
    shifts = (0.0, 0.1, 0.0, 0.0)
    scales = (1.0, 0.98, 1.0, 1.0)
    corrected = dataclasses.replace(plain, scales=scales, shifts=shifts)
    base_xy, _ = plain.points(grid)
    xy, _ = corrected.points(grid)
    for row in (0, 2, 3):
        np.testing.assert_allclose(
            xy[row * 16 : (row + 1) * 16], base_xy[row * 16 : (row + 1) * 16]
        )
    j = np.arange(16.0)
    expected = (4.0 - 0.125) - (0.98 * j / 4.0 + 0.1)  # row 2 of the file walks back
    np.testing.assert_allclose(xy[16:32, 1], expected)
    np.testing.assert_allclose(xy[16:32, 0], base_xy[16:32, 0])
