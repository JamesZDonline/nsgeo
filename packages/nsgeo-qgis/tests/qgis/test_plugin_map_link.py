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
from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject
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


# ---- the pointer leaving the canvas (M7 final review, Finding 1) -----------


def test_the_pointer_leaving_the_canvas_clears_an_active_preview(linked):
    """Before this fix, nothing handled the pointer leaving the canvas: a
    preview started near the edge and then carried onto another dock left
    the profile stuck showing it. Experiment (see the fix report) found
    that a QgsMapCanvas's Leave event lands on BOTH the canvas widget and
    `canvas.viewport()` -- `MapLink` installs its filter on the viewport,
    since that is the object whose own mouse tracking backs
    `xyCoordinates`, so this sends the event there."""
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)
    assert session.preview_key == keys[1]

    QCoreApplication.sendEvent(canvas.viewport(), QEvent(QEvent.Type.Leave))

    assert session.preview_key is None


def test_the_pointer_leaving_the_canvas_stops_the_pending_dwell(linked):
    """The filter must also stop the dwell, not just clear the preview: a
    dwell already queued when the pointer left would otherwise fire right
    after and silently re-establish the very preview the leave just
    cleared."""
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    assert link._dwell.isActive()

    QCoreApplication.sendEvent(canvas.viewport(), QEvent(QEvent.Type.Leave))

    assert not link._dwell.isActive()
    link._dwell.timeout.emit()  # a timeout already queued when the leave fired
    assert session.preview_key is None


def test_leaving_the_canvas_with_no_preview_up_is_a_silent_no_op(linked):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    link, session, _layers, canvas, keys = linked
    assert session.preview_key is None

    QCoreApplication.sendEvent(canvas.viewport(), QEvent(QEvent.Type.Leave))  # must not raise

    assert session.preview_key is None


def test_a_disposed_link_no_longer_clears_the_preview_on_leave(linked):
    """dispose() removes the Leave filter (guarded exactly like the
    existing canvas disconnect there) so a disposed link cannot go on
    calling `session.clear_preview()` after teardown."""
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)
    assert session.preview_key == keys[1]

    link.dispose()
    QCoreApplication.sendEvent(canvas.viewport(), QEvent(QEvent.Type.Leave))

    assert session.preview_key == keys[1]  # unchanged: the filter is gone


def test_a_disposed_link_still_removes_the_leave_filter_when_the_canvas_is_gone(linked):
    """Same shape as test_dispose_still_removes_the_items_when_the_canvas_is_gone:
    dispose() must not abort before the scene-removal loop just because it
    cannot reach the canvas to remove the Leave filter either."""
    link, _session, _layers, canvas, _keys = linked
    before = len(canvas.scene().items()) - 2  # the two this link added

    class _Dead:
        def __getattr__(self, name):
            raise RuntimeError("wrapped C/C++ object has been deleted")

    link.canvas = _Dead()
    link.dispose()  # must not raise, and must still remove the marker/band

    assert len(canvas.scene().items()) == before
    assert link._marker is None
    assert link._band is None


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


# ---- moving along the displayed line (walkthrough Tweak 1) -----------------


def test_moving_along_the_working_line_updates_the_cursor_without_the_dwell(linked):
    """The author's walkthrough: 'the cursor jumps a long way as you move
    unless you move really slowly'. The dwell exists to stop a sweep
    across the map loading line after line (spec §3.5) -- moving along a
    line already on screen costs nothing and must not wait for it. No
    `_fire_dwell()` call here on purpose: this is the whole point."""
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[0]].vertexAt(11))

    canvas.xyCoordinates.emit(target)

    assert session.current_trace == 11
    assert session.current_key == keys[0]


def test_moving_along_a_previewed_line_updates_the_preview_without_the_dwell(linked):
    """The other half of `_track_displayed_line`: the DISPLAYED line is the
    preview, not the working line, whenever one is up, and moving further
    along it must be just as immediate."""
    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)
    assert session.preview_key == keys[1] and session.preview_trace == 7

    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(20)))

    assert session.preview_trace == 20  # updated immediately, no _fire_dwell() call
    assert session.current_key == keys[0]  # still not promoted


