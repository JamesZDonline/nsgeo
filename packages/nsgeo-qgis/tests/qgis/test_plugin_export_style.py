"""The `.qml` written beside an export: ramp, stretch, and bilinear zoomed in."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.render import colormap
from nsgeo_qgis.export_style import write_style
from osgeo import gdal
from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsSingleBandPseudoColorRenderer,
)


@pytest.fixture
def tif(tmp_path):
    path = tmp_path / "export.tif"
    ds = gdal.GetDriverByName("GTiff").Create(str(path), 20, 20, 2, gdal.GDT_Float32)
    ds.SetGeoTransform((500.0, 0.5, 0.0, 700.0, 0.0, -0.5))
    for i in (1, 2):
        ds.GetRasterBand(i).WriteArray(np.linspace(-1, 1, 400, dtype=np.float32).reshape(20, 20))
    ds.Close()
    return path


def _items(layer):
    return layer.renderer().shader().rasterShaderFunction().colorRampItemList()


def test_the_style_file_sits_beside_the_raster_under_its_name(qgis_app, tif):
    out = write_style(tif, limit=0.8, colormap_name="amp_heat", unipolar=False)
    assert out == tif.with_suffix(".qml") and out.exists()


def test_a_fresh_layer_loads_the_style_as_its_default(qgis_app, tif):
    write_style(tif, limit=0.8, colormap_name="amp_heat", unipolar=False)
    layer = QgsRasterLayer(str(tif), "export", "gdal")  # no style call: the default is the .qml
    assert layer.isValid()
    renderer = layer.renderer()
    assert isinstance(renderer, QgsSingleBandPseudoColorRenderer)
    assert renderer.classificationMin() == pytest.approx(-0.8)
    assert renderer.classificationMax() == pytest.approx(0.8)
    items = _items(layer)
    assert len(items) == 256
    lut = colormap("amp_heat")
    assert items[0].color.red() == lut[0, 0] and items[255].color.blue() == lut[255, 2]
    assert items[0].value == pytest.approx(-0.8) and items[255].value == pytest.approx(0.8)
    # QgsProject path too, as the plugin adds it.
    project = QgsProject()
    project.addMapLayer(layer)
    assert project.mapLayers()


def test_a_unipolar_ramp_starts_at_zero(qgis_app, tif):
    write_style(tif, limit=4.0, colormap_name="amp_black_high", unipolar=True)
    layer = QgsRasterLayer(str(tif), "export", "gdal")
    assert layer.renderer().classificationMin() == 0.0
    assert layer.renderer().classificationMax() == pytest.approx(4.0)


def test_the_style_zooms_in_bilinear(qgis_app, tif):
    from qgis.core import Qgis, QgsBilinearRasterResampler

    write_style(tif, limit=1.0, colormap_name="amp_heat", unipolar=False)
    layer = QgsRasterLayer(str(tif), "export", "gdal")
    assert isinstance(layer.resampleFilter().zoomedInResampler(), QgsBilinearRasterResampler)
    assert layer.resamplingStage() == Qgis.RasterResamplingStage.ResampleFilter


def test_a_second_write_replaces_the_first(qgis_app, tif):
    write_style(tif, limit=1.0, colormap_name="amp_heat", unipolar=False)
    write_style(tif, limit=2.0, colormap_name="amp_heat", unipolar=False)
    layer = QgsRasterLayer(str(tif), "export", "gdal")
    assert layer.renderer().classificationMax() == pytest.approx(2.0)
