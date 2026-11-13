"""M16 B Task 3: building a surface from picks (the kept fill, the files, the fit, staleness).

Synthetic DZT lines on a real GeoPackage, so these run on CI. The builder itself is pinned
by the core's tests; here the question is whether the plugin feeds it the right things and
writes what it made."""

from __future__ import annotations

import json
import types
from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.slices import SurfaceSettings
from nsgeo.velocity import VelocityModel
from nsgeo_qgis import paraview_export
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.paraview_export import ParaViewExportCancelled, place_picks
from nsgeo_qgis.session import Pick
from nsgeo_qgis.surface_plan import INPUTS, STALE_REASONS
from nsgeo_qgis.surfaces import Surfaces
from plugin_testing import STEPS_RADAR, STEPS_ZERO, synthetic_dzt
from qgis.core import QgsProject

GRID = "Grid A"
#: Four picks on the two lines: (line index, trace, two-way time in ns).
PICKS = [(0, 5, 10.0), (0, 55, 11.0), (1, 5, 10.5), (1, 55, 11.5)]


def _noop(done, total):
    return True


def _pick(key: str, trace: int, time_ns: float, zero_ns: float | None = None) -> Pick:
    return Pick(
        line_key=key,
        trace=trace,
        time_ns=time_ns,
        distance_m=None,
        depth_m=None,
        velocity_m_ns=None,
        stack_json="",
        note="",
        created="2026-11-13T00:00:00+00:00",
        zero_ns=zero_ns,
    )


@pytest.fixture
def built_site(synth_site):
    """`(session, dock, export, layers, surfaces)`; surfaces build through `export`."""
    session, dock, export = synth_site
    project = QgsProject.instance()
    project.clear()
    layers = SiteLayers(session, project=project)
    layers.refresh()  # the site is already open
    surfaces = Surfaces(session, layers, export_for=lambda: export)
    yield session, dock, export, layers, surfaces
    layers.detach()
    project.clear()


def _fids(layers) -> list[int]:
    return sorted(f.id() for f in layers.layers["picks"].dataProvider().getFeatures())


def _write(layers, session, specs=PICKS) -> list[int]:
    before = set(_fids(layers))
    keys = session.keys()
    for line, trace, time_ns in specs:
        layers.write_pick(_pick(keys[line], trace, time_ns))
    return sorted(set(_fids(layers)) - before)


def _surface(built_site, name="Bowl", **settings):
    session, _, _, layers, surfaces = built_site
    fids = _write(layers, session)
    settings.setdefault("strength", 0.0)
    return surfaces.create(name, fids, SurfaceSettings(**settings)), fids


def _folder(surfaces) -> Path:
    return surfaces.folder(GRID)


def _listing(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())} if folder.is_dir() else {}


def test_a_build_writes_its_files_and_reports_its_fit(built_site):
    session, _, _, _, surfaces = built_site
    record, _ = _surface(built_site)
    (made,) = surfaces.build([record.feature_id], progress=_noop)
    folder = surfaces.folder(GRID)
    assert folder == Path(session.root) / "surfaces" / "Grid_A"
    report = json.loads((folder / f"{record.feature_id}.json").read_text())
    assert report == made.report
    assert set(report["files"]) == {"npz", "2dm", "dat"}
    for name in report["files"].values():
        assert (folder / name).is_file()
    assert {p.name for p in folder.iterdir()} == {
        f"{record.feature_id}.json",
        *report["files"].values(),
    }
    assert report["fit"]["picks"] == 4
    assert set(report["fit"]) == {
        "picks",
        "within_2cm",
        "within_5cm",
        "further",
        "at_edge",
        "on_holes",
    }
    assert set(report["inputs"]) == set(INPUTS)
    assert report["feature_id"] == record.feature_id and report["name"] == "Bowl"
    assert report["grid"] == GRID and report["kind"] == "surface"
    assert {"offset_m", "offset_votes", "offset_at_limit", "offset_reliable"} <= set(report)
    with np.load(folder / report["files"]["npz"]) as npz:
        assert {"depth_m", "strength", "cell", "origin", "azimuth", "crs"} <= set(npz.files)
        finite = int(np.isfinite(npz["depth_m"]).sum())
        assert float(npz["cell"]) == report["resolution"]["cell"]
    assert finite > 0 and report["cells"] == finite
    text = (folder / report["files"]["2dm"]).read_text().splitlines()
    assert text[0] == "MESH2D"
    nodes = [ln.split() for ln in text if ln.startswith("ND ")]
    assert len(nodes) == finite
    triangles = [ln.split() for ln in text if ln.startswith("E3T ")]
    assert triangles and all(t[-1] == "1" for t in triangles)
    assert all(float(n[4]) < 0.0 for n in nodes)  # z = -depth
    dat = (folder / report["files"]["dat"]).read_text().splitlines()
    assert dat[:7] == [
        "DATASET",
        'OBJTYPE "mesh2d"',
        "BEGSCL",
        f"ND {finite}",
        f"NC {len(triangles)}",
        'NAME "depth (m)"',
        "TS 0 0.0",
    ]
    assert dat[-1] == "ENDDS" and len(dat) - 8 == finite
    assert all(float(v) > 0.0 for v in dat[7:-1])


