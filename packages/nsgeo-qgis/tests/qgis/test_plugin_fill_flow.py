"""This grid's fill and stretch worked out in the background, with Cancel (#193).

The dock on a synthetic grid at a cell fine enough that the interpolation fill
takes seconds. `SLOW_CELL` is calibrated once (`_assert_slow`) so the hazard
cannot silently shrink. CI's runners build the same fill in 0.65 to 0.47 of this
machine's time (QGIS 4.2 ran at 0.47 once), so the cells are chosen for 0.47.
Measured here for one grid's fill: 0.022 m 0.85 s, 0.018 m 1.64 s, 0.016 m
2.5 s, 0.015 m 3.2 s. `SLOW_CELL` 0.015 m: 3.2 s here, about 1.5 s on CI, over
the 1.0 s floor (`MIN_SLOW_S`, 3.3 times the 0.3 s gap limit). `MID_CELL`
0.018 m: 1.6 s here, about 0.77 s on CI, over twice the 0.2 s budget (0.4 s)
with margin.
"""

from __future__ import annotations

import sys
import threading
import time

import numpy as np
import pytest
from nsgeo.render import PercentileClip, UnipolarClip
from nsgeo_qgis.fill_jobs import FillJob, FootprintJob
from nsgeo_qgis.slices_plan import (
    FILL_BUDGET_S,
    FILL_CANCELLED_NOTE,
    FILL_WORKING_GRIDS_INDICATOR,
    FILL_WORKING_INDICATOR,
    FOOTPRINT_WORKING_INDICATOR,
    STRETCH_WORKING_INDICATOR,
    Resolution,
    SliceFinish,
)
from nsgeo_qgis.stretch_jobs import StretchJob
from nsgeo_qgis.ui.site_scope import levels as site_levels
from nsgeo_qgis.ui.warnings_panel import NOTE
from plugin_testing import (
    LayoutProbe,
    connect_message_log,
    layout_width,
    slow_jobs,
    spin_until,
    wait_for_site,
)
from qgis.PyQt.QtCore import QCoreApplication, Qt, QTimer
from qgis.PyQt.QtWidgets import QMessageBox
from test_plugin_site_scope import _close, _open, _wait_for_refine, whole_site
from test_plugin_slices_dock import (  # noqa: F401 -- fixture
    PRESET,
    _docked_with,
    _ready,
    _set_finish,
    docked,
)

SLOW_CELL = 0.015
QUICK_CELL = 0.1
MID_CELL = 0.018
MIN_SLOW_S = 1.0
#: Whole site: the cell at which the three grids' fills together take about
#: 4.4 s here (CI at 0.47 of that, 2.1 s, about 0.7 s a grid against the 0.3 s
#: gap limit). Measured per cell: 0.08 m 1.0 s, 0.06 m 2.5 s, 0.05 m 4.4 s, in
#: the three grids' sum.
SITE_SLOW_CELL = 0.05
#: The floor: 3.3 times the gap limit, as MIN_SLOW_S.
MIN_SLOW_SITE_S = 1.0
#: The spec says "about 250 ms". The edit's own `FillFlow.request` waits its 0.2 s
#: budget on the GUI thread, which the gap timer sees (0.203 s measured), so the
#: limit is 0.3 s: 100 ms of slack instead of 47. The inline freeze it must catch
#: is seconds (`MIN_SLOW_S` is 3.3 times this limit, and 1.5 s on CI).
GAP_LIMIT_S = 0.3

_CALIBRATED: list[float] = []


def _flow(dock):
    return getattr(dock, "fill_flow", None)


def _idle(dock) -> bool:
    flow = _flow(dock)
    return flow is None or not (flow.working or flow.stretching)


def _wait_idle(dock) -> None:
    assert spin_until(lambda: _idle(dock), 60_000), "the fill flow never went idle"


def _assert_slow(dock) -> None:
    """The synchronous builds of the fixture's cells are slow enough to tell
    anything. SLOW_CELL takes at least MIN_SLOW_S (3.3 times the gap limit; CI has
    measured 0.47 to 0.65 of this machine's time, and SLOW_CELL takes 3.2 s here,
    so the floor still holds there and fails loudly on a much faster runner).
    MID_CELL must exceed twice the 0.2 s budget, or the cancel tests would draw
    it in the same tick and pass vacuously."""
    if _CALIBRATED:
        return
    from nsgeo_qgis.slices_engine import build_fill

    engine = dock.engine
    previous = Resolution(
        cell=dock.cell_spin.value(),
        dz_ns=dock.dz_spin.value(),
        t0_ns=dock.z0_spin.value(),
        t1_ns=dock.z1_spin.value(),
    )
    took: dict[float, float] = {}
    try:
        for cell in (SLOW_CELL, MID_CELL):
            engine.set_resolution(
                Resolution(
                    cell=cell, dz_ns=previous.dz_ns, t0_ns=previous.t0_ns, t1_ns=previous.t1_ns
                )
            )
            _, coverage = engine.slice_at(dock.current_window())
            settings = engine.finish_settings(SliceFinish())
            started = time.perf_counter()
            build_fill(coverage > 0, cell, settings)
            took[cell] = time.perf_counter() - started
    finally:
        engine.set_resolution(previous)
    assert took[SLOW_CELL] >= MIN_SLOW_S, f"the slow cell takes {took[SLOW_CELL]:.2f} s: shrunk"
    assert took[MID_CELL] >= 2 * FILL_BUDGET_S, (
        f"the mid cell takes {took[MID_CELL]:.2f} s: too fast"
    )
    _CALIBRATED.append(took[SLOW_CELL])


def _release(dock) -> None:
    """Join this dock's own worker threads (both `Refiner`s). Safe twice."""
    dock.refiner.shutdown()
    dock.fill_worker.shutdown()


def _calibrated(dock) -> None:
    """`_assert_slow`, and a failed one never leaks: the dock's
    workers are joined before the failure is raised, so a runner that is too
    fast for the fixture reports that, not a stray `nsgeo-refine` thread in
    some later test."""
    try:
        _assert_slow(dock)
    except BaseException:
        _release(dock)
        raise


@pytest.fixture
def quick(docked):  # noqa: F811
    """A prepared dock with a picture at a coarse cell."""
    dock, session = docked
    _ready(dock)
    dock.cell_spin.setValue(QUICK_CELL)
    dock.flush_debounce()
    _wait_idle(dock)
    assert dock.current_values() is not None
    return dock, session


@pytest.fixture
def slow(quick):
    dock, session = quick
    _calibrated(dock)
    return dock, session


class Gaps:
    """The largest gap between the ticks of a 10 ms timer on the GUI thread."""

    def __init__(self) -> None:
        self.largest = 0.0
        self._last = 0.0
        self._timer = QTimer()
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        now = time.perf_counter()
        self.largest = max(self.largest, now - self._last)
        self._last = now

    def start(self) -> None:
        self._last = time.perf_counter()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()


def _edit_cell(dock, cell: float) -> None:
    dock.cell_spin.setValue(cell)
    dock.flush_debounce()


def _notes(dock) -> list[str]:
    return [e.text for e in dock.warnings_panel.entries() if e.kind == NOTE]


def _watch_pictures(dock) -> list[tuple[float, tuple[int, ...]]]:
    """`(frame cell, picture shape)` at each `slice_changed`."""
    seen: list[tuple[float, tuple[int, ...]]] = []

    def record() -> None:
        values, frame = dock.current_values(), dock.current_frame()
        seen.append((frame.cell, values.shape) if values is not None and frame else (0.0, ()))

    dock.slice_changed.connect(record)
    return seen


def test_this_grid_never_blocks_the_gui_during_a_slow_fill(slow):
    dock, _ = slow
    changed: list[int] = []
    dock.slice_changed.connect(lambda: changed.append(1))
    gaps = Gaps()
    gaps.start()
    _edit_cell(dock, SLOW_CELL)
    at_edit = len(changed)
    texts: set[str] = set()
    counts_while_working: list[int] = []

    def landed() -> bool:
        flow = _flow(dock)
        texts.add(dock.refine_label.text())
        if flow is not None and flow.working:
            counts_while_working.append(len(changed))
        return flow is None or not flow.working

    assert spin_until(landed, 60_000)
    spin_until(lambda: False, 60)  # let the timer report a gap that ended just now
    gaps.stop()
    assert gaps.largest < GAP_LIMIT_S, f"the GUI thread stood still for {gaps.largest:.2f} s"
    assert any("%" in text for text in texts), texts
    assert counts_while_working, "the fill never showed as working"
    assert set(counts_while_working) == {at_edit}, "the map changed before the fill landed"
    assert len(changed) > at_edit
    _wait_idle(dock)


