"""The grid velocity dialog: every fit on a grid's lines, ticked and averaged,
and the grid's velocity set from them (grid velocity spec §4, §7)."""

from __future__ import annotations

import dataclasses
import re
import time

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.velocity import VelocityModel
from nsgeo.velocity_fit import StoredFit, fit_at_zero, fit_hyperbola
from nsgeo.velocity_source import (
    METHOD_FIT,
    METHOD_WEIGHTED_MEAN,
    SourceFit,
    VelocitySource,
    weighted_mean,
)
from plugin_testing import click_header_section, click_table_cell, synthetic_dzt
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from tests.real_data import GRID2_LINES

GRID_A = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)
GRID_B = Grid("B", (600.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)

HINT = "Slices and cuts on this grid use this velocity."
INTRO = (
    "Saved hyperbola fits on this grid's lines. Tick fits to average them; "
    "pick one to use its velocity."
)


@pytest.fixture
def plugin(fake_iface, tmp_path, answer_modal):
    """Three lines on grid A and one on grid B. Lines 1-3 are A's, in survey
    order; line 4 is B's. Every line's first fit is `fit-1`."""
    import nsgeo_qgis

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID_A)
    s.add_grid(GRID_B)
    lines = [
        Line.open(
            synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT", n_traces=60),
            GridPlacement("A" if i < 4 else "B", "y", float(i % 4), 0.0),
        )
        for i in (1, 2, 3, 4)
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


def _keys(plugin):
    """The four line keys: A's three in survey order, then B's."""
    return plugin.session.keys()


def _stored(t0, v, sigma=0.002, apex=30, n=4, fitted_at="2026-11-12T00:00:00+00:00"):
    pts = tuple((apex + i, t0 + i) for i in range(n))
    return StoredFit(t0, v, sigma, 0.25, apex, pts, fitted_at)


def _dialog(plugin, grid_id="A"):
    from nsgeo_qgis.ui.velocity_dialog import VelocityDialog

    return VelocityDialog(plugin.session, grid_id=grid_id)


def _rows(dialog):
    return [dialog.row_ref(r) for r in range(dialog.table.rowCount())]


def _save_spread(plugin):
    """Fits on every line, with repeated ids: line 1 has two (saved deepest
    first), lines 2 and 3 one each, and B's line one. Returns the refs of A's
    fits in the order the dialog lists them."""
    s = plugin.session
    k1, k2, k3, k4 = _keys(plugin)
    deep = s.add_velocity_fit(k1, _stored(30.0, 0.0910, apex=40))
    shallow = s.add_velocity_fit(k1, _stored(12.0, 0.0900, apex=20))
    two = s.add_velocity_fit(k2, _stored(9.8, 0.0920))
    three = s.add_velocity_fit(k3, _stored(22.4, 0.0905, 0.003))
    s.add_velocity_fit(k4, _stored(15.0, 0.1000))
    assert deep == two == three == "fit-1"  # the hazard: every line has a fit-1
    return [(k1, shallow), (k1, deep), (k2, two), (k3, three)]


def _record(plugin, refs, applied_at="2026-11-01T00:00:00Z"):
    """Set grid A's velocity from `refs` with a record of them, as Apply would."""
    s = plugin.session
    members = []
    for key, fit_id in refs:
        line = s.line_for_key(key)
        members.append(SourceFit.of(key, fit_id, line.path.stem, line.velocity_fits[fit_id]))
    record = VelocitySource.from_fits(members, applied_at=applied_at)
    s.apply_grid_velocity("A", VelocityModel.constant(record.v_m_ns), record)
    return record


def test_grid_dialog_lists_every_fit_on_the_grids_lines_only(plugin, message_log):
    refs = _save_spread(plugin)

    dialog = _dialog(plugin)

    assert _rows(dialog) == refs  # by line in survey order, then by t0; B's line left out
    lines = [dialog.table.item(r, 1).text() for r in range(4)]
    assert lines == ["FILE__001", "FILE__001", "FILE__002", "FILE__003"]
    assert dialog.table.horizontalHeaderItem(1).text() == "Line"
    assert dialog.table.item(0, 2).text() == "12.0"
    assert dialog.table.item(0, 3).text().startswith("0.0900")
    assert dialog.windowTitle() == "Velocity · A"
    assert dialog.velocity_hint.text() == HINT
    assert dialog.intro_text() == INTRO
    assert dialog.clear_button.text() == "Clear grid velocity"
    assert dialog.ticked_refs() == refs  # no record: every fit ticked
    v, sg = weighted_mean([(0.0900, 0.002), (0.0910, 0.002), (0.0920, 0.002), (0.0905, 0.003)])
    assert dialog.average_text() == f"{v:.4f} ± {sg:.4f} m/ns"
    assert dialog.average_meta_text() == "4 fits on 3 lines · t0 from 9.8 to 30.0 ns"
    assert message_log == []


@pytest.fixture
def shown(qgis_app):
    """`show(dialog)`: the dialog shown at a fixed size, so real clicks land
    on real cell geometry; hidden and deleted after the test."""
    from qgis.PyQt.QtWidgets import QApplication

    dialogs = []

    def show(dialog):
        dialogs.append(dialog)
        dialog.resize(800, 500)
        dialog.show()
        QApplication.processEvents()
        return dialog

    yield show
    for dialog in dialogs:
        dialog.hide()
        dialog.deleteLater()
    QApplication.processEvents()


def test_grid_dialog_sorts_by_a_clicked_column_and_keeps_ticks_and_selection(
    plugin, shown, message_log
):
    refs = _save_spread(plugin)
    dialog = shown(_dialog(plugin))
    dialog.set_ticked(refs[1:3])
    dialog.select_row(3)
    held = dialog.spin.value()
    header = dialog.table.horizontalHeader()
    assert header.sortIndicatorSection() == 1  # Line: the order the rows open in

    click_header_section(header, 2)  # t0

    by_t0 = [refs[2], refs[0], refs[3], refs[1]]  # 9.8, 12.0, 22.4, 30.0
    assert _rows(dialog) == by_t0
    assert header.sortIndicatorSection() == 2
    assert set(dialog.ticked_refs()) == set(refs[1:3])
    assert dialog.highlighted_ref() == refs[3]
    assert dialog.spin.value() == held  # a sort fills nothing
    click_header_section(header, 2)  # again: deepest first
    assert _rows(dialog) == by_t0[::-1]
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    click_header_section(header, 0)  # the tick column: no sort, and the indicator stays
    assert _rows(dialog) == by_t0[::-1]
    assert header.sortIndicatorSection() == 2
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    click_header_section(header, 1)  # Line: back to survey order
    assert _rows(dialog) == refs
    assert message_log == []


def test_grid_dialog_lights_the_picked_fits_curve_when_its_line_is_open(
    plugin, drive_dialog, message_log
):
    refs = _save_spread(plugin)
    view = plugin.profile_dock.view
    seen = []

    def _drive(d):
        d.select_row(1)  # line 1's fit at apex 40: line 1 is the open line
        i = view._saved_velocity_highlight
        seen.append(None if i is None else min(view._saved_velocity_curves[i], key=lambda p: p[1]))
        d.select_row(2)  # line 2's fit-1: not on the profile
        seen.append(view._saved_velocity_highlight)
        d.reject()

    drive_dialog(QDialog, "exec", _drive)

    plugin.open_grid_velocity_dialog("A")

    assert refs[1][0] == plugin.session.current_key
    assert seen[0][0] == pytest.approx(40, abs=0.5)
    assert seen[1] is None
    assert view._saved_velocity_highlight is None  # unlit once the dialog closes
    assert message_log == []


def test_grid_dialog_stars_lines_with_their_own_velocity_and_names_them(plugin, message_log):
    s = plugin.session
    refs = _save_spread(plugin)
    assert _dialog(plugin).starred_note_text() == ""
    s.set_line_velocity(refs[2][0], VelocityModel.constant(0.0889))

    dialog = _dialog(plugin)

    assert [dialog.table.item(r, 1).text() for r in range(4)] == [
        "FILE__001",
        "FILE__001",
        "FILE__002*",
        "FILE__003",
    ]
    assert dialog.starred_note_text() == (
        "* FILE__002 has its own velocity (0.0889). Apply doesn't change it."
    )
    assert message_log == []


def test_grid_dialog_names_several_lines_with_their_own_velocities(plugin, message_log):
    s = plugin.session
    k1, k2, k3, _ = _keys(plugin)
    _save_spread(plugin)
    s.set_line_velocity(k3, VelocityModel.constant(0.0912))
    s.set_line_velocity(k1, VelocityModel.constant(0.0889))
    assert _dialog(plugin).starred_note_text() == (
        "* FILE__001 (0.0889) and FILE__003 (0.0912) have their own velocities. "
        "Apply doesn't change them."
    )
    assert message_log == []


def test_grid_dialog_deletes_the_fit_of_the_row_picked_not_another_lines_fit_1(
    plugin, answer_modal, message_log
):
    s = plugin.session
    refs = _save_spread(plugin)
    k1, k2, k3, k4 = _keys(plugin)
    asked = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Yes)
    dialog = _dialog(plugin)
    dialog.select_row(2)  # line 2's fit-1
    assert dialog.row_ref(2) == (k2, "fit-1")

    dialog.delete_button.click()

    (args, _), *_ = asked
    assert "FILE__002's fit at 9.8 ns" in args[2]
    assert s.line_for_key(k2).velocity_fits == {}
    assert set(s.line_for_key(k1).velocity_fits) == {"fit-1", "fit-2"}
    assert set(s.line_for_key(k3).velocity_fits) == {"fit-1"}
    assert set(s.line_for_key(k4).velocity_fits) == {"fit-1"}
    assert _rows(dialog) == [refs[0], refs[1], refs[3]]
    assert dialog.ticked_refs() == [refs[0], refs[1], refs[3]]
    assert message_log == []


