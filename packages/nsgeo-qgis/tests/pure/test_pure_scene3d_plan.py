"""The 3-D view's title, scene grid, stretch and camera (M16 C)."""

from __future__ import annotations

import pytest
from nsgeo_qgis.scene3d_plan import (
    camera_pose,
    local_corners,
    padded_extent,
    scene_centre,
    scene_extent,
    scene_grid,
    scene_stretch,
    view_title,
)
from nsgeo_qgis.slices_plan import DEFAULT_STRETCH


def test_view_title_states_grid_stretch_and_stale_count():
    assert view_title("Grid 1", 3.0, 0) == "nsgeo 3D  ·  Grid 1  ·  depth stretched ×3"
    assert view_title("Grid 1", 2.5, 1) == (
        "nsgeo 3D  ·  Grid 1  ·  depth stretched ×2.5  ·  1 surface stale"
    )
    assert view_title("Grid 1", 3.0, 2).endswith("  ·  2 surfaces stale")


def test_scene_grid_follows_this_grid_and_keeps_the_last_in_whole_site():
    assert scene_grid("grid", "Grid 2", "Grid 1") == "Grid 2"
    assert scene_grid("site", "Grid 2", "Grid 1") == "Grid 1"
    assert scene_grid("site", "Grid 2", None) == "Grid 2"
    assert scene_grid("grid", None, None) is None


def test_scene_stretch_is_the_grids_own_or_the_default():
    assert scene_stretch(2.0) == 2.0
    for bad in (None, 0.0, -1.0, float("nan"), float("inf"), "x", True):
        assert scene_stretch(bad) == DEFAULT_STRETCH


def test_scene_stretch_is_kept_within_the_boxs_range():
    assert scene_stretch(100) == 50.0
    assert scene_stretch(0.01) == 0.1
    assert scene_stretch(2.25) == 2.25


def test_camera_frames_the_grid_at_mid_depth():
    pose = camera_pose([(0, 0), (20, 0), (20, 16), (0, 16)], [1.0, 3.0], 3.0)
    assert (pose.x, pose.y) == (10.0, 8.0)
    assert pose.z == pytest.approx(-2.0 * 3.0)
    assert pose.distance == pytest.approx(1.2 * 20.0)
    assert (pose.pitch, pose.yaw) == (45.0, 0.0)
    assert camera_pose([(0, 0), (2, 0), (2, 2), (0, 2)], [], 3.0).z == 0.0


def test_local_corners_scene_extent_and_centre():
    assert local_corners(3.0, 12.0) == [(0.0, 0.0), (3.0, 0.0), (3.0, 12.0), (0.0, 12.0)]
    tilted = [(5.0, 1.0), (9.0, 3.0), (7.0, 7.0), (3.0, 5.0)]
    assert scene_extent(tilted) == (3.0, 1.0, 9.0, 7.0)
    assert scene_centre(tilted) == (6.0, 4.0)
    pose = camera_pose(tilted, [], 3.0)
    assert (pose.x, pose.y) == scene_centre(tilted)


def test_scene_grid_falls_back_to_the_panels_when_the_last_grid_is_gone():
    assert scene_grid("site", "Grid 2", "Grid 1", ["Grid 1", "Grid 2"]) == "Grid 1"
    assert scene_grid("site", "Grid 2", "Grid 1", ["Grid 2"]) == "Grid 2"
    assert scene_grid("site", None, "Grid 1", []) is None
    assert scene_grid("grid", "Grid 2", "Grid 1", ["Grid 2"]) == "Grid 2"


def test_padded_extent_adds_a_tenth_of_the_longer_side_and_at_least_a_metre():
    big = [(0.0, 0.0), (40.0, 0.0), (40.0, 20.0), (0.0, 20.0)]
    assert padded_extent(big) == (-4.0, -4.0, 44.0, 24.0)
    small = [(5.0, 5.0), (8.0, 5.0), (8.0, 7.0), (5.0, 7.0)]
    assert padded_extent(small) == (4.0, 4.0, 9.0, 8.0)