def test_a_quick_fill_draws_in_the_same_tick(quick, monkeypatch):
    from nsgeo_qgis.ui.fill_flow import FillFlow

    dock, _ = quick
    seen: list[bool] = []
    real = FillFlow.working
    monkeypatch.setattr(
        FillFlow, "working", property(lambda self: seen.append(real.fget(self)) or real.fget(self))
    )
    pictures = _watch_pictures(dock)
    _edit_cell(dock, 0.2)
    assert [cell for cell, _ in pictures] == [0.2], "drawn once, inside the same call"
    assert dock.current_frame().cell == 0.2
    assert seen and not any(seen), "the flow was working, but a quick fill must not be"
    assert "fill" not in dock.refine_label.text()  # at most the stretch is being measured
    assert not dock.cancel_link.isVisibleTo(dock)
    _wait_idle(dock)


def test_cancel_with_a_picture_puts_everything_back(slow):
    dock, session = slow
    before = session.slice_resolution("A")
    assert before["cell"] == QUICK_CELL
    assert "max_distance_spacings" not in before
    pictures = _watch_pictures(dock)
    shape = dock.current_values().shape
    dock.grid_finish.max_distance_spin.setValue(0.9)  # a fill setting too
    _edit_cell(dock, SLOW_CELL)
    assert spin_until(lambda: _flow(dock) is not None and dock.fill_flow.working, 10_000)
    assert "max_distance_spacings" in session.slice_resolution("A")
    assert dock.cancel_link.isVisibleTo(dock)
    dock.cancel_link.linkActivated.emit("cancel")
    assert dock.cell_spin.value() == QUICK_CELL
    assert dock.grid_finish.value() == SliceFinish()
    assert session.slice_resolution("A") == before, "key presence included"
    assert dock.engine.frame.cell == QUICK_CELL
    assert not dock.fill_flow.latched
    assert not dock.cancel_link.isVisibleTo(dock)
    _wait_idle(dock)
    dock.flush_debounce()
    _wait_idle(dock)
    assert session.slice_resolution("A") == before
    assert pictures and all(p == (QUICK_CELL, shape) for p in pictures), pictures
    assert dock.grid_finish.value() == SliceFinish()
    assert _notes(dock) == []


def test_cancel_with_no_picture_latches_until_a_fill_setting_changes(
    tmp_path, qgis_app, monkeypatch
):
    gen = _docked_with(tmp_path, PRESET, record={"cell": SLOW_CELL})
    dock, session = next(gen)
    try:
        jobs: list[int] = []
        real = dock.engine.fill_job
        monkeypatch.setattr(
            dock.engine, "fill_job", lambda *a, **k: jobs.append(1) or real(*a, **k)
        )
        assert spin_until(lambda: _flow(dock) is not None and dock.fill_flow.working, 60_000)
        assert dock.current_values() is None
        before = session.slice_resolution("A")
        dock.cancel_link.linkActivated.emit("cancel")
        assert dock.fill_flow.latched
        assert FILL_CANCELLED_NOTE in _notes(dock)
        assert session.slice_resolution("A") == before, "no picture: the record stays"
        assert dock.cell_spin.value() == SLOW_CELL
        started = len(jobs)
        dock.slice_slider.setValue(min(dock.slice_slider.maximum(), 3))
        dock._on_prepared()
        QCoreApplication.processEvents()
        assert len(jobs) == started, "a slider move or a preparation starts no job"
        assert dock.current_values() is None
        assert not dock.fill_flow.working
        index = dock.grid_finish.method_combo.findData("idw")
        dock.grid_finish.method_combo.setCurrentIndex(index)
        assert spin_until(lambda: len(jobs) == started + 1, 20_000), "a method edit starts one"
        assert not dock.fill_flow.latched
        assert FILL_CANCELLED_NOTE not in _notes(dock)
        dock.fill_flow.stop()
    finally:
        gen.close()


def test_cancel_again_after_going_back_to_a_slow_picture_latches(slow):
    dock, session = slow
    _edit_cell(dock, SLOW_CELL)
    _wait_idle(dock)  # the picture at the slow cell is on the map
    assert dock.current_frame().cell == SLOW_CELL
    pictures = _watch_pictures(dock)
    _edit_cell(dock, MID_CELL)
    assert spin_until(lambda: _flow(dock) is not None and dock.fill_flow.working, 10_000)
    dock.cancel_link.linkActivated.emit("cancel")
    assert dock.cell_spin.value() == SLOW_CELL
    assert dock.fill_flow.working, "going back rebuilds the slow picture: the line shows again"
    assert not dock.fill_flow.latched
    dock.cancel_link.linkActivated.emit("cancel")
    assert dock.fill_flow.latched
    assert not dock.fill_flow.working
    assert FILL_CANCELLED_NOTE in _notes(dock)
    assert dock.cell_spin.value() == SLOW_CELL
    assert session.slice_resolution("A")["cell"] == SLOW_CELL
    assert pictures == [], "nothing was drawn while it was cancelled"


def test_a_stale_fill_never_lands(slow, monkeypatch):
    dock, _ = slow
    lands: list[tuple[float, bool]] = []
    real = FillJob.land

    def spy(self):
        ok = real(self)
        lands.append((self.frame.cell, ok))
        return ok

    monkeypatch.setattr(FillJob, "land", spy)
    _edit_cell(dock, SLOW_CELL)
    assert spin_until(lambda: _flow(dock) is not None and dock.fill_flow.working, 10_000)
    _edit_cell(dock, 0.15)
    _wait_idle(dock)
    assert SLOW_CELL not in [cell for cell, _ in lands], lands
    assert dock.engine.frame.cell == 0.15
    assert dock.current_frame().cell == 0.15
    assert dock.current_values().shape == (
        dock.engine.frame.ny,
        dock.engine.frame.nx,
    )


def test_the_stretch_lands_after_the_picture_and_redraws(fake_iface, site3, answer_modal):
    plugin = _open(fake_iface, site3, answer_modal)
    try:
        dock, layer = plugin.slices_dock, plugin.slice_layer
        _wait_idle(dock)
        spin_until(lambda: layer._renderer_key is not None, 20_000)
        previous = layer._renderer_key[2]
        new_cell = 0.25 if abs(dock.cell_spin.value() - 0.25) > 1e-9 else 0.2
        dock.cell_spin.setValue(new_cell)
        dock.flush_debounce()
        assert layer._renderer_key[2] == previous, "the first draw uses the previous limit"
        window, finish = dock.current_window(), dock.slice_finish()
        clip = UnipolarClip() if dock.engine.output_unipolar else PercentileClip()
        expected, _ = dock.engine.stretch_limit(window.n_levels, clip, finish)
        assert expected != pytest.approx(previous), "the fixture must move the stretch"
        assert spin_until(lambda: layer._renderer_key[2] == pytest.approx(expected), 30_000)
        _wait_idle(dock)
        assert dock.display_limit() == pytest.approx(expected)
    finally:
        _close(plugin, answer_modal)


def test_a_stretch_request_never_cancels_the_fill_work(slow, monkeypatch):
    from nsgeo_qgis.ui.fill_flow import FillFlow

    dock, _ = slow
    lands: list[tuple[float, bool]] = []
    real_land = FillJob.land

    def land_spy(self):
        ok = real_land(self)
        lands.append((self.frame.cell, ok))
        return ok

    monkeypatch.setattr(FillJob, "land", land_spy)
    asked: list[bool] = []
    real_request = FillFlow.request_stretch

    def request_spy(self, key, job):
        asked.append(self.working)
        return real_request(self, key, job)

    monkeypatch.setattr(FillFlow, "request_stretch", request_spy)
    _edit_cell(dock, SLOW_CELL)
    assert spin_until(lambda: dock.fill_flow.working, 10_000)
    dock.display_limit()
    dock.thickness_spin.setValue(dock.thickness_spin.value() + 2 * dock.dz_spin.value())
    dock.display_limit()
    # `display_limit` leaves the asking to the flow's own follow-on while fills run;
    # a request made anyway must not cancel the fill nor build a job (it would
    # drop an engine's held fill).
    dock.fill_flow.request_stretch("another key", lambda: pytest.fail("built while a fill runs"))
    assert dock.fill_flow.working, "the fill is still going"
    assert not any(not working for working in asked), asked
    _wait_idle(dock)
    assert lands == [(SLOW_CELL, True)], lands
    key = dock._stretch_key(dock._window, dock.slice_finish())
    assert dock._grid_refine.held_stretch(key) is not None, "the stretch for the current key landed"


