"""Ctrl+click (Cmd+click on a Mac) for velocity points and boxes with velocity
mode off, through the assembled plugin with real Qt mouse events."""

# ruff: noqa: F811 -- the imported `plugin` fixture is used by name
from __future__ import annotations

from nsgeo_qgis.plugin import VELOCITY_ON_CUT_TIP, VELOCITY_TIP
from plugin_testing import send_move_while_pressed
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
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


def _velocity_off(plugin):
    plugin.act_velocity.setChecked(False)
    plugin.act_velocity.triggered.emit(False)
    assert not plugin.profile_dock.view._velocity_mode


def _spy_picks(view):
    picks: list = []
    view.pick_requested.connect(lambda t, ns: picks.append((t, ns)))
    return picks


def _ctrl_click(v, x, y, mods=CTRL):
    QTest.mouseClick(v, LEFT, mods, _pos(v, x, y))


def test_ctrl_click_with_velocity_off_turns_it_on_and_places_a_dot(plugin):
    v, dock = _view(plugin), plugin.profile_dock
    _velocity_off(plugin)
    _ctrl_click(v, *_px(v, 40, 12.0))
    assert plugin.act_velocity.isChecked()
    assert not dock.velocity_strip.isHidden()
    assert len(dock.velocity_points()) == 1


def test_ctrl_click_in_pick_mode_switches_to_velocity(plugin):
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


def test_ctrl_drag_traces_a_box(plugin):
    v, dock = _view(plugin), plugin.profile_dock
    _velocity_off(plugin)
    a, b = _box_around(v)
    QTest.mousePress(v, LEFT, CTRL, _pos(v, *a))
    send_move_while_pressed(v, _pos(v, *b), LEFT)
    QTest.mouseRelease(v, LEFT, CTRL, _pos(v, *b))
    assert plugin.act_velocity.isChecked()
    assert 4 <= len(dock.velocity_points()) <= 10


def test_ctrl_shift_click_does_neither(plugin):
    v, dock = _view(plugin), plugin.profile_dock
    _velocity_off(plugin)
    picks = _spy_picks(v)
    _ctrl_click(v, *_px(v, 40, 12.0), mods=CTRL | SHIFT)
    assert picks == []
    assert dock.velocity_points() == []
    assert not plugin.act_velocity.isChecked()
    assert not plugin.act_pick.isChecked()


def test_shift_click_still_picks_with_velocity_on(plugin):
    v, dock = _view(plugin), plugin.profile_dock
    picks = _spy_picks(v)
    QTest.mouseClick(v, LEFT, SHIFT, _pos(v, *_px(v, 40, 12.0)))
    assert len(picks) == 1
    assert dock.velocity_points() == []


def test_ctrl_click_on_a_cut_places_nothing_and_says_why(plugin, monkeypatch):
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


def test_the_velocity_tooltip_mentions_the_box_and_the_shortcut(plugin):
    assert plugin.act_velocity.toolTip() == VELOCITY_TIP
    assert "drag a box" in VELOCITY_TIP
    assert "Cmd+click on a Mac" in VELOCITY_TIP
