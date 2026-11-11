"""Trace placement: how a line's trace index maps to real-world position.

Trace index is the join between geometry and data. `Profile.data[:, i]` and
`placement.trace_coords(...)[i]` describe the same trace, which is what makes
bidirectional map-to-profile navigation work.
"""

from __future__ import annotations

import math
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

    `scale` is grid metres per metre the wheel recorded: 1.0 places the line
    as recorded, 0.95 compresses it toward its start. The DZT header is left
    as recorded, so the correction is reversible (#3; placement corrections
    plan, call 1). `travel_shift` is metres, moving every trace forward along
    the line's own direction of travel. It is stored apart from `start_along`
    (where the line was recorded to begin) and is not scaled (#47; placement
    corrections plan, calls 1 and 4).
    """

    grid_id: str
    axis: str
    offset: float
    start_along: float = 0.0
    direction: int = 1
    label: str | None = None
    scale: float = 1.0
    travel_shift: float = 0.0

    def __post_init__(self) -> None:
        if self.axis not in ("x", "y"):
            raise ValueError(f"axis must be 'x' or 'y', got {self.axis!r}")
        if self.direction not in (1, -1):
            raise ValueError(f"direction must be +1 or -1, got {self.direction!r}")
        if not (math.isfinite(self.scale) and self.scale > 0):
            raise ValueError(f"scale must be finite and above 0, got {self.scale!r}")
        if not math.isfinite(self.travel_shift):
            raise ValueError(f"travel_shift must be finite, got {self.travel_shift!r}")

    def distance_along(self, n_traces: int, header: DztHeader) -> np.ndarray:
        spm = header.traces_per_metre
        if not spm > 0:
            raise ValueError(
                "traces_per_metre is not positive; this line was probably "
                "recorded with time triggering and cannot be positioned by a "
                "grid placement"
            )
        recorded = np.arange(n_traces, dtype=float) / spm
        return self.start_along + self.direction * (self.scale * recorded + self.travel_shift)

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
