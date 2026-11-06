"""The finished slice: interpolate the gaps, then smooth (interpolation spec §4).

One place that joins the two steps, so the dock's drawing and the exporter's
bands apply the same settings in the same order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from nsgeo.slices.interpolate import METHODS, SliceFill
from nsgeo.slices.smooth import smooth


@dataclass(frozen=True)
class FinishSettings:
    """How a slice is finished: the interpolation, then the smoothing."""

    method: str
    max_distance_m: float
    search_radius_m: float
    smooth_x_m: float = 0.0
    smooth_y_m: float = 0.0

    def __post_init__(self) -> None:
        if self.method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}, got {self.method!r}")
        distances = (
            self.max_distance_m,
            self.search_radius_m,
            self.smooth_x_m,
            self.smooth_y_m,
        )
        if not all(math.isfinite(d) and d >= 0.0 for d in distances):
            raise ValueError(f"distances must be finite and >= 0, got {distances}")
        # A neighbourhood smaller than the max distance would leave cells
        # unfilled that the user has allowed to fill.
        if self.search_radius_m < self.max_distance_m:
            raise ValueError(
                f"search radius {self.search_radius_m} is below max distance {self.max_distance_m}"
            )


def finish_slice(
    values: np.ndarray, weights: SliceFill, cell: float, settings: FinishSettings
) -> np.ndarray:
    """`smooth(weights.apply(values), ...)`: float32 `(ny, nx)`, NaN where still blank."""
    return smooth(weights.apply(values), cell, settings.smooth_x_m, settings.smooth_y_m)
