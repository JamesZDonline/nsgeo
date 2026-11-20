"""QGIS's 3-D view of a grid (M16 C): its picks at depth and its surfaces.

`Scene3D` owns the view. It opens QGIS's own 3-D canvas, shows the scene grid's saved picks as
spheres at their true depth (a derived memory layer, never saved), puts a mesh 3-D renderer on
the grid's surface layers, and keeps the title and camera. The view follows the site: a new
pick, a rebuilt surface or a changed stretch refresh it. It writes nothing to the site and
never marks it dirty.

Measured on a real QGIS 3.44 window (see the plan): configure the view through its live
`mapSettings()`, set its layers from the layer tree after a 0 ms turn (QGIS resets them to the
map's visible layers), and find its top-level dialog by window title to re-title it.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsMapLayer,
    QgsNullSymbolRenderer,
    QgsPoint,
    QgsProject,
    QgsReadWriteContext,
    QgsRectangle,
    QgsVector3D,
    QgsVectorLayer,
)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QApplication, QDialog, QDockWidget
from qgis.PyQt.QtXml import QDomDocument

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.scene3d_plan import (
    NO_GRID,
    PICK_COLOUR,
    PICK_RADIUS_M,
    PICKS_LAYER_NAME,
    VIEW_NAME,
    VIEW_REFUSED,
    camera_pose,
    local_corners,
    padded_extent,
    scene_centre,
    scene_grid,
    stretched_z,
    view_title,
)


def _alive(obj: Any) -> bool:
    return obj is not None and not sip.isdeleted(obj)


def _hide_from_identify(layer: Any) -> None:
    """Keep the derived picks out of QGIS's Identify tool. The flag operators return QFlags on
    QGIS 3 (PyQt5) but a plain int on QGIS 4 (PyQt6); hiding is cosmetic, so a failure is
    logged and the view still opens."""
    flags = layer.flags()
    try:
        layer.setFlags(flags & ~QgsMapLayer.LayerFlag.Identifiable)
        return
    except TypeError:
        pass
    try:
        value = int(flags) & ~int(QgsMapLayer.LayerFlag.Identifiable)
        layer.setFlags(QgsMapLayer.LayerFlag(value))
    except Exception as exc:  # noqa: BLE001 -- cosmetic; never block the view
        _log(f"3-D view: could not hide the derived picks from Identify: {exc}")


def _mesh_renderer(layer: Any, stretch: float) -> Any | None:
    """The mesh 3-D renderer for a surface layer: depth is the 2DM's Z (dataset group 0, taken
    as absolute), stretched, coloured by the layer's own 2-D depth colours."""
    from qgis._3d import QgsMesh3DSymbol

    symbol = QgsMesh3DSymbol()
    symbol.setVerticalDatasetGroupIndex(0)
    symbol.setIsVerticalMagnitudeRelative(False)
    symbol.setVerticalScale(stretch)
    symbol.setRenderingStyle(QgsMesh3DSymbol.RenderingStyle.ColorRamp2DRendering)
    metadata = QgsApplication.renderer3DRegistry().rendererMetadata("mesh")
    if metadata is None:  # a bare QgsApplication (a test) has not registered the 3-D types
        from qgis._3d import Qgs3D

        Qgs3D.initialize()
        metadata = QgsApplication.renderer3DRegistry().rendererMetadata("mesh")
    if metadata is None:
        _log("3-D view: QGIS has no mesh 3-D renderer, so a surface is not drawn")
        return None
    doc = QDomDocument()
    element = doc.createElement("renderer-3d")
    element.setAttribute("type", "mesh")
    element.setAttribute("layer", layer.id())
    holder = doc.createElement("symbol")
    holder.setAttribute("type", "mesh")
    symbol.writeXml(holder, QgsReadWriteContext())
    element.appendChild(holder)
    doc.appendChild(element)
    return metadata.createRenderer(element, QgsReadWriteContext())


def _picks_renderer() -> Any:
    from qgis._3d import QgsPhongMaterialSettings, QgsPoint3DSymbol, QgsVectorLayer3DRenderer

    symbol = QgsPoint3DSymbol()
    symbol.setShape(Qgis.Point3DShape.Sphere)
    symbol.setShapeProperties({"radius": PICK_RADIUS_M})
    material = QgsPhongMaterialSettings()
    material.setDiffuse(QColor(PICK_COLOUR))
    symbol.setMaterialSettings(material)
    symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    return QgsVectorLayer3DRenderer(symbol)