def test_grid_dialog_delete_warns_of_a_member_of_the_grids_or_its_lines_velocity(
    plugin, answer_modal, message_log
):
    s = plugin.session
    refs = _save_spread(plugin)
    grid_record = _record(plugin, refs[:3])
    k1 = refs[0][0]
    deep = s.line_for_key(k1).velocity_fits["fit-1"]
    line_member = SourceFit.of(k1, refs[1][1], "FILE__001", deep)
    s.apply_line_velocity(
        k1,
        VelocityModel.constant(line_member.v_m_ns),
        VelocitySource.from_fits([line_member], applied_at=None),
    )
    asked = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Yes)
    dialog = _dialog(plugin)

    dialog.select_row(3)  # line 3's fit: in no record
    dialog.delete_button.click()
    dialog.select_row(0)  # line 1's shallow fit: in the grid's average only
    dialog.delete_button.click()
    dialog.select_row(0)  # line 1's fit-1: in both
    dialog.delete_button.click()

    texts = [args[2] for args, _ in asked]
    assert "stays" not in texts[0] and "velocity" not in texts[0].split("?", 1)[1]
    assert "this grid's velocity, the average of 3 fits" in texts[1]
    assert "stays as it is" in texts[1]
    assert "this grid's velocity, the average of 3 fits" in texts[2]
    assert "This fit set FILE__001's velocity." in texts[2]
    assert "These velocities stay as they are" in texts[2]
    assert s.grid("A").velocity_source == grid_record  # deleting a member keeps the record
    assert message_log == []


