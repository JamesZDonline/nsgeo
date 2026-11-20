"""This grid's fill and stretch worked out in the background, with Cancel (#193).

The dock on a synthetic grid at a cell fine enough that the interpolation fill
takes seconds. `SLOW_CELL` is calibrated once (`_assert_slow`) so the hazard
cannot silently shrink: on a CI-class core the fill takes about 2 s; this
machine, loaded by other sessions, measured 2.0 to 2.2 s. The fixture asserts at
least 1.5 s here.
"""

from __future__ import annotations

import time

import pytest
from nsgeo.render import PercentileClip, UnipolarClip
from nsgeo_qgis.fill_jobs import FillJob
from nsgeo_qgis.slices_plan import (
    FILL_BUDGET_S,
    FILL_CANCELLED_NOTE,
    FILL_WORKING_GRIDS_INDICATOR,
    FILL_WORKING_INDICATOR,
    STRETCH_WORKING_INDICATOR,
    Resolution,
    SliceFinish,
)
from nsgeo_qgis.stretch_jobs import StretchJob
from nsgeo_qgis.ui.warnings_panel import NOTE
from plugin_testing import (
    LayoutProbe,
    connect_message_log,
    layout_width,
    slow_jobs,
    spin_until,
    wait_for_site,
)
from qgis.PyQt.QtCore import QCoreApplication, QTimer
from qgis.PyQt.QtWidgets import QMessageBox
from test_plugin_site_scope import _close, _open
from test_plugin_slices_dock import (  # noqa: F401 -- fixture
    PRESET,
    _docked_with,
    _ready,
    _set_finish,
    docked,
)

SLOW_CELL = 0.017
QUICK_CELL = 0.1
MID_CELL = 0.025
MIN_SLOW_S = 1.5
GAP_LIMIT_S = 0.25

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
    anything. SLOW_CELL takes at least MIN_SLOW_S: the brief asked for 2 s on
    CI, and this loaded machine measures 1.9 to 2.2 s, so 1.5 s keeps the check
    from flaking while a fast runner still fails loudly. MID_CELL must exceed
    twice the 0.2 s budget, or the cancel tests would draw it in the same tick
    and pass vacuously."""
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
    _assert_slow(dock)
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
    assert dock.fill_flow.working, "the fill is still going"
    assert any(asked), "a stretch was asked for while the fill ran"
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
        _assert_slow(dock)
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


class FakeStretch(StretchJob):
    def __init__(self, limit: float | None, final: bool = True, pause: float = 0.0) -> None:
        self.limit = limit
        self.final = final
        self.pause = pause
        self.fraction = 0.0

    def run(self, should_stop) -> None:
        time.sleep(self.pause)
        self.fraction = 1.0

    def land(self) -> bool:
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
