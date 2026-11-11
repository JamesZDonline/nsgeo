"""A vertical section along a cut: columns, crops, and finishing (cut spec §3, §4.7).

A section is the cube read along a drawn path. Its columns sit half a cell
apart (plan call 4), and each takes the bilinear blend of the four finished
cells around it, blank exactly where its nearest cell is blank: the pixel rule
of `resample.py` (#107), reached through `bilinear_taps` and `sample` and
never rewritten here. So a column equals the same point read off the finished
slice, level by level, and averaging a window of levels commutes with the
blend (the blend is linear and its blanks do not depend on the level).

The finished values are needed only at the cells the columns touch, so no
whole slice is finished unless smoothing asks for it:

* None, IDW and kriging with no smoothing fill only the columns' tap cells
  (`FillWeights.apply_at`) into a blank canvas and `sample` that.
* Smoothing finishes crops: a box round each piece of the cut (at most
  `SECTION_PIECE_M` of it), reaching the kernel's radius plus one cell past
  the nearest cells, so a smoothed section equals the sampled smoothed slice.
* Minimum curvature has no weights to reuse: it solves each crop on a plan
  built once for the cut (`plan_section_curvature`), reaching
  `SECTION_MARGIN_SPACINGS` line spacings plus one cell (plan call 7).

Measured on 2026-11-06 and again on 2026-11-11 after #111 (multigrid) and #107
(bilinear columns), one thread, on Grid 1's saved cubes with a 12 m diagonal
cut and columns at half a cell. Spike numbers, not this module's:

    case                                      0.2 m (234 levels)  0.05 m (211 levels)
    kriging, every level, tap cells only      11 ms               33 ms
    kriging on whole levels, then the blend   0.07 s              1.0 s
    kriging, smoothing Y 0.1 m, whole levels  0.12 s              2.2 s
    min curvature, one level, whole frame     0.02 s              0.30 s (15 iterations)
    min curvature, every level, whole frame   about 5 s           about 1 min

Smoothing whole levels at 0.05 m (2.2 s) is why smoothing works on crops.
Kriging against minimum curvature on one level, over the gap cells, differs
by 5.1-7.4% of the range at the 99th percentile and 17-43% at worst, which is
why a cut under minimum curvature shows a kriging stand-in until it is solved.

How far a curvature crop must reach is set by the line spacing, not by metres
(`curvature_margin_cells`). Minimum curvature through one-cell-wide lines
couples across lines like a spline across knots, falling by a fixed factor per
line crossed. Measured on 2026-11-11 on the ten real lines (0.5 m apart, levels
30, 90 and 150, max distance 0.25 m), the worst gap from a whole-frame solve on
the cut's columns, as a share of the level's range, worst of along x, along y
and a 12 m diagonal, with no smoothing (smoothing Y 0.1 m is no worse):

    reach (spacings)    2 (1 m)   4 (2 m)   6 (3 m)   8 (4 m)
    0.2 m cells         0.64%     0.017%    0.00016%  0.00003%
    0.05 m cells        3.2%      0.19%     0.0022%   0.0020%

So 1 m, the plan's first setting, missed the 0.1% requirement by up to 30x;
6 spacings meets it with 45x to spare. Solve time a level at 6 spacings, one
thread, 0.05 m cells: 0.18 s along x (12 m), 0.07 s along y (4.4 m), 0.20 s on
the 12 m diagonal; at 0.2 m cells 0.02 s. Planning each crop once is not
counted. A whole-frame solve at 0.05 m is 0.30 s a level.

Crops hold only up to a max distance of `CROP_MAX_DISTANCE_SPACINGS` (0.75)
line spacings. The 6-spacing reach rests on coupling that falls by a fixed
factor per line crossed, and a coverage hole has no lines to cross, so the
coupling reaches much further. Measured on 2026-11-11 on the ten real lines
with lines 3-6 dropped (a 2 m hole), worst gap on the cut's columns as a share
of the range: 3.3e-4 at 0.75 spacings, 2.1e-3 at 1.0, 0.5-0.9% at 1.5 and up
to 1.4% at 2.0; on synthetic grids with a 7 m hole the solved cut went blank
where the slice is filled. So above the threshold a section solves the whole
frame (`solve_section_level_whole`), about 0.30 s a level on Grid 1 at 0.05 m.

numpy only.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from nsgeo.slices.cube import SliceCube
from nsgeo.slices.curvature import CurvaturePlan, plan_curvature
from nsgeo.slices.finish import FinishSettings
from nsgeo.slices.frame import CubeFrame
from nsgeo.slices.interpolate import FillWeights
from nsgeo.slices.resample import Taps, bilinear_taps, sample
from nsgeo.slices.smooth import SMOOTH_TRUNCATE_SIGMAS, smooth

# How far a curvature crop reaches round the cut, in line spacings (see the module docstring).
SECTION_MARGIN_SPACINGS: float = 6.0
SECTION_PIECE_M: float = 4.0  # the most of a cut one crop covers
# Crops are exact only while no hole can couple far past the lines: up to this max distance, in line
# spacings. Past it a section solves the whole frame (`uses_crops`, I1 of M15's final review).
CROP_MAX_DISTANCE_SPACINGS: float = 0.75
_STEP_SLACK = 1e-9  # relative: a step of exactly half a cell is allowed


@dataclass(frozen=True, eq=False)
class SectionColumns:
    """Where a section's columns sit: along the path, and among the frame's cells."""

    distance_m: np.ndarray  # (n,) from 0 to the path's length
    local: np.ndarray  # (n, 2) frame-local metres
    world: np.ndarray  # (n, 2) in the frame's CRS
    cells: np.ndarray  # (n,) intp flat cell id, -1 outside the frame (== taps.nearest)
    taps: Taps  # the pixel rule's corners (#107)

    @cached_property
    def tap_cells(self) -> np.ndarray:
        """Sorted unique flat ids of the inside columns' taps: the only cells a section reads."""
        inside = self.cells >= 0
        return np.unique(self.taps.ids[:, inside])


