"""The export pipeline, without Qt: bands of a site or a grid at any cell and pixel.

`run_export` rebuilds the live Whole-site composition (`SiteEngine.slice_at`,
`SliceEngine.finish`) from `nsgeo.slices` alone, so it can run on a worker
thread: no live engine, no session, no shared cache, no Qt. This grid is the
same pipeline with one grid, normalisation `"none"`, and a lattice from
`frame_lattice`. `estimate_export` sizes it before anything runs.

Order of work (spec 6.2): band by band, holding every grid's fill weights.

Measured, then chosen (spec 6.2)
--------------------------------
`packages/nsgeo-qgis/scripts/bench_site.py --export CELL PIXEL`, on synthetic
lines laid like the walkthrough site's: ten 20 m grids at 0.5 m line spacing,
60 traces a metre, eight of them 4-10 degrees off north and two near 90, in a
65 x 84 m block. Edge-match normalisation, 3 bands of 5 ns, kriging at 0.75
line spacings (and minimum curvature at the same distance), no smoothing.
One thread, 2026-11-11. Peak is `tracemalloc` over the whole run, prepared
lines excluded (the live engines hold them already; the lines here are 246 MB).
The first band includes the setup: plans, taps, seams and, for kriging, every
grid's fill weights (14 s a grid at 0.025 m).

| cell | pixel | method | lattice | first band (s) | band (s) | peak (MB) | estimate (MB) |
|---|---|---|---|---|---|---|---|
| 0.05 | 0.05 | kriging | 1304 x 1687 | 14.4 | 0.4 | 294 | 305 |
| 0.05 | 0.05 | min curvature | 1304 x 1687 | 7.6 | 3.3 | 302 | 311 |
| 0.025 | 0.025 | kriging | 2607 x 3374 | 147.6 | 0.9 | 1204 | 1220 |
| 0.025 | 0.025 | min curvature | 2607 x 3374 | 44.0 | 22.0 | 1179 | 1243 |
| 0.025 | 0.0125 | kriging | 5214 x 6748 | 159.5 | 2.2 | 2768 | 2783 |
| 0.025 | 0.0125 | min curvature | 5214 x 6748 | 51.2 | 20.6 | 2743 | 2806 |

Where the memory goes at 0.025 m cell, 0.0125 m pixel: the taps, 1575 MB (52 B
for each of 30 M covered pixels); the fill weights, 614 MB; one band's
accumulators, 401 MB. Every grid streams at these line counts. Minimum
curvature's band is 2.1 s a grid (the spec's worst case was 11 s); a cancel
lands inside one grid's solve.

Decision: band by band, at `EXPORT_BUDGET_BYTES` = `DEFAULT_BUDGET_BYTES` (1.5 GB),
not more, because the live engines hold up to 1.5 GB of their own in the same
process. The walkthrough cases fit (0.05 m cell at a 0.05 m pixel, and 0.025 m
at 0.025 m). The 0.025 m cell at a 0.0125 m pixel row does not (2.8 GB, most of
it the taps): it is refused before it starts, with the finest pixel that fits.
Lifting that ceiling (rebuilding each grid's taps per band, or strip-wise or
grid-by-grid composition) is a follow-up. On this geometry, by `estimate_export`
bisected on a 1 mm grid, the finest pixel that fits is 0.021 m at a 0.025 m
cell and 0.016 m at a 0.05 m cell.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

import numpy as np
from nsgeo.slices import (
    CubeFrame,
    CurvaturePlan,
    FinishSettings,
    Footprint,
    PreparedLine,
    Provenance,
    Seam,
    SiteLattice,
    SliceCube,
    SliceFill,
    SolveStopped,
    ZAxis,
    bilinear_taps,
    build_cube,
    compose_footprints,
    covered_cells,
    covered_pixels,
    find_seams,
    finish_slice,
    footprint,
    normalise,
    plan_fill,
    plan_line,
    slice_extent,
    smooth,
    stream_slice,
    window_on,
)

from nsgeo_qgis.slices_plan import (
    EXPORT_BUDGET_BYTES,
    MemoryEstimate,
    choose_residency,
    estimate_memory,
)


class ExportCancelled(Exception):
    """The user cancelled an export between two bands (plan call 11).

    Raised by the exporters when their `progress` callback returns False, so a
    caller can tell a cancel from a failure and report each in its own words.
    The pipeline raises it where its `should_stop` says so: between grids and
    inside a minimum-curvature solve.
    """


#: Bytes a bilinear tap costs per output pixel (`Taps`: four ids, four weights, one cell id).
TAP_BYTES_PER_PIXEL = 52

#: Bytes per pixel of a grid's window that building its taps holds on top of them
#: (the pixel centres and the transform's intermediates): measured 37-51 against
#: the largest grid's window, so 56 covers it.
GATHER_BYTES_PER_PIXEL = 56

#: Bytes per output pixel the compose holds: a float32 sum, a uint8 count and the float32 result.
COMPOSE_BYTES_PER_PIXEL = 9

#: Bytes per frame cell one grid's band holds while it is finished: its binned
#: values and coverage (float32, int32) and its shown slice (float32).
BAND_BYTES_PER_CELL = 12

#: Bytes per frame cell a stream bin holds while it runs: a float32 sum and an int64 count.
STREAM_BYTES_PER_CELL = 12

#: Bytes per frame cell a minimum-curvature solve holds besides its plan:
#: the result, the data, the padded direction, `q`, `work`, `r` and `z`.
SOLVE_BYTES_PER_CELL = 36

#: How many lattice points per side a grid in another CRS is probed with to find its window.
_PROBE_POINTS = 96

#: A bigger file than this holds its bands as BigTIFF; used by the writers, here for the estimate.
OVERVIEW_FACTOR = 4.0 / 3.0


@dataclass(frozen=True, eq=False)
class ExportGrid:
    """One grid as the export sees it: a snapshot taken when Export was pressed.

    `lines` are the prepared lines, `frame` the grid's frame at the export cell
    and `z` its own time axis. `finish` is the interpolation in metres.
    `world_to_frame` takes (n, 2) points in the output CRS to the frame's CRS;
    None when the frame already shares the output CRS. `run_export` calls it
    only while building this grid's taps, never when the spec is built.
    """

    grid_id: str
    lines: tuple[PreparedLine, ...]
    frame: CubeFrame
    z: ZAxis
    finish: FinishSettings
    spacing_m: float
    gain: float
    world_to_frame: Callable[[np.ndarray], np.ndarray] | None = None


@dataclass(frozen=True, eq=False)
class ExportSpec:
    """Everything an export needs: the grids, the output and the bands.

    `windows` are each band's `(top_ns, thickness_ns)` on the site's time axis;
    every grid maps them onto its own axis (`window_on`), or is absent from a
    band its axis misses. `method` is the normalisation (`"none"` for This
    grid). `coverage` writes trace counts instead of amplitudes.
    """

    grids: tuple[ExportGrid, ...]
    lattice: SiteLattice
    windows: tuple[tuple[float, float], ...]
    method: str
    coverage: bool


@dataclass(frozen=True)
class ExportEstimate:
    """What an export holds and writes, in bytes.

    `held_bytes` is the memory the export adds while it runs, the sum of
    `per_band` less the prepared lines, which the live engines already hold and
    the export only refers to. `file_bytes` is the uncompressed file, overviews
    included. `per_band` names the parts: `lines` (informational), `cubes`,
    `weights`, `taps`, `gather` (building the taps), `band` and `solve`.
    """

    held_bytes: int
    file_bytes: int
    per_band: dict[str, int]


@dataclass(frozen=True, eq=False)
class ExportBand:
    """One finished band: float32 on the spec's lattice, NaN for nodata, and
    the `(a, b)` applied to each grid present in it (1, 0 for counts)."""

    array: np.ndarray
    factors: dict[str, tuple[float, float]]


# ---- sizing -----------------------------------------------------------------
def _grid_estimate(grid: ExportGrid, n_covered: int) -> MemoryEstimate:
    samples = sum(int(line.data.size) for line in grid.lines)
    return estimate_memory(samples, grid.frame.n_cells, grid.z.nz, n_covered)


#: A memo of covered-cell counts for `estimate_export`, owned by whoever calls it repeatedly.
CoveredCache = dict[tuple[object, ...], tuple[tuple[PreparedLine, ...], int]]


def _covered(grid: ExportGrid, cache: CoveredCache | None = None) -> int:
    """The cells any trace of `grid` falls in at its frame. With a `cache`, each
    (grid, frame, lines) is counted once: the count walks every trace (about 100 ms
    on ten grids of 400 lines), and the dialog asks for many pixels at one cell.
    The cache keeps a reference to the lines it keyed on, so their ids stay theirs."""
    if cache is None:
        return covered_cells(grid.frame, (line.coords for line in grid.lines))
    key = (grid.grid_id, grid.frame, tuple(id(line) for line in grid.lines))
    hit = cache.get(key)
    if hit is None:
        count = covered_cells(grid.frame, (line.coords for line in grid.lines))
        hit = cache[key] = (grid.lines, count)
    return hit[1]


def _fixed_bytes(spec: ExportSpec, covered: Sequence[int]) -> dict[str, int]:
    """The parts of the estimate that do not depend on which grids keep a cube."""
    estimates = [_grid_estimate(g, n) for g, n in zip(spec.grids, covered)]
    pixel = spec.lattice.pixel
    taps = sum(
        TAP_BYTES_PER_PIXEL * covered_pixels([slice_extent(g.frame)], pixel) for g in spec.grids
    )
    gather = GATHER_BYTES_PER_PIXEL * max(
        (covered_pixels([slice_extent(g.frame)], pixel) for g in spec.grids), default=0
    )
    cells = [g.frame.n_cells for g in spec.grids]
    band = BAND_BYTES_PER_CELL * sum(cells) + COMPOSE_BYTES_PER_PIXEL * spec.lattice.n_pixels
    # One grid is binned at a time and one is solved at a time: the largest counts.
    band += STREAM_BYTES_PER_CELL * max(cells, default=0)
    solve = 0
    if not spec.coverage:
        curving = [g.frame.n_cells for g in spec.grids if g.finish.method == "min_curvature"]
        solve = SOLVE_BYTES_PER_CELL * max(curving, default=0)
    return {
        "lines": sum(e.lines_bytes for e in estimates),
        "weights": sum(e.weights_bytes for e in estimates),
        "taps": int(taps),
        "gather": int(gather),
        "band": int(band),
        "solve": int(solve),
    }


def _residencies(spec: ExportSpec, covered: Sequence[int]) -> dict[str, str]:
    """Each grid's `"resident"` or `"streaming"`, by `choose_residency`.

    Grid by grid, in order, on that grid's own estimate. The budget a cube is
    judged against is what the export has left: the cap less everything that is
    held whatever is chosen, and the cubes already kept, so ten grids that each
    fit alone are not all resident at once.
    """
    fixed = _fixed_bytes(spec, covered)
    left = EXPORT_BUDGET_BYTES - sum(v for k, v in fixed.items() if k != "lines")
    out: dict[str, str] = {}
    for grid, n_covered in zip(spec.grids, covered):
        est = _grid_estimate(grid, n_covered)
        cube = MemoryEstimate(lines_bytes=0, cube_bytes=est.cube_bytes)
        n_traces = sum(int(line.data.shape[1]) for line in grid.lines)
        mode = choose_residency(cube, n_traces, budget_bytes=max(0, left))
        out[grid.grid_id] = mode
        if mode == "resident":
            left -= est.cube_bytes
    return out


def estimate_export(spec: ExportSpec, cache: CoveredCache | None = None) -> ExportEstimate:
    """The memory `run_export` holds and the file it feeds, before anything runs.

    Through `estimate_memory` and `covered_cells` for the cubes and the fill
    weights, `TAP_BYTES_PER_PIXEL` per covered output pixel for the taps, and
    one band's accumulators. A grid keeps a cube only where `choose_residency`
    says so (`_residencies`); the rest stream. `cache` memoises the covered-cell counts
    across calls (`CoveredCache`); None counts afresh.
    """
    covered = [_covered(g, cache) for g in spec.grids]
    parts = _fixed_bytes(spec, covered)
    modes = _residencies(spec, covered)
    parts["cubes"] = sum(
        _grid_estimate(g, n).cube_bytes
        for g, n in zip(spec.grids, covered)
        if modes[g.grid_id] == "resident"
    )
    held = sum(v for k, v in parts.items() if k != "lines")
    file_bytes = int(spec.lattice.n_pixels * 4 * len(spec.windows) * OVERVIEW_FACTOR)
    return ExportEstimate(held_bytes=int(held), file_bytes=file_bytes, per_band=parts)


# ---- the taps ---------------------------------------------------------------
def _window_of(grid: ExportGrid, lattice: SiteLattice) -> tuple[int, int, int, int] | None:
    """The lattice rows and columns `(row0, row1, col0, col1)` that may hold `grid`'s frame.

    Where the frame shares the output CRS this is `SiteEngine._gather`'s window:
    the frame's extent, plus one pixel. For a grid in another CRS only the
    inverse transform is known, so a coarse probe of the lattice finds where it
    lands: the probe points within a hop of the frame's extent, and the blocks
    between them. Either way `footprint` then tightens it to the pixels inside.
    """
    p = lattice.pixel
    xmin, ymin, xmax, ymax = slice_extent(grid.frame)
    if grid.world_to_frame is None:
        col0 = max(0, math.floor((xmin - lattice.x0) / p) - 1)
        col1 = min(lattice.width, math.ceil((xmax - lattice.x0) / p) + 1)
        row0 = max(0, math.floor((lattice.y1 - ymax) / p) - 1)
        row1 = min(lattice.height, math.ceil((lattice.y1 - ymin) / p) + 1)
    else:
        step = max(1, math.ceil(max(lattice.width, lattice.height) / _PROBE_POINTS))
        cols = np.unique(np.append(np.arange(0, lattice.width, step), lattice.width - 1))
        rows = np.unique(np.append(np.arange(0, lattice.height, step), lattice.height - 1))
        xs = lattice.x0 + (cols.astype(float) + 0.5) * p
        ys = lattice.y1 - (rows.astype(float) + 0.5) * p
        grid_x, grid_y = np.meshgrid(xs, ys)
        probe = np.column_stack([grid_x.ravel(), grid_y.ravel()])
        moved = np.asarray(grid.world_to_frame(probe), dtype=float).reshape(rows.size, cols.size, 2)

        def hop(values: np.ndarray) -> float:
            gaps = np.concatenate([np.abs(np.diff(values, axis=a)).ravel() for a in (0, 1)])
            gaps = gaps[np.isfinite(gaps)]
            return float(gaps.max()) if gaps.size else 0.0

        hx, hy = hop(moved[..., 0]), hop(moved[..., 1])
        near = (
            (moved[..., 0] >= xmin - hx)
            & (moved[..., 0] <= xmax + hx)
            & (moved[..., 1] >= ymin - hy)
            & (moved[..., 1] <= ymax + hy)
        )
        if not near.any():
            return None
        near_rows, near_cols = np.nonzero(near)
        row0 = int(rows[max(0, int(near_rows.min()) - 1)])
        row1 = int(rows[min(rows.size - 1, int(near_rows.max()) + 1)]) + 1
        col0 = int(cols[max(0, int(near_cols.min()) - 1)])
        col1 = int(cols[min(cols.size - 1, int(near_cols.max()) + 1)]) + 1
    if col1 > col0 and row1 > row0:
        return row0, row1, col0, col1
    return None


def _gather(grid: ExportGrid, lattice: SiteLattice) -> Footprint:
    """`grid`'s bilinear taps under each lattice pixel, kept to its own window.

    `SiteEngine._gather`, rebuilt from core calls and with no shared cache:
    only the pixels in the frame's window are looked up, through
    `world_to_frame` for a frame in another CRS, and `footprint` keeps the
    tight window around those inside the frame.
    """
    window = _window_of(grid, lattice)
    if window is None:
        return footprint(bilinear_taps(grid.frame, np.empty((0, 2))), 0, 0)
    row0, row1, col0, col1 = window
    p = lattice.pixel
    # The same centres as `SiteLattice.pixel_centres`, restricted.
    xs = lattice.x0 + (np.arange(col0, col1).astype(float) + 0.5) * p
    ys = lattice.y1 - (np.arange(row0, row1).astype(float) + 0.5) * p
    grid_x, grid_y = np.meshgrid(xs, ys)
    centres = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    if grid.world_to_frame is not None:
        centres = np.asarray(grid.world_to_frame(centres), dtype=float)
    taps = bilinear_taps(grid.frame, centres)
    return footprint(taps, row1 - row0, col1 - col0, row0, col0)


# ---- one grid's state across the bands ---------------------------------------
class _GridState:
    """What one grid keeps between bands: its plans, cube, taps and fill."""

    def __init__(self, grid: ExportGrid, mode: str) -> None:
        self.grid = grid
        self.plans = [plan_line(line, grid.frame, grid.z) for line in grid.lines]
        self.cube: SliceCube | None = None
        if mode == "resident":
            self.cube = build_cube(
                grid.lines,
                self.plans,
                grid.frame,
                grid.z,
                Provenance(
                    line_keys=tuple(line.key for line in grid.lines),
                    preset_name="",
                    steps=(),
                    transform="",
                    velocity=None,
                    built_utc="",
                    core_version="",
                ),
            )
        self.footprint: Footprint | None = None
        self.fill: SliceFill | CurvaturePlan | None = None

    def bin(self, k0: int, k1: int) -> tuple[np.ndarray, np.ndarray]:
        """The window's values and coverage, `(ny, nx)`, NaN where uncovered."""
        if self.cube is not None:
            return self.cube.slice_levels(k0, k1), self.cube.coverage()
        grid = self.grid
        return stream_slice(grid.lines, self.plans, grid.frame, grid.z, k0, k1)

    def finish(
        self, values: np.ndarray, coverage: np.ndarray, should_stop: Callable[[], bool]
    ) -> np.ndarray:
        """`values` interpolated into the blanks and smoothed, as `SliceEngine.finish`
        does it: the fill is planned on first use and kept for every later band."""
        grid, settings = self.grid, self.grid.finish
        cell = grid.frame.cell
        if self.fill is None:
            self.fill = plan_fill(
                coverage > 0, cell, settings.method, settings.max_distance_m,
                settings.search_radius_m,
            )  # fmt: skip
        if isinstance(self.fill, CurvaturePlan):
            try:
                solved, _ = self.fill.solve(values, should_stop)
            except SolveStopped:
                raise ExportCancelled() from None
            return smooth(solved, cell, settings.smooth_x_m, settings.smooth_y_m)
        return finish_slice(values, self.fill, cell, settings)