def test_vertices_are_in_world_coordinates_of_the_grids_crs(built_site):
    session, _, _, _, surfaces = built_site
    record, _ = _surface(built_site)
    (made,) = surfaces.build([record.feature_id], progress=_noop)
    folder = surfaces.folder(GRID)
    nodes = [ln.split() for ln in (folder / made.report["files"]["2dm"]).read_text().splitlines()]
    nodes = np.array([[float(v) for v in n[2:5]] for n in nodes if n[0] == "ND"])
    # The grid sits at the origin with azimuth 0: world x, y are the frame's.
    assert nodes[:, 0].min() > 0.0 and nodes[:, 0].max() < 3.0
    assert nodes[:, 1].min() > 0.0 and nodes[:, 1].max() < 12.0
    # a rotated grid turns them (the frame's axes, not a copy of the local numbers)
    grid = session.grid(GRID)
    import dataclasses

    session.replace_grid(dataclasses.replace(grid, origin=(1000.0, 2000.0), azimuth=90.0))
    (again,) = surfaces.build([record.feature_id], progress=_noop)
    rows = (folder / again.report["files"]["2dm"]).read_text().splitlines()
    turned = np.array([[float(v) for v in r.split()[2:5]] for r in rows if r.startswith("ND ")])
    # azimuth 90: local +Y points east, local +X points south
    assert turned[:, 0].min() > 1000.0 and turned[:, 1].max() < 2000.0


def test_a_second_build_reuses_the_exports_fill(built_site, monkeypatch):
    _, _, export, _, surfaces = built_site
    record, _ = _surface(built_site)
    calls = []
    real = paraview_export.fill_levels
    monkeypatch.setattr(
        paraview_export, "fill_levels", lambda *a, **k: calls.append(1) or real(*a, **k)
    )
    surfaces.build([record.feature_id], progress=_noop)
    surfaces.build([record.feature_id], progress=_noop)
    assert len(calls) == 1
    # an export of the same grid and choice fills nothing either
    choice = export.defaults(GRID)
    export.run(GRID, choice, progress=_noop)
    assert len(calls) == 1


def test_a_cancelled_build_keeps_the_previous_one(built_site):
    _, _, _, _, surfaces = built_site
    record, _ = _surface(built_site)
    surfaces.build([record.feature_id], progress=_noop)
    folder = surfaces.folder(GRID)
    before = _listing(folder)
    seen = []

    def stop_after_the_fill(done, total):
        seen.append(done)
        return done < total * 0.8

    with pytest.raises(ParaViewExportCancelled):
        surfaces.build([record.feature_id], progress=stop_after_the_fill)
    assert seen
    assert _listing(folder) == before
    assert not [p for p in folder.iterdir() if p.name.endswith(".part")]
    assert surfaces.built(record.feature_id) is not None


