from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def plugin(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT")
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5)))
    s.add_lines(lines)
    key = s.keys()[0]
    s.set_profiles(key, lines[0].load())
    s.open_line(key)
    yield plugin, s, key
    # Every test below leaves the session dirty (add_grid/add_lines/a
    # step append all dirty it, and only test_presets_save_apply_and_
    # persist ever calls session.save()), so plugin.unload()'s own "save
    # before unloading" prompt is a real QMessageBox.question -- left
    # undriven, tests/qgis/conftest.py's no-unhandled-modals guard raises
    # AssertionError out of this fixture's teardown on every test that
    # uses it, regardless of whether the test body itself passed.
    # Discard: nothing here needs the save to actually happen.
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_difference_view_shows_what_a_step_removed(plugin):
    plugin, s, key = plugin
    pd, prd = plugin.processing_dock, plugin.profile_dock
    pd.add_step("dewow")
    pd.add_step("background_mean")
    pd.list.setCurrentRow(1)
    pd.diff_button.setChecked(True)
    assert "background_mean" in prd.difference_label.text()
    diff = prd.current_radargram()
    result = s.stack_for(key).result()
    assert diff is not result
    np.testing.assert_allclose(diff.data, s.stack_for(key).intermediate(0).data - result.data)
    pd.diff_button.setChecked(False)
    assert prd.difference_label.text() == ""


def test_difference_view_declines_sample_count_changing_steps(plugin):
    plugin, s, key = plugin
    pd, prd = plugin.processing_dock, plugin.profile_dock
    s.append_step(key, build_step("time_zero", mode="sample", sample=40))  # deterministic crop
    pd.list.setCurrentRow(0)
    messages = []
    prd.error.connect(messages.append)
    pd.diff_button.setChecked(True)
    assert messages and "sample count" in messages[0]
    assert not pd.diff_button.isChecked()
    assert prd.difference_label.text() == ""


def _menu_action(menu, text):
    return next(a for a in menu.actions() if a.text() == text)


def test_presets_save_apply_and_persist(plugin, tmp_path):
    """The apply and delete steps trigger the real `QAction`s from the
    menu (`.trigger()`), not `apply_preset_named`/`session.delete_preset`
    called directly -- reading `action.text()` without ever firing it
    proved nothing about the actual menu wiring, the same hazard Task 16's
    dead menu path shipped past review with (see `add_menu`'s own
    triggered-for-real test in test_plugin_processing_dock.py)."""
    plugin, s, key = plugin
    pd = plugin.processing_dock
    pd.add_step("dewow")
    pd.add_step("gain_agc")
    pd.save_preset_named("campus")
    assert s.preset_names() == ["campus"]
    other = s.keys()[1]
    s.open_line(other)
    assert pd.list.count() == 0

    _menu_action(pd.presets_menu, "campus").trigger()
    assert [i.text() for i in (pd.list.item(r) for r in range(pd.list.count()))] == [
        "dewow",
        "gain_agc",
    ]
    s.save()
    assert '"presets"' in (tmp_path / "survey.nsgeo.json").read_text()

    delete_menu = _menu_action(pd.presets_menu, "Delete").menu()
    _menu_action(delete_menu, "campus").trigger()
    assert s.preset_names() == []


def test_save_preset_prompt_rejects_blank_names_and_cancel(plugin, answer_modal):
    """`_save_preset_prompt` (the "Save current stack as..." action) was
    the sole reason `QInputDialog.getText` joined this tier's forbidden-
    modal list, yet nothing drove it -- a guard added for a path nothing
    exercises is a guard nobody has shown is needed. Triggers the real
    menu action three times: Cancel, a blank name, and a whitespace-only
    name, each of which must leave no preset behind; a fourth real name
    then does save one, proving the rejections aren't just "nothing ever
    saves anything" from a dock with no steps."""
    plugin, s, key = plugin
    pd = plugin.processing_dock
    pd.add_step("dewow")
    action = _menu_action(pd.presets_menu, "Save current stack as…")

    answer_modal(QInputDialog, "getText", ("campus", False))  # Cancel
    action.trigger()
    assert s.preset_names() == []

    answer_modal(QInputDialog, "getText", ("", True))  # OK, but blank
    action.trigger()
    assert s.preset_names() == []

    answer_modal(QInputDialog, "getText", ("   ", True))  # OK, whitespace only
    action.trigger()
    assert s.preset_names() == []

    answer_modal(QInputDialog, "getText", ("campus", True))
    action.trigger()
    assert s.preset_names() == ["campus"]


