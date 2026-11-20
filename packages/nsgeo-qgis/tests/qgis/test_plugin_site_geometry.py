"""`site_geometry`: one-call point transforms, outlines and gathers (#75)."""

from __future__ import annotations

import time

import numpy as np
import pytest
from nsgeo_qgis.site_geometry import transform_points
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
)


def one_at_a_time(points: np.ndarray, source: str, target: str) -> np.ndarray:
    ct = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem(source),
        QgsCoordinateReferenceSystem(target),
        QgsProject.instance(),
    )
    out = np.empty((len(points), 2))
    for i, (x, y) in enumerate(points):
        moved = ct.transform(QgsPointXY(float(x), float(y)))
        out[i] = (moved.x(), moved.y())
    return out


def context():
    return QgsProject.instance().transformContext()


@pytest.mark.parametrize("target", ["EPSG:32617", "EPSG:4326"])
def test_transform_points_matches_one_point_at_a_time(qgis_app, target):
    rng = np.random.default_rng(7)
    points = np.column_stack([rng.uniform(400_000, 600_000, 1000), rng.uniform(0, 5_000_000, 1000)])
    got = transform_points(points, "EPSG:32616", target, context())
    assert got.shape == (1000, 2)
    np.testing.assert_allclose(got, one_at_a_time(points, "EPSG:32616", target), rtol=0, atol=1e-9)


def test_transform_points_handles_none_and_one_point(qgis_app):
    none = transform_points(np.empty((0, 2)), "EPSG:32616", "EPSG:32615", context())
    assert none.shape == (0, 2)
    one = np.array([[500_000.0, 4_000_000.0]])
    got = transform_points(one, "EPSG:32616", "EPSG:32615", context())
    assert got.shape == (1, 2)
    np.testing.assert_allclose(
        got, one_at_a_time(one, "EPSG:32616", "EPSG:32615"), rtol=0, atol=1e-9
    )


def test_transform_points_refuses_a_missing_transform(qgis_app):
    with pytest.raises(RuntimeError, match="no coordinate transform from"):
        transform_points(np.zeros((3, 2)), "EPSG:32616", "not a crs", context())


def test_transform_points_is_one_call_not_one_per_point(qgis_app):
    rng = np.random.default_rng(3)
    points = np.column_stack([rng.uniform(400_000, 600_000, 100_000), rng.uniform(0, 5e6, 100_000)])
    batched = float("inf")
    for _ in range(3):  # the fastest of three: one stall under load must not decide it
        t0 = time.perf_counter()
        transform_points(points, "EPSG:32616", "EPSG:32615", context())
        batched = min(batched, time.perf_counter() - t0)
    t0 = time.perf_counter()
    one_at_a_time(points, "EPSG:32616", "EPSG:32615")
    looped = time.perf_counter() - t0
    assert looped >= 3.0 * batched, (looped, batched)


@pytest.mark.parametrize(
    "points",
    [
        [[500_000.0, 4_000_000.0]],  # one point: QGIS checks no error for it
        [[-87.0, 36.0], [500_000.0, 4_000_000.0], [-86.9, 36.1]],  # one bad among good
    ],
)
def test_transform_points_refuses_points_outside_the_target(qgis_app, points):
    """A grid declared in degrees but holding metres: the per-point path raised; the
    batched transform hands back inf without a word, which became an OverflowError
    in the lattice. It must refuse, in a sentence that says what to check."""
    with pytest.raises(RuntimeError, match="outside where EPSG:32616 is defined"):
        transform_points(np.array(points), "EPSG:4326", "EPSG:32616", context())


def test_transform_points_passes_non_finite_input_through(qgis_app):
    points = np.array([[500_000.0, 4_000_000.0], [np.nan, np.nan], [np.inf, 1.0]])
    got = transform_points(points, "EPSG:32616", "EPSG:32615", context())
    assert np.isfinite(got[0]).all() and not np.isfinite(got[1:]).all(axis=1).any()


def test_transform_points_refuses_a_shape_that_is_not_points(qgis_app):
    with pytest.raises(ValueError, match=r"\(n, 2\)"):
        transform_points(np.zeros((4, 3)), "EPSG:32616", "EPSG:32615", context())
