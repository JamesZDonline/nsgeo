"""Import GPS lines: the dialog and its toolbar action (M17a Task 4, P10, P11)."""

from __future__ import annotations

import pytest
from nsgeo.geometry import Grid, GridPlacement, TrackPlacement
from nsgeo.processing import build_step
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.add_data_dialog import GPS, AddDataDialog
from nsgeo_qgis.ui.add_data_dialog import GRID as MODE_GRID
from nsgeo_qgis.ui.gps_import_dialog import (
    COL_ENDS,
    COL_GAP,
    COL_STATUS,
    HEADERS,
)
from nsgeo_qgis.ui.preset_box import PRESET_GONE
from plugin_testing import synthetic_dzt, synthetic_gps_dzt
from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtWidgets import QFormLayout, QMessageBox
from tests.real_data import GPS_LINES

LAT0, LON0 = 45.2, 10.5
M_PER_DEG = 6_371_000.0 * 3.141592653589793 / 180.0


def fix(trace: int, quality: int = 4, lon: float = LON0) -> tuple[int, float, float, int]:
    """A fix on a line walked due north at 0.1 m a trace."""
    return (trace, LAT0 + trace * 0.1 / M_PER_DEG, lon, quality)


def gps_file(folder, name, qualities=None, lon=LON0):
    """A 200-trace line at 10 traces a metre with fixes at 25, 75, 125, 175."""
    q = {25: 4, 75: 4, 125: 4, 175: 4, **(qualities or {})}
    return synthetic_gps_dzt(
        folder, name, [fix(t, q[t], lon) for t in sorted(q)], traces_per_metre=10.0
    )


def gps_dialog(session):
    """An Add data dialog on its GPS page."""
    return AddDataDialog(session, mode=GPS)


def grid_dialog(session, grid_id="A"):
    """An Add data dialog on its Grid page."""
    return AddDataDialog(session, grid_id=grid_id, mode=MODE_GRID)


def set_project_crs(authid):
    project = QgsProject.instance()
    old = project.crs()
    project.setCrs(QgsCoordinateReferenceSystem(authid))
    return lambda: project.setCrs(old)


@pytest.fixture
def project_utm(qgis_app):
    restore = set_project_crs("EPSG:32632")
    yield
    restore()


@pytest.fixture
def project_degrees(qgis_app):
    restore = set_project_crs("EPSG:4326")
    yield
    restore()


@pytest.fixture
def session(qgis_app, tmp_path, project_utm):
    s = SiteSession()
    (tmp_path / "site").mkdir()
    s.new_site(tmp_path / "site")
    return s


@pytest.fixture(autouse=True)
def _flush_deferred_deletes(qgis_app):
    """See test_plugin_import_dialog.py's fixture of the same name."""
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


def cells(d, row):
    return [d.table.item(row, c).text() for c in range(d.table.columnCount())]


# ---- the table ---------------------------------------------------------------


def test_adding_files_plans_rows_and_shows_the_coordinates(session, tmp_path):
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    assert d_dlg.windowTitle() == "Add GPR data"
    assert [d.table.horizontalHeaderItem(c).text() for c in range(6)] == HEADERS
    assert HEADERS == ["File", "Traces", "RTK fixes", "Without RTK", "Ends", "Status"]
    assert d.status.text() == "Add DZT files that have a DZG beside them."
    assert not d_dlg.import_button.isEnabled()

    raw = tmp_path / "raw"
    bridged = gps_file(raw, "FILE__002.DZT", {75: 5})
    clean = gps_file(raw, "FILE__001.DZT")
    bare = synthetic_dzt(raw, "FILE__003.DZT", n_traces=60)
    d.add_files([bridged, clean, bare])

    assert d.table.rowCount() == 3
    # sorted like the tape import: by trailing number
    assert cells(d, 0) == ["FILE__001.DZT", "200", "4 of 4", "—", "2.50 / 2.40 m", "ready"]
    assert cells(d, 1) == ["FILE__002.DZT", "200", "3 of 4", "10.0 m", "2.50 / 2.40 m", "ready"]
    assert cells(d, 2) == ["FILE__003.DZT", "60", "—", "—", "—", "no DZG beside it"]
    assert d.status.text() == "2 of 3 file(s) ready to import."
    assert d_dlg.import_button.text() == "Import" and d_dlg.import_button.isEnabled()
    assert d.crs_label.text() == "EPSG:32632"
    assert d.note_label.text() == ""
    d_dlg.reject()


