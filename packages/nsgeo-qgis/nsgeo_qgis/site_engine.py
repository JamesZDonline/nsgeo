"""The site view's engine: one `SliceEngine` per grid, composed per tick.

Spec 4.2-4.8 and plan Ruling 1. `SiteEngine` owns one M11 `SliceEngine`
per included grid -- separate from the Slices dock's own *This grid*
engine -- and turns them into one normalised slice on a common north-up
lattice (`SiteSlice`). Like `SliceEngine` it owns no widgets and declares
no `pyqtSignal`: its consumer is constructor callbacks, for the same
reason `slices_engine.py` gives.

**At most one line preparation runs at a time, across every engine (trap
1).** Two at once segfaulted M11. Each `SliceEngine` already stops its own
previous task before starting another; nothing in it stops two engines
overlapping. So no engine here prepares except through `_dispatch_next`,
which starts the head of a queue only when no task may still be
executing -- `SliceEngine.has_live_task` over its own engines, the
retiring ones, and the `exclusive_with` peers (the dock's engine) -- and
otherwise looks again in `_RETRY_MS`. It never blocks. `has_live_task`,
not `is_running` (ruling T3-b): M11's `clear()`, and so `dispose()`, set
`is_running` False when their bounded confirm wait gives up with the
task still reading a line; `has_live_task` stays True until the task's
`finished` has run. Every path that could start a preparation some other
way is closed:

* a grid that moves: `SliceEngine` would re-prepare itself from its
  `grids_changed` slot (M11, Ruling M). These engines are built with
  `on_grid_moved` (R-P2), so a move clears the engine and calls
  `_on_grid_moved`, which re-queues the grid. If that `clear()`'s wait
  gave up, the old task is still live and the gate holds the grid back;
* a grid whose source changes while it prepares, and `cancel()`: the
  engine is cancelled and confirmed (`cancel_preparation`, bounded by
  about one line's processing) and stays in `_engines`, so a task that
  outlives the wait is still seen by the gate;
* a grid dropped from the source (by `set_source`, by becoming "no
  lines", or by being deleted from the session) and `clear()`:
  `_drop_engine` cancels while the engine is still tracked, and an engine
  whose task outlived the wait is parked as retiring -- still in the
  gate -- and disposed by `_reap_retired` once the task has ended.

`_preparing` names the grid the dispatcher started. An engine's
`on_prepared` counts only for that grid; a callback from a preparation
this engine cancelled (they fire from inside the cancel's own wait) is
ignored, because whoever cancelled already set the state.

**Slot order.** `__init__` connects `session.grids_changed` before any
per-grid engine exists, so `_on_grids_changed` runs BEFORE each engine's
own handler. Inside that call the engines have not reacted yet: a moved
grid's engine still holds lines binned at the old registration. So it
reads no engine state. It drops the caches the edit made stale and
handles grids that no longer exist (those engines are disposed, not
consulted). A moved grid is driven by `_on_grid_moved`, which runs after
its engine has cleared, and the geometry is rebuilt there -- never in the
synchronous slot. A preparation whose grid moved under it is not marked
ready or failed: its callback arrives from inside the engine's `clear()`,
before `_on_grid_moved`, and `_on_engine_prepared` recognises it by the
grid's registration no longer matching the one it was dispatched against.

**Caches**: the gathers (each grid's `Footprint` on the lattice, once per
grid per lattice, spec 4.7) and the seams (once per geometry, from each
ready grid's coverage, which does not depend on the window). Both are
dropped whenever the geometry is rebuilt: a resolution change, or a grid
becoming ready, moving or leaving. A grid edit drops only what it changes
(final review I2): a gather when that grid's registration changed, the
seams when any registration or line spacing did. A velocity edit
relabels depths and drops neither; `grids_changed` does not say which
grid changed, so `_seen` records what the caches were derived from.

**Progress** (spec 4.2): each engine reports lines done through its own
`on_progress`, bound to its grid id; `grid_progress` and `on_changed`
carry it to the grid list.
"""

from __future__ import annotations

import contextlib
import functools
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from nsgeo.slices import (
    CubeFrame,
    Footprint,
    Seam,
    SiteLattice,
    SliceWindow,
    ZAxis,
    compose_footprints,
    fill,
    find_seams,
    footprint,
    grid_axis,
    lattice_pixel,
    limit_over_slices,
    normalise,
    site_axis,
    slice_extent,
    window_on,
)
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
)
from qgis.PyQt.QtCore import QEventLoop, QObject, QTimer

from nsgeo_qgis.slices_engine import _REDRAW_SMOOTHING, SliceEngine
from nsgeo_qgis.slices_plan import (
    MAX_FRAME_CELLS,
    Resolution,
    SiteSource,
    SourceChoice,
    format_bytes,
    limit_windows,
    radius_cells_for,
)

#: Ruling 1: how long the dispatcher waits before looking again while an
#: engine -- its own or a peer -- is still preparing.
_RETRY_MS = 50

#: Points per edge when a frame's outline is transformed into another CRS.
#: A transverse Mercator edge is not quite straight in a neighbouring zone.
_EDGE_POINTS = 8


def _ignore() -> None:
    """A retiring engine's `on_grid_moved`: its moves no longer matter."""


