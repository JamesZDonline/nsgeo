"""M16 C Task 2: `Scene3D` shows a grid's picks at depth and its surfaces in a (fake) 3-D view.

The real `createNewMapCanvas3D` hangs offscreen, so every test goes through `FakeIface`'s fake
canvas. Synthetic lines on a real GeoPackage, so these run on CI."""

from __future__ import annotations

import re
import types

import pytest
from nsgeo.geometry import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.slices import SurfaceSettings
from nsgeo_qgis.scene3d import Scene3D
from nsgeo_qgis.scene3d_plan import BUTTON_TIP, NO_GRID, VIEW_NAME, VIEW_REFUSED, view_title
from nsgeo_qgis.surface_layers import SurfaceLayers
from plugin_testing import GRID, spin_until, synthetic_dzt
from qgis.core import QgsProject, QgsReadWriteContext
from qgis.PyQt.QtXml import QDomDocument
from test_plugin_surface_build import PICKS, _noop, _pick, _surface

A = GRID.id
B = "Grid B"


def _vertical_scale(layer):
    """The layer's 3-D mesh symbol's `vertical-scale`, or None when it has no renderer."""
    renderer = layer.renderer3D()
    if renderer is None:
        return None
    doc = QDomDocument()
    root = doc.createElement("r")
    doc.appendChild(root)
    renderer.writeXml(root, QgsReadWriteContext())
    (found,) = re.findall(r'vertical-scale="([^"]+)"', doc.toString())
    return float(found)


def _all_rows(layers):
    picks = layers.layers["picks"]
    return layers.pick_rows(picks.dataProvider().allFeatureIds())


def _depths_of(scene, grid_id):
    """`pick_depths` for every saved pick on `grid_id`, the Nones dropped."""
    _, session, surfaces, _, _, export = scene
    rows = [(r.pick.line_key, r.pick) for r in _all_rows(surfaces.layers)]
    return [d for d in export.pick_depths(grid_id, rows) if d is not None]


def _z(scene):
    return sorted(f.geometry().constGet().z() for f in scene[0].picks_layer.getFeatures())


@pytest.fixture
def scene(built_site, tmp_path, fake_iface):
    """`(scene3d, session, surfaces, surface_layers, iface, export)`: grid A with a built
    surface, grid B (a line, four picks) with another, both shown on the map."""
    session, _, export, layers, surfaces = built_site
    project = QgsProject.instance()
    record_a, _ = _surface(built_site, "Bowl A")
    surfaces.build([record_a.feature_id], progress=_noop)
    session.add_grid(Grid(B, (20.0, 0.0), 0.0, 3.0, 12.0, "EPSG:32616", 0.5))
    paths = [synthetic_dzt(tmp_path / "rawb", f"B__00{i}.DZT", n_traces=60) for i in (1, 2)]
    session.add_lines(
        [Line.open(p, GridPlacement(B, "y", 0.5 + i, 0.0, 1, p.stem)) for i, p in enumerate(paths)]
    )
    keys = session.keys_on_grid(B)
    for line, trace, time_ns in PICKS:
        layers.write_pick(_pick(keys[line], trace, time_ns))
    fids = sorted(f.id() for f in layers.layers["picks"].dataProvider().getFeatures())[-4:]
    record_b = surfaces.create("Bowl B", fids, SurfaceSettings(strength=0.0))
    surfaces.build([record_b.feature_id], progress=_noop)
    sl = SurfaceLayers(session, layers, surfaces, project=project)
    sl.sync()
    state = types.SimpleNamespace(scope="grid", grid=A)
    dock = types.SimpleNamespace(
        scope=lambda: state.scope,
        grid_combo=types.SimpleNamespace(currentText=lambda: state.grid),
        state=state,
    )
    s3d = Scene3D(session, layers, surfaces, sl, lambda: export, dock, fake_iface, project=project)
    s3d.dock_state = state
    yield s3d, session, surfaces, sl, fake_iface, export
    s3d.dispose()
    sl.dispose()


