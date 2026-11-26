"""Change setup… on a magnetometer file: one file or every file, corrections kept (M19a)."""

from __future__ import annotations

import dataclasses

import pytest
from nsgeo.mag import MagFile, MagSetup
from nsgeo_qgis.plugin import NsgeoPlugin
from nsgeo_qgis.session import SURVEY_FILE
from nsgeo_qgis.ui.mag_setup_dialog import MagSetupDialog
from nsgeo_qgis.ui.mag_setup_form import MagSetupForm
from plugin_testing import synthetic_grad601
from qgis.PyQt.QtCore import QCoreApplication, QEvent
from qgis.PyQt.QtWidgets import QDialog, QMessageBox

YES = QMessageBox.StandardButton.Yes
NO = QMessageBox.StandardButton.No

SCALES = (1.0, 0.9, 1.1, 1.0, 0.95, 1.05, 1.0, 0.98)
SHIFTS = (0.0, 0.1, -0.1, 0.0, 0.2, -0.2, 0.0, 0.05)


def _correct(session, grid_id, scales=SCALES, shifts=SHIFTS):
    mag = session.mag_file_on(grid_id)
    session.set_mag_file(dataclasses.replace(mag, scales=scales, shifts=shifts))
    return session.mag_file_on(grid_id)


@pytest.fixture
def dialog(mag_site):
    session, _ = mag_site
    d = MagSetupDialog(session, "M1")
    yield d
    d.deleteLater()


def _give_m2(session, root, **kw):
    path = synthetic_grad601(root / "raw" / "mag", "m2.dat", **kw)
    session.set_mag_file(MagFile.open(path, "M2", MagSetup()))
    return session.mag_file_on("M2")


def test_the_dialog_opens_on_the_files_setup(mag_site):
    session, root = mag_site
    chosen = dataclasses.replace(MagSetup(), far_y=True, missing_run=7)
    session.set_mag_file(dataclasses.replace(session.mag_file_on("M1"), setup=chosen))
    d = MagSetupDialog(session, "M1")
    try:
        assert d.windowTitle() == "Change setup · m1.dat"
        assert isinstance(d.form, MagSetupForm)
        assert d.form.title() == "Setup"
        assert d.form.setup() == chosen
        assert d.every_box.text() == "Use this setup for every magnetometer file on the site"
        assert not d.every_box.isChecked()
        assert d.apply_button.text() == "Apply"
    finally:
        d.deleteLater()


def test_changing_the_corner_moves_the_traverses(mag_site, dialog):
    session, _ = mag_site
    before = session.mag_file_on("M1")
    dialog.form.set_setup(dataclasses.replace(before.setup, far_x=True))
    dialog.accept()
    mag = session.mag_file_on("M1")
    grid = session.grid("M1")
    assert mag.setup.far_x
    assert mag.traverses(grid)[0].placement.offset == pytest.approx(4 - 0.25)
    assert dialog.changed_grids == ["M1"]
    assert session.dirty


def test_changing_the_setup_keeps_each_traverses_corrections(mag_site, dialog):
    session, _ = mag_site
    before = _correct(session, "M1")
    dialog.form.set_setup(dataclasses.replace(before.setup, far_x=True))
    dialog.accept()
    mag = session.mag_file_on("M1")
    assert mag.setup.far_x
    assert mag.scales == before.scales == SCALES
    assert mag.shifts == before.shifts == SHIFTS
    assert mag.path == before.path


def test_a_setup_that_does_not_fit_asks_and_no_changes_nothing(mag_site, dialog, answer_modal):
    session, _ = mag_site
    before = session.mag_file_on("M1")
    assert not session.dirty
    calls = answer_modal(QMessageBox, "question", NO)
    dialog.form.set_setup(dataclasses.replace(before.setup, spacing_m=1.0))
    dialog.accept()
    assert len(calls) == 1
    args = calls[0][0]
    assert args[1] == "File does not fit its grid"
    assert args[2].startswith("m1.dat does not fit grid M1 with this setup:\n")
    assert args[2].endswith("\nApply anyway? Nothing is cropped or stretched.")
    assert session.mag_file_on("M1") is before
    assert not session.dirty
    assert dialog.changed_grids == []
    # Yes applies it.
    answer_modal(QMessageBox, "question", YES)
    dialog.accept()
    assert session.mag_file_on("M1").setup.spacing_m == 1.0
    assert dialog.changed_grids == ["M1"]


def test_every_file_changes_each_and_is_remembered(mag_site, dialog):
    session, root = mag_site
    _give_m2(session, root)
    m1 = _correct(session, "M1")
    m2 = _correct(session, "M2", scales=(1.0,) * 4 + (0.9,) * 4, shifts=(0.0,) * 7 + (0.3,))
    new = dataclasses.replace(MagSetup(), far_x=True)
    before_remembered = session.mag_setup()
    dialog.form.set_setup(new)
    dialog.every_box.setChecked(True)
    dialog.accept()
    assert sorted(dialog.changed_grids) == ["M1", "M2"]
    for grid_id, old in (("M1", m1), ("M2", m2)):
        mag = session.mag_file_on(grid_id)
        assert mag.setup == new
        assert (mag.scales, mag.shifts) == (old.scales, old.shifts)
    assert session.mag_setup() == new
    assert before_remembered != new


