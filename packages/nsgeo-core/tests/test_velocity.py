"""Layered velocity: boundaries in two-way time, depth by integration.

Depth is measured from time zero. Before a time_zero step a real SIR-4000
file (position -11.09 ns) therefore has negative depth at the top. That is
correct, and the last test pins it against a real header.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io.dzt import read_header
from nsgeo.model.survey import Line, Site
from nsgeo.project import load_site, save_site
from nsgeo.velocity import C_M_PER_NS, VelocityModel, resolve_velocity

from tests.synthetic import write_dzt

DATA = Path(__file__).parent / "data" / "local"
FILES = sorted(p for p in DATA.rglob("*") if p.suffix.lower() == ".dzt") if DATA.exists() else []


def test_constant_velocity_depth_is_half_v_t():
    m = VelocityModel.constant(0.1)
    np.testing.assert_allclose(m.depth_at(np.array([0.0, 20.0, 40.0])), [0.0, 1.0, 2.0])
    assert m.is_constant
    assert m.surface_velocity == 0.1


def test_negative_time_gives_negative_depth():
    m = VelocityModel.constant(0.1)
    assert m.depth_at(np.array([-11.0]))[0] == pytest.approx(-0.55)


def test_from_dielectric_matches_c_over_sqrt_epsr():
    m = VelocityModel.from_dielectric(14.0)
    assert m.surface_velocity == pytest.approx(C_M_PER_NS / 14.0**0.5)
    assert m.surface_velocity == pytest.approx(0.0801, abs=1e-4)
    with pytest.raises(ValueError, match="dielectric"):
        VelocityModel.from_dielectric(0.0)


def test_two_layers_integrate_piecewise():
    m = VelocityModel(layers=((0.0, 0.1), (20.0, 0.05)))
    np.testing.assert_allclose(m.depth_at(np.array([0.0, 10.0, 20.0, 40.0])), [0.0, 0.5, 1.0, 1.5])
    np.testing.assert_allclose(
        m.velocity_at(np.array([-5.0, 5.0, 20.0, 99.0])), [0.1, 0.1, 0.05, 0.05]
    )
    assert not m.is_constant


def test_depth_is_monotone_for_any_valid_model():
    m = VelocityModel(layers=((0.0, 0.12), (15.0, 0.07), (60.0, 0.09)))
    d = m.depth_at(np.linspace(-10, 120, 400))
    assert np.all(np.diff(d) > 0)


def test_validation():
    with pytest.raises(ValueError, match="at least one"):
        VelocityModel(layers=())
    with pytest.raises(ValueError, match="0 ns"):
        VelocityModel(layers=((5.0, 0.1),))
    with pytest.raises(ValueError, match="increase"):
        VelocityModel(layers=((0.0, 0.1), (0.0, 0.2)))
    with pytest.raises(ValueError, match="positive"):
        VelocityModel(layers=((0.0, -0.1),))
    with pytest.raises(ValueError, match="positive"):
        VelocityModel.constant(0.0)


def test_layers_are_normalised_to_floats_and_immutable():
    m = VelocityModel(layers=((0, 1), (10, 2)))
    assert m.layers == ((0.0, 1.0), (10.0, 2.0))
    with pytest.raises(AttributeError):
        m.layers = ()  # type: ignore[misc]


def test_dict_round_trip():
    m = VelocityModel(layers=((0.0, 0.1), (20.0, 0.05)))
    doc = m.to_dict()
    assert doc == {"layers": [{"top_ns": 0.0, "v_m_ns": 0.1}, {"top_ns": 20.0, "v_m_ns": 0.05}]}
    assert VelocityModel.from_dict(doc) == m


@pytest.fixture
def line_and_grid(tmp_path):
    p = tmp_path / "L0.DZT"
    write_dzt(p, np.zeros((512, 30), dtype=np.int32))  # synthetic header has epsr 14
    grid = Grid("G", (0.0, 0.0), 0.0, 10.0, 10.0, "EPSG:32616", 0.5)
    line = Line.open(p, GridPlacement(grid_id="G", axis="y", offset=0.0))
    return line, grid


def test_resolution_order_is_line_then_grid_then_header(line_and_grid):
    line, grid = line_and_grid
    header_v = VelocityModel.from_dielectric(14.0)
    assert resolve_velocity(line, grid) == header_v
    assert resolve_velocity(line, None) == header_v
    grid_v = VelocityModel.constant(0.09)
    from dataclasses import replace

    grid2 = replace(grid, velocity=grid_v)
    assert resolve_velocity(line, grid2) == grid_v
    line2 = replace(line, velocity=VelocityModel.constant(0.07))
    assert resolve_velocity(line2, grid2) == VelocityModel.constant(0.07)


def test_project_round_trips_velocities_and_tolerates_their_absence(tmp_path, line_and_grid):
    line, grid = line_and_grid
    from dataclasses import replace

    grid = replace(grid, velocity=VelocityModel(layers=((0.0, 0.1), (20.0, 0.05))))
    line = replace(line, velocity=VelocityModel.constant(0.07))
    out = tmp_path / "survey.nsgeo.json"
    save_site(Site(grids=[grid], lines=[line]), out)
    back = load_site(out)
    assert back.grids[0].velocity == grid.velocity
    assert back.lines[0].velocity == VelocityModel.constant(0.07)

    bare = Site(grids=[replace(grid, velocity=None)], lines=[replace(line, velocity=None)])
    save_site(bare, out)
    text = out.read_text()
    assert "velocity" not in text
    back = load_site(out)
    assert back.grids[0].velocity is None and back.lines[0].velocity is None


@pytest.mark.skipif(not FILES, reason="no real DZT files in tests/data/local")
def test_real_header_suggestion_puts_the_top_of_the_record_below_zero_depth():
    h = read_header(FILES[0])
    m = VelocityModel.from_dielectric(h.epsr)
    top = float(m.depth_at(np.array([h.position_ns]))[0])
    assert -0.46 < top < -0.43  # -11.09 ns at 0.0801 m/ns
