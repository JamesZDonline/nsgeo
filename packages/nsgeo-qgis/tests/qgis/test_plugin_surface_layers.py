"""M16 B Task 4: built surfaces as mesh layers on the map (synthetic lines, a real GeoPackage)."""

# ruff: noqa: F811  (built_site is the surface-build tests' fixture, imported by name)
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from nsgeo.slices import SurfaceSettings
from nsgeo_qgis.surface_layers import (
    DEPTH_GROUP,
    GROUP_NAME,
    PROP_BUILD,
    PROP_FEATURE,
    SurfaceLayers,
    depth_ramp,
)
from plugin_testing import spin_until
from qgis.core import QgsMeshDatasetIndex, QgsMeshLayer, QgsProject
from qgis.PyQt.QtWidgets import QApplication
from test_plugin_surface_build import (
    GRID,
    _noop,
    _surface,
    _write,
    built_site,  # noqa: F401  (the fixture, by its own name)
)


@pytest.fixture
def shown(built_site):  # noqa: F811
    """`(session, layers, surfaces, surface_layers, project)`."""
    session, _, _, layers, surfaces = built_site
    project = QgsProject.instance()
    sl = SurfaceLayers(session, layers, surfaces, project=project)
    yield session, layers, surfaces, sl, project
    sl.dispose()


def _mesh_layers(project):
    return [lyr for lyr in project.mapLayers().values() if isinstance(lyr, QgsMeshLayer)]


def _by_feature(project, fid):
    return [lyr for lyr in _mesh_layers(project) if lyr.customProperty(PROP_FEATURE) == fid]


def _depth_index(layer) -> int:
    (i,) = [
        i
        for i in layer.datasetGroupsIndexes()
        if layer.datasetGroupMetadata(QgsMeshDatasetIndex(i)).name() == DEPTH_GROUP
    ]
    return i


def _surfaces_group(layers):
    (group,) = [c for c in layers.group.children() if c.name() == GROUP_NAME]
    return group


def _build(built_site_pieces, name="Bowl", **settings):
    record, _ = _surface(built_site_pieces, name, **settings)
    surfaces = built_site_pieces[4]
    (made,) = surfaces.build([record.feature_id], progress=_noop)
    return record, made


def test_a_built_surface_is_a_mesh_layer_coloured_by_depth(built_site, shown):
    session, layers, surfaces, sl, project = shown
    record, made = _build(built_site)
    assert _mesh_layers(project) == []  # nothing is drawn until the layers are synced
    sl.sync()
    (layer,) = _by_feature(project, record.feature_id)
    assert layer.isValid() and layer.name() == "Bowl"
    assert layer.providerType() == "mdal"
    assert layer.crs().authid() == session.grid(GRID).crs
    assert Path(layer.source()) == surfaces.folder(GRID) / made.report["files"]["2dm"]
    assert layer.customProperty(PROP_BUILD) == made.report["files"]["npz"].split("-")[1][:8]
    index = _depth_index(layer)
    settings = layer.rendererSettings()
    assert settings.activeScalarDatasetGroup() == index
    built = surfaces.built(record.feature_id)
    scalar = settings.scalarSettings(index)
    assert scalar.classificationMinimum() == pytest.approx(float(np.nanmin(built.depth_m)))
    assert scalar.classificationMaximum() == pytest.approx(float(np.nanmax(built.depth_m)))
    # Inverted Turbo: the shallow end of the ramp is Turbo's last colour (warm), not its first.
    ramp, name = depth_ramp()
    assert name == "Turbo"
    from qgis.core import QgsStyle

    turbo = QgsStyle.defaultStyle().colorRamp("Turbo")
    assert ramp.color(0.0).name() == turbo.color(1.0).name()
    assert ramp.color(1.0).name() == turbo.color(0.0).name()
    # It sits in a "Surfaces" group in the site's group, directly below picks.
    group = _surfaces_group(layers)
    kids = layers.group.children()
    picks_row = [
        i
        for i, c in enumerate(kids)
        if getattr(c, "layerId", lambda: "")() == layers.layers["picks"].id()
    ]
    assert kids[picks_row[0] + 1] is group
    assert [c.layerId() for c in group.children()] == [layer.id()]


def test_surfaces_of_one_grid_share_one_depth_range(built_site, shown):
    session, layers, surfaces, sl, project = shown
    a, _ = _build(built_site, "A")
    fids = _write(layers, session, [(0, 10, 12.0), (0, 40, 12.5), (1, 10, 12.5), (1, 40, 13.0)])
    b = surfaces.create("B", fids, SurfaceSettings(strength=0.0))
    surfaces.build([b.feature_id], progress=_noop)
    sl.sync()
    lows, highs = [], []
    for record in (a, b):
        built = surfaces.built(record.feature_id)
        lows.append(float(np.nanmin(built.depth_m)))
        highs.append(float(np.nanmax(built.depth_m)))
    assert lows[0] != lows[1] or highs[0] != highs[1]
    for record in (a, b):
        (layer,) = _by_feature(project, record.feature_id)
        scalar = layer.rendererSettings().scalarSettings(_depth_index(layer))
        assert scalar.classificationMinimum() == pytest.approx(min(lows))
        assert scalar.classificationMaximum() == pytest.approx(max(highs))


