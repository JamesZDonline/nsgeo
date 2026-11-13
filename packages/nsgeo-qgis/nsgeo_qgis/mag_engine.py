"""The magnetometer maps behind the Mag panel: cached per grid, then mosaicked.

No Qt and no `qgis` here, so the cache and the mosaic can be tested on their
own. A grid's map costs a fraction of a second to a second (plan call P10), so
a map is kept for as long as nothing it was made from has changed: the file
object, the file's size and time stamp on disk, the grid's placement and the
settings. Moving a grid therefore draws it afresh, and dragging the cell back
to a value already seen costs nothing.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from nsgeo.geometry import Grid
from nsgeo.mag import DEFAULT_CELL_M, MagFile, display_centre, grid_map, mosaic
from nsgeo.render import PercentileClip
from nsgeo.slices import CubeFrame, SiteLattice, limit_over_slices

from nsgeo_qgis.slices_plan import SITE_MAX_COVERED_PIXELS, SITE_MAX_PIXELS, SliceFinish

#: Half the display range is this percentile of |value - centre| (plan call P12).
MAG_STRETCH_PERCENTILE = 95.0
#: Kriging out to three quarters of the traverse spacing, unsmoothed (P15).
DEFAULT_MAG_FINISH = SliceFinish(method="kriging", max_distance_spacings=0.75)


@dataclass(frozen=True)
class MagSettings:
    cell: float = DEFAULT_CELL_M
    finish: SliceFinish = DEFAULT_MAG_FINISH


@dataclass(frozen=True, eq=False)
class MagMosaic:
    """The maps drawn together on one north-up lattice."""

    array: np.ndarray  # (H, W) float32, NaN nodata
    lattice: SiteLattice
    grids: tuple[str, ...]  # drawn, in site order
    left_out: tuple[str, ...]  # in another CRS (plan call P11)

    def centre(self) -> float:
        return display_centre(self.array)

    def limit(self) -> float:
        return limit_over_slices(
            (self.array - self.centre(),), PercentileClip(MAG_STRETCH_PERCENTILE)
        )


def _grid_key(grid: Grid) -> tuple[Any, ...]:
    return (grid.id, grid.origin, grid.azimuth, grid.size_x, grid.size_y, grid.crs)


class MagEngine:
    def __init__(self, *, max_entries: int = 32) -> None:
        self._max = max(1, int(max_entries))
        self._maps: OrderedDict[tuple[Any, ...], tuple[CubeFrame, np.ndarray]] = OrderedDict()

    def grid_map(
        self, mag: MagFile, grid: Grid, settings: MagSettings
    ) -> tuple[CubeFrame, np.ndarray]:
        """The frame over `grid` and its finished map, computed once per input set."""
        stat = os.stat(mag.path)
        key = (mag, stat.st_size, stat.st_mtime_ns, _grid_key(grid), settings)
        hit = self._maps.get(key)
        if hit is not None:
            self._maps.move_to_end(key)
            return hit
        finish = settings.finish.in_metres(mag.setup.spacing_m)
        made = grid_map(mag, grid, settings.cell, finish)
        self._maps[key] = made
        while len(self._maps) > self._max:
            self._maps.popitem(last=False)
        return made

    def mosaic(
        self, items: Sequence[tuple[MagFile, Grid]], settings: MagSettings
    ) -> MagMosaic | None:
        """Every grid in `items` on one lattice, in the CRS of the first.
        A grid in another CRS is left out and named. None for no items."""
        if not items:
            return None
        crs = items[0][1].crs
        drawn = [(m, g) for m, g in items if g.crs == crs]
        left_out = tuple(g.id for _, g in items if g.crs != crs)
        maps = [self.grid_map(m, g, settings) for m, g in drawn]
        lattice, array = mosaic(
            maps,
            settings.cell,
            crs,
            max_pixels=SITE_MAX_PIXELS,
            max_covered=SITE_MAX_COVERED_PIXELS,
        )
        return MagMosaic(array, lattice, tuple(g.id for _, g in drawn), left_out)

    def clear(self) -> None:
        self._maps.clear()