def test_unloading_while_a_fill_runs_lands_nothing(fake_iface, site3, answer_modal, monkeypatch):
    plugin = _open(fake_iface, site3, answer_modal)
    unloaded = False
    try:
        dock = plugin.slices_dock
        engine = dock.engine
        landed: list[int] = []
        real = engine._land_fill
        monkeypatch.setattr(engine, "_land_fill", lambda job: landed.append(1) or real(job))
        problems: list[str] = []
        disconnect = connect_message_log(
            lambda msg, tag, level: problems.append(msg) if level >= 1 else None
        )
        try:
            _edit_cell(dock, SLOW_CELL)
            assert spin_until(lambda: dock.fill_flow.working, 10_000)
            # This dock's own worker threads (other tests' may still be unwinding).
            mine = list(dock.fill_worker._executor._threads)
            assert mine and all(t.name.startswith("nsgeo-fill") for t in mine)
            answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
            plugin.unload()
            unloaded = True
            for _ in range(20):
                QCoreApplication.processEvents()
                time.sleep(0.01)
        finally:
            disconnect()
        assert landed == []
        assert not any(t.is_alive() for t in mine)
        assert engine._disposed
        assert [m for m in problems if "fill" in m.lower()] == []
    finally:
        if not unloaded:
            _close(plugin, answer_modal)


def test_cancel_goes_back_to_a_preview_that_is_on_the_map(slow):
    """The picture is whatever array is drawn, a minimum-curvature preview
    included: a kriging picture, then a preview, then a slow cell."""
    dock, session = slow
    _set_finish(dock, method="min_curvature")
    _wait_idle(dock)
    assert dock.provisional, "a preview is on the map"
    before = session.slice_resolution("A")
    assert before["method"] == "min_curvature"
    _edit_cell(dock, SLOW_CELL)
    assert spin_until(lambda: _flow(dock) is not None and dock.fill_flow.working, 10_000)
    dock.cancel_link.linkActivated.emit("cancel")
    assert dock.grid_finish.value().method == "min_curvature"
    assert dock.cell_spin.value() == QUICK_CELL
    assert session.slice_resolution("A") == before
    assert not dock.fill_flow.latched
    assert FILL_CANCELLED_NOTE not in _notes(dock)
    _wait_idle(dock)


def test_cancel_with_only_a_preview_since_opening_does_not_latch(tmp_path, qgis_app):
    gen = _docked_with(tmp_path, PRESET, record={"cell": QUICK_CELL, "method": "min_curvature"})
    dock, session = next(gen)
    try:
        assert spin_until(lambda: dock.current_values() is not None, 60_000)
        assert dock.provisional
        _wait_idle(dock)
        _calibrated(dock)
        _edit_cell(dock, SLOW_CELL)
        assert spin_until(lambda: dock.fill_flow.working, 10_000)
        dock.cancel_link.linkActivated.emit("cancel")
        assert not dock.fill_flow.latched
        assert FILL_CANCELLED_NOTE not in _notes(dock)
        assert dock.cell_spin.value() == QUICK_CELL
        dock.fill_flow.stop()
    finally:
        gen.close()


def test_cancel_puts_back_only_the_fill_settings(slow):
    """A z or smoothing edit made while the fill ran is not the fill's: it
    survives Cancel, in the panel, the engine and the saved record."""
    dock, session = slow
    before = session.slice_resolution("A")
    _edit_cell(dock, SLOW_CELL)
    assert spin_until(lambda: _flow(dock) is not None and dock.fill_flow.working, 10_000)
    dock.z0_spin.setValue(3.0)
    dock.grid_finish.smooth_x_spin.setValue(0.1)
    dock.cancel_link.linkActivated.emit("cancel")
    assert dock.cell_spin.value() == QUICK_CELL
    assert dock.z0_spin.value() == 3.0
    assert dock.grid_finish.smooth_x_spin.value() == pytest.approx(0.1)
    record = session.slice_resolution("A")
    assert record["cell"] == QUICK_CELL
    assert record["t0_ns"] == 3.0
    assert record["smooth_x_m"] == pytest.approx(0.1)
    assert dock.engine.z.t0_ns == pytest.approx(3.0)
    assert dock.engine.frame.cell == QUICK_CELL
    assert set(before) <= set(record)
    _wait_idle(dock)


def test_a_z_edit_mid_stretch_never_lands_a_stale_stretch(quick, monkeypatch):
    dock, _ = quick
    slow_jobs(monkeypatch, dock.engine, ("stretch_job",), pause=0.6)
    _edit_cell(dock, 0.2)
    assert spin_until(lambda: dock.fill_flow.stretching, 10_000)
    dock.z0_spin.setValue(4.0)  # the key does not change, the windows do
    dock.flush_debounce()
    _wait_idle(dock)
    window, finish = dock.current_window(), dock.slice_finish()
    clip = UnipolarClip() if dock.engine.output_unipolar else PercentileClip()
    fresh, _ = dock.engine.stretch_limit(window.n_levels, clip, finish)
    assert dock.display_limit() == pytest.approx(fresh)


def test_this_grid_keeps_a_current_stretch_when_only_its_fill_is_missing(quick, monkeypatch):
    """#236: This grid's `_fill_jobs`, like the site's, leaves the stretch job
    out when the stretch held is for this very key: a final one would be
    measured again (and, for minimum curvature, replaced by a provisional one)."""
    dock, _ = quick
    dock.display_limit()
    _wait_idle(dock)
    window, finish = dock.current_window(), dock.slice_finish()
    key = dock._stretch_key(window, finish)
    held = dock._grid_refine.held_stretch(key)
    assert held is not None
    jobs: list[int] = []
    real = dock.engine.stretch_job
    monkeypatch.setattr(dock.engine, "stretch_job", lambda *a, **k: jobs.append(1) or real(*a, **k))
    dock.engine._drop_fill()  # the fill is missing, the stretch's key is unchanged
    dock.refresh_slice()
    _wait_idle(dock)
    assert dock.engine.fill_held(dock.engine.slice_at(window)[1], finish)
    assert jobs == [], "a current stretch was measured again"
    assert dock._grid_refine.held_stretch(key) == held


def test_this_grids_status_line_counts_what_the_draw_built(quick, monkeypatch):
    """#236: the status line was set before `slice_changed`, whose listener
    (the map layer's `to_north_up`) builds the frame's north-up plan, so the
    memory it named lagged one draw. Stand-in: a listener that makes the plans
    hold a gigabyte."""
    from nsgeo_qgis import slices_engine

    dock, _ = quick
    held = [0]
    monkeypatch.setattr(slices_engine, "north_up_plans_nbytes", lambda: held[0])

    def build_plan() -> None:
        held[0] = 10**9

    dock.slice_changed.connect(build_plan)
    try:
        dock.refresh_slice()
        _wait_idle(dock)
        assert "1.0 GB" in dock._grid_status_text()
        assert dock.status_label.text() == dock._grid_status_text(), "the line lags the draw"
    finally:
        dock.slice_changed.disconnect(build_plan)


def test_a_scope_switch_applies_a_pending_change_before_it_stops_the_work(slow):
    dock, _ = slow
    dock.cell_spin.setValue(SLOW_CELL)  # pending in the debounce
    dock.set_scope("site")
    try:
        assert not dock.fill_flow.working, "a fill started by the apply must not run on"
        assert not dock.cancel_link.isVisibleTo(dock)
    finally:
        dock.set_scope("grid")
        dock.fill_flow.stop()
        wait_for_site(dock.site_engine, 60_000)


def test_clearing_the_map_forgets_the_limit_and_the_picture(quick):
    dock, _ = quick
    dock.display_limit()
    _wait_idle(dock)
    dock.display_limit()
    assert dock._limit_shown is not None
    dock.engine.clear()
    dock.refresh_slice()
    assert dock._limit_shown is None
    assert dock.current_values() is None
    assert dock.fill_picture._picture is None


def test_closing_the_survey_while_a_fill_runs_lands_nothing(
    fake_iface, site3, answer_modal, monkeypatch
):
    plugin = _open(fake_iface, site3, answer_modal)
    try:
        dock = plugin.slices_dock
        landed: list[int] = []
        real = dock.engine._land_fill
        monkeypatch.setattr(dock.engine, "_land_fill", lambda job: landed.append(1) or real(job))
        _edit_cell(dock, SLOW_CELL)
        assert spin_until(lambda: dock.fill_flow.working, 10_000)
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.session.close_site()
        assert not dock.fill_flow.working
        assert spin_until(lambda: not dock.fill_worker.busy and not dock.fill_flow.working, 20_000)
        for _ in range(20):
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert landed == []
        assert dock.current_frame() is None or dock.current_frame().cell != SLOW_CELL
        assert not dock.fill_flow.latched
    finally:
        _close(plugin, answer_modal)


@pytest.mark.parametrize("width", ["narrow", "wide"])
def test_the_cancel_link_keeps_the_readout_row_one_line_high(quick, width):
    """W1: the working line and its link share the readout's row; showing the
    link moves neither the content's height nor the depth slider."""
    dock, _ = quick
    dock.setFloating(True)
    dock.resize(layout_width(dock, width), 700)
    dock.show()
    probe = LayoutProbe(dock)
    baseline = probe.settle()
    dock.refine_label.setText("Working out the fill at 0.017 m: 42%")
    dock.cancel_link.show()
    assert probe.settle() == baseline
    probe.assert_indicator_shares_the_readouts_row()
    assert dock.cancel_link.height() <= dock.refine_label.height() + 2