def _check(should_stop: Callable[[], bool]) -> None:
    if should_stop():
        raise ExportCancelled()


def _seams(spec: ExportSpec, states: dict[str, _GridState]) -> tuple[Seam, ...]:
    """Seams between the grids at the export frames, found once (`SiteEngine._site_seams`):
    coverage does not depend on the window, so one level's gives it."""
    frames = {g.grid_id: g.frame for g in spec.grids}
    coverages = {g.grid_id: states[g.grid_id].bin(0, 1)[1] for g in spec.grids}
    spacings = {g.grid_id: g.spacing_m for g in spec.grids}
    return find_seams(frames, coverages, spacings)


def run_export(
    spec: ExportSpec,
    *,
    should_stop: Callable[[], bool],
    progress: Callable[[int, int, str], None],
) -> Iterator[ExportBand]:
    """The bands of `spec`, one at a time, each composed on `spec.lattice`.

    The live Whole-site composition (`SiteEngine.slice_at`) at the export's own
    cell, rebuilt from `nsgeo.slices` alone so it can run on a worker thread:
    no live engine, no session, no shared cache.

    First, once: each grid's plans, its cube where `choose_residency` keeps
    one, its taps, and for edge match the seams at the export frames. Then
    band by band: every grid's window on its own axis (absent where its axis
    misses the band), each present grid binned, `normalise` measured on the
    BINNED values at this cell (never carried over from a live view), then each
    grid finished and the grids composed. Coverage mode writes the counts and
    normalises nothing.

    `should_stop` is asked between grids and inside a minimum-curvature solve;
    True raises `ExportCancelled`. `progress(band_index, n_bands, grid_id)`, the
    band counted from 0, is called before each present grid is finished.
    """
    covered = [_covered(g) for g in spec.grids]
    modes = _residencies(spec, covered)
    states: dict[str, _GridState] = {}
    for grid in spec.grids:
        _check(should_stop)
        state = _GridState(grid, modes[grid.grid_id])
        state.footprint = _gather(grid, spec.lattice)
        states[grid.grid_id] = state
    seams: tuple[Seam, ...] = ()
    if spec.method == "edge" and not spec.coverage:
        _check(should_stop)
        seams = _seams(spec, states)
    gains = {g.grid_id: g.gain for g in spec.grids}
    cell = spec.grids[0].frame.cell if spec.grids else spec.lattice.pixel
    per_pixel = max(1, round(spec.lattice.pixel / cell))
    n_bands = len(spec.windows)
    for band, (top_ns, thickness_ns) in enumerate(spec.windows):
        binned: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for grid in spec.grids:
            window = window_on(grid.z, top_ns, thickness_ns)
            if window is not None:
                _check(should_stop)
                binned[grid.grid_id] = states[grid.grid_id].bin(window.k0, window.k1)
        factors: dict[str, tuple[float, float]]
        if spec.coverage:
            factors = dict.fromkeys(binned, (1.0, 0.0))
        else:
            factors = normalise(spec.method, binned, seams, gains)
        shown: dict[str, np.ndarray] = {}
        for grid_id in list(binned):
            _check(should_stop)
            progress(band, n_bands, grid_id)
            values, cov = binned.pop(grid_id)
            if spec.coverage:
                shown[grid_id] = np.where(cov > 0, cov, np.nan).astype(np.float32)
            else:
                a, b = factors[grid_id]
                shown[grid_id] = a * states[grid_id].finish(values, cov, should_stop) + b
        layers = []
        for grid in spec.grids:
            where = states[grid.grid_id].footprint
            if grid.grid_id in shown and where is not None:
                layers.append((where, shown[grid.grid_id]))
        array = compose_footprints(
            spec.lattice, layers, counts=spec.coverage, cells_per_pixel=per_pixel
        )
        yield ExportBand(array=array, factors=factors)
