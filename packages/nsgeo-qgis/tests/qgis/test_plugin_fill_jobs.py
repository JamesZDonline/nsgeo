"""Fill jobs: built on a worker, landed only where the engine still wants them (#193)."""

from __future__ import annotations

import threading

import numpy as np
import pytest
from nsgeo.slices import SliceWindow, SolveStopped
from nsgeo_qgis import slices_engine
from nsgeo_qgis.slices_plan import Resolution, SliceFinish, SourceChoice
from plugin_testing import spin_until
from test_plugin_slices_dock import _docked_with
from test_plugin_slices_engine import PRESET, _prepare, sourced  # noqa: F401 -- fixture

METHODS = ["idw", "kriging", "min_curvature"]


def _finish(method: str) -> SliceFinish:
    return SliceFinish(method=method)


@pytest.mark.parametrize("method", METHODS)
def test_a_fill_job_builds_what_fill_for_builds(sourced, monkeypatch, method):  # noqa: F811
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, cov = engine.slice_at(SliceWindow(4, 14))
    finish = _finish(method)
    expected = engine.finish(values, cov, finish)
    expected_preview = engine.preview(values, cov, finish) if method == "min_curvature" else None
    engine._drop_fill()
    assert not engine.fill_held(cov, finish)
    job = engine.fill_job(cov, finish)
    job.run(lambda: False)
    assert job.fraction == 1.0
    assert job.land() is True
    assert engine.fill_held(cov, finish)
    calls = []
    real = slices_engine.plan_fill
    monkeypatch.setattr(
        slices_engine, "plan_fill", lambda *a, **k: calls.append(1) or real(*a, **k)
    )
    assert np.array_equal(engine.finish(values, cov, finish), expected, equal_nan=True)
    assert calls == []
    if expected_preview is not None:
        assert np.array_equal(engine.preview(values, cov, finish), expected_preview, equal_nan=True)
        assert calls == []


def _held_job(engine, session):
    _prepare(engine, session)
    _, cov = engine.slice_at(SliceWindow(4, 14))
    finish = _finish("idw")
    job = engine.fill_job(cov, finish)
    job.run(lambda: False)
    return job, cov, finish


def _frame_changes(engine, session, cov, finish):
    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))


def _new_source(engine, session, cov, finish):
    engine.set_source(
        SourceChoice(
            grid_id="A",
            preset="p",
            transform="amp_envelope",
            line_keys=tuple(session.keys())[:2],
        )
    )


def _cleared(engine, session, cov, finish):
    engine.clear()


def _disposed(engine, session, cov, finish):
    engine.dispose()


def _another_job(engine, session, cov, finish):
    engine.fill_job(cov, finish)


@pytest.mark.parametrize("move", [_frame_changes, _new_source, _cleared, _disposed, _another_job])
def test_a_fill_job_lands_nowhere_after_its_engine_moved_on(sourced, move):  # noqa: F811
    engine, session, _, _ = sourced
    job, cov, finish = _held_job(engine, session)
    move(engine, session, cov, finish)
    assert job.land() is False
    assert engine._weights is None


def test_a_dz_edit_keeps_a_running_job_landable(sourced):  # noqa: F811
    engine, session, _, _ = sourced
    job, cov, finish = _held_job(engine, session)
    engine.set_resolution(Resolution(cell=0.25, dz_ns=1.0, t0_ns=2.0, t1_ns=30.0))
    assert job.land() is True


def test_a_stopped_fill_job_raises_and_holds_nothing(sourced):  # noqa: F811
    engine, session, _, _ = sourced
    _prepare(engine, session)
    _, cov = engine.slice_at(SliceWindow(4, 14))
    finish = _finish("min_curvature")
    job = engine.fill_job(cov, finish)
    with pytest.raises(SolveStopped):
        job.run(lambda: True)
    assert job.fill is None
    assert job.land() is False
    assert not engine.fill_held(cov, finish)


def test_the_fill_worker_names_its_threads(qgis_app, tmp_path):
    gen = _docked_with(tmp_path, PRESET)
    dock, session = next(gen)
    try:
        engine = dock.engine
        _prepare(engine, session)
        _, cov = engine.slice_at(SliceWindow(4, 14))
        job = engine.fill_job(cov, _finish("idw"))
        names: list[str] = []
        real_run = job.run

        def run(should_stop):
            names.append(threading.current_thread().name)
            real_run(should_stop)

        job.run = run  # type: ignore[method-assign]
        landed: list = []
        dock.fill_worker.start([job], landed.append, lambda m: None)
        assert spin_until(lambda: landed, 5000)
        assert names[0].startswith("nsgeo-fill")
    finally:
        gen.close()


def test_a_min_curvature_job_reports_the_plan_then_the_preview(sourced):  # noqa: F811
    engine, session, _, _ = sourced
    _prepare(engine, session)
    _, cov = engine.slice_at(SliceWindow(4, 14))
    job = engine.fill_job(cov, _finish("min_curvature"))
    seen: list[tuple[str, float]] = []
    original = slices_engine.plan_fill

    def spy(populated, cell, method, md, sr, *, should_stop=None, progress=None):
        def tap(p):
            progress(p)
            seen.append((method, job.fraction))

        return original(populated, cell, method, md, sr, should_stop=should_stop, progress=tap)

    slices_engine.plan_fill = spy
    try:
        job.run(lambda: False)
    finally:
        slices_engine.plan_fill = original
    plan = [f for m, f in seen if m == "min_curvature"]
    kriging = [f for m, f in seen if m == "kriging"]
    assert plan and kriging
    assert max(plan) <= 0.7 + 1e-9
    assert min(kriging) >= 0.7 - 1e-9
    assert job.fraction == 1.0


def test_a_refused_landing_lets_go_of_the_fill(sourced):  # noqa: F811
    engine, session, _, _ = sourced
    job, cov, finish = _held_job(engine, session)
    engine.clear()
    assert job.land() is False
    assert job.fill is None and job.preview is None
