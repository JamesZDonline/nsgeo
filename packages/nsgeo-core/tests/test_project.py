from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model import Cut
from nsgeo.model.survey import Line, Site
from nsgeo.processing import StepStack, build_step
from nsgeo.project import (
    CUTS_SCHEMA_VERSION,
    READABLE_SCHEMA_VERSIONS,
    VELOCITY_SOURCE_SCHEMA_VERSION,
    ProjectError,
    line_key,
    load_site,
    save_site,
)
from nsgeo.velocity import VelocityModel
from nsgeo.velocity_fit import StoredFit
from nsgeo.velocity_source import METHOD_FIT, SourceFit, VelocitySource

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


def test_a_grid_without_a_velocity_saves_none_and_loads_none(tmp_path, site):
    # #4: an unset grid velocity is "fall through to the line headers", not
    # an error, so it must survive the file as unset rather than as a number.
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert "velocity" not in json.loads(out.read_text())["grids"][0]
    assert load_site(out).grids[0].velocity is None


def test_a_stored_grid_velocity_loads_unchanged(tmp_path, site):
    # #4: making the velocity optional must not disturb a file that has one,
    # layered or not, to the last digit.
    model = VelocityModel(((0.0, 0.08012345678), (20.0, 0.07)))
    site.grids[0] = dataclasses.replace(site.grids[0], velocity=model)
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert load_site(out).grids[0].velocity == model


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
    doc["schema_version"] = 4
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="schema version 4"):
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


def test_cubes_round_trip_through_the_survey_json(tmp_path):
    site = Site()
    site.cubes = {
        "grid-a-standard": {
            "grid_id": "A",
            "preset": "slice-standard",
            "transform": "amp_envelope",
            "cell": 0.1,
            "array": "slices/grid-a-standard.npz",
        }
    }
    path = tmp_path / "survey.nsgeo.json"
    save_site(site, path)
    assert load_site(path).cubes == site.cubes


def test_a_site_with_no_cubes_writes_no_cubes_key(tmp_path):
    """Same rule presets already follow: absent, not an empty object."""
    path = tmp_path / "survey.nsgeo.json"
    save_site(Site(), path)
    assert "cubes" not in json.loads(path.read_text())


def test_an_older_file_without_cubes_still_loads(tmp_path):
    path = tmp_path / "survey.nsgeo.json"
    path.write_text(json.dumps({"schema_version": 1, "grids": [], "lines": []}))
    assert load_site(path).cubes == {}


@pytest.mark.parametrize("bad_cubes", [["x"], 5, "slices/a.npz"], ids=["list", "int", "str"])
def test_cubes_must_be_an_object_keyed_by_id(tmp_path, bad_cubes):
    """Mirrors the presets guard immediately above it in load_site: every
    other collection here (grids, presets, stacks) is validated the same
    way, and a non-dict cubes value would otherwise survive a load/save
    cycle intact and surface later wherever M11 does `site.cubes.items()`."""
    path = tmp_path / "survey.nsgeo.json"
    path.write_text(json.dumps({"schema_version": 1, "grids": [], "lines": [], "cubes": bad_cubes}))
    with pytest.raises(ProjectError, match="'cubes' must be an object"):
        load_site(path)


