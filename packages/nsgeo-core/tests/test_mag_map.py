from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.mag import MagFile, MagSetup, clear_mag_cache
from nsgeo.mag.map import DEFAULT_CELL_M, bin_readings, display_centre, grid_map, mosaic
from nsgeo.slices import CubeFrame, FinishSettings

from tests.mag_data import write_grad601

CRS = "EPSG:32616"


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_mag_cache()
    yield
    clear_mag_cache()


def test_the_default_cell_is_an_eighth_of_a_metre():
    assert DEFAULT_CELL_M == 0.125


def test_bin_readings_averages_each_cell_and_leaves_empty_cells_nan():
    frame = CubeFrame((0.0, 0.0), 0.0, 1.0, 3, 2, CRS)
    world = np.array([[1.2, 0.3], [1.7, 0.9]])
    out = bin_readings(frame, world, np.array([2.0, 4.0]))
    assert out.dtype == np.float32
    assert out.shape == (2, 3)
    assert out[0, 1] == 3.0
    mask = np.ones((2, 3), dtype=bool)
    mask[0, 1] = False
    assert np.isnan(out[mask]).all()


def test_readings_outside_the_frame_are_dropped():
    frame = CubeFrame((0.0, 0.0), 0.0, 1.0, 2, 2, CRS)
    world = np.array([[0.5, 0.5], [-1.0, 0.5], [5.0, 5.0], [0.5, 9.0]])
    out = bin_readings(frame, world, np.array([1.0, 10.0, 20.0, 30.0]))
    assert out[0, 0] == 1.0
    assert int(np.isfinite(out).sum()) == 1


def _four_by_two(tmp_path):
    setup = MagSetup(axis="x", spacing_m=0.25, first_offset_m=0.125, sensors=1)
    grid = Grid("M", (0.0, 0.0), 0.0, 4.0, 2.0, CRS, 0.25, instrument="mag")
    path = write_grad601(tmp_path / "a.dat", np.full((8, 32), 5.0))
    return MagFile.open(path, "M", setup), grid


def test_grid_map_fills_between_traverses_within_the_max_distance(tmp_path):
    mag, grid = _four_by_two(tmp_path)
    cell = 0.125
    frame, none = grid_map(mag, grid, cell, FinishSettings("none", 0.1875, 0.375))
    assert (frame.nx, frame.ny) == (32, 16)
    rows = np.isfinite(none).all(axis=1)
    assert rows.sum() == 8
    assert (np.isfinite(none).sum(axis=1) > 0).sum() == 8
    _, kriged = grid_map(mag, grid, cell, FinishSettings("kriging", 0.1875, 0.375))
    assert np.isfinite(kriged).all()
    np.testing.assert_allclose(kriged, 5.0, atol=1e-4)
    _, zero = grid_map(mag, grid, cell, FinishSettings("kriging", 0.0, 0.375))
    np.testing.assert_array_equal(zero, none)


def _const_grid(tmp_path, name, origin, value):
    setup = MagSetup(axis="x", spacing_m=0.25, first_offset_m=0.125, sensors=1)
    grid = Grid(name, origin, 0.0, 2.0, 2.0, CRS, 0.25, instrument="mag")
    path = write_grad601(tmp_path / f"{name}.dat", np.full((8, 16), value))
    return grid, MagFile.open(path, name, setup)


def test_the_mosaic_of_two_touching_grids_holds_each_where_it_lies(tmp_path):
    settings = FinishSettings("kriging", 0.1875, 0.375)
    ga, ma = _const_grid(tmp_path, "A", (10.0, 20.0), 1.0)
    gb, mb = _const_grid(tmp_path, "B", (12.0, 21.0), 3.0)
    maps = [grid_map(ma, ga, 0.125, settings), grid_map(mb, gb, 0.125, settings)]
    lattice, out = mosaic(maps, 0.125, CRS, max_pixels=10**6, max_covered=10**6)
    assert lattice.geotransform[1] == 0.125
    assert lattice.geotransform[5] == -0.125
    assert out.shape == (lattice.height, lattice.width)
    centres = lattice.pixel_centres()
    x, y = centres[:, 0], centres[:, 1]
    flat = out.ravel()
    left = (x > 10.0) & (x < 11.875) & (y > 20.0) & (y < 22.0)
    right = (x > 12.125) & (x < 14.0) & (y > 21.0) & (y < 23.0)
    # B sits a metre higher than A, so the lattice's box holds two empty corners.
    off = ((x > 12.1) & (y < 20.9)) | ((x < 11.9) & (y > 22.1))
    assert left.any() and right.any() and off.any()
    np.testing.assert_allclose(flat[left], 1.0, atol=1e-4)
    np.testing.assert_allclose(flat[right], 3.0, atol=1e-4)
    assert np.isnan(flat[off]).all()


def test_a_mosaic_in_another_crs_is_refused(tmp_path):
    settings = FinishSettings("none", 0.0, 0.0)
    ga, ma = _const_grid(tmp_path, "A", (10.0, 20.0), 1.0)
    maps = [grid_map(ma, ga, 0.125, settings)]
    with pytest.raises(ValueError, match="EPSG:32617"):
        mosaic(maps, 0.125, "EPSG:32617", max_pixels=10**6, max_covered=10**6)
    with pytest.raises(ValueError):
        mosaic([], 0.125, CRS, max_pixels=10**6, max_covered=10**6)


