"""#84: the toolbar's Panels button -- one entry per panel, three layouts.

"Open" below means not closed (`isHidden()` is False), which a panel
still is while it sits behind another tab. "In front" is
`QgsDockWidget.isUserVisible()`: open AND the raised tab. The two differ
only for Processing and Slices, which share a tab group, and that
difference is most of what these tests are about.
"""

from __future__ import annotations

import pytest
from nsgeo_qgis.plugin import _TABIFIED_KEY, NsgeoPlugin
from qgis.core import QgsSettings
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication, QEvent
from qgis.PyQt.QtWidgets import QToolButton

PANELS = ("Survey", "Profile", "Processing", "Slices")
LAYOUTS = ("Profile work", "Slices work", "Show all")


def _entries(plugin):
    return {a.text(): a for a in plugin.panels_menu.actions() if a.text()}


def _docks(plugin):
    return dict(
        zip(
            PANELS,
            (plugin.survey_dock, plugin.profile_dock, plugin.processing_dock, plugin.slices_dock),
        )
    )


def _open(plugin):
    return {name for name, dock in _docks(plugin).items() if not dock.isHidden()}


def _choose(plugin, text):
    _entries(plugin)[text].trigger()
    QCoreApplication.processEvents()


@pytest.fixture
def shown_plugin(fake_iface, qgis_app):
    """The plugin in a SHOWN main window, Slices tabbed onto Processing as
    on a first start.

    Shown, unlike most of this tier: which tab is in front, and the sizes
    a panel comes back at, only exist on a window that has been laid out.
    """
    QgsSettings().setValue(_TABIFIED_KEY, False)
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    main = fake_iface.mainWindow()
    main.resize(1400, 900)
    main.show()
    QCoreApplication.processEvents()  # runs the tabify timer
    try:
        assert plugin.slices_dock in main.tabifiedDockWidgets(plugin.processing_dock)
        assert plugin.processing_dock.isUserVisible()
        assert not plugin.slices_dock.isUserVisible()
        yield plugin
    finally:
        plugin.unload()
        main.close()
        QgsSettings().setValue(_TABIFIED_KEY, False)


def test_the_panels_button_drops_down_the_four_panels_then_the_layouts(fake_iface):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        button = plugin.toolbar.widgetForAction(plugin.act_panels)
        assert isinstance(button, QToolButton)
        assert button.text() == "Panels"
        assert button.menu() is plugin.panels_menu
        # One click opens the menu: the button does nothing else.
        assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
        actions = plugin.panels_menu.actions()
        assert [a.text() for a in actions] == [*PANELS, "", *LAYOUTS]
        assert actions[4].isSeparator()
        assert all(a.isCheckable() for a in actions[:4])
        assert not any(a.isCheckable() for a in actions[5:])
    finally:
        plugin.unload()


def test_every_open_panel_is_ticked_even_the_one_behind_a_tab(shown_plugin):
    assert [a.isChecked() for a in shown_plugin.panels_menu.actions()[:4]] == [True] * 4


def test_a_panel_entry_follows_its_panel_however_it_is_closed(shown_plugin):
    survey = _entries(shown_plugin)["Survey"]
    shown_plugin.survey_dock.close()  # the panel's own close button
    assert not survey.isChecked()
    shown_plugin.survey_dock.toggleViewAction().trigger()  # QGIS's View > Panels
    assert survey.isChecked()


def test_a_panel_entry_keeps_its_name_when_the_panel_retitles_itself(fake_iface):
    """The Profile panel's title names the open line, and a dock's own
    `toggleViewAction()` takes its text from the title: used as the menu
    entry, it would read "nsgeo Profile · FILE__001 · 6301 traces"."""
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.profile_dock.setWindowTitle("nsgeo Profile · FILE__001 · 6301 traces")
        assert [a.text() for a in plugin.panels_menu.actions()[:4]] == list(PANELS)
    finally:
        plugin.unload()