def test_a_full_cubes_record_round_trips_unchanged_even_with_an_absolute_array(tmp_path):
    """Two things at once, because they are the same guarantee seen from
    both sides.

    First: a record carrying every key `nsgeo_qgis.slice_export.
    cube_record` writes -- not just the five `test_cubes_round_trip_
    through_the_survey_json` above already covers, but also `lines`, `z`
    and `view` -- round-trips through `save_site`/`load_site` with no key
    dropped, renamed or coerced.

    Second, and the reason M11's `cube_record` has to do the sanitising
    itself: `save_site` does not route a record's `array` through
    `project.line_key` the way it does every line path elsewhere in a
    Site. An absolute `array` therefore round-trips VERBATIM, with no
    error and no rewrite -- proving `save_site` is not the safety net, so
    whatever calls it (`cube_record`) has to be.
    """
    site = Site()
    site.cubes = {
        "grid-a-standard": {
            "grid_id": "A",
            "preset": "slice-standard",
            "transform": "amp_envelope",
            "cell": 0.1,
            "lines": ["data/L0.DZT", "data/L1.DZT"],
            "z": {"t0_ns": 2.0, "t1_ns": 30.0, "dz_ns": 0.5},
            "array": "slices/grid-a-standard.npz",
            "view": {
                "thickness_ns": 5.0,
                "step_ns": 2.5,
                "radius_m": 0.75,
                "palette": "amp_heat",
                "stretch": "shared across the cube",
                "coverage": False,
            },
        },
        "out-of-tree": {
            "grid_id": "A",
            "preset": "slice-standard",
            "transform": "none",
            "cell": 0.1,
            "lines": [],
            "z": {"t0_ns": 0.0, "t1_ns": 10.0, "dz_ns": 1.0},
            "array": "/home/someone/scratch/cube.npz",
            "view": {
                "thickness_ns": 1.0,
                "step_ns": 1.0,
                "radius_m": 0.0,
                "palette": "seismic",
                "stretch": "this slice",
                "coverage": True,
            },
        },
    }
    path = tmp_path / "survey.nsgeo.json"
    save_site(site, path)
    reloaded = load_site(path).cubes
    assert reloaded == site.cubes
    assert reloaded["out-of-tree"]["array"] == "/home/someone/scratch/cube.npz"


def _a_fit() -> StoredFit:
    return StoredFit(
        t0_ns=18.4,
        v_m_ns=0.0984,
        v_stderr_m_ns=0.0041,
        rms_ns=0.31,
        apex_trace=412,
        points=((389, 21.2), (412, 18.6), (437, 21.9)),
        fitted_at="2026-10-22T14:02:11Z",
    )


def test_velocity_fits_survive_a_save_and_load(tmp_path, site):
    fit = _a_fit()
    source = VelocitySource.from_fits([SourceFit.of("data/L0.DZT", "f1", "L0", fit)], None)
    site.lines[0] = dataclasses.replace(
        site.lines[0], velocity_fits={"f1": fit}, velocity_source=source
    )
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    loaded = load_site(out).lines[0]
    assert loaded.velocity_fits == {"f1": fit}
    assert loaded.velocity_from_fit == "f1"
    assert loaded.velocity_source == source
    assert loaded.velocity_fits["f1"].points == ((389, 21.2), (412, 18.6), (437, 21.9))


def test_a_fits_time_zero_survives_a_save_and_load(tmp_path, site):
    fit = dataclasses.replace(_a_fit(), zero_ns=-0.4775)
    site.lines[0] = dataclasses.replace(site.lines[0], velocity_fits={"f1": fit})
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert load_site(out).lines[0].velocity_fits["f1"].zero_ns == -0.4775


