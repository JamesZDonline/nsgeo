"""Planning an Import GPS lines table without Qt or qgis (M17a Task 4, #134)."""

from __future__ import annotations

from pathlib import Path

import pytest
from nsgeo.geometry import END_LIMIT_M, Grid, TrackPlacement
from nsgeo_qgis.gps_import import (
    NO_GPS_FORMAT,
    OUTSIDE,
    count_with_gps,
    first_fixed_lonlat,
    import_messages,
    plan_gps_rows,
    shifted_lines,
    with_grid,
)
from plugin_testing import (
    synthetic_dt1,
    synthetic_dzt,
    synthetic_gps_dzt,
    synthetic_mala,
    synthetic_segy,
)
from tests.dzg_data import local_xy, write_dzg

LAT0, LON0 = 45.2, 10.5
TO_XY = local_xy(LAT0, LON0)
CRS = "EPSG:32632"
M_PER_DEG = 6_371_000.0 * 3.141592653589793 / 180.0


def fix(trace: int, quality: int = 4) -> tuple[int, float, float, int]:
    """A fix on a line walked due north at 0.1 m a trace."""
    return (trace, LAT0 + trace * 0.1 / M_PER_DEG, LON0, quality)


def never(_: Path) -> bool:
    return False


def always(_lon: float, _lat: float) -> bool:
    return True


def plan(paths, taken=never, usable=always):
    return plan_gps_rows(paths, TO_XY, CRS, taken, usable)


def make(folder: Path, name: str, qualities: dict[int, int] | None = None, **kw) -> Path:
    """A 200-trace line at 10 traces a metre with fixes at 25, 75, 125, 175."""
    q = {25: 4, 75: 4, 125: 4, 175: 4, **(qualities or {})}
    return synthetic_gps_dzt(
        folder, name, [fix(t, q[t]) for t in sorted(q)], traces_per_metre=10.0, **kw
    )


def test_a_ready_row_carries_its_line_counts_bridges_and_ends(tmp_path):
    path = make(tmp_path, "FILE__001.DZT", {75: 5})
    (row,) = plan([path])
    assert row.refusal is None
    assert row.path == path
    assert row.n_traces == 200
    assert (row.n_fixes, row.n_fixed) == (4, 3)
    assert row.line is not None and row.line.n_traces == 200
    placement = row.line.placement
    assert isinstance(placement, TrackPlacement)
    assert placement.crs == CRS and placement.label == "FILE__001"
    assert placement.travel_shift == 0.0
    (bridge,) = row.bridges
    assert (bridge.first_trace, bridge.last_trace) == (25, 125)
    assert bridge.metres == pytest.approx(10.0, abs=0.01)
    assert row.without_rtk_m == pytest.approx(10.0, abs=0.01)
    assert row.end_runs == pytest.approx((2.5, 2.4), abs=0.01)


def test_a_row_with_no_bridge_has_none_without_rtk(tmp_path):
    (row,) = plan([make(tmp_path, "FILE__001.DZT")])
    assert row.bridges == () and row.without_rtk_m == 0.0


def test_rows_that_cannot_be_placed_are_refused_with_their_reason(tmp_path):
    bare = synthetic_dzt(tmp_path, "FILE__001.DZT")
    none = make(tmp_path, "FILE__002.DZT", {25: 1, 75: 1, 125: 1, 175: 1})
    one = make(tmp_path, "FILE__003.DZT", {25: 1, 75: 4, 125: 1, 175: 1})
    falling = synthetic_gps_dzt(
        tmp_path, "FILE__004.DZT", [fix(50), fix(25), fix(75)], traces_per_metre=10.0
    )
    rows = plan([bare, none, one, falling])
    assert [r.refusal for r in rows[:3]] == [
        "no DZG beside it",
        "no RTK-fixed position",
        "only one RTK-fixed position",
    ]
    assert rows[3].refusal is not None
    assert rows[3].refusal.startswith("could not read it: ")
    assert "trace numbers must rise" in rows[3].refusal
    for r in rows:
        assert r.line is None
        assert r.bridges == () and r.end_runs == (0.0, 0.0)
    assert rows[0].n_traces == 60  # the DZT itself read fine
    assert (rows[1].n_fixes, rows[1].n_fixed) == (4, 0)


