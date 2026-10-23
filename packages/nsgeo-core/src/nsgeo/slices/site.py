"""The site view's numpy core: one lattice, one window mapping, seams, normalisation.

A site is several grids shown as one map. Everything here is pure numpy and
does no I/O, so the plugin only has to feed it arrays.

* `SiteLattice` and `lattice_pixel` -- the common north-up pixel lattice
  (spec 4.7, Ruling 2) and `compose`, which gathers grid-local slices onto it.
* `site_axis`, `grid_axis` and `window_on` -- the time-window mapping
  (spec 4.3). `window_on` is the single place a site window becomes a grid
  window; lining up by depth, once velocity fitting lands, replaces its body.
* `seam_masks` and `find_seams` -- where two grids meet (spec 4.6.1).
* `background_level`, `edge_match_solve`, `normalise` -- spec 4.6.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from nsgeo.slices.display import SliceWindow
from nsgeo.slices.frame import CubeFrame, ZAxis

NORMALISATION_METHODS = ("none", "background", "edge", "histogram")
BACKGROUND_FRACTION = 0.75
SEAM_WIDTH_SPACINGS = 1.5
MIN_SEAM_CELLS = 20

_SNAP = 1e-6  # levels: window and axis snapping
_RIGHT_ANGLE_TOL_DEG = 1e-9
#: Ruling F-5: how far, in cells, a frame's far corner may sit from where an
#: axis-aligned frame's would and the frame still count as axis-aligned.
AXIS_SNAP_CELLS = 0.01


def _snap_eps(coords: Iterable[float], pixel: float) -> float:
    """Scale-aware snapping tolerance, in pixels, for a coordinate ratio.

    The same `64 * eps * max(1, |coord|) / pixel` margin `to_north_up` uses:
    a fixed epsilon on the ratio is too small at UTM magnitudes.
    """
    magnitude = max(1.0, *(abs(c) for c in coords))
    return 64.0 * float(np.finfo(float).eps) * magnitude / pixel


@dataclass(frozen=True)
class SiteLattice:
    """A north-up pixel lattice in the site's CRS.

    `x0` is the west edge and `y1` the north edge, both whole multiples of
    `pixel`, so the lattice is stable as grids are included or excluded.
    Row 0 is north, matching the geotransform's negative y size.
    """

    x0: float
    y1: float
    pixel: float
    width: int
    height: int
    crs: str

    @property
    def geotransform(self) -> tuple[float, ...]:
        return (self.x0, self.pixel, 0.0, self.y1, 0.0, -self.pixel)

    @property
    def n_pixels(self) -> int:
        return self.width * self.height

    def pixel_centres(self) -> np.ndarray:
        """(height * width, 2) world coordinates, row-major, row 0 at the north."""
        xs = self.x0 + (np.arange(self.width, dtype=float) + 0.5) * self.pixel
        ys = self.y1 - (np.arange(self.height, dtype=float) + 0.5) * self.pixel
        grid_x, grid_y = np.meshgrid(xs, ys)
        return np.column_stack([grid_x.ravel(), grid_y.ravel()])

    @classmethod
    def covering(
        cls,
        extents: Sequence[tuple[float, float, float, float]],
        pixel: float,
        crs: str,
    ) -> SiteLattice:
        """The smallest lattice, anchored on multiples of `pixel`, holding every extent.

        Each extent is `(xmin, ymin, xmax, ymax)` already in `crs`. Edge
        indices are snapped with `to_north_up`'s scale-aware epsilon, so an
        extent that ends exactly on a pixel boundary does not gain a phantom
        row or column from floating-point residue at UTM magnitudes.
        """
        if len(extents) == 0:
            raise ValueError("need at least one extent")
        if not pixel > 0.0:
            raise ValueError(f"pixel must be positive, got {pixel}")
        xmin = min(e[0] for e in extents)
        ymin = min(e[1] for e in extents)
        xmax = max(e[2] for e in extents)
        ymax = max(e[3] for e in extents)
        eps = _snap_eps((xmin, ymin, xmax, ymax), pixel)
        ix0 = math.floor(xmin / pixel + eps)
        ix1 = math.ceil(xmax / pixel - eps)
        iy0 = math.floor(ymin / pixel + eps)
        iy1 = math.ceil(ymax / pixel - eps)
        return cls(
            x0=ix0 * pixel,
            y1=iy1 * pixel,
            pixel=pixel,
            width=max(1, ix1 - ix0),
            height=max(1, iy1 - iy0),
            crs=crs,
        )


def snap_azimuth(azimuth_deg: float, extent_m: float, cell: float) -> float:
    """The nearest multiple of 90 degrees if the frame is axis-aligned in effect.

    Ruling F-5 (final review D3). A frame counts as axis-aligned when its
    deviation from the nearest right angle moves its far corner by less
    than `AXIS_SNAP_CELLS` (1%) of a cell across the frame's own extent:
    `extent_m * |sin(deviation)| < 0.01 * cell`, `extent_m` the distance
    from the frame's origin to its far corner. Otherwise `azimuth_deg` is
    returned unchanged. A grid laid north-up in a CRS that differs from the
    site's by a datum shift alone comes out microdegrees off; taken at face
    value it halves the lattice pitch (Ruling 2) and quadruples the pixels
    for a turn no pixel can see. Feed the result to `lattice_pixel`.
    """
    right = 90.0 * round(azimuth_deg / 90.0)
    deviation = math.radians(azimuth_deg - right)
    if extent_m * abs(math.sin(deviation)) < AXIS_SNAP_CELLS * cell:
        return right
    return azimuth_deg


def lattice_pixel(cell: float, azimuths: Iterable[float]) -> float:
    """The lattice pitch for a site (Ruling 2): `cell`, or `cell / 2` if any frame is rotated.

    A backward nearest-neighbour gather loses no cell when every frame is
    axis-aligned (each cell holds exactly one pixel centre at pitch = cell),
    but does lose cells in a rotated frame. At half the pitch a rotated
    square still contains a lattice point. An azimuth counts as a multiple
    of 90 degrees within 1e-9 degrees; `snap_azimuth` decides first whether
    a frame a hair off a right angle is axis-aligned in effect (Ruling F-5).
    """
    for az in azimuths:
        if abs(az - 90.0 * round(az / 90.0)) > _RIGHT_ANGLE_TOL_DEG:
            return cell / 2.0
    return cell


def compose(lattice: SiteLattice, layers: Sequence[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """Gather grid-local slices onto the lattice; overlaps take the mean.

    Each layer is `(ids, values)`: `ids` is `(n_pixels,)` from
    `frame.cell_index(lattice.pixel_centres())` (-1 outside the frame) and
    `values` is the frame's `(ny, nx)` array. Each pixel is the mean of the
    finite values covering it, NaN where none do. Returns float32
    `(height, width)`.
    """
    total = np.zeros(lattice.n_pixels, dtype=float)
    count = np.zeros(lattice.n_pixels, dtype=np.int64)
    for ids, values in layers:
        ids = np.asarray(ids)
        if ids.shape != (lattice.n_pixels,):
            raise ValueError(f"ids must be ({lattice.n_pixels},), got {ids.shape}")
        flat = np.asarray(values, dtype=float).reshape(-1)
        got = flat[np.clip(ids, 0, flat.size - 1)]
        ok = (ids >= 0) & np.isfinite(got)
        total += np.where(ok, got, 0.0)
        count += ok
    out = np.full(lattice.n_pixels, np.nan, dtype=float)
    np.divide(total, count, out=out, where=count > 0)
    return out.reshape(lattice.height, lattice.width).astype(np.float32)


@dataclass(frozen=True, eq=False)
class Footprint:
    """Where one layer lands on a lattice: a window, and the cell ids inside it.

    The window is lattice rows `[row0, row1)` and columns `[col0, col1)`;
    `ids` is `(row1 - row0, col1 - col0)`, the frame cell under each pixel
    centre, -1 outside the frame. Every pixel outside the window is -1 in
    the whole-lattice gather this stands for, so `compose_footprints` over
    windows gives exactly what `compose` gives over the whole lattice
    (final review I1): a 50 m grid at 30 degrees touches about a tenth of a
    ten-grid site's half-pitch lattice. Built tight by `footprint`.

    `eq=False`, as for `Seam`: an ndarray field.
    """

    row0: int
    row1: int
    col0: int
    col1: int
    ids: np.ndarray

    def __post_init__(self) -> None:
        shape = (self.row1 - self.row0, self.col1 - self.col0)
        if self.ids.shape != shape:
            raise ValueError(f"ids must be {shape} for this window, got {self.ids.shape}")

    @property
    def n_pixels(self) -> int:
        return int(self.ids.size)


def footprint(ids: np.ndarray, row0: int = 0, col0: int = 0) -> Footprint:
    """The tight window around the placed pixels of a block of cell ids.

    `ids` is `(rows, cols)` with its top-left pixel at lattice `(row0,
    col0)`: a whole-lattice gather reshaped to `(height, width)`, or a
    padded window around one frame. Only rows and columns that place a
    pixel (an id >= 0) are kept, so every edge of the window places one.
    With no placed pixel the footprint is empty, at `(row0, col0)`.
    """
    ids = np.asarray(ids)
    if ids.ndim != 2:
        raise ValueError(f"ids must be 2-D, got shape {ids.shape}")
    placed = ids >= 0
    rows = np.flatnonzero(placed.any(axis=1))
    cols = np.flatnonzero(placed.any(axis=0))
    if rows.size == 0:
        return Footprint(row0, row0, col0, col0, np.empty((0, 0), dtype=ids.dtype))
    r0, r1 = int(rows[0]), int(rows[-1]) + 1
    c0, c1 = int(cols[0]), int(cols[-1]) + 1
    return Footprint(row0 + r0, row0 + r1, col0 + c0, col0 + c1, ids[r0:r1, c0:c1].copy())


def compose_footprints(
    lattice: SiteLattice, layers: Sequence[tuple[Footprint, np.ndarray]]
) -> np.ndarray:
    """`compose`, each layer accumulated over its own window only (final review I1).

    Each layer is `(footprint, values)`, `values` the frame's `(ny, nx)`
    array. The same sums and counts in the same layer order as `compose`,
    so the result is bit-identical to `compose` over the whole-lattice
    gathers the footprints stand for. Raises ValueError for a window that
    is not on the lattice.
    """
    total = np.zeros((lattice.height, lattice.width), dtype=float)
    count = np.zeros((lattice.height, lattice.width), dtype=np.int64)
    for where, values in layers:
        if not (
            0 <= where.row0 <= where.row1 <= lattice.height
            and 0 <= where.col0 <= where.col1 <= lattice.width
        ):
            raise ValueError(
                f"window rows {where.row0}:{where.row1}, cols {where.col0}:{where.col1} "
                f"is not on the {lattice.height} x {lattice.width} lattice"
            )
        if where.n_pixels == 0:
            continue
        flat = np.asarray(values, dtype=float).reshape(-1)
        got = flat[np.clip(where.ids, 0, flat.size - 1)]
        ok = (where.ids >= 0) & np.isfinite(got)
        window = (slice(where.row0, where.row1), slice(where.col0, where.col1))
        total[window] += np.where(ok, got, 0.0)
        count[window] += ok
    out = np.full(lattice.n_pixels, np.nan, dtype=float)
    np.divide(total.reshape(-1), count.reshape(-1), out=out, where=count.reshape(-1) > 0)
    return out.reshape(lattice.height, lattice.width).astype(np.float32)


def site_axis(
    bounds: Iterable[tuple[float, float]], t0_ns: float, t1_ns: float, dz_ns: float
) -> ZAxis | None:
    """The union of the grids' `(start, end)` time bounds, clipped to `[t0_ns, t1_ns]`.

    The union is the envelope: a regular axis cannot have gaps. Returns None
    when no bounds are given or nothing remains after clipping.
    """
    spans = list(bounds)
    if not spans:
        return None
    lo = max(min(s[0] for s in spans), t0_ns)
    hi = min(max(s[1] for s in spans), t1_ns)
    if hi < lo:
        return None
    if hi == lo:
        return ZAxis(t0_ns=lo, dz_ns=dz_ns, nz=1)
    return ZAxis.from_range(lo, hi, dz_ns)


def grid_axis(site_z: ZAxis, bounds: tuple[float, float]) -> ZAxis | None:
    """The levels of `site_z` inside `bounds`, on `site_z`'s own lattice of levels.

    Returns None when no level is inside.
    """
    start, end = bounds
    dz = site_z.dz_ns
    k0 = max(0, math.ceil((start - site_z.t0_ns) / dz - _SNAP))
    k1 = min(site_z.nz - 1, math.floor((end - site_z.t0_ns) / dz + _SNAP))
    if k1 < k0:
        return None
    return ZAxis(t0_ns=site_z.t0_ns + k0 * dz, dz_ns=dz, nz=k1 - k0 + 1)


def window_on(z: ZAxis, top_ns: float, thickness_ns: float) -> SliceWindow | None:
    """The one place a site window becomes a grid window.

    Maps a time window onto `z`'s levels. Unlike `ZAxis.level_range` it
    returns None, not one clamped level, when the window misses the axis; a
    window overhanging an end is thinner. The `1e-6` snap keeps a grid axis
    offset from the site axis by whole levels from flooring one level low.
    """
    k0 = math.floor((top_ns - z.t0_ns) / z.dz_ns + _SNAP)
    k1 = k0 + max(1, round(thickness_ns / z.dz_ns))
    if k1 <= 0 or k0 >= z.nz:
        return None
    return SliceWindow(max(0, k0), min(k1, z.nz))


@dataclass(frozen=True, eq=False)
class Seam:
    """Two grids' facing strips. `a < b`; masks are `(ny, nx)` in their own frame.

    `eq=False`: the generated `__eq__`/`__hash__` over ndarray fields raise, so a
    Seam compares and hashes by identity instead.
    """

    a: str
    b: str
    mask_a: np.ndarray
    mask_b: np.ndarray


def _distance_to_footprint(cells: CubeFrame, other: CubeFrame) -> np.ndarray:
    """(ny, nx) distance of `cells`' centres from `other`'s footprint, in `other`'s metres."""
    xs = (np.arange(cells.nx, dtype=float) + 0.5) * cells.cell
    ys = (np.arange(cells.ny, dtype=float) + 0.5) * cells.cell
    gx, gy = np.meshgrid(xs, ys)
    x_hat, y_hat = cells.axes()
    origin = np.asarray(cells.origin, dtype=float)
    world = origin + gx.reshape(-1, 1) * x_hat + gy.reshape(-1, 1) * y_hat
    local = other.to_local(world)
    dx = np.maximum(np.maximum(-local[:, 0], local[:, 0] - other.nx * other.cell), 0.0)
    dy = np.maximum(np.maximum(-local[:, 1], local[:, 1] - other.ny * other.cell), 0.0)
    return np.hypot(dx, dy).reshape(cells.ny, cells.nx)