def test_a_line_entry_without_fits_loads(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    entry = json.loads(out.read_text())["lines"][0]
    assert "velocity_fits" not in entry
    assert "velocity_from_fit" not in entry
    assert "velocity_source" not in entry
    loaded = load_site(out).lines[0]
    assert loaded.velocity_fits == {}
    assert loaded.velocity_from_fit is None


def test_a_file_with_fits_still_declares_schema_version_1(tmp_path, site):
    site.lines[0] = dataclasses.replace(site.lines[0], velocity_fits={"f1": _a_fit()})
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert json.loads(out.read_text())["schema_version"] == 1


def test_an_old_velocity_from_fit_naming_a_missing_fit_loads_no_record(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["lines"][0]["velocity_fits"] = {"f1": _a_fit().to_dict()}
    doc["lines"][0]["velocity_from_fit"] = "gone"
    out.write_text(json.dumps(doc))
    loaded = load_site(out).lines[0]
    assert loaded.velocity_from_fit is None
    assert loaded.velocity_source is None
    assert set(loaded.velocity_fits) == {"f1"}


@pytest.mark.parametrize("pointer", ['["f1"]', "{}", "7", "null"])
def test_a_non_string_velocity_from_fit_loads_as_no_selection(tmp_path, site, pointer):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    text = out.read_text()
    doc = json.loads(text)
    doc["lines"][0]["velocity_fits"] = {"f1": _a_fit().to_dict()}
    doc["lines"][0]["velocity_from_fit"] = "@@"
    # Hand-written JSON, as a person editing the file would leave it.
    out.write_text(json.dumps(doc).replace('"@@"', pointer))
    loaded = load_site(out).lines[0]
    assert loaded.velocity_from_fit is None
    assert loaded.velocity_source is None
    assert set(loaded.velocity_fits) == {"f1"}


def test_a_malformed_fit_raises_project_error_naming_the_line(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["lines"][0]["velocity_fits"] = {"f1": {"t0_ns": 1.0}}
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="data/L0.DZT"):
        load_site(out)


def _two_grid_site():
    g = _grid()
    return Site(grids=[dataclasses.replace(g, id="A"), dataclasses.replace(g, id="B")], lines=[])


def test_slice_sources_and_site_view_round_trip(tmp_path):
    site = _two_grid_site()
    site.slice_sources = {
        "A": {"preset": "slice-standard", "lines": ["data/L0.DZT"], "gain": 1.5},
        "B": {"preset": "slice-raw", "lines": None},
    }
    site.site_view = {"grids": ["A", "B"], "transform": "amp_envelope", "normalisation": "edge"}
    path = tmp_path / "survey.nsgeo.json"
    save_site(site, path)
    loaded = load_site(path)
    assert loaded.slice_sources == site.slice_sources
    assert loaded.site_view == site.site_view


_FULL_RESOLUTION = {
    "cell": 0.1,
    "dz_ns": 0.25,
    "t0_ns": 2.0,
    "t1_ns": 40.0,
    "max_distance_spacings": 1.5,
}


def test_a_remembered_resolution_round_trips(tmp_path):
    site = _two_grid_site()
    site.slice_sources = {"A": {"preset": "p", "resolution": dict(_FULL_RESOLUTION)}}
    site.site_view = {"grids": ["A"], "resolution": {"cell": 0.2, "max_distance_spacings": 0.75}}
    path = tmp_path / "survey.nsgeo.json"
    save_site(site, path)
    loaded = load_site(path)
    assert loaded.slice_sources == site.slice_sources
    assert loaded.site_view == site.site_view


def _load_with_resolution(tmp_path, resolution):
    site = _two_grid_site()
    path = tmp_path / "survey.nsgeo.json"
    save_site(site, path)
    doc = json.loads(path.read_text())
    doc["slice_sources"] = {"A": {"preset": "p", "resolution": resolution}}
    doc["site_view"] = {"transform": "none", "resolution": resolution}
    # allow_nan so a NaN reaches the loader as the bare token a hand-edit or
    # another writer could leave, not as a refused dump.
    path.write_text(json.dumps(doc, allow_nan=True))
    return load_site(path)


# Review Focus 2 (#71): a hand-edited or damaged value reads as unset and the
# survey still opens.
@pytest.mark.parametrize(
    "resolution",
    [
        [],
        {"cell": "0.2"},
        {"cell": 0},
        {"cell": -1.0},
        {"dz_ns": 0},
        {"cell": True},
        {"max_distance_spacings": -0.5},
        {"t0_ns": 5.0, "t1_ns": 5.0},
        {"t0_ns": 9.0, "t1_ns": 2.0},
        {"colour": 1},
        {"dz_ns": float("nan")},
        {"cell": 10**400},
    ],
    ids=[
        "list",
        "string-cell",
        "zero-cell",
        "negative-cell",
        "zero-dz",
        "bool-cell",
        "negative-max-distance",
        "empty-z-range",
        "reversed-z-range",
        "unknown-key",
        "nan-dz",
        "huge-int-cell",
    ],
)
def test_a_bad_remembered_resolution_value_reads_as_unset(tmp_path, resolution):
    loaded = _load_with_resolution(tmp_path, resolution)
    assert loaded.slice_sources == {"A": {"preset": "p"}}
    assert loaded.site_view == {"transform": "none"}


def test_an_integer_too_large_for_a_float_reads_as_unset_and_the_survey_opens(tmp_path):
    """Review Focus 2: JSON has no size limit on an integer, and one too large
    for a float made the loader raise OverflowError instead of reading the
    value as unset, for a resolution field and for a gain alike."""
    site = _two_grid_site()
    path = tmp_path / "survey.nsgeo.json"
    save_site(site, path)
    doc = json.loads(path.read_text())
    doc["slice_sources"] = {
        "A": {"preset": "p", "gain": 10**400},
        "B": {"preset": "p", "resolution": {"cell": 10**400, "dz_ns": 0.25}},
    }
    doc["site_view"] = {"transform": "none", "resolution": {"t1_ns": -(10**400)}}
    path.write_text(json.dumps(doc))
    loaded = load_site(path)
    assert loaded.slice_sources == {
        "A": {"preset": "p"},
        "B": {"preset": "p", "resolution": {"dz_ns": 0.25}},
    }
    assert loaded.site_view == {"transform": "none"}


def test_a_partly_bad_resolution_keeps_its_good_values(tmp_path):
    loaded = _load_with_resolution(tmp_path, {"cell": 0.1, "dz_ns": -1})
    assert loaded.slice_sources == {"A": {"preset": "p", "resolution": {"cell": 0.1}}}
    assert loaded.site_view == {"transform": "none", "resolution": {"cell": 0.1}}


def test_a_survey_without_them_loads_with_empty_defaults(tmp_path):
    path = tmp_path / "survey.nsgeo.json"
    path.write_text(json.dumps({"schema_version": 1, "grids": [], "lines": []}))
    loaded = load_site(path)
    assert loaded.slice_sources == {}
    assert loaded.site_view == {}


@pytest.mark.parametrize("key", ["slice_sources", "site_view"])
@pytest.mark.parametrize("bad", [[], 5, "x"], ids=["list", "int", "str"])
def test_a_wrong_top_level_type_is_a_project_error(tmp_path, key, bad):
    path = tmp_path / "survey.nsgeo.json"
    path.write_text(json.dumps({"schema_version": 1, "grids": [], "lines": [], key: bad}))
    with pytest.raises(ProjectError, match=f"'{key}' must be an object"):
        load_site(path)


def test_an_entry_for_an_unknown_grid_is_dropped_on_load(tmp_path):
    site = _two_grid_site()
    path = tmp_path / "survey.nsgeo.json"
    save_site(site, path)
    doc = json.loads(path.read_text())
    doc["slice_sources"] = {"A": {"preset": "p"}, "GONE": {"preset": "q"}}
    doc["site_view"] = {"grids": ["A", "GONE"], "transform": "none"}
    path.write_text(json.dumps(doc))
    loaded = load_site(path)
    assert loaded.slice_sources == {"A": {"preset": "p"}}
    assert loaded.site_view == {"grids": ["A"], "transform": "none"}


def test_a_wrong_typed_inner_value_reads_as_unset(tmp_path):
    site = _two_grid_site()
    path = tmp_path / "survey.nsgeo.json"
    save_site(site, path)
    doc = json.loads(path.read_text())
    doc["slice_sources"] = {
        "A": {"preset": 3, "lines": "L0", "gain": -2.0},
        "B": {"preset": "ok", "gain": 0.0},
        "GONE": 7,
    }
    doc["site_view"] = {"grids": "A", "transform": 4}
    path.write_text(json.dumps(doc))
    loaded = load_site(path)
    assert loaded.slice_sources == {"A": {}, "B": {"preset": "ok"}}
    assert loaded.site_view == {}


def test_empty_ones_are_not_written(tmp_path):
    path = tmp_path / "survey.nsgeo.json"
    save_site(Site(), path)
    doc = json.loads(path.read_text())
    assert "slice_sources" not in doc
    assert "site_view" not in doc


def test_remembered_finish_fields_are_kept_and_cleaned(tmp_path):
    good = {"method": "kriging", "max_distance_spacings": 0.75, "smooth_x_m": 0.3}
    loaded = _load_with_resolution(tmp_path, {**good, "cell": 0.2})
    assert loaded.slice_sources == {"A": {"preset": "p", "resolution": {**good, "cell": 0.2}}}
    assert loaded.site_view == {"transform": "none", "resolution": {**good, "cell": 0.2}}
    for bad in (
        {"method": "bogus"},
        {"method": 3},
        {"max_distance_spacings": -1},
        {"smooth_x_m": float("nan")},
        {"smooth_y_m": -1},
    ):
        loaded = _load_with_resolution(tmp_path, {**good, **bad})
        (key,) = bad
        kept = loaded.site_view["resolution"]
        assert key not in kept
        assert {k: v for k, v in good.items() if k != key} == {
            k: v for k, v in kept.items() if k != key
        }


def test_an_old_radius_spacings_is_dropped_on_load(tmp_path):
    # A 0.2.0 survey remembers a fill radius; this build has none and never
    # maps it onto the new controls (interpolation spec §8).
    loaded = _load_with_resolution(tmp_path, {"cell": 0.2, "radius_spacings": 0.5})
    assert loaded.site_view["resolution"] == {"cell": 0.2}


def test_scale_and_travel_shift_round_trip(tmp_path, site):
    site.lines[1] = dataclasses.replace(
        site.lines[1],
        placement=dataclasses.replace(site.lines[1].placement, scale=0.9542, travel_shift=0.24),
    )
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    back = load_site(out)
    assert back.lines[1].placement == site.lines[1].placement
    assert back.lines[0].placement.scale == 1.0 and back.lines[0].placement.travel_shift == 0.0


def test_a_line_without_corrections_writes_neither_key(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    for entry in json.loads(out.read_text())["lines"]:
        assert "scale" not in entry["placement"] and "travel_shift" not in entry["placement"]


@pytest.mark.parametrize("field,value", [("scale", 0), ("scale", "x"), ("travel_shift", None)])
def test_a_bad_scale_in_the_file_is_a_project_error_naming_the_line(tmp_path, site, field, value):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["lines"][0]["placement"][field] = value
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(out)


def test_a_null_placement_in_the_file_is_a_project_error_naming_the_line(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["lines"][0]["placement"] = None
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(out)


def _cut_site(cuts=True):
    site = _two_grid_site()
    if cuts:
        site.cuts = [
            Cut(id="c1", name="Cut 1", grid_id="A", vertices=((0.0, 0.0), (3.0, 0.0), (3.0, 4.5))),
            Cut(id="c2", name="Cut 2", grid_id="B", vertices=((1.0, 1.0), (2.0, 5.0))),
        ]
    return site


def test_cuts_round_trip_and_bump_the_schema_only_when_present(tmp_path):
    path = tmp_path / "survey.nsgeo.json"
    site = _cut_site()
    save_site(site, path)
    doc = json.loads(path.read_text())
    assert doc["schema_version"] == CUTS_SCHEMA_VERSION == 2
    assert load_site(path).cuts == site.cuts
    save_site(_cut_site(cuts=False), path)
    doc = json.loads(path.read_text())
    assert doc["schema_version"] == 1
    assert "cuts" not in doc
    assert load_site(path).cuts == []


def test_loads_schema_1_2_and_3_and_refuses_4(tmp_path):
    assert READABLE_SCHEMA_VERSIONS == (1, 2, 3)
    path = tmp_path / "survey.nsgeo.json"
    save_site(_cut_site(), path)
    doc = json.loads(path.read_text())
    for version, ok in ((1, True), (2, True), (3, True), (4, False)):
        doc["schema_version"] = version
        path.write_text(json.dumps(doc))
        if ok:
            load_site(path)
        else:
            with pytest.raises(ProjectError, match="schema version 4"):
                load_site(path)


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "c", "name": "n", "grid_id": "A"},
        {"id": "c", "name": "n", "grid_id": "A", "vertices": [[0, 0], [1]]},
        {"id": "c", "name": "n", "grid_id": "A", "vertices": [[0, 0], [1, 2, 3]]},
        {"id": "c", "name": "n", "grid_id": "A", "vertices": [[0, 0], [1e999, 1]]},
        {"id": "c", "name": "n", "grid_id": "A", "vertices": [[0, 0], ["a", 1]]},
        {"id": "c", "name": "n", "grid_id": "A", "vertices": [[0, 0]]},
        {"id": "c", "name": "n", "grid_id": "A", "vertices": "oops"},
        "not an object",
    ],
)
def test_a_malformed_cut_entry_is_a_project_error(tmp_path, entry):
    path = tmp_path / "survey.nsgeo.json"
    save_site(_cut_site(), path)
    doc = json.loads(path.read_text())
    doc["cuts"] = [entry]
    path.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="cut"):
        load_site(path)