def test_an_unreadable_dzt_is_refused_not_raised(tmp_path):
    junk = tmp_path / "FILE__001.DZT"
    junk.write_bytes(b"not a radar file")
    (row,) = plan([junk])
    assert row.line is None and row.n_traces is None
    assert row.refusal is not None and row.refusal.startswith("could not read it: ")


def test_a_file_already_in_the_site_is_refused_with_how_to_switch(tmp_path):
    path = make(tmp_path, "FILE__001.DZT")
    (row,) = plan([path], taken=lambda p: p == path)
    assert row.refusal == "already in the site"
    assert row.line is None
    # planned, then refused: its counts and ends are still there
    assert (row.n_traces, row.n_fixes, row.n_fixed) == (200, 4, 4)
    assert row.end_runs == pytest.approx((2.5, 2.4), abs=0.01)


def test_a_file_outside_the_site_crs_is_refused(tmp_path):
    path = make(tmp_path, "FILE__001.DZT")
    seen: list[tuple[float, float]] = []

    def usable(lon: float, lat: float) -> bool:
        seen.append((lon, lat))
        return False

    (row,) = plan([path], usable=usable)
    assert row.refusal == f"outside what {CRS} can place"
    assert row.line is None
    # asked at the line's own first RTK-fixed position
    assert seen == [pytest.approx((LON0, LAT0 + 25 * 0.1 / M_PER_DEG))]


def test_rows_come_back_in_the_order_the_paths_were_given(tmp_path):
    a = make(tmp_path, "FILE__002.DZT")
    b = make(tmp_path, "FILE__001.DZT")
    assert [r.path for r in plan([a, b])] == [a, b]


def test_first_fixed_lonlat_is_the_first_rtk_fix_of_the_dzg_beside_the_dzt(tmp_path):
    path = make(tmp_path, "FILE__001.DZT")
    # a non-RTK fix before the first RTK one is not it
    write_dzg(path.with_suffix(".DZG"), [fix(10, 1), fix(25), fix(75)])
    lon, lat = first_fixed_lonlat(path)
    assert lon == pytest.approx(LON0, abs=1e-6)
    assert lat == pytest.approx(LAT0 + 25 * 0.1 / M_PER_DEG, abs=1e-6)


def test_first_fixed_lonlat_is_none_when_there_is_nothing_to_read(tmp_path):
    assert first_fixed_lonlat(synthetic_dzt(tmp_path, "FILE__001.DZT")) is None
    assert first_fixed_lonlat(tmp_path / "missing.DZT") is None
    none = make(tmp_path, "FILE__002.DZT", {25: 1, 75: 1, 125: 1, 175: 1})
    assert first_fixed_lonlat(none) is None


def test_shifted_lines_sets_the_shift_on_ready_rows_only(tmp_path):
    ok = make(tmp_path, "FILE__001.DZT")
    bad = synthetic_dzt(tmp_path, "FILE__002.DZT")
    ok2 = make(tmp_path, "FILE__003.DZT")
    rows = plan([ok, bad, ok2])
    lines = shifted_lines(rows, 0.24)
    assert [ln.path for ln in lines] == [ok, ok2]
    assert all(isinstance(ln.placement, TrackPlacement) for ln in lines)
    assert [ln.placement.travel_shift for ln in lines] == [0.24, 0.24]
    assert rows[0].line is not None and rows[0].line.placement.travel_shift == 0.0  # untouched


