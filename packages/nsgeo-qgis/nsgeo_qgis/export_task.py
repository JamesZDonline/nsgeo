"""The export as a QGIS background task: the work off the GUI thread, the panel left alone.

`ExportTask.run()` runs on a worker thread. It reads only what the spec holds (a
snapshot built on the GUI thread) and never touches a live `SliceEngine` or
`SiteEngine`, the session, a widget or a layer, and never `warnings.catch_warnings()`.

Three hazards, all recorded elsewhere in this codebase (see `slices_engine.py`):

* `QgsApplication.taskManager().addTask()` keeps no Python reference, so the
  task is held in `_held` until `finished` has run; `addTask()` returning 0
  means it was never added, and that branch still notifies.
* `QgsTaskWrapper` swallows an exception raised in `finished` with no traceback,
  so `finished` guards its whole body, clears the hold first, and logs a raising
  `on_done` through `QgsMessageLog`.
* Cancelling a task still queued runs `finished(False)` synchronously inside
  `cancel()`, so `on_done` can run before `start_export` has returned.

`QgsTask.setDescription` is not documented thread-safe, so the worker only
stashes its progress and calls `setProgress` (thread-safe); a slot on
`progressChanged`, which Qt delivers on the GUI thread, writes the description.

The files: both partials (values with its overviews, then the coverage companion
with its overviews) are written before either is committed. Any cancel or failure
discards both and leaves both existing targets untouched.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsTask

from nsgeo_qgis.export_pipeline import ExportCancelled, ExportSpec, run_export
from nsgeo_qgis.site_export import SiteExportPlan
from nsgeo_qgis.slice_export import (
    ExportPlan,
    build_overviews,
    commit_partial,
    discard_partial,
    partial_path,
)

_LOG_TAG = "nsgeo"


@dataclass(frozen=True)
class WriterPlan:
    """How the bands are written: the writer, the plans and the stretch rules.

    `coverage_plan` and `coverage_clip` are None when there is no counts companion.
    """

    writer: Any  # has write_bands(path, plan, bands, *, clip, progress_band=None) -> float
    plan: ExportPlan | SiteExportPlan
    coverage_plan: ExportPlan | SiteExportPlan | None
    clip: Any
    coverage_clip: Any | None = None


@dataclass(frozen=True)
class ExportResult:
    ok: bool
    cancelled: bool
    error: str | None
    target: Path
    coverage_target: Path | None
    limit: float | None
    coverage_limit: float | None


#: The one export in flight; addTask() keeps no reference of its own.
_held: ExportTask | None = None


def running_export() -> ExportTask | None:
    """The export in flight, or None."""
    return _held


def start_export(task: ExportTask) -> bool:
    """Queue `task`. False: another export is held, nothing was queued, `on_done` is not called.

    True: `on_done` will be called exactly once, including when the task manager refuses the
    task (then it is called at once with an error).
    """
    global _held
    if _held is not None:
        return False
    _held = task
    if not QgsApplication.taskManager().addTask(task):
        task.deliver_failure("The export could not be started.")
    return True


class ExportTask(QgsTask):
    def __init__(
        self,
        description: str,
        spec: ExportSpec,
        writer_plan: WriterPlan,
        target: Path,
        coverage_spec: ExportSpec | None,
        coverage_target: Path | None,
        on_done: Callable[[ExportResult], None],
        what: str | None = None,
    ) -> None:
        super().__init__(description, QgsTask.CanCancel)
        self._spec = spec
        self._writer_plan = writer_plan
        self._target = Path(target)
        self._coverage_spec = coverage_spec if coverage_target is not None else None
        self._coverage_target = Path(coverage_target) if coverage_target is not None else None
        self._on_done = on_done
        self._what = what or description
        self._error: str | None = None
        self._cancelled = False
        self._limit: float | None = None
        self._coverage_limit: float | None = None
        # Written by the worker, read by the GUI-thread slot below.
        self._latest: tuple[str, int, int, str] = (self._what, 0, 0, "")
        self._delivered = False
        self.progressChanged.connect(self._show_progress)

    # ---- GUI thread -----------------------------------------------------------
    def _show_progress(self, _progress: float) -> None:
        what, k, n, grid = self._latest
        if n:
            self.setDescription(f"Exporting {what}: band {k} of {n} · {grid}")

    def deliver_failure(self, message: str) -> None:
        self._error = message
        self._deliver(False)

    def finished(self, result: bool) -> None:
        self._deliver(result)

    def _deliver(self, ok: bool) -> None:
        global _held
        try:
            if self._delivered:
                return
            self._delivered = True
            cancelled = not ok and self._error is None and (self._cancelled or self.isCanceled())
            error = self._error
            if not ok and not cancelled and error is None:
                error = "The export stopped without finishing."
            result = ExportResult(
                ok=ok,
                cancelled=cancelled,
                error=None if ok else error,
                target=self._target,
                coverage_target=self._coverage_target,
                limit=self._limit if ok else None,
                coverage_limit=self._coverage_limit if ok else None,
            )
            if _held is self:
                _held = None
            self._on_done(result)
        except Exception:
            QgsMessageLog.logMessage(
                f"Export finish handler failed:\n{traceback.format_exc()}",
                _LOG_TAG,
                Qgis.MessageLevel.Critical,
            )
        finally:
            if _held is self:
                _held = None

    # ---- worker thread --------------------------------------------------------
    def run(self) -> bool:
        partials: list[Path] = []
        try:
            values = partial_path(self._target)
            partials.append(values)
            phases = 2 if self._coverage_spec is not None else 1
            self._limit = self._write(
                values, self._spec, self._writer_plan.plan, self._writer_plan.clip, 0, phases
            )
            if self._coverage_spec is not None and self._coverage_target is not None:
                counts = partial_path(self._coverage_target)
                partials.append(counts)
                self._coverage_limit = self._write(
                    counts,
                    self._coverage_spec,
                    self._writer_plan.coverage_plan,
                    self._writer_plan.coverage_clip,
                    1,
                    phases,
                    what="coverage",
                )
            if self.isCanceled():
                raise ExportCancelled()
            commit_partial(values, self._target)
            if self._coverage_spec is not None and self._coverage_target is not None:
                commit_partial(partials[1], self._coverage_target)
            partials.clear()
            self.setProgress(100.0)
            return True
        except ExportCancelled:
            self._cancelled = True
            return False
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Export failed:\n{traceback.format_exc()}", _LOG_TAG, Qgis.MessageLevel.Warning
            )
            self._error = str(exc) or type(exc).__name__
            return False
        finally:
            for partial in partials:
                discard_partial(partial)

    def _write(
        self,
        partial: Path,
        spec: ExportSpec,
        plan: Any,
        clip: Any,
        phase: int,
        phases: int,
        what: str | None = None,
    ) -> float:
        label = what or self._what
        count = [0]
        in_band = [-1, 0]  # the band last announced, and how many grids it has announced

        def overall(fraction: float) -> None:
            self.setProgress(100.0 * (phase + min(fraction, 1.0)) / phases)

        def progress(band: int, n_bands: int, grid_id: str) -> None:
            count[0] = n_bands
            self._latest = (label, band + 1, n_bands, grid_id)
            if in_band[0] != band:
                in_band[:] = [band, 0]
            in_band[1] += 1
            # `setProgress` emits only when the value changes, and the description follows
            # the emission, so each grid announced moves the value a hair (less than half
            # a band, which `band_done` then passes).
            overall((band + min(0.5, 0.01 * in_band[1])) / n_bands)

        def band_done(done: int) -> None:
            if count[0]:
                overall(done / count[0])

        bands = run_export(spec, should_stop=self.isCanceled, progress=progress)
        limit = self._writer_plan.writer.write_bands(
            partial, plan, bands, clip=clip, progress_band=band_done
        )
        build_overviews(partial, self.isCanceled)
        return float(limit)