def test_moving_onto_a_different_line_still_waits_for_the_dwell(linked):
    """Only switching to a DIFFERENT line still pays the dwell -- that is
    what the dwell is for, and this fix must not remove it."""
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[1]].vertexAt(7))

    canvas.xyCoordinates.emit(target)

    assert session.preview_key is None  # not yet -- the timer has not fired
    assert link._dwell.isActive()


def test_moving_off_every_line_still_only_clears_the_preview_on_the_dwell(linked):
    """Leaving the dwell running is deliberate: moving OFF the displayed
    line must still clear the preview on the dwell, not immediately, so
    crossing a gap between two lines does not flicker the profile back to
    the working line and out again."""
    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)
    assert session.preview_key == keys[1]

    canvas.xyCoordinates.emit(QgsPointXY(999_999.0, 999_999.0))

    assert session.preview_key == keys[1]  # unchanged until the dwell fires
    _fire_dwell(link)
    assert session.preview_key is None


def _shrink_tolerance(canvas: QgsMapCanvas) -> None:
    """Set `canvas` to a small, known extent so 12 SCREEN pixels (the
    hover tolerance) corresponds to a small MAP-unit distance.

    Finding 3 (M7 walkthrough re-review): `mapUnitsPerPixel()` defaults to
    1.0 on a bare, unresized `QgsMapCanvas()` (verified directly), giving
    a 12.0-unit tolerance -- six times the `linked` fixture's own 2.0-unit
    inter-line spacing. Nothing built on that fixture's geometry alone can
    ever fall outside tolerance, so a test that deletes
    `_track_displayed_line`'s tolerance check entirely, or compares an
    unsquared distance against it, still passed: verified by deliberately
    breaking the check both ways and rerunning this file, twice, before
    this fix. Shrinking the tolerance (not the geometry) is what actually
    separates "close enough to hit" from "genuinely too far", at
    0.01 x 12 = 0.12 map units -- well under the fixture's own spacing.
    """
    from qgis.core import QgsRectangle

    canvas.resize(400, 400)
    canvas.setExtent(QgsRectangle(0.0, 0.0, 4.0, 4.0))  # mapUnitsPerPixel() == 0.01


def test_the_tolerance_check_rejects_a_hover_on_a_genuinely_different_line(linked):
    """Finding 3 (M7 walkthrough re-review): under the DEFAULT tolerance,
    hovering exactly on line 1's own vertex 7 also counts as hovering line
    0 (the displayed line) -- the two are only 2.0 map units apart, well
    inside the default 12.0-unit tolerance -- so `_track_displayed_line`
    silently moved line 0's cursor to whatever vertex on IT is nearest,
    before the dwell ever ran. `test_moving_onto_a_different_line_still_
    waits_for_the_dwell` above never noticed, because it only checks
    `preview_key`/the dwell, never `current_trace`.

    `_shrink_tolerance` makes the same kind of assertion meaningful: with
    the pointer genuinely out of tolerance, the working line's own trace
    must not move at all, and only the dwell may still decide whether to
    preview the other line. Verified by mutation: deleting
    `_track_displayed_line`'s `if index < 0 or sq_dist > tolerance *
    tolerance: return` guard entirely makes this fail (`current_trace`
    changes to line 0's own nearest vertex regardless of distance).
    """
    link, session, _layers, canvas, keys = linked
    session.set_trace(keys[0], 3)
    _shrink_tolerance(canvas)
    target = QgsPointXY(link._geometries()[keys[1]].vertexAt(7))

    canvas.xyCoordinates.emit(target)

    assert session.current_trace == 3  # unchanged -- genuinely out of tolerance now
    assert session.preview_key is None  # not yet -- the timer has not fired
    assert link._dwell.isActive()