def test_open_shows_the_scene_grids_picks_and_surfaces(scene):
    s3d, session, surfaces, surface_layers, iface, _ = scene
    session._set_dirty(False)
    s3d.open()
    assert s3d.is_open() and s3d.grid_id == A
    shown = surface_layers.layers_by_feature()
    assert len(shown) == 2
    for rec in surfaces.records():
        expect = 3.0 if rec.grid_id == A else None
        assert _vertical_scale(shown[rec.feature_id]) == expect
    pts = list(s3d.picks_layer.getFeatures())
    depths = _depths_of(scene, A)
    assert len(depths) == 4 and len(pts) == 4
    assert sorted(f.geometry().constGet().z() for f in pts) == pytest.approx(
        sorted(-d * 3.0 for d in depths)
    )
    settings = iface.canvases3d[VIEW_NAME].mapSettings()
    assert settings.terrainRenderingEnabled() is False
    assert iface.dialogs3d[VIEW_NAME].windowTitle() == view_title(A, 3.0, 0)
    assert len(iface.canvases3d[VIEW_NAME].cameraController().poses) == 1
    assert session.dirty is False
    # QGIS resets the view to the map's layers in the tick it opens; the 0 ms re-set from the
    # layer tree puts the picks layer back (the fake alone copies at creation and would pass)
    settings.setLayers([])
    assert spin_until(lambda: s3d.picks_layer.id() in [lyr.id() for lyr in settings.layers()])


def test_opening_again_reuses_the_view_and_brings_it_forward(scene):
    s3d, _, _, _, iface, _ = scene
    s3d.open()
    dialog = iface.dialogs3d[VIEW_NAME]
    before = dialog.raised
    s3d.open()
    assert iface.created3d == 1 and s3d.is_open()
    assert dialog.raised == before + 1


def test_a_view_closed_by_hand_cleans_up_and_opens_again(scene):
    s3d, session, surfaces, surface_layers, iface, _ = scene
    session._set_dirty(False)
    s3d.open()
    picks_id = s3d.picks_layer.id()
    iface.closeMapCanvas3D(VIEW_NAME)
    assert not s3d.is_open()
    assert QgsProject.instance().mapLayer(picks_id) is None and s3d.picks_layer is None
    assert all(lyr.renderer3D() is None for lyr in surface_layers.layers_by_feature().values())
    assert session.dirty is False
    s3d.open()
    assert iface.created3d == 2 and s3d.is_open()
    s3d.close()
    assert not s3d.is_open() and iface.canvases3d == {}
    assert all(lyr.renderer3D() is None for lyr in surface_layers.layers_by_feature().values())
    assert session.dirty is False


def test_a_new_pick_and_a_rebuild_show_without_reopening(scene):
    s3d, session, surfaces, surface_layers, iface, _ = scene
    session._set_dirty(False)
    s3d.open()
    n = len(list(s3d.picks_layer.getFeatures()))
    keys = session.keys_on_grid(A)
    surfaces.layers.write_pick(_pick(keys[0], 30, 10.2))
    session.picks_changed.emit()  # as the picks layer's edits announce a pick
    assert spin_until(lambda: len(list(s3d.picks_layer.getFeatures())) == n + 1)
    # a rebuild puts a new layer on the map; the listener gives it the renderer
    (record,) = [r for r in surfaces.records() if r.grid_id == A]
    old = surface_layers.layers_by_feature()[record.feature_id].id()
    surfaces.set_settings(record.feature_id, SurfaceSettings(strength=0.0, window_m=0.03))
    surfaces.build([record.feature_id], progress=_noop)
    surface_layers.sync()
    new = surface_layers.layers_by_feature()[record.feature_id]
    assert new.id() != old
    assert spin_until(lambda: _vertical_scale(new) == 3.0)
    assert session.dirty is False


def test_the_stretch_restretches_picks_and_surfaces(scene):
    s3d, session, surfaces, surface_layers, iface, _ = scene
    s3d.open()
    depths = _depths_of(scene, A)
    session.remember_volume(A, stretch=2.0)
    s3d.refresh()
    assert _z(scene) == pytest.approx(sorted(-d * 2.0 for d in depths))
    (record,) = [r for r in surfaces.records() if r.grid_id == A]
    assert _vertical_scale(surface_layers.layers_by_feature()[record.feature_id]) == 2.0
    assert iface.dialogs3d[VIEW_NAME].windowTitle() == view_title(A, 2.0, 0)
    assert "×2" in iface.dialogs3d[VIEW_NAME].windowTitle()


