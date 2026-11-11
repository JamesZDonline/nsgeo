"""The export as a background task: it runs, cancels, fails and finishes safely.

The pipeline and the overview build are replaced with small fakes so the tests
are about the task (threads, the holder, cancellation, the two partial files),
not about pixels; the pixels are pinned in the pipeline and writer tests.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from nsgeo_qgis import export_task
from nsgeo_qgis.export_pipeline import ExportBand, ExportCancelled
from nsgeo_qgis.export_task import (
    ExportResult,
    ExportTask,
    WriterPlan,
    running_export,
    start_export,
)
from nsgeo_qgis.slice_export import partial_path
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QCoreApplication, QThreadPool

TIMEOUT = 20.0


def _wait(predicate: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + TIMEOUT
    while not predicate():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        QCoreApplication.processEvents()
        time.sleep(0.005)


class FakeWriter:
    """Writes a marker file at the partial path, one write per band, and records calls."""

    def __init__(self, tag: bytes, fail_at: int | None = None) -> None:
        self.tag = tag
        self.fail_at = fail_at
        self.threads: list[str] = []

    def write_bands(self, path, plan, bands, *, clip, progress_band=None) -> float:
        self.threads.append(threading.current_thread().name)
        done = 0
        with open(path, "wb") as handle:
            handle.write(self.tag)
            for _band in bands:
                done += 1
                if self.fail_at == done:
                    raise RuntimeError("the writer broke")
                if progress_band is not None:
                    progress_band(done)
        return 2.5 if self.tag == b"values" else 7.5


@pytest.fixture
def fake_run(monkeypatch):
    """`run_export` yields `n` bands, polling `should_stop` like the real one."""
    state = SimpleNamespace(n=3, hook=None, specs=[])

    def run(spec, *, should_stop, progress):
        state.specs.append(spec)
        for k in range(state.n):
            if should_stop():
                raise ExportCancelled()
            progress(k, state.n, f"grid-{k}")
            if state.hook is not None:
                state.hook(spec, k)
            yield ExportBand(np.zeros((2, 2), np.float32), {})

    monkeypatch.setattr(export_task, "run_export", run)
    monkeypatch.setattr(export_task, "build_overviews", lambda path, should_stop=None: None)
    return state


@pytest.fixture(autouse=True)
def _nothing_held():
    yield
    task = running_export()
    if task is not None:
        task.cancel()
        _wait(lambda: running_export() is None, "the held task to end")


def _make(tmp_path, on_done, *, coverage=True, writer=None, cov_writer=None, **kw):
    target = tmp_path / "out.tif"
    cov_target = tmp_path / "out_coverage.tif" if coverage else None
    writer = writer or FakeWriter(b"values")
    plan = WriterPlan(
        writer=writer,
        plan=object(),
        coverage_plan=object() if coverage else None,
        clip=object(),
        coverage_clip=object() if coverage else None,
    )
    if coverage and cov_writer is not None:
        # one writer serves both; a different writer for the companion is a test-only trick
        plan = WriterPlan(
            writer=_Dispatch(writer, cov_writer),
            plan="values",
            coverage_plan="counts",
            clip=object(),
            coverage_clip=object(),
        )
    task = ExportTask(
        "Exporting slices",
        "spec",
        plan,
        target,
        "cov-spec" if coverage else None,
        cov_target,
        on_done,
        **kw,
    )
    return task, target, cov_target


class _Dispatch:
    def __init__(self, values, counts) -> None:
        self.values, self.counts = values, counts

    def write_bands(self, path, plan, bands, **kw) -> float:
        writer = self.values if plan == "values" else self.counts
        return writer.write_bands(path, plan, bands, **kw)


def _collector():
    results: list[ExportResult] = []
    return results, results.append


def test_it_runs_to_completion(qgis_app, tmp_path, fake_run):
    results, on_done = _collector()
    task, target, cov = _make(tmp_path, on_done)
    assert start_export(task)
    _wait(lambda: results, "the export to finish")
    (result,) = results
    assert result.ok and not result.cancelled and result.error is None
    assert target.read_bytes() == b"values" and cov.read_bytes() == b"values"
    assert (result.target, result.coverage_target) == (target, cov)
    assert (result.limit, result.coverage_limit) == (2.5, 2.5)
    assert not partial_path(target).exists() and not partial_path(cov).exists()
    assert running_export() is None
    assert fake_run.specs == ["spec", "cov-spec"]


def test_the_work_runs_off_the_gui_thread_and_finish_on_it(qgis_app, tmp_path, fake_run):
    gui = threading.current_thread().name
    where: list[str] = []
    writer = FakeWriter(b"values")
    task, *_ = _make(
        tmp_path, lambda r: where.append(threading.current_thread().name), writer=writer
    )
    assert start_export(task)
    _wait(lambda: where, "the export to finish")
    assert gui not in writer.threads and where == [gui]


def test_without_a_companion_only_the_values_file_is_written(qgis_app, tmp_path, fake_run):
    results, on_done = _collector()
    task, target, _ = _make(tmp_path, on_done, coverage=False)
    assert start_export(task)
    _wait(lambda: results, "the export to finish")
    assert results[0].ok and results[0].coverage_limit is None and target.exists()
    assert list(tmp_path.glob("*")) == [target]


def test_progress_spans_both_files_and_the_description_names_the_band(qgis_app, tmp_path, fake_run):
    seen: list[tuple[float, str]] = []
    results, on_done = _collector()
    task, *_ = _make(tmp_path, on_done, what="site slices")
    task.progressChanged.connect(lambda p: seen.append((p, task.description())))
    # Slow the worker at the start of one band of each file so the GUI slot can run.
    fake_run.hook = lambda spec, k: time.sleep(0.15) if k == 1 else None
    assert start_export(task)
    _wait(lambda: results, "the export to finish")
    progresses = [p for p, _ in seen]
    assert progresses == sorted(progresses) and max(progresses) == 100.0
    descriptions = [d for _, d in seen if d.startswith("Exporting site slices")]
    assert any("band 2 of 3 · grid-1" in d for d in descriptions), seen
    assert any(d.startswith("Exporting coverage: band") for _, d in seen), seen


def test_cancel_mid_run_leaves_no_partial_and_no_target(qgis_app, tmp_path, fake_run):
    results, on_done = _collector()
    task, target, cov = _make(tmp_path, on_done)
    fake_run.hook = lambda spec, k: task.cancel() if k == 1 else None
    assert start_export(task)
    _wait(lambda: results, "the cancelled export to finish")
    (result,) = results
    assert result.cancelled and not result.ok and result.error is None
    assert list(tmp_path.glob("*")) == []
    assert running_export() is None


@pytest.mark.parametrize("phase", ["values overviews", "companion", "companion overviews"])
def test_a_cancel_in_a_later_phase_keeps_both_existing_targets(
    qgis_app, tmp_path, fake_run, monkeypatch, phase
):
    results, on_done = _collector()
    task, target, cov = _make(tmp_path, on_done)
    target.write_bytes(b"old values")
    cov.write_bytes(b"old counts")
    calls: list[Path] = []

    def overviews(path, should_stop=None):
        calls.append(Path(path))
        if (phase == "values overviews" and len(calls) == 1) or (
            phase == "companion overviews" and len(calls) == 2
        ):
            task.cancel()
            raise ExportCancelled()

    monkeypatch.setattr(export_task, "build_overviews", overviews)
    if phase == "companion":
        fake_run.hook = lambda spec, k: task.cancel() if spec == "cov-spec" and k == 1 else None
    assert start_export(task)
    _wait(lambda: results, "the cancelled export to finish")
    assert results[0].cancelled
    assert target.read_bytes() == b"old values" and cov.read_bytes() == b"old counts"
    assert sorted(p.name for p in tmp_path.glob("*")) == ["out.tif", "out_coverage.tif"]


def test_a_failure_in_the_companion_keeps_both_existing_targets(qgis_app, tmp_path, fake_run):
    results, on_done = _collector()
    task, target, cov = _make(
        tmp_path,
        on_done,
        writer=FakeWriter(b"values"),
        cov_writer=FakeWriter(b"counts", fail_at=2),
    )
    target.write_bytes(b"old values")
    cov.write_bytes(b"old counts")
    assert start_export(task)
    _wait(lambda: results, "the failed export to finish")
    (result,) = results
    assert not result.ok and not result.cancelled and "the writer broke" in (result.error or "")
    assert target.read_bytes() == b"old values" and cov.read_bytes() == b"old counts"
    assert sorted(p.name for p in tmp_path.glob("*")) == ["out.tif", "out_coverage.tif"]


def test_a_failure_in_the_overviews_keeps_the_existing_targets(
    qgis_app, tmp_path, fake_run, monkeypatch
):
    results, on_done = _collector()
    task, target, cov = _make(tmp_path, on_done)
    target.write_bytes(b"old")

    def broken(path, should_stop=None):
        raise RuntimeError("no room for overviews")

    monkeypatch.setattr(export_task, "build_overviews", broken)
    assert start_export(task)
    _wait(lambda: results, "the failed export to finish")
    assert "no room for overviews" in (results[0].error or "")
    assert [p.name for p in tmp_path.glob("*")] == ["out.tif"]
    assert target.read_bytes() == b"old"


def test_an_exception_in_run_reports_an_error(qgis_app, tmp_path, fake_run):
    results, on_done = _collector()
    task, target, _ = _make(tmp_path, on_done, writer=FakeWriter(b"values", fail_at=1))
    assert start_export(task)
    _wait(lambda: results, "the failed export to finish")
    (result,) = results
    assert not result.ok and not result.cancelled and result.error == "the writer broke"
    assert result.limit is None and list(tmp_path.glob("*")) == []
    assert running_export() is None


def test_cancelling_a_queued_task_calls_on_done_synchronously(qgis_app, tmp_path, fake_run):
    from qgis.core import QgsTask

    results, on_done = _collector()
    task, *_ = _make(tmp_path, on_done)
    manager = QgsApplication.taskManager()
    release = threading.Event()
    n_threads = QThreadPool.globalInstance().maxThreadCount()
    running = [threading.Event() for _ in range(n_threads)]
    finished = [threading.Event() for _ in range(n_threads)]

    def block(_task, started, ended):
        started.set()
        release.wait(TIMEOUT)
        ended.set()

    # Occupy every worker thread so the export stays queued. The manager deletes a
    # finished task's C++ object, so completion is tracked by events, never by status().
    blockers = [
        QgsTask.fromFunction("block", lambda t, a=a, b=b: block(t, a, b))
        for a, b in zip(running, finished)
    ]
    for blocker in blockers:
        manager.addTask(blocker)
    try:
        for event in running:
            assert event.wait(TIMEOUT), "a blocking task never started"
        assert start_export(task)
        assert task.status() == QgsTask.Queued
        task.cancel()
        assert len(results) == 1 and results[0].cancelled and not results[0].ok
        assert running_export() is None
        assert list(tmp_path.glob("*")) == []
    finally:
        release.set()
        _wait(lambda: all(e.is_set() for e in finished), "the blockers")


def test_an_exception_in_on_done_does_not_escape_and_the_hold_is_cleared(
    qgis_app, tmp_path, fake_run
):
    called: list[int] = []

    def on_done(result):
        called.append(1)
        raise RuntimeError("the handler broke")

    task, *_ = _make(tmp_path, on_done)
    assert start_export(task)
    _wait(lambda: called, "on_done")
    _wait(lambda: running_export() is None, "the hold to clear")
    # finished() returning normally is all QgsTaskWrapper would let us see; a second
    # export can start, which needs the hold gone.
    results, ok_done = _collector()
    again, *_ = _make(tmp_path, ok_done)
    assert start_export(again)
    _wait(lambda: results, "the second export")
    assert called == [1]


def test_a_second_export_while_one_is_held_is_refused(qgis_app, tmp_path, fake_run):
    started, release = threading.Event(), threading.Event()
    fake_run.hook = lambda spec, k: (started.set(), release.wait(TIMEOUT))
    results, on_done = _collector()
    first, *_ = _make(tmp_path, on_done)
    other_results, other_done = _collector()
    second, *_ = _make(tmp_path / "x", other_done)
    assert start_export(first)
    assert started.wait(TIMEOUT), "the first export never started"
    assert running_export() is first
    assert start_export(second) is False
    assert other_results == []
    release.set()
    _wait(lambda: results, "the first export to finish")
    assert results[0].ok and other_results == []


def test_add_task_failure_calls_on_done_with_an_error_and_drops_the_hold(
    qgis_app, tmp_path, fake_run, monkeypatch
):
    manager = QgsApplication.taskManager()
    monkeypatch.setattr(
        export_task.QgsApplication, "taskManager", staticmethod(lambda: _Refusing(manager))
    )
    results, on_done = _collector()
    task, *_ = _make(tmp_path, on_done)
    assert start_export(task) is True
    assert len(results) == 1 and not results[0].ok and not results[0].cancelled
    assert results[0].error
    assert running_export() is None


class _Refusing:
    def __init__(self, manager: Any) -> None:
        self._manager = manager

    def addTask(self, task) -> int:  # noqa: N802 - Qt's name
        return 0


def test_the_running_export_is_the_held_task_until_it_ends(qgis_app, tmp_path, fake_run):
    started, release = threading.Event(), threading.Event()
    fake_run.hook = lambda spec, k: (started.set(), release.wait(TIMEOUT))
    results, on_done = _collector()
    task, *_ = _make(tmp_path, on_done)
    assert running_export() is None
    assert start_export(task)
    assert started.wait(TIMEOUT)
    assert running_export() is task
    release.set()
    _wait(lambda: results, "the export to finish")
    assert running_export() is None


def test_the_worker_never_calls_a_live_engine_and_a_redraw_still_works(
    qgis_app, tmp_path, fake_run, monkeypatch
):
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo_qgis.session import SiteSession
    from nsgeo_qgis.site_engine import SiteEngine
    from nsgeo_qgis.slices_engine import SliceEngine
    from nsgeo_qgis.slices_plan import Resolution, SourceChoice
    from plugin_testing import synthetic_dzt

    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=40)
        lines.append(Line.open(p, GridPlacement("A", "y", 1.0 + i, 0.0, 1, p.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = [
        {"step": "time_zero", "params": {}, "enabled": True},
        {"step": "dewow", "params": {}, "enabled": True},
    ]
    engine = SliceEngine(session)
    try:
        engine.set_source(
            SourceChoice(
                grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(session.keys())
            )
        )
        assert engine.wait_for_preparation(20_000)
        engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))

        gui = threading.current_thread()
        off_thread: list[str] = []

        def spy(cls, name):
            original = getattr(cls, name)

            def wrapper(*args, **kwargs):
                if threading.current_thread() is not gui:
                    off_thread.append(f"{cls.__name__}.{name}")
                return original(*args, **kwargs)

            monkeypatch.setattr(cls, name, wrapper)

        for cls in (SliceEngine, SiteEngine):
            for name, member in list(vars(cls).items()):
                if callable(member) and not name.startswith("__"):
                    spy(cls, name)

        started, release = threading.Event(), threading.Event()
        fake_run.hook = lambda spec, k: (started.set(), release.wait(TIMEOUT))
        results, on_done = _collector()
        task, *_ = _make(tmp_path, on_done)
        assert start_export(task)
        assert started.wait(TIMEOUT), "the export never started"
        window = SimpleNamespace()  # redraw: a real slice while the task is mid-band
        from nsgeo.slices import SliceWindow

        window = SliceWindow(0, 10)
        shown, _coverage = engine.slice_at(window)
        assert shown.size > 0
        release.set()
        _wait(lambda: results, "the export to finish")
        assert results[0].ok
        assert off_thread == []
    finally:
        engine.dispose()
