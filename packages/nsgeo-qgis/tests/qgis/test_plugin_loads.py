from __future__ import annotations

import nsgeo_qgis
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.plugin import _TABIFIED_KEY, NsgeoPlugin
from plugin_testing import synthetic_dzt
from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QCoreApplication, Qt
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
    text = item.text() if item is not None else ""
    assert "core" in text and ("build " in text or "development checkout" in text)

    plugin.unload()
    assert plugin.toolbar is None
    assert fake_iface.menu_actions == []
    assert plugin.loader is None


def test_the_plugin_builds_and_disposes_its_map_link(fake_iface):
    canvas = fake_iface.mapCanvas()
    before = len(canvas.scene().items())

    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    assert plugin.map_link is not None
    assert len(canvas.scene().items()) == before + 2

    plugin.unload()
    assert plugin.map_link is None
    assert len(canvas.scene().items()) == before


# ---- the pick tool, end to end through the plugin (M8, spec §4.1) ----------


def _plugin_with_one_line(fake_iface, tmp_path):
    """A loaded plugin over a site with one placed line, open as the
    working line. Returns (plugin, key) -- the caller calls unload()."""
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from plugin_testing import synthetic_dzt

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
    plugin.session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem))])
    key = plugin.session.keys()[0]
    plugin.session.open_line(key)
    return plugin, key


def test_the_pick_action_is_a_checkable_toggle_that_drives_the_view(
    fake_iface, tmp_path, answer_modal
):
    # NOTE on the brief's test: `_plugin_with_one_line`'s add_grid/add_lines
    # both dirty the session (SiteSession._set_dirty(True)) and this test
    # never closes it, so plugin.unload() below reaches
    # save_with_prompt(ask_first=True) and calls QMessageBox.question --
    # forbidden by this tier's `_no_unhandled_modals` autouse fixture
    # unless answered. Confirmed directly: run as the brief wrote it (no
    # `answer_modal`), this test failed in its own `finally` block with
    # "AssertionError: unexpected modal: QMessageBox.question(...)",
    # masking whatever the test body itself found. Every other file in
    # this tier that unloads a dirty plugin already answers Discard the
    # same way (test_plugin_gain_strip.py, test_plugin_import_dialog.py,
    # test_plugin_difference_presets.py) -- added here for consistency.
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin, _key = _plugin_with_one_line(fake_iface, tmp_path)
    try:
        assert plugin.act_pick is not None
        assert plugin.act_pick.isCheckable()

        plugin.act_pick.setChecked(True)
        plugin.act_pick.triggered.emit(True)
        assert plugin.profile_dock.view.cursor().shape() == Qt.CursorShape.CrossCursor

        plugin.act_pick.setChecked(False)
        plugin.act_pick.triggered.emit(False)
        assert plugin.profile_dock.view.cursor().shape() == Qt.CursorShape.ArrowCursor
    finally:
        plugin.unload()


def test_the_pick_action_is_disabled_until_a_line_is_open(fake_iface, tmp_path):
    """A crosshair over an empty profile invites a click that can do
    nothing. The action follows the working line, not merely the site."""
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    try:
        assert plugin.act_pick.isEnabled() is False

        from nsgeo.geometry.grid import Grid
        from nsgeo.geometry.placement import GridPlacement
        from nsgeo.model.survey import Line
        from plugin_testing import synthetic_dzt

        plugin.session.new_site(tmp_path)
        plugin.session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
        p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
        plugin.session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem))])
        # A site with no line open yet: still disabled.
        assert plugin.act_pick.isEnabled() is False

        plugin.session.open_line(plugin.session.keys()[0])
        assert plugin.act_pick.isEnabled() is True

        plugin.session.close_site()
        assert plugin.act_pick.isEnabled() is False
    finally:
        plugin.unload()


def test_disabling_the_pick_action_also_turns_the_crosshair_off(fake_iface, tmp_path):
    """Closing the site with the toggle still checked would otherwise
    leave the view in pick mode forever: the action greys out, so there
    is no control left to switch it back."""
    plugin, _key = _plugin_with_one_line(fake_iface, tmp_path)
    try:
        plugin.act_pick.setChecked(True)
        plugin.act_pick.triggered.emit(True)
        assert plugin.profile_dock.view.cursor().shape() == Qt.CursorShape.CrossCursor

        plugin.session.close_site()

        assert plugin.act_pick.isChecked() is False
        assert plugin.profile_dock.view.cursor().shape() == Qt.CursorShape.ArrowCursor
    finally:
        plugin.unload()


