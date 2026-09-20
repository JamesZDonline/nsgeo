from __future__ import annotations

import nsgeo_qgis
from nsgeo_qgis.plugin import NsgeoPlugin
from qgis.PyQt.QtWidgets import QDialog


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
        # Processing stays the visible tab: M11 adds a capability, it does
        # not take the screen away from the dock people already use.
        assert plugin.processing_dock.visibleRegion is not None
    finally:
        plugin.unload()


def test_unloading_closes_an_open_line_chooser(fake_iface, qgis_app, tmp_path):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.session.new_site(tmp_path)
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
