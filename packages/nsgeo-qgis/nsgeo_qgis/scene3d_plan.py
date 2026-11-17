"""The 3-D view's arithmetic and wording (M16 C): its title, which grid it shows, the depth
stretch and where the camera looks.

Pure: no qgis import, so the pure tier and mypy run it. The text lives here, not in
`scene3d.py` or `plugin.py` (the plugin boundary).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from nsgeo_qgis.slices_plan import DEFAULT_STRETCH

VIEW_NAME: str = "nsgeo 3D"
PICK_RADIUS_M: float = 0.06
NO_GRID: str = "Add a grid first: the 3-D view shows one grid."
BUTTON_TIP: str = (
    "Open QGIS's 3-D view of the grid the Slices panel shows: its picks at depth and its surfaces"
)
PICKS_LAYER_NAME: str = "Picks at depth (3D view)"


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


def scene_grid(scope: str, shown: str | None, last: str | None) -> str | None:
    """The grid the view shows: the one the panel shows, but in Whole site the last one."""
    if scope == "site":
        return last if last is not None else shown
    return shown


def stretched_z(depth_m: float, stretch: float) -> float:
    """The map Z of a point `depth_m` down, with the depth stretched."""
    return -depth_m * stretch


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
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    mid = (min(depths) + max(depths)) / 2.0 if depths else 0.0
    extent = max(max(xs) - min(xs), max(ys) - min(ys))
    return CameraPose(cx, cy, stretched_z(mid, stretch), 1.2 * extent, 45.0, 0.0)