def test_a_pick_from_the_profile_reaches_the_picks_table(fake_iface, tmp_path, answer_modal):
    """The whole loop: ProfileView -> ProfileDock.pick_requested ->
    plugin -> session.add_pick -> SiteLayers -> the picks layer."""
    # See test_the_pick_action_is_a_checkable_toggle_that_drives_the_view's
    # NOTE: the session is dirty from _plugin_with_one_line and never
    # closed, so unload() below needs an answer for its save prompt.
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin, key = _plugin_with_one_line(fake_iface, tmp_path)
    try:
        plugin.profile_dock.view.pick_requested.emit(12, 18.0)

        assert plugin.layers.feature_count("picks") == 1
        feat = next(plugin.layers.layers["picks"].getFeatures())
        assert feat["line_key"] == key
        assert feat["trace"] == 12
        assert feat["time_ns"] == pytest.approx(18.0)
    finally:
        plugin.unload()


def test_a_pick_that_cannot_be_written_is_reported_not_swallowed(
    fake_iface, tmp_path, monkeypatch, answer_modal
):
    """session.add_pick raises by design. It is never connected directly
    to a signal: an exception escaping a slot reaches qFatal() in the CI
    container and aborts the job. The relay catches it and puts the
    reason on the message bar, where someone authoring data will see
    it."""
    # See test_the_pick_action_is_a_checkable_toggle_that_drives_the_view's
    # NOTE: the session is dirty from _plugin_with_one_line and never
    # closed, so unload() below needs an answer for its save prompt.
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin, _key = _plugin_with_one_line(fake_iface, tmp_path)
    try:
        said = []
        monkeypatch.setattr(plugin, "message", lambda text, *a, **kw: said.append(text))

        def boom(pick):
            raise RuntimeError("disk full")

        monkeypatch.setattr(plugin.layers, "write_pick", boom)
        plugin.profile_dock.view.pick_requested.emit(12, 18.0)

        assert plugin.layers.feature_count("picks") == 0
        assert any("disk full" in text for text in said)
    finally:
        plugin.unload()


def test_the_slices_dock_is_tabified_with_processing(fake_iface, qgis_app):
    """... and survives QGIS restoring its own window layout afterwards.

    M11 walkthrough: in a real QGIS 3.44 both docks came back from
    `tabifiedDockWidgets()` empty and sat stacked in one column, although
    `initGui()` had called `tabifyDockWidget`. Instrumented in that real
    QGIS, on this repo's own profile, the sequence is:

        1.4 s   our tab is in place
        2.67 s  QGIS restores the saved layout -- tab gone, main window
                resized in the same tick
        2.95 s  `initializationCompleted`

    So the restore is the thing that undoes it, and QGIS's own
    "startup is over" signal is the first moment after it. This test
    replays exactly that -- `restoreState` with the layout as it was
    BEFORE the tab, which is what QGIS itself does -- so it fails against
    any version that tabs only during `initGui()` or only from a timer.
    """
    QgsSettings().setValue(_TABIFIED_KEY, False)
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        assert plugin.slices_dock is not None
        assert plugin.slices_dock.objectName() == "nsgeoSlicesDock"
        main = fake_iface.mainWindow()
        # The layout QGIS has saved from a previous session: no tab.
        before_tab = main.saveState()
        assert plugin.slices_dock not in main.tabifiedDockWidgets(plugin.processing_dock)

        # The Plugin-Manager path: nothing will overwrite the layout, so
        # the timer's attempt is the one that sticks.
        QCoreApplication.processEvents()
        assert plugin.slices_dock in main.tabifiedDockWidgets(plugin.processing_dock)

        # The startup path: QGIS restores its saved layout over the top.
        assert main.restoreState(before_tab)
        assert plugin.slices_dock not in main.tabifiedDockWidgets(plugin.processing_dock)

        # ... and this is the moment the tab has to be re-applied.
        fake_iface.initializationCompleted.emit()
        tabbed = main.tabifiedDockWidgets(plugin.processing_dock)
        assert plugin.slices_dock in tabbed
        # Once only: the flag is now set, so a user who later drags the
        # two apart is not overruled on their next start.
        assert QgsSettings().value(_TABIFIED_KEY, False, type=bool)
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


def test_a_profile_that_has_already_been_tabbed_once_is_left_alone(fake_iface, qgis_app):
    """The flag is what keeps this from overruling the user every start.

    Someone who drags Slices out of the tab group has given QGIS their
    answer, and QGIS saves it; a plugin that re-tabs unconditionally on
    every startup would silently overwrite that answer forever.
    """
    QgsSettings().setValue(_TABIFIED_KEY, True)
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        main = fake_iface.mainWindow()
        QCoreApplication.processEvents()
        fake_iface.initializationCompleted.emit()
        assert plugin.slices_dock not in main.tabifiedDockWidgets(plugin.processing_dock)
    finally:
        plugin.unload()
        QgsSettings().setValue(_TABIFIED_KEY, False)


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


