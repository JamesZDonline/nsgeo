"""The refine worker: one background thread, results handed back on the GUI
thread (plan call 6). Jobs here are small fakes, so none of this depends on
the slices engine; the responsiveness test uses a real solve."""

from __future__ import annotations

import gc
import queue
import threading
import time
import weakref

import numpy as np
import pytest
from nsgeo.slices import SolveStopped, plan_curvature
from nsgeo_qgis import refine as refine_module
from nsgeo_qgis.refine import Refiner
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication, QObject, QTimer


class Job:
    """Records where it ran; optionally blocks, loops or raises."""

    def __init__(self, name="job", *, gate=None, loop=False, error=None):
        self.name = name
        self.gate = gate
        self.loop = loop
        self.error = error
        self.ran = False
        self.thread_name = None
        self.thread = None
        self.stopped_by_request = False
        self.started = threading.Event()
        self.returned = threading.Event()

    def run(self, should_stop):
        self.ran = True
        self.thread = threading.current_thread()
        self.thread_name = self.thread.name
        self.started.set()
        try:
            if self.error is not None:
                raise self.error
            if self.gate is not None:
                self.gate.wait(5)
            deadline = time.monotonic() + 5  # a cancel regression must not hang the suite
            while self.loop and time.monotonic() < deadline:
                if should_stop():
                    self.stopped_by_request = True
                    break
                time.sleep(0.001)
        finally:
            self.returned.set()


def _pump_until(predicate, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() > deadline:
            pytest.fail("timed out waiting for the condition")
        QCoreApplication.processEvents()
        time.sleep(0.002)


def _pump_for(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.002)


@pytest.fixture
def refiner(qgis_app):
    parent = QObject()
    r = Refiner(parent)
    yield r
    r.shutdown()
    del parent


def test_jobs_land_in_order_on_the_gui_thread(refiner):
    jobs = [Job("a"), Job("b"), Job("c")]
    landed, errors = [], []
    refiner.start(
        jobs,
        lambda j: landed.append((j, threading.current_thread())),
        errors.append,
    )
    _pump_until(lambda: len(landed) == 3)
    assert errors == []
    assert [j for j, _ in landed] == jobs
    assert all(j.thread_name.startswith("nsgeo-refine") for j in jobs)
    assert all(t is threading.main_thread() for _, t in landed)


def test_a_custom_thread_name_prefix_names_the_thread(qgis_app):
    parent = QObject()
    worker = Refiner(parent, thread_name_prefix="nsgeo-cut")
    try:
        job, landed = Job("a"), []
        worker.start([job], landed.append, lambda m: None)
        _pump_until(lambda: landed)
        assert job.thread_name.startswith("nsgeo-cut")
    finally:
        worker.shutdown()
        del parent


def test_busy_is_false_when_the_last_job_lands(refiner):
    jobs = [Job("a"), Job("b")]
    busy_at_landing = []
    refiner.start(jobs, lambda j: busy_at_landing.append(refiner.busy), lambda m: None)
    assert refiner.busy
    _pump_until(lambda: len(busy_at_landing) == 2)
    assert busy_at_landing == [True, False]
    assert not refiner.busy


def test_cancel_stops_the_running_job_and_drops_the_rest(refiner):
    looping, after = Job("loop", loop=True), Job("after")
    landed = []
    refiner.start([looping, after], landed.append, lambda m: None)
    assert looping.started.wait(2)
    refiner.cancel()
    assert looping.returned.wait(1)
    assert not refiner.busy
    _pump_for(0.15)
    assert landed == []
    assert not after.ran


def test_a_new_start_supersedes_the_old_one(refiner):
    gate = threading.Event()
    a1, a2 = Job("a1", gate=gate), Job("a2")
    b1, b2 = Job("b1"), Job("b2")
    landed = []
    refiner.start([a1, a2], landed.append, lambda m: None)
    assert a1.started.wait(2)
    refiner.start([b1, b2], landed.append, lambda m: None)
    gate.set()
    _pump_until(lambda: len(landed) == 2)
    _pump_for(0.1)
    assert landed == [b1, b2]
    assert not a2.ran


def test_only_one_job_runs_at_a_time(refiner):
    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    class Counting:
        def run(self, should_stop):
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.01)
            with lock:
                state["now"] -= 1

    landed = []
    for _ in range(5):
        refiner.start([Counting(), Counting()], landed.append, lambda m: None)
    _pump_until(lambda: not refiner.busy and len(landed) >= 2)
    _pump_for(0.1)
    assert state["max"] == 1


def test_a_job_error_is_reported_not_raised(refiner):
    bad, after = Job("bad", error=ValueError("no good")), Job("after")
    errors, landed = [], []
    refiner.start([bad, after], landed.append, errors.append)
    _pump_until(lambda: errors)
    _pump_for(0.1)
    assert errors == ["ValueError: no good"]
    assert landed == []
    assert not after.ran
    assert not refiner.busy


