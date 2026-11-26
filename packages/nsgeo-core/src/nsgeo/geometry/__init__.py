"""Coordinate frames and trace placement."""

from __future__ import annotations

from nsgeo.geometry.fit import GridFit, fit_grid_from_corners
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement, Placement
from nsgeo.geometry.track import (
    ANCHOR_ALL,
    ANCHOR_RTK,
    END_LIMIT_M,
    Bridge,
    ToXY,
    TrackFix,
    TrackPlacement,
    anchor_rule,
    gps_length_note,
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
    "ANCHOR_ALL",
    "ANCHOR_RTK",
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
    "anchor_rule",
    "fit_frame",
    "fit_grid_from_corners",
    "gps_length_note",
    "main_direction",
    "measure_spacing",
    "metres_outside",
    "track_from_log",
]
