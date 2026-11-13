"""A Grad601 file on a mag grid: its readings, per-traverse corrections and world points."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from nsgeo.geometry.grid import Grid
from nsgeo.mag.grad601 import mark_missing, read_grad601
from nsgeo.mag.setup import MagSetup
from nsgeo.mag.traverses import Traverse, traverses

#: How many files stay resident. A 60 x 240 grid is about 115 kB, so six
#: grids and their marked copies fit with room to spare.
_CACHE_SIZE = 16


@lru_cache(maxsize=_CACHE_SIZE)
def _read_raw(path_str: str, size: int, mtime_ns: int) -> np.ndarray:
    """Cached file read. `size` and `mtime_ns` key the entry so an edited file is re-read."""
    raw = read_grad601(Path(path_str))
    raw.setflags(write=False)
    return raw


@lru_cache(maxsize=_CACHE_SIZE)
def _read_marked(path_str: str, size: int, mtime_ns: int, missing_run: int) -> np.ndarray:
    marked = mark_missing(_read_raw(path_str, size, mtime_ns), missing_run)
    marked.setflags(write=False)
    return marked


def clear_mag_cache() -> None:
    _read_raw.cache_clear()
    _read_marked.cache_clear()


@dataclass(frozen=True, eq=False)
class MagFile:
    """One magnetometer file on one mag grid. Equality is identity (`eq=False`), as for `Line`.

    `scales` and `shifts` hold one correction per traverse (a row of the file),
    in the sense `GridPlacement.scale` and `.travel_shift` have for a GPR line.
    """

    path: Path
    grid_id: str
    setup: MagSetup
    n_rows: int
    n_readings: int
    scales: tuple[float, ...]
    shifts: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.scales) != self.n_rows or not all(
            math.isfinite(s) and s > 0 for s in self.scales
        ):
            raise ValueError(
                f"scales must be {self.n_rows} finite numbers above 0, one per traverse"
            )
        if len(self.shifts) != self.n_rows or not all(math.isfinite(s) for s in self.shifts):
            raise ValueError(f"shifts must be {self.n_rows} finite numbers, one per traverse")

    @classmethod
    def open(cls, path: Path, grid_id: str, setup: MagSetup) -> MagFile:
        """Read the file once for its shape. Starts uncorrected."""
        path = Path(path)
        stat = path.stat()
        n_rows, n_readings = _read_raw(str(path), stat.st_size, stat.st_mtime_ns).shape
        return cls(
            path=path,
            grid_id=grid_id,
            setup=setup,
            n_rows=int(n_rows),
            n_readings=int(n_readings),
            scales=(1.0,) * int(n_rows),
            shifts=(0.0,) * int(n_rows),
        )

    def raw(self) -> np.ndarray:
        """The file as read, zeros kept. Read-only and cached."""
        stat = self.path.stat()
        return _read_raw(str(self.path), stat.st_size, stat.st_mtime_ns)

    def readings(self) -> np.ndarray:
        """The readings with runs of missing data as NaN. Read-only and cached."""
        stat = self.path.stat()
        return _read_marked(str(self.path), stat.st_size, stat.st_mtime_ns, self.setup.missing_run)

    def traverses(self, grid: Grid) -> tuple[Traverse, ...]:
        return traverses(self.setup, grid, self.n_rows, self.n_readings, self.scales, self.shifts)

    def local_points(self, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
        """Every finite reading as ((m, 2) grid-local metres, (m,) values), in walked order."""
        readings = self.readings()
        per_metre = self.setup.readings_per_metre
        xy: list[np.ndarray] = []
        values: list[np.ndarray] = []
        for t in self.traverses(grid):
            row = t.walked(readings[t.row])
            keep = np.isfinite(row)
            xy.append(t.placement.local(self.n_readings, per_metre)[keep])
            values.append(row[keep])
        if not xy:
            return np.empty((0, 2)), np.empty(0)
        return np.concatenate(xy), np.concatenate(values)

    def points(self, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
        """Every finite reading as ((m, 2) world coordinates, (m,) values)."""
        local, values = self.local_points(grid)
        return grid.to_world(local), values
