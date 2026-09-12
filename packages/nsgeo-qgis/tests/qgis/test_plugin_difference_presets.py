from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtWidgets import QMessageBox

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


def test_presets_save_apply_and_persist(plugin, tmp_path):
    plugin, s, key = plugin
    pd = plugin.processing_dock
    pd.add_step("dewow")
    pd.add_step("gain_agc")
    pd.save_preset_named("campus")
    assert s.preset_names() == ["campus"]
    other = s.keys()[1]
    s.open_line(other)
    assert pd.list.count() == 0
    pd.apply_preset_named("campus")
    assert [i.text() for i in (pd.list.item(r) for r in range(pd.list.count()))] == [
        "dewow",
        "gain_agc",
    ]
    assert [a.text() for a in pd.presets_menu.actions() if a.text() == "campus"]
    s.save()
    assert '"presets"' in (tmp_path / "survey.nsgeo.json").read_text()
    s.delete_preset("campus")
    assert s.preset_names() == []


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
