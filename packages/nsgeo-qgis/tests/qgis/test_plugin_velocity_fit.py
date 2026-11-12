"""Velocity-fit mode through the assembled plugin: toolbar toggle, dock and
view wired as `plugin.py` wires them. Real Qt mouse events, not handler calls.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.velocity import VelocityModel
from nsgeo.velocity_fit import StoredFit, fit_at_zero, fit_hyperbola
from plugin_testing import apply_fit, send_move_while_pressed, synthetic_dzt
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QMessageBox

# Sized to its lines along their axis (60 traces = 1 m), as an import sizes a
# grid: the Profile is drawn against the grid's length, so a longer grid would
# leave the clicked pixels in blank space.
GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 1.0, "EPSG:32616", 0.5)
NO_MOD = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton


@pytest.fixture
def plugin(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    # The session is dirty and never closed; unload() would prompt to save.
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    lines = [
        Line.open(
            synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT", n_traces=60),
            GridPlacement("A", "y", float(i), 0.0),
        )
        for i in (1, 2)
    ]
    s.add_lines(lines)
    for key, line in zip(s.keys(), lines, strict=True):
        s.set_profiles(key, line.load())
    s.open_line(s.keys()[0])
    plugin.profile_dock.view.resize(500, 300)
    try:
        yield plugin
    finally:
        plugin.unload()


def _view(plugin):
    return plugin.profile_dock.view


def _local(v, x, y):
    r = v.image_rect()
    return QPoint(r.left() + x, r.top() + y)


def _click(v, x, y, button=LEFT):
    QTest.mouseClick(v, button, NO_MOD, _local(v, x, y))


def _check(act):
    act.setChecked(True)
    act.triggered.emit(True)


def test_turning_on_velocity_mode_turns_off_pick_mode(plugin):
    _check(plugin.act_pick)
    assert _view(plugin)._pick_mode is True

    _check(plugin.act_velocity)

    assert not plugin.act_pick.isChecked()
    assert _view(plugin)._pick_mode is False
    assert _view(plugin)._velocity_mode is True


def test_turning_on_pick_mode_turns_off_velocity_mode(plugin):
    _check(plugin.act_velocity)
    assert _view(plugin)._velocity_mode is True

    _check(plugin.act_pick)

    assert not plugin.act_velocity.isChecked()
    assert _view(plugin)._velocity_mode is False
    assert _view(plugin)._pick_mode is True


def test_the_velocity_action_is_disabled_and_unchecked_with_no_line(plugin):
    _check(plugin.act_velocity)
    assert plugin.act_velocity.isEnabled()

    plugin.session.close_site()

    assert not plugin.act_velocity.isEnabled()
    assert not plugin.act_velocity.isChecked()
    assert _view(plugin)._velocity_mode is False


def test_a_disabled_velocity_action_cannot_be_fired(plugin):
    plugin.session.close_site()
    assert not plugin.act_velocity.isEnabled()

    # Not `act.trigger()`: on this Qt a bare QAction.trigger() ignores
    # isEnabled() (it checks and emits regardless), so it proves nothing.
    # The toolbar button is the path a user has, and it does honour it.
    button = plugin.toolbar.widgetForAction(plugin.act_velocity)
    button.click()

    assert not plugin.act_velocity.isChecked()
    assert _view(plugin)._velocity_mode is False


def test_a_click_in_velocity_mode_adds_a_point(plugin):
    v = _view(plugin)
    _check(plugin.act_velocity)
    _click(v, 40, 30)
    _click(v, 60, 50)
    pts = plugin.profile_dock.velocity_points()
    assert len(pts) == 2
    assert pts[0][0] == v.transform.trace_index_at(40)  # the first click is the apex
    assert pts[0][1] == pytest.approx(v.transform.time_of_y(30))
    assert v._velocity_points == pts  # the shown zero is 0 here, so the view gets the same list


def test_a_velocity_click_on_the_axis_margin_adds_no_point(plugin):
    v = _view(plugin)
    _check(plugin.act_velocity)
    _click(v, 40, -5)  # above the image: a time before the record starts
    _click(v, -5, 30)  # on the depth-axis margin
    assert plugin.profile_dock.velocity_points() == []


def _right_click_at(v, pos, dx=0.0):
    r = v.image_rect()
    QTest.mouseClick(
        v,
        Qt.MouseButton.RightButton,
        NO_MOD,
        QPoint(round(r.left() + pos[0] + dx), round(r.top() + pos[1])),
    )


def test_a_right_click_drops_the_nearest_point_not_the_first_in_range(plugin):
    v = _view(plugin)
    _check(plugin.act_velocity)
    _click(v, 40, 30)
    _click(v, 50, 30)
    first, second = plugin.profile_dock.velocity_points()
    p1, p2 = v._velocity_positions(v.transform)
    assert 0 < p2[0] - p1[0] < 12  # both within reach of one click

    _right_click_at(v, p2, dx=-1)  # nearer the second, yet the first is in range too
    assert plugin.profile_dock.velocity_points() == [first]


def test_a_right_click_discards_only_within_the_tolerance(plugin):
    v = _view(plugin)
    _check(plugin.act_velocity)
    # The distances are literals on purpose: deriving them from
    # VELOCITY_DISCARD_PX let a 100 px tolerance pass this test.
    _click(v, 40, 30)
    (p,) = v._velocity_positions(v.transform)
    pt = plugin.profile_dock.velocity_points()

    _right_click_at(v, p, dx=14)  # just outside the 12 px tolerance
    assert plugin.profile_dock.velocity_points() == pt
    _right_click_at(v, p, dx=10)  # just inside it
    assert plugin.profile_dock.velocity_points() == []


def test_opening_another_line_clears_the_working_points(plugin):
    v = _view(plugin)
    _check(plugin.act_velocity)
    _click(v, 40, 30)
    _click(v, 60, 50)
    assert len(plugin.profile_dock.velocity_points()) == 2

    plugin.session.open_line(plugin.session.keys()[1])

    assert plugin.profile_dock.velocity_points() == []
    assert v._velocity_points == []


def test_velocity_mode_leaves_selection_drag_and_the_cutoff_handle_alone(plugin):
    v = _view(plugin)
    assert v._velocity_mode is False
    v.set_cutoff(40.0)
    line_y = round(v._cutoff_y(v.transform))
    QTest.mousePress(v, LEFT, NO_MOD, _local(v, 100, line_y))
    assert v._cutoff_grab is not None  # the handle grabbed; nothing swallowed it
    QTest.mouseRelease(v, LEFT, NO_MOD, _local(v, 100, line_y))
    assert plugin.profile_dock.velocity_points() == []

    # A plain press-drag-release off the line still selects a range.
    got = []
    v.range_selected.connect(lambda a, b: got.append((a, b)))
    QTest.mousePress(v, LEFT, NO_MOD, _local(v, 20, 10))
    send_move_while_pressed(v, _local(v, 120, 10))
    QTest.mouseRelease(v, LEFT, NO_MOD, _local(v, 120, 10))
    assert got and plugin.profile_dock.velocity_points() == []


def test_a_velocity_press_near_the_cutoff_line_adds_a_point_and_takes_no_grab(plugin):
    v = _view(plugin)
    v.set_cutoff(40.0)
    line_y = round(v._cutoff_y(v.transform))
    _check(plugin.act_velocity)

    _click(v, 100, line_y)

    assert v._cutoff_grab is None
    assert len(plugin.profile_dock.velocity_points()) == 1
    assert v.cutoff_ns == 40.0


# ---- fitting, the strip, and the buttons ----------------------------------
#
# Points go in through the view's own `velocity_point_requested` signal, the
# path a click takes after the view has turned pixels into (trace, ns): the
# pixel rounding of a real click would blur the exact numbers these tests pin.
# The 60-trace fixture lines are 1 m long (60 traces per metre).

TRACES_PER_M = 60.0
TRUE_V = 0.1
TRUE_T0 = 20.0
APEX_TRACE = 30


def _hyperbola_ns(trace: int) -> float:
    dx = (trace - APEX_TRACE) / TRACES_PER_M
    return math.sqrt(TRUE_T0**2 + (4.0 / TRUE_V**2) * dx**2)


def _click_hyperbola(plugin, traces=(APEX_TRACE, 15, 45, 5, 55)):
    v = _view(plugin)
    for tr in traces:
        v.velocity_point_requested.emit(tr, _hyperbola_ns(tr))


def _velocity_on(plugin):
    _check(plugin.act_velocity)
    return plugin.profile_dock


def test_the_strip_is_hidden_until_velocity_mode_is_on(plugin):
    dock = plugin.profile_dock
    assert dock.velocity_strip.isHidden()
    _check(plugin.act_velocity)
    assert not dock.velocity_strip.isHidden()
    plugin.act_velocity.setChecked(False)
    plugin.act_velocity.triggered.emit(False)
    assert dock.velocity_strip.isHidden()


def test_five_points_produce_a_velocity_and_a_sigma_in_the_strip(plugin):
    dock = _velocity_on(plugin)
    _click_hyperbola(plugin)

    fit = dock.velocity_fit_result()
    assert fit is not None
    assert fit.v_m_ns == pytest.approx(TRUE_V, rel=1e-2)
    assert fit.n_points == 5
    text = dock.velocity_readout.text()
    assert "±" in text
    assert "0.1000" in text  # a fixed four decimals, so the read-out does not jitter
    assert "5 pts" in text


def test_the_fitted_curve_is_handed_to_the_view_in_traces_and_ns(plugin):
    dock = _velocity_on(plugin)
    _click_hyperbola(plugin)

    curve = _view(plugin)._velocity_curve
    assert len(curve) == 200
    traces = [c[0] for c in curve]
    assert min(traces) == pytest.approx(0.0) and max(traces) == pytest.approx(59.0)
    tr, t = min(curve, key=lambda c: c[1])  # the apex: the curve's earliest time
    assert tr == pytest.approx(APEX_TRACE, abs=0.5)
    assert t == pytest.approx(dock.velocity_fit_result().t0_ns, abs=0.01)
    for tr, t in curve:  # and it follows the clicked data's own curve
        assert t == pytest.approx(
            math.sqrt(TRUE_T0**2 + (4 / TRUE_V**2) * ((tr - 30) / 60) ** 2), abs=0.25
        )


def test_three_points_show_the_solvers_own_refusal_and_no_curve(plugin):
    dock = _velocity_on(plugin)
    traces = (APEX_TRACE, 15, 45)
    _click_hyperbola(plugin, traces)

    x = np.array([tr / TRACES_PER_M for tr in traces])
    t = np.array([_hyperbola_ns(tr) for tr in traces])
    with pytest.raises(ValueError) as refusal:
        fit_hyperbola(x, t, x[0])
    assert str(refusal.value) in dock.velocity_readout.text()  # verbatim, not paraphrased
    assert dock.velocity_fit_result() is None
    assert _view(plugin)._velocity_curve == []


def test_a_line_with_no_traces_per_metre_explains_instead_of_raising(plugin, tmp_path):
    s = plugin.session
    _velocity_on(plugin)
    _click_hyperbola(plugin)  # a curve on the calibrated line, to be cleared
    assert len(_view(plugin)._velocity_curve) == 200
    path = synthetic_dzt(tmp_path / "raw", "TIMEMODE.DZT", n_traces=60, traces_per_metre=0.0)
    line = Line.open(path, GridPlacement("A", "y", 3.0, 0.0))
    s.add_lines([line])
    key = s.line_key(line)
    s.set_profiles(key, line.load())
    s.open_line(key)
    dock = _velocity_on(plugin)

    _view(plugin).velocity_point_requested.emit(10, 25.0)  # must not raise out of the slot

    assert "distance calibration" in dock.velocity_readout.text()
    assert dock.velocity_fit_result() is None
    assert _view(plugin)._velocity_curve == []


def _time_zero_to(plugin, sample):
    s = plugin.session
    s.append_step(s.keys()[0], build_step("time_zero", mode="sample", sample=sample))
    return _velocity_on(plugin)


def test_without_time_zero_the_note_names_the_first_break(plugin):
    dock = _velocity_on(plugin)
    assert "radar's own zero" in dock.velocity_note.text()


@pytest.mark.parametrize("sample", [49, 50, 51, 52])
def test_with_a_time_zero_step_the_note_is_quiet(plugin, sample):
    dock = _time_zero_to(plugin, sample)
    assert dock.velocity_note.text() == ""


def test_a_disabled_time_zero_brings_the_note_back(plugin):
    dock = _time_zero_to(plugin, 51)
    plugin.session.set_step_enabled(plugin.session.keys()[0], 0, False)
    assert "radar's own zero" in dock.velocity_note.text()


def test_the_note_gives_the_velocity_measured_from_the_first_break(plugin):
    from nsgeo.processing.timezero import first_break_ns

    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    text = dock.velocity_note.text()
    assert "Measured from the first break, this fit would be" in text
    first_break = first_break_ns(s.stack_for(key, insert=False).source)
    distance = s.line_for_key(key).distance_along()
    x = np.array([distance[tr] for tr, _ in dock.velocity_points()])
    t = np.array([t for _, t in dock.velocity_points()])
    v_break = fit_hyperbola(x, t - first_break, x[0]).v_m_ns
    v_now = dock.velocity_fit_result().v_m_ns
    assert f"{v_break:.4f} m/ns ({(v_break / v_now - 1) * 100:+.1f}%)" in text
    assert text.endswith("Add a Time zero step to measure from it.")


def test_apply_to_line_sets_the_line_velocity(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    v = dock.velocity_fit_result().v_m_ns

    dock.apply_line_button.click()

    assert s.resolved_velocity(key).surface_velocity == pytest.approx(v)
    assert s.line_for_key(key).velocity is not None
    assert "line override" in dock.velocity_label.text()
    assert s.dirty


def test_apply_to_grid_sets_the_grid_velocity(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    _click_hyperbola(plugin)
    v = dock.velocity_fit_result().v_m_ns

    dock.apply_grid_button.click()

    assert s.grid("A").velocity.surface_velocity == pytest.approx(v)
    assert s.resolved_velocity(s.keys()[1]).surface_velocity == pytest.approx(v)  # the other line


def test_save_fit_stores_it_without_changing_any_velocity(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    before = s.resolved_velocity(key)
    label_before = dock.velocity_label.text()
    _click_hyperbola(plugin)
    fit = dock.velocity_fit_result()

    dock.save_fit_button.click()

    line = s.line_for_key(key)
    assert line.velocity is None and s.grid("A").velocity is None  # nothing was applied
    assert s.resolved_velocity(key) == before
    assert dock.velocity_label.text() == label_before
    assert len(line.velocity_fits) == 1
    _, stored = next(iter(line.velocity_fits.items()))
    # No override was made, so there is no fit that "produced" it.
    assert line.velocity_from_fit is None
    assert stored.v_m_ns == pytest.approx(fit.v_m_ns)
    assert stored.apex_trace == APEX_TRACE
    assert [p[0] for p in stored.points] == [30, 15, 45, 5, 55]  # trace indices, not metres
    assert s.dirty


def test_save_fit_says_where_the_fit_went_and_keeps_the_readout(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    _click_hyperbola(plugin)
    readout = dock.velocity_readout.text()
    assert readout.startswith("v = ")
    assert "Set velocity override" not in readout
    v = dock.velocity_fit_result().v_m_ns
    sigma = dock.velocity_fit_result().v_stderr_m_ns

    dock.save_fit_button.click()

    # The points are cleared (#128), so the read-out carries the saved fit's
    # own numbers rather than the live fit's line.
    text = dock.velocity_readout.text()
    assert text.startswith(f"Fit saved: v = {v:6.4f} ± {sigma:6.4f} m/ns")
    assert "Set velocity override" in text
    assert "Survey panel" in text
    assert "next hyperbola" in text
    assert text.count("Fit saved") == 1
    assert len(s.line_for_key(s.keys()[0]).velocity_fits) == 1


def test_the_next_fit_action_replaces_the_saved_pointer(plugin):
    dock = _velocity_on(plugin)
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    assert "Fit saved" in dock.velocity_readout.text()

    dock.clear_velocity_button.click()
    assert "Fit saved" not in dock.velocity_readout.text()
    assert dock.velocity_readout.text().startswith("Click the hyperbola's apex")


def test_apply_after_save_names_the_saved_fit_as_the_overrides_source(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    dock.apply_line_button.click()
    line = s.line_for_key(key)
    (fit_id,) = line.velocity_fits
    assert line.velocity is not None and line.velocity_from_fit == fit_id


def test_apply_of_an_unsaved_fit_leaves_no_provenance(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    dock.apply_line_button.click()
    assert s.line_for_key(key).velocity_from_fit is not None

    _click_hyperbola(plugin)
    _view(plugin).velocity_point_discarded.emit(4)  # a different, unsaved fit
    dock.apply_line_button.click()

    line = s.line_for_key(key)
    assert line.velocity.surface_velocity == pytest.approx(dock.velocity_fit_result().v_m_ns)
    assert line.velocity_from_fit is None  # a bare "line" beats a false provenance


def test_save_alone_leaves_the_pointer_on_the_fit_that_drives_the_line(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    dock.apply_line_button.click()
    (first,) = s.line_for_key(key).velocity_fits

    _click_hyperbola(plugin)
    _view(plugin).velocity_point_discarded.emit(4)
    dock.save_fit_button.click()  # a second fit, stored but not applied

    line = s.line_for_key(key)
    assert len(line.velocity_fits) == 2
    assert line.velocity_from_fit == first


def test_apply_after_saving_a_different_fit_names_the_applied_one(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    _click_hyperbola(plugin)
    _view(plugin).velocity_point_discarded.emit(4)
    dock.save_fit_button.click()
    dock.apply_line_button.click()

    line = s.line_for_key(key)
    second = [i for i, f in line.velocity_fits.items() if len(f.points) == 4]
    assert line.velocity_from_fit == second[0]


def test_apply_after_the_saved_fit_was_deleted_applies_nothing_and_names_nothing(
    plugin, message_log
):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    (fit_id,) = s.line_for_key(key).velocity_fits
    s.remove_velocity_fit(key, fit_id)  # deleted from the velocity dialog meanwhile

    assert not dock.apply_line_button.isEnabled()  # the store is asked, not remembered
    assert not dock.apply_grid_button.isEnabled()
    assert dock.velocity_readout.text().startswith("Click the hyperbola's apex")
    assert "Fit saved" not in dock.velocity_readout.text()
    # The slots themselves, not the disabled buttons (a click on one emits
    # nothing): the Apply-time store check must hold on its own.
    dock._apply_velocity_to_line()
    dock._apply_velocity_to_grid()

    line = s.line_for_key(key)
    assert line.velocity is None and line.velocity_from_fit is None
    assert s.grid("A").velocity is None
    assert message_log == []


def _saved(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    (fit_id,) = s.line_for_key(key).velocity_fits
    return s, dock, key, fit_id


def test_save_fit_clears_the_working_points_but_the_saved_curve_stays(plugin, message_log):
    s, dock, key, _ = _saved(plugin)
    assert dock.velocity_points() == []
    assert dock.velocity_fit_result() is None
    v = _view(plugin)
    assert v._velocity_points == [] and v._velocity_curve == []
    assert len(v._saved_velocity_curves) == 1
    assert not dock.save_fit_button.isEnabled()
    assert message_log == []


def test_apply_to_line_after_save_sets_the_saved_fits_velocity_and_names_it(plugin, message_log):
    s, dock, key, fit_id = _saved(plugin)
    assert dock.apply_line_button.isEnabled()

    dock.apply_line_button.click()

    line = s.line_for_key(key)
    assert line.velocity.surface_velocity == pytest.approx(line.velocity_fits[fit_id].v_m_ns)
    assert line.velocity_from_fit == fit_id
    assert dock.velocity_readout.text().startswith("Fit saved")  # still the saved state
    assert message_log == []


def test_apply_to_grid_after_save_sets_the_saved_fits_velocity(plugin, message_log):
    s, dock, key, fit_id = _saved(plugin)
    assert dock.apply_grid_button.isEnabled()

    dock.apply_grid_button.click()

    assert s.grid("A").velocity.surface_velocity == pytest.approx(
        s.line_for_key(key).velocity_fits[fit_id].v_m_ns
    )
    assert s.line_for_key(key).velocity is None  # the line itself was not overridden
    assert message_log == []


def test_strip_apply_to_grid_after_save_records_the_saved_fit(plugin, message_log):
    from nsgeo.velocity_source import METHOD_FIT

    s, dock, key, fit_id = _saved(plugin)
    stored = s.line_for_key(key).velocity_fits[fit_id]

    dock.apply_grid_button.click()

    grid = s.grid("A")
    assert grid.velocity == VelocityModel.constant(stored.v_m_ns)
    record = grid.velocity_source
    assert record.method == METHOD_FIT and record.applied_at is not None
    (member,) = record.members
    assert (member.line_key, member.fit_id, member.line_label) == (key, fit_id, "FILE__001")
    assert member.names(fit_id, stored)
    assert member.v_m_ns == stored.v_m_ns and member.zero_ns == stored.zero_ns
    assert s.line_for_key(key).velocity_source is None  # the line got nothing
    assert message_log == []


def test_strip_apply_to_grid_of_an_unsaved_fit_records_nothing(plugin, message_log):
    s, dock, key, _ = _saved(plugin)
    dock.apply_grid_button.click()
    assert s.grid("A").velocity_source is not None
    _click_hyperbola(plugin)
    _view(plugin).velocity_point_discarded.emit(4)  # a different fit, not saved

    dock.apply_grid_button.click()

    grid = s.grid("A")
    assert grid.velocity == VelocityModel.constant(dock.velocity_fit_result().v_m_ns)
    assert grid.velocity_source is None  # a bare number beats a false record
    assert message_log == []


def test_strip_apply_to_grid_of_unsaved_points_a_stored_fit_shares_records_nothing(
    plugin, message_log
):
    # The line's same-points rule is not extended to the grid (task 4 brief).
    s, dock, key, _ = _saved(plugin)
    _click_hyperbola(plugin)  # the saved fit's points again, unsaved

    dock.apply_grid_button.click()

    assert s.grid("A").velocity is not None and s.grid("A").velocity_source is None
    assert message_log == []


def test_strip_apply_to_line_after_save_records_the_fit_at_the_lines_zero(plugin, message_log):
    s, dock, key, fit_id = _saved(plugin)
    stored = s.line_for_key(key).velocity_fits[fit_id]
    s.append_step(key, build_step("time_zero", mode="sample", sample=80))
    zero = s.line_zero(key)
    moved = fit_at_zero(stored, s.line_for_key(key).distance_along(), zero)
    assert moved.v_m_ns != pytest.approx(stored.v_m_ns, rel=1e-3)

    dock.apply_line_button.click()

    line = s.line_for_key(key)
    assert line.velocity == VelocityModel.constant(moved.v_m_ns)
    (member,) = line.velocity_source.members
    assert (member.line_key, member.fit_id, member.line_label) == (key, fit_id, "FILE__001")
    assert member.v_m_ns == moved.v_m_ns and member.t0_ns == moved.t0_ns
    assert member.zero_ns == pytest.approx(zero)
    assert line.velocity_from_fit == fit_id
    assert message_log == []


def test_strip_apply_to_line_of_points_a_stored_fit_shares_records_it_at_the_lines_zero(
    plugin, message_log
):
    s, dock, key, fit_id = _saved(plugin)
    stored = s.line_for_key(key).velocity_fits[fit_id]
    _click_hyperbola(plugin)  # the same clicks again, unsaved
    s.append_step(key, build_step("time_zero", mode="sample", sample=80))
    zero = s.line_zero(key)
    moved = fit_at_zero(stored, s.line_for_key(key).distance_along(), zero)
    assert dock.velocity_fit_result().v_m_ns == pytest.approx(moved.v_m_ns, rel=1e-12)

    dock.apply_line_button.click()

    line = s.line_for_key(key)
    assert line.velocity.surface_velocity == pytest.approx(moved.v_m_ns, rel=1e-12)
    (member,) = line.velocity_source.members
    assert member.fit_id == fit_id and member.v_m_ns == moved.v_m_ns
    assert member.zero_ns == pytest.approx(zero)
    assert message_log == []


def test_profile_label_names_the_grids_source(plugin, message_log):
    from nsgeo.velocity_source import SourceFit, VelocitySource
    from nsgeo_qgis.ui.profile_dock import velocity_source

    s = plugin.session
    key = s.keys()[0]
    fits = [
        StoredFit(20.0, 0.09, 0.004, 0.2, 30, ((30, 20.0), (15, 21.0)), "t"),
        StoredFit(41.0, 0.10, 0.004, 0.2, 20, ((20, 41.0), (10, 42.0)), "t"),
    ]
    ids = [s.add_velocity_fit(key, f) for f in fits]
    members = [SourceFit.of(key, i, "FILE__001", f) for i, f in zip(ids, fits, strict=True)]
    average = VelocitySource.from_fits(members, applied_at=None)
    s.apply_grid_velocity("A", VelocityModel.constant(average.v_m_ns), average)
    assert velocity_source(s, key) == "Grid A, average of 2 fits"
    assert "Grid A, average of 2 fits" in plugin.profile_dock.velocity_label.text()
    one = VelocitySource.from_fits(members[:1], applied_at=None)
    s.apply_grid_velocity("A", VelocityModel.constant(0.09), one)
    assert velocity_source(s, key) == "Grid A, fit on FILE__001"
    s.set_grid_velocity("A", VelocityModel.constant(0.09))
    assert velocity_source(s, key) == "Grid A"
    assert message_log == []


def test_the_next_point_ends_the_saved_state_and_apply_acts_on_the_new_fit(plugin, message_log):
    s, dock, key, fit_id = _saved(plugin)
    _click_hyperbola(plugin)  # the next hyperbola

    assert "Fit saved" not in dock.velocity_readout.text()
    assert dock.save_fit_button.isEnabled()
    dock.apply_line_button.click()
    line = s.line_for_key(key)
    assert line.velocity.surface_velocity == pytest.approx(dock.velocity_fit_result().v_m_ns)
    assert message_log == []


def test_one_new_point_after_save_leaves_apply_disabled_not_acting_on_the_saved_fit(
    plugin, message_log
):
    s, dock, key, _ = _saved(plugin)
    _view(plugin).velocity_point_requested.emit(30, _hyperbola_ns(30))
    assert not dock.apply_line_button.isEnabled()
    assert not dock.apply_grid_button.isEnabled()
    dock._apply_velocity_to_line()  # the slot, not the disabled button
    dock._apply_velocity_to_grid()
    assert s.line_for_key(key).velocity is None
    assert s.grid("A").velocity is None
    assert message_log == []


def test_clear_after_save_ends_the_saved_state(plugin, message_log):
    s, dock, key, _ = _saved(plugin)
    dock.clear_velocity_button.click()
    for b in (dock.apply_line_button, dock.apply_grid_button, dock.save_fit_button):
        assert not b.isEnabled()
    assert dock.velocity_readout.text().startswith("Click the hyperbola's apex")
    dock._apply_velocity_to_line()  # the slot, not the disabled button
    dock._apply_velocity_to_grid()
    assert s.line_for_key(key).velocity is None
    assert s.grid("A").velocity is None
    assert message_log == []


def test_switching_line_after_save_ends_the_saved_state(plugin, message_log):
    s, dock, key, _ = _saved(plugin)
    other = s.keys()[1]
    s.open_line(other)
    for b in (dock.apply_line_button, dock.apply_grid_button, dock.save_fit_button):
        assert not b.isEnabled()
    s.open_line(key)  # back again: the saved state did not wait here
    for b in (dock.apply_line_button, dock.apply_grid_button, dock.save_fit_button):
        assert not b.isEnabled()
    assert "Fit saved" not in dock.velocity_readout.text()
    dock._apply_velocity_to_line()  # the slot, not the disabled button
    assert s.line_for_key(key).velocity is None and s.line_for_key(other).velocity is None
    assert message_log == []


def test_turning_velocity_mode_off_after_save_ends_the_saved_state(plugin, message_log):
    s, dock, key, _ = _saved(plugin)
    plugin.act_velocity.setChecked(False)
    plugin.act_velocity.triggered.emit(False)
    plugin.act_velocity.setChecked(True)
    plugin.act_velocity.triggered.emit(True)
    assert not dock.apply_line_button.isEnabled()
    assert "Fit saved" not in dock.velocity_readout.text()
    dock._apply_velocity_to_line()  # the slot, not the disabled button
    assert s.line_for_key(key).velocity is None
    assert message_log == []


def test_a_time_zero_added_after_save_measures_the_saved_fit_from_it(plugin, message_log):
    # Save on the radar's own clock, then add the Time zero step the strip's
    # note suggests. The read-out and both Applies must give the fit measured
    # from the new zero -- the number the velocity dialog shows and applies --
    # not the one it was stored with.
    s, dock, key, fit_id = _saved(plugin)
    stored = s.line_for_key(key).velocity_fits[fit_id]
    s.append_step(key, build_step("time_zero", mode="sample", sample=80))
    zero = s.line_zero(key)
    assert zero != pytest.approx(stored.zero_ns)  # the zero really moved
    expected = fit_at_zero(stored, s.line_for_key(key).distance_along(), zero).v_m_ns
    assert expected != pytest.approx(stored.v_m_ns, rel=1e-3)  # and the number with it

    assert dock.apply_line_button.isEnabled() and dock.apply_grid_button.isEnabled()
    assert f"v = {expected:6.4f}" in dock.velocity_readout.text()
    dock.apply_line_button.click()
    dock.apply_grid_button.click()

    line = s.line_for_key(key)
    assert line.velocity.surface_velocity == pytest.approx(expected, rel=1e-12)
    assert line.velocity_from_fit == fit_id
    assert s.grid("A").velocity.surface_velocity == pytest.approx(expected, rel=1e-12)
    assert message_log == []


def test_a_saved_fit_that_cannot_be_measured_at_a_new_time_zero_is_never_applied(
    plugin, message_log
):
    # A zero late enough that the refit fails: the velocity dialog flags the
    # fit "cannot be fitted at this time zero" and never applies it. The
    # strip must not apply the stored number behind its back.
    s, dock, key, fit_id = _saved(plugin)
    stored = s.line_for_key(key).velocity_fits[fit_id]
    s.append_step(key, build_step("time_zero", mode="sample", sample=150))
    with pytest.raises(ValueError):
        fit_at_zero(stored, s.line_for_key(key).distance_along(), s.line_zero(key))

    assert not dock.apply_line_button.isEnabled()
    assert not dock.apply_grid_button.isEnabled()
    assert "Fit saved" not in dock.velocity_readout.text()
    dock._apply_velocity_to_line()  # the slots, not the disabled buttons
    dock._apply_velocity_to_grid()

    line = s.line_for_key(key)
    assert line.velocity is None and line.velocity_from_fit is None
    assert s.grid("A").velocity is None
    assert message_log == []


def test_apply_names_a_stored_fit_with_the_same_points_saved_before_another(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    (first,) = s.line_for_key(key).velocity_fits
    _click_hyperbola(plugin)
    _view(plugin).velocity_point_discarded.emit(4)
    dock.save_fit_button.click()  # the dock's last save is now a different fit
    _click_hyperbola(plugin)  # the first's points again

    dock.apply_line_button.click()

    assert s.line_for_key(key).velocity_from_fit == first


def test_adding_time_zero_moves_a_saved_fit_exactly_as_shifting_its_points(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    (fit_id,) = s.line_for_key(key).velocity_fits
    stored = s.line_for_key(key).velocity_fits[fit_id]
    _click_hyperbola(plugin)  # the same clicks again: the save cleared the working points
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    zero = s.line_zero(key)
    distance = s.line_for_key(key).distance_along()
    x = np.array([distance[tr] for tr, _ in stored.points])
    expected = fit_hyperbola(x, np.array([t for _, t in stored.points]) - zero, x[0])
    assert dock.velocity_fit_result().v_m_ns == pytest.approx(expected.v_m_ns, rel=1e-9)
    dock.apply_line_button.click()
    assert s.line_for_key(key).velocity_from_fit == fit_id  # points are compared on the radar clock


def test_a_saved_fit_records_the_zero_it_was_measured_from(plugin):
    s, dock = plugin.session, _time_zero_to(plugin, 51)
    key = s.keys()[0]
    _click_hyperbola(plugin, tuple(range(0, 60, 6)))
    fit_points = dock.velocity_points()
    assert all(t == pytest.approx(_hyperbola_ns(tr) + dock.shown_zero_ns()) for tr, t in fit_points)
    dock.save_fit_button.click()
    (stored,) = s.line_for_key(key).velocity_fits.values()
    assert stored.zero_ns == pytest.approx(s.line_zero(key))
    assert stored.points == tuple(fit_points)


def test_the_drawn_points_and_saved_curve_follow_the_shown_clock_after_a_time_zero(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    (stored,) = s.line_for_key(key).velocity_fits.values()
    _click_hyperbola(plugin)  # the save cleared the working points; draw them again
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    shown = dock.shown_zero_ns()
    zero = s.line_zero(key)
    assert shown == pytest.approx(zero)

    drawn = _view(plugin)._velocity_points
    assert [tr for tr, _ in drawn] == [tr for tr, _ in dock.velocity_points()]
    for (_, t_drawn), (_, t_radar) in zip(drawn, dock.velocity_points(), strict=True):
        assert t_drawn == pytest.approx(t_radar - shown, abs=1e-9)

    from nsgeo.velocity_fit import fit_at_zero

    distance = s.line_for_key(key).distance_along()
    refit_t0 = fit_at_zero(stored, distance, zero).t0_ns
    (curve,) = _view(plugin)._saved_velocity_curves
    # The apex time on the shown clock, which here is the line's clock.
    assert min(t for _, t in curve) == pytest.approx(refit_t0, abs=0.01)
    assert abs(refit_t0 - stored.t0_ns) > 0.03  # so the stored t0 would be caught


def test_the_fit_label_uses_the_refit_t0_after_a_zero_change(plugin):
    from nsgeo.velocity_fit import fit_at_zero
    from nsgeo_qgis.ui.profile_dock import velocity_source

    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    (fit_id,) = s.line_for_key(key).velocity_fits
    stored = s.line_for_key(key).velocity_fits[fit_id]
    apply_fit(s, key, fit_id)
    # Sample 52 puts the zero 0.17 ns after the radar's: enough to change the
    # label's one decimal.
    s.append_step(key, build_step("time_zero", mode="sample", sample=52))
    distance = s.line_for_key(key).distance_along()
    refit_t0 = fit_at_zero(stored, distance, s.line_zero(key)).t0_ns
    assert f"{refit_t0:.1f}" != f"{stored.t0_ns:.1f}"

    label = velocity_source(s, key)

    assert label == f"line override (fit at {refit_t0:.1f} ns)"


def test_working_points_stay_on_their_reflection_across_a_time_zero_change(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin, (APEX_TRACE, 15, 45))
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    shown_zero = dock.shown_zero_ns()
    assert shown_zero == pytest.approx(-0.0433, abs=1e-3)
    v = _view(plugin)
    for tr in (5, 55):
        v.velocity_point_requested.emit(tr, _hyperbola_ns(tr) - shown_zero)

    radar_t = [t for _, t in dock.velocity_points()]
    assert radar_t == pytest.approx([_hyperbola_ns(tr) for tr in (APEX_TRACE, 15, 45, 5, 55)])
    distance = s.line_for_key(key).distance_along()
    x = np.array([distance[tr] for tr in (APEX_TRACE, 15, 45, 5, 55)])
    expected = fit_hyperbola(x, np.array(radar_t) - s.line_zero(key), x[0])
    assert dock.velocity_fit_result().v_m_ns == pytest.approx(expected.v_m_ns, rel=1e-9)


def test_saving_twice_needs_new_points_and_keeps_both_under_distinct_ids(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    dock.save_fit_button.click()  # disabled: nothing is left to save (#128)
    assert len(s.line_for_key(s.keys()[0]).velocity_fits) == 1
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    assert sorted(s.line_for_key(s.keys()[0]).velocity_fits) == ["fit-1", "fit-2"]


def test_the_buttons_are_disabled_until_there_is_a_fit(plugin):
    dock = _velocity_on(plugin)
    for b in (dock.apply_line_button, dock.apply_grid_button, dock.save_fit_button):
        assert not b.isEnabled()
    _click_hyperbola(plugin)
    for b in (dock.apply_line_button, dock.apply_grid_button, dock.save_fit_button):
        assert b.isEnabled()


def test_clear_empties_the_points_the_fit_and_the_curve(plugin):
    dock = _velocity_on(plugin)
    _click_hyperbola(plugin)
    assert dock.velocity_fit_result() is not None

    dock.clear_velocity_button.click()

    assert dock.velocity_points() == []
    assert dock.velocity_fit_result() is None
    assert _view(plugin)._velocity_points == [] and _view(plugin)._velocity_curve == []
    assert not dock.apply_line_button.isEnabled()


def test_discarding_a_point_refits(plugin):
    dock = _velocity_on(plugin)
    _click_hyperbola(plugin)
    _view(plugin).velocity_point_discarded.emit(4)
    assert dock.velocity_fit_result().n_points == 4
    _view(plugin).velocity_point_discarded.emit(3)
    assert dock.velocity_fit_result() is None  # three points: the solver refuses


def test_opening_another_line_resets_the_strip(plugin):
    dock = _velocity_on(plugin)
    _click_hyperbola(plugin)
    plugin.session.open_line(plugin.session.keys()[1])
    assert dock.velocity_fit_result() is None
    assert "±" not in dock.velocity_readout.text()


def test_a_line_collected_against_the_axis_still_fits_and_draws_at_the_right_trace(
    plugin, tmp_path
):
    s = plugin.session
    path = synthetic_dzt(tmp_path / "raw", "REVERSED.DZT", n_traces=60)
    line = Line.open(path, GridPlacement("A", "y", 4.0, 1.0, -1))  # metres fall as traces rise
    s.add_lines([line])
    key = s.line_key(line)
    s.set_profiles(key, line.load())
    s.open_line(key)
    dock = _velocity_on(plugin)

    _click_hyperbola(plugin)  # the same traces; the metres now run the other way

    fit = dock.velocity_fit_result()
    assert fit.v_m_ns == pytest.approx(TRUE_V, rel=1e-2)
    tr, _ = min(_view(plugin)._velocity_curve, key=lambda c: c[1])
    assert tr == pytest.approx(APEX_TRACE, abs=0.5)


def test_add_velocity_fit_and_applying_it_dirty_and_announce(plugin):
    from nsgeo.velocity_fit import StoredFit

    s = plugin.session
    key = s.keys()[0]
    stored = StoredFit(
        20.0, 0.1, 0.004, 0.2, 30, ((30, 20.0), (15, 21.0)), "2026-10-23T00:00:00+00:00"
    )
    s._set_dirty(False)
    heard = []
    s.lines_changed.connect(lambda: heard.append(1))

    fit_id = s.add_velocity_fit(key, stored)

    assert s.line_for_key(key).velocity_fits[fit_id] == stored
    assert s.dirty and heard == [1]
    heard.clear()
    apply_fit(s, key, fit_id)
    assert s.line_for_key(key).velocity_from_fit == fit_id and heard == [1]
    s.set_line_velocity(key, VelocityModel.constant(0.1))  # a typed number drops the record
    assert s.line_for_key(key).velocity_from_fit is None
    assert s.add_velocity_fit(key, stored) != fit_id


def test_a_velocity_click_on_a_previewed_line_is_refused_with_a_message(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    errors = []
    dock.error.connect(errors.append)
    s.set_preview(s.keys()[1], 5)

    _view(plugin).velocity_point_requested.emit(10, 25.0)

    assert dock.velocity_points() == []
    assert errors and "preview" in errors[0]


def test_a_velocity_discard_on_a_previewed_line_changes_nothing(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    _click_hyperbola(plugin)
    s.set_preview(s.keys()[1], 5)

    _view(plugin).velocity_point_discarded.emit(0)

    assert len(dock.velocity_points()) == 5


def test_the_curve_and_points_are_not_painted_over_a_previewed_line(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    _click_hyperbola(plugin)
    assert len(_view(plugin)._velocity_curve) == 200

    s.set_preview(s.keys()[1], 5)

    assert _view(plugin)._velocity_curve == []
    assert _view(plugin)._velocity_points == []
    assert len(dock.velocity_points()) == 5  # the working line's points are kept

    s.clear_preview()  # and they come back when the preview ends
    assert len(_view(plugin)._velocity_curve) == 200
    assert len(_view(plugin)._velocity_points) == 5


def test_point_collection_resumes_once_the_preview_ends(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    v = _view(plugin)
    s.set_preview(s.keys()[1], 5)
    _click(v, 40, 30)
    assert dock.velocity_points() == []  # refused while previewing

    s.clear_preview()
    _click(v, 40, 30)

    assert len(dock.velocity_points()) == 1


def _two_saved_fits(s, key):
    from nsgeo.velocity_fit import StoredFit

    a = StoredFit(20.0, 0.09, 0.004, 0.2, 30, ((30, 20.0), (15, 21.0)), "t")
    b = StoredFit(41.0, 0.12, 0.004, 0.2, 20, ((20, 41.0), (10, 42.0)), "t")
    return s.add_velocity_fit(key, a), a, s.add_velocity_fit(key, b), b


def test_remove_velocity_fit_drops_only_that_fit_dirties_and_announces(plugin):
    s = plugin.session
    key = s.keys()[0]
    id_a, a, id_b, _ = _two_saved_fits(s, key)
    s._set_dirty(False)
    heard = []
    s.lines_changed.connect(lambda: heard.append(1))

    s.remove_velocity_fit(key, id_b)

    assert s.line_for_key(key).velocity_fits == {id_a: a}
    assert s.dirty and heard == [1]


def test_removing_the_fit_that_set_the_velocity_keeps_the_velocity_but_not_the_claim(plugin):
    from nsgeo_qgis.ui.profile_dock import velocity_source

    s = plugin.session
    key = s.keys()[0]
    id_a, _, _, _ = _two_saved_fits(s, key)
    apply_fit(s, key, id_a)

    s.remove_velocity_fit(key, id_a)

    line = s.line_for_key(key)
    assert line.velocity == VelocityModel.constant(0.09)
    assert line.velocity_from_fit is None
    assert velocity_source(s, key) == "line override"


def test_removing_another_fit_leaves_the_pointer_alone(plugin):
    s = plugin.session
    key = s.keys()[0]
    id_a, _, id_b, _ = _two_saved_fits(s, key)
    apply_fit(s, key, id_a)

    s.remove_velocity_fit(key, id_b)

    assert s.line_for_key(key).velocity_from_fit == id_a


def test_remove_velocity_fit_rejects_an_unknown_fit_id(plugin):
    s = plugin.session
    key = s.keys()[0]
    id_a, a, id_b, b = _two_saved_fits(s, key)
    with pytest.raises(KeyError):
        s.remove_velocity_fit(key, "no-such-fit")
    assert s.line_for_key(key).velocity_fits == {id_a: a, id_b: b}


def _stub_fit(monkeypatch, v, sigma):
    from nsgeo.velocity_fit import HyperbolaFit
    from nsgeo_qgis.ui import profile_dock

    monkeypatch.setattr(
        profile_dock, "fit_hyperbola", lambda *a, **k: HyperbolaFit(0.5, 20.0, v, sigma, 0.09, 5)
    )


def test_a_sigma_over_a_fifth_of_v_adds_a_poorly_constrained_note(plugin, monkeypatch):
    _stub_fit(monkeypatch, 0.1, 0.021)  # 21 %
    dock = _velocity_on(plugin)
    _click_hyperbola(plugin)
    text = dock.velocity_readout.text()
    assert "poorly constrained" in text
    assert "further along the limbs" in text
    assert dock.apply_line_button.isEnabled()  # advice, not a gate


def test_a_sigma_under_a_fifth_of_v_adds_no_note(plugin, monkeypatch):
    _stub_fit(monkeypatch, 0.1, 0.019)  # 19 %
    dock = _velocity_on(plugin)
    _click_hyperbola(plugin)
    assert "poorly constrained" not in dock.velocity_readout.text()
    assert "±" in dock.velocity_readout.text()


def test_turning_velocity_mode_off_clears_the_working_marks_but_keeps_saved_fits(plugin):
    dock = _velocity_on(plugin)
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    _click_hyperbola(plugin)
    v = _view(plugin)
    assert v._velocity_points and v._velocity_curve and v._saved_velocity_curves

    plugin.act_velocity.setChecked(False)
    plugin.act_velocity.triggered.emit(False)

    assert v._velocity_points == []
    assert v._velocity_curve == []
    assert len(v._saved_velocity_curves) == 1  # what is already measured stays visible


def test_a_right_click_in_velocity_mode_abandons_a_stale_cutoff_grab(plugin):
    v = _view(plugin)
    _check(plugin.act_velocity)
    v._cutoff_ns = 33.0  # where a lost-release drag had dragged it to
    v._cutoff_grab = 12.0  # ...from here

    _click(v, 10, 10, Qt.MouseButton.RightButton)  # nowhere near a point

    assert v._cutoff_grab is None
    assert v._cutoff_ns == 12.0  # the abandoned drag is undone, as a left press does


def test_a_line_that_vanishes_from_a_refresh_still_resets_the_strip_by_key_error(
    plugin, monkeypatch
):
    dock = _velocity_on(plugin)
    _click_hyperbola(plugin)
    assert dock.apply_line_button.isEnabled()
    dock._velocity_points = []  # the read-out and buttons are now stale
    monkeypatch.setattr(
        plugin.session, "resolved_velocity", lambda key: (_ for _ in ()).throw(KeyError(key))
    )

    plugin.session.lines_changed.emit()

    assert "Click the hyperbola" in dock.velocity_readout.text()
    assert not dock.apply_line_button.isEnabled()


def test_a_refresh_with_no_open_line_still_resets_the_strip(plugin):
    dock = _velocity_on(plugin)
    _click_hyperbola(plugin)
    assert dock.apply_line_button.isEnabled()
    dock._velocity_points = []  # stale, as above
    dock._working_key = None

    plugin.session.lines_changed.emit()

    assert not dock.apply_line_button.isEnabled()
    assert not dock.save_fit_button.isEnabled()
    assert "±" not in dock.velocity_readout.text()


def test_one_update_builds_the_distance_axis_the_same_number_of_times_however_many_fits_are_saved(
    plugin, monkeypatch
):
    from nsgeo.velocity_fit import StoredFit

    s, dock = plugin.session, plugin.profile_dock
    key = s.keys()[0]
    calls = []
    real = Line.distance_along
    monkeypatch.setattr(Line, "distance_along", lambda self: calls.append(1) or real(self))

    def _count():
        calls.clear()
        dock._update_velocity_fit()
        return len(calls)

    s.add_velocity_fit(key, StoredFit(20.0, 0.1, 0.004, 0.2, 30, ((30, 20.0),), "t"))
    one = _count()
    for i in range(4):
        s.add_velocity_fit(key, StoredFit(20.0 + i, 0.1, 0.004, 0.2, 20 + i, ((20, 20.0),), "t"))
    assert _count() == one