def test_without_the_checkbox_only_this_file_changes(mag_site, dialog):
    session, root = mag_site
    m2 = _give_m2(session, root)
    before_remembered = session.mag_setup()
    new = dataclasses.replace(MagSetup(), far_x=True)
    dialog.form.set_setup(new)
    dialog.accept()
    assert session.mag_file_on("M1").setup == new
    assert session.mag_file_on("M2") is m2
    assert session.mag_setup() == before_remembered


def test_applying_the_unchanged_setup_changes_nothing(mag_site, dialog):
    session, _ = mag_site
    before = session.mag_file_on("M1")
    changes = []
    session.mag_changed.connect(lambda: changes.append(1))
    dialog.accept()
    assert dialog.changed_grids == []
    assert session.mag_file_on("M1") is before
    assert changes == [] and not session.dirty


def test_change_mag_setup_refuses_a_grid_with_no_file(mag_site):
    session, _ = mag_site
    with pytest.raises(KeyError):
        session.change_mag_setup("M2", MagSetup())
    with pytest.raises(KeyError):
        session.change_mag_setup("G1", MagSetup())


def test_change_mag_setup_signals_once_for_every_file(mag_site):
    session, root = mag_site
    _give_m2(session, root)
    changes = []
    session.mag_changed.connect(lambda: changes.append(1))
    new = dataclasses.replace(MagSetup(), far_y=True)
    done = session.change_mag_setup("M1", new, every_file=True)
    assert sorted(done) == ["M1", "M2"]
    assert changes == [1]


def test_apply_after_the_site_was_replaced_changes_nothing(mag_site, dialog):
    session, root = mag_site
    session.save()
    session.open_site(root / SURVEY_FILE)  # a new Site object
    dialog.form.set_setup(dataclasses.replace(MagSetup(), far_x=True))
    dialog.accept()
    assert dialog.status.text() == "The site changed; nothing was changed."
    assert session.mag_file_on("M1").setup == MagSetup()
    assert dialog.changed_grids == []
    assert dialog.isVisible() is False


def test_the_status_shows_missing_and_fit_live(mag_site):
    session, root = mag_site
    _give_m2(session, root, missing=((0, 4, 8),))
    d = MagSetupDialog(session, "M2")
    try:
        assert d.status.text() == "8 readings are missing data, on traverse 1."
        d.form.missing_spin.setValue(9)
        assert d.status.text() == "No readings are missing data."
        d.form.spacing_spin.setValue(1.0)
        lines = d.status.text().split("\n")
        assert lines[0] == "No readings are missing data."
        assert len(lines) == 2 and "traverses 1 m apart" in lines[1]
    finally:
        d.deleteLater()


# ---- the plugin ------------------------------------------------------------------


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
            p.session.save()
        p.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()


def test_change_setup_from_the_mag_panel_opens_the_dialog(plugin, mag_site, drive_dialog):
    _, root = mag_site
    plugin.session.open_site(root / SURVEY_FILE)
    QCoreApplication.processEvents()
    shown = []

    def drive(dlg):
        shown.append(dlg)
        dlg.form.set_setup(dataclasses.replace(dlg.form.setup(), far_x=True))
        dlg.accept()

    drive_dialog(QDialog, "exec", drive)
    plugin.mag_dock.setup_requested.emit("M1")
    assert len(shown) == 1 and isinstance(shown[0], MagSetupDialog)
    assert plugin.session.mag_file_on("M1").setup.far_x
    assert plugin.messages[-1] == "m1.dat: setup changed."


def test_change_setup_from_the_survey_panel_for_every_file(plugin, mag_site, drive_dialog):
    session, root = mag_site
    plugin.session.open_site(root / SURVEY_FILE)
    _give_m2(plugin.session, root)
    QCoreApplication.processEvents()

    def drive(dlg):
        dlg.form.set_setup(dataclasses.replace(dlg.form.setup(), far_x=True))
        dlg.every_box.setChecked(True)
        dlg.accept()

    drive_dialog(QDialog, "exec", drive)
    plugin.survey_dock.mag_setup_requested.emit("M1")
    assert plugin.messages[-1] == "Setup changed for 2 magnetometer files."


def test_a_cancelled_change_setup_says_nothing(plugin, mag_site, drive_dialog):
    _, root = mag_site
    plugin.session.open_site(root / SURVEY_FILE)
    drive_dialog(QDialog, "exec", lambda dlg: dlg.reject())
    plugin.open_mag_setup_dialog("M1")
    assert plugin.messages == []
