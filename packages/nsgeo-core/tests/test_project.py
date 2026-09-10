from __future__ import annotations

import json

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line, Site
from nsgeo.processing import StepStack, build_step
from nsgeo.project import ProjectError, load_site, save_site

from tests.synthetic import write_dzt


@pytest.fixture
def site(tmp_path):
    grid = Grid(
        id="G1",
        origin=(500.0, 700.0),
        azimuth=30.0,
        size_x=20.0,
        size_y=20.0,
        crs="EPSG:32616",
        default_spacing=0.5,
    )
    lines = []
    for i, axis in enumerate(["y", "y", "x"]):
        p = tmp_path / "data" / f"L{i}.DZT"
        p.parent.mkdir(exist_ok=True)
        write_dzt(p, np.zeros((512, 60), dtype=np.int32))
        lines.append(
            Line.open(
                p,
                GridPlacement(
                    grid_id="G1",
                    axis=axis,
                    offset=i * 0.5,
                    start_along=0.0,
                    direction=-1 if i == 1 else 1,
                    label=f"line {i}",
                ),
            )
        )
    return Site(grids=[grid], lines=lines)


def test_round_trips(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    back = load_site(out)
    assert len(back.grids) == 1
    assert back.grids[0].azimuth == pytest.approx(30.0)
    assert len(back.lines) == 3
    assert [ln.placement.axis for ln in back.lines] == ["y", "y", "x"]
    assert back.lines[1].placement.direction == -1
    assert back.lines[2].placement.label == "line 2"


def test_paths_are_stored_relative_with_posix_separators(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    stored = [ln["path"] for ln in doc["lines"]]
    assert stored == ["data/L0.DZT", "data/L1.DZT", "data/L2.DZT"]
    assert not any(p.startswith("/") or "\\" in p for p in stored)


def test_moving_the_whole_project_still_loads(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    moved = tmp_path / "moved"
    moved.mkdir()
    (tmp_path / "data").rename(moved / "data")
    out.rename(moved / "survey.nsgeo.json")
    back = load_site(moved / "survey.nsgeo.json")
    assert len(back.lines) == 3


def test_writes_schema_version(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert json.loads(out.read_text())["schema_version"] == 1


def test_rejects_future_schema_version(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["schema_version"] = 99
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="schema version 99"):
        load_site(out)


def test_rejects_unknown_placement_type(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["lines"][0]["placement"]["type"] = "teleport"
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="teleport"):
        load_site(out)


def test_missing_dzt_file_names_the_path(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    (tmp_path / "data" / "L0.DZT").unlink()
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(out)


def test_output_is_human_readable(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    text = out.read_text()
    assert "\n" in text and "  " in text  # indented, diffable


def test_dzt_outside_project_dir_is_a_project_error(tmp_path):
    """Storing an absolute path would silently break portability, so refuse."""
    project = tmp_path / "project"
    project.mkdir()
    elsewhere = tmp_path / "elsewhere" / "L9.DZT"
    elsewhere.parent.mkdir()
    write_dzt(elsewhere, np.zeros((512, 60), dtype=np.int32))
    grid = Grid(
        id="G1",
        origin=(0.0, 0.0),
        azimuth=0.0,
        size_x=20.0,
        size_y=20.0,
        crs="EPSG:32616",
        default_spacing=0.5,
    )
    line = Line.open(elsewhere, GridPlacement(grid_id="G1", axis="y", offset=0.0))
    with pytest.raises(ProjectError, match="not under the project directory"):
        save_site(Site(grids=[grid], lines=[line]), project / "survey.nsgeo.json")


def test_stack_keyed_by_a_path_that_matches_no_line_is_refused(tmp_path, site):
    """Lines live under data/, so a stack keyed by the bare filename matches
    no line: silently dropping it on save would lose processing provenance."""
    out = tmp_path / "survey.nsgeo.json"
    site.stacks = {"L0.DZT": StepStack()}
    with pytest.raises(ProjectError, match="match no line"):
        save_site(site, out)
    assert not out.exists()  # a bad save leaves no partial output


def test_stacks_round_trip_in_a_nested_layout(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    st = StepStack()
    st.append(build_step("dewow", window_ns=4.0))
    site.stacks = {"data/L0.DZT": st}
    save_site(site, out)
    back = load_site(out)
    assert back.stacks["data/L0.DZT"].to_dicts() == st.to_dicts()
