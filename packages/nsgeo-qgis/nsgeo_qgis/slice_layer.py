"""The active slice on the map: a float raster, restyled and reloaded in place.

A real float32 raster with NaN nodata, not a picture. A reader can then
query an amplitude, and the same values go out to the GeoTIFF unchanged --
spec 9.4's reason for exporting float rather than bytes applies just as
well to what is on screen.

Rewritten in place on every tick rather than rebuilt: verified against
this GDAL and QGIS, `reloadData()` refreshes the pixel values, and the
layer's `width()`/`height()` follow even when the cell slider changes the
shape, so a drag never churns the layer tree.

Uncompressed, unlike the export (plan Ruling 3). Measured here at GDAL
3.8.4: `COMPRESS=DEFLATE, PREDICTOR=3` costs 8.8 ms for a 300x300 float
band and 25.2 ms at 600x600, against 1.0 and 1.3 ms uncompressed. Spec
9.5's option set is argued for a file someone keeps; this one lives in a
scratch directory for the length of a session.

That scratch file is also why this layer is a PREVIEW and says so in its
name: it is deliberately outside the project tree, so it cannot be
committed by accident or mistaken for the artefact -- and a saved QGIS
project would find it gone. `slice_export.py` writes the durable one.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import numpy as np
from nsgeo.render import colormap
from nsgeo.slices import CubeFrame, to_north_up
from osgeo import gdal
from qgis.core import (
    QgsColorRampShader,
    QgsCoordinateReferenceSystem,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtGui import QColor

from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.log import log as _log
from nsgeo_qgis.session import SiteSession

_CREATION_OPTIONS = ["INTERLEAVE=BAND", "TILED=NO", "BIGTIFF=IF_SAFER"]
LAYER_NAME = "Slice (live preview)"


def build_shader(lut: np.ndarray, limit: float, unipolar: bool) -> QgsRasterShader:
    """A 256-stop ramp from a core colour table.

    The core's LUT is the authority on colour, here as in the profile
    view, so the map and the radargram cannot drift apart. All 256 stops
    rather than a subsample: it is rebuilt only when the palette or the
    limit changes, never per tick, and a subsampled ramp would
    interpolate across the non-linear stretch of `amp_heat`.
    """
    lo = 0.0 if unipolar else -float(limit)
    hi = float(limit)
    items = [
        QgsColorRampShader.ColorRampItem(
            lo + (hi - lo) * i / 255.0,
            QColor(int(lut[i, 0]), int(lut[i, 1]), int(lut[i, 2])),
            f"{lo + (hi - lo) * i / 255.0:.3f}",
        )
        for i in range(256)
    ]
    function = QgsColorRampShader()
    function.setColorRampType(QgsColorRampShader.Type.Interpolated)
    function.setColorRampItemList(items)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(function)
    return shader


class SliceLayer(QObject):
    """The one live raster layer showing the dock's current slice.

    Owns a scratch GeoTIFF and, once created, one `QgsRasterLayer` that is
    rewritten and reloaded rather than replaced -- see the module
    docstring for why. Every public method guards its own body: `update`
    is reached from a slider slot, and an exception escaping a slot
    aborts the CI container (see `plugin.py`'s module docstring).
    """

    def __init__(
        self, session: SiteSession, layers: SiteLayers, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.layers = layers
        self._dir = Path(tempfile.mkdtemp(prefix="nsgeo-slice-"))
        self.path = self._dir / "slice.tif"
        self.layer: QgsRasterLayer | None = None
        #: `(colormap_name, limit, unipolar)` the current renderer was
        #: built for, or `None` before the first one. Rebuilding a 256-stop
        #: shader on every tick of the depth slider is waste, and the
        #: renderer is what makes the layer flicker if replaced needlessly.
        self._renderer_key: tuple[str, float, bool] | None = None

    # ---- the one thing this class does -------------------------------
    def update(
        self,
        values: np.ndarray,
        frame: CubeFrame,
        *,
        limit: float,
        colormap_name: str,
        unipolar: bool,
        subtitle: str,
    ) -> None:
        try:
            array, geotransform = to_north_up(values, frame)
            self._write(array, geotransform, frame.crs)
            if self.layer is None:
                self._create_layer()
            else:
                self.layer.dataProvider().reloadData()
            if self.layer is None:
                return
            key = (colormap_name, float(limit), bool(unipolar))
            if key != self._renderer_key:
                self._apply_renderer(colormap_name, limit, unipolar)
                self._renderer_key = key
            self.layer.setCustomProperty("nsgeo/window", subtitle)
            self.layer.setAbstract(subtitle)
            self.layer.triggerRepaint()
        except Exception as exc:  # noqa: BLE001 -- reached from a slider slot
            _log(f"could not draw the slice layer: {exc}")

    def _write(
        self,
        array: np.ndarray,
        geotransform: tuple[float, float, float, float, float, float],
        crs: str,
    ) -> None:
        driver = gdal.GetDriverByName("GTiff")
        height, width = array.shape
        dataset = driver.Create(
            str(self.path), width, height, 1, gdal.GDT_Float32, options=_CREATION_OPTIONS
        )
        try:
            dataset.SetGeoTransform(geotransform)
            dataset.SetProjection(QgsCoordinateReferenceSystem(crs).toWkt())
            band = dataset.GetRasterBand(1)
            band.SetNoDataValue(float("nan"))
            band.WriteArray(array)
            band.FlushCache()
        finally:
            # Hold the dataset in a local and set it to None explicitly:
            # GDAL flushes to disk on destruction, and a dataset collected
            # mid-expression (rather than through a bound name) is a real
            # trap -- it bit the spike behind this plan's own measurements.
            dataset = None

    def _create_layer(self) -> None:
        layer = QgsRasterLayer(str(self.path), LAYER_NAME, "gdal")
        project = self.layers.project
        # addToLegend=False: this is a scratch preview, not a durable
        # artefact, and it joins the site's own group below like every
        # other layer here -- it does not sit unparented at legend root.
        project.addMapLayer(layer, False)
        if self.layers.group is not None:
            self.layers.group.addLayer(layer)
        self.layer = layer
        # A fresh layer has never had a renderer built for it.
        self._renderer_key = None

    def _apply_renderer(self, colormap_name: str, limit: float, unipolar: bool) -> None:
        assert self.layer is not None
        provider = self.layer.dataProvider()
        shader = build_shader(colormap(colormap_name), limit, unipolar)
        renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
        lo = 0.0 if unipolar else -float(limit)
        renderer.setClassificationMin(lo)
        renderer.setClassificationMax(float(limit))
        self.layer.setRenderer(renderer)

    # ---- lifecycle ------------------------------------------------------
    def clear(self) -> None:
        try:
            if self.layer is not None:
                self.layers.project.removeMapLayer(self.layer.id())
                self.layer = None
                self._renderer_key = None
        except Exception as exc:  # noqa: BLE001 -- see the class docstring
            _log(f"could not clear the slice layer: {exc}")

    def dispose(self) -> None:
        try:
            self.clear()
        finally:
            shutil.rmtree(self._dir, ignore_errors=True)
