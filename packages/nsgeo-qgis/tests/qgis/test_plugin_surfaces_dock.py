"""M16 B Task 5: the Surfaces panel, its place among the panels, and the export with surfaces.

The plugin runs over a synthetic site (conftest `surface_plugin`)."""

from __future__ import annotations

import json
from pathlib import Path

from nsgeo.slices import SurfaceSettings
from nsgeo_qgis.surface_layers import PROP_FEATURE
from nsgeo_qgis.ui.surfaces_dock import ALL_GRIDS
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QDialog, QInputDialog, QScrollArea
from tests.vtk_reader import read_vtk_xml


def _shown(plugin) -> str:
    item = plugin.iface.messageBar().currentItem()
    return item.text() if item is not None else ""


def _layers_of(fid):
    return [
        lyr
        for lyr in QgsProject.instance().mapLayers().values()
        if lyr.customProperty(PROP_FEATURE) == fid
    ]


def _rows(dock):
    return [
        [dock.table.item(r, c).text() for c in range(dock.table.columnCount())]
        for r in range(dock.table.rowCount())
    ]


def _made(plugin, name="Bowl", build=True, **settings):
    """A surface of the four picks, built when asked (strength 0: synthetic data)."""
    settings.setdefault("strength", 0.0)
    record = plugin.surfaces.create(name, plugin.pick_fids, SurfaceSettings(**settings))
    if build:
        plugin.build_surfaces([record.feature_id])
    QCoreApplication.processEvents()
    plugin.surfaces_dock.refresh()
    return record


def test_the_panels_menu_lists_surfaces(surface_plugin):
    plugin = surface_plugin
    entries = [a.text() for a in plugin.panels_menu.actions() if a.text()]
    assert "Surfaces" in entries
    entry = next(a for a in plugin.panels_menu.actions() if a.text() == "Surfaces")
    assert entry.isCheckable() and plugin.surfaces_dock in plugin.docks
    assert plugin.surfaces_dock.windowTitle() == "nsgeo Surfaces"


def test_the_panel_is_tabbed_with_slices(surface_plugin, fake_iface):
    plugin = surface_plugin
    main = fake_iface.mainWindow()
    main.resize(1400, 900)
    main.show()
    try:
        deadline = 200
        while plugin.surfaces_dock not in main.tabifiedDockWidgets(plugin.slices_dock):
            QCoreApplication.processEvents()
            deadline -= 1
            assert deadline, "Surfaces never joined Slices's tab group"
    finally:
        main.close()


def test_the_panel_lists_surfaces_with_fit_and_state(surface_plugin):
    plugin = surface_plugin
    dock = plugin.surfaces_dock
    assert dock.table.rowCount() == 0
    fresh = _made(plugin, build=False)
    dock.refresh()
    assert _rows(dock) == [["Bowl", "Grid A", "4", "", "not built"]]
    plugin.build_surfaces([fresh.feature_id])
    row = _rows(dock)[0]
    report = plugin.surfaces.state(fresh.feature_id).report
    within = report["fit"]["within_2cm"]
    assert row == ["Bowl", "Grid A", "4", f"{within}/4", ""]
    assert dock.grid_combo.itemText(0) == ALL_GRIDS and dock.grid_combo.count() == 2
    # the grid filter narrows the list
    dock.grid_combo.setCurrentText("Grid A")
    assert dock.table.rowCount() == 1
    dock.grid_combo.setCurrentIndex(0)
    assert dock.table.rowCount() == 1
    # the contents scroll
    assert isinstance(dock.widget(), QScrollArea) and dock.widget().widgetResizable()


def test_the_selected_surface_shows_its_fit_and_settings(surface_plugin):
    plugin = surface_plugin
    dock = plugin.surfaces_dock
    record = _made(plugin, window_m=0.035)
    assert dock.details.isHidden()
    dock.table.selectRow(0)
    assert not dock.details.isHidden() and dock.details.title() == "Bowl"
    assert dock.form.window_spin.value() == 3.5
    labels = [dock.fit_form.itemAt(i, dock.fit_form.ItemRole.LabelRole) for i in range(4)]
    assert [w.widget().text() for w in labels] == ["Picks", "Offset", "Cover", "Built"]
    assert dock.stale_label.isHidden()
    assert record.feature_id in dock.selected_ids()


