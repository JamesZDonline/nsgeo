"""Measure in Edit lines (#159): the dialog's wiring around the core measurement.

Most tests replace `measure_destagger` in `nsgeo_qgis.destagger_job` with a
canned function that records what it was given and can block on an event, so
the dialog's handling of a run in flight is tested without the cost or the
luck of real data. The tests that need the real measurement say so.
"""

from __future__ import annotations

import threading

import nsgeo_qgis.destagger_job as job_module
import numpy as np
import pytest
from nsgeo.destagger import (
    AxisResult,
    DestaggerResult,
    LineResult,
    LineStatus,
    MeasureLine,
)
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.destagger_job import box_value, measure_summary
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.edit_lines_dialog import (
    CHANGED,
    COL_DESTAGGER,
    COL_START,
    MEASURE_DISCARDED,
    MEASURE_SITE_CHANGED,
    MEASURE_STOPPED,
    EditLinesDialog,
)
from plugin_testing import synthetic_dzt
from tests.real_data import GPS_LINES

GRID5 = Grid("Grid5", (500.0, 700.0), 0.0, 15.0, 15.0, "EPSG:32616", 0.5)
GRID_B = Grid("B", (600.0, 700.0), 0.0, 10.0, 9.0, "EPSG:32616", 0.5)
N_LINES = 6
LONG = 480  # 8 m at 60 traces/m: long enough that the end trims leave something


def spin_until(predicate, timeout_ms: int = 20_000) -> bool:
    from plugin_testing import spin_until as spin

    return spin(predicate, timeout_ms)


