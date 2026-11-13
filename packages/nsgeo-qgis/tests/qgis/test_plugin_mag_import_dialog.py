"""Import mag…: the dialog behind the toolbar button, its setup picture, and the plugin wiring."""

from __future__ import annotations

import dataclasses

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.mag import MagSetup
from nsgeo_qgis.plugin import NsgeoPlugin
from nsgeo_qgis.session import SURVEY_FILE
from nsgeo_qgis.ui.mag_import_dialog import MagImportDialog
from nsgeo_qgis.ui.mag_setup_picture import MagSetupPicture
from plugin_testing import synthetic_grad601
from qgis.PyQt.QtCore import QCoreApplication, QEvent
from qgis.PyQt.QtWidgets import QMessageBox

YES = QMessageBox.StandardButton.Yes
NO = QMessageBox.StandardButton.No


@pytest.fixture
def folder(mag_site):
    _, root = mag_site
    return root / "raw" / "mag"


@pytest.fixture
def dialog(mag_site):
    session, _ = mag_site
    d = MagImportDialog(session)
    yield d
    d.deleteLater()


def _fresh_grid(session, gid):
    session.add_grid(Grid(gid, (120.0, 100.0), 0.0, 4.0, 4.0, "EPSG:32616", 0.5, instrument="mag"))


def test_importing_a_file_puts_it_on_its_grid_with_the_setup(mag_site, dialog, folder):
    session, _ = mag_site
    dialog.add_files([synthetic_grad601(folder, "m2.dat")])
    assert dialog.row_grid(0) == "M2"
    chosen = dataclasses.replace(MagSetup(), far_x=True)
    dialog.set_setup(chosen)
    seen = []
    dialog.imported.connect(seen.append)
    dialog.accept()
    mag = session.mag_file_on("M2")
    assert mag is not None and mag.path.name == "m2.dat"
    assert mag.setup == chosen
    assert len(seen) == 1 and seen[0][0][1] == "M2"
    assert not dialog.isVisible()


def test_the_setup_is_remembered_for_the_next_import(mag_site, dialog, folder):
    session, _ = mag_site
    chosen = dataclasses.replace(MagSetup(), far_y=True, missing_run=6)
    dialog.add_files([synthetic_grad601(folder, "m2.dat")])
    dialog.set_setup(chosen)
    dialog.accept()
    assert session.mag_setup() == chosen
    assert MagImportDialog(session).setup() == chosen


def test_each_row_takes_the_next_empty_mag_grid(mag_site, dialog, folder):
    session, _ = mag_site
    _fresh_grid(session, "M3")
    dialog.add_files([synthetic_grad601(folder, "a.dat"), synthetic_grad601(folder, "b.dat")])
    assert [dialog.row_grid(0), dialog.row_grid(1)] == ["M2", "M3"]  # M1 holds a file


def test_a_row_with_no_free_grid_has_none_and_import_says_so(mag_site, dialog, folder):
    session, _ = mag_site
    dialog.add_files([synthetic_grad601(folder, "a.dat"), synthetic_grad601(folder, "b.dat")])
    assert [dialog.row_grid(0), dialog.row_grid(1)] == ["M2", None]
    dialog.accept()
    assert dialog.status.text() == "Choose a mag grid for b.dat."
    assert session.mag_file_on("M2") is None


def test_a_file_that_does_not_fit_asks_before_importing(mag_site, dialog, folder, answer_modal):
    session, _ = mag_site
    dialog.add_files([synthetic_grad601(folder, "big.dat", rows=60, readings=240)])
    assert "grid is 4 m along Y" in dialog.table.item(0, 4).text()
    calls = answer_modal(QMessageBox, "question", NO)
    dialog.accept()
    assert session.mag_file_on("M2") is None
    args = calls[0][0]
    assert args[1] == "Files do not fit their grids"
    assert args[2].startswith("1 file(s) do not fit their grids:\nbig.dat: 240 readings at 8 per")
    assert args[2].endswith("Import anyway? Nothing is cropped or stretched.")
    calls = answer_modal(QMessageBox, "question", YES)
    dialog.accept()
    mag = session.mag_file_on("M2")
    assert mag is not None and mag.n_readings == 240 and mag.n_rows == 60


def test_importing_onto_a_grid_with_a_file_asks_then_replaces(
    mag_site, dialog, folder, answer_modal
):
    session, _ = mag_site
    dialog.add_files([synthetic_grad601(folder, "new.dat")])
    dialog.set_row_grid(0, "M1")
    calls = answer_modal(QMessageBox, "question", NO)
    dialog.accept()
    assert session.mag_file_on("M1").path.name == "m1.dat"
    args = calls[0][0]
    assert args[1] == "Replace files"
    assert args[2] == "Replace the files already on these grids?\nM1: m1.dat → new.dat"
    answer_modal(QMessageBox, "question", YES)
    dialog.accept()
    assert session.mag_file_on("M1").path.name == "new.dat"