def test_changing_a_setting_marks_it_stale_and_rebuild_clears_it(surface_plugin):
    plugin = surface_plugin
    dock = plugin.surfaces_dock
    record = _made(plugin)
    dock.table.selectRow(0)
    first_build = plugin.surfaces.state(record.feature_id).report["files"]["npz"]
    dock.form.smoothing_spin.setValue(0.25)  # saved at once
    assert plugin.surfaces.records()[0].settings.smoothing_m == 0.25
    QCoreApplication.processEvents()
    assert _rows(dock)[0][4] == "stale"
    assert dock.stale_label.text().startswith("Stale: its settings changed")
    assert not dock.stale_label.isHidden()
    assert dock.table.selectedItems()  # the selection survived the refresh
    dock.rebuild_button.click()
    QCoreApplication.processEvents()
    assert _rows(dock)[0][4] == ""
    assert plugin.surfaces.state(record.feature_id).report["files"]["npz"] != first_build
    assert plugin.surfaces.state(record.feature_id).stale == ()
    assert [lyr.name() for lyr in _layers_of(record.feature_id)] == ["Bowl"]


def test_rebuild_with_surfaces_on_two_grids_builds_each_in_turn(surface_plugin, monkeypatch):
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo_qgis.session import Pick
    from plugin_testing import synthetic_dzt

    plugin = surface_plugin
    session = plugin.session
    root = session.root
    session.add_grid(Grid("Grid B", (20.0, 0.0), 0.0, 3.0, 12.0, "EPSG:32616", 0.5))
    extra = []
    for i in range(2):
        path = synthetic_dzt(root.parent / "raw", f"FILE__01{i}.DZT", n_traces=60)
        extra.append(Line.open(path, GridPlacement("Grid B", "y", 0.5 + i, 0.0, 1, path.stem)))
    session.add_lines(extra)
    keys = [
        k for k in list(session.keys()) if session.line_for_key(k).placement.grid_id == "Grid B"
    ]
    before = {f.id() for f in plugin.layers.layers["picks"].dataProvider().getFeatures()}
    for key, trace, time_ns in [(keys[0], 5, 10.0), (keys[0], 55, 11.0), (keys[1], 5, 10.5)]:
        plugin.layers.write_pick(
            Pick(key, trace, time_ns, None, None, None, "", "", "2026-11-13T00:00:00+00:00", None)
        )
    fids_b = sorted(
        {f.id() for f in plugin.layers.layers["picks"].dataProvider().getFeatures()} - before
    )
    a = _made(plugin, "A", build=False)
    b = plugin.surfaces.create("B", fids_b, SurfaceSettings(strength=0.0))
    calls = []
    real = plugin.surfaces.build

    def spy(ids, *, progress):
        calls.append(list(ids))
        return real(ids, progress=progress)

    monkeypatch.setattr(plugin.surfaces, "build", spy)
    plugin.surfaces_dock.refresh()
    plugin.surfaces_dock.table.selectAll()
    plugin.surfaces_dock.rebuild_button.click()
    assert sorted(calls) == sorted([[a.feature_id], [b.feature_id]])  # one grid's at a time
    assert all(plugin.surfaces.state(r.feature_id).built for r in (a, b))
    assert len(_layers_of(a.feature_id)) == 1 and len(_layers_of(b.feature_id)) == 1