def test_a_raising_on_landed_is_contained(refiner, monkeypatch):
    logged = []
    monkeypatch.setattr(refine_module, "_log", logged.append)
    jobs = [Job("a"), Job("b")]
    landed = []

    def on_landed(job):
        landed.append(job)
        if job is jobs[0]:
            raise RuntimeError("landing failed")

    refiner.start(jobs, on_landed, lambda m: None)
    _pump_until(lambda: len(landed) == 2)
    assert landed == jobs
    assert any("landing failed" in m for m in logged)
    assert not refiner.busy


def _refine_threads():
    return [t for t in threading.enumerate() if t.name.startswith("nsgeo-refine")]


def test_shutdown_joins_the_worker(refiner):
    looping = Job("loop", loop=True)
    refiner.start([looping], lambda j: None, lambda m: None)
    assert looping.started.wait(2)
    t0 = time.monotonic()
    refiner.shutdown()
    assert time.monotonic() - t0 < 1.0  # cancelled, not left to run out its bound
    assert looping.stopped_by_request
    assert not looping.thread.is_alive()  # joined, not merely asked to stop
    assert _refine_threads() == []
    refiner.shutdown()


def test_shutdown_survives_a_deleted_parent_and_ends_starts(qgis_app):
    parent = QObject()
    r = Refiner(parent)
    sip.delete(parent)
    r.shutdown()
    r.shutdown()
    job = Job("late")
    r.start([job], lambda j: None, lambda m: None)
    assert not r.busy
    time.sleep(0.05)
    assert not job.ran


def test_a_start_after_the_parent_is_deleted_is_a_no_op(qgis_app):
    parent = QObject()
    r = Refiner(parent)
    sip.delete(parent)
    job = Job("late")
    r.start([job], lambda j: None, lambda m: None)
    assert not r.busy
    time.sleep(0.05)
    assert not job.ran
    r.shutdown()


def test_a_start_after_the_parent_is_deleted_stops_the_running_list(qgis_app, monkeypatch):
    """With its poll gone, nothing the list solves could land, and each job
    holds its plan: the ignored start stops it all the same."""
    logged = []
    monkeypatch.setattr(refine_module, "_log", logged.append)
    parent = QObject()
    r = Refiner(parent)
    looping = Job("loop", loop=True)
    r.start([looping], lambda j: None, lambda m: None)
    assert looping.started.wait(2)
    sip.delete(parent)
    r.start([Job("late")], lambda j: None, lambda m: None)
    assert looping.returned.wait(1)
    assert looping.stopped_by_request
    assert not r.busy
    assert len(logged) == 1 and "deleted" in logged[0]
    assert "shut down" not in logged[0], "the worker was not shut down"
    r.shutdown()
    r.start([Job("later")], lambda j: None, lambda m: None)
    assert "shut down" in logged[-1]


def test_an_unrequested_solve_stop_is_reported(refiner):
    errors, landed = [], []
    refiner.start([Job("s", error=SolveStopped())], landed.append, errors.append)
    _pump_until(lambda: errors)
    assert len(errors) == 1 and errors[0]
    assert landed == []
    assert not refiner.busy


def test_an_error_with_no_message_is_reported_by_its_type(refiner):
    errors = []
    refiner.start([Job("m", error=MemoryError())], lambda j: None, errors.append)
    _pump_until(lambda: errors)
    assert errors == ["MemoryError"]
    assert not refiner.busy


def test_an_error_is_reported_with_its_type(refiner):
    """A KeyError's message is only the key, which names nothing."""
    errors = []
    refiner.start([Job("k", error=KeyError("k"))], lambda j: None, errors.append)
    _pump_until(lambda: errors)
    assert errors == ["KeyError: 'k'"]
    assert not refiner.busy


class Fatal(BaseException):
    """Not an Exception, as KeyboardInterrupt and SystemExit are not."""


class Unprintable(Exception):
    def __init__(self, raises):
        super().__init__()
        self.raises = raises

    def __str__(self):
        raise self.raises("no message")


@pytest.mark.parametrize("raises", [RuntimeError, Fatal])
def test_an_error_that_cannot_be_printed_still_ends_the_list(refiner, raises):
    errors, landed = [], []
    refiner.start([Job("u", error=Unprintable(raises))], landed.append, errors.append)
    _pump_until(lambda: errors)
    assert errors == ["Unprintable"]
    assert not refiner.busy
    _pump_until(lambda: not refiner._poll.isActive())
    after = Job("after")
    refiner.start([after], landed.append, errors.append)
    _pump_until(lambda: landed)
    assert landed == [after]


def test_a_base_exception_still_ends_the_list(refiner):
    errors, landed = [], []
    refiner.start([Job("f", error=Fatal("boom"))], landed.append, errors.append)
    _pump_until(lambda: errors)
    assert errors == ["Fatal: boom"]
    assert not refiner.busy
    _pump_until(lambda: not refiner._poll.isActive())
    after = Job("after")
    refiner.start([after], landed.append, errors.append)
    _pump_until(lambda: landed)
    assert landed == [after]


def _released(ref):
    gc.collect()
    return ref() is None


