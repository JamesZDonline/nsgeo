from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.survey_dock import ROLE_ID, ROLE_KIND, SurveyDock
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QFileDialog

GRID = Grid(
    "A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5, velocity=VelocityModel.constant(0.08)
)


@pytest.fixture
def dock(qgis_app, tmp_path):
    session = SiteSession()
    dock = SurveyDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT")
        lines.append(
            Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1 if i % 2 == 0 else -1, p.stem))
        )
    session.add_lines(lines)
    return session, dock


def test_tree_mirrors_site_grids_and_lines(dock):
    session, dock = dock
    root = dock.tree.topLevelItem(0)
    assert root.text(0) == session.site_name
    grid_item = root.child(0)
    assert grid_item.data(0, ROLE_KIND) == "grid" and grid_item.data(0, ROLE_ID) == "A"
    assert "0.080" in grid_item.text(0)
    assert grid_item.childCount() == 3
    line_item = grid_item.child(1)
    assert line_item.data(0, ROLE_KIND) == "line"
    assert line_item.data(0, ROLE_ID) == "raw/FILE__002.DZT"
    assert (
        "FILE__002" in line_item.text(0)
        and "0.50" in line_item.text(0)
        and "↓" in line_item.text(0)
    )


def test_tree_follows_session_changes(dock):
    session, dock = dock
    session.remove_line("raw/FILE__003.DZT")
    assert dock.tree.topLevelItem(0).child(0).childCount() == 2
    session.add_grid(Grid("B", (0.0, 0.0), 0.0, 1.0, 1.0, "EPSG:32616", 0.5))
    assert dock.tree.topLevelItem(0).childCount() == 2
    assert "empty" in dock.tree.topLevelItem(0).child(1).text(0)


def test_clicking_a_line_opens_it_and_selection_follows_the_session(dock):
    session, dock = dock
    item = dock.item_for_key("raw/FILE__002.DZT")
    dock.tree.itemClicked.emit(item, 0)
    assert session.current_key == "raw/FILE__002.DZT"
    session.open_line("raw/FILE__003.DZT")
    assert dock.tree.currentItem() is dock.item_for_key("raw/FILE__003.DZT")


def test_status_shows_dirty_state(dock):
    session, dock = dock
    assert "modified" in dock.status.text()
    session.save()
    assert "modified" not in dock.status.text()
    assert "survey.nsgeo.json" in dock.status.text()


def test_line_velocity_override_is_marked(dock):
    session, dock = dock
    session.set_line_velocity("raw/FILE__001.DZT", VelocityModel.constant(0.095))
    assert "v 0.095*" in dock.item_for_key("raw/FILE__001.DZT").text(0)


def test_context_actions_remove_lines_and_grids(dock):
    session, dock = dock
    dock.remove_line_action("raw/FILE__001.DZT", confirm=False)
    assert "raw/FILE__001.DZT" not in session.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
    with pytest.raises(ValueError):
        dock.remove_grid_action("A", confirm=False)


def test_closing_the_site_empties_the_tree(dock):
    session, dock = dock
    session.close_site()
    assert dock.tree.topLevelItemCount() == 0
    assert dock.status.text() == "no site open"


def test_plugin_wires_the_dock_and_file_actions(fake_iface, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    assert plugin.survey_dock in fake_iface.docks
    assert plugin.survey_dock.allowedAreas() & Qt.DockWidgetArea.LeftDockWidgetArea
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)
    assert plugin.save_with_prompt() is True
    assert not plugin.session.dirty
    plugin.unload()
    assert plugin.survey_dock is None


# ---- additional coverage: the "Get these right" requirements and the
# signal/slot failure-path hazard (see the module docstring in survey_dock.py
# and plugin.py) that the brief's own test list does not exercise. ----------


