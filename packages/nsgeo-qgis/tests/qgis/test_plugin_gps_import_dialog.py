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


def ready(page, name="G1", spacing=0.5):
    """Name the new grid and type its spacing: what a hand-added test file set needs
    (the synthetic files share one track, so nothing can be measured)."""
    page.name_edit.setText(name)
    page.spacing.setValue(spacing)


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
    assert d_dlg.windowTitle() == "Add GPR data into a new grid"
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
    assert d.status.text() == "Name the new grid."
    assert not d_dlg.import_button.isEnabled()
    assert d_dlg.import_button.text() == "Import 2 line(s) into a new grid"
    ready(d)
    assert d.status.text() == "2 of 3 file(s) ready to import."
    assert d_dlg.windowTitle() == "Add GPR data into new grid G1"
    assert d_dlg.import_button.text() == "Import 2 line(s) into new grid G1"
    assert d_dlg.import_button.isEnabled()
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
    ready(d)
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
    ready(d)
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
    assert d_dlg.import_button.text() == d.import_text() == "Import 0 line(s) into a new grid"
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
    ready(dialog.gps_page)
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
    ready(dialog.gps_page)
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
    ready(dialog.gps_page)
    dialog.gps_page.shift.setValue(0.24)
    dialog.accept()

    lines = plugin.session.site.lines
    assert [ln.path.name for ln in lines] == ["FILE__001.DZT", "FILE__002.DZT"]
    assert all(isinstance(ln.placement, TrackPlacement) for ln in lines)
    assert [ln.placement.travel_shift for ln in lines] == [0.24, 0.24]
    assert plugin.session.site_crs() == "EPSG:32632"
    assert plugin.session.site.crs == "EPSG:32632"
    assert shown == [
        "imported 2 GPS line(s) into new grid G1 (0.5 × 19.9 m, spacing 0.50 m)",
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
    ready(dialog.gps_page)
    dialog.accept()
    assert len(plugin.session.site.lines) == 1
    assert shown[0] == "imported 1 GPS line(s) into new grid G1 (0.5 × 19.9 m, spacing 0.50 m)"
    assert shown[-1] == "not imported: FILE__002.DZT (no DZG beside it)"


def test_an_import_into_a_site_with_grids_uses_their_crs(plugin, tmp_path, project_degrees):
    plugin.session.add_grid(Grid("A", (500_000.0, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32632", 0.5))
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    dialog.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    assert dialog.gps_page.crs_label.text() == "EPSG:32632"
    assert dialog.gps_page.note_label.text() == "picked for you: the CRS the site's other grids use"
    ready(dialog.gps_page, "G9")
    dialog.accept()
    (line,) = plugin.session.site.lines
    assert line.placement.crs == "EPSG:32632" and line.placement.grid_id == "G9"
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
    ready(first.gps_page)
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
    ready(dialog.gps_page)
    dialog.accept()

    lines = plugin.session.site.lines
    assert len(lines) == len(GPS_LINES) == 60
    assert plugin.session.site_crs() == dialog.gps_page._crs.authid()
    walked = {ln.path.name: float(ln.distance_along()[-1]) for ln in lines}
    assert 29.5 <= walked["FILE__011.DZT"] <= 31.0
    assert shown[0].startswith("imported 60 GPS line(s) into new grid G1 (")
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
    labels = [form.itemAt(r, QFormLayout.ItemRole.LabelRole).widget().text() for r in range(7)]
    assert labels == [
        "Target grid",
        "Name",
        "Spacing (m)",
        "Fitted",
        "Destagger (m)",
        "Processing preset",
        "Coordinates:",
    ]
    assert form.itemAt(5, QFormLayout.ItemRole.FieldRole).widget() is d.preset_box


def test_gps_import_with_a_preset_changes_only_the_new_lines_and_remembers_the_sites_choice(
    session, tmp_path
):
    _preset_from_a_line(session, tmp_path, "Plain")
    first_dlg = gps_dialog(session)
    first = first_dlg.gps_page
    first.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    ready(first, "G1")
    first_dlg.accept()
    before = session.stack_for(first.imported_keys[0]).to_dicts()
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files([gps_file(tmp_path / "raw", "FILE__002.DZT")])
    d.preset_box.combo.setCurrentIndex(d.preset_box.combo.findData("Plain"))
    d.target_combo.setCurrentIndex(d.target_combo.findData("G1"))  # now G1 has lines
    d.preset_box.combo.setCurrentIndex(d.preset_box.combo.findData("Plain"))
    d_dlg.accept()
    assert session.stack_for(first.imported_keys[0]).to_dicts() == before
    assert session.stack_for(d.imported_keys[0]).to_dicts() == session.site.presets["Plain"]
    assert session.site.import_presets == {"site": "Plain", "grids": {"G1": "Plain"}}
    assert "S" not in session.site.slice_sources
    assert gps_dialog(session).gps_page.preset_box.chosen() == "Plain"


def test_a_preset_deleted_under_the_gps_dialog_imports_nothing(session, tmp_path):
    _preset_from_a_line(session, tmp_path, "Plain")
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    ready(d)
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
    ready(first, "G1", 0.5)
    first_dlg.accept()
    assert len(first.imported_keys) == 2
    for k in first.imported_keys:
        session.append_step(k, build_step("dewow", window_ns=12.0))
    session.save_preset("Plain", first.imported_keys[0])
    kept = {k: session.stack_for(k).to_dicts() for k in first.imported_keys}
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files(list(GPS_LINES[2:4]))
    ready(d, "G2", 0.5)
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
    ready(d)
    d.preset_box.combo.setCurrentIndex(d.preset_box.combo.findData("Plain"))

    def boom(*a, **k):
        raise RuntimeError("no disk")

    monkeypatch.setattr(session, "apply_preset_to", boom)
    d_dlg.accept()
    assert d_dlg.result() == d_dlg.DialogCode.Accepted
    assert len(d.imported_keys) == 1
    assert "could not be applied" in d.status.text()


# ---- M17b Task 5: into a grid, new or existing ---------------------------------------

import math  # noqa: E402

import numpy as np  # noqa: E402

M_PER_DEG_LON = M_PER_DEG * math.cos(math.radians(LAT0))


def walk_file(folder, name, east_m=0.0, north_m=0.0, south=False, bearing=0.0):
    """A 200-trace line at 0.1 m a trace starting east_m/north_m from the
    origin, walked along `bearing` (degrees clockwise from north), or the
    opposite way with south=True."""
    sin, cos = math.sin(math.radians(bearing)), math.cos(math.radians(bearing))
    fixes = []
    for t in (25, 75, 125, 175):
        run = (200 - t if south else t) * 0.1
        lat = LAT0 + (north_m + run * cos) / M_PER_DEG
        lon = LON0 + (east_m + run * sin) / M_PER_DEG_LON
        fixes.append((t, lat, lon, 4))
    return synthetic_gps_dzt(folder, name, fixes, traces_per_metre=10.0)


def zigzag(folder, n=8, start=1):
    """n lines 0.5 m apart, alternate files walked south."""
    return [
        walk_file(folder, f"FILE__{k:03d}.DZT", east_m=0.5 * (k - start), south=bool(k % 2 == 0))
        for k in range(start, start + n)
    ]


def grid_ids(session):
    return [g.id for g in session.site.grids]


def test_new_grid_is_the_first_target_and_import_waits_for_a_name(session, tmp_path):
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    assert [d.target_combo.itemText(i) for i in range(d.target_combo.count())] == ["New grid"]
    d.add_files(zigzag(tmp_path / "raw"))
    assert d.target() is None and d.target_combo.currentText() == "New grid"
    assert d.status.text() == "Name the new grid." and not d_dlg.import_button.isEnabled()
    d.name_edit.setText("G4")
    assert d_dlg.import_button.isEnabled()
    assert abs(d.spacing.value() - 0.5) < 0.01
    assert d.spacing_note.text() == "measured from the tracks; type over it if it is wrong"
    assert d.fitted.text().startswith("4.0 × 20.0 m, azimuth ")
    assert d.fitted.text().endswith(
        "lined up with the lines, half a spacing outside the outer ones"
    )
    d_dlg.reject()


def test_a_typed_spacing_sticks_and_the_grid_is_one_spacing_wider_per_line(session, tmp_path):
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    files = zigzag(tmp_path / "raw", n=9)
    d.add_files(files[:8])
    d.spacing.setValue(0.6)
    assert d.spacing_note.text() == ""
    d.add_files(files[8:])
    assert d.spacing.value() == 0.6
    d_dlg.reject()


def test_import_makes_the_grid_and_the_lines_in_one_step(plugin, tmp_path):
    shown: list[str] = []
    plugin.message = lambda text, level=None, title="nsgeo": shown.append(text)  # type: ignore[method-assign]
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    d = dialog.gps_page
    d.add_files(zigzag(tmp_path / "raw"))
    d.name_edit.setText("G4")
    d.spacing.setValue(0.6)
    dialog.accept()
    session = plugin.session
    grid = session.grid("G4")
    assert grid.default_spacing == 0.6 and grid.crs == session.site_crs() == "EPSG:32632"
    assert len(session.site.lines) == 8
    assert all(ln.placement.grid_id == "G4" for ln in session.site.lines)
    assert (
        shown[0].startswith("imported 8 GPS line(s) into new grid G4 (4.")
        and "m, spacing 0.60 m)" in shown[0]
    )
    result = d.last_import
    assert result is not None and result.grid_id == "G4" and len(result.order) == 8
    assert len(result.placed) == 8 and result.leftovers == []


def test_a_name_already_used_is_refused_up_front_and_at_import(session, tmp_path):
    session.add_grid(Grid("G4", (0.0, 0.0), 0.0, 5.0, 5.0, "EPSG:32632", 0.5))
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files(zigzag(tmp_path / "raw"))
    d.name_edit.setText("G4")
    assert d.status.text() == "A grid named G4 already exists."
    assert not d_dlg.import_button.isEnabled()
    d.name_edit.setText("G5")  # free now ...
    assert d_dlg.import_button.isEnabled()
    session.add_grid(Grid("G5", (0.0, 0.0), 0.0, 5.0, 5.0, "EPSG:32632", 0.5))  # ... taken after
    d_dlg.accept()
    assert d.status.text() == "A grid named G5 already exists."
    assert session.site.lines == [] and grid_ids(session) == ["G4", "G5"]
    d_dlg.reject()


def test_one_file_gives_nothing_to_measure_until_a_spacing_is_typed(session, tmp_path):
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files([walk_file(tmp_path / "raw", "FILE__001.DZT")])
    d.name_edit.setText("G1")
    assert d.spacing.text() == "—" and d.spacing.value() == 0.0
    assert d.spacing_note.text() == "type one: one line gives nothing to measure it from"
    assert d.fitted.text() == "—" and not d_dlg.import_button.isEnabled()
    d.spacing.setValue(0.5)
    assert d_dlg.import_button.isEnabled()
    d_dlg.accept()
    assert abs(session.grid("G1").size_x - 0.5) < 1e-6


def test_crossing_sets_share_no_direction_so_the_smallest_rectangle_is_fitted(session, tmp_path):
    # Three sets of three lines, 60 degrees apart: no set holds most of the length.
    files = []
    for set_no, bearing in enumerate((0.0, 60.0, 120.0)):
        sin, cos = math.sin(math.radians(bearing)), math.cos(math.radians(bearing))
        for k in range(3):
            files.append(
                walk_file(
                    tmp_path / "raw",
                    f"FILE__{3 * set_no + k + 1:03d}.DZT",
                    east_m=0.5 * k * cos,
                    north_m=-0.5 * k * sin,
                    bearing=bearing,
                )
            )
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files(files)
    d.name_edit.setText("G1")
    assert d.spacing.text() == "—"
    assert d.spacing_note.text() == "type one: these lines share no direction to measure it along"
    d.spacing.setValue(0.5)
    assert d.fitted.text().endswith(
        "the smallest rectangle around them; these lines share no direction"
    )
    d_dlg.reject()


def test_the_new_grid_rows_hide_for_an_existing_grid(session, tmp_path):
    session.add_grid(Grid("A", (0.0, 0.0), 0.0, 5.0, 5.0, "EPSG:32632", 0.5))
    d_dlg = gps_dialog(session)
    d_dlg.show()
    d = d_dlg.gps_page
    assert d.name_edit.isVisibleTo(d_dlg) and d.fitted.isVisibleTo(d_dlg)
    d.target_combo.setCurrentIndex(d.target_combo.findData("A"))
    assert not d.name_edit.isVisibleTo(d_dlg) and not d.fitted.isVisibleTo(d_dlg)
    form = d._form
    assert not form.labelForField(d.name_edit).isVisibleTo(d_dlg)
    assert d_dlg.windowTitle() == "Add GPR data into A"
    d_dlg.reject()


def _xy(lon, lat):
    to_xy = __import__("nsgeo_qgis.ui.gps_import_dialog", fromlist=["x"]).lonlat_to_xy(
        QgsCoordinateReferenceSystem("EPSG:32632")
    )
    x, y = to_xy(np.array([lon]), np.array([lat]))
    return float(x[0]), float(y[0])


def test_an_existing_grid_shows_metres_outside_and_refuses_a_line_wholly_outside(session, tmp_path):
    x0, y0 = _xy(LON0, LAT0)
    grid = Grid("A", (x0 - 1.0, y0 - 3.0), 0.0, 3.0, 16.0, "EPSG:32632", 0.5)
    session.add_grid(grid)
    raw = tmp_path / "raw"
    files = [
        walk_file(raw, "FILE__001.DZT"),
        walk_file(raw, "FILE__002.DZT", east_m=0.5),
        walk_file(raw, "FILE__003.DZT", east_m=30.0),  # far east of the grid
    ]
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files(files)
    d.target_combo.setCurrentIndex(d.target_combo.findData("A"))
    heads = [d.table.horizontalHeaderItem(c).text() for c in range(d.table.columnCount())]
    assert heads == [*HEADERS[:5], "Outside A", "Status"]
    assert cells(d, 0)[5].endswith(" m") and not cells(d, 0)[5].startswith("all")
    assert 6.5 < float(cells(d, 0)[5].split()[0]) < 7.3
    assert colours(d, 0, 5) == AMBER
    assert cells(d, 2)[5].startswith("all 19.") and cells(d, 2)[6] == "outside A"
    assert colours(d, 2, 5) == RED and colours(d, 2, 6) == RED
    assert d_dlg.import_button.text() == "Import 2 line(s) into A"
    d_dlg.accept()
    assert [ln.placement.grid_id for ln in session.site.lines] == ["A", "A"]
    assert session.grid("A") == grid
    msgs = [t for t, _ in d.messages]
    assert msgs[0] == "imported 2 GPS line(s) into A"
    assert any("lies outside A and is left out of its slices" in t for t in msgs)
    assert msgs[-1] == "not imported: FILE__003.DZT (outside A)"
    assert d.last_import is not None and d.last_import.leftovers == []


def test_the_preset_becomes_the_new_grids_slices_preset(session, tmp_path):
    _preset_from_a_line(session, tmp_path, "Plain")
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files(zigzag(tmp_path / "raw"))
    d.name_edit.setText("G4")
    d.preset_box.combo.setCurrentIndex(d.preset_box.combo.findData("Plain"))
    assert d.preset_box.note.text() == "G4's first lines: this becomes its Slices preset too."
    d_dlg.accept()
    assert session.site.slice_sources["G4"]["preset"] == "Plain"
    assert session.site.import_presets["grids"]["G4"] == "Plain"
    for k in d.imported_keys:
        assert session.stack_for(k).to_dicts() == session.site.presets["Plain"]


def test_a_refused_add_lines_takes_the_new_grid_and_its_preset_back(session, tmp_path, monkeypatch):
    _preset_from_a_line(session, tmp_path, "Plain")
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files(zigzag(tmp_path / "raw"))
    d.name_edit.setText("G4")
    d.preset_box.combo.setCurrentIndex(d.preset_box.combo.findData("Plain"))

    def refuse(lines):
        raise ValueError("those lines do not fit")

    monkeypatch.setattr(session, "add_lines", refuse)
    d_dlg.accept()
    assert "G4" not in grid_ids(session) and "G4" not in session.site.slice_sources
    assert d.status.text() == "those lines do not fit"
    assert d_dlg.result() != d_dlg.DialogCode.Accepted
    d_dlg.reject()


def test_a_site_without_a_crs_and_a_geographic_project_lands_in_the_picked_zone(
    qgis_app, tmp_path, session, project_degrees
):
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files(zigzag(tmp_path / "raw"))
    d.name_edit.setText("G4")
    assert session.site_crs() is None
    d_dlg.accept()
    assert session.grid("G4").crs == session.site_crs() == "EPSG:32632"
    assert {ln.placement.crs for ln in session.site.lines} == {"EPSG:32632"}


def test_a_grid_removed_under_the_page_refuses_the_import(session, tmp_path):
    session.add_grid(Grid("A", (0.0, 0.0), 0.0, 5.0, 5.0, "EPSG:32632", 0.5))
    d_dlg = gps_dialog(session)
    d = d_dlg.gps_page
    d.add_files(zigzag(tmp_path / "raw"))
    d.target_combo.setCurrentIndex(d.target_combo.findData("A"))
    session.remove_grid("A")
    assert d.target() is None and not d_dlg.import_button.isEnabled()
    d.name_edit.setText("G1")
    d_dlg.accept()
    assert d.status.text() == "grid 'A' no longer exists; nothing was imported"
    assert session.site.lines == [] and grid_ids(session) == []
    d_dlg.reject()


# ---- the preview -----------------------------------------------------------------


def canvas_corners(plugin, grid):
    from qgis.core import QgsCoordinateTransform, QgsPointXY

    canvas = plugin.iface.mapCanvas()
    xform = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem(grid.crs),
        canvas.mapSettings().destinationCrs(),
        QgsProject.instance(),
    )
    world = grid.to_world(
        np.array([[0, 0], [grid.size_x, 0], [grid.size_x, grid.size_y], [0, grid.size_y]], float)
    )
    return [xform.transform(QgsPointXY(float(x), float(y))) for x, y in world]


def test_the_new_grid_is_previewed_dashed_on_the_map_and_cleared_when_it_is_not(plugin, tmp_path):
    plugin.session.add_grid(Grid("A", (0.0, 0.0), 0.0, 5.0, 5.0, "EPSG:32632", 0.5))
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    overlay = dialog.overlay
    assert overlay is not None and overlay.grid is None
    d = dialog.gps_page
    d.add_files(zigzag(tmp_path / "raw"))
    assert d.proposal() is not None
    want = canvas_corners(plugin, d.proposal())
    assert len(overlay.grid) == 4
    for got, exp in zip(overlay.grid, want):
        assert got.x() == pytest.approx(exp.x(), abs=1e-6)
        assert got.y() == pytest.approx(exp.y(), abs=1e-6)
    d.target_combo.setCurrentIndex(d.target_combo.findData("A"))
    assert overlay.grid is None
    d.target_combo.setCurrentIndex(0)
    assert overlay.grid is not None
    dialog.set_mode(MODE_GRID)
    assert overlay.grid is None
    dialog.set_mode(GPS)
    assert overlay.grid is not None
    dialog.reject()


@pytest.mark.parametrize("how", ["accept", "reject", "close"])
def test_the_preview_leaves_the_map_however_the_dialog_finishes(plugin, tmp_path, how):
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    overlay = dialog.overlay
    d = dialog.gps_page
    d.add_files(zigzag(tmp_path / "raw"))
    d.name_edit.setText("G4")
    assert overlay.grid is not None
    getattr(dialog, how)()
    assert overlay.disposed
    assert plugin._add_data_dialog is None


def test_a_dialog_destroyed_without_finishing_still_gives_the_preview_back(plugin, tmp_path):
    from qgis.PyQt import sip

    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    overlay = dialog.overlay
    dialog.setParent(None)
    sip.delete(dialog)
    assert overlay.disposed and plugin._add_data_dialog is None


def test_the_site_closing_under_a_previewing_dialog_refuses_the_import(plugin, tmp_path):
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    d = dialog.gps_page
    d.add_files(zigzag(tmp_path / "raw"))
    d.name_edit.setText("G4")
    plugin.session.close_site()
    dialog.accept()
    assert d.status.text() == "The site changed; nothing was imported."
    dialog.reject()


# ---- real data ---------------------------------------------------------------


@pytest.mark.skipif(not GPS_LINES, reason="no GPS-recorded DZT files in tests/data/local")
def test_the_sixty_real_lines_fit_a_new_grid_they_sit_inside(plugin, project_degrees):
    plugin.open_add_data_dialog(None, GPS)
    dialog = plugin._add_data_dialog
    d = dialog.gps_page
    d.add_files(list(GPS_LINES))
    d.name_edit.setText("G1")
    assert d.spacing_note.text().startswith("measured")
    dialog.accept()
    session = plugin.session
    grid = session.grid("G1")
    assert len(session.keys_on_grid("G1")) == len(GPS_LINES) == 60
    assert grid.default_spacing == pytest.approx(0.496, abs=0.01)
    fractions = []
    for ln in session.site.lines:
        local = grid.to_local(ln.trace_coords({}))
        inside = (
            (local[:, 0] >= 0)
            & (local[:, 0] <= grid.size_x)
            & (local[:, 1] >= 0)
            & (local[:, 1] <= grid.size_y)
        )
        fractions.append(float(inside.mean()))
    # One outer line wanders about half a metre across its own track, past the
    # half-spacing margin (87.7 % of its traces inside); every other line sits
    # inside to the last trace or two.
    assert float(np.mean(fractions)) >= 0.99
    assert sorted(fractions)[1] >= 0.99 and min(fractions) >= 0.85