def test_clicking_an_outlier_selects_its_pick_and_opens_its_line(surface_plugin, monkeypatch):
    plugin = surface_plugin
    # The map link also follows a selection to its line; hold the selection back so that what
    # opens the line and the trace here is the panel itself.
    selected = []
    monkeypatch.setattr(plugin.layers, "select_picks", selected.append)
    dock = plugin.surfaces_dock
    session = plugin.session
    record = _made(plugin, strength=1e9)  # every pick sits on a hole: all four are outliers
    dock.table.selectRow(0)
    assert dock.outlier_list.count() == 4
    outlier = plugin.surfaces.state(record.feature_id).report["outliers"][2]
    session.open_line(next(k for k in list(session.keys()) if k != outlier["line_key"]))
    assert session.current_key != outlier["line_key"]
    assert dock.outlier_list.item(2).text().endswith("on a hole")
    dock.outlier_list.itemClicked.emit(dock.outlier_list.item(2))
    (row,) = [
        r
        for r in plugin.surfaces.members(record.feature_id)
        if r.pick.line_key == outlier["line_key"] and r.pick.trace == outlier["trace"]
    ]
    assert selected == [[row.fid]]
    assert session.current_key == outlier["line_key"]
    assert session.current_trace == outlier["trace"]


def test_an_outlier_on_a_line_that_left_the_site_is_only_selected(surface_plugin):
    plugin = surface_plugin
    dock = plugin.surfaces_dock
    session = plugin.session
    record = _made(plugin, strength=1e9)
    dock.table.selectRow(0)
    outliers = plugin.surfaces.state(record.feature_id).report["outliers"]
    gone = outliers[0]["line_key"]
    other = next(k for k in list(session.keys()) if k != gone)
    session.open_line(other)
    session.remove_lines([gone])
    QCoreApplication.processEvents()
    dock.refresh()
    dock.table.selectRow(0)
    index = next(i for i, o in enumerate(dock._outliers) if o["line_key"] == gone)
    dock.outlier_list.itemClicked.emit(dock.outlier_list.item(index))
    assert gone not in list(session.keys())
    assert session.current_key == other  # its line is gone: nothing was opened
    assert len(plugin.layers.selected_pick_ids()) == 1  # but the pick is selected


def test_select_its_picks_and_add_and_remove_selected(surface_plugin):
    plugin = surface_plugin
    dock = plugin.surfaces_dock
    fids = plugin.pick_fids
    record = plugin.surfaces.create("Bowl", fids[:3], SurfaceSettings(strength=0.0))
    dock.refresh()
    dock.table.selectRow(0)
    dock.select_button.click()
    assert plugin.layers.selected_pick_ids() == sorted(fids[:3])
    plugin.layers.select_picks([fids[3]])
    dock.add_button.click()
    assert sorted(r.fid for r in plugin.surfaces.members(record.feature_id)) == sorted(fids)
    plugin.layers.select_picks([fids[0]])
    dock.remove_button.click()
    assert sorted(r.fid for r in plugin.surfaces.members(record.feature_id)) == sorted(fids[1:])
    # a refusal is shown, not raised: three picks is the least a surface may keep
    plugin.layers.select_picks([fids[1]])
    dock.remove_button.click()
    assert "at least 3 picks" in _shown(plugin)
    assert len(plugin.surfaces.members(record.feature_id)) == 3


def test_removing_picks_that_are_not_in_the_surface_says_so(surface_plugin):
    plugin = surface_plugin
    dock = plugin.surfaces_dock
    fids = plugin.pick_fids
    record = plugin.surfaces.create("Bowl", fids[:3], SurfaceSettings(strength=0.0))
    dock.refresh()
    dock.table.selectRow(0)
    plugin.layers.select_picks([fids[3]])  # not one of its picks
    dock.remove_button.click()
    assert "None of the picks selected" in _shown(plugin)
    assert len(plugin.surfaces.members(record.feature_id)) == 3


def _press(button_text):
    """A driver for a QMessageBox: press the button with this text."""

    def driver(box):
        (button,) = [b for b in box.buttons() if b.text().replace("&", "") == button_text]
        button.click()

    return driver