def test_the_scene_follows_this_grid_and_keeps_its_grid_in_whole_site(scene):
    s3d, session, surfaces, surface_layers, iface, _ = scene
    s3d.open()
    poses = iface.canvases3d[VIEW_NAME].cameraController().poses
    assert len(poses) == 1
    s3d.dock_state.grid = B
    s3d.refresh()
    assert s3d.grid_id == B
    for rec in surfaces.records():
        expect = 3.0 if rec.grid_id == B else None
        assert _vertical_scale(surface_layers.layers_by_feature()[rec.feature_id]) == expect
    assert len(poses) == 2 and poses[1][0].x() > 15.0  # framed on grid B
    assert iface.dialogs3d[VIEW_NAME].windowTitle() == view_title(B, 3.0, 0)
    s3d.dock_state.scope = "site"
    s3d.dock_state.grid = A
    s3d.refresh()
    assert s3d.grid_id == B and len(poses) == 2


def test_a_stale_surface_is_counted_in_the_title(scene):
    s3d, session, surfaces, surface_layers, iface, _ = scene
    s3d.open()
    (record,) = [r for r in surfaces.records() if r.grid_id == A]
    surfaces.set_settings(record.feature_id, SurfaceSettings(strength=0.0, window_m=0.03))
    s3d.refresh()
    title = iface.dialogs3d[VIEW_NAME].windowTitle()
    assert title == view_title(A, 3.0, 1) and title.endswith("1 surface stale")


def test_an_empty_grid_opens_an_empty_scene_with_its_title(scene):
    s3d, session, surfaces, surface_layers, iface, _ = scene
    session.add_grid(Grid("Grid C", (40.0, 0.0), 0.0, 3.0, 12.0, "EPSG:32616", 0.5))
    s3d.dock_state.grid = "Grid C"
    s3d.open()
    assert s3d.grid_id == "Grid C" and list(s3d.picks_layer.getFeatures()) == []
    assert iface.dialogs3d[VIEW_NAME].windowTitle() == view_title("Grid C", 3.0, 0)
    assert len(iface.canvases3d[VIEW_NAME].cameraController().poses) == 1


def test_a_picks_layer_removed_by_hand_comes_back(scene):
    s3d, session, surfaces, surface_layers, iface, _ = scene
    s3d.open()
    first = s3d.picks_layer.id()
    # let open()'s own 0 ms layer re-set fire first, or it would also serve the refresh below
    settings = iface.canvases3d[VIEW_NAME].mapSettings()
    assert spin_until(lambda: not s3d._layers_timer.isActive())
    # a handler connected after the fake's own copy empties the view's layers as the picks
    # layer is added, standing in for QGIS's same-tick miss
    miss = lambda *_: settings.setLayers([])  # noqa: E731
    QgsProject.instance().layersAdded.connect(miss)
    QgsProject.instance().removeMapLayer(first)
    s3d.refresh()  # the picks layer is recreated here, and the view's layers re-set on a turn
    QgsProject.instance().layersAdded.disconnect(miss)
    assert s3d.picks_layer is not None and s3d.picks_layer.id() != first
    assert QgsProject.instance().mapLayer(s3d.picks_layer.id()) is not None
    assert len(list(s3d.picks_layer.getFeatures())) == 4
    assert s3d.picks_layer.id() not in [lyr.id() for lyr in settings.layers()]
    assert spin_until(lambda: s3d.picks_layer.id() in [lyr.id() for lyr in settings.layers()])


def test_a_cleared_project_forgets_the_scene_layers(scene):
    s3d, session, surfaces, surface_layers, iface, _ = scene
    s3d.open()
    QgsProject.instance().clear()
    assert s3d.picks_layer is None
    s3d.close()
    s3d.open()
    assert s3d.is_open() and s3d.picks_layer is not None


def _no_scene_layers_left(s3d, surface_layers):
    assert s3d.picks_layer is None
    assert not any(
        lyr.name() == "Picks at depth (3D view)"
        for lyr in QgsProject.instance().mapLayers().values()
    )
    assert all(lyr.renderer3D() is None for lyr in surface_layers.layers_by_feature().values())


def test_a_leftover_view_of_the_same_name_is_closed_and_a_fresh_one_opens(scene):
    s3d, session, surfaces, surface_layers, iface, _ = scene
    old = iface.createNewMapCanvas3D(VIEW_NAME)  # as a view restored with a saved project
    assert old is not None
    s3d.open()
    assert s3d.is_open() and iface.created3d == 2
    assert iface.canvases3d[VIEW_NAME] is not old
    assert iface.dialogs3d[VIEW_NAME].windowTitle() == view_title(A, 3.0, 0)