def test_import_messages_follow_the_copy_in_order(tmp_path):
    bridged = make(tmp_path, "FILE__001.DZT", {75: 5})  # start 2.5 m, end 2.4 m, one bridge
    bare = synthetic_dzt(tmp_path, "FILE__002.DZT")
    rows = plan([bridged, bare])
    assert END_LIMIT_M == 2.0
    assert import_messages(rows, 1, into="G1", gid="G1") == [
        "imported 1 GPS line(s) into G1",
        "FILE__001.DZT: 10.0 m without an RTK fix, traces 25–125",
        "FILE__001.DZT: its start runs 2.5 m before the first RTK fix",
        "FILE__001.DZT: its end runs 2.4 m past the last RTK fix",
        "not imported: FILE__002.DZT (no DZG beside it)",
    ]


def test_an_end_run_within_the_limit_is_not_reported(tmp_path):
    path = synthetic_gps_dzt(
        tmp_path,
        "FILE__001.DZT",
        [fix(15), fix(185)],  # 1.5 m before, 1.4 m after
        traces_per_metre=10.0,
    )
    rows = plan([path])
    assert import_messages(rows, 1, into="G1", gid="G1") == ["imported 1 GPS line(s) into G1"]


def test_a_dzg_naming_a_trace_beyond_its_dzt_is_refused(tmp_path):
    # A DZG that belongs to another, longer file: a fix at trace 250 of 200.
    path = synthetic_gps_dzt(
        tmp_path,
        "FILE__001.DZT",
        [fix(25), fix(125), fix(250)],
        traces_per_metre=10.0,
    )
    (row,) = plan([path])
    assert row.line is None
    assert row.refusal is not None and row.refusal.startswith("could not read it: ")
    assert "names trace 250" in row.refusal and "200 traces" in row.refusal


def test_the_crs_is_asked_before_anything_is_projected(tmp_path):
    path = make(tmp_path, "FILE__001.DZT")

    def failing_to_xy(lon, lat):
        import numpy as np

        return np.full(len(lon), np.nan), np.full(len(lat), np.nan)

    (row,) = plan_gps_rows([path], failing_to_xy, CRS, never, lambda lon, lat: False)
    assert row.refusal == f"outside what {CRS} can place"


def test_count_with_gps_counts_the_files_whose_dzg_holds_an_rtk_fix(tmp_path):
    with_fix = make(tmp_path, "FILE__001.DZT")
    float_only = synthetic_gps_dzt(
        tmp_path, "FILE__002.DZT", [fix(t, 5) for t in (25, 75)], traces_per_metre=10.0
    )
    bare = synthetic_dzt(tmp_path, "FILE__003.DZT")
    assert count_with_gps([with_fix, float_only, bare]) == 1
    assert count_with_gps([with_fix, make(tmp_path, "FILE__004.DZT")]) == 2
    assert count_with_gps([]) == 0


def _grid_around(rows, gid="G1", pad=0.0, north=None):
    """A grid whose frame covers the rows' tracks (south-west corner at their
    minimum), `north` metres long when given."""
    import numpy as np

    pts = np.vstack([r.line.trace_coords({}) for r in rows if r.line is not None])
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    length = (hi[1] - lo[1]) if north is None else north
    return Grid(gid, (lo[0] - pad, lo[1]), 0.0, hi[0] - lo[0] + 2 * pad + 1.0, length, CRS, 0.5)


def test_with_grid_refuses_a_line_wholly_outside_and_reports_metres_past_the_end(tmp_path):
    inside = make(tmp_path, "FILE__001.DZT")
    rows = plan([inside])
    ys = rows[0].line.trace_coords({})[:, 1]
    full = float(ys.max() - ys.min())
    grid = _grid_around(rows, north=full - 3.0)  # the line runs 3 m past the grid's end
    kept, outside = with_grid(rows, grid)
    assert kept[0].refusal is None
    assert outside[inside] == pytest.approx(3.0, abs=0.2)

    far = Grid("G2", (grid.origin[0] + 500.0, grid.origin[1]), 0.0, 5.0, 40.0, CRS, 0.5)
    kept, outside = with_grid(rows, far)
    assert kept[0].refusal == OUTSIDE.format(gid="G2") == "outside G2"
    assert kept[0].line is None and outside == {}


