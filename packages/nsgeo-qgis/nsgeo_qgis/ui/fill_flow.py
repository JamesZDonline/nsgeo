"""One scope's side of the fill worker: the fill, then the shared stretch (#193).

A fine cell makes the interpolation fill take seconds. The Slices panel used to
build it on the GUI thread, and QGIS froze. `FillFlow` runs the fill, and then
the shared colour stretch measured over it, on the dock's `nsgeo-fill` worker
(`Refiner`), while the map keeps its last picture and stretch. It owns no
widgets and draws nothing: the scope hands it jobs and callbacks and says what
to show.

* **`request`** answers whether the caller draws now. It starts the fills,
  waits `FILL_BUDGET_S` on the GUI thread so a quick fill never flickers a
  working line, and returns True when every fill landed in that time. Otherwise
  it returns False, the flow is `working`, and `on_done` draws when the last
  fill lands. A request for the fill already running is dropped.
* **Never inside the draw.** `Refiner.settle` delivers landings synchronously, in
  the caller's frame. A landing that then drew would re-enter the very draw that
  called `request`. So a landing seen inside `request` draws nothing: the
  answer True says the caller draws, and `on_done` runs only from the worker's
  own poll timer, never under a draw.
* **Footprint jobs join the fill list** after the fills (the site's first draw
  at a new lattice gathers each grid's footprint there too, so the landing draw
  builds nothing). The working line does not count them.
* **The stretch follows the fills as a second list.** It starts once the last
  fill has landed, so a quick fill is never held up by the (longer) stretch,
  and the stretch job reads a fill the engine already holds. It lands through
  `on_stretch`. A stretch whose fill landing was refused (stale work) measured
  nothing and is dropped: the next draw asks again.
* **Cancel** stops the worker and clears the state; the scope decides what
  that means (revert, or latch). While `latched` the scope starts no job.

Every Qt slot here guards its whole body. Nothing runs off the GUI thread but
the jobs, which touch only what they captured.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Any

from qgis.PyQt.QtCore import QObject, QTimer

from nsgeo_qgis.fill_jobs import FillJob, FootprintJob
from nsgeo_qgis.log import log as _log
from nsgeo_qgis.refine import Refiner
from nsgeo_qgis.slices_plan import (
    FILL_BUDGET_S,
    FILL_POLL_MS,
    FILL_WORKING_GRIDS_INDICATOR,
    FILL_WORKING_INDICATOR,
    STRETCH_WORKING_INDICATOR,
)
from nsgeo_qgis.stretch_jobs import StretchJob


class FillFlow(QObject):
    def __init__(
        self,
        parent: QObject,
        worker: Refiner,
        *,
        on_done: Callable[[], None],
        on_stretch: Callable[[Hashable, float, bool], None],
        on_cancelled: Callable[[], None],
        on_tick: Callable[[], None] | None = None,
        on_error: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._worker = worker
        self._on_done = on_done
        self._on_stretch = on_stretch
        self._on_cancelled = on_cancelled
        self._on_tick = on_tick
        self._on_error = on_error
        #: The fills of the running request and how many have landed.
        self._key: Hashable | None = None
        self._fills: list[FillJob | FootprintJob] = []
        #: How many of them are fills: the footprint jobs after them run
        #: silently, so the working line never counts them (#193).
        self._fill_count = 0
        self._total = 0
        self._landed = 0
        self._working = False
        #: The stretch to start once the last fill has landed, the stretch
        #: running, and the key it was asked for.
        self._pending_stretch: StretchJob | None = None
        self._stretch_key: Hashable | None = None
        self._stretching = False
        #: Inside `request`'s wait: landings are counted and never drawn.
        self._requesting = False
        self._all_landed = False
        self._failed = False
        self._latched = False
        self._timer = QTimer(self)
        self._timer.setInterval(FILL_POLL_MS)
        self._timer.timeout.connect(self._tick)

    # ---- state ------------------------------------------------------------
    @property
    def working(self) -> bool:
        """Fills are pending."""
        return self._working

    @property
    def stretching(self) -> bool:
        """The shared stretch is being measured."""
        return self._stretching

    @property
    def latched(self) -> bool:
        return self._latched

    def latch(self) -> None:
        self._latched = True

    def unlatch(self) -> None:
        self._latched = False

    def progress_text(self, cell_m: float, *, grids: bool) -> str:
        """The working line, or "" when nothing runs. `grids`: Whole site, which
        counts the grid being filled rather than a percentage."""
        if self._working:
            if grids:
                # Footprint jobs follow the fills and are not counted: the line
                # stays on the last grid while they run. Footprints alone count
                # themselves.
                total = self._fill_count or self._total
                n = min(self._landed + 1, total)
                return FILL_WORKING_GRIDS_INDICATOR.format(cell=cell_m, n=n, total=total)
            fraction = 0.0
            if self._landed < len(self._fills):
                fraction = self._fills[self._landed].fraction
            percent = max(0, min(99, int(fraction * 100.0)))
            return FILL_WORKING_INDICATOR.format(cell=cell_m, percent=percent)
        if self._stretching:
            return STRETCH_WORKING_INDICATOR
        return ""

    # ---- requests ---------------------------------------------------------
    def request(self, key: Hashable, jobs: Any, *, stretch_key: Hashable) -> bool:
        """Whether the caller draws now.

        `jobs` is the `FillJob`s, the `FootprintJob`s, then at most one `StretchJob`, or a callable
        that makes them: made only when the work will start, since making a fill
        job drops the engine's held fill. The same `key` as the fill work
        running: dropped, and False; the flow draws once on landing. Another
        key: the running work is cancelled and `jobs` start. True when every
        fill has landed within `FILL_BUDGET_S` (no working state), otherwise
        False. Empty `jobs`: True."""
        if self._latched:
            return False
        if self._working and self._key == key:
            return False
        built = list(jobs() if callable(jobs) else jobs)
        fills = [j for j in built if isinstance(j, (FillJob, FootprintJob))]
        stretch = next((j for j in built if isinstance(j, StretchJob)), None)
        self._clear()
        self._worker.cancel()
        if not fills:
            if stretch is not None:
                self._start_stretch(stretch_key, stretch)
            return True
        self._key = key
        self._fills = fills
        self._total = len(fills)
        self._fill_count = sum(1 for j in fills if isinstance(j, FillJob))
        self._landed = 0
        self._working = True
        self._pending_stretch = stretch
        self._stretch_key = stretch_key
        self._all_landed = False
        self._failed = False
        self._requesting = True
        try:
            self._worker.start(fills, self._fill_landed, self._failed_with)
            self._worker.settle(FILL_BUDGET_S)
        finally:
            self._requesting = False
        if self._all_landed:
            self._begin_pending_stretch()
            return True
        if self._failed:
            return False
        if not self._worker.busy:
            # Nothing is running and nothing came: a worker that was shut down.
            self._clear()
            return False
        self._timer.start()
        return False

    def request_stretch(self, stretch_key: Hashable, job: Any) -> None:
        """Measure the shared stretch for `stretch_key` (`job`, or a callable that
        makes it, made only when it starts). Nothing while fill work runs (the
        stretch follows it) or while a stretch for the same key runs; another
        key cancels the stretch running."""
        if self._latched or self._working:
            return
        if self._stretching and self._stretch_key == stretch_key:
            return
        self._start_stretch(stretch_key, job() if callable(job) else job)

    def cancel(self) -> None:
        """The link: stop the worker, clear both states, and tell the scope."""
        self._clear()
        self._worker.cancel()
        try:
            self._on_cancelled()
        except Exception as exc:  # noqa: BLE001 -- the link's slot must not raise
            _log(f"could not handle a cancelled fill: {exc}")

    def stop(self) -> None:
        """A scope switch, a closed survey, or work for what is no longer drawn:
        cancel without the callback. The latch is not touched: `FillPicture` is
        its one owner (`latch`/`unlatch` with its note), so a stop that must
        also unlatch says so there."""
        self._clear()
        self._worker.cancel()

    def drop_stretch(self) -> None:
        """The held stretch was dropped (the cube's geometry or source moved): a
        stretch measured over what it snapshotted, running or waiting for its
        fills, would be stored as current. Cancelled, never landed; the next
        draw asks again."""
        self._pending_stretch = None
        if self._stretching:
            self._stretching = False
            self._worker.cancel()
            if not self._working:
                self._timer.stop()

    # ---- landings ----------------------------------------------------------
    def _clear(self) -> None:
        self._working = False
        self._stretching = False
        self._fills = []
        self._fill_count = 0
        self._total = 0
        self._landed = 0
        self._key = None
        self._pending_stretch = None
        self._timer.stop()

    def _start_stretch(self, stretch_key: Hashable, job: StretchJob) -> None:
        self._stretch_key = stretch_key
        self._stretching = True
        self._worker.start([job], self._stretch_landed, self._failed_with)
        self._timer.start()

    def _begin_pending_stretch(self) -> None:
        job, self._pending_stretch = self._pending_stretch, None
        if job is not None:
            self._start_stretch(self._stretch_key, job)

    def _fill_landed(self, job: Any) -> None:
        # Called by the worker's poll timer, or inside `request`'s wait.
        try:
            try:
                job.land()
            except Exception as exc:  # noqa: BLE001 -- a refused landing is stale work
                _log(f"could not land a fill: {exc}")
            self._landed += 1
            if self._landed < self._total:
                return
            # Let go of the landed jobs: each holds the fill it built, which an
            # engine since removed or unticked would otherwise keep alive.
            self._fills = []
            self._working = False
            self._all_landed = True
            if self._requesting:
                return  # the caller draws now; a draw here would re-enter its own
            self._begin_pending_stretch()
            if not self._stretching:
                self._timer.stop()
            self._on_done()
        except Exception as exc:  # noqa: BLE001 -- from the worker's poll timer
            _log(f"could not draw after a fill: {exc}")

    def _stretch_landed(self, job: Any) -> None:
        try:
            self._stretching = False
            self._timer.stop()
            limit = getattr(job, "limit", None)
            if limit is None:
                return  # stale: its fill was refused, so it measured nothing
            self._on_stretch(self._stretch_key, float(limit), bool(job.final))
        except Exception as exc:  # noqa: BLE001 -- from the worker's poll timer
            _log(f"could not take the colour stretch: {exc}")

    def _failed_with(self, message: str) -> None:
        try:
            what = "fill" if self._working else "colour stretch"
            self._clear()
            self._failed = True
            if self._on_error is not None:
                self._on_error(what, message)
            else:
                _log(f"the {what} failed: {message}")
        except Exception as exc:  # noqa: BLE001 -- from the worker's poll timer
            _log(f"could not report a failed fill: {exc}")

    def _tick(self) -> None:
        try:
            if not (self._working or self._stretching):
                self._timer.stop()
                return
            if self._on_tick is not None:
                self._on_tick()
        except Exception as exc:  # noqa: BLE001 -- a QTimer.timeout slot
            _log(f"could not show the fill's progress: {exc}")
