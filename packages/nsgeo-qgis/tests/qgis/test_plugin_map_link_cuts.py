"""MapLink on cuts: hover, select, cursor tracking both ways (cut spec §4.3, plan calls 9 and 10).

Grid A is rotated 10.497 degrees, so a cut is oblique in world coordinates
as well as to the lines; its lines are 0.5 m apart, and the cut runs close
enough to them (0.35 m across 2.5 m) that hovering a point on it is also
within hover reach of a line (the canvas is 30 m wide, so the reach is about half a metre).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.cut_sections import CutSections
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.map_link import MapLink
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.slices_dock import SlicesDock
from plugin_testing import synthetic_dzt
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
)
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtWidgets import QMessageBox
from test_plugin_slices_dock import _ready

GRID = Grid("A", (500.0, 700.0), 10.497, 6.0, 6.0, "EPSG:32616", 0.5)
UTM16 = QgsCoordinateReferenceSystem("EPSG:32616")
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
CUT = [(1.55, 0.5), (1.9, 3.0)]  # oblique to the lines, 0.1-0.4 m from line x = 1.5 near its start
CELL_HALF = 0.125  # Slices cell 0.25, columns every half cell


def _local_on_cut(session, key, distance):
    return session.cut_for_key(key).point_at(distance)


def _world(grid, local):
    x, y = grid.to_world(np.array([local], dtype=float))[0]
    return QgsPointXY(float(x), float(y))


@pytest.fixture
def cutlink(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    lines = [
        Line.open(
            synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60),
            GridPlacement("A", "y", 1.0 + 0.5 * i, 0.0, 1, f"FILE__00{i + 1}"),
        )
        for i in range(5)
    ]
    session.add_lines(lines)
    session.site.presets["p"] = [{"step": "dewow", "params": {}, "enabled": True}]
    session.presets_changed.emit()
    dock = SlicesDock(session)
    _ready(dock)
    sections = CutSections(session, dock)
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(layers.crs())
    centre = _world(GRID, (2.0, 2.0))
    canvas.setExtent(
        QgsRectangle(centre.x() - 15, centre.y() - 12, centre.x() + 15, centre.y() + 12)
    )
    link = MapLink(session, layers, canvas)
    link.set_sections(sections)
    key = session.add_cut("A", CUT)
    keys = session.keys()
    session.open_line(keys[0])
    yield SimpleNamespace(
        link=link,
        session=session,
        layers=layers,
        canvas=canvas,
        sections=sections,
        key=key,
        keys=keys,
        dock=dock,
    )
    link.dispose()
    sections.dispose()
    dock.refiner.shutdown()
    dock.engine.wait_for_preparation(20_000)
    dock.engine.dispose()
    dock.deleteLater()
    layers.detach()
    project.clear()


def _fire_dwell(link):
    link._dwell.timeout.emit()


def _hover(c, point):
    c.canvas.xyCoordinates.emit(point)
    _fire_dwell(c.link)


def _spot(c, distance):
    """The world point `distance` along the cut, and the column it should find."""
    local = _local_on_cut(c.session, c.key, distance)
    return _world(GRID, local), c.sections.column_at(c.key, distance)


def test_cut_mode_hover_previews_the_cut_not_the_nearby_line(cutlink):
    c = cutlink
    c.link.set_cut_mode(True)
    point, column = _spot(c, 0.30 + 0.03)  # 0.1 m from line x = 1.5 near the start
    assert column is not None

    _hover(c, point)

    assert c.session.preview_key == c.key
    assert c.session.preview_trace == column
    cut = c.session.cut_for_key(c.key)
    local = GRID.to_local(np.array([[point.x(), point.y()]]))[0]
    assert column == c.sections.column_at(c.key, cut.locate((local[0], local[1]))[0])
    assert c.session.current_key == c.keys[0]  # hover never moves the working line


def test_line_mode_ignores_cuts(cutlink):
    c = cutlink
    point, _ = _spot(c, 0.33)

    _hover(c, point)

    assert c.session.preview_key in c.keys
    assert c.session.preview_key != c.key


def test_changing_mode_mid_hover_leaves_no_stale_preview(cutlink):
    c = cutlink
    c.link.set_cut_mode(True)
    point, _ = _spot(c, 0.33)
    _hover(c, point)
    assert c.session.preview_key == c.key

    c.link.set_cut_mode(False)

    assert c.session.preview_key is None
    assert not c.link.cut_mode


def test_the_working_cut_stays_open_when_another_layer_becomes_current(cutlink):
    c = cutlink
    c.link.set_cut_mode(True)
    c.session.open_line(c.key)

    c.link.set_cut_mode(False)

    assert c.session.current_key == c.key
    on_a_line = QgsPointXY(
        c.link._geometries()[c.keys[4]].vertexAt(10)
    )  # line x = 3.0, away from the cut
    _hover(c, on_a_line)
    assert c.session.preview_key == c.keys[4]
    assert c.session.current_key == c.key
    lines = c.layers.layers["lines"]
    fid = next(f.id() for f in lines.getFeatures() if f["line_key"] == c.keys[2])
    lines.selectByIds([fid])
    assert c.session.current_key == c.keys[2]


def test_selecting_a_cut_opens_it(cutlink):
    c = cutlink
    cuts = c.layers.layers["cuts"]
    fid = next(f.id() for f in cuts.getFeatures() if f["cut_key"] == c.key)

    cuts.selectByIds([fid])

    assert c.session.current_key == c.key


def test_tracking_works_both_ways_along_a_cut(cutlink):
    c = cutlink
    c.link.set_cut_mode(True)
    c.session.open_line(c.key)
    assert not isinstance(c.sections.section(c.key, build_cube=True), str)

    seen = []
    for distance in (0.4, 1.0, 1.6, 2.2):
        point, column = _spot(c, distance)
        c.canvas.xyCoordinates.emit(point)  # no dwell: moving along the working cut is free
        seen.append(c.session.current_trace)
        assert c.session.current_trace == column
    assert seen == sorted(seen) and len(set(seen)) == 4

    c.session.set_trace(c.key, 20)
    section = c.sections.section(c.key, build_cube=False)
    want = QgsPointXY(*section.columns.world[20])
    assert c.link._marker.isVisible()
    assert c.link._marker.center().distance(want) < 1e-6


def test_the_marker_and_band_follow_a_selection_on_a_cut(cutlink):
    c = cutlink
    c.session.open_line(c.key)
    section = c.sections.section(c.key, build_cube=True)

    c.session.set_selection(c.key, 5, 12)

    assert c.link._band.numberOfVertices() == 8
    first = c.link._band.getPoint(0, 0)
    assert QgsPointXY(first).distance(QgsPointXY(*section.columns.world[5])) < 1e-6
    c.session.clear_selection()
    assert c.link._band.numberOfVertices() == 0


def test_a_cut_with_no_section_shows_no_cursor_but_still_previews(cutlink):
    c = cutlink
    c.link.set_cut_mode(True)
    c.dock.engine.drop_cube()
    c.link.set_sections(None)
    point, _ = _spot(c, 0.33)

    _hover(c, point)

    assert c.session.preview_key == c.key
    assert c.session.preview_trace == -1
    assert not c.link._marker.isVisible()


def test_hover_on_a_geographic_canvas_finds_the_right_column(cutlink):
    c = cutlink
    c.link.set_cut_mode(True)
    to_geo = QgsCoordinateTransform(UTM16, WGS84, QgsProject.instance())
    centre = to_geo.transform(_world(GRID, (2.0, 2.0)))
    c.canvas.setDestinationCrs(WGS84)
    c.canvas.setExtent(
        QgsRectangle(
            centre.x() - 0.0001, centre.y() - 0.00008, centre.x() + 0.0001, centre.y() + 0.00008
        )
    )
    point, column = _spot(c, 1.2 + 0.03)
    assert column is not None

    _hover(c, to_geo.transform(point))

    assert c.session.preview_key == c.key
    assert c.session.preview_trace == column
    # ... and the marker comes back to the same ground, in degrees.
    c.session.open_line(c.key)
    section = c.sections.section(c.key, build_cube=True)
    c.session.set_trace(c.key, 20)
    want = to_geo.transform(QgsPointXY(*section.columns.world[20]))
    assert c.link._marker.center().distance(want) < 1e-9


def test_hovering_a_cut_while_a_line_works_never_writes_to_the_cut(cutlink):
    c = cutlink
    c.link.set_cut_mode(True)
    point, _ = _spot(c, 0.33)
    _hover(c, point)
    assert c.session.preview_key == c.key
    written: list[int] = []
    c.session.picks_changed.connect(lambda: written.append(1))

    with pytest.raises(ValueError, match="working line"):
        c.session.add_pick(c.key, 3, 10.0)

    assert written == []


def test_the_plugin_follows_the_current_layer(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    try:
        plugin.session.new_site(tmp_path)
        plugin.session.add_grid(GRID)
        cuts = plugin.layers.layers["cuts"]
        lines = plugin.layers.layers["lines"]

        fake_iface.setActiveLayer(cuts)
        assert plugin.map_link.cut_mode
        fake_iface.setActiveLayer(lines)
        assert not plugin.map_link.cut_mode
        fake_iface.setActiveLayer(cuts)
        fake_iface.setActiveLayer(None)
        assert not plugin.map_link.cut_mode

        # A rebuild replaces the layer objects: the new cuts layer still counts.
        plugin.layers.detach()
        plugin.layers.refresh()
        new_cuts = plugin.layers.layers["cuts"]
        assert new_cuts is not cuts
        fake_iface.setActiveLayer(new_cuts)
        assert plugin.map_link.cut_mode
    finally:
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.unload()
