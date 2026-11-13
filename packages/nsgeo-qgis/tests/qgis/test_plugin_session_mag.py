"""Magnetometer grids and files in the session (M19a, Task 4)."""

from __future__ import annotations

import dataclasses

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.mag import MagFile, MagSetup
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from plugin_testing import synthetic_dzt, synthetic_grad601
from test_plugin_session import Spy


def test_set_mag_file_replaces_the_grids_file_and_announces_it(mag_site):
    session, root = mag_site
    old = session.mag_file_on("M1")
    assert old is not None
    new = MagFile.open(synthetic_grad601(root / "raw" / "mag", "m1b.dat"), "M1", MagSetup())
    session.save()
    changed = Spy(session.mag_changed)
    assert session.set_mag_file(new) is old
    assert len(changed.calls) == 1
    assert session.dirty
    assert session.mag_file_on("M1") is new
    assert session.mag_files() == [new]
    assert session.mag_for_key(session.mag_key(new)) is new
    with pytest.raises(KeyError):
        session.mag_for_key(session.mag_key(old))


def test_set_mag_file_on_an_empty_grid_returns_none(mag_site):
    session, root = mag_site
    m2 = MagFile.open(synthetic_grad601(root / "raw" / "mag", "m2.dat"), "M2", MagSetup())
    assert session.set_mag_file(m2) is None
    assert [g.id for g in session.mag_grids()] == ["M1", "M2"]
    assert [g.id for g in session.gpr_grids()] == ["G1"]


def test_the_same_file_cannot_sit_on_two_grids(mag_site):
    session, root = mag_site
    again = MagFile.open(session.mag_file_on("M1").path, "M2", MagSetup())
    changed = Spy(session.mag_changed)
    with pytest.raises(ValueError):
        session.set_mag_file(again)
    assert changed.calls == [] and session.mag_file_on("M2") is None


def test_a_mag_file_cannot_go_on_a_gpr_grid(mag_site):
    session, root = mag_site
    bad = MagFile.open(synthetic_grad601(root / "raw" / "mag", "x.dat"), "G1", MagSetup())
    with pytest.raises(ValueError):
        session.set_mag_file(bad)
    ghost = dataclasses.replace(bad, grid_id="nope")
    with pytest.raises(ValueError):
        session.set_mag_file(ghost)
    assert len(session.mag_files()) == 1


def test_dzt_lines_cannot_go_on_a_mag_grid(mag_site):
    session, root = mag_site
    path = synthetic_dzt(root / "raw" / "M1", "FILE__009.DZT")
    line = Line.open(path, GridPlacement("M1", "y", 1.0, 0.05, 1, path.stem))
    before = session.keys()
    with pytest.raises(ValueError, match="grid 'M1' is a magnetometer grid; DZT lines go on GPR"):
        session.add_lines([line])
    assert session.keys() == before


def test_removing_a_mag_grid_holding_a_file_needs_with_lines(mag_site):
    session, root = mag_site
    session.set_mag_view(grid="M1")
    session.save()
    changed = Spy(session.mag_changed)
    with pytest.raises(ValueError):
        session.remove_grid("M1")
    assert changed.calls == [] and session.mag_file_on("M1") is not None
    session.remove_grid("M1", with_lines=True)
    assert len(changed.calls) == 1
    assert session.mag_files() == []
    assert "grid" not in session.mag_view()
    assert [g.id for g in session.mag_grids()] == ["M2"]
    session.save()  # still validates


def test_removing_an_empty_mag_grid_needs_nothing_more(mag_site):
    session, _ = mag_site
    session.remove_grid("M2")
    assert [g.id for g in session.mag_grids()] == ["M1"]


def test_a_grids_instrument_cannot_change(mag_site):
    session, _ = mag_site
    with pytest.raises(ValueError, match="a grid's instrument cannot change"):
        session.replace_grid(dataclasses.replace(session.grid("M1"), instrument="gpr"))
    with pytest.raises(ValueError, match="a grid's instrument cannot change"):
        session.replace_grid(dataclasses.replace(session.grid("G1"), instrument="mag"))
    assert session.grid("M1").instrument == "mag"


def test_replacing_a_mag_grid_keeps_its_file(mag_site):
    session, _ = mag_site
    session.replace_grid(dataclasses.replace(session.grid("M1"), size_x=5.0))
    assert session.mag_file_on("M1") is not None


def test_remove_mag_file_announces_and_dirties(mag_site):
    session, _ = mag_site
    key = session.mag_key(session.mag_file_on("M1"))
    session.save()
    changed = Spy(session.mag_changed)
    session.remove_mag_file(key)
    assert session.mag_files() == [] and session.dirty and len(changed.calls) == 1
    with pytest.raises(KeyError):
        session.remove_mag_file(key)


def test_mag_view_and_setup_merge_and_dirty_only_on_change(mag_site):
    session, _ = mag_site
    session.save()
    assert session.mag_view() == {}
    session.set_mag_view(scope="site", cell=0.25)
    assert session.dirty
    assert session.mag_view() == {"scope": "site", "cell": 0.25}
    session.save()
    session.set_mag_view(cell=0.25)
    assert not session.dirty
    session.set_mag_view(palette="viridis")
    assert session.mag_view() == {"scope": "site", "cell": 0.25, "palette": "viridis"}
    session.mag_view()["cell"] = 9  # a copy
    assert session.mag_view()["cell"] == 0.25
    session.save()
    assert session.mag_setup() is None
    session.remember_mag_setup(MagSetup())
    assert session.dirty and session.mag_setup() == MagSetup()
    session.save()
    session.remember_mag_setup(MagSetup())
    assert not session.dirty
    session.remember_mag_setup(MagSetup(spacing_m=0.25, first_offset_m=0.125))
    assert session.dirty


def test_mag_colours_are_a_scope(mag_site):
    session, _ = mag_site
    session.set_slice_colours("mag", own=True)
    assert session.slice_colours("mag") == {"own": True}


def test_a_saved_mag_site_reopens_with_its_files(mag_site):
    session, root = mag_site
    session.set_mag_view(grid="M1")
    session.remember_mag_setup(MagSetup())
    session.save()
    again = SiteSession()
    again.open_site(session.json_path)
    assert [g.id for g in again.mag_grids()] == ["M1", "M2"]
    assert again.mag_file_on("M1").path == session.mag_file_on("M1").path
    assert again.mag_file_on("M2") is None
    assert again.mag_view() == {"grid": "M1"}
    assert again.mag_setup() == MagSetup()
    assert again.mag_key(again.mag_files()[0]) == session.mag_key(session.mag_files()[0])


def test_a_gpr_site_has_no_mag(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.add_grid(Grid("A", (0.0, 0.0), 0.0, 5.0, 5.0, "EPSG:32616", 1.0))
    assert s.mag_files() == [] and s.mag_grids() == [] and s.mag_setup() is None
    assert [g.id for g in s.gpr_grids()] == ["A"]
