from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.gain_strip import GainStrip
from nsgeo_qgis.ui.profile_dock import ProfileDock
from nsgeo_qgis.ui.profile_view import MARGIN_TOP
from nsgeo_qgis.ui.view_transform import ViewTransform
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, Qt
from qgis.PyQt.QtGui import QMouseEvent
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QMessageBox

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def strip(qgis_app):
    """A bare, parentless, shown `GainStrip` -- exactly the shape
    `test_plugin_profile_view.py`'s `make_view` fixture documents as a
    segfault hazard at interpreter shutdown (a top-level widget GC might
    destroy it while still shown, racing Qt's own teardown). `hide()` +
    `deleteLater()` on teardown is that fixture's own fix, copied here for
    the same reason -- it does not, by itself, fix the separate ordering
    hazard `_send_double_click` below exists for; see that function's own
    docstring.
    """
    s = GainStrip()
    s.resize(96, 300 + MARGIN_TOP + 28)
    s.show()
    t = ViewTransform.fit(100, 200, 0.0, 0.5, 600, 300)
    s.set_time_mapping(t, MARGIN_TOP)
    s.set_points([[0.0, 0.0], [100.0, 20.0]])
    yield s
    s.hide()
    s.deleteLater()


def _send_move_while_pressed(
    widget, local_pos: QPoint, held_button=Qt.MouseButton.LeftButton
) -> None:
    """A mouse move sent *while a button is logically held* (between a
    `QTest.mousePress` and the matching `mouseRelease`) is not reliably
    delivered by `QTest.mouseMove` -- verified directly in this same
    offscreen-QPA environment by `test_plugin_profile_view.py`'s own copy
    of this helper (see its docstring): the identical mousePress +
    mouseMove sequence this task's own brief specified for the drag test
    below never invoked `mouseMoveEvent` at all while the button was still
    down. Building and sending the `QMouseEvent` directly bypasses
    `QTest`'s cursor-warp-based simulation and reaches the widget's real
    `mouseMoveEvent` every time, exactly as a genuine OS-level drag does.
    """
    local = QPointF(local_pos)
    glob = QPointF(widget.mapToGlobal(local_pos))
    ev = QMouseEvent(
        QEvent.Type.MouseMove,
        local,
        glob,
        Qt.MouseButton.NoButton,
        held_button,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, ev)


def _send_double_click(widget, local_pos: QPoint, button=Qt.MouseButton.LeftButton) -> None:
    """`QTest.mouseDClick` is not just unreliable the way plain
    `QTest.mouseMove` is (see `_send_move_while_pressed` above) -- verified
    directly, it corrupts state in this offscreen-QPA environment that
    outlives both the widget and the test: a `QTest.mouseDClick` call
    here, in what became `test_double_click_adds_and_right_click_removes`,
    made `test_plugin_profile_view.py::test_mouse_move_emits_the_trace_
    under_the_cursor` -- an unrelated test, in a different file, on a
    widget that does not exist yet when this one runs -- fail every time
    it ran afterwards in the same session, its `QTest.mouseMove` silently
    never reaching `mouseMoveEvent` at all. Isolated with a minimal
    `QWidget` outside this file entirely (no GainStrip involved): a bare
    `QTest.mouseDClick` on one widget in one test reproducibly blocks a
    plain, buttonless `QTest.mouseMove` on a *different* widget in the
    *next* test; neither `hide()`/`deleteLater()` on the first widget nor
    a forced extra `QMouseEvent(MouseButtonRelease, ...)` afterwards
    cleared it. Replacing `QTest.mouseDClick` with the same four events a
    real double-click actually delivers (press, release, dblclick,
    release -- Qt turns the second physical press into a
    `MouseButtonDblClick`, not a second `MouseButtonPress`), sent directly
    via `QApplication.sendEvent` the same way `_send_move_while_pressed`
    bypasses `QTest` above, reaches `mouseDoubleClickEvent` correctly and
    was confirmed, in that same minimal reproduction, to leave no such
    trace behind.
    """
    local = QPointF(local_pos)
    glob = QPointF(widget.mapToGlobal(local_pos))

    def send(typ: QEvent.Type, buttons: Qt.MouseButton) -> None:
        QApplication.sendEvent(
            widget,
            QMouseEvent(typ, local, glob, button, buttons, Qt.KeyboardModifier.NoModifier),
        )

    send(QEvent.Type.MouseButtonPress, button)
    send(QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)
    send(QEvent.Type.MouseButtonDblClick, button)
    send(QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)