@dataclass(frozen=True, eq=False)
class SiteSlice:
    """One tick of the site view.

    `array` is `(height, width)` float32 on `lattice`, NaN for nodata.
    `windows` names every ready grid, None where the grid is absent at
    this time (spec 4.3: a blank grid that is named). `factors` is the
    `(a, b)` applied to each present grid, manual gain included.

    `eq=False`, as for `Seam` (Ruling T1-a): a generated `__eq__` over an
    ndarray field raises rather than comparing.
    """

    array: np.ndarray
    lattice: SiteLattice
    windows: dict[str, SliceWindow | None]
    factors: dict[str, tuple[float, float]]


class SiteEngine(QObject):
    """Every included grid, prepared one at a time, shown as one slice."""

    def __init__(
        self,
        session: Any,
        on_changed: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        exclusive_with: Sequence[SliceEngine] = (),
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.on_changed = on_changed
        self.on_error = on_error
        self._exclusive_with = tuple(exclusive_with)
        self._source: SiteSource | None = None
        self._engines: dict[str, SliceEngine] = {}
        #: "ready", "preparing", "queued", "no lines" or "failed: <message>".
        self._states: dict[str, str] = {}
        #: The first error reported during the current preparation, per grid.
        self._errors: dict[str, str] = {}
        #: (lines done, lines total) of the grid being prepared (spec 4.2).
        self._progress: dict[str, tuple[int, int]] = {}
        #: Engines dropped while their task outlived the cancel's bounded
        #: wait (ruling T3-b): out of the source, still in the dispatch
        #: gate, disposed by `_reap_retired` once the task has ended.
        self._retiring: list[SliceEngine] = []
        self._queue: list[str] = []
        self._preparing: str | None = None
        #: The preparing grid's registration when it was dispatched.
        self._preparing_fp: tuple[Any, ...] | None = None
        #: False after `cancel()`: passive until the next `set_source`.
        self._active = False
        self._disposed = False
        self._in_dispatch = False
        self._dispatch_again = False
        self._resolution: Resolution | None = None
        self._site_z: ZAxis | None = None
        self._lattice: SiteLattice | None = None
        self._gathers: dict[str, Footprint] = {}
        self._seams: tuple[Seam, ...] | None = None
        #: Each site grid's (registration, line spacing) as of the last
        #: `set_source` or `grids_changed`: what the caches derive from.
        self._seen: dict[str, tuple[tuple[Any, ...], float]] = {}
        self._redraw_ms: float | None = None
        # One timer, restarted, rather than a `QTimer.singleShot` per busy
        # check: every callback ends by asking for the next dispatch, and
        # separate single shots would pile up while a peer prepares.
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.setInterval(_RETRY_MS)
        self._retry.timeout.connect(self._dispatch_next)
        self._reaper = QTimer(self)
        self._reaper.setSingleShot(True)
        self._reaper.setInterval(_RETRY_MS)
        self._reaper.timeout.connect(self._reap_retired)
        session.site_closed.connect(self._on_site_closed)
        session.grids_changed.connect(self._on_grids_changed)

    # ---- state ------------------------------------------------------------
    @property
    def site_z(self) -> ZAxis | None:
        return self._site_z

    @property
    def lattice(self) -> SiteLattice | None:
        return self._lattice

    @property
    def ready_grids(self) -> tuple[str, ...]:
        """The grids with prepared lines, in source order."""
        if self._source is None:
            return ()
        return tuple(
            c.grid_id for c in self._source.grids if self._states.get(c.grid_id) == "ready"
        )

    @property
    def is_running(self) -> bool:
        """Whether a grid is preparing or waiting to, or a task is still live."""
        if self._preparing is not None or (self._active and bool(self._queue)):
            return True
        return self.has_live_task

    @property
    def has_live_task(self) -> bool:
        """Whether any preparation task of this site may still be executing.

        Over every engine it owns, retiring ones included, by
        `SliceEngine.has_live_task` (ruling T3-b). For whoever must hold
        another engine back -- the dock's, in Task 5 -- until the site's
        work has really stopped.
        """
        return any(e.has_live_task for e in (*self._engines.values(), *self._retiring))

    def grid_progress(self, grid_id: str) -> tuple[int, int] | None:
        """`(lines done, lines total)` while `grid_id` prepares, else None (spec 4.2)."""
        if self._states.get(grid_id) != "preparing":
            return None
        return self._progress.get(grid_id)

    def grid_state(self, grid_id: str) -> str:
        try:
            return self._states[grid_id]
        except KeyError:
            raise KeyError(f"grid {grid_id!r} is not in the site source") from None

    def engine_for(self, grid_id: str) -> SliceEngine | None:
        """A grid's engine, for reading (provenance, z, frame). Never dispatch on it."""
        return self._engines.get(grid_id)

    # ---- source -----------------------------------------------------------
    def set_source(self, source: SiteSource) -> None:
        """Point the site at `source`, keeping what has not changed.

        A grid whose choice is unchanged keeps its prepared lines (or its
        place in the queue, or its failure: a caller re-sending the same
        source must not re-run a failing preparation forever -- a changed
        choice retries it). A changed grid is queued, a removed grid's
        engine disposed, and a grid with no line keys is `"no lines"` and
        never dispatched. Resumes after `cancel()`.
        """
        if not self.session.is_open:
            raise RuntimeError("no site is open")
        old = {c.grid_id: c for c in self._source.grids} if self._source is not None else {}
        wanted = {c.grid_id for c in source.grids}
        ready_before = self.ready_grids
        states_before = dict(self._states)
        for grid_id in [g for g in self._states if g not in wanted]:
            self._drop_grid(grid_id)
        self._source = source
        self._seen = self._grid_snapshot()
        self._active = True
        for choice in source.grids:
            grid_id = choice.grid_id
            if not choice.line_keys:
                self._drop_engine(grid_id)
                self._states[grid_id] = "no lines"
                continue
            if old.get(grid_id) == choice and grid_id in self._engines:
                continue
            if grid_id == self._preparing:
                self._preparing = None  # its cancelled callback is not a result
                self._engines[grid_id].cancel_preparation()
            self._ensure_engine(grid_id)
            self._states[grid_id] = "queued"
        self._queue = [c.grid_id for c in source.grids if self._states.get(c.grid_id) == "queued"]
        if self.ready_grids != ready_before:
            self._rebuild_geometry_reporting()
        # Ruling T3-f: a drop, or a grid becoming "no lines", is news to the
        # grid list whether or not the grid was ready.
        if self.ready_grids != ready_before or self._states != states_before:
            self._notify_changed()
        self._dispatch_next()

    def _choice_for(self, grid_id: str) -> SourceChoice | None:
        if self._source is None:
            return None
        for choice in self._source.grids:
            if choice.grid_id == grid_id:
                return choice
        return None

    def _ensure_engine(self, grid_id: str) -> SliceEngine:
        engine = self._engines.get(grid_id)
        if engine is None:
            engine = SliceEngine(
                self.session,
                on_prepared=functools.partial(self._on_engine_prepared, grid_id),
                on_error=functools.partial(self._on_engine_error, grid_id),
                on_progress=functools.partial(self._on_engine_progress, grid_id),
                parent=self,
                on_grid_moved=functools.partial(self._on_grid_moved, grid_id),
            )
            self._engines[grid_id] = engine
        return engine

    def _drop_engine(self, grid_id: str) -> None:
        """Release a grid's engine without ever losing sight of a live task.

        Ruling T3-b. The engine is cancelled while it is still in
        `_engines`: the confirm wait spins the event loop, and a retry that
        fires inside it must still see the engine. If the bounded wait gave
        up, `dispose()` now would run M11's `clear()`, which reports the
        engine idle while its task still reads a line -- so it is parked
        as retiring instead, inside the dispatch gate, and disposed by
        `_reap_retired` once the task has ended.
        """
        if self._preparing == grid_id:
            self._preparing = None  # set first: the cancel waits, and the wait calls back
        self._progress.pop(grid_id, None)
        engine = self._engines.get(grid_id)
        if engine is None:
            return
        if engine.has_live_task:
            engine.cancel_preparation()
            if self._engines.get(grid_id) is not engine:
                return  # a call from inside that wait already released it
        del self._engines[grid_id]
        if engine.has_live_task:
            self._retire(engine)
        else:
            engine.dispose()

    def _retire(self, engine: SliceEngine) -> None:
        # Nothing it does now is a result. The move hook becomes a no-op,
        # not None: None would bring back M11's self-dispatch on a move.
        engine.on_prepared = None
        engine.on_progress = None
        engine.on_grid_moved = _ignore
        self._retiring.append(engine)
        self._reaper.start()

    def _reap_retired(self) -> None:
        """Dispose retiring engines whose task has ended (a timer slot)."""
        try:
            alive = []
            for engine in self._retiring:
                if engine.has_live_task:
                    alive.append(engine)
                else:
                    engine.dispose()
            self._retiring = alive
            if alive and not self._disposed:
                self._reaper.start()
        except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
            self._report(f"could not release a dropped grid's engine: {exc}")

    def _drop_grid(self, grid_id: str) -> None:
        self._drop_engine(grid_id)
        self._states.pop(grid_id, None)
        self._errors.pop(grid_id, None)
        if grid_id in self._queue:
            self._queue.remove(grid_id)

    @staticmethod
    def _fingerprint(grid: Any) -> tuple[Any, ...]:
        # The very fields `SliceEngine` decides a move by (Ruling M), so the
        # two can never disagree about whether a grid moved.
        return SliceEngine._grid_fingerprint(grid)

    def _registration(self, grid_id: str) -> tuple[Any, ...] | None:
        try:
            return self._fingerprint(self.session.grid(grid_id))
        except (KeyError, RuntimeError):
            return None

    # ---- preparation, one at a time ---------------------------------------
    def _anything_live(self) -> bool:
        """The dispatch gate (Ruling 1, ruling T3-b): may any task still execute?

        `has_live_task`, never `is_running`: M11's `clear()` sets
        `is_running` False when its wait gives up with the task still
        reading. Over this site's engines, the retiring ones, and the
        `exclusive_with` peers.
        """
        engines = (*self._engines.values(), *self._retiring, *self._exclusive_with)
        return any(engine.has_live_task for engine in engines)

    def _dispatch_next(self) -> None:
        """Start the queue's head if nothing else is preparing (Ruling 1).

        Also a slot (the retry timer), so it reports rather than raises.
        Reentrancy-safe: an engine can finish synchronously inside its own
        `set_source` (nothing to schedule, or `addTask` refused), and that
        callback asks for the next dispatch from inside this one. It is
        recorded in `_dispatch_again` and run by the loop below, not
        recursively.
        """
        try:
            if self._disposed or not self._active:
                return
            if self._in_dispatch:
                self._dispatch_again = True
                return
            self._in_dispatch = True
            try:
                self._dispatch_again = True
                while self._dispatch_again:
                    self._dispatch_again = False
                    self._start_next()
            finally:
                self._in_dispatch = False
        except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
            self._report(f"could not start preparing the next grid: {exc}")

    def _start_next(self) -> None:
        if not self._active or self._preparing is not None or not self._queue:
            return
        if self._anything_live():
            self._retry.start()
            return
        grid_id = self._queue.pop(0)
        choice = self._choice_for(grid_id)
        engine = self._engines.get(grid_id)
        if choice is None or engine is None:
            self._dispatch_again = True
            return
        self._preparing = grid_id
        self._preparing_fp = self._registration(grid_id)
        self._states[grid_id] = "preparing"
        self._errors.pop(grid_id, None)
        self._progress[grid_id] = (0, len(choice.line_keys))
        self._notify_changed()  # spec 4.2: "preparing 0 of n" in the list
        if self._preparing != grid_id or not self._active or self._disposed:
            self._dispatch_again = True  # the callback changed the plan
            return
        try:
            engine.set_source(choice)
        except Exception as exc:  # noqa: BLE001 -- a refused preset fails this grid only
            if self._preparing == grid_id:
                self._preparing = None
            self._states[grid_id] = f"failed: {exc}"
            self._report(f"{grid_id}: {exc}")
            self._notify_changed()
            self._dispatch_again = True

    def _on_engine_prepared(self, grid_id: str) -> None:
        """A grid's engine reached a terminal edge: mark it, redraw, go on."""
        try:
            if self._disposed or grid_id != self._preparing:
                return  # cancelled, superseded or dropped: that path set the state
            engine = self._engines.get(grid_id)
            if engine is None:
                self._preparing = None
                self._dispatch_next()
                return
            if self._registration(grid_id) != self._preparing_fp:
                return  # the grid moved under it; `_on_grid_moved` re-queues it
            self._preparing = None
            self._progress.pop(grid_id, None)
            if engine.is_prepared:
                self._states[grid_id] = "ready"
            else:
                reason = self._errors.get(grid_id, "no line could be prepared")
                self._states[grid_id] = f"failed: {reason}"
            self._rebuild_geometry_reporting()
            self._notify_changed()
            self._dispatch_next()
        except Exception as exc:  # noqa: BLE001 -- called from QgsTask's finished
            self._report(f"could not finish preparing grid {grid_id!r}: {exc}")

    def _on_engine_progress(self, grid_id: str, done: int, total: int) -> None:
        """A line finished (spec 4.2's "preparing n of m"); announced through `on_changed`."""
        try:
            if self._disposed or grid_id != self._preparing:
                return
            self._progress[grid_id] = (int(done), int(total))
            self._notify_changed()
        except Exception as exc:  # noqa: BLE001 -- reached from a task's signal
            self._report(f"could not report grid {grid_id!r}'s progress: {exc}")

    def _on_engine_error(self, grid_id: str, message: str) -> None:
        with contextlib.suppress(Exception):
            if grid_id == self._preparing:
                self._errors.setdefault(grid_id, message)
            self._report(f"{grid_id}: {message}")

    def _on_grid_moved(self, grid_id: str) -> None:
        """R-P2: `grid_id`'s engine dropped lines binned at its old place.

        Called by the engine after its `clear()`, so the engine state read
        here is current. Re-queued, and dispatched only while active:
        after `cancel()` the grid waits for the next `set_source`.
        """
        try:
            if self._disposed:
                return
            if self._preparing == grid_id:
                self._preparing = None
            if grid_id not in self._engines:
                return
            self._states[grid_id] = "queued"
            if self._active and grid_id not in self._queue and self._source is not None:
                self._queue.append(grid_id)
                order = {c.grid_id: i for i, c in enumerate(self._source.grids)}
                self._queue.sort(key=lambda g: order.get(g, len(order)))
            self._rebuild_geometry_reporting()
            self._notify_changed()
            self._dispatch_next()
        except Exception as exc:  # noqa: BLE001 -- runs inside a grids_changed slot
            self._report(f"could not re-queue grid {grid_id!r} after it moved: {exc}")

    def _on_grids_changed(self) -> None:
        """`grids_changed`, delivered before the engines' own (see the module docstring)."""
        try:
            if self._disposed or self._source is None or not self.session.is_open:
                return
            self._drop_stale_caches()
            existing = {grid.id for grid in self.session.site.grids}
            gone = [c.grid_id for c in self._source.grids if c.grid_id not in existing]
            if not gone:
                return
            for grid_id in gone:
                self._drop_grid(grid_id)
            self._source = SiteSource(
                transform=self._source.transform,
                grids=tuple(c for c in self._source.grids if c.grid_id not in gone),
            )
            self._rebuild_geometry_reporting()
            self._notify_changed()
            self._dispatch_next()
        except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
            self._report(f"could not follow the grid change: {exc}")

    def _on_site_closed(self) -> None:
        try:
            self.clear()
        except Exception as exc:  # noqa: BLE001 -- a slot must report, never raise
            self._report(f"could not release the site view: {exc}")

    # ---- geometry ---------------------------------------------------------
    def set_resolution(self, resolution: Resolution | None) -> None:
        """Store the site resolution and re-derive the geometry.

        Raises ValueError naming the pixel count when the lattice over the
        ready grids exceeds `MAX_FRAME_CELLS` (spec 4.7); the geometry is
        then empty until a coarser cell or fewer grids fit.
        """
        self._resolution = resolution
        try:
            self._rebuild_geometry()
        finally:
            self._notify_changed()

    def _rebuild_geometry_reporting(self) -> None:
        try:
            self._rebuild_geometry()
        except Exception as exc:  # noqa: BLE001 -- reached from callbacks
            self._report(str(exc))

    def _rebuild_geometry(self) -> None:
        """The site axis, each ready grid's resolution on it, and the lattice."""
        self._drop_caches()
        self._site_z = None
        self._lattice = None
        res = self._resolution
        ready = self.ready_grids
        if res is None or not ready or not self.session.is_open:
            return
        lattice = self._covering_lattice(ready, res.cell)
        if lattice.n_pixels > MAX_FRAME_CELLS:
            raise ValueError(
                f"the site lattice would be {lattice.width} x {lattice.height} = "
                f"{lattice.n_pixels:,} pixels at {lattice.pixel:g} m, more than the "
                f"{MAX_FRAME_CELLS:,} a slice can be drawn at: the included grids are too "
                "far apart for this cell size. Choose a coarser cell or include fewer grids"
            )
        bounds = {g: self._engines[g].prepared_z_bounds() for g in ready}
        site_z = site_axis(
            [b for b in bounds.values() if b is not None], res.t0_ns, res.t1_ns, res.dz_ns
        )
        for grid_id in ready:
            b = bounds[grid_id]
            gz = grid_axis(site_z, b) if site_z is not None and b is not None else None
            if gz is None or gz.nz < 2:
                # R-P3: `Resolution` needs t1 > t0, so a one-level axis is
                # no resolution -- the grid is absent at every window.
                self._apply_resolution(grid_id, None)
            else:
                self._apply_resolution(
                    grid_id, Resolution(res.cell, res.dz_ns, gz.t0_ns, gz.t_end_ns)
                )
        self._site_z = site_z
        self._lattice = lattice

    def _apply_resolution(self, grid_id: str, want: Resolution | None) -> None:
        """Give an engine its resolution, unless it is already binned at exactly it.

        Every grid becoming ready re-derives the geometry for all of them;
        re-setting an unchanged resolution would drop every plan and any
        resident cube for nothing. A changed frame or axis always goes
        through, and `set_resolution` drops the plans (trap 3).
        """
        engine = self._engines[grid_id]
        if want is None:
            if engine.frame is not None or engine.z is not None:
                engine.set_resolution(None)
            return
        frame = CubeFrame.for_grid(self.session.grid(grid_id), want.cell)
        z = ZAxis.from_range(want.t0_ns, want.t1_ns, want.dz_ns)
        if engine.frame == frame and engine.z == z:
            return
        engine.set_resolution(want)

    def _site_crs(self) -> str:
        """Spec 4.7: the site's CRS is the one its GeoPackage uses, `grids[0].crs`."""
        return str(self.session.site.grids[0].crs)

    def _covering_lattice(self, ready: Sequence[str], cell: float) -> SiteLattice:
        site_crs = self._site_crs()
        extents = []
        azimuths = []
        for grid_id in ready:
            frame = CubeFrame.for_grid(self.session.grid(grid_id), cell)
            extents.append(self._extent_in(frame, site_crs))
            azimuths.append(self._azimuth_in(frame, site_crs))
        return SiteLattice.covering(extents, lattice_pixel(cell, azimuths), site_crs)

    @staticmethod
    def _transform(points: np.ndarray, source: str, target: str) -> np.ndarray:
        """(n, 2) points from `source` to `target`; a missing transform raises.

        An invalid `QgsCoordinateTransform` returns its input unchanged
        while reporting success (`layers._require_transform`), which would
        draw a grid in the wrong place without a word.
        """
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem(source),
            QgsCoordinateReferenceSystem(target),
            QgsProject.instance(),
        )
        if not transform.isValid():
            raise RuntimeError(f"no coordinate transform from {source} to {target}")
        out = np.empty((len(points), 2), dtype=float)
        for i, (x, y) in enumerate(np.asarray(points, dtype=float)):
            moved = transform.transform(QgsPointXY(float(x), float(y)))
            out[i] = (moved.x(), moved.y())
        return out

    @classmethod
    def _extent_in(cls, frame: CubeFrame, crs: str) -> tuple[float, float, float, float]:
        if frame.crs == crs:
            return slice_extent(frame)
        x_hat, y_hat = frame.axes()
        w, h = frame.nx * frame.cell, frame.ny * frame.cell
        t = np.linspace(0.0, 1.0, _EDGE_POINTS + 1)
        local = np.concatenate(
            [
                np.column_stack([t * w, np.zeros_like(t)]),
                np.column_stack([np.full_like(t, w), t * h]),
                np.column_stack([t * w, np.full_like(t, h)]),
                np.column_stack([np.zeros_like(t), t * h]),
            ]
        )
        outline = np.asarray(frame.origin) + local[:, :1] * x_hat + local[:, 1:] * y_hat
        moved = cls._transform(outline, frame.crs, crs)
        return (
            float(moved[:, 0].min()),
            float(moved[:, 1].min()),
            float(moved[:, 0].max()),
            float(moved[:, 1].max()),
        )

    @classmethod
    def _azimuth_in(cls, frame: CubeFrame, crs: str) -> float:
        """The frame's bearing in the site CRS, for `lattice_pixel` (Ruling 2).

        A grid laid north-up in another zone is turned by the difference in
        meridian convergence, so it counts as rotated on the site lattice.
        """
        if frame.crs == crs:
            return frame.azimuth
        _, y_hat = frame.axes()
        origin = np.asarray(frame.origin, dtype=float)
        ends = cls._transform(
            np.array([origin, origin + y_hat * frame.ny * frame.cell]), frame.crs, crs
        )
        dx, dy = ends[1] - ends[0]
        return math.degrees(math.atan2(dx, dy))

    def _drop_caches(self) -> None:
        self._gathers = {}
        self._seams = None

    def _grid_snapshot(self) -> dict[str, tuple[tuple[Any, ...], float]]:
        """Each site grid's registration and line spacing: what the caches derive from."""
        if not self.session.is_open:
            return {}
        return {
            grid.id: (self._fingerprint(grid), float(grid.default_spacing))
            for grid in self.session.site.grids
        }

    def _drop_stale_caches(self) -> None:
        """After a grid edit, drop only the caches it changed (final review I2).

        A gather depends on its grid's registration, so it goes when that
        grid's fingerprint changed (or the grid came or went). The seams
        depend on every registration and line spacing (Ruling 3's width),
        so they go when any of those changed. A velocity-only edit changes
        neither: it relabels depths, and the next tick reuses everything.
        """
        before, now = self._seen, self._grid_snapshot()
        self._seen = now
        for grid_id in set(before) | set(now):
            old, new = before.get(grid_id), now.get(grid_id)
            if old == new:
                continue
            self._seams = None
            if old is None or new is None or old[0] != new[0]:
                self._gathers.pop(grid_id, None)

    def values_key(self) -> tuple[Any, ...]:
        """What a grid edit can change in the values drawn (final review I2).

        Each ready grid's registration and line spacing -- the spacing sets
        the fill radius in cells and the seam width. Never its velocity,
        which only relabels depths. For a cache of something measured over
        the drawn values, such as the dock's shared stretch.
        """
        snapshot = self._grid_snapshot()
        return tuple((grid_id, snapshot.get(grid_id)) for grid_id in self.ready_grids)

    def _gather(self, grid_id: str, lattice: SiteLattice) -> Footprint:
        """`grid_id`'s frame cell under each lattice pixel, kept to its own window.

        Once per grid per lattice (spec 4.7). Only the pixels inside the
        frame's extent (plus one) are looked up, and, for a frame in
        another CRS, transformed into it first. The result is a
        `Footprint`, the tight window around the placed pixels (final
        review I1): every pixel outside it is outside the frame, so the
        tick composes over the window alone. A whole-lattice array per
        grid made a rotated site, at half the pitch (Ruling 2), cost a
        full-lattice pass per grid per tick.
        """
        cached = self._gathers.get(grid_id)
        if cached is not None:
            return cached
        frame = self._engines[grid_id].frame
        if frame is None:
            raise RuntimeError(f"grid {grid_id!r} has no frame")
        xmin, ymin, xmax, ymax = self._extent_in(frame, lattice.crs)
        p = lattice.pixel
        col0 = max(0, math.floor((xmin - lattice.x0) / p) - 1)
        col1 = min(lattice.width, math.ceil((xmax - lattice.x0) / p) + 1)
        row0 = max(0, math.floor((lattice.y1 - ymax) / p) - 1)
        row1 = min(lattice.height, math.ceil((lattice.y1 - ymin) / p) + 1)
        if col1 > col0 and row1 > row0:
            cols = np.arange(col0, col1)
            rows = np.arange(row0, row1)
            # The same centres as `SiteLattice.pixel_centres`, restricted.
            xs = lattice.x0 + (cols.astype(float) + 0.5) * p
            ys = lattice.y1 - (rows.astype(float) + 0.5) * p
            grid_x, grid_y = np.meshgrid(xs, ys)
            centres = np.column_stack([grid_x.ravel(), grid_y.ravel()])
            if frame.crs != lattice.crs:
                centres = self._transform(centres, lattice.crs, frame.crs)
            ids = frame.cell_index(centres).reshape(row1 - row0, col1 - col0)
            gathered = footprint(ids, row0, col0)
        else:
            gathered = footprint(np.empty((0, 0), dtype=np.intp))
        self._gathers[grid_id] = gathered
        return gathered

    def _site_seams(self) -> tuple[Seam, ...]:
        """Seams between the ready grids, once per geometry (spec 4.6.1).

        Coverage does not depend on the window, so one level's slice gives
        it -- for every ready grid, including those absent at this tick.
        """
        if self._seams is None:
            frames: dict[str, CubeFrame] = {}
            coverages: dict[str, np.ndarray] = {}
            spacings: dict[str, float] = {}
            for grid_id in self.ready_grids:
                engine = self._engines[grid_id]
                if engine.frame is None or engine.z is None:
                    continue
                frames[grid_id] = engine.frame
                coverages[grid_id] = engine.slice_at(SliceWindow(0, 1))[1]
                spacings[grid_id] = self.session.grid(grid_id).default_spacing
            self._seams = find_seams(frames, coverages, spacings)
        return self._seams

    def _require_lattice(self) -> tuple[SiteLattice, Resolution]:
        if self._lattice is None or self._resolution is None:
            raise RuntimeError(
                "no site geometry: prepare a grid and choose a resolution that fits first"
            )
        return self._lattice, self._resolution

    # ---- slices -----------------------------------------------------------
    def _shown(
        self,
        top_ns: float,
        thickness_ns: float,
        radius_spacings: float,
        method: str,
        manual: Mapping[str, float],
        coverage: bool,
    ) -> tuple[
        dict[str, SliceWindow | None], dict[str, np.ndarray], dict[str, tuple[float, float]]
    ]:
        """Each present grid's displayed slice, grid-local, and what was applied.

        Spec 4.6: factors are measured on binned cells (`normalise` takes
        the unfilled values) and applied to the filled slice,
        `a * fill(values) + b`. Coverage mode shows the counts, 0 as NaN,
        and normalises nothing (Ruling 7).
        """
        _, res = self._require_lattice()
        windows: dict[str, SliceWindow | None] = {}
        binned: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for grid_id in self.ready_grids:
            engine = self._engines[grid_id]
            z = engine.z
            window = window_on(z, top_ns, thickness_ns) if z is not None else None
            windows[grid_id] = window
            if window is not None:
                binned[grid_id] = engine.slice_at(window)
        if coverage:
            counts = {
                g: np.where(cov > 0, cov, np.nan).astype(np.float32)
                for g, (_, cov) in binned.items()
            }
            return windows, counts, dict.fromkeys(binned, (1.0, 0.0))
        seams = self._site_seams() if method == "edge" else ()
        factors = normalise(method, binned, seams, manual)
        shown: dict[str, np.ndarray] = {}
        for grid_id, (values, cov) in binned.items():
            a, b = factors[grid_id]
            spacing = self.session.grid(grid_id).default_spacing
            shown[grid_id] = (
                a * fill(values, cov, radius_cells_for(spacing, radius_spacings, res.cell)) + b
            )
        return windows, shown, factors

    def slice_at(
        self,
        top_ns: float,
        thickness_ns: float,
        *,
        radius_spacings: float,
        method: str,
        manual: Mapping[str, float],
        coverage: bool = False,
    ) -> SiteSlice:
        """One tick: every ready grid's window, normalised, filled and composed.

        Spec 4.3: the same time window in every grid (`window_on`); a grid
        whose range misses it is absent (`windows[g] is None`) and nodata.
        """
        lattice, _ = self._require_lattice()
        # Per-geometry caches are built outside the timer: they are not a redraw.
        for grid_id in self.ready_grids:
            if self._engines[grid_id].frame is not None:
                self._gather(grid_id, lattice)
        if method == "edge" and not coverage:
            self._site_seams()
        started = time.perf_counter()
        windows, shown, factors = self._shown(
            top_ns, thickness_ns, radius_spacings, method, manual, coverage
        )
        array = compose_footprints(lattice, [(self._gather(g, lattice), shown[g]) for g in shown])
        self._record_redraw((time.perf_counter() - started) * 1000.0)
        return SiteSlice(array=array, lattice=lattice, windows=windows, factors=factors)

    def _record_redraw(self, ms: float) -> None:
        if self._redraw_ms is None:
            self._redraw_ms = ms
        else:
            self._redraw_ms = _REDRAW_SMOOTHING * self._redraw_ms + (1.0 - _REDRAW_SMOOTHING) * ms

    def shared_limit(
        self,
        thickness_ns: float,
        clip: Any,
        *,
        radius_spacings: float,
        method: str,
        manual: Mapping[str, float],
    ) -> float:
        """One display limit for the site at this thickness (spec 4.5, Ruling 4).

        Measured over every present grid's filled slice AFTER
        normalisation and manual adjustment -- the values drawn -- at
        `limit_windows` of the site axis (at most twelve, both ends kept),
        never over raw levels (trap 4).
        """
        self._require_lattice()
        z = self._site_z
        if z is None:
            raise RuntimeError("no site time axis: no ready grid covers the z range")
        thickness_levels = max(1, int(round(thickness_ns / z.dz_ns)))
        slices: list[np.ndarray] = []
        for window in limit_windows(z, thickness_levels):
            _, shown, _ = self._shown(
                z.t0_ns + window.k0 * z.dz_ns,
                window.n_levels * z.dz_ns,
                radius_spacings,
                method,
                manual,
                coverage=False,
            )
            slices.extend(shown.values())
        if not slices:
            return float(clip.limit(np.array([], dtype=float)))
        return limit_over_slices(slices, clip)

    @property
    def held_bytes(self) -> int:
        """What the site holds in memory, as M11's `format_status` counts it.

        The prepared lines, plus a cube only where an engine keeps one
        resident. Still held after leaving site scope (Ruling 1), so This
        grid's status line names it too (final review M2).
        """
        held = 0
        for engine in self._engines.values():
            if not engine.is_prepared:
                continue
            estimate = engine.estimate
            held += estimate.lines_bytes
            if engine.mode == "resident":
                held += estimate.cube_bytes
        return held

    def status_text(self) -> str:
        """`3 grids · 62 lines held in memory, 74 MB · slices redraw in 11 ms`.

        What is HELD: `held_bytes`.
        """
        held_by = [e for e in self._engines.values() if e.is_prepared]
        n_lines = sum(e.line_count for e in held_by)
        held = self.held_bytes
        grids = "grid" if len(held_by) == 1 else "grids"
        lines = "line" if n_lines == 1 else "lines"
        speed = "—" if self._redraw_ms is None else f"{max(1, round(self._redraw_ms))} ms"
        return (
            f"{len(held_by)} {grids} · {n_lines} {lines} held in memory, "
            f"{format_bytes(held)} · slices redraw in {speed}"
        )

    # ---- lifecycle --------------------------------------------------------
    def cancel(self) -> None:
        """Stop preparing (Ruling 1: leaving site scope). Prepared grids stay.

        The grid being prepared is cancelled, and confirmed stopped, with
        `cancel_preparation`; it and the rest of the queue wait, `"queued"`,
        for the next `set_source`. Nothing is dispatched until then -- not
        even a grid that moves meanwhile.
        """
        self._stop_dispatching()
        for engine in list(self._engines.values()):
            if engine.has_live_task:
                engine.cancel_preparation()

    def _stop_dispatching(self) -> None:
        """Passive, with nothing queued; the grid being prepared goes back to waiting.

        `_preparing` is cleared BEFORE anything is cancelled: a cancel
        waits, and the cancelled task's callback arrives inside that wait.
        """
        self._active = False
        self._retry.stop()
        self._queue.clear()
        preparing, self._preparing = self._preparing, None
        if preparing is not None and preparing in self._states:
            self._states[preparing] = "queued"

    def clear(self) -> None:
        """Drop the source, every engine and the geometry (`site_closed`).

        Each engine goes the way `_drop_engine` sends it: cancelled while
        still tracked, then disposed -- or, if its task outlived the
        cancel's bounded wait, kept as retiring until the task ends, so the
        next site's first grid cannot start beside it (trap 1).
        """
        had_anything = self._source is not None or bool(self._engines)
        self._stop_dispatching()
        for grid_id in list(self._engines):
            self._drop_engine(grid_id)
        self._states.clear()
        self._errors.clear()
        self._progress.clear()
        self._source = None
        self._resolution = None
        self._site_z = None
        self._lattice = None
        self._drop_caches()
        self._seen = {}
        self._redraw_ms = None
        if had_anything:
            self._notify_changed()

    def dispose(self) -> None:
        """Tear down. A retiring engine is disposed now too: its own
        `dispose()` cancels and waits, bounded, as M11's teardown does."""
        self._disposed = True
        self._retry.stop()
        self._reaper.stop()
        with contextlib.suppress(TypeError, RuntimeError):
            self.session.site_closed.disconnect(self._on_site_closed)
        with contextlib.suppress(TypeError, RuntimeError):
            self.session.grids_changed.disconnect(self._on_grids_changed)
        self.on_changed = None
        self.clear()
        retiring, self._retiring = self._retiring, []
        for engine in retiring:
            engine.dispose()
        self.on_error = None

    def wait_until_idle(self, timeout_ms: int = 60_000) -> bool:
        """Spin the event loop until nothing is preparing or queued. For tests."""
        if not self.is_running:
            return True
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(10)
        deadline = QTimer()
        deadline.setSingleShot(True)

        def check() -> None:
            try:
                if not self.is_running:
                    loop.quit()
            except Exception:  # noqa: BLE001 -- a slot; stop waiting rather than raise
                loop.quit()

        poll.timeout.connect(check)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(timeout_ms)
        loop.exec()
        poll.stop()
        deadline.stop()
        return not self.is_running

    # ---- reporting --------------------------------------------------------
    def _notify_changed(self) -> None:
        callback = self.on_changed
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:  # noqa: BLE001 -- reached from slots and task callbacks
            self._report(f"could not update after the site changed: {exc}")

    def _report(self, message: str) -> None:
        """Through `on_error`; a raising `on_error` has nowhere further to go."""
        callback = self.on_error
        if callback is None:
            return
        with contextlib.suppress(Exception):
            callback(message)
