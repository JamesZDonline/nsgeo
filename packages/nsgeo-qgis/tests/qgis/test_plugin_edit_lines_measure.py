"""Measure in Edit lines (#159): the dialog's wiring around the core measurement.

Most tests replace `measure_destagger` in `nsgeo_qgis.destagger_job` with a
canned function that records what it was given and can block on an event, so
the dialog's handling of a run in flight is tested without the cost or the
luck of real data. The tests that need the real measurement say so.
"""

from __future__ import annotations

import threading
import time

import nsgeo_qgis.destagger_job as job_module
import numpy as np
import pytest
from nsgeo.destagger import (
    AxisResult,
    DestaggerResult,
    LineResult,
    LineStatus,
    MeasureLine,
    MeasureStopped,
)
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.destagger_job import measure_summary
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.edit_lines_dialog import (
    CHANGED,
    COL_DESTAGGER,
    COL_START,
    MEASURE_DISCARDED,
    MEASURE_NO_TARGETS,
    MEASURE_SITE_CHANGED,
    MEASURE_STOPPED,
    EditLinesDialog,
)
from plugin_testing import spin_until, synthetic_dzt
from tests.real_data import GPS_LINES

GRID5 = Grid("Grid5", (500.0, 700.0), 0.0, 15.0, 15.0, "EPSG:32616", 0.5)
GRID_B = Grid("B", (600.0, 700.0), 0.0, 10.0, 9.0, "EPSG:32616", 0.5)
N_LINES = 6
LONG = 480  # 8 m at 60 traces/m: long enough that the end trims leave something


STAGGER_TRACES = 9  # 0.15 m at 60 traces/m, injected into every shared-field line


