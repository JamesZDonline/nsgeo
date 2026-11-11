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
    monkeypatch.setattr(export_task, "build_overviews", lambda path, should_stop=None, **kw: None)
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


def test_progress_spans_both_files(qgis_app, tmp_path, fake_run):
    seen: list[float] = []
    results, on_done = _collector()
    task, *_ = _make(tmp_path, on_done, what="site slices")
    task.progressChanged.connect(seen.append)
    assert start_export(task)
    _wait(lambda: results, "the export to finish")
    assert seen == sorted(seen) and max(seen) == 100.0
    assert any(p < 50.0 for p in seen) and any(p > 50.0 for p in seen)


def test_the_description_follows_the_band_and_the_grid_in_a_long_export(
    qgis_app, tmp_path, fake_run
):
    """`setProgress` emits per 0.1% only, so a description on it lags in a long export."""
    fake_run.n = 60
    stalled, release = threading.Event(), threading.Event()
    grids = ("g0", "g1", "g2")

    def run(spec, *, should_stop, progress):
        for k in range(fake_run.n):
            for grid in grids:
                progress(k, fake_run.n, grid)
                if spec == "spec" and (k, grid) == (30, "g2"):
                    stalled.set()
                    release.wait(TIMEOUT)
            yield ExportBand(np.zeros((2, 2), np.float32), {})

    export_task.run_export = run  # restored by the fake_run fixture's monkeypatch teardown
    results, on_done = _collector()
    task, *_ = _make(tmp_path, on_done, what="site slices")
    assert start_export(task)
    try:
        assert stalled.wait(TIMEOUT), "the export never reached band 31"
        _wait(
            lambda: task.description() == "Exporting site slices: band 31 of 60 \u00b7 g2",
            "the description to name band 31, grid g2",
        )
    finally:
        release.set()
    _wait(lambda: results, "the export to finish")


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

    def overviews(path, should_stop=None, **kw):
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


def test_a_companion_that_cannot_be_renamed_leaves_the_written_values_file_reported(
    qgis_app, tmp_path, fake_run, monkeypatch
):
    results, on_done = _collector()
    task, target, cov = _make(tmp_path, on_done)
    target.write_bytes(b"old values")
    cov.write_bytes(b"old counts")
    real = export_task.commit_partial

    def commit(partial, to):
        if Path(to) == cov:
            raise PermissionError(13, "in use by another program")
        real(partial, to)

    monkeypatch.setattr(export_task, "commit_partial", commit)
    assert start_export(task)
    _wait(lambda: results, "the half-committed export to finish")
    (result,) = results
    assert not result.ok and not result.cancelled
    assert result.values_written, "the values file was replaced"
    assert result.limit == 2.5
    assert target.read_bytes() == b"values" and cov.read_bytes() == b"old counts"
    assert sorted(p.name for p in tmp_path.glob("*")) == ["out.tif", "out_coverage.tif"]


def test_a_failure_before_any_commit_writes_nothing(qgis_app, tmp_path, fake_run):
    results, on_done = _collector()
    task, target, cov = _make(
        tmp_path, on_done, writer=FakeWriter(b"values"), cov_writer=FakeWriter(b"counts", fail_at=2)
    )
    assert start_export(task)
    _wait(lambda: results, "the failed export to finish")
    assert not results[0].values_written and results[0].limit is None


def test_the_companions_overviews_are_built_for_counts(qgis_app, tmp_path, fake_run, monkeypatch):
    results, on_done = _collector()
    task, target, cov = _make(tmp_path, on_done)
    task._writer_plan = WriterPlan(
        writer=task._writer_plan.writer,
        plan=SimpleNamespace(coverage=False),
        coverage_plan=SimpleNamespace(coverage=True),
        clip=object(),
        coverage_clip=object(),
    )
    seen: list[tuple[str, bool]] = []

    def overviews(path, should_stop=None, *, counts=False):
        seen.append((Path(path).name, counts))

    monkeypatch.setattr(export_task, "build_overviews", overviews)
    assert start_export(task)
    _wait(lambda: results, "the export to finish")
    assert results[0].ok
    assert seen == [("out.partial.tif", False), ("out_coverage.partial.tif", True)]


def test_a_failure_in_the_overviews_keeps_the_existing_targets(
    qgis_app, tmp_path, fake_run, monkeypatch
):
    results, on_done = _collector()
    task, target, cov = _make(tmp_path, on_done)
    target.write_bytes(b"old")

    def broken(path, should_stop=None, **kw):
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
        assert task.status() == QgsTask.TaskStatus.Queued
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