def test_grid_dialog_flags_disagreement_across_lines(plugin, message_log):
    s = plugin.session
    k1, k2, k3, _ = _keys(plugin)
    # 0.090 and 0.100 are 0.010 apart, over 2 x 0.0028: they disagree. 0.095
    # sits within 2σ of both. Each line's own fit-1, so a flag keyed by bare
    # fit id could not tell line 2's from the others.
    s.add_velocity_fit(k1, _stored(10.0, 0.0900))
    s.add_velocity_fit(k1, _stored(20.0, 0.0950))
    s.add_velocity_fit(k2, _stored(15.0, 0.0950))
    s.add_velocity_fit(k3, _stored(25.0, 0.1000))

    dialog = _dialog(plugin)

    assert dialog.flagged_refs() == {(k1, "fit-1"), (k3, "fit-1")}
    flags = [dialog.flag_text(r) for r in range(4)]
    assert ["disagrees" in f for f in flags] == [True, False, False, True]
    assert dialog.average_warning_text().startswith("Some ticked fits disagree")
    dialog.set_ticked([(k1, "fit-2"), (k2, "fit-1"), (k3, "fit-1")])
    assert dialog.average_warning_text() == ""
    assert message_log == []


def test_grid_dialog_apply_of_an_average_sets_grid_velocity_and_record_not_line_overrides(
    plugin, drive_dialog, message_log
):
    s = plugin.session
    refs = _save_spread(plugin)
    k1, k2, k3, k4 = _keys(plugin)
    s.set_line_velocity(k2, VelocityModel.constant(0.0889))
    drive_dialog(QDialog, "exec", lambda d: (d.use_average_button.click(), d.accept()))

    plugin.open_grid_velocity_dialog("A")

    expected, _ = weighted_mean(
        [(0.0900, 0.002), (0.0910, 0.002), (0.0920, 0.002), (0.0905, 0.003)]
    )
    grid = s.grid("A")
    assert grid.velocity.surface_velocity == pytest.approx(expected, rel=1e-12)  # unrounded
    record = grid.velocity_source
    assert record.method == METHOD_WEIGHTED_MEAN
    assert [(m.line_key, m.fit_id) for m in record.members] == refs
    assert [m.line_label for m in record.members] == [
        "FILE__001",
        "FILE__001",
        "FILE__002",
        "FILE__003",
    ]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", record.applied_at)  # P6
    assert s.line_for_key(k2).velocity == VelocityModel.constant(0.0889)  # left alone
    assert s.line_for_key(k1).velocity is None and s.line_for_key(k3).velocity is None
    assert s.grid("B").velocity is None and s.grid("B").velocity_source is None
    assert message_log == []