def test_a_source_change_clears_the_stale_slice_from_the_map(
    fake_iface, qgis_app, tmp_path, answer_modal
):
    """Fix round 1, Important 4. `set_source` empties the engine's lines
    SYNCHRONOUSLY (before any re-preparation even starts), but nothing
    called `refresh_slice()` again until the NEXT successful preparation
    -- `refresh_slice()`'s own early return (not prepared) set `_values =
    None` without emitting `slice_changed`, the only signal
    `plugin._on_slice_changed` uses to `clear()` the map layer. From the
    moment a combo changed, the map kept showing the PREVIOUS source's
    slice -- indefinitely if the new source never prepares, as here: grid
    B has no lines, so `_lines` stays empty even once "preparation"
    (trivially) finishes."""
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.session.new_site(tmp_path)
        plugin.session.add_grid(Grid("A", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
        lines = [
            Line.open(
                synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60),
                GridPlacement("A", "y", 1.0 + i, 0.0, 1, f"L{i}"),
            )
            for i in range(3)
        ]
        plugin.session.add_lines(lines)
        plugin.session.site.presets["p"] = [{"step": "dewow", "params": {}, "enabled": True}]
        plugin.session.presets_changed.emit()

        dock = plugin.slices_dock
        assert dock is not None
        dock.prepare()
        assert dock.engine.wait_for_preparation(20_000)
        dock.flush_debounce()  # apply the seeded default resolution and render once
        assert plugin.slice_layer is not None
        assert plugin.slice_layer.layer is not None, "the map must show something before the switch"

        plugin.session.add_grid(Grid("B", (100.0, 100.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
        dock.grid_combo.setCurrentText("B")  # grid B has no lines: "prepares" synchronously, empty
        assert not dock.engine.is_prepared

        assert plugin.slice_layer.layer is None, (
            "the stale slice from grid A must not still be on the map for a source with no lines"
        )
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    finally:
        plugin.unload()


def test_the_profile_band_follows_the_slice_window(fake_iface, qgis_app, tmp_path):
    """The one thing spec 9.3 adds to the profile view, end to end through
    the plugin's own wiring rather than by calling the dock directly."""
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.slices_dock.window_changed.emit(12.0, 16.0)
        assert plugin.profile_dock.view._slice_band == (12.0, 16.0)
        plugin.slices_dock.window_cleared.emit()
        assert plugin.profile_dock.view._slice_band is None
    finally:
        plugin.unload()


def test_the_profile_band_is_drawn_on_a_line_opened_after_the_window_moved(
    fake_iface, qgis_app, tmp_path, answer_modal
):
    """Walkthrough round 2, W8: "If I open the line AFTER I have moved the
    position slider, the slice's time window isn't drawn until I move the
    position slider again."

    The band is a property of the SLICE -- one window, identical on every
    line -- but it lives in per-line view state. `refresh_slice()` emits
    `window_cleared` on EVERY tick that cannot produce a slice: an
    exception, or a source that stopped being prepared. That wipes the
    band. Nothing ever puts it back, because `window_changed` only fires
    when the window CHANGES -- and it has not. So after any failed tick
    (W7's cell-size errors, say) the band stays gone through every line
    the user opens, until they happen to nudge the slider.

    Opening a line is therefore the moment to re-announce, which is the
    same gap `_resync_gain_strip` already closes for the gain strip:
    `line_opened` is the event the other docks never re-sync from.

    Note what the existing `test_the_profile_band_follows_the_slice_window`
    does NOT do -- it emits `window_changed` directly and never opens a
    line at all, so it passes either way.
    """
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        session = plugin.session
        session.new_site(tmp_path)
        session.add_grid(Grid("A", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
        lines = [
            Line.open(
                synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60),
                GridPlacement("A", "y", 1.0 + i, 0.0, 1, f"L{i}"),
            )
            for i in range(2)
        ]
        session.add_lines(lines)
        session.site.presets["p"] = [{"step": "dewow", "params": {}, "enabled": True}]
        session.presets_changed.emit()
        keys = session.keys()
        # Armed before the assertions: unload() takes the save-prompt path
        # whether or not they pass, and an unanswered modal would replace
        # the real failure with the conftest guard's own.
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)

        # A REAL window, not a hand-emitted signal: the dock has to be
        # holding one for there to be anything to re-announce, which is
        # the whole mechanism under test.
        dock = plugin.slices_dock
        dock.prepare()
        assert dock.engine.wait_for_preparation(20_000)
        dock.flush_debounce()
        assert dock.current_window() is not None

        session.open_line(keys[0])
        band = plugin.profile_dock.view._slice_band
        assert band is not None

        # Exactly what a failed tick does -- `refresh_slice()`'s own
        # error and not-prepared branches both emit this.
        dock.window_cleared.emit()
        assert plugin.profile_dock.view._slice_band is None

        session.open_line(keys[1])
        assert plugin.profile_dock.view._slice_band == band, (
            "a line opened after a failed tick cleared the band must show "
            "it again -- the window never stopped being current"
        )

        # ... and the other half of the guard: `line_opened("")` IS the
        # clear (no line open at all). Re-announcing onto that would draw
        # a slice band across an empty panel.
        session.line_opened.emit("")
        assert plugin.profile_dock.view._slice_band is None, (
            "with no line open there is nothing for a band to be drawn on"
        )
    finally:
        plugin.unload()
