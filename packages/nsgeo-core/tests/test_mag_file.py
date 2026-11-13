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