def test_two_files_on_one_grid_are_refused(mag_site, dialog, folder):
    session, _ = mag_site
    dialog.add_files([synthetic_grad601(folder, "a.dat"), synthetic_grad601(folder, "b.dat")])
    dialog.set_row_grid(1, "M2")
    expected = "a.dat and b.dat are both on grid M2; a mag grid holds one file."
    assert dialog.status.text() == expected
    dialog.accept()
    assert dialog.status.text() == expected
    assert session.mag_file_on("M2") is None


def test_a_bad_setup_is_reported_and_nothing_changes(mag_site, dialog, folder):
    session, _ = mag_site
    before = session.mag_setup()
    dialog.add_files([synthetic_grad601(folder, "a.dat")])
    dialog.separation_spin.setValue(0.7)
    with pytest.raises(ValueError, match="sensor separation"):
        dialog.setup()
    dialog.accept()
    assert dialog.status.text() == (
        "the sensor separation (0.7 m) must be a whole number of traverse spacings (0.5 m)"
    )
    assert session.mag_file_on("M2") is None
    assert session.mag_setup() == before


def test_an_unreadable_file_is_named_and_not_added(dialog, folder):
    folder.mkdir(parents=True, exist_ok=True)
    ragged = folder / "ragged.dat"
    ragged.write_bytes(b"1\t2\t3\r\n4\t5\r\n")
    dialog.add_files([ragged])
    assert dialog.table.rowCount() == 0
    assert dialog.status.text() == (
        "Could not read ragged.dat: ragged.dat: row 2 has 2 readings but row 1 has 3; "
        "this does not look like a Grad601 grid file"
    )


def test_import_after_the_site_was_replaced_adds_nothing(mag_site, dialog, folder, tmp_path):
    session, root = mag_site
    dialog.add_files([synthetic_grad601(folder, "a.dat")])
    other = tmp_path / "other"
    other.mkdir()
    session.new_site(other)
    dialog.accept()
    assert dialog.status.text() == "The site changed; nothing was imported."
    assert session.site.mag_files == []
    session.open_site(root / SURVEY_FILE)  # the old site again: a different Site object
    dialog.accept()
    assert dialog.status.text() == "The site changed; nothing was imported."
    assert session.mag_file_on("M2") is None


def test_import_after_the_site_was_closed_adds_nothing(mag_site, dialog, folder):
    session, _ = mag_site
    dialog.add_files([synthetic_grad601(folder, "a.dat")])
    session.close_site()
    dialog.accept()
    assert dialog.status.text() == "The site changed; nothing was imported."


def test_the_columns_follow_the_setup_and_the_grid(mag_site, dialog, folder):
    dialog.add_files([synthetic_grad601(folder, "a.dat", missing=((2, 3, 6),))])
    t = dialog.table
    assert [t.horizontalHeaderItem(c).text() for c in range(5)] == [
        "File",
        "Grid",
        "Size",
        "Missing",
        "Fits",
    ]
    assert t.item(0, 2).text() == "8 × 32"
    assert t.item(0, 3).text() == "6"
    assert t.item(0, 4).text() == "yes"
    dialog.missing_spin.setValue(8)  # a run of 6 no longer counts
    assert t.item(0, 3).text() == "0"
    dialog.rpm_spin.setValue(4)
    assert t.item(0, 4).text() != "yes"
    assert t.item(0, 4).toolTip() != ""


def test_the_flipped_box_is_disabled_when_parallel(dialog):
    assert dialog.flipped_box.isEnabled()
    dialog.walked_combo.setCurrentIndex(dialog.walked_combo.findData(False))
    assert not dialog.flipped_box.isEnabled()


def test_grid_combos_refill_and_keep_each_choice(mag_site, dialog, folder):
    session, _ = mag_site
    dialog.add_files([synthetic_grad601(folder, "a.dat")])
    dialog.set_row_grid(0, "M1")
    _fresh_grid(session, "M3")
    assert dialog.row_grid(0) == "M1"
    assert dialog.table.cellWidget(0, 1).findData("M3") >= 0


# ---- the picture -------------------------------------------------------------


def test_the_picture_arrows_follow_the_walking_pattern_and_the_corner(qgis_app):
    pic = MagSetupPicture()
    pic.set_setup(MagSetup())
    zig = pic.arrows()
    assert [a[0] for a in zig] == list(range(8))
    assert [a[3] for a in zig] == [
        1,
        -1,
        1,
        -1,
        1,
        -1,
        1,
        -1,
    ]  # traverses 1 and 3 out, 2 and 4 back
    assert zig[0][1][1] < zig[0][2][1]  # the first traverse goes up Y from the origin
    assert zig[1][1][1] > zig[1][2][1]  # the second is walked back
    pic.set_setup(MagSetup(zigzag=False))
    assert {a[3] for a in pic.arrows()} == {1}
    assert all(a[1][1] < a[2][1] for a in pic.arrows())
    pic.set_setup(MagSetup(far_y=True))
    assert pic.arrows()[0][1][1] > pic.arrows()[0][2][1]  # starts at the far end of Y now
    pic.set_setup(MagSetup(axis="x", far_x=True))
    first = pic.arrows()[0]
    assert first[1][0] > first[2][0] and first[1][1] == first[2][1]
    # drawn three times further apart than the spacing
    pic.set_setup(MagSetup())
    arrows = pic.arrows()
    assert arrows[1][1][0] - arrows[0][1][0] == pytest.approx(1.5)


