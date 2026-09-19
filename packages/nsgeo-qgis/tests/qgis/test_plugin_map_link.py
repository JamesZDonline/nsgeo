"""MapLink: the map <-> profile link (M7, spec §3)."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.map_link import MapLink
from nsgeo_qgis.session import SiteSession
from plugin_testing import synthetic_dzt
from qgis.core import QgsPointXY, QgsProject
from qgis.gui import QgsMapCanvas

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def linked(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 2.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(layers.crs())
    link = MapLink(session, layers, canvas)
    keys = session.keys()
    session.open_line(keys[0])
    yield link, session, layers, canvas, keys
    link.dispose()
    layers.detach()
    project.clear()


def _vertex(link, key, i):
    return QgsPointXY(link._geometries()[key].vertexAt(i))


def test_the_marker_sits_on_the_traces_own_vertex(linked):
    link, session, _layers, _canvas, keys = linked

    session.set_trace(keys[0], 10)

    want = _vertex(link, keys[0], 10)
    assert link._marker.isVisible()
    assert link._marker.center().distance(want) < 1e-6


def test_the_band_spans_the_selected_traces(linked):
    link, session, _layers, _canvas, keys = linked

    session.set_selection(keys[0], 4, 9)

    assert link._band.numberOfVertices() == 6  # 4..9 inclusive


def test_clearing_the_selection_empties_the_band(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_selection(keys[0], 4, 9)

    session.clear_selection()

    assert link._band.numberOfVertices() == 0


def test_the_marker_follows_the_preview_not_the_working_line(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_trace(keys[0], 10)

    session.set_preview(keys[1], 3)

    want = _vertex(link, keys[1], 3)
    assert link._marker.center().distance(want) < 1e-6


def test_hovering_the_working_line_keeps_its_own_selection_band(linked):
    """`preview_key == current_key` is reachable and emits, and it means
    the pointer is over the line already being worked on -- not a preview.
    Testing `preview_key is not None` alone blanks that line's own band."""
    link, session, _layers, _canvas, keys = linked
    session.set_selection(keys[0], 4, 9)

    session.set_preview(keys[0], 3)

    assert link._band.numberOfVertices() == 6
    assert link._marker.isVisible()


def test_a_preview_shows_no_selection_band(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_selection(keys[0], 4, 9)

    session.set_preview(keys[1], 3)

    assert link._band.numberOfVertices() == 0


def test_snapping_back_restores_the_working_lines_marker_and_band(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_trace(keys[0], 10)
    session.set_selection(keys[0], 4, 9)

    session.set_preview(keys[1], 3)
    session.clear_preview()

    assert link._marker.center().distance(_vertex(link, keys[0], 10)) < 1e-6
    assert link._band.numberOfVertices() == 6


def test_closing_the_site_hides_both_items(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_trace(keys[0], 10)
    session.set_selection(keys[0], 4, 9)

    session.close_site()

    assert not link._marker.isVisible()
    assert link._band.numberOfVertices() == 0


def test_dispose_takes_both_items_off_the_scene_and_is_idempotent(qgis_app, tmp_path):
    """I4's lesson: a QgsMapCanvasItem is owned by the canvas SCENE, and
    nothing removes it when the Python wrapper goes away."""
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    canvas = QgsMapCanvas()
    before = len(canvas.scene().items())

    link = MapLink(session, layers, canvas)
    assert len(canvas.scene().items()) == before + 2

    link.dispose()
    assert len(canvas.scene().items()) == before

    link.dispose()  # must not raise
    assert len(canvas.scene().items()) == before
    layers.detach()
    project.clear()


def test_the_geometry_cache_is_rebuilt_after_the_lines_change(linked):
    link, session, _layers, _canvas, keys = linked
    first = link._geometries()  # populate
    assert link._geoms is not None

    session.remove_line(keys[1])

    # `lines_changed` invalidates the cache, and because keys[0] is still
    # the open line `_refresh()` immediately rebuilds it (to redraw that
    # line's own marker) within the same slot call -- so by the time this
    # returns `_geoms` is a NEW dict, not the old one merely edited in
    # place, and the removed line is gone from it.
    assert link._geoms is not None
    assert link._geoms is not first
    assert keys[1] not in link._geometries()


def test_geometries_are_transformed_into_canvas_crs(linked):
    """Hit testing (Task 4) measures its tolerance in canvas units, so the
    cache must already be transformed -- not left in the layer's CRS.

    Asserting against a DIFFERENT canvas CRS is the only version of this
    test that can fail: with the canvas on the layer's own CRS the
    transform is a no-op and an untransformed cache looks identical.

    No manual `link._invalidate()` here: the whole point is to exercise
    `canvas.destinationCrsChanged` -> `_on_lines_changed` -> `_invalidate`,
    the one connection nothing else in this suite reaches (a rewrite in
    Task 4/5 that drops that `connect()` call must fail here)."""
    from qgis.core import QgsCoordinateReferenceSystem

    link, _session, layers, canvas, keys = linked
    in_layer_crs = QgsPointXY(link._geometries()[keys[0]].vertexAt(0))

    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    in_wgs84 = QgsPointXY(link._geometries()[keys[0]].vertexAt(0))

    assert abs(in_wgs84.x()) <= 180.0 and abs(in_wgs84.y()) <= 90.0
    assert in_wgs84.distance(in_layer_crs) > 1.0


def test_a_canvas_crs_unreachable_from_the_layer_produces_no_untransformed_geometry(
    linked, message_log
):
    """`QgsCoordinateTransform.transform()` does not raise when PROJ has no
    path between two CRSs -- it reports success and leaves the geometry
    untouched, which would otherwise relabel raw layer-CRS coordinates as
    canvas-CRS ones with nothing downstream able to tell.

    A projected Earth CRS (the grid's own EPSG:32616) against a
    geographic Mars CRS is a genuinely invalid transform on this build
    (`QgsCoordinateTransform(...).isValid()` is False) -- the same pairing
    `SiteLayers._require_transform`'s docstring uses -- so this is a real
    failure, not a stubbed one."""
    from qgis.core import QgsCoordinateReferenceSystem

    link, session, _layers, canvas, keys = linked
    session.set_trace(keys[0], 10)
    session.set_selection(keys[0], 4, 9)
    assert link._marker.isVisible()

    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("ESRI:104905"))  # GCS_Mars_2000

    assert not link._marker.isVisible()
    assert link._band.numberOfVertices() == 0
    assert link._geometries() == {}
    assert any("no coordinate transform" in m for m in message_log)
