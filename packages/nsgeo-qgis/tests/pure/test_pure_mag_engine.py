"""The Qt-free magnetometer map cache and mosaic behind the Mag panel."""

from __future__ import annotations

import dataclasses
import os

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.mag import MagFile, MagSetup
from nsgeo_qgis.mag_engine import (
    DEFAULT_MAG_FINISH,
    MAG_STRETCH_PERCENTILE,
    MagEngine,
    MagSettings,
)
from plugin_testing import synthetic_grad601


def _grid(grid_id="M1", origin=(100.0, 100.0), crs="EPSG:32616"):
    return Grid(grid_id, origin, 0.0, 4.0, 4.0, crs, 0.5, instrument="mag")


def _file(tmp_path, grid_id="M1", name="m1.dat", value=5.0):
    path = synthetic_grad601(tmp_path, name, value=value)
    return MagFile.open(path, grid_id, MagSetup())


def test_a_grid_map_is_computed_once_per_settings(tmp_path):
    engine = MagEngine()
    mag, grid = _file(tmp_path), _grid()
    settings = MagSettings()
    _, first = engine.grid_map(mag, grid, settings)
    _, again = engine.grid_map(mag, grid, settings)
    assert again is first
    _, finer = engine.grid_map(mag, grid, dataclasses.replace(settings, cell=0.25))
    assert finer is not first
    assert finer.shape != first.shape


def test_a_replaced_file_is_mapped_afresh(tmp_path):
    engine = MagEngine()
    mag, grid = _file(tmp_path), _grid()
    _, first = engine.grid_map(mag, grid, MagSettings())
    synthetic_grad601(tmp_path, "m1.dat", value=9.0)
    stat = os.stat(mag.path)
    os.utime(mag.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    _, second = engine.grid_map(mag, grid, MagSettings())
    assert second is not first


def test_a_moved_grid_is_mapped_afresh(tmp_path):
    engine = MagEngine()
    mag = _file(tmp_path)
    frame_a, a = engine.grid_map(mag, _grid(), MagSettings())
    frame_b, b = engine.grid_map(mag, _grid(origin=(110.0, 100.0)), MagSettings())
    assert b is not a
    assert frame_b.origin != frame_a.origin


def test_a_grid_in_another_crs_is_left_out(tmp_path):
    engine = MagEngine()
    items = [
        (_file(tmp_path, "M1", "a.dat"), _grid("M1")),
        (_file(tmp_path, "M2", "b.dat"), _grid("M2", (104.0, 100.0), crs="EPSG:32617")),
    ]
    result = engine.mosaic(items, MagSettings())
    assert result is not None
    assert result.grids == ("M1",)
    assert result.left_out == ("M2",)
    assert result.lattice.crs == "EPSG:32616"


def test_no_items_is_no_mosaic():
    assert MagEngine().mosaic([], MagSettings()) is None


def test_the_limit_is_the_95th_percentile_about_the_median(tmp_path):
    engine = MagEngine()
    result = engine.mosaic([(_file(tmp_path), _grid())], MagSettings())
    assert result is not None
    finite = result.array[np.isfinite(result.array)].astype(float)
    centre = float(np.median(finite))
    assert result.centre() == pytest.approx(centre)
    assert MAG_STRETCH_PERCENTILE == 95.0
    assert result.limit() == pytest.approx(np.percentile(np.abs(finite - centre), 95.0), rel=0.05)


def test_the_default_finish_is_kriging_at_three_quarters_of_the_traverse_spacing():
    assert DEFAULT_MAG_FINISH.method == "kriging"
    assert DEFAULT_MAG_FINISH.max_distance_spacings == 0.75
    assert MagSettings().cell == 0.125


def test_the_finish_reaches_by_the_files_traverse_spacing_not_the_grids(tmp_path):
    engine = MagEngine()
    mag, grid = _file(tmp_path), _grid()
    # The grid says 0.5 m; a file walked 1 m apart must reach twice as far.
    wide = MagFile.open(mag.path, "M1", dataclasses.replace(MagSetup(), spacing_m=1.0))
    near = engine.grid_map(mag, grid, MagSettings())[1]
    far = engine.grid_map(wide, grid, MagSettings())[1]
    assert np.isfinite(far).sum() >= np.isfinite(near).sum()


def test_the_cache_is_bounded_and_clearable(tmp_path):
    engine = MagEngine(max_entries=2)
    mag, grid = _file(tmp_path), _grid()
    first = engine.grid_map(mag, grid, MagSettings(cell=0.5))[1]
    engine.grid_map(mag, grid, MagSettings(cell=0.25))
    engine.grid_map(mag, grid, MagSettings(cell=0.2))
    assert engine.grid_map(mag, grid, MagSettings(cell=0.5))[1] is not first
    again = engine.grid_map(mag, grid, MagSettings(cell=0.5))[1]
    engine.clear()
    assert engine.grid_map(mag, grid, MagSettings(cell=0.5))[1] is not again
