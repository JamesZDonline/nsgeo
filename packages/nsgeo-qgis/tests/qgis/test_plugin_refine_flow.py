"""RefineFlow: the rules both scopes' refines follow (plan calls 5 and 7).

A fake refiner and fake jobs, so each rule is pinned on its own; the
scopes' tests drive the same rules through real solves.
"""

from __future__ import annotations

import pytest
from nsgeo_qgis.ui.refine_flow import RefineFlow
from qgis.PyQt.QtCore import QObject


class _Refiner:
    def __init__(self) -> None:
        self.busy = False
        self.cancels = 0
        self.started: list[list] = []

    def start(self, jobs, on_landed, on_error) -> None:
        self.cancel()
        self.started.append(list(jobs))
        self.busy = bool(jobs)

    def cancel(self) -> None:
        self.cancels += 1
        self.busy = False


class _Engine:
    """Holds one plan at a time, as `SliceEngine` does."""

    def __init__(self) -> None:
        self.plan = object()

    def holds(self, plan) -> bool:
        return plan is self.plan


class _Job:
    def __init__(self, engine: _Engine, key: bytes) -> None:
        self.engine = engine
        self.plan = engine.plan
        self.key = key

    def land(self) -> bool:
        return self.engine.holds(self.plan)


@pytest.fixture
def flow(qgis_app):
    parent = QObject()
    refiner = _Refiner()
    flow = RefineFlow(parent, refiner, lambda: None)  # type: ignore[arg-type]
    yield flow, refiner
    flow.rest.stop()


def _running(flow, refiner, jobs) -> None:
    """A preview of `jobs`' slices, rested: the list runs with them at its head."""
    flow.previewed((job.engine, job.key) for job in jobs)
    flow.rested(jobs, [], lambda job: None, lambda message: None)
    flow.rest.stop()
    assert refiner.busy


def test_a_preview_waiting_for_exactly_the_head_keeps_the_list(flow):
    flow, refiner = flow
    a, b = _Engine(), _Engine()
    jobs = [_Job(a, b"a"), _Job(b, b"b")]
    _running(flow, refiner, jobs)
    cancels = refiner.cancels
    flow.previewed([(a, b"a"), (b, b"b")])
    assert refiner.busy and refiner.cancels == cancels
    assert not flow.rest.isActive()
    # One landed: the redraw waits for the rest of the head, which runs on.
    flow.landed(jobs[0])
    flow.previewed([(b, b"b")])
    assert refiner.busy and refiner.cancels == cancels


@pytest.mark.parametrize(
    "case", ["another window", "a grid left", "a plan dropped", "a solve landed elsewhere"]
)
def test_any_other_preview_cancels_the_list_and_restarts_the_rest(flow, case):
    flow, refiner = flow
    a, b = _Engine(), _Engine()
    _running(flow, refiner, [_Job(a, b"a"), _Job(b, b"b")])
    if case == "another window":
        awaited = [(a, b"a2"), (b, b"b2")]
    elif case == "a grid left":
        awaited = [(a, b"a")]
    elif case == "a plan dropped":
        a.plan = object()  # a finish edit: the same values, so the same key
        awaited = [(a, b"a"), (b, b"b")]
    else:
        awaited = [(b, b"b")]  # a's slice was solved by an export meanwhile
    flow.previewed(awaited)
    assert not refiner.busy
    assert flow.rest.isActive()
    assert flow.provisional


def test_a_draw_that_rebuilds_cancels_the_list_first(flow):
    flow, refiner = flow
    a = _Engine()
    _running(flow, refiner, [_Job(a, b"a")])
    flow.before_draw(rebuilds=False)
    assert refiner.busy
    flow.before_draw(rebuilds=True)
    assert not refiner.busy
    # The draw that follows decides the rest: the same window previews anew.
    flow.previewed([(a, b"a")])
    assert flow.rest.isActive()


def test_a_rest_queues_each_solve_once_telling_grids_apart_by_engine(flow):
    """Two grids can hold equal values: the same key on two engines is two
    solves, and the same solve queued as the slice's and a stretch window's
    is one."""
    flow, refiner = flow
    a, b = _Engine(), _Engine()
    current = [_Job(a, b"same"), _Job(b, b"same")]
    stretch = [_Job(a, b"same"), _Job(a, b"other")]
    flow.previewed((job.engine, job.key) for job in current)
    assert flow.rested(current, stretch, lambda job: None, lambda message: None) is False
    assert refiner.started == [[current[0], current[1], stretch[1]]]
    assert flow.total == 3
