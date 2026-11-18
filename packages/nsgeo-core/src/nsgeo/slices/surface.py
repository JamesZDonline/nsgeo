"""Surfaces from picks: follow the reflection the picks name, leave holes where it fades.

The picks are joined into a guide over the area they cover. In each cell the
builder takes the strongest swing of the filled squared amplitude within a small
window of the guide, refines it between levels, and keeps the cell only when the
prepared volume's strength passes a test. A 3x3 median removes single-cell jumps
and never fills a hole. The volume is read in slabs and only the region's
columns are kept, so no whole cube is ever held (M16 spec §5.3, calls 7 and 17).

numpy only.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from nsgeo.slices.curvature import plan_curvature
from nsgeo.slices.frame import ZAxis
from nsgeo.slices.smooth import smooth
from nsgeo.slices.volume import PreparedVolume, VolumeSettings, prepare_volume
from nsgeo.velocity import VelocityModel

JOINS = ("min_curvature", "idw")
HULL_MARGIN_M = 0.3
OFFSET_SEARCH_M = 0.05
JUMP_M = 0.06
JOIN_REACH_M = 2.0
IDW_MIN_DISTANCE_M = 0.05
_IDW_BLOCK = 20000
FIT_CLOSE_M = 0.02
FIT_NEAR_M = 0.05
_WINDOW_SLACK = 1e-9  # a level exactly one window away still counts
_FIT_SLACK = 1e-6  # the surface is float32: a pick at the edge of its window is still inside it


def _positive(x: float) -> bool:
    return math.isfinite(x) and x > 0.0


def _non_negative(x: float) -> bool:
    return math.isfinite(x) and x >= 0.0


@dataclass(frozen=True)
class SurfaceSettings:
    """How a surface is built: the pick join, the tracking window, the strength test, smoothing."""

    join: str = "min_curvature"
    window_m: float = 0.02
    strength: float = 1.0
    smoothing_m: float = 0.0

    def __post_init__(self) -> None:
        if self.join not in JOINS:
            raise ValueError(f"join must be one of {JOINS}, got {self.join!r}")
        if not _positive(self.window_m):
            raise ValueError(f"window_m must be finite and > 0, got {self.window_m}")
        if not _non_negative(self.strength):
            raise ValueError(f"strength must be finite and >= 0, got {self.strength}")
        if not _non_negative(self.smoothing_m):
            raise ValueError(f"smoothing_m must be finite and >= 0, got {self.smoothing_m}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "join": self.join,
            "window_m": self.window_m,
            "strength": self.strength,
            "smoothing_m": self.smoothing_m,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> SurfaceSettings:
        """Valid fields of `doc` laid over the defaults; anything else is ignored."""
        fields: dict[str, Any] = {}
        if doc.get("join") in JOINS:
            fields["join"] = doc["join"]
        checks = {"window_m": _positive, "strength": _non_negative, "smoothing_m": _non_negative}
        for name, valid in checks.items():
            try:
                value = float(doc[name])
            except (KeyError, TypeError, ValueError):
                continue
            if valid(value):
                fields[name] = value
        return cls(**fields)


@dataclass(frozen=True)
class Outlier:
    """A pick the surface does not honour, and why (`reason`).

    "hole": the cell is empty (`surface_m` is None). "edge": the surface is held at the edge
    of its window, so the reflection lies further from the pick than the window allows.
    "far": the surface is more than the window from the pick.
    """

    index: int
    picked_m: float
    surface_m: float | None
    reason: str


@dataclass(frozen=True)
class SurfaceFit:
    """How the surface sits against its picks, in the picks' input order.

    Every pick is counted once: `on_holes`, `at_edge` (kept, with the surface held at the
    window's edge), or else by its distance to the surface in `within_close`, `within_near`
    or `further`. The `outliers` are the hole, edge and far picks.
    """

    within_close: int
    within_near: int
    further: int
    at_edge: int
    on_holes: int
    outliers: tuple[Outlier, ...]


@dataclass(frozen=True, eq=False)
class Surface:
    """A built surface. Arrays are `(ny, nx)`; `depth_m` and `guide_m` are NaN where empty."""

    depth_m: np.ndarray = field(repr=False)
    strength: np.ndarray = field(repr=False)
    guide_m: np.ndarray = field(repr=False)
    region: np.ndarray = field(repr=False)
    offset_m: float
    offset_votes: int
    offset_at_limit: int
    cell: float
    fit: SurfaceFit

    @property
    def offset_reliable(self) -> bool:
        """True when picks voted and fewer than half the votes sit on the offset search limit.

        A vote on the limit only says the strongest swing is at least that far away; when at
        least half sit there the offset is unreliable, and a stronger reflection out of reach is
        likely pulling the surface, so the picks should be checked. The flag does not catch a
        stronger reflection whose sidelobe falls inside the search: that can pull the offset,
        unflagged (a known blind spot)."""
        return self.offset_votes > 0 and 2 * self.offset_at_limit < self.offset_votes


def _hull(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Convex hull vertices, counter-clockwise, collinear points dropped."""
    pts = sorted(set(zip(x.tolist(), y.tolist())))
    if len(pts) < 3:
        return np.array(pts, dtype=float).reshape(-1, 2)

    def half(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for p in points:
            while (
                len(out) >= 2
                and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])
                <= 0
            ):
                out.pop()
            out.append(p)
        return out

    return np.array(half(pts)[:-1] + half(pts[::-1])[:-1], dtype=float)


