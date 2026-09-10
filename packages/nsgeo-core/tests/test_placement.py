from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io.dzt import read_header

from tests.synthetic import write_dzt


@pytest.fixture
def header(tmp_path):
    p = tmp_path / "h.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32), traces_per_metre=60.0)
    return read_header(p)


@pytest.fixture
def frames():
    return {
        "G": Grid(
            id="G",
            origin=(0.0, 0.0),
            azimuth=0.0,
            size_x=20.0,
            size_y=20.0,
            crs="EPSG:32616",
            default_spacing=0.5,
        )
    }


def test_distance_along_forward(header):
    pl = GridPlacement(grid_id="G", axis="y", offset=0.5)
    d = pl.distance_along(120, header)
    assert d[0] == pytest.approx(0.0)
    assert d[60] == pytest.approx(1.0)  # 60 traces/m
    assert d[119] == pytest.approx(119 / 60)


def test_distance_along_reversed_decreases(header):
    """Zigzag: traces stay in raw file order, the coordinate decreases."""
    pl = GridPlacement(grid_id="G", axis="y", offset=0.5, start_along=20.0, direction=-1)
    d = pl.distance_along(120, header)
    assert d[0] == pytest.approx(20.0)
    assert d[60] == pytest.approx(19.0)
    assert np.all(np.diff(d) < 0)


def test_start_along_offsets_a_line_beginning_inside_the_grid(header):
    pl = GridPlacement(grid_id="G", axis="y", offset=0.5, start_along=3.5)
    d = pl.distance_along(60, header)
    assert d[0] == pytest.approx(3.5)
    assert d[-1] == pytest.approx(3.5 + 59 / 60)


def test_axis_y_line_varies_in_world_y(header, frames):
    pl = GridPlacement(grid_id="G", axis="y", offset=2.0)
    xy = pl.trace_coords(60, header, frames)
    assert xy.shape == (60, 2)
    np.testing.assert_allclose(xy[:, 0], 2.0)  # constant cross-axis
    assert xy[-1, 1] == pytest.approx(59 / 60)


def test_axis_x_line_varies_in_world_x(header, frames):
    """Cross-hatched grids: the same grid holds lines along both axes."""
    pl = GridPlacement(grid_id="G", axis="x", offset=2.0)
    xy = pl.trace_coords(60, header, frames)
    np.testing.assert_allclose(xy[:, 1], 2.0)
    assert xy[-1, 0] == pytest.approx(59 / 60)


def test_cross_hatched_lines_share_one_grid(header, frames):
    along_y = GridPlacement(grid_id="G", axis="y", offset=1.0)
    along_x = GridPlacement(grid_id="G", axis="x", offset=1.0)
    a = along_y.trace_coords(60, header, frames)
    b = along_x.trace_coords(60, header, frames)
    assert not np.allclose(a, b)
    # they cross near local (1, 1)
    assert np.min(np.linalg.norm(a[:, None, :] - b[None, :, :], axis=-1)) < 0.05


def test_rotated_grid_places_traces_correctly(header):
    frames = {
        "G": Grid(
            id="G",
            origin=(100.0, 200.0),
            azimuth=90.0,
            size_x=20.0,
            size_y=20.0,
            crs="EPSG:32616",
            default_spacing=0.5,
        )
    }
    pl = GridPlacement(grid_id="G", axis="y", offset=0.0)
    xy = pl.trace_coords(61, header, frames)
    np.testing.assert_allclose(xy[0], [100.0, 200.0], atol=1e-9)
    np.testing.assert_allclose(xy[60], [101.0, 200.0], atol=1e-9)  # +Y is east


def test_unknown_grid_id_raises(header):
    pl = GridPlacement(grid_id="MISSING", axis="y", offset=0.0)
    with pytest.raises(KeyError, match="MISSING"):
        pl.trace_coords(10, header, {})


def test_rejects_bad_axis():
    with pytest.raises(ValueError, match="axis"):
        GridPlacement(grid_id="G", axis="z", offset=0.0)


def test_rejects_bad_direction():
    with pytest.raises(ValueError, match="direction"):
        GridPlacement(grid_id="G", axis="y", offset=0.0, direction=0)


def test_rejects_zero_traces_per_metre(tmp_path):
    """Time-triggered acquisition has no meaningful trace spacing; a grid
    placement cannot position such a line."""
    p = tmp_path / "t.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32), traces_per_metre=0.0)
    hdr = read_header(p)
    pl = GridPlacement(grid_id="G", axis="y", offset=0.0)
    with pytest.raises(ValueError, match="traces_per_metre"):
        pl.distance_along(10, hdr)
