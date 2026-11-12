"""The line velocity dialog, and the saved fits drawn on the profile."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.velocity import VelocityModel
from nsgeo.velocity_fit import StoredFit, applied_fit_note, fit_at_zero, fit_hyperbola
from plugin_testing import synthetic_dzt
from qgis.core import Qgis
from qgis.PyQt.QtCore import Qt
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


def test_the_dialog_seeds_from_the_grid_when_the_line_has_no_override(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    s.set_grid_velocity("A", VelocityModel.constant(0.0888))
    assert s.line_for_key(key).velocity is None
    assert _dialog(plugin).spin.value() == pytest.approx(0.0888)


def test_the_dialog_seeds_from_the_header_dielectric_with_no_line_or_grid_velocity(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    line = s.line_for_key(key)
    assert line.velocity is None and s.grid_for_line(line).velocity is None
    expected = VelocityModel.from_dielectric(line.header.epsr).surface_velocity
    assert _dialog(plugin).spin.value() == pytest.approx(expected, abs=1e-4)


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

    from nsgeo.velocity_source import SourceFit, VelocitySource
    from nsgeo_qgis.ui.profile_dock import velocity_source

    s, key = plugin.session, plugin.session.keys()[0]
    s.set_line_velocity(key, VelocityModel.constant(0.09))
    line = s.line_for_key(key)
    # A record whose member names a fit id the line does not have, as a hand-edited file leaves it.
    stored = _stored(18.4, 0.09)
    member = SourceFit.of(key, "gone", "L", stored)
    record = VelocitySource.from_fits([member], applied_at=None)
    dangling = dataclasses.replace(line, velocity_source=record)
    assert dangling.velocity_from_fit is None
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

    # Fainter, not merely different: the strongest pixel a saved curve leaves
    # is well short of the working curve's. A saved curve at full alpha would
    # reach the working curve's peak, whatever its line width.
    def _peak(img):
        peak = 0
        for y in range(img.height()):
            for x in range(img.width()):
                a, b = img.pixelColor(x, y), none.pixelColor(x, y)
                peak = max(
                    peak,
                    abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()),
                )
        return peak

    assert _peak(saved_only) < 0.6 * _peak(working_only)


def test_drawing_the_saved_curves_changes_the_picture(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    view = plugin.profile_dock.view
    s.add_velocity_fit(key, _stored(18.0, 0.09))
    with_curve = view.grab().toImage()
    view.set_saved_velocity_fits([])
    assert view.grab().toImage() != with_curve


# ---- deleting a saved fit ----------------------------------------------------


def _answer_delete(answer_modal, button):
    """Answer the delete prompt. Later questions (unload's save prompt) get
    the same answer, which is harmless in a throwaway site folder."""
    return answer_modal(QMessageBox, "question", button)


def test_delete_is_enabled_only_while_a_fit_is_selected(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    fit_id = s.add_velocity_fit(key, _stored(18.0, 0.09))
    dialog = _dialog(plugin)
    assert not dialog.delete_button.isEnabled()

    dialog.select_fit(fit_id)
    assert dialog.delete_button.isEnabled()

    dialog.table.clearSelection()
    assert not dialog.delete_button.isEnabled()


def test_delete_asks_which_fit_then_removes_it_from_the_line_and_the_list(plugin, answer_modal):
    s, key = plugin.session, plugin.session.keys()[0]
    keep = s.add_velocity_fit(key, _stored(18.0, 0.0900))
    bad = s.add_velocity_fit(key, _stored(41.0, 0.1500, 0.0040))
    asked = _answer_delete(answer_modal, QMessageBox.StandardButton.Yes)
    dialog = _dialog(plugin)
    dialog.select_fit(bad)

    dialog.delete_button.click()

    (args, _), *_ = asked
    assert "41.0 ns" in args[2] and "0.1500" in args[2]  # names the fit being deleted
    assert set(s.line_for_key(key).velocity_fits) == {keep}
    assert dialog.table.rowCount() == 1
    assert dialog.fit_id_at_row(0) == keep
    assert not dialog.delete_button.isEnabled()  # nothing is selected any more


def test_answering_no_keeps_the_fit(plugin, answer_modal):
    s, key = plugin.session, plugin.session.keys()[0]
    fit_id = s.add_velocity_fit(key, _stored(18.0, 0.09))
    _answer_delete(answer_modal, QMessageBox.StandardButton.No)
    dialog = _dialog(plugin)
    dialog.select_fit(fit_id)

    dialog.delete_button.click()

    assert fit_id in s.line_for_key(key).velocity_fits
    assert dialog.table.rowCount() == 1


def test_deleting_the_odd_fit_out_clears_the_disagreement_flag_on_the_rest(plugin, answer_modal):
    ids, flagged, dialog = _flagged(plugin, (0.090, 0.002), (0.150, 0.002))
    assert flagged == frozenset(ids)
    _answer_delete(answer_modal, QMessageBox.StandardButton.Yes)
    dialog.select_fit(ids[1])

    dialog.delete_button.click()

    assert dialog.flagged_fit_ids() == frozenset()
    assert dialog.flag_text(0) == ""


def test_deleting_the_fit_behind_the_velocity_says_the_velocity_stays(plugin, answer_modal):
    from nsgeo_qgis.ui.profile_dock import velocity_source

    s, key = plugin.session, plugin.session.keys()[0]
    fit_id = s.add_velocity_fit(key, _stored(18.0, 0.0900))
    s.set_line_velocity(key, VelocityModel.constant(0.09))
    s.set_velocity_from_fit(key, fit_id)
    asked = _answer_delete(answer_modal, QMessageBox.StandardButton.Yes)
    dialog = _dialog(plugin)  # opens with the applied fit selected

    dialog.delete_button.click()

    (args, _), *_ = asked
    assert "line's velocity" in args[2]  # the prompt warns before, not after
    assert s.line_for_key(key).velocity == VelocityModel.constant(0.09)
    assert velocity_source(s, key) == "line override"


def test_the_prompt_for_a_fit_not_behind_the_velocity_does_not_mention_the_velocity(
    plugin, answer_modal
):
    s, key = plugin.session, plugin.session.keys()[0]
    fit_id = s.add_velocity_fit(key, _stored(18.0, 0.0900))
    asked = _answer_delete(answer_modal, QMessageBox.StandardButton.Yes)
    dialog = _dialog(plugin)
    dialog.select_fit(fit_id)

    dialog.delete_button.click()

    (args, _), *_ = asked
    assert "line's velocity" not in args[2]


def test_after_a_delete_the_spin_box_shows_the_lines_own_velocity_again(plugin, answer_modal):
    s, key = plugin.session, plugin.session.keys()[0]
    s.set_line_velocity(key, VelocityModel.constant(0.0777))
    bad = s.add_velocity_fit(key, _stored(41.0, 0.1500))
    _answer_delete(answer_modal, QMessageBox.StandardButton.Yes)
    dialog = _dialog(plugin)
    dialog.select_fit(bad)
    assert dialog.spin.value() == pytest.approx(0.15)  # selecting copied the fit's velocity

    dialog.delete_button.click()

    assert dialog.spin.value() == pytest.approx(0.0777)  # not the deleted fit's number
    assert dialog.selected_fit_id() is None


def test_a_delete_stands_even_when_the_dialog_is_then_cancelled(plugin, answer_modal, drive_dialog):
    s, key = plugin.session, plugin.session.keys()[0]
    bad = s.add_velocity_fit(key, _stored(41.0, 0.15))
    _answer_delete(answer_modal, QMessageBox.StandardButton.Yes)
    drive_dialog(
        QDialog, "exec", lambda d: (d.select_fit(bad), d.delete_button.click(), d.reject())
    )

    plugin.open_velocity_dialog(key)

    line = s.line_for_key(key)
    assert line.velocity_fits == {}
    assert line.velocity is None  # deleting set no velocity on the way


# ---- the selected fit, lit on the profile -------------------------------------


def _highlighted_apex(view):
    i = view._saved_velocity_highlight
    if i is None:
        return None
    return min(view._saved_velocity_curves[i], key=lambda p: p[1])[0]


def test_the_fit_selected_in_the_dialog_is_lit_on_the_profile_until_it_closes(plugin, drive_dialog):
    s, key = plugin.session, plugin.session.keys()[0]
    view = plugin.profile_dock.view
    s.add_velocity_fit(key, _stored(18.0, 0.09, apex=30))
    shallow_left = s.add_velocity_fit(key, _stored(12.0, 0.12, apex=20))
    deep = s.add_velocity_fit(key, _stored(41.0, 0.10, apex=40))
    seen = []

    def _drive(d):
        d.select_fit(shallow_left)
        seen.append(_highlighted_apex(view))
        d.select_fit(deep)
        seen.append(_highlighted_apex(view))
        d.reject()

    drive_dialog(QDialog, "exec", _drive)

    plugin.open_velocity_dialog(key)

    assert seen[0] == pytest.approx(20, abs=0.5)
    assert seen[1] == pytest.approx(40, abs=0.5)
    assert view._saved_velocity_highlight is None


def test_the_fit_behind_the_velocity_is_lit_as_the_dialog_opens(plugin, drive_dialog):
    s, key = plugin.session, plugin.session.keys()[0]
    view = plugin.profile_dock.view
    s.add_velocity_fit(key, _stored(18.0, 0.09, apex=30))
    applied = s.add_velocity_fit(key, _stored(41.0, 0.12, apex=20))
    s.set_line_velocity(key, VelocityModel.constant(0.12))
    s.set_velocity_from_fit(key, applied)
    seen = []
    drive_dialog(QDialog, "exec", lambda d: (seen.append(_highlighted_apex(view)), d.reject()))

    plugin.open_velocity_dialog(key)

    assert seen == [pytest.approx(20, abs=0.5)]


def test_a_deleted_fit_is_no_longer_lit(plugin, answer_modal, drive_dialog):
    s, key = plugin.session, plugin.session.keys()[0]
    view = plugin.profile_dock.view
    s.add_velocity_fit(key, _stored(18.0, 0.09, apex=30))
    bad = s.add_velocity_fit(key, _stored(41.0, 0.15, apex=20))
    _answer_delete(answer_modal, QMessageBox.StandardButton.Yes)
    seen = []

    def _drive(d):
        d.select_fit(bad)
        d.delete_button.click()
        seen.append((view._saved_velocity_highlight, len(view._saved_velocity_curves)))
        d.reject()

    drive_dialog(QDialog, "exec", _drive)

    plugin.open_velocity_dialog(key)

    assert seen == [(None, 1)]


def test_a_dialog_for_a_line_the_profile_is_not_showing_lights_nothing(plugin, drive_dialog):
    s = plugin.session
    other = s.keys()[1]
    view = plugin.profile_dock.view
    s.add_velocity_fit(s.keys()[0], _stored(18.0, 0.09))
    fit_id = s.add_velocity_fit(other, _stored(41.0, 0.12))
    seen = []
    drive_dialog(
        QDialog,
        "exec",
        lambda d: (d.select_fit(fit_id), seen.append(view._saved_velocity_highlight), d.reject()),
    )

    plugin.open_velocity_dialog(other)

    assert seen == [None]


def test_a_lit_saved_curve_is_drawn_stronger_than_an_unlit_one(plugin):
    view = plugin.profile_dock.view
    curve = [(float(t), 10.0 + 0.5 * t) for t in range(60)]
    view.set_saved_velocity_fits([])
    view.grab()  # warm-up: the first paint after a change is not the settled one
    none = view.grab().toImage()
    view.set_saved_velocity_fits([curve])
    view.grab()
    unlit = view.grab().toImage()
    view.set_saved_velocity_fits([curve], highlighted=0)
    view.grab()
    lit = view.grab().toImage()

    def _ink(img):
        """Summed colour change against the empty picture: more, stronger
        pixels means a bolder line."""
        total = 0
        for y in range(img.height()):
            for x in range(img.width()):
                a, b = img.pixelColor(x, y), none.pixelColor(x, y)
                total += abs(a.red() - b.red()) + abs(a.green() - b.green())
                total += abs(a.blue() - b.blue())
        return total

    assert _ink(lit) > 2 * _ink(unlit) > 0


def test_deleting_another_fit_leaves_the_applied_fit_selected_so_apply_keeps_it(
    plugin, answer_modal, drive_dialog
):
    s, key = plugin.session, plugin.session.keys()[0]
    applied = s.add_velocity_fit(key, _stored(18.0, 0.09123456))
    other = s.add_velocity_fit(key, _stored(41.0, 0.15))
    s.set_line_velocity(key, VelocityModel.constant(0.09123456))
    s.set_velocity_from_fit(key, applied)
    _answer_delete(answer_modal, QMessageBox.StandardButton.Yes)
    drive_dialog(
        QDialog,
        "exec",
        lambda d: (d.select_fit(other), d.delete_button.click(), d.accept()),
    )

    plugin.open_velocity_dialog(key)

    line = s.line_for_key(key)
    assert line.velocity_from_fit == applied
    assert line.velocity == VelocityModel.constant(0.09123456)  # not the box's 0.0912


def test_apply_after_deleting_the_fit_behind_the_velocity_keeps_the_velocity_exactly(
    plugin, answer_modal, drive_dialog
):
    s, key = plugin.session, plugin.session.keys()[0]
    applied = s.add_velocity_fit(key, _stored(18.0, 0.09123456))
    s.set_line_velocity(key, VelocityModel.constant(0.09123456))
    s.set_velocity_from_fit(key, applied)
    _answer_delete(answer_modal, QMessageBox.StandardButton.Yes)
    drive_dialog(QDialog, "exec", lambda d: (d.delete_button.click(), d.accept()))

    plugin.open_velocity_dialog(key)

    line = s.line_for_key(key)
    assert line.velocity == VelocityModel.constant(0.09123456)  # "stays as it is"
    assert line.velocity_from_fit is None


def test_a_number_typed_over_the_untouched_override_still_applies(plugin, drive_dialog):
    s, key = plugin.session, plugin.session.keys()[0]
    s.set_line_velocity(key, VelocityModel.constant(0.09123456))
    drive_dialog(QDialog, "exec", lambda d: (d.spin.setValue(0.0950), d.accept()))

    plugin.open_velocity_dialog(key)

    assert s.line_for_key(key).velocity == VelocityModel.constant(0.095)


def test_a_lit_saved_curve_shows_over_a_working_curve_on_the_same_line(plugin):
    """Select the fit just saved from the working points, and the two curves
    coincide: the lit one must still be visible."""
    view = plugin.profile_dock.view
    curve = [(float(t), 10.0 + 0.5 * t) for t in range(60)]

    def _picture(working, saved, highlighted):
        view.set_velocity_fit([], working)
        view.set_saved_velocity_fits(saved, highlighted=highlighted)
        view.grab()  # warm-up: the first paint after a change is not the settled one
        return view.grab().toImage()

    def _ink(a, b):
        total = 0
        for y in range(a.height()):
            for x in range(a.width()):
                p, q = a.pixelColor(x, y), b.pixelColor(x, y)
                total += abs(p.red() - q.red()) + abs(p.green() - q.green())
                total += abs(p.blue() - q.blue())
        return total

    none = _picture([], [], None)
    lit_alone = _picture([], [curve], 0)
    unlit = _picture(curve, [curve], None)
    lit = _picture(curve, [curve], 0)
    # Lighting the curve changes at least a third as much ink as the lit curve
    # makes on its own: antialiased edges peeking out from under the working
    # curve are not "visible".
    assert _ink(lit, unlit) > _ink(lit_alone, none) / 3


def _hyperbola_fit(plugin, key=None):
    """A real hyperbola (t0 20 ns, v 0.1) saved on the radar clock with no step."""
    key = key or plugin.session.keys()[0]
    distance = plugin.session.line_for_key(key).distance_along()
    traces = (30, 15, 45, 5, 55)
    x = np.array([distance[t] for t in traces])
    t = np.sqrt(400.0 + (4.0 / 0.01) * (x - x[0]) ** 2)
    fitted = fit_hyperbola(x, t, x[0])
    return StoredFit(
        fitted.t0_ns,
        fitted.v_m_ns,
        fitted.v_stderr_m_ns,
        fitted.rms_ns,
        30,
        tuple((tr, float(ti)) for tr, ti in zip(traces, t, strict=True)),
        "2026-11-10T00:00:00+00:00",
    )


def test_the_dialog_lists_each_fit_at_the_lines_current_zero(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    stored = _hyperbola_fit(plugin)
    s.add_velocity_fit(key, stored)
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    distance = s.line_for_key(key).distance_along()
    moved = fit_at_zero(stored, distance, s.line_zero(key))
    assert moved.v_m_ns != pytest.approx(stored.v_m_ns, abs=1e-5)

    dialog = _dialog(plugin)

    cell = dialog.table.item(0, 2).text()
    assert cell.startswith(f"{moved.v_m_ns:.4f}")
    assert not cell.startswith(f"{stored.v_m_ns:.4f}")


def test_the_dialog_flags_an_applied_velocity_its_fit_no_longer_measures(
    plugin, drive_dialog, message_log
):
    # Spec 7.2 rule 1 and 7.3: opening and applying changes nothing; adopting
    # the re-measured number takes a deliberate click on the row.
    s, key = plugin.session, plugin.session.keys()[0]
    stored = _hyperbola_fit(plugin)
    fit_id = s.add_velocity_fit(key, stored)
    s.set_line_velocity(key, VelocityModel.constant(stored.v_m_ns))
    s.set_velocity_from_fit(key, fit_id)
    before = s.line_for_key(key)
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    distance = s.line_for_key(key).distance_along()
    current = fit_at_zero(stored, distance, s.line_zero(key)).v_m_ns
    assert round(current, 4) != round(stored.v_m_ns, 4)

    dialog = _dialog(plugin)

    assert applied_fit_note(stored.v_m_ns, current) in dialog.flag_text(0)
    assert dialog.highlighted_fit_id() == fit_id  # selected for the profile curve
    assert dialog.spin.value() == pytest.approx(stored.v_m_ns, abs=1e-4)  # box not filled
    drive_dialog(QDialog, "exec", lambda d: d.accept())
    plugin.open_velocity_dialog(key)
    line = s.line_for_key(key)
    assert line.velocity == before.velocity
    assert line.velocity_source == before.velocity_source

    def _click_then_accept(d):
        d.table.cellClicked.emit(0, 2)
        d.accept()

    drive_dialog(QDialog, "exec", _click_then_accept)
    plugin.open_velocity_dialog(key)
    line = s.line_for_key(key)
    assert line.velocity == VelocityModel.constant(current)
    assert line.velocity_from_fit == fit_id
    assert line.velocity_source.members[0].v_m_ns == current
    assert line.velocity_source != before.velocity_source
    assert message_log == []


def test_an_untouched_apply_keeps_a_single_fit_record_and_its_date(
    plugin, drive_dialog, message_log
):
    s, key = plugin.session, plugin.session.keys()[0]
    ids = _save_three(plugin)
    record = _record_of(plugin, ids[:1], applied_at="2026-11-01T00:00:00Z")
    drive_dialog(QDialog, "exec", lambda d: d.accept())
    plugin.open_velocity_dialog(key)
    line = s.line_for_key(key)
    assert line.velocity_source == record
    assert line.velocity_source.applied_at == "2026-11-01T00:00:00Z"
    assert message_log == []


def test_ticking_and_unticking_through_the_table_updates_the_average(plugin, message_log):
    ids = _save_three(plugin)
    dialog = _dialog(plugin)
    dialog.table.item(2, 0).setCheckState(Qt.CheckState.Unchecked)
    v, sg = _expected_mean(_THREE[:2])
    assert dialog.average_text() == f"{v:.4f} ± {sg:.4f} m/ns"
    assert dialog.average_meta_text() == "2 fits · t0 from 9.8 to 15.0 ns"
    assert dialog.all_check.checkState() == Qt.CheckState.PartiallyChecked
    assert dialog.ticked_refs() == _refs(plugin, ids[:2])
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.average_text() == "No fits ticked"
    assert dialog.all_check.checkState() == Qt.CheckState.Unchecked
    dialog.table.item(1, 0).setCheckState(Qt.CheckState.Checked)
    assert dialog.average_meta_text() == "1 fit · t0 15.0 ns"
    assert message_log == []


def test_clicking_the_all_box_cycles_checked_and_unchecked(plugin, message_log):
    _save_three(plugin)
    dialog = _dialog(plugin)
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.all_check.checkState() == Qt.CheckState.PartiallyChecked
    dialog.all_check.click()  # partly -> all
    assert dialog.all_check.checkState() == Qt.CheckState.Checked
    assert len(dialog.ticked_refs()) == 3
    assert dialog.average_meta_text().startswith("3 fits")
    dialog.all_check.click()  # all -> none
    assert dialog.all_check.checkState() == Qt.CheckState.Unchecked
    assert dialog.ticked_refs() == []
    assert dialog.average_text() == "No fits ticked"
    dialog.all_check.click()
    assert len(dialog.ticked_refs()) == 3
    assert message_log == []


def test_a_pick_is_kept_when_an_unusable_row_is_then_selected(plugin, message_log):
    import dataclasses

    s, key = plugin.session, plugin.session.keys()[0]
    good = s.add_velocity_fit(key, _stored(18.0, 0.0912))
    bad = dataclasses.replace(
        _hyperbola_fit(plugin),
        points=tuple(
            (tr, 0.1 + 0.01 * i) for i, (tr, _) in enumerate(_hyperbola_fit(plugin).points)
        ),
    )
    bad_id = s.add_velocity_fit(key, bad)
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    dialog = _dialog(plugin)
    assert bad_id in dialog._unusable
    dialog.select_fit(good)
    held = dialog.spin.value()
    dialog.select_fit(bad_id)
    assert dialog.spin.value() == held  # still A's value
    _apply(plugin, dialog)
    assert s.line_for_key(key).velocity_from_fit == good
    assert message_log == []


def test_use_average_after_a_time_zero_change_records_the_remeasured_numbers(plugin, message_log):
    from nsgeo.velocity_source import weighted_mean

    s, key = plugin.session, plugin.session.keys()[0]
    stored = _hyperbola_fit(plugin)
    ids = [s.add_velocity_fit(key, stored), s.add_velocity_fit(key, stored)]
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    zero = s.line_zero(key)
    moved = fit_at_zero(stored, s.line_for_key(key).distance_along(), zero)
    assert moved.v_m_ns != pytest.approx(stored.v_m_ns, abs=1e-5)
    dialog = _dialog(plugin)
    dialog.use_average_button.click()
    _apply(plugin, dialog)
    line = s.line_for_key(key)
    record = line.velocity_source
    assert [m.fit_id for m in record.members] == ids
    for m in record.members:
        assert m.v_m_ns == moved.v_m_ns and m.t0_ns == moved.t0_ns
        assert m.zero_ns == moved.zero_ns == pytest.approx(zero)
    expected, _ = weighted_mean([(moved.v_m_ns, moved.v_stderr_m_ns)] * 2)
    assert line.velocity.surface_velocity == pytest.approx(expected, rel=1e-12)
    assert message_log == []


def test_the_dialog_shows_stored_values_when_the_line_cannot_be_read(plugin):
    from plugin_testing import connect_message_log

    logged = []
    disconnect = connect_message_log(lambda msg, tag, level: logged.append((msg, level)))
    s, key = plugin.session, plugin.session.keys()[0]
    stored = _hyperbola_fit(plugin)
    s.add_velocity_fit(key, stored)
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    s.set_profiles(key, [])  # no source attached: the dialog must read the file
    s.line_for_key(key).path.rename(s.line_for_key(key).path.with_suffix(".gone"))

    try:
        dialog = _dialog(plugin)
    finally:
        disconnect()

    assert dialog.table.item(0, 2).text().startswith(f"{stored.v_m_ns:.4f}")
    assert not [m for m, level in logged if level == Qgis.MessageLevel.Critical]


def test_a_line_with_no_cached_profiles_is_read_for_the_refit(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    stored = _hyperbola_fit(plugin)
    s.add_velocity_fit(key, stored)
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    distance = s.line_for_key(key).distance_along()
    moved = fit_at_zero(stored, distance, s.line_zero(key))
    s.set_profiles(key, [])  # nothing cached: the dialog loads the file itself
    assert s.line_zero(key) is None

    dialog = _dialog(plugin)

    assert dialog.table.item(0, 2).text().startswith(f"{moved.v_m_ns:.4f}")


def test_an_unrefittable_fit_is_listed_but_never_applied(plugin, drive_dialog):
    import dataclasses

    s, key = plugin.session, plugin.session.keys()[0]
    good = _hyperbola_fit(plugin)
    # Times so early that the zero at sample 51 leaves them non-positive.
    bad = dataclasses.replace(
        good, points=tuple((tr, 0.1 + 0.01 * i) for i, (tr, _) in enumerate(good.points))
    )
    fit_id = s.add_velocity_fit(key, bad)
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))

    dialog = _dialog(plugin)
    seeded = dialog.spin.value()
    dialog.select_fit(fit_id)

    assert "cannot be fitted at this time zero" in dialog.flag_text(0)
    assert dialog.table.item(0, 2).text().startswith(f"{bad.v_m_ns:.4f}")  # stored values shown
    assert dialog.delete_button.isEnabled()
    assert dialog.highlighted_fit_id() == fit_id
    assert dialog.selected_fit_id() is None
    assert dialog.spin.value() == seeded  # its stored v was not loaded

    s.set_line_velocity(key, VelocityModel.constant(0.09))
    drive_dialog(QDialog, "exec", lambda d: (d.select_fit(fit_id), d.accept()))
    plugin.open_velocity_dialog(key)
    line = s.line_for_key(key)
    assert line.velocity == VelocityModel.constant(0.09)
    assert line.velocity_from_fit is None


# ---- tick boxes, the weighted average and what Apply records -------------------

_THREE = ((9.8, 0.0900, 0.002), (15.0, 0.0910, 0.002), (22.4, 0.0920, 0.003))


def _save_three(plugin, fits=_THREE):
    s, key = plugin.session, plugin.session.keys()[0]
    return [s.add_velocity_fit(key, _stored(t0, v, sg)) for t0, v, sg in fits]


def _refs(plugin, ids, key=None):
    key = key or plugin.session.keys()[0]
    return [(key, i) for i in ids]


def _apply(plugin, dialog, key=None):
    key = key or plugin.session.keys()[0]
    plugin.session.apply_line_velocity(key, dialog.velocity(), dialog.chosen_source())


def _expected_mean(fits=_THREE):
    from nsgeo.velocity_source import weighted_mean

    return weighted_mean([(v, sg) for _, v, sg in fits])


def test_every_usable_fit_is_ticked_when_there_is_no_record(plugin, message_log):
    ids = _save_three(plugin)
    dialog = _dialog(plugin)
    assert dialog.ticked_refs() == _refs(plugin, ids)
    assert dialog.all_check.checkState() == Qt.CheckState.Checked
    assert message_log == []


def test_an_unusable_fit_cannot_be_ticked(plugin, message_log):
    import dataclasses

    s, key = plugin.session, plugin.session.keys()[0]
    good = _hyperbola_fit(plugin)
    bad = dataclasses.replace(
        good, points=tuple((tr, 0.1 + 0.01 * i) for i, (tr, _) in enumerate(good.points))
    )
    fit_id = s.add_velocity_fit(key, bad)
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))

    dialog = _dialog(plugin)

    item = dialog.table.item(0, 0)
    assert not item.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert dialog.ticked_refs() == []
    dialog.all_check.setCheckState(Qt.CheckState.Checked)
    dialog.set_ticked([(key, fit_id)])
    assert dialog.ticked_refs() == []
    assert message_log == []


def test_the_average_reads_weighted_mean_count_and_depth_range(plugin, message_log):
    _save_three(plugin)
    dialog = _dialog(plugin)
    v, sg = _expected_mean()
    assert dialog.average_text() == f"{v:.4f} ± {sg:.4f} m/ns"
    assert dialog.average_meta_text() == "3 fits · t0 from 9.8 to 22.4 ns"
    assert dialog.use_average_button.isEnabled()
    assert dialog.average_warning_text() == ""
    assert message_log == []


def test_unticking_all_reads_no_fits_ticked_and_disables_use_average(plugin, message_log):
    _save_three(plugin)
    dialog = _dialog(plugin)
    dialog.all_check.setCheckState(Qt.CheckState.Unchecked)
    assert dialog.ticked_refs() == []
    assert dialog.average_text() == "No fits ticked"
    assert not dialog.use_average_button.isEnabled()
    dialog.all_check.setCheckState(Qt.CheckState.Checked)
    assert len(dialog.ticked_refs()) == 3
    assert message_log == []


def test_a_partly_ticked_table_shows_the_all_box_partly_checked(plugin, message_log):
    ids = _save_three(plugin)
    dialog = _dialog(plugin)
    dialog.set_ticked(_refs(plugin, ids[:2]))
    assert dialog.all_check.checkState() == Qt.CheckState.PartiallyChecked
    assert dialog.average_meta_text() == "2 fits · t0 from 9.8 to 15.0 ns"
    assert message_log == []


def test_disagreeing_ticked_fits_show_the_warning_and_agreeing_ones_do_not(plugin, message_log):
    warning = (
        "Some ticked fits disagree with each other. The ground may be layered, "
        "and one number may not suit every depth."
    )
    ids = _save_three(plugin, ((10.0, 0.090, 0.002), (20.0, 0.091, 0.002), (30.0, 0.140, 0.002)))
    dialog = _dialog(plugin)
    assert dialog.average_warning_text() == warning
    dialog.set_ticked(_refs(plugin, ids[:2]))
    assert dialog.average_warning_text() == ""
    assert dialog.use_average_button.isEnabled()  # a warning never blocks
    assert message_log == []


def test_a_zero_sigma_fit_ticked_shows_why_and_disables_use_average(plugin, message_log):
    _save_three(plugin, ((10.0, 0.090, 0.002), (20.0, 0.091, 0.0)))
    dialog = _dialog(plugin)
    assert "cannot be weighted" in dialog.average_text()
    assert "20.0 ns" in dialog.average_text()
    assert not dialog.use_average_button.isEnabled()
    assert message_log == []


def test_opening_the_dialog_computes_the_average_once(plugin, message_log, monkeypatch):
    from nsgeo_qgis.ui import velocity_dialog

    _save_three(plugin)
    real = velocity_dialog.weighted_mean
    calls = []

    def counting(values):
        calls.append(list(values))
        return real(values)

    monkeypatch.setattr(velocity_dialog, "weighted_mean", counting)
    _dialog(plugin)
    assert len(calls) == 1
    assert message_log == []


def test_use_average_then_apply_records_the_ticked_fits_unrounded(plugin, message_log):
    s, key = plugin.session, plugin.session.keys()[0]
    ids = _save_three(plugin)
    dialog = _dialog(plugin)
    dialog.use_average_button.click()
    assert dialog.spin.value() == pytest.approx(_expected_mean()[0], abs=5e-5)
    _apply(plugin, dialog)

    line = s.line_for_key(key)
    assert line.velocity.surface_velocity == pytest.approx(_expected_mean()[0], rel=1e-12)
    from nsgeo.velocity_source import METHOD_WEIGHTED_MEAN

    assert line.velocity_source.method == METHOD_WEIGHTED_MEAN
    assert [(m.line_key, m.fit_id) for m in line.velocity_source.members] == _refs(plugin, ids)
    assert line.velocity_source.applied_at is not None
    assert message_log == []


def test_use_average_with_one_tick_records_a_fit(plugin, message_log):
    from nsgeo.velocity_source import METHOD_FIT

    s, key = plugin.session, plugin.session.keys()[0]
    ids = _save_three(plugin)
    dialog = _dialog(plugin)
    dialog.set_ticked(_refs(plugin, ids[1:2]))
    dialog.use_average_button.click()
    _apply(plugin, dialog)
    line = s.line_for_key(key)
    assert line.velocity_source.method == METHOD_FIT
    assert line.velocity_from_fit == ids[1]
    assert line.velocity == VelocityModel.constant(0.091)
    assert message_log == []


def test_a_picked_row_then_apply_records_that_fit(plugin, message_log):
    from nsgeo.velocity_source import METHOD_FIT

    s, key = plugin.session, plugin.session.keys()[0]
    ids = _save_three(plugin)
    dialog = _dialog(plugin)
    dialog.select_fit(ids[2])
    _apply(plugin, dialog)
    line = s.line_for_key(key)
    assert line.velocity_source.method == METHOD_FIT
    assert line.velocity_from_fit == ids[2]
    assert line.velocity == VelocityModel.constant(0.092)
    assert message_log == []


def _record_of(plugin, ids, applied_at="2026-11-01T00:00:00Z"):
    from nsgeo.velocity_source import SourceFit, VelocitySource

    s, key = plugin.session, plugin.session.keys()[0]
    line = s.line_for_key(key)
    members = [SourceFit.of(key, i, line.path.stem, line.velocity_fits[i]) for i in ids]
    record = VelocitySource.from_fits(members, applied_at=applied_at)
    s.apply_line_velocity(key, VelocityModel.constant(record.v_m_ns), record)
    return record


def test_an_untouched_apply_keeps_the_record_as_it_was(plugin, message_log, drive_dialog):
    s, key = plugin.session, plugin.session.keys()[0]
    ids = _save_three(plugin)
    record = _record_of(plugin, ids[:2])
    drive_dialog(QDialog, "exec", lambda d: d.accept())

    plugin.open_velocity_dialog(key)

    line = s.line_for_key(key)
    assert line.velocity_source == record
    assert line.velocity == VelocityModel.constant(record.v_m_ns)  # not rounded to the box
    assert message_log == []


def test_a_number_typed_over_the_average_drops_the_record(plugin, message_log):
    s, key = plugin.session, plugin.session.keys()[0]
    _save_three(plugin)
    dialog = _dialog(plugin)
    dialog.use_average_button.click()
    dialog.spin.setValue(0.0777)
    _apply(plugin, dialog)
    line = s.line_for_key(key)
    assert line.velocity == VelocityModel.constant(0.0777)
    assert line.velocity_source is None
    assert message_log == []


def test_ticks_changed_after_use_average_without_a_second_press_drop_the_record(
    plugin, message_log
):
    s, key = plugin.session, plugin.session.keys()[0]
    ids = _save_three(plugin)
    dialog = _dialog(plugin)
    dialog.use_average_button.click()
    dialog.set_ticked(_refs(plugin, ids[:2]))
    _apply(plugin, dialog)
    assert s.line_for_key(key).velocity_source is None
    dialog = _dialog(plugin)
    dialog.set_ticked(_refs(plugin, ids[:2]))
    dialog.use_average_button.click()
    _apply(plugin, dialog)  # a second press records the two
    assert len(s.line_for_key(key).velocity_source.members) == 2
    assert message_log == []


def test_reopening_ticks_the_records_members(plugin, message_log):
    ids = _save_three(plugin)
    _record_of(plugin, ids[:2])
    dialog = _dialog(plugin)
    assert dialog.ticked_refs() == _refs(plugin, ids[:2])
    assert message_log == []


def test_the_note_names_a_deleted_member_and_a_time_zero_change(plugin, message_log):
    s, key = plugin.session, plugin.session.keys()[0]
    stored = _hyperbola_fit(plugin)
    first = s.add_velocity_fit(key, stored)
    second = s.add_velocity_fit(key, stored)
    _record_of(plugin, [first, second])
    assert "(applied 2026-11-01)" in _dialog(plugin).source_note_text()
    s.remove_velocity_fit(key, second)
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    moved = fit_at_zero(stored, s.line_for_key(key).distance_along(), s.line_zero(key))

    note = _dialog(plugin).source_note_text()

    assert "This velocity is the average of 2 fits" in note
    assert "deleted" in note
    assert f"now gives {moved.v_m_ns:.4f}" in note
    assert message_log == []


def test_a_record_with_every_member_unchanged_has_no_change_lines(plugin, message_log):
    ids = _save_three(plugin)
    _record_of(plugin, ids)
    note = _dialog(plugin).source_note_text()
    assert note == "This velocity is the average of 3 fits (applied 2026-11-01)."
    assert _dialog_without_record(plugin) is not None
    assert message_log == []


def _dialog_without_record(plugin):
    s, key = plugin.session, plugin.session.keys()[0]
    s.set_line_velocity(key, VelocityModel.constant(0.09))
    dialog = _dialog(plugin)
    assert dialog.source_note_text() == ""
    return dialog


def test_clear_override_drops_velocity_and_record(plugin, message_log, drive_dialog):
    s, key = plugin.session, plugin.session.keys()[0]
    ids = _save_three(plugin)
    _record_of(plugin, ids)
    drive_dialog(QDialog, "exec", lambda d: d.clear_button.click())
    plugin.open_velocity_dialog(key)
    line = s.line_for_key(key)
    assert line.velocity is None and line.velocity_source is None
    assert message_log == []


def test_deleting_a_member_says_so_in_the_confirmation_and_keeps_the_velocity(
    plugin, message_log, answer_modal
):
    s, key = plugin.session, plugin.session.keys()[0]
    ids = _save_three(plugin)
    record = _record_of(plugin, ids[:2])
    asked = _answer_delete(answer_modal, QMessageBox.StandardButton.Yes)
    dialog = _dialog(plugin)
    dialog.select_fit(ids[0])

    dialog.delete_button.click()

    (args, _), *_ = asked
    assert "average of 2 fits" in args[2] and "stays as it is" in args[2]
    line = s.line_for_key(key)
    assert line.velocity == VelocityModel.constant(record.v_m_ns)
    assert line.velocity_source == record
    assert "deleted" in dialog.source_note_text()
    assert dialog.ticked_refs() == _refs(plugin, ids[1:2])
    assert message_log == []


def test_the_profile_label_names_an_average_on_the_line(plugin, message_log):
    from nsgeo_qgis.ui.profile_dock import velocity_source

    s, key = plugin.session, plugin.session.keys()[0]
    ids = _save_three(plugin)
    _record_of(plugin, ids)
    assert velocity_source(s, key) == "line override, average of 3 fits"
    _record_of(plugin, ids[:1])
    assert velocity_source(s, key) == "line override (fit at 9.8 ns)"
    assert message_log == []
