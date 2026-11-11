"""Picks on a cut: a distance and a time, following the grid (cut spec §4.5, §4.8).

The plugin runs on `site3` (three 6 x 6 m grids side by side, four lines each,
a GeoPackage behind it), and grid A holds the cut `H` along x, 4 m long.
"""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest
from nsgeo.model import is_cut_key
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.cut_sections import CutSection
from nsgeo_qgis.map_link import CUT_GONE_TEXT
from nsgeo_qgis.session import Pick
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsProject
from qgis.PyQt.QtWidgets import QMessageBox
from test_plugin_cut_sections import H, site  # noqa: F401 -- fixtures

T = 12.5


@pytest.fixture
def opened(site):  # noqa: F811
    """The plugin with cut `H` on grid A drawn and open as the working cut."""
    plugin = site
    key = plugin.session.add_cut("A", H)
    plugin.session.open_line(key)
    assert isinstance(plugin.cut_sections.section(key, build_cube=True), CutSection)
    return plugin, key


def _rows(plugin):
    return list(plugin.layers.layers["picks"].getFeatures())


def _pick_at(plugin, key, column, time_ns=T):
    plugin._on_pick_requested(key, column, time_ns)
    return _rows(plugin)[-1]


def _world(session, grid_id, local):
    grid = session.grid(grid_id)
    x, y = grid.to_world(np.asarray([local], dtype=float))[0]
    return float(x), float(y)


def _select(plugin, feature):
    layer = plugin.layers.layers["picks"]
    layer.selectByIds([feature.id()])


def test_a_pick_on_a_cut_lands_on_the_cut_and_records_its_provenance(opened):
    plugin, key = opened
    session = plugin.session
    section = plugin.cut_sections.section(key, build_cube=True)
    row = _pick_at(plugin, key, 12)
    cut = session.cut_for_key(key)
    distance = float(section.columns.distance_m[12])
    assert (row["line_key"], row["trace"]) == (key, 12)
    assert row["distance_m"] == pytest.approx(distance)
    want = _world(session, "A", cut.point_at(distance))
    point = row.geometry().asPoint()
    assert (point.x(), point.y()) == pytest.approx(want, abs=1e-9)
    assert plugin.layers.layers["picks"].crs().authid() == "EPSG:32616"
    doc = json.loads(row["stack_json"])
    assert doc["kind"] == "cut" and doc["cut_id"] == cut.id
    assert row["time_ns"] == T
    velocity = session.cut_velocity("A")
    assert row["depth_m"] == pytest.approx(float(velocity.depth_at([T])[0]))
    assert row["velocity_m_ns"] == pytest.approx(float(velocity.velocity_at([T])[0]))


def test_selecting_a_cut_pick_reopens_the_cut_at_its_distance(opened):
    plugin, key = opened
    session = plugin.session
    row = _pick_at(plugin, key, 12)
    other = session.keys()[0]
    session.open_line(other)
    assert session.current_key == other
    _select(plugin, row)
    assert session.current_key == key
    assert session.current_trace == plugin.cut_sections.column_at(key, row["distance_m"])


def test_renaming_the_cut_keeps_the_way_back(opened):
    plugin, key = opened
    session = plugin.session
    row = _pick_at(plugin, key, 12)
    session.rename_cut(key, "Wall")
    session.open_line(session.keys()[0])
    _select(plugin, plugin.layers.layers["picks"].getFeature(row.id()))
    assert session.current_key == key


def test_deleting_the_cut_leaves_its_picks_and_selecting_one_says_so(opened):
    plugin, key = opened
    session = plugin.session
    row = _pick_at(plugin, key, 12)
    before = (row.geometry().asPoint(), row["distance_m"], row["depth_m"])
    session.remove_cut(key)
    other = session.keys()[0]
    session.open_line(other)
    told = []
    plugin.map_link.on_info = told.append
    (after,) = _rows(plugin)
    assert (after.geometry().asPoint(), after["distance_m"], after["depth_m"]) == before
    _select(plugin, after)
    assert told == [CUT_GONE_TEXT]
    assert session.current_key == other