def _pipeline_helpers():
    """The pure tier's site builder: two grids, one turned, built from core calls."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "pure" / "test_pure_export_pipeline.py"
    found = importlib.util.spec_from_file_location("_export_pipeline_builders", path)
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


def test_a_cancel_mid_band_over_the_real_stack_leaves_nothing_and_never_touches_an_engine(
    qgis_app, tmp_path, monkeypatch
):
    """Minimum curvature at a fine cell through the real pipeline, writer and overviews.

    Cancelled at band 1, grid A (band 0 is already written): no partial remains, no
    target appears, an existing target is byte-identical, and a live slice redraw on
    the GUI thread works while the worker is mid-run. Every attribute access on a
    live `SliceEngine` or `SiteEngine` off the GUI thread is recorded.
    """
    import dataclasses

    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo.render import PercentileClip
    from nsgeo.slices import FinishSettings, SliceWindow
    from nsgeo_qgis.session import SiteSession
    from nsgeo_qgis.site_engine import SiteEngine
    from nsgeo_qgis.site_export import (
        GeoTiffSiteWriter,
        SiteBand,
        SiteExportPlan,
        SiteGridRecord,
    )
    from nsgeo_qgis.slices_engine import SliceEngine
    from nsgeo_qgis.slices_plan import Resolution, SliceFinish, SourceChoice
    from plugin_testing import synthetic_dzt

    helpers = _pipeline_helpers()
    finish = FinishSettings("min_curvature", 0.25, 1.0, 0.05, 0.05)
    spec = helpers._site(0.05, "background", finish=finish)
    coverage_spec = dataclasses.replace(spec, coverage=True)
    z = helpers.Z

    def plan(coverage: bool) -> SiteExportPlan:
        bands = tuple(
            SiteBand(SliceWindow(int(i * 4), int(i * 4 + 4)), f"band {i}", {})
            for i in range(len(spec.windows))
        )
        return SiteExportPlan(
            lattice=spec.lattice,
            site_z=z,
            bands=bands[:1] if coverage else bands,
            transform="amp_envelope",
            method="none" if coverage else "background",
            cell_m=0.05,
            finish=None if coverage else SliceFinish("min_curvature"),
            grids=tuple(
                SiteGridRecord(g.grid_id, "p", None, 1.0, 0.5, g.frame.azimuth, g.frame.crs)
                for g in spec.grids
            ),
            coverage=coverage,
        )

    writer_plan = WriterPlan(
        GeoTiffSiteWriter(), plan(False), plan(True), PercentileClip(), PercentileClip()
    )

    # A live engine the export must never touch.
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
        for cls in (SliceEngine, SiteEngine):
            original = cls.__getattribute__

            def recording(self, name, _original=original, _cls=cls):
                if threading.current_thread() is not gui and not name.startswith("__"):
                    off_thread.append(f"{_cls.__name__}.{name}")
                return _original(self, name)

            monkeypatch.setattr(cls, "__getattribute__", recording)

        out = tmp_path / "out"
        out.mkdir()
        target, cov_target = out / "site.tif", out / "site_coverage.tif"
        target.write_bytes(b"old values")
        cov_target.write_bytes(b"old counts")

        real_run = export_task.run_export
        at_band_1, release = threading.Event(), threading.Event()

        def run(spec_, *, should_stop, progress):
            def watched(band, n_bands, grid_id):
                progress(band, n_bands, grid_id)
                if (band, grid_id) == (1, "A"):
                    at_band_1.set()
                    release.wait(TIMEOUT)

            return real_run(spec_, should_stop=should_stop, progress=watched)

        monkeypatch.setattr(export_task, "run_export", run)
        results, on_done = _collector()
        task = ExportTask(
            "Exporting site slices", spec, writer_plan, target, coverage_spec, cov_target, on_done
        )
        assert start_export(task)
        assert at_band_1.wait(120), "the export never reached band 1"
        shown, _coverage = engine.slice_at(SliceWindow(0, 10))  # the live view still draws
        assert shown.size > 0
        task.cancel()
        release.set()
        _wait(lambda: results, "the cancelled export to finish")
        (result,) = results
        assert result.cancelled and not result.ok
        assert sorted(p.name for p in out.glob("*")) == ["site.tif", "site_coverage.tif"]
        assert target.read_bytes() == b"old values" and cov_target.read_bytes() == b"old counts"
        assert off_thread == []
        monkeypatch.undo()
    finally:
        engine.dispose()
