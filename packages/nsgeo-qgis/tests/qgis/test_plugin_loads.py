from __future__ import annotations

import nsgeo_qgis
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.plugin import NsgeoPlugin
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtWidgets import QDialog, QMessageBox


def test_class_factory_builds_a_plugin_that_adds_and_removes_its_ui(fake_iface):
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    assert plugin.toolbar is not None
    assert plugin.toolbar.objectName() == "nsgeoToolBar"
    assert [name for name, _ in fake_iface.menu_actions] == ["&nsgeo"]
    assert plugin.loader is not None

    plugin.show_about()
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "core" in item.text()

    plugin.unload()
    assert plugin.toolbar is None
    assert fake_iface.menu_actions == []
    assert plugin.loader is None


def test_the_plugin_builds_and_disposes_its_map_link(fake_iface):
    from nsgeo_qgis.plugin import NsgeoPlugin

    canvas = fake_iface.mapCanvas()
    before = len(canvas.scene().items())

    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    assert plugin.map_link is not None
    assert len(canvas.scene().items()) == before + 2

    plugin.unload()
    assert plugin.map_link is None
    assert len(canvas.scene().items()) == before


def test_the_slices_dock_is_tabified_with_processing(fake_iface, qgis_app):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        assert plugin.slices_dock is not None
        assert plugin.slices_dock.objectName() == "nsgeoSlicesDock"
        main = fake_iface.mainWindow()
        tabbed = main.tabifiedDockWidgets(plugin.processing_dock)
        assert plugin.slices_dock in tabbed
        # fix round 1, M5: the line this replaces --
        # `assert plugin.processing_dock.visibleRegion is not None` -- named
        # the bound method itself (no `()`), which is never None and so
        # could never fail; it pinned nothing. There is no reliable way to
        # ask an offscreen QMainWindow that is never `show()`n which
        # tabified dock is raised (`isVisible()` requires the whole
        # ancestor chain, including the top-level window, to be shown,
        # which this test suite deliberately never does for the whole
        # fixture's stability) -- so this only re-asserts the meaningful
        # half above (they are genuinely tabified together) and says so
        # rather than keep a check that could never fail.
    finally:
        plugin.unload()


def test_unloading_closes_an_open_line_chooser(fake_iface, qgis_app, tmp_path, answer_modal):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.session.new_site(tmp_path)
        # Ruling U: open_line_choice_dialog now needs a grid selected in
        # the Slices dock, and add_grid() dirties the session -- so
        # unload() below takes the save-prompt path this test must answer.
        plugin.session.add_grid(Grid("A", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.open_line_choice_dialog()
        assert plugin._line_choice_dialog is not None
        dialog = plugin._line_choice_dialog
        plugin.unload()
        # reject(), not close(): closeEvent only calls reject() on a
        # VISIBLE dialog, and this plugin hides dialogs deliberately.
        assert dialog.result() == QDialog.DialogCode.Rejected
    finally:
        if plugin.session is not None:
            plugin.unload()


def test_accepting_the_line_chooser_after_the_grid_changed_is_discarded(
    fake_iface, qgis_app, tmp_path, answer_modal
):
    """Fix round 3, Ruling Z: `LineChoiceDialog` is modeless and binds
    `grid_id` once, at open time. Nothing stops the user from changing
    the Source group's own grid combo while it sits open -- accepting
    afterwards must not commit the OLD grid's keys against the NEW
    grid's frame, which is exactly the `6 of 3 included` and silent
    trace drop Ruling U's own scoping exists to remove, just reached one
    step later than a cross-grid pick inside the dialog itself would
    have."""
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.session.new_site(tmp_path)
        plugin.session.add_grid(Grid("A", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
        plugin.session.add_grid(Grid("B", (100.0, 100.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
        line = Line.open(
            synthetic_dzt(tmp_path / "raw", "FILE__0001.DZT", n_traces=60),
            GridPlacement("A", "y", 1.0, 0.0, 1, "LA"),
        )
        plugin.session.add_lines([line])
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)

        plugin.open_line_choice_dialog()  # opened while the dock's grid combo shows "A"
        dialog = plugin._line_choice_dialog
        assert dialog is not None
        assert dialog.table.rowCount() == 1  # grid A's one line

        plugin.slices_dock.grid_combo.setCurrentText("B")  # changed while the dialog is open
        after_switch = plugin.slices_dock.included_keys()

        dialog.select_all()  # the (stale, grid-A) result the dialog would otherwise commit
        dialog.accept()

        assert plugin.slices_dock.included_keys() == after_switch, (
            "the OLD grid's line choice must not be committed after the grid changed"
        )
        item = fake_iface.messageBar().currentItem()
        assert item is not None and "grid changed" in item.text()
    finally:
        plugin.unload()
