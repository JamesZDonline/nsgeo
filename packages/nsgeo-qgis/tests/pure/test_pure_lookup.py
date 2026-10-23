from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.fit import fit_grid_from_corners
from nsgeo.geometry.grid import Grid
from nsgeo_qgis.lookup import (
    CORNER_ROLES,
    ImportOptions,
    compass_label,
    corner_frame,
    identity_curve,
    nearest_trace,
    plan_import,
    recompute_offsets,
    roles_from_ring,
    rotate_roles,
    rows_to_lines,
    sort_files,
    trailing_number,
    utm_epsg,
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


def test_hand_edited_direction_survives_recompute_and_start_along_follows_it(three):
    # A per-row direction flip: recompute_offsets must not re-derive
    # row.direction from direction_mode/slot once direction_edited is set
    # (mirrors offset_edited/label_edited), and the start_along mirroring
    # -- keyed off row.direction, not options.direction_mode -- must
    # follow the hand-set direction too, not strand it with the *other*
    # direction's start_along and a spurious "reversed direction" note.
    rows = plan_import(three, OPTS)
    assert rows[1].direction == -1  # alternate's default for slot 1
    rows[1].direction = 1
    rows[1].direction_edited = True
    recompute_offsets(rows, OPTS)
    recompute_offsets(rows, OPTS)  # a second, unrelated replan must not undo it
    assert rows[1].direction == 1
    assert rows[1].start_along == 0.0  # forward: starts at options.start_along
    assert "reversed direction" not in rows[1].note


def test_hand_edited_labels_survive_recompute(three):
    rows = plan_import(three, OPTS)
    rows[1].label = "line 6a"
    rows[1].label_edited = True
    recompute_offsets(rows, OPTS)
    assert rows[1].label == "line 6a"


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


def test_reversed_direction_note_is_idempotent_and_clears_once_grid_length_is_known(tmp_path):
    """Round 2 regression: the reversed-direction note (added when a
    direction=-1 row can't be positioned because grid_size_along is
    unknown) used to embed _merge_note's own "; " delimiter, so it was
    stored as two components -- only the first recognised by the
    "reversed direction" marker on a later call. That orphaned the second
    component, which then grew by one copy on every recompute_offsets
    call and could never be cleared, even after the grid length became
    known and the row was correctly placed."""
    unknown = ImportOptions("A", "y", 0.5)  # grid_size_along=None
    path_a = synthetic_dzt(tmp_path, "FILE__001.DZT")
    path_b = synthetic_dzt(tmp_path, "FILE__002.DZT")
    rows = plan_import([path_a, path_b], unknown)  # plan_import itself recomputes once
    reversed_row = next(r for r in rows if r.direction == -1)
    note_after_first_recompute = reversed_row.note
    assert "reversed direction" in note_after_first_recompute

    for _ in range(3):
        recompute_offsets(rows, unknown)
    assert reversed_row.note == note_after_first_recompute  # unchanged, not growing
    assert reversed_row.note.count("reversed direction") == 1

    known = ImportOptions("A", "y", 0.5, grid_size_along=11.0)
    recompute_offsets(rows, known)
    assert "reversed direction" not in reversed_row.note  # cleared, not left stale
    assert reversed_row.start_along == pytest.approx(11.0)


# --- corner rules ---------------------------------------------------------

G = Grid("A", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)
W = [tuple(p) for p in G.to_world(np.array([[0, 0], [5, 0], [5, 11], [0, 11]], dtype=float))]


def _pts(*rows):
    return [W[i] if i in rows else None for i in range(4)]


def test_corner_roles_order():
    assert CORNER_ROLES == ("origin", "+X", "+X+Y", "+Y")


@pytest.mark.parametrize(
    "lon, lat, epsg",
    [
        (-86.8, 36.1, 32616),
        (-84.0, 10.0, 32617),
        (-84.000001, 10.0, 32616),
        (180.0, 0.0, 32601),
        (-180.0, 0.0, 32601),
        (179.99, 0.0, 32660),
        (0.5, -0.0001, 32731),
        (0.5, 84.0, 32631),
    ],
)
def test_utm_epsg_picks_the_zone(lon, lat, epsg):
    assert utm_epsg(lon, lat) == epsg


@pytest.mark.parametrize("lon, lat", [(0.0, 84.01), (0.0, -84.01), (float("nan"), 0.0)])
def test_utm_epsg_is_none_where_utm_is_undefined(lon, lat):
    assert utm_epsg(lon, lat) is None


@pytest.mark.parametrize("rows", [(0, 1), (0, 3), (0, 1, 2), (1, 2, 3), (0, 1, 2, 3)])
def test_corner_frame_recovers_the_grid(rows):
    f = corner_frame(_pts(*rows))
    fit = fit_grid_from_corners(f.local, f.world)
    assert f.rows == rows
    assert fit.origin == pytest.approx(G.origin, abs=1e-9)
    assert fit.azimuth == pytest.approx(30.0, abs=1e-9)
    assert fit.residual_rms < 1e-9


def test_corner_frame_measures_each_axis_from_its_own_edges():
    f = corner_frame(_pts(0, 1))
    assert (f.size_x, f.size_y) == (pytest.approx(5.0), None)
    pts = _pts(0, 1, 2, 3)
    x_hat, _ = G.axes()
    pts[2] = tuple(np.asarray(pts[2]) + 0.4 * x_hat)
    assert corner_frame(pts).size_x == pytest.approx(5.2, abs=1e-9)  # mean of 5.0 and 5.4


@pytest.mark.parametrize(
    "rows, message",
    [
        ((0,), "at least two corners"),
        ((0, 2), "don't fix the size along X"),
        ((1, 3), "don't fix the size along X"),
        ((1, 2), "don't fix the size along X"),
    ],
)
def test_corner_frame_refuses_corners_that_do_not_fix_the_grid(rows, message):
    with pytest.raises(ValueError, match=message):
        corner_frame(_pts(*rows))


def test_corner_frame_refuses_the_wrong_slot_count():
    with pytest.raises(ValueError, match="expected four corner slots, got 3"):
        corner_frame([W[0], W[1], W[2]])


def test_corner_frame_names_y_when_y_is_unfixed():
    with pytest.raises(ValueError, match="don't fix the size along Y"):
        corner_frame(_pts(2, 3))


def test_corner_frame_refuses_coincident_corners():
    with pytest.raises(ValueError, match="coincide"):
        corner_frame([W[0], W[0], None, None])


def test_corner_frame_refuses_mirrored_corners():
    four = [W[0], W[3], W[2], W[1]]
    with pytest.raises(ValueError, match="mirrored"):
        corner_frame(four)
    with pytest.raises(ValueError, match="mirrored"):
        corner_frame([W[0], W[3], None, W[1]])


@pytest.mark.parametrize("a, b", [(0, 1), (1, 2), (2, 3), (3, 0)])
def test_corner_frame_refuses_crossed_corners(a, b):
    pts = list(W)
    pts[a], pts[b] = pts[b], pts[a]
    with pytest.raises(ValueError, match="out of order"):
        corner_frame(pts)


def test_corner_frame_refuses_crossed_corners_with_noise():
    offsets = [(0.03, -0.02), (-0.04, 0.01), (0.02, 0.05), (-0.01, -0.03)]
    pts = [(p[0] + o[0], p[1] + o[1]) for p, o in zip(W, offsets, strict=True)]
    pts[2], pts[3] = pts[3], pts[2]
    with pytest.raises(ValueError, match="out of order"):
        corner_frame(pts)


def test_corner_frame_refuses_corners_in_a_line():
    line = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), None]
    with pytest.raises(ValueError, match="in a line"):
        corner_frame(line)


