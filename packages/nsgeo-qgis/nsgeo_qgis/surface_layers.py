"""Built surfaces on the 2-D map (M16 B Task 4; spec §5.4): one mesh layer per surface.

A surface's saved build (`Surfaces.built`) is a `.2dm` mesh with a `.dat` "depth (m)" dataset.
`SurfaceLayers.sync` shows each build that has at least one cell as a `QgsMeshLayer` in a
"Surfaces" group inside the site's group, directly below `picks`:

* The layer is coloured by depth with an inverted Turbo ramp (shallow is warm, as in the
  ParaView scene), over one range shared by every built surface of the grid.
* A surface whose inputs have changed since its build is labelled "(stale)" and keeps showing
  that build (spec call 9).
* A rebuilt surface's new layer takes the old one's row, and only then are the files no json
  names deleted (`Surfaces.sweep`): a delete that fails (Windows keeps a mesh file open) is
  skipped and tried again at the next sync.
* A layer the user removed stays removed until that surface builds again.

The session's signals that can change what is shown call `request_sync`, which coalesces
them through a zero-delay timer; the plugin calls `sync` itself after a build. Nothing here
changes what the Slices panel shows, and nothing calls `sweep` during a build.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from qgis.core import (
    Qgis,
    QgsColorRampShader,
    QgsCoordinateReferenceSystem,
    QgsLayerTree,
    QgsMeshDatasetIndex,
    QgsMeshLayer,
    QgsMessageLog,
    QgsStyle,
)
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.sip import isdeleted

from nsgeo_qgis.surfaces import BuiltSurface, Surfaces

#: The legend group's name, and the property that finds it again after a drag.
GROUP_NAME = "Surfaces"
_GROUP_PROP = "nsgeo/surfaces_group"
PROP_FEATURE = "nsgeo/feature_id"
PROP_BUILD = "nsgeo/build"
#: The dataset the 2DM's DAT carries (it is the depth in positive metres).
DEPTH_GROUP = "depth (m)"
STALE_SUFFIX = " (stale)"

_BUILD_KEY = re.compile(r"-([0-9a-f]{8})\.npz$")


def layer_name(name: str, stale: bool) -> str:
    return name + STALE_SUFFIX if stale else name


def build_key(built: BuiltSurface) -> str:
    """The 8 characters that name a build's files (`<id>-<build>.npz`)."""
    found = _BUILD_KEY.search(built.files["npz"].name)
    return found.group(1) if found else built.files["npz"].name


def depth_ramp() -> Any:
    """Turbo, inverted so that shallow is warm; Spectral (already warm at one end) when the
    default style has no Turbo. Returns `(ramp, name)`."""
    style = QgsStyle.defaultStyle()
    for name in ("Turbo", "Spectral"):
        ramp = style.colorRamp(name)
        if ramp is not None:
            if name == "Turbo":
                ramp.invert()
            return ramp, name
    return None, ""


@dataclass
class _Shown:
    layer_id: str
    build: str


def _log(message: str) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", Qgis.MessageLevel.Warning)


