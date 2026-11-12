"""The ParaView export dialog and its wiring (M16 A, Task 4): the Slices panel's button, the
dialog's size and refusals, what is remembered, launching ParaView, and cancelling."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis import plugin as plugin_module
from nsgeo_qgis.paraview_export import ParaViewExport, paraview_folder
from nsgeo_qgis.ui.paraview_dialog import ParaViewExportDialog
from plugin_testing import synthetic_dzt
from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QProcess
from qgis.PyQt.QtWidgets import QDialog, QMessageBox

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [
    {"step": "time_zero", "params": {}, "enabled": True},
    {"step": "dewow", "params": {}, "enabled": True},
]


@pytest.fixture
def plugin(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    QgsSettings().remove(plugin_module._PARAVIEW_KEY)
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", 1.0 + i, 0.0, 1, p.stem)))
    s.add_lines(lines)
    s.site.presets["p"] = list(PRESET)
    plugin.slices_dock.rebuild_source()
    dock = plugin.slices_dock
    dock.grid_combo.setCurrentText("A")
    dock.preset_combo.setCurrentText("p")
    dock.transform_combo.set_value("amp_envelope")
    assert dock.engine.wait_for_preparation(20_000), "preparation did not finish"
    yield plugin, s
    QgsSettings().remove(plugin_module._PARAVIEW_KEY)
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def _open_dialog(plugin_obj, drive_dialog, driver):
    """Click the panel's button with `driver` answering the dialog; the dialogs shown."""
    calls = drive_dialog(QDialog, "exec", driver)
    plugin_obj.slices_dock.paraview_button.click()
    return calls


def _make_dialog(plugin_obj):
    session, dock = plugin_obj.session, plugin_obj.slices_dock
    export = ParaViewExport(session, dock)
    return ParaViewExportDialog(
        ["A"], "A", export.defaults, export.summary, "", hints_for=export.panel_values
    )


# ---- the button and the dialog ---------------------------------------------------------------


def test_the_button_is_on_whenever_a_site_is_open_in_either_scope(plugin):
    plugin_obj, _s = plugin
    dock = plugin_obj.slices_dock
    assert dock.paraview_button.text() == "ParaView…"
    assert dock.paraview_button.isEnabled()
    dock.set_scope("site")
    assert dock.paraview_button.isEnabled()


def test_the_button_opens_the_dialog_on_the_panels_grid(plugin, drive_dialog):
    plugin_obj, s = plugin
    shown: list[tuple] = []

    def driver(d):
        assert isinstance(d, ParaViewExportDialog)
        shown.append((d.grid_id(), d.cell_spin.value(), d.cell_hint.text()))
        d.reject()

    calls = _open_dialog(plugin_obj, drive_dialog, driver)
    export = ParaViewExport(s, plugin_obj.slices_dock)
    assert len(calls) == 1
    grid, cell, hint = shown[0]
    assert grid == plugin_obj.slices_dock.grid_combo.currentText()
    assert cell == pytest.approx(export.defaults(grid).cell)
    assert hint.startswith("Slices panel:")


def test_editing_the_cell_refreshes_the_size(plugin):
    dialog = _make_dialog(plugin[0])
    before = dialog.size_label.text()
    assert "about" in before
    dialog.cell_spin.setValue(dialog.cell_spin.value() / 2)
    assert dialog.size_label.text() != before


def test_the_dialog_lists_what_will_be_written(plugin):
    dialog = _make_dialog(plugin[0])
    assert "paraview" in dialog.folder_label.text() and "A" in dialog.folder_label.text()
    assert "cells" in dialog.volume_label.text() and "depths" in dialog.volume_label.text()
    assert dialog.also_label.text() == "0 picks, 3 lines"
    assert dialog.disk_label.text().endswith("free")
    assert dialog.trend_spin.value() > 0 and dialog.period_spin.value() > 0


def test_a_too_fine_cell_is_refused_before_export(plugin):
    dialog = _make_dialog(plugin[0])
    dialog.path_edit.setText("/bin/true")
    dialog.cell_spin.setValue(0.002)
    assert not dialog.export_button.isEnabled() and not dialog.open_button.isEnabled()
    assert "too fine" in dialog.size_label.text()
    dialog.cell_spin.setValue(0.25)  # back to something that works
    assert dialog.export_button.isEnabled() and dialog.open_button.isEnabled()


def test_with_no_paraview_path_only_export_is_enabled(plugin):
    dialog = _make_dialog(plugin[0])
    assert dialog.export_button.isEnabled() and not dialog.open_button.isEnabled()
    dialog.path_edit.setText("/usr/bin/paraview")
    assert dialog.open_button.isEnabled()


