"""Preparing lines, holding plans, and handing over one slice per tick.

Spec 6.1's three tiers, owned in one place. Tier 1 -- load, preset,
transform -- is the only expensive step (about 0.9 s for 24 lines) and
depends on the preset and the transform and on nothing else, so it is
cached here and every geometric parameter stays cheap. Tier 2, the
resample-and-bin plan, depends on the cell size, dz and the z range, and
is dropped wholesale whenever any of them moves. Tier 3 is a slice, which
is what `slice_at` returns.

**No `pyqtSignal`.** `tests/pure/test_no_orphan_signals.py` requires a
`connect` in the package for every declared signal, and this module's
consumer (the Slices dock) does not exist yet. Constructor callbacks are
the pattern `LineLoader` already uses for exactly this, and they keep that
rule honest instead of inviting a `connect` that satisfies a grep and
consumes nothing.

Five hazards, all of them recorded elsewhere in this codebase and all of
them live here:

* `QgsApplication.taskManager().addTask()` keeps no strong reference to a
  `QgsTask.fromFunction()` task. `_pending` is the keep-alive; without it
  the task is collected silently and `on_finished` never runs. `addTask()`
  returning 0 means it was never added at all, so the bookkeeping has to
  be undone in that branch -- and, like every other terminal path below,
  it must still notify.
* `QgsTaskWrapper.finished()` swallows any exception an `on_finished`
  callback raises, with no traceback anywhere -- worse than the ordinary
  slot hazard, which at least reaches stderr (verified directly in its
  installed source: the exception is stored on an attribute and never
  logged or re-raised). `finished()` guards its own body with `except`,
  and EVERY terminal path -- success, a whole-task exception, an
  exception raised while finishing -- calls `_finish_preparation()` from
  a `finally`, because `wait_for_preparation` (and any future caller)
  waits on that callback and must see a request it is actually watching
  end, not hang for the whole timeout (`loader.py`'s own `addTask()`
  -failure branch draws the identical lesson by re-emitting
  `loading_changed`). Because a `finally` runs OUTSIDE `finished`'s own
  `except`, `_finish_preparation` and `_report` must guard THEMSELVES
  too -- the dock's `on_prepared` (Task 3) rebuilds widgets and really
  can raise, and neither a raising `on_prepared` nor a raising `on_error`
  may reach `QgsTaskWrapper`'s silent swallow. An earlier version of this
  module put the `_finish_preparation()` call inside the `try`, which
  reopened exactly this hole; a caller-supplied callback raising past a
  `finally` is no safer than one raising past `finished()` itself.
* The site can be closed, or a different site opened, while a preparation
  is in flight. `_generation` and the captured site identity together
  decide whether a result may be kept: keys are relative paths, so the
  same string can name a line in two different sites. These two checks
  are the one place a terminal path stays silent on purpose -- a newer
  request, or a different site, owns the notification now.
* **A `LinePlan` must never outlive the frame or z axis it was built
  against.** Every `Resolution` field invalidates every plan.
  `_rebuild_geometry` drops them by setting `_plans = None`, and
  `build_cube`/`stream_slice` carry M10's own guard underneath as a second
  line of defence. Do not "optimise" this into a partial update: M10
  measured the silent version binning every trace into the wrong cell with
  entirely plausible coverage.
* **`replace_grid`/`remove_grid` change exactly the fields a cube is
  binned from, and the prepared lines' own `coords` too** -- and M10's
  stale-plan guard cannot see it, because `plan.frame` and the frame this
  engine holds become the SAME (now stale) object once the grid moves, so
  `!=` never fires. `_on_grids_changed` therefore re-prepares the whole
  source, not merely the geometry, whenever the CHOSEN grid's binning
  fields change. The fingerprint (`_grid_fingerprint`) is captured in
  `set_source`, beside the `trace_coords` call it protects -- NOT in
  `_rebuild_geometry`, which may not have run yet: Task 3 sets a source
  and a resolution as two separate calls, and keying the fingerprint to
  the second one left a window where a grid move between them went
  undetected, measured as a silent, uniform 4-cell shift (1 m at a
  0.25 m cell) with no exception and no change in total coverage. A
  velocity-only edit is deliberately excluded from the fingerprint,
  since that relabels depths without rebinning -- but it still drops any
  resident `_cube` (never the lines or the plans), because `cube()`
  freezes a `Provenance` snapshot at build time and `provenance()` reads
  velocity live; without this, an export's recorded velocity would depend
  on whether a cube happened to be resident.
* **Two real preparations must never run at once.** `_generation` decides
  whose RESULT is kept, never whether a superseded task is still actually
  executing -- and two of them reading the same lines on two worker
  threads segfaulted this plugin reproducibly, both for the identical
  choice re-requested faster than it could finish (Task 3, fix round 1)
  and for two genuinely different choices a click apart (fix round 2,
  Ruling V). `set_source` and `dispose()` both call `_cancel_in_flight()`
  first, which cancels and CONFIRMS (waits, bounded by roughly one line's
  processing) that any previous task has actually stopped before either
  proceeds. See `_cancel_in_flight`'s own docstring for why it must run
  before `_generation` is bumped, not after.
* **The confirm wait above is itself a nested event loop, and reopens the
  same hazard if not guarded (Ruling W, fix round 3).** `wait_for_
  preparation`'s `QEventLoop.exec()` can deliver a SECOND `set_source`
  call -- a person changing a combo again while the first change is still
  being cancelled -- from inside the first call's own frame. Measured
  directly: the reentrant call dispatches its own task, then the outer
  call resumes and dispatches a second one on top, restoring the very
  segfault the confirm wait exists to prevent, with the OLDER choice
  winning instead of the newer one. Closed with both halves together,
  neither sufficient alone: `set_source`'s own `_dispatching` guard queues
  (never refuses) a reentrant call so the latest choice still wins, and
  `_cancel_in_flight`'s wait passes `ExcludeUserInputEvents` so a mouse
  wheel or held key over a combo cannot trigger the reentrancy in the
  first place (a `QTimer` or a queued signal still can, which is why the
  guard is still needed even with the narrower event mask).
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

import nsgeo
import numpy as np
from nsgeo.processing import Radargram, StepStack, build_step
from nsgeo.slices import (
    CubeFrame,
    LinePlan,
    PreparedLine,
    Provenance,
    SliceCube,
    SliceWindow,
    ZAxis,
    build_cube,
    fill,
    limit_over_slices,
    plan_line,
    plan_windows,
    stream_slice,
)
from nsgeo.slices.fill import clear_kernel_cache
from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QEventLoop, QObject, QTimer

from nsgeo_qgis.slices_plan import (
    NO_TRANSFORM,
    MemoryEstimate,
    Resolution,
    SourceChoice,
    choose_residency,
    estimate_memory,
    format_status,
    preset_transform_conflict,
)

#: How much of the previous redraw timing survives into the reported one.
#: A plain last-value readout flickers between 2 ms and 9 ms on a drag and
#: is unreadable; this smooths it without hiding a real change.
_REDRAW_SMOOTHING = 0.7

#: Ruling V (M11, Task 3 fix round 2): how long `_cancel_in_flight` waits
#: for a cancelled preparation to actually clear before giving up and
#: proceeding anyway. `work()` checks `isCanceled()` once per line, so a
#: cancelled task stops within one line's processing -- measured at
#: roughly 13 ms to load plus 26 ms for an envelope, ~40 ms total. This is
#: several times that, generous for a slower disk or a larger file, while
#: staying two orders of magnitude below a full ~0.9 s preparation -- long
#: enough to almost never fire the "proceed anyway" branch, short enough
#: that it can never be mistaken for the UI hanging.
_CANCEL_TIMEOUT_MS = 250

#: Ruling W (fix round 3): the sentinel meaning "no choice is queued",
#: distinct from `None` -- `set_source(None)` is itself a legitimate call
#: (clearing the source), so `None` cannot double as "nothing queued" the
#: way it usually would.
_NOT_QUEUED = object()


class SliceEngine(QObject):
    """Everything between a chosen source and a slice. Owns no widgets."""

    def __init__(
        self,
        session: Any,
        on_prepared: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.on_prepared = on_prepared
        self.on_error = on_error
        self.on_progress = on_progress
        self._choice: SourceChoice | None = None
        self._resolution: Resolution | None = None
        self._lines: list[PreparedLine] = []
        #: The preset's steps as they stood when preparation was
        #: dispatched -- see `provenance()`. Deliberately NOT a live read
        #: of `site.presets[name]`: `save_preset` overwrites a name in
        #: place and `delete_preset` removes it outright, both ordinary
        #: actions while a source stays prepared (Ruling K).
        self._steps: tuple[dict[str, Any], ...] = ()
        self._plans: list[LinePlan] | None = None
        self._frame: CubeFrame | None = None
        self._z: ZAxis | None = None
        #: The chosen grid's binning fields as of the last `set_source`
        #: (Ruling P) -- NOT `_rebuild_geometry`, which may not have run
        #: yet (a resolution may not exist). Compared against on
        #: `grids_changed` (see `_on_grids_changed`/`_grid_fingerprint`,
        #: Ruling M).
        self._grid_fp: tuple[Any, ...] | None = None
        self._cube: SliceCube | None = None
        self._mode = "streaming"
        self._always_resident = False
        self._budget_bytes = DEFAULT_BUDGET_BYTES
        self._redraw_ms: float | None = None
        self._generation = 0
        self._running = False
        # See the module docstring: addTask() keeps no reference of its
        # own, so a task with no Python reference is collected silently
        # and its on_finished never runs.
        self._pending: set[QgsTask] = set()
        #: Tasks `_cancel_in_flight()` itself asked to stop (fix round 2,
        #: Ruling V). `QgsTaskWrapper.finished()` (verified directly in its
        #: installed source) synthesises `Exception("Task canceled")` for
        #: ANY cancelled task, indistinguishable by message alone from one
        #: this engine did not ask to cancel -- membership here is what
        #: lets `finished()` tell "expected, we did this on purpose" from
        #: "genuinely failed" apart, so a person rapidly changing combos
        #: never sees a spurious "Task canceled" warning.
        self._deliberately_cancelled: set[QgsTask] = set()
        #: Ruling W (fix round 3): guards `set_source` against itself.
        #: `_cancel_in_flight`'s confirm step spins a nested `QEventLoop`,
        #: which -- `ExcludeUserInputEvents` alone does not stop a
        #: `QTimer` or a queued signal -- can still deliver a SECOND,
        #: different `set_source` call from inside the first one's own
        #: call frame. Left unguarded, the reentrant call finishes first
        #: (bumping `_generation` and dispatching its own task), and then
        #: the OUTER call resumes, bumps `_generation` PAST it, and
        #: dispatches a second real task on top -- restoring the exact
        #: two-tasks-at-once segfault Ruling V exists to remove, with the
        #: OLDER (outer, chronologically-first) choice winning instead of
        #: the newer one. See `set_source`'s own guard for the rest.
        self._dispatching = False
        #: The choice a reentrant `set_source` call recorded while
        #: `_dispatching` was `True`, or `_NOT_QUEUED`. Applied by the
        #: outer call's own `finally`, once it is safe to dispatch again --
        #: "the latest choice wins" is the property a person clicking
        #: through the Source combos actually expects, and queuing (rather
        #: than refusing) is what keeps that true even when a change
        #: arrives while another is still being cancelled.
        self._queued_choice: Any = _NOT_QUEUED
        session.site_closed.connect(self.clear)
        session.grids_changed.connect(self._on_grids_changed)

    # ---- state ------------------------------------------------------------
    @property
    def is_prepared(self) -> bool:
        return bool(self._lines)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def line_count(self) -> int:
        return len(self._lines)

    @property
    def frame(self) -> CubeFrame | None:
        return self._frame

    @property
    def z(self) -> ZAxis | None:
        return self._z

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def choice(self) -> SourceChoice | None:
        """What this engine was last pointed at. The exporter needs it to
        write a recipe; nothing may reach past this for `_choice`."""
        return self._choice

    @property
    def has_cube(self) -> bool:
        """Whether a resident cube is currently held.

        Public because "did this operation quietly build a cube?" is a
        contract, not an implementation detail: spec 7.4 makes a resident
        cube a latency optimisation and never a capability, and export is
        the operation most tempted to forget that.
        """
        return self._cube is not None

    @property
    def output_unipolar(self) -> bool:
        """Whether a slice from this source has no negative side.

        Exactly `transform != NO_TRANSFORM`, and that is a structural fact
        rather than a guess: the transform is appended AFTER the preset's
        steps, so it is always the last enabled step. `_build_stack`
        asserts the two agree, so a future edit that reorders them fails
        loudly instead of putting unipolar data on a bipolar table.
        """
        return self._choice is not None and self._choice.transform != NO_TRANSFORM

    @property
    def estimate(self) -> MemoryEstimate:
        samples = sum(int(line.data.size) for line in self._lines)
        n_cells = self._frame.n_cells if self._frame is not None else 0
        nz = self._z.nz if self._z is not None else 0
        return estimate_memory(samples, n_cells, nz)

    def set_always_resident(self, flag: bool) -> None:
        """The settings override of spec 9.2, worded there for what it
        buys: *keep the whole volume in memory for faster dragging*."""
        self._always_resident = bool(flag)
        self._choose_mode()

    def set_budget_bytes(self, budget: int) -> None:
        self._budget_bytes = int(budget)
        self._choose_mode()

    def _choose_mode(self) -> None:
        self._mode = choose_residency(
            self.estimate, len(self._lines), self._budget_bytes, self._always_resident
        )

    # ---- source -----------------------------------------------------------
    def _cancel_in_flight(self) -> None:
        """Stop any preparation already running, and wait for it to clear.

        Ruling V (fix round 2): `_generation` discards a superseded
        task's RESULT, which is not the same thing as stopping the task
        itself -- two real preparations reading the same lines on two
        worker threads segfaulted this plugin reproducibly (Task 3, fix
        round 1), and that fix only closed the identical-choice case
        (`SlicesDock.prepare`'s own no-op guard). Two GENUINELY DIFFERENT
        choices dispatched within about a second of each other -- a
        person clicking through the Source combos, not just a test
        fixture -- still overlapped. `loader.py` avoids the analogous
        hazard by refusing to double-dispatch a key at all
        (`if key in self._tasks`); the equivalent here, since a superseded
        choice must still be replaced rather than merely refused, is to
        cancel the old one and confirm it actually stopped before
        starting the new one.

        Called BEFORE `_generation` is bumped, deliberately: the
        cancelled task's own `finished()` callback is what actually
        clears `self._running` and wakes `wait_for_preparation` below (via
        `_finish_preparation`) -- and `finished()` only takes that path
        when its captured generation still matches `self._generation`.
        Bumping first would make every one of THIS task's own terminal
        paths look stale to itself, so `wait_for_preparation` would never
        see the `on_prepared` it is waiting on and would sit out the full
        timeout even though the task genuinely, promptly stopped.

        Bounded, not open-ended: `work()` checks `isCanceled()` once per
        line, so this waits about one line's processing
        (`_CANCEL_TIMEOUT_MS`), not the ~0.9 s a full preparation takes.
        If it still has not cleared by then, this reports through
        `on_error` and returns anyway rather than refusing the caller's
        new choice -- a `set_source` that sometimes silently declines to
        take effect is a worse failure mode than a rare residual overlap
        this method already spends its whole budget trying to prevent;
        `set_source` proceeding is what actually keeps "the latest choice
        always wins" true even in that unlikely case.

        Records each cancelled task in `_deliberately_cancelled` before
        calling `cancel()` (verified directly against `QgsTaskWrapper`'s
        installed source: it synthesises `Exception("Task canceled")` for
        ANY cancelled task, indistinguishable by message alone from a
        task this engine did not ask to stop) -- `finished()` checks that
        set to tell "expected, we did this" apart from "genuinely failed"
        before deciding whether to report anything through `on_error`.

        Waits with `ExcludeUserInputEvents` (Ruling W, fix round 3): half
        of closing the reentrancy hole this confirm step itself opened --
        see `set_source`'s own `_dispatching` guard for the other half,
        and `wait_for_preparation`'s docstring for why excluding user
        input alone is not enough (a `QTimer` or a queued signal still
        gets through, which the guard is what actually stops).
        """
        for task in list(self._pending):
            self._deliberately_cancelled.add(task)
            with contextlib.suppress(RuntimeError):  # the C++ side is already gone
                task.cancel()
        if self._running and not self.wait_for_preparation(
            _CANCEL_TIMEOUT_MS, QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
        ):
            self._report(
                "a previous slice-source preparation did not stop in time; "
                "proceeding with the new choice anyway"
            )

    def set_source(self, choice: SourceChoice | None) -> None:
        """Choose what goes into the cube and start preparing it.

        Raises ValueError, synchronously and before any work starts, if
        the preset carries an amplitude transform (plan Ruling 2) -- the
        caller is a dialog, and a refusal it can show is worth more than
        an error that arrives a second later through a callback. Never
        raises for a QUEUED, reentrant call (see the guard below) -- there
        is no caller left on the stack to hand a raised exception to by
        the time this method dispatches a queued choice on its own behalf.

        Cancels and waits out any preparation already in flight first
        (`_cancel_in_flight`, Ruling V) -- see its own docstring for why
        that must happen before, not after, `_generation` is bumped.

        Guarded against itself (Ruling W, fix round 3): `_cancel_in_
        flight`'s confirm step spins a nested event loop, which can
        deliver a SECOND `set_source` call (a person changing a combo
        again while the first change is still being cancelled) from
        INSIDE this very call's own frame. Measured directly before this
        guard existed: the reentrant call would dispatch its own task
        while this outer call was still cancelling the one before it, and
        then this outer call would resume and dispatch a second task on
        top -- two real tasks running at once again, with the OLDER
        (outer) choice ending up as `self._choice` because this frame
        bumps `_generation` last. A reentrant call is recorded in
        `_queued_choice` and returns immediately instead of dispatching;
        the OUTER call's own `finally` applies it once dispatching here is
        safe again, so the LATEST choice still wins -- just not from
        inside the nested loop that caused the problem.
        """
        if self._dispatching:
            self._queued_choice = choice
            return
        self._dispatching = True
        try:
            self._cancel_in_flight()
            self._generation += 1
            self._lines = []
            self._steps = ()
            self._plans = None
            self._cube = None
            self._grid_fp = None
            self._redraw_ms = None
            self._choice = choice
            if choice is None or not self.session.is_open:
                self._rebuild_geometry()
                return

            site = self.session.site
            steps = list(site.presets.get(choice.preset, []))
            conflict = preset_transform_conflict(steps)
            if conflict is not None:
                self._choice = None
                raise ValueError(
                    f"the preset {choice.preset!r} already contains the amplitude transform "
                    f"{conflict!r}. A cube's transform is chosen here and applied last, so "
                    f"remove {conflict!r} from the preset or choose it in Transform, not both"
                )
            # Captured now, not re-read from `site.presets` in `provenance()`:
            # `save_preset` overwrites a name in place and `delete_preset`
            # removes it outright, both ordinary actions while a source stays
            # prepared, and a live read would then describe steps the cube
            # was never actually built from (Ruling K) -- the same reasoning
            # `provenance()` already applies to `line_keys`, one field over.
            self._steps = tuple(dict(s) for s in steps)

            jobs: list[tuple[str, Any, np.ndarray]] = []
            frames = site.frames
            # Captured HERE, beside the `trace_coords` call below that actually
            # depends on it -- NOT in `_rebuild_geometry` (Ruling P). Task 3
            # calls `set_source` and `set_resolution` as two separate steps, so
            # a resolution -- and therefore a `_rebuild_geometry` call -- may
            # not exist yet when a grid changes. Keying the fingerprint to
            # `_rebuild_geometry` left exactly that window with `_grid_fp`
            # still None, so `_on_grids_changed` skipped silently and a later
            # `_rebuild_geometry` built a frame from the NEW grid while these
            # lines' `coords` stayed computed from the OLD one -- measured as a
            # uniform 4-cell shift (1 m / 0.25 m cell) with no exception and no
            # change in total coverage.
            grid = frames.get(choice.grid_id)
            self._grid_fp = self._grid_fingerprint(grid) if grid is not None else None
            for key in choice.line_keys:
                try:
                    line = self.session.line_for_key(key)
                    jobs.append((key, line, line.trace_coords(frames)))
                except Exception as exc:  # noqa: BLE001 -- a missing grid or a stale key
                    self._report(f"{key}: {exc}")
            if not jobs:
                self._rebuild_geometry()
                self._finish_preparation()
                return
            self._start_task(jobs, steps, choice.transform, self._generation)
        finally:
            self._dispatching = False
            queued, self._queued_choice = self._queued_choice, _NOT_QUEUED
            if queued is not _NOT_QUEUED:
                # Applies through a normal (now non-reentrant, since
                # `_dispatching` was just cleared above) call to this same
                # method, rather than a second copy of the body above.
                # There is no caller left to hand a refusal to from here,
                # so a `ValueError` for the queued choice is reported
                # through `on_error` instead -- the same channel every
                # other failure reached from a callback already uses.
                try:
                    self.set_source(queued)
                except ValueError as exc:
                    self._report(str(exc))

    def _build_stack(self, steps: Sequence[dict[str, Any]], transform: str) -> StepStack:
        """The preset, then the transform. Order is the whole point.

        `StepStack.output_unipolar` reports the LAST ENABLED step and is
        deliberately conservative: `[amp_abs, gain_agc]` reports False
        though AGC preserves unipolarity. Appending the transform makes
        that conservatism irrelevant, because the transform is always
        last. The assert is cheap and pins the property for whoever edits
        this next.
        """
        stack = StepStack.from_dicts([dict(s) for s in steps])
        if transform != NO_TRANSFORM:
            stack.append(build_step(transform))
        if stack.output_unipolar != (transform != NO_TRANSFORM):
            raise ValueError(
                "the built stack's polarity disagrees with the chosen transform; "
                "the transform must be the last enabled step"
            )
        return stack

    def _start_task(
        self,
        jobs: list[tuple[str, Any, np.ndarray]],
        steps: Sequence[dict[str, Any]],
        transform: str,
        generation: int,
    ) -> None:
        # Validated on the main thread, before the task runs, so a bad
        # preset cannot surface from a worker thread.
        self._build_stack(steps, transform)
        requested_against = self.session.site
        total = len(jobs)
        failures: list[str] = []

        def work(task: QgsTask) -> Any:
            out: list[PreparedLine] = []
            for index, (key, line, coords) in enumerate(jobs):
                if task.isCanceled():
                    return None
                try:
                    profiles = line.load()
                    radargram = Radargram.from_profile(profiles[0])
                    stack = self._build_stack(steps, transform)
                    stack.source = radargram
                    result = stack.result()
                    out.append(
                        PreparedLine(
                            key=key,
                            data=np.asarray(result.data, dtype=np.float32),
                            dt_ns=result.dt_ns,
                            t0_ns=result.t0_ns,
                            coords=coords,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 -- one bad line must not
                    # abandon the other twenty-three; it is named and skipped.
                    failures.append(f"{key}: {exc}")
                task.setProgress(100.0 * (index + 1) / total)
            return out

        def finished(exception: BaseException | None, result: Any = None) -> None:
            self._pending.discard(task)
            # Fix round 2, Ruling V: recorded (and cleared) here, before
            # any staleness check, because `_cancel_in_flight()` cancels
            # this very task BEFORE `_generation` is bumped past it -- see
            # that method's own docstring for why -- so this callback
            # still sees a MATCHING generation and does not return early.
            was_cancelled_here = task in self._deliberately_cancelled
            self._deliberately_cancelled.discard(task)
            # Whether THIS callback owns the notification duty. It does
            # not for the two staleness checks just below -- a newer
            # request, or a different site, already owns it -- but every
            # other exit from here on is this request's own terminal
            # edge, and the `finally` below must fire `_finish_preparation`
            # for every one of them: a whole-task exception, an exception
            # raised while finishing (e.g. `_rebuild_geometry` below), and
            # plain success alike. Before this, three of the four exits
            # skipped it, and a caller waiting on it (`wait_for_preparation`)
            # blocked for the whole timeout instead of waking -- the same
            # lesson `loader.py`'s own addTask()-failure branch draws by
            # re-emitting `loading_changed` rather than leaving it unset.
            notify = False
            try:
                if generation != self._generation:
                    return  # a newer source was chosen; this result is stale
                if self.session.site is not requested_against:
                    return  # the site was closed or replaced under us
                notify = True
                self._running = False
                for message in failures:
                    self._report(message)
                if exception is not None:
                    # `QgsTaskWrapper.finished()` (verified directly in its
                    # installed source) synthesises `Exception("Task
                    # canceled")` for ANY cancelled task, indistinguishable
                    # by message alone from one this engine did not ask to
                    # stop. Stay silent for exactly the ones `_cancel_in_
                    # flight()` cancelled on purpose -- a person rapidly
                    # changing the Source combos must not see a spurious
                    # "Task canceled" warning for doing exactly what those
                    # combos already invite; a genuine failure (a bad file,
                    # a worker-side bug) still gets reported either way.
                    if not (was_cancelled_here and str(exception) == "Task canceled"):
                        self._report(str(exception))
                    return
                self._lines = list(result or [])
                self._rebuild_geometry()
            except Exception as exc:  # noqa: BLE001 -- see the module docstring:
                # QgsTaskWrapper swallows this with no traceback anywhere.
                self._running = False
                notify = True
                self._report(f"could not finish preparing the slice source: {exc}")
            finally:
                if notify:
                    self._finish_preparation()

        task = QgsTask.fromFunction("nsgeo: prepare slice source", work, on_finished=finished)
        task.progressChanged.connect(lambda pct: self._emit_progress(pct, total))
        self._pending.add(task)
        self._running = True
        if not QgsApplication.taskManager().addTask(task):
            # Never added, so on_finished will never run and nothing else
            # holds a reference either: undo everything here, and notify
            # just as every other terminal path does (see the module
            # docstring) -- loader.py's own version of this branch
            # re-emits `loading_changed(key, False)` for the same reason.
            self._pending.discard(task)
            self._running = False
            self._report("could not schedule the slice source preparation")
            self._finish_preparation()

    def _emit_progress(self, percent: float, total: int) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(int(round(percent / 100.0 * total)), total)
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            self._report(f"could not report progress: {exc}")

    def _finish_preparation(self) -> None:
        """Announce the terminal edge, and never let the callback escape.

        Called from `finished`'s own `finally` so that EVERY terminal path
        notifies (a caller watching for completion must not hang), which
        means it runs OUTSIDE `finished`'s own `except`. So the guard
        belongs here: `QgsTaskWrapper.finished` swallows anything raised
        out of an `on_finished` callback with no log and no traceback
        anywhere -- verified directly in its installed source -- and the
        dock's `on_prepared` (Task 3) rebuilds widgets, so it is a handler
        that really can raise.
        """
        if self.on_prepared is None:
            return
        try:
            self.on_prepared()
        except Exception as exc:  # noqa: BLE001 -- see above
            self._report(f"could not finish preparing the slice source: {exc}")

    def _report(self, message: str) -> None:
        """Report through `on_error`, and never let IT escape either.

        Called from `finished`'s `except` and from `_finish_preparation`'s
        own except above, both of which must not let a SECOND exception
        (a raising `on_error`) replace or compound the first -- there is
        no further channel to report a reporting failure to, so this is
        the one place in this module that swallows silently rather than
        reporting a step further.
        """
        if self.on_error is None:
            return
        with contextlib.suppress(Exception):
            self.on_error(message)

    # ---- geometry ---------------------------------------------------------
    def set_resolution(self, resolution: Resolution | None) -> None:
        """Set the binning geometry. Drops every plan; see the module docstring."""
        self._resolution = resolution
        self._rebuild_geometry()

    def _rebuild_geometry(self) -> None:
        # Unconditional, and wholesale. There is no such thing as keeping
        # a plan across a geometry change. `_grid_fp` is deliberately left
        # alone here: it is keyed to `set_source` (Ruling P), not to this
        # method, because this method may not have run at all yet (no
        # resolution chosen) when a grid change needs to be detected, and
        # because `set_resolution` also calls this method and must not
        # blank a fingerprint that still correctly describes the grid the
        # CURRENT lines were prepared against.
        self._plans = None
        self._cube = None
        self._frame = None
        self._z = None
        self._redraw_ms = None
        if self._choice is None or self._resolution is None or not self.session.is_open:
            self._choose_mode()
            return
        grid = self.session.grid(self._choice.grid_id)
        res = self._resolution
        self._frame = CubeFrame.for_grid(grid, res.cell)
        self._z = ZAxis.from_range(res.t0_ns, res.t1_ns, res.dz_ns)
        self._choose_mode()

    @staticmethod
    def _grid_fingerprint(grid: Any) -> tuple[Any, ...]:
        """The grid fields a cube is actually binned from.

        Deliberately NOT the whole `Grid`. `velocity` relabels depths
        without rebinning -- that is the entire reason the z axis is
        two-way time (spec 5.2) -- and `default_spacing` only seeds the
        dock's default fill radius, so re-running 0.9 s of preparation
        for either would be waste. `Grid` is a frozen dataclass, so these
        compare exactly.
        """
        return (grid.origin, grid.azimuth, grid.size_x, grid.size_y, grid.crs)

    def _on_grids_changed(self) -> None:
        """React to `replace_grid`/`remove_grid` (Ruling M), and to a
        velocity-only edit that leaves binning untouched (Ruling Q).

        A slot on a `pyqtSignal`: every branch below reports through
        `on_error`/`_finish_preparation` rather than raising past this
        method, matching every other slot in this codebase.

        `replace_grid` changes exactly the fields `CubeFrame.for_grid`
        reads AND the world coordinates every prepared line's `coords`
        were computed from -- M10's `_check_plans_current` guard is
        structurally blind to it, because `plan.frame` and the frame this
        engine holds become the SAME (now stale) object, so `!=` never
        fires. A full re-preparation, not merely a geometry rebuild, is
        the only way to pick up coordinates that were computed from the
        OLD grid.

        When the fingerprint has NOT changed, `replace_grid` may still
        have run -- `set_grid_velocity` goes through it too, and
        `grids_changed` carries no information about which grid or which
        field changed. `provenance()` reads `resolved_velocity` LIVE, but
        `cube()` freezes a `Provenance` snapshot into the `SliceCube` the
        moment it is built; a resident cube built before a velocity edit
        would otherwise export the STALE velocity forever, while a
        streaming source (no cube held) always reads the fresh one. Only
        `self._cube` is dropped -- the prepared lines and the plans do not
        depend on velocity at all, so dropping them would pay 0.9 s for
        nothing.
        """
        if self._choice is None:
            return
        grid_id = self._choice.grid_id
        try:
            grid = self.session.grid(grid_id)
        except KeyError:
            self.clear()
            self._report(f"grid {grid_id!r} no longer exists; the slice source was cleared")
            return
        if self._grid_fp is None:
            return
        if self._grid_fingerprint(grid) != self._grid_fp:
            try:
                self.set_source(self._choice)
            except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
                self._report(f"could not re-prepare after the grid changed: {exc}")
            return
        self._cube = None

    def _require_geometry(self) -> tuple[CubeFrame, ZAxis]:
        if self._frame is None or self._z is None:
            raise RuntimeError("no slice geometry: choose a source and a resolution first")
        return self._frame, self._z

    def _ensure_plans(self) -> list[LinePlan]:
        """Plan every line against the CURRENT frame and axis.

        Lets `CoverageError` propagate rather than caching a failure: a
        line whose recording window does not cover the z range names
        itself in the message, and spec 9.1 wants the user to act on that
        (shrink the range, or exclude the line) rather than see a slice
        with a line silently missing from it.
        """
        if self._plans is None:
            frame, z = self._require_geometry()
            self._plans = [plan_line(line, frame, z) for line in self._lines]
        return self._plans

    # ---- slices -----------------------------------------------------------
    def _slice(self, window: SliceWindow) -> tuple[np.ndarray, np.ndarray]:
        """One slice, untimed. Used where a redraw timing would be a lie --
        the shared-limit pass takes tens of windows and is not a redraw."""
        frame, z = self._require_geometry()
        if not self._lines:
            raise RuntimeError("no lines are prepared")
        plans = self._ensure_plans()
        if self._mode == "resident":
            cube = self.cube()
            return cube.slice_levels(window.k0, window.k1), cube.coverage()
        return stream_slice(self._lines, plans, frame, z, window.k0, window.k1)

    def slice_at(self, window: SliceWindow) -> tuple[np.ndarray, np.ndarray]:
        """One slice and its coverage, both (ny, nx) in the grid-local frame.

        `values` is NaN where `coverage` is zero -- unfilled, which is
        what the coverage view shows and what `fill` consumes.
        """
        if self._mode == "resident":
            self.cube()  # built outside the timer: a build is not a redraw
        started = time.perf_counter()
        result = self._slice(window)
        self._record_redraw((time.perf_counter() - started) * 1000.0)
        return result

    def _record_redraw(self, ms: float) -> None:
        if self._redraw_ms is None:
            self._redraw_ms = ms
        else:
            self._redraw_ms = _REDRAW_SMOOTHING * self._redraw_ms + (1.0 - _REDRAW_SMOOTHING) * ms

    def shared_limit(self, thickness_levels: int, clip: Any, radius_cells: int) -> float:
        """One display limit for the whole source, at this thickness.

        Spec 8's shared stretch. Measured over slices at the thickness
        being displayed and never over the raw levels -- see
        `nsgeo.slices.display.shared_limit` for the measurement that makes
        the difference a bug rather than a nuance.

        Final review, Important 1: measured over `fill(...)`ed slices, not
        raw (unfilled) ones -- `radius_cells` is now a required argument,
        not an afterthought. `refresh_slice()` always displays `fill(values,
        coverage, radius_cells())`; this method used to measure the shared
        limit over `self._slice(w)[0]` (the UNFILLED array, coverage-zero
        cells still `NaN`) while `display_limit()`'s "this slice" branch
        measured the FILLED one -- two branches of the same stretch
        measuring two different quantities, and the shared (default)
        branch measuring something never actually drawn. Measured directly
        on this repo's own four real DZT files at the dock's own seeded
        defaults (thickness 23 levels, radius 0.75 m, cell 0.25 m -> 3
        cells; see `test_shared_limit_measures_the_filled_array_actually_
        displayed`): the unfilled measurement came out 1.10x too high with
        `amp_envelope` (2.114 vs. the correct 1.926) and 1.69x too high
        with no transform (0.364 vs. 0.215) -- the out-of-the-box
        configuration, since `transform_combo` auto-selects "none" -- so
        every slice rendered noticeably dimmer than intended, identically
        at every depth: exactly the "reads as dim data rather than a wrong
        limit" failure `render.UnipolarClip`'s and `display.shared_limit`'s
        own docstrings exist to prevent, one layer further out. Both
        numbers are a property of this corpus and this processing, not a
        guarantee about any other one -- do not turn them into a
        threshold.

        Builds its own window list and fills each one directly, in BOTH
        modes, rather than delegating the resident branch to
        `nsgeo.slices.display.shared_limit`: that function reads
        `cube.slice_levels` straight, with no fill step of its own, so
        using it here would leave the resident branch with the same bug
        this fix removes from the streaming one. Windows abut (`step ==
        thickness`) and a thinner FINAL window is appended whenever
        `thickness_levels` does not evenly divide `z.nz`, exactly as the
        core `shared_limit` does -- omitting it would silently measure the
        resident and streaming stretch over two different sets of levels,
        which is the mismatch a mode switch must never produce.
        """
        _, z = self._require_geometry()
        windows = list(plan_windows(z, thickness_levels, thickness_levels))
        if windows[-1].k1 < z.nz:
            windows.append(SliceWindow(windows[-1].k1, z.nz))
        if self._mode == "resident":
            cube = self.cube()
            coverage = cube.coverage()
            slices = (fill(cube.slice_levels(w.k0, w.k1), coverage, radius_cells) for w in windows)
        else:
            slices = (fill(*self._slice(w), radius_cells) for w in windows)
        return limit_over_slices(slices, clip)

    def cube(self) -> SliceCube:
        """The resident cube, built on first use and cached.

        A latency optimisation, never a capability (spec 7.4) -- every
        caller here works without one. The exporter and the `.npz` writer
        use it because they want the whole volume anyway.

        Raises the same `RuntimeError` `_slice` already raises for zero
        lines (M11 Task 6 fix round 1, Important 2). Without this guard,
        `save_cube_npz`'s direct `engine.cube()` call -- unlike `slice_at`,
        which reaches `_slice`'s own check first in every mode but this
        one -- built and returned a full-size, all-NaN `SliceCube` with no
        exception at all: `set_source` clears `_lines` synchronously while
        a re-preparation is still in flight, but leaves `_frame`/`_z`
        alone, so `_require_geometry()` keeps succeeding. A click on "Save
        cube..." during that ~0.9 s window wrote a real `.npz`, recorded
        it in `site.cubes`, and reported success -- a survey file gaining
        a record for a cube with no data in it.
        """
        if self._cube is None:
            if not self._lines:
                raise RuntimeError("no lines are prepared")
            frame, z = self._require_geometry()
            plans = self._ensure_plans()
            self._cube = build_cube(self._lines, plans, frame, z, self.provenance())
        return self._cube

    def provenance(self) -> Provenance:
        """What a reader needs to trust the cube.

        `line_keys` comes from the lines that were actually PREPARED, not
        from the lines that were asked for: a line that failed is not in
        the cube, and a provenance that claims it is misleads exactly the
        reader it exists for.

        `steps` is `self._steps` -- the preset as it stood when
        preparation was DISPATCHED (captured in `set_source`), never a
        live re-read of `site.presets[preset_name]` (Ruling K):
        `save_preset` overwrites a name in place and `delete_preset`
        removes it outright, both ordinary actions while a source stays
        prepared, and a live read would then describe steps the cube was
        never actually built from -- the same defect this docstring
        already rejects for `line_keys`, one field over.
        """
        if self._choice is None:
            raise RuntimeError("no source is chosen")
        velocity = None
        if self._lines:
            velocity = self.session.resolved_velocity(self._lines[0].key).to_dict()
        return Provenance(
            line_keys=tuple(line.key for line in self._lines),
            preset_name=self._choice.preset,
            steps=self._steps,
            transform=self._choice.transform or "none",
            velocity=velocity,
            built_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            core_version=nsgeo.__version__,
        )

    def status_text(self) -> str:
        return format_status(self._mode, len(self._lines), self.estimate, self._redraw_ms)

    # ---- lifecycle --------------------------------------------------------
    def clear(self) -> None:
        """Drop the source and everything derived from it.

        Final review, Important 2: `_cancel_in_flight()` runs FIRST, before
        `_generation` is bumped -- the same order `set_source` and
        `dispose()` already use, and for the identical reason (see
        `_cancel_in_flight`'s own docstring). Before this fix, `clear()`
        forced `_running` to `False` directly without cancelling
        `_pending`, and `_cancel_in_flight`'s own confirm-and-wait is
        gated on `if self._running` -- so the very next call into it saw
        `_running` already `False` and skipped the wait entirely, even
        though a task genuinely dispatched before `clear()` was still
        executing on a worker thread. `site_closed -> clear()` immediately
        followed by `site_opened -> ... -> set_source()` -- the ordinary
        "File > Open site..." sequence -- is precisely how that happens: a
        one-grid site's own construction auto-dispatches a ~0.9 s
        preparation, the user opens a different site mid-preparation, and
        the newly-dispatched task then ran concurrently with the one
        `clear()` never actually stopped -- two preparations on two worker
        threads, the condition this module's own docstring records as
        having "segfaulted this plugin reproducibly". Reachable the same
        way through `_on_grids_changed`'s removed-grid branch, which also
        calls `clear()`.
        """
        self._cancel_in_flight()
        self._generation += 1
        self._choice = None
        self._resolution = None
        self._lines = []
        self._steps = ()
        self._plans = None
        self._frame = None
        self._z = None
        self._grid_fp = None
        self._cube = None
        self._redraw_ms = None
        self._running = False
        # A large cube's kernel spectra are tens of megabytes and have no
        # reason to outlive the source that needed them.
        clear_kernel_cache()

    def dispose(self) -> None:
        # nsgeo-qgis fix round 1 (M11, Task 3): stop any in-flight
        # preparation FIRST. Every caller of this method before Task 3's
        # SlicesDock always called wait_for_preparation() itself before
        # ever disposing, so a task genuinely still running at dispose()
        # time was never actually exercised -- until SlicesDock.
        # rebuild_source() started dispatching one automatically the
        # moment a grid, preset and lines already exist, from ANY
        # plugin's initGui(), including test fixtures that have nothing
        # to do with slices and never call wait_for_preparation()
        # themselves (test_plugin_difference_presets.py's `plugin`
        # fixture, say, which saves a preset mid-test and unloads without
        # knowing a SlicesDock is listening at all). Left running past
        # dispose(), that task keeps executing against callbacks this
        # method is about to null out, and can still be mid-flight when a
        # LATER, unrelated test's own real QgsTask starts -- measured
        # directly as a segfault (two worker threads inside dewow's
        # `running_mean` at once, from two different tests' orphaned
        # tasks, not from anything in the same test).
        #
        # Fix round 2 (Ruling V): routed through `_cancel_in_flight()`
        # rather than a bare `wait_for_preparation()` -- a teardown has no
        # reason to sit out however much of a full ~0.9 s preparation is
        # left when it is about to discard the result anyway; cancelling
        # first bounds this to one line's processing
        # (`_CANCEL_TIMEOUT_MS`), the same reasoning `set_source` now
        # uses for the same problem.
        self._cancel_in_flight()
        # Same two exceptions map_link.py's own disconnects suppress, and
        # for the same reason: a RuntimeError from a wrapper that reports
        # as not-deleted but whose underlying C++ object is gone regardless
        # must not stop this method from still calling clear() below.
        with contextlib.suppress(TypeError, RuntimeError):
            self.session.site_closed.disconnect(self.clear)
        with contextlib.suppress(TypeError, RuntimeError):
            self.session.grids_changed.disconnect(self._on_grids_changed)
        self.clear()
        self.on_prepared = None
        self.on_error = None
        self.on_progress = None

    def wait_for_preparation(
        self,
        timeout_ms: int = 20_000,
        flags: QEventLoop.ProcessEventsFlag = QEventLoop.ProcessEventsFlag.AllEvents,
    ) -> bool:
        """Spin the event loop until preparation finishes.

        For tests, directly -- and, with a short timeout,
        `_cancel_in_flight()` (fix rounds 1-2), which every real
        `set_source` and `dispose()` call routes through: a real caller
        blocking for at most one line's processing (or, uncancelled, one
        full preparation) is a small, bounded cost, and safer than
        proceeding while a task is still writing into this engine.

        `flags` narrows what this nested loop processes while waiting.
        `_cancel_in_flight` (Ruling W, fix round 3) passes
        `ExcludeUserInputEvents`: a task's own `finished` still arrives
        (it is a posted event, not user input), so the confirm keeps
        working, but a mouse wheel or a held arrow key over a `QComboBox`
        -- which emits `currentTextChanged` every 10-20 ms, well inside
        this wait's own ~250 ms window -- can no longer re-enter
        `set_source` from inside this very call. Left at the default
        here for tests, which often DRIVE this wait by changing a combo
        or emitting a signal themselves and need that processed.

        Returns whether it actually finished while this waited, not merely
        whether nothing is running afterwards -- a bare timeout would
        otherwise read as success.
        """
        if not self._running:
            return True
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        finished = False
        previous = self.on_prepared

        def done() -> None:
            nonlocal finished
            finished = True
            # `_finish_preparation` already guards its call to THIS
            # function against a raising callback (Ruling O), which means
            # a raising `previous()` cannot escape `done()` either way --
            # but without this `finally`, it would skip `loop.quit()` and
            # leave this helper waiting out the full `timeout_ms` instead
            # of waking as soon as preparation actually finished.
            try:
                if previous is not None:
                    previous()
            finally:
                loop.quit()

        self.on_prepared = done
        timer.start(timeout_ms)
        loop.exec(flags)
        self.on_prepared = previous
        return finished and not self._running