def seam_masks(
    frame_a: CubeFrame, frame_b: CubeFrame, width_m: float
) -> tuple[np.ndarray, np.ndarray]:
    """Cells of each frame whose centre lies within `width_m` of the other's footprint.

    Geometry only. Distance is measured in the other frame's local
    coordinates (0 inside its rectangle). All-False when the CRSs differ.
    """
    if frame_a.crs != frame_b.crs:
        return (
            np.zeros((frame_a.ny, frame_a.nx), dtype=bool),
            np.zeros((frame_b.ny, frame_b.nx), dtype=bool),
        )
    return (
        _distance_to_footprint(frame_a, frame_b) <= width_m,
        _distance_to_footprint(frame_b, frame_a) <= width_m,
    )


def find_seams(
    frames: Mapping[str, CubeFrame],
    coverages: Mapping[str, np.ndarray],
    spacings: Mapping[str, float],
    *,
    width_spacings: float = SEAM_WIDTH_SPACINGS,
    min_cells: int = MIN_SEAM_CELLS,
) -> tuple[Seam, ...]:
    """Every pair of grids with `min_cells` populated cells on each side of their seam.

    The strip width is `width_spacings` times the larger line spacing of the
    pair. Masks are restricted to populated cells (`coverage > 0`). Pairs
    come in id order, each with `a < b`.
    """
    seams = []
    ids = sorted(frames)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            width = width_spacings * max(spacings[a], spacings[b])
            mask_a, mask_b = seam_masks(frames[a], frames[b], width)
            mask_a = mask_a & (np.asarray(coverages[a]) > 0)
            mask_b = mask_b & (np.asarray(coverages[b]) > 0)
            if int(mask_a.sum()) >= min_cells and int(mask_b.sum()) >= min_cells:
                seams.append(Seam(a, b, mask_a, mask_b))
    return tuple(seams)


