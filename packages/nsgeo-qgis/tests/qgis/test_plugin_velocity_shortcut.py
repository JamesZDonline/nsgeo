"""Ctrl+click (Cmd+click on a Mac) for velocity points and boxes with velocity
mode off, through the assembled plugin with real Qt mouse events."""

from __future__ import annotations

from nsgeo_qgis.plugin import VELOCITY_ON_CUT_TIP, VELOCITY_TIP
from plugin_testing import send_move_while_pressed
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication
from test_plugin_velocity_box import (  # noqa: F401 -- plugin is the shared fixture
    LEFT,
    _box_around,
    _pos,
    _px,
    _view,
    plugin,
)

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


def _velocity_off(plugin):  # noqa: F811
    plugin.act_velocity.setChecked(False)
    plugin.act_velocity.triggered.emit(False)
    assert not plugin.profile_dock.view._velocity_mode


def _spy_picks(view):
    picks: list = []
    view.pick_requested.connect(lambda t, ns: picks.append((t, ns)))
    return picks


def _ctrl_click(v, x, y, mods=CTRL):
    QTest.mouseClick(v, LEFT, mods, _pos(v, x, y))


def test_ctrl_click_with_velocity_off_turns_it_on_and_places_a_dot(plugin):  # noqa: F811
    v, dock = _view(plugin), plugin.profile_dock
    _velocity_off(plugin)
    _ctrl_click(v, *_px(v, 40, 12.0))
    assert plugin.act_velocity.isChecked()
    assert not dock.velocity_strip.isHidden()
    assert len(dock.velocity_points()) == 1


def test_ctrl_click_in_pick_mode_switches_to_velocity(plugin):  # noqa: F811
    v = _view(plugin)
    _velocity_off(plugin)
    plugin.act_pick.setChecked(True)
    plugin.act_pick.triggered.emit(True)
    picks = _spy_picks(v)
    _ctrl_click(v, *_px(v, 40, 12.0))
    assert not plugin.act_pick.isChecked()
    assert plugin.act_velocity.isChecked()
    assert picks == []
    assert len(plugin.profile_dock.velocity_points()) == 1


def test_ctrl_drag_traces_a_box(plugin):  # noqa: F811
    v, dock = _view(plugin), plugin.profile_dock
    _velocity_off(plugin)
    a, b = _box_around(v)
    QTest.mousePress(v, LEFT, CTRL, _pos(v, *a))
    send_move_while_pressed(v, _pos(v, *b), LEFT)
    QTest.mouseRelease(v, LEFT, CTRL, _pos(v, *b))
    assert plugin.act_velocity.isChecked()
    assert 4 <= len(dock.velocity_points()) <= 10


def test_ctrl_shift_click_does_neither(plugin):  # noqa: F811
    v, dock = _view(plugin), plugin.profile_dock
    _velocity_off(plugin)
    picks = _spy_picks(v)
    _ctrl_click(v, *_px(v, 40, 12.0), mods=CTRL | SHIFT)
    assert picks == []
    assert dock.velocity_points() == []
    assert not plugin.act_velocity.isChecked()
    assert not plugin.act_pick.isChecked()


def test_shift_click_still_picks_with_velocity_on(plugin):  # noqa: F811
    v, dock = _view(plugin), plugin.profile_dock
    picks = _spy_picks(v)
    QTest.mouseClick(v, LEFT, SHIFT, _pos(v, *_px(v, 40, 12.0)))
    assert len(picks) == 1
    assert dock.velocity_points() == []


def test_ctrl_click_on_a_cut_places_nothing_and_says_why(plugin, monkeypatch):  # noqa: F811
    s = plugin.session
    cut = s.add_cut("A", [(1.0, 1.0), (4.0, 1.0)])
    v = _view(plugin)
    shown = v.transform  # a cut has no data in this fixture, so keep the line's transform
    s.open_line(cut)
    v.transform = shown
    _velocity_off(plugin)
    said: list = []
    monkeypatch.setattr(plugin, "message", lambda text, level=None, **kw: said.append(text))
    _ctrl_click(v, *_px(v, 5, 12.0))
    assert not plugin.act_velocity.isChecked()
    assert plugin.profile_dock.velocity_points() == []
    assert said == [VELOCITY_ON_CUT_TIP]


