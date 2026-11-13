from __future__ import annotations

import numpy as np
from nsgeo.geometry.grid import Grid
from nsgeo.mag.setup import MagSetup
from nsgeo.mag.traverses import traverses, walked_direction

GRID = Grid("M", (0.0, 0.0), 0.0, 2.0, 4.0, "EPSG:32616", 0.5)
S = MagSetup(readings_per_metre=4.0)


def stored_along(t, n, rpm):
    a = t.placement.along(n, rpm)
    return a[::-1] if t.reversed else a


def test_walked_direction_follows_the_passes():
    def dirs(s, n):
        return [walked_direction(s, r) for r in range(n)]

    assert dirs(MagSetup(), 8) == [1, -1, 1, -1, 1, -1, 1, -1]
    assert dirs(MagSetup(sensor_separation_m=0.5), 8) == [1, 1, -1, -1, 1, 1, -1, -1]
    assert dirs(MagSetup(sensors=1), 4) == [1, -1, 1, -1]
    assert dirs(MagSetup(zigzag=False), 8) == [1] * 8


def test_each_reading_sits_mid_interval_whichever_way_it_was_walked():
    t = traverses(S, GRID, 4, 16)
    for i in (0, 1):
        np.testing.assert_allclose(stored_along(t[i], 16, 4.0), 0.125 + 0.25 * np.arange(16))
    assert (t[0].placement.direction, t[1].placement.direction) == (1, -1)
    assert (t[0].reversed, t[1].reversed) == (False, True)
    assert t[1].placement.label == "traverse 2"
    stored = np.arange(16.0)
    np.testing.assert_array_equal(t[1].walked(stored), stored[::-1])
    np.testing.assert_array_equal(t[0].walked(stored), stored)


def test_an_unflipped_return_traverse_keeps_its_stored_order():
    t = traverses(MagSetup(readings_per_metre=4.0, flipped=False), GRID, 4, 16)[1]
    assert t.reversed is False
    assert t.placement.direction == -1
    np.testing.assert_allclose(t.placement.along(16, 4.0), 3.875 - 0.25 * np.arange(16))


def test_traverses_step_across_from_the_starting_corner():
    t = traverses(S, GRID, 4, 16)
    assert [x.placement.offset for x in t] == [0.25, 0.75, 1.25, 1.75]
    far = traverses(MagSetup(readings_per_metre=4.0, far_x=True, far_y=True), GRID, 4, 16)
    assert [x.placement.offset for x in far] == [1.75, 1.25, 0.75, 0.25]
    np.testing.assert_allclose(far[0].placement.along(16, 4.0), 3.875 - 0.25 * np.arange(16))
    assert far[0].placement.direction == -1


def test_destagger_moves_each_traverse_along_its_own_walk():
    base = traverses(S, GRID, 4, 16)
    moved = traverses(S, GRID, 4, 16, shifts=(0.1,) * 4)
    np.testing.assert_allclose(
        moved[0].placement.along(16, 4.0), base[0].placement.along(16, 4.0) + 0.1
    )
    np.testing.assert_allclose(
        moved[1].placement.along(16, 4.0), base[1].placement.along(16, 4.0) - 0.1
    )


def test_scales_stretch_the_traverse():
    t = traverses(S, GRID, 4, 16, scales=(0.5, 1.0, 1.0, 1.0))[0]
    assert t.placement.scale == 0.5


def test_traverses_along_x_put_the_offset_in_y():
    grid = Grid("M", (0.0, 0.0), 0.0, 4.0, 2.0, "EPSG:32616", 0.5)
    t = traverses(MagSetup(axis="x", readings_per_metre=4.0), grid, 4, 16)
    for x in t:
        np.testing.assert_allclose(x.placement.local(16, 4.0)[:, 1], x.placement.offset)
    assert [x.placement.offset for x in t] == [0.25, 0.75, 1.25, 1.75]
