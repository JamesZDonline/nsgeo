"""#57: the map's `lines` selection and the Survey panel's line selection are one,
through the whole plugin (MapLink, SurveyDock and the two `connect` lines in plugin.py)."""

from __future__ import annotations

import shutil
from pathlib import Path

import nsgeo_qgis
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.velocity import VelocityModel
from plugin_testing import CRS, gps_line, synthetic_dzt
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QWidget
from tests.real_data import GRID2_LINES

CTRL = Qt.KeyboardModifier.ControlModifier
# Six tape lines 0.5 m apart on one grid; the others are added per test.
GRID = Grid("A", (500.0, 700.0), 0.0, 4.0, 11.0, CRS, 0.5)
UNPLACED = "raw/FILE__TIME.DZT"
GPS = "raw/FILE__GPS.DZT"


def _tape(tmp_path, n=6):
    lines = []
    for i in range(n):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", 0.25 + i * 0.5, 0.0, 1, p.stem)))
    return lines


@pytest.fixture(autouse=True)
def _release_ctrl_after_each_test():
    """Qt keeps the last input event's modifiers application-wide, so a Ctrl-click
    here leaves Ctrl "held" for later tests in the process (their plain clicks
    then extend the selection). One event with no modifiers clears it."""
    yield
    probe = QWidget()
    probe.show()
    QTest.keyRelease(probe, Qt.Key.Key_Control, Qt.KeyboardModifier.NoModifier)
    probe.deleteLater()
    assert QApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier


@pytest.fixture
def wired(fake_iface, tmp_path):
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    session = plugin.session
    session.new_site(tmp_path)
    session.add_grid(GRID)
    session.add_lines(_tape(tmp_path))
    session.add_lines([gps_line(tmp_path / "raw", "FILE__GPS.DZT", {25: 4, 175: 4})])
    p = synthetic_dzt(tmp_path / "raw", "FILE__TIME.DZT", traces_per_metre=0.0)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 3.5, 0.0, 1, p.stem))])
    yield plugin
    plugin.session.save()  # unload would ask about unsaved changes
    plugin.unload()


def _tape_keys(plugin):
    return [k for k in plugin.session.keys() if k not in (GPS, UNPLACED)]  # noqa: SIM118


def _layer_keys(plugin):
    layer = plugin.layers.layers["lines"]
    return sorted(str(f["line_key"]) for f in layer.selectedFeatures())


def _select_on_map(plugin, keys):
    """Stands in for a rectangle with QGIS's Select tool: the layer's selection."""
    layer = plugin.layers.layers["lines"]
    ids = [f.id() for f in layer.getFeatures() if str(f["line_key"]) in set(keys)]
    assert len(ids) == len(keys)
    layer.selectByIds(ids)


def _panel_keys(plugin):
    return plugin.survey_dock.selected_line_keys()


def _click(dock, item, modifier=Qt.KeyboardModifier.NoModifier):
    if not dock.isVisible():
        # The plugin's dock sits in a main window nobody shows: float it, or the
        # tree stays a few pixels tall and the click lands on no row.
        dock.setFloating(True)
        dock.resize(400, 600)
        dock.show()
    parent = item.parent()
    while parent is not None:
        parent.setExpanded(True)
        parent = parent.parent()
    QApplication.processEvents()  # lay the shown tree out before measuring a row
    pos = dock.tree.visualItemRect(item).center()
    QTest.mouseClick(dock.tree.viewport(), Qt.MouseButton.LeftButton, modifier, pos)


def test_a_rectangle_over_several_lines_selects_them_in_the_panel_and_opens_nothing(wired):
    plugin = wired
    keys = _tape_keys(plugin)[:3]

    _select_on_map(plugin, keys)

    assert _panel_keys(plugin) == keys
    assert plugin.session.current_key is None
    assert _layer_keys(plugin) == sorted(keys)


def test_a_ctrl_click_in_the_panel_takes_the_line_off_the_map_and_opens_nothing(wired):
    plugin = wired
    dock = plugin.survey_dock
    keys = _tape_keys(plugin)[:3]
    _select_on_map(plugin, keys)

    _click(dock, dock.item_for_key(keys[1]), CTRL)
    assert _panel_keys(plugin) == [keys[0], keys[2]]
    assert _layer_keys(plugin) == [keys[0], keys[2]]
    _click(dock, dock.item_for_key(keys[0]), CTRL)  # down to one

    assert _panel_keys(plugin) == [keys[2]]
    assert _layer_keys(plugin) == [keys[2]]
    assert plugin.session.current_key is None