def test_a_short_disk_warns_and_says_how_much_is_needed_but_still_exports(plugin, monkeypatch):
    dialog = _make_dialog(plugin[0])
    export_bytes = dialog._summary_for("A", dialog.choice()).export_bytes
    usage = shutil._ntuple_diskusage(10**12, 10**12 - 1000, 1000)
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage)
    dialog.cell_spin.setValue(dialog.cell_spin.value() * 1.01)  # an edit refreshes
    text = dialog.disk_label.text()
    assert text.startswith("only 1000 bytes free") or text.startswith("only 1 MB free")
    assert "needs about" in text
    assert dialog.disk_label.property("warning") is True
    assert dialog.export_button.isEnabled()
    assert export_bytes > 0


# ---- what accepting does ---------------------------------------------------------------------


def test_accepting_remembers_the_grids_volume_record_and_the_paraview_path(
    plugin, drive_dialog, message_log
):
    plugin_obj, s = plugin

    def driver(d):
        d.dz_spin.setValue(0.5)
        d.stretch_spin.setValue(2.0)
        d.path_edit.setText("/no/such/paraview")
        d.export_button.click()

    _open_dialog(plugin_obj, drive_dialog, driver)
    assert s.volume_record("A")["dz_ns"] == pytest.approx(0.5)
    assert s.volume_record("A")["stretch"] == pytest.approx(2.0)
    assert QgsSettings().value(plugin_module._PARAVIEW_KEY) == "/no/such/paraview"
    assert paraview_folder(s, "A").is_dir()
    assert any("Exported A for ParaView to" in m for m in message_log)


def test_a_rejected_dialog_remembers_and_writes_nothing(plugin, drive_dialog):
    plugin_obj, s = plugin
    _open_dialog(plugin_obj, drive_dialog, lambda d: (d.dz_spin.setValue(0.5), d.reject()))
    assert s.volume_record("A") == {}
    assert not paraview_folder(s, "A").exists()


def _fake_paraview(tmp_path) -> Path:
    exe = tmp_path / "fakeparaview"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def test_export_and_open_launches_paraview_with_the_folder(
    plugin, drive_dialog, monkeypatch, tmp_path
):
    plugin_obj, s = plugin
    exe = _fake_paraview(tmp_path)
    spied: list[tuple] = []
    monkeypatch.setattr(QProcess, "startDetached", staticmethod(lambda *a: spied.append(a) or True))

    def driver(d):
        d.path_edit.setText(str(exe))
        d.open_button.click()

    _open_dialog(plugin_obj, drive_dialog, driver)
    folder = paraview_folder(s, "A")
    assert spied == [(str(exe), [f"--script={folder / 'open_scene.py'}"], str(folder))]


def test_plain_export_does_not_launch(plugin, drive_dialog, monkeypatch, tmp_path):
    plugin_obj, _s = plugin
    exe = _fake_paraview(tmp_path)
    spied: list[tuple] = []
    monkeypatch.setattr(QProcess, "startDetached", staticmethod(lambda *a: spied.append(a) or True))

    def driver(d):
        d.path_edit.setText(str(exe))
        d.export_button.click()

    _open_dialog(plugin_obj, drive_dialog, driver)
    assert spied == []


def test_a_paraview_that_will_not_start_says_how_to_open(plugin, drive_dialog, message_log):
    plugin_obj, s = plugin

    def driver(d):
        d.path_edit.setText("/no/such/paraview")
        d.open_button.click()

    _open_dialog(plugin_obj, drive_dialog, driver)
    assert any("could not be started" in m and "open.sh" in m for m in message_log)


def test_launch_paraview_refuses_an_empty_or_missing_program(tmp_path):
    assert not plugin_module.launch_paraview("", tmp_path)
    assert not plugin_module.launch_paraview(str(tmp_path / "nothing"), tmp_path)
    assert not plugin_module.launch_paraview(str(tmp_path), tmp_path)  # a folder


def test_with_no_paraview_path_it_writes_and_says_how_to_open(plugin, drive_dialog, message_log):
    plugin_obj, s = plugin
    _open_dialog(plugin_obj, drive_dialog, lambda d: d.export_button.click())
    folder = paraview_folder(s, "A")
    assert (folder / "open.sh").is_file()
    assert any(str(folder) in m and "open.sh" in m for m in message_log)


def test_a_cancelled_export_reports_cancelled_and_writes_nothing(
    plugin, drive_dialog, message_log, monkeypatch
):
    plugin_obj, s = plugin
    monkeypatch.setattr(
        plugin_obj,
        "_export_progress",
        lambda title, total, show_now=False: (lambda done, of: done == 0, _FakeBar()),
    )
    _open_dialog(plugin_obj, drive_dialog, lambda d: d.export_button.click())
    assert any("ParaView export cancelled" in m for m in message_log)
    assert not paraview_folder(s, "A").exists()
    assert not list(paraview_folder(s, "A").parent.glob("*.partial"))


class _FakeBar:
    def setLabelText(self, text):  # noqa: N802 -- Qt's name
        self.text = text

    def labelText(self):  # noqa: N802
        return getattr(self, "text", "")

    def close(self):
        pass

    def deleteLater(self):  # noqa: N802
        pass