def test_time_triggered_lines_appear_in_the_tree_marked_not_omitted(dock, tmp_path):
    # GridPlacement.distance_along raises ValueError for a time-triggered
    # acquisition (traces_per_metre <= 0). Such a line has no geometry, but
    # it is still part of the site: it must show up here, distinguishable
    # from a placeable line, rather than silently vanishing from the tree
    # or taking the whole rebuild down with it.
    session, dock = dock
    p = synthetic_dzt(tmp_path / "raw", "FILE__TIME.DZT", traces_per_metre=0.0)
    line = Line.open(p, GridPlacement("A", "y", 2.0, 0.0, 1, p.stem))
    session.add_lines([line])
    grid_item = dock.tree.topLevelItem(0).child(0)
    assert grid_item.childCount() == 4  # not omitted
    item = dock.item_for_key("raw/FILE__TIME.DZT")
    assert item is not None
    assert "unplaced" in item.text(0)


def test_rebuild_survives_an_unexpected_error_and_leaves_an_honest_empty_tree(dock, monkeypatch):
    # A signal handler's exception never reaches whatever emitted the
    # signal (PyQt prints it to stderr and emit() returns as if nothing
    # happened), so rebuild() must catch its own failures: a half-built
    # tree would look complete and be silently wrong, which is worse than
    # an obviously empty one with a visible error.
    session, dock = dock

    def boom(_line):
        raise RuntimeError("simulated bug while building a line item")

    monkeypatch.setattr(dock, "_line_item", boom)
    session.add_grid(Grid("C", (0.0, 0.0), 0.0, 1.0, 1.0, "EPSG:32616", 0.5))
    assert dock.tree.topLevelItemCount() == 0
    assert "error" in dock.status.text().lower()


def test_remove_line_action_reraises_rather_than_silently_dropping_a_missing_key(dock):
    # Symmetric with remove_grid_action's already-tested ValueError path:
    # a programmatic caller (confirm=False) must see the failure, not have
    # it disappear along with the (nonexistent) line.
    session, dock = dock
    with pytest.raises(KeyError):
        dock.remove_line_action("raw/NOPE.DZT", confirm=False)


def test_new_site_reports_unexpected_errors_without_crashing_or_losing_state(
    fake_iface, tmp_path, monkeypatch
):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path))
    )

    def boom(*_a, **_k):
        raise OSError("simulated read-only filesystem")

    monkeypatch.setattr(plugin.session, "new_site", boom)
    plugin.new_site()  # must not raise: this is a QAction.triggered slot
    assert not plugin.session.is_open
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "simulated read-only filesystem" in item.text()
    plugin.unload()


def test_save_with_prompt_reports_unexpected_errors_and_keeps_the_site_dirty(
    fake_iface, tmp_path, monkeypatch
):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)
    assert plugin.session.dirty

    def boom(**_kw):
        raise OSError("simulated disk-full error")

    monkeypatch.setattr(plugin.session, "save", boom)
    assert plugin.save_with_prompt() is False
    assert plugin.session.dirty  # never silently marked clean on a failed save
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "simulated disk-full error" in item.text()
    # No plugin.unload() here: the site is deliberately left dirty, and
    # unload() itself would then show a real "save before continuing?"
    # confirmation prompt (ask_first=True) -- a modal that would block
    # forever under the offscreen platform with nothing to answer it.
    # That prompt is independent of save()'s own behaviour, so undoing the
    # monkeypatch would not help either. This test's job ends at the
    # assertions above; plugin/session cleanup is not part of it.


def test_unload_releases_every_toolbar_and_menu_action(fake_iface):
    # Task 5 fixed this leak for the menu's About action (removePluginMenu
    # alone drops the Python reference but never deletes the underlying
    # QAction). The toolbar actions this task adds are not children of the
    # toolbar itself (QToolBar.addAction does not reparent), so unload()
    # must deleteLater() each of them explicitly too, not just tear down
    # the toolbar that displayed them.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    assert plugin.toolbar_actions and plugin.menu_actions
    assert plugin.act_new is not None
    plugin.unload()
    assert plugin.toolbar_actions == []
    assert plugin.menu_actions == []
    assert plugin.act_new is None
