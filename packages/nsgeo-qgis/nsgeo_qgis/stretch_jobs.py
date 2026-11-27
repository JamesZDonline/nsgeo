"""The shared colour stretch measured off the GUI thread, equal to today's (#193).

`StretchJob` is a `RefineJob`: `run(should_stop)` executes on a worker and uses
only numpy and what was captured when it was made on the GUI thread (a frozen
`WindowSource` per grid, copies of the solved cache, the clip and the
normalisation inputs). It touches no Qt, session or QGIS object and never a
live engine. `land()` runs on the GUI thread afterwards: it marks the cached
solves a final pass read as recently used in their engines (`GridStretch.touch`,
called there only), and the scope stores the result.

The per-window measurement is a handful of pure functions here -- `shared_windows`,
`shown_window`, `limit_of` and `draw_window` -- that the synchronous paths
(`SiteEngine._shown`/`_measure`, `SliceEngine.shared_limit`) call too, so there
is one implementation of what a stretch measures.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import chain
from typing import TYPE_CHECKING, Any

import numpy as np
from nsgeo.slices import (
    CubeFrame,
    FillWeights,
    FinishSettings,
    LinePlan,
    PreparedLine,
    Seam,
    SliceCube,
    SliceFill,
    SliceWindow,
    SolveStopped,
    ZAxis,
    finish_slice,
    limit_over_slices,
    normalise,
    plan_windows,
    smooth,
    stream_slice,
)

from nsgeo_qgis.slices_plan import limit_windows

if TYPE_CHECKING:
    from nsgeo_qgis.fill_jobs import FillJob


class WindowSource:
    """A frozen snapshot of what slices a grid: its frame, z axis and either the
    resident cube or the prepared lines and their plans.

    `slice` is pure numpy, as `SliceEngine._slice`. Neither `SliceCube.slice_levels`
    nor `stream_slice` writes what it reads (fancy indexing copies, results are
    fresh arrays), so nothing here is copied except the line and plan lists,
    which are held as tuples so a later in-place change of the engine's lists
    cannot reach a running job.
    """

    def __init__(
        self,
        frame: CubeFrame,
        z: ZAxis,
        *,
        cube: SliceCube | None,
        lines: Sequence[PreparedLine],
        plans: Sequence[LinePlan],
    ) -> None:
        self.frame = frame
        self.z = z
        self._cube = cube
        self._lines = tuple(lines)
        self._plans = tuple(plans)

    def slice(self, window: SliceWindow) -> tuple[np.ndarray, np.ndarray]:
        if self._cube is not None:
            return self._cube.slice_levels(window.k0, window.k1), self._cube.coverage()
        return stream_slice(self._lines, self._plans, self.frame, self.z, window.k0, window.k1)


# ---- the pure measurement ---------------------------------------------------
def shared_windows(z: ZAxis, thickness_levels: int, curvature: bool) -> list[SliceWindow]:
    """The windows one grid's shared stretch is measured over: for minimum
    curvature `limit_windows` (at most twelve); otherwise every abutting window
    plus a thinner tail window when the thickness does not divide the axis."""
    if curvature:
        return list(limit_windows(z, thickness_levels))
    windows = list(plan_windows(z, thickness_levels, thickness_levels))
    if windows[-1].k1 < z.nz:
        windows.append(SliceWindow(windows[-1].k1, z.nz))
    return windows


def shown_window(
    binned: Mapping[str, tuple[np.ndarray, np.ndarray]],
    method: str,
    seams: Sequence[Seam],
    manual: Mapping[str, float],
    draw: Callable[[str, np.ndarray, np.ndarray], np.ndarray],
) -> tuple[dict[str, np.ndarray], dict[str, tuple[float, float]]]:
    """Each present grid's displayed slice and the factors applied (spec 4.6):
    `normalise` on the binned cells, then `a * draw(values) + b`."""
    factors = normalise(method, binned, seams, manual)
    shown: dict[str, np.ndarray] = {}
    for grid_id, (values, cov) in binned.items():
        a, b = factors[grid_id]
        shown[grid_id] = a * draw(grid_id, values, cov) + b
    return shown, factors


def limit_of(slices: Iterable[np.ndarray], clip: Any) -> float:
    """`clip`'s limit over `slices`; the empty site's limit when there are none.
    An iterable is consumed one slice at a time, so a generator streams."""
    items = iter(slices)
    try:
        first = next(items)
    except StopIteration:
        return float(clip.limit(np.array([], dtype=float)))
    return limit_over_slices(chain([first], items), clip)


class _Unsolved(Exception):
    """A minimum-curvature window is not in the solved cache."""


class _Fills:
    """One grid's fill for a job: the held one where its cells match, otherwise
    built here (never installed) with `should_stop`, once per distinct mask."""

    def __init__(
        self,
        fill: SliceFill | None,
        preview: FillWeights | None,
        cell: float,
        settings: FinishSettings,
        should_stop: Callable[[], bool],
    ) -> None:
        self._held = (fill, preview)
        self._cell = cell
        self._settings = settings
        self._should_stop = should_stop
        self._built: dict[bytes, tuple[SliceFill, FillWeights | None]] = {}

    def holds(self, coverage: np.ndarray) -> bool:
        fill = self._held[0]
        return fill is not None and bool(np.array_equal(fill.populated, (coverage > 0).ravel()))

    def get(self, coverage: np.ndarray) -> tuple[SliceFill, FillWeights | None]:
        if self.holds(coverage):
            fill, preview = self._held
            assert fill is not None
            return fill, preview
        # Lazy: the engine imports this module. The one fill rule lives there.
        from nsgeo_qgis.slices_engine import build_fill

        populated = coverage > 0
        key = populated.tobytes()
        if key not in self._built:
            self._built[key] = build_fill(
                populated, self._cell, self._settings, should_stop=self._should_stop
            )
        return self._built[key]


@dataclass
class GridStretch:
    """What one grid contributes to a stretch, captured on the GUI thread."""

    source: WindowSource
    settings: FinishSettings
    cell: float
    #: The fill job whose result is read when the job runs, or None.
    fill_job: FillJob | None = None
    #: The engine's held fill and preview when `fill_job` is None (None: build).
    held: tuple[SliceFill, FillWeights | None] | None = None
    #: A copy of the engine's solved-slice cache (minimum curvature only).
    solved: dict[bytes, np.ndarray] = field(default_factory=dict)
    #: GUI thread: marks solve keys recently used in the engine's own cache,
    #: as the synchronous stretch does when it reads them (None: no cache).
    touch: Callable[[Sequence[bytes]], None] | None = None


def draw_window(
    values: np.ndarray,
    coverage: np.ndarray,
    fills: _Fills,
    cell: float,
    settings: FinishSettings,
    *,
    mode: str,
    solved: Mapping[bytes, np.ndarray],
    used: list[bytes] | None = None,
) -> np.ndarray:
    """One window as the stretch draws it. `mode` is `"fill"` (the fill),
    `"solved"` (a cached minimum-curvature solve, smoothed; `_Unsolved` when not
    cached; its key appended to `used`) or `"preview"` (the kriging stand-in)."""
    if mode == "solved":
        from nsgeo_qgis.slices_engine import solve_key

        if not fills.holds(coverage):
            raise _Unsolved
        key = solve_key(values)
        hit = solved.get(key)
        if hit is None:
            raise _Unsolved
        if used is not None:
            used.append(key)
        return smooth(hit, cell, settings.smooth_x_m, settings.smooth_y_m)
    fill, preview = fills.get(coverage)
    if mode == "preview":
        assert preview is not None  # built with the plan
        return finish_slice(values, preview, cell, settings)
    return finish_slice(values, fill, cell, settings)


class StretchJob:
    """The shared limit, measured as `stretch_limit` measures it today.

    `limit` is None and `final` False until `run` completes; a job whose fill
    job landed refused (its `fill` is None) measures nothing and leaves them so.
    `steps` is one `{grid_id: SliceWindow | None}` per measured window; the
    slice scope has one grid and no normalisation (`site=False`).
    """

    def __init__(
        self,
        grids: Mapping[str, GridStretch],
        steps: Sequence[Mapping[str, SliceWindow | None]],
        clip: Any,
        *,
        curvature: bool,
        site: bool,
        method: str = "none",
        manual: Mapping[str, float] | None = None,
        seams: Sequence[Seam] = (),
    ) -> None:
        self._grids = dict(grids)
        self._steps = [dict(s) for s in steps]
        self._clip = clip
        self._curvature = curvature
        self._site = site
        self._method = method
        self._manual = dict(manual or {})
        self._seams = tuple(seams)
        self.limit: float | None = None
        self.final = False
        #: Set once `run` has let go of what it captured: a second run has
        #: nothing to measure, so it measures nothing (never the empty site's
        #: limit, which would read as final).
        self._released = False
        #: The solve keys a final minimum-curvature pass read, by grid, with
        #: each grid's `touch`: refreshed in the engines when the job lands.
        self._used: list[tuple[Callable[[Sequence[bytes]], None], list[bytes]]] = []
        #: Written by the worker, read by the GUI thread: a float store.
        self.fraction = 0.0

    def run(self, should_stop: Callable[[], bool]) -> None:
        """Worker thread. Raises `SolveStopped` when stopped. Whatever happens,
        everything captured is released at the end: `land` needs only `limit`
        and `final`, so a job run again measures nothing."""
        self.limit, self.final, self.fraction = None, False, 0.0
        self._used = []
        if self._released:
            return
        try:
            self._measure(should_stop)
        finally:
            self._released = True
            self._grids = {}
            self._steps = []
            self._seams = ()

    def _measure(self, should_stop: Callable[[], bool]) -> None:
        fills: dict[str, _Fills] = {}
        for grid_id, grid in self._grids.items():
            fill, preview = None, None
            if grid.fill_job is not None:
                # Read once: the GUI thread may refuse the landing and let go.
                fill, preview = grid.fill_job.fill, grid.fill_job.preview
                if fill is None or (grid.settings.method == "min_curvature" and preview is None):
                    return  # stale: measure nothing
            elif grid.held is not None:
                fill, preview = grid.held
            fills[grid_id] = _Fills(fill, preview, grid.cell, grid.settings, should_stop)

        total = len(self._steps) * (2 if self._curvature else 1)
        done = 0
        used: dict[str, list[bytes]] = {grid_id: [] for grid_id in self._grids}

        def windows(mode: str) -> Iterator[np.ndarray]:
            nonlocal done
            for step in self._steps:
                if should_stop():
                    raise SolveStopped
                yield from self._window(step, fills, mode, used)
                done += 1
                self.fraction = done / total

        def pass_(mode: str) -> float:
            # Both scopes stream, as `SliceEngine.shared_limit` and
            # `SiteEngine._measure` do: one window's slices alive at a time.
            return limit_of(windows(mode), self._clip)

        if not self._curvature:
            self.limit, self.final = pass_("fill"), True
        else:
            try:
                self.limit, self.final = pass_("solved"), True
                self._used = [
                    (touch, used[grid_id])
                    for grid_id, grid in self._grids.items()
                    if (touch := grid.touch) is not None and used[grid_id]
                ]
            except _Unsolved:
                self.limit, self.final = pass_("preview"), False
        self.fraction = 1.0

    def _window(
        self,
        step: Mapping[str, SliceWindow | None],
        fills: Mapping[str, _Fills],
        mode: str,
        used: Mapping[str, list[bytes]],
    ) -> Iterator[np.ndarray]:
        binned: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for grid_id, window in step.items():
            if window is not None:
                binned[grid_id] = self._grids[grid_id].source.slice(window)

        def draw(grid_id: str, values: np.ndarray, cov: np.ndarray) -> np.ndarray:
            grid = self._grids[grid_id]
            return draw_window(
                values,
                cov,
                fills[grid_id],
                grid.cell,
                grid.settings,
                mode=mode,
                solved=grid.solved,
                used=used[grid_id],
            )

        if not self._site:
            return (draw(grid_id, *pair) for grid_id, pair in binned.items())
        shown, _ = shown_window(binned, self._method, self._seams, self._manual, draw)
        return iter(shown.values())

    def land(self) -> bool:
        """GUI thread: the scope stores `limit` and `final`. The solves a final
        pass read are marked recently used in their engines, as the synchronous
        stretch marks them, so the next solves evict other slices first."""
        used, self._used = self._used, []
        for touch, keys in used:
            touch(keys)
        return True
