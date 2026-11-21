"""Time zero's line through the whole plugin: Processing panel, session and
profile dock wired as `plugin.py` wires them (spec §4.11, §4.12). Built the
way `test_plugin_time_cutoff.py` builds its plugin."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from plugin_testing import needs_real_data, synthetic_dzt
from qgis.PyQt.QtWidgets import QApplication, QMessageBox
from tests.real_data import CAMPUS_LINES, GPS_LINES

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)
GPS_GRID = Grid("G", (500.0, 700.0), 0.0, 30.0, 29.98, "EPSG:32616", 0.5)


def _plugin_with_line(fake_iface, tmp_path, path=None, grid=GRID, placement=None):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(grid)
    p = path or synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, placement or GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    return plugin, s, key


def _unload(plugin, answer_modal):
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    host = getattr(plugin, "_test_host", None)
    if host is not None:
        dock = plugin.processing_dock
        dock.form_area.addWidget(dock.form)
        host.close()
        host.deleteLater()
        QApplication.processEvents()
        plugin._test_host = None
    plugin.unload()


def _row_of(plugin, s, key, row=0):
    return s.stack_for(key).entries[row][0].params["sample"]


def test_dragging_time_zeros_line_writes_its_row(fake_iface, tmp_path, answer_modal):
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    try:
        s.append_step(key, build_step("time_zero", mode="sample", sample=20))
        plugin.processing_dock.list.setCurrentRow(0)
        dock = plugin.profile_dock
        rg = dock._shown_radargram
        dock.view.cutoff_dragged.emit(rg.t0_ns + 26 * rg.dt_ns)
        assert _row_of(plugin, s, key) == 26
        assert plugin.processing_dock.form.editors["sample"].value() == 26
        step = s.stack_for(key).entries[0][0]
        s._set_dirty(False)
        dock.view.cutoff_dragged.emit(dock.view.cutoff_ns)
        assert s.stack_for(key).entries[0][0] is step
        assert not s.dirty
    finally:
        _unload(plugin, answer_modal)


def test_a_typed_row_moves_the_line(fake_iface, tmp_path, answer_modal):
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    try:
        s.append_step(key, build_step("time_zero", mode="sample", sample=20))
        pd = plugin.processing_dock
        pd.list.setCurrentRow(0)
        dock = plugin.profile_dock
        t = dock.view.transform
        mid = (t.time_lo + t.time_hi) / 2
        dock.view.transform = t.with_window(t.trace_lo + 5, t.trace_hi - 5, mid - 5.0, mid + 5.0)
        tr = dock.view.transform
        z = dock.shown_zero_ns()
        before_window = (tr.time_lo + z, tr.time_hi + z)
        y_before = tr.y_of_time(dock.view.cutoff_ns)
        pd.form.set_value("sample", "30")
        pd.form.commit()
        assert _row_of(plugin, s, key) == 30
        rg = plugin.profile_dock._shown_radargram
        assert dock.view.cutoff_ns == pytest.approx(rg.t0_ns + 30 * rg.dt_ns)
        tr = dock.view.transform
        z2 = dock.shown_zero_ns()
        assert (tr.time_lo + z2, tr.time_hi + z2) == pytest.approx(before_window)
        # the picture held, so the line moved down by exactly the ten rows
        row_px = rg.dt_ns / (tr.time_hi - tr.time_lo) * tr.height
        assert tr.y_of_time(dock.view.cutoff_ns) - y_before == pytest.approx(10 * row_px)
        # A stale line reads 0 ns on its own clock too, so prove it is live: its
        # next drag must still be accepted (the identity check passes).
        assert dock._cutoff_step is s.stack_for(key).entries[0][0]
        dock.view.cutoff_dragged.emit(rg.t0_ns + 33 * rg.dt_ns)
        assert _row_of(plugin, s, key) == 33
    finally:
        _unload(plugin, answer_modal)


def test_after_a_drag_the_line_reads_zero_again_and_the_picture_holds(
    fake_iface, tmp_path, answer_modal
):
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    try:
        s.append_step(key, build_step("time_zero", mode="sample", sample=20))
        plugin.processing_dock.list.setCurrentRow(0)
        dock = plugin.profile_dock
        t = dock.view.transform
        mid = (t.time_lo + t.time_hi) / 2
        dock.view.transform = t.with_window(t.trace_lo + 5, t.trace_hi - 5, mid - 5.0, mid + 5.0)

        def radar_window():
            tr = dock.view.transform
            z = dock.shown_zero_ns()
            return (z + tr.time_lo, z + tr.time_hi)

        before = radar_window()
        rg = dock._shown_radargram
        dock.view.cutoff_dragged.emit(rg.t0_ns + 26 * rg.dt_ns)
        assert _row_of(plugin, s, key) == 26
        assert dock.view.cutoff_ns == pytest.approx(0.0, abs=1e-9)
        assert radar_window() == pytest.approx(before)
    finally:
        _unload(plugin, answer_modal)


def test_dragging_with_difference_on_keeps_it_off_and_writes_the_row(
    fake_iface, tmp_path, answer_modal
):
    """E's rule: selecting Time zero declines Difference; the drag does not
    bring it back, and still writes."""
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    try:
        pd = plugin.processing_dock
        s.append_step(key, build_step("time_zero", mode="sample", sample=20))
        pd.add_step("dewow")
        pd.list.setCurrentRow(1)
        pd.diff_button.setChecked(True)
        pd.list.setCurrentRow(0)
        assert not pd.diff_button.isChecked()
        dock = plugin.profile_dock
        rg = dock._shown_radargram
        dock.view.cutoff_dragged.emit(rg.t0_ns + 26 * rg.dt_ns)
        assert not pd.diff_button.isChecked()
        assert dock.difference_label.text() == ""
        assert _row_of(plugin, s, key) == 26
    finally:
        _unload(plugin, answer_modal)


def test_a_valid_difference_view_on_time_zero_draws_no_row_line(fake_iface, tmp_path, answer_modal):
    """With sample 0 nothing is cropped, so Difference on Time zero is not
    declined; its record is the difference, whose rows are not the step's."""
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    try:
        pd = plugin.processing_dock
        s.append_step(key, build_step("time_zero", mode="sample", sample=0))
        pd.list.setCurrentRow(0)
        assert plugin.profile_dock.view.cutoff_ns is not None
        pd.diff_button.setChecked(True)
        assert pd.diff_button.isChecked()
        assert plugin.profile_dock.difference_label.text() != ""
        assert plugin.profile_dock.view.cutoff_ns is None
        pd.diff_button.setChecked(False)
        assert plugin.profile_dock.view.cutoff_ns is not None
    finally:
        _unload(plugin, answer_modal)


