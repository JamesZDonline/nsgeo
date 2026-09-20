from __future__ import annotations

import nsgeo_qgis
from nsgeo.geometry.grid import Grid
from nsgeo_qgis.plugin import NsgeoPlugin
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
