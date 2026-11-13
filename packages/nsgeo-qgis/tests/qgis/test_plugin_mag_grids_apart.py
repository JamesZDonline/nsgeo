"""The GPR panels never list a magnetometer grid (M19a spec §8 anti-goal)."""

from __future__ import annotations

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.ui import site_scope
from nsgeo_qgis.ui.edit_lines_dialog import EditLinesDialog
from nsgeo_qgis.ui.import_dialog import ImportDialog
from nsgeo_qgis.ui.slices_dock import SlicesDock
from nsgeo_qgis.ui.survey_dock import SurveyDock
from plugin_testing import synthetic_dzt
from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY, QgsRectangle
from qgis.PyQt.QtWidgets import QMenu, QMessageBox


def _combo_items(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def test_the_dzt_import_dialog_lists_only_gpr_grids(mag_site):
    session, _ = mag_site
    d = ImportDialog(session, grid_id="G1")
    try:
        assert _combo_items(d.grid_combo) == ["G1"]
    finally:
        d.deleteLater()


def test_the_slices_panel_lists_only_gpr_grids(mag_site):
    session, _ = mag_site
    dock = SlicesDock(session)
    try:
        assert _combo_items(dock.grid_combo) == ["G1"]
    finally:
        dock.refiner.shutdown()
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.deleteLater()


def test_whole_site_rows_are_only_gpr_grids(mag_site):
    session, _ = mag_site
    assert site_scope.included_grids(session) == ("G1",)
    rows = site_scope.site_rows(session, None, ())
    assert [r.grid_id for r in rows] == ["G1"]
    session.set_site_view(grids=["G1", "M1"])
    assert site_scope.included_grids(session) == ("G1",)


def test_edit_lines_offers_only_gpr_grids(mag_site):
    session, _ = mag_site
    d = EditLinesDialog(session, "G1")
    try:
        assert d._grid_ids == ["G1"]
        assert _combo_items(d.grid_combo) == ["G1"]
    finally:
        d.hide()
        d.deleteLater()


def test_move_to_grid_offers_only_gpr_grids(mag_site):
    session, _ = mag_site
    dock = SurveyDock(session)
    try:
        session.add_grid(Grid("G2", (600.0, 700.0), 0.0, 5.0, 5.0, "EPSG:32616", 1.0))
        menu = QMenu()
        key = session.keys()[0]
        dock._add_move_menu(menu, [key], "Move to grid")
        assert [a.text() for a in dock.move_menu.actions()] == ["G1", "G2"]
    finally:
        dock.deleteLater()


def test_a_cut_cannot_start_on_a_mag_grid(real_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    iface = real_iface(QgsCoordinateReferenceSystem("EPSG:32616"), QgsRectangle(0, 0, 800, 600))
    plugin = nsgeo_qgis.classFactory(iface)
    plugin.initGui()
    try:
        session = plugin.session
        session.new_site(tmp_path)
        session.add_grid(
            Grid("M", (300.0, 200.0), 0.0, 100.0, 100.0, "EPSG:32616", 0.5, instrument="mag")
        )
        click = [QgsPointXY(350.0, 250.0)]
        assert plugin._cut_grid_and_vertices(click) is None
        session.add_grid(Grid("G", (320.0, 220.0), 0.0, 100.0, 100.0, "EPSG:32616", 0.5))
        path = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
        session.add_lines([Line.open(path, GridPlacement("G", "y", 10.0, 0.0, 1, "a"))])
        found = plugin._cut_grid_and_vertices(click)
        assert found is not None and found[0] == "G"
    finally:
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.unload()