def test_a_refused_view_raises_and_leaves_nothing_behind(scene):
    s3d, session, surfaces, surface_layers, iface, _ = scene
    iface.refuse3d = True
    with pytest.raises(RuntimeError, match="3-D view"):
        s3d.open()
    assert not s3d.is_open() and s3d.grid_id is None
    _no_scene_layers_left(s3d, surface_layers)
    iface.refuse3d = False
    s3d.open()  # a later open works
    assert s3d.is_open()


def test_a_docked_view_is_retitled_and_a_swapped_holder_still_is(scene):
    from qgis.PyQt.QtWidgets import QDockWidget

    s3d, session, surfaces, surface_layers, iface, _ = scene
    iface.dock3d = True
    s3d.open()
    holder = iface.dialogs3d[VIEW_NAME]
    assert isinstance(holder, QDockWidget)
    assert holder.windowTitle() == view_title(A, 3.0, 0)
    before = holder.raised
    s3d.open()
    assert holder.raised == before + 1
    # undock: QGIS builds a new holder carrying the current title
    iface.swap_holder3d(VIEW_NAME)
    assert not isinstance(iface.dialogs3d[VIEW_NAME], QDockWidget)
    session.remember_volume(A, stretch=2.0)
    s3d.refresh()
    assert iface.dialogs3d[VIEW_NAME].windowTitle() == view_title(A, 2.0, 0)


# ---- Task 3: the plugin's 3D view button ----------------------------------------------------


def _scene_layers_in_project():
    return [
        lyr for lyr in QgsProject.instance().mapLayers().values() if "Picks at depth" in lyr.name()
    ]


def test_the_3d_view_button_opens_the_scene_of_the_slices_panels_grid(surface_plugin):
    plugin = surface_plugin
    assert plugin.act_view3d.text() == "3D view"
    assert plugin.act_view3d.toolTip() == BUTTON_TIP
    plugin.act_view3d.trigger()
    assert plugin.scene3d.is_open()
    assert plugin.scene3d.grid_id == plugin.slices_dock.grid_combo.currentText() == GRID.id
    assert VIEW_NAME in plugin.iface.canvases3d


def test_a_scope_change_reaches_the_scene(surface_plugin):
    plugin = surface_plugin
    seen = []
    plugin.slices_dock.scope_changed.connect(seen.append)
    plugin.slices_dock.set_scope("site")
    assert seen == ["site"]
    plugin.slices_dock.set_scope("site")
    assert seen == ["site"]
    plugin.slices_dock.set_scope("grid")
    assert seen == ["site", "grid"]


def test_open_with_no_grid_warns_in_the_message_bar_and_does_not_raise(surface_plugin):
    plugin = surface_plugin
    plugin.slices_dock.grid_combo.clear()
    messages = []
    plugin.message = lambda text, level=None, *a, **k: messages.append(text)
    plugin.open_view3d()
    assert messages == [NO_GRID] and not plugin.scene3d.is_open()


def test_a_refused_view_warns_in_the_message_bar(surface_plugin):
    plugin = surface_plugin
    plugin.iface.refuse3d = True
    messages = []
    plugin.message = lambda text, level=None, *a, **k: messages.append(text)
    plugin.open_view3d()
    assert messages == [VIEW_REFUSED] and not plugin.scene3d.is_open()


def test_closing_the_site_closes_the_view(surface_plugin):
    plugin = surface_plugin
    plugin.open_view3d()
    assert plugin.scene3d.is_open() and _scene_layers_in_project()
    plugin.session.close_site()
    assert not plugin.scene3d.is_open()
    assert not _scene_layers_in_project()
    assert all(
        lyr.renderer3D() is None
        for lyr in QgsProject.instance().mapLayers().values()
        if hasattr(lyr, "renderer3D")
    )


def test_a_failing_close_does_not_escape_the_site_closed_slot(surface_plugin):
    plugin = surface_plugin

    def boom():
        raise RuntimeError("boom")

    real = plugin.scene3d.close
    plugin.scene3d.close = boom
    try:
        plugin._close_view3d()  # logs, never raises
    finally:
        plugin.scene3d.close = real


def test_unload_closes_the_view(surface_plugin):
    plugin = surface_plugin
    plugin.open_view3d()
    iface = plugin.iface
    plugin.unload()
    assert VIEW_NAME not in iface.canvases3d
    assert not _scene_layers_in_project()
    assert plugin.scene3d is None