def picks_span_an_area(x_m: np.ndarray, y_m: np.ndarray, *, tolerance_m: float = 0.01) -> bool:
    """False for fewer than 3 points, or when every point is within `tolerance_m` of the line
    through the two farthest apart."""
    x = np.asarray(x_m, dtype=float).ravel()
    y = np.asarray(y_m, dtype=float).ravel()
    if x.size < 3:
        return False
    hull = _hull(x, y)
    if len(hull) < 2:
        return False
    gap = np.hypot(hull[:, None, 0] - hull[None, :, 0], hull[:, None, 1] - hull[None, :, 1])
    a, b = np.unravel_index(int(np.argmax(gap)), gap.shape)
    ex, ey = hull[b] - hull[a]
    length = math.hypot(ex, ey)
    if length == 0.0:
        return False
    off = np.abs(ex * (y - hull[a, 1]) - ey * (x - hull[a, 0])) / length
    return bool(off.max() > tolerance_m)


def surface_volume(
    filled: np.ndarray,
    z: ZAxis,
    velocity: VelocityModel,
    cell: float,
    settings: VolumeSettings,
    *,
    slab_levels: int = 64,
    progress: Callable[[int, int], bool] | None = None,
) -> PreparedVolume:
    """`prepare_volume` with no sideways blur: a surface's strength never blurs (call 17)."""
    return prepare_volume(
        filled,
        z,
        velocity,
        cell,
        replace(settings, blur_m=0.0),
        slab_levels=slab_levels,
        progress=progress,
    )


def _peak_shift(vm: np.ndarray, v0: np.ndarray, vp: np.ndarray) -> np.ndarray:
    """Where a parabola through three neighbouring levels peaks, in levels from the middle one,
    clamped to half a level. Zero where it is not a clean peak."""
    denom = vm - 2.0 * v0 + vp
    ok = np.isfinite(denom) & np.isfinite(vm) & np.isfinite(vp) & (denom < 0.0)
    shift = np.where(ok, 0.5 * (vm - vp) / np.where(ok, denom, 1.0), 0.0)
    return np.clip(shift, -0.5, 0.5)


def _spans(lo: int, hi: int, size: int) -> Iterator[tuple[int, int]]:
    for c0 in range(lo, hi, size):
        yield c0, min(c0 + size, hi)


def _level_span(depths: np.ndarray, centre: np.ndarray, reach: float) -> tuple[np.ndarray, ...]:
    """First level and one past the last level within `reach` of each `centre`."""
    lo = np.searchsorted(depths, centre - reach - _WINDOW_SLACK, side="left")
    hi = np.searchsorted(depths, centre + reach + _WINDOW_SLACK, side="right")
    return lo, hi