def test_delete_asks_first_and_keeps_the_picks(surface_plugin, drive_dialog):
    plugin = surface_plugin
    dock = plugin.surfaces_dock
    record = _made(plugin)
    dock.table.selectRow(0)
    asked = []

    def decline(box):
        asked.append((box.text(), sorted(b.text().replace("&", "") for b in box.buttons())))
        _press("Cancel")(box)

    drive_dialog(QDialog, "exec", decline)
    dock.delete_button.click()
    assert len(asked) == 1
    assert asked[0][0].startswith("Delete “Bowl”? Its 4 picks stay")
    assert asked[0][1] == ["Cancel", "Delete"]  # the mockup's buttons, not Yes/No
    assert [r.name for r in plugin.surfaces.records()] == ["Bowl"]  # declined: kept
    folder = plugin.surfaces.folder("Grid A")
    drive_dialog(QDialog, "exec", _press("Delete"))
    dock.delete_button.click()
    QCoreApplication.processEvents()
    assert plugin.surfaces.records() == []
    assert dock.table.rowCount() == 0
    saved = {f.id() for f in plugin.layers.layers["picks"].dataProvider().getFeatures()}
    assert set(plugin.pick_fids) <= saved  # the picks all stay
    assert _layers_of(record.feature_id) == []
    assert not list(folder.glob(f"{record.feature_id}*"))


def test_rename_refuses_a_taken_name(surface_plugin, answer_modal):
    plugin = surface_plugin
    dock = plugin.surfaces_dock
    plugin.surfaces.create("Bowl", plugin.pick_fids[:3], SurfaceSettings())
    other = plugin.surfaces.create("Ridge", plugin.pick_fids, SurfaceSettings())
    dock.refresh()
    ridge_row = [r[0] for r in _rows(dock)].index("Ridge")
    dock.table.selectRow(ridge_row)
    answer_modal(QInputDialog, "getText", (" bowl ", True))
    dock.rename_button.click()
    assert "already exists" in _shown(plugin)
    assert {r.name for r in plugin.surfaces.records()} == {"Bowl", "Ridge"}
    answer_modal(QInputDialog, "getText", ("Crest", True))
    dock.rename_button.click()
    QCoreApplication.processEvents()
    assert {r.name for r in plugin.surfaces.records()} == {"Bowl", "Crest"}
    assert other.feature_id in dock.selected_ids()  # still the selected row


def test_the_export_includes_surfaces_from_the_plugin(surface_plugin, drive_dialog, monkeypatch):
    from nsgeo_qgis import plugin as plugin_module
    from nsgeo_qgis.ui.paraview_dialog import ParaViewExportDialog
    from qgis.PyQt.QtWidgets import QDialog

    plugin = surface_plugin
    record = _made(plugin)
    seen = {}
    real = plugin_module.ParaViewExport

    def spy(session, dock, surfaces=None):
        export = real(session, dock, surfaces)
        seen["export"] = export
        return export

    monkeypatch.setattr(plugin_module, "ParaViewExport", spy)

    def driver(dialog):
        assert isinstance(dialog, ParaViewExportDialog)
        dialog.accept()

    drive_dialog(QDialog, "exec", driver)
    plugin.export_paraview()
    export = seen["export"]
    assert export.surfaces is plugin.surfaces and export.skipped_surfaces == []
    message = _shown(plugin)
    assert message.startswith("Exported Grid A for ParaView to ")
    folder = Path(message.split(" to ", 1)[1].split(". ")[0].rstrip("."))
    record_json = json.loads((folder / "export.json").read_text())
    assert [f["name"] for f in record_json["features"]] == [record.name]
    assert read_vtk_xml(folder / "features.vtp")["NumberOfPoints"] > 0


