from __future__ import annotations

import nsgeo_qgis
import pytest
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QMessageBox


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
