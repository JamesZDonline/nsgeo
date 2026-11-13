"""The active slice on the map: a float raster, restyled and repointed in place.

A real float32 raster with NaN nodata, not a picture. A reader can then
query an amplitude, and the same values go out to the GeoTIFF unchanged --
spec 9.4's reason for exporting float rather than bytes applies just as
well to what is on screen.

The layer object is kept across ticks rather than rebuilt, so a drag
never churns the layer tree: each tick points the same `QgsRasterLayer`
at a new file with `setDataSource()`, and `width()`/`height()` follow
even when the cell slider changes the shape. Every tick writes a NEW file
rather than rewriting one in place, because Windows cannot delete or
replace a file QGIS holds open, and GDAL's `Create()` deletes first -- an
in-place rewrite failed there with "Permission denied" on the second
tick (found in the 0.1.0 walkthrough; Linux allows it, so CI never saw
it). QGIS's render threads can keep the old file open briefly after the
switch too, so superseded files are deleted best-effort, at the end of
the tick that supersedes them (#54); one a render thread still holds is
met again by the next tick's scan.

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

import contextlib
import os
import shutil
import tempfile
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from nsgeo.render import colormap
from nsgeo.slices import CubeFrame, to_north_up
from osgeo import gdal
from qgis.core import (
    Qgis,
    QgsBilinearRasterResampler,
    QgsColorRampShader,
    QgsCoordinateReferenceSystem,
    QgsDataProvider,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtGui import QColor

from nsgeo_qgis import own_colours
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.log import log as _log

#: Deletion goes through this name so a test can refuse one file without
#: patching `os.remove` for the whole process.
_remove = os.remove
_CREATION_OPTIONS = ["INTERLEAVE=BAND", "TILED=NO", "BIGTIFF=IF_SAFER"]
LAYER_NAME = "Slice (live preview)"
#: M12 spec 4.5: the same one layer, renamed while the dock shows the whole site.
SITE_LAYER_NAME = "Site slice (live preview)"
#: M19a: the magnetometer map, a second layer beside the slice.
MAG_LAYER_NAME = "Mag (live preview)"


def build_shader(
    lut: np.ndarray, limit: float, unipolar: bool, centre: float = 0.0
) -> QgsRasterShader:
    """A 256-stop ramp from a core colour table.

    The core's LUT is the authority on colour, here as in the profile
    view, so the map and the radargram cannot drift apart. All 256 stops
    rather than a subsample: it is rebuilt only when the palette or the
    limit changes, never per tick, and a subsampled ramp would
    interpolate across the non-linear stretch of `amp_heat`.

    A bipolar ramp runs `centre - limit` to `centre + limit` (a magnetometer
    map is centred on its median, M19a); a unipolar one ignores `centre`.
    """
    lo = 0.0 if unipolar else float(centre) - float(limit)
    hi = float(limit) if unipolar else float(centre) + float(limit)
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


def apply_smooth_resampling(layer: QgsRasterLayer) -> None:
    """Draw `layer` smooth when zoomed in: QGIS otherwise shows each pixel as
    a hard block. Zoomed-out drawing is left as QGIS has it."""
    layer.resampleFilter().setZoomedInResampler(QgsBilinearRasterResampler())
    # Pinned so a provider-level ("early") resampling setting cannot bypass
    # the filter above.
    layer.setResamplingStage(Qgis.RasterResamplingStage.ResampleFilter)


def apply_renderer(
    layer: QgsRasterLayer,
    colormap_name: str,
    limit: float,
    unipolar: bool,
    centre: float = 0.0,
) -> None:
    """The slice look on `layer`: pseudocolour ramp over band 1 at `limit`, smooth zoomed in."""
    shader = build_shader(colormap(colormap_name), limit, unipolar, centre)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    renderer.setClassificationMin(0.0 if unipolar else float(centre) - float(limit))
    renderer.setClassificationMax(float(limit) if unipolar else float(centre) + float(limit))
    layer.setRenderer(renderer)
    apply_smooth_resampling(layer)


class SliceLayer(QObject):
    """The one live raster layer showing the dock's current slice.

    Owns scratch GeoTIFFs and, once created, one `QgsRasterLayer` that is
    repointed at the newest one rather than replaced -- see the module
    docstring for why. Every public method guards its own body: `update`
    is reached from a slider slot, and an exception escaping a slot
    aborts the CI container (see `plugin.py`'s module docstring).

    #180: with `own=True` the layer wears the user's own QGIS symbology
    instead of the plugin's palette and stretch (`own_colours`). The plugin
    then never replaces the renderer: it puts the user's style on once, and
    on each new slice only works a computed min/max out again. An edit the
    user makes in Layer Properties is reported through `own_style_changed`
    with the new style, so the dock can remember it; the plugin's own changes
    to the layer are not edits, and are not reported.
    """

    #: The user's own style (QGIS style XML) changed: they edited it in Layer
    #: Properties, or the plugin seeded it from its palette (#180).
    own_style_changed = pyqtSignal(str)

    def __init__(self, layers: SiteLayers, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.layers = layers
        self._dir = Path(tempfile.mkdtemp(prefix="nsgeo-slice-"))
        #: The CURRENT file: the one the layer reads. Replaced, never
        #: rewritten, on every update, and moved only once the layer
        #: actually reads the new one.
        self.path = self._dir / "slice-000000.tif"
        self._serial = 0
        self.layer: QgsRasterLayer | None = None
        #: `("nsgeo", colormap_name, limit, unipolar)` the current renderer
        #: was built for, `("own", style)` while the layer wears the user's
        #: own style (#180), or `None` before the first one. Rebuilding a
        #: 256-stop shader on every tick of the depth slider is waste, and the
        #: renderer is what makes the layer flicker if replaced needlessly.
        self._renderer_key: tuple[Any, ...] | None = None
        #: A fresh layer's own symbology, kept by `_create_layer` (#180).
        self._plain_style: str | None = None
        #: Above zero while this class changes the layer itself, so the
        #: layer's own style signals are not taken for the user's edits.
        self._busy = 0
        #: The map view in a given CRS, as (xmin, ymin, xmax, ymax), for a
        #: style whose min/max is computed over the "Current canvas"; set by
        #: the plugin, which has the canvas. None: the whole slice.
        self.extent_in: Callable[[QgsCoordinateReferenceSystem], Any] | None = None
        #: The name this class last gave the layer (`LAYER_NAME` or
        #: `SITE_LAYER_NAME`), or `None` before the first. Compared with the
        #: requested name rather than `layer.name()`, so a user's rename is
        #: not undone on the next tick.
        self._name: str | None = None

    # ---- the one thing this class does -------------------------------
    def update(
        self,
        values: np.ndarray,
        frame: CubeFrame,
        *,
        limit: float | Callable[[], float],
        colormap_name: str,
        unipolar: bool,
        subtitle: str,
        counts: bool = False,
        own: bool = False,
        own_style: str | None = None,
    ) -> None:
        """One grid's slice: resampled north-up, then drawn by `update_north_up`.
        `counts=True` is for the coverage view: counts are taken, never blended,
        and always drawn in the plugin's colours."""
        try:
            array, geotransform = to_north_up(values, frame, counts=counts)
            self.update_north_up(
                array,
                geotransform,
                frame.crs,
                limit=limit,
                colormap_name=colormap_name,
                unipolar=unipolar,
                subtitle=subtitle,
                own=own and not counts,
                own_style=own_style,
            )
        except Exception as exc:  # noqa: BLE001 -- reached from a slider slot
            _log(f"could not draw the slice layer: {exc}")

    def update_north_up(
        self,
        array: np.ndarray,
        geotransform: tuple[float, ...],
        crs: str,
        *,
        limit: float | Callable[[], float],
        colormap_name: str,
        unipolar: bool,
        subtitle: str,
        name: str = LAYER_NAME,
        own: bool = False,
        own_style: str | None = None,
        centre: float = 0.0,
    ) -> None:
        """Draw an array that is already north-up on `geotransform` (M12: the
        site lattice, spec 4.5). Every path to the map comes through here, so
        each one writes a fresh file and repoints, never rewrites the file the
        layer reads (the Windows rule in the module docstring).

        `name` renames the existing layer in place, rather than rebuilding
        it, so switching scope never churns the layer tree. It is applied
        only when it differs from the name this class last gave the layer
        -- a scope switch -- so a rename by the user survives every tick in
        between (0.1.0's rule for `_repoint`).

        The extent and CRS are checked explicitly. Under M11's
        `reloadData()` the provider took the new extent and CRS but the
        LAYER kept those it was created with (verified on QGIS 3.44), and
        the site's lattice grows as grids become ready while a grid in
        another CRS shares this layer. `setDataSource` moves both itself
        (measured on QGIS 3.44.7), so the checks are a guard that costs
        nothing: each is a no-op whenever the layer already agrees.

        `own` (#180): wear the user's own style `own_style` rather than the
        palette at `limit`; `None` starts one from the palette and limit and
        reports it through `own_style_changed`. A computed min/max in that
        style is worked out again for this slice (`own_colours.refit`).
        `limit` may be a callable, read only when the palette is drawn or a
        style seeded: the shared stretch is a pass over the whole cube, and
        the user's own colours do not need it.
        """
        self._busy += 1
        try:
            self._serial += 1
            new_path = self._dir / f"slice-{self._serial:06d}.tif"
            try:
                self._write(new_path, array, tuple(geotransform), crs)
                if self._layer_gone():
                    self.layer = None
                    self._create_layer(new_path, name)
                else:
                    self._repoint(new_path)
                    self._ensure_group_membership()
            finally:
                # Even when the write or the repoint failed: a full-size
                # file was probably written, and a persistent failure must
                # not grow the scratch folder by one file per tick.
                self._sweep()
            if self.layer is None:
                return
            if self._name != name:
                self.layer.setName(name)
                self._name = name
            extent = self.layer.dataProvider().extent()
            if self.layer.extent() != extent:
                self.layer.setExtent(extent)
            wanted = QgsCoordinateReferenceSystem(crs)
            if wanted.isValid() and self.layer.crs() != wanted:
                self.layer.setCrs(wanted)
            seeded = None
            if own:
                seeded = self._apply_own(
                    own_style, colormap_name, limit, unipolar, array, tuple(geotransform), centre
                )
            else:
                value = float(limit() if callable(limit) else limit)
                if (
                    self._renderer_key is not None
                    and self._renderer_key[0] == "own"
                    and self._plain_style is not None
                ):
                    # Leaving the user's colours: their brightness, saturation,
                    # blending and resampling go too, not only their renderer.
                    own_colours.apply_style_text(self.layer, self._plain_style)
                key = ("nsgeo", colormap_name, value, bool(unipolar), float(centre))
                if key != self._renderer_key:
                    self._apply_renderer(colormap_name, value, unipolar, centre)
                    self._renderer_key = key
            self.layer.setCustomProperty("nsgeo/window", subtitle)
            self.layer.serverProperties().setAbstract(subtitle)
            self.layer.triggerRepaint()
            if seeded is not None:
                self.own_style_changed.emit(seeded)
        except Exception as exc:  # noqa: BLE001 -- reached from a slider slot
            _log(f"could not draw the slice layer: {exc}")
        finally:
            self._busy -= 1

    def _apply_own(
        self,
        own_style: str | None,
        colormap_name: str,
        limit: float | Callable[[], float],
        unipolar: bool,
        array: np.ndarray,
        geotransform: tuple[float, ...],
        centre: float = 0.0,
    ) -> str | None:
        """Put the user's style on once, then refit it to this slice. Returns
        the style when it was seeded from the palette here (to report), else
        None. A saved style QGIS cannot read is logged and replaced by a seed.

        `own_style` None always seeds, even over another scope's own style
        already on the layer: the seed is reported and stored at once, so the
        next tick brings it back as this scope's style."""
        assert self.layer is not None
        seeded = None
        if own_style is None:
            seeded = self._seed(colormap_name, limit, unipolar, centre)
        elif self._renderer_key != ("own", own_style):
            try:
                own_colours.apply_style_text(self.layer, own_style)
                self._renderer_key = ("own", own_style)
            except ValueError as exc:
                _log(f"could not use the saved slice colours, so the palette's are used: {exc}")
                seeded = self._seed(colormap_name, limit, unipolar, centre)
        own_colours.refit(self.layer, array, geotransform, self._view())
        return seeded

    def _seed(
        self,
        colormap_name: str,
        limit: float | Callable[[], float],
        unipolar: bool,
        centre: float = 0.0,
    ) -> str:
        assert self.layer is not None
        value = float(limit() if callable(limit) else limit)
        own_colours.seed_style(self.layer, colormap_name, value, unipolar, centre)
        text = own_colours.style_text(self.layer)
        self._renderer_key = ("own", text)
        return text

    def _view(self) -> Any:
        """The map view in the layer's CRS for a "Current canvas" min/max."""
        if self.extent_in is None or self.layer is None:
            return None
        try:
            return self.extent_in(self.layer.crs())
        except Exception as exc:  # noqa: BLE001 -- the whole slice will do
            _log(f"could not read the map view for the slice colours: {exc}")
            return None

    def _on_style_signal(self) -> None:
        """The layer's style changed: an edit by the user, when the layer
        wears their own colours and this class is not the one changing it.
        Reported only when the style is really different. A slot: never raises."""
        try:
            if self._busy or self.layer is None or sip.isdeleted(self.layer):
                return
            key = self._renderer_key
            if key is None or key[0] != "own":
                return
            text = own_colours.style_text(self.layer)
            if text == key[1]:
                return
            self._renderer_key = ("own", text)
            self.own_style_changed.emit(text)
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise
            _log(f"could not read the slice layer's new colours: {exc}")

    def shows_own_colours(self) -> bool:
        """Whether the layer is alive and wears the user's own style."""
        return (
            not self._layer_gone()
            and self._renderer_key is not None
            and self._renderer_key[0] == "own"
        )

    def own_style_now(self) -> str | None:
        """The user's style as the layer shows it now (with this slice's
        computed range), or None when it shows the plugin's colours."""
        if not self.shows_own_colours():
            return None
        assert self.layer is not None
        return own_colours.style_text(self.layer)

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

    def _sweep(self) -> None:
        """Delete every scratch file but the two that may be wanted, and
        never raise.

        A scan of the directory rather than a list of superseded files, so
        a file whose write or repoint failed, and sidecars such as GDAL's
        `.aux.xml` or an `.ovr`, are covered too. Two files are kept, both
        and not either (#54): `self.path`, the file the last successful
        repoint set (or the one `_create_layer` was given), and the layer's
        live `source()` while it is alive. They are the same file after a
        good tick, and after a `setDataSource` that raised before taking
        effect; they differ when it took a file the layer cannot read: the
        layer is left invalid on the new file, and `self.path` still names
        the last good one. A file QGIS's render threads still hold open
        cannot be deleted on Windows; it is simply met again by the next
        update's scan.
        """
        try:
            keep = {self.path.name}
            if self.layer is not None and not sip.isdeleted(self.layer):
                keep.add(Path(self.layer.source().split("|")[0]).name)
            for entry in self._dir.iterdir():
                if any(entry.name == k or entry.name.startswith(k + ".") for k in keep):
                    continue
                with contextlib.suppress(OSError):
                    _remove(entry)
        except Exception as exc:  # noqa: BLE001 -- housekeeping must not stop an update
            _log(f"could not tidy the slice scratch folder: {exc}")

    def _repoint(self, path: Path) -> None:
        """Point the existing layer at `path`, keeping its identity.

        Verified on QGIS 3.40, 3.44 and 4.2: `setDataSource` keeps the
        renderer (and its classification range), so `_renderer_key` stays
        valid. `loadDefaultStyle` is off by `ReadFlags()` for the same
        reason: a default style would replace that renderer. The layer's
        current name is passed back in, because the call applies it and a
        rename by the user must survive a tick.
        """
        assert self.layer is not None
        self.layer.setDataSource(
            str(path),
            self.layer.name(),
            "gdal",
            QgsDataProvider.ProviderOptions(),
            QgsDataProvider.ReadFlags(),
        )
        if not self.layer.isValid():
            raise RuntimeError(f"could not open {path}: {self.layer.error().summary()}")
        # The renderer survives the repoint, but `_apply_renderer` only runs
        # when the stretch changes. QGIS 3.44 restores the resampler from the
        # saved style on `setDataSource`, so this per-tick call is a guard.
        # Not over the user's own colours (#180): their resampling is theirs.
        if self._renderer_key is None or self._renderer_key[0] != "own":
            apply_smooth_resampling(self.layer)
        self.path = path

    def _write(
        self,
        path: Path,
        array: np.ndarray,
        geotransform: tuple[float, ...],
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
        # the layer simply kept showing whatever was already on disk.
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
                    str(path), width, height, 1, gdal.GDT_Float32, options=_CREATION_OPTIONS
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
                    # `write_north_up` already uses `Close()` on
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

    def _create_layer(self, path: Path, name: str = LAYER_NAME) -> None:
        layer = QgsRasterLayer(str(path), name, "gdal")
        # #180: the user's edits in Layer Properties arrive as these.
        layer.rendererChanged.connect(self._on_style_signal)
        layer.styleChanged.connect(self._on_style_signal)
        # addToLegend=False: this is a scratch preview, not a durable
        # artefact, and it joins the site's own group below like every
        # other layer here -- it does not sit unparented at legend root.
        self.layers.project.addMapLayer(layer, False)
        self.layer = layer
        self.path = path
        self._name = name
        # A fresh layer has never had a renderer built for it.
        self._renderer_key = None
        #: QGIS's own symbology for a fresh layer: what leaving the user's own
        #: colours (#180) puts back under the palette.
        self._plain_style = own_colours.style_text(layer)
        self._ensure_group_membership()

    def _apply_renderer(
        self, colormap_name: str, limit: float, unipolar: bool, centre: float = 0.0
    ) -> None:
        assert self.layer is not None
        # A fresh layer's first draw, and any new renderer. Each tick's
        # repoint sets the resampling again in `_repoint`.
        apply_renderer(self.layer, colormap_name, limit, unipolar, centre)

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