def test_grid_dialog_a_picked_row_records_that_lines_fit(plugin, drive_dialog, message_log):
    s = plugin.session
    refs = _save_spread(plugin)

    def _drive(d):
        d.table.cellClicked.emit(2, 3)  # line 2's fit-1
        d.accept()

    drive_dialog(QDialog, "exec", _drive)

    plugin.open_grid_velocity_dialog("A")

    grid = s.grid("A")
    assert grid.velocity == VelocityModel.constant(0.0920)
    (member,) = grid.velocity_source.members
    assert grid.velocity_source.method == METHOD_FIT
    assert (member.line_key, member.fit_id, member.line_label) == (*refs[2], "FILE__002")
    assert grid.velocity_source.summary() == "fit on FILE__002"
    assert message_log == []


def test_grid_dialog_a_real_click_in_a_tick_cell_off_the_box_does_not_pick(
    plugin, shown, message_log
):
    # Line 3's fit (0.0905) differs from the average, so a pick would show in
    # the box as well as in the record.
    refs = _save_spread(plugin)
    dialog = shown(_dialog(plugin))
    dialog.use_average_button.click()
    held = dialog.spin.value()
    assert round(held, 4) != 0.0905

    click_table_cell(dialog.table, 3, 0, right_edge=True)

    assert dialog.table.item(3, 0).checkState() == Qt.CheckState.Checked  # off the box
    assert dialog.highlighted_ref() == refs[3]  # selected, for the curve
    assert dialog.spin.value() == held
    source = dialog.chosen_source()
    assert source.method == METHOD_WEIGHTED_MEAN  # the average stays the record
    assert [(m.line_key, m.fit_id) for m in source.members] == refs

    click_table_cell(dialog.table, 2, 3)  # a data cell does pick: line 2's fit-1
    assert dialog.spin.value() == pytest.approx(0.0920)
    source = dialog.chosen_source()
    assert source.method == METHOD_FIT
    assert (source.members[0].line_key, source.members[0].fit_id) == refs[2]
    assert message_log == []