def test_a_stale_surface_is_labelled_and_keeps_its_last_build(built_site, shown):
    session, layers, surfaces, sl, project = shown
    record, made = _build(built_site)
    sl.sync()
    (layer,) = _by_feature(project, record.feature_id)
    key = layer.customProperty(PROP_BUILD)
    assert layer.name() == "Bowl"
    session.remember_volume(GRID, period_ns=3.0)  # a volume parameter: the surface is stale
    assert surfaces.state(record.feature_id).stale == ("volume",)
    sl.sync()
    (layer,) = _by_feature(project, record.feature_id)
    assert layer.name() == "Bowl (stale)"
    assert layer.customProperty(PROP_BUILD) == key  # still the last build, not rebuilt
    assert (surfaces.folder(GRID) / made.report["files"]["2dm"]).is_file()
    # a rebuild brings it up to date
    surfaces.build([record.feature_id], progress=_noop)
    sl.sync()
    (layer,) = _by_feature(project, record.feature_id)
    assert layer.name() == "Bowl"


def test_a_rebuild_writes_new_files_and_swaps_the_layer(built_site, shown, monkeypatch):
    session, layers, surfaces, sl, project = shown
    record, first = _build(built_site)
    other, _ = _build(built_site, "Other")
    sl.sync()
    (old,) = _by_feature(project, record.feature_id)
    group = _surfaces_group(layers)
    row = [c.layerId() for c in group.children()].index(old.id())
    old_files = {surfaces.folder(GRID) / n for n in first.report["files"].values()}
    old_key = old.customProperty(PROP_BUILD)
    (second,) = surfaces.build([record.feature_id], progress=_noop)
    new_files = {surfaces.folder(GRID) / n for n in second.report["files"].values()}
    assert not old_files & new_files and all(f.exists() for f in old_files | new_files)
    sl.sync()
    (layer,) = _by_feature(project, record.feature_id)
    assert layer.customProperty(PROP_BUILD) != old_key
    group = _surfaces_group(layers)
    assert [c.layerId() for c in group.children()].index(layer.id()) == row
    assert not any(f.exists() for f in old_files) and all(f.exists() for f in new_files)
    # Windows keeps a mesh file open: a delete that fails is skipped, and the next sweep retries.
    (third,) = surfaces.build([record.feature_id], progress=_noop)
    stuck = {surfaces.folder(GRID) / n for n in second.report["files"].values()}
    real = Path.unlink

    def refuse(self, *a, **k):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", refuse)
    sl.sync()  # succeeds
    (layer,) = _by_feature(project, record.feature_id)
    assert layer.customProperty(PROP_BUILD) == Path(third.files[0]).name.split("-")[1][:8]
    assert all(f.exists() for f in stuck)
    monkeypatch.setattr(Path, "unlink", real)
    assert sorted(surfaces.sweep(GRID)) == sorted(stuck)
    assert not any(f.exists() for f in stuck)


def test_an_empty_surface_has_no_layer_and_exports_cleanly(built_site, shown):
    from tests.vtk_reader import read_vtk_xml

    session, layers, surfaces, sl, project = shown
    export = built_site[2]
    record, made = _build(built_site, strength=1e9)
    assert made.report["cells"] == 0
    sl.sync()
    assert _by_feature(project, record.feature_id) == []
    assert [c for c in layers.group.children() if c.name() == GROUP_NAME] == []
    export.surfaces = surfaces
    folder = export.run(GRID, export.defaults(GRID), progress=_noop)
    doc = read_vtk_xml(folder / "features.vtp")
    assert doc["NumberOfPoints"] == 0
    rec = json.loads((folder / "export.json").read_text())
    assert [f["name"] for f in rec["features"]] == ["Bowl"]


def test_deleting_a_surface_removes_its_layer_and_files(built_site, shown):
    session, layers, surfaces, sl, project = shown
    record, made = _build(built_site)
    sl.sync()
    assert _by_feature(project, record.feature_id)
    surfaces.delete(record.feature_id)
    sl.sync()
    assert _mesh_layers(project) == []
    assert [c for c in layers.group.children() if c.name() == GROUP_NAME] == []
    assert list(surfaces.folder(GRID).iterdir()) == []


def test_closing_the_site_removes_the_surface_layers(built_site, shown):
    session, layers, surfaces, sl, project = shown
    _build(built_site)
    sl.sync()
    assert _mesh_layers(project)
    session.close_site()
    assert _mesh_layers(project) == []


def test_a_layer_removed_by_hand_returns_only_after_a_rebuild(built_site, shown):
    session, layers, surfaces, sl, project = shown
    record, _ = _build(built_site)
    sl.sync()
    (layer,) = _by_feature(project, record.feature_id)
    project.removeMapLayer(layer.id())
    sl.sync()
    sl.sync()
    assert _by_feature(project, record.feature_id) == []
    surfaces.build([record.feature_id], progress=_noop)
    sl.sync()
    assert len(_by_feature(project, record.feature_id)) == 1


def test_signals_ask_for_a_sync_that_coalesces(built_site, shown, monkeypatch):
    session, layers, surfaces, sl, project = shown
    record, _ = _build(built_site)
    calls = []
    real = sl.sync
    monkeypatch.setattr(sl, "sync", lambda: calls.append(1) or real())
    for signal in (session.features_changed, session.picks_changed, session.lines_changed):
        signal.emit()
    session.slice_sources_changed.emit(GRID)
    session.grids_changed.emit()
    session.presets_changed.emit()
    assert calls == []
    assert spin_until(lambda: bool(calls), 5000)
    QApplication.processEvents()
    assert calls == [1]
    assert len(_by_feature(project, record.feature_id)) == 1


def test_dispose_removes_its_layers_and_group_and_stops_listening(built_site, shown):
    session, layers, surfaces, sl, project = shown
    _build(built_site)
    sl.sync()
    sl.dispose()
    assert _mesh_layers(project) == []
    assert [c for c in layers.group.children() if c.name() == GROUP_NAME] == []
    session.features_changed.emit()
    QApplication.processEvents()
    assert _mesh_layers(project) == []
