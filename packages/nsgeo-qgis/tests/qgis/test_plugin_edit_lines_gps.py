"""M17b (#134): GPS lines are rows in Edit lines: Label, Destagger and Grid only."""

from __future__ import annotations

import nsgeo_qgis.destagger_job as job_module
import numpy as np
import pytest
from nsgeo.destagger import AxisResult, DestaggerResult, LineResult, LineStatus
from nsgeo.geometry import Grid, GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.edit_lines_dialog import (
    CHANGED,
    COL_ALONG,
    COL_DESTAGGER,
    COL_DIR,
    COL_LABEL,
    COL_LENGTH,
    COL_OFFSET,
    COL_PICKS,
    COL_SCALE,
    COL_START,
    COL_TRACES,
    GPS_SKIP,
    GPS_TIP,
    EditLinesDialog,
)
from plugin_testing import (
    CRS,
    LAT0,
    LON0,
    M_PER_DEG,
    open_gps,
    spin_until,
    synthetic_dzt,
    synthetic_gps_dzt,
)
from qgis.PyQt.QtCore import Qt

GA = Grid("A", (0.0, 0.0), 0.0, 10.0, 15.0, CRS, 0.5)
GB = Grid("B", (50.0, 0.0), 0.0, 8.0, 9.0, CRS, 0.5)
ORDER = ["T1", "G1", "T2", "G2", "T3"]
TAPES = ["T1", "T2", "T3"]
GPSES = ["G1", "G2"]


def _gps(folder, name, lon):
    path = synthetic_gps_dzt(
        folder,
        name,
        [(t, LAT0 + t * 0.1 / M_PER_DEG, lon, 4) for t in (25, 175)],
        n_traces=200,
        traces_per_metre=10.0,
    )
    return open_gps(path, grid_id="A")


def _tape(folder, name, i):
    p = synthetic_dzt(folder, name, n_traces=60)
    return Line.open(
        p,
        GridPlacement(
            "A", "y", 0.25 + 0.5 * i, 0.0 if i != 1 else 15.0, 1 if i != 1 else -1, f"tape {name}"
        ),
    )


