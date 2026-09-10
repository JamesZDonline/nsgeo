"""Profile, Line, and Site.

Ownership runs one way: a Line owns its Profiles, and a Profile holds no
back-reference. That keeps Profile a pure, picklable, trivially testable data
object with no cycles.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import Placement
from nsgeo.io.dzt import DztHeader, read_header, read_samples, trace_count

#: How many lines' sample arrays stay resident. A 30x30 m grid at 0.5 m
#: spacing is about 100 MB in total, so a bound of 16 lines is generous
#: while still preventing unbounded growth over a long session.
_CACHE_SIZE = 16


@dataclass(frozen=True)
class Profile:
    """One channel of one radargram. `data` is raw and never mutated."""

    data: np.ndarray
    header: DztHeader

    @property
    def n_samples(self) -> int:
        return int(self.data.shape[0])

    @property
    def n_traces(self) -> int:
        return int(self.data.shape[1])


@lru_cache(maxsize=_CACHE_SIZE)
def _load_profiles(path_str: str, size: int, mtime_ns: int) -> tuple[Profile, ...]:
    """Cached sample load. `size` and `mtime_ns` are part of the key so an
    edited file is not served from a stale entry."""
    path = Path(path_str)
    header = read_header(path)
    stack = read_samples(path, header)
    profiles: list[Profile] = []
    for channel in stack:
        channel.setflags(write=False)
        profiles.append(Profile(data=channel, header=header))
    return tuple(profiles)


def clear_profile_cache() -> None:
    _load_profiles.cache_clear()


@dataclass(frozen=True)
class Line:
    """One collected survey line. Headers are eager, samples are lazy."""

    path: Path
    header: DztHeader
    placement: Placement
    n_traces: int

    @classmethod
    def open(cls, path: Path, placement: Placement) -> Line:
        """Read the header and derive the trace count. Reads 1024 bytes plus
        a stat, regardless of file size."""
        path = Path(path)
        header = read_header(path)
        return cls(
            path=path,
            header=header,
            placement=placement,
            n_traces=trace_count(path, header),
        )

    def load(self) -> list[Profile]:
        """Sample arrays, one Profile per channel. Cached."""
        stat = self.path.stat()
        return list(_load_profiles(str(self.path), stat.st_size, stat.st_mtime_ns))

    def distance_along(self) -> np.ndarray:
        return self.placement.distance_along(self.n_traces, self.header)

    def trace_coords(self, frames: Mapping[str, Grid]) -> np.ndarray:
        return self.placement.trace_coords(self.n_traces, self.header, frames)


@dataclass
class Site:
    grids: list[Grid] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)

    @property
    def frames(self) -> dict[str, Grid]:
        return {g.id: g for g in self.grids}

    def validate(self) -> None:
        """Fail loudly on structural problems rather than at render time."""
        ids = [g.id for g in self.grids]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate grid ids: {sorted(dupes)}")
        known = set(ids)
        for line in self.lines:
            grid_id = getattr(line.placement, "grid_id", None)
            if grid_id is not None and grid_id not in known:
                raise ValueError(f"line {line.path.name} references unknown grid {grid_id!r}")