def test_track_displayed_line_tolerance_is_a_distance_not_a_squared_distance(linked):
    """The same hazard `_hit_test`'s own
    `test_the_tolerance_is_a_distance_not_a_squared_distance` guards
    against, for `_track_displayed_line`'s own SEPARATE tolerance check
    (map_link.py, inside `_track_displayed_line`) -- `closestVertexWithContext`
    returns a squared distance, so the tolerance must be squared to match
    it, and a miss test cannot tell a correct comparison from a backwards
    one (see that other test's docstring for why: with the default
    mapUnitsPerPixel() of 1.0, tol=12 > sqrt(tol)=3.46, so comparing the
    squared distance against a raw, unsquared tolerance is *stricter*
    than correct, not looser -- a hit inside the real tolerance but
    outside its square root is the only probe that separates them.

    Verified by mutation: changing this check's `tolerance * tolerance`
    to a bare `tolerance` makes this fail (the perturbed point is then
    treated as a miss, and `current_trace` stays at the sentinel).
    """
    link, session, _layers, canvas, keys = linked
    session.set_trace(keys[0], 3)
    tol = canvas.mapUnitsPerPixel() * link.HOVER_TOLERANCE_PX
    assert tol > 1.0, "the discriminating band exists only while tol > sqrt(tol)"
    on = link._geometries()[keys[0]].vertexAt(11)
    near = QgsPointXY(on.x() + tol * 0.8, on.y())

    canvas.xyCoordinates.emit(near)

    assert session.current_trace != 3  # a real hit under the correct (squared) comparison


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


# ---- selecting a pick or a mark jumps to it (M8, spec §3.4, §4.4) ----------


MARK_DZX = """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="www.geophysical.com/DZX/1.02"><File><name>FILE__003.DZT</name>
<Profile><WayPt><scan>27</scan><mark>User</mark><name>Mark1</name></WayPt></Profile></File></DZX>"""


def _feature_with(layers, name, field, value):
    """The id of the one feature in `name` whose `field` equals `value`."""
    ids = [f.id() for f in layers.layers[name].getFeatures() if f[field] == value]
    assert len(ids) == 1, f"expected exactly one {name} with {field}={value!r}, got {len(ids)}"
    return ids[0]


def _add_a_marked_line(session, tmp_path):
    """A third line carrying a DZX mark at scan 27. `add_lines` emits
    lines_changed, which refills `marks` -- the `linked` fixture's own
    two lines have no sidecar, so without this the marks table is
    empty. Returns (key, scan)."""
    p = synthetic_dzt(tmp_path / "raw", "FILE__003.DZT", n_traces=60)
    (tmp_path / "raw" / "FILE__003.DZX").write_text(MARK_DZX)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 4.0, 0.0, 1, p.stem))])
    return "raw/FILE__003.DZT", 27


def test_selecting_a_pick_opens_its_line_and_moves_the_trace(linked):
    """Spec §3.4's closing promise: "the same mechanism serves picks
    later: selecting a pick feature jumps to its line and trace." One
    gesture, QGIS's own Select tool, no map tool of ours."""
    link, session, layers, canvas, keys = linked
    session.open_line(keys[1])
    session.add_pick(keys[1], 33, 21.0)
    session.open_line(keys[0])
    assert session.current_key == keys[0]

    layers.layers["picks"].selectByIds([_feature_with(layers, "picks", "trace", 33)])

    assert session.current_key == keys[1]
    assert session.current_trace == 33


def test_selecting_a_mark_opens_its_line_and_moves_the_trace(linked, tmp_path):
    """Spec §4.4: `marks` stays derived and read-only, but a mark has to
    be navigable or it is decoration."""
    link, session, layers, canvas, keys = linked
    marked_key, scan = _add_a_marked_line(session, tmp_path)
    assert layers.feature_count("marks") == 1
    session.open_line(keys[0])

    layers.layers["marks"].selectByIds([_feature_with(layers, "marks", "scan", scan)])

    assert session.current_key == marked_key
    assert session.current_trace == scan


def test_the_marks_layer_stays_read_only(linked, tmp_path):
    """§4.4: M8 confirms marks render and are read-only; it does not make
    them editable. `marks` is derived from the DZX and refilled on every
    grid or line change, so an edit would be silently discarded."""
    link, session, layers, canvas, keys = linked
    _add_a_marked_line(session, tmp_path)
    assert layers.feature_count("marks") == 1  # it renders
    assert layers.layers["marks"].readOnly() is True
    assert layers.layers["picks"].readOnly() is False


def test_selecting_several_picks_at_once_jumps_nowhere(linked):
    """Same rule as a multi-selection of lines (spec §3.4): there is no
    single answer and guessing one is worse than doing nothing."""
    link, session, layers, canvas, keys = linked
    session.open_line(keys[1])
    session.add_pick(keys[1], 10, 12.0)
    session.add_pick(keys[1], 40, 25.0)
    session.open_line(keys[0])

    layers.layers["picks"].selectByIds(
        [
            _feature_with(layers, "picks", "trace", 10),
            _feature_with(layers, "picks", "trace", 40),
        ]
    )

    assert session.current_key == keys[0]