def test_the_picture_shows_the_error_when_the_setup_is_invalid(dialog):
    dialog.separation_spin.setValue(0.7)
    assert dialog.picture.arrows() == []
    assert "sensor separation" in dialog.picture.error_text
    dialog.separation_spin.setValue(1.0)
    assert len(dialog.picture.arrows()) == 8


def test_changing_a_field_changes_the_dialog_picture(dialog):
    before = dialog.picture.arrows()
    dialog.walked_combo.setCurrentIndex(dialog.walked_combo.findData(False))
    assert dialog.picture.arrows() != before
    before = dialog.picture.arrows()
    dialog.corner_combo.setCurrentIndex(dialog.corner_combo.findData(2))
    assert dialog.picture.arrows() != before


# ---- the plugin ----------------------------------------------------------------


@pytest.fixture
def plugin(fake_iface, qgis_app):
    p = NsgeoPlugin(fake_iface)
    p.initGui()
    messages = []
    p.message = lambda text, level=None, title="nsgeo": messages.append(text)
    p.messages = messages
    try:
        yield p
    finally:
        if p.session.is_open and p.session.dirty:
            p.session.save()  # unload() would ask whether to save
        p.unload()  # rejects an open import dialog, which then deletes itself
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()


def _open(plugin, root):
    plugin.session.open_site(root / SURVEY_FILE)
    QCoreApplication.processEvents()


def test_the_toolbar_action_is_greyed_out_until_a_site_is_open(plugin, mag_site):
    _, root = mag_site
    act = plugin.act_import_mag
    assert act.text() == "Import mag…"
    assert act.toolTip() == "Imports Bartington Grad601 grid files onto magnetometer grids."
    assert [a.text() for a in plugin.toolbar_actions][
        [a.text() for a in plugin.toolbar_actions].index("Import DZT…") + 1
    ] == "Import mag…"
    assert not act.isEnabled()
    _open(plugin, root)
    assert act.isEnabled()
    plugin.session.close_site()
    assert not act.isEnabled()


def test_new_mag_grid_opens_the_grid_dialog_as_magnetometer(plugin, mag_site):
    _, root = mag_site
    _open(plugin, root)
    plugin.open_mag_import_dialog(None)
    plugin._mag_import_dialog.new_grid_requested.emit()
    assert plugin._grid_dialog is not None
    assert plugin._grid_dialog.instrument_combo.currentText() == "Magnetometer"
    plugin._grid_dialog.reject()


def test_the_survey_panels_import_request_opens_the_dialog_on_that_grid(plugin, mag_site):
    _, root = mag_site
    _open(plugin, root)
    plugin.survey_dock.mag_import_requested.emit("M2")
    assert plugin._mag_import_dialog is not None
    first = plugin._mag_import_dialog
    plugin.survey_dock.mag_import_requested.emit("M2")
    assert plugin._mag_import_dialog is first  # one at a time
    first.reject()
    QCoreApplication.processEvents()
    assert plugin._mag_import_dialog is None


def test_the_summary_says_how_many_readings_are_missing_and_where(plugin, mag_site):
    _, root = mag_site
    _open(plugin, root)
    plugin.open_mag_import_dialog("M2")
    d = plugin._mag_import_dialog
    d.add_files([synthetic_grad601(root / "raw" / "mag", "m3.dat", missing=((2, 3, 6),))])
    d.accept()
    assert "m3.dat: 6 readings are missing data, on traverse 3." in plugin.messages


def test_importing_shows_the_mag_panel_on_the_imported_grid(plugin, mag_site):
    _, root = mag_site
    _open(plugin, root)
    assert plugin.mag_dock.isHidden()
    plugin.open_mag_import_dialog("M2")
    d = plugin._mag_import_dialog
    d.add_files([synthetic_grad601(root / "raw" / "mag", "m3.dat")])
    d.accept()
    assert not plugin.mag_dock.isHidden()
    assert plugin.mag_dock.grid_combo.currentData() == "M2"


def test_the_toolbar_action_starts_from_the_survey_panels_mag_grid(plugin, mag_site, monkeypatch):
    session, root = mag_site
    _open(plugin, root)
    _fresh_grid(plugin.session, "M3")
    monkeypatch.setattr(plugin.survey_dock, "target_mag_grid_id", lambda: "M3")
    plugin._import_mag_from_toolbar()
    d = plugin._mag_import_dialog
    d.add_files([synthetic_grad601(root / "raw" / "mag", "m3.dat")])
    assert d.row_grid(0) == "M3"  # not the first free grid, M2