def background_level(
    values: np.ndarray, coverage: np.ndarray, mask: np.ndarray | None = None
) -> float | None:
    """Mean of the weakest `BACKGROUND_FRACTION` of `|values|` over populated cells.

    Populated means `coverage > 0` (and inside `mask` when given). The count
    kept is `ceil(0.75 * n)`, so one cell keeps itself. Returns None when no
    cell qualifies or the level is not positive.
    """
    use = np.asarray(coverage) > 0
    if mask is not None:
        use = use & np.asarray(mask, dtype=bool)
    magnitude = np.abs(np.asarray(values, dtype=float)[use])
    magnitude = magnitude[np.isfinite(magnitude)]
    if magnitude.size == 0:
        return None
    keep = max(1, math.ceil(BACKGROUND_FRACTION * magnitude.size - 1e-9))
    level = float(np.sort(magnitude)[:keep].mean())
    return level if level > 0.0 else None


def _components(ids: Sequence[str], seam_levels: Sequence[tuple]) -> list[list[str]]:
    """Connected groups of `ids` under the seam terms; singletons included."""
    parent = {g: g for g in ids}

    def find(g: str) -> str:
        while parent[g] != g:
            parent[g] = parent[parent[g]]
            g = parent[g]
        return g

    for a, b, *_ in seam_levels:
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for g in ids:
        groups.setdefault(find(g), []).append(g)
    return list(groups.values())