def test_unticking_a_panel_closes_it_even_behind_another_tab(shown_plugin):
    # Slices starts open but behind Processing: QgsDockWidget's own
    # setUserVisible(False) does nothing to a panel in that state.
    _choose(shown_plugin, "Slices")
    assert shown_plugin.slices_dock.isHidden()
    assert not _entries(shown_plugin)["Slices"].isChecked()


def test_ticking_a_closed_panel_brings_it_back_in_front_of_its_tab_group(fake_iface, shown_plugin):
    main = fake_iface.mainWindow()
    _choose(shown_plugin, "Slices")
    _choose(shown_plugin, "Slices")
    assert not shown_plugin.slices_dock.isHidden()
    assert shown_plugin.slices_dock in main.tabifiedDockWidgets(shown_plugin.processing_dock)
    # Qt alone would put it back BEHIND Processing, out of sight, so the
    # tick would look as if it had done nothing.
    assert shown_plugin.slices_dock.isUserVisible()


def test_profile_work_leaves_survey_and_profile(shown_plugin):
    _choose(shown_plugin, "Profile work")
    assert _open(shown_plugin) == {"Survey", "Profile"}
    assert [a.isChecked() for a in shown_plugin.panels_menu.actions()[:4]] == [
        True,
        True,
        False,
        False,
    ]


def test_slices_work_leaves_survey_and_slices_with_slices_in_front(shown_plugin):
    _choose(shown_plugin, "Slices work")
    assert _open(shown_plugin) == {"Survey", "Slices"}
    assert shown_plugin.slices_dock.isUserVisible()


def test_show_all_after_profile_work_puts_every_panel_back_where_it_was(fake_iface, shown_plugin):
    main = fake_iface.mainWindow()
    profile_height = shown_plugin.profile_dock.height()
    right_width = shown_plugin.processing_dock.width()

    _choose(shown_plugin, "Profile work")
    _choose(shown_plugin, "Show all")

    assert _open(shown_plugin) == set(PANELS)
    assert shown_plugin.slices_dock in main.tabifiedDockWidgets(shown_plugin.processing_dock)
    assert shown_plugin.processing_dock.isUserVisible()  # the start-up front tab
    assert shown_plugin.profile_dock.height() == profile_height
    assert shown_plugin.processing_dock.width() == right_width


def test_show_all_after_slices_work_keeps_slices_in_front(fake_iface, shown_plugin):
    main = fake_iface.mainWindow()
    _choose(shown_plugin, "Slices work")
    _choose(shown_plugin, "Show all")
    assert _open(shown_plugin) == set(PANELS)
    assert shown_plugin.slices_dock in main.tabifiedDockWidgets(shown_plugin.processing_dock)
    assert shown_plugin.slices_dock.isUserVisible()


def test_a_panel_that_fails_to_open_is_reported_and_its_entry_stays_unticked(
    fake_iface, shown_plugin, monkeypatch
):
    _choose(shown_plugin, "Slices")

    def refuse(*_args):
        raise RuntimeError("no room")

    monkeypatch.setattr(shown_plugin.slices_dock, "setUserVisible", refuse)
    _choose(shown_plugin, "Slices")
    assert not _entries(shown_plugin)["Slices"].isChecked()
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "no room" in item.text()


def test_a_layout_that_fails_is_reported(fake_iface, shown_plugin, monkeypatch):
    def refuse(*_args):
        raise RuntimeError("no room")

    monkeypatch.setattr(shown_plugin.profile_dock, "setUserVisible", refuse)
    _choose(shown_plugin, "Profile work")
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "no room" in item.text()


def test_unloading_removes_the_panels_button_and_its_menu(fake_iface, qgis_app):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    menu, button = plugin.panels_menu, plugin.act_panels
    entries = list(menu.actions())
    plugin.unload()
    assert plugin.panels_menu is None
    assert plugin.act_panels is None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(menu)
    assert sip.isdeleted(button)
    assert all(sip.isdeleted(a) for a in entries)
