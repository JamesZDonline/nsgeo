"""Import GPS lines: the dialog and its toolbar action (M17a Task 4, P10, P11)."""

from __future__ import annotations

import pytest
from nsgeo.geometry import Grid, GridPlacement, TrackPlacement
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.gps_import_dialog import (
    COL_ENDS,
    COL_GAP,
    COL_STATUS,
    HEADERS,
    GpsImportDialog,
)
from nsgeo_qgis.ui.import_dialog import ImportDialog
from plugin_testing import synthetic_dzt, synthetic_gps_dzt
from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.PyQt.QtCore import QEvent
from qgis.PyQt.QtWidgets import QMessageBox
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
    d = GpsImportDialog(session)
    assert d.windowTitle() == "Import GPS lines"
    assert [d.table.horizontalHeaderItem(c).text() for c in range(6)] == HEADERS
    assert HEADERS == ["File", "Traces", "RTK fixes", "Without RTK", "Ends", "Status"]
    assert d.status.text() == "Add DZT files that have a DZG beside them."
    assert not d.import_button.isEnabled()

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
    assert d.import_button.text() == "Import" and d.import_button.isEnabled()
    assert d.crs_label.text() == "Coordinates: EPSG:32632"
    assert d.note_label.text() == ""
    d.reject()


def test_the_destagger_box_and_buttons_follow_the_copy(session):
    d = GpsImportDialog(session)
    assert (d.shift.minimum(), d.shift.maximum()) == (-2.0, 2.0)
    assert d.shift.singleStep() == 0.01 and d.shift.decimals() == 2 and d.shift.value() == 0.0
    assert d.shift.toolTip() == (
        "Moves every trace forward along the way its line was walked, for every line in "
        "this import. Change it per line later from the Survey panel."
    )
    assert d.add_button.text() == "Add files…" and d.remove_button.text() == "Remove"
    d.reject()


def test_a_geographic_project_picks_the_utm_zone_and_says_why(
    qgis_app, tmp_path, session, project_degrees
):
    d = GpsImportDialog(session)
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    assert d.crs_label.text() == "Coordinates: EPSG:32632"
    assert d.note_label.text().startswith("picked for you:")
    placement = d.rows[0].line.placement
    assert placement.crs == "EPSG:32632"
    d.reject()


def test_remove_drops_the_selected_rows_and_replans(session, tmp_path):
    d = GpsImportDialog(session)
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
    assert not d.import_button.isEnabled()
    d.reject()


def test_a_file_already_in_the_site_shows_how_to_switch(session, tmp_path):
    from nsgeo.model import Line

    raw = tmp_path / "raw"
    taken = gps_file(raw, "FILE__001.DZT")
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32632", 0.5))
    session.add_lines(
        [Line.open(taken, GridPlacement(grid_id="A", axis="y", offset=0.5, start_along=0.0))]
    )
    d = GpsImportDialog(session)
    d.add_files([taken])
    # planned, then refused: the row keeps its counts and ends
    assert cells(d, 0) == [
        "FILE__001.DZT",
        "200",
        "4 of 4",
        "—",
        "2.50 / 2.40 m",
        "already in the site (remove it first to place it by GPS)",
    ]
    d.reject()


def test_a_site_crs_that_cannot_place_a_file_refuses_that_row(qgis_app, session, tmp_path):
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    d = GpsImportDialog(session)
    d.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])  # zone 32 is far from zone 16
    assert d.crs_label.text() == "Coordinates: EPSG:32616"
    assert cells(d, 0)[COL_STATUS] == "outside what EPSG:32616 can place"
    assert d.status.text() == "0 of 1 file(s) ready to import."
    assert not d.import_button.isEnabled()
    d.accept()
    assert d.status.text() == "Nothing to import: no file is ready."
    assert session.site.lines == [] and session.site_crs() == "EPSG:32616"
    d.reject()


# ---- the cues, the opening state and the Import details --------------------------

AMBER = ("#fbf3df", "#8a5a00")
RED = ("#fbe9e7", "#a12a1e")