class GatedPut:
    """The worker's queue with a `put` held until `gate` opens: a stop that
    lands after the worker's own stop check and before its put. The worker
    skips the put for a stop it sees, so only this race leaves a late
    entry, and the poll and `shutdown` must still let go of it."""

    def __init__(self, hold=lambda item: True):
        self.queue = queue.SimpleQueue()
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.hold = hold

    def put(self, item):
        if self.hold(item):
            self.entered.set()
            self.gate.wait(5)
        self.queue.put(item)

    def get_nowait(self):
        return self.queue.get_nowait()


def test_a_job_that_finishes_as_it_is_cancelled_is_let_go(refiner):
    """It can never land, and a real job holds its values and plan (about
    220 MB at the frame cap): it must not wait in the queue for the next
    list."""
    refiner._done = gated = GatedPut()
    held = [Job("late")]
    ref = weakref.ref(held[0])
    refiner.start([held.pop()], lambda j: None, lambda m: None)
    assert gated.entered.wait(2)  # past its stop check
    refiner.cancel()
    _pump_for(0.1)  # the poll ticks while the put is held
    gated.gate.set()
    _pump_until(lambda: _released(ref), 2)
    assert not refiner.busy


def test_a_list_started_from_a_landing_still_lets_go_of_its_late_job(refiner):
    """The poll's "worker idle" is read for one list; a landing that starts
    another in the same drain must not let that reading stop the poll
    while the new list still runs (#120 review)."""
    held = [Job("late")]
    ref = weakref.ref(held[0])
    refiner._done = gated = GatedPut(
        hold=lambda item: item[1] is not None and item[1].name == "late"
    )
    first, quick = Job("first"), Job("quick")
    landed = []

    def on_quick(job):
        landed.append(job)
        refiner.cancel()  # as a preview for another window does

    def on_first(job):
        refiner.start([quick, held.pop()], on_quick, lambda m: None)
        gated.entered.wait(2)  # `quick` is queued, so it lands in this same drain

    refiner.start([first], on_first, lambda m: None)
    time.sleep(0.05)  # `first`'s list has ended before the first drain
    _pump_until(lambda: landed)
    assert landed == [quick]
    _pump_for(0.1)
    gated.gate.set()
    _pump_until(lambda: _released(ref), 2)
    assert not refiner.busy


def test_a_job_stopped_with_its_panel_deleted_is_let_go(qgis_app):
    """With the panel gone there is no poll to drain the queue, so a job
    whose list was stopped is not queued at all."""
    parent = QObject()
    r = Refiner(parent)
    gate = threading.Event()
    held = [Job("late", gate=gate)]  # ignores should_stop: it finishes, not raises
    ref, returned, started = weakref.ref(held[0]), held[0].returned, held[0].started
    r.start([held.pop()], lambda j: None, lambda m: None)
    assert started.wait(2)
    sip.delete(parent)
    r.start([], lambda j: None, lambda m: None)  # ignored, and stops the list
    gate.set()
    assert returned.wait(2)
    deadline = time.monotonic() + 2
    while not _released(ref) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _released(ref)
    r.shutdown()


def test_shutdown_lets_go_of_what_the_stopped_list_queued(refiner):
    refiner._done = gated = GatedPut()
    held = [Job("late")]
    ref = weakref.ref(held[0])
    refiner.start([held.pop()], lambda j: None, lambda m: None)
    assert gated.entered.wait(2)  # past its stop check
    threading.Timer(0.05, gated.gate.set).start()  # shutdown joins the worker
    refiner.shutdown()
    assert _released(ref)


TICK_MS = 10


class SolveJob:
    """A real minimum-curvature solve, about half a second."""

    def __init__(self):
        n = 500
        cell = 0.1
        pop = np.zeros((n, n), bool)
        pop[2::5, :] = True  # rows centred 0.25 m + k * 0.5 m
        yy, xx = np.indices((n, n))
        self.values = (np.sin(xx * 0.02) + np.cos(yy * 0.03)).astype(np.float32)
        self.plan = plan_curvature(pop, cell, 0.375)
        self.result = None

    def run(self, should_stop):
        self.result = self.plan.solve(self.values, should_stop)


def test_the_gui_thread_keeps_running_during_a_solve(refiner):
    """The solve leaves the GIL to the GUI thread (numpy releases it), so a
    10 ms timer keeps ticking at about its rate. Measured against the time
    taken, not a fixed count, which a faster solve would make unreachable
    and a slower one easy (#120). The solve ticks at about 0.99 of the rate;
    a pure-Python job, which shares the GIL, at 0.43 to 0.51, and one that
    holds it in a single C call at about 0.1."""
    job = SolveJob()  # planning is not the worker's, so it is outside the timing
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(TICK_MS)
    landed, errors = [], []
    t0 = time.monotonic()
    refiner.start([job], landed.append, errors.append)
    _pump_until(lambda: landed or errors, 30)
    assert errors == []
    timer.stop()
    elapsed = time.monotonic() - t0
    expected = elapsed * 1000.0 / TICK_MS
    print(f"solve {elapsed:.2f} s, {len(ticks)} of {expected:.0f} ticks")
    assert job.result is not None
    assert expected >= 10, "the solve is too quick to tell anything"
    assert len(ticks) >= 0.75 * expected
