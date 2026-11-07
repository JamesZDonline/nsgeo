from __future__ import annotations

import dataclasses
import json

import pytest
from nsgeo.geometry import Grid, GridPlacement
from nsgeo_qgis.line_edit import (
    CHANGED_ELSEWHERE,
    EditOutcome,
    GridEditReport,
    LineEdit,
    Skipped,
    edge_inset,
    followed_length,
    length_along,
    placement_note,
    same_placement,
    start_at_inset,
    width_across,
)
from plugin_testing import SUNNYSIDE, needs_sunnyside

GRID = Grid("A", (0.0, 0.0), 0.0, 10.0, 15.0, "EPSG:32616", 0.5)  # 10 m in x, 15 m in y
GB = Grid("B", (50.0, 0.0), 0.0, 8.0, 9.0, "EPSG:32616", 0.5)
FRAMES = {"A": GRID, "B": GB}
FWD = GridPlacement("A", "y", 0.25, 0.0, 1, "line 1")
REV = GridPlacement("A", "y", 0.75, 15.0, -1, "line 2")
STALE = GridPlacement("A", "y", 3.75, 16.0, -1, "line 8")  # Grid 5's case
XREV = GridPlacement("A", "x", 2.0, 9.5, -1, "x 1")


def test_the_inset_is_measured_from_the_edge_the_line_starts_at():
    assert edge_inset(FWD, 15.0) == 0.0 and edge_inset(REV, 15.0) == 0.0
    assert edge_inset(STALE, 15.0) == pytest.approx(-1.0)
    assert start_at_inset(-1, 0.2, 15.0) == pytest.approx(14.8)
    assert (length_along(GRID, "y"), width_across(GRID, "y")) == (15.0, 10.0)
    assert (length_along(GRID, "x"), width_across(GRID, "x")) == (10.0, 15.0)


def test_a_length_change_moves_reversed_lines_with_the_far_edge_only():
    at16 = dataclasses.replace(REV, start_along=16.0)
    assert followed_length(at16, 16.0, 15.0).start_along == pytest.approx(15.0)
    assert followed_length(FWD, 16.0, 15.0) == FWD
    assert followed_length(STALE, 15.0, 14.0).start_along == pytest.approx(15.0)  # keeps its 1 m


def test_flip_sends_start_to_the_other_edge_keeping_the_inset():
    p = LineEdit("k", dataclasses.replace(FWD, start_along=0.2)).flipped(FRAMES).placed(FRAMES)
    assert (p.direction, p.start_along) == (-1, pytest.approx(14.8))
    q = LineEdit("k", XREV).flipped(FRAMES).placed(FRAMES)
    assert (q.direction, q.start_along) == (1, pytest.approx(0.5))  # x lines use size_x


def test_flipping_twice_is_no_change_at_all():
    seen = dataclasses.replace(FWD, start_along=0.3)
    e = LineEdit("k", seen).flipped(FRAMES).flipped(FRAMES)
    assert not e.changes(FRAMES) and same_placement(e.placed(FRAMES), seen)
    assert not LineEdit("k", REV).moved_to("B", FRAMES).moved_to("A", FRAMES).changes(FRAMES)


def test_snap_puts_each_line_at_its_own_edge():
    assert LineEdit("k", STALE).snapped().placed(FRAMES).start_along == 15.0
    assert (
        LineEdit("k", dataclasses.replace(FWD, start_along=0.4))
        .snapped()
        .placed(FRAMES)
        .start_along
        == 0.0
    )
    assert LineEdit("k", XREV).snapped().placed(FRAMES).start_along == 10.0


def test_a_move_keeps_the_inset_against_the_new_grids_length():
    assert LineEdit("k", REV, grid_id="B").placed(FRAMES) == GridPlacement(
        "B", "y", 0.75, 9.0, -1, "line 2"
    )
    moved = LineEdit("k", REV, start_along=14.5).moved_to("B", FRAMES)
    assert moved.placed(FRAMES).start_along == pytest.approx(8.5)


def test_an_inset_start_is_worked_out_against_the_length_when_applied():
    e = LineEdit("k", FWD).flipped(FRAMES)
    assert e.placed({"A": dataclasses.replace(GRID, size_y=20.0)}).start_along == 20.0


def test_shift_moves_the_offset_and_placed_names_a_missing_grid():
    assert LineEdit("k", REV).shifted(0.5, FRAMES).placed(FRAMES).offset == pytest.approx(1.25)
    with pytest.raises(KeyError):
        LineEdit("k", REV, grid_id="Z").placed(FRAMES)


def test_the_note_judges_only_the_start_and_the_offset():
    assert placement_note(STALE, GRID) == "starts 1.00 m past the far edge"
    inside = placement_note(dataclasses.replace(FWD, start_along=0.4), GRID)
    assert inside == "starts 0.40 m inside the near edge"
    assert placement_note(dataclasses.replace(FWD, start_along=0.04), GRID) == ""
    wide = placement_note(dataclasses.replace(REV, offset=10.3), GRID)
    assert wide == "offset 10.30 m is outside the grid's 10.00 m width"
    assert placement_note(REV, GRID) == ""


def test_the_messages_say_what_changed_and_name_what_was_left_alone():
    out = EditOutcome(changed=("a", "b"), skipped=(Skipped("c", "line 8", CHANGED_ELSEWHERE),))
    assert out.message() == (
        "changed 2 line(s); line 8 changed elsewhere while the table was open, "
        "so it was left as it is"
    )
    assert EditOutcome().message() == "nothing changed"
    assert (
        EditOutcome(changed=("a",), reordered=True).message()
        == "changed 1 line(s) and reordered the lines"
    )
    assert GridEditReport("Grid5", moved=(("y", 15.0, 15),)).message() == (
        "Grid5 is now 15.00 m along y; its 15 reversed line(s) moved with the far edge."
    )
    assert GridEditReport("A").message() == ""


@needs_sunnyside
def test_on_sunnyside_the_note_flags_exactly_grid5s_reversed_lines():
    data = json.loads(SUNNYSIDE.read_text())
    grids = {
        g["id"]: Grid(
            g["id"],
            tuple(g["origin"]),
            g["azimuth"],
            g["size_x"],
            g["size_y"],
            g["crs"],
            g["default_spacing"],
        )
        for g in data["grids"]
    }
    rows = []
    for line in data["lines"]:
        p = GridPlacement(**{k: v for k, v in line["placement"].items() if k != "type"})
        rows.append((p.grid_id, p.label, placement_note(p, grids[p.grid_id])))
    assert len(rows) == 210
    flagged = [r for r in rows if r[2]]
    assert len(flagged) == 15
    assert {r[0] for r in flagged} == {"Grid5"}
    assert {r[2] for r in flagged} == {"starts 1.00 m past the far edge"}