def colours(d, row, col):
    item = d.table.item(row, col)
    return item.background().color().name(), item.foreground().color().name()


def plain(d, row, col):
    return d.table.item(row, col).background().style() == 0  # Qt.NoBrush


def test_the_cells_worth_a_look_are_amber_and_refused_statuses_red(session, tmp_path):
    raw = tmp_path / "raw"
    d = GpsImportDialog(session)
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
    d.reject()


def test_the_coordinates_show_the_sites_crs_before_any_file_is_added(qgis_app, session):
    session.add_grid(Grid("A", (500_000.0, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32616", 0.5))
    d = GpsImportDialog(session)
    assert d.crs_label.text() == "Coordinates: EPSG:32616"
    d.reject()


def test_the_notes_sit_beside_the_boxes_and_the_footer_is_one_row(session):
    d = GpsImportDialog(session)
    layout = d.layout()
    footer = layout.itemAt(layout.count() - 1).layout()
    assert footer.itemAt(0).widget() is d.status and footer.itemAt(1).widget() is d.buttons
    d.reject()


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
    plugin.open_gps_import_dialog()
    dialog = plugin._gps_import_dialog
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
    plugin.open_gps_import_dialog()
    dialog = plugin._gps_import_dialog
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

    plugin.open_gps_import_dialog()
    dialog = plugin._gps_import_dialog
    assert dialog is not None
    dialog.add_files([a, b])
    dialog.shift.setValue(0.24)
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
    assert plugin._gps_import_dialog is None  # finished() ran


def test_import_reports_refused_files_last(plugin, tmp_path):
    shown: list[str] = []
    plugin.message = lambda text, level=None, title="nsgeo": shown.append(text)  # type: ignore[method-assign]
    raw = tmp_path / "raw"
    plugin.open_gps_import_dialog()
    dialog = plugin._gps_import_dialog
    dialog.add_files([gps_file(raw, "FILE__001.DZT"), synthetic_dzt(raw, "FILE__002.DZT")])
    dialog.accept()
    assert len(plugin.session.site.lines) == 1
    assert shown[0] == "imported 1 GPS line(s)"
    assert shown[-1] == "not imported: FILE__002.DZT (no DZG beside it)"


def test_an_import_into_a_site_with_grids_uses_their_crs(plugin, tmp_path, project_degrees):
    plugin.session.add_grid(Grid("A", (500_000.0, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32632", 0.5))
    plugin.open_gps_import_dialog()
    dialog = plugin._gps_import_dialog
    dialog.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    assert dialog.crs_label.text() == "Coordinates: EPSG:32632"
    assert dialog.note_label.text() == "picked for you: the CRS the site's other grids use"
    dialog.accept()
    (line,) = plugin.session.site.lines
    assert line.placement.crs == "EPSG:32632"
    assert plugin.session.site.crs == "EPSG:32632"  # pinned by the first GPS line


def test_import_after_the_site_was_replaced_adds_nothing(plugin, tmp_path):
    plugin.open_gps_import_dialog()
    dialog = plugin._gps_import_dialog
    dialog.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    other = tmp_path / "other"
    other.mkdir()
    plugin.session.close_site()
    plugin.session.new_site(other)
    dialog.accept()
    assert dialog.status.text() == "The site changed; nothing was imported."
    assert plugin.session.site.lines == [] and plugin.session.site_crs() is None
    assert plugin._gps_import_dialog is dialog  # still open
    dialog.reject()


def test_import_after_the_site_was_closed_adds_nothing(plugin, tmp_path):
    plugin.open_gps_import_dialog()
    dialog = plugin._gps_import_dialog
    dialog.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    plugin.session.close_site()
    dialog.accept()
    assert dialog.status.text() == "The site changed; nothing was imported."
    dialog.reject()


def test_a_site_crs_that_appeared_while_the_dialog_was_open_replans_instead_of_importing(
    plugin, tmp_path, project_degrees
):
    plugin.open_gps_import_dialog()
    dialog = plugin._gps_import_dialog
    dialog.add_files([gps_file(tmp_path / "raw", "FILE__001.DZT")])
    assert dialog.crs_label.text() == "Coordinates: EPSG:32632"
    plugin.session.add_grid(Grid("A", (500_000.0, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32633", 0.5))
    dialog.accept()
    assert plugin.session.site.lines == []
    assert dialog.crs_label.text() == "Coordinates: EPSG:32633"
    assert "EPSG:32633" in dialog.status.text()
    dialog.reject()


def test_a_file_already_in_the_site_cannot_be_imported_twice(plugin, tmp_path):
    raw = tmp_path / "raw"
    path = gps_file(raw, "FILE__001.DZT")
    plugin.open_gps_import_dialog()
    first = plugin._gps_import_dialog
    first.add_files([path])
    first.accept()
    plugin.open_gps_import_dialog()
    second = plugin._gps_import_dialog
    second.add_files([path])
    assert cells(second, 0)[COL_STATUS].startswith("already in the site")
    second.reject()


# ---- the plugin --------------------------------------------------------------


def test_the_toolbar_action_needs_an_open_site_but_no_grid(
    fake_iface, tmp_path, answer_modal, project_utm
):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    act = plugin.act_import_gps
    assert act.text() == "Import GPS lines…"
    assert act.toolTip() == (
        "Imports DZT files with a DZG beside them, each placed along its RTK GPS track."
    )
    actions = plugin.toolbar_actions
    assert actions.index(act) == actions.index(plugin.act_import) + 1
    assert not act.isEnabled()
    plugin.open_gps_import_dialog()
    assert plugin._gps_import_dialog is None  # no site: nothing opens

    (tmp_path / "site").mkdir()
    plugin.session.new_site(tmp_path / "site")
    assert plugin.session.site.grids == []
    assert act.isEnabled()
    act.trigger()
    assert plugin._gps_import_dialog is not None
    plugin.session.close_site()
    assert not act.isEnabled()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
    assert plugin._gps_import_dialog is None and plugin.act_import_gps is None


def test_the_gps_import_dialog_is_single_instance_and_closes_on_unload(plugin):
    plugin.open_gps_import_dialog()
    first = plugin._gps_import_dialog
    plugin.open_gps_import_dialog()
    assert plugin._gps_import_dialog is first
    plugin.unload()
    assert plugin._gps_import_dialog is None


def test_the_tape_import_still_places_by_the_tapes_beside_a_dzg(session, tmp_path):
    session.add_grid(Grid("A", (500_000.0, 5_000_000.0), 0.0, 5.0, 11.0, "EPSG:32632", 0.5))
    path = gps_file(tmp_path / "raw", "FILE__001.DZT")
    assert path.with_suffix(".DZG").exists()
    d = ImportDialog(session, grid_id="A")
    d.add_files([path])
    d.accept()
    (line,) = session.site.lines
    assert isinstance(line.placement, GridPlacement)
    assert not isinstance(line.placement, TrackPlacement)


# ---- real data ---------------------------------------------------------------


@pytest.mark.skipif(not GPS_LINES, reason="no GPS-recorded DZT files in tests/data/local")
def test_importing_the_first_gps_survey(plugin, project_degrees):
    shown: list[str] = []
    plugin.message = lambda text, level=None, title="nsgeo": shown.append(text)  # type: ignore[method-assign]
    plugin.open_gps_import_dialog()
    dialog = plugin._gps_import_dialog
    dialog.add_files(list(GPS_LINES))
    assert [r.refusal for r in dialog.rows] == [None] * len(GPS_LINES)
    dialog.accept()

    lines = plugin.session.site.lines
    assert len(lines) == len(GPS_LINES) == 60
    assert plugin.session.site_crs() == dialog._crs.authid()
    walked = {ln.path.name: float(ln.distance_along()[-1]) for ln in lines}
    assert 29.5 <= walked["FILE__011.DZT"] <= 31.0
    assert shown[0] == "imported 60 GPS line(s)"
    assert not any("without an RTK fix" in m for m in shown)
