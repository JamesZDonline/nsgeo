"""Each row of a Grad601 file as a traverse placed in its grid by `GridPlacement`."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.mag.setup import MagSetup


@dataclass(frozen=True)
class Traverse:
    """One file row: where it is placed, and whether its stored order is the reverse of walked."""

    row: int
    placement: GridPlacement
    reversed: bool

    def walked(self, stored_row: np.ndarray) -> np.ndarray:
        """The row's readings in the order they were walked."""
        return stored_row[::-1] if self.reversed else stored_row


def walked_direction(setup: MagSetup, row: int) -> int:
    """+1 the first traverse's way, -1 the other way."""
    k = setup.passes_apart()
    block = setup.sensors * k
    pass_index = (row // block) * k + (row % block) % k
    return 1 if (not setup.zigzag or pass_index % 2 == 0) else -1


def traverses(
    setup: MagSetup,
    grid: Grid,
    n_rows: int,
    n_readings: int,
    scales: Sequence[float] | None = None,
    shifts: Sequence[float] | None = None,
) -> tuple[Traverse, ...]:
    """Every row placed in `grid`; reading j sits (j + 0.5) / readings_per_metre from its edge."""
    size_along = grid.size_y if setup.axis == "y" else grid.size_x
    size_across = grid.size_x if setup.axis == "y" else grid.size_y
    far_along = setup.far_y if setup.axis == "y" else setup.far_x
    far_across = setup.far_x if setup.axis == "y" else setup.far_y
    sign = -1 if far_along else 1
    edge = size_along if far_along else 0.0
    sign_x = -1 if far_across else 1
    edge_x = size_across if far_across else 0.0
    out = []
    for row in range(n_rows):
        d = walked_direction(setup, row)
        half = 0.5 if d > 0 else n_readings - 0.5
        placement = GridPlacement(
            grid.id,
            setup.axis,
            edge_x + sign_x * (setup.first_offset_m + row * setup.spacing_m),
            start_along=edge + sign * half / setup.readings_per_metre,
            direction=sign * d,
            label=f"traverse {row + 1}",
            scale=1.0 if scales is None else scales[row],
            travel_shift=0.0 if shifts is None else shifts[row],
        )
        out.append(Traverse(row, placement, d < 0 and setup.flipped))
    return tuple(out)
