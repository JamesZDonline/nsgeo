"""Where a cube's cells are, and what its vertical axis means.

A CubeFrame is a raster frame -- integer cell counts and one cell size --
where a Grid is a survey frame with continuous extents and a line spacing.
They are separate types because a cube must exist for lines that belong to
no grid: binning consumes per-trace world coordinates and never learns that
the lines were parallel, so RTK-positioned paths need a frame no Grid
produced. `for_points` is that constructor.

Cells are square. A rectangular cell would let the along-line and
cross-line resolutions be tuned apart, which sounds useful and is not: it
bakes an acquisition artefact into the product, and the fill radius already
covers the real need.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from nsgeo.geometry.grid import Grid
    from nsgeo.velocity import VelocityModel


@dataclass(frozen=True)
class CubeFrame:
    """An affine raster frame in world coordinates.

    `azimuth` follows Grid exactly: degrees clockwise from CRS north to
    frame-local +Y. Sharing the convention is what lets `for_grid` copy it
    straight across.
    """

    origin: tuple[float, float]
    azimuth: float
    cell: float
    nx: int
    ny: int
    crs: str

    def __post_init__(self) -> None:
        if not self.cell > 0.0:
            raise ValueError(f"cell must be positive, got {self.cell}")
        if self.nx < 1 or self.ny < 1:
            raise ValueError(f"nx and ny must be >= 1, got {self.nx} x {self.ny}")

    @property
    def n_cells(self) -> int:
        return self.nx * self.ny

    def axes(self) -> tuple[np.ndarray, np.ndarray]:
        """Unit vectors of frame-local +X and +Y in world coordinates."""
        a = math.radians(self.azimuth)
        y_hat = np.array([math.sin(a), math.cos(a)])
        x_hat = np.array([math.cos(a), -math.sin(a)])
        return x_hat, y_hat

    def to_local(self, world: np.ndarray) -> np.ndarray:
        """(n, 2) world coordinates -> (n, 2) frame-local metres."""
        world = np.asarray(world, dtype=float)
        if world.ndim != 2 or world.shape[1] != 2:
            raise ValueError(f"expected (n, 2) world coordinates, got {world.shape}")
        x_hat, y_hat = self.axes()
        rel = world - np.asarray(self.origin, dtype=float)
        return np.column_stack([rel @ x_hat, rel @ y_hat])

    def cell_index(self, world: np.ndarray) -> np.ndarray:
        """(n, 2) world coordinates -> (n,) flat cell ids; -1 when outside.

        The flat id is `iy * nx + ix`, which is the column layout SliceCube
        stores. Points outside are -1 rather than clipped to the edge: a
        trace that missed the frame is not evidence about the nearest cell,
        and clipping would pile a whole excluded line onto one border row.

        A point exactly on the frame's own OUTER edge can land a hair on
        the wrong side of it: `to_local`'s `world - origin` subtraction,
        and (for a `for_points` frame) the origin's own construction by
        re-projecting a local coordinate back through the same rotation,
        take different chains of floating-point operations to reach the
        same point, so they need not cancel to the bit. The error this
        leaves scales with the coordinate magnitude, not with the cell --
        a UTM easting or northing (~1e6) carries far more absolute
        round-off than a toy coordinate does, and can exceed a realistic
        GPR cell size (0.05 m) outright. `tol` is sized to that magnitude
        and applied only to points that already floor to -1 or nx/ny: an
        interior cell boundary is never touched, and a point that floors
        inside the frame -- however close to an edge -- is left alone.

        The `64.0` multiplier is a bound, not a fit: an analytic error walk
        of the `to_local` / re-projection round trip admits 8-10 ulps of
        slack under adversarial rounding, and a sweep of `for_grid` frames
        over 3 UTM origins x 8 azimuths x 3 cell sizes x 3 extents found
        the worst case actually needed was 0.81 ulps -- so even the
        adversarial bound holds with room to spare, and 64 is chosen well
        above it rather than tuned to the sweep's own worst case. At UTM
        scale this is 5.7e-9 m, seven orders of magnitude below the
        smallest realistic cell, so it is far too small to swallow a
        genuine miss -- a real off-frame point misses by a cell fraction,
        not by ulps.

        A NaN local coordinate (a GPS dropout in a real DZT) or one whose
        magnitude, once divided by `cell`, would overflow `intp` -- far
        beyond any real survey, but reachable from corrupt input -- must
        never reach the `floor().astype(intp)` cast below: numpy leaves
        that cast undefined outside its range, so depending on the
        platform it can wrap into a small, VALID-looking cell id instead
        of landing safely outside the frame. `finite` masks such rows out
        deterministically, before the cast, so correctness never depends
        on which undefined behaviour a platform happens to choose.
        """
        world = np.asarray(world, dtype=float)
        local = self.to_local(world)
        position = local / self.cell
        bound = np.iinfo(np.intp).max / 4.0
        finite = (np.isfinite(position) & (np.abs(position) < bound)).all(axis=1)
        safe = np.where(finite[:, None], local, 0.0)

        ix = np.floor(safe[:, 0] / self.cell).astype(np.intp)
        iy = np.floor(safe[:, 1] / self.cell).astype(np.intp)

        tol = 64.0 * np.finfo(float).eps * np.maximum(1.0, np.abs(world).max(axis=1))
        ix = np.where((ix == -1) & (safe[:, 0] >= -tol), 0, ix)
        iy = np.where((iy == -1) & (safe[:, 1] >= -tol), 0, iy)
        ix = np.where((ix == self.nx) & (safe[:, 0] <= self.nx * self.cell + tol), self.nx - 1, ix)
        iy = np.where((iy == self.ny) & (safe[:, 1] <= self.ny * self.cell + tol), self.ny - 1, iy)

        inside = finite & (ix >= 0) & (ix < self.nx) & (iy >= 0) & (iy < self.ny)
        return np.where(inside, iy * self.nx + ix, -1)

    @classmethod
    def for_grid(cls, grid: Grid, cell: float) -> CubeFrame:
        """A frame covering `grid`, sharing its origin, azimuth and CRS.

        Extents round up, so a grid whose size is not a whole number of
        cells is fully covered rather than clipped short.
        """
        if not cell > 0.0:
            raise ValueError(f"cell must be positive, got {cell}")
        return cls(
            origin=grid.origin,
            azimuth=grid.azimuth,
            cell=cell,
            nx=max(1, int(math.ceil(grid.size_x / cell))),
            ny=max(1, int(math.ceil(grid.size_y / cell))),
            crs=grid.crs,
        )

    @classmethod
    def for_points(
        cls,
        world: np.ndarray,
        cell: float,
        crs: str,
        azimuth: float = 0.0,
        margin: float = 0.0,
    ) -> CubeFrame:
        """A frame covering scattered trace coordinates at a given azimuth.

        The constructor for lines that belong to no grid. `azimuth` is the
        caller's: choosing a good one for an arbitrary path is a separate
        problem, and defaulting to 0 gives an axis-aligned frame that is
        always correct if not always tight.
        """
        world = np.asarray(world, dtype=float)
        if world.ndim != 2 or world.shape[1] != 2 or world.shape[0] == 0:
            raise ValueError(f"expected a non-empty (n, 2) array, got {world.shape}")
        if not cell > 0.0:
            raise ValueError(f"cell must be positive, got {cell}")
        a = math.radians(azimuth)
        x_hat = np.array([math.cos(a), -math.sin(a)])
        y_hat = np.array([math.sin(a), math.cos(a)])
        px = world @ x_hat
        py = world @ y_hat
        lo_x = float(px.min()) - margin
        lo_y = float(py.min()) - margin
        hi_x = float(px.max()) + margin
        hi_y = float(py.max()) + margin
        origin = lo_x * x_hat + lo_y * y_hat
        # `+ 1`: nx/ny counts cells inclusively across lo..hi, not just the
        # (possibly fractional) number of whole cells floor() gives back.
        return cls(
            origin=(float(origin[0]), float(origin[1])),
            azimuth=azimuth,
            cell=cell,
            nx=max(1, int(math.floor((hi_x - lo_x) / cell)) + 1),
            ny=max(1, int(math.floor((hi_y - lo_y) / cell)) + 1),
            crs=crs,
        )


@dataclass(frozen=True)
class ZAxis:
    """The cube's vertical axis, in two-way travel time.

    Time, not depth, because that is what the instrument measures: depth is
    derived through a VelocityModel, so a cube built under one velocity
    relabels under another without rebinning. An elevation-referenced axis
    is designed for and not built -- nothing in the cube's shape assumes
    the axis is time, only this class does.
    """

    t0_ns: float
    dz_ns: float
    nz: int

    def __post_init__(self) -> None:
        if not self.dz_ns > 0.0:
            raise ValueError(f"dz_ns must be positive, got {self.dz_ns}")
        if self.nz < 1:
            raise ValueError(f"nz must be >= 1, got {self.nz}")

    @property
    def t_end_ns(self) -> float:
        return self.t0_ns + (self.nz - 1) * self.dz_ns

    def times_ns(self) -> np.ndarray:
        return self.t0_ns + np.arange(self.nz, dtype=float) * self.dz_ns

    def depths_m(self, velocity: VelocityModel) -> np.ndarray:
        return velocity.depth_at(self.times_ns())

    @classmethod
    def from_range(cls, t0_ns: float, t1_ns: float, dz_ns: float) -> ZAxis:
        if not dz_ns > 0.0:
            raise ValueError(f"dz_ns must be positive, got {dz_ns}")
        if not t1_ns > t0_ns:
            raise ValueError(f"t1_ns must exceed t0_ns, got {t0_ns} .. {t1_ns}")
        span = (t1_ns - t0_ns) / dz_ns
        # `span` need not land exactly on an integer even when t1_ns - t0_ns
        # is an exact multiple of dz_ns (0.3 / 0.1 in double precision does
        # not) -- plain floor() would then silently drop the final level
        # this method's own name promises to include. Snap to the nearest
        # integer only when the division is within float rounding of one;
        # a genuinely fractional span is never close enough to be affected.
        nearest = round(span)
        n_steps = nearest if math.isclose(span, nearest, rel_tol=1e-9) else math.floor(span)
        return cls(t0_ns=t0_ns, dz_ns=dz_ns, nz=n_steps + 1)

    def level_range(self, top_ns: float, thickness_ns: float) -> tuple[int, int]:
        """Half-open [k0, k1) for a window, INTERSECTED with the axis.

        The contract is intersection, not a clamped copy of the requested
        window: the returned range is genuinely thinner than requested at
        either end when the window overhangs the axis (e.g. `top_ns=-10`
        on a `t0_ns=0` axis returns `(0, 1)`, not a window shifted back to
        start at 0; a window that overhangs the far end similarly returns
        fewer levels than `thickness_ns` implies, e.g. `(96, 100)` on a
        100-level axis for `top=48, thickness=4`). It never returns an
        empty range: a window entirely off the end still yields one level,
        because a viewer asking for a slice needs a slice, not a
        zero-column array to special-case.

        This matters beyond this function: a caller that wants to know
        the depth window actually averaged -- the plugin's depth readout
        is exactly this -- must derive it from the returned `(k0, k1)`,
        never by re-deriving it from `(top_ns, thickness_ns)`, because
        those two need not agree with what was actually returned.
        """
        if not thickness_ns > 0.0:
            raise ValueError(f"thickness_ns must be positive, got {thickness_ns}")
        k0 = int(math.floor((top_ns - self.t0_ns) / self.dz_ns))
        k1 = k0 + max(1, int(round(thickness_ns / self.dz_ns)))
        k0 = max(0, min(k0, self.nz - 1))
        k1 = max(k0 + 1, min(k1, self.nz))
        return k0, k1