# ---- the flow on its own ---------------------------------------------------


class FakeFill(FillJob):
    """A fill job that only sleeps; `land` says what it is told."""

    def __init__(self, pause: float = 0.0, *, refuse: bool = False) -> None:
        self.pause = pause
        self.refuse = refuse
        self.fraction = 0.0
        self.fill = None
        self.preview = None
        self.lands = 0

    def run(self, should_stop) -> None:
        end = time.monotonic() + self.pause
        while time.monotonic() < end and not should_stop():
            time.sleep(0.005)
        self.fraction = 1.0

    def land(self) -> bool:
        self.lands += 1
        return not self.refuse


class FakeFootprint(FootprintJob):
    """A footprint job that only sleeps, or fails with `error`."""

    def __init__(self, pause: float = 0.0, *, error: Exception | None = None) -> None:
        self.pause = pause
        self.error = error
        self.fraction = 0.0
        self.footprint = None

    def run(self, should_stop) -> None:
        time.sleep(self.pause)
        if self.error is not None:
            raise self.error
        self.fraction = 1.0

    def land(self) -> bool:
        return True


class FakeStretch(StretchJob):
    def __init__(self, limit: float | None, final: bool = True, pause: float = 0.0) -> None:
        self.limit = limit
        self.final = final
        self.pause = pause
        self.fraction = 0.0
        self.lands = 0

    def run(self, should_stop) -> None:
        time.sleep(self.pause)
        self.fraction = 1.0

    def land(self) -> bool:
        self.lands += 1
        return True


@pytest.fixture
def flow_probe(qgis_app):
    from nsgeo_qgis.refine import Refiner
    from nsgeo_qgis.ui.fill_flow import FillFlow

    parent = QTimer()  # any QObject
    worker = Refiner(parent, thread_name_prefix="nsgeo-fill-test")
    log: list = []
    flow = FillFlow(
        parent,
        worker,
        on_done=lambda: log.append("done"),
        on_stretch=lambda key, limit, final: log.append(("stretch", key, limit, final)),
        on_cancelled=lambda: log.append("cancelled"),
        on_tick=lambda: log.append("tick"),
        on_error=lambda what, message: log.append(("error", what, message)),
    )
    yield flow, worker, log
    flow.stop()
    worker.shutdown()


def test_a_landing_inside_the_wait_never_draws_inside_the_callers_frame(flow_probe):
    flow, _, log = flow_probe
    draw: list[str] = []

    def drawing() -> bool:
        draw.append("begin")
        answer = flow.request("k", [FakeFill()], stretch_key="s")
        draw.append(f"requested {answer}")
        draw.append("end")
        return answer

    assert drawing() is True
    assert draw == ["begin", "requested True", "end"]
    assert "done" not in log, "on_done must not run inside the draw that called request"
    assert not flow.working
    QCoreApplication.processEvents()
    assert "done" not in log


def test_a_slow_fill_is_drawn_once_from_the_poll_not_inside_a_request(flow_probe):
    flow, _, log = flow_probe
    job = FakeFill(0.6)
    assert flow.request("k", [job, FakeStretch(2.0)], stretch_key="s") is False
    assert flow.working
    assert (
        flow.request("k", lambda: pytest.fail("the same key is dropped"), stretch_key="s") is False
    )
    assert spin_until(lambda: "done" in log, 10_000)
    assert log.count("done") == 1
    assert job.lands == 1
    assert spin_until(lambda: ("stretch", "s", 2.0, True) in log, 10_000)
    assert not flow.working and not flow.stretching


def test_the_stretch_follows_the_fills_and_never_holds_up_a_quick_one(flow_probe):
    flow, _, log = flow_probe
    assert flow.request("k", [FakeFill(), FakeStretch(1.0, pause=0.6)], stretch_key="s") is True
    assert flow.stretching and not flow.working
    assert flow.progress_text(0.05, grids=False) == STRETCH_WORKING_INDICATOR
    assert spin_until(lambda: ("stretch", "s", 1.0, True) in log, 10_000)


def test_a_stretch_with_no_limit_is_dropped(flow_probe):
    flow, _, log = flow_probe
    flow.request_stretch("s", FakeStretch(None))
    assert flow.stretching
    assert spin_until(lambda: not flow.stretching, 10_000)
    assert not [entry for entry in log if isinstance(entry, tuple) and entry[0] == "stretch"]


def test_a_measured_stretch_is_landed_before_it_is_handed_on(flow_probe):
    """#236: the stretch job's `land` runs on the GUI thread (it refreshes the
    solves it read in their engines); a stale one, which measured nothing, is not."""
    flow, _, log = flow_probe
    measured, stale = FakeStretch(1.0), FakeStretch(None)
    flow.request_stretch("s", measured)
    assert spin_until(lambda: ("stretch", "s", 1.0, True) in log, 10_000)
    assert measured.lands == 1
    flow.request_stretch("t", stale)
    assert spin_until(lambda: not flow.stretching, 10_000)
    assert stale.lands == 0


def test_a_stretch_request_waits_for_the_fills_and_for_its_own_key(flow_probe):
    flow, _, log = flow_probe
    flow.request("k", [FakeFill(0.4)], stretch_key="s")
    flow.request_stretch("t", lambda: pytest.fail("not while a fill runs"))
    assert spin_until(lambda: not flow.working, 10_000)
    flow.request_stretch("t", FakeStretch(3.0, pause=0.5))
    assert flow.stretching
    flow.request_stretch("t", lambda: pytest.fail("the same key is running"))
    flow.request_stretch("u", FakeStretch(4.0))
    assert spin_until(lambda: ("stretch", "u", 4.0, True) in log, 10_000)
    assert not [e for e in log if isinstance(e, tuple) and e[:2] == ("stretch", "t")]


def test_cancel_calls_back_and_stop_does_not(flow_probe):
    flow, _, log = flow_probe
    flow.request("k", [FakeFill(1.0)], stretch_key="s")
    flow.cancel()
    assert not flow.working and log.count("cancelled") == 1
    flow.latch()
    flow.request("k", [FakeFill(1.0)], stretch_key="s")  # latched: nothing starts
    assert not flow.working
    flow.unlatch()
    flow.request("k", [FakeFill(1.0)], stretch_key="s")
    flow.stop()
    assert not flow.working and log.count("cancelled") == 1
    assert not flow.latched


def test_progress_reads_the_running_job_or_the_grids_landed(flow_probe):
    flow, _, _ = flow_probe
    first = FakeFill(0.6)
    flow.request("k", [first, FakeFill(0.0)], stretch_key="s")
    first.fraction = 0.42
    assert flow.progress_text(0.05, grids=False) == FILL_WORKING_INDICATOR.format(
        cell=0.05, percent=42
    )
    assert flow.progress_text(0.05, grids=True) == FILL_WORKING_GRIDS_INDICATOR.format(
        cell=0.05, n=1, total=2
    )
    assert spin_until(lambda: not flow.working, 10_000)
    assert flow.progress_text(0.05, grids=False) == ""


def test_footprints_alone_are_worded_as_placing_the_grids(flow_probe):
    """#236: a coverage draw's footprint request read "Working out the fill"."""
    flow, _, _ = flow_probe
    flow.request("k", [FakeFootprint(0.6), FakeFootprint(0.0)], stretch_key="s")
    assert flow.progress_text(0.05, grids=True) == FOOTPRINT_WORKING_INDICATOR.format(
        cell=0.05, n=1, total=2
    )
    assert spin_until(lambda: not flow.working, 10_000)


def test_a_failed_footprint_is_named_as_the_footprints(flow_probe):
    """#236: a failed footprint gather was reported as a failed fill."""
    flow, _, log = flow_probe
    failing = FakeFootprint(error=ValueError("no transform"))
    assert flow.request("k", [FakeFill(), failing], stretch_key="s") is False
    assert spin_until(lambda: not flow.working, 10_000)
    assert ("error", "footprints", "ValueError: no transform") in log


def test_stop_never_touches_the_latch(flow_probe):
    """FillPicture is the latch's one owner: a stop only cancels the work."""
    flow, _, _ = flow_probe
    flow.latch()
    flow.stop()
    assert flow.latched
    flow.unlatch()
    assert not flow.latched


def test_a_this_grid_preparation_under_the_site_never_cancels_the_sites_stretch(
    fake_iface, site3, answer_modal
):
    from test_plugin_site_scope import whole_site

    plugin = _open(fake_iface, site3, answer_modal)
    try:
        dock = plugin.slices_dock
        whole_site(plugin)
        assert dock.scope() == "site"
        _wait_idle(dock)  # the site's own fills run on this worker too
        job = FakeStretch(1.0, pause=0.8)
        dock.fill_flow.request_stretch("site-key", job)
        assert dock.fill_flow.stretching
        dock._on_prepared()  # a This-grid preparation lands under Whole site
        assert dock.fill_flow.stretching, "the site's stretch was cancelled"
        assert spin_until(lambda: not dock.fill_flow.stretching, 20_000)
        assert not dock.fill_worker.busy
    finally:
        _close(plugin, answer_modal)


