"""A line placed along the GPS track logged with it (M17a, #134; M21d).

A track with two or more RTK-fixed fixes (quality 4) anchors on those only.
Traces between two anchors sit on the straight segment between them, evenly by
trace number, so a dropout to float or plain GPS is bridged, never trusted.
Past the first and last anchor a line runs on in a straight line at its
heading, by the wheel's metres per trace. `travel_shift` moves every trace
forward along the walked path, as it does for `GridPlacement` (#47).

A track with fewer RTK fixes (MALÅ `.cor` and SEG-Y logs have none) anchors on
every fix with a position, `anchor_on="all"`, optionally smoothed over
`smooth_m` metres along the track (spec M21 §16).

The projection is injected: the core has no pyproj. `to_xy(lon, lat)` takes
degrees and returns metres in the placement's CRS.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields

import numpy as np

from nsgeo.geometry.grid import Grid
from nsgeo.io.dzg import RTK_FIXED, DzgLog
from nsgeo.io.header import RadarHeader

ToXY = Callable[[np.ndarray, np.ndarray], "tuple[np.ndarray, np.ndarray]"]
"""(lon, lat) in degrees -> (x, y) in metres."""

END_LIMIT_M: float = 2.0
"""A start or end run longer than this is flagged."""

HEADING_BASE_M: float = 1.0
"""An end's heading is taken from an anchor at least this far away (1 Hz jitter)."""


_NAN_KEY = "nan"


def _key(value: object) -> object:
    """A value as it compares: every NaN is one, and None stays apart from it."""
    if isinstance(value, float) and math.isnan(value):
        return _NAN_KEY
    return value


@dataclass(frozen=True, eq=False)
class TrackFix:
    """One GGA fix of a line, placed. x and y are NaN for a fix with no position.

    Equality and hash treat every NaN as the same value, so two placements built
    from the same log are equal (a plain dataclass compares NaN by identity).
    """

    trace: int
    x: float
    y: float
    lat: float
    lon: float
    alt_m: float | None = None
    geoid_m: float | None = None
    quality: int = 4

    def _fields(self) -> tuple[object, ...]:
        return tuple(_key(getattr(self, f.name)) for f in fields(self))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TrackFix):
            return NotImplemented
        return self._fields() == other._fields()

    def __hash__(self) -> int:
        return hash(self._fields())


@dataclass(frozen=True)
class Bridge:
    """A dropout: the anchors either side of one or more non-RTK fixes."""

    first_trace: int
    last_trace: int
    metres: float


#: `TrackPlacement.anchor_on` values.
ANCHOR_RTK = "rtk"
ANCHOR_ALL = "all"


def _positioned(fix: TrackFix) -> bool:
    return math.isfinite(fix.x) and math.isfinite(fix.y)


def _is_anchor(fix: TrackFix) -> bool:
    return fix.quality == RTK_FIXED and _positioned(fix)


#: The thinning step for measuring a jittery track's length: positions at
#: least this far apart along it (spec M21 §16).
THIN_M: float = 5.0


def thinned_length(xy: np.ndarray, step: float = THIN_M) -> float:
    """The length of the path through `xy` (n, 2), keeping only points at least
    `step` from the last kept one (and the last point). Jitter of a metre or two
    would otherwise make a 1 Hz track 10-50 % long by itself."""
    if len(xy) < 2:
        return 0.0
    kept = [xy[0]]
    for p in xy[1:]:
        if math.hypot(*(p - kept[-1])) >= step:
            kept.append(p)
    if math.hypot(*(xy[-1] - kept[-1])) > 0:
        kept.append(xy[-1])
    k = np.array(kept)
    return float(np.hypot(*np.diff(k, axis=0).T).sum())


def smoothed(anchors: tuple[TrackFix, ...], smooth_m: float) -> tuple[TrackFix, ...]:
    """`anchors` with each position the mean of the anchors within `smooth_m / 2`
    of it along the track; the window shrinks at the ends. 0 returns them as they
    are, the same objects.

    Distance along the track is measured by trace number, scaled by the track's
    thinned length over its trace span: traces are evenly spaced in distance on a
    wheel-triggered line, and the raw path between jittery fixes is not.
    """
    if smooth_m <= 0 or len(anchors) < 3:
        return anchors
    xy = np.array([(f.x, f.y) for f in anchors])
    traces = np.array([f.trace for f in anchors], dtype=float)
    span = traces[-1] - traces[0]
    length = thinned_length(xy)
    if not length > 0:
        length = float(np.hypot(*np.diff(xy, axis=0).T).sum())
    s = (traces - traces[0]) * (length / span)
    lo = np.searchsorted(s, s - smooth_m / 2.0 - 1e-9, side="left")
    hi = np.searchsorted(s, s + smooth_m / 2.0 + 1e-9, side="right")
    sums = np.vstack([np.zeros((1, 2)), np.cumsum(xy, axis=0)])
    mean = (sums[hi] - sums[lo]) / (hi - lo)[:, None]
    return tuple(dataclasses.replace(f, x=float(x), y=float(y)) for f, (x, y) in zip(anchors, mean))


