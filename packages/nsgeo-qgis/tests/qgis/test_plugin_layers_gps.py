"""M17a, P12: GPS lines, the stretches without an RTK fix, their marks and picks, on the map."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest
from nsgeo.geometry import END_LIMIT_M, Grid, GridPlacement, track_from_log
from nsgeo.io import dzg_for, read_dzg
from nsgeo.model.survey import Line
from nsgeo_qgis.layers import (
    CUT_COLOUR,
    DERIVED,
    GRID_COLOURS,
    LEGEND_ORDER,
    NO_GRID_COLOUR,
    RTK_GAP_COLOUR,
    TABLES,
    SiteLayers,
)
from nsgeo_qgis.map_link import MapLink
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.gps_import_dialog import lonlat_to_xy
from plugin_testing import synthetic_dzt, synthetic_gps_dzt
from qgis.core import (
    NULL,
    QgsCoordinateReferenceSystem,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsMapLayer,
    QgsPointXY,
    QgsProject,
    QgsProviderRegistry,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtCore import QMetaType
from tests.real_data import GRID2_LINES

CRS = "EPSG:32632"
LAT0, LON0 = 45.2, 10.5
M_PER_DEG = 6_371_000.0 * math.pi / 180.0

DZX = """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="www.geophysical.com/DZX/1.02"><File><name>{name}</name>
<Profile><WayPt><scan>50</scan><mark>User</mark><name>Mark1</name></WayPt></Profile></File></DZX>"""


def fix(trace, quality=4):
    """A fix on a line walked due north at 0.1 m a trace."""
    return (trace, LAT0 + trace * 0.1 / M_PER_DEG, LON0, quality)


def gps_line(folder, name, qualities, n_traces=200, travel_shift=0.0):
    """A line at 10 traces a metre with a fix at each trace of `qualities`."""
    path = synthetic_gps_dzt(
        folder,
        name,
        [fix(t, q) for t, q in sorted(qualities.items())],
        n_traces=n_traces,
        traces_per_metre=10.0,
    )
    return open_gps(path, travel_shift=travel_shift)


def open_gps(path, crs=CRS, travel_shift=0.0, grid_id=None):
    log = read_dzg(dzg_for(path))
    placement = track_from_log(log, lonlat_to_xy(QgsCoordinateReferenceSystem(crs)), crs)
    placement = dataclasses.replace(placement, travel_shift=travel_shift, grid_id=grid_id)
    return Line.open(path, placement)


def _site(tmp_path, pinned):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    if pinned:
        session.set_site_crs(CRS)  # what the first GPS import does
    return session, SiteLayers(session, project=project), project


@pytest.fixture
def site(qgis_app, tmp_path):
    session, layers, project = _site(tmp_path, True)
    yield session, layers, tmp_path
    layers.detach()
    project.clear()


@pytest.fixture
def tape_site(qgis_app, tmp_path):
    session, layers, project = _site(tmp_path, False)
    yield session, layers, tmp_path
    layers.detach()
    project.clear()


def feature(layers, table, **where):
    found = [
        f for f in layers.layers[table].getFeatures() if all(f[k] == v for k, v in where.items())
    ]
    assert len(found) == 1, (table, where, len(found))
    return found[0]


def vertices(f):
    return [(p.x(), p.y()) for p in f.geometry().asPolyline()]


def test_the_new_table_and_fields_are_declared():
    fields = [name for name, _ in TABLES["lines"][1]]
    assert fields[-3:] == ["file_name", "placed_by", "without_rtk_m"]
    assert TABLES["rtk_gaps"] == (
        QgsWkbTypes.Type.LineString,
        [
            ("line_key", "str"),
            ("kind", "str"),
            ("first_trace", "int"),
            ("last_trace", "int"),
            ("metres", "float"),
        ],
    )
    assert DERIVED == ("grids", "lines", "marks", "cuts", "rtk_gaps")
    assert LEGEND_ORDER == ("picks", "marks", "cuts", "rtk_gaps", "lines", "grids")


def test_a_gps_line_with_no_grid_is_drawn_along_its_track(site):
    session, layers, tmp = site
    line = gps_line(tmp / "raw", "FILE__001.DZT", {25: 4, 175: 4}, travel_shift=0.24)
    session.add_lines([line])

    f = feature(layers, "lines")
    expected = line.trace_coords({})
    got = np.array(vertices(f))
    assert got.shape == expected.shape
    assert np.allclose(got, expected, atol=1e-6)
    assert f["placed_by"] == "gps"
    assert f["grid_id"] == ""
    for tape_only in ("axis", "offset_m", "start_along_m", "direction"):
        assert f[tape_only] == NULL, tape_only
    d = line.placement.distance_along(line.n_traces, line.header)
    walked = float(d[-1] - d[0])
    assert f["length_m"] == pytest.approx(walked)
    assert f["length_m"] == pytest.approx(f.geometry().length(), abs=1e-6)
    assert f["without_rtk_m"] == pytest.approx(0.0)
    assert f["n_traces"] == 200
    assert f["file_name"] == "FILE__001.DZT"
    assert layers.layers["lines"].crs().authid() == CRS


def test_a_grid_free_site_draws_its_gps_lines(site):
    session, layers, tmp = site
    assert not session.site.grids
    session.add_lines(
        [
            gps_line(tmp / "raw", "FILE__001.DZT", {25: 4, 175: 4}),
            gps_line(tmp / "raw", "FILE__002.DZT", {25: 4, 175: 4}),
        ]
    )
    assert layers.feature_count("lines") == 2
    assert layers.feature_count("grids") == 0
    # The tables are in the legend, in order, with the gap table above the lines.
    names = [c.layer().name() for c in layers.group.findLayers()]
    assert names.index("rtk_gaps") < names.index("lines")
    session.remove_line("raw/FILE__001.DZT")
    session.remove_line("raw/FILE__002.DZT")
    assert layers.feature_count("lines") == 0  # the last line out clears the tables


def test_a_bridge_is_drawn_in_rtk_gaps(site):
    session, layers, tmp = site
    line = gps_line(tmp / "raw", "FILE__001.DZT", {15: 4, 75: 5, 125: 4, 185: 4})
    session.add_lines([line])

    (bridge,) = line.placement.bridges()
    assert layers.feature_count("rtk_gaps") == 1
    f = feature(layers, "rtk_gaps", kind="bridge")
    assert f["line_key"] == "raw/FILE__001.DZT"
    assert (f["first_trace"], f["last_trace"]) == (15, 125)
    assert f["metres"] == pytest.approx(bridge.metres)
    coords = line.trace_coords({})
    assert np.allclose(np.array(vertices(f)), coords[15:126], atol=1e-6)
    assert feature(layers, "lines")["without_rtk_m"] == pytest.approx(bridge.metres)


def test_only_long_end_runs_are_drawn(site):
    session, layers, tmp = site
    # trace 30 is 3 m from the start; the end anchor sits 0.4 m from the last trace
    long_start = gps_line(tmp / "raw", "FILE__001.DZT", {30: 4, 195: 4})
    # trace 5 is 0.5 m from the start, and the end run is 0.4 m
    short = gps_line(tmp / "raw", "FILE__002.DZT", {5: 4, 195: 4})
    session.add_lines([long_start, short])

    assert layers.feature_count("rtk_gaps") == 1
    f = feature(layers, "rtk_gaps")
    assert f["line_key"] == "raw/FILE__001.DZT"
    assert f["kind"] == "start"
    assert (f["first_trace"], f["last_trace"]) == (0, 30)
    start_m, _ = long_start.placement.end_runs(long_start.n_traces, long_start.header)
    assert start_m > END_LIMIT_M
    assert f["metres"] == pytest.approx(start_m)
    assert np.allclose(np.array(vertices(f)), long_start.trace_coords({})[:31], atol=1e-6)


def test_a_long_end_run_at_the_far_end_is_an_end_feature(site):
    session, layers, tmp = site
    line = gps_line(tmp / "raw", "FILE__001.DZT", {5: 4, 150: 4})
    session.add_lines([line])
    f = feature(layers, "rtk_gaps")
    assert f["kind"] == "end"
    assert (f["first_trace"], f["last_trace"]) == (150, 199)
    _, end_m = line.placement.end_runs(line.n_traces, line.header)
    assert f["metres"] == pytest.approx(end_m)
    assert np.allclose(np.array(vertices(f)), line.trace_coords({})[150:], atol=1e-6)


def test_marks_on_a_gps_line_sit_on_its_track(site):
    session, layers, tmp = site
    line = gps_line(tmp / "raw", "FILE__001.DZT", {25: 4, 175: 4})
    (tmp / "raw" / "FILE__001.DZX").write_text(DZX.format(name="FILE__001.DZT"))
    session.add_lines([line])

    f = feature(layers, "marks")
    assert f["scan"] == 50
    p = f.geometry().asPoint()
    assert (p.x(), p.y()) == pytest.approx(tuple(line.trace_coords({})[50]), abs=1e-6)


def test_a_pick_on_a_gps_line_sits_on_its_track(site):
    session, layers, tmp = site
    line = gps_line(tmp / "raw", "FILE__001.DZT", {25: 4, 175: 4})
    session.add_lines([line])

    session.open_line("raw/FILE__001.DZT")
    session.add_pick("raw/FILE__001.DZT", 80, 20.0)
    f = next(layers.layers["picks"].getFeatures())
    p = f.geometry().asPoint()
    assert (p.x(), p.y()) == pytest.approx(tuple(line.trace_coords({})[80]), abs=1e-6)


def test_a_pick_on_a_gps_line_is_put_back_on_its_track_by_follow_lines(site):
    session, layers, tmp = site
    line = gps_line(tmp / "raw", "FILE__001.DZT", {25: 4, 175: 4})
    session.add_lines([line])
    session.open_line("raw/FILE__001.DZT")
    session.add_pick("raw/FILE__001.DZT", 80, 20.0)
    picks = layers.layers["picks"]
    feature_id = next(picks.getFeatures()).id()
    assert picks.dataProvider().changeGeometryValues(
        {feature_id: QgsGeometry.fromPointXY(QgsPointXY(1.0, 2.0))}
    )

    assert layers.follow_lines() == 1

    p = next(picks.getFeatures()).geometry().asPoint()
    assert (p.x(), p.y()) == pytest.approx(tuple(line.trace_coords({})[80]), abs=1e-6)


def test_tape_lines_are_drawn_as_before_with_placed_by_tape(tape_site):
    session, layers, tmp = tape_site
    grid = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)
    session.add_grid(grid)
    p = synthetic_dzt(tmp / "raw", "FILE__001.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.5, 0.0, 1, p.stem))])
    f = feature(layers, "lines")
    assert f["placed_by"] == "tape"
    assert f["without_rtk_m"] == NULL
    assert f["grid_id"] == "A"
    assert f["axis"] == "y"
    assert layers.feature_count("rtk_gaps") == 0


def test_gps_and_tape_lines_share_a_site_and_the_no_grid_category_is_styled(site):
    session, layers, tmp = site
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, CRS, 0.5))
    p = synthetic_dzt(tmp / "raw", "FILE__001.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.5, 0.0, 1, p.stem))])
    session.add_lines([gps_line(tmp / "raw", "FILE__002.DZT", {25: 4, 175: 4})])
    assert layers.feature_count("lines") == 2

    cats = {str(c.value()): c for c in layers.layers["lines"].renderer().categories()}
    assert set(cats) == {"A", ""}
    none = cats[""]
    assert none.label() == "No grid"
    assert none.symbol().color().name() == NO_GRID_COLOUR
    stroke = none.symbol().symbolLayer(0)
    assert none.symbol().width() == pytest.approx(0.2)
    assert stroke.useCustomDashPattern()
    assert list(stroke.customDashVector()) == [3.0, 2.0]
    assert NO_GRID_COLOUR != RTK_GAP_COLOUR


def test_the_gap_table_is_dotted_pink_and_not_selectable(site):
    session, layers, tmp = site
    session.add_lines([gps_line(tmp / "raw", "FILE__001.DZT", {15: 4, 75: 5, 125: 4, 185: 4})])
    layer = layers.layers["rtk_gaps"]
    symbol = layer.renderer().symbol()
    assert symbol.color().name() == RTK_GAP_COLOUR
    assert symbol.width() == pytest.approx(0.8)
    stroke = symbol.symbolLayer(0)
    assert stroke.useCustomDashPattern()
    assert list(stroke.customDashVector()) == [0.5, 1.0]
    assert not (layer.flags() & QgsMapLayer.LayerFlag.Identifiable)
    # ... and selecting a gap navigates nowhere: MapLink binds no slot to it.
    link = MapLink(session, layers, QgsMapCanvas())
    try:
        assert set(link._selection_slots) == {"lines", "picks", "marks", "cuts"}
        assert "rtk_gaps" not in link._bound
    finally:
        link.dispose()
    assert RTK_GAP_COLOUR not in GRID_COLOURS
    assert RTK_GAP_COLOUR != CUT_COLOUR


def test_an_older_package_gains_the_new_fields_and_table(site):
    session, layers, tmp = site
    session.add_lines([gps_line(tmp / "raw", "FILE__001.DZT", {15: 4, 75: 5, 125: 4, 185: 4})])
    session.save()
    layers.detach()
    project = QgsProject.instance()
    project.clear()

    # An older package: the old `lines` fields, and no `rtk_gaps` table at all.
    connection = (
        QgsProviderRegistry.instance()
        .providerMetadata("ogr")
        .createConnection(str(session.gpkg_path), {})
    )
    connection.dropVectorTable("", "rtk_gaps")
    del connection
    old = QgsFields()
    for name, kind in TABLES["lines"][1]:
        if name in ("placed_by", "without_rtk_m"):
            continue
        old.append(
            QgsField(
                name,
                {"str": QMetaType.Type.QString, "int": QMetaType.Type.Int}.get(
                    kind, QMetaType.Type.Double
                ),
            )
        )
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = "lines"
    opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
    writer = QgsVectorFileWriter.create(
        str(session.gpkg_path),
        old,
        QgsWkbTypes.Type.LineString,
        QgsCoordinateReferenceSystem(CRS),
        project.transformContext(),
        opts,
    )
    assert writer.hasError() == QgsVectorFileWriter.WriterError.NoError
    del writer
    assert not QgsVectorLayer(f"{session.gpkg_path}|layername=rtk_gaps", "x", "ogr").isValid()
    stale = QgsVectorLayer(f"{session.gpkg_path}|layername=lines", "x", "ogr")
    assert "placed_by" not in [f.name() for f in stale.fields()]
    del stale

    again = SiteSession()
    layers2 = SiteLayers(again, project=project)
    again.open_site(tmp / "survey.nsgeo.json")
    try:
        assert [f.name() for f in layers2.layers["lines"].fields() if f.name() != "fid"] == [
            n for n, _ in TABLES["lines"][1]
        ]
        assert layers2.feature_count("lines") == 1
        assert [f.name() for f in layers2.layers["rtk_gaps"].fields() if f.name() != "fid"] == [
            n for n, _ in TABLES["rtk_gaps"][1]
        ]
        assert layers2.feature_count("rtk_gaps") == 1
    finally:
        layers2.detach()


@pytest.mark.skipif(len(GRID2_LINES) != 60, reason="needs Grid 2 in tests/data/local/grid2")
def test_the_second_surveys_dropout_is_drawn(tape_site):
    session, layers, _ = tape_site
    session.set_site_crs("EPSG:32616")
    path = next(p for p in GRID2_LINES if p.name == "FILE__039.DZT")
    line = open_gps(path, "EPSG:32616")
    session.add_lines([line])
    bridges = [f for f in layers.layers["rtk_gaps"].getFeatures() if f["kind"] == "bridge"]
    assert len(bridges) == 1
    assert (bridges[0]["first_trace"], bridges[0]["last_trace"]) == (149, 246)


def test_a_gps_line_naming_a_grid_in_another_crs_is_drawn_in_its_own_crs(site):
    session, layers, tmp = site
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    path = synthetic_gps_dzt(
        tmp / "raw",
        "FILE__001.DZT",
        [fix(25), fix(75, 5), fix(125), fix(185)],
        traces_per_metre=10.0,
    )
    (tmp / "raw" / "FILE__001.DZX").write_text(DZX.format(name="FILE__001.DZT"))
    line = open_gps(path, grid_id="A")
    session.add_lines([line])
    assert session.grid_for_line(line) is not None  # the hazard: a grid in another CRS

    expected = line.trace_coords({})
    assert np.allclose(np.array(vertices(feature(layers, "lines"))), expected, atol=1e-6)
    assert feature(layers, "lines")["grid_id"] == ""
    m = feature(layers, "marks").geometry().asPoint()
    assert (m.x(), m.y()) == pytest.approx(tuple(expected[50]), abs=1e-6)
    gap = feature(layers, "rtk_gaps", kind="bridge")
    assert np.allclose(np.array(vertices(gap)), expected[25:126], atol=1e-6)
    session.open_line("raw/FILE__001.DZT")
    session.add_pick("raw/FILE__001.DZT", 80, 20.0)
    p = next(layers.layers["picks"].getFeatures()).geometry().asPoint()
    assert (p.x(), p.y()) == pytest.approx(tuple(expected[80]), abs=1e-6)


def test_a_tape_only_site_has_no_no_grid_row(tape_site):
    session, layers, tmp = tape_site
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    p = synthetic_dzt(tmp / "raw", "FILE__001.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.5, 0.0, 1, p.stem))])
    cats = list(layers.layers["lines"].renderer().categories())
    assert [str(c.value()) for c in cats] == ["A"]
    assert [c.label() for c in cats] == ["A"]