def edge_match_solve(
    levels: Mapping[str, float | None],
    seam_levels: Sequence[tuple[str, str, float, float, float]],
) -> dict[str, float]:
    """Gains per grid from a global weighted least squares over the seams.

    Each seam term is `(a, b, S_ab, S_ba, weight)`, one equation
    `x_a + ln S_ab = x_b + ln S_ba` in log gains. Every connected group is
    solved at once (minimum-norm, since a group has one free constant) and
    then anchored so its corrected backgrounds match the site's in the
    geometric mean. A group with no known level keeps its minimum-norm
    solution, so a lone grid with level None has gain 1. A final shift makes
    the geometric mean of all gains 1.
    """
    ids = sorted(levels)
    ln_level = {g: math.log(level) for g in ids if (level := levels[g])}
    ln_b_site = float(np.mean(list(ln_level.values()))) if ln_level else 0.0
    x = dict.fromkeys(ids, 0.0)
    for group in _components(ids, seam_levels):
        index = {g: i for i, g in enumerate(group)}
        terms = [s for s in seam_levels if s[0] in index and s[1] in index]
        if terms:
            design = np.zeros((len(terms), len(group)))
            rhs = np.zeros(len(terms))
            w = np.zeros(len(terms))
            for r, (a, b, s_ab, s_ba, weight) in enumerate(terms):
                design[r, index[a]] = 1.0
                design[r, index[b]] = -1.0
                rhs[r] = math.log(s_ba) - math.log(s_ab)
                w[r] = math.sqrt(weight)
            sol = np.linalg.lstsq(design * w[:, None], rhs * w, rcond=None)[0]
            for g, v in zip(group, sol):
                x[g] = float(v)
        known = [g for g in group if g in ln_level]
        if known:
            shift = ln_b_site - float(np.mean([x[g] + ln_level[g] for g in known]))
            for g in group:
                x[g] += shift
    mean_x = float(np.mean(list(x.values()))) if x else 0.0
    return {g: math.exp(x[g] - mean_x) for g in ids}