def test_grid_dialog_the_all_box_ticks_every_usable_fit_across_lines(plugin, message_log):
    refs = _save_spread(plugin)
    dialog = _dialog(plugin)
    dialog.set_ticked(refs[2:3])
    assert dialog.all_check.checkState() == Qt.CheckState.PartiallyChecked

    dialog.all_check.click()  # partly -> all

    assert dialog.ticked_refs() == refs
    assert dialog.average_meta_text() == "4 fits on 3 lines · t0 from 9.8 to 30.0 ns"
    dialog.all_check.click()  # all -> none
    assert dialog.ticked_refs() == []
    assert dialog.average_text() == "No fits ticked"
    assert message_log == []


def test_grid_dialog_ticks_changed_after_use_average_drop_the_record(
    plugin, drive_dialog, message_log
):
    # Spec §7.2 rule 4: the box no longer holds the average of what is ticked.
    s = plugin.session
    refs = _save_spread(plugin)

    def _drive(d):
        d.use_average_button.click()
        d.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        d.accept()

    drive_dialog(QDialog, "exec", _drive)
    plugin.open_grid_velocity_dialog("A")

    grid = s.grid("A")
    assert grid.velocity is not None and grid.velocity_source is None

    def _drive_again(d):
        d.set_ticked([refs[0], refs[2]])
        d.use_average_button.click()  # a second press records what is ticked now
        d.accept()

    drive_dialog(QDialog, "exec", _drive_again)
    plugin.open_grid_velocity_dialog("A")

    record = s.grid("A").velocity_source
    assert [(m.line_key, m.fit_id) for m in record.members] == [refs[0], refs[2]]
    assert message_log == []


def test_grid_dialog_a_line_imported_again_does_not_pass_its_new_fit_1_for_the_old(
    plugin, message_log
):
    # Spec §7.1 and §12: the line keeps its key, but its fits and its id
    # counter start over. Only `fitted_at` tells the new fit-1 from the old.
    s = plugin.session
    refs = _save_spread(plugin)
    k3 = refs[3][0]
    record = _record(plugin, [refs[0], refs[3]])
    path = s.line_for_key(k3).path
    s.remove_line(k3)
    s.add_lines([Line.open(path, GridPlacement("A", "y", 3.0, 0.0))])
    assert s.keys_on_grid("A")[-1] == k3
    new = s.add_velocity_fit(
        k3, _stored(22.4, 0.0905, 0.003, fitted_at="2026-11-13T09:00:00+00:00")
    )
    assert new == refs[3][1]  # the same id as the record's member

    dialog = _dialog(plugin)

    assert dialog.source_note_text() == "\n".join(
        [
            "This velocity is the average of 2 fits (applied 2026-11-01).",
            "FILE__003's fit at 22.4 ns: deleted",
        ]
    )
    assert refs[3] in _rows(dialog)
    assert dialog.ticked_refs() == [refs[0]]  # the new fit-1 is not the member
    assert dialog.chosen_source() == record  # nothing filled: the record stays
    assert message_log == []


