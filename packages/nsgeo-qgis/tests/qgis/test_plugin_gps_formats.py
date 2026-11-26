"""GPS mode places MALÅ and SEG-Y lines (M21d, radar formats spec §16).

Every coordinate here is made up, about the place the other GPS tests use.
"""

from __future__ import annotations

import dataclasses

import pytest
from nsgeo.project import load_site
from nsgeo_qgis.gps_import import gps_file_filter
from nsgeo_qgis.ui.add_data_dialog import GPS, AddDataDialog
from nsgeo_qgis.ui.gps_import_dialog import COL_FIXES, COL_GAP, COL_STATUS, FILE_FILTER
from plugin_testing import synthetic_gps_mala, synthetic_gps_segy
from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.PyQt.QtCore import QEvent
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

LAT0, LON0 = 45.2, 10.5
M_PER_DEG = 6_371_000.0 * 3.141592653589793 / 180.0
GPS_FILTER = (
    "All GPS radar files (*.dzt *.DZT *.rd3 *.RD3 *.rd7 *.RD7 *.sgy *.SGY *.segy *.SEGY);;"
    "GSSI DZT (*.dzt *.DZT);;MALÅ (*.rd3 *.RD3 *.rd7 *.RD7);;"
    "SEG-Y (*.sgy *.SGY *.segy *.SEGY);;All files (*)"
)


def north(trace: int, east_m: float = 0.0) -> tuple[float, float]:
    """(lat, lon) of a line walked due north at 0.1 m a trace, `east_m` across."""
    return LAT0 + trace * 0.1 / M_PER_DEG, LON0 + east_m / (M_PER_DEG * 0.7046)


def cor_rows(east_m: float = 0.0, jitter: float = 0.0):
    """A fix every 20 traces, counted from 1, DGPS, optionally jittering east-west."""
    rows = []
    for i in range(10):
        lat, lon = north(20 * i, east_m + (jitter if i % 2 else -jitter))
        rows.append((1 + 20 * i, lat, lon, 2))
    return rows


def segy_positions(east_m: float = 0.0):
    return [(north(t, east_m)[1], north(t, east_m)[0]) for t in range(200)]


def lines_in(tmp_path):
    raw = tmp_path / "site" / "raw"
    mala = synthetic_gps_mala(raw, "DAT_0001.rd7", cor_rows(), interval=0.1)
    segy = synthetic_gps_segy(raw, "LINE02.sgy", segy_positions(east_m=2.0), x_mm=None)
    return mala, segy


@pytest.fixture
def project_utm(qgis_app):
    project = QgsProject.instance()
    old = project.crs()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:32632"))
    yield
    project.setCrs(old)


@pytest.fixture(autouse=True)
def _flush_deferred_deletes(qgis_app):
    yield
    qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def plugin(fake_iface, tmp_path, answer_modal, project_utm):
    import nsgeo_qgis

    p = nsgeo_qgis.classFactory(fake_iface)
    p.initGui()
    (tmp_path / "site").mkdir()
    p.session.new_site(tmp_path / "site")
    yield p
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    p.unload()


def test_the_gps_picker_lists_every_format_with_a_gps_source(plugin, answer_modal):
    assert FILE_FILTER == gps_file_filter() == GPS_FILTER
    calls = answer_modal(QFileDialog, "getOpenFileNames", ([], ""))
    plugin.open_add_data_dialog(None, GPS)
    plugin._add_data_dialog.gps_page._choose_files()
    (args, _kwargs) = calls[0]
    assert args[1] == "Select radar files" and args[3] == GPS_FILTER
    plugin._add_data_dialog.reject()


def test_mala_and_segy_rows_are_ready_with_their_notes(plugin, tmp_path):
    mala, segy = lines_in(tmp_path)
    plugin.open_add_data_dialog(None, GPS)
    d = plugin._add_data_dialog.gps_page
    d.add_files([mala, segy])
    rows = {d.table.item(r, 0).text(): r for r in range(d.table.rowCount())}
    m, s = rows["DAT_0001.rd7"], rows["LINE02.sgy"]
    assert d.table.item(m, COL_STATUS).text() == (
        "ready · no RTK fix: placed on its 10 GPS fixes as recorded"
    )
    assert d.table.item(m, COL_FIXES).text() == "0 of 10"
    assert d.table.item(m, COL_GAP).text() == "—"
    assert d.table.item(s, COL_STATUS).text().startswith("ready · no RTK fix: placed on its ")
    plugin._add_data_dialog.reject()


def test_the_smooth_box_replans_and_reaches_the_imported_lines(plugin, tmp_path, qgis_app):
    raw = tmp_path / "site" / "raw"
    mala = synthetic_gps_mala(raw, "DAT_0001.rd7", cor_rows(jitter=1.0), interval=0.1)
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    d = dialog.gps_page
    d.add_files([mala])
    d.smooth.setValue(5.0)
    d._smooth_timer.stop()
    d._smooth_settled()  # what the debounce timer does when the value settles
    assert d.table.item(0, COL_STATUS).text() == (
        "ready · no RTK fix: placed on its 10 GPS fixes, smoothed over 5 m"
    )
    d.name_edit.setText("M1")
    d.spacing.setValue(1.0)
    dialog.accept()
    (line,) = plugin.session.site.lines
    assert line.placement.anchor_on == "all" and line.placement.smooth_m == 5.0


def test_mala_and_segy_lines_import_onto_a_new_grid_and_reopen(plugin, tmp_path):
    mala, segy = lines_in(tmp_path)
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    d = dialog.gps_page
    d.add_files([mala, segy])
    d.name_edit.setText("M2")
    d.spacing.setValue(2.0)
    dialog.accept()
    session = plugin.session
    assert sorted(ln.path.name for ln in session.site.lines) == ["DAT_0001.rd7", "LINE02.sgy"]
    assert all(ln.placement.grid_id == "M2" for ln in session.site.lines)
    assert session.site_crs() == "EPSG:32632"
    # The smoothing is a per-line setting that survives a save.
    first = session.site.lines[0]
    session.site.lines[0] = dataclasses.replace(
        first, placement=dataclasses.replace(first.placement, smooth_m=3.0)
    )
    session.save()
    back = load_site(session.json_path)
    smooth = {ln.path.name: ln.placement.smooth_m for ln in back.lines}
    assert smooth[first.path.name] == 3.0


def test_add_datas_gps_note_counts_mala_and_segy_lines(qgis_app, tmp_path):
    from nsgeo.geometry.grid import Grid
    from nsgeo_qgis.session import SiteSession
    from nsgeo_qgis.ui.add_data_dialog import GRID

    session = SiteSession()
    (tmp_path / "site").mkdir()
    session.new_site(tmp_path / "site")
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32632", 0.5))
    mala, segy = lines_in(tmp_path)
    dialog = AddDataDialog(session, grid_id="A", mode=GRID)
    dialog.add_files([mala, segy])
    dialog._update_note()
    assert dialog.gps_note.text() == "2 of 2 files have a GPS log beside them."
    dialog.reject()
