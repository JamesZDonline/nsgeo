"""One scope's minimum-curvature refine: the preview, the rest and the list.

Interpolation spec §7, plan calls 5 and 7. This grid and Whole site share
the dock's one `Refiner`, so two solves never run at once, and each scope
keeps one `RefineFlow`: its own rest timer, whether what it draws is a
kriging preview and which solves that preview waits for, the running
list's progress, and the scope's shared stretch, provisional until the
windows it is measured over are solved. What a rest queues, how a scope
redraws and where its status goes stay the scope's own. The rules both
scopes follow are kept here, once, so the two cannot drift apart:

* **A draw that builds new weights or a new plan cancels the running list
  first** (`before_draw`): every solve in it was made on a plan about to
  be dropped, so none could land, and each would hold its dropped plan
  alive through the build.
* **A preview cancels the running list and restarts the rest**, unless it
  waits for exactly the solves at the head of that list, each still on
  the plan its engine holds. That is a redraw of the window being solved,
  not a new slow window: a site grid whose solve landed is drawn while the
  others still solve, and a cancel there would lose the solve in progress
  and start the rest over at every landing. A list for a window left
  behind, for a plan since dropped, or for a grid that has left the site
  is always cancelled, so it never draws over the newer one.
* **A full minimum-curvature draw** (a cache hit, or a solve inside the
  budget) leaves a running list alone, so stretch windows queued behind a
  landed slice still land. Another method's draw stops it.
* **A landed solve redraws** only when the preview on screen waits for it.
  When the list ends, a provisional stretch is dropped, so the redraw
  measures the final one; the redraw is then a cache hit.
* **Nothing left to solve is a state to leave, never one to keep.** A rest
  with no job redraws a preview whose slices were solved meanwhile (an
  export solves every band), and a provisional stretch found with nothing
  on its way to finish it arms the rest again.

Solves are told apart by `(engine, key)`, never the key alone: two of a
site's grids can hold equal values. Owns no widgets and declares no
signals. The rest timer's slot is the scope's, and guards its own body.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from qgis.PyQt.QtCore import QObject, QTimer

from nsgeo_qgis.refine import Refiner
from nsgeo_qgis.slices_plan import (
    MEASURING_STRETCH_INDICATOR,
    PREVIEW_INDICATOR,
    REFINE_REST_MS,
    REFINING_GRIDS_INDICATOR,
    REFINING_SLICE_INDICATOR,
)

#: A solve as a flow tells it apart: the engine it lands in, and its key.
SolveId = tuple[Any, bytes]


def solve_id(job: Any) -> SolveId:
    """`job`'s `SolveId`: a `PendingSolve`, or any job with `engine` and `key`.
    The plan is checked apart (`RefineFlow.previewed`), never held in an id:
    an id held past a rebuild would keep the dropped plan alive."""
    return (job.engine, job.key)


class RefineFlow:
    """One scope's side of the shared refiner (see the module docstring)."""

    def __init__(self, parent: QObject, refiner: Refiner, on_rest: Callable[[], None]) -> None:
        #: The dock's one worker, shared by both scopes.
        self.refiner = refiner
        #: Minimum curvature's rest (plan call 5): every preview that cancels
        #: restarts it, so the refine starts only once the depth has rested,
        #: however it was moved.
        self.rest = QTimer(parent)
        self.rest.setSingleShot(True)
        self.rest.setInterval(REFINE_REST_MS)
        self.rest.timeout.connect(on_rest)
        #: Whether what the scope draws is a kriging preview, refined once the
        #: depth rests.
        self.provisional = False
        #: How many of the running list have landed, of how many, and how many
        #: of the list are the slice on screen's (they run first): the indicator.
        self.done = 0
        self.total = 0
        self.slice_jobs = 0
        #: `(key, limit, final)`: the scope's shared stretch and the scope's
        #: own key for what it was measured over. `final` is False for minimum
        #: curvature's provisional stretch, measured over kriging previews
        #: until its windows are solved (plan call 7).
        self.stretch: tuple[Any, float, bool] | None = None
        #: The solves the preview on screen waits for.
        self._awaited: frozenset[SolveId] = frozenset()
        #: The running list's head: the slice on screen's solves not landed
        #: yet, by `SolveId`. Kept as jobs, so their plans can be checked.
        self._head: dict[SolveId, Any] = {}

    def indicator(self, *, grids: bool = False) -> str:
        """The scope's one-line refine indicator (walkthrough round 1, W1-W3):
        what the worker is solving while it runs, the preview's note while one
        is drawn, and empty otherwise. `grids` in Whole site, where several
        grids are solved for one slice. The slice's solves run first, so the
        count tells which phase the list is in; stretch counts cover stretch
        windows only. Never the status line's: that one's height moves the
        panel under the user's wheel."""
        if self.refiner.busy:
            # A list still solving a slice the panel has left (the user moved
            # back to a solved one) says nothing of that slice: the draw on
            # screen is final, so only the stretch windows can be named.
            if self.provisional and self.done < self.slice_jobs:
                if grids and self.slice_jobs > 1:
                    return REFINING_GRIDS_INDICATOR.format(done=self.done, total=self.slice_jobs)
                return REFINING_SLICE_INDICATOR
            stretch_total = self.total - self.slice_jobs
            if stretch_total > 0:
                return MEASURING_STRETCH_INDICATOR.format(
                    done=max(0, self.done - self.slice_jobs), total=stretch_total
                )
        if self.provisional:
            return PREVIEW_INDICATOR
        return ""

    # ---- draws ------------------------------------------------------------
    def before_draw(self, *, rebuilds: bool) -> None:
        """A draw is about to start. When it `rebuilds` the weights or the
        plan (a finish edit, a new cell or source, another method), the
        running list is cancelled now: it was made on a plan about to be
        dropped, so it neither competes with the build nor keeps that plan
        alive through it. The rest is the draw's to decide."""
        if rebuilds:
            self.cancel()

    def cancel(self) -> None:
        """Cancel the running list, whatever it holds: it was queued for what
        is no longer drawn (a plan about to be dropped, or a set of grids that
        has changed). The rest and the preview are the next draw's to decide,
        and a full draw leaves a list alone, so a list it should not keep is
        cancelled here, before it."""
        self.refiner.cancel()
        self._head = {}

    def previewed(self, awaited: Iterable[SolveId]) -> None:
        """The scope drew a preview waiting for the solves `awaited`. A list
        whose head is exactly those solves, each still on its engine's held
        plan, is this window's own, and runs on. Any other is cancelled and
        the rest restarted: a list for a window left behind, for a plan
        since dropped (its solves could never land), or with a grid that has
        left the site."""
        waits = frozenset(awaited)
        self.provisional = True
        keep = (
            bool(waits)
            and self.refiner.busy
            and waits == set(self._head)
            and all(job.engine.holds(job.plan) for job in self._head.values())
        )
        if not keep:
            self.refiner.cancel()
            self._head = {}
            self.rest.start()
        self._awaited = waits

    def finished(self, *, stop: bool) -> None:
        """The scope drew in full, so nothing on screen waits. `stop` when the
        method is not minimum curvature: a running list is then for a method
        no longer shown."""
        self.provisional = False
        self._awaited = frozenset()
        if stop:
            self.stop()

    def stop(self) -> bool:
        """No refine is owed: nothing is drawn, the draw failed, another
        method shows, or the scope was left. Cancels the list and the rest.
        Whether a preview or a refine stood, so the scope's status line, which
        said so, needs resetting."""
        stood = self.provisional or self.refiner.busy
        self.refiner.cancel()
        self.rest.stop()
        self.provisional = False
        self._awaited = frozenset()
        self._head = {}
        return stood

    # ---- the list ---------------------------------------------------------
    def rested(
        self,
        current: Sequence[Any],
        stretch: Sequence[Any],
        on_landed: Callable[[Any], None],
        on_error: Callable[[str], None],
    ) -> bool:
        """The depth rested: queue `current`, the slice on screen's solves,
        then `stretch`, the stretch windows not solved yet, each once (plan
        calls 5 and 7). Whether the scope must redraw now, since nothing would
        arm the rest for it again: a preview with nothing left to solve, or a
        provisional stretch whose windows all are."""
        queued: dict[SolveId, Any] = {}
        for job in (*current, *stretch):
            queued.setdefault(solve_id(job), job)
        redraw = self.provisional and not current
        if queued:
            self._head = {solve_id(job): job for job in current}
            self.done, self.total = 0, len(queued)
            self.slice_jobs = len(self._head)
            self.refiner.start(list(queued.values()), on_landed, on_error)
        elif self.stretch is not None and not self.stretch[2]:
            self.stretch = None  # every window is solved: measure the final one
            redraw = True
        return redraw

    def landed(self, job: Any) -> bool:
        """A solve finished, handed over on the GUI thread. It lands in its
        engine's cache whatever is on screen. Whether the scope redraws: for
        a solve the preview on screen waits for, and once the list ends,
        with a provisional stretch dropped so the final one is measured."""
        landed = job.land()
        ident = solve_id(job)
        self.done += 1
        self._head.pop(ident, None)
        redraw = landed and self.provisional and ident in self._awaited
        if not self.refiner.busy:
            self._head = {}
            if self.stretch is not None and not self.stretch[2]:
                self.stretch = None
            redraw = True
        return redraw

    def failed(self, message: str) -> str:
        """The list ended in an error. The preview stays on screen, blanks
        and all; what the scope reports."""
        self._head = {}
        return f"minimum curvature failed: {message}"

    # ---- the shared stretch -------------------------------------------------
    def stretch_limit(self, key: Any, measure: Callable[[], tuple[float, bool]]) -> float:
        """The shared stretch for `key`, re-measured (`measure() -> (limit,
        final)`) only when the one held is for another key: a measurement
        is a pass over many windows, never a per-tick cost. A provisional
        stretch, held or just measured, arms the rest when nothing is on its
        way to finish it (a refine that failed, or one a failed draw
        cancelled), so the next rest queues its windows (plan call 7)."""
        held = self.stretch
        if held is not None and held[0] == key:
            if not held[2]:
                self._arm()
            return held[1]
        value, final = measure()
        self.stretch = (key, value, final)
        if not final:
            self._arm()
        return value

    def stretch_final(self, key: Any) -> bool:
        """Whether the stretch held is final for `key`. A rest then asks for
        no stretch solves (Ruling R11): asking slices and hashes every window
        on the GUI thread, about 84 ms at a million cells, for nothing."""
        held = self.stretch
        return held is not None and held[0] == key and held[2]

    def _arm(self) -> None:
        if not self.refiner.busy and not self.rest.isActive():
            self.rest.start()