def test_grid_dialog_an_untouched_apply_keeps_the_record_as_it_was(
    plugin, drive_dialog, message_log
):
    s = plugin.session
    refs = _save_spread(plugin)
    record = _record(plugin, refs[1:3])
    drive_dialog(QDialog, "exec", lambda d: d.accept())

    plugin.open_grid_velocity_dialog("A")

    assert s.grid("A").velocity_source == record
    assert s.grid("A").velocity == VelocityModel.constant(record.v_m_ns)
    assert message_log == []


def test_grid_dialog_a_typed_number_drops_the_record(plugin, drive_dialog, message_log):
    s = plugin.session
    refs = _save_spread(plugin)
    _record(plugin, refs[1:3])
    drive_dialog(QDialog, "exec", lambda d: (d.spin.setValue(0.0777), d.accept()))

    plugin.open_grid_velocity_dialog("A")

    assert s.grid("A").velocity == VelocityModel.constant(0.0777)
    assert s.grid("A").velocity_source is None
    assert message_log == []


def test_grid_dialog_reopens_with_the_records_members_ticked(plugin, message_log):
    refs = _save_spread(plugin)
    _record(plugin, [refs[1], refs[3]])

    dialog = _dialog(plugin)

    assert dialog.ticked_refs() == [refs[1], refs[3]]
    assert dialog.all_check.checkState() == Qt.CheckState.PartiallyChecked
    assert dialog.source_note_text() == (
        "This velocity is the average of 2 fits (applied 2026-11-01)."
    )
    assert message_log == []


def test_grid_dialog_selects_a_single_fit_record_quietly_on_open(plugin, message_log):
    refs = _save_spread(plugin)
    record = _record(plugin, [refs[2]])
    dialog = _dialog(plugin)
    assert dialog.highlighted_ref() == refs[2]
    assert dialog.source_note_text() == (
        "This velocity is FILE__002's fit at 9.8 ns (applied 2026-11-01)."
    )
    assert dialog.chosen_source() == record  # opening filled nothing
    assert message_log == []


def test_grid_dialog_note_names_a_member_moved_to_another_grid_and_a_removed_line(
    plugin, message_log
):
    s = plugin.session
    refs = _save_spread(plugin)
    k1, k2, k3, _ = _keys(plugin)
    record = _record(plugin, [refs[0], refs[2], refs[3]])
    s.move_lines([k2], "B")
    s.remove_line(k3)

    dialog = _dialog(plugin)

    assert dialog.source_note_text() == "\n".join(
        [
            "This velocity is the average of 3 fits (applied 2026-11-01).",
            "FILE__002's fit at 9.8 ns: line moved to grid B",
            "FILE__003's fit at 22.4 ns: line removed",
        ]
    )
    assert _rows(dialog) == refs[:2]  # the moved and removed lines' fits are not A's
    assert dialog.ticked_refs() == [refs[0]]
    assert s.grid("A").velocity_source == record  # the record stays as it was
    assert message_log == []


