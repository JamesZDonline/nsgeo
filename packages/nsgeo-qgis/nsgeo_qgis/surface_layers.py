"""Built surfaces on the 2-D map (M16 B Task 4; spec §5.4): one mesh layer per surface.

A surface's saved build (`Surfaces.built`) is a `.2dm` mesh with a `.dat` "depth (m)" dataset.
`SurfaceLayers.sync` shows each build that has at least one cell as a `QgsMeshLayer` in a
"Surfaces" group inside the site's group, directly below `picks`:

* The layer is coloured by depth with an inverted Turbo ramp (shallow is warm, as in the
  ParaView scene), over one range shared by every built surface of the grid. It is styled
  when it is made and again only when its grid's range changes, so colours the user chose by
  hand survive an ordinary sync.
* A surface whose inputs have changed since its build is labelled "(stale)" and keeps showing
  that build (spec call 9).
* A rebuilt surface's new layer takes the old one's row, and only then are the files no json
  names deleted (`Surfaces.sweep`): a delete that fails (Windows keeps a mesh file open) is
  skipped and tried again at the next sync.
* A layer the user removed stays removed until that surface builds again. A cleared project
  (File > New, another project opened) forgets the layers without counting that as removal.
* While `Surfaces.building` is set, nothing is swept (the files of a build in progress are
  named by no json yet): a sync then only notes that it is owed, and the caller syncs once
  the build is done.

The session's signals that can change what is shown call `request_sync`, which coalesces
them through a zero-delay timer; the plugin calls `sync` itself after a build. Nothing here
changes what the Slices panel shows.
"""

from __future__ import annotations

import contextlib
import re
import uuid
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
    QgsProject,
    QgsStyle,
)
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.sip import isdeleted

from nsgeo_qgis.surface_plan import layer_name, merge_range
from nsgeo_qgis.surfaces import Surfaces

#: The legend group's name, and the property that finds this one again after a drag. The
#: property's value is new for every group made: a group read back from a saved project
#: carries an old value, and is never adopted.
GROUP_NAME = "Surfaces"
_GROUP_PROP = "nsgeo/surfaces_group"
PROP_FEATURE = "nsgeo/feature_id"
PROP_BUILD = "nsgeo/build"
#: The dataset the 2DM's DAT carries (it is the depth in positive metres).
DEPTH_GROUP = "depth (m)"

_BUILD_KEY = re.compile(r"-([0-9a-f]{8})\.npz$")


def build_key(files: Any) -> str:
    """The 8 characters that name a build's files (`<id>-<build>.npz`); `files` is a json
    `files` mapping or a name."""
    name = files["npz"] if isinstance(files, dict) else str(files)
    found = _BUILD_KEY.search(Path(name).name)
    return found.group(1) if found else name


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
    #: The depth range the layer is coloured over (None until styled).
    styled: tuple[float, float] | None = None


def _log(message: str) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", Qgis.MessageLevel.Warning)


