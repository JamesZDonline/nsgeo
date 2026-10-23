"""The time cutoff through the whole plugin: Processing panel, session and
profile dock wired as `plugin.py` wires them. The dock-level behaviour is
in `test_plugin_profile_dock.py`; this file is what only the assembled
plugin can show, plus the real-data check.
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import StepStack, build_step
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QLineEdit, QMessageBox

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


def _plugin_with_line(fake_iface, tmp_path, path=None):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = path or synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    return plugin, s, key


def _unload(plugin, answer_modal):
    # The session is dirty by now; see test_plugin_gain_strip.py's
    # `test_plugin_routes_strip_edits_through_replace_step`.
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    host = getattr(plugin, "_test_host", None)
    if host is not None:
        # Hand the form back to its dock before the host goes: a parentless
        # top-level left alive over the form crashes the process at exit.
        dock = plugin.processing_dock
        dock.form_area.addWidget(dock.form)
        host.close()
        host.deleteLater()
        QApplication.processEvents()
        plugin._test_host = None
    plugin.unload()


def test_selecting_the_cutoff_row_in_the_processing_panel_shows_the_line(
    fake_iface, tmp_path, answer_modal
):
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    dock = plugin.processing_dock
    dock.add_step("dewow")
    dock.add_step("time_cutoff")
    assert dock.list.currentRow() == 1
    assert plugin.profile_dock.view.cutoff_ns is not None
    dock.list.setCurrentRow(0)
    assert plugin.profile_dock.view.cutoff_ns is None
    _unload(plugin, answer_modal)


def test_typing_a_cutoff_moves_the_line(fake_iface, tmp_path, answer_modal):
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    dock = plugin.processing_dock
    dock.add_step("dewow")
    dock.add_step("time_cutoff")
    rg = s.stack_for(key).source
    target = rg.t0_ns + (rg.n_samples - 50) * rg.dt_ns
    dock.form.set_value("end_ns", repr(target))
    dock.form.commit()
    assert s.stack_for(key).entries[1][0].params["end_ns"] == pytest.approx(target)
    assert plugin.profile_dock.view.cutoff_ns == pytest.approx(target)
    _unload(plugin, answer_modal)


@needs_real_data
def test_a_real_line_clips_where_the_line_is_dropped(fake_iface, tmp_path, answer_modal):
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path, REAL_DZT[0])
    dock = plugin.processing_dock
    s.append_step(key, build_step("time_zero", mode="first_break", threshold=0.25))
    dock.add_step("time_cutoff")
    assert dock.list.currentRow() == 1
    zeroed = s.stack_for(key).intermediate(0)
    end = zeroed.t0_ns + 300 * zeroed.dt_ns
    plugin.profile_dock.view.cutoff_dragged.emit(end)
    dock.list.setCurrentRow(0)
    assert plugin.profile_dock.image.rg.n_samples == 300
    stack = s.stack_for(key)
    again = StepStack.from_dicts(stack.to_dicts())
    assert again.entries[1][0].params["end_ns"] == end
    _unload(plugin, answer_modal)


def _clip(plugin, s, key, keep):
    """Drag the selected cutoff to `keep` samples in; returns that end time."""
    rg = s.stack_for(key).source
    end = rg.t0_ns + keep * rg.dt_ns
    plugin.profile_dock.view.cutoff_dragged.emit(end)
    assert s.stack_for(key).result().n_samples == keep
    return end


def test_selecting_the_cutoff_with_the_difference_view_on_shows_the_line(
    fake_iface, tmp_path, answer_modal
):
    """Ruling R7, order 1. Selecting a new row re-aims an active difference
    view at it, and a cutoff changes the sample count, so the difference is
    declined. That decline must still leave the cutoff's own view, the
    whole record with the line over it, not background_mean's difference
    with no line and no way back but another row."""
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    pd, prof = plugin.processing_dock, plugin.profile_dock
    pd.add_step("dewow")
    pd.add_step("background_mean")
    pd.add_step("time_cutoff")
    end = _clip(plugin, s, key, 200)
    pd.list.setCurrentRow(1)
    pd.diff_button.setChecked(True)
    assert prof.difference_label.text() == "Difference: background_mean"
    errors = []
    prof.error.connect(errors.append)
    pd.list.setCurrentRow(2)
    stack = s.stack_for(key)
    assert prof.image.rg.n_samples == stack.source.n_samples
    np.testing.assert_array_equal(prof.image.rg.data, stack.result_bypassing(2).data)
    assert prof.view.cutoff_ns == end
    assert not pd.diff_button.isChecked()
    assert prof.difference_label.text() == ""
    assert len(errors) == 1 and "sample count" in errors[0]
    _unload(plugin, answer_modal)


def test_the_difference_view_over_a_selected_cutoff_keeps_the_line(
    fake_iface, tmp_path, answer_modal
):
    """Ruling R7, order 2: the cutoff is selected first, then Difference is
    pressed. Declined as above, and the line stays, rather than the whole
    unclipped record shown with no line and no veil."""
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    pd, prof = plugin.processing_dock, plugin.profile_dock
    pd.add_step("dewow")
    pd.add_step("time_cutoff")
    end = _clip(plugin, s, key, 200)
    errors = []
    prof.error.connect(errors.append)
    pd.diff_button.setChecked(True)
    stack = s.stack_for(key)
    np.testing.assert_array_equal(prof.image.rg.data, stack.result_bypassing(1).data)
    assert prof.view.cutoff_ns == end
    assert not pd.diff_button.isChecked()
    assert prof.difference_label.text() == ""
    assert len(errors) == 1 and "sample count" in errors[0]
    _unload(plugin, answer_modal)


def test_a_dragged_cutoff_survives_an_unedited_commit_of_the_form(
    fake_iface, tmp_path, answer_modal
):
    """R3 from the line's side. A drag writes an exact end time, and the
    form follows it with a rounding of that time. Focus leaving the field
    commits the form, which must not write the rounding back: that would
    move the cutoff by a sample and dirty the session on a focus change.
    Swept along the record, and checked to have met ends the form's text
    cannot hold exactly, or the sweep would prove nothing."""
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    pd, prof = plugin.processing_dock, plugin.profile_dock
    pd.add_step("dewow")
    pd.add_step("time_cutoff")
    rg = s.stack_for(key).source
    changed = []
    s.stack_changed.connect(changed.append)
    lossy = 0
    for m in range(1, rg.n_samples, 7):
        end = rg.t0_ns + m * rg.dt_ns
        prof.view.cutoff_dragged.emit(end)
        assert s.stack_for(key).entries[1][0].params["end_ns"] == end
        text = pd.form.editors["end_ns"].text()
        assert float(text) == pytest.approx(end, rel=1e-5, abs=1e-9)
        lossy += float(text) != end
        changed.clear()
        pd.form.commit()
        assert changed == [], f"{m} samples: {text!r} was written back"
        assert s.stack_for(key).entries[1][0].params["end_ns"] == end
    assert lossy > 0
    _unload(plugin, answer_modal)


def _show_form_with_other_field(plugin):
    """Moves the panel's form into a shown, active host so its spinbox can
    really hold focus, and returns a line edit elsewhere to move focus to.
    (The dock itself is never activated under the offscreen platform.)"""
    from qgis.PyQt.QtWidgets import QVBoxLayout, QWidget

    host = QWidget()
    layout = QVBoxLayout(host)
    other = QLineEdit()
    layout.addWidget(plugin.processing_dock.form)
    layout.addWidget(other)
    host.show()
    host.activateWindow()
    QTest.qWaitForWindowActive(host)
    plugin._test_host = host  # keep it alive for the test
    return other


def _typing_past_the_end_leaves_the_record_whole(fake_iface, tmp_path, answer_modal, path):
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path, path)
    dock = plugin.processing_dock
    s.append_step(key, build_step("time_zero", mode="first_break", threshold=0.25))
    dock.add_step("time_cutoff")
    zeroed = s.stack_for(key).intermediate(0)
    end = zeroed.t0_ns + zeroed.n_samples * zeroed.dt_ns
    assert s.stack_for(key).entries[1][0].params["end_ns"] == end
    before = plugin.profile_dock.image.rg.n_samples
    other = _show_form_with_other_field(plugin)
    changed = []
    s.stack_changed.connect(changed.append)
    committed = []
    dock.form.committed.connect(committed.append)

    # Focus out: really focus the spinbox, type, then move focus away.
    spin = dock.form.editors["end_ns"]
    spin.setFocus()
    assert spin.hasFocus()
    edit = spin.lineEdit()
    edit.selectAll()
    QTest.keyClicks(edit, "99999")
    other.setFocus()
    assert not spin.hasFocus()
    assert len(committed) == 1  # the focus-out really committed
    assert s.stack_for(key).entries[1][0].params["end_ns"] == end
    assert plugin.profile_dock.image.rg.n_samples == before == zeroed.n_samples
    assert changed == []

    # And through Enter.
    spin = dock.form.editors["end_ns"]
    edit = spin.lineEdit()
    edit.selectAll()
    QTest.keyClicks(edit, "99999")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert spin.value() == pytest.approx(end)
    assert s.stack_for(key).entries[1][0].params["end_ns"] == end
    assert changed == []
    _unload(plugin, answer_modal)


@needs_real_data
def test_typing_past_the_end_on_a_real_line_leaves_the_record_whole(
    fake_iface, tmp_path, answer_modal
):
    _typing_past_the_end_leaves_the_record_whole(fake_iface, tmp_path, answer_modal, REAL_DZT[0])


def test_typing_past_the_end_leaves_the_record_whole(fake_iface, tmp_path, answer_modal):
    _typing_past_the_end_leaves_the_record_whole(fake_iface, tmp_path, answer_modal, None)


def _return_with_nothing_typed_writes_nothing(fake_iface, tmp_path, answer_modal, path):
    """R10 through the assembled plugin: Return in an untouched field must
    not turn the exact end time into its 6-digit display."""
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path, path)
    pd, prof = plugin.processing_dock, plugin.profile_dock
    pd.add_step("time_cutoff")
    rg = s.stack_for(key).source
    changed = []
    s.stack_changed.connect(changed.append)
    lossy = 0
    for m in [rg.n_samples, *range(1, rg.n_samples, 11)]:  # the seeded limit, then a sweep
        end = rg.t0_ns + m * rg.dt_ns
        if m != rg.n_samples:
            prof.view.cutoff_dragged.emit(end)
        spin = pd.form.editors["end_ns"]
        lossy += float(spin.text()) != end
        changed.clear()
        dirty = s.dirty
        QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
        assert changed == [], f"{m} samples: Return wrote {spin.text()!r}"
        assert s.stack_for(key).entries[0][0].params["end_ns"] == end
        assert s.dirty == dirty
    assert lossy > 0
    _unload(plugin, answer_modal)


def test_return_with_nothing_typed_writes_nothing(fake_iface, tmp_path, answer_modal):
    _return_with_nothing_typed_writes_nothing(fake_iface, tmp_path, answer_modal, None)


@needs_real_data
def test_return_with_nothing_typed_writes_nothing_on_a_real_line(
    fake_iface, tmp_path, answer_modal
):
    _return_with_nothing_typed_writes_nothing(fake_iface, tmp_path, answer_modal, REAL_DZT[0])


def test_an_untouched_cutoff_above_its_range_survives_return_and_focus_out(
    fake_iface, tmp_path, answer_modal
):
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    pd = plugin.processing_dock
    rg = s.stack_for(key).source
    pd.add_step("time_cutoff")
    pd.list.setCurrentRow(0)
    plugin.profile_dock.view.cutoff_dragged.emit(rg.t0_ns + 20 * rg.dt_ns)
    pd.add_step("time_cutoff")  # seeded at the record end of what row 0 left: 20 samples
    pd.add_step("time_cutoff")
    stored = rg.t0_ns + rg.n_samples * rg.dt_ns
    s.replace_step(
        key, 2, build_step("time_cutoff", end_ns=stored)
    )  # above row 2's range (row 1's output)
    pd.list.setCurrentRow(2)
    spin = pd.form.editors["end_ns"]
    assert spin.maximum() < stored  # the stored value is outside the range
    other = _show_form_with_other_field(plugin)
    changed = []
    s.stack_changed.connect(changed.append)
    spin.setFocus()
    assert spin.hasFocus()
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    other.setFocus()
    assert not spin.hasFocus()
    pd.form.commit()
    assert changed == []
    assert s.stack_for(key).entries[2][0].params["end_ns"] == stored
    _unload(plugin, answer_modal)