def test_a_pick_on_a_never_saved_cut_behaves_the_same_after_reopening(
    site,  # noqa: F811
    fake_iface,
    answer_modal,
):
    plugin = site
    session = plugin.session
    path = session.json_path
    key = session.add_cut("A", H)
    session.open_line(key)
    row = _pick_at(plugin, key, 12)
    where = row.geometry().asPoint()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    session.close_site()
    session.open_site(path)
    assert key not in session.cut_keys()
    (again,) = _rows(plugin)
    assert again.geometry().asPoint() == where
    told = []
    plugin.map_link.on_info = told.append
    _select(plugin, again)
    assert told == [CUT_GONE_TEXT]


def test_a_crs_rebuild_keeps_the_cut_pick(opened):
    plugin, key = opened
    session = plugin.session
    row = _pick_at(plugin, key, 12)
    distance = row["distance_m"]
    layer = plugin.layers.layers["picks"]
    assert layer.crs().authid() == "EPSG:32616"
    session.replace_grid(dataclasses.replace(session.grid("A"), crs="EPSG:32617"))
    layer = plugin.layers.layers["picks"]
    assert layer.crs().authid() == "EPSG:32617"  # the table really was rebuilt
    assert key in session.cut_keys()
    (kept,) = [r for r in _rows(plugin) if r["line_key"] == key]
    assert (kept["time_ns"], kept["trace"], kept["distance_m"]) == (T, 12, distance)
    grid = session.grid("A")
    world = grid.to_world(np.asarray([session.cut_for_key(key).point_at(distance)]))[0]
    want = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:32617"),
        layer.crs(),
        QgsProject.instance(),
    ).transform(QgsPointXY(float(world[0]), float(world[1])))
    point = kept.geometry().asPoint()
    assert (point.x(), point.y()) == pytest.approx((want.x(), want.y()), abs=1e-6)


def test_a_cell_change_reopens_the_pick_at_the_same_distance_and_time(opened):
    plugin, key = opened
    dock = plugin.slices_dock
    row = _pick_at(plugin, key, 12)
    distance = row["distance_m"]
    profile = plugin.profile_dock
    before = profile.view._picks
    assert before == [(plugin.cut_sections.column_at(key, distance), T)]
    dock.cell_spin.setValue(dock.cell_spin.value() * 2)
    dock.flush_debounce()
    dock.engine.wait_for_preparation(20_000)
    dock.refresh_slice()
    session = plugin.session
    column = plugin.cut_sections.column_at(key, distance)
    assert column != before[0][0]
    assert profile.view._picks == [(column, T)]  # redrawn by section_changed alone
    (stored,) = _rows(plugin)
    assert (stored["distance_m"], stored["trace"]) == (distance, 12)
    # Selecting it reopens at the distance's column now, not at the stored trace.
    session.open_line(session.keys()[0])
    _select(plugin, stored)
    assert session.current_key == key
    assert session.current_trace == column != stored["trace"]


def test_a_moved_grid_moves_cut_picks_and_keeps_distance(opened):
    plugin, key = opened
    session = plugin.session
    row = _pick_at(plugin, key, 12)
    old = row.geometry().asPoint()
    distance = row["distance_m"]
    grid = session.grid("A")
    session.replace_grid(dataclasses.replace(grid, origin=(grid.origin[0] + 1.0, grid.origin[1])))
    (moved,) = _rows(plugin)
    point = moved.geometry().asPoint()
    assert (point.x() - old.x(), point.y() - old.y()) == pytest.approx((1.0, 0.0), abs=1e-9)
    assert moved["distance_m"] == distance


