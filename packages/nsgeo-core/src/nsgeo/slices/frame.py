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

        A point exactly on a frame's near edge -- e.g. one `for_points` sized
        the frame around -- can land a hair below 0.0 in local coordinates:
        `to_local` reaches it by a different chain of floating-point
        rotations than whatever produced the origin, so the two need not
        cancel to the bit. `eps` absorbs that round-off without opening the
        door to real misses, which in practice sit whole cells away.
        """
        local = self.to_local(world)
        eps = 1e-9 * self.cell
        ix = np.floor((local[:, 0] + eps) / self.cell).astype(np.intp)
        iy = np.floor((local[:, 1] + eps) / self.cell).astype(np.intp)
        inside = (ix >= 0) & (ix < self.nx) & (iy >= 0) & (iy < self.ny)
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
        # nextafter keeps a point exactly on the far edge inside the frame:
        # floor((hi - lo) / cell) would otherwise index one cell past the end.
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
        return cls(t0_ns=t0_ns, dz_ns=dz_ns, nz=int(math.floor((t1_ns - t0_ns) / dz_ns)) + 1)

    def level_range(self, top_ns: float, thickness_ns: float) -> tuple[int, int]:
        """Half-open [k0, k1) for a window, clamped to the axis.

        Never returns an empty range: a window entirely off the end still
        yields one level, because a viewer asking for a slice needs a
        slice, not a zero-column array to special-case.
        """
        if not thickness_ns > 0.0:
            raise ValueError(f"thickness_ns must be positive, got {thickness_ns}")
        k0 = int(math.floor((top_ns - self.t0_ns) / self.dz_ns))
        k1 = k0 + max(1, int(round(thickness_ns / self.dz_ns)))
        k0 = max(0, min(k0, self.nz - 1))
        k1 = max(k0 + 1, min(k1, self.nz))
        return k0, k1
