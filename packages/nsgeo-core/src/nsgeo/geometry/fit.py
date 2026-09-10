"""Fit a grid frame to surveyed control points.

GNSS corners, on-map digitising, and existing polygons are three UI paths that
all produce the same four numbers. This is the shared implementation.

The fit is rigid: rotation and translation only, no scale and no reflection.
That is deliberate. A grid that was not actually square shows up as a nonzero
residual, which is a QC number worth reporting, rather than being silently
absorbed into a scale factor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class GridFit:
    origin: tuple[float, float]
    azimuth: float
    residual_rms: float


def fit_grid_from_corners(local: np.ndarray, world: np.ndarray) -> GridFit:
    """Least-squares rigid fit of grid-local metres to world coordinates."""
    local = np.asarray(local, dtype=float)
    world = np.asarray(world, dtype=float)
    if local.shape != world.shape:
        raise ValueError(f"local and world must be the same length: {local.shape} vs {world.shape}")
    if local.ndim != 2 or local.shape[1] != 2:
        raise ValueError(f"expected (n, 2) coordinates, got {local.shape}")
    if len(local) < 2:
        raise ValueError("need at least two control points to fit a grid")

    lc = local.mean(axis=0)
    wc = world.mean(axis=0)
    cov = (local - lc).T @ (world - wc)
    u, _, vt = np.linalg.svd(cov)

    # Forbid reflection: a mirrored layout is a data-entry error, not a rotation.
    d = np.sign(np.linalg.det(vt.T @ u.T))
    rot = vt.T @ np.diag([1.0, d]) @ u.T

    origin = wc - rot @ lc
    predicted = (rot @ local.T).T + origin
    residual = float(np.sqrt(np.mean(np.sum((world - predicted) ** 2, axis=1))))

    # rot maps local to world, so rot @ (0, 1) is the world direction of
    # grid-local +Y, which is (sin azimuth, cos azimuth).
    azimuth = math.degrees(math.atan2(rot[0, 1], rot[1, 1])) % 360.0

    return GridFit(
        origin=(float(origin[0]), float(origin[1])),
        azimuth=azimuth,
        residual_rms=residual,
    )
