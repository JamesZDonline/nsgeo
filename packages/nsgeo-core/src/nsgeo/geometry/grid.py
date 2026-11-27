"""Grid as a coordinate frame.

A Grid is not a container of lines. It is an affine frame that converts
grid-local metres to world coordinates. Lines reference it by id, which is what
lets one grid hold cross-hatched lines running in both directions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nsgeo.geometry.affine import local_axes, local_to_world, world_to_local
from nsgeo.velocity import VelocityModel
from nsgeo.velocity_source import VelocitySource


@dataclass(frozen=True)
class Grid:
    id: str
    origin: tuple[float, float]
    azimuth: float
    size_x: float
    size_y: float
    crs: str
    default_spacing: float
    velocity: VelocityModel | None = None
    velocity_source: VelocitySource | None = None

    def axes(self) -> tuple[np.ndarray, np.ndarray]:
        """Unit vectors of grid-local +X and +Y in world coordinates.

        azimuth is degrees clockwise from CRS north to grid-local +Y, so
        +Y = (sin a, cos a) and +X is that turned 90 degrees clockwise.
        """
        return local_axes(self.azimuth)

    def to_world(self, local: np.ndarray) -> np.ndarray:
        """Convert (n, 2) grid-local metres to (n, 2) world coordinates."""
        return local_to_world(self.origin, self.azimuth, local)

    def to_local(self, world: np.ndarray) -> np.ndarray:
        """Convert (n, 2) world coordinates to (n, 2) grid-local metres (`to_world`'s inverse)."""
        return world_to_local(self.origin, self.azimuth, world)