def test_the_velocity_tooltip_mentions_the_box_and_the_shortcut(plugin):  # noqa: F811
    assert plugin.act_velocity.toolTip() == VELOCITY_TIP
    assert "drag a box" in VELOCITY_TIP
    assert "Cmd+click on a Mac" in VELOCITY_TIP


def test_ctrl_shift_in_velocity_mode_places_no_dot(plugin):  # noqa: F811
    v, dock = _view(plugin), plugin.profile_dock
    picks = _spy_picks(v)
    _ctrl_click(v, *_px(v, 40, 12.0), mods=CTRL | SHIFT)
    assert picks == []
    assert dock.velocity_points() == []
    assert plugin.act_velocity.isChecked()


def test_ctrl_shift_in_pick_mode_places_nothing(plugin):  # noqa: F811
    v, dock = _view(plugin), plugin.profile_dock
    _velocity_off(plugin)
    plugin.act_pick.setChecked(True)
    plugin.act_pick.triggered.emit(True)
    picks = _spy_picks(v)
    _ctrl_click(v, *_px(v, 40, 12.0), mods=CTRL | SHIFT)
    assert picks == []
    assert dock.velocity_points() == []
    assert plugin.act_pick.isChecked()
    assert not plugin.act_velocity.isChecked()


def test_a_ctrl_press_in_the_axis_margin_changes_no_mode(plugin):  # noqa: F811
    v = _view(plugin)
    _velocity_off(plugin)
    plugin.act_pick.setChecked(True)
    plugin.act_pick.triggered.emit(True)
    QTest.mouseClick(v, LEFT, CTRL, _pos(v, -5, 10))  # left of the radargram
    QTest.mouseClick(v, LEFT, CTRL, _pos(v, 10, -5))  # above it
    assert plugin.act_pick.isChecked()
    assert not plugin.act_velocity.isChecked()
    assert plugin.profile_dock.velocity_points() == []


def _show_with_tall_dock(plugin):  # noqa: F811
    main = plugin.iface.mainWindow()
    main.resize(1200, 900)
    main.show()
    for _ in range(10):
        QApplication.processEvents()
    main.resizeDocks([plugin.profile_dock], [450], Qt.Orientation.Vertical)
    for _ in range(10):
        QApplication.processEvents()
    return main


def test_ctrl_click_lands_where_clicked_when_the_strip_shrinks_the_view(plugin):  # noqa: F811
    v, dock = _view(plugin), plugin.profile_dock
    main = _show_with_tall_dock(plugin)
    try:
        _velocity_off(plugin)
        for _ in range(10):
            QApplication.processEvents()
        h0 = v.height()
        x, y = _px(v, 60, 20.0)
        sample = v.transform.time_of_y(y + 1) - v.transform.time_of_y(y)
        _ctrl_click(v, x, y)
        assert v.height() < h0  # the strip really took room from the view
        ((_, ns),) = dock.velocity_points()
        assert abs(ns - 20.0) <= max(sample, 0.2)
    finally:
        main.hide()


def test_ctrl_drag_box_keeps_its_corners_when_the_strip_shrinks_the_view(plugin):  # noqa: F811
    v, dock = _view(plugin), plugin.profile_dock
    main = _show_with_tall_dock(plugin)
    try:
        _velocity_off(plugin)
        for _ in range(10):
            QApplication.processEvents()
        h0 = v.height()
        a, b = _box_around(v)
        boxes: list = []
        v.velocity_box_drawn.connect(lambda *args: boxes.append(args))
        QTest.mousePress(v, LEFT, CTRL, _pos(v, *a))
        assert v.height() < h0
        # The end point is read through the resized transform, as a user's is.
        end = _px(v, 90, 30.0)
        send_move_while_pressed(v, _pos(v, *end), LEFT)
        QTest.mouseRelease(v, LEFT, CTRL, _pos(v, *end))
        ((_, _, top, bottom),) = boxes
        assert abs(top - 8.0) <= 0.3
        assert abs(bottom - 30.0) <= 0.3
        assert dock.velocity_points() is not None
    finally:
        main.hide()