def test_a_grid_velocity_change_rederives_depth_and_a_line_override_does_not(opened):
    plugin, key = opened
    session = plugin.session
    _pick_at(plugin, key, 12)
    (row,) = _rows(plugin)
    first, first_velocity = row["depth_m"], row["velocity_m_ns"]
    session.set_line_velocity(session.keys()[0], VelocityModel.constant(0.2))
    (row,) = _rows(plugin)
    assert (row["depth_m"], row["velocity_m_ns"]) == (first, first_velocity)
    session.set_grid_velocity("A", VelocityModel.constant(0.1))
    (row,) = _rows(plugin)
    assert row["depth_m"] == pytest.approx(0.1 * T / 2.0)
    assert row["velocity_m_ns"] == pytest.approx(0.1)
    assert row["depth_m"] != pytest.approx(first)
    assert (row["trace"], row["time_ns"]) == (12, T)


def test_opening_a_site_rederives_cut_picks_with_no_engine_prepared(
    site,  # noqa: F811
    fake_iface,
    answer_modal,
):
    plugin = site
    session = plugin.session
    key = session.add_cut("A", H)
    session.open_line(key)
    session.save()
    row = _pick_at(plugin, key, 12)
    path = session.json_path
    layer = plugin.layers.layers["picks"]
    # Stale the derived fields behind the plugin's back, as an older build or a
    # hand edit would leave them, then reopen.
    provider = layer.dataProvider()
    i_depth = provider.fieldNameIndex("depth_m")
    i_vel = provider.fieldNameIndex("velocity_m_ns")
    provider.changeAttributeValues({row.id(): {i_depth: 9.9, i_vel: 0.9}})
    session.close_site()
    plugin.slices_dock.engine.dispose()  # nothing prepared when the site opens
    session.open_site(path)
    (again,) = _rows(plugin)
    velocity = session.cut_velocity("A")
    assert again["depth_m"] == pytest.approx(float(velocity.depth_at([T])[0]))
    assert again["velocity_m_ns"] == pytest.approx(float(velocity.velocity_at([T])[0]))


def test_removing_a_grid_keeps_its_cut_picks_on_the_map(opened, answer_modal):
    plugin, key = opened
    row = _pick_at(plugin, key, 12)
    before = {name: row[name] for name in ("line_key", "trace", "distance_m", "time_ns", "depth_m")}
    where = row.geometry().asPoint()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Yes)
    plugin.survey_dock.remove_grid_action("A")
    assert "A" not in [g.id for g in plugin.session.site.grids]
    (after,) = _rows(plugin)
    assert {name: after[name] for name in before} == before
    assert after.geometry().asPoint() == where


def test_a_pick_past_a_shrunk_grid_edge_keeps_its_distance(opened):
    plugin, key = opened
    session = plugin.session
    section = plugin.cut_sections.section(key, build_cube=True)
    last = section.columns.distance_m.size - 1
    row = _pick_at(plugin, key, last)
    distance = row["distance_m"]
    assert distance == pytest.approx(4.0)
    session.replace_grid(
        dataclasses.replace(session.grid("A"), size_x=3.0)
    )  # the cut now overhangs
    (after,) = _rows(plugin)
    assert after["distance_m"] == distance
    want = _world(session, "A", session.cut_for_key(key).point_at(distance))
    point = after.geometry().asPoint()
    assert (point.x(), point.y()) == pytest.approx(want, abs=1e-9)
    # The profile keeps working: still the cut's title, and no overlay while no section is drawn.
    assert plugin.profile_dock.windowTitle().startswith("nsgeo Profile · cut:")
    assert plugin.profile_dock.view._picks == []


def test_the_profile_overlays_cut_picks_at_their_columns(opened):
    plugin, key = opened
    section = plugin.cut_sections.section(key, build_cube=True)
    first = _pick_at(plugin, key, 12)
    _pick_at(plugin, key, 30, 20.0)
    got = plugin.profile_dock.view._picks
    assert sorted(got) == [
        (plugin.cut_sections.column_at(key, first["distance_m"]), T),
        (plugin.cut_sections.column_at(key, float(section.columns.distance_m[30])), 20.0),
    ]