def test_mappings_round_trip(strip):
    assert strip.time_of_y(strip.y_of_time(37.0)) == pytest.approx(37.0)
    assert strip.db_of_x(strip.x_of_db(12.0)) == pytest.approx(12.0)
    assert strip.y_of_time(0.0) == MARGIN_TOP


def test_dragging_a_handle_moves_its_point_and_emits(strip):
    got = []
    strip.points_changed.connect(got.append)
    x0, y0 = strip.x_of_db(20.0), strip.y_of_time(100.0)
    assert strip.handle_at(QPoint(int(x0), int(y0))) == 1
    QTest.mousePress(
        strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(x0), int(y0))
    )
    # Not QTest.mouseMove: see _send_move_while_pressed's docstring above --
    # a move sent while a button is held is not reliably delivered by it in
    # this offscreen environment.
    _send_move_while_pressed(strip, QPoint(int(strip.x_of_db(30.0)), int(y0)))
    QTest.mouseRelease(
        strip,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(strip.x_of_db(30.0)), int(y0)),
    )
    assert got and got[-1][1][1] == pytest.approx(30.0, abs=0.5)
    assert strip.points()[1][0] == pytest.approx(100.0, abs=0.5)


def test_double_click_adds_and_right_click_removes(strip):
    got = []
    strip.points_changed.connect(got.append)
    mid = QPoint(int(strip.x_of_db(10.0)), int(strip.y_of_time(50.0)))
    # Not QTest.mouseDClick: see _send_double_click's docstring above -- it
    # corrupts mouse state in this offscreen environment that outlives
    # this test entirely.
    _send_double_click(strip, mid)
    assert len(strip.points()) == 3 and got[-1][1][0] == pytest.approx(50.0, abs=0.5)
    QTest.mouseClick(strip, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, mid)
    assert len(strip.points()) == 2
    QTest.mouseClick(
        strip,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(strip.x_of_db(0.0)), int(strip.y_of_time(0.0))),
    )
    assert len(strip.points()) == 2  # never below two


def test_profile_dock_shows_the_strip_only_when_asked(qgis_app, tmp_path):
    # A parentless ProfileDock is a top-level widget -- the same hazard
    # test_plugin_profile_view.py's make_view fixture and
    # test_plugin_profile_dock.py's opened/bare fixtures document and guard
    # against (a shown top-level widget destroyed by Python's GC instead of
    # Qt segfaults at interpreter shutdown): torn down explicitly at the end
    # of this test, the same way those fixtures do in their own teardown.
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    assert dock.gain_strip.isHidden()
    dock.show_gain_strip([[-11.0, 0.0], [99.0, 0.0]])
    assert not dock.gain_strip.isHidden()
    assert dock.gain_strip.y_of_time(-11.0) == pytest.approx(
        MARGIN_TOP + dock.view.transform.y_of_time(-11.0)
    )
    changed = []
    dock.gain_points_changed.connect(changed.append)
    dock.gain_strip.set_points([[-11.0, 0.0], [99.0, 12.0]])
    dock.gain_strip.points_changed.emit(dock.gain_strip.points())
    assert changed and changed[0][1][1] == 12.0
    dock.show_gain_strip(None)
    assert dock.gain_strip.isHidden()
    dock.hide()
    dock.deleteLater()


