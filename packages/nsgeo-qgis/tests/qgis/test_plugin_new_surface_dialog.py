"""M16 B Task 5: the toolbar's "Surface from picks…" and the New surface dialog.

The plugin runs over a synthetic site (conftest `surface_plugin`); the dialog is driven through
`drive_dialog`, so what it shows is read off the real dialog."""

from __future__ import annotations

from nsgeo.slices import SurfaceSettings
from nsgeo_qgis.surface_layers import PROP_FEATURE
from nsgeo_qgis.surface_plan import LOCKED_PICKS_TEXT
from nsgeo_qgis.ui.new_surface_dialog import NewSurfaceDialog
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QDialog


def _shown(plugin) -> str:
    item = plugin.iface.messageBar().currentItem()
    return item.text() if item is not None else ""


def _layers_of(fid):
    return [
        lyr
        for lyr in QgsProject.instance().mapLayers().values()
        if lyr.customProperty(PROP_FEATURE) == fid
    ]


def _open(plugin, drive_dialog, driver):
    """Trigger the toolbar action with `driver` answering the dialog; returns its calls."""
    calls = drive_dialog(QDialog, "exec", driver)
    plugin.act_surface.trigger()
    QCoreApplication.processEvents()
    return calls


def test_the_toolbar_action_opens_the_dialog_on_the_selected_picks(surface_plugin, drive_dialog):
    plugin = surface_plugin
    assert plugin.act_surface.text() == "Surface from picks…" and plugin.act_surface.isEnabled()
    plugin.layers.select_picks(plugin.pick_fids)
    seen = {}

    def driver(dialog):
        assert isinstance(dialog, NewSurfaceDialog)
        seen["count"] = dialog.count_label.text()
        seen["create"] = dialog.create_button.isEnabled()
        seen["refusal"] = dialog.refusal_label.text()
        dialog.name_edit.setText("Bowl")
        seen["create_named"] = dialog.create_button.isEnabled()
        dialog.reject()

    calls = _open(plugin, drive_dialog, driver)
    assert len(calls) == 1
    assert seen["count"].startswith("4 picks selected, all on Grid Grid A")
    assert "FILE__001 to FILE__002" in seen["count"]
    assert seen["refusal"] == "" and not seen["create"] and seen["create_named"]
    assert plugin.surfaces.records() == []  # cancelled: nothing was made


def test_the_toolbar_action_follows_the_site(fake_iface):
    from nsgeo_qgis.plugin import NsgeoPlugin

    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        assert not plugin.act_surface.isEnabled()
    finally:
        plugin.unload()


def test_with_no_picks_selected_it_says_how_to_select(surface_plugin, drive_dialog):
    seen = {}

    def driver(dialog):
        dialog.name_edit.setText("Bowl")
        seen["count"] = dialog.count_label.text()
        seen["refusal"] = dialog.refusal_label.text()
        seen["create"] = dialog.create_button.isEnabled()
        dialog.reject()

    _open(surface_plugin, drive_dialog, driver)
    assert seen["count"] == "No picks selected."
    assert seen["refusal"].startswith("Select picks on the map first")
    assert not seen["create"]


def test_the_dialog_shows_the_refusal_and_disables_create(surface_plugin, drive_dialog):
    plugin = surface_plugin
    plugin.layers.select_picks(plugin.pick_fids[:2])
    seen = {}

    def driver(dialog):
        dialog.name_edit.setText("Ditch")
        seen["refusal"] = dialog.refusal_label.text()
        seen["visible"] = not dialog.refusal_label.isHidden()
        seen["create"] = dialog.create_button.isEnabled()
        dialog.reject()

    _open(plugin, drive_dialog, driver)
    assert "at least 3 picks" in seen["refusal"] and "(2 selected)" in seen["refusal"]
    assert seen["visible"] and not seen["create"]


def test_the_dialog_states_picks_that_will_move(surface_plugin, drive_dialog):
    plugin = surface_plugin
    plugin.surfaces.create("Bowl", plugin.pick_fids, SurfaceSettings(strength=0.0))
    plugin.layers.select_picks(plugin.pick_fids[:3])
    seen = {}

    def driver(dialog):
        seen["note"] = dialog.note_label.text()
        seen["visible"] = not dialog.note_label.isHidden()
        dialog.reject()

    _open(plugin, drive_dialog, driver)
    assert seen["visible"]
    assert "All 3 are in “Bowl”; they will move to this surface" in seen["note"]
    assert "“Bowl” is left with 1 pick, too few to rebuild" in seen["note"]