def _measure_offset(
    vol: PreparedVolume, iy: np.ndarray, ix: np.ndarray, depth: np.ndarray, max_levels: int
) -> tuple[float, int, int]:
    """`(offset, votes, at_limit)`: the median of (refined swing argmax within `OFFSET_SEARCH_M` of
    a pick) minus the pick, the picks that voted, and the votes whose argmax is the first or last
    level of the search.

    A vote on the limit is censored (the strongest swing may lie further out) but still counts at
    the limit in the median, which stays unbiased while fewer than half the votes sit there. A
    pick with no finite level in reach casts no vote; with none at all the offset is 0.0."""
    depths = vol.depths_m
    nd = depths.size
    step = float(depths[1] - depths[0]) if nd > 1 else 0.0
    covered = vol.covered[iy, ix]
    lo, hi = _level_span(depths, depth, OFFSET_SEARCH_M)
    use = np.flatnonzero(covered & (lo < hi))
    if use.size == 0:
        return 0.0, 0, 0
    first = np.maximum(lo - 1, 0)
    last = np.minimum(hi + 1, nd)
    series = {int(p): np.full(int(last[p] - first[p]), np.nan) for p in use}
    for c0, c1 in _spans(int(first[use].min()), int(last[use].max()), max_levels):
        sw = vol.swing(c0, c1)
        for p in use:
            a, b = max(c0, int(first[p])), min(c1, int(last[p]))
            if a < b:
                series[int(p)][a - first[p] : b - first[p]] = sw[a - c0 : b - c0, iy[p], ix[p]]
    found = []
    at_limit = 0
    for p in use:
        col = series[int(p)]
        first_in, last_in = int(lo[p] - first[p]), int(hi[p] - first[p])
        inner = col[first_in:last_in]
        if not np.isfinite(inner).any():
            continue
        k = first_in + int(np.argmax(np.where(np.isfinite(inner), inner, -np.inf)))
        at_limit += k in (first_in, last_in - 1)
        vm = col[k - 1] if k > 0 else np.nan
        vp = col[k + 1] if k + 1 < col.size else np.nan
        shift = float(_peak_shift(np.array(vm), np.array(col[k]), np.array(vp)))
        refined = depths[int(first[p]) + k] + shift * step
        found.append(
            min(max(refined, depth[p] - OFFSET_SEARCH_M), depth[p] + OFFSET_SEARCH_M) - depth[p]
        )
    return (float(np.median(found)) if found else 0.0), len(found), int(at_limit)


