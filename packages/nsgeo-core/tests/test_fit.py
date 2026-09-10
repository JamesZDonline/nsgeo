from __future__ import annotations

import math

import numpy as np
import pytest
from nsgeo.geometry.fit import fit_grid_from_corners
from nsgeo.geometry.grid import Grid

LOCAL = np.array([[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]])


def _rotate(pts, deg, origin):
    a = math.radians(deg)
    y_hat = np.array([math.sin(a), math.cos(a)])
    x_hat = np.array([math.cos(a), -math.sin(a)])
    return np.asarray(origin) + pts[:, :1] * x_hat + pts[:, 1:] * y_hat


def test_recovers_origin_and_azimuth_exactly():
    world = _rotate(LOCAL, 30.0, (500.0, 700.0))
    fit = fit_grid_from_corners(LOCAL, world)
    assert fit.origin[0] == pytest.approx(500.0, abs=1e-6)
    assert fit.origin[1] == pytest.approx(700.0, abs=1e-6)
    assert fit.azimuth == pytest.approx(30.0, abs=1e-6)
    assert fit.residual_rms == pytest.approx(0.0, abs=1e-9)


def test_round_trips_through_grid_to_world():
    world = _rotate(LOCAL, 213.0, (10.0, -5.0))
    fit = fit_grid_from_corners(LOCAL, world)
    grid = Grid(
        id="G",
        origin=fit.origin,
        azimuth=fit.azimuth,
        size_x=20.0,
        size_y=20.0,
        crs="EPSG:32616",
        default_spacing=0.5,
    )
    np.testing.assert_allclose(grid.to_world(LOCAL), world, atol=1e-6)


def test_two_points_are_enough():
    world = _rotate(LOCAL[:2], 45.0, (0.0, 0.0))
    fit = fit_grid_from_corners(LOCAL[:2], world)
    assert fit.azimuth == pytest.approx(45.0, abs=1e-6)


def test_azimuth_is_normalised_to_0_360():
    world = _rotate(LOCAL, -45.0, (0.0, 0.0))
    fit = fit_grid_from_corners(LOCAL, world)
    assert 0.0 <= fit.azimuth < 360.0
    assert fit.azimuth == pytest.approx(315.0, abs=1e-6)


def test_non_square_grid_reports_nonzero_residual():
    """The QC number: a grid stretched on one axis cannot be fitted rigidly."""
    stretched = LOCAL.copy()
    stretched[:, 0] *= 1.10  # 10% long on one axis
    world = _rotate(stretched, 12.0, (0.0, 0.0))
    fit = fit_grid_from_corners(LOCAL, world)
    assert fit.residual_rms > 0.3


def test_noise_produces_small_residual():
    rng = np.random.default_rng(7)
    world = _rotate(LOCAL, 12.0, (0.0, 0.0)) + rng.normal(0, 0.02, LOCAL.shape)
    fit = fit_grid_from_corners(LOCAL, world)
    assert fit.residual_rms < 0.1


def test_rejects_reflection():
    """A mirrored layout is a data-entry error, not a rotation. The fit must
    not silently absorb it by flipping the frame."""
    world = _rotate(LOCAL, 0.0, (0.0, 0.0))
    world[:, 0] *= -1
    fit = fit_grid_from_corners(LOCAL, world)
    assert fit.residual_rms > 1.0


def test_requires_at_least_two_points():
    with pytest.raises(ValueError, match="at least two"):
        fit_grid_from_corners(LOCAL[:1], LOCAL[:1])


def test_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        fit_grid_from_corners(LOCAL, LOCAL[:3])
