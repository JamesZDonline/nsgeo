"""Planning an Import GPS lines table without Qt or qgis (M17a Task 4, #134)."""

from __future__ import annotations

from pathlib import Path

import pytest
from nsgeo.geometry import END_LIMIT_M, TrackPlacement
from nsgeo_qgis.gps_import import (
    first_fixed_lonlat,
    import_messages,
    plan_gps_rows,
    shifted_lines,
)
from plugin_testing import synthetic_dzt, synthetic_gps_dzt
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
    assert row.refusal == "already in the site (remove it first to place it by GPS)"
    assert row.line is None


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
    assert import_messages(rows, 1) == [
        "imported 1 GPS line(s)",
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
    assert import_messages(rows, 1) == ["imported 1 GPS line(s)"]
