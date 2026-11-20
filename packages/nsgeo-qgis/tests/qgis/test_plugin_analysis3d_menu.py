"""#227: the toolbar's 3D Analysis drop-down -- Surface from picks…, 3D view and
Export for ParaView… in one instant-popup button after Cut, and no ParaView…
button left on the Slices panel."""

from __future__ import annotations

from nsgeo_qgis.plugin import ANALYSIS_3D_TIP, PARAVIEW_TIP, NsgeoPlugin
from nsgeo_qgis.scene3d_plan import BUTTON_TIP
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication, QEvent
from qgis.PyQt.QtWidgets import QPushButton, QToolButton


def _the_four(plugin):
    return (plugin.act_analysis3d, plugin.act_surface, plugin.act_view3d, plugin.act_paraview)


def test_the_toolbar_has_a_3d_analysis_button_after_cut(fake_iface):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        button = plugin.toolbar.widgetForAction(plugin.act_analysis3d)
        assert isinstance(button, QToolButton) and button.text() == "3D Analysis"
        assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
        assert button.toolTip() == ANALYSIS_3D_TIP
        menu = button.menu()
        assert menu is plugin.analysis3d_menu and menu.toolTipsVisible()
        assert menu.actions() == [plugin.act_surface, plugin.act_view3d, plugin.act_paraview]
        assert [a.text() for a in menu.actions()] == [
            "Surface from picks…",
            "3D view",
            "Export for ParaView…",
        ]
        assert plugin.act_view3d.toolTip() == BUTTON_TIP
        assert plugin.act_paraview.toolTip() == PARAVIEW_TIP
        actions = plugin.toolbar.actions()
        i = actions.index(plugin.act_analysis3d)
        assert actions[i - 1].isSeparator() and actions[i - 2] is plugin.act_cut
        assert actions[i + 1].isSeparator() and actions[i + 2] is plugin.act_panels
        assert plugin.act_surface not in actions and plugin.act_view3d not in actions
    finally:
        plugin.unload()


def test_the_3d_analysis_button_and_its_entries_grey_until_a_site_opens(fake_iface, tmp_path):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        assert not any(a.isEnabled() for a in _the_four(plugin))
        folder = tmp_path / "site"
        folder.mkdir()
        plugin.session.new_site(folder)
        assert all(a.isEnabled() for a in _the_four(plugin))
        plugin.session.close_site()
        assert not any(a.isEnabled() for a in _the_four(plugin))
    finally:
        plugin.unload()


def test_unload_tidies_the_3d_analysis_button_away(fake_iface):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    menu, button = plugin.analysis3d_menu, plugin.act_analysis3d
    entries = list(menu.actions())
    plugin.unload()
    assert plugin.analysis3d_menu is None
    assert all(a is None for a in _the_four(plugin))
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(menu)
    assert sip.isdeleted(button)
    assert all(sip.isdeleted(a) for a in entries)


def test_the_slices_panel_has_no_paraview_button(fake_iface):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        dock = plugin.slices_dock
        assert not [b for b in dock.findChildren(QPushButton) if "ParaView" in b.text()]
        assert not hasattr(dock, "paraview_button")
    finally:
        plugin.unload()
