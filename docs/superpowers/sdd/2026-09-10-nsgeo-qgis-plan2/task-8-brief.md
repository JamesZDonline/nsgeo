### Task 8: `layers.py` — the site GeoPackage

Mirrors the session into `<site>.nsgeo.gpkg`: grids, lines, and marks are derived and read-only; picks is authored and editable. Regeneration is per table through the loaded layer's provider, never by touching the file.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/layers.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`

**Interfaces:**
- Consumes: `SiteSession` signals and accessors; `Line.trace_coords`, `Grid.to_world`, `read_dzx`
- Produces: `TABLES` (name → (wkb type, [(field, kind)])); `DERIVED = ("grids", "lines", "marks")`; `SiteLayers(session, project=None, parent=None)` with `layers: dict[str, QgsVectorLayer]`, `group`, `refresh()`, `ensure_tables()`, `refill_grids()`, `refill_lines()`, `refill_marks()`, `detach()`, `crs() -> QgsCoordinateReferenceSystem | None`, `feature_count(name) -> int`, `GRID_COLOURS`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer

from nsgeo_qgis.layers import DERIVED, TABLES, SiteLayers
from nsgeo_qgis.session import SiteSession

from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)

DZX = """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="www.geophysical.com/DZX/1.02"><File><name>FILE__002.DZT</name>
<Profile><WayPt><scan>30</scan><mark>User</mark><name>Mark1</name></WayPt></Profile></File></DZX>"""


@pytest.fixture
def populated(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1, p.stem)))
    (tmp_path / "raw" / "FILE__002.DZX").write_text(DZX)
    session.add_lines(lines)
    yield session, layers, project
    layers.detach()
    project.clear()


def test_tables_exist_with_the_declared_fields_and_flags(populated):
    session, layers, project = populated
    assert session.gpkg_path.is_file()
    for name, (_, fields) in TABLES.items():
        lyr = QgsVectorLayer(f"{session.gpkg_path}|layername={name}", name, "ogr")
        assert lyr.isValid(), name
        assert [f.name() for f in lyr.fields() if f.name() != "fid"] == [f for f, _ in fields]
    assert set(layers.layers) == set(TABLES)
    for name in TABLES:
        assert layers.layers[name].readOnly() is (name in DERIVED)
    assert layers.crs().authid() == "EPSG:32616"
    assert layers.layers["lines"].crs().authid() == "EPSG:32616"


def test_derived_tables_mirror_the_session(populated):
    session, layers, _ = populated
    assert layers.feature_count("grids") == 1
    assert layers.feature_count("lines") == 3
    assert layers.feature_count("marks") == 1
    feat = next(layers.layers["lines"].getFeatures())
    assert feat["line_key"] == "raw/FILE__001.DZT"
    assert feat["n_traces"] == 60
    assert feat["length_m"] == pytest.approx(1.0)
    assert feat.geometry().length() == pytest.approx(59 / 60, abs=1e-6)
    session.remove_line("raw/FILE__003.DZT")
    assert layers.feature_count("lines") == 2


def test_layers_are_grouped_in_the_project_under_the_site_name(populated):
    session, layers, project = populated
    group = project.layerTreeRoot().findGroup(f"nsgeo · {session.site_name}")
    assert group is not None
    assert len(group.findLayers()) == 4


def test_refill_never_touches_the_picks_table(populated):
    session, layers, _ = populated
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["time_ns"] = 43.1
    assert picks.dataProvider().addFeatures([f])[0]
    session.remove_line("raw/FILE__002.DZT")
    session.add_grid(Grid("B", (600.0, 700.0), 0.0, 2.0, 2.0, "EPSG:32616", 0.5))
    assert layers.feature_count("picks") == 1
    assert layers.feature_count("grids") == 2


def test_reopening_a_site_reuses_the_existing_package(populated, tmp_path):
    session, layers, project = populated
    session.save()
    layers.detach()
    again = SiteSession()
    layers2 = SiteLayers(again, project=project)
    again.open_site(tmp_path / "survey.nsgeo.json")
    assert layers2.feature_count("lines") == 3
    layers2.detach()


def test_grid_in_another_crs_is_transformed_into_the_package_crs(populated):
    session, layers, _ = populated
    session.add_grid(Grid("B", (-86.8, 36.4), 0.0, 0.001, 0.001, "EPSG:4326", 0.5))
    feats = {f["grid_id"]: f for f in layers.layers["grids"].getFeatures()}
    x = feats["B"].geometry().centroid().asPoint().x()
    assert 100_000 < x < 900_000  # UTM easting, not a longitude
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.layers'`

- [ ] **Step 3: Implement `layers.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/layers.py`:

```python
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
from nsgeo.io.dzx import DzxError, read_dzx
from nsgeo.model.survey import Line
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
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
        return Path(path).exists() and QgsVectorLayer(f"{path}|layername={name}", name, "ogr").isValid()

    def _create_table(
        self, path: str, name: str, wkb: Any, spec: list[tuple[str, str]], crs: QgsCoordinateReferenceSystem
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
            local = np.array([[0.0, 0.0], [grid.size_x, 0.0], [grid.size_x, grid.size_y], [0.0, grid.size_y]])
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
            f = QgsFeature(self.layers["lines"].fields())
            f.setGeometry(QgsGeometry.fromPolylineXY(self._points(line.trace_coords(site.frames), grid.crs)))
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
            coords = self._points(line.trace_coords(site.frames), grid.crs)
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
```

- [ ] **Step 4: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean. If `test_grid_in_another_crs_is_transformed_into_the_package_crs` fails with a null geometry, the transform context needs the project passed as above; check `QgsCoordinateTransform(source, target, self.project)` is used, not the two-argument form.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: per-site GeoPackage mirrored from the session

One package per site holds grids, lines, and marks (derived, read-only,
refilled per table through the loaded layer's provider) and picks
(authored, never touched by a refill). The package CRS is the first
grid's; other grids are transformed on write. Lines are styled per grid
with a categorised renderer."
```

---