def test_grid_dialog_an_unusable_fit_on_one_line_leaves_another_lines_fit_1_usable(
    plugin, message_log
):
    s = plugin.session
    k1, k2, _, _ = _keys(plugin)
    good = _hyperbola_fit(plugin, k1)
    # Times so early that a zero at sample 51 leaves them non-positive.
    bad = dataclasses.replace(
        good, points=tuple((tr, 0.1 + 0.01 * i) for i, (tr, _) in enumerate(good.points))
    )
    s.add_velocity_fit(k1, bad)
    s.add_velocity_fit(k2, good)
    s.append_step(k1, build_step("time_zero", mode="sample", sample=51))

    dialog = _dialog(plugin)

    assert _rows(dialog) == [(k1, "fit-1"), (k2, "fit-1")]
    assert "cannot be fitted at this time zero" in dialog.flag_text(0)
    assert "cannot be fitted" not in dialog.flag_text(1)
    assert dialog.ticked_refs() == [(k2, "fit-1")]
    assert dialog.table.item(1, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert not dialog.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert message_log == []


def test_grid_dialog_with_no_fits_says_so_and_still_applies_a_typed_velocity(
    plugin, drive_dialog, message_log
):
    s = plugin.session
    seen = []

    def _drive(d):
        seen.append(
            (
                d.table.rowCount(),
                d.average_text(),
                d.use_average_button.isEnabled(),
                d.all_check.isEnabled(),
                d.spin.value(),
                d.apply_button.isEnabled(),
            )
        )
        d.spin.setValue(0.0950)
        d.accept()

    drive_dialog(QDialog, "exec", _drive)

    plugin.open_grid_velocity_dialog("A")

    assert seen == [(0, "No fits on this grid's lines yet", False, False, 0.0, False)]
    assert s.grid("A").velocity == VelocityModel.constant(0.095)
    assert s.grid("A").velocity_source is None
    assert message_log == []


def test_grid_dialog_opens_on_the_grids_velocity(plugin, message_log):
    plugin.session.set_grid_velocity("A", VelocityModel.constant(0.0888))
    assert _dialog(plugin).spin.value() == pytest.approx(0.0888)
    assert message_log == []


def test_grid_dialog_clear_drops_velocity_and_record(plugin, drive_dialog, message_log):
    s = plugin.session
    refs = _save_spread(plugin)
    _record(plugin, refs)
    drive_dialog(QDialog, "exec", lambda d: d.clear_button.click())

    plugin.open_grid_velocity_dialog("A")

    assert s.grid("A").velocity is None and s.grid("A").velocity_source is None
    assert len(s.line_for_key(refs[0][0]).velocity_fits) == 2  # the fits themselves stay
    assert message_log == []


def test_grid_dialog_reads_each_fitted_lines_zero_once(plugin, monkeypatch, message_log):
    from nsgeo_qgis.ui import velocity_dialog

    s = plugin.session
    k1, k2, k3, _ = _keys(plugin)
    s.add_velocity_fit(k1, _stored(12.0, 0.0900))
    s.add_velocity_fit(k1, _stored(30.0, 0.0910))
    s.add_velocity_fit(k2, _stored(9.8, 0.0920))  # line 3 has none
    real = velocity_dialog.fits_at_line_zero
    calls = []

    def counting(session, key):
        calls.append(key)
        return real(session, key)

    monkeypatch.setattr(velocity_dialog, "fits_at_line_zero", counting)

    dialog = _dialog(plugin)
    assert calls == [k1, k2]

    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)  # untick
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)  # tick
    dialog.all_check.click()
    dialog.table.cellClicked.emit(2, 3)  # pick
    dialog.select_row(1)
    dialog.use_average_button.click()
    dialog.table.horizontalHeader().sectionClicked.emit(2)
    dialog.velocity()
    dialog.chosen_source()

    assert calls == [k1, k2]
    assert message_log == []


def test_set_velocity_on_a_grid_row_opens_the_grid_velocity_dialog(
    plugin, drive_dialog, message_log
):
    from nsgeo_qgis.ui.velocity_dialog import VelocityDialog

    calls = drive_dialog(QDialog, "exec", lambda d: d.reject())

    plugin.survey_dock.grid_velocity_requested.emit("A")

    (dialog,) = calls
    assert isinstance(dialog, VelocityDialog)
    assert dialog.grid_id == "A" and dialog.key is None
    assert plugin._grid_dialog is None  # not Edit grid
    assert message_log == []


def test_a_stale_grid_id_is_reported_not_raised(plugin, fake_iface):
    plugin.open_grid_velocity_dialog("gone")  # the autouse fixture fails on a swallowed error
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "gone" in item.text()


def _hyperbola_fit(plugin, key):
    """A real hyperbola (t0 20 ns, v 0.1) saved on the radar clock with no step."""
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


