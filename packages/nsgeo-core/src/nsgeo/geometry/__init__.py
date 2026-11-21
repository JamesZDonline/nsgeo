"""Coordinate frames and trace placement."""

from __future__ import annotations

from nsgeo.geometry.fit import GridFit, fit_grid_from_corners
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement, Placement
from nsgeo.geometry.spacing import (
    check_gap_m,
    gap_steps,
    left_out,
    usual_step,
)
from nsgeo.geometry.track import (
    END_LIMIT_M,
    Bridge,
    ToXY,
    TrackFix,
    TrackPlacement,
    track_from_log,
)
from nsgeo.geometry.track_fit import (
    ALONG_DEG,
    MIN_VOTE_M,
    TrackFrame,
    fit_frame,
    main_direction,
    measure_spacing,
    metres_outside,
)

__all__ = [
    "ALONG_DEG",
    "Bridge",
    "END_LIMIT_M",
    "Grid",
    "GridFit",
    "GridPlacement",
    "MIN_VOTE_M",
    "Placement",
    "ToXY",
    "TrackFix",
    "TrackFrame",
    "TrackPlacement",
    "check_gap_m",
    "fit_frame",
    "fit_grid_from_corners",
    "gap_steps",
    "left_out",
    "main_direction",
    "measure_spacing",
    "metres_outside",
    "track_from_log",
    "usual_step",
]
