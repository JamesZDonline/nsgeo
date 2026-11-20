"""Planning an Import GPS lines table (M17a, #134). No Qt and no qgis.

Each DZT with a DZG beside it becomes one row: a line placed along the RTK
track, at travel_shift 0, with the counts the dialog shows, or a refusal in
the dialog's own words. The shift is applied at Import, to every ready row
(`shifted_lines`). The projection, the "already in the site" test and the
"can this CRS place that spot" test are injected, so all of it runs in the
Qt-free tier.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from nsgeo.geometry import (
    ALONG_DEG,
    END_LIMIT_M,
    Bridge,
    Grid,
    ToXY,
    metres_outside,
    track_from_log,
)
from nsgeo.io import (
    RTK_FIXED,
    DzgError,
    DzgLog,
    DztError,
    dzg_for,
    read_dzg,
    read_header,
    trace_count,
)
from nsgeo.model import Line

NO_DZG = "no DZG beside it"
ALREADY_IN_SITE = "already in the site"
OUTSIDE = "outside {gid}"
#: A stretch outside the grid shorter than this is not worth a line (metres).
OUTSIDE_NOTE_M = 0.05


@dataclass(frozen=True)
class GpsImportResult:
    """What the GPS page did at Import, for the hand-on to the Grid page: the
    grid, every path the page held (its order), each imported line's
    `trace_coords`, and the refused paths that are neither already in the site
    nor outside the grid (in file order)."""

    grid_id: str
    order: list[Path]
    placed: dict[Path, np.ndarray]
    leftovers: list[Path]


@dataclass(frozen=True)
class GpsRow:
    path: Path
    line: Line | None  # placed at travel_shift 0; None when refused
    n_traces: int | None
    n_fixes: int
    n_fixed: int
    bridges: tuple[Bridge, ...]
    end_runs: tuple[float, float]
    refusal: str | None  # None when ready

    @property
    def without_rtk_m(self) -> float:
        return sum(b.metres for b in self.bridges)


def _first_fixed(log: DzgLog) -> tuple[float, float] | None:
    for f in log.fixes:
        if f.quality == RTK_FIXED and math.isfinite(f.lat) and math.isfinite(f.lon):
            return f.lon, f.lat
    return None


def first_fixed_lonlat(path: Path) -> tuple[float, float] | None:
    """(lon, lat) of the first RTK fix in the DZG beside the DZT `path`, or
    None when there is no DZG, it cannot be read, or it has no RTK fix."""
    try:
        dzg = dzg_for(path)
        if dzg is None:
            return None
        return _first_fixed(read_dzg(dzg))
    except (DzgError, OSError):
        return None


def _refused(
    path: Path,
    reason: str,
    n_traces: int | None = None,
    log: DzgLog | None = None,
) -> GpsRow:
    return GpsRow(
        path=path,
        line=None,
        n_traces=n_traces,
        n_fixes=0 if log is None else len(log.fixes),
        n_fixed=0 if log is None else log.n_fixed,
        bridges=(),
        end_runs=(0.0, 0.0),
        refusal=reason,
    )


def _plan_one(
    path: Path,
    to_xy: ToXY,
    crs: str,
    taken: Callable[[Path], bool],
    usable: Callable[[float, float], bool],
) -> GpsRow:
    try:
        header = read_header(path)
        n_traces = trace_count(path, header)
    except (DztError, OSError) as exc:
        return _refused(path, f"could not read it: {exc}")
    dzg = dzg_for(path)
    if dzg is None:
        return _refused(path, NO_DZG, n_traces)
    try:
        log = read_dzg(dzg, n_traces)
    except (DzgError, OSError) as exc:
        return _refused(path, f"could not read it: {exc}", n_traces)
    # Where the line starts decides whether `crs` can place it, asked before
    # anything is projected: a transform that fails point by point would
    # otherwise make the anchors vanish and the row read "no RTK-fixed position".
    first = _first_fixed(log)
    if first is not None and not usable(first[0], first[1]):
        return _refused(path, f"outside what {crs} can place", n_traces, log)
    try:
        placement = track_from_log(log, to_xy, crs, label=path.stem)
    except ValueError as exc:
        return _refused(path, str(exc), n_traces, log)
    bridges = placement.bridges()
    end_runs = placement.end_runs(n_traces, header)
    if taken(path):
        # Planned, then refused: the row still shows its counts and ends.
        return GpsRow(
            path=path,
            line=None,
            n_traces=n_traces,
            n_fixes=len(log.fixes),
            n_fixed=log.n_fixed,
            bridges=bridges,
            end_runs=end_runs,
            refusal=ALREADY_IN_SITE,
        )
    return GpsRow(
        path=path,
        line=Line.open(path, placement),
        n_traces=n_traces,
        n_fixes=len(log.fixes),
        n_fixed=log.n_fixed,
        bridges=bridges,
        end_runs=end_runs,
        refusal=None,
    )


def plan_gps_rows(
    paths: Sequence[Path],
    to_xy: ToXY,
    crs: str,
    taken: Callable[[Path], bool],
    usable: Callable[[float, float], bool],
) -> list[GpsRow]:
    """One row per path, in the order given. `taken(path)` says the file is
    already a line of the site; `usable(lon, lat)` says `crs` can place that
    spot (asked at each row's first RTK fix)."""
    return [_plan_one(Path(p), to_xy, crs, taken, usable) for p in paths]


def shifted_lines(rows: Sequence[GpsRow], metres: float, grid_id: str | None = None) -> list[Line]:
    """The ready rows' lines with `travel_shift` set to `metres`, and, when
    `grid_id` is given, `grid_id` set on each placement."""
    out: list[Line] = []
    for row in rows:
        if row.line is None:
            continue
        changes: dict[str, object] = {"travel_shift": float(metres)}
        if grid_id is not None:
            changes["grid_id"] = grid_id
        placement = dataclasses.replace(row.line.placement, **changes)  # type: ignore[type-var]
        out.append(dataclasses.replace(row.line, placement=placement))
    return out


def with_grid(
    rows: Sequence[GpsRow],
    grid: Grid,
    measured: tuple[Mapping[Path, float], Mapping[Path, bool]] | None = None,
) -> tuple[list[GpsRow], dict[Path, float]]:
    """Rows against an existing grid: a ready line with no trace inside it
    becomes refused `OUTSIDE`; the dict holds the metres outside for every
    ready row that stays. `measured` (metres outside, any trace inside; both by
    path) reuses what the caller already computed with `metres_outside`."""
    out: list[GpsRow] = []
    outside: dict[Path, float] = {}
    for row in rows:
        if row.line is None or row.refusal is not None:
            out.append(row)
            continue
        if measured is not None and row.path in measured[0]:
            metres, any_inside = measured[0][row.path], measured[1][row.path]
        else:
            metres, any_inside = metres_outside(grid, row.line.trace_coords({}))
        if not any_inside:
            out.append(dataclasses.replace(row, line=None, refusal=OUTSIDE.format(gid=grid.id)))
        else:
            out.append(row)
            outside[row.path] = metres
    return out, outside


def import_messages(
    rows: Sequence[GpsRow],
    imported: int,
    *,
    into: str,
    gid: str,
    outside: Mapping[Path, float] = {},  # noqa: B006 -- read only
    handed_on: Collection[Path] = (),
) -> list[str]:
    """What the plugin says after an import: the count and where it went, then
    every bridge, then every end run over END_LIMIT_M, then each line's metres
    outside its grid, then every refused file that is not handed on.
    `into` is "new grid G (w × l m, spacing s m)" or just the grid's id; `gid`
    is the grid's id, named in the outside warnings."""
    ready = [r for r in rows if r.refusal is None]
    out = [f"imported {imported} GPS line(s) into {into}"]
    for r in ready:
        for b in r.bridges:
            out.append(
                f"{r.path.name}: {b.metres:.1f} m without an RTK fix, "
                f"traces {b.first_trace}–{b.last_trace}"
            )
    for r in ready:
        start, end = r.end_runs
        if start > END_LIMIT_M:
            out.append(f"{r.path.name}: its start runs {start:.1f} m before the first RTK fix")
        if end > END_LIMIT_M:
            out.append(f"{r.path.name}: its end runs {end:.1f} m past the last RTK fix")
    for r in ready:
        metres = outside.get(r.path, 0.0)
        if metres >= OUTSIDE_NOTE_M:
            out.append(
                f"{r.path.name}: {metres:.1f} m lies outside {gid} and is left out of its slices"
            )
    for r in rows:
        if r.refusal is not None and r.path not in handed_on:
            out.append(f"not imported: {r.path.name} ({r.refusal})")
    return out


def count_with_gps(paths: Sequence[Path]) -> int:
    """How many of the DZT files in `paths` have a DZG beside them that holds
    at least one RTK fix with a position (the Add data dialog's GPS note)."""
    return sum(1 for p in paths if first_fixed_lonlat(p) is not None)


@dataclass(frozen=True)
class TapeGuess:
    """A leftover file's offset and direction on one grid axis, guessed from the
    GPS lines either side of it in file order, and the note that says how."""

    axis: str
    offset: float
    direction: int
    note: str


@dataclass(frozen=True)
class _Placed:
    axis: str | None  # the grid axis the line runs within ALONG_DEG of, if any
    offset: float  # mean local cross coordinate
    direction: int  # sign of the local along change


def _placed_line(coords: np.ndarray, grid: Grid) -> _Placed:
    local = grid.to_local(np.asarray(coords, dtype=float))
    step = local[-1] - local[0]
    dev_y = math.degrees(math.atan2(abs(step[0]), abs(step[1])))
    if dev_y <= ALONG_DEG:
        axis: str | None = "y"
    elif 90.0 - dev_y <= ALONG_DEG:
        axis = "x"
    else:
        axis = None
    if axis == "x":
        return _Placed(axis, float(local[:, 1].mean()), 1 if step[0] >= 0 else -1)
    return _Placed(axis, float(local[:, 0].mean()), 1 if step[1] >= 0 else -1)


def _spacings(k: int) -> str:
    return f"{k} spacing" if k == 1 else f"{k} spacings"


def guess_tape_rows(
    order: Sequence[Path], placed: Mapping[Path, np.ndarray], grid: Grid
) -> dict[Path, TapeGuess]:
    """A tape guess for each path in `order` that is not in `placed`.

    The offset is interpolated by file position between the nearest placed
    lines before and after; at an end, one `grid.default_spacing` per file
    further on, away from the placed line before it (or `+` with only one
    placed line; mirrored at the start). The direction is opposite the line
    before it in file order, placed or guessed, or opposite the line after it
    for the first file. A file is left out unless every neighbour used runs
    within ALONG_DEG of the same grid axis."""
    paths = list(order)
    info = {i: _placed_line(placed[p], grid) for i, p in enumerate(paths) if p in placed}
    idx = sorted(info)
    if not idx:
        return {}
    spacing = grid.default_spacing
    # offsets and the neighbours each leftover leans on
    guesses: dict[int, tuple[str, float, str]] = {}
    for i in range(len(paths)):
        if i in info:
            continue
        before = [j for j in idx if j < i]
        after = [j for j in idx if j > i]
        if before and after:
            a, b = before[-1], after[0]
            used = [info[a], info[b]]
            t = (i - a) / (b - a)
            offset = info[a].offset + (info[b].offset - info[a].offset) * t
            note = f"between {paths[a].stem} and {paths[b].stem}"
        elif before:
            a = before[-1]
            used = [info[a]]
            sign = 1.0
            if len(before) > 1:
                used.append(info[before[-2]])
                d = info[a].offset - info[before[-2]].offset
                sign = -1.0 if d < 0 else 1.0
            offset = info[a].offset + sign * spacing * (i - a)
            note = f"{_spacings(i - a)} after {paths[a].stem}"
        else:
            b = after[0]
            used = [info[b]]
            sign = -1.0
            if len(after) > 1:
                used.append(info[after[1]])
                d = info[after[1]].offset - info[b].offset
                sign = 1.0 if d < 0 else -1.0
            offset = info[b].offset + sign * spacing * (b - i)
            note = f"{_spacings(b - i)} before {paths[b].stem}"
        axes = {u.axis for u in used}
        if len(axes) != 1 or None in axes:
            continue
        guesses[i] = (axes.pop() or "y", offset, note)
    # directions: zigzag from the placed lines, forwards then backwards
    direction: dict[int, int] = {i: v.direction for i, v in info.items()}
    for i in range(len(paths)):
        if i in direction:
            continue
        if i - 1 in direction and i > idx[0]:
            direction[i] = -direction[i - 1]
    for i in range(idx[0] - 1, -1, -1):
        direction[i] = -direction[i + 1]
    out: dict[Path, TapeGuess] = {}
    for i, (axis, offset, note) in guesses.items():
        # a neighbour before it that is a leftover without a guess breaks the chain
        if i > idx[0] and i - 1 not in info and i - 1 not in guesses:
            continue
        out[paths[i]] = TapeGuess(axis, offset, direction[i], note)
    return out
