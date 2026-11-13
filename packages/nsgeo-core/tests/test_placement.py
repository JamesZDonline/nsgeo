from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io import trace_count
from nsgeo.io.dzt import read_header

from tests.real_data import CAMPUS_LINES
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


def test_scale_stretches_the_recorded_distance_from_the_start(header):
    d = GridPlacement("G", "y", 0.5, 1.0, scale=0.9).distance_along(120, header)
    assert d[0] == pytest.approx(1.0) and d[60] == pytest.approx(1.9)


def test_a_reversed_line_scales_toward_its_start(header):
    d = GridPlacement("G", "y", 0.5, 20.0, -1, scale=1.1).distance_along(120, header)
    assert d[0] == pytest.approx(20.0) and d[60] == pytest.approx(18.9)


def test_travel_shift_moves_every_trace_forward_along_its_own_direction(header):
    fwd = GridPlacement("G", "y", 0.5, 0.0, 1, travel_shift=0.24).distance_along(120, header)
    rev = GridPlacement("G", "y", 1.0, 20.0, -1, travel_shift=0.24).distance_along(120, header)
    assert (fwd[0], fwd[60]) == (pytest.approx(0.24), pytest.approx(1.24))
    assert (rev[0], rev[60]) == (pytest.approx(19.76), pytest.approx(18.76))


def test_the_shift_is_not_scaled(header):
    d = GridPlacement("G", "y", 0.5, scale=2.0, travel_shift=0.1).distance_along(120, header)
    assert d[60] == pytest.approx(2.1)


def test_the_defaults_place_exactly_as_before(header):
    d = GridPlacement("G", "y", 0.5, 3.5, -1).distance_along(120, header)
    assert np.array_equal(d, 3.5 - np.arange(120, dtype=float) / 60.0)


@pytest.mark.parametrize(
    "kw",
    [
        {"scale": 0.0},
        {"scale": -1.0},
        {"scale": float("nan")},
        {"scale": float("inf")},
        {"travel_shift": float("nan")},
        {"travel_shift": float("inf")},
    ],
)
def test_a_scale_or_shift_that_cannot_place_a_line_is_refused(kw):
    with pytest.raises(ValueError):
        GridPlacement("G", "y", 0.5, **kw)


def test_trace_coords_use_the_corrected_distance(header, frames):
    pl = GridPlacement("G", "x", 2.0, 1.0, 1, scale=1.5, travel_shift=0.2)
    xy = pl.trace_coords(60, header, frames)
    assert xy[:, 0] == pytest.approx(pl.distance_along(60, header))


def test_a_real_line_fitted_to_its_grid_ends_on_both_edges():
    """FILE__008 is the campus line that runs 11.10 m on its 10 m grid (#3)."""
    path = next((p for p in CAMPUS_LINES if p.stem == "FILE__008"), None)
    if path is None:
        pytest.skip("real campus data not present")
    h = read_header(path)
    n = trace_count(path, h)
    scale = 10.0 / ((n - 1) / h.traces_per_metre)
    fwd = GridPlacement("G", "y", 0.25, 0.0, 1, scale=scale).distance_along(n, h)
    rev = GridPlacement("G", "y", 0.75, 10.0, -1, scale=scale).distance_along(n, h)
    assert (fwd[0], fwd[-1]) == (pytest.approx(0.0), pytest.approx(10.0, abs=1e-9))
    assert (rev[0], rev[-1]) == (pytest.approx(10.0), pytest.approx(0.0, abs=1e-9))
    assert h.traces_per_metre == pytest.approx(60.0)  # the header stays as recorded


def test_along_and_local_are_the_placement_maths_without_a_header(tmp_path):
    p = GridPlacement("G", "y", 1.5, start_along=2.0, direction=-1, scale=0.9, travel_shift=0.1)
    np.testing.assert_allclose(p.along(5, 10.0), 2.0 - (0.9 * np.arange(5) / 10.0 + 0.1))
    np.testing.assert_allclose(
        p.local(5, 10.0), np.column_stack([np.full(5, 1.5), p.along(5, 10.0)])
    )
    q = GridPlacement("G", "x", 0.5, start_along=1.0)
    np.testing.assert_allclose(
        q.local(3, 10.0), np.column_stack([q.along(3, 10.0), np.full(3, 0.5)])
    )
    p10 = tmp_path / "t.DZT"
    write_dzt(p10, np.zeros((512, 10), dtype=np.int32), traces_per_metre=10.0)
    np.testing.assert_allclose(p.distance_along(5, read_header(p10)), p.along(5, 10.0))
