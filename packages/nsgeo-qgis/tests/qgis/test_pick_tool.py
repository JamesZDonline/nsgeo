"""PickPointTool: one click on the map, snapped (#63, spec §3 C2, §4.7).

Every test here runs on a real, shown canvas: EPSG:32616 over (0, 0)-(800,
600) at 800 x 600 px, so one pixel is exactly one metre (`_real_canvas`
asserts it) and a distance in pixels reads directly as metres. On it:

- `gps`, a point layer with one feature, G4, at (400, 300);
- `plan`, a polygon layer whose nearest vertex to G4 is at (414, 300).

The snap radius is 12 px, so from G4 eastwards along y = 300:
(408) G4 8 px, vertex 6 px; (410) G4 10, vertex 4; (384) G4 16, vertex 30.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from nsgeo_qgis.maptools.pick_tool import SNAP_TOLERANCE_PX, PickPointTool
from plugin_testing import feature_id, map_pixel, named_layer, send_map_key, send_map_mouse
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsSnappingConfig,
)
from qgis.gui import QgsMapToolPan
from qgis.PyQt.QtCore import QEvent, QPointF, Qt
from qgis.PyQt.QtGui import QKeyEvent, QMouseEvent

UTM16 = QgsCoordinateReferenceSystem("EPSG:32616")
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
PLAN_RING = [(414, 300), (514, 300), (514, 400), (414, 400)]


@pytest.fixture
def scene(real_canvas):
    """The canvas and its two layers (kept referenced: the canvas holds
    layers weakly, so a layer nothing else holds would vanish from it)."""
    canvas = real_canvas(UTM16, QgsRectangle(0, 0, 800, 600))
    gps = named_layer("Point", "gps", {"G4": (400, 300)})
    plan = named_layer("Polygon", "plan", {"plot 7": PLAN_RING})
    canvas.setLayers([gps, plan])
    made: list[PickPointTool] = []

    def tool(mode: str = "point") -> PickPointTool:
        t = PickPointTool(canvas, mode)
        made.append(t)
        return t

    yield SimpleNamespace(canvas=canvas, gps=gps, plan=plan, tool=tool)
    for t in made:
        t.finish()
        if canvas.mapTool() is t:
            canvas.unsetMapTool(t)
        t.dispose()


def _click(tool: PickPointTool, x: float, y: float) -> list[tuple[QgsPointXY, str]]:
    got: list[tuple[QgsPointXY, str]] = []
    tool.picked.connect(lambda p, label: got.append((QgsPointXY(p), label)))
    send_map_mouse(tool, "release", (x, y))
    return got


def _xy(point: QgsPointXY) -> tuple[float, float]:
    return (point.x(), point.y())


def test_the_radius_is_twelve_pixels_whatever_the_zoom(scene):
    # C2: "the radius is 12 px on screen, whatever the zoom" -- and a
    # constant, so the walkthrough can tune it. (400, 312) is 12 px
    # straight above G4 and 18 px from the vertex: in. (400, 313) is 13 px
    # from G4 and 19 px from the vertex: out.
    assert SNAP_TOLERANCE_PX == 12
    tool = scene.tool()
    assert tool.snap(QgsPointXY(400, 312)) == (QgsPointXY(400, 300), "G4 · gps")
    assert tool.snap(QgsPointXY(400, 313)) == (QgsPointXY(400, 313), "free click")
    # Zoomed out to 10 m/px, 100 m is 10 px: still in range.
    scene.canvas.setExtent(QgsRectangle(0, 0, 8000, 6000))
    QgsApplication.processEvents()
    assert scene.canvas.mapUnitsPerPixel() == pytest.approx(10.0)
    assert tool.snap(QgsPointXY(400, 400)) == (QgsPointXY(400, 300), "G4 · gps")


def test_a_click_near_a_point_snaps_to_it(scene):
    got = _click(scene.tool(), 408, 300)
    assert [(_xy(p), label) for p, label in got] == [((400.0, 300.0), "G4 · gps")]


def test_a_click_beyond_the_radius_is_free(scene):
    # Ruling R4: (384, 300), not (416, 300) -- the latter is 2 px from the
    # polygon's vertex and would snap to it. Here G4 is 16 px away and the
    # vertex 30 px, so nothing is in range.
    got = _click(scene.tool(), 384, 300)
    assert [(_xy(p), label) for p, label in got] == [((384.0, 300.0), "free click")]


def test_a_point_wins_over_a_nearer_vertex(scene):
    # G4 is 10 px away, the vertex only 4 px: a GPS fix beats a drawn
    # polygon's corner whenever both are in range (C2).
    got = _click(scene.tool(), 410, 300)
    assert [(_xy(p), label) for p, label in got] == [((400.0, 300.0), "G4 · gps")]


def test_with_no_point_in_range_the_nearest_vertex_wins(scene):
    # The second pass. (420, 300): G4 20 px away (out), the vertex 6 px.
    got = _click(scene.tool(), 420, 300)
    assert [(_xy(p), label) for p, label in got] == [((414.0, 300.0), "plot 7 · plan")]


def test_a_layer_not_on_the_canvas_is_never_snapped_to(scene):
    # Review Focus #3: a pick never snaps to a feature the user cannot see.
    # The hidden layer is a project layer with H1 right under the click, so
    # it would win if it were considered -- shown first, to prove it.
    hidden = named_layer("Point", "hidden", {"H1": (405, 300)})
    QgsProject.instance().addMapLayer(hidden)
    try:
        tool = scene.tool()
        scene.canvas.setLayers([hidden, scene.gps, scene.plan])
        assert tool.snap(QgsPointXY(405, 300)) == (QgsPointXY(405, 300), "H1 · hidden")
        scene.canvas.setLayers([scene.gps, scene.plan])
        got = _click(tool, 405, 300)
        assert [(_xy(p), label) for p, label in got] == [((400.0, 300.0), "G4 · gps")]
    finally:
        QgsProject.instance().removeMapLayer(hidden.id())


def test_the_label_names_the_target_and_the_click_uses_it(scene):
    tool = scene.tool()
    assert tool.snap_label == ""
    send_map_mouse(tool, "move", (408, 300))
    assert tool.snap_label == "G4 · gps"
    # "The click uses the same match the indicator showed": take G4's layer
    # off the canvas, then release on the same pixel -- still G4.
    scene.canvas.setLayers([scene.plan])
    got = _click(tool, 408, 300)
    assert [(_xy(p), label) for p, label in got] == [((400.0, 300.0), "G4 · gps")]
    # A release on another pixel snaps afresh: G4 is gone, the vertex wins.
    got = _click(tool, 409, 300)
    assert [(_xy(p), label) for p, label in got] == [((414.0, 300.0), "plot 7 · plan")]
    # Off every target, the label empties.
    send_map_mouse(tool, "move", (100, 100))
    assert tool.snap_label == ""


def test_a_click_after_the_view_moved_snaps_afresh(scene):
    # The last move's match is reused only while the pixel still shows the
    # same place: an arrow-key pan (or a CRS change) between the move and
    # the click leaves the cursor on the same pixel over different ground,
    # and reusing the match would pick a point nowhere near the click --
    # in the CRS case, in the wrong CRS.
    tool = scene.tool()
    pixel = map_pixel(scene.canvas, 408, 300)
    send_map_mouse(tool, "move", pixel)
    assert tool.snap_label == "G4 · gps"
    scene.canvas.setExtent(QgsRectangle(100, 0, 900, 600))  # 100 m east
    QgsApplication.processEvents()
    got: list[tuple[QgsPointXY, str]] = []
    tool.picked.connect(lambda p, label: got.append((QgsPointXY(p), label)))
    send_map_mouse(tool, "release", pixel)  # same pixel, but now map (508, 300)...
    # ...6 px from the polygon's (514, 300) vertex and far from G4.
    assert [(_xy(p), label) for p, label in got] == [((514.0, 300.0), "plot 7 · plan")]


def test_project_snapping_settings_are_neither_read_nor_changed(scene):
    # C2: picks snap whatever the project's snapping settings say. Set the
    # project to something that could never snap to G4 from 8 px.
    project = QgsProject.instance()
    original = project.snappingConfig()
    config = QgsSnappingConfig(project)
    config.setEnabled(True)
    config.setMode(Qgis.SnappingMode.ActiveLayer)
    config.setTypeFlag(Qgis.SnappingType.Segment)
    config.setTolerance(1)
    config.setUnits(Qgis.MapToolUnit.Pixels)
    project.setSnappingConfig(config)
    try:
        tool = scene.tool()
        send_map_mouse(tool, "move", (408, 300))
        got = _click(tool, 408, 300)
        assert [(_xy(p), label) for p, label in got] == [((400.0, 300.0), "G4 · gps")]
        assert project.snappingConfig() == config
    finally:
        project.setSnappingConfig(original)


def test_right_click_skips_and_esc_stops(scene):
    tool = scene.tool()
    seen: list[str] = []
    tool.picked.connect(lambda *_: seen.append("picked"))
    tool.skipped.connect(lambda: seen.append("skipped"))
    tool.stopped.connect(lambda: seen.append("stopped"))
    send_map_mouse(tool, "release", (408, 300), Qt.MouseButton.RightButton)
    assert seen == ["skipped"]
    esc = send_map_key(tool, Qt.Key.Key_Escape)
    assert seen == ["skipped", "stopped"]
    # QgsMapCanvas hands a key over accepted and carries on with its own
    # handling unless the tool ignore()s it: ignored means consumed.
    assert not esc.isAccepted()
    other = send_map_key(tool, Qt.Key.Key_Left)
    assert other.isAccepted()  # left for the canvas: arrow keys still pan
    assert seen == ["skipped", "stopped"]


def test_esc_reaches_the_tool_through_the_canvas_and_stops_there(scene):
    # The same convention, end to end: through the canvas, Esc stops the
    # pick and the canvas's own handling never runs (no keyPressed), while
    # an arrow key still pans.
    canvas = scene.canvas
    tool = scene.tool()
    canvas.setMapTool(tool)
    stopped: list[int] = []
    tool.stopped.connect(lambda: stopped.append(1))
    canvas_saw: list[int] = []
    canvas.keyPressed.connect(lambda e: canvas_saw.append(e.key()))
    QgsApplication.sendEvent(
        canvas, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert stopped == [1] and canvas_saw == []
    before = canvas.extent()
    QgsApplication.sendEvent(
        canvas, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
    )
    QgsApplication.processEvents()
    assert canvas_saw == [Qt.Key.Key_Left] and canvas.extent() != before
    tool.finish()


def test_switching_tools_cancels_once_unless_finished(scene):
    canvas = scene.canvas
    pan = QgsMapToolPan(canvas)
    tool = scene.tool()
    cancelled: list[int] = []
    tool.cancelled.connect(lambda: cancelled.append(1))
    canvas.setMapTool(tool)
    canvas.setMapTool(pan)
    assert cancelled == [1]
    canvas.setMapTool(tool)
    canvas.setMapTool(pan)
    assert cancelled == [1]  # once

    finished = scene.tool()
    after_finish: list[int] = []
    finished.cancelled.connect(lambda: after_finish.append(1))
    canvas.setMapTool(finished)
    finished.finish()
    canvas.setMapTool(pan)
    assert after_finish == []
    canvas.unsetMapTool(pan)


def test_polygon_mode_emits_the_clicked_feature(scene):
    # The topmost polygon under the click, searching only the canvas's
    # polygon layers in canvas.layers() order (first is drawn on top).
    # `upper` is stored in EPSG:4326, so the click is transformed into it.
    to_wgs = QgsCoordinateTransform(UTM16, WGS84, QgsProject.instance())
    square = [(300, 200), (500, 200), (500, 400), (300, 400)]
    wgs_square = [_xy(to_wgs.transform(QgsPointXY(*p))) for p in square]
    # "far" first, so "site" is not the layer's first feature id.
    upper = named_layer(
        "Polygon", "upper", {"far": [(0, 0), (1, 0), (1, 1)], "site": wgs_square}, crs="EPSG:4326"
    )
    # A project layer covering the whole view, but not on the canvas.
    offstage = named_layer("Polygon", "offstage", {"x": [(0, 0), (800, 0), (800, 600), (0, 600)]})
    QgsProject.instance().addMapLayer(offstage)
    try:
        canvas = scene.canvas
        canvas.setLayers([scene.gps, upper, scene.plan])
        tool = scene.tool("polygon")
        got: list[tuple[object, int]] = []
        tool.polygon_picked.connect(lambda layer, fid: got.append((layer, fid)))
        points: list[object] = []
        tool.picked.connect(lambda *a: points.append(a))

        send_map_mouse(tool, "move", (408, 300))  # G4 in range...
        assert tool.snap_label == ""  # ...but polygon mode never snaps
        send_map_mouse(tool, "release", (450, 350))  # inside site and plot 7
        assert len(got) == 1
        assert got[0][0] is upper and got[0][1] == feature_id(upper, "site")

        canvas.setLayers([scene.plan, upper])  # plan now on top
        send_map_mouse(tool, "release", (450, 350))
        assert got[1][0] is scene.plan and got[1][1] == feature_id(scene.plan, "plot 7")

        send_map_mouse(tool, "release", (100, 100))  # inside only `offstage`
        assert len(got) == 2
        assert points == []
    finally:
        QgsProject.instance().removeMapLayer(offstage.id())


def test_polygon_picked_carries_a_64_bit_feature_id(scene):
    # A pyqtSignal declared `int` is a C++ int: a feature id past 2**31
    # (a GeoPackage or PostGIS table can have them) arrives silently
    # wrapped -- verified, 2**31 + 7 came through as -2147483641 -- and
    # selects a different feature. QgsFeatureId is a qint64.
    tool = scene.tool("polygon")
    got: list[int] = []
    tool.polygon_picked.connect(lambda _layer, fid: got.append(fid))
    tool.polygon_picked.emit(scene.plan, 2**31 + 7)
    assert got == [2**31 + 7]


def test_an_exception_in_a_handler_becomes_failed_not_a_traceback(scene, monkeypatch):
    # Qt swallows an exception raised out of an override it calls (this
    # build prints it; CI's aborts -- see conftest's
    # _no_swallowed_slot_exceptions, which would fail this test if one
    # escaped). Each override reports through `failed` instead, which the
    # plugin turns into a message and the end of the pick.
    canvas = scene.canvas
    tool = scene.tool()
    failures: list[str] = []
    tool.failed.connect(failures.append)

    def broken(*_args: object) -> None:
        raise RuntimeError("index exploded")

    monkeypatch.setattr(tool, "_snap", broken)
    canvas.setMapTool(tool)
    pixel = map_pixel(canvas, 408, 300)
    # Through the canvas, as Qt delivers them: a direct call would raise
    # into this test instead of exercising the swallowed-exception path.
    QgsApplication.sendEvent(canvas.viewport(), _mouse(QEvent.Type.MouseMove, pixel, canvas))
    QgsApplication.sendEvent(
        canvas.viewport(), _mouse(QEvent.Type.MouseButtonRelease, pixel, canvas)
    )
    assert len(failures) == 2 and all("index exploded" in f for f in failures)
    tool.finish()


def _mouse(kind: QEvent.Type, pixel: object, canvas: object) -> QMouseEvent:
    """A plain QMouseEvent for the canvas's viewport: a left release, or a
    buttonless move."""
    release = kind == QEvent.Type.MouseButtonRelease
    return QMouseEvent(
        kind,
        QPointF(pixel),
        QPointF(canvas.viewport().mapToGlobal(pixel)),
        Qt.MouseButton.LeftButton if release else Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_a_disposed_pick_tool_is_disposable_again(scene, qgis_app):
    # Ported from test_a_disposed_digitise_tool_is_disposable_again_and_still_usable.
    # Disposal has to be idempotent -- more than one finaliser can reach
    # the same tool -- and it must NOT live in deactivate(), which fires
    # on every tool switch and leaves the tool legitimately
    # reactivatable. A tool whose canvas items are gone must therefore
    # still take moves and clicks without raising (an exception out of a
    # canvas event is swallowed by Qt), and without putting anything back.
    #
    # Counted off the scene, not off the tool: the snap marker is a
    # QgsMapCanvasItem, so the canvas's QGraphicsScene -- not the tool,
    # and not Python -- is what owns it.
    canvas = scene.canvas
    baseline = len(canvas.scene().items())
    tool = scene.tool()
    canvas.setMapTool(tool)
    send_map_mouse(tool, "move", (408, 300))
    assert len(canvas.scene().items()) == baseline + 1  # the marker is on the map

    tool.dispose()
    assert len(canvas.scene().items()) == baseline
    tool.dispose()  # idempotent
    qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(canvas.scene().items()) == baseline

    send_map_mouse(tool, "move", (408, 300))
    assert tool.snap_label == "G4 · gps"  # still a working tool...
    got = _click(tool, 408, 300)
    assert [(_xy(p), label) for p, label in got] == [((400.0, 300.0), "G4 · gps")]
    assert len(canvas.scene().items()) == baseline  # ...that draws nothing more
    tool.finish()


def test_leaving_the_canvas_takes_the_marker_off_the_map(scene, qgis_app):
    # deactivate() clears the marker (it comes back on the next move if the
    # tool is set again); only dispose() drops the indicator for good.
    canvas = scene.canvas
    baseline = len(canvas.scene().items())
    tool = scene.tool()
    canvas.setMapTool(tool)
    send_map_mouse(tool, "move", (408, 300))
    assert len(canvas.scene().items()) == baseline + 1
    tool.finish()
    canvas.unsetMapTool(tool)
    assert len(canvas.scene().items()) == baseline
    assert tool.snap_label == ""
    canvas.setMapTool(tool)
    send_map_mouse(tool, "move", (408, 300))
    assert len(canvas.scene().items()) == baseline + 1
    canvas.unsetMapTool(tool)
    assert len(canvas.scene().items()) == baseline
