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
from nsgeo.velocity_fit import fit_hyperbola
from plugin_testing import send_move_while_pressed, synthetic_dzt
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QMessageBox

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)
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


def test_a_click_in_velocity_mode_adds_a_point(plugin):
    v = _view(plugin)
    _check(plugin.act_velocity)
    _click(v, 40, 30)
    _click(v, 60, 50)
    pts = plugin.profile_dock.velocity_points()
    assert len(pts) == 2
    assert pts[0][0] == v.transform.trace_index_at(40)  # the first click is the apex
    assert pts[0][1] == pytest.approx(v.transform.time_of_y(30))
    assert v._velocity_points == pts  # and the view was handed the same list


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


def test_a_radargram_not_at_time_zero_warns_and_names_the_step(plugin):
    dock = _velocity_on(plugin)
    assert "time_zero" in dock.velocity_note.text()


# The fixture header puts sample 0 at -11.086 ns with dt = 0.2165 ns, so
# time_zero at sample k leaves t0 = -11.086 + k * 0.2165: k=51 -> -0.043 ns,
# k=50 -> -0.260, k=52 -> +0.173. Half a sample (0.108 ns) is the best a
# whole-sample crop can promise, so only k=51 is "at time zero".
def test_time_zero_at_the_nearest_sample_is_quiet(plugin):
    dock = _time_zero_to(plugin, 51)
    assert dock.velocity_note.text() == ""


@pytest.mark.parametrize("sample", [50, 52, 49])
def test_a_time_zero_more_than_half_a_sample_out_still_warns(plugin, sample):
    dock = _time_zero_to(plugin, sample)
    assert "time_zero" in dock.velocity_note.text()


def test_the_tolerance_scales_with_the_sample_interval(plugin, tmp_path):
    # 1000 ns over 512 samples: dt = 1.953 ns, so the closest crop (sample 6)
    # leaves t0 = +0.63 ns. That is the best this file can do, so no warning.
    s = plugin.session
    path = synthetic_dzt(tmp_path / "raw", "DEEP.DZT", n_traces=60, range_ns=1000.0)
    line = Line.open(path, GridPlacement("A", "y", 5.0, 0.0))
    s.add_lines([line])
    key = s.line_key(line)
    s.set_profiles(key, line.load())
    s.open_line(key)
    s.append_step(key, build_step("time_zero", mode="sample", sample=6))
    dock = _velocity_on(plugin)
    assert 0.5 < abs(dock.view.transform.t0_ns) < 0.5 * dock.view.transform.dt_ns
    assert dock.velocity_note.text() == ""


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
    _view(plugin).velocity_point_discarded.emit(4)
    dock.save_fit_button.click()
    dock.apply_line_button.click()

    line = s.line_for_key(key)
    second = [i for i, f in line.velocity_fits.items() if len(f.points) == 4]
    assert line.velocity_from_fit == second[0]


def test_save_fit_twice_keeps_both_under_distinct_ids(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    dock.save_fit_button.click()
    assert len(s.line_for_key(s.keys()[0]).velocity_fits) == 2


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


def test_add_velocity_fit_and_set_velocity_from_fit_dirty_and_announce(plugin):
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
    s.set_velocity_from_fit(key, fit_id)
    assert s.line_for_key(key).velocity_from_fit == fit_id and heard == [1]
    s.set_velocity_from_fit(key, None)
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
