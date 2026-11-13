"""Magnetometer maps: a grid's readings binned and filled, and grids mosaicked.

The finishing (`plan_fill`, `finish_slice`) and the site lattice are the GPR
slice maths in `nsgeo.slices`, reused unchanged: a mag grid is a slice whose
cells are the mean of the readings that fall in them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from nsgeo.geometry.grid import Grid
from nsgeo.mag.file import MagFile
from nsgeo.slices import (
    CubeFrame,
    FinishSettings,
    SiteLattice,
    bilinear_taps,
    compose_footprints,
    finish_slice,
    fitting_lattice,
    footprint,
    plan_fill,
    slice_extent,
)

#: The default cell, an eighth of a metre: one reading interval at 8 readings per metre.
DEFAULT_CELL_M = 0.125


def bin_readings(frame: CubeFrame, world: np.ndarray, values: np.ndarray) -> np.ndarray:
    """float32 `(ny, nx)`: the mean of the readings in each cell, NaN where none.

    Readings outside the frame are dropped.
    """
    world = np.asarray(world, dtype=float).reshape(-1, 2)
    values = np.asarray(values, dtype=float)
    ids = frame.cell_index(world)
    keep = ids >= 0
    total = np.bincount(ids[keep], weights=values[keep], minlength=frame.n_cells)
    count = np.bincount(ids[keep], minlength=frame.n_cells)
    out = np.full(frame.n_cells, np.nan, dtype=np.float32)
    np.divide(total, count, out=out, where=count > 0, casting="unsafe")
    return out.reshape(frame.ny, frame.nx)


def grid_map(
    mag: MagFile, grid: Grid, cell: float, settings: FinishSettings
) -> tuple[CubeFrame, np.ndarray]:
    """The frame over `grid` and its finished float32 `(ny, nx)` map."""
    frame = CubeFrame.for_grid(grid, cell)
    world, values = mag.points(grid)
    binned = bin_readings(frame, world, values)
    weights = plan_fill(
        np.isfinite(binned),
        cell,
        settings.method,
        settings.max_distance_m,
        settings.search_radius_m,
    )
    return frame, finish_slice(binned, weights, cell, settings)


def mosaic(
    maps: Sequence[tuple[CubeFrame, np.ndarray]],
    cell: float,
    crs: str,
    *,
    max_pixels: int,
    max_covered: int,
) -> tuple[SiteLattice, np.ndarray]:
    """The maps on one north-up lattice in `crs`, overlaps averaged, NaN off every grid."""
    if not maps:
        raise ValueError("a mosaic needs at least one map")
    for frame, _ in maps:
        if frame.crs != crs:
            raise ValueError(f"a map in {frame.crs} cannot join a mosaic in {crs}")
    extents = [slice_extent(frame) for frame, _ in maps]
    lattice = fitting_lattice(extents, cell, crs, max_pixels, max_covered)
    layers = []
    for (frame, values), (xmin, ymin, xmax, ymax) in zip(maps, extents):
        # The lattice pixels around the frame's box, one more on every side so
        # an edge pixel whose centre is just outside still gets a tap.
        pixel = lattice.pixel
        col0 = max(0, math.floor((xmin - lattice.x0) / pixel) - 1)
        col1 = min(lattice.width, math.ceil((xmax - lattice.x0) / pixel) + 1)
        row0 = max(0, math.floor((lattice.y1 - ymax) / pixel) - 1)
        row1 = min(lattice.height, math.ceil((lattice.y1 - ymin) / pixel) + 1)
        rows, cols = row1 - row0, col1 - col0
        xs = lattice.x0 + (np.arange(col0, col1, dtype=float) + 0.5) * pixel
        ys = lattice.y1 - (np.arange(row0, row1, dtype=float) + 0.5) * pixel
        grid_x, grid_y = np.meshgrid(xs, ys)
        world = np.column_stack([grid_x.ravel(), grid_y.ravel()])
        taps = bilinear_taps(frame, world)
        layers.append((footprint(taps, rows, cols, row0, col0), values))
    return lattice, compose_footprints(lattice, layers)


def display_centre(values: np.ndarray) -> float:
    """The median of the finite values, 0.0 when there are none."""
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    return float(np.median(finite)) if finite.size else 0.0
