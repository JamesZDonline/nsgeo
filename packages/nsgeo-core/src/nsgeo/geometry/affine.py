"""The rotation a `Grid` and a `CubeFrame` share: local metres to world and back.

Both carry an origin and an azimuth (degrees clockwise from CRS north to local
+Y), so the transform is written once here. No imports from the rest of nsgeo,
so either type can use it without a cycle.
"""

from __future__ import annotations

import math

import numpy as np


def local_axes(azimuth: float) -> tuple[np.ndarray, np.ndarray]:
    """Unit vectors of local +X and +Y in world coordinates.

    +Y = (sin a, cos a) and +X is that turned 90 degrees clockwise.
    """
    a = math.radians(azimuth)
    y_hat = np.array([math.sin(a), math.cos(a)])
    x_hat = np.array([math.cos(a), -math.sin(a)])
    return x_hat, y_hat


def local_to_world(origin: tuple[float, float], azimuth: float, local: np.ndarray) -> np.ndarray:
    """(n, 2) local metres -> (n, 2) world coordinates."""
    local = np.asarray(local, dtype=float)
    if local.ndim != 2 or local.shape[1] != 2:
        raise ValueError(f"expected (n, 2) local coordinates, got {local.shape}")
    x_hat, y_hat = local_axes(azimuth)
    return np.asarray(origin, dtype=float) + local[:, :1] * x_hat + local[:, 1:] * y_hat


def world_to_local(origin: tuple[float, float], azimuth: float, world: np.ndarray) -> np.ndarray:
    """(n, 2) world coordinates -> (n, 2) local metres (`local_to_world`'s inverse)."""
    world = np.asarray(world, dtype=float)
    if world.ndim != 2 or world.shape[1] != 2:
        raise ValueError(f"expected (n, 2) world coordinates, got {world.shape}")
    x_hat, y_hat = local_axes(azimuth)
    rel = world - np.asarray(origin, dtype=float)
    return np.column_stack([rel @ x_hat, rel @ y_hat])