def test_an_export_names_the_surfaces_it_left_out(surface_plugin, drive_dialog, monkeypatch):
    from nsgeo_qgis import plugin as plugin_module
    from qgis.PyQt.QtWidgets import QDialog

    plugin = surface_plugin
    _made(plugin)
    real = plugin_module.ParaViewExport

    def leaving(session, dock, surfaces=None):
        export = real(session, dock, surfaces)
        inner = export.run

        def run(*a, **k):
            folder = inner(*a, **k)
            export.skipped_surfaces = ["Bowl"]
            return folder

        export.run = run
        return export

    monkeypatch.setattr(plugin_module, "ParaViewExport", leaving)
    drive_dialog(QDialog, "exec", lambda dialog: dialog.accept())
    plugin.export_paraview()
    assert "“Bowl” was left out" in _shown(plugin)


def test_unloading_disposes_the_surface_layers_and_the_panel(surface_plugin):
    plugin = surface_plugin
    record = _made(plugin)
    assert len(_layers_of(record.feature_id)) == 1
    plugin.unload()
    assert plugin.surfaces is None and plugin.surface_layers is None
    assert plugin.surfaces_dock is None
    assert _layers_of(record.feature_id) == []


def test_an_unfocused_wheel_changes_no_setting(surface_plugin, monkeypatch):
    from nsgeo_qgis.ui.surface_settings_form import SteadyComboBox
    from qgis.PyQt.QtCore import QPoint, QPointF, Qt
    from qgis.PyQt.QtGui import QWheelEvent

    plugin = surface_plugin
    dock = plugin.surfaces_dock
    _made(plugin)
    dock.table.selectRow(0)
    saved = []
    monkeypatch.setattr(plugin.surfaces, "set_settings", lambda *a: saved.append(a))
    assert isinstance(dock.form.join_combo, SteadyComboBox)
    assert isinstance(dock.grid_combo, SteadyComboBox)
    for combo in (dock.form.join_combo, dock.grid_combo):
        before = combo.currentIndex()
        event = QWheelEvent(
            QPointF(2, 2),
            QPointF(2, 2),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        combo.wheelEvent(event)
        assert combo.currentIndex() == before and not event.isAccepted()
    assert saved == []


def test_a_refresh_keeps_the_whole_selection(surface_plugin):
    plugin = surface_plugin
    dock = plugin.surfaces_dock
    plugin.surfaces.create("A", plugin.pick_fids[:3], SurfaceSettings())
    plugin.surfaces.create("B", plugin.pick_fids[1:], SurfaceSettings())
    dock.refresh()
    dock.table.selectAll()
    ids = set(dock.selected_ids())
    assert len(ids) == 2
    dock.refresh()
    assert set(dock.selected_ids()) == ids


def test_add_selected_picks_says_they_are_also_in_another_surface(surface_plugin):
    plugin = surface_plugin
    dock = plugin.surfaces_dock
    fids = plugin.pick_fids
    bowl = plugin.surfaces.create("Bowl", fids[:3], SurfaceSettings())
    ridge = plugin.surfaces.create("Ridge", [fids[3], fids[2], fids[1]], SurfaceSettings())
    dock.refresh()
    dock.table.selectRow([r[0] for r in _rows(dock)].index("Ridge"))
    plugin.layers.select_picks([fids[0]])
    dock.add_button.click()
    assert "“Bowl”" in _shown(plugin) and "also in" in _shown(plugin)
    assert "move" not in _shown(plugin)
    assert fids[0] in {r.fid for r in plugin.surfaces.members(ridge.feature_id)}
    assert fids[0] in {r.fid for r in plugin.surfaces.members(bowl.feature_id)}


def test_the_build_message_stays_until_it_is_closed(surface_plugin):
    plugin = surface_plugin
    record = plugin.surfaces.create("Bowl", plugin.pick_fids[:3], SurfaceSettings(strength=0.0))
    plugin.iface.messageBar().clearWidgets()
    plugin.build_surfaces([record.feature_id])
    item = plugin.iface.messageBar().currentItem()
    assert item is not None and "Bowl" in item.text()
    assert item.duration() == 0
    plugin.message("something else")
    assert plugin.iface.messageBar().currentItem().duration() == 6


def test_build_refuses_while_an_export_runs(surface_plugin, monkeypatch):
    from nsgeo_qgis import plugin as plugin_module
    from nsgeo_qgis.surface_plan import EXPORT_RUNNING

    plugin = surface_plugin
    record = _made(plugin, build=False)
    real = plugin_module.running_export
    monkeypatch.setattr(plugin_module, "running_export", lambda: object())
    try:
        plugin.build_surfaces([record.feature_id])
        assert _shown(plugin) == EXPORT_RUNNING
    finally:
        # Put it back by hand: `monkeypatch.undo()` would also lift the modal guards.
        monkeypatch.setattr(plugin_module, "running_export", real)
    assert not plugin.surfaces.state(record.feature_id).built


def test_the_progress_label_names_the_surface(surface_plugin, monkeypatch):
    plugin = surface_plugin
    record = _made(plugin, build=False)
    titles = []
    real = plugin._export_progress

    def spy(title, total, **kw):
        titles.append(title)
        return real(title, total, **kw)

    monkeypatch.setattr(plugin, "_export_progress", spy)
    plugin.build_surfaces([record.feature_id])
    assert titles == ["Building “Bowl”"]


def test_an_oserror_on_the_second_grid_still_syncs_and_reports_both(surface_plugin, monkeypatch):
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo_qgis.session import Pick
    from plugin_testing import synthetic_dzt

    plugin = surface_plugin
    session = plugin.session
    session.add_grid(Grid("Grid B", (20.0, 0.0), 0.0, 3.0, 12.0, "EPSG:32616", 0.5))
    extra = []
    for i in range(2):
        path = synthetic_dzt(session.root.parent / "raw", f"FILE__01{i}.DZT", n_traces=60)
        extra.append(Line.open(path, GridPlacement("Grid B", "y", 0.5 + i, 0.0, 1, path.stem)))
    session.add_lines(extra)
    keys = [
        k for k in list(session.keys()) if session.line_for_key(k).placement.grid_id == "Grid B"
    ]
    before = {f.id() for f in plugin.layers.layers["picks"].dataProvider().getFeatures()}
    for key, trace, time_ns in [(keys[0], 5, 10.0), (keys[0], 55, 11.0), (keys[1], 5, 10.5)]:
        plugin.layers.write_pick(
            Pick(key, trace, time_ns, None, None, None, "", "", "2026-11-13T00:00:00+00:00", None)
        )
    fids_b = sorted(
        {f.id() for f in plugin.layers.layers["picks"].dataProvider().getFeatures()} - before
    )
    a = _made(plugin, "A", build=False)
    b = plugin.surfaces.create("B", fids_b, SurfaceSettings(strength=0.0))
    real = plugin.surfaces.build

    def build(ids, *, progress):
        if list(ids) == [b.feature_id]:
            raise OSError("No space left on device")
        return real(ids, progress=progress)

    monkeypatch.setattr(plugin.surfaces, "build", build)
    messages = []
    monkeypatch.setattr(
        plugin, "message", lambda text, level=None, title="nsgeo", duration=6: messages.append(text)
    )
    plugin.build_surfaces([a.feature_id, b.feature_id])
    assert plugin.surfaces.state(a.feature_id).built  # A's build stands...
    assert len(_layers_of(a.feature_id)) == 1  # ...and is on the map
    assert any(m.startswith("Built “A”") for m in messages)
    assert any("Could not build “B”" in m and "No space left" in m for m in messages)
    assert plugin.surfaces_dock.table.item(0, 4).text() in ("", "not built")


def test_a_grid_that_lost_all_its_lines_reads_as_unavailable(surface_plugin):
    plugin = surface_plugin
    record = _made(plugin)
    plugin.session.remove_lines(list(plugin.session.keys()))
    QCoreApplication.processEvents()
    state = plugin.surfaces.state(record.feature_id)
    assert state.built and state.stale == ("unavailable",)
    plugin.surfaces_dock.refresh()  # the panel survives it
    assert _rows(plugin.surfaces_dock)[0][4] == "stale"
