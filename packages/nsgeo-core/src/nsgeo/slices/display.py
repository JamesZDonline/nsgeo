"""What a slice viewer and a slice exporter need, and nothing a binner does.

Three jobs, each deferred out of M10 because it had no caller there and
this plan gives it one:

* planning the set of windows a stack of slices is cut at, which is the
  one place spec 6.6's independent `(thickness, step)` pair becomes a
  finite list -- the dock's navigation and the exporter's bands are the
  same plan read at different steps;
* saying, in both units, what a window ACTUALLY averaged, derived from
  `(k0, k1)` and never from the `(top_ns, thickness_ns)` that produced
  them;
* the display stretch shared across a cube, and the north-up resample an
  export writes through.

Pure numpy, like the rest of the core.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from nsgeo.render import Normalizer
from nsgeo.slices.cube import SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis, slice_extent
from nsgeo.velocity import VelocityModel


@dataclass(frozen=True)
class SliceWindow:
    """A half-open level range `[k0, k1)`, the unit a slice is cut from.

    Levels, not nanoseconds: the conversion belongs to one `ZAxis`, and
    carrying times here would let a window outlive the axis that gave it
    meaning -- which is precisely the stale-plan hazard the binner's own
    guard exists for.
    """

    k0: int
    k1: int

    def __post_init__(self) -> None:
        if self.k0 < 0:
            raise ValueError(f"k0 must be >= 0, got {self.k0}")
        if self.k1 <= self.k0:
            raise ValueError(f"a window must hold at least one level, got {self.k0}..{self.k1}")

    @property
    def n_levels(self) -> int:
        return self.k1 - self.k0


def plan_windows(z: ZAxis, thickness_levels: int, step_levels: int) -> tuple[SliceWindow, ...]:
    """Every window of `thickness_levels`, starting every `step_levels`.

    Spec 6.6: thickness and step are independent and nothing assumes
    slices tile. `step == thickness` gives abutting windows; `step <
    thickness` gives the overlapping stack that is the standard practice
    and the default. The count is spec 9.4's band formula exactly --
    `(nz - thickness) // step + 1` -- so a GeoTIFF's band count and the
    dock's slice count are the same number by construction rather than by
    two agreeing implementations.

    Only whole windows: a trailing partial window would be thinner than
    every other band in the same file, and a reader comparing bands has no
    way to see that from the pixels.
    """
    if thickness_levels < 1:
        raise ValueError(f"thickness_levels must be >= 1, got {thickness_levels}")
    if step_levels < 1:
        raise ValueError(f"step_levels must be >= 1, got {step_levels}")
    if thickness_levels >= z.nz:
        return (SliceWindow(0, z.nz),)
    tops = range(0, z.nz - thickness_levels + 1, step_levels)
    return tuple(SliceWindow(k, k + thickness_levels) for k in tops)


def window_times_ns(z: ZAxis, window: SliceWindow) -> tuple[float, float]:
    """(first, last) two-way time of the levels the window averages.

    `(n_levels - 1) * dz` wide, not `n_levels * dz`: a level is a point
    sample, not a bin. `plan_line` resamples each level at its exact time
    by linear interpolation between the two nearest recorded samples, so
    averaging n of them averages n points spanning n-1 intervals. The
    off-by-one version overstates every window by one sample interval and,
    at thickness 1, claims a range where there is a single sample.
    """
    if window.k1 > z.nz:
        raise ValueError(f"window {window.k0}..{window.k1} exceeds the axis ({z.nz} levels)")
    return (z.t0_ns + window.k0 * z.dz_ns, z.t0_ns + (window.k1 - 1) * z.dz_ns)


def window_depths_m(z: ZAxis, window: SliceWindow, velocity: VelocityModel) -> tuple[float, float]:
    """The same window in metres, through the velocity model."""
    lo, hi = window_times_ns(z, window)
    depths = velocity.depth_at(np.array([lo, hi], dtype=float))
    return (float(depths[0]), float(depths[1]))


def window_label(z: ZAxis, window: SliceWindow, velocity: VelocityModel | None = None) -> str:
    """`12.0-16.0 ns / 0.60-0.80 m`, or the ns half alone with no velocity.

    Always the window's full range, never its centre: spec 6.6's reason is
    that with overlapping slices the extent of what is being averaged is
    the thing a reader would otherwise mistake for vertical resolution.
    Derived from `window`, which is what `ZAxis.level_range` returned --
    a label rebuilt from the requested top and thickness would claim a
    window the axis refused to give.
    """
    lo, hi = window_times_ns(z, window)
    text = f"{lo:.1f}-{hi:.1f} ns"
    if velocity is not None:
        lo_m, hi_m = window_depths_m(z, window, velocity)
        text += f" / {lo_m:.2f}-{hi_m:.2f} m"
    return text


def limit_over_slices(slices: Iterable[np.ndarray], clip: Normalizer) -> float:
    """`clip`'s limit measured over every finite value in `slices`.

    Nodata is dropped HERE rather than left to the normaliser, because
    `PercentileClip` and `UnipolarClip` both subsample with a plain stride
    BEFORE filtering non-finite values. On a slice that is ~80% nodata --
    the ordinary case at 0.5 m line spacing and 0.10 m cells, spec 6.4 --
    that would spend four fifths of the sampling budget on NaN and measure
    the percentile from what little survived.
    """
    finite: list[np.ndarray] = []
    for item in slices:
        flat = np.asarray(item, dtype=float).ravel()
        finite.append(flat[np.isfinite(flat)])
    if not finite:
        raise ValueError("limit_over_slices needs at least one slice")
    if all(part.size == 0 for part in finite):
        return clip.limit(np.array([], dtype=float))
    return clip.limit(np.concatenate(finite))


def shared_limit(cube: SliceCube, thickness_levels: int, clip: Normalizer) -> float:
    """One display limit for the whole cube, at the thickness being shown.

    Spec 8: shared across the cube by default so depths stay comparable.
    The thickness is an argument and not a detail, because the stretch is
    a property of `(cube, thickness)` and NOT of the cube: a window mean
    has far lower variance than the levels it averages, so measuring over
    `cube.mean` gives a limit that is systematically too high. On one
    realistic cube `UnipolarClip().limit(cube.mean)` returned 2.59 where
    the correct limit for the displayed 10-level slice was 0.87 -- every
    slice then renders at about a third of its intended brightness,
    identically at every depth, so it reads as dim data rather than as a
    wrong limit. M10 recorded this on `UnipolarClip` and shipped no
    helper, for want of a caller; this is the helper, and the caller is
    the Slices dock.

    Windows abut (`step == thickness`), so every level contributes exactly
    once and no depth is weighted more heavily than another -- including
    the tail: `plan_windows` emits whole windows only, because its output
    is also the GeoTIFF's bands and bands of unequal thickness are not
    comparable (spec 9.4). A stretch is a measurement rather than an
    export, so the tail gets a final, thinner window instead of being
    dropped: at nz=181 and thickness=23 that is 20 levels -- and on a
    real cube those were the BRIGHTEST levels in it, so excluding them
    would leave a deep reflector clipped against a stretch it never
    contributed to. A thin end window is also exactly what the viewer
    produces there: `ZAxis.level_range` returns a genuinely thinner
    window at either end of the axis.
    """
    windows = list(plan_windows(cube.z, thickness_levels, thickness_levels))
    if windows[-1].k1 < cube.z.nz:
        windows.append(SliceWindow(windows[-1].k1, cube.z.nz))
    return limit_over_slices((cube.slice_levels(w.k0, w.k1) for w in windows), clip)


def to_north_up(
    values: np.ndarray, frame: CubeFrame
) -> tuple[np.ndarray, tuple[float, float, float, float, float, float]]:
    """Resample a grid-local slice into a north-up raster and its geotransform.

    Spec 3 keeps cells grid-local so a cell column draws from a consistent
    set of traces, and resamples north-up only on the way out, because
    rotated GeoTIFFs are second-class in GDAL and QGIS. This is that one
    resample.

    Returns `(array, geotransform)` where `array` is (h, w) float32 with
    NaN outside the frame, and `geotransform` is GDAL's six-tuple
    `(origin_x, pixel_w, 0, origin_y, 0, -pixel_h)` anchored at the box's
    TOP-LEFT corner.

    Two things to get right, in the order they bite:

    * **Row 0 is north.** A raster's rows run south (the geotransform's
      y pixel size is negative) while a `CubeFrame`'s y index 0 is its
      southern edge, because frame-local +Y is north at azimuth 0. The
      output is therefore the frame's rows reversed, exactly, for an
      axis-aligned frame. Getting this wrong mirrors every slice
      vertically and produces an image that looks entirely plausible.
    * **Outside is nodata, never the nearest cell.** A rotated frame does
      not fill its own bounding box; clamping the corners to the nearest
      in-frame value would smear a real edge out across ground that was
      never surveyed.

    Nearest neighbour, not bilinear: these values are already cell means
    over real traces, and `fill` (spec 6.4) is the one place smoothing is
    a decision the user makes with a radius they can see. Interpolating
    again here would invent structure below the cell size and do it
    invisibly.
    """
    values = np.asarray(values, dtype=float)
    if values.shape != (frame.ny, frame.nx):
        raise ValueError(
            f"values must be {(frame.ny, frame.nx)} to match the frame, got {values.shape}"
        )
    xmin, ymin, xmax, ymax = slice_extent(frame)
    cell = frame.cell
    # `(xmax - xmin) / cell` is an exact integer for an axis-aligned frame,
    # but in floating point it lands a few ulps above one, so a plain
    # ceil() adds a phantom all-nodata row and column. Snap the ratio --
    # scale-free, unlike a tolerance in metres. Measured before the fix: a
    # cell=0.1, nx=29 frame produced a (13, 30) raster, and 102 of 1000
    # widths tripped at that cell size.
    #
    # A FIXED epsilon on the ratio is not enough on its own: `xmin`/`xmax`
    # come out of `slice_extent`'s own arithmetic on `frame.origin`, and
    # the subtraction that cancels their shared magnitude loses more ulps
    # the larger that magnitude is -- the same lesson `cell_index`'s own
    # boundary tolerance is built around. At a UTM-scale origin (~5e5-5e6)
    # a plain `1e-9` is itself too small (measured residual 1.86e-9 to
    # 3.73e-9 above the true integer at cell=0.1 and cell=0.05), so the
    # bound is scaled by the same `64 * eps * max(1, |coord|)` margin
    # `cell_index` uses, converted from metres to cells by dividing by
    # `cell`.
    eps = 64.0 * np.finfo(float).eps * max(1.0, abs(xmin), abs(xmax), abs(ymin), abs(ymax)) / cell
    width = max(1, int(math.ceil((xmax - xmin) / cell - eps)))
    height = max(1, int(math.ceil((ymax - ymin) / cell - eps)))

    # Cell CENTRES, so a sample lands in the middle of its output pixel
    # rather than on a boundary where round-off decides which cell it
    # reads -- the same reason `cell_index` has its own edge tolerance.
    xs = xmin + (np.arange(width, dtype=float) + 0.5) * cell
    ys = ymax - (np.arange(height, dtype=float) + 0.5) * cell  # row 0 is north
    grid_x, grid_y = np.meshgrid(xs, ys)
    world = np.column_stack([grid_x.ravel(), grid_y.ravel()])

    ids = frame.cell_index(world)
    flat = values.reshape(-1)
    # `ids` is -1 outside; clip only so the gather is in-bounds, and let
    # `where` discard those rows. Indexing with a raw -1 would silently
    # read the frame's LAST cell instead.
    gathered = flat[np.clip(ids, 0, flat.size - 1)]
    out = np.where(ids >= 0, gathered, np.nan).reshape(height, width)
    return out.astype(np.float32), (xmin, cell, 0.0, ymax, 0.0, -cell)
