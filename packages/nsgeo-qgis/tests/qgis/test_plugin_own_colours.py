"""#180: a slice coloured with the user's own QGIS symbology."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.render import colormap
from nsgeo_qgis import own_colours
from nsgeo_qgis.slice_layer import build_shader
from osgeo import gdal
from qgis.core import (
    QgsColorRampShader,
    QgsContrastEnhancement,
    QgsCoordinateReferenceSystem,
    QgsRasterLayer,
    QgsRasterMinMaxOrigin,
    QgsSingleBandGrayRenderer,
    QgsSingleBandPseudoColorRenderer,
)

#: 20 columns by 10 rows, 1 m cells, top-left at (500000, 4000010).
GT = (500000.0, 1.0, 0.0, 4000010.0, 0.0, -1.0)


def _tif(path, array):
    ds = gdal.GetDriverByName("GTiff").Create(str(path), array.shape[1], array.shape[0], 1, 6)
    ds.SetGeoTransform(GT)
    ds.SetProjection(QgsCoordinateReferenceSystem("EPSG:32616").toWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(float("nan"))
    band.WriteArray(array)
    ds.Close()


def _ramp_values():
    return np.tile(np.linspace(-4.0, 6.0, 20, dtype=np.float32), (10, 1))


@pytest.fixture
def layer(qgis_app, tmp_path):
    path = tmp_path / "slice.tif"
    _tif(path, _ramp_values())
    made = QgsRasterLayer(str(path), "slice", "gdal")
    assert made.isValid()
    return made


def _shade(renderer, value):
    ok, r, g, b, _ = renderer.shader().rasterShaderFunction().shade(value)
    assert ok
    return (r, g, b)


def _set_origin(layer, limits, extent=QgsRasterMinMaxOrigin.Extent.WholeRaster, **kwargs):
    renderer = layer.renderer().clone()
    origin = renderer.minMaxOrigin()
    origin.setLimits(limits)
    origin.setExtent(extent)
    origin.setStatAccuracy(QgsRasterMinMaxOrigin.StatAccuracy.Exact)
    if "lower" in kwargs:
        origin.setCumulativeCutLower(kwargs["lower"])
        origin.setCumulativeCutUpper(kwargs["upper"])
    if "factor" in kwargs:
        origin.setStdDevFactor(kwargs["factor"])
    renderer.setMinMaxOrigin(origin)
    layer.setRenderer(renderer)


# ---- the starting point -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "unipolar"), [("seismic", False), ("grey_black_high", False), ("amp_heat", True)]
)
def test_the_seed_draws_what_the_plugin_drew(layer, name, unipolar):
    own_colours.seed_style(layer, name, 5.0, unipolar)
    ours = layer.renderer()
    theirs = QgsSingleBandPseudoColorRenderer(
        layer.dataProvider(), 1, build_shader(colormap(name), 5.0, unipolar)
    )
    lo = 0.0 if unipolar else -5.0
    for value in np.linspace(lo, 5.0, 41):
        got, want = _shade(ours, value), _shade(theirs, value)
        assert max(abs(a - b) for a, b in zip(got, want)) <= 2, (value, got, want)


def test_the_seed_is_an_editable_ramp_held_as_typed_numbers(layer):
    own_colours.seed_style(layer, "seismic", 5.0, False)
    renderer = layer.renderer()
    assert isinstance(renderer, QgsSingleBandPseudoColorRenderer)
    assert (renderer.classificationMin(), renderer.classificationMax()) == (-5.0, 5.0)
    assert renderer.minMaxOrigin().limits() == QgsRasterMinMaxOrigin.Limits.NotSet
    function = renderer.shader().rasterShaderFunction()
    assert function.sourceColorRamp() is not None
    assert function.sourceColorRamp().type() == "gradient"
    assert len(function.colorRampItemList()) == 3  # blue, white at zero, red


# ---- the style as text --------------------------------------------------------------------


def test_the_style_text_round_trips_onto_another_layer(layer, tmp_path):
    own_colours.seed_style(layer, "amp_heat", 2.5, True)
    text = own_colours.style_text(layer)
    other_path = tmp_path / "other.tif"
    _tif(other_path, _ramp_values())
    other = QgsRasterLayer(str(other_path), "other", "gdal")
    own_colours.apply_style_text(other, text)
    assert isinstance(other.renderer(), QgsSingleBandPseudoColorRenderer)
    assert own_colours.style_range(other) == (0.0, 2.5)
    assert own_colours.style_text(other) == text


def test_unreadable_style_text_is_refused(layer):
    with pytest.raises(ValueError):
        own_colours.apply_style_text(layer, "not a style at all <")


# ---- following QGIS's min/max settings on a new slice --------------------------------------


def test_typed_numbers_stay(layer):
    own_colours.seed_style(layer, "seismic", 5.0, False)
    assert not own_colours.refit(layer, _ramp_values() * 3.0, GT)
    assert own_colours.style_range(layer) == (-5.0, 5.0)


def test_a_minimum_maximum_range_is_worked_out_again_keeping_the_colours(layer):
    own_colours.seed_style(layer, "seismic", 5.0, False)
    _set_origin(layer, QgsRasterMinMaxOrigin.Limits.MinimumMaximum)
    values = _ramp_values()
    values[0, 0] = np.nan
    assert own_colours.refit(layer, values, GT)
    lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
    assert own_colours.style_range(layer) == pytest.approx((lo, hi))
    items = layer.renderer().shader().rasterShaderFunction().colorRampItemList()
    # White keeps its place along the ramp (entry 128 of 256), in the new range.
    assert [i.value for i in items] == pytest.approx([lo, lo + 128 / 255 * (hi - lo), hi])
    assert items[1].color.name() == "#ffffff"
    assert _shade(layer.renderer(), hi)[0] == 255


def test_a_cumulative_cut_uses_the_chosen_percentages(layer):
    own_colours.seed_style(layer, "seismic", 5.0, False)
    _set_origin(layer, QgsRasterMinMaxOrigin.Limits.CumulativeCut, lower=0.1, upper=0.9)
    values = _ramp_values()
    assert own_colours.refit(layer, values, GT)
    want = tuple(np.percentile(values, [10.0, 90.0]))
    assert own_colours.style_range(layer) == pytest.approx(want)


def test_a_mean_and_standard_deviation_range_uses_the_chosen_factor(layer):
    own_colours.seed_style(layer, "seismic", 5.0, False)
    _set_origin(layer, QgsRasterMinMaxOrigin.Limits.StdDev, factor=1.0)
    values = _ramp_values()
    assert own_colours.refit(layer, values, GT)
    mean, sd = float(values.mean()), float(values.std())
    assert own_colours.style_range(layer) == pytest.approx((mean - sd, mean + sd))


def test_current_canvas_fits_the_cells_in_view(layer):
    own_colours.seed_style(layer, "seismic", 5.0, False)
    _set_origin(
        layer,
        QgsRasterMinMaxOrigin.Limits.MinimumMaximum,
        extent=QgsRasterMinMaxOrigin.Extent.FixedCanvas,
    )
    values = _ramp_values()
    # The right half of the slice: columns 10..19.
    view = (500010.0, 4000000.0, 500020.0, 4000010.0)
    assert own_colours.refit(layer, values, GT, view)
    assert own_colours.style_range(layer) == pytest.approx(
        (float(values[:, 10:].min()), float(values[:, 10:].max()))
    )


def test_updated_canvas_is_left_to_qgis(layer):
    own_colours.seed_style(layer, "seismic", 5.0, False)
    _set_origin(
        layer,
        QgsRasterMinMaxOrigin.Limits.MinimumMaximum,
        extent=QgsRasterMinMaxOrigin.Extent.UpdatedCanvas,
    )
    assert not own_colours.refit(layer, _ramp_values(), GT)
    assert own_colours.legend_text(layer) == "your own colours · fitted to the map view"


def test_a_slice_with_nothing_to_fit_keeps_the_range(layer):
    own_colours.seed_style(layer, "seismic", 5.0, False)
    _set_origin(layer, QgsRasterMinMaxOrigin.Limits.MinimumMaximum)
    assert not own_colours.refit(layer, np.full((10, 20), np.nan, dtype=np.float32), GT)
    assert own_colours.style_range(layer) == (-5.0, 5.0)


def test_a_grey_renderer_takes_the_new_range_in_its_contrast_stretch(layer):
    renderer = QgsSingleBandGrayRenderer(layer.dataProvider(), 1)
    enhancement = QgsContrastEnhancement(layer.dataProvider().dataType(1))
    enhancement.setContrastEnhancementAlgorithm(
        QgsContrastEnhancement.ContrastEnhancementAlgorithm.StretchToMinimumMaximum
    )
    enhancement.setMinimumValue(0.0)
    enhancement.setMaximumValue(1.0)
    renderer.setContrastEnhancement(enhancement)
    layer.setRenderer(renderer)
    _set_origin(layer, QgsRasterMinMaxOrigin.Limits.MinimumMaximum)
    assert own_colours.refit(layer, _ramp_values(), GT)
    assert own_colours.style_range(layer) == pytest.approx((-4.0, 6.0))


def test_a_ramp_typed_by_hand_keeps_its_proportions(layer):
    own_colours.seed_style(layer, "seismic", 5.0, False)
    renderer = layer.renderer().clone()
    function = renderer.shader().rasterShaderFunction()
    items = function.colorRampItemList()
    # Spend the ramp's first half on -5..-4: a hand-placed stop.
    items[1] = QgsColorRampShader.ColorRampItem(-4.0, items[1].color, "")
    function.setColorRampItemList(items)
    layer.setRenderer(renderer)
    assert own_colours.set_range(layer, 0.0, 100.0)
    moved = layer.renderer().shader().rasterShaderFunction().colorRampItemList()
    assert [i.value for i in moved] == pytest.approx([0.0, 10.0, 100.0])


# ---- the legend line and the crop ---------------------------------------------------------


def test_the_legend_line_names_the_range(layer):
    own_colours.seed_style(layer, "seismic", 5.0, False)
    assert own_colours.legend_text(layer) == "your own colours · -5 – 5"
    assert own_colours.legend_text(None) == "your own colours"


def test_crop_outside_the_slice_is_empty():
    values = _ramp_values()
    assert own_colours.crop(values, GT, (0.0, 0.0, 1.0, 1.0)).size == 0
    assert own_colours.crop(values, GT, (499000.0, 3999000.0, 501000.0, 4001000.0)).shape == (
        10,
        20,
    )
