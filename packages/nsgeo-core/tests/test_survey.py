from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line, Profile, Site, clear_profile_cache

from tests.synthetic import write_dzt


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_profile_cache()
    yield
    clear_profile_cache()


@pytest.fixture
def grid():
    return Grid(
        id="G",
        origin=(0.0, 0.0),
        azimuth=0.0,
        size_x=20.0,
        size_y=20.0,
        crs="EPSG:32616",
        default_spacing=0.5,
    )


def _line(tmp_path, name="a.DZT", n_traces=120, n_channels=1, offset=0.5):
    p = tmp_path / name
    if n_channels == 1:
        data = np.zeros((512, n_traces), dtype=np.int32)
    else:
        data = np.zeros((n_channels, 512, n_traces), dtype=np.int32)
    write_dzt(p, data, n_channels=n_channels)
    return Line.open(p, GridPlacement(grid_id="G", axis="y", offset=offset))


def test_open_reads_header_and_trace_count_without_samples(tmp_path):
    line = _line(tmp_path, n_traces=137)
    assert line.n_traces == 137
    assert line.header.n_samples == 512


def test_load_returns_one_profile_per_channel(tmp_path):
    line = _line(tmp_path, n_channels=3)
    profiles = line.load()
    assert len(profiles) == 3
    assert all(p.n_traces == 120 for p in profiles)
    assert all(p.n_samples == 512 for p in profiles)


def test_all_channels_share_a_trace_count(tmp_path):
    """The invariant that makes trace index a valid join."""
    line = _line(tmp_path, n_channels=2)
    counts = {p.n_traces for p in line.load()}
    assert len(counts) == 1


def test_load_is_cached(tmp_path):
    line = _line(tmp_path)
    assert line.load()[0].data is line.load()[0].data


def test_cache_is_bounded(tmp_path):
    from nsgeo.model.survey import _load_profiles

    for i in range(_load_profiles.cache_parameters()["maxsize"] + 3):
        _line(tmp_path, name=f"f{i}.DZT", n_traces=8).load()
    info = _load_profiles.cache_info()
    assert info.currsize <= info.maxsize


def test_distance_along_uses_the_placement(tmp_path):
    line = _line(tmp_path, n_traces=120)
    d = line.distance_along()
    assert len(d) == 120
    assert d[60] == pytest.approx(1.0)


def test_trace_coords_join_data_by_index(tmp_path, grid):
    """Profile.data[:, i] and trace_coords()[i] are the same trace."""
    line = _line(tmp_path, n_traces=60, offset=2.0)
    xy = line.trace_coords({"G": grid})
    profile = line.load()[0]
    assert xy.shape[0] == profile.data.shape[1] == line.n_traces


def test_profile_data_is_read_only(tmp_path):
    """Raw data is never mutated."""
    line = _line(tmp_path)
    with pytest.raises(ValueError):
        line.load()[0].data[0, 0] = 1


def test_site_frames_maps_id_to_grid(grid):
    site = Site(grids=[grid], lines=[])
    assert site.frames["G"] is grid


def test_site_validate_rejects_dangling_grid_id(tmp_path, grid):
    line = Line.open(
        _line(tmp_path).path,
        GridPlacement(grid_id="NOPE", axis="y", offset=0.0),
    )
    site = Site(grids=[grid], lines=[line])
    with pytest.raises(ValueError, match="NOPE"):
        site.validate()


def test_site_validate_rejects_duplicate_grid_ids(grid):
    site = Site(grids=[grid, grid], lines=[])
    with pytest.raises(ValueError, match="duplicate"):
        site.validate()


def test_site_accepts_cross_hatched_lines_in_one_grid(tmp_path, grid):
    a = _line(tmp_path, name="y.DZT")
    b = Line.open(
        _line(tmp_path, name="x.DZT").path, GridPlacement(grid_id="G", axis="x", offset=0.5)
    )
    site = Site(grids=[grid], lines=[a, b])
    site.validate()


def test_profile_is_hashable_with_identity_equality(tmp_path):
    """Frozen dataclasses over ndarrays cannot use field equality (ambiguous
    truth value) — eq=False gives identity semantics and a working hash."""
    line = _line(tmp_path)
    a = line.load()[0]
    assert a == a
    assert hash(a) == hash(a)
    assert a != Profile(data=a.data, header=a.header)
    assert len({a, a}) == 1
