"""The time cutoff through the whole plugin: Processing panel, session and
profile dock wired as `plugin.py` wires them. The dock-level behaviour is
in `test_plugin_profile_dock.py`; this file is what only the assembled
plugin can show, plus the real-data check.
"""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import StepStack, build_step
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.PyQt.QtWidgets import QMessageBox

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
