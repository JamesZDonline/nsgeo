from __future__ import annotations

from typing import Any

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.import_dialog import (
    COL_DIR,
    COL_INCLUDE,
    COL_LABEL,
    COL_NOTE,
    COL_OFFSET,
    COL_START,
    ImportDialog,
)
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.add_grid(GRID)
    return s


@pytest.fixture(autouse=True)
def _flush_deferred_deletes(qgis_app):
    """See test_plugin_grid_dialog.py's fixture of the same name: a dialog
    opened through the plugin gets a `destroyed`-connected closure
    (clear_if_current), and letting several such dialogs pile up unflushed
    until qgis_app's own session-scoped exitQgis() segfaults reaping them
    all in one batch. Flushing after every test instead means exitQgis()
    only ever reaps whatever the *last* test left outstanding."""
    yield
    qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# ---- Step 1's brief tests, verbatim -----------------------------------------


def test_table_shows_planned_rows_and_edits_flow_back(session, tmp_path):
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT", n_traces=60) for i in (2, 1, 3)]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    assert d.table.rowCount() == 3
    assert [d.table.item(r, COL_LABEL).text() for r in range(3)] == [
        "FILE__001",
        "FILE__002",
        "FILE__003",
    ]
    assert [d.table.item(r, COL_OFFSET).text() for r in range(3)] == ["0.00", "0.50", "1.00"]
    assert d.table.item(1, COL_DIR).text() == "−1"
    d.set_include(1, False)
    assert [d.table.item(r, COL_OFFSET).text() for r in range(3) if d.rows[r].include] == [
        "0.00",
        "0.50",
    ]
    d.set_offset(2, 3.25)
    d.set_include(1, True)
    assert d.rows[2].offset == 3.25 and d.rows[2].offset_edited
    assert d.table.item(1, COL_OFFSET).text() == "0.50"


def test_remove_and_reorder(session, tmp_path):
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT") for i in (1, 2, 3)]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    d.table.selectRow(2)
    d.move_selected(-1)
    assert [r.path.stem for r in d.rows] == ["FILE__001", "FILE__003", "FILE__002"]
    assert [r.offset for r in d.rows] == [0.0, 0.5, 1.0]
    d.table.selectRow(0)
    d.remove_selected()
    assert [r.path.stem for r in d.rows] == ["FILE__003", "FILE__002"]
    assert d.rows[0].offset == 0.0


def test_accept_adds_lines_and_fills_the_layer(session, tmp_path):
    layers = SiteLayers(session)
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT") for i in (1, 2, 3)]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    d.set_include(1, False)
    d.accept()
    assert d.imported_keys == ["raw/FILE__001.DZT", "raw/FILE__003.DZT"]
    assert session.keys() == d.imported_keys
    assert layers.feature_count("lines") == 2
    layers.detach()