class SurfaceLayers:
    def __init__(self, session: Any, layers: Any, surfaces: Surfaces, project: Any = None) -> None:
        self.session = session
        self.layers = layers
        self.surfaces = surfaces
        self.project = project if project is not None else QgsProject.instance()
        self._shown: dict[str, _Shown] = {}
        #: feature id -> the build the user removed from the map; it returns with a new build.
        self._dismissed: dict[str, str] = {}
        #: build key -> (lowest depth, highest depth): read from a build's npz once.
        self._depths: dict[str, tuple[float, float]] = {}
        self._token = ""
        self._owed = False
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
        self.project.cleared.connect(self._on_cleared)

    # ---- entry points ----------------------------------------------------------
    def request_sync(self, *_: Any) -> None:
        """Ask for a `sync` at the next turn of the event loop; many asks make one."""
        try:
            if not self._disposed and not self._timer.isActive():
                self._timer.start()
        except Exception as exc:  # noqa: BLE001 -- a slot: a raise here would be swallowed
            _log(f"could not schedule the surface layers: {exc}")

    def _on_timer(self) -> None:
        try:
            if self.surfaces.building:
                self._owed = True  # the plugin syncs when the build is done
                return
            self.sync()
        except Exception as exc:  # noqa: BLE001 -- a slot
            _log(f"could not update the surface layers: {exc}")

    def _on_site_closed(self, *_: Any) -> None:
        try:
            self._remove_all()
            self._dismissed.clear()
            self._depths.clear()
        except Exception as exc:  # noqa: BLE001 -- a slot
            _log(f"could not remove the surface layers: {exc}")

    def _on_cleared(self) -> None:
        """The project dropped every layer and group: forget them, as no one's doing."""
        try:
            self._shown.clear()
            self._token = ""
        except Exception as exc:  # noqa: BLE001 -- a slot
            _log(f"could not forget the surface layers: {exc}")

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
        with contextlib.suppress(TypeError, RuntimeError):
            self.project.cleared.disconnect(self._on_cleared)
        self._remove_all()

    # ---- the tree ------------------------------------------------------------
    def _site_group(self) -> Any:
        group = self.layers.group
        return None if group is None or isdeleted(group) else group

    def _surfaces_group(self, *, make: bool) -> Any:
        """This object's group, found under the live site group by its own token."""
        site = self._site_group()
        if site is None:
            return None
        if self._token:
            for child in site.children():
                if QgsLayerTree.isGroup(child) and child.customProperty(_GROUP_PROP) == self._token:
                    return child
        if not make:
            return None
        row = 0
        picks = self.layers.layers.get("picks")
        if picks is not None and not isdeleted(picks):
            for i, child in enumerate(site.children()):
                if QgsLayerTree.isLayer(child) and child.layerId() == picks.id():
                    row = i + 1
        group = site.insertGroup(row, GROUP_NAME)
        self._token = uuid.uuid4().hex
        group.setCustomProperty(_GROUP_PROP, self._token)
        return group

    def _drop_layer(self, layer_id: str) -> None:
        if self.project.mapLayer(layer_id) is not None:
            self.project.removeMapLayer(layer_id)

    def _drop_group_if_empty(self) -> None:
        group = self._surfaces_group(make=False)
        if group is not None and not group.children():
            group.parent().removeChildNode(group)
            self._token = ""

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
        self._token = ""

    # ---- the layers ------------------------------------------------------------
    @staticmethod
    def _make_layer(files: dict[str, Path], crs: str, name: str, fid: str, key: str) -> Any:
        layer = QgsMeshLayer(str(files["2dm"]), name, "mdal")
        if not layer.isValid():
            raise RuntimeError(f"the mesh {files['2dm'].name} could not be opened")
        if not layer.addDatasets(str(files["dat"])):
            raise RuntimeError(f"the depths {files['dat'].name} could not be loaded")
        layer.setCrs(QgsCoordinateReferenceSystem(crs))
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
        shader = QgsColorRampShader(low, high, ramp, Qgis.ShaderInterpolationMethod.Linear)
        # A new shader has no colour stops, and changing its range does not make any.
        shader.classifyColorRamp()
        scalar.setColorRampShader(shader)
        scalar.setClassificationMinimumMaximum(low, high)
        settings.setScalarSettings(index, scalar)
        layer.setRendererSettings(settings)
        layer.triggerRepaint()

    def _put(self, fid: str, files: dict[str, Path], crs: str, name: str, key: str) -> Any:
        """Make the layer for a build and put it where the surface's old one was (or, for a
        new one, at the foot of the group); the old one goes only after the new one is in."""
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
                return None
            row = len(parent.children())
        layer = self._make_layer(files, crs, name, fid, key)
        self.project.addMapLayer(layer, False)
        try:
            parent.insertLayer(row, layer)
        except BaseException:
            self.project.removeMapLayer(layer.id())
            raise
        if old is not None:
            self._drop_layer(old.layer_id)
        self._shown[fid] = _Shown(layer.id(), key)
        return layer

    def sync(self) -> None:
        """Bring the map in line with the saved builds, then delete the files no build owns
        (never while a build runs: the sync is then owed, and the caller makes it afterwards)."""
        self._timer.stop()
        if self._disposed:
            return
        if self.surfaces.building:
            self._owed = True
            return
        self._owed = False
        if self.session.site is None:
            self._remove_all()
            return
        # A layer the user took out of the project stays out until that surface builds again.
        for fid, shown in list(self._shown.items()):
            if self.project.mapLayer(shown.layer_id) is None:
                self._dismissed[fid] = shown.build
                del self._shown[fid]
        records = {r.feature_id: r for r in self.surfaces.records()}
        members = self.surfaces.layers.members_by_feature()  # one scan for every surface
        states = {fid: self.surfaces.state(fid, members) for fid in records}
        # fid -> (build key, files) of each build that has at least one cell.
        wanted: dict[str, str] = {}
        for fid, state in states.items():
            report = state.report
            if state.built and report and int(report.get("cells", 0)) > 0:
                wanted[fid] = build_key(report["files"])
        for fid in list(self._shown):
            if fid not in wanted:
                self._drop_layer(self._shown.pop(fid).layer_id)
        for fid in list(self._dismissed):
            if fid not in wanted:
                del self._dismissed[fid]
        # One depth range for every surface of a grid, so equal colours mean equal depths.
        ranges: dict[str, tuple[float, float]] = {}
        for fid, key in list(wanted.items()):
            if key not in self._depths:
                built = self.surfaces.built(fid)
                if built is None or not bool(np.isfinite(built.depth_m).any()):
                    del wanted[fid]
                    continue
                self._depths[key] = (
                    float(np.nanmin(built.depth_m)),
                    float(np.nanmax(built.depth_m)),
                )
            grid = records[fid].grid_id
            low, high = self._depths[key]
            ranges[grid] = merge_range(ranges.get(grid), low, high)
        for fid, key in wanted.items():
            record = records[fid]
            name = layer_name(record.name, bool(states[fid].stale))
            shown = self._shown.get(fid)
            layer = None
            if shown is not None and shown.build == key:
                layer = self.project.mapLayer(shown.layer_id)
                if layer is not None and layer.name() != name:
                    layer.setName(name)
            elif self._dismissed.get(fid) != key:
                built = self.surfaces.built(fid)
                if built is None:
                    continue
                try:
                    layer = self._put(fid, built.files, built.crs, name, key)
                except Exception as exc:  # noqa: BLE001 -- one surface must not stop the rest
                    _log(f"could not show the surface {record.name!r}: {exc}")
                    continue
                self._dismissed.pop(fid, None)
            shown = self._shown.get(fid)
            if layer is not None and shown is not None:
                span = ranges[record.grid_id]
                if shown.styled != span:
                    self._style(layer, *span)
                    shown.styled = span
        self._drop_group_if_empty()
        # Every grid folder, not only those with a surface: a deleted surface's files go too.
        # Never on an unreadable features table: it lists no surface, and every build would go.
        root = Path(self.session.root) / "surfaces"
        if root.is_dir() and self.surfaces.layers.features_available():
            for folder in sorted(root.iterdir()):
                if folder.is_dir():
                    self.surfaces.sweep(folder.name)
