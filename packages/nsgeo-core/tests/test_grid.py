from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid


def g(azimuth=0.0, origin=(0.0, 0.0)):
    return Grid(
        id="G",
        origin=origin,
        azimuth=azimuth,
        size_x=20.0,
        size_y=20.0,
        crs="EPSG:32616",
        default_spacing=0.5,
    )


def test_zero_azimuth_aligns_local_axes_with_world():
    """azimuth is degrees clockwise from CRS north to grid-local +Y."""
    x_hat, y_hat = g(0.0).axes()
    np.testing.assert_allclose(y_hat, [0.0, 1.0], atol=1e-12)
    np.testing.assert_allclose(x_hat, [1.0, 0.0], atol=1e-12)


def test_ninety_degree_azimuth_points_local_y_east():
    x_hat, y_hat = g(90.0).axes()
    np.testing.assert_allclose(y_hat, [1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(x_hat, [0.0, -1.0], atol=1e-12)


def test_axes_stay_orthonormal_and_right_handed():
    for az in (0.0, 17.5, 90.0, 213.0, 359.9):
        x_hat, y_hat = g(az).axes()
        assert np.dot(x_hat, y_hat) == pytest.approx(0.0, abs=1e-12)
        assert np.linalg.norm(x_hat) == pytest.approx(1.0)
        assert np.linalg.norm(y_hat) == pytest.approx(1.0)
        cross = x_hat[0] * y_hat[1] - x_hat[1] * y_hat[0]
        assert cross == pytest.approx(1.0)


def test_to_world_translates_by_origin():
    grid = g(0.0, origin=(100.0, 200.0))
    out = grid.to_world(np.array([[0.0, 0.0], [1.0, 2.0]]))
    np.testing.assert_allclose(out, [[100.0, 200.0], [101.0, 202.0]])


def test_to_world_rotates_then_translates():
    grid = g(90.0, origin=(10.0, 20.0))
    out = grid.to_world(np.array([[0.0, 5.0]]))  # 5 m along local +Y
    np.testing.assert_allclose(out, [[15.0, 20.0]], atol=1e-12)


def test_to_world_preserves_distances():
    grid = g(37.0, origin=(5.0, -3.0))
    local = np.array([[0.0, 0.0], [3.0, 4.0]])
    out = grid.to_world(local)
    assert np.linalg.norm(out[1] - out[0]) == pytest.approx(5.0)


def test_to_world_rejects_wrong_shape():
    with pytest.raises(ValueError, match=r"\(n, 2\)"):
        g().to_world(np.zeros((3, 3)))
