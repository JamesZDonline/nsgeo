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
  request, or a different site, owns the notification now. The
  closed-site check still ends `_running` and wakes a confirm wait
  without calling `on_prepared` (ruling T3-e, M12): it is this request's
  own edge, and leaving the wait to time out reported a stopped task as
  "did not stop in time".
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
  since that relabels depths without rebinning -- but an edit to the
  chosen grid's velocity still drops any resident `_cube` (never the
  lines or the plans), because `cube()` freezes a `Provenance` snapshot
  at build time and `provenance()` reads velocity live; without this, an
  export's recorded velocity would depend on whether a cube happened to
  be resident. Only the chosen grid's own edit does (M12 final review
  I2): `grids_changed` fires for every grid, and a site holds one engine
  per grid, so dropping on any edit threw away every resident cube in
  the site for one grid's velocity.
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
* **A background solve must never land on a plan it was not made from**
  (interpolation spec §7, plan calls 6 and 8). Minimum curvature keeps its
  solved slices keyed by the values alone, so a solve made on the plan for
  one cell or line set, landing after that plan was replaced, would be
  served for the new one: plausible, and wrong. `PendingSolve.land` checks
  that the engine still holds the very plan object the job was made from,
  and every place that drops or replaces the plan drops the solved slices
  with it (`_drop_fill`). The cache is written on the GUI thread only.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timezone
from typing import Any

import nsgeo
import numpy as np
from nsgeo.geometry import GridPlacement
from nsgeo.processing import Radargram, StepStack, build_step, step_title
from nsgeo.slices import (
    CubeFrame,
    CurvaturePlan,
    FillWeights,
    FinishSettings,
    LinePlan,
    PreparedLine,
    Provenance,
    SliceCube,
    SliceFill,
    SliceWindow,
    ZAxis,
    build_cube,
    covered_cells,
    finish_slice,
    limit_over_slices,
    plan_fill,
    plan_line,
    plan_windows,
    smooth,
    stream_slice,
)
from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QEventLoop, QObject, QTimer

