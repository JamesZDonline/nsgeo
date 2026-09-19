"""MapLink: the map <-> profile link (M7, spec §3)."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.map_link import MapLink
from nsgeo_qgis.session import SiteSession
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
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


# ---- ambient hover (spec §3.2) ----------------------------------------------


def _fire_dwell(link):
    """Drive the dwell timer deterministically instead of waiting on it."""
    link._dwell.timeout.emit()


def test_hovering_a_line_previews_it_at_the_hovered_trace(linked):
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[1]].vertexAt(7))

    canvas.xyCoordinates.emit(target)
    _fire_dwell(link)

    assert session.preview_key == keys[1]
    assert session.preview_trace == 7


def test_hover_never_moves_the_working_line(linked):
    """The headline guard of the whole design (spec §3.3)."""
    link, session, _layers, canvas, keys = linked
    opened = []
    session.line_opened.connect(opened.append)
    target = QgsPointXY(link._geometries()[keys[1]].vertexAt(7))

    canvas.xyCoordinates.emit(target)
    _fire_dwell(link)

    assert session.current_key == keys[0]
    assert opened == []


def test_hovering_the_working_line_moves_its_cursor_not_a_preview(linked):
    """Ruling 12: the working line's cursor IS `current_trace`. Routing a
    hover over it through `set_preview` would give one line two sources of
    truth for one cursor, and the map marker would stop following a drag
    in the profile."""
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[0]].vertexAt(11))

    canvas.xyCoordinates.emit(target)
    _fire_dwell(link)

    assert session.preview_key is None
    assert session.current_trace == 11
    assert session.current_key == keys[0]


def test_hovering_the_working_line_ends_a_preview_of_another(linked):
    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)
    assert session.preview_key == keys[1]

    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[0]].vertexAt(11)))
    _fire_dwell(link)

    assert session.preview_key is None
    assert session.current_trace == 11


def test_hovering_away_from_every_line_clears_the_preview(linked):
    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)
    assert session.preview_key == keys[1]

    canvas.xyCoordinates.emit(QgsPointXY(999_999.0, 999_999.0))
    _fire_dwell(link)

    assert session.preview_key is None


def test_the_preview_waits_for_the_dwell(linked):
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[1]].vertexAt(7))

    canvas.xyCoordinates.emit(target)

    assert session.preview_key is None  # not yet -- the timer has not fired
    assert link._dwell.isActive()


def test_only_the_last_position_of_a_sweep_is_used(linked):
    link, session, _layers, canvas, keys = linked

    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[0]].vertexAt(2)))
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)

    assert session.preview_key == keys[1]
    assert session.preview_trace == 7


def test_the_dwell_timer_really_fires_on_its_own(linked):
    """The other hover tests drive the timer by hand; this one proves the
    timer is actually started and connected."""
    from qgis.PyQt.QtTest import QTest

    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))

    QTest.qWait(link.HOVER_DWELL_MS * 4)

    assert session.preview_key == keys[1]


def test_the_tolerance_is_a_distance_not_a_squared_distance(linked):
    """closestVertexWithContext returns a SQUARED distance, so the tolerance
    must be squared to match it.

    The discriminating probe is a HIT, not a miss. With mapUnitsPerPixel()
    == 1.0 the tolerance is 12 map units and 12 > sqrt(12), so comparing
    the squared distance against a RAW tolerance is *stricter* than
    correct, not looser: it rejects past 3.46 m where the correct
    comparison rejects past 12 m. A miss test therefore passes under both
    spellings and proves nothing. Hovering inside the real tolerance but
    outside sqrt(tolerance) separates them."""
    link, session, _layers, canvas, keys = linked
    tol = canvas.mapUnitsPerPixel() * link.HOVER_TOLERANCE_PX
    assert tol > 1.0, "the discriminating band exists only while tol > sqrt(tol)"
    on = link._geometries()[keys[1]].vertexAt(7)
    near = QgsPointXY(on.x() + tol * 0.8, on.y())

    canvas.xyCoordinates.emit(near)
    _fire_dwell(link)

    assert session.preview_key is not None


def test_a_disposed_link_stops_tracking_the_pointer(linked):
    """dispose() must stop the link writing to a session the plugin has
    finished with -- the same class of leak as the canvas items.

    The target vertex is captured before dispose(): `_geometries()` is
    unusable afterwards (its layer lookup goes through `self.layers`,
    which a disposed link is not guaranteed to still have working)."""
    link, session, _layers, canvas, keys = linked
    before = session.current_trace
    target = QgsPointXY(link._geometries()[keys[0]].vertexAt(11))

    link.dispose()
    canvas.xyCoordinates.emit(target)  # disconnected: must not restart the dwell
    link._dwell.timeout.emit()  # a queued timeout landing late: must not act either

    assert session.current_trace == before
    assert not link._dwell.isActive()


def test_a_disposed_link_ignores_a_dwell_that_was_already_queued(linked):
    """The guard's own case: dispose() stops the timer and disconnects, but
    an emission already in flight can still land. Distinct from
    test_a_disposed_link_stops_tracking_the_pointer above, which pins the
    disconnect -- with the disconnect in place `_last_point` is never set,
    so that test cannot pin this guard: an unguarded `_on_dwell` would
    still return early at its own `point is None` check, and the test
    would pass either way. Arming the dwell BEFORE dispose() (so
    `_last_point` is set and the timer running) and then firing the
    timeout manually reproduces the real case instead: a QTimer.timeout
    already queued on the Qt event loop when dispose() ran."""
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[0]].vertexAt(11))
    canvas.xyCoordinates.emit(target)  # arms the dwell and sets _last_point
    before = session.current_trace

    link.dispose()
    link._dwell.timeout.emit()  # the queued emission landing after teardown

    assert session.current_trace == before


def test_dispose_still_removes_the_items_when_the_canvas_is_gone(linked):
    """Item I4's lesson, again: dispose() must take the marker and band off
    the scene even when it cannot reach the canvas to disconnect from it.
    A real deleted QgsMapCanvas is awkward to construct safely while the
    marker/band still reference it, so this substitutes a stub whose every
    attribute access raises RuntimeError -- the same shape a genuinely
    deleted sip wrapper presents to anything that touches it."""
    link, _session, _layers, canvas, _keys = linked
    before = len(canvas.scene().items()) - 2  # the two this link added

    class _Dead:
        def __getattr__(self, name):
            raise RuntimeError("wrapped C/C++ object has been deleted")

    link.canvas = _Dead()
    link.dispose()

    assert len(canvas.scene().items()) == before
    assert link._marker is None
    assert link._band is None


def test_hover_with_no_site_open_does_nothing(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    layers = SiteLayers(session, project=project)
    canvas = QgsMapCanvas()
    link = MapLink(session, layers, canvas)

    canvas.xyCoordinates.emit(QgsPointXY(1.0, 2.0))
    link._dwell.timeout.emit()  # must not raise

    assert session.preview_key is None
    link.dispose()
    project.clear()


@needs_real_data
def test_hovering_a_real_line_previews_its_real_trace(qgis_app, tmp_path):
    """Spec §7: real data is the primary validation. The synthetic fixtures
    above all use one synthetic header; a real GSSI file has its own
    traces_per_metre and trace count, and those are what turn a pointer
    position into a trace index."""
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    line = Line.open(REAL_DZT[0], GridPlacement("A", "y", 0.0, 0.0, 1, "real"))
    session.add_lines([line])
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(layers.crs())
    link = MapLink(session, layers, canvas)
    key = session.keys()[0]
    session.open_line(key)

    want = line.n_traces // 3
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[key].vertexAt(want)))
    link._dwell.timeout.emit()

    # The working line is the only line, so the preview is a no-op on the
    # dock -- what is being asserted is that the hit test resolved a real
    # file's geometry to the right trace index.
    assert link._hit_test(QgsPointXY(link._geometries()[key].vertexAt(want))) == (key, want)
    assert session.current_key == key
    link.dispose()
    layers.detach()
    project.clear()


def test_a_previewed_line_is_requested_from_the_loader(linked, monkeypatch):
    from nsgeo_qgis.loader import LineLoader

    link, session, _layers, canvas, keys = linked
    asked: list[str] = []
    loader = LineLoader(session, on_error=lambda k, m: None)
    monkeypatch.setattr(loader, "request", asked.append)

    session.set_preview(keys[1], 7)

    assert asked == [keys[1]]


# ---- selection promotes (spec §3.4) -----------------------------------------


def _feature_id(layers, key):
    layer = layers.layers["lines"]
    for f in layer.getFeatures():
        if str(f["line_key"]) == key:
            return f.id()
    raise AssertionError(f"no feature for {key!r}")


def test_selecting_one_line_makes_it_the_working_line(linked):
    link, session, layers, _canvas, keys = linked
    assert session.current_key == keys[0]

    layers.layers["lines"].selectByIds([_feature_id(layers, keys[1])])

    assert session.current_key == keys[1]


def test_promotion_goes_through_open_line_so_it_cannot_diverge(linked):
    link, session, layers, _canvas, keys = linked
    opened = []
    session.line_opened.connect(opened.append)

    layers.layers["lines"].selectByIds([_feature_id(layers, keys[1])])

    assert opened == [keys[1]]


def test_selecting_several_lines_promotes_none(linked):
    link, session, layers, _canvas, keys = linked

    layers.layers["lines"].selectByIds([_feature_id(layers, keys[0]), _feature_id(layers, keys[1])])

    assert session.current_key == keys[0]


def test_deselecting_everything_promotes_nothing(linked):
    link, session, layers, _canvas, keys = linked
    layer = layers.layers["lines"]
    layer.selectByIds([_feature_id(layers, keys[1])])

    layer.removeSelection()

    assert session.current_key == keys[1]  # unchanged by the deselect


def test_promotion_still_works_after_the_lines_layer_is_rebuilt(linked):
    """A site reopen -- `SiteLayers.detach()` clearing its layer registry,
    then `refresh()` rebuilding it, the exact sequence `_on_site_opened`
    runs on every close/open pair -- replaces the `lines` layer object
    outright: `ensure_tables()` only reuses `self.layers[name]` when the
    name is already present, and `detach()` empties that dict first.

    A plain `refresh()` on its own (what this test used to call) cannot
    exercise this at all: it truncates and refills the *same* table in
    place, so the layer object never changes and a connection made once at
    construction stays valid regardless of whether `_rebind_layer` ever
    runs again -- the test passed for the wrong reason. Closing and
    reopening the site is the real replacement path, and it is also the
    only one of the two that fires the `site_closed`/`site_opened` signals
    `_on_lines_changed` actually listens for, so it exercises the fix in
    the same way production does."""
    link, session, layers, _canvas, keys = linked
    json_path = session.json_path
    session.save()  # add_grid/add_lines only staged the site in memory

    session.close_site()
    session.open_site(json_path)

    layers.layers["lines"].selectByIds([_feature_id(layers, keys[1])])

    assert session.current_key == keys[1]


def test_a_disposed_link_stops_promoting_on_selection(linked):
    link, session, layers, _canvas, keys = linked
    link.dispose()

    layers.layers["lines"].selectByIds([_feature_id(layers, keys[1])])

    assert session.current_key == keys[0]


def test_a_disposed_link_does_not_re_arm_itself_on_the_next_lines_signal(linked):
    """`_on_lines_changed` calls `_rebind_layer()`, which reconnects
    `selectionChanged` -- so without its own disposal sentinel, a
    lines/grids/site signal landing after dispose() would silently undo
    dispose()'s own unbind and let a disposed link start promoting again.
    Distinct from test_a_disposed_link_stops_promoting_on_selection above,
    which never exercises this: nothing there fires a signal between
    dispose() and the selection, so that test cannot tell a real unbind
    apart from one that was quietly reinstated."""
    link, session, layers, _canvas, keys = linked
    link.dispose()

    session.lines_changed.emit()
    layers.layers["lines"].selectByIds([_feature_id(layers, keys[1])])

    assert session.current_key == keys[0]
