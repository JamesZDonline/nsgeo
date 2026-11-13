"""A line placed along the RTK GPS track logged beside its DZT (M17a, #134).

Only RTK-fixed fixes (quality 4) are anchors. Traces between two anchors sit on
the straight segment between them, evenly by trace number, so a dropout to
float or plain GPS is bridged, never trusted. Past the first and last anchor a
line runs on in a straight line at its heading, by the wheel's metres per
trace. `travel_shift` moves every trace forward along the walked path, as it
does for `GridPlacement` (#47).

The projection is injected: the core has no pyproj. `to_xy(lon, lat)` takes
degrees and returns metres in the placement's CRS.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np

from nsgeo.geometry.grid import Grid
from nsgeo.io.dzg import RTK_FIXED, DzgLog
from nsgeo.io.dzt import DztHeader

ToXY = Callable[[np.ndarray, np.ndarray], "tuple[np.ndarray, np.ndarray]"]
"""(lon, lat) in degrees -> (x, y) in metres."""

END_LIMIT_M: float = 2.0
"""A start or end run longer than this is flagged."""

HEADING_BASE_M: float = 1.0
"""An end's heading is taken from an anchor at least this far away (1 Hz jitter)."""


@dataclass(frozen=True)
class TrackFix:
    """One GGA fix of a line, placed. x and y are NaN for a fix with no position."""

    trace: int
    x: float
    y: float
    lat: float
    lon: float
    alt_m: float | None = None
    geoid_m: float | None = None
    quality: int = 4


@dataclass(frozen=True)
class Bridge:
    """A dropout: the anchors either side of one or more non-RTK fixes."""

    first_trace: int
    last_trace: int
    metres: float


def _is_anchor(fix: TrackFix) -> bool:
    return fix.quality == RTK_FIXED and math.isfinite(fix.x) and math.isfinite(fix.y)


