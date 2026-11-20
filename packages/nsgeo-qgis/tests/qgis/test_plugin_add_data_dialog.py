"""Add data: one dialog, a Grid page and a GPS page, the switch between them
(M17b Task 4, #134, decision 15)."""

from __future__ import annotations

import math

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
from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject, QgsSettings
from qgis.PyQt.QtCore import QEvent
from qgis.PyQt.QtWidgets import QMessageBox

LAT0, LON0 = 45.2, 10.5
M_PER_DEG = 6_371_000.0 * 3.141592653589793 / 180.0
GRID_A = Grid("A", (500_000.0, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32632", 0.5)
NO_GRID = "This site has no grid yet. Add one with Add grid…, or place the lines by GPS."


def name_it(dialog, name="N1"):
    """Name the new grid a GPS import makes and type its spacing (one file: nothing to measure)."""
    dialog.gps_page.name_edit.setText(name)
    dialog.gps_page.spacing.setValue(0.5)


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
    assert d.windowTitle() == d.gps_page.title() == "Add GPR data into A"  # opened on A
    d.set_mode(GRID)
    assert d.windowTitle() == "Add GPR data into A"
    d.reject()


def test_the_switch_buttons_keep_their_place_as_the_note_comes_and_goes(session, tmp_path):
    # Walkthrough W2: hiding the GPS note must not widen or move the buttons.
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.show()
    QgsApplication.processEvents()
    before = (d.grid_button.geometry(), d.gps_button.geometry())
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    QgsApplication.processEvents()
    assert d.gps_note.isVisible()
    assert (d.grid_button.geometry(), d.gps_button.geometry()) == before
    d.set_mode(GPS)
    QgsApplication.processEvents()
    assert not d.gps_note.isVisible()
    assert (d.grid_button.geometry(), d.gps_button.geometry()) == before
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
    assert d.import_button.text() == "Import 0 line(s) into A"
    assert not d.import_button.isEnabled()
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
    d = AddDataDialog(session, mode=GPS)
    d.add_files([gps_file(raw, "FILE__001.DZT")])
    name_it(d)
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
    gps = AddDataDialog(session, mode=GPS)
    gps.add_files([gps_file(raw, "FILE__001.DZT")])
    name_it(gps)
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
    dlg = AddDataDialog(plugin.session, mode=GPS)
    dlg.add_files([path])
    name_it(dlg)
    dlg.accept()
    (key,) = plugin.session.keys()
    plugin.session.move_lines([key], "B")
    plugin.survey_dock.import_requested.emit("B")
    d = plugin._add_data_dialog
    assert d is not None and d.mode() == GPS  # B holds only GPS lines
    QgsSettings().setValue(MODE_KEY, GRID)
    plugin.survey_dock.import_requested.emit("A")  # raised, no files: switched to A's mode
    assert plugin._add_data_dialog is d and d.mode() == GRID
    assert d.grid_page.grid_combo.currentData() == "A"
    d.reject()


def test_the_toolbar_opens_gps_on_new_grid_and_grid_on_the_panels_grid(
    plugin, tmp_path, monkeypatch
):
    # Walkthrough W5: the toolbar's GPR… opens GPS mode on New grid; the Survey
    # panel's grid stays the Grid page's target. Raising the open dialog keeps it so.
    (tmp_path / "site").mkdir()
    plugin.session.new_site(tmp_path / "site")
    plugin.session.add_grid(GRID_A)
    monkeypatch.setattr(plugin.survey_dock, "target_grid_id", lambda: "A")
    QgsSettings().setValue(MODE_KEY, GPS)
    plugin.act_add_gpr.trigger()
    d = plugin._add_data_dialog
    assert d is not None and d.mode() == GPS
    assert d.gps_page.target() is None and d.gps_page.target_combo.currentText() == "New grid"
    assert d.grid_page.grid_combo.currentData() == "A"
    plugin.act_add_gpr.trigger()  # raised, no files
    assert plugin._add_data_dialog is d and d.gps_page.target() is None
    plugin.survey_dock.import_requested.emit("A")  # a grid's own Add GPR data…: that grid
    assert d.gps_page.target() == "A"
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


# ---- the grids move under an open dialog -------------------------------------------


def test_a_grid_added_under_a_gridless_dialog_fills_the_combo_and_enables_import(
    bare_session, tmp_path
):
    d = AddDataDialog(bare_session, mode=GRID)
    d.add_files([synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")])
    assert d.grid_page.grid_combo.count() == 0 and not d.import_button.isEnabled()
    bare_session.add_grid(GRID_A)
    assert d.grid_page.grid_combo.currentData() == "A"
    assert d.import_button.isEnabled() and d.import_button.text() == "Import 1 line(s) into A"
    assert d.windowTitle() == "Add GPR data into A"
    assert d.grid_page.status.text() == ""
    d.reject()


def test_retarget_goes_ahead_while_the_dialog_has_files_but_no_grid(bare_session, tmp_path):
    d = AddDataDialog(bare_session, mode=GRID)
    d.add_files([synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")])
    d.grid_page.session.add_grid(GRID_A)  # the combo fills with A
    bare_session.add_grid(_grid("B", 600_000.0))
    assert d.grid_page.grid_combo.currentData() == "A"
    d.retarget("B")  # files and a grid now: left alone
    assert d.grid_page.grid_combo.currentData() == "A"
    d.reject()
    d = AddDataDialog(bare_session, grid_id="A", mode=GRID)
    d.add_files([synthetic_dzt(tmp_path / "raw", "FILE__002.DZT")])
    d.grid_page.grid_combo.clear()  # no grid selected, as on a gridless site
    d.retarget("B")
    assert d.grid_page.grid_combo.currentData() == "B"
    d.reject()


def test_an_added_grid_leaves_a_chosen_target_and_its_edits_alone(session, tmp_path):
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.add_files([synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT") for i in (1, 2)])
    d.grid_page.set_offset(1, 3.25)
    session.add_grid(_grid("B", 600_000.0))
    assert d.grid_page.grid_combo.count() == 2
    assert d.grid_page.grid_combo.currentData() == "A"
    assert d.grid_page.rows[1].offset == 3.25
    d.reject()


def test_a_grid_removed_under_the_dialog_leaves_the_combo_and_import_refuses(session, tmp_path):
    session.add_grid(_grid("B", 600_000.0))
    d = AddDataDialog(session, grid_id="A", mode=GRID)
    d.add_files([synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")])
    session.remove_grid("A")
    assert d.grid_page.grid_combo.findData("A") < 0
    d.accept()  # the combo fell back to B: it must not import there
    assert "no longer exists" in d.grid_page.status.text()
    assert session.keys() == []
    d.reject()
    only = AddDataDialog(session, grid_id="B", mode=GRID)
    only.add_files([synthetic_dzt(tmp_path / "raw", "FILE__002.DZT")])
    session.remove_grid("B")
    assert only.grid_page.grid_combo.count() == 0
    only.accept()
    assert "no longer exists" in only.grid_page.status.text()
    only.reject()


def test_the_gps_page_opens_on_the_grid_the_dialog_was_opened_for(session):
    d = AddDataDialog(session, grid_id="A", mode=GPS)
    assert d.gps_page.target() == "A" and d.gps_page.target_combo.currentText() == "A"
    d.reject()
    d = AddDataDialog(session, mode=GPS)
    assert d.gps_page.target() is None  # New grid
    d.retarget("A")
    assert d.gps_page.target() == "A"
    d.reject()


# ---- files GPS cannot place: the hand-on (M17b Task 6) ---------------------------
from nsgeo_qgis.ui.import_dialog import COL_DIR, COL_NOTE, COL_OFFSET  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

COS_LAT = math.cos(math.radians(LAT0))
DLON = 0.5 / (M_PER_DEG * COS_LAT)  # half a metre east, in degrees of longitude
AMBER = QColor("#fbf3df")


def survey(folder, missing=(3, 6), n=10):
    """`n` files one half-metre apart, due north; the files at `missing` have no DZG."""
    paths = []
    for i in range(n):
        name = f"FILE__{i:03d}.DZT"
        if i in missing:
            paths.append(synthetic_dzt(folder, name, traces_per_metre=10.0))
        else:
            track = [
                (t, LAT0 + t * 0.1 / M_PER_DEG, LON0 + i * DLON, 4) for t in (25, 75, 125, 175)
            ]
            paths.append(synthetic_gps_dzt(folder, name, track, traces_per_metre=10.0))
    return paths


def cell(page, r, col):
    return page.table.item(r, col)


def handed_on_dialog(session, tmp_path):
    batches: list[list] = []
    d = AddDataDialog(session, mode=GPS)
    d.imported.connect(batches.append)
    d.add_files(survey(tmp_path / "raw"))
    d.gps_page.target_combo.setCurrentIndex(0)  # New grid
    d.gps_page.name_edit.setText("G4")
    return d, batches


def test_files_gps_cannot_place_are_handed_on_to_grid_mode_with_a_guess(session, tmp_path):
    d, batches = handed_on_dialog(session, tmp_path)
    d.accept()
    assert len(session.site.lines) == 8
    assert d.result() == 0  # not accepted: the dialog stays open
    assert d.mode() == GRID
    page = d.grid_page
    assert page.grid_combo.currentData() == "G4"
    assert [r.path.name for r in page.rows] == ["FILE__003.DZT", "FILE__006.DZT"]
    assert [r.offset for r in page.rows] == pytest.approx([1.75, 3.25], abs=0.02)
    assert [r.direction for r in page.rows] == [-1, -1]
    for r in range(2):
        for col in (COL_OFFSET, COL_DIR):
            assert cell(page, r, col).background().color() == AMBER
    assert cell(page, 0, COL_NOTE).text() == "between FILE__002 and FILE__004"
    assert cell(page, 1, COL_NOTE).text() == "between FILE__005 and FILE__007"
    assert page.banner.isVisibleTo(d)
    assert page.banner.text() == (
        "8 GPS line(s) are in G4. GPS could not place 2 file(s): place them by the tapes, "
        "or Cancel to leave them out. Offsets and directions are guessed from the GPS lines "
        "either side of each one."
    )
    assert not page.first_offset.isVisibleTo(d)
    assert not page.direction_alternate.isVisibleTo(d)
    texts = [t for t, _ in batches[0]]
    assert texts[0].startswith("imported 8 GPS line(s) into new grid G4")
    assert not any("not imported" in t for t in texts)
    assert d.import_button.text() == "Import 2 line(s) into G4"


def test_switching_mode_ends_the_hand_on_on_the_grid_page_too(session, tmp_path):
    d, _ = handed_on_dialog(session, tmp_path)
    d.accept()
    page = d.grid_page
    assert page.banner.isVisibleTo(d) and not page.first_offset.isVisibleTo(d)
    d.set_mode(GPS)
    d.set_mode(GRID)
    assert not page.banner.isVisibleTo(d)
    assert page.first_offset.isVisibleTo(d)
    assert page.direction_alternate.isVisibleTo(d)
    d.reject()


def test_importing_the_handed_on_files_adds_tape_lines_and_closes(session, tmp_path):
    d, batches = handed_on_dialog(session, tmp_path)
    d.accept()
    d.accept()
    lines = session.site.lines
    assert len(lines) == 10
    tape = [ln for ln in lines if isinstance(ln.placement, GridPlacement)]
    assert len(tape) == 2 and {ln.placement.grid_id for ln in tape} == {"G4"}
    assert d.result() == 1  # accepted
    assert len(batches) == 2


def test_cancel_after_the_hand_on_leaves_the_gps_lines_and_adds_nothing(session, tmp_path):
    d, _ = handed_on_dialog(session, tmp_path)
    d.accept()
    d.reject()
    assert len(session.site.lines) == 8
    assert not any(isinstance(ln.placement, GridPlacement) for ln in session.site.lines)


def test_editing_a_guessed_offset_clears_its_amber_and_note(session, tmp_path):
    d, _ = handed_on_dialog(session, tmp_path)
    d.accept()
    page = d.grid_page
    page.set_offset(0, 2.0)
    assert cell(page, 0, COL_OFFSET).background().color() != AMBER
    assert cell(page, 0, COL_NOTE).text() == ""
    assert cell(page, 1, COL_NOTE).text() != ""


def test_editing_a_guessed_direction_clears_the_rows_guess(session, tmp_path):
    d, _ = handed_on_dialog(session, tmp_path)
    d.accept()
    page = d.grid_page
    page.set_direction(0, 1)
    assert page.rows[0].guess == ""
    assert cell(page, 0, COL_DIR).background().color() != AMBER
    assert cell(page, 0, COL_NOTE).text() == ""
    assert page.rows[1].guess != ""


def test_an_already_in_the_site_refusal_is_not_handed_on(session, tmp_path):
    raw = tmp_path / "raw"
    paths = survey(raw, missing=())
    d = AddDataDialog(session, mode=GPS)
    d.add_files(paths)
    d.gps_page.name_edit.setText("G4")
    d.accept()
    assert d.result() == 1
    (extra,) = survey(tmp_path / "more", missing=(), n=1)
    d2 = AddDataDialog(session, mode=GPS)
    d2.add_files([paths[0], extra])
    d2.gps_page.target_combo.setCurrentIndex(d2.gps_page.target_combo.findData("G4"))
    d2.accept()
    assert len(session.site.lines) == 11
    assert d2.result() == 1 and d2.mode() == GPS  # closed as before: nothing to hand on


def test_the_hand_on_import_does_not_change_the_remembered_mode(session, tmp_path):
    d, _ = handed_on_dialog(session, tmp_path)
    d.accept()
    assert QgsSettings().value(MODE_KEY) == GPS
    d.accept()  # the tape Import of the leftovers
    assert QgsSettings().value(MODE_KEY) == GPS


def test_a_failing_guess_still_hands_the_files_on_without_one(session, tmp_path, monkeypatch):
    import nsgeo_qgis.ui.add_data_dialog as mod

    def boom(*_a, **_k):
        raise RuntimeError("no guess today")

    monkeypatch.setattr(mod, "guess_tape_rows", boom)
    d, batches = handed_on_dialog(session, tmp_path)
    d.accept()
    assert len(session.site.lines) == 8 and d.mode() == GRID
    assert [r.path.name for r in d.grid_page.rows] == ["FILE__003.DZT", "FILE__006.DZT"]
    assert all(r.guess == "" for r in d.grid_page.rows)
    assert "could not import" not in d.gps_page.status.text()
    assert len(batches) == 1


def test_a_dzt_that_cannot_be_read_stays_in_the_gps_summary_not_the_hand_on(session, tmp_path):
    paths = survey(tmp_path / "raw")
    bad = tmp_path / "raw" / "FILE__099.DZT"
    bad.write_bytes(b"not a dzt")
    d = AddDataDialog(session, mode=GPS)
    batches: list[list] = []
    d.imported.connect(batches.append)
    d.add_files([*paths, bad])
    d.gps_page.name_edit.setText("G4")
    d.accept()
    assert [r.path.name for r in d.grid_page.rows] == ["FILE__003.DZT", "FILE__006.DZT"]
    texts = [t for t, _ in batches[0]]
    assert any(t.startswith("not imported: FILE__099.DZT (could not read it") for t in texts)
    assert not any("FILE__003" in t and "not imported" in t for t in texts)