def column_distances(length_m: float, step_m: float) -> np.ndarray:
    """Distances of a section's columns along a path: 0, step, 2*step, ... with
    a last column exactly at `length_m`. Defined once, so whoever places a
    column by distance (the plugin's cursor) agrees with `section_columns`.

    The tolerance keeps a length that is a whole number of steps from growing
    a sliver column from rounding (30.000000000000004 steps).
    """
    if not (length_m > 0.0 and step_m > 0.0):
        raise ValueError(f"length and step must be positive, got {length_m} and {step_m}")
    count = int(math.ceil(length_m / step_m - 1e-9))
    distance = np.minimum(np.arange(count + 1, dtype=float) * step_m, length_m)
    distance[-1] = length_m
    return distance


def section_columns(
    frame: CubeFrame, path_local: np.ndarray, step_m: float | None = None
) -> SectionColumns:
    """Columns along a polyline given in frame-local metres.

    They are `step_m` apart (default half a cell) from 0, with a last column
    exactly at the path's length. A step over half a cell would let a cell go
    unread, so it is refused.
    """
    path = np.asarray(path_local, dtype=float)
    if path.ndim != 2 or path.shape[1] != 2 or path.shape[0] < 2:
        raise ValueError(f"a path needs at least two (x, y) points, got shape {path.shape}")
    if not np.isfinite(path).all():
        raise ValueError("path points must be finite")
    half = frame.cell / 2.0
    step = half if step_m is None else float(step_m)
    if not step > 0.0 or step > half * (1.0 + _STEP_SLACK):
        raise ValueError(f"step must be in (0, {half}], got {step}")
    along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(path, axis=0).T))])
    length = float(along[-1])
    if not length > 0.0:
        raise ValueError("the path has zero length")
    distance = column_distances(length, step)
    local = np.column_stack(
        [np.interp(distance, along, path[:, 0]), np.interp(distance, along, path[:, 1])]
    )
    x_hat, y_hat = frame.axes()
    world = np.asarray(frame.origin, dtype=float) + local[:, :1] * x_hat + local[:, 1:] * y_hat
    taps = bilinear_taps(frame, world)
    return SectionColumns(distance, local, world, taps.nearest.astype(np.intp), taps)