def test_a_failed_stretch_is_named_as_the_stretch(flow_probe):
    flow, _, log = flow_probe

    class Failing(FakeStretch):
        def run(self, should_stop) -> None:
            raise ValueError("no windows")

    flow.request_stretch("s", Failing(None))
    assert spin_until(lambda: not flow.stretching, 10_000)
    assert ("error", "colour stretch", "ValueError: no windows") in log


def test_dropping_the_stretch_cancels_a_running_and_a_waiting_one(flow_probe):
    flow, _, log = flow_probe
    flow.request_stretch("s", FakeStretch(1.0, pause=0.5))
    flow.drop_stretch()
    assert not flow.stretching
    flow.request("k", [FakeFill(0.4), FakeStretch(2.0)], stretch_key="t")
    flow.drop_stretch()
    assert spin_until(lambda: not flow.working, 10_000)
    assert not flow.stretching
    spin_until(lambda: False, 150)
    assert not [e for e in log if isinstance(e, tuple) and e[0] == "stretch"]


def test_a_failed_fill_is_reported_and_clears_the_state(flow_probe):
    flow, _, log = flow_probe

    class Failing(FakeFill):
        def run(self, should_stop) -> None:
            raise ValueError("no room")

    assert flow.request("k", [Failing()], stretch_key="s") is False
    assert not flow.working
    assert ("error", "fill", "ValueError: no room") in log


# ---- Whole site (#193) ------------------------------------------------------
#: Not the site's seeded 0.1 m: a cell equal to the seed is not remembered as chosen.
SITE_QUICK_CELL = 0.2


def _site_cell(dock, cell: float) -> None:
    """Edit the site's cell and apply it at once, as the debounce would."""
    dock.cell_spin.setValue(cell)
    dock.flush_debounce()


def _applied_cell(dock) -> float:
    return dock.site_engine._resolution.cell


_SITE_CALIBRATED: list[float] = []


def _picture_cell(dock) -> float | None:
    """The cell of the picture on the map (the tick that draws it runs from the
    event loop, after the edit has applied)."""
    picture = dock.fill_picture._picture
    return None if picture is None else picture[1]["cell"]


def _assert_slow_site(dock) -> None:
    """The three grids' fills, built one after another, take at least
    MIN_SLOW_SITE_S at SITE_SLOW_CELL: the brief asked for 2 s on CI; this
    loaded machine is calibrated to measure it, and a fast runner still fails
    loudly rather than pass vacuously."""
    if _SITE_CALIBRATED:
        return
    from nsgeo_qgis.slices_engine import build_fill

    engine = dock.site_engine
    previous = engine._resolution
    engine.set_resolution(
        Resolution(
            cell=SITE_SLOW_CELL,
            dz_ns=previous.dz_ns,
            t0_ns=previous.t0_ns,
            t1_ns=previous.t1_ns,
        )
    )
    total = 0.0
    try:
        top = previous.t0_ns + 5.0
        for grid_id in engine.ready_grids:
            grid = engine._engines[grid_id]
            window = engine._grid_window(grid_id, top, 3.0)
            _, coverage = grid.slice_at(window)
            started = time.perf_counter()
            build_fill(coverage > 0, SITE_SLOW_CELL, grid.finish_settings(SliceFinish()))
            total += time.perf_counter() - started
    finally:
        engine.set_resolution(previous)
    assert total >= MIN_SLOW_SITE_S, f"the site's fills take {total:.2f} s together: shrunk"
    _SITE_CALIBRATED.append(total)


@pytest.fixture
def site_quick(fake_iface, site3, answer_modal):
    """The plugin on three grids, Whole site, a picture at a coarse cell."""
    plugin = _open(fake_iface, site3, answer_modal)
    try:
        dock = whole_site(plugin)
        _site_cell(dock, SITE_QUICK_CELL)
        assert spin_until(lambda: _picture_cell(dock) == SITE_QUICK_CELL, 60_000)
        _wait_idle(dock)
        assert dock.current_site_slice() is not None
        assert _applied_cell(dock) == SITE_QUICK_CELL
        yield plugin, dock
    finally:
        _close(plugin, answer_modal)


@pytest.fixture
def site_slow(site_quick):
    plugin, dock = site_quick
    _assert_slow_site(dock)
    return plugin, dock


def _watch_site(dock) -> list[tuple[float, int]]:
    """`(applied cell, grids shown)` at each `slice_changed`."""
    seen: list[tuple[float, int]] = []

    def record() -> None:
        shown = dock.current_site_slice()
        seen.append((_applied_cell(dock), len(shown.windows) if shown is not None else 0))

    dock.slice_changed.connect(record)
    return seen


def test_whole_site_never_blocks_the_gui_during_a_slow_fill(site_slow):
    _, dock = site_slow
    changed: list[int] = []
    drawn_at: list[float] = []
    dock.slice_changed.connect(lambda: changed.append(1))
    dock.slice_changed.connect(lambda: drawn_at.append(_applied_cell(dock)))
    gaps = Gaps()
    gaps.start()
    _site_cell(dock, SITE_SLOW_CELL)
    at_edit = len(changed)
    texts: list[str] = []
    counts_while_working: list[int] = []
    shown_before = dock.current_site_slice()

    def landed() -> bool:
        flow = _flow(dock)
        texts.append(dock.refine_label.text())
        if flow is not None and flow.working:
            counts_while_working.append(len(changed))
        # Done when the slow cell is on the map: the tick that asks for the fills
        # runs from the event loop, so the flow is not working just yet.
        return SITE_SLOW_CELL in drawn_at and not (flow is not None and flow.working)

    assert spin_until(landed, 120_000)
    spin_until(lambda: False, 60)  # let the timer report a gap that ended just now
    gaps.stop()
    assert gaps.largest < GAP_LIMIT_S, f"the GUI thread stood still for {gaps.largest:.2f} s"
    first = FILL_WORKING_GRIDS_INDICATOR.format(cell=SITE_SLOW_CELL, n=1, total=3)
    last = FILL_WORKING_GRIDS_INDICATOR.format(cell=SITE_SLOW_CELL, n=3, total=3)
    assert first in texts, texts
    assert last in texts, texts
    assert texts.index(first) < texts.index(last)
    assert counts_while_working, "the fill never showed as working"
    assert set(counts_while_working) == {at_edit}, "the map changed before the fills landed"
    assert len(changed) > at_edit
    assert dock.current_site_slice() is not shown_before
    assert _applied_cell(dock) == SITE_SLOW_CELL
    _wait_idle(dock)


def _spy_lands(monkeypatch) -> list[tuple[str, bool]]:
    lands: list[tuple[str, bool]] = []
    real = FillJob.land

    def spy(self):
        ok = real(self)
        lands.append((self.grid_id, ok))
        return ok

    monkeypatch.setattr(FillJob, "land", spy)
    return lands


def _a_and_c_are_drawn(dock) -> None:
    shown = dock.current_site_slice()
    assert sorted(shown.windows) == ["A", "C"]
    for grid_id in ("A", "C"):
        lattice = shown.lattice
        x0, x1 = {"A": (500.0, 506.0), "C": (512.0, 518.0)}[grid_id]
        cols = slice(int((x0 - lattice.x0) / lattice.pixel), int((x1 - lattice.x0) / lattice.pixel))
        assert np.isfinite(shown.array[:, cols]).any(), grid_id


def test_a_grid_unticked_mid_fill_never_lands_and_the_rest_draws(site_slow, monkeypatch):
    plugin, dock = site_slow
    lands = _spy_lands(monkeypatch)
    _site_cell(dock, SITE_SLOW_CELL)
    assert spin_until(lambda: dock.fill_flow.working, 10_000)
    dock.site_panel.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    _wait_idle(dock)
    spin_until(lambda: False, 200)
    _wait_idle(dock)
    assert ("B", True) not in lands, lands
    assert _applied_cell(dock) == SITE_SLOW_CELL
    assert plugin.session.site_view()["grids"] == ["A", "C"]
    _a_and_c_are_drawn(dock)
    assert dock.site_engine.fills_missing(*dock._site.drawn_at, dock.site_finish.value()) == []


def test_a_grid_removed_mid_fill_never_lands(site_slow, monkeypatch):
    plugin, dock = site_slow
    lands = _spy_lands(monkeypatch)
    _site_cell(dock, SITE_SLOW_CELL)
    assert spin_until(lambda: dock.fill_flow.working, 10_000)
    plugin.session.remove_grid("B", with_lines=True)
    _wait_idle(dock)
    spin_until(lambda: False, 200)
    _wait_idle(dock)
    assert ("B", True) not in lands, lands
    assert _applied_cell(dock) == SITE_SLOW_CELL
    _a_and_c_are_drawn(dock)


