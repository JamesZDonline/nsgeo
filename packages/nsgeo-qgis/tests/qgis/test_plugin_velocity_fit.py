"""Velocity-fit mode through the assembled plugin: toolbar toggle, dock and
view wired as `plugin.py` wires them. Real Qt mouse events, not handler calls.
"""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QMessageBox

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)
NO_MOD = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton


@pytest.fixture
def plugin(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    # The session is dirty and never closed; unload() would prompt to save.
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    lines = [
        Line.open(
            synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT", n_traces=60),
            GridPlacement("A", "y", float(i), 0.0),
        )
        for i in (1, 2)
    ]
    s.add_lines(lines)
    for key, line in zip(s.keys(), lines, strict=True):
        s.set_profiles(key, line.load())
    s.open_line(s.keys()[0])
    plugin.profile_dock.view.resize(500, 300)
    try:
        yield plugin
    finally:
        plugin.unload()


def _view(plugin):
    return plugin.profile_dock.view


def _local(v, x, y):
    r = v.image_rect()
    return QPoint(r.left() + x, r.top() + y)


def _click(v, x, y, button=LEFT):
    QTest.mouseClick(v, button, NO_MOD, _local(v, x, y))


def _check(act):
    act.setChecked(True)
    act.triggered.emit(True)


def test_turning_on_velocity_mode_turns_off_pick_mode(plugin):
    _check(plugin.act_pick)
    assert _view(plugin)._pick_mode is True

    _check(plugin.act_velocity)

    assert not plugin.act_pick.isChecked()
    assert _view(plugin)._pick_mode is False
    assert _view(plugin)._velocity_mode is True


def test_turning_on_pick_mode_turns_off_velocity_mode(plugin):
    _check(plugin.act_velocity)
    assert _view(plugin)._velocity_mode is True

    _check(plugin.act_pick)

    assert not plugin.act_velocity.isChecked()
    assert _view(plugin)._velocity_mode is False
    assert _view(plugin)._pick_mode is True


def test_the_velocity_action_is_disabled_and_unchecked_with_no_line(plugin):
    _check(plugin.act_velocity)
    assert plugin.act_velocity.isEnabled()

    plugin.session.close_site()

    assert not plugin.act_velocity.isEnabled()
    assert not plugin.act_velocity.isChecked()
    assert _view(plugin)._velocity_mode is False


def test_a_click_in_velocity_mode_adds_a_point(plugin):
    v = _view(plugin)
    _check(plugin.act_velocity)
    _click(v, 40, 30)
    _click(v, 60, 50)
    pts = plugin.profile_dock.velocity_points()
    assert len(pts) == 2
    assert pts[0][0] == v.transform.trace_index_at(40)  # the first click is the apex
    assert pts[0][1] == pytest.approx(v.transform.time_of_y(30))
    assert v._velocity_points == pts  # and the view was handed the same list


def test_a_velocity_click_on_the_axis_margin_adds_no_point(plugin):
    v = _view(plugin)
    _check(plugin.act_velocity)
    _click(v, 40, -5)  # above the image: a time before the record starts
    _click(v, -5, 30)  # on the depth-axis margin
    assert plugin.profile_dock.velocity_points() == []


def test_a_right_click_drops_the_nearest_point(plugin):
    v = _view(plugin)
    _check(plugin.act_velocity)
    _click(v, 40, 30)
    _click(v, 80, 50)
    keep = plugin.profile_dock.velocity_points()[1]

    _click(v, 42, 32, Qt.MouseButton.RightButton)
    assert plugin.profile_dock.velocity_points() == [keep]

    # A right-click far from any point removes nothing.
    _click(v, 150, 20, Qt.MouseButton.RightButton)
    assert plugin.profile_dock.velocity_points() == [keep]


def test_opening_another_line_clears_the_working_points(plugin):
    v = _view(plugin)
    _check(plugin.act_velocity)
    _click(v, 40, 30)
    _click(v, 60, 50)
    assert len(plugin.profile_dock.velocity_points()) == 2

    plugin.session.open_line(plugin.session.keys()[1])

    assert plugin.profile_dock.velocity_points() == []
    assert v._velocity_points == []


def test_velocity_mode_leaves_selection_drag_and_the_cutoff_handle_alone(plugin):
    v = _view(plugin)
    assert v._velocity_mode is False
    v.set_cutoff(40.0)
    line_y = round(v._cutoff_y(v.transform))
    QTest.mousePress(v, LEFT, NO_MOD, _local(v, 100, line_y))
    assert v._cutoff_grab is not None  # the handle grabbed; nothing swallowed it
    QTest.mouseRelease(v, LEFT, NO_MOD, _local(v, 100, line_y))
    assert plugin.profile_dock.velocity_points() == []
