from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.edit_lines_dialog import (
    CHANGED,
    COL_ALONG,
    COL_DIR,
    COL_GRID,
    COL_LABEL,
    COL_LENGTH,
    COL_NOTE,
    COL_OFFSET,
    COL_START,
    COL_TRACES,
    EditLinesDialog,
)
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtWidgets import QMessageBox

GRID5 = Grid("Grid5", (500.0, 700.0), 0.0, 15.0, 15.0, "EPSG:32616", 0.5)
GRID_B = Grid("B", (600.0, 700.0), 0.0, 10.0, 9.0, "EPSG:32616", 0.5)
# (start, direction): rows 1 and 3 are the stale reversed lines (written when
# the grid was 1 m longer); row 5 is reversed and right.
SHAPE = [(0.0, 1), (16.0, -1), (0.0, 1), (16.0, -1), (0.0, 1), (15.0, -1)]


class Spy:
    def __init__(self, signal):
        self.calls: list = []
        signal.connect(lambda *a: self.calls.append(a))


def _lines(tmp_path, grid):
    lines = []
    for i, (start, d) in enumerate(SHAPE):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(
            Line.open(p, GridPlacement(grid, "y", 0.25 + 0.5 * i, start, d, f"line {i + 1}"))
        )
    return lines


def _site(tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.add_grid(GRID5)
    s.add_grid(GRID_B)
    s.add_lines(_lines(tmp_path, "Grid5"))
    return s


@pytest.fixture
def table(qgis_app, tmp_path):
    session = _site(tmp_path)
    dialog = EditLinesDialog(session, "Grid5")
    yield session, dialog
    dialog.hide()
    dialog.deleteLater()


def _cell(dialog, row, col):
    return dialog.table.item(row, col).text()


def _changed(dialog, col):
    return [
        dialog.table.item(r, col).background().color() == CHANGED
        for r in range(dialog.table.rowCount())
    ]


def test_snap_on_every_row_fixes_the_stale_reversed_lines_and_nothing_else(table):
    session, dialog = table
    keys = dialog.keys()
    changed = Spy(session.lines_changed)
    dialog.select_keys(keys)
    dialog.snap_to_edge()
    assert [_cell(dialog, r, COL_START) for r in range(6)] == [
        "0.00",
        "15.00",
        "0.00",
        "15.00",
        "0.00",
        "15.00",
    ]
    assert [dialog.table.item(r, COL_START).background().color() == CHANGED for r in range(6)] == [
        False,
        True,
        False,
        True,
        False,
        False,
    ]
    assert dialog.status.text() == "2 lines changed · 0 picks will move with them"
    assert session.line_for_key(keys[1]).placement.start_along == 16.0  # nothing before OK
    dialog.accept()
    assert [session.line_for_key(k).placement.start_along for k in keys] == [
        0.0,
        15.0,
        0.0,
        15.0,
        0.0,
        15.0,
    ]
    assert set(dialog.outcome.changed) == {keys[1], keys[3]} and len(changed.calls) == 1


def test_the_table_lists_the_grids_lines_in_survey_order_with_their_placements(table):
    session, dialog = table
    assert dialog.keys() == session.keys_on_grid("Grid5")
    assert [_cell(dialog, r, COL_LABEL) for r in range(6)] == [f"line {i}" for i in range(1, 7)]
    assert [_cell(dialog, r, COL_START) for r in range(6)] == [
        "0.00",
        "16.00",
        "0.00",
        "16.00",
        "0.00",
        "15.00",
    ]
    assert [_cell(dialog, r, COL_DIR) for r in range(6)] == ["+1", "−1", "+1", "−1", "+1", "−1"]
    assert [dialog.table.cellWidget(r, COL_GRID).currentText() for r in range(6)] == ["Grid5"] * 6
    assert {_cell(dialog, r, COL_ALONG) for r in range(6)} == {"y"}
    assert {_cell(dialog, r, COL_TRACES) for r in range(6)} == {"60"}
    assert {_cell(dialog, r, COL_LENGTH) for r in range(6)} == {"1.00"}
    assert [_cell(dialog, r, COL_NOTE) for r in range(6)] == [
        "",
        "starts 1.00 m past the far edge",
        "",
        "starts 1.00 m past the far edge",
        "",
        "",
    ]
    assert dialog.header_label.text() == "Grid5 · 15.00 m along y × 15.00 m across · 6 lines"
    assert dialog.windowTitle() == "Edit lines · Grid5"


def test_cancel_applies_nothing(table):
    session, dialog = table
    keys = dialog.keys()
    before = [session.line_for_key(k).placement for k in keys]
    changed = Spy(session.lines_changed)
    dialog.select_keys(keys)
    dialog.snap_to_edge()
    dialog.shift_offset(1.0)
    dialog.reject()
    assert [session.line_for_key(k).placement for k in keys] == before
    assert changed.calls == []


def test_flip_sends_start_to_the_other_edge_and_back(table):
    _, dialog = table
    key = dialog.keys()[0]
    dialog.select_keys([key])
    dialog.flip()
    assert (_cell(dialog, 0, COL_DIR), _cell(dialog, 0, COL_START)) == ("−1", "15.00")
    assert _changed(dialog, COL_DIR)[0] and _changed(dialog, COL_START)[0]
    dialog.flip()
    assert (_cell(dialog, 0, COL_DIR), _cell(dialog, 0, COL_START)) == ("+1", "0.00")
    assert not any(_changed(dialog, COL_DIR)) and not any(_changed(dialog, COL_START))
    assert dialog.status.text() == ""


def test_typing_in_a_cell_edits_only_that_row(table):
    _, dialog = table
    keys = dialog.keys()
    dialog.table.item(2, COL_LABEL).setText("redone")
    dialog.table.item(2, COL_OFFSET).setText("0,40")
    # Dir first: a flip keeps the line's inset from its edge, so it would
    # recompute a Start typed before it.
    dialog.table.item(2, COL_DIR).setText("-1")
    dialog.table.item(2, COL_START).setText("0.5")
    e = dialog.edit_for(keys[2])
    assert (e.label, e.offset, e.start_along, e.direction) == ("redone", 0.4, 0.5, -1)
    assert [dialog.edit_for(k).changes(dialog.session.site.frames) for k in keys] == [
        False,
        False,
        True,
        False,
        False,
        False,
    ]
    assert _cell(dialog, 2, COL_OFFSET) == "0.40"


def test_a_cell_that_is_not_a_number_is_reverted_and_says_so(table):
    _, dialog = table
    keys = dialog.keys()
    dialog.table.item(2, COL_OFFSET).setText("abc")
    assert dialog.status.text() == "'abc' is not a number; unchanged"
    assert _cell(dialog, 2, COL_OFFSET) == "1.25"
    assert dialog.edit_for(keys[2]).offset is None
    dialog.table.item(2, COL_DIR).setText("0")
    assert dialog.status.text() == "'0' is not recognised as a direction; unchanged"
    assert dialog.edit_for(keys[2]).direction is None
    assert _cell(dialog, 2, COL_DIR) == "+1"


def test_shift_moves_each_selected_offset_by_the_amount(table):
    _, dialog = table
    dialog.select_keys(dialog.keys()[:2])
    dialog.shift_offset(0.1)
    assert [_cell(dialog, r, COL_OFFSET) for r in range(3)] == ["0.35", "0.85", "1.25"]


def test_moving_rows_to_another_grid_keeps_them_listed_until_ok(table):
    session, dialog = table
    key = dialog.keys()[5]
    dialog.select_keys([key])
    dialog.move_to("B")
    assert dialog.table.cellWidget(5, COL_GRID).currentText() == "B"
    assert _cell(dialog, 5, COL_START) == "9.00"
    assert dialog.table.rowCount() == 6 and dialog.keys()[5] == key
    dialog.accept()
    assert session.keys_on_grid("B")[-1] == key


def test_up_and_down_set_the_survey_order(table):
    session, dialog = table
    k = dialog.keys()
    dialog.select_keys([k[1], k[2]])
    dialog.move_selected(-1)
    assert dialog.keys() == [k[1], k[2], k[0], k[3], k[4], k[5]]
    assert dialog.selected_keys() == [k[1], k[2]]
    assert not dialog.up_button.isEnabled() and dialog.down_button.isEnabled()
    dialog.move_selected(-1)  # would leave the table: nothing
    assert dialog.keys() == [k[1], k[2], k[0], k[3], k[4], k[5]]
    dialog.select_keys([k[5]])
    assert not dialog.down_button.isEnabled() and dialog.up_button.isEnabled()
    dialog.accept()
    assert session.keys_on_grid("Grid5") == dialog.keys()


def test_the_status_counts_the_picks_that_will_move(qgis_app, tmp_path):
    session = _site(tmp_path)
    keys = session.keys_on_grid("Grid5")

    class Store:
        def picks_for(self, key):
            return [object(), object()] if key == keys[0] else []

    session.set_pick_store(Store())
    dialog = EditLinesDialog(session, "Grid5")
    dialog.select_keys([keys[0]])
    dialog.flip()
    assert dialog.status.text() == "1 line changed · 2 picks will move with it"
    dialog.table.item(2, COL_LABEL).setText("renamed")
    assert dialog.status.text() == "2 lines changed · 2 picks will move with them"
    dialog.deleteLater()


def test_the_bulk_panel_is_greyed_until_rows_are_selected_and_counts_them(table):
    _, dialog = table
    assert not dialog.bulk.isEnabled()
    dialog.select_keys(dialog.keys()[:3])
    assert dialog.bulk.isEnabled()
    assert dialog.bulk.title() == "Change the 3 selected lines"
    dialog.select_keys([])
    assert not dialog.bulk.isEnabled()


def test_ok_skips_a_line_changed_elsewhere_and_names_it(table):
    session, dialog = table
    keys = dialog.keys()
    dialog.select_keys([keys[2]])
    dialog.flip()
    session.edit_lines([_edit_offset(session, keys[2], 3.0)])
    dialog.accept()
    assert dialog.outcome.skipped[0].label == "line 3"
    assert session.line_for_key(keys[2]).placement.offset == 3.0
    assert session.line_for_key(keys[2]).placement.direction == 1


def _edit_offset(session, key, offset):
    from nsgeo_qgis.line_edit import LineEdit

    return LineEdit(key, seen=session.line_for_key(key).placement, offset=offset)


def test_a_concurrent_length_edit_is_not_undone_by_ok(table):
    import dataclasses

    session, dialog = table
    k = dialog.keys()
    dialog.select_keys([k[0]])
    dialog.flip()
    session.replace_grid(dataclasses.replace(GRID5, size_y=14.0))
    dialog.accept()
    starts = [session.line_for_key(key).placement.start_along for key in k]
    assert starts[0] == 14.0 and starts[1] == 15.0 and starts[3] == 15.0 and starts[5] == 14.0


def test_the_dialog_survives_its_grid_being_removed(table):
    session, dialog = table
    dialog.select_keys(dialog.keys())
    session.remove_grid("Grid5", with_lines=True)
    dialog.flip()
    dialog.snap_to_edge()
    dialog.accept()
    assert dialog.status.text() == "grid 'Grid5' no longer exists; nothing was changed"
    assert dialog.result() != dialog.DialogCode.Accepted


def test_a_site_closed_under_the_dialog_changes_nothing(table):
    session, dialog = table
    dialog.select_keys(dialog.keys())
    session.close_site()
    dialog.flip()
    assert dialog.status.text() == "no site is open"
    dialog.accept()
    assert dialog.status.text() == "no site is open; nothing was changed"
    assert dialog.outcome is None and dialog.result() != dialog.DialogCode.Accepted


def test_a_different_site_opened_under_the_dialog_changes_nothing(table, tmp_path):
    session, dialog = table
    dialog.select_keys(dialog.keys())
    dialog.flip()
    other = tmp_path.parent / (tmp_path.name + "_other")
    other.mkdir()
    session.new_site(other)
    dialog.accept()
    assert dialog.status.text() == (
        "a different site was opened while the table was open; nothing was changed"
    )
    assert dialog.outcome is None


def test_a_line_with_no_distance_axis_is_listed_and_editable(qgis_app, tmp_path):
    session = _site(tmp_path)
    p = synthetic_dzt(tmp_path / "raw", "FILE__099.DZT", n_traces=40, traces_per_metre=0.0)
    session.add_lines([Line.open(p, GridPlacement("Grid5", "y", 5.0, 0.0, 1, "timed"))])
    dialog = EditLinesDialog(session, "Grid5")
    assert dialog.table.rowCount() == 7
    assert _cell(dialog, 6, COL_LENGTH) == ""
    dialog.table.item(6, COL_OFFSET).setText("6.0")
    dialog.accept()
    assert session.line_for_key(dialog.keys()[6]).placement.offset == 6.0
    dialog.deleteLater()


def test_open_edit_lines_dialog_opens_one_table_per_grid_and_reports_on_ok(
    fake_iface, tmp_path, answer_modal, message_log
):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(Grid("A", (500.0, 700.0), 0.0, 15.0, 15.0, "EPSG:32616", 0.5))
    plugin.session.add_lines(_lines(tmp_path, "A"))
    k = plugin.session.keys_on_grid("A")
    plugin.open_edit_lines_dialog("A", [k[0]])
    dialog = plugin._edit_lines_dialogs["A"]
    assert dialog.selected_keys() == [k[0]]
    plugin.open_edit_lines_dialog("A", [k[1]])
    assert plugin._edit_lines_dialogs["A"] is dialog and dialog.selected_keys() == [k[1]]
    dialog.snap_to_edge()
    dialog.accept()
    assert any("Edit lines · A: changed" in m for m in message_log)
    assert plugin._edit_lines_dialogs == {}

    plugin.open_edit_lines_dialog("A", [])
    left_open = plugin._edit_lines_dialogs["A"]
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
    assert left_open.result() != left_open.DialogCode.Accepted
    assert plugin._edit_lines_dialogs == {}
