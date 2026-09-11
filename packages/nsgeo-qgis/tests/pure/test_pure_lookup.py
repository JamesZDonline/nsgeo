from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.fit import fit_grid_from_corners
from nsgeo.geometry.grid import Grid
from nsgeo_qgis.lookup import (
    ImportOptions,
    corners_from_polygon,
    identity_curve,
    nearest_trace,
    plan_import,
    recompute_offsets,
    rows_to_lines,
    sort_files,
    trailing_number,
)
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt

OPTS = ImportOptions(grid_id="A", axis="y", spacing=0.5, grid_size_along=11.0)


def test_trailing_number_and_vendor_neutral_sort(tmp_path):
    assert trailing_number("FILE__012") == 12
    assert trailing_number("DAT_0007") == 7
    assert trailing_number("LINE03") == 3
    assert trailing_number("notes") is None
    paths = [tmp_path / n for n in ("FILE__010.DZT", "FILE__002.DZT", "FILE__001.DZT", "extra.DZT")]
    assert [p.name for p in sort_files(paths)] == [
        "FILE__001.DZT",
        "FILE__002.DZT",
        "FILE__010.DZT",
        "extra.DZT",
    ]


@pytest.fixture
def three(tmp_path):
    return [synthetic_dzt(tmp_path, f"FILE__00{i}.DZT", n_traces=60 * (i + 1)) for i in (3, 1, 2)]


def test_plan_import_orders_offsets_alternates_direction_and_reads_headers(three):
    rows = plan_import(three, OPTS)
    assert [r.path.name for r in rows] == ["FILE__001.DZT", "FILE__002.DZT", "FILE__003.DZT"]
    assert [r.offset for r in rows] == [0.0, 0.5, 1.0]
    assert [r.direction for r in rows] == [1, -1, 1]
    assert [r.label for r in rows] == ["FILE__001", "FILE__002", "FILE__003"]
    assert [r.n_traces for r in rows] == [120, 180, 240]
    assert rows[0].length_m == pytest.approx(2.0)
    assert all(r.include and r.placeable and r.sidecar is None for r in rows)


def test_excluding_a_row_pulls_later_rows_into_its_slot(three):
    rows = plan_import(three, OPTS)
    rows[1].include = False
    recompute_offsets(rows, OPTS)
    assert [r.offset for r in rows if r.include] == [0.0, 0.5]
    assert [r.direction for r in rows if r.include] == [1, -1]


def test_hand_edited_offsets_survive_recompute(three):
    rows = plan_import(three, OPTS)
    rows[2].offset = 3.25
    rows[2].offset_edited = True
    rows[0].include = False
    recompute_offsets(rows, OPTS)
    assert [r.offset for r in rows if r.include] == [0.0, 3.25]


def test_direction_modes_and_line_number_labels(three):
    forward = ImportOptions("A", "y", 0.5, direction_mode="forward", label_source="number")
    rows = plan_import(three, forward)
    assert [r.direction for r in rows] == [1, 1, 1]
    assert [r.label for r in rows] == ["line 0", "line 1", "line 2"]
    reverse = ImportOptions("A", "y", 0.5, direction_mode="reverse", first_offset=2.0)
    rows = plan_import(three, reverse)
    assert [r.direction for r in rows] == [-1, -1, -1]
    assert rows[0].offset == 2.0


def test_time_triggered_files_are_flagged_and_excluded(tmp_path):
    good = synthetic_dzt(tmp_path, "FILE__001.DZT")
    bad = synthetic_dzt(tmp_path, "FILE__002.DZT", traces_per_metre=0.0)
    rows = plan_import([good, bad], OPTS)
    assert rows[1].placeable is False and rows[1].include is False
    assert "time-triggered" in rows[1].note
    assert rows[1].length_m is None
    lines = rows_to_lines(rows, OPTS)
    assert [ln.path.name for ln in lines] == ["FILE__001.DZT"]


def test_overrunning_the_grid_is_a_warning_note(tmp_path):
    long = synthetic_dzt(tmp_path, "FILE__001.DZT", n_traces=60 * 12)  # 12 m in an 11 m grid
    rows = plan_import([long], OPTS)
    assert "exceeds" in rows[0].note and rows[0].include


