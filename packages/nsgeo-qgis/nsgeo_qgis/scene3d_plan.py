"""The 3-D view's arithmetic and wording (M16 C): its title, which grid it shows, the depth
stretch and where the camera looks.

Pure: no qgis import, so the pure tier and mypy run it. The text lives here, not in
`scene3d.py` or `plugin.py` (the plugin boundary).
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from nsgeo_qgis.slices_plan import DEFAULT_STRETCH

VIEW_NAME: str = "nsgeo 3D"
PICK_RADIUS_M: float = 0.06
PICK_COLOUR: str = "#1f1f1f"
NO_GRID: str = "Add a grid first: the 3-D view shows one grid."
BUTTON_TIP: str = (
    "Open QGIS's 3-D view of the grid the Slices panel shows: its picks at depth and its surfaces"
)
VIEW_FAILED: str = "Could not open the 3-D view: {error}"
PICKS_LAYER_NAME: str = "Picks at depth (3D view)"
VIEW_REFUSED: str = (
    "QGIS would not open the 3-D view: a view named 'nsgeo 3D' is already open and could not "
    "be closed. Close it and try again."
)


def scene_stretch(record: Mapping[str, object]) -> float:
    """The record's `stretch` when it is a finite number above 0, else the default."""
    value = record.get("stretch")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_STRETCH
    value = float(value)
    return value if math.isfinite(value) and value > 0.0 else DEFAULT_STRETCH


def view_title(grid_name: str, stretch: float, n_stale: int) -> str:
    """The window title: the grid, the stretch, and how many surfaces are out of date."""
    title = f"{VIEW_NAME}  ·  {grid_name}  ·  depth stretched ×{stretch:g}"
    if n_stale > 0:
        title += f"  ·  {n_stale:g} {'surface' if n_stale == 1 else 'surfaces'} stale"
    return title


def scene_grid(
    scope: str,
    shown: str | None,
    last: str | None,
    existing: Collection[str] | None = None,
) -> str | None:
    """The grid the view shows: the one the panel shows, but in Whole site the last one, unless
    that grid no longer exists (`existing` lists the grids that do), then the panel's."""
    if scope == "site":
        if last is not None and (existing is None or last in existing):
            return last
        return shown
    return shown


def stretched_z(depth_m: float, stretch: float) -> float:
    """The map Z of a point `depth_m` down, with the depth stretched."""
    return -depth_m * stretch


def local_corners(size_x: float, size_y: float) -> list[tuple[float, float]]:
    """A grid's four corners in its own frame, as (x, y) pairs from the origin."""
    return [(0.0, 0.0), (size_x, 0.0), (size_x, size_y), (0.0, size_y)]


def scene_extent(corners: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    """The corners' bounding box: (xmin, ymin, xmax, ymax)."""
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return min(xs), min(ys), max(xs), max(ys)


def padded_extent(
    corners: Sequence[tuple[float, float]],
) -> tuple[float, float, float, float]:
    """The scene's extent: the bounding box plus a margin of 10% of its longer side (at least
    1 m) all round, so picks on a line that runs past the grid's edge are not culled."""
    xmin, ymin, xmax, ymax = scene_extent(corners)
    margin = max(1.0, 0.1 * max(xmax - xmin, ymax - ymin))
    return xmin - margin, ymin - margin, xmax + margin, ymax + margin


def scene_centre(corners: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """The middle of the corners' bounding box: the view's origin and where the camera looks."""
    xmin, ymin, xmax, ymax = scene_extent(corners)
    return (xmin + xmax) / 2.0, (ymin + ymax) / 2.0


@dataclass(frozen=True)
class CameraPose:
    x: float
    y: float
    z: float
    distance: float
    pitch: float
    yaw: float


def camera_pose(
    corners: Sequence[tuple[float, float]], depths: Sequence[float], stretch: float
) -> CameraPose:
    """Where the camera looks: the grid's centre, at the middle of its depths."""
    xmin, ymin, xmax, ymax = scene_extent(corners)
    cx, cy = scene_centre(corners)
    mid = (min(depths) + max(depths)) / 2.0 if depths else 0.0
    extent = max(xmax - xmin, ymax - ymin)
    return CameraPose(cx, cy, stretched_z(mid, stretch), 1.2 * extent, 45.0, 0.0)