def test_saving_over_an_existing_preset_name_asks_first(plugin, answer_modal):
    plugin, s, key = plugin
    pd = plugin.processing_dock
    pd.add_step("dewow")
    pd.save_preset_named("campus")
    original = list(s.site.presets["campus"])

    calls = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.No)
    pd.add_step("gain_agc")
    pd.save_preset_named("campus")
    assert calls  # asked before touching an existing name
    assert s.site.presets["campus"] == original  # declined: untouched

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Yes)
    pd.save_preset_named("campus")
    assert s.site.presets["campus"] != original  # confirmed: now includes gain_agc


def test_applying_a_preset_updates_the_form_and_gain_strip_for_the_selected_row(plugin):
    """Loading a preset replaces the whole stack in place, so every row
    keeps its index while its contents change underneath it -- exactly
    the shape that broke Task 17: a guard keyed on (key, row) alone left
    a stale form open, which then wrote its (wrong) values back and
    destroyed a step. ProcessingDock._show_form now also compares step
    object *identity* (`_shown_step`), and NsgeoPlugin._sync_gain_strip
    resyncs unconditionally on every real `step_selected` -- both are
    claimed to already handle this correctly; this proves it rather than
    assuming it, by actually selecting row 0 on one line's curve step
    (form + strip both showing it), then applying a preset that puts a
    plain, non-curve step at that same row 0 on a different line.
    """
    plugin, s, key = plugin
    pd, prd = plugin.processing_dock, plugin.profile_dock
    pd.add_step("gain_agc")
    pd.add_step_with_dialog("gain_curve")
    pd.save_preset_named("first")

    other = s.keys()[1]
    s.open_line(other)
    pd.add_step_with_dialog("gain_curve")  # row 0 on the OTHER line: a curve step
    assert pd.list.currentRow() == 0
    assert pd.form.step_name == "gain_curve"
    assert not prd.gain_strip.isHidden()

    pd.apply_preset_named("first")  # row 0 becomes gain_agc: no curve
    assert [pd.list.item(r).text() for r in range(pd.list.count())] == [
        "gain_agc",
        "gain_curve",
    ]
    assert pd.list.currentRow() == 0
    assert pd.form.step_name == "gain_agc"  # not the stale gain_curve form
    assert prd.gain_strip.isHidden()  # row 0 is gain_agc now: no curve to show


def test_difference_view_clears_when_switching_lines(plugin):
    """`_difference_index` lives on ProfileDock, `diff_button`'s checked
    state lives on ProcessingDock, and the two are kept in sync only by
    the signals each side emits -- the same "a view caches session state
    and lets it drift" shape as Task 17's parameter form and Task 18's
    gain strip. Opening a different line always resets the difference
    view (the old step index means nothing on a different stack), but
    left unchecked, `diff_button` would carry on claiming a mode that was
    already off underneath it."""
    plugin, s, key = plugin
    pd, prd = plugin.processing_dock, plugin.profile_dock
    pd.add_step("dewow")
    pd.add_step("background_mean")
    pd.list.setCurrentRow(1)
    pd.diff_button.setChecked(True)
    assert prd.difference_label.text() != ""

    other = s.keys()[1]
    s.open_line(other)

    assert not pd.diff_button.isChecked()
    assert prd.difference_label.text() == ""


def test_difference_view_recovers_when_the_differenced_step_disappears(plugin):
    """`StepStack.difference`/`intermediate` raise `IndexError` for an
    out-of-range index (stack.py), not only `ValueError` for a sample-
    count change -- and removing the differenced step (or applying a
    shorter preset, this task's own feature) produces exactly that. Left
    uncaught, it escapes `current_radargram` into the render slots' broad
    `except Exception`: logged Critical, the button still checked, the
    label still naming a step that no longer exists."""
    plugin, s, key = plugin
    pd, prd = plugin.processing_dock, plugin.profile_dock
    pd.add_step("dewow")
    pd.add_step("background_mean")
    pd.list.setCurrentRow(1)
    pd.diff_button.setChecked(True)
    assert prd.difference_label.text() != ""

    messages = []
    prd.error.connect(messages.append)
    s.remove_step(key, 1)  # the differenced step itself is gone

    assert messages and "out of range" in messages[0]
    assert not pd.diff_button.isChecked()
    assert prd.difference_label.text() == ""


def test_diff_button_is_disabled_with_no_line_open(plugin):
    plugin, s, key = plugin
    pd = plugin.processing_dock
    assert pd.diff_button.isEnabled()
    s.close_site()
    assert not pd.diff_button.isEnabled()