def test_rows_to_lines_builds_grid_placements(three):
    rows = plan_import(three, OPTS)
    lines = rows_to_lines(rows, OPTS)
    p = lines[1].placement
    assert (p.grid_id, p.axis, p.offset, p.direction, p.label) == ("A", "y", 0.5, -1, "FILE__002")


def test_nearest_trace_within_tolerance():
    a = np.column_stack([np.zeros(10), np.arange(10.0)])
    b = np.column_stack([np.full(10, 5.0), np.arange(10.0)])
    hit = nearest_trace({"a": a, "b": b}, (4.8, 3.2), tolerance=0.5)
    assert hit is not None
    key, idx, dist = hit
    assert (key, idx) == ("b", 3) and dist == pytest.approx((0.2**2 + 0.2**2) ** 0.5)
    assert nearest_trace({"a": a, "b": b}, (2.5, 3.0), tolerance=0.5) is None
    assert nearest_trace({}, (0.0, 0.0), tolerance=1.0) is None


def test_corners_from_polygon_yields_a_fittable_rectangle():
    grid = Grid("G", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)
    world = grid.to_world(np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 11.0], [0.0, 11.0]]))
    ring = [tuple(p) for p in world] + [tuple(world[0])]  # closed ring, as QGIS gives it
    corners = corners_from_polygon(ring, origin_index=0, plus_y_index=3)
    assert corners.size_x == pytest.approx(5.0) and corners.size_y == pytest.approx(11.0)
    fit = fit_grid_from_corners(corners.local, corners.world)
    assert fit.azimuth == pytest.approx(30.0, abs=1e-6)
    assert fit.residual_rms < 1e-9
    assert fit.origin == pytest.approx((500.0, 700.0))


def test_corners_from_polygon_rejects_non_adjacent_plus_y():
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    with pytest.raises(ValueError, match="adjacent"):
        corners_from_polygon(ring, origin_index=0, plus_y_index=2)
    with pytest.raises(ValueError, match="four"):
        corners_from_polygon(ring[:3], origin_index=0, plus_y_index=1)


def test_identity_curve_spans_the_time_axis_at_zero_db():
    assert identity_curve(-11.0, 0.5, 5) == [[-11.0, 0.0], [-9.0, 0.0]]


@needs_real_data
def test_real_files_plan_cleanly():
    rows = plan_import(REAL_DZT, OPTS)
    assert len(rows) == 10
    assert [r.n_traces for r in rows] == [608, 625, 629, 658, 613, 608, 635, 666, 653, 606]
    assert all(9.0 < r.length_m < 13.0 for r in rows)
    assert sum(r.sidecar is not None for r in rows) == 9
    by_name = {r.path.stem: r for r in rows}
    assert len(by_name["FILE__007"].sidecar.marks) == 1
    assert by_name["FILE__010"].sidecar is None
    assert "exceeds" in by_name["FILE__008"].note  # 11.10 m in an 11.0 m grid


# --- defects found in the brief's reference implementation, beyond its given
# tests (see task-7-report.md for the full write-up) -------------------------


def test_recompute_offsets_preserves_other_notes_and_is_idempotent(tmp_path):
    """The reference `recompute_offsets` always reassigned `row.note` from
    scratch, so any note set once at construction time (a malformed-sidecar
    warning) was silently erased the moment recompute_offsets ran -- which
    plan_import always does immediately, and which the import dialog will do
    again on every table edit. recompute_offsets must only ever touch the
    note components it is itself responsible for, and must not duplicate
    them when called again."""
    path = synthetic_dzt(tmp_path, "FILE__001.DZT", n_traces=60 * 12)  # 12 m, overruns 11 m
    rows = plan_import([path], OPTS)
    assert "exceeds" in rows[0].note
    rows[0].note = f"sidecar unreadable: boom; {rows[0].note}"
    recompute_offsets(rows, OPTS)
    assert "sidecar unreadable: boom" in rows[0].note
    assert "exceeds" in rows[0].note
    recompute_offsets(rows, OPTS)  # idempotent: no duplication on a second call
    assert rows[0].note.count("exceeds") == 1
    assert rows[0].note.count("sidecar unreadable") == 1