def test_the_progress_dialog_shows_at_once_and_says_it_is_preparing(
    plugin, drive_dialog, monkeypatch
):
    plugin_obj, _s = plugin
    seen: dict = {}
    real = plugin_obj._export_progress

    def spy(title, total, show_now=False):
        callback, bar = real(title, total, show_now=show_now)
        seen.update(title=title, show_now=show_now, bar=bar)

        def wrapped(done, of):
            seen.setdefault("labels", []).append(bar.labelText())
            return callback(done, of)

        return wrapped, bar

    monkeypatch.setattr(plugin_obj, "_export_progress", spy)
    _open_dialog(plugin_obj, drive_dialog, lambda d: d.export_button.click())
    assert seen["title"] == "Exporting for ParaView" and seen["show_now"] is True
    assert seen["labels"][0] == "Preparing lines…"
    assert seen["labels"][-1] == "Exporting for ParaView"


def test_a_busy_slices_panel_warns_and_writes_nothing(
    plugin, drive_dialog, message_log, monkeypatch
):
    plugin_obj, s = plugin
    monkeypatch.setattr(
        type(plugin_obj.slices_dock), "foreign_preparing", property(lambda self: True)
    )
    # the panel's engine is prepared on this source, so busy applies only to a standalone run:
    monkeypatch.setattr(ParaViewExport, "_panel_engine", lambda self, source: None)
    _open_dialog(plugin_obj, drive_dialog, lambda d: d.export_button.click())
    assert any("still preparing" in m for m in message_log)
    assert not paraview_folder(s, "A").exists()


# ---- fix round 1: transform None, and Enter in a field ----------------------------------------


def test_the_dialogs_transform_equals_the_panels_for_every_option(plugin):
    from nsgeo_qgis.ui.site_scope import transform_value

    plugin_obj, _s = plugin
    dock = plugin_obj.slices_dock
    dialog = _make_dialog(plugin_obj)
    for value in dock.transform_combo.values():
        dock.transform_combo.set_value(value)
        fresh = _make_dialog(plugin_obj)
        assert fresh.choice().transform == transform_value(value)
        dialog.transform_combo.set_value(value)
        assert dialog.choice().transform == transform_value(value)


def test_none_picked_in_the_dialog_exports(plugin, drive_dialog, message_log):
    plugin_obj, s = plugin

    def driver(d):
        d.transform_combo.set_value("none")
        d.export_button.click()

    _open_dialog(plugin_obj, drive_dialog, driver)
    assert paraview_folder(s, "A").is_dir(), message_log
    assert s.volume_record("A")["transform"] == ""


def test_the_panel_on_none_gives_a_dialog_default_of_none_that_exports(
    plugin, drive_dialog, message_log
):
    plugin_obj, s = plugin
    plugin_obj.slices_dock.transform_combo.set_value("none")
    plugin_obj.slices_dock.engine.wait_for_preparation(20_000)
    seen = []

    def driver(d):
        seen.append((d.choice().transform, d.transform_combo.value()))
        d.export_button.click()

    _open_dialog(plugin_obj, drive_dialog, driver)
    assert seen == [("", "none")]
    assert paraview_folder(s, "A").is_dir(), message_log


def test_a_record_that_kept_none_heals(plugin):
    plugin_obj, s = plugin
    s.remember_volume("A", transform="none")
    assert _make_dialog(plugin_obj).choice().transform == ""


def test_switching_grids_shows_each_grids_own_transform(plugin):
    from nsgeo_qgis.slices_plan import VolumeChoice

    plugin_obj, s = plugin
    export = ParaViewExport(s, plugin_obj.slices_dock)
    own = {
        "A": VolumeChoice(0.2, 0.2, "amp_square"),
        "B": VolumeChoice(0.2, 0.2, ""),
        "C": VolumeChoice(0.2, 0.2, "amp_envelope"),
    }
    dialog = ParaViewExportDialog(
        ["A", "B", "C"], "A", lambda g: own[g], export.summary, "", hints_for=None
    )
    for grid in ("B", "C", "A", "B"):
        dialog.grid_combo.setCurrentText(grid)
        assert dialog.choice().transform == own[grid].transform


def test_enter_in_a_spin_commits_and_refreshes_but_does_not_export(plugin):
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtTest import QTest

    dialog = _make_dialog(plugin[0])
    dialog.path_edit.setText("/bin/true")
    dialog.show()
    before = dialog.size_label.text()
    dialog.cell_spin.setFocus()
    dialog.cell_spin.selectAll()
    QTest.keyClicks(dialog.cell_spin, "0.1")
    assert dialog.size_label.text() == before  # nothing committed yet
    QTest.keyClick(dialog.cell_spin, Qt.Key.Key_Return)
    assert dialog.result() == 0 and dialog.isVisible() and not dialog.open_after()
    assert dialog.cell_spin.value() == pytest.approx(0.1)
    assert dialog.size_label.text() != before
    QTest.keyClick(dialog.path_edit, Qt.Key.Key_Return)
    assert dialog.isVisible()
    dialog.close()
