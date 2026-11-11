"""Drawing a cut: the Cut toggle, the tool, and what a finished path becomes (cut spec §4.1)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.maptools.cut_tool import CutTool
from nsgeo_qgis.plugin import CUT_HINT_TEXT, OUTSIDE_TEXT, TOO_FEW_TEXT
from plugin_testing import send_map_key, send_map_mouse, synthetic_dzt
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
)
from qgis.gui import QgsMapToolPan
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QMessageBox

UTM16 = QgsCoordinateReferenceSystem("EPSG:32616")
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")

# Both grids sit on the canvas (0, 0)-(800, 600) at 1 m per pixel; A and B overlap in
# (350, 250)-(400, 300).
GRID_A = Grid("A", (300.0, 200.0), 0.0, 100.0, 100.0, "EPSG:32616", 0.5)
GRID_B = Grid("B", (350.0, 250.0), 0.0, 100.0, 100.0, "EPSG:32616", 0.5)


def _line(tmp_path, grid_id, name, offset):
    return Line.open(
        synthetic_dzt(tmp_path / "raw", f"{name}.DZT", n_traces=60),
        GridPlacement(grid_id, "y", offset, 0.0, 1, name),
    )


@pytest.fixture
def drawing(real_iface, tmp_path, answer_modal):
    """A plugin on a shown canvas with grids A and B, each with lines, and a site open."""
    import nsgeo_qgis

    iface = real_iface(UTM16, QgsRectangle(0, 0, 800, 600))
    plugin = nsgeo_qgis.classFactory(iface)
    plugin.initGui()
    session = plugin.session
    session.new_site(tmp_path)
    session.add_grid(GRID_A)
    session.add_grid(GRID_B)
    session.add_lines(
        [_line(tmp_path, "A", "FILE__001", 10.0), _line(tmp_path, "A", "FILE__002", 20.0)]
    )
    session.add_lines([_line(tmp_path, "B", "FILE__011", 10.0)])
    yield SimpleNamespace(
        iface=iface,
        plugin=plugin,
        session=session,
        canvas=iface.mapCanvas(),
        bar=iface.messageBar(),
    )
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def _bar(bar: Any) -> list[str]:
    return [item.text() for item in bar.items()]


def _draw(d, *points, finish=True):
    tool = d.canvas.mapTool()
    assert isinstance(tool, CutTool)
    for p in points:
        send_map_mouse(tool, "release", p)
    if finish:
        send_map_key(tool, Qt.Key.Key_Return)


def test_the_cut_toggle_follows_the_site_and_makes_the_cuts_layer_current(
    real_iface, tmp_path, answer_modal
):
    import nsgeo_qgis

    iface = real_iface(UTM16, QgsRectangle(0, 0, 800, 600))
    plugin = nsgeo_qgis.classFactory(iface)
    plugin.initGui()
    try:
        assert not plugin.act_cut.isEnabled()  # no site

        plugin.session.new_site(tmp_path)
        plugin.session.add_grid(GRID_A)
        assert plugin.act_cut.isEnabled()  # a site, not a line

        plugin.act_cut.setChecked(True)
        plugin.act_cut.triggered.emit(True)
        tool = iface.mapCanvas().mapTool()
        assert isinstance(tool, CutTool)
        assert iface.activeLayer() is plugin.layers.layers["cuts"]
        assert plugin.map_link.cut_mode
        assert CUT_HINT_TEXT in _bar(iface.messageBar())

        plugin.act_cut.setChecked(False)
        plugin.act_cut.triggered.emit(False)
        assert iface.mapCanvas().mapTool() is None
        assert CUT_HINT_TEXT not in _bar(iface.messageBar())
    finally:
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.unload()


def test_drawing_a_cut_adds_marks_unsaved_refills_and_opens_it(drawing):
    d = drawing
    d.session.save()
    assert not d.session.dirty
    d.plugin.act_cut.trigger()
    assert d.plugin.act_cut.isChecked()

    _draw(d, (310, 210), (340, 240))

    keys = d.session.cut_keys()
    assert len(keys) == 1
    assert d.session.dirty
    assert d.plugin.layers.layers["cuts"].featureCount() == 1
    assert d.session.current_key == keys[0]
    assert isinstance(d.canvas.mapTool(), CutTool)
    vertices = d.session.cut_for_key(keys[0]).vertices
    assert np.asarray(vertices) == pytest.approx(np.array([[10.0, 10.0], [40.0, 40.0]]))


def test_a_first_click_outside_every_grid_is_refused(drawing):
    d = drawing
    d.plugin.act_cut.trigger()

    _draw(d, (50, 50), (340, 240))

    assert OUTSIDE_TEXT in _bar(d.bar)
    assert d.session.cut_keys() == []


def test_one_point_or_two_on_the_same_spot_is_refused(drawing):
    d = drawing
    d.plugin.act_cut.trigger()

    _draw(d, (310, 210))
    assert TOO_FEW_TEXT in _bar(d.bar)
    d.bar.clearWidgets()

    _draw(d, (310, 210), (310, 210))
    assert TOO_FEW_TEXT in _bar(d.bar)
    assert d.session.cut_keys() == []


def test_a_first_click_inside_two_grids_takes_the_first_in_survey_order(drawing):
    d = drawing
    d.plugin.act_cut.trigger()

    _draw(d, (370, 270), (380, 290))  # inside A and B

    (key,) = d.session.cut_keys()
    assert d.session.cut_for_key(key).grid_id == "A"
    assert d.session.cut_for_key(key).vertices == (
        pytest.approx((70.0, 70.0)),
        pytest.approx((80.0, 90.0)),
    )


def test_a_cut_drawn_on_a_geographic_canvas_lands_in_grid_metres(
    real_iface, tmp_path, answer_modal
):
    import nsgeo_qgis

    grid = Grid("G", (518204.0, 4649000.0), 10.0, 100.0, 80.0, "EPSG:32616", 0.5)
    to_geo = QgsCoordinateTransform(UTM16, WGS84, QgsProject.instance())
    centre = to_geo.transform(QgsPointXY(518254.0, 4649040.0))
    iface = real_iface(
        WGS84,
        QgsRectangle(
            centre.x() - 0.004, centre.y() - 0.003, centre.x() + 0.004, centre.y() + 0.003
        ),
    )
    plugin = nsgeo_qgis.classFactory(iface)
    plugin.initGui()
    try:
        plugin.session.new_site(tmp_path)
        plugin.session.add_grid(grid)
        local = np.array([[10.0, 5.0], [40.0, 30.0], [70.0, 20.0]])
        world = grid.to_world(local)
        points = [to_geo.transform(QgsPointXY(float(x), float(y))) for x, y in world]

        plugin._on_cut_drawn(points)

        (key,) = plugin.session.cut_keys()
        got = np.asarray(plugin.session.cut_for_key(key).vertices)
        assert np.abs(got - local).max() < 1e-6
    finally:
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.unload()


def test_another_map_tool_unchecks_cut(drawing):
    d = drawing
    d.plugin.act_cut.trigger()
    assert d.plugin.act_cut.isChecked()

    pan = QgsMapToolPan(d.canvas)
    d.canvas.setMapTool(pan)

    assert not d.plugin.act_cut.isChecked()
    assert d.plugin._cut_tool is None
    assert CUT_HINT_TEXT not in _bar(d.bar)
    d.canvas.unsetMapTool(pan)


def test_the_first_point_alone_chooses_the_grid(drawing, monkeypatch):
    # A later point that will not transform must not make the plugin skip the
    # grid the first click is in and take another, or none: it says why.
    from nsgeo_qgis import plugin as plugin_module

    d = drawing
    real = plugin_module.crs_transform

    def pick(canvas_crs, grid_crs, project):
        transform = real(canvas_crs, grid_crs, project)
        assert transform is None  # same CRS here; the failure is simulated below
        return SimpleNamespace(
            transform=lambda p: (_ for _ in ()).throw(QgsCsException()) if p.x() > 500 else p
        )

    monkeypatch.setattr(plugin_module, "crs_transform", pick)
    d.plugin.act_cut.trigger()

    _draw(d, (310, 210), (600, 240))

    assert d.session.cut_keys() == []
    assert any("cannot be placed" in text for text in _bar(d.bar))