def test_with_grid_leaves_refused_rows_alone(tmp_path):
    ok = make(tmp_path, "FILE__001.DZT")
    bare = synthetic_dzt(tmp_path, "FILE__002.DZT")
    rows = plan([ok, bare])
    kept, outside = with_grid(rows, _grid_around(rows[:1]))
    assert kept[1] is rows[1] and set(outside) == {ok}


def test_shifted_lines_can_set_the_grid(tmp_path):
    rows = plan([make(tmp_path, "FILE__001.DZT")])
    (line,) = shifted_lines(rows, 0.1, grid_id="G1")
    assert line.placement.grid_id == "G1" and line.placement.travel_shift == 0.1
    assert rows[0].line.placement.grid_id is None


def test_import_messages_name_a_new_grid_list_outside_metres_and_skip_handed_on(tmp_path):
    ok = make(tmp_path, "FILE__001.DZT")
    bare = synthetic_dzt(tmp_path, "FILE__002.DZT")
    other = synthetic_dzt(tmp_path, "FILE__003.DZT")
    rows = plan([ok, bare, other])
    into = "new grid G4 (4.0 × 20.0 m, spacing 0.50 m)"
    assert import_messages(rows, 1, into=into, gid="G4", outside={ok: 3.04}, handed_on=[bare]) == [
        "imported 1 GPS line(s) into new grid G4 (4.0 × 20.0 m, spacing 0.50 m)",
        "FILE__001.DZT: its start runs 2.5 m before the first RTK fix",
        "FILE__001.DZT: its end runs 2.4 m past the last RTK fix",
        "FILE__001.DZT: 3.0 m lies outside G4 and is left out of its slices",
        "not imported: FILE__003.DZT (no DZG beside it)",
    ]
    # an existing grid, and a stretch under 0.05 m is not worth a line
    assert import_messages(rows[:1], 1, into="G1", gid="G1", outside={ok: 0.04})[-1].startswith(
        "FILE__001"
    )
    assert "outside" not in " ".join(
        import_messages(rows[:1], 1, into="G1", gid="G1", outside={ok: 0.04})
    )
    assert "outside G1" in import_messages(rows[:1], 1, into="G1", gid="G1", outside={ok: 1.0})[-1]


def test_the_outside_warning_names_the_grid_whatever_its_name_looks_like(tmp_path):
    ok = make(tmp_path, "FILE__001.DZT")
    rows = plan([ok])
    into = "new grid North field (4.0 × 20.0 m, spacing 0.50 m)"
    out = import_messages(rows, 1, into=into, gid="North field", outside={ok: 2.0})
    assert out[-1] == "FILE__001.DZT: 2.0 m lies outside North field and is left out of its slices"
    out = import_messages(rows, 1, into="2", gid="2", outside={ok: 2.0})
    assert "lies outside 2 and" in out[-1]


def test_with_grid_reuses_measurements_it_is_given(tmp_path):
    ok = make(tmp_path, "FILE__001.DZT")
    rows = plan([ok])
    grid = _grid_around(rows)
    _, outside = with_grid(rows, grid, measured=({ok: 7.5}, {ok: True}))
    assert outside == {ok: 7.5}


# ---- the hand-on guess (M17b Task 6) -------------------------------------------
import numpy as np  # noqa: E402
from nsgeo_qgis.gps_import import TapeGuess, guess_tape_rows  # noqa: E402

G0 = Grid("G", (0.0, 0.0), 0.0, 10.0, 20.0, CRS, 0.5)
NAMES = [Path(f"FILE__{n}.DZT") for n in range(302, 312)]


def _along_y(x, up=True):
    ys = np.linspace(0, 20, 5)
    return np.column_stack([np.full(5, x), ys if up else ys[::-1]])


def _along_x(y, right=True):
    xs = np.linspace(0, 10, 5)
    return np.column_stack([xs if right else xs[::-1], np.full(5, y)])


