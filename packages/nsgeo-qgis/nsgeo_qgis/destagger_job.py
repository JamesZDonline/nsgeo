"""The background half of Measure in Edit lines (#159).

`MeasureJob` is a `RefineJob` for `nsgeo_qgis.refine.Refiner`: it reads the
lines the dialog has not prepared yet, then measures them. It imports no Qt and
touches no session, site or widget: the dialog captures everything it needs
(paths, headers, placements) on the GUI thread when Measure is pressed.
`box_value` and `measure_summary` are the plain functions that turn the result
into the Destagger box and the status line.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from nsgeo.destagger import (
    AXIS_FAILED,
    NO_NEIGHBOUR,
    DestaggerResult,
    EnvelopeBins,
    LineStatus,
    MeasureLine,
    MeasureStopped,
    envelope_bins,
    measure_destagger,
)
from nsgeo.geometry import GridPlacement
from nsgeo.io import DztError, DztHeader, read_samples

#: Names listed per group in the summary before "and {n} more" (P12).
MAX_NAMES = 6


@dataclass(frozen=True)
class JobLine:
    key: str
    label: str
    path: Path
    header: DztHeader
    placement: GridPlacement  # LineEdit.placed(frames) at press time


class MeasureJob:
    def __init__(self, lines: Sequence[JobLine], cached: Mapping[str, EnvelopeBins]) -> None:
        self._lines = list(lines)
        self.prepared: dict[str, EnvelopeBins] = dict(cached)
        self.unreadable: dict[str, str] = {}
        self.result: DestaggerResult | None = None
        self.stopped = False
        todo = sum(1 for ln in self._lines if ln.key not in self.prepared)
        #: (lines read, lines to read); replaced whole by the worker, read by the GUI.
        self.progress: tuple[int, int] = (0, todo)

    def run(self, should_stop: Callable[[], bool]) -> None:
        todo = [ln for ln in self._lines if ln.key not in self.prepared]
        for i, line in enumerate(todo):
            if should_stop():
                self.stopped = True
                return
            try:
                # P4: the first channel, as the spike measured.
                samples = read_samples(line.path, line.header)[0]
                self.prepared[line.key] = envelope_bins(
                    samples, line.header.dt_ns, line.header.position_ns
                )
            except (OSError, DztError, ValueError) as exc:
                self.unreadable[line.key] = str(exc)
            self.progress = (i + 1, len(todo))
        measured = [
            MeasureLine(ln.key, self.prepared[ln.key], ln.placement, ln.header)
            for ln in self._lines
            if ln.key in self.prepared
        ]
        try:
            self.result = measure_destagger(measured, should_stop)
        except MeasureStopped:
            self.stopped = True


def box_value(result: DestaggerResult) -> float | None:
    """The grid value of the axis with more lines behind it among the axes that
    measured (C11, Ruling 14); None only when no axis measured."""
    measured = [a for a in result.axes.values() if a.destagger is not None]
    if not measured:
        return None
    return max(measured, key=lambda a: a.lines_used).destagger


def _names(items: Sequence[str], sep: str, limit: int | None) -> str:
    if limit is None:
        return sep.join(items)
    shown = list(items[:limit])
    if len(items) > limit:
        shown.append(f"and {len(items) - limit} more")
    return sep.join(shown)


def measure_summary(
    result: DestaggerResult,
    filled: Sequence[str],
    unreadable: Mapping[str, str],
    labels: Mapping[str, str],
    limit: int | None = MAX_NAMES,
) -> str:
    """The status line after a measure. The groups describe only `filled`, the
    rows that were selected (P6). Each group names at most `limit` lines (P12);
    `None` names them all, for the tooltip (Ruling 15)."""
    parts: list[str] = []
    axes = list(result.axes.values())
    one = len(axes) == 1
    if not axes:  # every file was unreadable, so there was nothing to measure
        parts.append("Could not measure: no line could be read. Nothing was changed.")
    for a in axes:
        if a.destagger is not None:
            numbers = f"{a.destagger:+.3f} m from {a.lines_used} lines (±{a.spread_m:.3f} m)."
            parts.append(f"Measured {numbers}" if one else f"Along {a.axis}: measured {numbers}")
        elif one:
            parts.append(f"Could not measure: {a.reason}. Nothing was changed.")
        else:
            parts.append(f"Along {a.axis}: could not measure ({a.reason}); nothing changed there.")
    # When every axis failed, the axis reasons already cover the lines that had no
    # neighbour or that went with their grid; the others are still named (Ruling 12).
    all_failed = bool(axes) and all(a.destagger is None for a in axes)
    covered = (NO_NEIGHBOUR, AXIS_FAILED) if all_failed else ()

    own: list[str] = []
    left: list[str] = []
    skipped: list[str] = []
    for key in filled:
        label = labels.get(key, key)
        line = result.lines.get(key)
        if line is None:
            if key in unreadable:
                skipped.append(f"{label} (could not be read: {unreadable[key]})")
        elif line.status is LineStatus.OWN and line.destagger is not None:
            own.append(f"{label} {line.destagger:+.3f}")
        elif line.status is LineStatus.CHANGES:
            left.append(f"{label} changes partway along")
        elif line.status is LineStatus.NO_MATCH:
            left.append(f"{label} has no clear match")
        elif line.status is LineStatus.NOT_MEASURED and line.reason not in covered:
            skipped.append(f"{label} ({line.reason})")
    if own:
        parts.append(f"Own values: {_names(own, ', ', limit)}.")
    if left:
        parts.append(f"Left at the grid value: {_names(left, '; ', limit)}.")
    if skipped:
        parts.append(f"Not measured, left as they were: {_names(skipped, '; ', limit)}.")
    return " ".join(parts)