def test_roles_from_ring_puts_the_origin_where_plus_y_points_north():
    pts, idx = roles_from_ring(W + [W[0]])
    assert idx == [0, 1, 2, 3]
    assert pts == W


@pytest.mark.parametrize("az", [0, 30, 100, 200, 300])
def test_roles_from_ring_default_plus_y_is_within_45_degrees_of_north(az):
    g = Grid("A", (500.0, 700.0), float(az), 5.0, 11.0, "EPSG:32616", 0.5)
    ring = [tuple(p) for p in g.to_world(np.array([[0, 0], [5, 0], [5, 11], [0, 11]], dtype=float))]
    pts, _ = roles_from_ring(ring)
    dx, dy = pts[3][0] - pts[0][0], pts[3][1] - pts[0][1]
    assert abs(np.degrees(np.arctan2(dx, dy))) <= 45.0 + 1e-9


def test_roles_from_ring_is_winding_independent():
    pts, idx = roles_from_ring([W[3], W[2], W[1], W[0], W[3]])
    assert pts == W
    assert idx == [3, 2, 1, 0]


def test_roles_from_ring_ignores_a_repeated_vertex():
    pts, idx = roles_from_ring([W[0], W[1], W[1], W[2], W[3], W[0]])
    assert len(pts) == 4 and idx == [0, 1, 2, 3]


def test_roles_from_ring_refuses_anything_but_four_corners():
    with pytest.raises(ValueError, match="got 3"):
        roles_from_ring(W[:3])
    with pytest.raises(ValueError, match="got 5"):
        roles_from_ring(W + [(1.0, 2.0)])


def test_rotate_roles_keeps_the_frame_right_handed():
    rolled = rotate_roles(W)
    assert rolled == [W[1], W[2], W[3], W[0]]
    f = corner_frame(rolled)
    assert fit_grid_from_corners(f.local, f.world).residual_rms < 1e-9


def test_rotate_roles_moves_empty_rows_too():
    rows = ["a", None, "c", None]
    assert rotate_roles(rows) == [None, "c", None, "a"]
    out = rows
    for _ in range(4):
        out = rotate_roles(out)
    assert out == rows


@pytest.mark.parametrize(
    "dx, dy, label",
    [
        (0, 1, "N"),
        (1, 1, "NE"),
        (1, 0, "E"),
        (1, -1, "SE"),
        (0, -1, "S"),
        (-1, -1, "SW"),
        (-1, 0, "W"),
        (-1, 1, "NW"),
        (0.38, 1, "N"),
        (0.42, 1, "NE"),
    ],
)
def test_compass_label(dx, dy, label):
    assert compass_label((10.0 + dx, 20.0 + dy), (10.0, 20.0)) == label


def test_roles_from_ring_tie_goes_to_the_lower_vertex_on_either_winding():
    g = Grid("A", (500.0, 700.0), 45.0, 5.0, 5.0, "EPSG:32616", 0.5)
    sq = [tuple(p) for p in g.to_world(np.array([[0, 0], [5, 0], [5, 5], [0, 5]], dtype=float))]
    for ring, lowest_tied in ((sq, 0), (sq[::-1], 2)):
        _, idx = roles_from_ring(ring)
        assert idx[0] == lowest_tied