from nsgeo_qgis.line_edit import same_placement
from nsgeo_qgis.slices_plan import (
    DEFAULT_METHOD,
    LIVE_SOLVE_BUDGET_MS,
    NO_TRANSFORM,
    PREVIEW_METHOD,
    SOLVED_SLICES_KEPT,
    MemoryEstimate,
    Resolution,
    SliceFinish,
    SourceChoice,
    choose_residency,
    estimate_memory,
    format_status,
    limit_windows,
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


def solve_key(values: np.ndarray) -> bytes:
    """The solved-slice cache key of `values` (plan call 8): a BLAKE2b digest
    of their bytes, shape and dtype. The values themselves, never the window
    they came from: another preset or line set at the same window gives other
    values on the same plan, and must not be served this solve."""
    values = np.ascontiguousarray(values)
    digest = hashlib.blake2b(values.tobytes(), digest_size=16)
    digest.update(str(values.shape).encode())
    digest.update(str(values.dtype).encode())
    return digest.digest()


class PendingSolve:
    """One minimum-curvature solve for the refine worker (a `RefineJob`,
    plan calls 6 and 8).

    `run` is the worker's, and touches only the job: its private copy of the
    values, the plan (frozen: read, never written) and its own result
    fields. `land` is the GUI thread's, and the only way a background solve
    reaches the engine's cache. It lands only while the engine still holds
    the very plan the job was made from (see the module docstring).
    """

    def __init__(
        self,
        engine: SliceEngine,
        plan: CurvaturePlan,
        values: np.ndarray,
        key: bytes,
        *,
        copy: bool = True,
    ) -> None:
        self._engine = engine
        self._plan = plan
        # `copy=False` only for an array the engine has just made and hands
        # to no one else (`stretch_solves`), which is private already.
        self._values: np.ndarray | None = np.array(values, copy=True) if copy else values
        #: The solved-slice cache key of the values (`solve_key`).
        self.key = key
        #: Set by `run`: the unsmoothed slice, and the solve's own time in ms.
        self.solved: np.ndarray | None = None
        self.ms: float | None = None

    @property
    def engine(self) -> SliceEngine:
        """The engine this solve lands in. With `key`, what tells two jobs
        apart: two of a site's grids can hold equal values."""
        return self._engine

    @property
    def plan(self) -> CurvaturePlan:
        """The plan this solve runs on. It lands only while its engine still
        holds it (`SliceEngine.holds`)."""
        return self._plan

    def run(self, should_stop: Callable[[], bool]) -> None:
        """Solve, on the worker thread; `SolveStopped` when `should_stop` asks."""
        values = self._values
        if values is None:
            raise RuntimeError("this solve has already run")
        try:
            started = time.perf_counter()
            solved, _ = self._plan.solve(values, should_stop)
            self.ms = (time.perf_counter() - started) * 1000.0
            self.solved = solved
        finally:
            # A list holds its jobs until it ends: twelve stretch windows'
            # values need not outlive their solves.
            self._values = None

    def land(self) -> bool:
        """Into the engine's cache, and its last solve time, on the GUI
        thread, only if the engine still holds the plan this job was made
        from. Whether it did."""
        if self.solved is None or self.ms is None:
            return False
        return self._engine._land(self._plan, self.key, self.solved, self.ms)


class SliceEngine(QObject):
    """Everything between a chosen source and a slice. Owns no widgets."""

    def __init__(
        self,
        session: Any,
        on_prepared: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        parent: QObject | None = None,
        *,
        on_grid_moved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.on_prepared = on_prepared
        self.on_error = on_error
        self.on_progress = on_progress
        #: R-P2 (M12): who re-prepares when the chosen grid moves. None (the
        #: default) keeps M11's behaviour: this engine re-prepares itself.
        #: Set, a move clears this engine and calls the hook instead, so
        #: an owner that serialises preparations across several engines
        #: (`SiteEngine`, trap 1) queues the re-preparation rather than
        #: having it start beside another engine's. See
        #: `_hand_over_the_move`.
        self.on_grid_moved = on_grid_moved
        self._choice: SourceChoice | None = None
        self._resolution: Resolution | None = None
        self._lines: list[PreparedLine] = []
        #: `_covered_count`'s cache; `None` means not counted for the current
        #: lines and frame (#113).
        self._covered: int | None = None
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
        #: Every site line's placement as of the last `set_source`, label
        #: dropped (a label is never geometry), keyed by line key. What
        #: `placements_changed` compares against on `lines_changed`: the
        #: prepared lines' `coords` were computed from these (line editing
        #: spec §4.5).
        self._placements: dict[str, Any] = {}
        #: The chosen grid itself, as of the last `set_source` or
        #: `grids_changed` (M12 final review I2): whether an edit that
        #: moved nothing was to THIS grid -- its velocity -- or to another.
        self._grid_seen: Any = None
        self._cube: SliceCube | None = None
        #: The interpolation weights for the current frame and settings, built
        #: on first use and kept: applying them is cheap per slice, building
        #: them is not (interpolation spec §7). One `(key, weights, preview)`
        #: with `key = (frame, method, max distance, search radius)`: the
        #: settings the weights are built from, so a smoothing drag never
        #: rebuilds them. Dropped wherever the lines or the frame can have
        #: changed, and checked against each slice's coverage too. For
        #: minimum curvature `weights` is the `CurvaturePlan` and `preview`
        #: the kriging weights built with it (plan call 5); for any other
        #: method `preview` is None.
        self._weights: tuple[tuple[Any, ...], SliceFill, FillWeights | None] | None = None
        #: Slices solved on that plan, unsmoothed, least recently used first
        #: (plan call 8), keyed by `solve_key`; at most `SOLVED_SLICES_KEPT`.
        #: Written on the GUI thread only, and dropped with the plan.
        self._solved: OrderedDict[bytes, np.ndarray] = OrderedDict()
        #: How long the last solve on that plan took, in ms; None before one
        #: has run on it (plan call 5). Dropped with the plan.
        self._last_solve_ms: float | None = None
        self._mode = "streaming"
        self._always_resident = False
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
        #: Ruling T3-e (M12): ends a `wait_for_preparation` in progress
        #: WITHOUT calling `on_prepared`. Set only while one is waiting.
        self._wake_waiter: Callable[[], None] | None = None
        session.site_closed.connect(self.clear)
        session.grids_changed.connect(self._on_grids_changed)
        # After `grids_changed`: a grid-length change moves reversed lines
        # and emits both, and the re-preparation `grids_changed` starts
        # leaves nothing for this one to do (line editing spec §4.5).
        session.lines_changed.connect(self._on_lines_changed)

    # ---- state ------------------------------------------------------------
    @property
    def is_prepared(self) -> bool:
        return bool(self._lines)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def has_live_task(self) -> bool:
        """Whether a preparation task of this engine may still be executing.

        Ruling T3-b (M12). `is_running` is this engine's CURRENT request,
        and `clear()` (so `dispose()` too) sets it False even when its
        bounded confirm wait gave up -- the abandoned task is then still
        reading a line on a worker thread until its next `isCanceled()`
        check. `_pending` holds every task until its `finished` has run,
        whatever its generation, so this is the truth a dispatcher needs
        before it starts another preparation (trap 1). M11's dock keeps
        reading `is_running`, whose meaning is unchanged.
        """
        return self._running or bool(self._pending)

    @property
    def line_count(self) -> int:
        return len(self._lines)

    def prepared_lines(self) -> tuple[PreparedLine, ...]:
        """The prepared lines, read-only. A tuple, not the live list: a
        caller inspecting coverage must not be able to reorder or drop
        what the next `_ensure_plans()` will plan."""
        return tuple(self._lines)

    def prepared_z_bounds(self) -> tuple[float, float] | None:
        """The two-way time range EVERY prepared line covers, or None.

        The INTERSECTION, never the union: `plan_line` refuses a cube
        whose z range runs past any one line's own recording window, so
        the range they have in common is the only one that can be binned.

        Read off the PREPARED lines -- the same `PreparedLine` objects
        `plan_line` validates -- rather than off the raw DZT headers,
        which is the whole point of its existing. A preset that crops the
        sample axis (`time_zero` drops 49 of 512 rows on this repo's own
        real files, moving the start ~10.6 ns later) leaves the header
        describing a window the processed line no longer has. Seeding the
        dock's z range from the header instead of from this shipped a
        default that could not slice at all: see
        `test_the_seeded_z_range_survives_a_preset_that_crops_the_sample_axis`.
        """
        if not self._lines:
            return None
        t0 = max(line.t0_ns for line in self._lines)
        t1 = min(line.t0_ns + (line.data.shape[0] - 1) * line.dt_ns for line in self._lines)
        if not t1 > t0:
            return None
        return (t0, t1)

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
        """The status line's and the residency choice's figures. The weights
        are counted for the method of those held (#148): the engine is handed
        a finish only when it draws, so before its first draw on a frame it
        counts the default method's, one set."""
        samples = sum(int(line.data.size) for line in self._lines)
        n_cells = self._frame.n_cells if self._frame is not None else 0
        nz = self._z.nz if self._z is not None else 0
        method = self._weights[0][1] if self._weights is not None else DEFAULT_METHOD
        return estimate_memory(samples, n_cells, nz, self._covered_count(), method=method)

    def _covered_count(self) -> int:
        """Cells the prepared lines fall in, for the packed cube's size (#113).

        Cached: the status line reads `estimate` on every redraw, and a count
        bins every trace. It never goes through `plan_line`, which can raise,
        and this is read from slots. Reset wherever `_plans` or `_lines` is.
        """
        if self._frame is None or not self._lines:
            return 0
        if self._covered is None:
            self._covered = covered_cells(self._frame, (line.coords for line in self._lines))
        return self._covered

    def set_always_resident(self, flag: bool) -> None:
        """The settings override of spec 9.2, worded there for what it
        buys: *keep the whole volume in memory for faster dragging*.

        Ruling AN (M11 final review): wired to a checkbox in the dock's
        Display group rather than to settings -- this plugin has no
        settings infrastructure, and building one was ruled beyond this
        milestone's scope.
        """
        self._always_resident = bool(flag)
        self._choose_mode()

    def _choose_mode(self) -> None:
        # Ruling AN (M11 final review): `set_budget_bytes` -- a second
        # override, for the BUDGET rather than the always-resident flag --
        # is deleted. It had zero callers anywhere, production or test: the
        # budget is a constant (spec 9.1/7.4 never asks for it to be
        # configurable), and an orphaned setter is worse than no setter at
        # all. `choose_residency`'s own `budget_bytes` default is this same
        # constant, so leaving it out here is not a behaviour change.
        self._mode = choose_residency(
            self.estimate,
            sum(int(line.data.shape[1]) for line in self._lines),
            always_resident=self._always_resident,
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

    def cancel_preparation(self) -> None:
        """Stop the preparation in flight, confirm it stopped, and start nothing.

        Ruling 1 (M12): `SiteEngine` owns one engine per grid and lets
        them prepare strictly one at a time, because two preparations at
        once segfault (trap 1). Leaving site scope must stop the grid
        being prepared without touching the grids already prepared, and
        none of the existing entry points does only that: `set_source`
        dispatches a new task, and `clear()` also drops the choice and the
        resolution. This is `_cancel_in_flight` made public -- cancel, and
        wait (bounded by `_CANCEL_TIMEOUT_MS`, about one line's processing)
        until the task has really ended.

        Afterwards `is_running` is False, unless that bounded wait ran out
        (reported through `on_error`). Then it stays True until the task
        actually finishes, which is exactly what a caller checking
        `is_running` before its next dispatch needs to see.

        The engine's lines are not to be trusted afterwards: the
        cancelled `set_source` had already dropped the previous ones, and
        the cancelled task's result may or may not have landed. The
        caller re-dispatches with `set_source` when it wants the grid.
        """
        self._cancel_in_flight()

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
            self._covered = None
            self._cube = None
            self._drop_fill()
            self._grid_fp = None
            self._placements = {}
            self._grid_seen = None
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
                # By title: the user removes it from the Processing list,
                # which shows titles, not ids (#82).
                title = step_title(conflict)
                raise ValueError(
                    f"the preset {choice.preset!r} already contains the {title} step. "
                    f"A cube's amplitude transform is chosen here and applied last, so "
                    f"remove {title} from the preset or choose it in Transform, not both"
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
            self._grid_seen = grid
            self._placements = {
                key: self._without_label(self.session.line_for_key(key).placement)
                for key in self.session.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
            }
            for key in choice.line_keys:
                try:
                    line = self.session.line_for_key(key)
                    other = getattr(line.placement, "grid_id", None)
                    if other is not None and other != choice.grid_id:
                        # A line moved to another grid is no longer this
                        # grid's to bin: its coords would land in a frame it
                        # is not placed in. The dock prunes its own choice,
                        # but a Whole site engine re-queued from a source the
                        # dock has not resent yet can still carry the key
                        # (line editing spec §4.5).
                        self._report(
                            f"{key}: now on grid {other!r}, not {choice.grid_id!r}; "
                            "left out of this source"
                        )
                        continue
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
                    # The site was closed or replaced under us. Ruling T3-e
                    # (M12): with the generation still matching, this is
                    # THIS request's own terminal edge -- any newer request
                    # bumps the generation first -- so it ends `_running`
                    # and wakes `_cancel_in_flight`'s confirm wait (which
                    # `clear()` on `site_closed` is spinning right now).
                    # Without that the wait sat out `_CANCEL_TIMEOUT_MS` and
                    # reported "did not stop in time" about a task that
                    # had stopped. It applies nothing and reports nothing,
                    # and wakes the wait without `on_prepared`: the dock's
                    # `_on_prepared` redraws and refills widgets, which has
                    # no business running for a site that is gone.
                    self._running = False
                    if self._wake_waiter is not None:
                        self._wake_waiter()
                    return
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
                self._covered = None
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
        #
        # The fill weights are the exception: they depend on the frame and the
        # populated cells, never on the z axis, so a dz/z0/z1 edit keeps them
        # (rebuilding takes about 5 s at 0.05 m on a 50 m grid). Kept only while
        # the frame is unchanged; `_fill_for` still checks the key and the
        # populated mask before reusing them. `set_source` and `clear` drop them.
        # The slices solved on a kept plan stay with it: a solve depends on the
        # plan and the values alone (plan call 8).
        held = (self._weights, self._solved, self._last_solve_ms)
        self._plans = None
        self._covered = None
        self._cube = None
        self._drop_fill()
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
        if held[0] is not None and held[0][0][0] == self._frame:
            self._weights, self._solved, self._last_solve_ms = held
        self._choose_mode()

    @staticmethod
    def _grid_fingerprint(grid: Any) -> tuple[Any, ...]:
        """The grid fields a cube is actually binned from.

        Deliberately NOT the whole `Grid`. `velocity` relabels depths
        without rebinning -- that is the entire reason the z axis is
        two-way time (spec 5.2) -- and `default_spacing` only seeds the
        dock's default cell and its interpolation distance, so re-running 0.9 s of preparation
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
        OLD grid. With `on_grid_moved` set (R-P2, M12) that
        re-preparation is handed to the owner instead of started here --
        see `_hand_over_the_move`.

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
        nothing -- and only when the chosen grid itself changed
        (`_grid_seen`, M12 final review I2). An edit to another grid
        leaves this cube's provenance true; a site's `SiteEngine` holds
        one engine per grid, and dropping every cube for one grid's
        velocity rebuilt them all on the UI thread on the next tick.
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
            if self.on_grid_moved is not None:
                self._hand_over_the_move(grid_id)
                return
            try:
                self.set_source(self._choice)
            except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
                self._report(f"could not re-prepare after the grid changed: {exc}")
            return
        if grid != self._grid_seen:
            self._cube = None  # Ruling Q: this grid's velocity changed
        self._grid_seen = grid

    @staticmethod
    def _without_label(placement: Any) -> Any:
        """A placement as geometry only: the label names a line and never
        moves it, so a label-only edit must not re-prepare (line editing spec §4.5)."""
        if isinstance(placement, GridPlacement):
            return dataclasses.replace(placement, label=None)
        return placement

    def _on_grid(self, key: str, grid_id: str) -> bool:
        try:
            placed = getattr(self.session.line_for_key(key).placement, "grid_id", None)
        except KeyError:
            return False  # removed in the same change
        return placed == grid_id

    def had_line(self, key: str) -> bool:
        """Whether `key` was a site line at the last `set_source`."""
        return key in self._placements

    def placements_changed(self, keys: Iterable[str]) -> bool:
        """Whether any of `keys`, a site line at the last `set_source` and
        still one, now sits somewhere else (label ignored). A line removed
        is not a move: `remove_lines` has its own way of reaching this
        engine, and a key that was never captured has nothing to compare."""
        for key in keys:
            old = self._placements.get(key)
            if old is None:
                continue
            try:
                new = self._without_label(self.session.line_for_key(key).placement)
            except KeyError:
                continue
            if isinstance(old, GridPlacement) and isinstance(new, GridPlacement):
                if not same_placement(old, new):
                    return True
            elif old != new:
                return True
        return False

    def _on_lines_changed(self) -> None:
        """React to `lines_changed` when a line this source holds moved
        (line editing spec §4.5): its prepared `coords` were computed from
        the old placement, so it is re-prepared the way a grid move is.

        A slot on a `pyqtSignal`: it reports, never raises. With
        `on_grid_moved` set the re-preparation is handed to the owner by the
        same `_hand_over_the_move` a grid move uses, so the owner's queue
        (trap 1) and This grid's site-scope gate (R-P5) still decide when a
        task starts. Otherwise this engine re-prepares itself, narrowed to
        the keys still on its grid: a line moved to another grid has left.
        An import or a removal leaves every captured placement as it was,
        and a label-only edit differs in nothing but the label, so neither
        reaches either branch."""
        try:
            choice = self._choice
            if choice is None or not self._placements or not self.session.is_open:
                return
            if not self.placements_changed(choice.line_keys):
                return
            if self.on_grid_moved is not None:
                self._hand_over_the_move(choice.grid_id)
                return
            # In survey order, as the dock's own choice is: a reorder can
            # arrive in the same change as the edit.
            held = set(choice.line_keys)
            narrowed = tuple(
                k
                for k in self.session.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
                if k in held and self._on_grid(k, choice.grid_id)
            )
            try:
                self.set_source(dataclasses.replace(choice, line_keys=narrowed))
            except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
                self._report(f"could not re-prepare after a line moved: {exc}")
        except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
            self._report(f"could not follow the line change: {exc}")

    def _hand_over_the_move(self, grid_id: str) -> None:
        """R-P2 (M12): the chosen grid moved and an owner re-prepares.

        The `set_source(self._choice)` above starts a task from inside
        this slot, outside any queue an owner keeps across engines. Moving
        one grid while another grid prepares -- or moving a grid that two
        engines hold -- would then run two preparations at once, which
        segfaulted M11 (trap 1). So: `clear()`, which cancels and waits
        out any task in flight and drops the lines binned at the old
        registration, then tell the owner, who queues the grid. Nothing is
        dispatched here.

        Still a slot: neither half may raise past it, so both report
        through `on_error`.
        """
        try:
            self.clear()
        except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
            self._report(f"could not drop the slice source after grid {grid_id!r} moved: {exc}")
        hook = self.on_grid_moved
        if hook is None:
            return
        try:
            hook()
        except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
            self._report(f"could not re-prepare after grid {grid_id!r} moved: {exc}")

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
        what the coverage view shows and what `finish` consumes.
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

    def finish_settings(self, finish: SliceFinish) -> FinishSettings:
        """`finish` in metres, at the chosen grid's line spacing NOW.

        The spacing is read from the session each time, so a spacing edit
        moves the metres without the finish moving (interpolation spec §8).
        """
        if self._choice is None or not self.session.is_open:
            raise RuntimeError("no source is chosen")
        return finish.in_metres(self.session.grid(self._choice.grid_id).default_spacing)

    def weights_cached(self, finish: SliceFinish) -> bool:
        """Whether `finish` would reuse the weights already built, so the
        caller knows to show a wait cursor when it would not. Compares the
        key only: a change of lines goes through `set_source`, which clears
        the cache, and `_fill_for` checks coverage as well. For minimum
        curvature the plan and its kriging preview are built together, so
        this means both."""
        frame = self._frame
        if self._weights is None or frame is None:
            return False
        return self._weights[0] == self._weights_key(frame, self.finish_settings(finish))

    @property
    def weights_nbytes(self) -> int:
        """The bytes held for interpolation now, 0 before anything is built:
        the weights, and for minimum curvature the plan, its kriging preview
        and the solved slices (plan call 9)."""
        if self._weights is None:
            return 0
        _, fill, preview = self._weights
        held = fill.nbytes + (0 if preview is None else preview.nbytes)
        return held + sum(solved.nbytes for solved in self._solved.values())

    @property
    def last_solve_ms(self) -> float | None:
        """How long the last minimum-curvature solve on the plan held now
        took; None before one has run on it, and after it is dropped."""
        return self._last_solve_ms

    @staticmethod
    def _weights_key(frame: CubeFrame, settings: FinishSettings) -> tuple[Any, ...]:
        # Smoothing is applied after the weights and is not part of them.
        return (frame, settings.method, settings.max_distance_m, settings.search_radius_m)

    def _drop_fill(self) -> None:
        """Drop the weights, or the minimum-curvature plan with its preview,
        and every slice solved on it (plan call 8)."""
        self._weights = None
        self._solved = OrderedDict()
        self._last_solve_ms = None

    def _held_fill(
        self, populated: np.ndarray, frame: CubeFrame, settings: FinishSettings
    ) -> tuple[tuple[Any, ...], SliceFill, FillWeights | None] | None:
        """What is held, if it was built for these settings and these cells."""
        held = self._weights
        if (
            held is not None
            and held[0] == self._weights_key(frame, settings)
            and np.array_equal(held[1].populated, populated.ravel())
        ):
            return held
        return None

    def _fill_for(
        self, coverage: np.ndarray, frame: CubeFrame, settings: FinishSettings
    ) -> tuple[SliceFill, FillWeights | None]:
        """The weights for these settings and cells, built if they are not
        held. For minimum curvature, the plan and the kriging preview at the
        same max distance and search radius, built together (plan call 5)."""
        populated = coverage > 0
        held = self._held_fill(populated, frame, settings)
        if held is not None:
            return held[1], held[2]
        # Dropped first: holding the old plan, preview and solved slices while
        # the new ones are built would double the peak, about 0.9 GB more at
        # the cell cap (`MAX_FRAME_CELLS`).
        self._drop_fill()
        md, sr = settings.max_distance_m, settings.search_radius_m
        fill = plan_fill(populated, frame.cell, settings.method, md, sr)
        preview: FillWeights | None = None
        if isinstance(fill, CurvaturePlan):
            built = plan_fill(populated, frame.cell, PREVIEW_METHOD, md, sr)
            assert isinstance(built, FillWeights)  # kriging plans weights
            preview = built
        self._weights = (self._weights_key(frame, settings), fill, preview)
        return fill, preview

    def section_fills(self, finish: SliceFinish) -> tuple[SliceFill, FillWeights | None]:
        """The fill a cut's section finishes with, and the kriging stand-in
        under minimum curvature (cut spec §5).

        What the engine holds when it was built for these settings and this
        cube's covered cells, which is what the slice's own draw leaves
        behind; otherwise built through `_fill_for` and held, so a cut never
        plans weights of its own. Needs a cube: `RuntimeError` without lines.
        """
        frame, _ = self._require_geometry()
        return self._fill_for(self.cube().coverage(), frame, self.finish_settings(finish))

    def _keep_solved(self, key: bytes, solved: np.ndarray) -> None:
        """Into the solved-slice cache as the most recent; the least recently
        used go past `SOLVED_SLICES_KEPT` (plan call 8)."""
        self._solved[key] = solved
        self._solved.move_to_end(key)
        while len(self._solved) > SOLVED_SLICES_KEPT:
            self._solved.popitem(last=False)

    def holds(self, plan: SliceFill) -> bool:
        """Whether `plan` is the plan or weights held now. Identity, not
        equality: a rebuilt plan for the same settings is another plan, and a
        solve made on a dropped one never lands (see the module docstring)."""
        held = self._weights
        return held is not None and held[1] is plan

    def _land(self, plan: CurvaturePlan, key: bytes, solved: np.ndarray, ms: float) -> bool:
        """`PendingSolve.land`: keep a background solve only while `plan` is
        still the one held (`holds`)."""
        if not self.holds(plan):
            return False
        self._keep_solved(key, solved)
        self._last_solve_ms = ms
        return True

    def _solved_slice(
        self, plan: CurvaturePlan, values: np.ndarray, key: bytes | None
    ) -> np.ndarray:
        """`values` solved on `plan`, unsmoothed: from the cache, or solved
        here and timed (plan calls 5 and 8)."""
        if key is None:
            key = solve_key(values)
        solved = self._solved.get(key)
        if solved is not None:
            self._solved.move_to_end(key)
            return solved
        started = time.perf_counter()
        solved, _ = plan.solve(values)
        self._last_solve_ms = (time.perf_counter() - started) * 1000.0
        self._keep_solved(key, solved)
        return solved

    def finish(
        self,
        values: np.ndarray,
        coverage: np.ndarray,
        finish: SliceFinish,
        *,
        key: bytes | None = None,
    ) -> np.ndarray:
        """`values` interpolated into blank cells and smoothed (interpolation
        spec §5-6), with the weights built on first use and reused after.
        Always the full result: minimum curvature is solved here if it is not
        cached, never previewed (`preview` is the dock's choice to make).

        `key` is `solve_key(values)` when the caller has it already. A draw
        hashes its slice once and passes the key on (`finish_is_slow`,
        `pending_solve`): a hash costs about 7 ms at a million cells. It is
        trusted, never checked: it must be `solve_key` of this very `values`
        array, or another slice's solve is served, or this one is cached under
        another slice's key. Every caller hashes the array it passes.

        The cell is the frame's, never a widget's: a refused resolution edit
        leaves the spin ahead of the frame, and the weights must describe the
        array they are applied to (#104).

        For minimum curvature this is `finish_slice` split in two, so the cache
        can hold the solve without the smoothing: a smoothing edit or a scrub
        back to a slice already seen never solves again (plan call 8).
        """
        frame, _ = self._require_geometry()
        settings = self.finish_settings(finish)
        fill, _ = self._fill_for(coverage, frame, settings)
        if isinstance(fill, CurvaturePlan):
            solved = self._solved_slice(fill, values, key)
            return smooth(solved, frame.cell, settings.smooth_x_m, settings.smooth_y_m)
        return finish_slice(values, fill, frame.cell, settings)

    def preview(self, values: np.ndarray, coverage: np.ndarray, finish: SliceFinish) -> np.ndarray:
        """What a slow slice is drawn as while the depth moves (plan call 5):
        for minimum curvature, kriging at the same max distance, search radius
        and smoothing, so its blanks are the full result's. Any other method
        is quick already, so its preview is `finish` itself."""
        if finish.method != "min_curvature":
            return self.finish(values, coverage, finish)
        frame, _ = self._require_geometry()
        settings = self.finish_settings(finish)
        _, preview = self._fill_for(coverage, frame, settings)
        assert preview is not None  # built with the plan
        return finish_slice(values, preview, frame.cell, settings)

    def solve_cost_ms(
        self,
        values: np.ndarray,
        coverage: np.ndarray,
        finish: SliceFinish,
        *,
        key: bytes | None = None,
    ) -> float | None:
        """What `finish` would spend solving `values`, as far as is known (plan
        call 5): 0.0 when nothing is to be solved (another method, or these
        values solved on the plan held), the last solve's time on the plan
        held otherwise, and None when none is timed on it yet. A plan not
        built yet has none. Builds nothing. `key` as for `finish`: `solve_key`
        of this very `values` array."""
        if finish.method != "min_curvature":
            return 0.0
        frame, _ = self._require_geometry()
        if self._held_fill(coverage > 0, frame, self.finish_settings(finish)) is None:
            return None
        if (solve_key(values) if key is None else key) in self._solved:
            return 0.0
        return self._last_solve_ms

    def finish_is_slow(
        self,
        values: np.ndarray,
        coverage: np.ndarray,
        finish: SliceFinish,
        *,
        key: bytes | None = None,
    ) -> bool:
        """Plan call 5's "slow": minimum curvature, these values not solved
        on the plan held, and the last solve on it over `LIVE_SOLVE_BUDGET_MS`
        or none timed on it yet (`solve_cost_ms`). A plan not built yet has
        none, so the first draw on a new plan is always a preview. False for
        any other method. Builds nothing. `key` as for `finish`: `solve_key`
        of this very `values` array."""
        cost = self.solve_cost_ms(values, coverage, finish, key=key)
        return cost is None or cost > LIVE_SOLVE_BUDGET_MS

    def is_solved(
        self,
        values: np.ndarray,
        coverage: np.ndarray,
        finish: SliceFinish,
        *,
        key: bytes | None = None,
    ) -> bool:
        """Whether `finish` would serve `values` from the solved-slice cache:
        minimum curvature, the plan for these settings and cells held, and
        these values solved on it (plan call 8). Builds and solves nothing.
        `key` as for `finish`: trusted, so it must be `solve_key` of this very
        `values` array; every caller hashes the array it passes."""
        if finish.method != "min_curvature":
            return False
        frame, _ = self._require_geometry()
        if self._held_fill(coverage > 0, frame, self.finish_settings(finish)) is None:
            return False
        return (solve_key(values) if key is None else key) in self._solved

    def pending_solve(
        self,
        values: np.ndarray,
        coverage: np.ndarray,
        finish: SliceFinish,
        *,
        key: bytes | None = None,
    ) -> PendingSolve | None:
        """A job that solves `values` in the background (plan call 6), or None
        when the method is not minimum curvature or they are solved already.
        Builds the plan if it is not held. `key` as for `finish`: trusted, so
        it must be `solve_key` of this very `values` array, or the job lands
        its solve under another slice's key; every caller hashes the array it
        passes."""
        if finish.method != "min_curvature":
            return None
        return self._job_for(values, coverage, finish, key=key, copy=True)

    def window_solve(self, window: SliceWindow, finish: SliceFinish) -> PendingSolve | None:
        """`pending_solve` for this engine's own `window`, sliced here for the
        job alone, so it is private without a copy. Untimed: handing out
        jobs is not a redraw."""
        if finish.method != "min_curvature":
            return None
        return self._job_for(*self._slice(window), finish, key=None, copy=False)

    def _job_for(
        self,
        values: np.ndarray,
        coverage: np.ndarray,
        finish: SliceFinish,
        *,
        key: bytes | None,
        copy: bool,
    ) -> PendingSolve | None:
        frame, _ = self._require_geometry()
        plan, _ = self._fill_for(coverage, frame, self.finish_settings(finish))
        assert isinstance(plan, CurvaturePlan)  # the method is minimum curvature
        if key is None:
            key = solve_key(values)
        if key in self._solved:
            # Recently used: what a list is about to land must evict other
            # slices, never the stretch windows it is completing.
            self._solved.move_to_end(key)
            return None
        return PendingSolve(self, plan, values, key, copy=copy)

    def stretch_solves(self, thickness_levels: int, finish: SliceFinish) -> list[PendingSolve]:
        """A job for each window the minimum-curvature stretch is measured
        over (`limit_windows`) that is not solved yet, in their order (plan
        call 7). [] when all are, and for any other method."""
        if finish.method != "min_curvature":
            return []
        _, z = self._require_geometry()
        jobs: list[PendingSolve] = []
        for window in limit_windows(z, thickness_levels):
            job = self.window_solve(window, finish)
            if job is not None:
                jobs.append(job)
        return jobs

    def stretch_limit(
        self, thickness_levels: int, clip: Any, finish: SliceFinish
    ) -> tuple[float, bool]:
        """The shared limit to show now, and whether it is final (plan call 7).

        For minimum curvature: `shared_limit` over the solved windows when
        every one is solved, else the provisional `shared_limit(...,
        preview=True)`. One pass decides and, when final, measures: each
        window is sliced and hashed once, and its cached solve smoothed, with
        no job built and nothing copied. Any other method is always final.
        """
        if finish.method != "min_curvature":
            return self.shared_limit(thickness_levels, clip, finish), True
        frame, z = self._require_geometry()
        settings = self.finish_settings(finish)
        solved: list[np.ndarray] = []
        for window in limit_windows(z, thickness_levels):
            values, coverage = self._slice(window)
            hit = None
            if self._held_fill(coverage > 0, frame, settings) is not None:
                key = solve_key(values)
                hit = self._solved.get(key)
                if hit is not None:
                    self._solved.move_to_end(key)
            if hit is None:
                return self.shared_limit(thickness_levels, clip, finish, preview=True), False
            solved.append(hit)
        sx, sy = settings.smooth_x_m, settings.smooth_y_m
        return limit_over_slices((smooth(s, frame.cell, sx, sy) for s in solved), clip), True

    def shared_limit(
        self, thickness_levels: int, clip: Any, finish: SliceFinish, *, preview: bool = False
    ) -> float:
        """One display limit for the whole source, at this thickness.

        Spec 8's shared stretch. Measured over slices at the thickness
        being displayed and never over the raw levels -- see
        `nsgeo.slices.display.shared_limit` for the measurement that makes
        the difference a bug rather than a nuance.

        Measured over the FINISHED slices (interpolated and smoothed), the
        arrays `refresh_slice()` displays, never the raw unfilled ones: with
        a raw measurement the default (shared) stretch measured something
        never drawn. On this repo's four real DZT files at the dock's then
        seeded defaults the unfilled measurement came out 1.10x too high with
        `amp_envelope` and 1.69x too high with no transform, so every slice
        rendered noticeably dimmer than intended (final review, Important 1;
        a property of that corpus, not a threshold).

        Builds its own window list and finishes each one directly, in BOTH
        modes, rather than delegating the resident branch to
        `nsgeo.slices.display.shared_limit`: that function reads
        `cube.slice_levels` straight, with no finishing step, so it would
        leave the resident branch with the bug the streaming one was fixed
        for. Windows abut (`step == thickness`) and a thinner FINAL window is
        appended whenever `thickness_levels` does not evenly divide `z.nz`,
        exactly as the core `shared_limit` does -- omitting it would measure
        the resident and streaming stretch over two different sets of levels,
        which a mode switch must never produce.

        Minimum curvature solves every window it measures, so it measures at
        most twelve (`limit_windows`, both ends kept: the site's rule, plan
        call 7). With `preview=True` it measures their kriging previews
        instead, the provisional stretch that stands in until those windows
        are solved; the final limit always comes from minimum-curvature
        slices (interpolation spec §7).
        """
        _, z = self._require_geometry()
        if finish.method == "min_curvature":
            windows = list(limit_windows(z, thickness_levels))
        else:
            windows = list(plan_windows(z, thickness_levels, thickness_levels))
            if windows[-1].k1 < z.nz:
                windows.append(SliceWindow(windows[-1].k1, z.nz))
        draw = self.preview if preview else self.finish
        if self._mode == "resident":
            cube = self.cube()
            coverage = cube.coverage()
            slices = (draw(cube.slice_levels(w.k0, w.k1), coverage, finish) for w in windows)
        else:
            slices = (draw(*self._slice(w), finish) for w in windows)
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

    def drop_cube(self) -> None:
        """Release a resident cube, if one is cached, without touching
        anything else.

        Final review, Important 4: `save_cube_npz` calls `cube()` to get
        the whole volume it wants to write, which -- in "streaming" mode --
        caches it into `self._cube` where nothing else ever reads it back
        (`_slice`'s streaming branch calls `stream_slice` directly) and
        nothing but `set_source`/`clear` ever resets it again. That
        silently and PERMANENTLY promoted a streaming engine's real memory
        footprint by the whole cube -- 111 MB held at spec 7.2's own
        24-line/native-dz row, 359 MB at cell 0.05 m -- while `_mode`
        stayed "streaming" and `format_status` (which branches on `_mode`,
        not on whether a cube happens to be cached) went on reporting only
        the prepared lines. `save_cube_npz` calls this afterwards, only
        when `mode == "streaming"`: a "resident" engine already wanted the
        cube for faster redraws, and dropping it there would only force an
        immediate, wasted rebuild on the very next slice.
        """
        self._cube = None

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

        A line can be removed from the survey while a source stays
        prepared, and `resolved_velocity` raises KeyError for a key that
        is gone. The cube's own arrays are still correct, so losing the
        depth LABEL is the only honest consequence -- blanking the map
        and breaking "Save cube..." and "Export GeoTIFF" is not. Falling
        through to the next prepared line is faithful rather than
        arbitrary: `resolve_velocity` goes line override -> grid velocity
        -> header dielectric, and a cube is built from one grid (spec 3),
        so another line of the same grid almost always carries the same
        model.
        """
        if self._choice is None:
            raise RuntimeError("no source is chosen")
        velocity = None
        for line in self._lines:
            try:
                velocity = self.session.resolved_velocity(line.key).to_dict()
                break
            except (KeyError, RuntimeError):
                continue
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
        self._covered = None
        self._frame = None
        self._z = None
        self._grid_fp = None
        self._placements = {}
        self._grid_seen = None
        self._cube = None
        self._drop_fill()
        self._redraw_ms = None
        self._running = False

    def dispose(self) -> None:
        # Cheap cluster (M11 final review): set, and never cleared. A
        # queued signal delivered from INSIDE `_cancel_in_flight()`'s own
        # nested event loop below (Ruling W's hazard -- see `set_source`'s
        # own docstring) could otherwise reach `set_source` while
        # `_dispatching` still reads `False` here, since this method never
        # sets it itself: that reentrant call would then dispatch a brand
        # new `QgsTask` rather than merely queue itself, and this teardown
        # has no `finally` (unlike `set_source`'s own) to apply a queued
        # choice or to wait for that new task afterwards -- a task
        # dispatched during teardown would simply outlive it, orphaned.
        # Setting this here instead makes any such reentrant call queue
        # into `_queued_choice` like any other nested `set_source` call,
        # and leaving it set afterwards means that queued choice is never
        # applied by anything -- exactly right for an engine that is being
        # torn down and must dispatch nothing further.
        self._dispatching = True
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
        with contextlib.suppress(TypeError, RuntimeError):
            self.session.lines_changed.disconnect(self._on_lines_changed)
        self.clear()
        self.on_prepared = None
        self.on_error = None
        self.on_progress = None
        self.on_grid_moved = None

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

        previous_wake = self._wake_waiter

        def wake() -> None:
            # Ruling T3-e: the same wake as `done`, minus `on_prepared` --
            # for a terminal edge that applies nothing (a closed site).
            nonlocal finished
            finished = True
            loop.quit()
            if previous_wake is not None:
                previous_wake()

        self.on_prepared = done
        self._wake_waiter = wake
        timer.start(timeout_ms)
        loop.exec(flags)
        self.on_prepared = previous
        self._wake_waiter = previous_wake
        return finished and not self._running