@pytest.mark.parametrize("steps", [STEPS_ZERO, STEPS_RADAR], ids=["time_zero", "radar_clock"])
def test_picks_on_another_clock_land_on_the_cube_clock(built_site, steps):
    session, _, export, _, _ = built_site
    session.site.presets["p"] = list(steps)
    choice = export.defaults(GRID)
    got = export.fill(GRID, choice, progress=_noop)
    key = session.keys()[0]
    # one radar time, written against two clocks
    a = _pick(key, 20, 10.0, zero_ns=0.0)
    b = _pick(key, 20, 10.0 - 4.0, zero_ns=4.0)
    placed = place_picks([(key, a), (key, b)], got.lines, got.prov, got.frame, got.velocity)
    assert placed[0] is not None and placed[1] is not None
    assert placed[0].depth_m == pytest.approx(placed[1].depth_m)
    assert (placed[0].x_m, placed[0].y_m) == (placed[1].x_m, placed[1].y_m)
    # and a pick on a line that is not among the prepared lines is None
    assert place_picks([("raw/none.DZT", a)], got.lines, got.prov, got.frame, got.velocity) == [
        None
    ]
    del got


def _change(name, session, surfaces, layers, record):
    """Change exactly one input of the built surface."""
    if name == "picks":
        extra = _write(layers, session, [(0, 30, 10.5)])
        surfaces.add_picks(record.feature_id, extra)
    elif name == "settings":
        surfaces.set_settings(record.feature_id, SurfaceSettings(strength=0.0, window_m=0.03))
    elif name == "source":
        steps = [dict(s) for s in session.site.presets["p"]]
        steps[-1]["enabled"] = False
        session.site.presets["p"] = steps
    elif name == "resolution":
        session.remember_volume(GRID, cell=0.5)
    elif name == "fill":
        session.remember_slice_resolution(GRID, method="idw")
    elif name == "volume":
        session.remember_volume(GRID, period_ns=3.0)
    elif name == "velocity":
        session.set_grid_velocity(GRID, VelocityModel(layers=((0.0, 0.1),)))
    else:  # pragma: no cover
        raise AssertionError(name)


@pytest.mark.parametrize("name", INPUTS)
def test_each_input_marks_the_surface_stale_with_its_reason(built_site, name):
    session, _, _, layers, surfaces = built_site
    record, _ = _surface(built_site)
    assert surfaces.state(record.feature_id).built is False
    assert surfaces.state(record.feature_id).stale == ()
    surfaces.build([record.feature_id], progress=_noop)
    assert surfaces.state(record.feature_id).stale == ()
    _change(name, session, surfaces, layers, record)
    state = surfaces.state(record.feature_id)
    assert state.built and state.stale == (name,)
    assert name in STALE_REASONS and state.report is not None


def test_the_blur_and_the_slices_panel_never_make_a_surface_stale(built_site):
    session, dock, _, _, surfaces = built_site
    record, _ = _surface(built_site)
    surfaces.build([record.feature_id], progress=_noop)
    session.remember_volume(GRID, blur_m=0.3)
    session.remember_volume(GRID, stretch=2.0)
    session.remember_slice_resolution(GRID, cell=0.31, dz_ns=0.77)
    dock.transform_combo = types.SimpleNamespace(value=lambda: "amp_abs")
    dock.grid_id = "elsewhere"
    assert surfaces.state(record.feature_id).stale == ()


def test_a_member_deleted_by_hand_marks_the_surface_stale(built_site):
    session, _, _, layers, surfaces = built_site
    fids = _write(layers, session, PICKS + [(0, 30, 10.5)])
    record = surfaces.create("Bowl", fids, SurfaceSettings(strength=0.0))
    surfaces.build([record.feature_id], progress=_noop)
    layer = layers.layers["picks"]
    assert layer.startEditing()
    try:
        assert layer.deleteFeature(fids[-1])
    finally:
        assert layer.commitChanges()
    state = surfaces.state(record.feature_id)
    assert state.stale == ("picks",)
    (again,) = surfaces.build([record.feature_id], progress=_noop)
    assert again.report["fit"]["picks"] == 4
    assert surfaces.state(record.feature_id).stale == ()


