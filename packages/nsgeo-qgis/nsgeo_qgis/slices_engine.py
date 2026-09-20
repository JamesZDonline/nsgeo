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
  slot hazard, which at least reaches stderr. `finished()` guards its own
  body with `except`, not merely `finally`. Independently of that: EVERY
  terminal path -- success, a whole-task exception, an exception raised
  while finishing -- must call `_finish_preparation()`, in a `finally`,
  because `wait_for_preparation` (and any future caller) waits on that
  callback and must see a request it is actually watching end, not hang
  for the whole timeout. `loader.py`'s own `addTask()`-failure branch
  draws the identical lesson by re-emitting `loading_changed`.
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
  fields change; a velocity-only edit is deliberately excluded (see
  `_grid_fingerprint`), since that relabels depths without rebinning.
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
    limit_over_slices,
    plan_line,
    plan_windows,
    stream_slice,
)
from nsgeo.slices import shared_limit as cube_shared_limit
from nsgeo.slices.fill import clear_kernel_cache
from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QEventLoop, QObject, QTimer

from nsgeo_qgis.slices_plan import (
    DEFAULT_BUDGET_BYTES,
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
        #: The chosen grid's binning fields as of the last successful
        #: `_rebuild_geometry`. Compared against on `grids_changed` (see
        #: `_on_grids_changed` and `_grid_fingerprint`, Ruling M).
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
    def set_source(self, choice: SourceChoice | None) -> None:
        """Choose what goes into the cube and start preparing it.

        Raises ValueError, synchronously and before any work starts, if
        the preset carries an amplitude transform (plan Ruling 2) -- the
        caller is a dialog, and a refusal it can show is worth more than
        an error that arrives a second later through a callback.
        """
        self._generation += 1
        self._lines = []
        self._steps = ()
        self._plans = None
        self._cube = None
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
        if self.on_prepared is None:
            return
        self.on_prepared()

    def _report(self, message: str) -> None:
        if self.on_error is not None:
            self.on_error(message)

    # ---- geometry ---------------------------------------------------------
    def set_resolution(self, resolution: Resolution | None) -> None:
        """Set the binning geometry. Drops every plan; see the module docstring."""
        self._resolution = resolution
        self._rebuild_geometry()

    def _rebuild_geometry(self) -> None:
        # Unconditional, and wholesale. There is no such thing as keeping
        # a plan across a geometry change.
        self._plans = None
        self._cube = None
        self._frame = None
        self._z = None
        self._grid_fp = None
        self._redraw_ms = None
        if self._choice is None or self._resolution is None or not self.session.is_open:
            self._choose_mode()
            return
        grid = self.session.grid(self._choice.grid_id)
        res = self._resolution
        self._frame = CubeFrame.for_grid(grid, res.cell)
        self._z = ZAxis.from_range(res.t0_ns, res.t1_ns, res.dz_ns)
        self._grid_fp = self._grid_fingerprint(grid)
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
        """React to `replace_grid`/`remove_grid` (Ruling M).

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
        if self._grid_fp is not None and self._grid_fingerprint(grid) != self._grid_fp:
            try:
                self.set_source(self._choice)
            except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
                self._report(f"could not re-prepare after the grid changed: {exc}")

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

    def shared_limit(self, thickness_levels: int, clip: Any) -> float:
        """One display limit for the whole source, at this thickness.

        Spec 8's shared stretch. Measured over slices at the thickness
        being displayed and never over the raw levels -- see
        `nsgeo.slices.display.shared_limit` for the measurement that makes
        the difference a bug rather than a nuance.

        The streaming branch mirrors that function's own tail-window
        handling by hand rather than calling it: `nsgeo.slices.display
        .shared_limit` takes a `SliceCube` and reads `cube.slice_levels`,
        which this mode deliberately holds none of. Windows abut
        (`step == thickness`) and a thinner FINAL window is appended
        whenever `thickness_levels` does not evenly divide `z.nz`, exactly
        as the cube version does -- omitting it would silently measure the
        resident and streaming stretch over two different sets of levels,
        which is the mismatch a mode switch must never produce.
        """
        _, z = self._require_geometry()
        if self._mode == "resident":
            return cube_shared_limit(self.cube(), thickness_levels, clip)
        windows = list(plan_windows(z, thickness_levels, thickness_levels))
        if windows[-1].k1 < z.nz:
            windows.append(SliceWindow(windows[-1].k1, z.nz))
        return limit_over_slices((self._slice(w)[0] for w in windows), clip)

    def cube(self) -> SliceCube:
        """The resident cube, built on first use and cached.

        A latency optimisation, never a capability (spec 7.4) -- every
        caller here works without one. The exporter and the `.npz` writer
        use it because they want the whole volume anyway.
        """
        if self._cube is None:
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
        """Drop the source and everything derived from it."""
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

    def wait_for_preparation(self, timeout_ms: int = 20_000) -> bool:
        """Spin the event loop until preparation finishes. For tests.

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
            if previous is not None:
                previous()
            loop.quit()

        self.on_prepared = done
        timer.start(timeout_ms)
        loop.exec()
        self.on_prepared = previous
        return finished and not self._running