def test_plan_import_survives_one_corrupt_header_among_good_files(tmp_path):
    """The reference `plan_import` read every header with no try/except, so
    one corrupt/non-DZT file in an import batch raised and produced *no*
    rows at all -- the exact "crash that kills the whole import" the brief's
    sharp edges warn against for traces_per_metre=0, just triggered by an
    unreadable header instead."""
    good = synthetic_dzt(tmp_path, "FILE__001.DZT")
    garbage = tmp_path / "FILE__002.DZT"
    garbage.write_bytes(b"not a dzt file")
    rows = plan_import([good, garbage], OPTS)
    assert [r.path.name for r in rows] == ["FILE__001.DZT", "FILE__002.DZT"]
    bad = rows[1]
    assert bad.n_traces is None and bad.length_m is None
    assert bad.include is False and bad.placeable is False
    assert "cannot read header" in bad.note
    # Review round 1, finding 3: nothing is known about a file whose header
    # never read, so the note must not assert a false fact about its
    # acquisition mode.
    assert "time-triggered" not in bad.note
    lines = rows_to_lines(rows, OPTS)
    assert [ln.path.name for ln in lines] == ["FILE__001.DZT"]


# --- review round 1 findings -------------------------------------------------


@needs_real_data
def test_reversed_lines_are_placed_within_the_grid_on_real_files():
    """Finding 1: GridPlacement.distance_along is
    start_along + direction * (i / spm), so a direction=-1 row starting at
    the same start_along as a direction=1 row runs *backward*, off the far
    side of the origin edge, instead of down into the grid. A reversed row
    must start at the far end of the axis (start_along + grid_size_along)
    for its samples to land inside [0, grid_size_along] at all.

    With the default alternating zigzag, half of the ten real lines are
    reversed. Every one of them must run from the far edge back toward the
    origin, landing within the grid except for FILE__008, which is already
    known to overrun it by about 10 cm (666 traces / 60 traces per metre =
    11.1 m in an 11.0 m grid) -- not by the ~10 m a mirrored placement
    would produce.
    """
    rows = plan_import(REAL_DZT, OPTS)
    lines = rows_to_lines(rows, OPTS)
    reversed_lines = [ln for ln in lines if ln.placement.direction == -1]
    assert len(reversed_lines) == 5  # FILE__002, 004, 006, 008, 010
    overruns = 0
    for ln in reversed_lines:
        along = ln.distance_along()
        assert along.max() == pytest.approx(OPTS.grid_size_along)
        assert along.min() > -0.15  # the known ~10 cm overrun, never ~10 m
        if along.min() < 0:
            overruns += 1
    assert overruns == 1  # exactly FILE__008


def test_corners_from_polygon_rejects_a_mirrored_plus_y_pick():
    """Finding 2: only a *diagonal* plus_y_index was rejected. Of the two
    corners adjacent to the origin, exactly one yields a right-handed
    frame; the other silently mirrors +X and +Y onto each other's corners.
    fit_grid_from_corners forbids reflection by construction, so the
    mirrored pick still returns a plausible-looking grid (same size,
    azimuth, and origin as the correct pick) with only a large
    residual_rms to show for it."""
    grid = Grid("G", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)
    world = grid.to_world(np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 11.0], [0.0, 11.0]]))
    ring = [tuple(p) for p in world] + [tuple(world[0])]
    with pytest.raises(ValueError, match="mirrored"):
        corners_from_polygon(ring, origin_index=1, plus_y_index=2)


def test_corners_from_polygon_mirror_check_is_winding_independent():
    """Finding 2, continued: the mirror check must key off world-coordinate
    handedness, not the ring's own traversal direction. Reversing the
    ring's vertex order must not change which pick is flagged: the same
    physical +Y corner is still accepted, and the same physical +X corner
    (now offered as a plausible plus_y_index) is still rejected."""
    grid = Grid("G", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)
    world = grid.to_world(np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 11.0], [0.0, 11.0]]))
    reversed_ring = [tuple(world[i]) for i in (0, 3, 2, 1)]
    reversed_ring = reversed_ring + [reversed_ring[0]]
    # index 1 of the reversed ring is world[3], the true +Y corner: valid.
    corners = corners_from_polygon(reversed_ring, origin_index=0, plus_y_index=1)
    assert corners.size_x == pytest.approx(5.0) and corners.size_y == pytest.approx(11.0)
    fit = fit_grid_from_corners(corners.local, corners.world)
    assert fit.residual_rms < 1e-9
    # index 3 of the reversed ring is world[1], the true +X corner: mirrored.
    with pytest.raises(ValueError, match="mirrored"):
        corners_from_polygon(reversed_ring, origin_index=0, plus_y_index=3)
