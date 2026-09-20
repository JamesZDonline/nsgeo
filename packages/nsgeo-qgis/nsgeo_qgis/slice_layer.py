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
import warnings
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
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtGui import QColor

from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.log import log as _log

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

    def __init__(self, layers: SiteLayers, parent: QObject | None = None) -> None:
        super().__init__(parent)
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
            if self._layer_gone():
                self.layer = None
                self._create_layer()
            else:
                self.layer.dataProvider().reloadData()
                self._ensure_group_membership()
            if self.layer is None:
                return
            key = (colormap_name, float(limit), bool(unipolar))
            if key != self._renderer_key:
                self._apply_renderer(colormap_name, limit, unipolar)
                self._renderer_key = key
            self.layer.setCustomProperty("nsgeo/window", subtitle)
            self.layer.serverProperties().setAbstract(subtitle)
            self.layer.triggerRepaint()
        except Exception as exc:  # noqa: BLE001 -- reached from a slider slot
            _log(f"could not draw the slice layer: {exc}")

    def _layer_gone(self) -> bool:
        """Whether `self.layer` needs replacing rather than reused.

        Three ways this happens, all real (fix round 1, Important 3,
        verified directly against this build): never created (`None`);
        the C++ object destroyed out from under this Python wrapper --
        `QgsProject.layersWillBeRemoved` is exactly the hazard
        `SiteLayers._on_layers_removed` documents, and this layer is not
        immune to it just because `SiteLayers` does not track it; or
        still alive but no longer registered in the project at all --
        `SiteLayers.detach()` runs on every `site_closed` (every "Open
        site...") and, being written for tables it manages itself, does
        not know this layer exists to preserve it.
        """
        if self.layer is None:
            return True
        if sip.isdeleted(self.layer):
            return True
        return self.layers.project.mapLayer(self.layer.id()) is None

    def _ensure_group_membership(self) -> None:
        """Rejoin `layers.group` if this layer is alive and registered but
        has no node in the CURRENT group -- the other half of Important 3.

        `SiteLayers.detach()` removes the group NODE (not the layer
        itself) on every site close, so an alive, still-registered layer
        can be left with no node anywhere: verified directly, `node in
        tree: True` before a close, `False` after, and still `False` after
        a later site opens a brand new group -- `update()` used to only
        ever test `self.layer is None`, which this layer already was not,
        so it neither rejoined nor regained a node. Pixels kept being
        rewritten correctly; nobody could see them.
        """
        group = self.layers.group
        if group is None or sip.isdeleted(group):
            return
        assert self.layer is not None
        if group.findLayer(self.layer.id()) is None:
            group.addLayer(self.layer)

    def _write(
        self,
        array: np.ndarray,
        geotransform: tuple[float, float, float, float, float, float],
        crs: str,
    ) -> None:
        # Fix round 1, Important 5 / Ruling AA: scoped to this method only
        # (`gdal.ExceptionMgr` restores the PROCESS-WIDE exception mode on
        # exit -- verified directly: `GetUseExceptions()` is 0 both before
        # and after this block, 1 only inside it), because a bare
        # `gdal.UseExceptions()` would change the mode for the whole QGIS
        # process and every other consumer of the bindings, which this
        # plugin does not own. Without this, a failed `Create()` returned
        # `None` and the `.SetGeoTransform` below raised `AttributeError`
        # -- a real failure, but the wrong exception for the wrong reason
        # -- and `band.WriteArray(array)`'s own `CPLErr` return was
        # discarded outright, so a failed write was silently ignored and
        # the next `reloadData()` simply republished whatever was already
        # on disk.
        #
        # `ExceptionMgr` alone does NOT also silence GDAL's one-time
        # "neither UseExceptions() nor DontUseExceptions() has been
        # called" FutureWarning, contrary to what fix round 1's review
        # verified for this exact wrap -- checked directly against this
        # build (GDAL 3.8.4): `gdal._UserHasSpecifiedIfUsingExceptions()`
        # is still `0` *inside* the `with` block below, because
        # `ExceptionMgr` calls the LOCAL `_SetExceptionsLocal`, a
        # different, unrelated flag from the one the warning actually
        # checks (only the real, process-global `gdal.UseExceptions()` /
        # `DontUseExceptions()` sets that one, per `gdal.py` itself) --
        # `Create()` still raised the warning under `-W
        # error::FutureWarning` with the wrap already in place. Silencing
        # the WARNING OUTPUT here, scoped with Python's own `warnings`
        # filter, is not the global change Ruling AA forbids: it never
        # touches any GDAL exception-mode flag, local or global, so every
        # other consumer of these bindings sees exactly the state it saw
        # before this call.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            with gdal.ExceptionMgr(useExceptions=True):
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
                    # Cheap cluster (final review): `dataset.Close()`,
                    # then the local set to `None` -- `slice_export.py`'s
                    # `GeoTiffSliceWriter.write` already uses `Close()` on
                    # this same GDAL build (>= 3.7), which surfaces a
                    # write error at close time instead of leaving it
                    # silent until garbage collection, where a SWIG
                    # destructor cannot raise. Holding the dataset in a
                    # local and setting it to `None` explicitly afterwards
                    # is still needed regardless: a dataset collected
                    # mid-expression (rather than through a bound name) is
                    # a real trap -- it bit the spike behind this plan's
                    # own measurements.
                    dataset.Close()
                    dataset = None

    def _create_layer(self) -> None:
        layer = QgsRasterLayer(str(self.path), LAYER_NAME, "gdal")
        # addToLegend=False: this is a scratch preview, not a durable
        # artefact, and it joins the site's own group below like every
        # other layer here -- it does not sit unparented at legend root.
        self.layers.project.addMapLayer(layer, False)
        self.layer = layer
        # A fresh layer has never had a renderer built for it.
        self._renderer_key = None
        self._ensure_group_membership()

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
            if (
                self.layer is not None
                and not sip.isdeleted(self.layer)
                and self.layers.project.mapLayer(self.layer.id()) is not None
            ):
                self.layers.project.removeMapLayer(self.layer.id())
        except Exception as exc:  # noqa: BLE001 -- see the class docstring
            _log(f"could not clear the slice layer: {exc}")
        finally:
            # Unconditional, even on the exception path above: Important
            # 3's companion hazard is `self.layer.id()` raising
            # `RuntimeError` on an already-deleted wrapper, which must not
            # leave `self.layer` pointing at a dead object forever the way
            # `update()` used to for the same underlying reason.
            self.layer = None
            self._renderer_key = None

    def dispose(self) -> None:
        try:
            self.clear()
        finally:
            shutil.rmtree(self._dir, ignore_errors=True)