def test_plugin_routes_strip_edits_through_replace_step(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    plugin.processing_dock.add_step("dewow")
    plugin.processing_dock.add_step_with_dialog("gain_curve")
    plugin.processing_dock.list.setCurrentRow(1)
    assert not plugin.profile_dock.gain_strip.isHidden()
    plugin.profile_dock.gain_strip.set_points([[-11.0, 0.0], [50.0, 6.0], [99.0, 0.0]])
    plugin.profile_dock.gain_strip.points_changed.emit(plugin.profile_dock.gain_strip.points())
    assert s.stack_for(key).entries[1][0].params["points"][1] == [50.0, 6.0]
    plugin.processing_dock.list.setCurrentRow(0)
    assert plugin.profile_dock.gain_strip.isHidden()
    # The session is dirty by now (new_site/add_grid/add_lines/the stack
    # edits above); unload() prompts to save, and the offscreen-modal
    # guard in conftest.py fails fast on any unanswered prompt rather than
    # hang -- see test_plugin_survey_dock.py's own unload() tests for the
    # same pattern. Discard: this test does not care whether the site was
    # saved, only that unload() tears the docks down.
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_plugin_reports_a_bad_curve_edit_instead_of_raising(fake_iface, tmp_path, answer_modal):
    """`points_changed` is a public signal on a public widget: nothing
    stops a payload reaching `_on_gain_points` that `GainStrip` itself
    would never emit through its own UI (its "never below two" rule guards
    dragging/clicking, not this signal). `build_step`'s own `ValueError`
    ("gain_curve needs at least two control points") must be caught the
    same way `session.replace_step`'s already is -- not escape from this
    signal-connected slot (see the module docstring's own hazard note)
    leaving the step silently unchanged with no explanation.
    """
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    plugin.processing_dock.add_step_with_dialog("gain_curve")
    plugin.processing_dock.list.setCurrentRow(0)
    before = s.stack_for(key).entries[0][0]

    plugin.profile_dock.gain_strip.points_changed.emit([[0.0, 0.0]])  # only one point

    assert s.stack_for(key).entries[0][0] is before  # unchanged, not corrupted
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "at least two" in item.text()

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_dragging_a_point_past_its_neighbour_does_not_corrupt_it(
    fake_iface, tmp_path, answer_modal
):
    """Every point_changed emitted mid-drag runs through NsgeoPlugin's own
    session.replace_step, which -- via stack_changed -> ProcessingDock.
    rebuild() -> step_selected -- calls back into _sync_gain_strip. Verified
    directly: with no guard against that echo, _sync_gain_strip re-called
    show_gain_strip() -> GainStrip.set_points(), which re-sorts the point
    list by time; the instant a drag carries a point's time past a
    neighbour's, that resort remaps GainStrip._drag's fixed index onto the
    *neighbour* instead of the point actually under the cursor, and the
    next move silently overwrote the neighbour's (time, dB) with the drag's
    new position -- the neighbour's own value was gone, not merely
    reordered. A single instant jump does not show this (the resort's
    output happens to still agree with the pre-jump order until a second
    move writes through the now-wrong index), so this drags through
    several intermediate positions the way a real, continuous drag would.
    """
    import nsgeo_qgis
    from nsgeo.processing import build_step

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    plugin.processing_dock.add_step_with_dialog("gain_curve")
    s.replace_step(
        key, 0, build_step("gain_curve", points=[[0.0, 0.0], [50.0, 10.0], [100.0, 20.0]])
    )
    plugin.processing_dock.list.setCurrentRow(0)
    strip = plugin.profile_dock.gain_strip

    x = strip.x_of_db(10.0)  # dragged point's dB never changes below
    assert strip.handle_at(QPoint(int(x), int(strip.y_of_time(50.0)))) == 1
    QTest.mousePress(
        strip,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(x), int(strip.y_of_time(50.0))),
    )
    for t in (60.0, 80.0, 100.0, 120.0, 150.0):  # crosses the t=100 neighbour partway through
        _send_move_while_pressed(strip, QPoint(int(x), int(strip.y_of_time(t))))
    QTest.mouseRelease(
        strip,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(x), int(strip.y_of_time(150.0))),
    )

    final = s.stack_for(key).entries[0][0].params["points"]
    assert [0.0, 0.0] in final
    assert [100.0, 20.0] in final, f"the (100, 20) neighbour was corrupted: {final}"
    assert any(t > 100.0 and db == pytest.approx(10.0) for t, db in final)

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