def test_a_cut_on_an_unknown_grid_is_a_project_error(tmp_path):
    path = tmp_path / "survey.nsgeo.json"
    save_site(_cut_site(), path)
    doc = json.loads(path.read_text())
    doc["cuts"][0]["grid_id"] = "nowhere"
    path.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="nowhere"):
        load_site(path)


def test_duplicate_cut_ids_fail_validate():
    site = _cut_site()
    site.cuts.append(dataclasses.replace(site.cuts[0], name="Again"))
    with pytest.raises(ValueError, match="duplicate cut ids"):
        site.validate()
    site = _cut_site()
    site.cuts[0] = dataclasses.replace(site.cuts[0], grid_id="zzz")
    with pytest.raises(ValueError, match="unknown grid"):
        site.validate()


# --- velocity source records (grid velocity from fits, Task 1) ---


def _record(key="data/L0.DZT", fit_id="fit-1", label="L0", fit=None) -> VelocitySource:
    member = SourceFit.of(key, fit_id, label, fit or _a_fit())
    return VelocitySource.from_fits([member], "2026-11-12T09:00:00Z")


def _version(path) -> int:
    return json.loads(path.read_text())["schema_version"]


def test_a_site_without_records_saves_as_today(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert _version(out) == 1
    assert "velocity_source" not in out.read_text()
    site.cuts = [Cut(id="c1", name="Cut 1", grid_id="G1", vertices=((0.0, 0.0), (3.0, 4.0)))]
    save_site(site, out)
    assert _version(out) == 2
    assert "velocity_source" not in out.read_text()


def test_a_line_record_lifts_the_file_to_version_3_and_round_trips(tmp_path, site):
    assert VELOCITY_SOURCE_SCHEMA_VERSION == 3
    record = _record()
    site.lines[0] = dataclasses.replace(
        site.lines[0], velocity_fits={"fit-1": _a_fit()}, velocity_source=record
    )
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert _version(out) == 3
    doc = json.loads(out.read_text())
    assert "velocity_source" in doc["lines"][0]
    assert "velocity_from_fit" not in doc["lines"][0]
    assert load_site(out).lines[0].velocity_source == record


def test_a_grid_record_lifts_the_file_to_version_3_and_round_trips(tmp_path, site):
    a, b = _record(), _record("data/L1.DZT", "fit-2", "L1")
    average = VelocitySource.from_fits([a.members[0], b.members[0]], None)
    site.grids[0] = dataclasses.replace(
        site.grids[0], velocity=VelocityModel.constant(average.v_m_ns), velocity_source=average
    )
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert _version(out) == 3
    assert load_site(out).grids[0].velocity_source == average


def test_a_record_and_cuts_save_as_version_3(tmp_path, site):
    site.cuts = [Cut(id="c1", name="Cut 1", grid_id="G1", vertices=((0.0, 0.0), (3.0, 4.0)))]
    site.lines[0] = dataclasses.replace(site.lines[0], velocity_source=_record())
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert _version(out) == 3
    assert load_site(out).cuts == site.cuts


def test_version_3_loads_and_4_is_refused(tmp_path, site):
    site.lines[0] = dataclasses.replace(site.lines[0], velocity_source=_record())
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    load_site(out)
    doc = json.loads(out.read_text())
    doc["schema_version"] = 4
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="schema version 4"):
        load_site(out)


