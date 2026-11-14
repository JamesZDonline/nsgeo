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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from nsgeo.geometry import END_LIMIT_M, Bridge, ToXY, track_from_log
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
ALREADY_IN_SITE = "already in the site (remove it first to place it by GPS)"


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


def shifted_lines(rows: Sequence[GpsRow], metres: float) -> list[Line]:
    """The ready rows' lines with `travel_shift` set to `metres`."""
    out: list[Line] = []
    for row in rows:
        if row.line is None:
            continue
        placement = dataclasses.replace(row.line.placement, travel_shift=float(metres))  # type: ignore[type-var]
        out.append(dataclasses.replace(row.line, placement=placement))
    return out


def import_messages(rows: Sequence[GpsRow], imported: int) -> list[str]:
    """What the plugin says after an import: the count, then every bridge,
    then every end run over END_LIMIT_M, then every refused file."""
    ready = [r for r in rows if r.refusal is None]
    out = [f"imported {imported} GPS line(s)"]
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
    for r in rows:
        if r.refusal is not None:
            out.append(f"not imported: {r.path.name} ({r.refusal})")
    return out