def test_the_destagger_box_and_buttons_follow_the_copy(session):
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    assert (d.shift.minimum(), d.shift.maximum()) == (-2.0, 2.0)
    assert d.shift.singleStep() == 0.01 and d.shift.decimals() == 2 and d.shift.value() == 0.0
    assert d.shift.toolTip() == (
        "Moves every trace forward along the way its line was walked, for every line in "
        "this import. Change it per line later from the Survey panel."
    )
    assert d.add_button.text() == "Add files…" and d.remove_button.text() == "Remove"
    d_dlg.reject()


def test_a_geographic_project_picks_the_utm_zone_and_says_why(
    qgis_app, tmp_path, session, project_degrees
):
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    assert d.crs_label.text() == "EPSG:32632"
    assert d.note_label.text().startswith("picked for you:")
    placement = d.rows[0].line.placement
    assert placement.crs == "EPSG:32632"
    d_dlg.reject()


def test_remove_drops_the_selected_rows_and_replans(session, tmp_path):
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    raw = tmp_path / "raw"
    d.add_files([gps_file(raw, f"FILE__00{i}.DZT") for i in (1, 2, 3)])
    d.add_files([raw / "FILE__002.DZT"])  # already there
    assert d.table.rowCount() == 3
    d.table.selectRow(1)
    d.remove_selected()
    assert [r.path.name for r in d.rows] == ["FILE__001.DZT", "FILE__003.DZT"]
    assert d.status.text() == "2 of 2 file(s) ready to import."
    d.table.selectAll()
    d.remove_selected()
    assert d.table.rowCount() == 0
    assert d.status.text() == "Add DZT files that have a DZG beside them."
    assert not d_dlg.import_button.isEnabled()
    d_dlg.reject()


def test_a_file_already_in_the_site_shows_how_to_switch(session, tmp_path):
    from nsgeo.model import Line

    raw = tmp_path / "raw"
    taken = gps_file(raw, "FILE__001.DZT")
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32632", 0.5))
    session.add_lines(
        [Line.open(taken, GridPlacement(grid_id="A", axis="y", offset=0.5, start_along=0.0))]
    )
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files([taken])
    # planned, then refused: the row keeps its counts and ends
    assert cells(d, 0) == [
        "FILE__001.DZT",
        "200",
        "4 of 4",
        "—",
        "2.50 / 2.40 m",
        "already in the site",
    ]
    d_dlg.reject()


def test_a_site_crs_that_cannot_place_a_file_refuses_that_row(qgis_app, session, tmp_path):
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])  # zone 32 is far from zone 16
    assert d.crs_label.text() == "EPSG:32616"
    assert cells(d, 0)[COL_STATUS] == "outside what EPSG:32616 can place"
    assert d.status.text() == "0 of 1 file(s) ready to import."
    assert not d_dlg.import_button.isEnabled()
    d_dlg.accept()
    assert d.status.text() == "Nothing to import: no file is ready."
    assert session.site.lines == [] and session.site_crs() == "EPSG:32616"
    d_dlg.reject()


# ---- the cues, the opening state and the Import details --------------------------

AMBER = ("#fbf3df", "#8a5a00")
RED = ("#fbe9e7", "#a12a1e")


def colours(d, row, col):
    item = d.table.item(row, col)
    return item.background().color().name(), item.foreground().color().name()


def plain(d, row, col):
    return d.table.item(row, col).background().style() == Qt.BrushStyle.NoBrush


def test_the_cells_worth_a_look_are_amber_and_refused_statuses_red(session, tmp_path):
    raw = tmp_path / "raw"
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files(
        [
            gps_file(raw, "FILE__001.DZT"),  # 2.5 / 2.4 m: both ends over the limit
            gps_file(raw, "FILE__002.DZT", {75: 5}),  # a bridge
            synthetic_gps_dzt(  # 1.5 / 1.4 m, no bridge: nothing to flag
                raw, "FILE__003.DZT", [fix(15), fix(185)], traces_per_metre=10.0
            ),
            synthetic_dzt(raw, "FILE__004.DZT", n_traces=60),  # refused
        ]
    )
    assert colours(d, 0, COL_ENDS) == AMBER and plain(d, 0, COL_GAP)
    assert colours(d, 1, COL_GAP) == AMBER and colours(d, 1, COL_ENDS) == AMBER
    assert plain(d, 2, COL_GAP) and plain(d, 2, COL_ENDS) and plain(d, 2, COL_STATUS)
    assert colours(d, 3, COL_STATUS) == RED and plain(d, 3, COL_GAP)
    assert plain(d, 0, COL_STATUS)
    d_dlg.reject()


