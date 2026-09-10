"""Grid as a coordinate frame.

A Grid is not a container of lines. It is an affine frame that converts
grid-local metres to world coordinates. Lines reference it by id, which is what
lets one grid hold cross-hatched lines running in both directions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple  # noqa: UP035

import numpy as np


@dataclass(frozen=True)
class Grid:
    id: str
    origin: Tuple[float, float]  # noqa: UP006
    azimuth: float
    size_x: float
    size_y: float
    crs: str
    default_spacing: float

    def axes(self) -> Tuple[np.ndarray, np.ndarray]:  # noqa: UP006
        """Unit vectors of grid-local +X and +Y in world coordinates.

        azimuth is degrees clockwise from CRS north to grid-local +Y, so
        +Y = (sin a, cos a) and +X is that turned 90 degrees clockwise.
        """
        a = math.radians(self.azimuth)
        y_hat = np.array([math.sin(a), math.cos(a)])
        x_hat = np.array([math.cos(a), -math.sin(a)])
        return x_hat, y_hat

    def to_world(self, local: np.ndarray) -> np.ndarray:
        """Convert (n, 2) grid-local metres to (n, 2) world coordinates."""
        local = np.asarray(local, dtype=float)
        if local.ndim != 2 or local.shape[1] != 2:
            raise ValueError(f"expected (n, 2) local coordinates, got {local.shape}")
        x_hat, y_hat = self.axes()
        return np.asarray(self.origin, dtype=float) + local[:, :1] * x_hat + local[:, 1:] * y_hat
