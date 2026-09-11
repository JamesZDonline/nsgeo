"""The site GeoPackage: one file, several tables, four rules.

1. Regenerate per table, never per file: rebuilding `lines` truncates and
   refills that table; the file is never deleted, so picks survive and
   Windows file locks never bite.
2. All writes go through the loaded QGIS layer's data provider, never a
   second OGR handle on a package QGIS already has open.
3. Derived tables (grids, lines, marks) are read-only in QGIS; the survey
   JSON is the source of truth for geometry. Picks are authored.
4. A signal slot's exception never reaches whatever emitted the signal --
   PyQt5 prints it to stderr and moves on -- so `refresh()` contains each
   table's own refill and logs a failure via `QgsMessageLog` rather than
   letting one bad table silently cancel the other two.

The package CRS is the CRS of the first grid; other grids are transformed
into it on write. If the first grid's own CRS changes (or a package
predates a field this version of `TABLES` expects), every table is
rebuilt: `picks` rows are carried across (matching fields copied by name,
geometry transformed to the new CRS), and the derived tables are simply
refilled anew immediately afterward.
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
from qgis.PyQt import sip
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


def _log(message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Warning) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", level)


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
        # A layer removed from the legend by hand (or any other code) is
        # gone from QGIS but not from the GeoPackage: drop it from our
        # registry so the next refresh reopens it, rather than holding a
        # Python wrapper around a since-deleted C++ object.
        self.project.layersWillBeRemoved.connect(self._on_layers_removed)

    # ---- lifecycle --------------------------------------------------------
    def _on_site_opened(self) -> None:
        self.detach()
        self.refresh()

    def _on_layers_removed(self, ids: list[str]) -> None:
        gone = {
            name for name, lyr in self.layers.items() if not sip.isdeleted(lyr) and lyr.id() in ids
        }
        for name in gone:
            del self.layers[name]

    def detach(self) -> None:
        if self.layers:
            ids = [lyr.id() for lyr in self.layers.values() if not sip.isdeleted(lyr)]
            if ids:
                self.project.removeMapLayers(ids)
            self.layers.clear()
        if self.group is not None:
            if not sip.isdeleted(self.group):
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
        if site is None:
            return
        if not site.grids:
            self._clear_derived_tables()
            return
        self.ensure_tables()
        for name, fn in (
            ("grids", self.refill_grids),
            ("lines", self.refill_lines),
            ("marks", self.refill_marks),
        ):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 -- see rule 4 above
                _log(f"could not refill {name!r}: {exc}", Qgis.MessageLevel.Critical)

    def _clear_derived_tables(self) -> None:
        """No grids left: there is nothing to derive line/mark geometry
        from. The tables were already created while a grid existed, so
        clear them rather than leaving the last grid's stale features on
        the map. `picks` is untouched, same as every other refill."""
        for name in DERIVED:
            if name not in self.layers:
                continue  # a site that has never had a grid: nothing to clear
            try:
                self._refill(name, [])
            except Exception as exc:  # noqa: BLE001 -- see rule 4 above
                _log(f"could not clear {name!r}: {exc}", Qgis.MessageLevel.Critical)

    # ---- tables -----------------------------------------------------------
    def ensure_tables(self) -> None:
        path = str(self.session.gpkg_path)
        crs = self.crs()
        assert crs is not None
        for name, (wkb, spec) in TABLES.items():
            self._ensure_table(path, name, wkb, spec, crs)
        if self.group is None:
            self.group = self.project.layerTreeRoot().addGroup(f"nsgeo · {self.session.site_name}")
        opened = []
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
            opened.append(layer)
        # A just-(re)created table's provider feature count is sometimes
        # left at the GPKG driver's -1 "not yet counted" sentinel until
        # something forces a recount -- measured to need every table in
        # this GeoPackage opened first: reloading a layer immediately
        # after opening it does not reliably clear it, reloading again
        # once the whole batch is open does. feature_count() below also
        # falls back to counting directly, belt and braces.
        for layer in opened:
            layer.reload()

    def _ensure_table(
        self,
        path: str,
        name: str,
        wkb: Any,
        spec: list[tuple[str, str]],
        crs: QgsCoordinateReferenceSystem,
    ) -> None:
        """Create the table if it doesn't exist yet, or rebuild it if its
        on-disk CRS or field set no longer matches `crs`/`spec`. A grid's
        CRS can change after its table was first created (`replace_grid`),
        and an older package can predate a field this version of `TABLES`
        expects -- either way, refilling into a stale table would write
        the wrong CRS or crash on a missing field.

        `picks` rows are migrated across the rebuild; the derived tables
        are about to be fully refilled by refill_grids/lines/marks right
        after this returns, so their old rows need no such care.
        """
        existing_crs, existing_fields = self._table_schema(path, name)
        up_to_date = existing_crs is not None and existing_crs == crs
        if up_to_date and existing_fields == [f for f, _ in spec]:
            return  # up to date; nothing to rebuild
        old_rows: list[tuple[dict[str, Any], QgsGeometry]] = []
        if name == "picks" and existing_crs is not None:
            old_rows = self._read_picks_rows(path, existing_crs, crs)
        self._drop_loaded_layer(name)
        self._create_table(path, name, wkb, spec, crs)
        if old_rows:
            # Built against the newly (re)created layer's own `.fields()`,
            # not `_fields(spec)`: a GPKG table always carries an implicit
            # leading "fid" field that `spec` doesn't list, and attributes
            # keyed off a Fields object one short of the provider's own
            # silently land one column over (measured directly: a pick's
            # `line_key` came back as its `time_ns` value, `time_ns` as
            # NULL). Setting by field *name* against the real fields is
            # what keeps this correct regardless of column order.
            layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
            new_field_names = {f.name() for f in layer.fields()}
            feats = []
            for attrs, geom in old_rows:
                f = QgsFeature(layer.fields())
                for fname, value in attrs.items():
                    if fname in new_field_names:
                        f[fname] = value
                f.setGeometry(geom)
                feats.append(f)
            ok, _ = layer.dataProvider().addFeatures(feats)
            if not ok:
                raise RuntimeError(
                    f"could not carry {name} rows across a rebuild: "
                    f"{layer.dataProvider().error().message()}"
                )

    @staticmethod
    def _table_schema(
        path: str, name: str
    ) -> tuple[QgsCoordinateReferenceSystem | None, list[str]]:
        """The on-disk table's CRS and field names, or (None, []) when the
        table doesn't exist yet."""
        if not Path(path).exists():
            return None, []
        layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
        if not layer.isValid():
            return None, []
        return layer.crs(), [f.name() for f in layer.fields() if f.name() != "fid"]

    def _read_picks_rows(
        self,
        path: str,
        existing_crs: QgsCoordinateReferenceSystem,
        target_crs: QgsCoordinateReferenceSystem,
    ) -> list[tuple[dict[str, Any], QgsGeometry]]:
        """Every row of the current on-disk `picks` table as a plain
        (field name -> value, geometry) pair, geometry already transformed
        if the CRS is changing. Read out *before* the table is dropped and
        recreated -- authored data, unlike grids/lines/marks there is
        nowhere else this comes from, so it must not be silently
        discarded. Kept as plain dicts rather than `QgsFeature` objects
        tied to the old schema, since the new table's field set (and its
        implicit `fid` column) may not match.
        """
        old_layer = QgsVectorLayer(f"{path}|layername=picks", "picks", "ogr")
        if not old_layer.isValid():
            return []
        transform = None
        if existing_crs != target_crs:
            transform = QgsCoordinateTransform(existing_crs, target_crs, self.project)
        field_names = [f.name() for f in old_layer.fields() if f.name() != "fid"]
        rows = []
        for old in old_layer.getFeatures():
            attrs = {fname: old[fname] for fname in field_names}
            geom = old.geometry()
            if transform is not None and not geom.isNull():
                geom.transform(transform)
            rows.append((attrs, geom))
        return rows

    def _drop_loaded_layer(self, name: str) -> None:
        layer = self.layers.pop(name, None)
        if layer is not None and not sip.isdeleted(layer):
            self.project.removeMapLayer(layer.id())

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

        Only `Line.trace_coords` is guarded: it (by way of
        `GridPlacement.distance_along`) raises `ValueError` for a
        time-triggered acquisition (traces_per_metre <= 0), a property of
        one file that must not abort the whole table. `self._points`
        (the CRS transform) stays outside the guard -- a `ValueError`
        from there is a real bug (a bad shape, a broken transform), not
        an unplaceable line, and must not be misreported as one.
        """
        try:
            xy = line.trace_coords(frames)
        except ValueError as exc:
            _log(f"{line.path.name} could not be placed and was left out of the map: {exc}")
            return None
        return self._points(xy, grid.crs)

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
        layer = self.layers[name]
        count = layer.featureCount()
        if count < 0:
            # Belt and braces alongside ensure_tables()'s reload(): the
            # GPKG driver's cached count can come back negative in cases
            # we haven't all named. Counting features directly is correct
            # regardless of why the cache is stale, and this is a handful
            # to a few thousand rows, never a reason to avoid it.
            count = sum(1 for _ in layer.getFeatures())
        return int(count)

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
        keys = self.session.keys()
        for key in keys:
            line = self.session.line_for_key(key)
            grid = self.session.grid_for_line(line)
            if grid is None:
                continue  # trackless lines arrive with TrackPlacement, later
            coords = self._line_points(line, grid, site.frames)
            if coords is None:
                continue  # unplaceable (e.g. time-triggered); degrade, don't abort the table
            f = QgsFeature(self.layers["lines"].fields())
            f.setGeometry(QgsGeometry.fromPolylineXY(coords))
            p: Any = line.placement
            f["line_key"] = key
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
        keys = self.session.keys()
        for key in keys:
            line = self.session.line_for_key(key)
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
                f["line_key"] = key
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