def test_switching_a_later_time_zero_into_sample_seeds_from_what_it_receives(
    fake_iface, tmp_path, answer_modal
):
    """Review Focus 1: [dewow, time_zero(first_break), gain_agc]. At threshold
    0.25 the source's first break is row 40 and the dewowed record's is 33."""
    from nsgeo.processing import first_break_row_or_none

    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    try:
        pd = plugin.processing_dock
        s.append_step(key, build_step("dewow"))
        s.append_step(key, build_step("time_zero", mode="first_break", threshold=0.25))
        s.append_step(key, build_step("gain_agc"))
        st = s.stack_for(key)
        assert first_break_row_or_none(st.source, 0.25) == 40
        assert first_break_row_or_none(st.intermediate(0), 0.25) == 33
        pd.list.setCurrentRow(1)
        pd.form.set_value("mode", "sample")
        pd.form.commit()
        assert _row_of(plugin, s, key, 1) == 33
        rg = plugin.profile_dock._shown_radargram
        assert plugin.profile_dock.view.cutoff_ns == pytest.approx(0.0, abs=1e-6)
        assert round(-rg.t0_ns / rg.dt_ns) == 33
    finally:
        _unload(plugin, answer_modal)


def _by_eye(plugin, s, key, seed):
    """The three checks of spec §4.11 on a real line: switching first_break ->
    sample seeds `seed`; selecting shows the line at 0 ns with `seed` rows
    above; dragging two rows up writes seed - 2."""
    pd = plugin.processing_dock
    dock = plugin.profile_dock
    s.append_step(key, build_step("time_zero", mode="first_break"))
    pd.list.setCurrentRow(0)
    pd.form.set_value("mode", "sample")
    pd.form.commit()
    assert _row_of(plugin, s, key) == seed
    rg = dock._shown_radargram
    assert dock.view.cutoff_ns == pytest.approx(0.0, abs=1e-6)
    assert round(-rg.t0_ns / rg.dt_ns) == seed
    dock.view.cutoff_dragged.emit(rg.t0_ns + (seed - 2) * rg.dt_ns)
    assert _row_of(plugin, s, key) == seed - 2
    assert dock.view.cutoff_ns == pytest.approx(0.0, abs=1e-6)


@needs_real_data
def test_time_zero_by_eye_on_the_campus_line(fake_iface, tmp_path, answer_modal):
    path = next(p for p in CAMPUS_LINES if p.name == "FILE__007.DZT")
    plugin, s, key = _plugin_with_line(
        fake_iface, tmp_path, path, placement=GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__007")
    )
    try:
        _by_eye(plugin, s, key, 49)
    finally:
        _unload(plugin, answer_modal)


@pytest.mark.skipif(not GPS_LINES, reason="needs the with-dzg lines in tests/data/local")
def test_time_zero_by_eye_on_a_gps_line(fake_iface, tmp_path, answer_modal):
    path = next(p for p in GPS_LINES if p.name == "FILE__010.DZT")
    plugin, s, key = _plugin_with_line(
        fake_iface,
        tmp_path,
        path,
        grid=GPS_GRID,
        placement=GridPlacement("G", "y", 0.25, 0.0, 1, "FILE__010"),
    )
    try:
        _by_eye(plugin, s, key, 44)
    finally:
        _unload(plugin, answer_modal)