def test_picks_moved_out_leave_too_few_to_rebuild(built_site):
    """Ruling R9: moving picks may leave a surface with fewer than 3; it keeps its last build."""
    _, _, _, layers, surfaces = built_site
    record, fids = _surface(built_site)
    surfaces.build([record.feature_id], progress=_noop)
    folder = surfaces.folder(GRID)
    before = _listing(folder)
    layers.set_pick_feature(fids[:2], None)
    with pytest.raises(ValueError, match="too few to rebuild"):
        surfaces.build([record.feature_id], progress=_noop)
    assert _listing(folder) == before
    assert surfaces.state(record.feature_id).stale == ("picks",)


def test_building_remembers_the_grids_3d_choice(built_site):
    session, _, export, _, surfaces = built_site
    record, _ = _surface(built_site)
    assert session.volume_record(GRID) == {}
    choice = export.defaults(GRID)
    surfaces.build([record.feature_id], progress=_noop)
    assert session.volume_record(GRID) == choice.to_record()


def test_a_build_is_refused_while_slices_prepare(built_site):
    _, dock, _, _, surfaces = built_site
    record, _ = _surface(built_site)
    dock.foreign_preparing = True
    with pytest.raises(RuntimeError, match="Slices are still preparing"):
        surfaces.build([record.feature_id], progress=_noop)
    assert not surfaces.folder(GRID).exists()


def test_a_pick_whose_line_is_not_prepared_is_skipped_not_fatal(built_site):
    session, _, _, layers, surfaces = built_site
    path = synthetic_dzt(Path(session.root) / "raw", "FILE__003.DZT", n_traces=60)
    session.add_lines([Line.open(path, GridPlacement(GRID, "y", 2.5, 0.0, 1, path.stem))])
    keys = session.keys()
    specs = PICKS + [(2, 30, 10.0)]
    fids = _write(layers, session, specs)
    record = surfaces.create("Bowl", fids, SurfaceSettings(strength=0.0))
    session.remember_slice_source(GRID, preset="p", lines=tuple(keys[:2]))
    (made,) = surfaces.build([record.feature_id], progress=_noop)
    assert made.report["fit"]["picks"] == 4
    assert [s["line_key"] for s in made.report["skipped"]] == [keys[2]]
    assert made.report["skipped"][0]["why"]


def test_sweep_deletes_only_unreferenced_files(built_site):
    _, _, _, _, surfaces = built_site
    record, _ = _surface(built_site)
    first = surfaces.build([record.feature_id], progress=_noop)[0].report
    second = surfaces.build([record.feature_id], progress=_noop)[0].report
    folder = surfaces.folder(GRID)
    assert set(first["files"].values()).isdisjoint(second["files"].values())
    (folder / "notes.txt").write_text("mine")
    (folder / f"{record.feature_id}-deadbeef.npz.part").write_bytes(b"x")
    surfaces.sweep(GRID)
    left = {p.name for p in folder.iterdir()}
    assert left == {"notes.txt", f"{record.feature_id}.json", *second["files"].values()}
    assert surfaces.built(record.feature_id) is not None
    surfaces.sweep(GRID)  # again: nothing more to do


def test_the_depth_range_down_to_is_honoured_like_the_exports(built_site, monkeypatch):
    """`t1_ns` clips the fill: a surface build and an export of one choice share one fill, and
    the resolution input carries the effective deepest time."""
    session, _, export, _, surfaces = built_site
    record, _ = _surface(built_site)
    surfaces.build([record.feature_id], progress=_noop)
    before = surfaces.inputs(record.feature_id)
    session.remember_volume(GRID, t1_ns=40.0)
    after = surfaces.inputs(record.feature_id)
    assert [k for k in INPUTS if before[k] != after[k]] == ["resolution"]
    (made,) = surfaces.build([record.feature_id], progress=_noop)
    assert surfaces.state(record.feature_id).stale == ()
    assert made.report["inputs"]["resolution"] == after["resolution"]


def test_a_surface_cannot_build_without_an_export(built_site):
    session, _, _, layers, _ = built_site
    surfaces = Surfaces(session, layers)
    record, _ = _surface(built_site, name="Other")
    with pytest.raises(RuntimeError):
        surfaces.build([record.feature_id], progress=_noop)
    with pytest.raises(RuntimeError):
        surfaces.inputs(record.feature_id)