@dataclass(frozen=True)
class TrackPlacement:
    """A line placed along its RTK GPS track.

    `fixes` are every fix of the log in trace order, whatever the quality: a
    non-RTK fix between two anchors is what marks a bridge. `travel_shift` is
    metres, positive moving every trace forward along the way the line was
    walked.
    """

    fixes: tuple[TrackFix, ...]
    crs: str
    grid_id: str | None = None
    label: str | None = None
    travel_shift: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "fixes", tuple(self.fixes))
        for a, b in zip(self.fixes, self.fixes[1:]):
            if not b.trace > a.trace:
                raise ValueError("trace numbers must rise along a GPS track")
        anchors = self.anchors()
        if not anchors:
            raise ValueError("no RTK-fixed position")
        if len(anchors) == 1:
            raise ValueError("only one RTK-fixed position")
        if all(math.hypot(a.x - anchors[0].x, a.y - anchors[0].y) < 1e-9 for a in anchors):
            raise ValueError("the RTK-fixed positions all lie at one point")
        if not math.isfinite(self.travel_shift):
            raise ValueError(f"travel_shift must be finite, got {self.travel_shift!r}")

    def anchors(self) -> tuple[TrackFix, ...]:
        """The RTK-fixed fixes with a position: the only ones traces are placed by."""
        return tuple(f for f in self.fixes if _is_anchor(f))

    def bridges(self) -> tuple[Bridge, ...]:
        """Each pair of consecutive anchors with a non-anchor fix between them."""
        out: list[Bridge] = []
        last: TrackFix | None = None
        gap = False
        for f in self.fixes:
            if _is_anchor(f):
                if last is not None and gap:
                    out.append(Bridge(last.trace, f.trace, math.hypot(f.x - last.x, f.y - last.y)))
                last, gap = f, False
            else:
                gap = True
        return tuple(out)

    # -- the run-on past each end ------------------------------------------------

    def _end_step(self, header: DztHeader, a: TrackFix, b: TrackFix) -> float:
        """Metres per trace beyond the end anchor `a`, whose neighbour anchor is `b`."""
        spm = header.traces_per_metre
        if spm > 0:
            return 1.0 / spm
        return math.hypot(b.x - a.x, b.y - a.y) / abs(b.trace - a.trace)

    def _heading(self, end: TrackFix, others: list[TrackFix]) -> np.ndarray:
        """Unit vector from `end` towards the nearest anchor at least HEADING_BASE_M
        away, else the farthest."""
        best: TrackFix | None = None
        best_d = -1.0
        for o in others:  # nearest to the end first
            d = math.hypot(o.x - end.x, o.y - end.y)
            if d >= HEADING_BASE_M:
                best, best_d = o, d
                break
            if d > best_d:
                best, best_d = o, d
        assert best is not None
        return np.array([best.x - end.x, best.y - end.y]) / best_d

    def _ends(self, header: DztHeader) -> tuple[tuple[TrackFix, np.ndarray, float], ...]:
        a = self.anchors()
        first_dir = self._heading(a[0], list(a[1:]))
        last_dir = self._heading(a[-1], list(reversed(a[:-1])))
        return (
            (a[0], first_dir, self._end_step(header, a[0], a[1])),
            (a[-1], last_dir, self._end_step(header, a[-1], a[-2])),
        )

    def positions(self, n_traces: int, header: DztHeader) -> np.ndarray:
        """(n_traces, 2) unshifted: on the anchor segments between anchors, and on
        straight runs at the heading beyond the first and last."""
        a = self.anchors()
        idx = np.arange(n_traces, dtype=float)
        traces = np.array([f.trace for f in a], dtype=float)
        xs = np.array([f.x for f in a])
        ys = np.array([f.y for f in a])
        pos = np.column_stack([np.interp(idx, traces, xs), np.interp(idx, traces, ys)])
        (first, first_dir, first_step), (last, last_dir, last_step) = self._ends(header)
        before = idx < first.trace
        if before.any():
            back = (first.trace - idx[before]) * first_step
            pos[before] = np.array([first.x, first.y]) - back[:, None] * first_dir
        after = idx > last.trace
        if after.any():
            fwd = (idx[after] - last.trace) * last_step
            pos[after] = np.array([last.x, last.y]) - fwd[:, None] * last_dir
        return pos

    def end_runs(self, n_traces: int, header: DztHeader) -> tuple[float, float]:
        """Metres placed before the first anchor and after the last."""
        (first, _, first_step), (last, _, last_step) = self._ends(header)
        start = max(first.trace, 0) * first_step
        end = max(n_traces - 1 - last.trace, 0) * last_step
        return start, end

    # -- the Placement protocol --------------------------------------------------

    def _path(self, n_traces: int, header: DztHeader) -> tuple[np.ndarray, np.ndarray]:
        pos = self.positions(n_traces, header)
        if n_traces == 0:
            return pos, np.zeros(0)
        steps = np.hypot(*np.diff(pos, axis=0).T) if n_traces > 1 else np.zeros(0)
        return pos, np.concatenate([[0.0], np.cumsum(steps)])

    def distance_along(self, n_traces: int, header: DztHeader) -> np.ndarray:
        """(n_traces,) metres walked: the cumulative path length plus travel_shift."""
        return self._path(n_traces, header)[1] + self.travel_shift

    def trace_coords(
        self, n_traces: int, header: DztHeader, frames: Mapping[str, Grid]
    ) -> np.ndarray:
        """(n_traces, 2) in the placement's CRS. `frames` is not needed."""
        pos, c = self._path(n_traces, header)
        if n_traces == 0:
            return pos
        q = c + self.travel_shift
        if n_traces == 1:
            return pos.copy()
        seg = np.clip(np.searchsorted(c, q, side="right") - 1, 0, n_traces - 2)
        length = c[seg + 1] - c[seg]
        safe = np.where(length > 0, length, 1.0)
        t = np.where(length > 0, (q - c[seg]) / safe, 0.0)
        out = pos[seg] + t[:, None] * (pos[seg + 1] - pos[seg])
        end = c[-1]
        over = q > end
        if over.any():
            out[over] = pos[-1] + (q[over] - end)[:, None] * self._tail_dir(pos, c, last=True)
        under = q < 0.0
        if under.any():
            out[under] = pos[0] + q[under][:, None] * self._tail_dir(pos, c, last=False)
        return out

    @staticmethod
    def _tail_dir(pos: np.ndarray, c: np.ndarray, *, last: bool) -> np.ndarray:
        """Unit direction of travel at the end (`last`) or start of the path, from
        the nearest segment with length."""
        d = np.diff(c)
        nz = np.flatnonzero(d > 0)
        if nz.size == 0:
            return np.zeros(2)
        k = nz[-1] if last else nz[0]
        v = pos[k + 1] - pos[k]
        return v / np.hypot(*v)


def track_from_log(
    log: DzgLog, to_xy: ToXY, crs: str, *, label: str | None = None
) -> TrackPlacement:
    """Place a DZG's fixes in `crs` with `to_xy`. Fixes with no position keep NaN x/y.

    Raises ValueError("no RTK-fixed position") or ValueError("only one RTK-fixed
    position") before projecting anything.
    """
    positioned = [f for f in log.fixes if math.isfinite(f.lat) and math.isfinite(f.lon)]
    fixed = sum(1 for f in positioned if f.quality == RTK_FIXED)
    if fixed == 0:
        raise ValueError("no RTK-fixed position")
    if fixed == 1:
        raise ValueError("only one RTK-fixed position")
    xs, ys = to_xy(
        np.array([f.lon for f in positioned], dtype=float),
        np.array([f.lat for f in positioned], dtype=float),
    )
    xy = {id(f): (float(x), float(y)) for f, x, y in zip(positioned, xs, ys)}
    nan = float("nan")
    fixes = tuple(
        TrackFix(
            trace=f.trace,
            x=xy.get(id(f), (nan, nan))[0],
            y=xy.get(id(f), (nan, nan))[1],
            lat=f.lat,
            lon=f.lon,
            alt_m=f.alt_m,
            geoid_m=f.geoid_m,
            quality=f.quality,
        )
        for f in log.fixes
    )
    return TrackPlacement(fixes=fixes, crs=crs, label=label)
