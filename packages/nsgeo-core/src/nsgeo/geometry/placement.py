"""Trace placement: how a line's trace index maps to real-world position.

Trace index is the join between geometry and data. `Profile.data[:, i]` and
`placement.trace_coords(...)[i]` describe the same trace, which is what makes
bidirectional map-to-profile navigation work.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from nsgeo.geometry.grid import Grid
from nsgeo.io.dzt import DztHeader


class Placement(Protocol):
    """How traces are positioned. Consumers use only these two methods and
    never learn which implementation they received."""

    def distance_along(self, n_traces: int, header: DztHeader) -> np.ndarray:
        """(n_traces,) metres along the line."""
        ...

    def trace_coords(
        self, n_traces: int, header: DztHeader, frames: Mapping[str, Grid]
    ) -> np.ndarray:
        """(n_traces, 2) world coordinates."""
        ...


@dataclass(frozen=True)
class GridPlacement:
    """A line positioned parametrically within a grid frame.

    `offset` is the position in metres along the axis the line does NOT run
    along, and is the geometric truth. `label` carries the human field name
    ("line 12") and is never used for geometry.
    """

    grid_id: str
    axis: str
    offset: float
    start_along: float = 0.0
    direction: int = 1
    label: str | None = None

    def __post_init__(self) -> None:
        if self.axis not in ("x", "y"):
            raise ValueError(f"axis must be 'x' or 'y', got {self.axis!r}")
        if self.direction not in (1, -1):
            raise ValueError(f"direction must be +1 or -1, got {self.direction!r}")

    def distance_along(self, n_traces: int, header: DztHeader) -> np.ndarray:
        spm = header.traces_per_metre
        if not spm > 0:
            raise ValueError(
                "traces_per_metre is not positive; this line was probably "
                "recorded with time triggering and cannot be positioned by a "
                "grid placement"
            )
        return self.start_along + self.direction * (np.arange(n_traces, dtype=float) / spm)

    def trace_coords(
        self, n_traces: int, header: DztHeader, frames: Mapping[str, Grid]
    ) -> np.ndarray:
        if self.grid_id not in frames:
            raise KeyError(f"no grid frame named {self.grid_id!r}")
        along = self.distance_along(n_traces, header)
        cross = np.full(n_traces, self.offset, dtype=float)
        if self.axis == "y":
            local = np.column_stack([cross, along])
        else:
            local = np.column_stack([along, cross])
        return frames[self.grid_id].to_world(local)