class Scene3D:
    def __init__(
        self,
        session: Any,
        layers: Any,
        surfaces: Any,
        surface_layers: Any,
        export_for: Callable[[], Any],
        dock: Any,
        iface: Any,
        project: Any = None,
    ) -> None:
        self.session = session
        self.layers = layers
        self.surfaces = surfaces
        self.surface_layers = surface_layers
        self.export_for = export_for
        self.dock = dock
        self.iface = iface
        self.project = project if project is not None else QgsProject.instance()
        self.grid_id: str | None = None
        self.picks_layer: QgsVectorLayer | None = None
        self._export: Any = None
        self._canvas: Any = None
        self._last_title = VIEW_NAME
        #: What the view was last framed on: the grid and its geometry (Edit grid moves it).
        self._framed_grid: str | None = None
        self._framed_geometry: tuple[Any, ...] | None = None
        #: The next 0 ms layers turn empties the view's layers first (a re-frame).
        self._rebuild_layers = False
        #: Bumped at each teardown, so a late `destroyed` from an old view does nothing.
        self._generation = 0
        #: layer id -> the stretch of the renderer this view put on it.
        self._applied: dict[str, float] = {}
        self._disposed = False
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._on_timer)
        self._layers_timer = QTimer()
        self._layers_timer.setSingleShot(True)
        self._layers_timer.setInterval(0)
        self._layers_timer.timeout.connect(self._set_view_layers)
        self._signals = [
            session.picks_changed,
            session.features_changed,
            session.slice_sources_changed,
            session.grids_changed,
            session.lines_changed,
            session.presets_changed,
            session.cuts_changed,
        ]
        for signal in self._signals:
            signal.connect(self.request_refresh)
        surface_layers.add_listener(self.request_refresh)
        self.project.cleared.connect(self._on_cleared)
        self.project.layersWillBeRemoved.connect(self._on_layers_will_be_removed)

    # ---- state -------------------------------------------------------------------
    def is_open(self) -> bool:
        return _alive(self._canvas)

    # ---- entry points ------------------------------------------------------------
    def open(self) -> None:
        """Open the view on the scene grid, or raise and refresh the one that is open."""
        if self.is_open():
            holder = self._holder()
            if holder is not None:
                holder.show()
                holder.raise_()
                holder.activateWindow()
            self.refresh()
            return
        grid = scene_grid(
            self.dock.scope(),
            self.dock.grid_combo.currentText() or None,
            None,
            self._grid_ids(),
        )
        if grid is None:
            raise ValueError(NO_GRID)
        try:
            self._open_on(grid)
        except BaseException:
            if self._canvas is not None:  # a view QGIS made: close it, not just forget it
                with contextlib.suppress(Exception):
                    self.iface.closeMapCanvas3D(VIEW_NAME)
            self._teardown()
            raise

    def _open_on(self, grid: str) -> None:
        self._export = self.export_for()
        self.grid_id = grid
        self._ensure_picks_layer()
        stretch = self._stretch(grid)
        self._fill_picks(grid, stretch)
        self._apply_renderers(grid, stretch)
        # QGIS refuses a second view of one name (one restored with a saved project, say).
        self.iface.closeMapCanvas3D(VIEW_NAME)
        canvas = self.iface.createNewMapCanvas3D(VIEW_NAME)
        if canvas is None:
            raise RuntimeError(VIEW_REFUSED)
        self._canvas = canvas
        generation = self._generation
        canvas.destroyed.connect(lambda *_: self._on_destroyed(generation))
        settings = canvas.mapSettings()
        settings.setTerrainRenderingEnabled(False)
        settings.setBackgroundColor(QColor(255, 255, 255))
        self._frame(grid, stretch)
        self._retitle(grid, stretch)

    def refresh(self) -> None:
        """Bring the open view in line with the site; nothing while it is closed."""
        if not self.is_open() or self._disposed:
            return
        shown = self.dock.grid_combo.currentText() or None
        grid = scene_grid(self.dock.scope(), shown, self.grid_id, self._grid_ids())
        if grid is None:
            grid = self.grid_id
        if grid is None or grid not in self._grid_ids():
            return
        self.grid_id = grid
        stretch = self._stretch(grid)
        if not self._picks_alive():
            self._ensure_picks_layer()
            self._layers_timer.start()
        self._fill_picks(grid, stretch)
        self._apply_renderers(grid, stretch)
        if grid != self._framed_grid or self._geometry_of(grid) != self._framed_geometry:
            self._frame(grid, stretch)
        self._retitle(grid, stretch)

    def request_refresh(self, *_: Any) -> None:
        """Ask for a `refresh` at the next turn of the event loop; many asks make one."""
        try:
            if not self._disposed and self.is_open() and not self._timer.isActive():
                self._timer.start()
        except Exception as exc:  # noqa: BLE001 -- a slot: a raise here would be swallowed
            _log(f"could not schedule the 3-D view: {exc}")

    def _on_timer(self) -> None:
        try:
            self.refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot: a raise here would be swallowed
            _log(f"could not refresh the 3-D view: {exc}")

    def close(self) -> None:
        """Close the view and take everything it added off the map."""
        if self.is_open():
            canvas = self._canvas
            self.iface.closeMapCanvas3D(VIEW_NAME)
            if canvas is self._canvas:
                self._teardown()
        else:
            self._teardown()

    def dispose(self) -> None:
        self.close()
        self._disposed = True
        self._timer.stop()
        for signal in self._signals:
            with contextlib.suppress(TypeError, RuntimeError):
                signal.disconnect(self.request_refresh)
        with contextlib.suppress(TypeError, RuntimeError):
            self.project.cleared.disconnect(self._on_cleared)
        with contextlib.suppress(TypeError, RuntimeError):
            self.project.layersWillBeRemoved.disconnect(self._on_layers_will_be_removed)

    # ---- the pieces --------------------------------------------------------------
    def _grid_ids(self) -> list[str]:
        site = self.session.site
        return [g.id for g in site.grids] if site is not None else []

    def _geometry_of(self, grid: str) -> tuple[Any, ...]:
        g = self.session.grid(grid)
        return (g.origin, g.azimuth, g.size_x, g.size_y, g.crs)

    def _stretch(self, grid: str) -> float:
        return self.session.view_stretch(grid)

    def _picks_alive(self) -> bool:
        layer = self.picks_layer
        return _alive(layer) and self.project.mapLayer(layer.id()) is not None

    def _ensure_picks_layer(self) -> None:
        if self._picks_alive():
            return
        grid_crs = self.layers.crs()
        has_crs = grid_crs is not None and grid_crs.isValid()
        # the CRS goes in the URI so QGIS never runs its "Specify CRS" validation on this layer
        if has_crs and grid_crs.authid():
            uri = f"PointZ?crs={grid_crs.authid()}&field=true_depth_m:double"
        else:
            uri = "PointZ?field=true_depth_m:double"
        options = QgsVectorLayer.LayerOptions()
        options.skipCrsValidation = True
        layer = QgsVectorLayer(uri, PICKS_LAYER_NAME, "memory", options)
        if has_crs:
            layer.setCrs(grid_crs)
        # QGIS asks "scratch layers will be lost" on exit / New / Open while a memory layer holds
        # features; this one is rebuilt from the picks, so there is nothing to lose
        layer.setCustomProperty("skipMemoryLayersCheck", 1)
        _hide_from_identify(layer)
        layer.setRenderer(QgsNullSymbolRenderer())
        layer.setRenderer3D(_picks_renderer())
        self.project.addMapLayer(layer, False)
        self.picks_layer = layer
        group = self.layers.group
        placed = False
        if group is not None:
            picks = self.layers.layers.get("picks")
            node = group.findLayer(picks.id()) if _alive(picks) else None
            parent = node.parent() if node is not None else None
            if node is not None and parent is not None:
                parent.insertLayer(parent.children().index(node) + 1, layer)
                placed = True
        if not placed:
            self.project.layerTreeRoot().addLayer(layer)

    def _fill_picks(self, grid: str, stretch: float) -> list[float]:
        """Rewrite the picks layer with the grid's picks at their true depth; the depths."""
        layer = self.picks_layer
        picks = self.layers.layers.get("picks")
        rows = []
        if _alive(picks):
            rows = [
                r
                for r in self.layers.pick_rows(picks.dataProvider().allFeatureIds())
                if r.point is not None
            ]
        depths = self._export.pick_depths(grid, [(r.pick.line_key, r.pick) for r in rows])
        wanted: list[tuple[float, float, float, float]] = []
        for row, depth in zip(rows, depths):
            if depth is None or row.point is None:
                continue
            wanted.append(
                (
                    float(row.point[0]),
                    float(row.point[1]),
                    float(stretched_z(depth, stretch)),
                    float(depth),
                )
            )
        kept = [w[3] for w in wanted]
        # refresh runs on many signals: rewrite only when a point moved, so the view does not
        # rebuild (flicker) for nothing
        now = []
        for f in layer.getFeatures():
            pt = f.geometry().constGet()
            now.append((pt.x(), pt.y(), pt.z(), float(f["true_depth_m"])))
        if sorted(now) == sorted(wanted):
            return kept
        features = []
        for x, y, z, depth in wanted:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry(QgsPoint(x, y, z)))
            feature.setAttribute("true_depth_m", depth)
            features.append(feature)
        provider = layer.dataProvider()
        provider.truncate()
        provider.addFeatures(features)
        layer.updateExtents()
        layer.triggerRepaint()
        # the open 3-D scene ignores repaints; this is the signal it rebuilds a layer on
        layer.trigger3DUpdate()
        return kept

    def _apply_renderers(self, grid: str, stretch: float) -> None:
        """A mesh 3-D renderer on the scene grid's surface layers, none on the others."""
        grid_of = {r.feature_id: r.grid_id for r in self.surfaces.records()}
        live = self.surface_layers.layers_by_feature()
        for fid, layer in live.items():
            if grid_of.get(fid) == grid:
                if self._applied.get(layer.id()) != stretch or layer.renderer3D() is None:
                    renderer = _mesh_renderer(layer, stretch)
                    if renderer is not None:
                        layer.setRenderer3D(renderer)
                        self._applied[layer.id()] = stretch
            elif layer.renderer3D() is not None:
                layer.setRenderer3D(None)
                self._applied.pop(layer.id(), None)
        ids = {layer.id() for layer in live.values()}
        for stale in [i for i in self._applied if i not in ids]:
            del self._applied[stale]

    def _corners(self, grid: str) -> list[tuple[float, float]]:
        import numpy as np

        g = self.session.grid(grid)
        local = np.array(local_corners(g.size_x, g.size_y))
        return [(float(x), float(y)) for x, y in g.to_world(local)]

    def _frame(self, grid: str, stretch: float) -> None:
        """Point the view at the grid: its CRS, origin and extent, and the camera."""
        corners = self._corners(grid)
        xmin, ymin, xmax, ymax = padded_extent(corners)
        cx, cy = scene_centre(corners)
        settings = self._canvas.mapSettings()
        settings.setCrs(QgsCoordinateReferenceSystem(self.session.grid(grid).crs))
        settings.setOrigin(QgsVector3D(cx, cy, 0.0))
        settings.setExtent(QgsRectangle(xmin, ymin, xmax, ymax))
        depths = self._depths_of(grid)
        pose = camera_pose(corners, depths, stretch)
        controller = self._canvas.cameraController()
        if hasattr(controller, "setLookingAtMapPoint"):
            controller.setLookingAtMapPoint(
                QgsVector3D(pose.x, pose.y, pose.z), pose.distance, pose.pitch, pose.yaw
            )
        else:  # QGIS 3.40: no map-point call, so look straight down from the right distance
            controller.resetView(pose.distance)
        self._framed_grid = grid
        self._framed_geometry = self._geometry_of(grid)
        # the CRS and origin change reaches no entity already built: rebuild them all
        self._rebuild_layers = True
        self._layers_timer.start()

    def _depths_of(self, grid: str) -> list[float]:
        layer = self.picks_layer
        if not _alive(layer):
            return []
        return [float(f["true_depth_m"]) for f in layer.getFeatures()]

    def _retitle(self, grid: str, stretch: float) -> None:
        stale = 0
        try:
            members = self.surfaces.layers.members_by_feature()
            for record in self.surfaces.records():
                if record.grid_id == grid and self.surfaces.state(record.feature_id, members).stale:
                    stale += 1
        except Exception as exc:  # noqa: BLE001 -- the title is not worth a refresh
            _log(f"3-D view: could not count the stale surfaces: {exc}")
        holder = self._holder()
        if holder is not None:
            title = view_title(grid, stretch, stale)
            holder.setWindowTitle(title)
            self._last_title = title
            if not holder.property("nsgeoHooked"):
                # QGIS re-applies its own stored title when docking toggles, and replaces the
                # holder: re-title the new one as soon as the old one goes
                holder.setProperty("nsgeoHooked", True)
                holder.destroyed.connect(self.request_refresh)

    def _holder(self) -> Any:
        """The window or dock holding the view, found afresh each time: docking and undocking
        rebuilds it. It is titled `VIEW_NAME` until we retitle it, then with that title."""
        titles = {VIEW_NAME, self._last_title}
        for widget in QApplication.allWidgets():
            if isinstance(widget, (QDialog, QDockWidget)) and widget.windowTitle() in titles:
                return widget
        return None

    def _set_view_layers(self) -> None:
        """The view follows the map's layers and drops what is not on them; set the layer tree's
        checked layers, which include the picks layer and the surfaces."""
        try:
            if self.is_open():
                settings = self._canvas.mapSettings()
                layers = self.project.layerTreeRoot().checkedLayers()
                if self._rebuild_layers:
                    self._rebuild_layers = False
                    settings.setLayers([])
                settings.setLayers(layers)
        except Exception as exc:  # noqa: BLE001 -- a slot
            _log(f"could not set the 3-D view's layers: {exc}")

    # ---- closing -----------------------------------------------------------------
    def _on_destroyed(self, generation: int) -> None:
        try:
            if generation == self._generation:
                self._teardown()
        except Exception as exc:  # noqa: BLE001 -- a slot
            _log(f"could not clean up after the 3-D view: {exc}")

    def _on_layers_will_be_removed(self, layer_ids: list[str]) -> None:
        """An open 3-D scene keeps a raw pointer to each layer it draws, and QGIS crashes on the
        next layer update if such a layer is deleted: clear the renderer of every layer of ours
        about to be deleted, while it is still alive (walkthrough L2 and C2)."""
        try:
            wanted = set(layer_ids)
            managed = list(self.surface_layers.layers_by_feature().values())
            if self.picks_layer is not None:
                managed.append(self.picks_layer)
            # Every layer this view gave a renderer, whatever SurfaceLayers' bookkeeping says
            # (it forgets a deleted surface before it removes the layer).
            managed += [self.project.mapLayer(i) for i in list(self._applied) if i in wanted]
            for layer in managed:
                if _alive(layer) and layer.id() in wanted and layer.renderer3D() is not None:
                    layer.setRenderer3D(None)
                    self._applied.pop(layer.id(), None)
        except Exception as exc:  # noqa: BLE001 -- a slot
            _log(f"could not clear a 3-D renderer before its layer was removed: {exc}")

    def _on_cleared(self) -> None:
        """The project was cleared: its layers are gone, so forget them."""
        try:
            self._forget_layers()
        except Exception as exc:  # noqa: BLE001 -- a slot
            _log(f"could not forget the 3-D view's layers: {exc}")

    def _forget_layers(self) -> None:
        self.picks_layer = None
        self._applied.clear()

    def _teardown(self) -> None:
        self._generation += 1
        self._layers_timer.stop()
        self._rebuild_layers = False
        self._framed_grid = None
        self._framed_geometry = None
        layer = self.picks_layer
        if _alive(layer) and self.project.mapLayer(layer.id()) is not None:
            self.project.removeMapLayer(layer.id())
        for surface in self.surface_layers.layers_by_feature().values():
            if surface.renderer3D() is not None:
                surface.setRenderer3D(None)
        self._forget_layers()
        self._canvas = None
        self._last_title = VIEW_NAME
        self._export = None
        self.grid_id = None
