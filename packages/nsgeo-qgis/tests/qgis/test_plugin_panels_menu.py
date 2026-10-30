"""#84: the toolbar's Panels button -- one entry per panel, three layouts.

"Open" below means not closed (`isHidden()` is False), which a panel
still is while it sits behind another tab. "In front" (`_in_front`) is
open AND the current tab of its group. The two differ only for panels
that share a tab group -- Processing and Slices, or a panel tabbed with
one of QGIS's own -- and that difference is most of what these tests are
about.
"""

from __future__ import annotations

import time

import pytest
from nsgeo_qgis.plugin import _TABIFIED_KEY, NsgeoPlugin
from qgis.core import QgsSettings
from qgis.gui import QgsDockWidget
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication, QEvent, Qt
from qgis.PyQt.QtWidgets import QTabBar, QToolButton

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


def _bar_of(dock):
    """The tab bar on screen that has a tab for `dock`, or None."""
    title = dock.windowTitle()
    for bar in dock.parentWidget().findChildren(QTabBar):
        if bar.isVisible() and title in [bar.tabText(i) for i in range(bar.count())]:
            return bar
    return None


def _in_front(dock):
    """Open, and the current tab of its tab group if it is in one.

    Read off the main window's own tab bars -- what is on the screen --
    and NOT `QgsDockWidget.isUserVisible()`: that is QGIS's record of the
    dock's `visibilityChanged` signals, the very thing the plugin calls
    `setUserVisible` on, so a test reading it would be checking the
    plugin's bookkeeping against itself.
    """
    if dock.isHidden():
        return False
    bar = _bar_of(dock)
    return bar is None or bar.tabText(bar.currentIndex()) == dock.windowTitle()


def _wait_for(condition, what):
    """Run events until `condition()` holds.

    Qt 6.10 lays out a newly shown window's docks, or a dock newly tabbed
    into one, a pass of the event loop later than Qt 6.9 did: after the
    first pass the tab bar is still hidden and the docks sit off-screen
    (measured in qgis/qgis:4.2 rebuilt on Qt 6.10.2). Waiting on the
    layout itself, not on a count of passes, holds for both.
    """
    deadline = time.monotonic() + 5
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
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
    try:
        # Also runs the tabify timer, which the tab bar is waiting on.
        _wait_for(lambda: _bar_of(plugin.processing_dock) is not None, "Slices tabbed on")
        assert plugin.slices_dock in main.tabifiedDockWidgets(plugin.processing_dock)
        assert _in_front(plugin.processing_dock)
        assert not _in_front(plugin.slices_dock)
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
    assert _in_front(shown_plugin.slices_dock)


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
    assert _in_front(shown_plugin.slices_dock)


def test_a_layout_brings_its_panels_in_front_of_a_qgis_panel_tabbed_with_them(fake_iface, qgis_app):
    """Survey tabbed behind one of QGIS's own panels, as anyone may have
    arranged it: Profile work is for working in Survey, so it brings Survey
    to the front -- and leaves QGIS's panel open behind it.

    Arranged before the window is shown, as QGIS's restored layout is, and
    on a profile where Slices was tabbed on an earlier start. Not with
    `shown_plugin`: the first-start tabbing, done after the window is shown
    while another tab group is on it, segfaults Qt 6.10 about half the
    time -- on main as well, so not this feature's doing.
    """
    QgsSettings().setValue(_TABIFIED_KEY, True)
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    main = fake_iface.mainWindow()
    layers = QgsDockWidget("Layers", main)
    layers.setObjectName("Layers")
    main.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, layers)
    main.tabifyDockWidget(plugin.survey_dock, layers)
    main.resize(1400, 900)
    main.show()
    try:
        _wait_for(lambda: _bar_of(layers) is not None, "Layers tabbed on")
        layers.raise_()
        QCoreApplication.processEvents()
        assert not _in_front(plugin.survey_dock)

        _choose(plugin, "Profile work")

        assert _in_front(plugin.survey_dock)
        assert not layers.isHidden()
    finally:
        plugin.unload()
        main.close()
        QgsSettings().setValue(_TABIFIED_KEY, False)


def test_show_all_after_profile_work_puts_every_panel_back_where_it_was(fake_iface, shown_plugin):
    main = fake_iface.mainWindow()
    # Off their defaults, so that "as before" means as the user left it.
    main.resizeDocks([shown_plugin.processing_dock], [430], Qt.Orientation.Horizontal)
    QCoreApplication.processEvents()
    right_width = shown_plugin.processing_dock.width()
    profile_height = shown_plugin.profile_dock.height()

    _choose(shown_plugin, "Profile work")
    _choose(shown_plugin, "Show all")

    assert _open(shown_plugin) == set(PANELS)
    assert shown_plugin.slices_dock in main.tabifiedDockWidgets(shown_plugin.processing_dock)
    assert _in_front(shown_plugin.processing_dock)  # the start-up front tab
    assert shown_plugin.processing_dock.width() == right_width
    assert shown_plugin.profile_dock.height() == profile_height


def test_show_all_after_slices_work_keeps_slices_in_front(fake_iface, shown_plugin):
    main = fake_iface.mainWindow()
    main.resizeDocks([shown_plugin.profile_dock], [260], Qt.Orientation.Vertical)
    QCoreApplication.processEvents()
    profile_height = shown_plugin.profile_dock.height()

    _choose(shown_plugin, "Slices work")
    _choose(shown_plugin, "Show all")

    assert _open(shown_plugin) == set(PANELS)
    assert shown_plugin.slices_dock in main.tabifiedDockWidgets(shown_plugin.processing_dock)
    assert _in_front(shown_plugin.slices_dock)
    # Slices work closed Profile: it comes back at the height it was left at.
    assert shown_plugin.profile_dock.height() == profile_height


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