def test_the_coordinates_show_the_sites_crs_before_any_file_is_added(qgis_app, session):
    session.add_grid(Grid("A", (500_000.0, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32616", 0.5))
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    assert d.crs_label.text() == "EPSG:32616"
    d_dlg.reject()


def test_the_page_keeps_its_status_and_the_dialog_owns_the_buttons(session):
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    assert d.status.parent() is d and d.status.isVisibleTo(d_dlg)
    assert d_dlg.import_button.text() == d.import_text() == "Import"
    d_dlg.reject()


def test_lonlat_to_xy_keeps_nan_and_survives_a_point_the_transform_refuses(qgis_app, monkeypatch):
    import numpy as np
    from nsgeo_qgis.ui import gps_import_dialog as mod
    from qgis.core import QgsCsException, QgsPointXY

    class Refuses:
        def __init__(self, *_a):
            pass

        def transform(self, p):
            if p.x() > 100:
                raise QgsCsException("outside")
            return QgsPointXY(p.x() * 2, p.y() * 3)

    monkeypatch.setattr(mod, "QgsCoordinateTransform", Refuses)
    to_xy = mod.lonlat_to_xy(QgsCoordinateReferenceSystem("EPSG:32632"))
    xs, ys = to_xy(np.array([1.0, np.nan, 150.0, 2.0]), np.array([1.0, 1.0, 1.0, np.nan]))
    assert xs[0] == 2.0 and ys[0] == 3.0
    assert np.isnan(xs[1:]).all() and np.isnan(ys[1:]).all()


def test_import_uses_the_planned_lines_even_if_a_file_became_unreadable(plugin, tmp_path):
    raw = tmp_path / "raw"
    path = gps_file(raw, "FILE__001.DZT")
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    dialog.add_files([path])
    path.write_bytes(b"gone")  # unreadable now; planning already read it
    dialog.accept()
    assert [ln.path.name for ln in plugin.session.site.lines] == ["FILE__001.DZT"]
    assert plugin.session.site_crs() == "EPSG:32632"


def test_the_messages_after_the_count_are_warnings(plugin, tmp_path):
    from qgis.core import Qgis

    shown: list = []
    plugin.message = lambda text, level=None, title="nsgeo": shown.append((text, level))  # type: ignore[method-assign]
    raw = tmp_path / "raw"
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    dialog.add_files([gps_file(raw, "FILE__001.DZT", {75: 5}), synthetic_dzt(raw, "FILE__002.DZT")])
    dialog.accept()
    assert len(shown) >= 3
    assert shown[0][1] == Qgis.MessageLevel.Info
    assert all(level == Qgis.MessageLevel.Warning for _, level in shown[1:])


# ---- Import ------------------------------------------------------------------


def test_import_adds_gps_lines_sets_the_site_crs_and_applies_the_shift(plugin, tmp_path):
    shown: list[str] = []
    plugin.message = lambda text, level=None, title="nsgeo": shown.append(text)  # type: ignore[method-assign]
    raw = tmp_path / "raw"
    a = gps_file(raw, "FILE__001.DZT", {75: 5})
    b = gps_file(raw, "FILE__002.DZT")
    assert plugin.session.site_crs() is None

    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    assert dialog is not None
    dialog.add_files([a, b])
    dialog.gps_page.shift.setValue(0.24)
    dialog.accept()

    lines = plugin.session.site.lines
    assert [ln.path.name for ln in lines] == ["FILE__001.DZT", "FILE__002.DZT"]
    assert all(isinstance(ln.placement, TrackPlacement) for ln in lines)
    assert [ln.placement.travel_shift for ln in lines] == [0.24, 0.24]
    assert plugin.session.site_crs() == "EPSG:32632"
    assert plugin.session.site.crs == "EPSG:32632"
    assert shown == [
        "imported 2 GPS line(s)",
        "FILE__001.DZT: 10.0 m without an RTK fix, traces 25–125",
        "FILE__001.DZT: its start runs 2.5 m before the first RTK fix",
        "FILE__001.DZT: its end runs 2.4 m past the last RTK fix",
        "FILE__002.DZT: its start runs 2.5 m before the first RTK fix",
        "FILE__002.DZT: its end runs 2.4 m past the last RTK fix",
    ]
    assert plugin._add_data_dialog is None  # finished() ran


def test_import_reports_refused_files_last(plugin, tmp_path):
    shown: list[str] = []
    plugin.message = lambda text, level=None, title="nsgeo": shown.append(text)  # type: ignore[method-assign]
    raw = tmp_path / "raw"
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    dialog.add_files([gps_file(raw, "FILE__001.DZT"), synthetic_dzt(raw, "FILE__002.DZT")])
    dialog.accept()
    assert len(plugin.session.site.lines) == 1
    assert shown[0] == "imported 1 GPS line(s)"
    assert shown[-1] == "not imported: FILE__002.DZT (no DZG beside it)"


def test_an_import_into_a_site_with_grids_uses_their_crs(plugin, tmp_path, project_degrees):
    plugin.session.add_grid(Grid("A", (500_000.0, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32632", 0.5))
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    dialog.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    assert dialog.gps_page.crs_label.text() == "EPSG:32632"
    assert dialog.gps_page.note_label.text() == "picked for you: the CRS the site's other grids use"
    dialog.accept()
    (line,) = plugin.session.site.lines
    assert line.placement.crs == "EPSG:32632"
    assert plugin.session.site.crs == "EPSG:32632"  # pinned by the first GPS line


def test_import_after_the_site_was_replaced_adds_nothing(plugin, tmp_path):
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    dialog.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    other = tmp_path / "other"
    other.mkdir()
    plugin.session.close_site()
    plugin.session.new_site(other)
    dialog.accept()
    assert dialog.gps_page.status.text() == "The site changed; nothing was imported."
    assert plugin.session.site.lines == [] and plugin.session.site_crs() is None
    assert plugin._add_data_dialog is dialog  # still open
    dialog.reject()


def test_import_after_the_site_was_closed_adds_nothing(plugin, tmp_path):
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    dialog.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    plugin.session.close_site()
    dialog.accept()
    assert dialog.gps_page.status.text() == "The site changed; nothing was imported."
    dialog.reject()


def test_a_site_crs_that_appeared_while_the_dialog_was_open_replans_instead_of_importing(
    plugin, tmp_path, project_degrees
):
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    dialog.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    assert dialog.gps_page.crs_label.text() == "EPSG:32632"
    plugin.session.add_grid(Grid("A", (500_000.0, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32633", 0.5))
    dialog.accept()
    assert plugin.session.site.lines == []
    assert dialog.gps_page.crs_label.text() == "EPSG:32633"
    assert "EPSG:32633" in dialog.gps_page.status.text()
    dialog.reject()


def test_a_file_already_in_the_site_cannot_be_imported_twice(plugin, tmp_path):
    raw = tmp_path / "raw"
    path = gps_file(raw, "FILE__001.DZT")
    plugin.open_add_data_dialog(None, GPS)
    first = plugin._add_data_dialog
    first.add_files([path])
    first.accept()
    plugin.open_add_data_dialog(None, GPS)
    second = plugin._add_data_dialog
    second.add_files([path])
    assert cells(second.gps_page, 0)[COL_STATUS].startswith("already in the site")
    second.reject()


# ---- the plugin --------------------------------------------------------------


def test_the_gps_import_dialog_is_single_instance_and_closes_on_unload(plugin):
    plugin.open_add_data_dialog(None, GPS)
    first = plugin._add_data_dialog
    plugin.open_add_data_dialog(None, GPS)
    assert plugin._add_data_dialog is first
    plugin.unload()
    assert plugin._add_data_dialog is None


def test_the_tape_import_still_places_by_the_tapes_beside_a_dzg(session, tmp_path):
    session.add_grid(Grid("A", (500_000.0, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32632", 0.5))
    path = gps_file(tmp_path / "raw", "FILE__001.DZT")
    assert path.with_suffix(".DZG").exists()
    d_dlg = grid_dialog(session, grid_id="A")
    d = d_dlg.grid_page
    d.add_files([path])
    d_dlg.accept()
    (line,) = session.site.lines
    assert isinstance(line.placement, GridPlacement)
    assert not isinstance(line.placement, TrackPlacement)


# ---- real data ---------------------------------------------------------------


@pytest.mark.skipif(not GPS_LINES, reason="no GPS-recorded DZT files in tests/data/local")
def test_importing_the_first_gps_survey(plugin, project_degrees):
    shown: list[str] = []
    plugin.message = lambda text, level=None, title="nsgeo": shown.append(text)  # type: ignore[method-assign]
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    dialog.add_files(list(GPS_LINES))
    assert [r.refusal for r in dialog.gps_page.rows] == [None] * len(GPS_LINES)
    dialog.accept()

    lines = plugin.session.site.lines
    assert len(lines) == len(GPS_LINES) == 60
    assert plugin.session.site_crs() == dialog.gps_page._crs.authid()
    walked = {ln.path.name: float(ln.distance_along()[-1]) for ln in lines}
    assert 29.5 <= walked["FILE__011.DZT"] <= 31.0
    assert shown[0] == "imported 60 GPS line(s)"
    assert not any("without an RTK fix" in m for m in shown)


# ---- #129: the Processing preset box -------------------------------------------------


def _preset_from_a_line(session, tmp_path, name):
    """Save `name` (a dewow) from a tape line on a side grid."""
    from nsgeo.model.survey import Line

    session.add_grid(Grid("S", (900.0, 700.0), 0.0, 5.0, 11.0, "EPSG:32632", 0.5))
    p = synthetic_dzt(tmp_path / "side", "SIDE__001.DZT", n_traces=60)
    line = Line.open(p, GridPlacement("S", "y", 0.0, 0.0, 1, p.stem))
    session.add_lines([line])
    key = session.line_key(line)
    session.append_step(key, build_step("dewow", window_ns=12.0))
    session.save_preset(name, key)


def test_the_preset_box_sits_under_the_destagger_row(session):
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    form = d.findChildren(QFormLayout)[0]
    labels = [form.itemAt(r, QFormLayout.ItemRole.LabelRole).widget().text() for r in range(3)]
    assert labels == ["Destagger (m)", "Processing preset", "Coordinates:"]
    assert form.itemAt(1, QFormLayout.ItemRole.FieldRole).widget() is d.preset_box


def test_gps_import_with_a_preset_changes_only_the_new_lines_and_remembers_the_sites_choice(
    session, tmp_path
):
    _preset_from_a_line(session, tmp_path, "Plain")
    first_dlg = gps_dialog(session)
    first = first_dlg.gps_page
    first.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    first_dlg.accept()
    before = session.stack_for(first.imported_keys[0]).to_dicts()
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files([gps_file(tmp_path / "raw", "FILE__002.DZT", lon=LON0 + 0.00002)])
    d.preset_box.combo.setCurrentIndex(d.preset_box.combo.findData("Plain"))
    d_dlg.accept()
    assert session.stack_for(first.imported_keys[0]).to_dicts() == before
    assert session.stack_for(d.imported_keys[0]).to_dicts() == session.site.presets["Plain"]
    assert session.site.import_presets == {"site": "Plain"}
    assert "S" not in session.site.slice_sources  # no Slices step in the GPS dialog
    assert gps_dialog(session).gps_page.preset_box.chosen() == "Plain"


def test_a_preset_deleted_under_the_gps_dialog_imports_nothing(session, tmp_path):
    _preset_from_a_line(session, tmp_path, "Plain")
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    d.preset_box.combo.setCurrentIndex(d.preset_box.combo.findData("Plain"))
    d.preset_box._on_presets_changed = lambda *a: None
    del session.site.presets["Plain"]
    d_dlg.accept()
    assert d.status.text() == PRESET_GONE.format(name="Plain")
    assert len(session.keys()) == 1  # only the side line


@pytest.mark.skipif(len(GPS_LINES) < 4, reason="no GPS-recorded DZT files in tests/data/local")
def test_real_gps_lines_import_with_a_preset(plugin, project_degrees):
    session = plugin.session
    first_dlg = gps_dialog(session)
    first = first_dlg.gps_page
    first.add_files(list(GPS_LINES[:2]))
    first_dlg.accept()
    assert len(first.imported_keys) == 2
    for k in first.imported_keys:
        session.append_step(k, build_step("dewow", window_ns=12.0))
    session.save_preset("Plain", first.imported_keys[0])
    kept = {k: session.stack_for(k).to_dicts() for k in first.imported_keys}
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files(list(GPS_LINES[2:4]))
    d.preset_box.combo.setCurrentIndex(d.preset_box.combo.findData("Plain"))
    d_dlg.accept()
    assert len(d.imported_keys) == 2
    for k in d.imported_keys:
        assert session.stack_for(k).to_dicts() == session.site.presets["Plain"]
    for k, dicts in kept.items():
        assert session.stack_for(k).to_dicts() == dicts
    assert session.site.import_presets["site"] == "Plain"


def test_a_preset_that_cannot_be_applied_is_reported_and_the_gps_import_stands(
    session, tmp_path, monkeypatch
):
    _preset_from_a_line(session, tmp_path, "Plain")
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    d.preset_box.combo.setCurrentIndex(d.preset_box.combo.findData("Plain"))

    def boom(*a, **k):
        raise RuntimeError("no disk")

    monkeypatch.setattr(session, "apply_preset_to", boom)
    d_dlg.accept()
    assert d_dlg.result() == d_dlg.DialogCode.Accepted
    assert len(d.imported_keys) == 1
    assert "could not be applied" in d.status.text()