def test_an_old_velocity_from_fit_loads_as_a_one_fit_record(tmp_path, site):
    fit = _a_fit()
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["lines"][0]["velocity_fits"] = {"fit-2": fit.to_dict()}
    doc["lines"][0]["velocity_from_fit"] = "fit-2"
    out.write_text(json.dumps(doc))
    loaded = load_site(out)
    line = loaded.lines[0]
    src = line.velocity_source
    assert src is not None
    assert src.method == METHOD_FIT
    assert src.applied_at is None
    assert src.members[0] == SourceFit.of("data/L0.DZT", "fit-2", "line 0", fit)  # placement label
    assert line.velocity_from_fit == "fit-2"
    save_site(loaded, out)
    assert _version(out) == 3


def test_a_record_naming_a_line_or_fit_the_file_lacks_still_loads(tmp_path, site):
    record = _record("raw/GONE.DZT", "fit-9", "GONE")
    site.lines[0] = dataclasses.replace(site.lines[0], velocity_source=record)
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    loaded = load_site(out).lines[0]
    assert loaded.velocity_source == record
    assert loaded.velocity_from_fit is None


def test_a_malformed_line_record_is_a_project_error_naming_the_line(tmp_path, site):
    site.lines[0] = dataclasses.replace(site.lines[0], velocity_source=_record())
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["lines"][0]["velocity_source"]["method"] = "median"
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(out)