@dataclass(frozen=True)
class TrackPlacement:
    """A line placed along its GPS track.

    `fixes` are every fix of the log in trace order, whatever the quality: a
    non-RTK fix between two anchors is what marks a bridge. `travel_shift` is
    metres, positive moving every trace forward along the way the line was
    walked. `anchor_on` is "rtk" (RTK-fixed fixes only) or "all" (every fix
    with a position, for a line without RTK); `smooth_m` smooths an "all"
    track's anchors over that many metres along it, 0 leaving them as recorded.
    """

    fixes: tuple[TrackFix, ...]
    crs: str
    grid_id: str | None = None
    label: str | None = None
    travel_shift: float = 0.0
    anchor_on: str = ANCHOR_RTK
    smooth_m: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "fixes", tuple(self.fixes))
        for a, b in zip(self.fixes, self.fixes[1:]):
            if not b.trace > a.trace:
                raise ValueError("trace numbers must rise along a GPS track")
        if self.anchor_on not in (ANCHOR_RTK, ANCHOR_ALL):
            raise ValueError(f"anchor_on must be 'rtk' or 'all', got {self.anchor_on!r}")
        if not (math.isfinite(self.smooth_m) and self.smooth_m >= 0):
            raise ValueError(f"smooth_m must be 0 or more, got {self.smooth_m!r}")
        if self.smooth_m > 0 and self.anchor_on == ANCHOR_RTK:
            raise ValueError("smoothing is for tracks without RTK")
        what = "RTK-fixed" if self.anchor_on == ANCHOR_RTK else "GPS"
        anchors = self.anchors()
        if not anchors:
            raise ValueError(f"no {what} position")
        if len(anchors) == 1:
            raise ValueError(f"only one {what} position")
        if all(math.hypot(a.x - anchors[0].x, a.y - anchors[0].y) < 1e-9 for a in anchors):
            raise ValueError(f"the {what} positions all lie at one point")
        if not math.isfinite(self.travel_shift):
            raise ValueError(f"travel_shift must be finite, got {self.travel_shift!r}")

    def anchors(self) -> tuple[TrackFix, ...]:
        """The fixes traces are placed by, as recorded: the RTK-fixed fixes with a
        position, or for an "all" track every fix with one."""
        if self.anchor_on == ANCHOR_ALL:
            return tuple(f for f in self.fixes if _positioned(f))
        return tuple(f for f in self.fixes if _is_anchor(f))

    def placed_anchors(self) -> tuple[TrackFix, ...]:
        """`anchors()` smoothed by `smooth_m`; the same objects when it is 0."""
        return smoothed(self.anchors(), self.smooth_m)

    def bridges(self) -> tuple[Bridge, ...]:
        """Each pair of consecutive anchors with a non-anchor fix between them."""
        out: list[Bridge] = []
        last: TrackFix | None = None
        gap = False
        if self.anchor_on == ANCHOR_ALL:
            return ()
        for f in self.fixes:
            if _is_anchor(f):
                if last is not None and gap:
                    out.append(Bridge(last.trace, f.trace, math.hypot(f.x - last.x, f.y - last.y)))
                last, gap = f, False
            else:
                gap = True
        return tuple(out)

    # -- the run-on past each end ------------------------------------------------

    def _end_step(self, header: RadarHeader, a: TrackFix, b: TrackFix) -> float:
        """Metres per trace beyond the end anchor `a`, whose neighbour anchor is `b`."""
        spm = header.traces_per_metre
        if spm > 0:
            return 1.0 / spm
        return math.hypot(b.x - a.x, b.y - a.y) / abs(b.trace - a.trace)

    def _heading(self, end: TrackFix, others: list[TrackFix]) -> np.ndarray:
        """Unit vector from `end` towards the first anchor, in the order given
        (inward along the track), at least HEADING_BASE_M away, else the farthest."""
        best: TrackFix | None = None
        best_d = -1.0
        for o in others:  # in track order from the end, not sorted by distance
            d = math.hypot(o.x - end.x, o.y - end.y)
            if d >= HEADING_BASE_M:
                best, best_d = o, d
                break
            if d > best_d:
                best, best_d = o, d
        assert best is not None
        return np.array([best.x - end.x, best.y - end.y]) / best_d

    def _ends(self, header: RadarHeader) -> tuple[tuple[TrackFix, np.ndarray, float], ...]:
        a = self.placed_anchors()
        first_dir = self._heading(a[0], list(a[1:]))
        last_dir = self._heading(a[-1], list(reversed(a[:-1])))
        return (
            (a[0], first_dir, self._end_step(header, a[0], a[1])),
            (a[-1], last_dir, self._end_step(header, a[-1], a[-2])),
        )

    def positions(self, n_traces: int, header: RadarHeader) -> np.ndarray:
        """(n_traces, 2) unshifted: on the anchor segments between anchors, and on
        straight runs at the heading beyond the first and last."""
        a = self.placed_anchors()
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

    def end_runs(self, n_traces: int, header: RadarHeader) -> tuple[float, float]:
        """Metres placed before the first anchor and after the last."""
        (first, _, first_step), (last, _, last_step) = self._ends(header)
        start = max(first.trace, 0) * first_step
        end = max(n_traces - 1 - last.trace, 0) * last_step
        return start, end

    # -- the Placement protocol --------------------------------------------------

    def _path(self, n_traces: int, header: RadarHeader) -> tuple[np.ndarray, np.ndarray]:
        pos = self.positions(n_traces, header)
        if n_traces == 0:
            return pos, np.zeros(0)
        steps = np.hypot(*np.diff(pos, axis=0).T) if n_traces > 1 else np.zeros(0)
        return pos, np.concatenate([[0.0], np.cumsum(steps)])

    def distance_along(self, n_traces: int, header: RadarHeader) -> np.ndarray:
        """(n_traces,) metres walked: the cumulative path length plus travel_shift."""
        return self._path(n_traces, header)[1] + self.travel_shift

    def trace_coords(
        self, n_traces: int, header: RadarHeader, frames: Mapping[str, Grid]
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


def anchor_rule(log: DzgLog) -> str:
    """ "rtk" when the log has two or more RTK-fixed positions, else "all" (§16)."""
    fixed = sum(
        1
        for f in log.fixes
        if f.quality == RTK_FIXED and math.isfinite(f.lat) and math.isfinite(f.lon)
    )
    return ANCHOR_RTK if fixed >= 2 else ANCHOR_ALL


def track_from_log(
    log: DzgLog, to_xy: ToXY, crs: str, *, label: str | None = None, smooth_m: float = 0.0
) -> TrackPlacement:
    """Place a GPS log's fixes in `crs` with `to_xy`. Fixes with no position keep NaN x/y.

    Two or more RTK-fixed positions anchor on those, ignoring `smooth_m`; fewer
    anchor on every positioned fix, smoothed over `smooth_m` metres. Raises
    ValueError("no GPS position") or ValueError("only one GPS position") before
    projecting anything.
    """
    positioned = [f for f in log.fixes if math.isfinite(f.lat) and math.isfinite(f.lon)]
    anchor_on = anchor_rule(log)
    if anchor_on == ANCHOR_ALL:
        if not positioned:
            raise ValueError("no GPS position")
        if len(positioned) == 1:
            raise ValueError("only one GPS position")
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
    return TrackPlacement(
        fixes=fixes,
        crs=crs,
        label=label,
        anchor_on=anchor_on,
        smooth_m=smooth_m if anchor_on == ANCHOR_ALL else 0.0,
    )


#: More than this fraction between the GPS and wheel lengths adds a note (§16).
LENGTH_TOLERANCE: float = 0.20


def gps_length_note(log: DzgLog, to_xy: ToXY, header: RadarHeader) -> str | None:
    """A note when the line's GPS track and its wheel disagree on its length by
    more than 20 %, else None (spec M21 §16).

    The GPS length is the track through the anchors `track_from_log` would use,
    thinned to positions `THIN_M` apart; the wheel's is their trace span over
    the header's traces per metre. None when the line has no wheel spacing, or
    the thinned track is under `THIN_M` long. Neither length is taken as right.
    """
    tpm = header.traces_per_metre
    if not tpm > 0:
        return None
    rtk = anchor_rule(log) == ANCHOR_RTK
    fixes = [
        f
        for f in log.fixes
        if math.isfinite(f.lat) and math.isfinite(f.lon) and (not rtk or f.quality == RTK_FIXED)
    ]
    if len(fixes) < 2:
        return None
    xs, ys = to_xy(
        np.array([f.lon for f in fixes], dtype=float), np.array([f.lat for f in fixes], dtype=float)
    )
    gps = thinned_length(np.column_stack([xs, ys]))
    if gps < THIN_M:
        return None
    wheel = (fixes[-1].trace - fixes[0].trace) / tpm
    if not wheel > 0 or abs(gps - wheel) <= LENGTH_TOLERANCE * wheel:
        return None
    return f"its GPS track is {gps:.0f} m but its wheel says {wheel:.0f} m: check which is right"