def _track(
    vol: PreparedVolume,
    iy: np.ndarray,
    ix: np.ndarray,
    target: np.ndarray,
    window_m: float,
    min_strength: float,
    max_levels: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`(depth, strength, held)` per column: the swing's refined peak within `window_m` of
    `target`, NaN where the column has no level in reach or its strength fails the test.

    `held` is True where the strongest level in the window is the window's first or last level
    and the swing at the next level outside the window is larger: the reflection lies beyond the
    window and the pick is held at its edge. False where no level lies outside."""
    depths = vol.depths_m
    nd = depths.size
    step = float(depths[1] - depths[0]) if nd > 1 else 0.0
    n = target.size
    lo, hi = _level_span(depths, target, window_m)
    best_v = np.full(n, -np.inf)
    best_k = np.full(n, -1)
    best_vm = np.full(n, np.nan)
    best_vp = np.full(n, np.nan)
    best_s = np.full(n, np.nan)
    out_lo = np.full(n, -np.inf)
    out_hi = np.full(n, -np.inf)
    cols = np.arange(n)
    live = lo < hi
    if live.any():
        for c0, c1 in _spans(int(lo[live].min()), int(hi[live].max()), max_levels):
            a, b = max(c0 - 1, 0), min(c1 + 1, nd)
            padded = np.full((c1 - c0 + 2, n), np.nan, dtype=np.float32)
            padded[a - (c0 - 1) : b - (c0 - 1)] = vol.swing(a, b)[:, iy, ix]
            _, strength = vol.slab(c0, c1)
            strength = strength[:, iy, ix]
            js = np.arange(c0, c1)[:, None]
            rows = np.arange(c0 - 1, c1 + 1)[:, None]
            fin = np.isfinite(padded)
            out_lo = np.maximum(out_lo, np.where(fin & (rows == lo - 1), padded, -np.inf).max(0))
            out_hi = np.maximum(out_hi, np.where(fin & (rows == hi), padded, -np.inf).max(0))
            inner = padded[1:-1]
            inside = (js >= lo) & (js < hi) & np.isfinite(inner)
            vals = np.where(inside, inner, -np.inf)
            local = np.argmax(vals, axis=0)
            v = vals[local, cols]
            better = v > best_v
            best_v = np.where(better, v, best_v)
            best_k = np.where(better, c0 + local, best_k)
            best_vm = np.where(better, padded[local, cols], best_vm)
            best_vp = np.where(better, padded[local + 2, cols], best_vp)
            best_s = np.where(better, strength[local, cols], best_s)
    found = best_k >= 0
    centre = np.where(found, best_v, np.nan)
    shift = _peak_shift(best_vm.astype(float), centre, best_vp.astype(float))
    depth = depths[np.where(found, best_k, 0)] + shift * step
    depth = np.clip(depth, target - window_m, target + window_m)
    with np.errstate(invalid="ignore"):
        keep = found & (best_s >= min_strength)
    with np.errstate(invalid="ignore"):
        held = keep & (
            ((best_k == lo) & (out_lo > best_v)) | ((best_k == hi - 1) & (out_hi > best_v))
        )
    return np.where(keep, depth, np.nan), np.where(keep, best_s, np.nan), held


def _median3(depth: np.ndarray) -> np.ndarray:
    """3x3 median over the kept cells, written to kept cells only: a hole stays a hole."""
    ny, nx = depth.shape
    p = np.pad(depth, 1, constant_values=np.nan)
    stack = np.stack([p[dy : ny + dy, dx : nx + dx] for dy in range(3) for dx in range(3)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(stack, axis=0)
    return np.where(np.isfinite(depth), med, np.nan)


def _inside_hull(poly: np.ndarray, gx: np.ndarray, gy: np.ndarray, margin: float) -> np.ndarray:
    ok = np.ones(gx.shape, dtype=bool)
    for (x0, y0), (x1, y1) in zip(poly, np.roll(poly, -1, axis=0)):
        ex, ey = x1 - x0, y1 - y0
        ok &= (ex * (gy - y0) - ey * (gx - x0)) / math.hypot(ex, ey) >= -margin
    return ok


def _guide(
    join: str,
    cell: float,
    region: np.ndarray,
    iy: np.ndarray,
    ix: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    depth: np.ndarray,
) -> np.ndarray:
    """The picks joined over the grid, `(ny, nx)` float64. Inverse distance is computed for the
    region's cells only (NaN elsewhere); minimum curvature joins the whole grid and is NaN beyond
    its reach of every pick."""
    shape = region.shape
    if join == "idw":
        ry, rx = np.nonzero(region)
        cx, cy = (rx + 0.5) * cell, (ry + 0.5) * cell
        out = np.full(shape, np.nan)
        values = np.empty(cx.size)
        for s in range(0, cx.size, _IDW_BLOCK):
            dist = np.hypot(cx[s : s + _IDW_BLOCK, None] - x, cy[s : s + _IDW_BLOCK, None] - y)
            w = 1.0 / np.maximum(dist, IDW_MIN_DISTANCE_M) ** 2
            values[s : s + _IDW_BLOCK] = (w * depth).sum(axis=1) / w.sum(axis=1)
        out[ry, rx] = values
        return out
    total = np.zeros(shape)
    count = np.zeros(shape)
    np.add.at(total, (iy, ix), depth)
    np.add.at(count, (iy, ix), 1.0)
    populated = count > 0
    mean = np.where(populated, total / np.maximum(count, 1.0), np.nan)
    joined = plan_curvature(populated, cell, JOIN_REACH_M).apply(mean.astype(np.float32))
    return np.where(np.isfinite(joined), joined.astype(float), np.nan)


def _fit(
    picked: np.ndarray,
    surface: np.ndarray,
    held: np.ndarray,
    guide: np.ndarray,
    window_m: float,
    beyond_window: np.ndarray | None = None,
) -> SurfaceFit:
    """`surface`, `held` (the depth before smoothing) and `guide` hold each pick's cell's values,
    NaN on a hole or off the grid. `beyond_window` flags the picks whose column's strongest swing
    lies outside the window (see `_track`); they are at the edge whatever the clamp did."""
    on_hole = ~np.isfinite(surface)
    miss = np.abs(surface - picked) - _FIT_SLACK  # distance, less float32 rounding
    with np.errstate(invalid="ignore"):
        edge = ~on_hole & (np.abs(held - guide) >= window_m - _FIT_SLACK)
        if beyond_window is not None:
            edge |= ~on_hole & beyond_window
        kept = ~on_hole & ~edge
        close = kept & (miss <= FIT_CLOSE_M)
        near = kept & (miss > FIT_CLOSE_M) & (miss <= FIT_NEAR_M)
        far = kept & (miss > FIT_NEAR_M)
        beyond = kept & (miss > window_m)
    outliers = []
    for i in np.flatnonzero(on_hole | edge | beyond):
        reason = "hole" if on_hole[i] else "edge" if edge[i] else "far"
        outliers.append(
            Outlier(int(i), float(picked[i]), None if on_hole[i] else float(surface[i]), reason)
        )
    return SurfaceFit(
        within_close=int(close.sum()),
        within_near=int(near.sum()),
        further=int(far.sum()),
        at_edge=int(edge.sum()),
        on_holes=int(on_hole.sum()),
        outliers=tuple(outliers),
    )


def build_surface(
    vol: PreparedVolume,
    x_m: np.ndarray,
    y_m: np.ndarray,
    depth_m: np.ndarray,
    settings: SurfaceSettings,
    *,
    max_levels: int = 64,
) -> Surface:
    """Build a surface from picks (frame-local metres, depths on the volume's depth scale).

    Raises ValueError for a blurred volume, picks of unequal length, a pick that is not
    finite, or picks that do not span an area. A pick outside the frame or the depth range
    takes no part in the guide or the offset and is reported on a hole.
    """
    if vol.settings.blur_m != 0.0:
        raise ValueError("a surface needs a volume prepared without the sideways blur")
    if max_levels < 1:
        raise ValueError(f"max_levels must be >= 1, got {max_levels}")
    x = np.asarray(x_m, dtype=float).ravel()
    y = np.asarray(y_m, dtype=float).ravel()
    depth = np.asarray(depth_m, dtype=float).ravel()
    if not x.size == y.size == depth.size:
        raise ValueError(f"picks must have equal lengths, got {x.size}, {y.size}, {depth.size}")
    if not (np.isfinite(x).all() and np.isfinite(y).all() and np.isfinite(depth).all()):
        raise ValueError("pick positions and depths must be finite")
    ny, nx = vol.covered.shape
    cell = vol.cell
    depths = vol.depths_m
    with np.errstate(invalid="ignore"):
        iy_all = np.floor(y / cell).astype(np.int64)
        ix_all = np.floor(x / cell).astype(np.int64)
    usable = (
        (iy_all >= 0)
        & (iy_all < ny)
        & (ix_all >= 0)
        & (ix_all < nx)
        & (depth >= depths[0])
        & (depth <= depths[-1])
    )
    if not picks_span_an_area(x[usable], y[usable]):
        in_frame = (iy_all >= 0) & (iy_all < ny) & (ix_all >= 0) & (ix_all < nx)
        raise ValueError(
            f"{int(usable.sum())} of {x.size} picks are usable "
            f"({int((~in_frame).sum())} outside the frame, "
            f"{int((in_frame & ~((depth >= depths[0]) & (depth <= depths[-1]))).sum())} outside "
            f"the depth range {depths[0]:.2f} to {depths[-1]:.2f} m); a surface needs at least 3 "
            "usable picks that do not all lie on one line"
        )
    ux, uy, ud = x[usable], y[usable], depth[usable]
    iy, ix = iy_all[usable], ix_all[usable]

    gx = np.broadcast_to((np.arange(nx) + 0.5) * cell, (ny, nx))
    gy = np.broadcast_to(((np.arange(ny) + 0.5) * cell)[:, None], (ny, nx))
    region = _inside_hull(_hull(ux, uy), gx, gy, HULL_MARGIN_M) & vol.covered
    guide = _guide(settings.join, cell, region, iy, ix, ux, uy, ud)
    region &= np.isfinite(guide)  # no flat guide beyond the join's reach of every pick

    offset, votes, at_limit = _measure_offset(vol, iy, ix, ud, max_levels)
    tracked = np.full((ny, nx), np.nan)
    strength = np.full((ny, nx), np.nan)
    beyond = np.zeros((ny, nx), dtype=bool)
    ry, rx = np.nonzero(region)
    if ry.size:
        d, s, h = _track(
            vol,
            ry,
            rx,
            guide[ry, rx] + offset,
            settings.window_m,
            settings.strength,
            max_levels,
        )
        tracked[ry, rx] = d
        strength[ry, rx] = s
        beyond[ry, rx] = h
    target = guide + offset
    # the median may borrow a neighbour's depth; it must not carry a cell out of its window
    final = np.clip(_median3(tracked), target - settings.window_m, target + settings.window_m)
    final = final - offset
    held32 = final.astype(np.float32)  # before smoothing: smoothing must not hide an edge pick
    if settings.smoothing_m > 0.0:
        final = smooth(final, cell, settings.smoothing_m, settings.smoothing_m)
    final32 = final.astype(np.float32)

    in_surface = np.full(depth.size, np.nan)
    in_surface[usable] = final32[iy, ix]
    guide32 = np.where(region, guide, np.nan).astype(np.float32)
    at_guide = np.full(depth.size, np.nan)
    at_guide[usable] = guide32[iy, ix]
    held = np.full(depth.size, np.nan)
    held[usable] = held32[iy, ix]
    beyond_pick = np.zeros(depth.size, dtype=bool)
    beyond_pick[usable] = beyond[iy, ix]
    return Surface(
        depth_m=final32,
        strength=strength.astype(np.float32),
        guide_m=guide32,
        region=region,
        offset_m=offset,
        offset_votes=votes,
        offset_at_limit=at_limit,
        cell=float(cell),
        fit=_fit(depth, in_surface, held, at_guide, settings.window_m, beyond_pick),
    )


def surface_mesh(
    depth_m: np.ndarray, cell: float, jump_m: float = JUMP_M
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`(points, triangles, cells)` for the kept cells of a depth grid.

    `points` is `(n, 3)` float64 as x, y, depth at each kept cell centre; `triangles` is `(m, 3)`
    int64 indices into `points`; `cells` is `(n,)` int64 flat cell ids. A triangle is dropped
    when a vertex is missing or its depths differ by more than `jump_m`.
    """
    d = np.asarray(depth_m, dtype=np.float64)
    ny, nx = d.shape
    valid = np.isfinite(d)
    idx = np.full(d.shape, -1, dtype=np.int64)
    idx[valid] = np.arange(int(valid.sum()))
    iy, ix = np.nonzero(valid)
    points = np.column_stack([(ix + 0.5) * cell, (iy + 0.5) * cell, d[valid]])
    cells = (iy * nx + ix).astype(np.int64)
    parts = [np.empty((0, 3), dtype=np.int64)]
    for corners in (((0, 0), (0, 1), (1, 1)), ((0, 0), (1, 1), (1, 0))):
        views = [(slice(dy, ny - 1 + dy), slice(dx, nx - 1 + dx)) for dy, dx in corners]
        ids = [idx[v] for v in views]
        depths = np.stack([d[v] for v in views])
        with np.errstate(invalid="ignore"):
            ok = (ids[0] >= 0) & (ids[1] >= 0) & (ids[2] >= 0)
            ok &= (depths.max(axis=0) - depths.min(axis=0)) <= jump_m
        parts.append(np.column_stack([i[ok] for i in ids]))
    return points, np.concatenate(parts), cells