@dataclass(frozen=True, eq=False)
class SectionCrop:
    """A box of cells round one piece of the cut, and the columns it serves."""

    rows: tuple[int, int]  # half-open
    cols: tuple[int, int]  # half-open
    columns: np.ndarray  # indices into the SectionColumns

    @property
    def shape(self) -> tuple[int, int]:
        return (self.rows[1] - self.rows[0], self.cols[1] - self.cols[0])

    def flat_cells(self, nx: int) -> np.ndarray:
        """Flat ids of the box's cells, row by row."""
        rows = np.arange(self.rows[0], self.rows[1], dtype=np.intp)
        cols = np.arange(self.cols[0], self.cols[1], dtype=np.intp)
        return (rows[:, None] * nx + cols[None, :]).ravel()


def smoothing_reach_cells(settings: FinishSettings, cell: float) -> int:
    """The smoothing kernel's radius in cells, the larger of the two axes (0 if none)."""
    sigma_m = max(settings.smooth_x_m, settings.smooth_y_m)
    if sigma_m == 0.0:
        return 0
    return int(math.ceil(SMOOTH_TRUNCATE_SIGMAS * (sigma_m / cell)))


def curvature_margin_cells(settings: FinishSettings, cell: float, spacing_m: float) -> int:
    """The margin `section_crops` needs for a minimum-curvature solve, in cells.

    `SECTION_MARGIN_SPACINGS` line spacings, or the smoothing kernel's radius
    if that is larger, plus one cell for the blend's far tap. It is in spacings
    because the curvature surface couples across lines by a fixed factor per
    line, so the reach that meets the 0.1% requirement follows the spacing:
    a 1 m margin on 0.5 m lines was 0.2-3% off a whole-frame solve, 3 m is
    0.002% (module docstring).
    """
    reach = int(math.ceil(SECTION_MARGIN_SPACINGS * spacing_m / cell))
    return max(reach, smoothing_reach_cells(settings, cell)) + 1


def uses_crops(max_distance_m: float, spacing_m: float) -> bool:
    """Whether a minimum-curvature section may be solved on crops (cut spec §4.7).

    True up to `CROP_MAX_DISTANCE_SPACINGS` line spacings; above it a hole can
    couple past any crop, so the whole frame is solved.
    """
    return max_distance_m <= CROP_MAX_DISTANCE_SPACINGS * spacing_m * (1.0 + 1e-9)


def section_crops(
    columns: SectionColumns,
    frame: CubeFrame,
    margin_cells: int,
    piece_m: float = SECTION_PIECE_M,
) -> tuple[SectionCrop, ...]:
    """Boxes round the cut, each serving at most `piece_m` of it (cut spec §4.7).

    Every inside column belongs to exactly one crop. A cut that leaves the
    frame and comes back gets separate crops, so no box spans the gap. A box
    reaches `margin_cells` past its columns' nearest cells and always holds
    every cell a column blends, clipped to the frame.
    """
    inside = np.flatnonzero(columns.cells >= 0)
    pieces: list[np.ndarray] = []
    if inside.size:
        runs = np.split(inside, np.flatnonzero(np.diff(inside) > 1) + 1)
        for run in runs:
            start = 0
            while start < run.size:
                reach = columns.distance_m[run] - columns.distance_m[run[start]]
                end = int(np.searchsorted(reach, piece_m, side="right"))
                pieces.append(run[start : max(end, start + 1)])
                start = max(end, start + 1)
    crops = []
    nx, ny = frame.nx, frame.ny
    for piece in pieces:
        iy, ix = np.divmod(columns.cells[piece], nx)
        lo_y, hi_y = int(iy.min()) - margin_cells, int(iy.max()) + margin_cells + 1
        lo_x, hi_x = int(ix.min()) - margin_cells, int(ix.max()) + margin_cells + 1
        weights = columns.taps.weights[:, piece]
        ids = columns.taps.ids[:, piece][weights > 0]
        if ids.size:
            ty, tx = np.divmod(ids, nx)
            lo_y, hi_y = min(lo_y, int(ty.min())), max(hi_y, int(ty.max()) + 1)
            lo_x, hi_x = min(lo_x, int(tx.min())), max(hi_x, int(tx.max()) + 1)
        crops.append(
            SectionCrop(
                rows=(max(lo_y, 0), min(hi_y, ny)),
                cols=(max(lo_x, 0), min(hi_x, nx)),
                columns=piece,
            )
        )
    return tuple(crops)


def _crop_taps(columns: SectionColumns, crops: Sequence[SectionCrop]) -> list[Taps]:
    return [columns.taps.take(crop.columns) for crop in crops]