def test_a_preview_cannot_take_a_pick(opened):
    plugin, key = opened
    session = plugin.session
    profile = plugin.profile_dock
    other = session.add_cut("A", [(1.0, 2.0), (5.0, 2.0)])
    session.set_preview(other, 3)
    errors = []
    profile.error.connect(errors.append)
    profile._pick(3, T)
    assert errors and "preview" in errors[0]
    assert _rows(plugin) == []
    with pytest.raises(ValueError):
        session.add_cut_pick(other, 3, 1.0, T, "{}")
    assert _rows(plugin) == []


def test_add_cut_pick_refuses_a_line_key_and_clamps_the_distance(opened):
    plugin, key = opened
    session = plugin.session
    with pytest.raises(ValueError):
        session.add_cut_pick(session.keys()[0], 1, 1.0, T, "{}")
    with pytest.raises(ValueError):
        session.add_cut_pick(key, 1, 1.0, float("nan"), "{}")
    pick = session.add_cut_pick(key, 400, 99.0, T, "{}")
    assert isinstance(pick, Pick) and pick.distance_m == pytest.approx(4.0)
    assert pick.time_ns == T and pick.trace == 400
    assert is_cut_key(pick.line_key)


def test_a_cut_pick_with_no_velocity_anywhere_has_no_depth(opened):
    plugin, key = opened
    session = plugin.session
    for line_key in session.keys_on_grid("A"):
        session.remove_lines([line_key])
    assert session.derived_cut_pick_fields(key, 1.0, T) == (None, None)


def test_a_pick_takes_its_distance_from_the_section_on_screen(opened):
    plugin, key = opened
    messages = []
    plugin.message = lambda text, level=None, title="nsgeo": messages.append(text)
    # Another cut is open: nothing is shown for `key`, so there is no column to take.
    other = plugin.session.add_cut("A", [(1.0, 2.0), (5.0, 2.0)])
    plugin.session.open_line(other)
    plugin._on_pick_requested(key, 12, T)
    assert _rows(plugin) == [] and messages and "no section" in messages[-1]
    # The section on screen is the one clicked, even when the service would answer differently.
    plugin.session.open_line(key)
    shown = plugin.profile_dock.shown_cut_section(key)
    assert shown is not None
    plugin.cut_sections.section = lambda *a, **k: "ignored"
    plugin._on_pick_requested(key, 12, T)
    (row,) = _rows(plugin)
    assert row["distance_m"] == pytest.approx(float(shown.columns.distance_m[12]))


def test_a_cut_pick_with_a_null_distance_is_left_alone_across_a_grid_move(opened, message_log):
    """The row has nowhere to follow from: its geometry, depth and velocity stay exactly as
    written, and nothing raises (cut spec §4.8)."""
    from qgis.core import NULL

    plugin, key = opened
    session = plugin.session
    _pick_at(plugin, key, 12)
    layer = plugin.layers.layers["picks"]
    (row,) = _rows(plugin)
    column = layer.fields().indexFromName("distance_m")
    assert layer.dataProvider().changeAttributeValues({row.id(): {column: NULL}})
    (row,) = _rows(plugin)
    assert row["distance_m"] == NULL
    before = (
        row.geometry().asPoint().x(),
        row.geometry().asPoint().y(),
        row["depth_m"],
        row["velocity_m_ns"],
    )
    grid = session.grid("A")
    session.replace_grid(dataclasses.replace(grid, origin=(grid.origin[0] + 1.0, grid.origin[1])))
    (after,) = _rows(plugin)
    point = after.geometry().asPoint()
    assert (point.x(), point.y(), after["depth_m"], after["velocity_m_ns"]) == before
    assert after["distance_m"] == NULL
    assert not [m for m in message_log if "could not" in m or "failed" in m]