@pytest.fixture
def mixed(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.set_site_crs(CRS)
    s.add_grid(GA)
    s.add_grid(GB)
    raw = tmp_path / "raw"
    s.add_lines(
        [
            _tape(raw, "T1.DZT", 0),
            _gps(raw, "G1.DZT", LON0),
            _tape(raw, "T2.DZT", 1),
            _gps(raw, "G2.DZT", LON0 + 0.5 / M_PER_DEG),
            _tape(raw, "T3.DZT", 2),
        ]
    )
    dialog = EditLinesDialog(s, "A")
    yield s, dialog
    dialog._measurer.shutdown()
    dialog.hide()
    dialog.deleteLater()


def _k(name):
    return f"raw/{name}.DZT"


def _keys(names):
    return [_k(n) for n in names]


def _cell(d, r, c):
    return d.table.item(r, c).text()


def _coords(s, name):
    return s.line_for_key(_k(name)).trace_coords(s.site.frames)


def test_the_table_lists_tape_and_gps_lines_in_survey_order(mixed):
    s, d = mixed
    assert d.keys() == _keys(ORDER)
    for r, name in enumerate(ORDER):
        if name in GPSES:
            for c in (COL_OFFSET, COL_DIR, COL_START, COL_SCALE):
                item = d.table.item(r, c)
                assert item.text() == "—"
                assert not item.flags() & Qt.ItemFlag.ItemIsEditable
                assert item.toolTip() == GPS_TIP
            assert _cell(d, r, COL_ALONG) == "GPS"
            assert _cell(d, r, COL_TRACES) == "200"
            assert float(_cell(d, r, COL_LENGTH)) == pytest.approx(
                s.line_for_key(d.keys()[r]).distance_along()[-1], abs=0.01
            )
            assert _cell(d, r, COL_PICKS) == "0"
        else:
            assert _cell(d, r, COL_ALONG) == "y"
            assert _cell(d, r, COL_OFFSET) != "—"
    assert GPS_TIP == (
        "A GPS line is placed by its track: Offset, Dir, Start and Scale do not apply."
    )


def test_label_and_destagger_of_a_gps_row_change_only_those(mixed):
    s, d = mixed
    key = _k("G1")
    before = _coords(s, "G1").copy()
    row = d.keys().index(key)
    d.table.item(row, COL_LABEL).setText("north walk")
    d.table.item(row, COL_DESTAGGER).setText("0.2")
    assert d.table.item(row, COL_DESTAGGER).background().color() == CHANGED
    assert d.status.text().startswith("1 line changed")
    d.accept()
    assert d.outcome.changed == (key,)
    p = s.line_for_key(key).placement
    assert (p.label, p.travel_shift, p.grid_id) == ("north walk", 0.2, "A")
    after = _coords(s, "G1")
    assert np.allclose(np.hypot(*(after - before).T), 0.2, atol=1e-3, rtol=0)  # along the track


def test_a_gps_row_moves_to_another_grid_with_its_track_unchanged(mixed):
    s, d = mixed
    key = _k("G2")
    before = _coords(s, "G2").copy()
    row = d.keys().index(key)
    d._combos[row].setCurrentText("B")
    assert d.edit_for(key).grid_id == "B"
    d.accept()
    assert s.line_for_key(key).placement.grid_id == "B"
    assert np.array_equal(_coords(s, "G2"), before)


def _select(d, names):
    d.select_keys(_keys(names))


@pytest.mark.parametrize(
    ("act", "what"),
    [
        (lambda d: d.shift_offset(0.5), "Offset"),
        (lambda d: d.flip(), "Dir"),
        (lambda d: d.set_start(2.0), "Start"),
        (lambda d: d.snap_to_edge(), "Start"),
        (lambda d: d.set_scale(1.1), "Scale"),
        (lambda d: d.fit_to_edges(), "Fit to grid edges"),
    ],
)
def test_tape_only_bulk_changes_leave_a_gps_row_alone_and_say_so(mixed, act, what):
    s, d = mixed
    seen = {k: d.edit_for(k) for k in _keys(ORDER)}
    _select(d, ["T1", "G1", "T2"])
    act(d)
    assert d.status.text() == GPS_SKIP.format(n=1, what=what)
    assert d.edit_for(_k("G1")) == seen[_k("G1")]
    assert d.edit_for(_k("T3")) == seen[_k("T3")]


def test_bulk_offset_changes_the_tapes_and_names_the_skip(mixed):
    s, d = mixed
    _select(d, ["T1", "G1", "T2"])
    d.shift_offset(0.5)
    assert d.status.text() == GPS_SKIP.format(n=1, what="Offset")
    assert [d.edit_for(_k(n)).offset for n in ("T1", "T2")] == [0.75, 1.25]
    assert d.edit_for(_k("G1")).label is None
    assert GPS_SKIP == "Left {n} GPS line(s) alone: {what} applies to tape lines only."


def test_no_note_when_no_gps_row_is_selected(mixed):
    s, d = mixed
    _select(d, ["T1", "T2"])
    d.shift_offset(0.5)
    assert "GPS" not in d.status.text()


def test_bulk_destagger_and_move_apply_to_every_selected_row(mixed):
    s, d = mixed
    _select(d, ["T1", "G1", "T2"])
    d.set_destagger(0.1)
    d.move_to("B")
    d.accept()
    for name in ("T1", "G1", "T2"):
        p = s.line_for_key(_k(name)).placement
        assert p.grid_id == "B" and p.travel_shift == pytest.approx(0.1)
    assert s.line_for_key(_k("T3")).placement.grid_id == "A"


def test_moving_a_gps_row_up_and_down_changes_the_survey_order(mixed):
    s, d = mixed
    _select(d, ["G1"])
    d.move_selected(1)
    assert d.keys() == _keys(["T1", "T2", "G1", "G2", "T3"])
    _select(d, ["G2"])
    d.move_selected(-1)
    assert d.keys() == _keys(["T1", "T2", "G2", "G1", "T3"])
    d.accept()
    assert s.keys_on_grid("A") == _keys(["T1", "T2", "G2", "G1", "T3"])


class Canned:
    def __init__(self):
        self.seen = []

    def __call__(self, lines, should_stop):
        self.seen.append([ln.key for ln in lines])
        results = {ln.key: LineResult(ln.key, "y", LineStatus.GRID, 0.12) for ln in lines}
        return DestaggerResult({"y": AxisResult("y", 0.12, 0.01, len(lines))}, results)


def test_measure_reads_the_tape_rows_only_and_names_the_gps_skip(mixed, monkeypatch):
    s, d = mixed
    canned = Canned()
    monkeypatch.setattr(job_module, "measure_destagger", canned)
    _select(d, ["T1", "G1", "T2"])
    d.measure()
    assert GPS_SKIP.format(n=1, what="Measure") in d.status.text()
    assert spin_until(lambda: not d._measurer.busy)
    assert canned.seen == [_keys(TAPES)]
    assert d.edit_for(_k("T1")).travel_shift == 0.12
    assert d.edit_for(_k("G1")).travel_shift is None
    assert GPS_SKIP.format(n=1, what="Measure") in d.status.text()


def test_measure_with_only_gps_rows_selected_starts_nothing(mixed, monkeypatch):
    s, d = mixed
    canned = Canned()
    monkeypatch.setattr(job_module, "measure_destagger", canned)
    _select(d, ["G1", "G2"])
    d.measure()
    assert GPS_SKIP.format(n=2, what="Measure") in d.status.text()
    assert not d._measurer.busy and canned.seen == []


def test_a_destagger_set_elsewhere_skips_that_row_and_applies_the_rest(mixed):
    s, d = mixed
    g1, t1 = _k("G1"), _k("T1")
    d.edit_for(g1)  # present
    row = d.keys().index(g1)
    d.table.item(row, COL_LABEL).setText("renamed")
    _select(d, ["T1"])
    d.set_destagger(0.3)
    s.set_travel_shift([g1], 0.2)
    d.accept()
    assert d.outcome.changed == (t1,)
    assert [x.key for x in d.outcome.skipped] == [g1]
    assert "G1 changed elsewhere" in d.outcome.message()
    assert s.line_for_key(g1).placement.label != "renamed"
    assert s.line_for_key(t1).placement.travel_shift == pytest.approx(0.3)