def _shared_field_dzt(folder, name, backward, n_traces=LONG):
    """A line whose traces come from one field over the grid, so lines walked
    opposite ways see the same features at the same places."""
    from tests.synthetic import write_dzt

    rng = np.random.default_rng(7)  # the same field for every line
    cells = rng.normal(size=(n_traces // 6, 512))
    field = np.repeat(cells, 6, axis=0).T  # (512, n_traces)
    noise = np.random.default_rng(abs(hash(name)) % 1000 + 1).normal(size=field.shape) * 0.05
    data = field + noise
    if backward:
        data = data[:, ::-1]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    write_dzt(path, (data * 1e6).astype(np.int32))
    return path


def _open(tmp_path, long=False, shape=None):
    """A site with six lines on Grid5 (and a second grid)."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID5)
    session.add_grid(GRID_B)
    lines = []
    for i in range(N_LINES):
        d, start = shape[i] if shape else ((1, 0.0) if i % 2 == 0 else (-1, 8.0))
        if long:
            path = _shared_field_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", d == -1)
        else:
            path = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        placement = GridPlacement("Grid5", "y", 0.25 + 0.5 * i, start, d, f"line {i + 1}")
        lines.append(Line.open(path, placement))
    session.add_lines(lines)
    return session


class Canned:
    """A stand-in for `measure_destagger`."""

    def __init__(self, values=None, gate=False, axes=None):
        self.values = values
        self.axes = axes
        self.gate = threading.Event() if gate else None
        self.seen: list[list[MeasureLine]] = []
        self.result: DestaggerResult | None = None

    def release(self):
        if self.gate is not None:
            self.gate.set()

    def __call__(self, lines, should_stop):
        self.seen.append(list(lines))
        if self.gate is not None:
            assert self.gate.wait(30), "the test never released the measure"
        results = {}
        for i, line in enumerate(lines):
            axis = line.placement.axis
            if self.values is not None and i in self.values:
                status, value = self.values[i]
            else:
                status, value = LineStatus.GRID, 0.12
            results[line.key] = LineResult(line.key, axis, status, value)
        axes = self.axes or {"y": AxisResult("y", 0.12, 0.011, len(lines))}
        self.result = DestaggerResult(dict(axes), results)
        return self.result


@pytest.fixture
def make(qgis_app, tmp_path, monkeypatch):
    made: list = []

    def _make(canned=None, **kw):
        session = _open(tmp_path, **kw)
        if canned is not None:
            monkeypatch.setattr(job_module, "measure_destagger", canned)
        dialog = EditLinesDialog(session, "Grid5")
        made.append((dialog, canned))
        return session, dialog

    yield _make
    for dialog, canned in made:
        if canned is not None:
            canned.release()
        dialog._measurer.shutdown()
        dialog.hide()
        dialog.deleteLater()


def _finish(dialog):
    assert spin_until(lambda: not dialog._measurer.busy)


def _shift(dialog, row):
    return dialog.edit_for(dialog.keys()[row]).travel_shift


def _refine_threads():
    return sum(t.name.startswith("nsgeo-refine") for t in threading.enumerate())


def test_measure_fills_the_selected_rows_and_the_box(make):
    canned = Canned({1: (LineStatus.OWN, 0.25)})
    session, dialog = make(canned)
    keys = dialog.keys()
    dialog.select_keys(keys[:4])
    dialog.measure()
    _finish(dialog)
    assert [_shift(dialog, r) for r in range(6)] == [0.12, 0.25, 0.12, 0.12, None, None]
    shaded = [dialog.table.item(r, COL_DESTAGGER).background().color() == CHANGED for r in range(6)]
    assert shaded == [True] * 4 + [False] * 2
    assert dialog.destagger_spin.value() == pytest.approx(0.12)
    labels = {k: f"line {i + 1}" for i, k in enumerate(keys)}
    assert dialog.status.text() == measure_summary(canned.result, keys[:4], {}, labels)
    assert "Own values: line 2 +0.250." in dialog.status.text()
    assert dialog.measure_button.text() == "Measure"
    assert len(canned.seen[0]) == N_LINES  # the whole grid is measured, four rows are filled


def test_measure_uses_the_tables_pending_placement(make):
    canned = Canned()
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.fit_to_edges()
    frames = session.site.frames
    keys = dialog.keys()
    expected = [dialog.edit_for(k).placed(frames).scale for k in keys]
    assert expected[0] > 1.5
    dialog.measure()
    _finish(dialog)
    assert [ln.placement.scale for ln in canned.seen[0]] == pytest.approx(expected)


def test_an_edit_while_measuring_discards_the_results(make):
    canned = Canned(gate=True)
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    assert spin_until(lambda: bool(canned.seen))
    dialog.table.item(2, COL_START).setText("1.5")
    canned.release()
    _finish(dialog)
    assert [_shift(dialog, r) for r in range(6)] == [None] * 6
    assert dialog.status.text() == MEASURE_DISCARDED


def test_a_destagger_edit_while_measuring_does_not_discard(make):
    canned = Canned(gate=True)
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    assert spin_until(lambda: bool(canned.seen))
    dialog.table.item(2, COL_DESTAGGER).setText("0.5")
    canned.release()
    _finish(dialog)
    assert [_shift(dialog, r) for r in range(6)] == [0.12] * 6
    assert dialog.status.text().startswith("Measured +0.120 m")


def test_stop_changes_nothing(make):
    canned = Canned(gate=True)
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    assert dialog.measure_button.text() == "Stop"
    assert spin_until(lambda: bool(canned.seen))  # the worker is inside the measure
    dialog.measure()
    assert dialog.measure_button.text() == "Measure"
    assert dialog.status.text() == MEASURE_STOPPED
    canned.release()
    assert spin_until(lambda: canned.result is not None)
    spin_until(lambda: False, 300)  # let any wrongly queued result land
    assert [_shift(dialog, r) for r in range(6)] == [None] * 6
    assert dialog.status.text() == MEASURE_STOPPED
    assert dialog.destagger_spin.value() == 0.0


def test_closing_the_dialog_stops_the_measure(make):
    canned = Canned(gate=True)
    before = _refine_threads()
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    assert spin_until(lambda: bool(canned.seen))
    canned.release()  # shutdown joins the worker, which must be able to end
    dialog.reject()
    assert _refine_threads() == before
    spin_until(lambda: False, 300)
    assert [_shift(dialog, r) for r in range(6)] == [None] * 6
    assert dialog.status.text() != MEASURE_DISCARDED
    assert "Measured" not in dialog.status.text()


def test_stop_stays_reachable_when_the_selection_is_cleared(make):
    canned = Canned(gate=True)
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    dialog.table.clearSelection()
    assert dialog.bulk.isEnabled()
    assert dialog.measure_button.text() == "Stop"
    dialog.measure()
    assert dialog.status.text() == MEASURE_STOPPED
    assert not dialog.bulk.isEnabled()  # nothing selected, nothing running


def test_a_site_closed_while_measuring_is_not_written_to(make):
    canned = Canned(gate=True)
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    assert spin_until(lambda: bool(canned.seen))
    session.close_site()
    canned.release()
    _finish(dialog)
    assert dialog.status.text() == MEASURE_SITE_CHANGED
    assert [_shift(dialog, r) for r in range(6)] == [None] * 6


def test_an_unreadable_line_is_named_and_the_rest_are_measured(make):
    session, dialog = make(long=True)
    keys = dialog.keys()
    session.line_for_key(keys[2]).path.unlink()
    dialog.select_keys(keys)
    dialog.measure()
    _finish(dialog)
    assert "could not be read:" in dialog.status.text()
    assert "line 3" in dialog.status.text()
    assert _shift(dialog, 2) is None
    filled = [_shift(dialog, r) is not None for r in range(6)]
    assert filled == [True, True, False, True, True, True]


def test_a_row_moved_to_another_grid_is_left_out(make):
    canned = Canned()
    session, dialog = make(canned)
    keys = dialog.keys()
    dialog._combos[2].setCurrentText("B")
    dialog.select_keys(keys)
    dialog.measure()
    _finish(dialog)
    given = [ln.key for ln in canned.seen[0]]
    assert keys[2] not in given
    assert len(given) == N_LINES - 1
    assert _shift(dialog, 2) is None
    assert [_shift(dialog, r) for r in (0, 1, 3, 4, 5)] == [0.12] * 5


def test_measuring_twice_reads_each_file_once_and_gives_the_same_values(make, monkeypatch):
    calls: list = []
    real = job_module.read_samples

    def counting(path, header=None):
        calls.append(path)
        return real(path, header)

    monkeypatch.setattr(job_module, "read_samples", counting)
    session, dialog = make(long=True)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    _finish(dialog)
    first = [_shift(dialog, r) for r in range(6)]
    box = dialog.destagger_spin.value()
    assert all(v is not None for v in first), dialog.status.text()
    dialog.measure()
    _finish(dialog)
    assert len(calls) == N_LINES
    assert [_shift(dialog, r) for r in range(6)] == first
    assert dialog.destagger_spin.value() == box


def test_a_one_way_grid_says_there_is_nothing_to_measure(make):
    session, dialog = make(long=True, shape=[(1, 0.0)] * N_LINES)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    _finish(dialog)
    assert dialog.status.text() == (
        "Could not measure: every line was walked the same way, so there is no stagger "
        "to measure. Nothing was changed."
    )
    assert [_shift(dialog, r) for r in range(6)] == [None] * 6


def test_two_axes_fill_each_row_from_its_own_axis(make, tmp_path, monkeypatch):
    def run(lines, should_stop):
        results = {
            ln.key: LineResult(
                ln.key,
                ln.placement.axis,
                LineStatus.GRID,
                0.30 if ln.placement.axis == "x" else 0.10,
            )
            for ln in lines
        }
        axes = {
            "x": AxisResult("x", 0.30, 0.02, 3),
            "y": AxisResult("y", 0.10, 0.01, 4),
        }
        return DestaggerResult(axes, results)

    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID5)
    lines = []
    for i in range(N_LINES):
        axis = "x" if i < 2 else "y"
        path = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(
            Line.open(path, GridPlacement("Grid5", axis, 0.25 + 0.5 * i, 0.0, 1, f"line {i + 1}"))
        )
    session.add_lines(lines)
    monkeypatch.setattr(job_module, "measure_destagger", run)
    dialog = EditLinesDialog(session, "Grid5")
    try:
        dialog.select_keys(dialog.keys())
        dialog.measure()
        _finish(dialog)
        assert [_shift(dialog, r) for r in range(6)] == [0.30, 0.30, 0.10, 0.10, 0.10, 0.10]
        assert dialog.destagger_spin.value() == pytest.approx(0.10)  # y has more lines (C11)
        assert dialog.status.text().startswith("Along x: measured +0.300 m from 3 lines")
        assert box_value(DestaggerResult({"x": AxisResult("x", 0.3, 0.0, 3)}, {})) == 0.3
    finally:
        dialog._measurer.shutdown()
        dialog.hide()
        dialog.deleteLater()


@pytest.mark.skipif(len(GPS_LINES) != 60, reason="needs Grid 1 in tests/data/local/with-dzg")
def test_measure_on_the_real_survey(qgis_app, tmp_path):
    length = 29.98  # the saved survey's length, not a rounded 30 m
    grid = Grid("G", (500.0, 700.0), 0.0, 30.0, length, "EPSG:32616", 0.5)
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(grid)
    lines = []
    for k, path in enumerate(GPS_LINES):
        forward = k % 2 == 0
        placement = GridPlacement(
            "G", "y", 0.25 + 0.5 * k, 0.0 if forward else length, 1 if forward else -1, f"l{k}"
        )
        lines.append(Line.open(path, placement))
    session.add_lines(lines)
    dialog = EditLinesDialog(session, "G")
    try:
        dialog.table.selectAll()
        dialog.measure()
        assert spin_until(lambda: not dialog._measurer.busy, 120_000), dialog.status.text()
        assert dialog.destagger_spin.value() == pytest.approx(0.15, abs=0.02), dialog.status.text()
        assert all(_shift(dialog, r) is not None for r in range(60))
    finally:
        dialog._measurer.shutdown()
        dialog.hide()
        dialog.deleteLater()
