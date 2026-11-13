"""CutTool: draw a cut on the map, point by point (cut spec §4.1).

On a real, shown canvas: EPSG:32616 over (0, 0)-(800, 600) at 1 m per pixel.
"""

from __future__ import annotations

import pytest
from nsgeo_qgis.maptools.cut_tool import CutTool
from plugin_testing import send_map_key, send_map_mouse
from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY, QgsRectangle
from qgis.PyQt.QtCore import Qt

UTM16 = QgsCoordinateReferenceSystem("EPSG:32616")


@pytest.fixture
def tool(real_canvas):
    canvas = real_canvas(UTM16, QgsRectangle(0, 0, 800, 600))
    made = CutTool(canvas)
    drawn: list[list[QgsPointXY]] = []
    made.drawn.connect(lambda pts: drawn.append([QgsPointXY(p) for p in pts]))
    made.drawn_log = drawn  # type: ignore[attr-defined]
    yield made
    made.dispose()


def _left(tool, *points):
    for p in points:
        send_map_mouse(tool, "release", p)


def test_left_clicks_add_points_and_right_click_finishes(tool):
    _left(tool, (100, 100), (200, 150), (300, 100))
    assert tool.drawn_log == []

    send_map_mouse(tool, "release", (300, 100), Qt.MouseButton.RightButton)

    assert len(tool.drawn_log) == 1
    got = [(p.x(), p.y()) for p in tool.drawn_log[0]]
    assert got == [(100, 100), (200, 150), (300, 100)]


def test_enter_finishes_and_backspace_removes_the_last_point(tool):
    _left(tool, (100, 100), (200, 150), (300, 100))
    back = send_map_key(tool, Qt.Key.Key_Backspace)
    done = send_map_key(tool, Qt.Key.Key_Return)

    assert [(p.x(), p.y()) for p in tool.drawn_log[0]] == [(100, 100), (200, 150)]
    # Consumed: an accepted Backspace would make QGIS delete the current layer's selection.
    assert not back.isAccepted() and not done.isAccepted()


def test_the_keys_the_tool_handles_never_reach_the_canvas(tool):
    seen: list[int] = []
    tool.canvas().keyPressed.connect(lambda e: seen.append(e.key()))
    canvas = tool.canvas()
    canvas.setMapTool(tool)
    try:
        from qgis.PyQt.QtCore import QEvent
        from qgis.PyQt.QtGui import QKeyEvent
        from qgis.PyQt.QtWidgets import QApplication

        for key in (Qt.Key.Key_Backspace, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            QApplication.sendEvent(
                canvas, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
            )
        assert seen == []
    finally:
        canvas.unsetMapTool(tool)


def test_esc_cancels_and_leaves_nothing_behind(tool):
    _left(tool, (100, 100), (200, 150))
    send_map_mouse(tool, "move", (250, 200))
    assert tool.band.numberOfVertices() > 0

    event = send_map_key(tool, Qt.Key.Key_Escape)

    assert not event.isAccepted()  # consumed: see pick_tool.py's trap
    assert tool.drawn_log == []
    assert tool.band.numberOfVertices() == 0
    send_map_key(tool, Qt.Key.Key_Return)  # nothing left to finish
    assert tool.drawn_log == []


def test_the_tool_stays_on_for_the_next_cut(tool):
    _left(tool, (100, 100), (200, 150))
    send_map_key(tool, Qt.Key.Key_Return)
    _left(tool, (300, 300), (400, 350), (500, 300))
    send_map_key(tool, Qt.Key.Key_Enter)

    assert [len(p) for p in tool.drawn_log] == [2, 3]
    assert tool.band.numberOfVertices() == 0


def test_a_moving_segment_follows_the_pointer(tool):
    _left(tool, (100, 100))
    send_map_mouse(tool, "move", (180, 120))
    assert tool.band.numberOfVertices() == 2


def test_an_exception_in_an_event_becomes_failed(tool, monkeypatch):
    failures: list[str] = []
    tool.failed.connect(failures.append)

    def boom(*_a):
        raise RuntimeError("no")

    monkeypatch.setattr(tool, "_add_point", boom)
    _left(tool, (100, 100))
    assert failures and "no" in failures[0]

    failures.clear()
    monkeypatch.setattr(tool, "_finish", boom)
    send_map_key(tool, Qt.Key.Key_Return)
    assert failures and "no" in failures[0]


def test_dispose_is_idempotent_and_draws_nothing_more(tool):
    failures: list[str] = []
    tool.failed.connect(failures.append)
    _left(tool, (100, 100), (150, 150))
    band = tool.band
    assert band.scene() is not None

    tool.dispose()
    tool.dispose()
    assert band.scene() is None  # taken off the canvas's scene

    _left(tool, (200, 200))
    send_map_mouse(tool, "move", (250, 250))
    send_map_key(tool, Qt.Key.Key_Return)
    assert failures == []
    assert tool.points == []
    assert tool.drawn_log == []