def _shared_field_dzt(folder, name, backward, index, n_traces=LONG):
    """A line whose traces come from one field over the grid, so lines walked
    opposite ways see the same features at the same places, except that each
    is displaced `STAGGER_TRACES` along its own direction of travel: the
    stagger the measurement should find. The destagger that cancels it is
    about -0.15 (features sit ahead along travel, so the shift is negative)."""
    from tests.synthetic import write_dzt

    rng = np.random.default_rng(7)  # the same field for every line
    cells = rng.normal(size=(n_traces // 6, 512))
    field = np.repeat(cells, 6, axis=0).T  # (512, n_traces), in grid order
    noise = np.random.default_rng(100 + index).normal(size=field.shape) * 0.05
    # Recorded order: a backward line is read from the far end.
    data = np.roll(field, STAGGER_TRACES, axis=1) + noise
    if backward:
        data = np.roll(field, -STAGGER_TRACES, axis=1)[:, ::-1] + noise
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    write_dzt(path, (data * 1e6).astype(np.int32))
    return path


def _open(tmp_path, long=False, shape=None, axes=None, n=N_LINES):
    """A site with six lines on Grid5 (and a second grid)."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID5)
    session.add_grid(GRID_B)
    lines = []
    for i in range(n):
        d, start = shape[i] if shape else ((1, 0.0) if i % 2 == 0 else (-1, 8.0))
        if long:
            path = _shared_field_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", d == -1, i)
        else:
            path = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        axis = axes[i] if axes else "y"
        placement = GridPlacement("Grid5", axis, 0.25 + 0.5 * i, start, d, f"line {i + 1}")
        lines.append(Line.open(path, placement))
    session.add_lines(lines)
    return session


class Canned:
    """A stand-in for `measure_destagger`."""

    def __init__(self, values=None, gate=False, axes=None, loop=False, boom=None):
        self.values = values
        self.loop = loop
        self.boom = boom
        self.stopped_by_request = False
        self.axes = axes
        self.gate = threading.Event() if gate else None
        self.seen: list[list[MeasureLine]] = []
        self.result: DestaggerResult | None = None

    def release(self):
        if self.gate is not None:
            self.gate.set()

    def __call__(self, lines, should_stop):
        self.seen.append(list(lines))
        if self.boom is not None:
            raise self.boom
        if self.loop:  # runs until it is asked to stop, like a long measure
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if should_stop():
                    self.stopped_by_request = True
                    raise MeasureStopped()
                time.sleep(0.005)
            raise AssertionError("the measure was never asked to stop")
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
    canned = Canned(loop=True)  # never ends unless asked: reject() must cancel it
    before = _refine_threads()
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    assert spin_until(lambda: bool(canned.seen))
    dialog.reject()
    assert canned.stopped_by_request
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
    # -0.15 cancels the injected stagger; the 1/120 m placement offset makes it -0.142.
    assert box == pytest.approx(-0.142, abs=0.02), dialog.status.text()
    assert first == pytest.approx([box] * N_LINES, abs=0.02)
    dialog.measure()
    _finish(dialog)
    assert len(calls) == N_LINES
    assert [_shift(dialog, r) for r in range(6)] == first
    assert dialog.destagger_spin.value() == box


def test_a_one_way_grid_says_there_is_nothing_to_measure(make, monkeypatch):
    calls: list = []
    real = job_module.read_samples

    def counting(path, header=None):
        calls.append(path)
        return real(path, header)

    monkeypatch.setattr(job_module, "read_samples", counting)
    session, dialog = make(long=True, shape=[(1, 0.0)] * N_LINES)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    _finish(dialog)
    assert dialog.status.text() == (
        "Could not measure: every line was walked the same way, so there is no stagger "
        "to measure. Nothing was changed."
    )
    assert [_shift(dialog, r) for r in range(6)] == [None] * 6
    assert calls == []  # known from the directions alone, so no file is read (D1)


def test_two_axes_fill_each_row_from_its_own_axis(qgis_app, tmp_path, monkeypatch):
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

    session = _open(tmp_path, axes=["x", "x", "y", "y", "y", "y"])
    monkeypatch.setattr(job_module, "measure_destagger", run)
    dialog = EditLinesDialog(session, "Grid5")
    try:
        dialog.select_keys(dialog.keys())
        dialog.measure()
        _finish(dialog)
        assert [_shift(dialog, r) for r in range(6)] == [0.30, 0.30, 0.10, 0.10, 0.10, 0.10]
        assert dialog.destagger_spin.value() == pytest.approx(0.10)  # y has more lines (C11)
        assert dialog.status.text().startswith("Along x: measured +0.300 m from 3 lines")
    finally:
        dialog._measurer.shutdown()
        dialog.hide()
        dialog.deleteLater()


def test_results_land_in_the_rows_selected_when_measure_was_pressed(make):
    canned = Canned({1: (LineStatus.OWN, 0.25)}, gate=True)
    session, dialog = make(canned)
    keys = dialog.keys()
    dialog.select_keys(keys[:4])
    dialog.measure()
    assert spin_until(lambda: bool(canned.seen))
    dialog.table.clearSelection()
    dialog.select_keys(keys[4:])
    canned.release()
    _finish(dialog)
    assert [_shift(dialog, r) for r in range(6)] == [0.12, 0.25, 0.12, 0.12, None, None]
    assert dialog.selected_keys() == keys[4:]


def test_values_are_rounded_to_the_boxs_precision(make):
    axes = {"y": AxisResult("y", 0.12345, 0.011, 6)}
    canned = Canned({0: (LineStatus.OWN, 0.12345)}, axes=axes)
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    _finish(dialog)
    assert _shift(dialog, 0) == 0.123
    assert dialog.destagger_spin.value() == 0.123


def test_an_error_in_the_measure_is_reported_and_changes_nothing(make):
    canned = Canned(boom=RuntimeError("boom"))
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    _finish(dialog)
    assert dialog.status.text() == "Could not measure: RuntimeError: boom. Nothing was changed."
    assert dialog.measure_button.text() == "Measure"
    assert [_shift(dialog, r) for r in range(6)] == [None] * 6


def test_measure_with_nothing_selected_says_what_to_do(make):
    canned = Canned()
    session, dialog = make(canned)
    dialog.table.clearSelection()
    dialog.measure()
    assert dialog.status.text() == MEASURE_NO_TARGETS
    assert not dialog._measurer.busy
    assert canned.seen == []


def test_progress_names_the_lines_read_and_then_the_comparison(make, monkeypatch):
    read_gate = threading.Event()
    reads: list = []
    real = job_module.read_samples

    def gated(path, header=None):
        reads.append(path)
        if len(reads) == 3:
            assert read_gate.wait(30), "the test never released the read"
        return real(path, header)

    monkeypatch.setattr(job_module, "read_samples", gated)
    canned = Canned(gate=True)
    session, dialog = make(canned)
    try:
        dialog.select_keys(dialog.keys())
        dialog.measure()
        assert spin_until(lambda: dialog.status.text() == "Measuring… read 2 of 6 lines")
        read_gate.set()
        assert spin_until(lambda: bool(canned.seen))  # progress is (6, 6) before this
        assert spin_until(lambda: dialog.status.text() == "Measuring… comparing lines")
    finally:
        read_gate.set()


def test_a_site_replaced_while_measuring_is_not_written_to(make, tmp_path):
    canned = Canned(gate=True)
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    assert spin_until(lambda: bool(canned.seen))
    session.close_site()
    (tmp_path / "other").mkdir()
    session.new_site(tmp_path / "other")
    canned.release()
    _finish(dialog)
    assert dialog.status.text() == MEASURE_SITE_CHANGED
    assert [_shift(dialog, r) for r in range(6)] == [None] * 6


def test_the_same_site_reopened_while_measuring_is_still_a_new_site(make):
    canned = Canned(gate=True)
    session, dialog = make(canned)
    session.save()
    json_path = session.json_path
    dialog.select_keys(dialog.keys())
    dialog.measure()
    assert spin_until(lambda: bool(canned.seen))
    session.close_site()
    session.open_site(json_path)
    assert session.json_path == json_path  # a path check would pass this
    canned.release()
    _finish(dialog)
    assert dialog.status.text() == MEASURE_SITE_CHANGED
    assert [_shift(dialog, r) for r in range(6)] == [None] * 6


def test_measure_with_every_selected_row_on_another_grid_starts_nothing(make):
    canned = Canned()
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    dialog.move_to("B")
    dialog.select_keys(dialog.keys())
    keys = dialog.keys()
    before = [dialog.edit_for(k) for k in keys]
    dialog.measure()
    assert not dialog._measurer.busy
    assert dialog.status.text() == MEASURE_NO_TARGETS
    assert canned.seen == []
    assert [dialog.edit_for(k) for k in keys] == before


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
    before = dialog.minimumSizeHint().width()
    try:
        dialog.table.selectAll()
        dialog.measure()
        assert spin_until(lambda: not dialog._measurer.busy, 120_000), dialog.status.text()
        assert dialog.destagger_spin.value() == pytest.approx(0.15, abs=0.02), dialog.status.text()
        assert all(_shift(dialog, r) is not None for r in range(60))
        assert dialog.minimumSizeHint().width() <= before  # the long summary wraps (A2)
    finally:
        dialog._measurer.shutdown()
        dialog.hide()
        dialog.deleteLater()


def test_a_long_summary_wraps_instead_of_widening_the_dialog(make):
    """The walkthrough's summary on a real grid pushed OK off the screen (A2)."""
    values = {i: (LineStatus.OWN, 0.2 + i / 100) for i in range(8)}
    session, dialog = make(Canned(values), n=8)
    before = dialog.minimumSizeHint().width()
    dialog.select_keys(dialog.keys())
    dialog.measure()
    _finish(dialog)
    assert len(dialog.status.text()) > 120
    assert dialog.minimumSizeHint().width() <= before


def test_the_tooltip_names_every_line_the_status_caps(make):
    values = {i: (LineStatus.OWN, 0.2 + i / 100) for i in range(8)}
    session, dialog = make(Canned(values), n=8)
    dialog.select_keys(dialog.keys())
    dialog.measure()
    _finish(dialog)
    assert "and 2 more" in dialog.status.text()
    assert "line 8 +0.270" not in dialog.status.text()
    tip = dialog.status.toolTip()
    assert "more" not in tip
    assert "line 7 +0.260, line 8 +0.270." in tip
    dialog.set_destagger(0.5)  # any other status text carries no tooltip
    assert dialog.status.toolTip() == ""


def test_a_dialog_for_a_closed_site_does_not_measure_another(make, tmp_path):
    canned = Canned()
    session, dialog = make(canned)
    dialog.select_keys(dialog.keys())
    session.close_site()
    (tmp_path / "other").mkdir()
    session.new_site(tmp_path / "other")
    dialog.measure()
    assert dialog.status.text() == (
        "a different site was opened while the table was open; nothing was changed"
    )
    assert not dialog._measurer.busy
    assert canned.seen == []
    assert [_shift(dialog, r) for r in range(6)] == [None] * 6