class SurfaceLayers:
    def __init__(self, session: Any, layers: Any, surfaces: Surfaces, project: Any = None) -> None:
        from qgis.core import QgsProject

        self.session = session
        self.layers = layers
        self.surfaces = surfaces
        self.project = project if project is not None else QgsProject.instance()
        self._shown: dict[str, _Shown] = {}
        #: feature id -> the build the user removed from the map; it returns with a new build.
        self._dismissed: dict[str, str] = {}
        self._disposed = False
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._on_timer)
        session.features_changed.connect(self.request_sync)
        session.picks_changed.connect(self.request_sync)
        session.slice_sources_changed.connect(self.request_sync)
        session.lines_changed.connect(self.request_sync)
        session.grids_changed.connect(self.request_sync)
        session.presets_changed.connect(self.request_sync)
        session.site_opened.connect(self.request_sync)
        session.site_closed.connect(self._on_site_closed)

    # ---- entry points ----------------------------------------------------------
    def request_sync(self, *_: Any) -> None:
        """Ask for a `sync` at the next turn of the event loop; many asks make one."""
        if not self._disposed and not self._timer.isActive():
            self._timer.start()

    def _on_timer(self) -> None:
        try:
            self.sync()
        except Exception as exc:  # noqa: BLE001 -- a slot: a raise here would be swallowed
            _log(f"could not update the surface layers: {exc}")

    def _on_site_closed(self, *_: Any) -> None:
        try:
            self._remove_all()
            self._dismissed.clear()
        except Exception as exc:  # noqa: BLE001 -- a slot
            _log(f"could not remove the surface layers: {exc}")

    def dispose(self) -> None:
        """Disconnect, and remove the layers and the group this made."""
        if self._disposed:
            return
        self._disposed = True
        self._timer.stop()
        for signal in (
            self.session.features_changed,
            self.session.picks_changed,
            self.session.slice_sources_changed,
            self.session.lines_changed,
            self.session.grids_changed,
            self.session.presets_changed,
            self.session.site_opened,
        ):
            with contextlib.suppress(TypeError, RuntimeError):
                signal.disconnect(self.request_sync)
        with contextlib.suppress(TypeError, RuntimeError):
            self.session.site_closed.disconnect(self._on_site_closed)
        self._remove_all()

    # ---- the tree ------------------------------------------------------------
    def _site_group(self) -> Any:
        group = self.layers.group
        return None if group is None or isdeleted(group) else group

    def _find_group(self, node: Any) -> Any:
        for child in node.children():
            if not QgsLayerTree.isGroup(child):
                continue
            if child.customProperty(_GROUP_PROP):
                return child
            found = self._find_group(child)
            if found is not None:
                return found
        return None

    def _surfaces_group(self, *, make: bool) -> Any:
        found = self._find_group(self.project.layerTreeRoot())
        if found is not None or not make:
            return found
        site = self._site_group()
        if site is None:
            return None
        row = 0
        picks = self.layers.layers.get("picks")
        if picks is not None and not isdeleted(picks):
            for i, child in enumerate(site.children()):
                if QgsLayerTree.isLayer(child) and child.layerId() == picks.id():
                    row = i + 1
        group = site.insertGroup(row, GROUP_NAME)
        group.setCustomProperty(_GROUP_PROP, "1")
        return group

    def _drop_layer(self, layer_id: str) -> None:
        if self.project.mapLayer(layer_id) is not None:
            self.project.removeMapLayer(layer_id)

    def _drop_group_if_empty(self) -> None:
        group = self._surfaces_group(make=False)
        if group is not None and not group.children():
            group.parent().removeChildNode(group)

    def _remove_all(self) -> None:
        for shown in list(self._shown.values()):
            self._drop_layer(shown.layer_id)
        self._shown.clear()
        group = self._surfaces_group(make=False)
        if group is not None:
            for child in list(group.children()):
                if QgsLayerTree.isLayer(child):
                    self._drop_layer(child.layerId())
            group.parent().removeChildNode(group)

    # ---- the layers ------------------------------------------------------------
    def _make_layer(self, built: BuiltSurface, name: str, fid: str, key: str) -> Any:
        layer = QgsMeshLayer(str(built.files["2dm"]), name, "mdal")
        if not layer.isValid():
            raise RuntimeError(f"the mesh {built.files['2dm'].name} could not be opened")
        if not layer.addDatasets(str(built.files["dat"])):
            raise RuntimeError(f"the depths {built.files['dat'].name} could not be loaded")
        layer.setCrs(QgsCoordinateReferenceSystem(built.crs))
        layer.setCustomProperty(PROP_FEATURE, fid)
        layer.setCustomProperty(PROP_BUILD, key)
        return layer

    @staticmethod
    def _style(layer: Any, low: float, high: float) -> None:
        """Colour the layer's depth dataset by the inverted ramp over `low` to `high`."""
        index = next(
            (
                i
                for i in layer.datasetGroupsIndexes()
                if layer.datasetGroupMetadata(QgsMeshDatasetIndex(i)).name() == DEPTH_GROUP
            ),
            None,
        )
        ramp, _ = depth_ramp()
        if index is None or ramp is None:
            return
        settings = layer.rendererSettings()
        settings.setActiveScalarDatasetGroup(index)
        scalar = settings.scalarSettings(index)
        scalar.setColorRampShader(QgsColorRampShader(low, high, ramp))
        scalar.setClassificationMinimumMaximum(low, high)
        settings.setScalarSettings(index, scalar)
        layer.setRendererSettings(settings)
        layer.triggerRepaint()

    def _put(self, fid: str, built: BuiltSurface, name: str, key: str) -> Any:
        """Make the layer for a build and put it where the surface's old one was (or, for a
        new one, at the foot of the group); the old one goes only after the new one is in."""
        layer = self._make_layer(built, name, fid, key)
        self.project.addMapLayer(layer, False)
        old = self._shown.get(fid)
        parent, row = None, 0
        if old is not None and self.project.mapLayer(old.layer_id) is not None:
            node = self.project.layerTreeRoot().findLayer(old.layer_id)
            if node is not None and node.parent() is not None:
                parent = node.parent()
                row = parent.children().index(node)
        if parent is None:
            parent = self._surfaces_group(make=True)
            if parent is None:
                self.project.removeMapLayer(layer.id())
                return None
            row = len(parent.children())
        parent.insertLayer(row, layer)
        if old is not None:
            self._drop_layer(old.layer_id)
        self._shown[fid] = _Shown(layer.id(), key)
        return layer

    def sync(self) -> None:
        """Bring the map in line with the saved builds, then delete the files no build owns."""
        self._timer.stop()
        if self._disposed:
            return
        if self.session.site is None:
            self._remove_all()
            return
        # A layer the user took out of the project stays out until that surface builds again.
        for fid, shown in list(self._shown.items()):
            if self.project.mapLayer(shown.layer_id) is None:
                self._dismissed[fid] = shown.build
                del self._shown[fid]
        records = {r.feature_id: r for r in self.surfaces.records()}
        builds: dict[str, BuiltSurface] = {}
        for fid in records:
            built = self.surfaces.built(fid)
            if built is not None and bool(np.isfinite(built.depth_m).any()):
                builds[fid] = built
        for fid in list(self._shown):
            if fid not in builds:
                self._drop_layer(self._shown.pop(fid).layer_id)
        for fid in list(self._dismissed):
            if fid not in builds:
                del self._dismissed[fid]
        # One depth range for every surface of a grid, so equal colours mean equal depths.
        ranges: dict[str, tuple[float, float]] = {}
        for fid, built in builds.items():
            grid = records[fid].grid_id
            low = float(np.nanmin(built.depth_m))
            high = float(np.nanmax(built.depth_m))
            old = ranges.get(grid)
            ranges[grid] = (low, high) if old is None else (min(old[0], low), max(old[1], high))
        for fid, built in builds.items():
            record = records[fid]
            key = build_key(built)
            stale = bool(self.surfaces.state(fid).stale)
            name = layer_name(record.name, stale)
            shown = self._shown.get(fid)
            layer = None
            if shown is not None and shown.build == key:
                layer = self.project.mapLayer(shown.layer_id)
                if layer is not None and layer.name() != name:
                    layer.setName(name)
            elif self._dismissed.get(fid) != key:
                try:
                    layer = self._put(fid, built, name, key)
                except Exception as exc:  # noqa: BLE001 -- one surface must not stop the rest
                    _log(f"could not show the surface {record.name!r}: {exc}")
                    continue
                self._dismissed.pop(fid, None)
            if layer is not None:
                self._style(layer, *ranges[record.grid_id])
        self._drop_group_if_empty()
        # Every grid folder, not only those with a surface: a deleted surface's files go too.
        root = Path(self.session.root) / "surfaces"
        if root.is_dir():
            for folder in sorted(root.iterdir()):
                if folder.is_dir():
                    self.surfaces.sweep(folder.name)