def test_clicking_empty_map_clears_both_and_the_open_line_stays_open(wired):
    plugin = wired
    keys = _tape_keys(plugin)
    plugin.session.open_line(keys[0])
    _select_on_map(plugin, keys[1:3])
    assert _panel_keys(plugin) == keys[1:3]

    plugin.layers.layers["lines"].removeSelection()

    assert _panel_keys(plugin) == []
    assert _layer_keys(plugin) == []
    assert plugin.session.current_key == keys[0]


def test_gps_lines_select_like_tape_lines(wired):
    plugin = wired
    keys = [_tape_keys(plugin)[0], GPS]

    _select_on_map(plugin, keys)
    assert _panel_keys(plugin) == keys
    assert plugin.session.current_key is None

    dock = plugin.survey_dock
    _click(dock, dock.item_for_key(keys[0]), CTRL)  # off in the panel
    assert _layer_keys(plugin) == [GPS]


def test_an_unplaced_line_stays_selected_in_the_panel_and_a_map_gesture_drops_it(wired):
    plugin = wired
    dock = plugin.survey_dock
    k0, k1 = _tape_keys(plugin)[:2]

    dock.tree.topLevelItem(0).child(0).setExpanded(True)
    for key in (UNPLACED, k0):  # as the user's own clicks select rows
        dock.item_for_key(key).setSelected(True)
    assert _layer_keys(plugin) == [k0]  # the map shows the rest
    assert sorted(_panel_keys(plugin)) == sorted([k0, UNPLACED])  # the panel keeps both

    _select_on_map(plugin, [k0, k1])  # a map gesture replaces the panel's selection
    assert _panel_keys(plugin) == [k0, k1]
    assert UNPLACED not in _panel_keys(plugin)


def test_the_selection_survives_a_bulk_velocity_in_both_places(wired):
    plugin = wired
    keys = _tape_keys(plugin)
    assert len(keys) == 6
    _select_on_map(plugin, keys)
    assert _panel_keys(plugin) == keys

    plugin.session.set_lines_velocity(keys, VelocityModel.constant(0.1))

    assert _panel_keys(plugin) == keys
    assert _layer_keys(plugin) == sorted(keys)


def test_delete_after_a_map_selection_removes_lines_only(wired):
    plugin = wired
    dock = plugin.survey_dock
    session = plugin.session
    keys = _tape_keys(plugin)[:2]
    _select_on_map(plugin, keys)
    grid_item = dock.tree.topLevelItem(0).child(0)
    grid_item.setSelected(True)  # a grid row swept into the selection

    dock.remove_selected_action(confirm=False)

    assert all(k not in session.keys() for k in keys)  # noqa: SIM118
    assert [g.id for g in session.site.grids] == ["A"]  # #31: lines only
    assert len(session.keys()) == 6  # 8 less the 2 removed


@pytest.mark.skipif(len(GRID2_LINES) < 6, reason="needs Grid 2 in tests/data/local/grid2")
def test_real_grid2_lines_select_from_the_map(fake_iface, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    paths = [shutil.copy(p, raw / p.name) for p in GRID2_LINES[:6]]
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    try:
        session = plugin.session
        session.new_site(tmp_path)
        session.add_grid(Grid("G2", (500.0, 700.0), 0.0, 4.0, 29.96, "EPSG:32616", 0.5))
        session.add_lines(
            [
                Line.open(p, GridPlacement("G2", "y", 0.25 + 0.5 * k, 0.0, 1, p.stem))
                for k, p in enumerate(map(Path, paths))
            ]
        )
        keys = session.keys()
        chosen = [keys[0], keys[2], keys[3], keys[5]]

        _select_on_map(plugin, chosen)

        assert _panel_keys(plugin) == chosen
        assert session.current_key is None
    finally:
        plugin.session.save()
        plugin.unload()


@pytest.mark.parametrize("hazard", ["clears", "stale_ids"])
def test_a_refill_that_changes_the_layers_selection_is_not_a_gesture(
    wired, monkeypatch, message_log, hazard
):
    """Spec §3.4, whatever the QGIS version: should a refill emit `selectionChanged`
    on the `lines` layer (emptied, or naming ids that no longer exist), neither
    selection is lost and nothing is logged."""
    plugin = wired
    keys = _tape_keys(plugin)
    _select_on_map(plugin, keys)
    layer = plugin.layers.layers["lines"]
    real = plugin.layers._refill_table

    def refill(name, features):
        real(name, features)
        if name == "lines":
            if hazard == "clears":
                layer.removeSelection()
            else:
                layer.selectByIds([9000, 9001])

    monkeypatch.setattr(plugin.layers, "_refill_table", refill)
    message_log.clear()

    plugin.session.set_lines_velocity(keys, VelocityModel.constant(0.1))

    assert _panel_keys(plugin) == keys
    assert _layer_keys(plugin) == sorted(keys)
    assert not [m for m in message_log if "selec" in m or "KeyError" in m], message_log
