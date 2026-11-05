"""The refine worker: one background thread, results handed back on the GUI
thread (plan call 6). Jobs here are small fakes, so none of this depends on
the slices engine; the responsiveness test uses a real solve."""

from __future__ import annotations

import threading
import time

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
        self.started = threading.Event()
        self.returned = threading.Event()

    def run(self, should_stop):
        self.ran = True
        self.thread_name = threading.current_thread().name
        self.started.set()
        try:
            if self.error is not None:
                raise self.error
            if self.gate is not None:
                self.gate.wait(5)
            deadline = time.monotonic() + 5  # a cancel regression must not hang the suite
            while self.loop and not should_stop() and time.monotonic() < deadline:
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
    assert errors == ["no good"]
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
    worker = next(t for t in threading.enumerate() if t.name == looping.thread_name)
    refiner.shutdown()
    assert not worker.is_alive()  # joined, not merely asked to stop
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


def test_an_unrequested_solve_stop_is_reported(refiner):
    errors, landed = [], []
    refiner.start([Job("s", error=SolveStopped())], landed.append, errors.append)
    _pump_until(lambda: errors)
    assert len(errors) == 1 and errors[0]
    assert landed == []
    assert not refiner.busy


def test_a_base_exception_still_ends_the_list(refiner):
    errors = []
    refiner.start([Job("m", error=MemoryError())], lambda j: None, errors.append)
    _pump_until(lambda: errors)
    assert errors == ["MemoryError"]
    assert not refiner.busy


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
    job = SolveJob()  # planning is not the worker's, so it is outside the timing
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    landed, errors = [], []
    t0 = time.monotonic()
    refiner.start([job], landed.append, errors.append)
    _pump_until(lambda: landed or errors, 30)
    assert errors == []
    timer.stop()
    elapsed = time.monotonic() - t0
    print(f"solve {elapsed:.2f} s, {len(ticks)} ticks")
    assert job.result is not None
    assert len(ticks) >= 10
