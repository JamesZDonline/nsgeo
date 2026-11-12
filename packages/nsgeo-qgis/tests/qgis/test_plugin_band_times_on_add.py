"""Band times come from the file whenever a raster layer is added, however it is added."""

from __future__ import annotations

import numpy as np
import pytest
from osgeo import gdal
from qgis.core import Qgis, QgsProject, QgsRasterLayer, QgsTemporalNavigationObject

N = 6


def _write(path, *, windows=True, tags=None):
    ds = gdal.GetDriverByName("GTiff").Create(str(path), 4, 4, N, gdal.GDT_Float32)
    ds.SetGeoTransform((0, 1, 0, 0, 0, -1))
    if tags:
        ds.SetMetadata(tags)
    for b in range(N):
        band = ds.GetRasterBand(b + 1)
        band.WriteArray(np.full((4, 4), b + 1, np.float32))
        if windows:
            lo = -1.8 + b * 1.0825
            band.SetMetadataItem("NSGEO_WINDOW_NS", f"{lo},{lo + 1.0825}")
    ds = None
    return path


@pytest.fixture
def plugin(fake_iface, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    canvas = fake_iface.mapCanvas()
    navigation = QgsTemporalNavigationObject(canvas)
    canvas.setTemporalController(navigation)
    plugin.navigation = navigation
    yield plugin
    plugin.unload()
    QgsProject.instance().removeAllMapLayers()


def _frame_bands(layer, nav):
    props = layer.temporalProperties()
    return [
        props.bandForTemporalRange(layer, nav.dateTimeRangeForFrameNumber(k))
        for k in range(nav.totalFrameCount())
    ]


def test_a_layer_added_by_hand_is_timed_from_its_file_and_fitted(plugin, tmp_path):
    layer = QgsRasterLayer(str(_write(tmp_path / "x.tif")), "x", "gdal")
    assert not layer.temporalProperties().isActive()
    QgsProject.instance().addMapLayer(layer)
    assert layer.temporalProperties().isActive()
    assert plugin.navigation.totalFrameCount() == N
    assert _frame_bands(layer, plugin.navigation) == list(range(1, N + 1))


def test_a_file_without_band_windows_is_left_alone(plugin, tmp_path):
    layer = QgsRasterLayer(str(_write(tmp_path / "old.tif", windows=False)), "old", "gdal")
    QgsProject.instance().addMapLayer(layer)
    assert not layer.temporalProperties().isActive()
    assert plugin.navigation.totalFrameCount() == 0


def test_a_counts_file_is_left_alone(plugin, tmp_path):
    path = _write(tmp_path / "c.tif", tags={"NSGEO_RESAMPLING": "largest_count"})
    layer = QgsRasterLayer(str(path), "c", "gdal")
    QgsProject.instance().addMapLayer(layer)
    assert not layer.temporalProperties().isActive()


def test_other_files_and_providers_are_not_read(plugin, tmp_path, monkeypatch):
    from nsgeo_qgis import plugin as plugin_module

    seen: list[str] = []
    monkeypatch.setattr(
        plugin_module, "restore_band_times", lambda layer, path: seen.append(str(path)) or "set"
    )
    path = _write(tmp_path / "x.png")
    QgsProject.instance().addMapLayer(QgsRasterLayer(str(path), "png", "gdal"))
    from qgis.core import QgsVectorLayer

    QgsProject.instance().addMapLayer(QgsVectorLayer("Point", "pts", "memory"))
    assert seen == []


def test_a_failure_while_wiring_is_logged_and_the_layer_is_still_added(
    plugin, tmp_path, monkeypatch, message_log
):
    from nsgeo_qgis import plugin as plugin_module

    def broken(layer, path):
        raise RuntimeError("the file went away")

    monkeypatch.setattr(plugin_module, "restore_band_times", broken)
    layer = QgsRasterLayer(str(_write(tmp_path / "x.tif")), "x", "gdal")
    QgsProject.instance().addMapLayer(layer)
    assert QgsProject.instance().mapLayer(layer.id()) is not None
    assert any("the file went away" in m for m in message_log)


def test_an_unloaded_plugin_no_longer_reacts(fake_iface, answer_modal, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.unload()
    layer = QgsRasterLayer(str(_write(tmp_path / "x.tif")), "x", "gdal")
    QgsProject.instance().addMapLayer(layer)
    assert not layer.temporalProperties().isActive()
    QgsProject.instance().removeAllMapLayers()


def test_a_reopened_project_is_timed_exactly_and_the_controller_refitted(plugin, tmp_path):
    """QGIS saves band times at whole seconds; reading from the file brings them back exact.
    The controller is fitted again after the read, whatever it was set to in between."""
    from qgis.PyQt.QtCore import QCoreApplication

    layer = QgsRasterLayer(str(_write(tmp_path / "x.tif")), "x", "gdal")
    QgsProject.instance().addMapLayer(layer)
    project_file = str(tmp_path / "p.qgz")
    assert QgsProject.instance().write(project_file)
    QgsProject.instance().clear()
    plugin.navigation.setNavigationMode(Qgis.TemporalNavigationMode.Disabled)
    assert QgsProject.instance().read(project_file)
    for _ in range(5):
        QCoreApplication.processEvents()
    (reopened,) = QgsProject.instance().mapLayersByName("x")
    assert plugin.navigation.totalFrameCount() == N
    assert _frame_bands(reopened, plugin.navigation) == list(range(1, N + 1))


def _save_and_clear(tmp_path) -> str:
    layer = QgsRasterLayer(str(_write(tmp_path / "x.tif")), "x", "gdal")
    QgsProject.instance().addMapLayer(layer)
    project_file = str(tmp_path / "p.qgz")
    assert QgsProject.instance().write(project_file)
    QgsProject.instance().clear()
    return project_file


def test_the_refit_after_a_read_beats_a_panel_that_reads_after_the_layers(plugin, tmp_path):
    """QGIS's Temporal Controller panel restores its own mode from the project after the
    layers are read. A `readProject` slot connected after the plugin's does the same here;
    only the deferred refit puts the controller back."""
    from qgis.PyQt.QtCore import QCoreApplication

    def panel(*_args):
        plugin.navigation.setNavigationMode(Qgis.TemporalNavigationMode.Disabled)

    project_file = _save_and_clear(tmp_path)
    QgsProject.instance().readProject.connect(panel)
    try:
        assert QgsProject.instance().read(project_file)
        for _ in range(5):
            QCoreApplication.processEvents()
        mode = plugin.navigation.navigationMode()
    finally:
        QgsProject.instance().readProject.disconnect(panel)
    assert mode == Qgis.TemporalNavigationMode.Animated
    (reopened,) = QgsProject.instance().mapLayersByName("x")
    assert _frame_bands(reopened, plugin.navigation) == list(range(1, N + 1))


def test_an_unloaded_plugin_does_not_refit_after_a_read(plugin, tmp_path):
    from qgis.PyQt.QtCore import QCoreApplication

    project_file = _save_and_clear(tmp_path)
    plugin.unload()
    plugin.navigation.setNavigationMode(Qgis.TemporalNavigationMode.Disabled)
    assert QgsProject.instance().read(project_file)
    for _ in range(5):
        QCoreApplication.processEvents()
    assert plugin.navigation.navigationMode() == Qgis.TemporalNavigationMode.Disabled


def test_layers_already_in_the_project_are_timed_when_the_plugin_starts(
    fake_iface, answer_modal, tmp_path
):
    import nsgeo_qgis

    layer = QgsRasterLayer(str(_write(tmp_path / "x.tif")), "x", "gdal")
    QgsProject.instance().addMapLayer(layer)
    assert not layer.temporalProperties().isActive()
    canvas = fake_iface.mapCanvas()
    navigation = QgsTemporalNavigationObject(canvas)
    canvas.setTemporalController(navigation)
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    try:
        assert layer.temporalProperties().isActive()
        assert navigation.totalFrameCount() == N
        assert _frame_bands(layer, navigation) == list(range(1, N + 1))
    finally:
        plugin.unload()
        QgsProject.instance().removeAllMapLayers()


def test_a_repaired_layer_is_timed_when_the_project_is_next_opened(plugin, tmp_path):
    """A file moved since the project was saved opens unavailable; re-pointing it (Change Data
    Source) does not add it again, so it is not wired then. The next open does it."""
    import shutil

    from qgis.PyQt.QtCore import QCoreApplication

    project_file = _save_and_clear(tmp_path)
    (tmp_path / "moved").mkdir()
    moved = tmp_path / "moved" / "x.tif"
    shutil.move(str(tmp_path / "x.tif"), str(moved))
    assert QgsProject.instance().read(project_file)
    (bad,) = QgsProject.instance().mapLayersByName("x")
    assert not bad.isValid()
    bad.setDataSource(str(moved), "x", "gdal")
    assert bad.isValid() and not plugin._timed_layer_ids  # not wired by the repair itself
    assert QgsProject.instance().write(project_file)
    QgsProject.instance().clear()
    assert QgsProject.instance().read(project_file)
    for _ in range(5):
        QCoreApplication.processEvents()
    (reopened,) = QgsProject.instance().mapLayersByName("x")
    assert _frame_bands(reopened, plugin.navigation) == list(range(1, N + 1))
