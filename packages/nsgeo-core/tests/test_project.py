from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line, Site
from nsgeo.processing import StepStack, build_step
from nsgeo.project import ProjectError, line_key, load_site, save_site

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


def _grid():
    return Grid(
        id="G1",
        origin=(0.0, 0.0),
        azimuth=0.0,
        size_x=20.0,
        size_y=20.0,
        crs="EPSG:32616",
        default_spacing=0.5,
    )


def _line_at(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_dzt(path, np.zeros((512, 60), dtype=np.int32))
    return Line.open(path, GridPlacement(grid_id="G1", axis="y", offset=0.0))


def test_allow_absolute_stores_an_absolute_posix_path_for_an_out_of_tree_file(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    line = _line_at(tmp_path / "elsewhere" / "L9.DZT")
    out = project / "survey.nsgeo.json"
    save_site(Site(grids=[_grid()], lines=[line]), out, allow_absolute=True)
    stored = json.loads(out.read_text())["lines"][0]["path"]
    assert Path(stored).is_absolute()
    assert stored == line.path.resolve().as_posix()
    assert "\\" not in stored


def test_absolute_path_round_trips_through_load(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    line = _line_at(tmp_path / "elsewhere" / "L9.DZT")
    out = project / "survey.nsgeo.json"
    save_site(Site(grids=[_grid()], lines=[line]), out, allow_absolute=True)
    back = load_site(out)
    assert back.lines[0].path.resolve() == line.path.resolve()
    assert back.lines[0].n_traces == 60


def test_in_tree_files_stay_relative_even_when_absolute_is_allowed(tmp_path, site):
    """The option is a fallback for out-of-tree files, not a switch to absolute."""
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out, allow_absolute=True)
    stored = [ln["path"] for ln in json.loads(out.read_text())["lines"]]
    assert stored == ["data/L0.DZT", "data/L1.DZT", "data/L2.DZT"]


def test_mixed_project_keeps_in_tree_relative_and_out_of_tree_absolute(tmp_path):
    project = tmp_path / "project"
    inside = _line_at(project / "data" / "L0.DZT")
    outside = _line_at(tmp_path / "elsewhere" / "L9.DZT")
    out = project / "survey.nsgeo.json"
    save_site(Site(grids=[_grid()], lines=[inside, outside]), out, allow_absolute=True)
    stored = [ln["path"] for ln in json.loads(out.read_text())["lines"]]
    assert stored[0] == "data/L0.DZT"
    assert Path(stored[1]).is_absolute()
    assert len(load_site(out).lines) == 2


def test_stack_for_an_absolute_line_is_keyed_by_the_absolute_string(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    line = _line_at(tmp_path / "elsewhere" / "L9.DZT")
    key = line.path.resolve().as_posix()
    st = StepStack()
    st.append(build_step("dewow", window_ns=4.0))
    out = project / "survey.nsgeo.json"
    save_site(Site(grids=[_grid()], lines=[line], stacks={key: st}), out, allow_absolute=True)
    assert load_site(out).stacks[key].to_dicts() == st.to_dicts()


def test_a_symlinked_data_directory_keeps_its_stacks_and_stays_saveable(tmp_path):
    """Survey data on an external disk, symlinked into the project as `data/`.

    An ordinary arrangement when GPR data runs to gigabytes, and one the
    relative-path format is meant to support. It used to open, show none of
    its saved processing, and then refuse every save: `save_site` keyed by a
    resolved path (the external disk, out of tree) while `load_site` keyed by
    the raw stored string, so the stack was loaded under a key nothing would
    ever ask for, the plain save was refused as out-of-tree, and the
    `allow_absolute` fallback the plugin offers next failed too -- the stack
    was now an orphan matching no line.

    Asserts all three halves: the key a session would look up hits, the
    stack behind it is the one that was saved, and a plain save still
    works and still stores the portable relative path.
    """
    project = tmp_path / "project"
    line = _line_at(project / "data" / "L0.DZT")
    stack = StepStack()
    stack.append(build_step("dewow", window_ns=4.0))
    out = project / "survey.nsgeo.json"
    save_site(Site(grids=[_grid()], lines=[line], stacks={"data/L0.DZT": stack}), out)

    external = tmp_path / "external"
    (project / "data").rename(external)
    (project / "data").symlink_to(external, target_is_directory=True)
    assert (project / "data").is_symlink()

    back = load_site(out)
    # Exactly what SiteSession.line_key() computes for this line.
    key = line_key(back.lines[0].path, project.resolve(), allow_absolute=True)
    assert key in back.stacks
    assert back.stacks[key].to_dicts() == stack.to_dicts()

    save_site(back, out)
    assert [ln["path"] for ln in json.loads(out.read_text())["lines"]] == ["data/L0.DZT"]


def test_a_non_canonical_stored_path_is_keyed_the_way_a_save_keys_it(tmp_path):
    """The format is advertised as human-readable and hand-editable, so a
    path that is correct but not canonical must behave like the canonical
    one. `data/../data/L0.DZT` is such a path -- pathlib collapses a `.`
    segment on its own but never a `..` one -- and keying a loaded stack by
    the raw string made it an orphan that no save would accept again."""
    project = tmp_path / "project"
    line = _line_at(project / "data" / "L0.DZT")
    stack = StepStack()
    stack.append(build_step("dewow", window_ns=4.0))
    out = project / "survey.nsgeo.json"
    save_site(Site(grids=[_grid()], lines=[line], stacks={"data/L0.DZT": stack}), out)

    doc = json.loads(out.read_text())
    doc["lines"][0]["path"] = "data/../data/L0.DZT"
    out.write_text(json.dumps(doc, indent=2) + "\n")

    back = load_site(out)
    assert "data/L0.DZT" in back.stacks
    assert back.stacks["data/L0.DZT"].to_dicts() == stack.to_dicts()

    save_site(back, out)
    assert [ln["path"] for ln in json.loads(out.read_text())["lines"]] == ["data/L0.DZT"]


def test_out_of_tree_error_names_the_opt_in(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    line = _line_at(tmp_path / "elsewhere" / "L9.DZT")
    with pytest.raises(ProjectError, match="allow_absolute=True"):
        save_site(Site(grids=[_grid()], lines=[line]), project / "survey.nsgeo.json")
