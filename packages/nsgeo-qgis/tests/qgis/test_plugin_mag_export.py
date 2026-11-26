"""Export GeoTIFF… on the Mag panel: the file, its style, replacing it, its layer."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.render import colormap
from nsgeo_qgis import mag_engine
from nsgeo_qgis.plugin import NsgeoPlugin
from nsgeo_qgis.session import SURVEY_FILE
from osgeo import gdal
from plugin_testing import read_bands
from qgis.core import QgsProject, QgsRasterLayer
from qgis.PyQt.QtCore import QCoreApplication, QEvent
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox


@pytest.fixture
def plugin(fake_iface, qgis_app):
    p = NsgeoPlugin(fake_iface)
    p.initGui()
    messages = []
    p.message = lambda text, level=None, title="nsgeo", duration=6: messages.append(text)
    p.messages = messages
    try:
        yield p
    finally:
        if p.session.is_open and p.session.dirty:
            p.session.save()
        p.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()


@pytest.fixture
def shown(plugin, mag_site):
    """The plugin on the mag site with the Mag panel drawn on M1. Yields `(plugin, root)`."""
    _, root = mag_site
    plugin.session.open_site(root / SURVEY_FILE)
    QCoreApplication.processEvents()
    plugin.mag_dock.show_grid("M1")
    plugin.mag_dock.refresh(closed_ok=True)
    assert plugin.mag_dock.current_map() is not None
    return plugin, root


def _save_as(answer_modal, path):
    return answer_modal(QFileDialog, "getSaveFileName", (str(path), "GeoTIFF (*.tif)"))


def _layers_reading(path):
    return [
        layer
        for layer in QgsProject.instance().mapLayers().values()
        if layer.source().replace("\\", "/") == str(path).replace("\\", "/")
    ]


def test_exporting_this_grid_writes_one_band_in_nt(shown, answer_modal):
    plugin, root = shown
    target = root / "mag-M1.tif"
    calls = _save_as(answer_modal, target)
    expected = plugin.mag_dock.export_map()
    plugin.mag_dock.export_requested.emit()

    assert calls[0][0][1] == "Export the mag map"
    assert calls[0][0][2] == str(root / "mag-M1.tif")
    assert calls[0][0][3] == "GeoTIFF (*.tif)"
    bands = read_bands(target)
    assert len(bands) == 1 and bands[0].dtype == np.float32
    np.testing.assert_array_equal(bands[0], expected.array)
    assert np.isnan(bands[0]).any() == np.isnan(expected.array).any()
    ds = gdal.Open(str(target))
    try:
        assert ds.GetGeoTransform() == pytest.approx(expected.lattice.geotransform)
        assert ds.GetRasterBand(1).GetDescription() == "Magnetic gradient (nT)"
        meta = ds.GetMetadata()
        assert meta["NSGEO_INSTRUMENT"] == "mag"
        assert meta["NSGEO_UNITS"] == "nT"
        assert meta["NSGEO_GRIDS"] == "M1"
        for key in (
            "NSGEO_CELL_M",
            "NSGEO_INTERPOLATION",
            "NSGEO_MAX_DISTANCE_M",
            "NSGEO_SMOOTH_X_M",
            "NSGEO_SMOOTH_Y_M",
        ):
            assert key in meta
    finally:
        ds.Close()
    assert target.with_suffix(".qml").exists()
    assert len(_layers_reading(target)) == 1
    assert _layers_reading(target)[0].name() == "mag-M1"
    assert plugin.messages[-1] == "Exported mag-M1.tif."


def test_the_site_scope_defaults_to_mag_site_tif(shown, answer_modal):
    plugin, root = shown
    plugin.mag_dock.set_scope("site")
    plugin.mag_dock.refresh(closed_ok=True)
    calls = _save_as(answer_modal, root / "mag-site.tif")
    plugin.mag_dock.export_requested.emit()
    assert calls[0][0][2] == str(root / "mag-site.tif")
    assert plugin.messages[-1] == "Exported mag-site.tif."


def test_the_style_follows_the_panel(shown, answer_modal):
    plugin, root = shown
    dock = plugin.mag_dock
    target = root / "a.tif"
    _save_as(answer_modal, target)
    dock.export_requested.emit()
    mosaic = dock.export_map()
    layer = QgsRasterLayer(str(target), "a", "gdal")
    lut = colormap(dock.palette())
    renderer = layer.renderer()
    assert renderer.classificationMin() == pytest.approx(mosaic.centre() - mosaic.limit())
    assert renderer.classificationMax() == pytest.approx(mosaic.centre() + mosaic.limit())
    items = renderer.shader().rasterShaderFunction().colorRampItemList()
    assert items[0].color.getRgb()[:3] == tuple(int(v) for v in lut[0])

    # Own colours: the user's style is what is written.
    dock.colours_combo.setCurrentIndex(1)
    dock.refresh(closed_ok=True)
    from nsgeo_qgis.own_colours import set_range

    set_range(plugin.mag_layer.layer, -3.0, 7.0)
    assert plugin.mag_layer.own_style_now() is not None
    second = root / "b.tif"
    _save_as(answer_modal, second)
    dock.export_requested.emit()
    written = QgsRasterLayer(str(second), "b", "gdal")
    assert written.renderer().classificationMin() == pytest.approx(-3.0)
    assert written.renderer().classificationMax() == pytest.approx(7.0)


def test_exporting_over_a_shown_file_asks_then_replaces_the_layer(shown, answer_modal):
    plugin, root = shown
    dock = plugin.mag_dock
    target = root / "mag-M1.tif"
    _save_as(answer_modal, target)
    dock.export_requested.emit()
    old = target.read_bytes()
    assert len(_layers_reading(target)) == 1

    # Change the picture, so a second export would differ.
    dock.cell_spin.setValue(0.25)
    dock.refresh(closed_ok=True)

    asks = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.No)
    dock.export_requested.emit()
    assert asks[0][0][1] == "Replace export"
    assert asks[0][0][2] == "mag-M1.tif is shown in the project. Replace it and its layer?"
    assert target.read_bytes() == old
    assert len(_layers_reading(target)) == 1

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Yes)
    dock.export_requested.emit()
    assert target.read_bytes() != old
    layers = _layers_reading(target)
    assert len(layers) == 1
    (band,) = read_bands(target)
    np.testing.assert_array_equal(band, dock.export_map().array)


def test_an_export_lands_above_the_mag_layer(shown, answer_modal):
    plugin, root = shown
    group = plugin.layers.group
    mag_id = plugin.mag_layer.layer.id()

    def index(layer):
        return group.children().index(group.findLayer(layer.id()))

    target = root / "mag-M1.tif"
    _save_as(answer_modal, target)
    plugin.mag_dock.export_requested.emit()
    (exported,) = _layers_reading(target)
    assert index(exported) + 1 == index(plugin.mag_layer.layer)
    assert group.findLayer(mag_id) is not None

    # A GPR export goes through the same path.
    gpr = root / "gpr.tif"
    ds = gdal.GetDriverByName("GTiff").Create(str(gpr), 4, 4, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((500.0, 0.5, 0.0, 700.0, 0.0, -0.5))
    ds.Close()
    problem = plugin._add_export_layer(
        gpr, limit=1.0, palette="amp_heat", unipolar=False, temporal=None
    )
    assert problem is None
    (slice_export,) = _layers_reading(gpr)
    assert index(slice_export) + 1 == index(plugin.mag_layer.layer)


def test_a_map_too_large_is_refused(shown, answer_modal, monkeypatch):
    plugin, root = shown
    target = root / "mag-M1.tif"
    _save_as(answer_modal, target)
    monkeypatch.setattr(mag_engine, "MAG_EXPORT_MAX_PIXELS", 100)
    plugin.mag_dock.export_requested.emit()
    assert plugin.messages[-1] == (
        f"The mag map is too large to export at {plugin.mag_dock.settings().cell:g} m. "
        "Choose a coarser cell."
    )
    assert not target.exists()


def test_export_is_disabled_with_nothing_drawn(plugin, mag_site):
    _, root = mag_site
    assert not plugin.mag_dock.export_button.isEnabled()
    plugin.session.open_site(root / SURVEY_FILE)
    QCoreApplication.processEvents()
    plugin.mag_dock.show_grid("M2")  # no file on M2
    plugin.mag_dock.refresh(closed_ok=True)
    assert plugin.mag_dock.current_map() is None
    assert not plugin.mag_dock.export_button.isEnabled()
    assert plugin.mag_dock.export_map() is None
    plugin.mag_dock.show_grid("M1")
    plugin.mag_dock.refresh(closed_ok=True)
    assert plugin.mag_dock.export_button.isEnabled()