def _line_set(skip, make_line=_along_y):
    """Ten files, offsets 0.25, 0.75, ..., zigzag; `skip` are the indices not placed."""
    placed = {
        p: make_line(0.25 + 0.5 * i, i % 2 == 0) for i, p in enumerate(NAMES) if i not in skip
    }
    return NAMES, placed


def test_a_gap_between_two_placed_lines_gets_the_midpoint_and_a_zigzag_direction():
    order, placed = _line_set({2})
    guess = guess_tape_rows(order, placed, G0)
    assert set(guess) == {NAMES[2]}
    g = guess[NAMES[2]]
    assert g == TapeGuess("y", pytest.approx(1.25), 1, "between FILE__303 and FILE__305")


def test_two_leftovers_in_a_row_interpolate_by_file_position():
    order, placed = _line_set({2, 3})
    guess = guess_tape_rows(order, placed, G0)
    assert guess[NAMES[2]].offset == pytest.approx(0.25 + 0.5 * 2)
    assert guess[NAMES[3]].offset == pytest.approx(0.25 + 0.5 * 3)
    assert [guess[NAMES[2]].direction, guess[NAMES[3]].direction] == [1, -1]


def test_a_leftover_after_the_last_placed_line_gets_one_spacing_on():
    order, placed = _line_set({9})
    g = guess_tape_rows(order, placed, G0)[NAMES[9]]
    assert g.offset == pytest.approx(0.25 + 0.5 * 8 + 0.5)
    assert g.note == "1 spacing after FILE__310"
    assert g.direction == -(1 if 8 % 2 == 0 else -1)


def test_further_files_on_get_a_spacing_each_and_the_plural_note():
    order, placed = _line_set({8, 9})
    guess = guess_tape_rows(order, placed, G0)
    assert guess[NAMES[9]].note == "2 spacings after FILE__309"
    assert guess[NAMES[9]].offset == pytest.approx(0.25 + 0.5 * 7 + 1.0)


def test_the_first_file_goes_one_spacing_before_and_opposite_its_follower():
    order, placed = _line_set({0})
    g = guess_tape_rows(order, placed, G0)[NAMES[0]]
    assert g.note == "1 spacing before FILE__303"
    assert g.offset == pytest.approx(0.25)  # the placed line at 0.75 minus one spacing
    assert g.direction == 1  # file 303 runs down (-1)


def test_one_placed_line_makes_the_end_guess_plus():
    order = NAMES[:2]
    placed = {NAMES[0]: _along_y(0.25)}
    g = guess_tape_rows(order, placed, G0)[NAMES[1]]
    assert g.offset == pytest.approx(0.75) and g.direction == -1


def test_neighbours_at_45_degrees_give_no_guess():
    diag = np.column_stack([np.linspace(0, 10, 5), np.linspace(0, 10, 5)])
    order = NAMES[:3]
    placed = {NAMES[0]: diag, NAMES[2]: diag + 1.0}
    assert guess_tape_rows(order, placed, G0) == {}


def test_lines_along_x_guess_axis_x_with_offsets_in_local_y():
    order, placed = _line_set({4}, _along_x)
    g = guess_tape_rows(order, placed, G0)[NAMES[4]]
    assert g.axis == "x"
    assert g.offset == pytest.approx(0.25 + 0.5 * 4)
    assert g.direction == 1


def test_a_diagonal_neighbour_leaves_every_leftover_that_leans_on_it_unguessed():
    diag = np.column_stack([np.linspace(0, 10, 5), np.linspace(0, 10, 5)])
    order = NAMES[:4]
    placed = {NAMES[0]: _along_y(0.25), NAMES[1]: diag}
    # files 2 and 3 both lean on the diagonal line 1 (and line 0): the axes disagree
    assert guess_tape_rows(order, placed, G0) == {}


G200 = Grid("R", (100.0, 200.0), 200.0, 10.0, 20.0, CRS, 0.5)


