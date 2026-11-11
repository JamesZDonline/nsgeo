"""The site view's numpy core: one lattice, one window mapping, seams, normalisation.

A site is several grids shown as one map. Everything here is pure numpy and
does no I/O, so the plugin only has to feed it arrays.

* `SiteLattice` -- the common north-up pixel lattice (spec 4.7), at the cell
  size whatever a grid's bearing; `Footprint`, `footprint` and
  `compose_footprints` sample each grid-local slice onto it with the
  bilinear rule (`nsgeo.slices.resample`).
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
from nsgeo.slices.resample import Taps, max_pool_counts, sample, sample_counts

NORMALISATION_METHODS = ("none", "background", "edge", "histogram")
BACKGROUND_FRACTION = 0.75
SEAM_WIDTH_SPACINGS = 1.5
MIN_SEAM_CELLS = 20

_SNAP = 1e-6  # levels: window and axis snapping


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


def covered_pixels(extents: Sequence[tuple[float, float, float, float]], pixel: float) -> int:
    """About how many lattice pixels the grids' windows hold together at `pixel`.

    The sum over extents of `ceil(width / pixel) * ceil(height / pixel)`: what
    the gathers hold taps for, and what a compose samples.
    """
    total = 0
    for xmin, ymin, xmax, ymax in extents:
        total += max(1, math.ceil((xmax - xmin) / pixel)) * max(1, math.ceil((ymax - ymin) / pixel))
    return total


def fitting_lattice(
    extents: Sequence[tuple[float, float, float, float]],
    cell: float,
    crs: str,
    max_pixels: int,
    max_covered: int,
) -> SiteLattice:
    """`SiteLattice.covering` at `cell * 2**k`, for the smallest `k >= 0` that fits.

    Fits means the lattice has at most `max_pixels` pixels (what the compose
    accumulates) and the grids' windows hold at most `max_covered` together
    (`covered_pixels`: what the gathers and the sampling cost). Doubling
    keeps each coarser pixel a whole number of cells, so the preview's
    lattice nests on the full one.

    Raises ValueError for limits no pitch can meet: a lattice anchored on
    multiples of its pixel is up to 2 x 2 pixels even for a point, and each
    extent covers at least one.
    """
    if max_pixels < 4 or max_covered < len(extents):
        raise ValueError(
            f"limits that can never fit: max_pixels={max_pixels}, "
            f"max_covered={max_covered} for {len(extents)} extents"
        )
    pixel = cell
    while True:
        lattice = SiteLattice.covering(extents, pixel, crs)
        if lattice.n_pixels <= max_pixels and covered_pixels(extents, pixel) <= max_covered:
            return lattice
        pixel *= 2.0


def finest_fitting_cell(
    extents: Sequence[tuple[float, float, float, float]],
    cell: float,
    crs: str,
    max_pixels: int,
    max_covered: int,
) -> float:
    """The finest cell, in whole centimetres above `cell`, the site draws in full at.

    Steps up from `cell` in 0.01 m: the first `c = n / 100 > cell` for which
    `fitting_lattice` keeps `c` itself (under both limits). So the answer is
    rounded up to 0.01 m and the cell one step finer does not fit, unless
    that is the current cell. Raises ValueError for limits no pitch can meet.
    """
    fitting_lattice(extents, cell, crs, max_pixels, max_covered)  # validates the limits
    n = math.floor(cell * 100.0 + 1e-9) + 1
    while True:
        candidate = round(n / 100.0, 2)
        if fitting_lattice(extents, candidate, crs, max_pixels, max_covered).pixel == candidate:
            return candidate
        n += 1


def stretching_grids(
    extents: Mapping[str, tuple[float, float, float, float]],
    cell: float,
    crs: str,
    max_pixels: int,
    max_covered: int,
    *,
    most: int = 3,
) -> list[str]:
    """The grids whose omission alone lets the site draw at full detail at `cell`.

    Full detail means under both limits (`fitting_lattice` keeps `cell`).
    Largest cut of the lattice's pixel count first, at most `most`; empty for
    a single grid or when no one grid's omission is enough.
    """
    if len(extents) < 2:
        return []
    ids = list(extents)
    whole = SiteLattice.covering([extents[g] for g in ids], cell, crs).n_pixels
    cuts: list[tuple[int, str]] = []
    for grid_id in ids:
        rest = [extents[g] for g in ids if g != grid_id]
        if fitting_lattice(rest, cell, crs, max_pixels, max_covered).pixel != cell:
            continue
        cuts.append((whole - SiteLattice.covering(rest, cell, crs).n_pixels, grid_id))
    cuts.sort(key=lambda c: -c[0])
    return [g for _, g in cuts[:most]]


@dataclass(frozen=True, eq=False)
class Footprint:
    """Where one layer lands on a lattice: a window, and the taps of its pixels.

    The window is lattice rows `[row0, row1)` and columns `[col0, col1)`;
    `taps` holds the bilinear taps (`nsgeo.slices.resample`) of its pixel
    centres, row-major over the window, so `taps.n` is the window's pixel
    count. Every pixel outside the window is outside the frame, so
    `compose_footprints` works over windows alone (final review I1): a 50 m
    grid at 30 degrees touches a small part of a ten-grid site's lattice.
    Built tight by `footprint`.

    `eq=False`, as for `Seam`: the taps hold ndarrays.
    """

    row0: int
    row1: int
    col0: int
    col1: int
    taps: Taps

    def __post_init__(self) -> None:
        n = (self.row1 - self.row0) * (self.col1 - self.col0)
        if self.taps.n != n:
            raise ValueError(f"taps must hold {n} points for this window, got {self.taps.n}")

    @property
    def n_pixels(self) -> int:
        return int(self.taps.n)


def footprint(taps: Taps, rows: int, cols: int, row0: int = 0, col0: int = 0) -> Footprint:
    """The tight window around the inside points of a block of taps.

    `taps` is row-major over a `(rows, cols)` block whose top-left pixel is
    at lattice `(row0, col0)`: a whole-lattice gather, or a padded window
    around one frame. Only rows and columns holding a point with
    `taps.inside` are kept, so every edge of the window places one. With
    none the footprint is empty, at `(row0, col0)`.
    """
    if taps.n != rows * cols:
        raise ValueError(f"taps must hold {rows * cols} points for {rows} x {cols}, got {taps.n}")
    inside = taps.inside.reshape(rows, cols)
    placed_rows = np.flatnonzero(inside.any(axis=1))
    placed_cols = np.flatnonzero(inside.any(axis=0))
    if placed_rows.size == 0:
        return Footprint(row0, row0, col0, col0, taps.take(np.empty(0, dtype=np.intp)))
    r0, r1 = int(placed_rows[0]), int(placed_rows[-1]) + 1
    c0, c1 = int(placed_cols[0]), int(placed_cols[-1]) + 1
    index = np.arange(rows * cols, dtype=np.intp).reshape(rows, cols)[r0:r1, c0:c1].ravel()
    return Footprint(row0 + r0, row0 + r1, col0 + c0, col0 + c1, taps.take(index))


def compose_footprints(
    lattice: SiteLattice,
    layers: Sequence[tuple[Footprint, np.ndarray]],
    *,
    counts: bool = False,
    cells_per_pixel: int = 1,
) -> np.ndarray:
    """Sample each layer over its own window and average the overlaps.

    Each layer is `(footprint, values)`, `values` the frame's `(ny, nx)`
    array. A layer is sampled bilinearly (`sample`), or as whole counts
    (`sample_counts`) when `counts`. A pixel is the mean of the finite
    samples covering it, NaN where none do. Accumulated in float32 with a
    uint8 count (a pixel is covered by a handful of grids), so a tick holds
    no float64 lattice. Returns float32 `(height, width)`. Raises ValueError
    for a window that is not on the lattice.

    `cells_per_pixel` is how many cells a pixel spans (a preview's 2**k).
    Above 1, counts are first max-pooled (`max_pool_counts`) over enough
    cells that every cell lies within some pixel's corners, so no line is
    hidden between pixels; amplitudes are untouched.
    """
    take = sample_counts if counts else sample
    reach = math.ceil(cells_per_pixel / math.sqrt(2.0)) if counts and cells_per_pixel > 1 else 0
    total = np.zeros((lattice.height, lattice.width), dtype=np.float32)
    count = np.zeros((lattice.height, lattice.width), dtype=np.uint8)
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
        if reach:
            values = max_pool_counts(values, reach)
        got = take(values, where.taps).reshape(where.row1 - where.row0, where.col1 - where.col0)
        ok = np.isfinite(got)
        window = (slice(where.row0, where.row1), slice(where.col0, where.col1))
        total[window] += np.where(ok, got, np.float32(0.0))
        count[window] += ok
    out = np.full((lattice.height, lattice.width), np.nan, dtype=np.float32)
    np.divide(total, count, out=out, where=count > 0)
    return out


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
