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
from qgis.PyQt.QtWidgets import QApplication, QDialog
from qgis.PyQt.QtXml import QDomDocument

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.scene3d_plan import (
    NO_GRID,
    PICK_RADIUS_M,
    PICKS_LAYER_NAME,
    VIEW_NAME,
    camera_pose,
    scene_grid,
    scene_stretch,
    stretched_z,
    view_title,
)

_PICK_COLOUR = "#1f1f1f"


def _alive(obj: Any) -> bool:
    return obj is not None and not sip.isdeleted(obj)


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
    material.setDiffuse(QColor(_PICK_COLOUR))
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
        self._dialog: Any = None
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
        ]
        for signal in self._signals:
            signal.connect(self.request_refresh)
        surface_layers.add_listener(self.request_refresh)
        self.project.cleared.connect(self._on_cleared)

    # ---- state -------------------------------------------------------------------
    def is_open(self) -> bool:
        return _alive(self._canvas)

    # ---- entry points ------------------------------------------------------------
    def open(self) -> None:
        """Open the view on the scene grid, or raise and refresh the one that is open."""
        if self.is_open():
            if _alive(self._dialog):
                self._dialog.show()
                self._dialog.raise_()
                self._dialog.activateWindow()
            self.refresh()
            return
        grid = scene_grid(self.dock.scope(), self.dock.grid_combo.currentText() or None, None)
        if grid is None:
            raise ValueError(NO_GRID)
        self._export = self.export_for()
        self.grid_id = grid
        self._ensure_picks_layer()
        stretch = self._stretch(grid)
        self._fill_picks(grid, stretch)
        self._apply_renderers(grid, stretch)
        canvas = self.iface.createNewMapCanvas3D(VIEW_NAME)
        self._canvas = canvas
        self._dialog = self._find_dialog()
        generation = self._generation
        canvas.destroyed.connect(lambda *_: self._on_destroyed(generation))
        settings = canvas.mapSettings()
        settings.setTerrainRenderingEnabled(False)
        settings.setBackgroundColor(QColor(255, 255, 255))
        self._layers_timer.start()
        self._frame(grid, stretch)
        self._retitle(grid, stretch)

    def refresh(self) -> None:
        """Bring the open view in line with the site; nothing while it is closed."""
        if not self.is_open() or self._disposed:
            return
        shown = self.dock.grid_combo.currentText() or None
        grid = scene_grid(self.dock.scope(), shown, self.grid_id)
        if grid is None:
            grid = self.grid_id
        if grid is None:
            return
        changed = grid != self.grid_id
        self.grid_id = grid
        stretch = self._stretch(grid)
        if not self._picks_alive():
            self._ensure_picks_layer()
            self._layers_timer.start()
        self._fill_picks(grid, stretch)
        self._apply_renderers(grid, stretch)
        if changed:
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

    # ---- the pieces --------------------------------------------------------------
    def _stretch(self, grid: str) -> float:
        return scene_stretch(self.session.volume_record(grid))

    def _picks_alive(self) -> bool:
        layer = self.picks_layer
        return _alive(layer) and self.project.mapLayer(layer.id()) is not None

    def _ensure_picks_layer(self) -> None:
        if self._picks_alive():
            return
        grid_crs = self.layers.crs()
        crs = grid_crs.authid() if grid_crs is not None else ""
        uri = f"PointZ?crs={crs}&field=true_depth_m:double" if crs else "PointZ"
        layer = QgsVectorLayer(uri, PICKS_LAYER_NAME, "memory")
        layer.setRenderer(QgsNullSymbolRenderer())
        layer.setRenderer3D(_picks_renderer())
        self.project.addMapLayer(layer, False)
        group = self.layers.group
        placed = False
        if group is not None:
            picks = self.layers.layers.get("picks")
            node = group.findLayer(picks.id()) if _alive(picks) else None
            if node is not None:
                group.insertLayer(group.children().index(node) + 1, layer)
                placed = True
        if not placed:
            self.project.layerTreeRoot().addLayer(layer)
        self.picks_layer = layer

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
        features = []
        kept: list[float] = []
        for row, depth in zip(rows, depths):
            if depth is None or row.point is None:
                continue
            feature = QgsFeature(layer.fields())
            feature.setGeometry(
                QgsGeometry(QgsPoint(row.point[0], row.point[1], stretched_z(depth, stretch)))
            )
            feature.setAttribute("true_depth_m", float(depth))
            features.append(feature)
            kept.append(float(depth))
        provider = layer.dataProvider()
        provider.truncate()
        provider.addFeatures(features)
        layer.updateExtents()
        layer.triggerRepaint()
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
        local = np.array([[0.0, 0.0], [g.size_x, 0.0], [g.size_x, g.size_y], [0.0, g.size_y]])
        return [(float(x), float(y)) for x, y in g.to_world(local)]

    def _frame(self, grid: str, stretch: float) -> None:
        """Point the view at the grid: its CRS, origin and extent, and the camera."""
        corners = self._corners(grid)
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        settings = self._canvas.mapSettings()
        settings.setCrs(QgsCoordinateReferenceSystem(self.session.grid(grid).crs))
        settings.setOrigin(QgsVector3D((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, 0.0))
        settings.setExtent(QgsRectangle(min(xs), min(ys), max(xs), max(ys)))
        depths = self._depths_of(grid)
        pose = camera_pose(corners, depths, stretch)
        self._canvas.cameraController().setLookingAtMapPoint(
            QgsVector3D(pose.x, pose.y, pose.z), pose.distance, pose.pitch, pose.yaw
        )

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
        if _alive(self._dialog):
            self._dialog.setWindowTitle(view_title(grid, stretch, stale))

    def _find_dialog(self) -> Any:
        for widget in QApplication.allWidgets():
            if (
                isinstance(widget, QDialog)
                and widget.isWindow()
                and (widget.windowTitle() == VIEW_NAME)
            ):
                return widget
        return None

    def _set_view_layers(self) -> None:
        """The view follows the map's layers and drops what is not on them; set the layer tree's
        checked layers, which include the picks layer and the surfaces."""
        try:
            if self.is_open():
                self._canvas.mapSettings().setLayers(self.project.layerTreeRoot().checkedLayers())
        except Exception as exc:  # noqa: BLE001 -- a slot
            _log(f"could not set the 3-D view's layers: {exc}")

    # ---- closing -----------------------------------------------------------------
    def _on_destroyed(self, generation: int) -> None:
        try:
            if generation == self._generation:
                self._teardown()
        except Exception as exc:  # noqa: BLE001 -- a slot
            _log(f"could not clean up after the 3-D view: {exc}")

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
        layer = self.picks_layer
        if _alive(layer) and self.project.mapLayer(layer.id()) is not None:
            self.project.removeMapLayer(layer.id())
        for surface in self.surface_layers.layers_by_feature().values():
            if surface.renderer3D() is not None:
                surface.setRenderer3D(None)
        self._forget_layers()
        self._canvas = None
        self._dialog = None
        self._export = None
        self.grid_id = None
