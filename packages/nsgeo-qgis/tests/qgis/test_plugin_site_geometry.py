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
    np.testing.assert_allclose(got, one_at_a_time(points, "EPSG:32616", target), atol=1e-9)


def test_transform_points_handles_none_and_one_point(qgis_app):
    none = transform_points(np.empty((0, 2)), "EPSG:32616", "EPSG:32615", context())
    assert none.shape == (0, 2)
    one = np.array([[500_000.0, 4_000_000.0]])
    got = transform_points(one, "EPSG:32616", "EPSG:32615", context())
    assert got.shape == (1, 2)
    np.testing.assert_allclose(got, one_at_a_time(one, "EPSG:32616", "EPSG:32615"), atol=1e-9)


def test_transform_points_refuses_a_missing_transform(qgis_app):
    with pytest.raises(RuntimeError, match="no coordinate transform from"):
        transform_points(np.zeros((3, 2)), "EPSG:32616", "not a crs", context())


def test_transform_points_is_one_call_not_one_per_point(qgis_app):
    rng = np.random.default_rng(3)
    points = np.column_stack([rng.uniform(400_000, 600_000, 100_000), rng.uniform(0, 5e6, 100_000)])
    t0 = time.perf_counter()
    transform_points(points, "EPSG:32616", "EPSG:32615", context())
    batched = time.perf_counter() - t0
    t0 = time.perf_counter()
    one_at_a_time(points, "EPSG:32616", "EPSG:32615")
    looped = time.perf_counter() - t0
    assert looped >= 3.0 * batched, (looped, batched)