def test_cancel_with_a_picture_puts_the_site_back(site_slow):
    plugin, dock = site_slow
    session = plugin.session
    before = session.site_resolution()
    assert before["cell"] == SITE_QUICK_CELL
    assert "max_distance_spacings" not in before
    seen = _watch_site(dock)
    dock.site_finish.max_distance_spin.setValue(0.9)  # a fill setting too
    _site_cell(dock, SITE_SLOW_CELL)
    assert spin_until(lambda: dock.fill_flow.working, 10_000)
    assert "max_distance_spacings" in session.site_resolution()
    assert dock.cancel_link.isVisibleTo(dock)
    dock.cancel_link.linkActivated.emit("cancel")
    assert dock.cell_spin.value() == SITE_QUICK_CELL
    assert dock.site_finish.value() == SliceFinish()
    assert session.site_resolution() == before, "key presence included"
    assert _applied_cell(dock) == SITE_QUICK_CELL
    assert not dock.fill_flow.latched
    assert not dock.cancel_link.isVisibleTo(dock)
    _wait_idle(dock)
    dock.flush_debounce()
    assert spin_until(lambda: bool(seen), 30_000), "going back redraws the picture"
    _wait_idle(dock)
    assert session.site_resolution() == before
    assert dock.cell_spin.value() == SITE_QUICK_CELL
    assert dock.site_finish.value() == SliceFinish()
    assert seen and all(cell == SITE_QUICK_CELL for cell, _ in seen), seen
    assert _notes(dock) == []


def test_cancel_with_no_picture_latches_the_site(fake_iface, site3, answer_modal):
    """A survey opened with a slow saved site cell has no picture to go back
    to: the note, no job from a slider move or from a grid becoming ready, and a
    fill setting draws again."""
    plugin = _open(fake_iface, site3, answer_modal)
    try:
        dock = plugin.slices_dock
        jobs: list[int] = []
        real = dock.site_engine.fill_jobs
        dock.site_engine.fill_jobs = lambda *a, **k: jobs.append(1) or real(*a, **k)
        plugin.session.remember_site_resolution(cell=SITE_SLOW_CELL)
        dock.set_scope("site")
        assert spin_until(lambda: dock.fill_flow.working, 60_000)
        assert dock.current_site_slice() is None, "nothing was ever drawn for the site"
        record = plugin.session.site_resolution()
        dock.cancel_link.linkActivated.emit("cancel")
        assert dock.fill_flow.latched
        assert FILL_CANCELLED_NOTE in _notes(dock)
        assert plugin.session.site_resolution() == record
        assert dock.cell_spin.value() == SITE_SLOW_CELL
        wait_for_site(dock.site_engine, 60_000)
        started = len(jobs)
        dock.slice_slider.setValue(min(dock.slice_slider.maximum(), dock.slice_slider.value() + 2))
        spin_until(lambda: False, 300)
        assert len(jobs) == started and not dock.fill_flow.working, "a slider move starts none"
        # A grid becoming ready (a preparation landing) builds nothing either.
        table = dock.site_panel.table
        table.item(2, 0).setCheckState(Qt.CheckState.Unchecked)
        wait_for_site(dock.site_engine, 60_000)
        spin_until(lambda: False, 200)
        table.item(2, 0).setCheckState(Qt.CheckState.Checked)
        wait_for_site(dock.site_engine, 60_000)
        spin_until(lambda: False, 300)
        assert dock.site_engine.ready_grids == ("A", "B", "C")
        assert len(jobs) == started and not dock.fill_flow.working
        assert dock.fill_flow.latched
        dock.site_finish.method_combo.setCurrentIndex(dock.site_finish.method_combo.findData("idw"))
        assert spin_until(lambda: len(jobs) > started, 20_000), "a method edit draws again"
        assert not dock.fill_flow.latched
        assert FILL_CANCELLED_NOTE not in _notes(dock)
        dock.fill_flow.stop()
        dock.site_engine.fill_jobs = real
    finally:
        _close(plugin, answer_modal)


def test_a_site_with_nothing_to_draw_keeps_a_cancelled_fills_latch(site_quick, monkeypatch):
    _, dock = site_quick
    dock.fill_picture.cancelled(("other",))  # a cancel with no picture of the site's: latches
    assert dock.fill_flow.latched
    monkeypatch.setattr(type(dock.site_engine), "geometry_problem", property(lambda self: "x"))
    dock._site.refresh_slice()
    assert not dock._site.drawn
    assert dock.fill_flow.latched, "nothing to draw is not a fill setting changing"
    dock.fill_picture.unlatch()


def test_a_slider_move_mid_fill_never_restarts_the_grid_in_flight(site_slow):
    """The key is what the tick wants, not what is still missing: the missing
    set shrinks as each grid lands, and a slider move or a bare redraw after
    the first landing must leave the running jobs alone."""
    _, dock = site_slow
    flow = dock.fill_flow
    _site_cell(dock, SITE_SLOW_CELL)
    assert spin_until(lambda: flow.working and flow._landed >= 1, 60_000)
    assert flow._landed < len(flow._fills)
    jobs = [id(job) for job in flow._fills]
    # The three grids' fills, then their footprints on the new lattice (#193).
    assert sum(isinstance(job, FillJob) for job in flow._fills) == 3
    assert len(jobs) == 6
    landed = flow._landed
    dock.slice_slider.setValue(min(dock.slice_slider.maximum(), dock.slice_slider.value() + 1))
    dock._site.tick.stop()
    dock._site.refresh_slice()
    dock._site.refresh_slice()
    assert [id(job) for job in flow._fills] == jobs, "the work was restarted"
    assert flow._landed >= landed
    texts: list[str] = []
    assert spin_until(lambda: texts.append(dock.refine_label.text()) or not flow.working, 120_000)
    last = FILL_WORKING_GRIDS_INDICATOR.format(cell=SITE_SLOW_CELL, n=3, total=3)
    assert last in texts, texts
    assert not any(t.endswith("of 2") for t in texts), texts
    _wait_idle(dock)


def _open_short_c(fake_iface, site3_factory, answer_modal):
    """The site with grid C recording half the time: C's axis ends mid-slider."""
    return _open(fake_iface, site3_factory(samples={"C": 256}), answer_modal)


def _slider_with_and_without_c(dock) -> tuple[int, int]:
    """A slider value whose window reaches C, and one past C's axis end."""
    from nsgeo_qgis.ui.site_scope import levels

    engine, z = dock.site_engine, dock.site_engine.site_z
    thickness, _ = levels(z, dock.thickness_spin.value(), dock.step_spin.value())
    span = thickness * z.dz_ns
    present = [
        v for v in range(z.nz) if engine._grid_window("C", z.t0_ns + v * z.dz_ns, span) is not None
    ]
    assert present and present[-1] < z.nz - 1, "C must end inside the site's axis"
    return present[0], present[-1] + 5


def test_crossing_a_grids_axis_end_mid_fill_never_restarts_the_work(
    fake_iface, site3_factory, answer_modal
):
    plugin = _open_short_c(fake_iface, site3_factory, answer_modal)
    try:
        dock = whole_site(plugin)
        _assert_slow_site(dock)
        flow = dock.fill_flow
        inside, outside = _slider_with_and_without_c(dock)
        dock.slice_slider.setValue(inside)
        spin_until(lambda: False, 100)
        _wait_idle(dock)
        _site_cell(dock, SITE_SLOW_CELL)
        assert spin_until(lambda: flow.working and flow._landed >= 1, 60_000)
        assert flow._landed < len(flow._fills)
        jobs = [id(job) for job in flow._fills]
        landed = flow._landed
        for value in (outside, inside, outside):  # across the axis end, both ways
            dock.slice_slider.setValue(value)
            dock._site.tick.stop()
            dock._site.refresh_slice()
            assert [id(job) for job in flow._fills] == jobs, f"restarted at slider {value}"
            assert flow._landed >= landed
        assert flow.working
        texts: list[str] = []
        assert spin_until(
            lambda: texts.append(dock.refine_label.text()) or not flow.working, 120_000
        )
        assert not any("of 1" in t or "of 2" in t for t in texts), texts
        _wait_idle(dock)
    finally:
        _close(plugin, answer_modal)