def test_the_name_is_checked_as_it_is_typed(surface_plugin, drive_dialog):
    plugin = surface_plugin
    plugin.surfaces.create("Bowl", plugin.pick_fids[:3], SurfaceSettings(strength=0.0))
    plugin.layers.select_picks(plugin.pick_fids)
    seen = []

    def driver(dialog):
        for typed in ("", "  bowl ", "Other"):
            dialog.name_edit.setText(typed)
            seen.append((dialog.create_button.isEnabled(), dialog.name_problem.text(), typed))
        dialog.reject()

    _open(plugin, drive_dialog, driver)
    assert [s[0] for s in seen] == [False, False, True]
    assert seen[0][1] == "" and "already exists" in seen[1][1] and seen[2][1] == ""


def test_return_in_a_spin_box_does_not_create(surface_plugin, drive_dialog):
    plugin = surface_plugin
    plugin.layers.select_picks(plugin.pick_fids)
    seen = {}

    def driver(dialog):
        dialog.name_edit.setText("Bowl")
        dialog.show()  # a hidden dialog never reacts to its default button
        dialog.settings_button.setChecked(True)
        spin = dialog.form.window_spin
        spin.lineEdit().setText("3.5")
        QTest.keyClick(spin, Qt.Key.Key_Return)
        seen["window"] = spin.value()
        seen["result"] = dialog.result()
        seen["settings"] = dialog.settings()
        dialog.reject()  # (also hides it)

    _open(plugin, drive_dialog, driver)
    assert seen["window"] == 3.5  # the typed value was committed...
    assert seen["settings"].window_m == 0.035
    assert seen["result"] != QDialog.DialogCode.Accepted  # ...and nothing was accepted
    assert plugin.surfaces.records() == []


def test_a_spin_box_ignores_the_wheel_until_it_has_focus(qgis_app):
    from nsgeo_qgis.ui.surface_settings_form import SurfaceSettingsForm
    from qgis.PyQt.QtCore import QPoint, QPointF
    from qgis.PyQt.QtGui import QWheelEvent

    form = SurfaceSettingsForm()
    spin = form.strength_spin
    assert spin.focusPolicy() == Qt.FocusPolicy.StrongFocus
    event = QWheelEvent(
        QPointF(2, 2),
        QPointF(2, 2),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    before = spin.value()
    spin.wheelEvent(event)
    assert spin.value() == before and not event.isAccepted()


def test_create_and_build_adds_the_surface_and_its_layer(surface_plugin, drive_dialog):
    plugin = surface_plugin
    plugin.layers.select_picks(plugin.pick_fids)

    def driver(dialog):
        dialog.name_edit.setText("  Bowl ")
        dialog.form.strength_spin.setValue(0.0)  # the synthetic data has no typical strength
        dialog.accept()

    _open(plugin, drive_dialog, driver)
    (record,) = plugin.surfaces.records()
    assert record.name == "Bowl" and record.settings.strength == 0.0
    state = plugin.surfaces.state(record.feature_id)
    assert state.built and state.stale == ()
    assert [r.fid for r in plugin.surfaces.members(record.feature_id)] == plugin.pick_fids
    (layer,) = _layers_of(record.feature_id)  # synced after the build
    assert layer.name() == "Bowl"
    assert _shown(plugin).startswith("Built “Bowl”: ")


def test_a_locked_site_file_says_to_save_the_picks_layers_edits(
    surface_plugin, drive_dialog, monkeypatch
):
    plugin = surface_plugin
    plugin.layers.select_picks(plugin.pick_fids)

    def locked(*_a, **_k):
        raise RuntimeError("could not write the feature: database is locked")

    monkeypatch.setattr(plugin.layers, "write_feature", locked)

    def driver(dialog):
        dialog.name_edit.setText("Bowl")
        dialog.accept()

    _open(plugin, drive_dialog, driver)
    assert plugin.surfaces.records() == []
    assert _shown(plugin) == LOCKED_PICKS_TEXT