def finish_section(
    cube: SliceCube, fill: FillWeights, columns: SectionColumns, settings: FinishSettings
) -> np.ndarray:
    """(nz, n) float32: every level of the cube, finished and read along the columns.

    Equals `sample(finish_slice(cube.level(k), fill, cell, settings), taps)`
    at every level k, without finishing the whole slice. Minimum curvature has
    no weights, so a `CurvaturePlan` is refused: use `solve_section_level`.
    """
    if isinstance(fill, CurvaturePlan):
        raise TypeError("a curvature plan solves whole levels; use solve_section_level")
    frame = cube.frame
    nx = frame.nx
    out = np.full((cube.z.nz, columns.distance_m.size), np.nan, dtype=np.float32)
    canvas = np.full((frame.ny, nx), np.nan, dtype=np.float32)
    flat = canvas.reshape(-1)
    reach = smoothing_reach_cells(settings, frame.cell)
    if reach == 0:
        cells = columns.tap_cells
        for k in range(cube.z.nz):
            flat[cells] = fill.apply_at(cube.level(k), cells)
            out[k] = sample(canvas, columns.taps)
        return out
    crops = section_crops(columns, frame, reach + 1)
    taps = _crop_taps(columns, crops)
    cell_ids = [crop.flat_cells(nx) for crop in crops]
    for k in range(cube.z.nz):
        level = cube.level(k)
        for crop, crop_taps, ids in zip(crops, taps, cell_ids):
            block = fill.apply_at(level, ids).reshape(crop.shape)
            (r0, r1), (c0, c1) = crop.rows, crop.cols
            canvas[r0:r1, c0:c1] = smooth(
                block, frame.cell, settings.smooth_x_m, settings.smooth_y_m
            )
            out[k, crop.columns] = sample(canvas, crop_taps)
    return out


def plan_section_curvature(
    populated: np.ndarray, crops: Sequence[SectionCrop], cell: float, max_distance_m: float
) -> tuple[CurvaturePlan, ...]:
    """One curvature plan per crop, built once and used for every level (plan call 7)."""
    pop = np.asarray(populated, dtype=bool)
    return tuple(
        plan_curvature(
            pop[crop.rows[0] : crop.rows[1], crop.cols[0] : crop.cols[1]], cell, max_distance_m
        )
        for crop in crops
    )


def solve_section_level(
    level: np.ndarray,
    columns: SectionColumns,
    crops: Sequence[SectionCrop],
    plans: Sequence[CurvaturePlan],
    settings: FinishSettings,
    cell: float,
    should_stop: Callable[[], bool] | None = None,
) -> np.ndarray:
    """(n,) float32: one level solved on the crops and read along the columns.

    `SolveStopped` propagates when `should_stop` asks. Columns in no crop (outside
    the frame) are NaN.
    """
    level = np.asarray(level)
    canvas = np.full(level.shape, np.nan, dtype=np.float32)
    out = np.full(columns.distance_m.size, np.nan, dtype=np.float32)
    for crop, plan, crop_taps in zip(crops, plans, _crop_taps(columns, crops)):
        (r0, r1), (c0, c1) = crop.rows, crop.cols
        solved, _ = plan.solve(level[r0:r1, c0:c1], should_stop)
        canvas[r0:r1, c0:c1] = smooth(solved, cell, settings.smooth_x_m, settings.smooth_y_m)
        out[crop.columns] = sample(canvas, crop_taps)
    return out


def solve_section_level_whole(
    level: np.ndarray,
    columns: SectionColumns,
    plan: CurvaturePlan,
    settings: FinishSettings,
    cell: float,
    should_stop: Callable[[], bool] | None = None,
) -> np.ndarray:
    """(n,) float32: one level solved on the whole frame and read along the columns.

    The path for a max distance above `CROP_MAX_DISTANCE_SPACINGS` (`uses_crops`).
    `plan` is the frame's own plan, the one the slice view solves with. A solve
    writes nothing to it, so jobs on several threads may share it.
    """
    solved, _ = plan.solve(np.asarray(level), should_stop)
    smoothed = smooth(solved, cell, settings.smooth_x_m, settings.smooth_y_m)
    return np.asarray(sample(smoothed, columns.taps), dtype=np.float32)
