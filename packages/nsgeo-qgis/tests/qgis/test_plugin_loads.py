from __future__ import annotations

import nsgeo_qgis


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