def normalise(
    method: str,
    slices: Mapping[str, tuple[np.ndarray, np.ndarray]],
    seams: Sequence[Seam] = (),
    manual: Mapping[str, float] | None = None,
) -> dict[str, tuple[float, float]]:
    """An affine `(a, b)` per grid, applied as `a * v + b`, manual multiplier folded in.

    `slices` maps grid id to `(values, coverage)`, binned and not filled.
    `"none"` gives `(m, 0)`; `"background"` gives each grid `B_site / B_i`;
    `"edge"` solves the seams globally (a seam whose strip has no positive
    level is dropped, the rest weighted by the smaller strip's cell count);
    `"histogram"` matches every grid's populated mean and standard deviation
    to the pooled ones, and a grid with zero spread or no populated cells
    gets `(1, 0)`. Raises ValueError on an unknown method.
    """
    if method not in NORMALISATION_METHODS:
        raise ValueError(
            f"unknown normalisation {method!r}; expected one of {NORMALISATION_METHODS}"
        )
    m = {g: (manual or {}).get(g, 1.0) for g in slices}
    if method == "none":
        return {g: (m[g], 0.0) for g in slices}
    if method == "histogram":
        return _histogram(slices, m)
    levels = {g: background_level(v, c) for g, (v, c) in slices.items()}
    terms: list[tuple[str, str, float, float, float]] = []
    if method == "edge":
        for s in seams:
            if s.a not in slices or s.b not in slices:
                continue
            s_ab = background_level(*slices[s.a], s.mask_a)
            s_ba = background_level(*slices[s.b], s.mask_b)
            if s_ab is None or s_ba is None:
                continue
            terms.append((s.a, s.b, s_ab, s_ba, float(min(s.mask_a.sum(), s.mask_b.sum()))))
    gains = edge_match_solve(levels, terms)
    return {g: (m[g] * gains[g], 0.0) for g in slices}


def _histogram(
    slices: Mapping[str, tuple[np.ndarray, np.ndarray]], m: Mapping[str, float]
) -> dict[str, tuple[float, float]]:
    populated = {}
    for g, (v, c) in slices.items():
        vals = np.asarray(v, dtype=float)[np.asarray(c) > 0]
        populated[g] = vals[np.isfinite(vals)]
    pooled = np.concatenate(list(populated.values())) if populated else np.empty(0)
    out = {}
    for g, vals in populated.items():
        if vals.size == 0 or pooled.size == 0 or not vals.std() > 0.0:
            out[g] = (m[g], 0.0)
            continue
        a = float(pooled.std() / vals.std())
        b = float(pooled.mean() - a * vals.mean())
        out[g] = (m[g] * a, m[g] * b)
    return out
