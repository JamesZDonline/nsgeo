"""The Mag panel and the layer it draws: `Mag (live preview)`."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.mag import MagFile, MagSetup
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SURVEY_FILE, SiteSession
from nsgeo_qgis.slice_layer import MAG_LAYER_NAME, SliceLayer
from nsgeo_qgis.slices_plan import SliceFinish
from nsgeo_qgis.ui.mag_dock import MagDock, draw_mag_layer
from plugin_testing import synthetic_grad601
from qgis.core import QgsProject, QgsRectangle
from qgis.PyQt.QtCore import QCoreApplication

REAL_MAG = Path(__file__).resolve().parents[3] / "nsgeo-core/tests/data/local/mag-data/example1.dat"


def _tick(dock):
    """Let the 120 ms debounce through."""
    dock._debounce.stop()
    dock._on_debounce()
    QCoreApplication.processEvents()


class World:
    def __init__(self, session):
        self.session = session
        self.project = QgsProject.instance()
        self.layers = SiteLayers(session, project=self.project)
        session.site_opened.emit()  # builds the site's layer group for the already-open site
        self.layer = SliceLayer(self.layers)
        self.dock = MagDock(session)
        self.dock.map_changed.connect(lambda: draw_mag_layer(self.dock, self.layer))
        self.layer.own_style_changed.connect(self.dock.set_own_style)
        self.errors = []
        self.dock.error.connect(self.errors.append)
        self.dock.show()
        QCoreApplication.processEvents()

    def drawn(self):
        return self.project.mapLayersByName(MAG_LAYER_NAME)

    def extent(self):
        return self.layer.layer.extent()

    def close(self):
        self.dock.hide()
        self.dock.deleteLater()
        self.layer.dispose()
        self.layers.detach()
        self.project.clear()


@pytest.fixture
def world(mag_site):
    session, _ = mag_site
    QgsProject.instance().clear()
    w = World(session)
    yield w
    w.close()


def test_this_grid_draws_the_chosen_grid_on_the_mag_layer(world):
    dock = world.dock
    assert dock.scope() == "grid"
    dock.show_grid("M1")
    assert world.layer.layer.name() == MAG_LAYER_NAME == "Mag (live preview)"
    assert world.extent().contains(QgsRectangle(100.0, 100.0, 104.0, 104.0))
    assert world.layer.layer.extent().width() < 8.0
    group = world.layers.group
    assert group.findLayer(world.layer.layer.id()) is not None
    assert world.layer.layer.customProperty("nsgeo/window") == "M1 · m1.dat"
    assert dock.subtitle() == "M1 · m1.dat"


def test_whole_site_draws_every_mag_grid_holding_a_file_and_no_gpr_grid(world, mag_site):
    session, root = mag_site
    session.set_mag_file(
        MagFile.open(synthetic_grad601(root / "raw" / "mag", "m2.dat"), "M2", MagSetup())
    )
    dock = world.dock
    assert [dock.grid_combo.itemText(i) for i in range(dock.grid_combo.count())] == ["M1", "M2"]
    dock.set_scope("site")
    assert dock.current_map().grids == ("M1", "M2")
    extent = world.extent()
    assert extent.contains(QgsRectangle(100.0, 100.0, 108.0, 104.0))
    assert extent.xMaximum() < 120.0  # the GPR grid at (500, 700) is nowhere in it
    assert dock.subtitle() == "2 mag grids"


def test_the_default_colours_centre_on_the_median(world):
    dock = world.dock
    dock.show_grid("M1")
    assert dock.palette() == "grey_black_high"
    mosaic = dock.current_map()
    finite = mosaic.array[np.isfinite(mosaic.array)]
    renderer = world.layer.layer.renderer()
    centre = float(np.median(finite))
    assert mosaic.centre() == pytest.approx(centre)
    assert renderer.classificationMin() == pytest.approx(centre - mosaic.limit())
    assert renderer.classificationMax() == pytest.approx(centre + mosaic.limit())


def test_own_colours_are_kept_in_the_mag_scope(world):
    dock, session = world.dock, world.session
    dock.show_grid("M1")
    assert not dock.own_colours_on()
    dock.colours_combo.setCurrentIndex(1)
    assert dock.own_colours_on()
    assert session.slice_colours("mag")["own"] is True
    assert session.slice_colours("grid") == {} and session.slice_colours("site") == {}
    style = dock.own_style()
    assert isinstance(style, str) and style  # seeded from the palette and reported
    assert dock.symbology_button.isEnabled()
    dock.set_scope("site")
    assert dock.own_colours_on()  # one scope serves both buttons (P9)
    dock.set_own_style("<qgis/>")
    assert session.slice_colours("mag")["style"] == "<qgis/>"
    dock.colours_combo.setCurrentIndex(0)
    assert not dock.own_colours_on()
    assert not dock.symbology_button.isEnabled()


def test_cell_and_finish_changes_redraw_and_are_remembered(world, mag_site):
    session, root = mag_site
    dock = world.dock
    dock.show_grid("M1")
    drawn = []
    dock.map_changed.connect(lambda: drawn.append(1))
    before = dock.current_map().array.shape
    dock.cell_spin.setValue(0.25)
    assert drawn == []  # debounced
    _tick(dock)
    assert len(drawn) == 1
    assert dock.settings().cell == 0.25
    assert dock.current_map().array.shape != before
    dock.finish_panel.method_combo.setCurrentIndex(dock.finish_panel.method_combo.findData("none"))
    dock.finish_panel.smooth_x_spin.setValue(0.1)
    _tick(dock)
    assert dock.settings().finish.method == "none"
    dock.set_scope("site")
    assert dock.palette() == "grey_black_high"
    index = dock.palette_combo.findText("seismic")
    dock.palette_combo.setCurrentIndex(index)
    view = session.mag_view()
    assert view["cell"] == 0.25 and view["scope"] == "site" and view["palette"] == "seismic"
    assert view["finish"]["method"] == "none" and view["finish"]["smooth_x_m"] == pytest.approx(0.1)
    session.save()
    world.close()
    session.close_site()
    session.open_site(root / SURVEY_FILE)
    QgsProject.instance().clear()
    again = World(session)
    try:
        assert again.dock.scope() == "site"
        assert again.dock.settings().cell == 0.25
        assert again.dock.settings().finish == SliceFinish("none", 0.75, 0.1, 0.0)
        assert again.dock.palette() == "seismic"
        assert again.dock.cell_spin.value() == 0.25
    finally:
        again.close()
        # `world`'s own teardown runs on an already-closed world: harmless.


def test_editing_a_mag_grid_moves_its_map(world):
    dock, session = world.dock, world.session
    dock.show_grid("M1")
    x0 = world.extent().xMinimum()
    old = session.grid("M1")
    session.replace_grid(dataclasses.replace(old, origin=(old.origin[0] + 10.0, old.origin[1])))
    assert world.extent().xMinimum() == pytest.approx(x0 + 10.0)


def test_an_empty_mag_grid_draws_nothing_and_says_why(world, mag_site):
    session, root = mag_site
    dock = world.dock
    dock.show_grid("M1")
    assert world.drawn()
    dock.show_grid("M2")
    assert dock.status() == "Grid M2 has no magnetometer file yet."
    assert dock.current_map() is None
    assert world.drawn() == []
    assert world.errors == []
    # A site with no mag at all.
    session.remove_mag_file(session.mag_key(session.mag_file_on("M1")))
    dock.refresh()
    assert dock.status() == "Grid M2 has no magnetometer file yet."
    for grid in session.mag_grids():
        session.remove_grid(grid.id)
    assert dock.status() == "Import a magnetometer file to see it here."
    assert world.drawn() == [] and world.errors == []
    dock.set_scope("site")
    assert dock.status() == "Import a magnetometer file to see it here."
    assert world.drawn() == []


def test_a_grid_in_another_crs_is_left_out_and_named(world, mag_site):
    session, root = mag_site
    session.add_grid(Grid("M3", (200.0, 100.0), 0.0, 4.0, 4.0, "EPSG:32617", 0.5, instrument="mag"))
    session.set_mag_file(
        MagFile.open(synthetic_grad601(root / "raw" / "mag", "m3.dat"), "M3", MagSetup())
    )
    dock = world.dock
    dock.set_scope("site")
    assert dock.current_map().grids == ("M1",)
    assert dock.status() == "Left out of the whole site, being in another CRS: M3."
    assert world.drawn()


def test_the_panel_never_lists_a_gpr_grid(world):
    dock = world.dock
    ids = [dock.grid_combo.itemText(i) for i in range(dock.grid_combo.count())]
    assert "G1" not in ids and ids == ["M1", "M2"]
    assert dock.windowTitle() == "nsgeo Mag" and dock.objectName() == "nsgeoMagDock"
    assert (dock.grid_scope_button.text(), dock.site_scope_button.text()) == (
        "This grid",
        "Whole site",
    )


def test_it_draws_only_while_visible_and_clearing_on_close_site(world):
    dock, session = world.dock, world.session
    dock.show_grid("M1")
    assert world.drawn()
    dock.hide()
    calls = []
    dock.map_changed.connect(lambda: calls.append(1))
    dock.show_grid("M2")  # hidden: nothing is recomputed
    assert calls == [] and world.drawn()
    dock.show()  # showing redraws
    assert calls and world.drawn() == []
    dock.show_grid("M1")
    assert world.drawn()
    session.close_site()
    assert world.drawn() == []


def test_a_mag_only_view_is_not_written_to_a_gpr_only_site(qgis_app, tmp_path):
    """A site that never had mag saves without a `mag_view` key, shown or not."""
    root = tmp_path / "gpr_only"
    root.mkdir()
    session = SiteSession()
    session.new_site(root)
    session.add_grid(Grid("G1", (500.0, 700.0), 0.0, 20.0, 20.0, "EPSG:32616", 1.0))
    session.save()
    QgsProject.instance().clear()
    w = World(session)
    try:
        w.dock.show()
        w.dock.cell_spin.setValue(0.25)
        w.dock.palette_combo.setCurrentIndex(1)
        w.dock.set_scope("site")
        _tick(w.dock)
        assert w.dock.status() == "Import a magnetometer file to see it here."
        session.save()
        text = (root / SURVEY_FILE).read_text()
        assert "mag_view" not in text and not [k for k in json.loads(text) if k.startswith("mag")]
    finally:
        w.close()


@pytest.mark.skipif(not REAL_MAG.exists(), reason="no real mag files in tests/data/local")
def test_a_real_grid_draws(qgis_app, tmp_path):
    root = tmp_path / "real"
    root.mkdir()
    session = SiteSession()
    session.new_site(root)
    session.add_grid(
        Grid("R1", (400000.0, 4500000.0), 0.0, 30.0, 30.0, "EPSG:32616", 0.5, instrument="mag")
    )
    session.set_mag_file(MagFile.open(REAL_MAG.resolve(), "R1", MagSetup()))
    QgsProject.instance().clear()
    w = World(session)
    try:
        w.dock.show_grid("R1")
        mosaic = w.dock.current_map()
        assert mosaic is not None and mosaic.grids == ("R1",)
        assert np.isfinite(mosaic.array).mean() > 0.8
        assert w.drawn() and w.errors == []
    finally:
        w.close()