def _rotated(offset, up=True, length=20.0):
    """A line along local Y at local x = offset, in world coordinates of G200."""
    ys = np.linspace(0, length, 5)
    local = np.column_stack([np.full(5, offset), ys if up else ys[::-1]])
    return G200.to_world(local)


def _descending(skip):
    """Ten files numbered DOWN local X (offsets 9.75, 9.25, ...) on a rotated grid."""
    placed = {p: _rotated(9.75 - 0.5 * i, i % 2 == 0) for i, p in enumerate(NAMES) if i not in skip}
    return NAMES, placed


def test_files_numbered_down_the_grid_are_guessed_at_both_ends_and_between():
    order, placed = _descending({0, 4, 9})
    guess = guess_tape_rows(order, placed, G200)
    assert guess[NAMES[0]].offset == pytest.approx(9.75)  # one spacing before 9.25, away from 8.75
    assert guess[NAMES[0]].note == "1 spacing before FILE__303"
    assert guess[NAMES[4]].offset == pytest.approx(9.75 - 0.5 * 4)
    assert guess[NAMES[9]].offset == pytest.approx(9.75 - 0.5 * 9)  # 5.25, past 5.75 going down
    assert guess[NAMES[9]].note == "1 spacing after FILE__310"
    assert [guess[NAMES[i]].direction for i in (0, 4, 9)] == [1, 1, -1]


def test_the_end_guess_with_one_placed_line_steps_up_after_it_and_down_before_it():
    placed = {NAMES[1]: _along_y(5.0)}
    guess = guess_tape_rows(NAMES[:3], placed, G0)
    assert guess[NAMES[2]].offset == pytest.approx(5.5)
    assert guess[NAMES[0]].offset == pytest.approx(4.5)


def test_a_neighbour_under_a_metre_long_gives_no_guess():
    short = np.column_stack([np.full(3, 0.25), np.linspace(0.0, 0.5, 3)])
    placed = {NAMES[0]: short, NAMES[2]: _along_y(1.25)}
    assert guess_tape_rows(NAMES[:3], placed, G0) == {}


# ---- M21a: formats whose GPS log is not read yet (spec C10, §13) -------------


def test_a_dt1_is_refused_for_its_format_even_with_a_dzg_named_beside_it(tmp_path):
    p = synthetic_dt1(tmp_path, "LINE01.DT1", n_traces=200)
    write_dzg(p.with_suffix(".DZG"), [fix(25), fix(75), fix(125)])
    (row,) = plan([p])
    assert row.line is None and row.refusal == NO_GPS_FORMAT
    assert row.n_traces == 200 and row.n_fixes == 0  # the DZG was never read


def test_an_unreadable_dt1_is_refused_not_raised(tmp_path):
    p = synthetic_dt1(tmp_path, "LINE01.DT1")
    p.with_suffix(".HD").unlink()
    (row,) = plan([p])
    assert row.line is None and row.refusal == "could not read it: no LINE01.HD beside it"


def test_a_mala_line_is_refused_whatever_lies_beside_it(tmp_path):
    p = synthetic_mala(tmp_path, "DAT_0001.rd7", n_traces=200)
    p.with_suffix(".cor").write_text("1\t2024-01-01\t00:00:00\t0\tN\t0\tE\t0\tM\t1\n")
    write_dzg(p.with_suffix(".DZG"), [fix(25), fix(75), fix(125)])
    (row,) = plan([p])
    assert row.line is None and row.refusal == NO_GPS_FORMAT
    assert row.n_traces == 200 and row.n_fixes == 0


def test_a_segy_line_is_refused_though_its_traces_carry_the_geographic_flag(tmp_path):
    p = synthetic_segy(tmp_path, "LINE01.sgy", n_traces=200)
    write_dzg(p.with_suffix(".DZG"), [fix(25), fix(75), fix(125)])
    (row,) = plan([p])
    assert row.line is None and row.refusal == NO_GPS_FORMAT
    assert row.n_traces == 200 and row.n_fixes == 0