def test_a_grid_that_comes_into_range_gets_its_fill_on_the_next_request(
    fake_iface, site3_factory, answer_modal, monkeypatch
):
    plugin = _open_short_c(fake_iface, site3_factory, answer_modal)
    try:
        dock = whole_site(plugin)
        # No shared stretch: only the shown window's grids are filled (with one,
        # every ready grid is, and nothing is left for a move into range).
        dock.stretch_combo.setCurrentIndex(1)
        _assert_slow_site(dock)
        flow, engine = dock.fill_flow, dock.site_engine
        inside, outside = _slider_with_and_without_c(dock)
        dock.slice_slider.setValue(outside)
        spin_until(lambda: False, 100)
        _wait_idle(dock)
        _site_cell(dock, SITE_SLOW_CELL)
        assert spin_until(lambda: flow.working, 60_000)
        _wait_idle(dock)  # A and B filled for a window without C; the picture is drawn
        top = engine.site_z.t0_ns + inside * engine.site_z.dz_ns
        from nsgeo_qgis.ui.site_scope import levels

        z = engine.site_z
        thickness, _ = levels(z, dock.thickness_spin.value(), dock.step_spin.value())
        assert engine.fills_missing(top, thickness * z.dz_ns, dock.site_finish.value()) == ["C"]
        requested: list[list[str]] = []
        real = engine.fill_jobs
        monkeypatch.setattr(
            engine, "fill_jobs", lambda *a, **k: (requested.append(r := real(*a, **k)), r)[1]
        )
        dock.slice_slider.setValue(inside)
        dock._site.tick.stop()
        dock._site.refresh_slice()
        assert requested and [job.grid_id for job in requested[0]] == ["C"]
        _wait_idle(dock)
        assert engine.fills_missing(top, thickness * z.dz_ns, dock.site_finish.value()) == []
    finally:
        _close(plugin, answer_modal)


def test_closing_the_generator_runs_the_docked_teardown(tmp_path, qgis_app):
    gen = _docked_with(tmp_path, PRESET)
    dock, _ = next(gen)
    for worker in (dock.refiner, dock.fill_worker):
        worker._executor.submit(lambda: None).result()  # start its thread
    threads = list(dock.refiner._executor._threads) + list(dock.fill_worker._executor._threads)
    assert len(threads) == 2
    gen.close()
    assert dock.refiner._closed and dock.fill_worker._closed
    assert not any(t.is_alive() for t in threads)


def test_a_quick_site_fill_draws_in_the_same_tick(site_quick, monkeypatch):
    from nsgeo_qgis.ui.fill_flow import FillFlow

    _, dock = site_quick
    seen: list[bool] = []
    real = FillFlow.working
    monkeypatch.setattr(
        FillFlow, "working", property(lambda self: seen.append(real.fget(self)) or real.fget(self))
    )
    changes = _watch_site(dock)
    dock.cell_spin.setValue(0.25)
    dock._debounce.stop()
    dock._apply_resolution()
    dock._site.tick.stop()
    dock._site.refresh_slice()
    assert [cell for cell, _ in changes] == [0.25], "drawn once, inside the same call"
    assert seen and not any(seen), "the flow was working, but a quick fill must not be"
    assert "fill" not in dock.refine_label.text()
    assert not dock.cancel_link.isVisibleTo(dock)
    _wait_idle(dock)


def test_the_site_stretch_lands_after_the_picture_and_redraws(site_slow):
    plugin, dock = site_slow
    legends: list[str] = []
    dock.slice_changed.connect(lambda: legends.append(dock.legend_label.text()))
    previous = dock.legend_label.text()
    _site_cell(dock, SITE_SLOW_CELL)
    assert spin_until(lambda: _applied_cell(dock) == SITE_SLOW_CELL and bool(legends), 60_000)
    assert legends[0] == previous, "the first draw uses the previous limit"
    site = dock._site
    z = dock.site_engine.site_z
    expected, _ = dock.site_engine.stretch_limit(
        levels_ns(site, z),
        UnipolarClip() if site.unipolar() else PercentileClip(),
        finish=dock.site_finish.value(),
        method=dock.normalisation_panel.method(),
        manual=site.gains(),
    )
    assert f"{expected:.3g}" not in previous, "the fixture must move the stretch"
    assert spin_until(lambda: f"{expected:.3g}" in dock.legend_label.text(), 30_000)
    _wait_idle(dock)
    assert len(legends) >= 2
    assert dock.display_limit() == pytest.approx(expected)


def levels_ns(site, z) -> float:
    from nsgeo_qgis.ui.site_scope import levels

    thickness, _ = levels(z, site.dock.thickness_spin.value(), site.dock.step_spin.value())
    return thickness * z.dz_ns


def test_a_failed_calibration_leaves_no_worker_threads(docked, monkeypatch):  # noqa: F811
    dock, _ = docked
    _ready(dock)
    monkeypatch.setattr(sys.modules[__name__], "MIN_SLOW_S", 1e9)
    monkeypatch.setattr(sys.modules[__name__], "_CALIBRATED", [])
    for worker in (dock.refiner, dock.fill_worker):
        worker._executor.submit(lambda: None).result()  # start its thread
    threads = list(dock.refiner._executor._threads) + list(dock.fill_worker._executor._threads)
    assert len(threads) == 2
    assert {t.name.split("_")[0] for t in threads} >= {"nsgeo-fill"}
    with pytest.raises(AssertionError, match="shrunk"):
        _calibrated(dock)
    assert not any(t.is_alive() for t in threads)
    assert dock.refiner._closed and dock.fill_worker._closed
    assert not [t for t in threading.enumerate() if t in threads]


# ---- the final review's wave (#193) ---------------------------------------
def _main_thread_builds(monkeypatch) -> tuple[list[bool], list[bool]]:
    """`build_fill`'s callers, as `(on the main thread, on a worker)` flags."""
    from nsgeo_qgis import slices_engine

    real = slices_engine.build_fill
    main: list[bool] = []
    worker: list[bool] = []

    def spy(*args, **kwargs):
        (main if threading.current_thread() is threading.main_thread() else worker).append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(slices_engine, "build_fill", spy)
    return main, worker


def test_a_grid_above_the_shown_depth_gets_its_fill_and_the_stretch_follows(
    fake_iface, site3_factory, answer_modal, monkeypatch
):
    """I1: C's axis ends above the shown depth. A thickness edit re-measures the
    shared stretch (it equals the synchronous one) and C's fill was made by a
    job, on the worker, not by the stretch job beside the old fill."""
    plugin = _open_short_c(fake_iface, site3_factory, answer_modal)
    try:
        dock = whole_site(plugin)
        site, scope = dock.site_engine, dock._site
        _, outside = _slider_with_and_without_c(dock)
        dock.slice_slider.setValue(outside)
        spin_until(lambda: False, 100)
        _wait_idle(dock)
        _site_cell(dock, 0.25)
        assert spin_until(lambda: _picture_cell(dock) == 0.25, 60_000)
        _wait_idle(dock)
        finish = dock.site_finish.value()
        assert site.engine_for("C").weights_cached(finish), "C has its fill for the new cell"
        dock.thickness_spin.setValue(dock.thickness_spin.value() + 2 * dock.dz_spin.value())
        z = site.site_z

        def current() -> bool:
            return scope.refine.held_stretch(scope.stretch_key(z)) is not None

        assert spin_until(current, 30_000), "the stretch for the new thickness never landed"
        _wait_idle(dock)
        thickness, _ = site_levels(z, dock.thickness_spin.value(), dock.step_spin.value())
        clip = UnipolarClip() if scope.unipolar() else PercentileClip()
        expected, _ = site.stretch_limit(
            thickness * z.dz_ns,
            clip,
            finish=finish,
            method=dock.normalisation_panel.method(),
            manual=scope.gains(),
        )
        assert dock.display_limit() == pytest.approx(expected)
    finally:
        _close(plugin, answer_modal)


def test_the_rest_builds_nothing_on_the_gui_thread_for_a_grid_above_the_depth(
    fake_iface, site3_factory, answer_modal, monkeypatch
):
    plugin = _open_short_c(fake_iface, site3_factory, answer_modal)
    try:
        dock = whole_site(plugin)
        _, outside = _slider_with_and_without_c(dock)
        dock.slice_slider.setValue(outside)
        spin_until(lambda: False, 100)
        _wait_idle(dock)
        main, worker = _main_thread_builds(monkeypatch)
        panel = dock.site_finish
        panel.method_combo.setCurrentIndex(panel.method_combo.findData("min_curvature"))
        _wait_for_refine(dock, 120.0)
        assert worker, "the plans were built on the fill worker"
        assert main == [], "a plan was built on the GUI thread"
        assert dock.site_engine.engine_for("C").weights_cached(dock.site_finish.value())
    finally:
        _close(plugin, answer_modal)


def test_a_site_tick_slices_each_grid_once(site_quick, monkeypatch):
    from nsgeo_qgis.slices_engine import SliceEngine

    _, dock = site_quick
    calls: list[int] = []
    real = SliceEngine.slice_at
    monkeypatch.setattr(SliceEngine, "slice_at", lambda self, w: calls.append(1) or real(self, w))
    dock._site.tick.stop()
    dock._site.refresh_slice()
    assert len(calls) == len(dock.site_engine.ready_grids), calls


def test_the_flow_lets_go_of_landed_fills(site_slow):
    _, dock = site_slow
    flow = dock.fill_flow
    _site_cell(dock, SITE_SLOW_CELL)
    assert spin_until(lambda: flow.working, 60_000)
    assert flow._fills
    _wait_idle(dock)
    assert flow._fills == [], "landed jobs (and the fills they hold) are kept"


