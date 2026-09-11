"""The site GeoPackage: one file, several tables, three rules.

1. Regenerate per table, never per file: rebuilding `lines` truncates and
   refills that table; the file is never deleted, so picks survive and
   Windows file locks never bite.
2. All writes go through the loaded QGIS layer's data provider, never a
   second OGR handle on a package QGIS already has open.
3. Derived tables (grids, lines, marks) are read-only in QGIS; the survey
   JSON is the source of truth for geometry. Picks are authored.

The package CRS is the CRS of the first grid; other grids are transformed
into it on write.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from nsgeo.geometry.grid import Grid
from nsgeo.io.dzx import DzxError, read_dzx
from nsgeo.model.survey import Line
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
    QgsSymbol,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType, QObject
from qgis.PyQt.QtGui import QColor

from nsgeo_qgis.session import SiteSession

_KIND = {
    "str": QMetaType.Type.QString,
    "int": QMetaType.Type.Int,
    "float": QMetaType.Type.Double,
}

TABLES: dict[str, tuple[Any, list[tuple[str, str]]]] = {
    "grids": (
        QgsWkbTypes.Type.Polygon,
        [
            ("grid_id", "str"),
            ("azimuth", "float"),
            ("size_x", "float"),
            ("size_y", "float"),
            ("default_spacing", "float"),
            ("velocity_json", "str"),
        ],
    ),
    "lines": (
        QgsWkbTypes.Type.LineString,
        [
            ("line_key", "str"),
            ("grid_id", "str"),
            ("label", "str"),
            ("axis", "str"),
            ("offset_m", "float"),
            ("start_along_m", "float"),
            ("direction", "int"),
            ("n_traces", "int"),
            ("length_m", "float"),
            ("antenna", "str"),
            ("file_name", "str"),
        ],
    ),
    "marks": (
        QgsWkbTypes.Type.Point,
        [("line_key", "str"), ("scan", "int"), ("kind", "str"), ("name", "str")],
    ),
    "picks": (
        QgsWkbTypes.Type.Point,
        [
            ("line_key", "str"),
            ("trace", "int"),
            ("distance_m", "float"),
            ("time_ns", "float"),
            ("depth_m", "float"),
            ("velocity_m_ns", "float"),
            ("stack_json", "str"),
            ("note", "str"),
            ("created", "str"),
        ],
    ),
}
DERIVED = ("grids", "lines", "marks")

GRID_COLOURS = ["#2f6fb2", "#c0392b", "#27ae60", "#8e44ad", "#d35400", "#16a085"]


def _fields(spec: list[tuple[str, str]]) -> QgsFields:
    fields = QgsFields()
    for name, kind in spec:
        fields.append(QgsField(name, _KIND[kind]))
    return fields


class SiteLayers(QObject):
    def __init__(
        self, session: SiteSession, project: QgsProject | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.project = project or QgsProject.instance()
        self.layers: dict[str, QgsVectorLayer] = {}
        self.group: Any = None
        session.site_opened.connect(self._on_site_opened)
        session.site_closed.connect(self.detach)
        session.grids_changed.connect(self.refresh)
        session.lines_changed.connect(self.refresh)

    # ---- lifecycle --------------------------------------------------------
    def _on_site_opened(self) -> None:
        self.detach()
        self.refresh()

    def detach(self) -> None:
        if self.layers:
            self.project.removeMapLayers([lyr.id() for lyr in self.layers.values()])
            self.layers.clear()
        if self.group is not None:
            parent = self.group.parent()
            if parent is not None:
                parent.removeChildNode(self.group)
            self.group = None

    def crs(self) -> QgsCoordinateReferenceSystem | None:
        site = self.session.site
        if site is None or not site.grids:
            return None
        return QgsCoordinateReferenceSystem(site.grids[0].crs)

    def refresh(self) -> None:
        site = self.session.site
        if site is None or not site.grids:
            return  # a table needs a CRS; nothing to show without a grid anyway
        self.ensure_tables()
        self.refill_grids()
        self.refill_lines()
        self.refill_marks()

    # ---- tables -----------------------------------------------------------
    def ensure_tables(self) -> None:
        path = str(self.session.gpkg_path)
        crs = self.crs()
        assert crs is not None
        for name, (wkb, spec) in TABLES.items():
            if not self._table_exists(path, name):
                self._create_table(path, name, wkb, spec, crs)
        if self.group is None:
            self.group = self.project.layerTreeRoot().addGroup(f"nsgeo · {self.session.site_name}")
        for name in TABLES:
            if name in self.layers:
                continue
            layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
            if not layer.isValid():
                raise RuntimeError(f"could not open table {name!r} in {path}")
            layer.setReadOnly(name in DERIVED)
            self.project.addMapLayer(layer, False)
            self.group.addLayer(layer)
            self.layers[name] = layer

    @staticmethod
    def _table_exists(path: str, name: str) -> bool:
        return (
            Path(path).exists()
            and QgsVectorLayer(f"{path}|layername={name}", name, "ogr").isValid()
        )

    def _create_table(
        self,
        path: str,
        name: str,
        wkb: Any,
        spec: list[tuple[str, str]],
        crs: QgsCoordinateReferenceSystem,
    ) -> None:
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = name
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            if Path(path).exists()
            else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
        )
        writer = QgsVectorFileWriter.create(
            path, _fields(spec), wkb, crs, self.project.transformContext(), opts
        )
        if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
            raise RuntimeError(f"could not create table {name!r}: {writer.errorMessage()}")
        del writer  # closes the file handle before the layer opens it

    # ---- geometry helpers -------------------------------------------------
    def _transform_for(self, grid_crs: str) -> QgsCoordinateTransform | None:
        target = self.crs()
        assert target is not None
        source = QgsCoordinateReferenceSystem(grid_crs)
        if source == target:
            return None
        return QgsCoordinateTransform(source, target, self.project)

    def _points(self, xy: np.ndarray, grid_crs: str) -> list[QgsPointXY]:
        tr = self._transform_for(grid_crs)
        pts = [QgsPointXY(float(x), float(y)) for x, y in np.asarray(xy, dtype=float)]
        return [tr.transform(p) for p in pts] if tr is not None else pts

    def _line_points(
        self, line: Line, grid: Grid, frames: dict[str, Grid]
    ) -> list[QgsPointXY] | None:
        """World points for every trace of `line`, or None when the line
        cannot be positioned at all.

        `Line.trace_coords` (by way of `GridPlacement.distance_along`) raises
        `ValueError` for a time-triggered acquisition (traces_per_metre <= 0).
        That is a property of one file, not a reason to abort the whole
        table: the caller drops this one line and keeps the rest.
        """
        try:
            return self._points(line.trace_coords(frames), grid.crs)
        except ValueError as exc:
            QgsMessageLog.logMessage(
                f"{line.path.name} could not be placed and was left out of the map: {exc}",
                "nsgeo",
                Qgis.MessageLevel.Warning,
            )
            return None

    def _refill(self, name: str, features: list[QgsFeature]) -> None:
        layer = self.layers[name]
        provider = layer.dataProvider()
        if not provider.truncate():
            raise RuntimeError(f"could not truncate {name}: {provider.error().message()}")
        if features:
            ok, _ = provider.addFeatures(features)
            if not ok:
                raise RuntimeError(f"could not write {name}: {provider.error().message()}")
        layer.updateExtents()
        layer.triggerRepaint()

    def feature_count(self, name: str) -> int:
        return int(self.layers[name].featureCount())

    # ---- derived tables ---------------------------------------------------
    def refill_grids(self) -> None:
        site = self.session.site
        assert site is not None
        feats = []
        for grid in site.grids:
            local = np.array(
                [[0.0, 0.0], [grid.size_x, 0.0], [grid.size_x, grid.size_y], [0.0, grid.size_y]]
            )
            ring = self._points(grid.to_world(local), grid.crs)
            f = QgsFeature(self.layers["grids"].fields())
            f.setGeometry(QgsGeometry.fromPolygonXY([ring]))
            f["grid_id"] = grid.id
            f["azimuth"] = grid.azimuth
            f["size_x"] = grid.size_x
            f["size_y"] = grid.size_y
            f["default_spacing"] = grid.default_spacing
            f["velocity_json"] = json.dumps(grid.velocity.to_dict()) if grid.velocity else ""
            feats.append(f)
        self._refill("grids", feats)

    def refill_lines(self) -> None:
        site = self.session.site
        assert site is not None
        feats = []
        for line in site.lines:
            grid = self.session.grid_for_line(line)
            if grid is None:
                continue  # trackless lines arrive with TrackPlacement, later
            coords = self._line_points(line, grid, site.frames)
            if coords is None:
                continue  # unplaceable (e.g. time-triggered); degrade, don't abort the table
            f = QgsFeature(self.layers["lines"].fields())
            f.setGeometry(QgsGeometry.fromPolylineXY(coords))
            p: Any = line.placement
            f["line_key"] = self.session.line_key(line)
            f["grid_id"] = grid.id
            f["label"] = p.label or ""
            f["axis"] = p.axis
            f["offset_m"] = float(p.offset)
            f["start_along_m"] = float(p.start_along)
            f["direction"] = int(p.direction)
            f["n_traces"] = int(line.n_traces)
            f["length_m"] = float(line.n_traces / line.header.traces_per_metre)
            f["antenna"] = line.header.antenna
            f["file_name"] = line.path.name
            feats.append(f)
        self._refill("lines", feats)
        self._style_lines()

    def refill_marks(self) -> None:
        site = self.session.site
        assert site is not None
        feats = []
        for line in site.lines:
            grid = self.session.grid_for_line(line)
            if grid is None:
                continue
            try:
                info = read_dzx(line.path)
            except DzxError:
                continue
            if info is None or not info.marks:
                continue
            coords = self._line_points(line, grid, site.frames)
            if coords is None:
                continue  # unplaceable line; its marks have nowhere to go either
            for mark in info.marks:
                idx = max(0, min(mark.scan, line.n_traces - 1))
                f = QgsFeature(self.layers["marks"].fields())
                f.setGeometry(QgsGeometry.fromPointXY(coords[idx]))
                f["line_key"] = self.session.line_key(line)
                f["scan"] = int(mark.scan)
                f["kind"] = mark.kind
                f["name"] = mark.name
                feats.append(f)
        self._refill("marks", feats)

    def _style_lines(self) -> None:
        site = self.session.site
        assert site is not None
        categories = []
        for i, grid in enumerate(site.grids):
            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.GeometryType.LineGeometry)
            symbol.setColor(QColor(GRID_COLOURS[i % len(GRID_COLOURS)]))
            symbol.setWidth(0.5)
            categories.append(QgsRendererCategory(grid.id, symbol, grid.id))
        self.layers["lines"].setRenderer(QgsCategorizedSymbolRenderer("grid_id", categories))
        self.layers["lines"].triggerRepaint()


def line_for_feature(session: SiteSession, feature: QgsFeature) -> Line:
    """The session line a `lines` feature represents."""
    return session.line_for_key(str(feature["line_key"]))