def test_duplicate_import_is_reported_not_raised(session, tmp_path):
    files = [synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    d.accept()
    d2 = ImportDialog(session, grid_id="A")
    d2.add_files(files)
    d2.accept()
    assert "already" in d2.status.text()
    assert d2.result() != d2.DialogCode.Accepted


def test_axis_and_spacing_options_come_from_the_widgets(session, tmp_path):
    d = ImportDialog(session, grid_id="A")
    d.axis_combo.setCurrentIndex(d.axis_combo.findData("x"))
    d.spacing.setValue(0.25)
    d.first_offset.setValue(1.0)
    d.direction_forward.setChecked(True)
    d.label_number.setChecked(True)
    o = d.options()
    assert (o.axis, o.spacing, o.first_offset, o.direction_mode, o.label_source) == (
        "x",
        0.25,
        1.0,
        "forward",
        "number",
    )
    assert o.grid_size_along == 5.0  # size_x when lines run along x


@needs_real_data
def test_real_files_import_into_the_grid(session):
    d = ImportDialog(session, grid_id="A")
    d.add_files(REAL_DZT)
    assert d.table.rowCount() == 10
    assert "exceeds" in d.table.item(7, COL_NOTE).text()  # FILE__008, 11.10 m
    assert d.table.item(0, COL_INCLUDE).checkState() == Qt.CheckState.Checked
    d.accept()
    assert len(session.keys()) == 10


# ---- decisions beyond the brief's own tests ---------------------------------


def test_direction_and_start_along_are_derived_not_hand_editable(session, tmp_path):
    # recompute_offsets always re-derives both direction and start_along
    # from direction_mode/slot position (ImportRow has offset_edited, and
    # now label_edited, but no direction_edited -- lookup.py's own
    # docstring on the contract). A per-row edit to either would either be
    # silently discarded on the very next replan (which every other edit
    # in this dialog triggers), or -- worse, for start_along -- leave a
    # reversed row mirrored outside the grid if a replan were skipped
    # instead to preserve it. Both columns show the derived value and are
    # not user-editable; the real per-line control is the Direction mode,
    # plus reordering/excluding rows to change which slot a file lands in.
    d = ImportDialog(session, grid_id="A")
    d.add_files([synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")])
    for col in (COL_DIR, COL_START):
        assert not d.table.item(0, col).flags() & Qt.ItemFlag.ItemIsEditable


def test_add_files_ignores_a_file_already_in_the_table(session, tmp_path):
    # A second "Add files..." that reselects a file already in the table
    # (e.g. the native dialog remembers the last folder) must not add a
    # second row for it.
    path = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    d = ImportDialog(session, grid_id="A")
    d.add_files([path])
    d.add_files([path])
    assert d.table.rowCount() == 1


def test_bad_offset_entry_is_reported_and_reverted_not_crashed(session, tmp_path):
    d = ImportDialog(session, grid_id="A")
    d.add_files([synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")])
    d.table.item(0, COL_OFFSET).setText("not-a-number")  # must not raise
    assert d.rows[0].offset == 0.0 and not d.rows[0].offset_edited  # untouched
    assert "not a number" in d.status.text()
    assert d.table.item(0, COL_OFFSET).text() == "0.00"  # reverted, not left showing garbage


def test_hand_edited_label_survives_a_later_replan(session, tmp_path):
    # The wrinkle the brief calls out: recompute_offsets rewrites
    # row.label to the file stem on every replan unless label_edited is
    # set. Edited through the table (not the pure ImportRow field
    # directly, which test_pure_lookup.py already covers), then a later,
    # unrelated edit (here: excluding a different row) must not discard it.
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT") for i in (1, 2)]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    d.table.item(0, COL_LABEL).setText("line 6a")
    assert d.rows[0].label == "line 6a" and d.rows[0].label_edited
    d.set_include(1, False)  # an unrelated edit that triggers a full replan
    assert d.rows[0].label == "line 6a"
    assert d.table.item(0, COL_LABEL).text() == "line 6a"


def test_import_dialog_exec_is_guarded_by_default(session):
    # Task 9's autouse guard forbids QDialog.exec() so a test that trips
    # one fails fast instead of hanging under QT_QPA_PLATFORM=offscreen.
    # ImportDialog never calls its own exec() (see the module docstring),
    # but the guard patches QDialog itself, so this holds for any subclass.
    d = ImportDialog(session, grid_id="A")
    with pytest.raises(AssertionError):
        d.exec()


def test_add_files_button_is_guarded_by_default(session):
    # Calling the slot directly, not add_button.click(): a QAbstractButton
    # signal swallows an exception raised inside a connected slot (the
    # standing signal/slot hazard), so pytest.raises around .click() would
    # never see the guard's AssertionError propagate at all.
    d = ImportDialog(session, grid_id="A")
    with pytest.raises(AssertionError):
        d._choose_files()


def test_add_files_button_adds_the_chosen_files(session, tmp_path, answer_modal):
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT") for i in (1, 2)]
    calls = answer_modal(QFileDialog, "getOpenFileNames", ([str(p) for p in files], ""))
    d = ImportDialog(session, grid_id="A")
    d._choose_files()
    assert d.table.rowCount() == 2
    assert len(calls) == 1


# ---- plugin wiring -----------------------------------------------------------


def _open(plugin: Any, grid_id: str | None = None) -> ImportDialog:
    """Call open_import_dialog() and return the ImportDialog it just showed.

    Modeless (see plugin.py's module docstring and open_grid_dialog()'s
    own `_open` in test_plugin_grid_dialog.py, which this copies): no
    QDialog.exec anywhere here. open_import_dialog() returns immediately
    with a real, already-shown dialog tracked as `_import_dialog`, and
    driving it -- adding files, editing the table, accept()/reject() --
    exercises the exact same code path a live QGIS session would. This is
    also the only thing that would catch ImportDialog being wired up with
    exec() by mistake (Task 10's own lesson: drive_dialog's exec()
    monkeypatch never runs a real event loop, so it cannot observe an
    application-modal dialog freezing the toolbar/dock).
    """
    plugin.open_import_dialog(grid_id)
    dialog = plugin._import_dialog
    assert dialog is not None
    return dialog


def test_open_import_dialog_accepts_and_reports_through_the_message_bar(
    fake_iface, tmp_path, answer_modal
):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)

    dialog = _open(plugin, "A")
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT") for i in (1, 2)]
    dialog.add_files(files)
    dialog.accept()

    assert plugin._import_dialog is None  # finished() cleared it
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "imported 2 line(s)" in item.text()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_open_import_dialog_cancel_leaves_the_session_untouched(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)

    dialog = _open(plugin, "A")
    dialog.add_files([synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")])
    dialog.reject()

    assert plugin.session.keys() == []
    assert plugin._import_dialog is None
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_open_import_dialog_refuses_without_a_grid(fake_iface, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)

    plugin.open_import_dialog(None)  # no grids yet
    assert plugin._import_dialog is None
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "grid" in item.text().lower()
    plugin.unload()


def test_open_import_dialog_does_not_open_a_second_dialog_while_one_is_open(
    fake_iface, tmp_path, answer_modal
):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)

    first = _open(plugin, "A")
    plugin.open_import_dialog("A")
    assert plugin._import_dialog is first  # no second dialog created

    first.reject()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_unload_closes_a_visible_import_dialog(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)

    dialog = _open(plugin, "A")
    assert dialog.isVisible()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
    assert plugin._import_dialog is None


def test_open_import_dialog_recovers_from_a_dialog_destroyed_outside_finished(
    fake_iface, tmp_path, answer_modal
):
    # Mirrors test_plugin_grid_dialog.py's test of the same name for
    # GridDialog (round 5, Finding 6 there): `finished` is the only path
    # that is *expected* to clear self._import_dialog, so a dialog torn
    # down some other way (setParent(None) + deleteLater(), bypassing
    # finished() entirely) must still be caught by the destroyed()-
    # connected clear_if_current -- otherwise unload() would later call
    # reject() on an already-deleted C++ object, and every later "Import"
    # would wedge forever calling show()/raise_() on it.
    import nsgeo_qgis
    from qgis.PyQt.QtWidgets import QApplication

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)

    dialog = _open(plugin, "A")
    dialog.setParent(None)
    dialog.deleteLater()
    QApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)

    assert plugin._import_dialog is None  # cleared by destroyed(), not finished()

    # And a later open/unload must not raise or wedge.
    plugin.open_import_dialog("A")
    assert plugin._import_dialog is not None and plugin._import_dialog is not dialog
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()  # must not raise


def test_accept_refuses_when_the_site_closed_under_the_dialog(fake_iface, tmp_path):
    # Modeless means the toolbar stays clickable while this dialog is
    # open, so the site can be closed before Import is clicked --
    # impossible under an application-modal exec(). session.add_lines
    # would raise ProjectError ("no site is open") from inside accept(),
    # itself reached via buttons.accepted (a signal-connected slot); this
    # must be reported through `status`, not escape to stderr while the
    # dialog closes as though nothing were wrong.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)

    dialog = _open(plugin, "A")
    dialog.add_files([synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")])
    plugin.session.close_site()  # the site closes while the dialog is still open

    dialog.accept()  # must not raise

    assert "no site is open" in dialog.status.text().lower()
    assert dialog.result() != dialog.DialogCode.Accepted
    assert plugin._import_dialog is dialog  # still open -- nothing to clean up yet
    dialog.reject()
    plugin.unload()


def test_accept_refuses_when_a_different_site_was_opened_under_the_dialog(
    fake_iface, tmp_path, answer_modal
):
    # Worse than closing outright: probed directly without this guard --
    # site B's own grid "A" would be silently written into, no error at
    # all, exactly the Task 10 finding this dialog's module docstring
    # describes for GridDialog.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()

    site_a = tmp_path / "site_a"
    site_a.mkdir()
    plugin.session.new_site(site_a)
    plugin.session.add_grid(GRID)

    dialog = _open(plugin, "A")
    dialog.add_files([synthetic_dzt(site_a / "raw", "FILE__001.DZT")])

    site_b = tmp_path / "site_b"
    site_b.mkdir()
    plugin.session.new_site(site_b)  # a different site opened under the dialog
    plugin.session.add_grid(GRID)

    dialog.accept()  # OK, still believing it is importing into site A

    assert "different site" in dialog.status.text().lower()
    assert plugin.session.keys() == []  # site B's own grid A untouched
    dialog.reject()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_accept_refuses_when_the_target_grid_was_removed_under_the_dialog(
    fake_iface, tmp_path, answer_modal
):
    # Another dock action reachable while this dialog stays open and
    # clickable: "Remove grid" has no guard against an import still in
    # flight against the very grid it is removing (it succeeds because no
    # lines reference the grid yet -- the import hasn't been accepted).
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)

    dialog = _open(plugin, "A")
    dialog.add_files([synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")])
    plugin.session.remove_grid("A")

    dialog.accept()  # must not raise

    assert "no longer exists" in dialog.status.text().lower()
    assert plugin.session.keys() == []
    dialog.reject()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