def test_a_held_stretch_is_not_replaced_when_only_a_fill_is_missing(site_quick, monkeypatch):
    _, dock = site_quick
    site, scope = dock.site_engine, dock._site
    dock.display_limit()
    _wait_idle(dock)
    key = scope.stretch_key(site.site_z)
    held = scope.refine.held_stretch(key)
    assert held is not None
    jobs: list[int] = []
    real = site.stretch_job
    monkeypatch.setattr(site, "stretch_job", lambda *a, **k: jobs.append(1) or real(*a, **k))
    site.engine_for("A")._drop_fill()  # a fill is missing, the stretch's key is unchanged
    scope._run_tick()
    _wait_idle(dock)
    assert jobs == [], "a current stretch was measured again"
    assert scope.refine.held_stretch(key) == held


def test_the_cancel_link_tooltip_fits_a_cancel_with_and_without_a_picture(site_quick):
    _, dock = site_quick
    tip = dock.cancel_link.toolTip()
    assert "picture" in tip and "without one" in tip


def test_a_slider_move_mid_fill_never_makes_the_rest_build_the_grid_still_filling(
    fake_iface, site3_factory, answer_modal, monkeypatch
):
    """R1: A and B have landed, C (above the shown depth) is still on the worker; a
    slider move draws a preview and arms the rest, whose stretch solves would
    build C's plan on the GUI thread and refuse the worker's landing."""
    plugin = _open_short_c(fake_iface, site3_factory, answer_modal)
    try:
        dock = whole_site(plugin)
        _assert_slow_site(dock)
        flow, engine = dock.fill_flow, dock.site_engine
        _, outside = _slider_with_and_without_c(dock)
        dock.slice_slider.setValue(outside)
        spin_until(lambda: False, 100)
        _wait_idle(dock)
        panel = dock.site_finish
        panel.method_combo.setCurrentIndex(panel.method_combo.findData("min_curvature"))
        _wait_for_refine(dock, 120.0)
        main, worker = _main_thread_builds(monkeypatch)
        lands: list[tuple[str, bool]] = []
        real_land = FillJob.land
        monkeypatch.setattr(
            FillJob,
            "land",
            lambda self: lands.append((self.grid_id, real_land(self))) or lands[-1][1],
        )
        _site_cell(dock, SITE_SLOW_CELL)
        assert spin_until(lambda: flow.working and flow._landed >= 2, 120_000)
        assert flow._landed < flow._total, "C must still be filling"
        dock.slice_slider.setValue(min(dock.slice_slider.maximum(), outside + 1))
        dock._site.tick.stop()
        dock._site.refresh_slice()
        dock._site.refine.rest.stop()
        dock._site._on_rest()  # the rest ran out while C is still filling
        _wait_idle(dock)
        spin_until(lambda: False, 300)
        assert main == [], "the rest built a plan on the GUI thread"
        assert ("C", True) in lands, lands
        assert ("C", False) not in lands, lands
        assert engine.engine_for("C").weights_cached(dock.site_finish.value())
    finally:
        _close(plugin, answer_modal)


# ---- Task 6: the first draw's one-off work, in the background too (#193) -----
def _spy_footprints(monkeypatch, pause: float = 0.0) -> list[tuple[str, bool]]:
    """`(thread name, on the main thread)` of each `gather_footprint` call."""
    from nsgeo_qgis import site_geometry

    real = site_geometry.gather_footprint
    calls: list[tuple[str, bool]] = []

    def spy(*args, **kwargs):
        here = threading.current_thread()
        calls.append((here.name, here is threading.main_thread()))
        if pause:
            time.sleep(pause)
        return real(*args, **kwargs)

    monkeypatch.setattr(site_geometry, "gather_footprint", spy)
    return calls


def test_a_site_landing_builds_no_footprint_on_the_gui_thread(site_quick, monkeypatch):
    _, dock = site_quick
    calls = _spy_footprints(monkeypatch)
    _site_cell(dock, 0.15)
    assert spin_until(lambda: _picture_cell(dock) == 0.15, 60_000)
    _wait_idle(dock)
    assert calls, "no footprint was built for the new lattice"
    assert not [c for c in calls if c[1]], f"a footprint was built on the GUI thread: {calls}"
    assert all(name.startswith("nsgeo-fill") for name, _ in calls), calls
    site = dock.site_engine
    assert set(site._gathers) == set(site.ready_grids)


def test_a_footprint_for_a_stale_lattice_never_lands(site_quick, monkeypatch):
    from nsgeo_qgis.site_engine import SiteEngine

    _, dock = site_quick
    on_worker = threading.Event()
    from nsgeo_qgis import site_geometry

    real = site_geometry.gather_footprint

    def slow_gather(*args, **kwargs):
        if threading.current_thread() is not threading.main_thread():
            on_worker.set()
            time.sleep(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(site_geometry, "gather_footprint", slow_gather)
    lands: list[tuple[float, bool]] = []
    real_land = SiteEngine._land_footprint

    def land_spy(self, job):
        ok = real_land(self, job)
        lands.append((job.lattice.pixel, ok))
        return ok

    monkeypatch.setattr(SiteEngine, "_land_footprint", land_spy, raising=False)
    _site_cell(dock, 0.15)
    assert spin_until(on_worker.is_set, 30_000), "the footprints never ran on a worker"
    first_pixel = dock.site_engine.lattice.pixel
    _site_cell(dock, 0.25)
    assert spin_until(lambda: _picture_cell(dock) == 0.25, 60_000)
    _wait_idle(dock)
    assert (first_pixel, True) not in lands, lands
    assert _applied_cell(dock) == 0.25
    site = dock.site_engine
    assert set(site._gathers) == set(site.ready_grids)


def test_a_failed_footprint_shows_the_error_and_no_stale_picture(site_quick, monkeypatch):
    """#236: a footprint that failed on the worker read "could not work out the
    fill", kept the picture of the old lattice and set no error readout. It is
    shown as a failed draw is: the error on the readout, nothing on the map."""
    from nsgeo_qgis import site_geometry

    _, dock = site_quick
    real = site_geometry.gather_footprint

    def failing(*args, **kwargs):
        if threading.current_thread() is not threading.main_thread():
            raise ValueError("no transform")
        return real(*args, **kwargs)

    monkeypatch.setattr(site_geometry, "gather_footprint", failing)
    errors: list[str] = []
    dock.error.connect(errors.append)
    _site_cell(dock, 0.15)
    assert spin_until(lambda: bool(errors), 60_000), "the failure was never reported"
    _wait_idle(dock)
    assert errors == ["could not place the grids on the map: ValueError: no transform"]
    assert dock.readout.text() == f"error: {errors[0]}"
    assert dock.current_site_slice() is None, "the old lattice's picture stayed"
    assert not dock.cancel_link.isVisibleTo(dock)


def test_this_grids_first_north_up_plan_is_built_on_the_worker(
    fake_iface, site3, answer_modal, monkeypatch
):
    from nsgeo.slices import display

    plugin = _open(fake_iface, site3, answer_modal)
    try:
        dock = plugin.slices_dock
        builds: list[tuple[float, str]] = []
        real = display._build_north_up_plan

        def spy(frame):
            builds.append((frame.cell, threading.current_thread().name))
            return real(frame)

        monkeypatch.setattr(display, "_build_north_up_plan", spy)
        display.clear_north_up_plans()
        changed: list[int] = []
        dock.slice_changed.connect(lambda: changed.append(1))
        _edit_cell(dock, 0.03)
        assert spin_until(
            lambda: (
                dock.engine.frame is not None
                and dock.engine.frame.cell == 0.03
                and dock.current_frame() is not None
                and dock.current_frame().cell == 0.03
            ),
            60_000,
        )
        _wait_idle(dock)
        spin_until(lambda: False, 200)
        mine = [name for cell, name in builds if cell == 0.03]
        assert mine, "the plan for the new frame was never built"
        assert all(name.startswith("nsgeo-fill") for name in mine), builds
    finally:
        _close(plugin, answer_modal)


def test_ticking_coverage_mid_fill_never_restarts_the_work(site_slow):
    """Coverage needs no fills, only footprints: a coverage draw while the
    flow works must leave the running list alone (a request of another key
    would cancel it and restart the grid in flight)."""
    _, dock = site_slow
    flow = dock.fill_flow
    _site_cell(dock, SITE_SLOW_CELL)
    assert spin_until(lambda: flow.working and flow._landed >= 1, 60_000)
    jobs = [id(job) for job in flow._fills]
    assert len(jobs) == 6
    dock.coverage_check.setChecked(True)
    dock._site.tick.stop()
    dock._site.refresh_slice()
    dock._site.refresh_slice()
    assert [id(job) for job in flow._fills] == jobs, "the coverage tick restarted the work"
    assert spin_until(lambda: not flow.working, 120_000)
    _wait_idle(dock)
    site = dock.site_engine
    assert set(site._gathers) == set(site.ready_grids)
