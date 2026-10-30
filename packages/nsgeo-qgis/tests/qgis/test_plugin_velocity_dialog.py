"""The line velocity dialog, and the saved fits drawn on the profile."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.velocity import VelocityModel
from nsgeo.velocity_fit import StoredFit
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtWidgets import QDialog, QMessageBox

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def plugin(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

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


def _stored(t0, v, sigma=0.002, rms=0.25, apex=30, n=4):
    pts = tuple((apex + i, t0 + i) for i in range(n))
    return StoredFit(t0, v, sigma, rms, apex, pts, "2026-10-23T00:00:00+00:00")


def _dialog(plugin, key=None):
    from nsgeo_qgis.ui.velocity_dialog import VelocityDialog

    key = key or plugin.session.keys()[0]
    return VelocityDialog(plugin.session, key)


def _flagged(plugin, a, b):
    """Save two fits, each (v, sigma), and return their ids, the ids the
    dialog flags, and the dialog."""
    s, key = plugin.session, plugin.session.keys()[0]
    ids = [
        s.add_velocity_fit(key, _stored(18.0 + 23 * i, v, sg)) for i, (v, sg) in enumerate((a, b))
    ]
    dialog = _dialog(plugin)
    return ids, dialog.flagged_fit_ids(), dialog


def _row_text(dialog, row):
    table = dialog.table
    return " ".join(
        table.item(row, c).text() for c in range(table.columnCount()) if table.item(row, c)
    )


def test_the_dialog_lists_every_saved_fit_for_the_line(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    s.add_velocity_fit(key, _stored(18.0, 0.0900, 0.0021, 0.31, n=5))
    s.add_velocity_fit(key, _stored(41.0, 0.1200, 0.0034, 0.52, n=7))

    dialog = _dialog(plugin)

    assert dialog.table.rowCount() == 2
    for expected in ("18.0", "0.0900", "0.0021", "0.31", "5"):
        assert expected in _row_text(dialog, 0), _row_text(dialog, 0)
    for expected in ("41.0", "0.1200", "0.0034", "0.52", "7"):
        assert expected in _row_text(dialog, 1), _row_text(dialog, 1)


def test_fits_of_another_line_are_not_listed(plugin):
    s = plugin.session
    s.add_velocity_fit(s.keys()[1], _stored(18.0, 0.09))
    assert _dialog(plugin, s.keys()[0]).table.rowCount() == 0


def test_rows_are_sorted_by_t0_whatever_order_they_were_saved_in(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    late = s.add_velocity_fit(key, _stored(60.0, 0.11))
    early = s.add_velocity_fit(key, _stored(12.0, 0.09))
    mid = s.add_velocity_fit(key, _stored(35.0, 0.10))
    dialog = _dialog(plugin)
    assert [dialog.fit_id_at_row(r) for r in range(3)] == [early, mid, late]


def test_selecting_a_fit_and_accepting_applies_its_velocity(plugin, drive_dialog):
    s, key = plugin.session, plugin.session.keys()[0]
    s.add_velocity_fit(key, _stored(18.0, 0.0900))
    wanted = s.add_velocity_fit(key, _stored(41.0, 0.1200))
    calls = drive_dialog(QDialog, "exec", lambda d: (d.select_fit(wanted), d.accept()))

    plugin.open_velocity_dialog(key)

    assert len(calls) == 1
    line = s.line_for_key(key)
    assert line.velocity == VelocityModel.constant(0.12)
    assert line.velocity_from_fit == wanted


def test_the_dialog_opens_seeded_with_the_resolved_velocity(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    s.set_line_velocity(key, VelocityModel.constant(0.0777))
    assert _dialog(plugin).spin.value() == pytest.approx(0.0777)


def test_the_spin_box_is_a_four_decimal_velocity_bounded_at_the_speed_of_light_in_air(plugin):
    dialog = _dialog(plugin)
    spin = dialog.spin
    assert (spin.minimum(), spin.maximum(), spin.decimals(), spin.singleStep()) == (
        0.0,
        0.3,
        4,
        0.001,
    )


def test_typing_a_velocity_with_no_fit_selected_still_applies_and_leaves_no_pointer(
    plugin, drive_dialog
):
    s, key = plugin.session, plugin.session.keys()[0]
    fit_id = s.add_velocity_fit(key, _stored(18.0, 0.09))
    s.set_line_velocity(key, VelocityModel.constant(0.09))
    s.set_velocity_from_fit(key, fit_id)  # the override came from the fit...
    drive_dialog(QDialog, "exec", lambda d: (d.spin.setValue(0.0850), d.accept()))

    plugin.open_velocity_dialog(key)  # ...and then the user types a different number

    line = s.line_for_key(key)
    assert line.velocity == VelocityModel.constant(0.085)
    assert line.velocity_from_fit is None  # a typed number has no fit behind it


def test_typing_over_a_selected_fit_drops_the_fit_as_the_source(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    fit_id = s.add_velocity_fit(key, _stored(18.0, 0.0900))
    dialog = _dialog(plugin)
    dialog.select_fit(fit_id)
    assert dialog.selected_fit_id() == fit_id
    dialog.spin.setValue(0.0950)
    assert dialog.selected_fit_id() is None
    assert dialog.velocity() == VelocityModel.constant(0.095)


def test_retyping_the_selected_fits_own_velocity_keeps_the_fit_as_the_source(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    fit_id = s.add_velocity_fit(key, _stored(18.0, 0.0900))
    dialog = _dialog(plugin)
    dialog.select_fit(fit_id)
    dialog.spin.setValue(0.0950)
    dialog.spin.setValue(0.0900)
    assert dialog.selected_fit_id() == fit_id


def test_a_measured_line_velocity_names_the_fit_it_came_from(plugin):
    from nsgeo_qgis.ui.profile_dock import velocity_source

    s, key = plugin.session, plugin.session.keys()[0]
    fit_id = s.add_velocity_fit(key, _stored(18.4, 0.09))
    s.set_line_velocity(key, VelocityModel.constant(0.09))
    assert velocity_source(s, key) == "line override"  # typed: no pointer yet
    s.set_velocity_from_fit(key, fit_id)
    assert velocity_source(s, key) == "line override (fit at 18.4 ns)"
    assert "fit at 18.4 ns" in plugin.profile_dock.velocity_label.text()


def test_a_pointer_to_a_fit_that_is_gone_leaves_the_bare_source(plugin):
    import dataclasses

    from nsgeo_qgis.ui.profile_dock import velocity_source

    s, key = plugin.session, plugin.session.keys()[0]
    s.set_line_velocity(key, VelocityModel.constant(0.09))
    line = s.line_for_key(key)
    dangling = dataclasses.replace(line, velocity_from_fit="gone")  # as a hand-edited file
    s._lines_by_key[key] = dangling
    assert velocity_source(s, key) == "line override"


def test_clear_override_removes_the_line_velocity_and_the_pointer(plugin, drive_dialog):
    from nsgeo_qgis.ui.profile_dock import velocity_source

    s, key = plugin.session, plugin.session.keys()[0]
    fit_id = s.add_velocity_fit(key, _stored(18.0, 0.09))
    s.set_line_velocity(key, VelocityModel.constant(0.09))
    s.set_velocity_from_fit(key, fit_id)
    assert velocity_source(s, key) == "line override (fit at 18.0 ns)"
    drive_dialog(QDialog, "exec", lambda d: d.clear_button.click())

    plugin.open_velocity_dialog(key)

    line = s.line_for_key(key)
    assert line.velocity is None
    assert line.velocity_from_fit is None
    assert velocity_source(s, key) == "header ε 14"  # falls back to the grid, then the header
    assert fit_id in line.velocity_fits  # the measurement itself is kept


def test_clear_override_is_reachable_with_no_override_set(plugin):
    dialog = _dialog(plugin)
    assert dialog.clear_button.isEnabled()
    dialog.clear_button.click()
    assert dialog.velocity() is None
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_cancel_changes_nothing(plugin, drive_dialog):
    s, key = plugin.session, plugin.session.keys()[0]
    before = s.line_for_key(key)
    drive_dialog(QDialog, "exec", lambda d: (d.spin.setValue(0.2), d.reject()))

    plugin.open_velocity_dialog(key)

    assert s.line_for_key(key) == before


def test_a_stale_key_is_reported_not_raised(plugin, fake_iface):
    plugin.open_velocity_dialog("no-such-line")  # the autouse fixture fails on a swallowed error
    assert "no-such-line" in fake_iface.messageBar().currentItem().text()


def test_a_line_whose_velocity_cannot_be_resolved_is_reported_not_raised(
    plugin, fake_iface, monkeypatch
):
    # A header with epsr 0 loads fine and makes resolved_velocity raise ValueError.
    def boom(key):
        raise ValueError("relative dielectric permittivity must be positive, got 0.0")

    monkeypatch.setattr(plugin.session, "resolved_velocity", boom)
    plugin.open_velocity_dialog(plugin.session.keys()[0])
    assert "permittivity" in fake_iface.messageBar().currentItem().text()


def test_a_zero_velocity_cannot_be_applied(plugin):
    dialog = _dialog(plugin)
    dialog.spin.setValue(0.0)
    assert not dialog.apply_button.isEnabled()
    assert dialog.spin.specialValueText() == "required"
    dialog.spin.setValue(0.05)
    assert dialog.apply_button.isEnabled()


def test_applying_a_fit_stores_its_exact_velocity_not_the_spin_boxs_rounding(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    fit_id = s.add_velocity_fit(key, _stored(18.0, 0.09004))
    dialog = _dialog(plugin)
    dialog.select_fit(fit_id)
    assert dialog.velocity() == VelocityModel.constant(0.09004)  # spin shows 0.0900


# ---- the disagreement flag, pinned with literal numbers ---------------------


def test_two_fits_far_apart_are_flagged(plugin):
    # sigma 0.002 each: 2*hypot = 0.00566; the gap is 0.030
    ids, flagged, dialog = _flagged(plugin, (0.090, 0.002), (0.120, 0.002))
    assert flagged == frozenset(ids)
    assert dialog.flag_text(0) and dialog.flag_text(1)  # the rows say so too


def test_the_walkthrough_pair_one_sigma_apart_is_not_flagged(plugin):
    # Real fits from the M13 walkthrough: 0.0701 +- 0.0018 and 0.0733 +- 0.0024.
    # Gap 0.0032, hypot 0.0030 (1.07 sigma): indistinguishable. The old 1-sigma
    # rule flagged this pair; 2*hypot is 0.0060.
    _, flagged, dialog = _flagged(plugin, (0.0701, 0.0018), (0.0733, 0.0024))
    assert flagged == frozenset()
    assert not dialog.flag_text(0) and not dialog.flag_text(1)


def test_a_gap_of_about_two_and_a_half_sigma_is_not_flagged_which_a_summed_sigma_would_flag(plugin):
    # sigma 0.002 each: gap 0.0050 is under 2*hypot (0.00566) but over the sum
    # of the sigmas (0.004)
    _, flagged, _ = _flagged(plugin, (0.0900, 0.002), (0.0950, 0.002))
    assert flagged == frozenset()


def test_a_gap_just_over_two_combined_sigma_is_flagged(plugin):
    # sigma 0.002 each: gap 0.0060 is over 2*hypot (0.00566), under 3*hypot (0.0085)
    ids, flagged, _ = _flagged(plugin, (0.0900, 0.002), (0.0960, 0.002))
    assert flagged == frozenset(ids)


def test_unequal_sigmas_a_gap_inside_twice_the_quadrature_sum_is_not_flagged(plugin):
    # sigmas 0.001 and 0.004: 2*hypot = 0.00825. A gap of 0.0080 is inside it,
    # though well beyond hypot alone (0.00412).
    _, flagged, _ = _flagged(plugin, (0.0900, 0.001), (0.0980, 0.004))
    assert flagged == frozenset()


def test_unequal_sigmas_a_gap_beyond_twice_the_quadrature_sum_is_flagged(plugin):
    # the same sigmas, gap 0.0084 over 0.00825
    ids, flagged, _ = _flagged(plugin, (0.0900, 0.001), (0.0984, 0.004))
    assert flagged == frozenset(ids)


def test_flagging_is_per_pair_so_the_fit_that_agrees_with_both_neighbours_is_not_flagged(plugin):
    # sigma 0.003 each: 2*hypot = 0.00849. a-b gap 0.0050 and b-c gap 0.0050
    # are inside it; a-c gap 0.0100 is outside it.
    s, key = plugin.session, plugin.session.keys()[0]
    a = s.add_velocity_fit(key, _stored(10.0, 0.0900, 0.003))
    s.add_velocity_fit(key, _stored(30.0, 0.0950, 0.003))
    c = s.add_velocity_fit(key, _stored(50.0, 0.1000, 0.003))
    assert _dialog(plugin).flagged_fit_ids() == frozenset({a, c})


def test_a_single_fit_is_never_flagged(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    s.add_velocity_fit(key, _stored(10.0, 0.09))
    assert _dialog(plugin).flagged_fit_ids() == frozenset()


# ---- saved fits drawn on the profile ---------------------------------------


def test_each_saved_fit_reaches_the_view_as_a_curve_separate_from_the_working_fit(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    view = plugin.profile_dock.view
    s.add_velocity_fit(key, _stored(18.0, 0.09))
    s.add_velocity_fit(key, _stored(41.0, 0.12, apex=20))

    assert len(view._saved_velocity_curves) == 2
    assert all(len(c) >= 2 for c in view._saved_velocity_curves)
    assert view._velocity_curve == []  # the working fit is a different list
    apexes = sorted(min(c, key=lambda p: p[1])[0] for c in view._saved_velocity_curves)
    assert apexes[0] == pytest.approx(20, abs=0.5)
    assert apexes[1] == pytest.approx(30, abs=0.5)


def test_saved_curves_follow_the_open_line(plugin):
    s = plugin.session
    s.add_velocity_fit(s.keys()[0], _stored(18.0, 0.09))
    view = plugin.profile_dock.view
    assert len(view._saved_velocity_curves) == 1

    s.open_line(s.keys()[1])
    assert view._saved_velocity_curves == []

    s.open_line(s.keys()[0])
    assert len(view._saved_velocity_curves) == 1


def test_a_saved_curve_is_drawn_differently_from_the_working_fit_over_the_same_geometry(plugin):
    view = plugin.profile_dock.view
    curve = [(float(t), 10.0 + 0.5 * t) for t in range(60)]
    view.grab()  # warm-up: the first paint after a change is not the settled one
    view.set_saved_velocity_fits([curve])
    view.grab()
    saved_only = view.grab().toImage()
    view.set_saved_velocity_fits([])
    view.set_velocity_fit([], curve)
    view.grab()
    working_only = view.grab().toImage()
    view.set_velocity_fit([], [])
    none = view.grab().toImage()
    assert saved_only != none and working_only != none  # both really drew
    assert saved_only != working_only


def test_drawing_the_saved_curves_changes_the_picture(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    view = plugin.profile_dock.view
    s.add_velocity_fit(key, _stored(18.0, 0.09))
    with_curve = view.grab().toImage()
    view.set_saved_velocity_fits([])
    assert view.grab().toImage() != with_curve
