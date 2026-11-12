"""`fit_temporal_navigation`: the Temporal Controller steps one band per frame.

The windows below are real on-disk bands on the native dz grid (0.2165 ns): abutting
(step == thickness), overlapping (step < thickness) and gapped (step > thickness).
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo_qgis.slice_export import apply_band_windows, fit_temporal_navigation
from osgeo import gdal
from qgis.core import (
    Qgis,
    QgsProject,
    QgsRasterLayer,
    QgsTemporalNavigationObject,
)

DZ = 0.2165


def _layer(tmp_path, n_bands: int) -> QgsRasterLayer:
    path = str(tmp_path / "bands.tif")
    ds = gdal.GetDriverByName("GTiff").Create(path, 4, 4, n_bands, gdal.GDT_Float32)
    ds.SetGeoTransform((0, 1, 0, 0, 0, -1))
    for b in range(n_bands):
        ds.GetRasterBand(b + 1).WriteArray(np.full((4, 4), b + 1, np.float32))
    ds = None
    layer = QgsRasterLayer(path, "t", "gdal")
    assert layer.isValid()
    return layer


def _windows(n: int, step: float, thickness: float, start: float = 2.0):
    return [(start + k * step, start + k * step + thickness) for k in range(n)]


def _frame_bands(layer, nav):
    props = layer.temporalProperties()
    return [
        props.bandForTemporalRange(layer, nav.dateTimeRangeForFrameNumber(k))
        for k in range(nav.totalFrameCount())
    ]


@pytest.mark.parametrize(
    "step, thickness",
    [(DZ * 5, DZ * 5), (DZ * 2, DZ * 5), (DZ * 6, DZ * 3), (5.0, 5.0), (1.0, 3.0), (3.0, 1.0)],
    ids=["abut", "overlap", "gap", "abut-5ns", "overlap-5ns", "gap-5ns"],
)
def test_frame_k_shows_band_k_plus_1(qgis_app, tmp_path, step, thickness):
    n = 17
    layer = _layer(tmp_path, n)
    apply_band_windows(layer, _windows(n, step, thickness))
    nav = QgsTemporalNavigationObject()
    assert fit_temporal_navigation(nav, layer) is True
    assert nav.navigationMode() == Qgis.TemporalNavigationMode.Animated
    assert nav.currentFrameNumber() == 0
    assert nav.totalFrameCount() == n
    assert _frame_bands(layer, nav) == list(range(1, n + 1))


def test_one_band_uses_its_own_length(qgis_app, tmp_path):
    layer = _layer(tmp_path, 1)
    apply_band_windows(layer, [(2.0, 4.5)])
    nav = QgsTemporalNavigationObject()
    assert fit_temporal_navigation(nav, layer) is True
    assert nav.frameDuration().seconds() == pytest.approx(2.5)
    assert nav.totalFrameCount() == 1
    assert _frame_bands(layer, nav) == [1]


def test_the_project_time_settings_follow(qgis_app, tmp_path):
    layer = _layer(tmp_path, 3)
    apply_band_windows(layer, _windows(3, 5.0, 5.0, start=0.0))
    nav = QgsTemporalNavigationObject()
    assert fit_temporal_navigation(nav, layer)
    settings = QgsProject.instance().timeSettings()
    assert settings.timeStep() == pytest.approx(5.0)
    assert settings.timeStepUnit() == Qgis.TemporalUnit.Seconds
    assert settings.temporalRange() == nav.temporalExtents()


def test_a_layer_not_in_fixed_range_per_band_is_left_alone(qgis_app, tmp_path):
    layer = _layer(tmp_path, 3)  # never given band windows
    nav = QgsTemporalNavigationObject()
    mode, frame = nav.navigationMode(), nav.frameDuration().seconds()
    assert fit_temporal_navigation(nav, layer) is False
    assert nav.navigationMode() == mode
    assert nav.frameDuration().seconds() == frame


def test_a_layer_without_ranges_is_left_alone(qgis_app, tmp_path):
    layer = _layer(tmp_path, 3)
    layer.temporalProperties().setMode(Qgis.RasterTemporalMode.FixedRangePerBand)
    nav = QgsTemporalNavigationObject()
    assert fit_temporal_navigation(nav, layer) is False