def test_display_centre_is_the_median_of_finite_values():
    assert display_centre(np.array([1.0, 2.0, np.nan, 10.0])) == 2.0
    assert display_centre(np.full(3, np.nan)) == 0.0


def test_a_rotated_grid_far_from_the_origin_bins_each_traverse_in_one_column(tmp_path):
    grid = Grid("M", (512345.0, 4512345.0), 17.0, 4.0, 4.0, CRS, 0.5, instrument="mag")
    path = write_grad601(tmp_path / "a.dat", np.full((8, 32), 5.0))
    mag = MagFile.open(path, "M", MagSetup(spacing_m=0.5, first_offset_m=0.25, sensors=1))
    frame, binned = grid_map(mag, grid, 0.125, FinishSettings("none", 0.0, 0.0))
    per_column = np.isfinite(binned).sum(axis=0)
    assert (per_column > 0).sum() == 8
    assert set(per_column[per_column > 0]) == {32}


# -- Missing readings stay blank (mag plan B, Q13) --------------------------------

GAP_ROW = 29  # traverse 30, an interior traverse
GAP = slice(80, 92)  # 12 readings, 1.5 m at 8 per metre


def _gapped(tmp_path, *, gap=True):
    """A 30 m grid of 60 traverses x 240 readings, 1.5 m missing on traverse 30."""
    setup = MagSetup(axis="x")
    grid = Grid("M", (0.0, 0.0), 0.0, 30.0, 30.0, CRS, 0.5, instrument="mag")
    values = np.full((60, 240), 5.0)
    if gap:
        values[GAP_ROW, GAP] = 0.0
    path = write_grad601(tmp_path / ("gap.dat" if gap else "full.dat"), values)
    return MagFile.open(path, "M", setup), grid


DEFAULT_FINISH = FinishSettings("kriging", 0.375, 1.0)


def _footprint_cells(mag, grid, cell):
    """(rows, cols) of the cells whose centres lie in the missing readings' footprint."""
    (t,) = [t for t in mag.traverses(grid) if t.row == GAP_ROW]
    stored_gap = np.zeros(mag.n_readings, dtype=bool)
    stored_gap[GAP] = True
    missing = t.walked(stored_gap)
    along = t.placement.local(mag.n_readings, 8.0)[missing][:, 0]
    half_along = 0.5 / 8.0 * t.placement.scale
    lo, hi = along.min() - half_along, along.max() + half_along
    across = t.placement.offset
    centres = (np.arange(round(30.0 / cell)) + 0.5) * cell
    cols = np.flatnonzero((centres >= lo) & (centres < hi))
    rows = np.flatnonzero((centres >= across - 0.25) & (centres < across + 0.25))
    return rows, cols


def test_a_missing_run_is_blank_across_its_traverse_footprint(tmp_path):
    mag, grid = _gapped(tmp_path)
    _, out = grid_map(mag, grid, DEFAULT_CELL_M, DEFAULT_FINISH)
    rows, cols = _footprint_cells(mag, grid, DEFAULT_CELL_M)
    assert (rows.size, cols.size) == (4, 12)
    expected = np.zeros(out.shape, dtype=bool)
    expected[np.ix_(rows, cols)] = True
    np.testing.assert_array_equal(np.isnan(out), expected)


@pytest.mark.parametrize("method", ["none", "idw", "kriging", "min_curvature"])
def test_missing_readings_stay_blank_under_every_finish(tmp_path, method):
    mag, grid = _gapped(tmp_path)
    finish = FinishSettings(method, 1.5, 3.0, smooth_x_m=1.0, smooth_y_m=1.0)
    _, out = grid_map(mag, grid, DEFAULT_CELL_M, finish)
    rows, cols = _footprint_cells(mag, grid, DEFAULT_CELL_M)
    assert np.isnan(out[np.ix_(rows, cols)]).all()
    # The traverses either side of the gap are still drawn beside it.
    (t,) = [t for t in mag.traverses(grid) if t.row == GAP_ROW]
    beside = [int((t.placement.offset + d) // DEFAULT_CELL_M) for d in (-0.5, 0.5)]
    assert np.isfinite(out[np.ix_(beside, cols)]).all()


def test_a_destaggered_traverse_carries_its_blank_with_it(tmp_path):
    import dataclasses

    mag, grid = _gapped(tmp_path)
    _, before = grid_map(mag, grid, DEFAULT_CELL_M, DEFAULT_FINISH)
    shifts = list(mag.shifts)
    shifts[GAP_ROW] = 0.25
    moved = dataclasses.replace(mag, shifts=tuple(shifts))
    _, after = grid_map(moved, grid, DEFAULT_CELL_M, DEFAULT_FINISH)
    (t,) = [t for t in moved.traverses(grid) if t.row == GAP_ROW]
    step = round(0.25 / DEFAULT_CELL_M) * t.placement.direction
    np.testing.assert_array_equal(np.isnan(after), np.roll(np.isnan(before), step, axis=1))


def test_a_file_with_nothing_missing_maps_as_before(tmp_path):
    from nsgeo.mag import map as mag_map

    mag, grid = _gapped(tmp_path, gap=False)
    assert (
        mag_map.missing_mask(
            CubeFrame.for_grid(grid, DEFAULT_CELL_M), mag.missing_footprints(grid), DEFAULT_CELL_M
        ).sum()
        == 0
    )
    _, out = grid_map(mag, grid, DEFAULT_CELL_M, DEFAULT_FINISH)
    assert np.isfinite(out).all()