# ---- real data: four lines of Grid 2 ---------------------------------------------

GRID2_LENGTH = 29.96


@pytest.mark.skipif(len(GRID2_LINES) < 4, reason="needs Grid 2 in tests/data/local/grid2")
def test_real_grid2_lines_list_and_average_their_fits(qgis_app, tmp_path, message_log):
    """Four real lines with a Time zero step and a saved fit each. Nothing is
    cached, so the dialog reads each line to find its zero: the numbers it
    lists are each fit measured from its own line's zero, and Apply records
    those."""
    from nsgeo_qgis.session import SiteSession
    from nsgeo_qgis.ui.velocity_dialog import VelocityDialog

    s = SiteSession()
    s.new_site(tmp_path)
    s.add_grid(Grid("G2", (500.0, 700.0), 0.0, 2.0, GRID2_LENGTH, "EPSG:32616", 0.5))
    paths = GRID2_LINES[:4]
    s.add_lines(
        [
            Line.open(p, GridPlacement("G2", "y", 0.25 + 0.5 * k, 0.0, 1, p.stem))
            for k, p in enumerate(paths)
        ]
    )
    keys = s.keys()
    stored = {}
    for k, key in enumerate(keys):
        distance = s.line_for_key(key).distance_along()
        apex = len(distance) // 3 + 40 * k
        traces = [apex] + [apex + d for d in (-60, 60, -120, 120)]
        x = np.array([distance[t] for t in traces])
        # A diffraction at 25 + 3k ns on the radar clock, 0.1 m/ns.
        t0 = 25.0 + 3.0 * k
        t = np.sqrt(t0**2 + (4.0 / 0.01) * (x - x[0]) ** 2)
        fitted = fit_hyperbola(x, t, x[0])
        fit = StoredFit(
            fitted.t0_ns,
            fitted.v_m_ns,
            fitted.v_stderr_m_ns,
            fitted.rms_ns,
            apex,
            tuple((tr, float(ti)) for tr, ti in zip(traces, t, strict=True)),
            "2026-11-12T00:00:00+00:00",
        )
        s.add_velocity_fit(key, fit)
        stored[key] = fit
        s.append_step(key, build_step("time_zero"))
        assert s.line_zero(key) is None  # not open: the dialog must read the line

    started = time.perf_counter()
    dialog = VelocityDialog(s, grid_id="G2")
    opened = time.perf_counter() - started

    expected = {}
    for key in keys:
        zero = s.line_zero(key, load=True)
        assert zero is not None and abs(zero) > 0.1  # a real first break moves the numbers
        expected[key] = fit_at_zero(stored[key], s.line_for_key(key).distance_along(), zero)
        assert expected[key].v_m_ns != pytest.approx(stored[key].v_m_ns, abs=1e-4)
    assert _rows(dialog) == [(key, "fit-1") for key in keys]
    for row, key in enumerate(keys):
        assert dialog.table.item(row, 3).text().startswith(f"{expected[key].v_m_ns:.4f}")
    dialog.use_average_button.click()
    s.apply_grid_velocity("G2", dialog.velocity(), dialog.chosen_source())

    record = s.grid("G2").velocity_source
    assert [m.line_key for m in record.members] == keys
    for m in record.members:
        assert m.v_m_ns == expected[m.line_key].v_m_ns
        assert m.zero_ns == expected[m.line_key].zero_ns
    mean, _ = weighted_mean([(f.v_m_ns, f.v_stderr_m_ns) for f in expected.values()])
    assert s.grid("G2").velocity.surface_velocity == pytest.approx(mean, rel=1e-12)
    # Reported, not asserted: P9 is pinned by test_grid_dialog_reads_each_fitted_lines_zero_once,
    # since timing tests have flaked here before (#165).
    print(f"grid velocity dialog over 4 uncached Grid 2 lines opened in {opened:.2f} s")
    assert message_log == []
