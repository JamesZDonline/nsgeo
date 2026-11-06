"""One background thread that runs a list of solves and hands each back.

Minimum curvature can take longer than a frame (interpolation spec §7), so
the Slices panel draws a preview and refines in the background once the
depth rests. This module is only the worker: it knows nothing of slices.
A job is anything with `run(should_stop)`; the worker calls it on its
thread and the GUI thread then receives the finished job.

**A plain thread, not a `QgsTask`.** The hazards recorded in
`slices_engine.py`'s docstring are all about `QgsTask`: the task manager
keeps no strong reference, `addTask()` can return 0, and
`QgsTaskWrapper.finished()` swallows whatever a callback raises. A refine
needs none of what a task offers. It is pure numpy on arrays it owns, with
no Qt, no file reads and no session, and a task would flash in QGIS's task
list at every pause in scrubbing. So it is one
`ThreadPoolExecutor(max_workers=1)`: two solves can never run at once, and
a cancelled list ends its current iteration before the next list starts.

**The worker touches only its job.** Results cross to the GUI thread
through a `queue.SimpleQueue` that a `QTimer` drains every
`REFINE_POLL_MS`. Nothing Qt is touched off the GUI thread and no
cross-thread signal is used. Every entry carries the generation it was
queued under, so anything a cancelled or superseded list delivers late is
dropped on the GUI thread, never shown.

The poll slot is a Qt slot, so it guards its own body: an exception there
is swallowed by PyQt locally but aborts CI's QGIS containers (`qFatal`).
Exceptions from `on_landed` and `on_error` go to the log.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from nsgeo.slices import SolveStopped
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, QTimer

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.slices_plan import REFINE_POLL_MS

#: The worker thread's name prefix; tests and crash reports look for it.
THREAD_NAME_PREFIX = "nsgeo-refine"


def _describe(exc: BaseException) -> str:
    """The message, or the type when there is none (`MemoryError()`)."""
    return str(exc) or type(exc).__name__


class RefineJob(Protocol):
    def run(self, should_stop: Callable[[], bool]) -> None:
        """Runs on the worker thread and keeps its own result."""


class Refiner:
    def __init__(self, parent: QObject) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=THREAD_NAME_PREFIX)
        self._done: queue.SimpleQueue = queue.SimpleQueue()
        self._generation = 0
        self._stop = threading.Event()
        self._remaining = 0
        self._closed = False
        self._on_landed: Callable[[RefineJob], None] | None = None
        self._on_error: Callable[[str], None] | None = None
        self._poll = QTimer(parent)
        self._poll.timeout.connect(self._drain)

    @property
    def busy(self) -> bool:
        """A started list has jobs that have not landed yet."""
        return self._remaining > 0

    def start(
        self,
        jobs: Sequence[RefineJob],
        on_landed: Callable[[RefineJob], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Cancel whatever runs, then run `jobs` in order; each lands on the
        GUI thread through `on_landed` after it finishes."""
        if self._closed or sip.isdeleted(self._poll):
            _log("a refine was started after the worker shut down; ignored")
            return
        self.cancel()
        self._generation += 1
        self._stop = threading.Event()
        self._remaining = len(jobs)
        self._on_landed = on_landed
        self._on_error = on_error
        if not jobs:
            return
        self._executor.submit(self._run_list, self._generation, list(jobs), self._stop)
        self._poll.start(REFINE_POLL_MS)

    def cancel(self) -> None:
        """The running job stops at its next iteration; nothing more of its
        list lands."""
        self._stop.set()
        self._generation += 1
        self._remaining = 0

    def shutdown(self) -> None:
        """Cancel, then join the worker. Safe to call twice."""
        self._closed = True
        self.cancel()
        self._executor.shutdown(wait=True, cancel_futures=True)
        # The timer is parented to the dock, which may be gone by now.
        if not sip.isdeleted(self._poll):
            self._poll.stop()

    def _run_list(self, generation: int, jobs: list, stop: threading.Event) -> None:
        # Worker thread. Anything raised here would be lost in the future,
        # so every outcome is reported through the queue.
        for job in jobs:
            if stop.is_set():
                return
            try:
                job.run(stop.is_set)
            except SolveStopped:
                if stop.is_set():
                    return
                # Nobody asked it to stop, so the list must not end silently.
                self._done.put((generation, None, "the solve stopped unexpectedly"))
                return
            except BaseException as exc:
                self._done.put((generation, None, _describe(exc)))
                if not isinstance(exc, Exception):
                    raise
                return
            self._done.put((generation, job, None))

    def _drain(self) -> None:
        try:
            while True:
                try:
                    generation, job, message = self._done.get_nowait()
                except queue.Empty:
                    break
                # Re-read each time: a callback may have started a new list.
                if generation != self._generation:
                    continue
                if job is None:
                    self._remaining = 0
                    self._deliver(self._on_error, message)
                else:
                    self._remaining -= 1
                    self._deliver(self._on_landed, job)
            if self._remaining <= 0:
                self._poll.stop()
        except Exception as exc:
            _log(f"the refine poll failed: {exc}")

    @staticmethod
    def _deliver(callback: Callable | None, argument: object) -> None:
        if callback is None:
            return
        try:
            callback(argument)
        except Exception as exc:
            _log(f"a refine callback failed: {exc}")