def test_a_pick_with_no_trace_jumps_to_the_line_and_stops_there(linked):
    """The picks layer is editable, so a hand-digitised row can carry a
    line_key and nothing else. Opening the line is still the right
    answer; `int(NULL)` inside this slot would abort the CI container."""
    link, session, layers, canvas, keys = linked
    layer = layers.layers["picks"]
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = keys[1]
    assert layer.dataProvider().addFeatures([f])[0]
    session.open_line(keys[0])

    layer.selectByIds([_feature_with(layers, "picks", "line_key", keys[1])])

    assert session.current_key == keys[1]
    assert session.current_trace == -1


def test_a_disposed_link_stops_jumping_from_picks_and_marks(linked, tmp_path):
    """M7 Finding I1: `_on_lines_changed` re-armed a disposed link by
    calling `_rebind_layer` again. Three layers now, so the same failure
    has three ways to happen."""
    link, session, layers, canvas, keys = linked
    marked_key, scan = _add_a_marked_line(session, tmp_path)
    session.open_line(keys[1])
    session.add_pick(keys[1], 33, 21.0)
    session.open_line(keys[0])
    link.dispose()

    layers.layers["picks"].selectByIds([_feature_with(layers, "picks", "trace", 33)])
    assert session.current_key == keys[0]
    layers.layers["marks"].selectByIds([_feature_with(layers, "marks", "scan", scan)])
    assert session.current_key == keys[0]


def test_a_disposed_link_stays_disposed_when_the_layers_are_rebuilt(linked):
    """The disposal sentinel in `_on_lines_changed` covers all three
    bindings, not only `lines`."""
    link, session, layers, canvas, keys = linked
    session.open_line(keys[1])
    session.add_pick(keys[1], 33, 21.0)
    session.open_line(keys[0])
    link.dispose()

    session.lines_changed.emit()
    layers.layers["picks"].selectByIds([_feature_with(layers, "picks", "trace", 33)])

    assert session.current_key == keys[0]


def test_jumping_from_a_pick_still_works_after_the_site_is_reopened(linked):
    """A site reopen replaces every layer object (`detach()` empties the
    registry, `ensure_tables()` builds new ones), so a connection made
    once at construction would point at three dead wrappers and jumping
    would stop with no error at all -- the worst kind of stop. `lines`
    already has this test; picks need their own binding proved too."""
    link, session, layers, canvas, keys = linked
    session.open_line(keys[1])
    session.add_pick(keys[1], 33, 21.0)
    session.save()
    path = session.json_path

    session.close_site()
    session.open_site(path)
    keys = session.keys()
    session.open_line(keys[0])

    layers.layers["picks"].selectByIds([_feature_with(layers, "picks", "trace", 33)])

    assert session.current_key == keys[1]
    assert session.current_trace == 33


@needs_real_data
def test_selecting_a_real_files_mark_jumps_to_its_own_scan(qgis_app, tmp_path):
    """Spec §7: real data is the primary validation. The DZX above is a
    three-line fixture; a real GSSI sidecar carries its own scan numbers
    against its own trace count, and `refill_marks` clamps a scan into
    that count. Only a real pair proves the scan a mark reports is the
    trace the profile lands on.
    """
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    marked = [p for p in REAL_DZT if p.with_suffix(".DZX").exists()]
    if not marked:
        pytest.skip("no real DZT has a DZX sidecar")
    lines = [
        Line.open(p, GridPlacement("A", "y", i * 2.0, 0.0, 1, p.stem))
        for i, p in enumerate(marked[:2])
    ]
    session.add_lines(lines)
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(layers.crs())
    link = MapLink(session, layers, canvas)
    keys = session.keys()
    session.open_line(keys[0])
    marks = list(layers.layers["marks"].getFeatures())
    if not marks:
        pytest.skip("the real DZX sidecars carry no marks")
    feat = next((f for f in marks if str(f["line_key"]) != keys[0]), marks[0])
    want_key, want_scan = str(feat["line_key"]), int(feat["scan"])

    layers.layers["marks"].selectByIds([feat.id()])

    assert session.current_key == want_key
    assert session.current_trace == want_scan
    link.dispose()
    layers.detach()
    project.clear()
