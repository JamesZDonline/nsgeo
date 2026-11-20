"""Add data: one dialog, a Grid page and a GPS page, the switch between them
(M17b Task 4, #134, decision 15)."""

from __future__ import annotations

import pytest
from nsgeo.geometry import Grid, GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.add_data_dialog import (
    GPS,
    GRID,
    MODE_KEY,
    AddDataDialog,
    opening_mode,
)
from plugin_testing import synthetic_dzt, synthetic_gps_dzt
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsSettings
from qgis.PyQt.QtCore import QEvent
from qgis.PyQt.QtWidgets import QMessageBox

LAT0, LON0 = 45.2, 10.5
M_PER_DEG = 6_371_000.0 * 3.141592653589793 / 180.0
GRID_A = Grid("A", (500_000.0, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32632", 0.5)
NO_GRID = "This site has no grid yet. Add one with Add grid…, or place the lines by GPS."


def gps_file(folder, name, fixes=True):
    track = [(t, LAT0 + t * 0.1 / M_PER_DEG, LON0, 4) for t in (25, 75, 125, 175)] if fixes else []
    return synthetic_gps_dzt(folder, name, track, traces_per_metre=10.0)


@pytest.fixture(autouse=True)
def _mode_memory(qgis_app):
    """Nothing remembered at the start (conftest puts the user's value back)."""
    QgsSettings().remove(MODE_KEY)
    yield
    qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def _project_utm(qgis_app):
    project = QgsProject.instance()
    old = project.crs()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:32632"))
    yield
    project.setCrs(old)


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    (tmp_path / "site").mkdir()
    s.new_site(tmp_path / "site")
    s.add_grid(GRID_A)
    return s


@pytest.fixture
def bare_session(qgis_app, tmp_path):
    s = SiteSession()
    (tmp_path / "site").mkdir()
    s.new_site(tmp_path / "site")
    return s


# ---- the switch ----------------------------------------------------------------


def test_grid_is_checked_first_when_nothing_is_remembered(session):
    d = AddDataDialog(session, grid_id="A")
    assert d.mode() == GRID
    assert d.grid_button.isChecked() and not d.gps_button.isChecked()
    assert (d.grid_button.text(), d.gps_button.text()) == ("Grid", "GPS")
    d.reject()


def test_set_mode_swaps_the_page_retitles_and_hides_the_note(session, tmp_path):
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.show()
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    assert d.gps_note.isVisibleTo(d)
    d.set_mode(GPS)
    assert d.mode() == GPS and d.gps_button.isChecked() and not d.grid_button.isChecked()
    assert d.gps_page.isVisibleTo(d) and not d.grid_page.isVisibleTo(d)
    assert not d.gps_note.isVisibleTo(d)
    assert d.windowTitle() == d.gps_page.title() == "Add GPR data"
    d.set_mode(GRID)
    assert d.windowTitle() == "Add GPR data into A"
    d.reject()


def test_the_switch_buttons_are_exclusive(session):
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.gps_button.click()
    assert d.mode() == GPS and not d.grid_button.isChecked()
    d.gps_button.click()  # clicking the checked one does not uncheck it
    assert d.gps_button.isChecked()
    d.grid_button.click()
    assert d.mode() == GRID and not d.gps_button.isChecked()
    d.reject()


def test_the_import_button_follows_the_current_page(session, tmp_path):
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    assert not d.import_button.isEnabled()
    d.add_files([synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT") for i in (1, 2)])
    assert d.import_button.text() == "Import 2 line(s) into A" and d.import_button.isEnabled()
    d.set_mode(GPS)  # tape-only files: GPS has nothing ready
    assert d.import_button.text() == "Import" and not d.import_button.isEnabled()
    d.reject()


# ---- carrying the files across -------------------------------------------------


def test_the_files_and_their_edits_cross_the_switch_both_ways(session, tmp_path):
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT", n_traces=60) for i in (1, 2, 3)]
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.add_files(files)
    g = d.grid_page
    g.set_offset(1, 3.25)
    g.set_direction(2, -1 if g.rows[2].direction == 1 else 1)
    flipped = g.rows[2].direction
    d.set_mode(GPS)
    assert [p.name for p in d.gps_page.paths()] == [f.name for f in files]
    d.set_mode(GRID)
    assert d.grid_page.rows[1].offset == 3.25 and d.grid_page.rows[1].offset_edited
    assert d.grid_page.rows[2].direction == flipped and d.grid_page.rows[2].direction_edited
    d.reject()


def test_removing_a_file_on_the_gps_page_drops_it_from_the_grid_page(session, tmp_path):
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT", n_traces=60) for i in (1, 2, 3)]
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.add_files(files)
    d.grid_page.set_offset(2, 4.5)
    d.set_mode(GPS)
    d.gps_page.table.selectRow(0)
    d.gps_page.remove_selected()
    d.set_mode(GRID)
    assert [r.path.name for r in d.grid_page.rows] == ["FILE__002.DZT", "FILE__003.DZT"]
    assert d.grid_page.rows[1].offset == 4.5 and d.grid_page.rows[1].offset_edited
    d.reject()


def test_the_gps_pages_destagger_survives_a_round_trip(session, tmp_path):
    d = AddDataDialog(session, grid_id="A", mode=GPS)
    d.gps_page.shift.setValue(0.25)
    d.set_mode(GRID)
    d.set_mode(GPS)
    assert d.gps_page.shift.value() == 0.25
    d.reject()


# ---- the GPS note ------------------------------------------------------------------


def test_the_note_counts_files_with_a_usable_dzg(session, tmp_path):
    raw = tmp_path / "raw"
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.show()
    assert not d.gps_note.isVisibleTo(d)
    d.add_files(
        [
            gps_file(raw, "FILE__001.DZT"),
            gps_file(raw, "FILE__002.DZT"),
            synthetic_dzt(raw, "FILE__003.DZT"),
        ]
    )
    assert d.gps_note.text() == "2 of 3 files have a GPS log beside them."
    assert d.gps_note.isVisibleTo(d)
    d.reject()


def test_a_dzg_with_no_rtk_fix_does_not_count(session, tmp_path):
    raw = tmp_path / "raw"
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.show()
    d.add_files([gps_file(raw, "FILE__001.DZT", fixes=False)])
    assert not d.gps_note.isVisibleTo(d)
    d.reject()


def test_one_file_with_a_log_reads_in_the_singular(session, tmp_path):
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.show()
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    assert d.gps_note.text() == "This file has a GPS log beside it."
    d.reject()


def test_the_note_never_shows_in_gps_mode(session, tmp_path):
    d = AddDataDialog(session, grid_id="A", mode=GPS)
    d.show()
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    assert not d.gps_note.isVisibleTo(d)
    d.reject()


# ---- a site with no grid -----------------------------------------------------------


def test_grid_mode_on_a_site_with_no_grid_says_so_and_gps_is_still_offered(bare_session, tmp_path):
    d = AddDataDialog(bare_session, mode=GRID)
    assert d.grid_page.status.text() == NO_GRID
    assert not d.import_button.isEnabled()
    assert d.windowTitle() == "Add GPR data"
    d.add_files([synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")])
    assert not d.import_button.isEnabled()
    assert d.gps_button.isEnabled()
    d.set_mode(GPS)
    assert d.mode() == GPS
    d.reject()


# ---- mode memory -------------------------------------------------------------------


def test_a_grid_import_remembers_grid_and_a_gps_import_remembers_gps(session, tmp_path):
    raw = tmp_path / "raw"
    d = AddDataDialog(session, grid_id="A", mode=GPS)
    d.add_files([gps_file(raw, "FILE__001.DZT")])
    d.accept()
    assert QgsSettings().value(MODE_KEY) == GPS
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.add_files([synthetic_dzt(raw, "FILE__002.DZT")])
    d.accept()
    assert QgsSettings().value(MODE_KEY) == GRID


def test_cancel_and_a_refused_import_write_nothing(session, tmp_path):
    d = AddDataDialog(session, grid_id="A", mode=GPS)
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    d.reject()
    assert QgsSettings().value(MODE_KEY, None) is None
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.accept()  # nothing to import
    assert QgsSettings().value(MODE_KEY, None) is None
    d.reject()


def _grid(gid, east):
    return Grid(gid, (east, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32632", 0.5)


def test_opening_mode_follows_what_a_grid_holds(session, tmp_path):
    for gid, east in (("B", 600_000.0), ("C", 700_000.0)):
        session.add_grid(_grid(gid, east))
    raw = tmp_path / "raw"
    gps = AddDataDialog(session, grid_id="A", mode=GPS)
    gps.add_files([gps_file(raw, "FILE__001.DZT")])
    gps.accept()
    (gps_key,) = session.keys()
    session.move_lines([gps_key], "B")  # B: all GPS
    tape_path = synthetic_dzt(raw, "FILE__002.DZT")
    session.add_lines([Line.open(tape_path, GridPlacement("C", "y", 0.25, 0.0, 1, "t"))])
    for remembered in (GRID, GPS):
        QgsSettings().setValue(MODE_KEY, remembered)
        assert opening_mode(session, "B") == GPS  # all GPS
        assert opening_mode(session, "C") == GRID  # all tape
        assert opening_mode(session, "A") == remembered  # empty
        assert opening_mode(session, None) == remembered  # no grid
    session.move_lines([gps_key], "C")  # C: tape and GPS
    QgsSettings().setValue(MODE_KEY, GPS)
    assert opening_mode(session, "C") == GPS
    QgsSettings().setValue(MODE_KEY, GRID)
    assert opening_mode(session, "C") == GRID  # mixed: the remembered mode


# ---- the plugin --------------------------------------------------------------------


@pytest.fixture
def plugin(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    p = nsgeo_qgis.classFactory(fake_iface)
    p.initGui()
    yield p
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    p.unload()


def test_the_toolbar_has_an_add_data_button_in_place_of_the_two_imports(
    fake_iface, tmp_path, answer_modal
):
    import nsgeo_qgis
    from qgis.PyQt.QtWidgets import QToolButton

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    button = plugin.toolbar.widgetForAction(plugin.act_add_data)
    assert isinstance(button, QToolButton) and button.text() == "Add data"
    assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert button.toolTip() == (
        "Add survey data to the site: GPR lines placed by a grid's tapes or by GPS."
    )
    assert [a.text() for a in button.menu().actions()] == ["GPR…"]
    actions = plugin.toolbar_actions
    assert actions.index(plugin.act_add_data) == actions.index(plugin.act_add_grid) + 1
    texts = [a.text() for a in plugin.toolbar.actions()]
    assert "Import DZT…" not in texts and "Import GPS lines…" not in texts
    assert not plugin.act_add_data.isEnabled()
    (tmp_path / "site").mkdir()
    plugin.session.new_site(tmp_path / "site")
    assert plugin.act_add_data.isEnabled()
    plugin.session.close_site()
    assert not plugin.act_add_data.isEnabled()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
    assert plugin.act_add_data is None and plugin._add_data_dialog is None


def test_gpr_opens_one_dialog_and_a_second_press_raises_it(plugin, tmp_path):
    plugin.act_add_gpr.trigger()
    assert plugin._add_data_dialog is None  # no site: nothing opens
    (tmp_path / "site").mkdir()
    plugin.session.new_site(tmp_path / "site")
    plugin.session.add_grid(GRID_A)
    plugin.act_add_gpr.trigger()
    first = plugin._add_data_dialog
    assert first is not None and first.isVisible() and first.mode() == GRID
    plugin.act_add_gpr.trigger()
    assert plugin._add_data_dialog is first
    first.reject()
    assert plugin._add_data_dialog is None


def test_the_survey_panels_add_gpr_data_opens_it_on_that_grid_in_its_mode(plugin, tmp_path):
    (tmp_path / "site").mkdir()
    plugin.session.new_site(tmp_path / "site")
    plugin.session.add_grid(GRID_A)
    plugin.session.add_grid(_grid("B", 600_000.0))
    plugin.survey_dock.import_requested.emit("B")
    d = plugin._add_data_dialog
    assert d is not None and d.grid_page.grid_combo.currentData() == "B"
    d.reject()
    path = gps_file(tmp_path / "raw", "FILE__001.DZT")
    dlg = AddDataDialog(plugin.session, grid_id="B", mode=GPS)
    dlg.add_files([path])
    dlg.accept()
    (key,) = plugin.session.keys()
    plugin.session.move_lines([key], "B")
    plugin.survey_dock.import_requested.emit("B")
    d = plugin._add_data_dialog
    assert d is not None and d.mode() == GPS  # B holds only GPS lines
    QgsSettings().setValue(MODE_KEY, GRID)
    plugin.survey_dock.import_requested.emit("A")  # raised, no files: switched to A's mode
    assert plugin._add_data_dialog is d and d.mode() == GRID
    d.reject()


def test_imported_batches_reach_the_message_bar(plugin, tmp_path):
    from qgis.core import Qgis

    (tmp_path / "site").mkdir()
    plugin.session.new_site(tmp_path / "site")
    plugin.session.add_grid(GRID_A)
    shown: list = []
    plugin.message = lambda text, level=None, title="nsgeo": shown.append((text, level))  # type: ignore[method-assign]
    plugin.open_add_data_dialog("A", GRID)
    d = plugin._add_data_dialog
    d.add_files([synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")])
    d.accept()
    assert [t for t, _ in shown] == ["imported 1 line(s)"]
    assert shown[0][1] == Qgis.MessageLevel.Info


def test_a_dialog_destroyed_without_finished_is_cleared_too(plugin, tmp_path):
    from qgis.PyQt.QtWidgets import QApplication

    (tmp_path / "site").mkdir()
    plugin.session.new_site(tmp_path / "site")
    plugin.session.add_grid(GRID_A)
    plugin.open_add_data_dialog("A", GRID)
    dialog = plugin._add_data_dialog
    dialog.setParent(None)
    dialog.deleteLater()
    QApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
    assert plugin._add_data_dialog is None
    plugin.open_add_data_dialog("A", GRID)
    assert plugin._add_data_dialog is not None and plugin._add_data_dialog is not dialog