def test_a_malformed_grid_record_is_a_project_error_naming_the_grid(tmp_path, site):
    site.grids[0] = dataclasses.replace(site.grids[0], velocity_source=_record())
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["grids"][0]["velocity_source"]["members"] = []
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="G1"):
        load_site(out)


def test_fit_serial_saves_and_loads_without_lifting_the_version(tmp_path, site):
    site.lines[0] = dataclasses.replace(site.lines[0], fit_serial=5)
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert _version(out) == 1
    doc = json.loads(out.read_text())
    assert doc["lines"][0]["fit_serial"] == 5
    assert "fit_serial" not in doc["lines"][1]
    loaded = load_site(out)
    assert loaded.lines[0].fit_serial == 5
    assert loaded.lines[1].fit_serial == 0


def test_fit_serial_on_an_old_file_is_its_highest_fit_number(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    fit = _a_fit().to_dict()
    doc["lines"][0]["velocity_fits"] = {"fit-1": fit, "fit-4": fit, "f7": fit}
    out.write_text(json.dumps(doc))
    assert load_site(out).lines[0].fit_serial == 4


def test_fit_serial_is_the_larger_of_the_saved_and_the_highest_fit(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["lines"][0]["velocity_fits"] = {"fit-3": _a_fit().to_dict()}
    doc["lines"][0]["fit_serial"] = 2
    out.write_text(json.dumps(doc))
    assert load_site(out).lines[0].fit_serial == 3
    doc["lines"][0]["fit_serial"] = 9
    out.write_text(json.dumps(doc))
    assert load_site(out).lines[0].fit_serial == 9


def test_velocity_from_fit_reads_none_when_the_record_is_an_average_or_its_fit_is_gone(site):
    fit = _a_fit()
    line = site.lines[0]
    one = _record(fit=fit)
    with_fit = dataclasses.replace(line, velocity_fits={"fit-1": fit}, velocity_source=one)
    assert with_fit.velocity_from_fit == "fit-1"
    gone = dataclasses.replace(with_fit, velocity_fits={})
    assert gone.velocity_from_fit is None
    other = dataclasses.replace(fit, fitted_at="2026-12-01T00:00:00Z")
    reimported = dataclasses.replace(with_fit, velocity_fits={"fit-1": other})
    assert reimported.velocity_from_fit is None
    two = VelocitySource.from_fits(
        [one.members[0], _record("data/L1.DZT", "fit-2").members[0]], None
    )
    average = dataclasses.replace(
        line, velocity_fits={"fit-1": fit, "fit-2": fit}, velocity_source=two
    )
    assert average.velocity_from_fit is None
    assert line.velocity_from_fit is None


# ---- #180: the slice colours each scope keeps ------------------------------------------


def test_slice_colours_round_trip(tmp_path):
    site = _two_grid_site()
    site.slice_colours = {
        "grid": {"own": True, "style": "<qgis>grid</qgis>"},
        "site": {"own": False, "style": "<qgis>site</qgis>"},
    }
    path = tmp_path / "survey.nsgeo.json"
    save_site(site, path)
    assert json.loads(path.read_text())["slice_colours"] == site.slice_colours
    assert load_site(path).slice_colours == site.slice_colours


def test_no_slice_colours_writes_no_key(tmp_path):
    path = tmp_path / "survey.nsgeo.json"
    save_site(_two_grid_site(), path)
    assert "slice_colours" not in json.loads(path.read_text())
    assert load_site(path).slice_colours == {}


def test_damaged_slice_colours_read_as_unset(tmp_path):
    path = tmp_path / "survey.nsgeo.json"
    save_site(_two_grid_site(), path)
    doc = json.loads(path.read_text())
    doc["slice_colours"] = {
        "grid": {"own": "yes", "style": "<qgis/>"},
        "site": ["not", "an", "object"],
        "elsewhere": {"own": True},
    }
    path.write_text(json.dumps(doc))
    assert load_site(path).slice_colours == {"grid": {"style": "<qgis/>"}}


def test_slice_colours_that_are_not_an_object_read_as_unset(tmp_path):
    path = tmp_path / "survey.nsgeo.json"
    save_site(_two_grid_site(), path)
    doc = json.loads(path.read_text())
    doc["slice_colours"] = "own"
    path.write_text(json.dumps(doc))
    assert load_site(path).slice_colours == {}
