"""Measure the destagger a grid's lines share, from the lines themselves.

Stagger is a position error that alternates from line to line: lines walked one
way sit a little behind where they were recorded, lines walked back a little
ahead, so anything sharp zig-zags. A line compared with its neighbours walked
the other way (the mean of the two beside it) shows that disagreement; half of
it, with its sign changed, is the destagger every line needs. Because the
comparison is against the neighbours' mean, a feature running across the lines
at an angle, or a baseline that is not square, cancels and is never "corrected".

Each axis of a grid is measured as its own set of lines (design C11). The
destagger already set on a line is ignored (C1): positions are computed with
`travel_shift = 0`, so the result is a full value, and pressing Measure twice
gives the same numbers.

A grid value that cannot be measured says why instead of guessing (C10), and a
line that cannot be measured keeps the reason that stopped it. Lines clearly off
on their own then get their own value, and lines that change partway along or
match nothing are named and left at the grid value (`per_line`, design 7.4).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable

import numpy as np

from nsgeo.destagger.per_line import per_line_values
from nsgeo.destagger.prepare import EnvelopeBins
from nsgeo.destagger.profiles import (
    END_TRIM_M,
    PAIR_LAG_FACTOR,
    STEP_M,
    along_axis,
    bin_medians,
    grid_peak,
    line_curves,
    neighbour_indices,
    pair_curves,
    search_range_m,
    time_window,
)
from nsgeo.geometry import GridPlacement
from nsgeo.io.dzt import DztHeader

__all__ = [
    "AxisResult",
    "DestaggerResult",
    "LineResult",
    "LineStatus",
    "MeasureLine",
    "MeasureStopped",
    "measure_destagger",
    "one_way_result",
]

BOOTSTRAP = 300
MIN_USABLE_M = 2.0
MIN_LINES = 4
TIME_TOLERANCE = 1e-6

NO_DISTANCE = "no distance axis (recorded on a timer)"
TOO_SHORT = "too short to measure"
TIME_SETTINGS = "recorded with different time settings from the rest of the grid"
NO_NEIGHBOUR = "no line walked the other way beside it"
ONE_WAY = "every line was walked the same way, so there is no stagger to measure"
TOO_FEW = "too few lines walked in opposite directions to measure"
UNCLEAR = "no clear match between lines walked in opposite directions"
AXIS_FAILED = "its grid's value could not be measured"
NO_LINES = "none of the grid's lines could be measured"


class LineStatus(Enum):
    GRID = "grid value"
    OWN = "own value"
    CHANGES = "changes partway along"
    NO_MATCH = "no clear match"
    NOT_MEASURED = "not measured"


@dataclass(frozen=True)
class MeasureLine:
    key: str
    bins: EnvelopeBins
    placement: GridPlacement  # as the table shows it now; travel_shift is ignored (C1)
    header: DztHeader  # positions: replace(placement, travel_shift=0.0).distance_along(...)


@dataclass(frozen=True)
class LineResult:
    key: str
    axis: str
    status: LineStatus
    destagger: float | None  # None exactly when NOT_MEASURED
    reason: str = ""  # set for NOT_MEASURED


@dataclass(frozen=True)
class AxisResult:
    axis: str
    destagger: float | None  # None when the grid value could not be measured (C10)
    spread_m: float  # half the width of the 95% bootstrap interval; nan when destagger is None
    lines_used: int  # lines with an opposite-direction neighbour that were measured
    reason: str = ""  # ONE_WAY, TOO_FEW or UNCLEAR when destagger is None


@dataclass(frozen=True)
class DestaggerResult:
    axes: dict[str, AxisResult]  # one per axis present among the lines
    lines: dict[str, LineResult]  # one per input line


class MeasureStopped(Exception):
    """`should_stop` returned True."""


def measure_destagger(
    lines: Sequence[MeasureLine], should_stop: Callable[[], bool] = lambda: False
) -> DestaggerResult:
    """The grid value for each axis among `lines`, and a result for every line."""
    axes: dict[str, AxisResult] = {}
    results: dict[str, LineResult] = {}
    for axis in sorted({ln.placement.axis for ln in lines}):
        group = [ln for ln in lines if ln.placement.axis == axis]
        axes[axis], axis_lines = _measure_axis(axis, group, should_stop)
        results.update(axis_lines)
    return DestaggerResult(axes, {ln.key: results[ln.key] for ln in lines})


def one_way_result(placements: Mapping[str, GridPlacement]) -> DestaggerResult | None:
    """What `measure_destagger` gives when no axis among the lines was walked both
    ways, worked out from the placements alone, so no line need be read; None when
    some axis was, and the lines must be read and measured.

    With every line on an axis walked the same way, no line has one walked the other
    way beside it: each is NO_NEIGHBOUR and the axis ONE_WAY (TOO_FEW for a lone line),
    whatever its data. Reading the files could only name lines that are also too
    short, unreadable or recorded differently, on a grid where nothing can be measured.
    """
    axes: dict[str, AxisResult] = {}
    results: dict[str, LineResult] = {}
    for axis in sorted({p.axis for p in placements.values()}):
        group = [key for key, p in placements.items() if p.axis == axis]
        if len({placements[key].direction for key in group}) > 1:
            return None
        reason = ONE_WAY if len(group) >= 2 else TOO_FEW
        axes[axis] = AxisResult(axis, None, math.nan, 0, reason)
        for key in group:
            results[key] = LineResult(key, axis, LineStatus.NOT_MEASURED, None, NO_NEIGHBOUR)
    return DestaggerResult(axes, {key: results[key] for key in placements})


def _check(should_stop: Callable[[], bool]) -> None:
    if should_stop():
        raise MeasureStopped()


def _common_time_settings(lines: Sequence[MeasureLine]) -> tuple[float, float]:
    """The most common (dt_ns, t0_ns) among `lines`; the first seen wins a tie."""

    def same(a: MeasureLine, b: MeasureLine) -> bool:
        return (
            abs(a.bins.dt_ns - b.bins.dt_ns) <= TIME_TOLERANCE
            and abs(a.bins.t0_ns - b.bins.t0_ns) <= TIME_TOLERANCE
        )

    best = max(lines, key=lambda a: sum(same(a, b) for b in lines))
    return best.bins.dt_ns, best.bins.t0_ns


def _measure_axis(
    axis: str, group: Sequence[MeasureLine], should_stop: Callable[[], bool]
) -> tuple[AxisResult, dict[str, LineResult]]:
    out: dict[str, LineResult] = {}
    # The same lines in any order give the same numbers: the bootstrap resamples
    # curve rows, so the rows are always in offset order.
    group = sorted(group, key=lambda ln: (ln.placement.offset, ln.key))

    def exclude(line: MeasureLine, reason: str) -> None:
        out[line.key] = LineResult(line.key, axis, LineStatus.NOT_MEASURED, None, reason)

    # Exclusions, in order: no distance axis, other time settings, too short, no neighbour.
    remaining = []
    for line in group:
        _check(should_stop)
        if line.header.traces_per_metre > 0:
            remaining.append(line)
        else:
            exclude(line, NO_DISTANCE)
    if remaining:
        dt, t0 = _common_time_settings(remaining)
        kept = []
        for line in remaining:
            _check(should_stop)
            if (
                abs(line.bins.dt_ns - dt) <= TIME_TOLERANCE
                and abs(line.bins.t0_ns - t0) <= TIME_TOLERANCE
            ):
                kept.append(line)
            else:
                exclude(line, TIME_SETTINGS)
        remaining = kept
    alongs: dict[str, np.ndarray] = {}
    kept = []
    for line in remaining:
        _check(should_stop)
        along = replace(line.placement, travel_shift=0.0).distance_along(
            line.bins.data.shape[1], line.header
        )
        if float(along.max() - along.min()) - 2 * END_TRIM_M < MIN_USABLE_M:
            exclude(line, TOO_SHORT)
        else:
            alongs[line.key] = along
            kept.append(line)
    remaining = kept

    by_offset = sorted(range(len(remaining)), key=lambda i: remaining[i].placement.offset)
    directions = [ln.placement.direction for ln in remaining]
    neighbours = neighbour_indices(by_offset, directions)
    for i, line in enumerate(remaining):
        _check(should_stop)
        if i not in neighbours:
            exclude(line, NO_NEIGHBOUR)
    measured = [remaining[i] for i in sorted(neighbours)]

    def failed(reason: str) -> tuple[AxisResult, dict[str, LineResult]]:
        for line in measured:
            exclude(line, AXIS_FAILED)
        return AxisResult(axis, None, math.nan, len(measured), reason), out

    if not remaining:  # every line was excluded above, each with its own reason
        return failed(NO_LINES)
    if not measured:
        return failed(ONE_WAY if len(remaining) >= 2 else TOO_FEW)
    if len(measured) < MIN_LINES:
        return failed(TOO_FEW)

    # Re-index over the measured lines only (a line with no neighbour is nobody's neighbour).
    local_dirs = [ln.placement.direction for ln in measured]
    local_order = sorted(range(len(measured)), key=lambda j: measured[j].placement.offset)
    local_nb = neighbour_indices(local_order, local_dirs)

    n_bins = min(ln.bins.data.shape[0] for ln in measured)
    datas = [ln.bins.data[:n_bins] for ln in measured]
    cut = [replace(ln.bins, data=d) for ln, d in zip(measured, datas)]
    medians = bin_medians(cut)
    window = time_window(cut[0].t_ns, medians)
    along_list = [alongs[ln.key] for ln in measured]
    axis_m = along_axis(along_list)
    longest = max(float(a.max() - a.min()) for a in along_list)
    max_lag = int(round(search_range_m(longest) / STEP_M))

    def check() -> None:
        _check(should_stop)

    pairs = pair_curves(
        datas,
        along_list,
        axis_m,
        medians,
        window,
        local_order,
        local_dirs,
        PAIR_LAG_FACTOR * max_lag,
        check,
    )
    raw, normalised = line_curves(pairs, local_nb, local_dirs, max_lag, check)
    found = grid_peak(raw, normalised, BOOTSTRAP)
    if not found.clear:
        return failed(UNCLEAR)
    grid = float(found.destagger)
    verdicts = per_line_values(pairs, local_order, local_dirs, local_nb, grid, max_lag, check)
    for j, line in enumerate(measured):
        if j in verdicts.own:
            out[line.key] = LineResult(line.key, axis, LineStatus.OWN, grid + verdicts.own[j])
        elif j in verdicts.changes:
            out[line.key] = LineResult(line.key, axis, LineStatus.CHANGES, grid)
        elif j in verdicts.no_match:
            out[line.key] = LineResult(line.key, axis, LineStatus.NO_MATCH, grid)
        else:
            out[line.key] = LineResult(line.key, axis, LineStatus.GRID, grid)
    return AxisResult(axis, grid, float(found.spread_m), len(measured)), out
