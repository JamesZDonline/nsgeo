from __future__ import annotations

import dataclasses
import time
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.maptools.pick_tool import PickPointTool
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.grid_dialog import COL_A, COL_B, COL_FROM, COL_ROLE, GridDialog
from plugin_testing import feature_id, named_layer, send_map_key, send_map_mouse
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QPoint, Qt
from qgis.PyQt.QtWidgets import QAbstractItemView, QMessageBox

TRUE = Grid("A", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)

SITE = Grid("S", (518_204.112, 4_000_731.508), 10.0, 20.0, 20.0, "EPSG:32616", 0.5)
SITE_CORNERS = SITE.to_world(np.array([[0, 0], [20, 0], [20, 20], [0, 20]], dtype=float))
UTM16, WGS84 = QgsCoordinateReferenceSystem("EPSG:32616"), QgsCoordinateReferenceSystem("EPSG:4326")


@pytest.fixture
def project_crs(qgis_app):
    """Set the project CRS for a test and put the original back after."""
    original = QgsProject.instance().crs()

    def _set(crs: QgsCoordinateReferenceSystem) -> None:
        QgsProject.instance().setCrs(crs)

    yield _set
    QgsProject.instance().setCrs(original)


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    return s


@pytest.fixture(autouse=True)
def _flush_deferred_deletes(qgis_app):
    """Process every dialog's queued deleteLater() at the end of each test.

    Round 5, Finding 6 connects dialog.destroyed to a plugin.py closure so
    self._grid_dialog can never point at a dead C++ object -- but nothing
    in this file ever previously ran the Qt event loop, so 44 tests'
    worth of deleteLater()'d dialogs (each now destroyed()-connected back
    into plugin.py) piled up unflushed for qgis_app's own session-scoped
    exitQgis() to reap all at once at process teardown. Probed directly:
    that bulk, simultaneous destruction -- not any single dialog's --
    segfaults inside exitQgis() (crash while running a destroyed()
    slot, reentered from QGIS's own C++ teardown deep within it).
    Flushing after every test instead means exitQgis() only ever reaps
    whatever the *last* test itself left outstanding, which on its own
    is not a new failure mode: it is exactly what a real QGIS session
    already does with one dialog at a time (round 1, Finding 3).
    """
    yield
    qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _memory_layer(ring_world: np.ndarray) -> QgsVectorLayer:
    layer = QgsVectorLayer("Polygon?crs=EPSG:32616", "plan", "memory")
    ring = [QgsPointXY(*p) for p in ring_world]
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromPolygonXY([ring]))
    layer.dataProvider().addFeatures([f])
    return layer


def _pump(app: object, condition: object, timeout: float = 2.0) -> bool:
    """Process events until `condition()` is true or `timeout` elapses.

    QgsFeaturePickerWidget populates its feature list through a
    background QgsFeatureExpressionValuesGatherer thread -- setLayer()
    and setFeature() return immediately, before that thread has reported
    back, so a test that calls feature() right afterwards sees an
    invalid feature regardless of what was requested.
    """
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


def _select_sole_feature(qgis_app: object, dialog: GridDialog, layer: QgsVectorLayer) -> None:
    """Select `layer`'s only feature in `dialog`'s polygon row, waiting out
    QgsFeaturePickerWidget's asynchronous population (see _pump)."""
    dialog.layer_combo.setLayer(layer)
    _pump(qgis_app, lambda: dialog.feature_picker.feature().isValid())
    fid = next(layer.getFeatures()).id()
    dialog.feature_picker.setFeature(fid)
    _pump(qgis_app, lambda: dialog.feature_picker.feature().id() == fid)


def _open(plugin: Any, grid_id: str | None = None) -> GridDialog:
    """Call open_grid_dialog() and return the GridDialog it just showed.

    Fix round 4, Finding 1: GridDialog is modeless (plugin.py's
    open_grid_dialog() calls show(), not exec()) precisely so a map pick
    can reach the canvas at all -- exec()'s application-modal event loop
    terminates the instant the dialog is hidden, so _start_pick()'s
    dialog.hide() would otherwise end it before a single canvas click
    landed (verified directly with a bare QDialog; see the fix-round
    report). That also means these tests never monkeypatch QDialog.exec
    (unlike `drive_dialog` in conftest.py, which no test in this file
    uses any more but which is kept for a future genuinely-modal dialog):
    open_grid_dialog() returns immediately with a real, already-shown
    dialog tracked on the plugin as `_grid_dialog`, and driving it --
    typing into fields, clicking a Pick button, sending real map-tool
    events, calling accept()/reject() -- exercises the exact same code
    path a live QGIS session would.
    """
    plugin.open_grid_dialog(grid_id)
    dialog = plugin._grid_dialog
    assert dialog is not None
    return dialog


def test_ok_is_blocked_until_id_and_velocity_are_set(session):
    d = GridDialog(session)
    assert not d.ok_button.isEnabled()
    d.id_edit.setText("A")
    assert not d.ok_button.isEnabled()  # velocity still 0 = required
    d.velocity.setValue(0.08)
    # Round 3, Finding 1: no fallback CRS any more (the fallback tried in
    # rounds 1 and 2 was itself always going to be a CRS chosen only
    # because it passed the guard -- EPSG:3857 turned out to be exactly
    # the failure this dialog exists to prevent). crs_widget starts
    # unset in this bare test harness (no project CRS either), so OK
    # stays blocked until a CRS is actually picked.
    assert not d.ok_button.isEnabled()
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32616"))
    assert d.ok_button.isEnabled()


def test_crs_guard_blocks_every_route_to_a_bad_crs(session):
    # Fix round 2, Finding 2: one guard in _validate() rather than a
    # separate check bolted onto every path that can set crs_widget's
    # CRS. Several such paths, all caught by the same guard (round 3,
    # Finding 1 replaced the geographic check with units + local scale,
    # and removed the fallback route entirely -- see
    # test_ok_is_blocked_until_id_and_velocity_are_set and
    # test_crs_scale_guard_accepts_correct_uses_and_refuses_mismatches
    # for those):

    d = GridDialog(session)
    d.id_edit.setText("A")
    d.velocity.setValue(0.08)

    # 1. The *project's* own CRS, when it is geographic -- QGIS's
    #    out-of-the-box default for a brand-new project.
    original_project_crs = QgsProject.instance().crs()
    try:
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        d_project = GridDialog(session)
        d_project.id_edit.setText("A")
        d_project.velocity.setValue(0.08)
        assert not d_project.ok_button.isEnabled()
        assert "metres" in d_project.crs_hint.text().lower()
    finally:
        QgsProject.instance().setCrs(original_project_crs)

    # 2a. A CRS the user picks by hand that is valid but has no
    #     authority code (round 1, Finding 2).
    custom = QgsCoordinateReferenceSystem.fromProj(
        "+proj=omerc +lat_0=36 +lonc=15 +alpha=30 +k=1 +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs"
    )
    assert custom.isValid() and not custom.authid()  # the exact case this guards
    d.crs_widget.setCrs(custom)
    assert not d.ok_button.isEnabled()
    assert "authority" in d.crs_hint.text().lower()

    # 2b. ... or one the user picks that is geographic outright.
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    assert not d.ok_button.isEnabled()
    assert "metres" in d.crs_hint.text().lower()

    # Recovering with an ordinary registered, projected CRS re-enables OK
    # and clears the hint.
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32616"))
    assert d.ok_button.isEnabled()
    assert d.crs_hint.text() == ""


def test_crs_scale_guard_accepts_correct_uses_and_refuses_mismatches(session):
    # Fix round 3, Finding 1: authid() and mapUnits() == Meters are
    # necessary but not sufficient. Two whole families of CRS pass both
    # yet are not ground metres at the grid's own origin: EPSG:3857 (Web
    # Mercator -- mapUnits() reports Meters, isGeographic() is False,
    # but its scale factor grows without bound away from the equator),
    # and US survey feet zones (not geographic, valid authid, but not
    # metres at all -- caught by the units check directly, no scale
    # measurement needed).
    #
    # Points and expected |k-1| below were computed with QgsDistanceArea
    # (WGS84 ellipsoid) against a 1000 m baseline at each origin, in the
    # same script used for the fix-round report's calibration table.
    d = GridDialog(session)
    d.id_edit.setText("A")
    d.velocity.setValue(0.08)

    # Accepted, no hint: real CRSs used as intended (all measured well
    # under CRS_SCALE_WARN = 0.1%).
    for code, origin, why in (
        ("EPSG:32616", (500000.0, 3983948.453), "UTM 16N at its own central meridian"),
        ("EPSG:32616", (770421.370, 3988111.962), "UTM 16N near a zone edge"),
        ("EPSG:27700", (468748.556, 233978.339), "British National Grid"),
        ("EPSG:32119", (645754.486, 227483.520), "NC state plane, metres"),
    ):
        d.crs_widget.setCrs(QgsCoordinateReferenceSystem(code))
        d.origin_x.setValue(origin[0])
        d.origin_y.setValue(origin[1])
        assert d.ok_button.isEnabled(), why
        assert d.crs_hint.text() == "", why

    # Warned but not blocked: anisotropic equal-area CRSs away from
    # their own centre (~1.25%/~0.60% here) -- refusing these would
    # false-refuse legitimate work; CRS_SCALE_REFUSE is set well above
    # them (~2%).
    for code, origin in (
        ("EPSG:5070", (0.0, 2888222.097)),  # Albers CONUS, northern edge
        ("EPSG:3035", (5026876.835, 4731029.964)),  # ETRS89 LAEA, far corner
    ):
        d.crs_widget.setCrs(QgsCoordinateReferenceSystem(code))
        d.origin_x.setValue(origin[0])
        d.origin_y.setValue(origin[1])
        assert d.ok_button.isEnabled(), code
        assert "distort" in d.crs_hint.text().lower(), code

    # Refused: US survey feet, caught by the units check alone --
    # mapUnits() != Meters regardless of where the origin is.
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:2264"))
    d.origin_x.setValue(700000.0)
    d.origin_y.setValue(200000.0)
    assert not d.ok_button.isEnabled()
    assert "feet" in d.crs_hint.text().lower()

    # Refused: EPSG:3857 away from the equator. mapUnits() reports
    # Meters and isGeographic() is False, so only the local scale check
    # catches it -- 19.4% at lat 36, 27.0% at lat 43, both far past
    # CRS_SCALE_REFUSE.
    for origin, lat in (
        ((-9350837.227, 4300621.372), 36),
        ((-9350837.227, 5311971.847), 43),
    ):
        d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        d.origin_x.setValue(origin[0])
        d.origin_y.setValue(origin[1])
        assert not d.ok_button.isEnabled(), f"3857 at lat {lat}"
        assert "%" in d.crs_hint.text(), f"3857 at lat {lat}"


def test_crs_scale_check_skips_the_untouched_zero_origin(session):
    # Fix round 4, Finding 3: the (0, 0) skip in _crs_scale_error() is a
    # pure-accept path -- a regression here would silently *loosen* the
    # guard (measuring at (0, 0), the CRS's own origin, was verified to
    # give false positives for EPSG:5070/3035) rather than fail anything
    # visibly, so it needs its own test rather than relying on it never
    # coming up.
    d = GridDialog(session)
    d.id_edit.setText("A")
    d.velocity.setValue(0.08)
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:5070"))  # false-positive at (0, 0)
    assert d.origin_x.value() == 0.0 and d.origin_y.value() == 0.0
    assert d.ok_button.isEnabled()
    assert d.crs_hint.text() == ""


def test_crs_scale_check_skips_on_transform_failure_rather_than_refusing(session):
    # Fix round 4, Finding 3: the broad except in _crs_scale_error() is
    # also a pure-accept path. (1e8, 1e8) as a UTM 16N easting/northing
    # is genuinely outside the CRS's domain -- verified directly, the
    # transform itself raises QgsCsException ("Point outside of
    # projection domain") -- so this exercises the real exception path,
    # not a contrived stand-in for one.
    d = GridDialog(session)
    d.id_edit.setText("A")
    d.velocity.setValue(0.08)
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32616"))
    d.origin_x.setValue(1e8)
    d.origin_y.setValue(1e8)
    # Fix round 5, Finding 3: origin_x/origin_y.setValue() route through
    # _validate() only as a signal-connected slot -- if _crs_scale_error
    # raised instead of catching the exception, that exception would be
    # swallowed by Qt before it ever reached this test (the standing
    # signal/slot hazard), leaving crs_hint/ok_button exactly as they
    # were *before* these two setValue() calls, which already happened
    # to equal the expected "skip" outcome. A mutation that deletes
    # _crs_scale_error's except branch was confirmed to still pass here
    # without this line. Calling it directly, not through a signal,
    # means a real QgsCsException reaches this test instead of being
    # silently eaten.
    assert d._crs_scale_error(d.crs_widget.crs()) is None
    assert d.ok_button.isEnabled()
    assert d.crs_hint.text() == ""


def test_editing_an_existing_grid_prefills_and_keeps_its_id(session):
    session.add_grid(
        Grid(
            "A",
            (1.0, 2.0),
            45.0,
            3.0,
            4.0,
            "EPSG:32616",
            0.25,
            velocity=VelocityModel.constant(0.1),
        )
    )
    d = GridDialog(session, grid=session.grid("A"))
    assert d.id_edit.text() == "A" and not d.id_edit.isEnabled()
    assert d.velocity.value() == pytest.approx(0.1)
    d.azimuth.setValue(46.0)
    assert d.result_grid().azimuth == 46.0 and d.result_grid().default_spacing == 0.25


def test_crs_widget_stays_usable_when_the_hint_is_showing(session):
    # Fix round 3, Finding 2: crs_hint shared a row with crs_widget (a
    # QHBoxLayout, the way velocity_hint shares with velocity), which
    # squeezed crs_widget down to ~29 px and its inner combo to 0 -- the
    # CRS name entirely invisible exactly when the user is being told to
    # change it. crs_hint now gets its own row below crs_widget instead.
    d = GridDialog(session)
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))  # a real, long hint
    assert d.crs_hint.text() != ""
    d.adjustSize()
    d.show()
    try:
        assert d.crs_widget.width() > 200
    finally:
        d.hide()


def test_crs_hint_is_not_vertically_clipped_when_it_wraps_to_two_lines(session):
    # Fix round 4, Finding 2: crs_hint's own row (round 3's fix above)
    # was given a fixed single-line row height regardless of
    # heightForWidth() -- a QFormLayout row nested in the dialog's outer
    # QVBoxLayout via addLayout() does not participate in Qt's
    # height-for-width layout pass. Only the two scale-check messages
    # added this round are long enough to wrap to two lines; the
    # authority/units hints (one line each) were never affected.
    d = GridDialog(session)
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    d.origin_x.setValue(-9350837.227)  # lat ~36N -- a genuine REFUSE-level hint
    d.origin_y.setValue(4300621.372)
    assert "%" in d.crs_hint.text()
    d.adjustSize()
    d.show()
    try:
        # heightForWidth() at the label's actual width is what Qt itself
        # says the wrapped text needs; the clipping bug gave it less.
        needed = d.crs_hint.heightForWidth(d.crs_hint.width())
        assert d.crs_hint.height() >= needed
    finally:
        d.hide()


def test_form_columns_stay_aligned_across_the_split_form(session):
    # Fix round 5, Finding 4: splitting the form into form_top/form_bottom
    # around crs_hint (round 4's fix above) let each QFormLayout size its
    # own label column independently -- measured before this fix:
    # id_edit.x() == crs_widget.x() == 48 against origin_x.x() ==
    # azimuth.x() == 236, and crs_widget.width() == 665 against
    # azimuth.width() == 477. Every row's label is now built from one
    # shared width so both layouts' field columns line up regardless of
    # which form a given row is actually in.
    d = GridDialog(session)
    d.adjustSize()
    d.show()
    try:
        assert d.id_edit.x() == d.origin_x.x() == d.azimuth.x()
        assert d.crs_widget.x() == d.origin_x.x()
        assert d.crs_widget.width() == d.azimuth.width()
    finally:
        d.hide()


def test_grid_dialog_exec_is_guarded_by_default(session):
    # Task 9's autouse guard forbids QMessageBox/QFileDialog modals so a
    # test that trips one fails fast instead of hanging under
    # QT_QPA_PLATFORM=offscreen. GridDialog is the plugin's first real
    # QDialog, so the same guard must now cover QDialog.exec() too.
    d = GridDialog(session)
    with pytest.raises(AssertionError):
        d.exec()


# ---- plugin wiring ---------------------------------------------------------


def test_open_grid_dialog_accepts_and_adds_a_new_grid(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)

    dialog = _open(plugin)
    dialog.id_edit.setText("A")
    dialog.velocity.setValue(0.08)
    dialog.origin_x.setValue(10.0)
    dialog.origin_y.setValue(20.0)
    # Round 3, Finding 1: no fallback CRS any more -- this dialog's
    # crs_widget starts unset in this bare test harness (no project
    # CRS either), so a real user's OK button would stay disabled here
    # too until they pick one, exactly like
    # test_ok_is_blocked_until_id_and_velocity_are_set. accept()
    # bypasses that gating (nothing stops calling it directly, the way
    # this test does), so pick one explicitly to reflect what a real
    # user's flow requires, not incidentally re-prove Finding 2 (crs="").
    dialog.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32616"))
    dialog.accept()

    grid = plugin.session.grid("A")
    assert grid.origin == (10.0, 20.0)
    assert grid.velocity == VelocityModel.constant(0.08)
    assert grid.crs == "EPSG:32616"
    assert plugin._grid_dialog is None  # finished() cleared it
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_open_grid_dialog_cancel_leaves_the_session_untouched(fake_iface, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)

    dialog = _open(plugin)
    dialog.id_edit.setText("A")
    dialog.velocity.setValue(0.08)
    dialog.reject()

    assert plugin.session.site is not None and plugin.session.site.grids == []
    plugin.unload()


def test_open_grid_dialog_reports_a_duplicate_id_through_the_message_bar(
    fake_iface, tmp_path, answer_modal
):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(
        Grid(
            "A", (0.0, 0.0), 0.0, 1.0, 1.0, "EPSG:32616", 0.5, velocity=VelocityModel.constant(0.1)
        )
    )

    dialog = _open(plugin)
    dialog.id_edit.setText("A")
    dialog.velocity.setValue(0.08)
    dialog.accept()

    item = fake_iface.messageBar().currentItem()
    assert item is not None and "already exists" in item.text()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_open_grid_dialog_edits_an_existing_grid(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(
        Grid(
            "A",
            (1.0, 2.0),
            45.0,
            3.0,
            4.0,
            "EPSG:32616",
            0.25,
            velocity=VelocityModel.constant(0.1),
        )
    )

    dialog = _open(plugin, "A")
    assert dialog.id_edit.text() == "A" and not dialog.id_edit.isEnabled()
    dialog.azimuth.setValue(46.0)
    dialog.accept()

    assert plugin.session.grid("A").azimuth == pytest.approx(46.0)
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_open_grid_dialog_reports_a_stale_grid_id_without_crashing(fake_iface, tmp_path):
    # edit_grid_requested/grid_velocity_requested carry a grid id captured
    # off a context menu; open_grid_dialog is connected directly to both
    # (a QAction.triggered-style slot), so a ProjectError/KeyError raised
    # while looking the id up must not vanish into stderr.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)

    plugin.open_grid_dialog("does-not-exist")  # must not raise
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "does-not-exist" in item.text()
    plugin.unload()


def test_open_grid_dialog_does_not_open_a_second_dialog_while_one_is_open(fake_iface, tmp_path):
    # Fix round 4, Finding 1: modeless means the toolbar/dock stay
    # clickable while a grid dialog is open, unlike the old exec()'s
    # application-modal block -- so "Add grid" can be triggered again
    # before the first one closes. open_grid_dialog() must not open a
    # second one on top of the first (it would fight the first over the
    # canvas's one map tool during a map pick); it raises/activates the
    # existing one instead.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)

    first = _open(plugin)
    plugin.open_grid_dialog(None)
    assert plugin._grid_dialog is first  # no second dialog created

    first.reject()
    plugin.unload()


def test_open_grid_dialog_recovers_from_a_dialog_destroyed_outside_finished(fake_iface, tmp_path):
    # Fix round 5, Finding 6: finished() is the only path that is
    # *expected* to clear self._grid_dialog. Probed directly: destroying
    # the dialog some other way (setParent(None) + deleteLater(), which
    # bypasses finished() entirely) used to leave the tracker stale --
    # the next unload() would call reject() on an already-deleted C++
    # object (RuntimeError), and every later "Add grid" would wedge
    # forever calling show()/raise_() on it.
    import nsgeo_qgis
    from qgis.PyQt.QtWidgets import QApplication

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)

    dialog = _open(plugin)
    dialog.setParent(None)
    dialog.deleteLater()
    # sendPostedEvents(None, ...) flushes *every* object's queued
    # DeferredDelete in the whole process, not just this dialog's --
    # including ones left pending by earlier tests in the same run (their
    # own dialog.deleteLater() calls, never otherwise flushed). That
    # segfaults here, but not from anything this fix touches: it is the
    # pre-existing, out-of-scope object-leak this file already documents
    # (round 1, Finding 3's dialog leak; the map-tool leak noted in
    # plugin.py) becoming reachable only because this is the first
    # test to force a flush at all. Passing `dialog` as the receiver
    # restricts the flush to events actually posted to it, which is all
    # this test is testing.
    QApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)

    assert plugin._grid_dialog is None  # cleared by destroyed(), not finished()

    # And a later open/unload must not raise or wedge.
    plugin.open_grid_dialog(None)
    assert plugin._grid_dialog is not None and plugin._grid_dialog is not dialog
    plugin.unload()  # must not raise


def test_open_grid_dialog_seeds_velocity_from_the_header_dielectric(
    fake_iface, tmp_path, answer_modal
):
    # Fix round 1, Finding 6: one of the brief's two headline
    # requirements -- velocity is seeded from the first line's header
    # dielectric when the site already has lines -- had no test.
    import nsgeo_qgis
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from plugin_testing import synthetic_dzt

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    path = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")  # epsr 14.0
    plugin.session.add_lines([Line.open(path, GridPlacement("A", "y", 0.0, 0.0, 1, path.stem))])
    expected = VelocityModel.from_dielectric(14.0).surface_velocity

    # grid_id=None and no grids yet: open_grid_dialog's "new grid" path,
    # which is the one that seeds the suggestion.
    dialog = _open(plugin)
    # velocity is a 4-decimal QDoubleSpinBox, so setValue() itself
    # rounds -- compare at that precision, not the raw float's.
    assert dialog.velocity.value() == pytest.approx(expected, abs=5e-5)
    assert "dielectric" in dialog.velocity_hint.text().lower()

    dialog.reject()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_unload_closes_a_visible_grid_dialog(fake_iface, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)

    dialog = _open(plugin)
    assert dialog.isVisible()
    plugin.unload()
    assert plugin._grid_dialog is None


def test_finished_reports_when_the_site_closed_under_the_dialog(fake_iface, tmp_path):
    # Fix round 5, Finding 2(a): modeless means the toolbar stays
    # clickable while the dialog is open, so the site can be closed
    # before OK is clicked -- impossible under the old modal exec().
    # session.add_grid would then raise ProjectError ("no site is
    # open"), which is not in finished()'s except (ValueError, KeyError)
    # and has no outer handler -- it escaped to stderr with an empty
    # message bar, the dialog closing as if the grid had been saved.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)

    dialog = _open(plugin)
    dialog.id_edit.setText("A")
    dialog.velocity.setValue(0.08)
    dialog.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32616"))

    plugin.session.close_site()  # the site closes while the dialog is still open
    dialog.accept()  # must not raise

    item = fake_iface.messageBar().currentItem()
    assert item is not None and "no site is open" in item.text().lower()
    plugin.unload()


def test_finished_reports_when_a_different_site_was_opened_under_the_dialog(
    fake_iface, tmp_path, answer_modal
):
    # Fix round 5, Finding 2(b): probed editing grid A of site A, then
    # opening site B (which also defines its own grid A) while the
    # dialog was still open, then clicking OK -- B's A was silently
    # overwritten with A's geometry, no error at all. json_path
    # identifies which site session.add_grid/replace_grid would
    # actually act on; it changed under the dialog, so the edit must be
    # refused, not applied to whatever site happens to be open now.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()

    site_a = tmp_path / "site_a"
    site_a.mkdir()
    plugin.session.new_site(site_a)
    plugin.session.add_grid(
        Grid(
            "A",
            (999.0, 999.0),
            0.0,
            50.0,
            50.0,
            "EPSG:32616",
            0.5,
            velocity=VelocityModel.constant(0.1),
        )
    )

    dialog = _open(plugin, "A")  # editing site A's grid A
    dialog.azimuth.setValue(46.0)  # a real edit, so a leak-through would be visible

    site_b = tmp_path / "site_b"
    site_b.mkdir()
    plugin.session.new_site(site_b)  # a different site opened under the dialog
    plugin.session.add_grid(
        Grid(
            "A",
            (1.0, 2.0),
            45.0,
            3.0,
            4.0,
            "EPSG:32616",
            0.25,
            velocity=VelocityModel.constant(0.1),
        )
    )

    dialog.accept()  # OK, still believing it is editing site A's grid A

    # site B's own "A" must be untouched by site A's dialog.
    grid_b_a = plugin.session.grid("A")
    assert grid_b_a.origin == (1.0, 2.0) and grid_b_a.azimuth == 45.0
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "different site" in item.text().lower()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


# ---- pick on the map (#63) ---------------------------------------------------
#
# These are the digitise-flow tests Task 2 deleted with "Digitise on map",
# ported to the corner picks that replace it (spec §4.7: "the tests that pin
# those rules carry over rather than being deleted"). Each keeps the reason
# its original existed. The flows that click run on a shown 1 m/px canvas
# (`real_iface`) with G4 at (400, 300), so a pick can actually snap and the
# snap marker is actually drawn.

PICK_TEXT = "Click the {} corner. Right-click or Esc cancels."
PICK_ALL_TEXT = "Pick corners: click the {} corner ({} of 4). Right-click skips it, Esc stops."
POLYGON_TEXT = "Click the polygon to use. Right-click or Esc cancels."


def _pick_site(real_iface: Any, tmp_path: Any, crs: Any = UTM16, extent: Any = None) -> Any:
    """A plugin on a shown canvas (1 m/px over (0, 0)-(800, 600) by default)
    with G4 at (400, 300) on it, and its open dialog, corners in `crs`."""
    import nsgeo_qgis

    iface = real_iface(crs, extent or QgsRectangle(0, 0, 800, 600))
    plugin = nsgeo_qgis.classFactory(iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    gps = named_layer("Point", "gps", {"G4": (400, 300)})
    iface.mapCanvas().setLayers([gps])
    dialog = _open(plugin)
    dialog.corners_crs.setCrs(crs)
    return SimpleNamespace(
        iface=iface,
        plugin=plugin,
        canvas=iface.mapCanvas(),
        bar=iface.messageBar(),
        dialog=dialog,
        gps=gps,
    )


def _bar(bar: Any) -> list[str]:
    return [item.text() for item in bar.items()]


def _row(dialog: GridDialog, row: int) -> tuple[tuple[float, float], str] | None:
    point = dialog.corner_point(row)
    return None if point is None else ((point.x(), point.y()), dialog.corner_source(row))


def _scene_count(qgis_app: Any, canvas: Any) -> int:
    """Items in the canvas's QGraphicsScene, after any pending deleteLater().

    Counted off the scene, not off the tool: the snap marker is a
    QgsMapCanvasItem, so the scene -- not the tool, and not Python -- is
    what owns it. Dropping the tool's Python reference and collecting
    proves nothing; only the scene's own item list does. processEvents()
    does not run DeferredDelete, hence sendPostedEvents.
    """
    qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return len(canvas.scene().items())


def test_pick_flow_fills_the_row_and_restores_the_dialog(real_iface, tmp_path):
    # Ported from test_digitise_flow_through_the_plugin_fills_and_restores_the_dialog.
    # Fix round 4, Finding 1 (critical): this is the test that exposed the
    # bug. drive_dialog's exec() monkeypatch hid it completely: faking
    # exec() to just call a driver callback directly never runs Qt's real
    # application-modal event loop, so dialog.hide() never got the chance
    # to terminate it -- which is exactly what it does for real (verified
    # directly with a bare QDialog). No QDialog.exec anywhere in this test:
    # open_grid_dialog() calls show(), and this drives the real,
    # already-visible dialog exactly as a user would.
    t = _pick_site(real_iface, tmp_path)
    assert t.dialog.isVisible()
    # Something else in the main window has the keyboard focus, as a dock
    # often does in QGIS.
    elsewhere = t.plugin.survey_dock.findChild(QAbstractItemView)
    elsewhere.setFocus()
    assert t.iface.mainWindow().focusWidget() is elsewhere

    t.dialog.pick_buttons[1].click()
    assert t.dialog.isHidden()  # out of the way so the canvas can be clicked
    tool = t.canvas.mapTool()
    assert isinstance(tool, PickPointTool)
    assert _bar(t.bar) == [PICK_TEXT.format("+X")]
    # Esc reaches the tool only through the canvas's key events, so the
    # canvas is given the focus the hidden dialog had.
    assert t.iface.mainWindow().focusWidget() is t.canvas

    send_map_mouse(tool, "move", (408, 300))
    send_map_mouse(tool, "release", (408, 300))

    assert _row(t.dialog, 1) == ((400.0, 300.0), "G4 · gps")
    assert t.dialog.isVisible()  # the dialog is restored
    assert t.canvas.mapTool() is None  # the tool hands control back
    assert _bar(t.bar) == []
    t.dialog.reject()
    t.plugin.unload()


def test_pick_all_walks_the_corners_with_skip_and_stop(real_iface, tmp_path):
    # Spec §4.7: Pick all walks origin -> +X -> +X+Y -> +Y with "(n of 4)";
    # a right-click skips the corner and leaves its row as it was, Esc
    # stops and keeps what was picked.
    t = _pick_site(real_iface, tmp_path)
    t.dialog.pick_all_button.click()
    tool = t.canvas.mapTool()
    assert isinstance(tool, PickPointTool) and t.dialog.isHidden()
    texts = [_bar(t.bar)]
    send_map_mouse(tool, "release", (408, 300))  # origin: snaps to G4
    texts.append(_bar(t.bar))
    send_map_mouse(tool, "release", (200, 100), Qt.MouseButton.RightButton)  # skip +X
    texts.append(_bar(t.bar))
    send_map_mouse(tool, "release", (600, 500))  # +X+Y: a free click
    texts.append(_bar(t.bar))
    assert t.dialog.isHidden()  # still picking
    send_map_key(tool, Qt.Key.Key_Escape)  # stop before +Y

    assert texts == [
        [PICK_ALL_TEXT.format("origin", 1)],
        [PICK_ALL_TEXT.format("+X", 2)],
        [PICK_ALL_TEXT.format("+X+Y", 3)],
        [PICK_ALL_TEXT.format("+Y", 4)],
    ]
    assert [_row(t.dialog, r) for r in range(4)] == [
        ((400.0, 300.0), "G4 · gps"),
        None,
        ((600.0, 500.0), "free click"),
        None,
    ]
    assert t.dialog.isVisible() and t.canvas.mapTool() is None
    assert _bar(t.bar) == []
    t.dialog.reject()
    t.plugin.unload()


def test_pick_all_after_four_clicks_does_not_fit(real_iface, tmp_path):
    # C1: Fit runs only when Fit is pressed. Four picks fill four rows and
    # bring the dialog back; the form is untouched.
    t = _pick_site(real_iface, tmp_path)
    t.dialog.pick_all_button.click()
    tool = t.canvas.mapTool()
    corners = [(100.0, 100.0), (300.0, 100.0), (300.0, 250.0), (100.0, 250.0)]
    for xy in corners:
        send_map_mouse(tool, "release", xy)

    assert [_row(t.dialog, r) for r in range(4)] == [(xy, "free click") for xy in corners]
    assert (t.dialog.origin_x.value(), t.dialog.origin_y.value()) == (0.0, 0.0)
    assert t.dialog.fit_status.text() == ""
    assert t.dialog.isVisible() and t.canvas.mapTool() is None
    assert _bar(t.bar) == []
    t.dialog.reject()
    t.plugin.unload()


def test_single_pick_right_click_restores_the_dialog_untouched(real_iface, tmp_path):
    # Ported from test_digitise_flow_right_click_restores_the_dialog_without_a_pick.
    # Fix round 1, Finding 4: before that fix, a right-click meant to
    # cancel instead completed the pick (or set the origin), and there was
    # no way back short of killing QGIS if the pick was abandoned.
    t = _pick_site(real_iface, tmp_path)
    t.dialog.set_corner(1, QgsPointXY(10.0, 20.0), UTM16, "typed")
    t.dialog.pick_buttons[1].click()
    tool = t.canvas.mapTool()
    send_map_mouse(tool, "move", (408, 300))
    send_map_mouse(tool, "release", (408, 300), Qt.MouseButton.RightButton)  # cancel

    assert t.canvas.mapTool() is None
    assert t.dialog.isVisible()  # restored -- without completing the pick
    assert _row(t.dialog, 1) == ((10.0, 20.0), "typed")  # untouched
    assert _bar(t.bar) == []
    t.dialog.reject()
    t.plugin.unload()


def test_switching_map_tools_mid_pick_restores_the_dialog(real_iface, tmp_path):
    # Ported from test_digitise_flow_switching_map_tools_restores_the_dialog.
    # Fix round 1, Finding 4: switching to a completely different map tool
    # (e.g. Pan) mid-pick used to leave the dialog hidden forever, since
    # only a completed pick ever restored it.
    from qgis.gui import QgsMapToolPan

    t = _pick_site(real_iface, tmp_path)
    t.dialog.pick_all_button.click()
    assert t.dialog.isHidden()
    pan = QgsMapToolPan(t.canvas)
    t.canvas.setMapTool(pan)

    assert t.dialog.isVisible()
    assert t.canvas.mapTool() is pan  # the user's choice of tool stands
    assert _bar(t.bar) == []
    t.canvas.unsetMapTool(pan)
    t.dialog.reject()
    t.plugin.unload()


@pytest.mark.parametrize("breaks", ["the tool", "the dialog"])
def test_a_pick_that_fails_says_so_and_restores_the_dialog(real_iface, tmp_path, breaks):
    # However a pick ends, an exception included, the tool is released,
    # the instruction leaves the message bar and the dialog comes back --
    # and the failure is said, not swallowed by Qt (conftest's
    # _no_swallowed_slot_exceptions would fail this test if it were).
    t = _pick_site(real_iface, tmp_path)
    t.dialog.pick_buttons[0].click()
    tool = t.canvas.mapTool()

    def broken(*_args: object) -> None:
        raise RuntimeError("it broke")

    if breaks == "the tool":
        tool._snap = broken  # inside the tool's own canvasReleaseEvent
    else:
        t.dialog.set_corner = broken  # inside plugin.py's `picked` slot
    send_map_mouse(tool, "release", (100, 100))

    assert t.dialog.isVisible() and t.canvas.mapTool() is None
    assert _row(t.dialog, 0) is None
    texts = _bar(t.bar)
    assert len(texts) == 1 and "it broke" in texts[0]  # the error, not the instruction
    t.dialog.reject()
    t.plugin.unload()


def test_a_pick_that_cannot_be_converted_ends_and_says_why(real_iface, tmp_path):
    # A click set_corner cannot convert into "Corners in" ends the pick
    # rather than silently staying on the same corner with the dialog
    # hidden: the dialog comes back, its status line saying why. Latitude
    # 95 is outside every CRS (see test_set_corner_converts_from_its_own_crs_...).
    t = _pick_site(real_iface, tmp_path, crs=WGS84, extent=QgsRectangle(-0.4, 94.7, 0.4, 95.3))
    t.dialog.corners_crs.setCrs(UTM16)
    t.dialog.pick_all_button.click()
    tool = t.canvas.mapTool()
    event = send_map_mouse(tool, "release", QPoint(400, 300))
    assert event.mapPoint().y() > 90

    assert t.dialog.isVisible() and t.canvas.mapTool() is None
    assert _bar(t.bar) == []
    assert [_row(t.dialog, r) for r in range(4)] == [None] * 4
    assert t.dialog.fit_status.text() == "could not convert that point into EPSG:32616"
    t.dialog.reject()
    t.plugin.unload()


def test_a_pick_on_a_4326_canvas_lands_converted(real_iface, tmp_path):
    # The canvas reports its clicks in its own CRS; the row is in "Corners
    # in". A free click on a WGS84 canvas lands in UTM16 rows as exactly the
    # transform of the clicked point.
    t = _pick_site(real_iface, tmp_path, crs=WGS84, extent=_site_extent(WGS84))
    t.canvas.setLayers([])
    t.dialog.corners_crs.setCrs(UTM16)
    t.dialog.pick_buttons[0].click()
    tool = t.canvas.mapTool()
    event = send_map_mouse(tool, "release", QPoint(400, 300))

    expected = QgsCoordinateTransform(WGS84, UTM16, QgsProject.instance()).transform(
        event.mapPoint()
    )
    got = t.dialog.corner_point(0)
    assert got is not None
    assert got.x() == pytest.approx(expected.x(), abs=1e-6)
    assert got.y() == pytest.approx(expected.y(), abs=1e-6)
    assert got.distance(QgsPointXY(*SITE.origin)) < 400  # and it is near the site
    t.dialog.reject()
    t.plugin.unload()


def test_pick_polygon_on_map_selects_layer_and_feature(qgis_app, real_iface, tmp_path):
    # C5 (#28): picking a polygon on the map chooses it in the layer and
    # feature lists, which is what Fill then reads. The clicked feature is
    # the layer's second, so a fid mix-up would show.
    t = _pick_site(real_iface, tmp_path)
    plots = named_layer(
        "Polygon",
        "plots",
        {"west": [(0, 0), (50, 0), (50, 50)], "east": [(300, 200), (500, 200), (500, 400)]},
    )
    QgsProject.instance().addMapLayer(plots)
    try:
        east = feature_id(plots, "east")
        t.canvas.setLayers([t.gps, plots])
        t.dialog.pick_polygon_button.click()
        tool = t.canvas.mapTool()
        assert isinstance(tool, PickPointTool) and t.dialog.isHidden()
        assert _bar(t.bar) == [POLYGON_TEXT]

        send_map_mouse(tool, "release", (450, 300))  # inside "east"

        assert t.dialog.isVisible() and t.canvas.mapTool() is None
        assert _bar(t.bar) == []
        assert t.dialog.layer_combo.currentLayer() is plots
        assert _pump(qgis_app, lambda: t.dialog.feature_picker.feature().id() == east)
        chosen = t.dialog.chosen_polygon()
        assert chosen is not None and chosen[0] is plots
        assert chosen[1].asWkt() == plots.getFeature(east).geometry().asWkt()
        t.dialog.reject()
        t.plugin.unload()
    finally:
        QgsProject.instance().removeMapLayer(plots.id())


def test_open_grid_dialog_releases_a_stranded_map_tool_on_close(fake_iface, tmp_path):
    # Ported. Fix round 2, Finding 4: the dialog can finish (accept,
    # reject, or the window closed outright) while a pick is still in
    # progress, with neither a click nor the tool's own cancelled signal
    # ever having fired to release it -- e.g. a keyboard shortcut, or (as
    # simulated here) a caller that just gives up on the pick without
    # clicking the map or right-clicking to abort. Before that fix this
    # left a live map tool wired to a `dialog` open_grid_dialog was about
    # to delete; a later click on it raised RuntimeError out of a
    # signal-connected slot.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    canvas = fake_iface.mapCanvas()

    dialog = _open(plugin)
    dialog.pick_buttons[0].click()
    assert isinstance(canvas.mapTool(), PickPointTool)
    dialog.reject()  # gives up on the pick entirely, tool still active -- must not raise

    assert canvas.mapTool() is None  # released, not left stranded
    assert _bar(fake_iface.messageBar()) == []  # and its instruction with it
    plugin.unload()


def test_open_grid_dialog_releases_a_stranded_tool_on_accept_without_flashing_the_dialog(
    fake_iface, tmp_path, answer_modal
):
    # Ported. Fix round 3, Finding 3: releasing a still-active pick tool in
    # finished()'s cleanup (round 2, Finding 4's fix) runs unsetMapTool()
    # -> deactivate() -> cancelled -> the pick's own ending, which would
    # otherwise re-show `dialog` -- already accepted here -- for one
    # event-loop turn before deleteLater() actually destroys it.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    canvas = fake_iface.mapCanvas()

    dialog = _open(plugin)
    dialog.pick_all_button.click()
    assert isinstance(canvas.mapTool(), PickPointTool)
    assert dialog.isHidden()
    dialog.id_edit.setText("A")
    dialog.velocity.setValue(0.08)
    dialog.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32616"))
    dialog.accept()  # accepted mid-pick, tool still active -- must not raise

    assert canvas.mapTool() is None  # released
    assert dialog.isHidden()  # never re-shown after being accepted
    assert _bar(fake_iface.messageBar()) == []
    assert plugin.session.grid("A").crs == "EPSG:32616"
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_open_grid_dialog_shows_the_existing_dialog_even_if_hidden_mid_pick(fake_iface, tmp_path):
    # Ported. Fix round 5, Finding 5: re-triggering "Add grid" while the
    # dialog is hidden (a pick in progress -- _start_pick() hides it
    # deliberately) used to call only raise_()/activateWindow(), not
    # show(): a hidden window raised and activated is still invisible, so
    # the user got no window and no message at all.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)

    dialog = _open(plugin)
    dialog.pick_buttons[0].click()  # hides the dialog, arms the tool
    assert dialog.isHidden()

    plugin.open_grid_dialog(None)  # "Add grid" clicked again
    assert plugin._grid_dialog is dialog  # still the same dialog...
    assert dialog.isVisible()  # ...but now actually visible again

    dialog.reject()
    plugin.unload()


def test_a_pick_started_while_one_runs_replaces_it(real_iface, tmp_path, qgis_app):
    # The dialog re-shown mid-pick (above) has live Pick buttons. Pressing
    # one ends the running pick before the new one hides the dialog --
    # otherwise the old pick's ending would show the dialog again in the
    # middle of the new pick, and its instruction would stay up.
    t = _pick_site(real_iface, tmp_path)
    t.dialog.pick_buttons[0].click()
    first = t.canvas.mapTool()
    t.plugin.open_grid_dialog(None)
    assert t.dialog.isVisible()

    t.dialog.pick_buttons[2].click()
    second = t.canvas.mapTool()
    assert isinstance(second, PickPointTool) and second is not first
    assert t.dialog.isHidden()
    assert _bar(t.bar) == [PICK_TEXT.format("+X+Y")]
    send_map_mouse(second, "release", (408, 300))

    assert [_row(t.dialog, r) for r in range(4)] == [
        None,
        None,
        ((400.0, 300.0), "G4 · gps"),
        None,
    ]
    assert t.dialog.isVisible() and t.canvas.mapTool() is None
    assert _bar(t.bar) == []
    t.dialog.reject()
    t.plugin.unload()


def test_unload_closes_a_dialog_hidden_mid_pick(fake_iface, tmp_path):
    # Ported from test_unload_closes_a_dialog_hidden_mid_digitise_pick.
    # Fix round 5, Finding 1: QDialog::closeEvent only calls reject() when
    # the dialog isVisible() -- close() on a hidden one just accepts the
    # close event, and finished() never fires at all (verified directly on
    # a bare QDialog: hidden + close() -> 0 finished emissions; hidden +
    # reject() -> 1). Hidden mid-pick is this feature's *ordinary* state --
    # _start_pick() hides the dialog deliberately so the canvas can be
    # clicked -- so unload() must work in exactly the state its own
    # feature creates, not only the visible one. Left unfixed, this was
    # user-reachable (not merely a leak): a canvas click would re-show the
    # orphaned dialog over an unloaded plugin, and clicking OK would raise
    # AttributeError on self.session (already None), swallowed to stderr
    # -- the dialog closing as if the grid were saved when nothing was.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    canvas = fake_iface.mapCanvas()

    dialog = _open(plugin)
    dialog.pick_buttons[0].click()
    assert dialog.isHidden()
    assert isinstance(canvas.mapTool(), PickPointTool)

    plugin.unload()

    assert plugin._grid_dialog is None
    assert canvas.mapTool() is None
    assert _bar(fake_iface.messageBar()) == []


def test_completed_picks_leave_no_canvas_items(real_iface, tmp_path, qgis_app):
    # Ported from test_completed_digitise_picks_do_not_pile_rubber_bands_into_the_scene.
    # Final review, I4: a map tool's canvas items belong to the canvas's
    # QGraphicsScene, and the old flow only ever called unsetMapTool(),
    # which frees neither the tool nor them. Three attempts left three
    # items behind -- invisible, but exactly the object plugin.py's round-1
    # note implicates in a shutdown segfault "once enough of them pile up
    # alongside a QgsMapCanvas". Here the item is the snap marker, so each
    # pick first moves onto G4 to put one on the map. The tool itself must
    # go too (deleteLater), not only its marker.
    t = _pick_site(real_iface, tmp_path)
    baseline = _scene_count(qgis_app, t.canvas)
    tools = []
    for row in range(3):
        t.dialog.pick_buttons[row].click()
        tool = t.canvas.mapTool()
        tools.append(tool)
        send_map_mouse(tool, "move", (408, 300))
        assert _scene_count(qgis_app, t.canvas) == baseline + 1  # the marker is drawn
        send_map_mouse(tool, "release", (408, 300))
    assert _scene_count(qgis_app, t.canvas) == baseline
    assert all(sip.isdeleted(tool) for tool in tools)
    assert _bar(t.bar) == []
    t.dialog.reject()
    t.plugin.unload()


@pytest.mark.parametrize("abort", ["right-click", "esc", "switch tools"])
def test_an_aborted_pick_leaves_no_canvas_items(real_iface, tmp_path, qgis_app, abort):
    # Ported from test_an_aborted_digitise_pick_gives_its_rubber_band_back.
    # An abort reaches the plugin through a different signal from a
    # completed pick (skipped, stopped, cancelled), so each is a separate
    # finaliser and needs the disposal of its own.
    from qgis.gui import QgsMapToolPan

    t = _pick_site(real_iface, tmp_path)
    baseline = _scene_count(qgis_app, t.canvas)
    t.dialog.pick_buttons[0].click()
    tool = t.canvas.mapTool()
    send_map_mouse(tool, "move", (408, 300))
    assert _scene_count(qgis_app, t.canvas) == baseline + 1
    pan = QgsMapToolPan(t.canvas)
    if abort == "right-click":
        send_map_mouse(tool, "release", (408, 300), Qt.MouseButton.RightButton)
    elif abort == "esc":
        send_map_key(tool, Qt.Key.Key_Escape)
    else:
        t.canvas.setMapTool(pan)

    assert t.dialog.isVisible()  # round 1, Finding 4 still holds
    assert _scene_count(qgis_app, t.canvas) == baseline
    assert sip.isdeleted(tool)
    assert _bar(t.bar) == []
    if t.canvas.mapTool() is pan:
        t.canvas.unsetMapTool(pan)
    t.dialog.reject()
    t.plugin.unload()


def test_a_dialog_closed_mid_pick_leaves_no_canvas_items(real_iface, tmp_path, qgis_app):
    # Ported from test_a_dialog_closed_mid_pick_gives_the_rubber_band_back.
    # The third finaliser: open_grid_dialog()'s finished() teardown, which
    # blockSignals(True)s the tool precisely so `cancelled` does NOT run
    # (round 3, Finding 3) -- so it cannot lean on the cancelled path's
    # disposal, or its popping of the message, and must do its own.
    t = _pick_site(real_iface, tmp_path)
    baseline = _scene_count(qgis_app, t.canvas)
    t.dialog.pick_buttons[0].click()
    tool = t.canvas.mapTool()
    send_map_mouse(tool, "move", (408, 300))
    assert _scene_count(qgis_app, t.canvas) == baseline + 1
    t.dialog.reject()  # gives up on the pick outright, tool still active

    assert t.canvas.mapTool() is None
    # the baseline held the dialog's overlay item too, which went with it
    assert _scene_count(qgis_app, t.canvas) == baseline - 1
    assert sip.isdeleted(tool)
    assert _bar(t.bar) == []
    t.plugin.unload()


# ---- one corner table and Fit (#63) ------------------------------------------


def _utm_dialog(session) -> GridDialog:
    d = GridDialog(session)
    d.crs_widget.setCrs(UTM16)
    d.corners_crs.setCrs(UTM16)
    return d


def _type_row(d: GridDialog, row: int, e: float, n: float) -> None:
    d.corner_table.item(row, COL_A).setText(f"{e:.6f}")
    d.corner_table.item(row, COL_B).setText(f"{n:.6f}")


def _type_site(d: GridDialog) -> None:
    for row, (e, n) in enumerate(SITE_CORNERS):
        _type_row(d, row, e, n)


def test_the_dialog_has_one_corner_table_and_no_tabs(session):
    d = GridDialog(session)
    assert not hasattr(d, "tabs")
    assert not hasattr(d, "digitise_requested")
    assert [d.corner_table.item(r, COL_ROLE).text() for r in range(4)] == [
        "origin",
        "+X",
        "+X+Y",
        "+Y",
    ]


def test_typed_corners_fit_the_grid(session):
    d = _utm_dialog(session)
    _type_site(d)
    d.fit_corners()
    assert d.origin_x.value() == pytest.approx(SITE.origin[0], abs=1e-6)
    assert d.origin_y.value() == pytest.approx(SITE.origin[1], abs=1e-6)
    assert d.azimuth.value() == pytest.approx(10.0, abs=1e-6)
    assert d.size_x.value() == pytest.approx(20.0, abs=1e-6)
    assert d.size_y.value() == pytest.approx(20.0, abs=1e-6)
    assert d.fit_status.text() == "rigid fit RMS 0.000 m from 4 corners"
    assert all(o is not None and o < 1e-6 for o in d.corner_offsets())
    assert [d.corner_source(r) for r in range(4)] == ["typed"] * 4
    # a box Fit wrote is not "typed"; Use these keeps it that way, so a
    # second Fit on different corners overwrites both
    assert d.sizes_typed() == (False, False)
    d.use_measured_size()
    for row, (e, n) in enumerate(
        SITE.to_world(np.array([[0, 0], [30, 0], [30, 25], [0, 25]], float))
    ):
        _type_row(d, row, e, n)
    d.fit_corners()
    assert d.size_x.value() == pytest.approx(30.0, abs=1e-6)
    assert d.size_y.value() == pytest.approx(25.0, abs=1e-6)
    assert d.sizes_typed() == (False, False)


def test_a_typed_size_survives_fit_and_the_grid_stays_pinned_at_the_origin(session):
    d = _utm_dialog(session)
    d.size_x.setValue(18.0)
    _type_site(d)
    d.fit_corners()
    assert d.size_x.value() == 18.0
    assert d.size_y.value() == pytest.approx(20.0, abs=1e-6)
    assert d.origin_x.value() == pytest.approx(SITE.origin[0], abs=1e-6)
    assert d.origin_y.value() == pytest.approx(SITE.origin[1], abs=1e-6)
    assert d.corner_offsets() == pytest.approx([0, 2, 2, 0], abs=1e-6)
    assert not d.size_hint.isHidden()
    assert d.size_hint.text() == "the corners measure 20.00 × 20.00 m · your size is kept"
    d.use_measured_size()
    assert d.size_x.value() == pytest.approx(20.0, abs=1e-6)
    assert d.sizes_typed() == (False, False)
    assert d.size_hint.isHidden()


def test_fit_does_not_depend_on_typed_sizes(session):
    d = _utm_dialog(session)
    _type_site(d)
    d.fit_corners()
    first = (d.origin_x.value(), d.origin_y.value(), d.azimuth.value())
    d.size_x.setValue(7.0)
    d.size_y.setValue(9.0)
    d.fit_corners()
    assert (d.origin_x.value(), d.origin_y.value(), d.azimuth.value()) == pytest.approx(first)
    assert (d.size_x.value(), d.size_y.value()) == (7.0, 9.0)


def test_an_existing_grid_opens_with_both_sizes_typed(session):
    # 10 x 10 is the spin boxes' own default, so _prefill's setValue emits no
    # valueChanged: only the explicit marking makes these typed
    d = GridDialog(session, Grid("T", (500.0, 700.0), 30.0, 10.0, 10.0, "EPSG:32616", 0.5))
    assert d.sizes_typed() == (True, True)
    assert GridDialog(session).sizes_typed() == (False, False)


def test_off_by_follows_the_form_without_a_refit(session):
    d = _utm_dialog(session)
    _type_site(d)
    d.fit_corners()
    status = d.fit_status.text()
    d.azimuth.setValue(11.0)
    offsets = d.corner_offsets()
    assert all(o is not None and o > 0.1 for o in offsets[1:])
    assert d.fit_status.text() == status
    d.origin_x.setValue(0.0)
    d.origin_y.setValue(0.0)
    assert d.corner_offsets() == [None] * 4


def test_fit_refuses_coincident_corners(session):
    d = _utm_dialog(session)
    d.origin_x.setValue(111.0)
    _type_row(d, 0, *SITE_CORNERS[0])
    _type_row(d, 1, *SITE_CORNERS[0])
    d.fit_corners()
    assert "coincide" in d.fit_status.text()
    assert d.origin_x.value() == 111.0


def test_fit_refuses_mirrored_corners(session):
    d = _utm_dialog(session)
    for row, src in zip(range(4), (0, 3, 2, 1)):
        _type_row(d, row, *SITE_CORNERS[src])
    d.fit_corners()
    assert "mirrored" in d.fit_status.text()


def test_fit_needs_a_metric_grid_crs(session):
    d = _utm_dialog(session)
    _type_site(d)
    d.crs_widget.setCrs(WGS84)
    d.fit_corners()
    assert "metric CRS" in d.fit_status.text()
    assert d.origin_x.value() == 0.0


def test_a_non_number_cell_reports_and_leaves_the_row_empty(session):
    d = _utm_dialog(session)
    d.corner_table.item(0, COL_A).setText("518204,112")
    assert d.corner_point(0) is None
    assert "origin" in d.fit_status.text()
    assert "not a number" in d.fit_status.text()


def test_changing_corners_in_converts_the_points(session):
    d = _utm_dialog(session)
    _type_site(d)
    d.corners_crs.setCrs(WGS84)
    to_wgs = QgsCoordinateTransform(UTM16, WGS84, QgsProject.instance())
    want = to_wgs.transform(QgsPointXY(*SITE_CORNERS[0]))
    got = d.corner_point(0)
    assert got.x() == pytest.approx(want.x(), abs=1e-9)
    assert got.y() == pytest.approx(want.y(), abs=1e-9)
    heads = [d.corner_table.horizontalHeaderItem(c).text() for c in (COL_A, COL_B)]
    assert heads == ["lon", "lat"]
    d.corners_crs.setCrs(UTM16)
    back = d.corner_point(0)
    assert back.x() == pytest.approx(SITE_CORNERS[0][0], abs=1e-6)
    assert back.y() == pytest.approx(SITE_CORNERS[0][1], abs=1e-6)
    heads = [d.corner_table.horizontalHeaderItem(c).text() for c in (COL_A, COL_B)]
    assert heads == ["E", "N"]


def test_a_geographic_corners_crs_shows_eight_decimals_and_keeps_full_precision(session):
    d = _utm_dialog(session)
    d.corners_crs.setCrs(WGS84)
    d.set_corner(0, QgsPointXY(-86.123456789012, 36.123456789012), WGS84, "typed")
    assert d.corner_table.item(0, COL_A).text() == "-86.12345679"
    assert d.corner_point(0).x() == -86.123456789012
    # editing the other cell must not round this one
    d.corner_table.item(0, COL_B).setText("36.5")
    assert d.corner_point(0).x() == -86.123456789012
    assert d.corner_point(0).y() == 36.5


def test_set_corner_converts_from_its_own_crs_and_reports_a_failed_transform(session):
    d = _utm_dialog(session)
    lonlat = QgsCoordinateTransform(UTM16, WGS84, QgsProject.instance()).transform(
        QgsPointXY(*SITE_CORNERS[0])
    )
    assert d.set_corner(0, lonlat, WGS84, "free click")
    assert d.corner_point(0).x() == pytest.approx(SITE_CORNERS[0][0], abs=1e-3)
    assert d.corner_source(0) == "free click"
    # latitude 95 is outside every CRS: the transform raises, the row stays as it was
    before = d.corner_point(0)
    assert not d.set_corner(0, QgsPointXY(0.0, 95.0), WGS84, "free click")
    assert d.corner_point(0) == before
    assert d.fit_status.text() == "could not convert that point into EPSG:32616"


def test_rotate_carries_sources_and_swaps_typed_sizes(session):
    d = _utm_dialog(session)
    _type_row(d, 0, *SITE_CORNERS[0])
    _type_row(d, 2, *SITE_CORNERS[2])
    d.size_x.setValue(30.0)  # only size_x is typed; size_y stays at its default 10
    d.rotate_corners()
    assert d.corner_point(1).x() == pytest.approx(SITE_CORNERS[2][0])
    assert d.corner_point(0) is None and d.corner_point(2) is None
    assert d.corner_point(3).x() == pytest.approx(SITE_CORNERS[0][0])
    assert (d.size_x.value(), d.size_y.value()) == (10.0, 30.0)
    assert d.sizes_typed() == (False, True)
    assert d.corner_table.item(1, COL_FROM).text() == "typed"


def test_clear_empties_every_row_and_leaves_the_form(session):
    d = _utm_dialog(session)
    d.id_edit.setText("keep")
    d.size_x.setValue(33.0)
    _type_site(d)
    d.clear_corners()
    assert all(d.corner_point(r) is None for r in range(4))
    assert all(d.corner_table.item(r, c).text() == "" for r in range(4) for c in (COL_A, COL_B))
    assert d.id_edit.text() == "keep"
    assert d.size_x.value() == 33.0


def test_corners_changed_fires_on_every_row_change(session):
    d = _utm_dialog(session)
    d.set_corner(0, QgsPointXY(*SITE_CORNERS[0]), UTM16, "typed")
    seen: list[int] = []
    d.corners_changed.connect(lambda: seen.append(1))
    d.corner_table.item(0, COL_A).setText("518205.000")
    assert len(seen) == 1
    d.set_corner(1, QgsPointXY(*SITE_CORNERS[1]), UTM16, "typed")
    assert len(seen) == 2
    d.rotate_corners()
    assert len(seen) == 3
    d.clear_corners()
    assert len(seen) == 4


def test_only_fit_fits(session):
    d = _utm_dialog(session)
    _type_site(d)
    d.rotate_corners()
    d.clear_corners()
    _type_site(d)
    assert (d.origin_x.value(), d.origin_y.value(), d.azimuth.value()) == (0.0, 0.0, 0.0)


def test_corners_in_starts_on_the_project_crs_or_wgs84(session, project_crs):
    project_crs(UTM16)
    assert GridDialog(session).corners_crs.crs() == UTM16
    project_crs(QgsCoordinateReferenceSystem())
    assert GridDialog(session).corners_crs.crs() == WGS84


def test_fit_status_keeps_the_last_fit_line_through_row_changes(session):
    d = _utm_dialog(session)
    _type_site(d)
    d.fit_corners()
    line = d.fit_status.text()
    measured = d.measured_size()
    d.corner_table.item(0, COL_A).setText(f"{SITE_CORNERS[0][0] + 1.0:.6f}")  # a real edit
    assert d.corner_point(0).x() == pytest.approx(SITE_CORNERS[0][0] + 1.0)
    assert d.fit_status.text() == line
    d.rotate_corners()
    assert d.fit_status.text() == line
    assert d.measured_size() == (measured[1], measured[0])
    d.corners_crs.setCrs(WGS84)
    assert d.fit_status.text() == line
    assert d.measured_size() == (measured[1], measured[0])
    # an error covers the line; the next good edit brings it back
    d.corner_table.item(0, COL_A).setText("x")
    assert "not a number" in d.fit_status.text()
    d.corner_table.item(0, COL_A).setText("-86.0")
    assert d.fit_status.text() == line
    d.clear_corners()
    assert d.fit_status.text() == ""
    assert d.measured_size() is None


def test_a_refused_fit_line_also_survives_a_row_change(session):
    d = _utm_dialog(session)
    _type_row(d, 0, *SITE_CORNERS[0])
    d.fit_corners()
    refusal = d.fit_status.text()
    assert refusal
    d.set_corner(1, QgsPointXY(*SITE_CORNERS[1]), UTM16, "typed")
    assert d.fit_status.text() == refusal


def test_a_half_filled_row_reads_as_empty_and_blocks_fit(session):
    d = _utm_dialog(session)
    for row in (0, 2, 3):
        _type_row(d, row, *SITE_CORNERS[row])
    d.corner_table.item(1, COL_A).setText(f"{SITE_CORNERS[1][0]:.6f}")
    assert d.corner_point(1) is None
    assert d.fit_status.text() == "+X: needs both coordinates"
    d.fit_corners()
    assert d.fit_status.text() == "+X has only one coordinate: fill both or clear it"
    assert d.origin_x.value() == 0.0


def test_fit_refuses_a_row_whose_text_did_not_parse(session):
    d = _utm_dialog(session)
    for row in (1, 2, 3):
        _type_row(d, row, *SITE_CORNERS[row])
    d.corner_table.item(0, COL_A).setText("518204,112")
    d.corner_table.item(0, COL_B).setText(f"{SITE_CORNERS[0][1]:.6f}")
    assert d.corner_point(0) is None
    d.fit_corners()
    assert d.fit_status.text() == "origin: '518204,112' is not a number: fix it or clear the row"
    assert d.origin_x.value() == 0.0
    assert d.measured_size() is None


def _lonlat_typed(d: GridDialog) -> None:
    for row, p in enumerate(_wgs84_ring()):
        _type_row(d, row, p.x(), p.y())


def test_degrees_typed_as_metres_are_refused(session):
    d = _utm_dialog(session)
    _lonlat_typed(d)
    d.fit_corners()
    text = d.fit_status.text()
    assert text.startswith("the corners are only 0.") and text.endswith(
        " m apart in EPSG:32616: check that Corners in is the CRS they were measured in"
    )
    assert (d.origin_x.value(), d.origin_y.value(), d.azimuth.value()) == (0.0, 0.0, 0.0)
    assert (d.size_x.value(), d.size_y.value()) == (10.0, 10.0)
    assert d.crs_widget.crs() == UTM16
    assert d.measured_size() is None


def test_degrees_typed_as_metres_leave_an_existing_grid_alone(session):
    grid = dataclasses.replace(SITE, velocity=VelocityModel.constant(0.08))
    session.add_grid(grid)
    d = GridDialog(session, grid=grid)
    d.corners_crs.setCrs(UTM16)
    assert d.sizes_typed() == (True, True)
    _lonlat_typed(d)
    d.fit_corners()
    assert d.fit_status.text().startswith("the corners are only ")
    assert d.result_grid() == grid


def test_fill_refuses_a_layer_without_a_crs(qgis_app, session, plan_layer):
    layer = plan_layer(_wgs84_ring())
    layer.setCrs(QgsCoordinateReferenceSystem())
    assert not layer.crs().isValid()
    d = _utm_dialog(session)
    d.set_corner(0, QgsPointXY(*SITE_CORNERS[0]), UTM16, "typed")
    _select_sole_feature(qgis_app, d, layer)
    d.fill_from_polygon()
    assert d.fit_status.text() == "plan has no CRS: set one in its Layer Properties"
    assert d.corner_source(0) == "typed"
    assert d.corner_point(1) is None


def test_metres_typed_under_lon_lat_are_refused_as_such(session):
    d = _utm_dialog(session)
    d.corners_crs.setCrs(WGS84)
    _type_site(d)
    d.fit_corners()
    assert d.fit_status.text() == (
        "these are not longitudes and latitudes: "
        "check that Corners in is the CRS they were measured in"
    )
    assert d.origin_x.value() == 0.0
    assert d._lonlat(QgsPointXY(0.0, 91.0), WGS84) is None
    assert d._lonlat(QgsPointXY(181.0, 0.0), WGS84) is None


def test_a_refused_fit_puts_an_automatic_crs_back(session, project_crs, real_canvas):
    project_crs(UTM16)
    d = GridDialog(session, canvas=real_canvas(UTM16, _site_extent(UTM16)))
    d.origin_x.setValue(SITE.origin[0])
    d.origin_y.setValue(SITE.origin[1])
    d.azimuth.setValue(10.0)
    anchor = d._anchor
    d.corners_crs.setCrs(WGS84)
    mirrored = ((0, 0), (0, 0.0002), (0.0002, 0.0002), (0.0002, 0))
    for row, (dx, dy) in enumerate(mirrored):
        d.set_corner(row, QgsPointXY(-70.0 + dx, 36.0 + dy), WGS84, "typed")
    d.fit_corners()
    assert "mirrored" in d.fit_status.text()
    assert d.crs_widget.crs().authid() == "EPSG:32616"
    assert d.crs_is_auto()
    assert (d.origin_x.value(), d.origin_y.value(), d.azimuth.value()) == (
        SITE.origin[0],
        SITE.origin[1],
        10.0,
    )
    assert d._anchor == anchor


def test_a_successful_automatic_switch_clears_a_stale_hand_pick_message(
    session, project_crs, real_canvas
):
    project_crs(UTM16)
    d = GridDialog(session, canvas=real_canvas(UTM16, _site_extent(UTM16)))
    d.origin_x.setValue(1e8)  # outside UTM 16N's domain: the hand pick cannot convert
    d.origin_y.setValue(1e8)
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32617"))
    assert "could not convert" in d.crs_hint.text()
    d.origin_x.setValue(0.0)
    d.origin_y.setValue(0.0)
    d.corners_crs.setCrs(WGS84)
    for row, (dx, dy) in enumerate(((0, 0), (0.0002, 0), (0.0002, 0.0002), (0, 0.0002))):
        d.set_corner(row, QgsPointXY(-70.0 + dx, 36.0 + dy), WGS84, "typed")
    d.fit_corners()
    assert d.crs_widget.crs().authid() == "EPSG:32619"
    assert "could not convert" not in d.crs_hint.text()


def test_an_automatic_switch_that_cannot_convert_says_so(session, project_crs, real_canvas):
    project_crs(UTM16)
    d = GridDialog(session, canvas=real_canvas(UTM16, _site_extent(UTM16)))
    d.origin_x.setValue(1e8)
    d.origin_y.setValue(1e8)
    d._apply_auto_crs(QgsCoordinateReferenceSystem("EPSG:32617"), "")
    assert "could not convert the grid into EPSG:32617" in d.crs_hint.text()


def test_the_project_reason_for_a_crs_that_does_not_reach_the_spot(session):
    # No real CRS makes the transform raise at a lon/lat, so the branch is
    # called directly.
    d = GridDialog(session)
    assert d._project_reason(UTM16, "outside", None) == (
        "the project CRS (EPSG:32616) does not reach this location"
    )


def test_the_site_note_is_only_shown_when_the_site_differs_from_the_project(
    session, project_crs, real_canvas
):
    project_crs(UTM16)
    session.add_grid(SITE)
    d = GridDialog(session, canvas=real_canvas(UTM16, _site_extent(UTM16)))
    assert d.crs_widget.crs() == UTM16
    assert d.crs_hint.text() == ""


def test_a_fit_that_is_not_square_says_so(session):
    d = _utm_dialog(session)
    for row, (e, n) in enumerate(SITE_CORNERS):
        _type_row(d, row, e + (0.05 if row == 2 else 0.0), n)
    d.fit_corners()
    text = d.fit_status.text()
    assert text.startswith("rigid fit RMS 0.0")
    assert not text.startswith("rigid fit RMS 0.000")
    assert text.endswith(" m from 4 corners · not quite square: see off by")


# ---- fill from a polygon (#27) ----------------------------------------------


def _wgs84_ring() -> list[QgsPointXY]:
    xform = QgsCoordinateTransform(UTM16, WGS84, QgsProject.instance())
    return [xform.transform(QgsPointXY(*p)) for p in SITE_CORNERS]


def _polygon_layer(
    ring: list[QgsPointXY], kind: str = "Polygon", crs: str = "EPSG:4326"
) -> QgsVectorLayer:
    layer = QgsVectorLayer(f"{kind}?crs={crs}", "plan", "memory")
    f = QgsFeature()
    if kind == "Polygon":
        f.setGeometry(QgsGeometry.fromPolygonXY([ring]))
    else:
        f.setGeometry(QgsGeometry.fromMultiPolygonXY([[ring]]))
    layer.dataProvider().addFeatures([f])
    return layer


@pytest.fixture
def plan_layer(qgis_app):
    made: list[QgsVectorLayer] = []

    def _make(*args: Any, **kwargs: Any) -> QgsVectorLayer:
        layer = _polygon_layer(*args, **kwargs)
        QgsProject.instance().addMapLayer(layer)
        made.append(layer)
        return layer

    yield _make
    for layer in made:
        QgsProject.instance().removeMapLayer(layer.id())


def _geo_dialog(session) -> GridDialog:
    d = GridDialog(session)
    d.corners_crs.setCrs(WGS84)
    d.crs_widget.setCrs(UTM16)
    return d


SITE_SOURCES = ["v0 SW", "v1 SE", "v2 NE", "v3 NW"]


def test_fill_from_a_4326_polygon_gives_the_known_utm_grid(qgis_app, session, plan_layer):
    layer = plan_layer(_wgs84_ring())
    d = _geo_dialog(session)
    _select_sole_feature(qgis_app, d, layer)
    d.fill_from_polygon()
    d.fit_corners()
    assert d.origin_x.value() == pytest.approx(SITE.origin[0], abs=1e-3)
    assert d.origin_y.value() == pytest.approx(SITE.origin[1], abs=1e-3)
    assert d.azimuth.value() == pytest.approx(10.0, abs=1e-6)
    assert d.size_x.value() == pytest.approx(20.0, abs=1e-3)
    assert d.size_y.value() == pytest.approx(20.0, abs=1e-3)
    assert [d.corner_source(r) for r in range(4)] == SITE_SOURCES


def test_fill_reads_a_multipolygon_layer(qgis_app, session, plan_layer):
    layer = plan_layer(_wgs84_ring(), kind="MultiPolygon")
    d = _geo_dialog(session)
    _select_sole_feature(qgis_app, d, layer)
    d.fill_from_polygon()
    ring = _wgs84_ring()
    for r in range(4):
        assert d.corner_point(r).x() == pytest.approx(ring[r].x(), abs=1e-9)
        assert d.corner_point(r).y() == pytest.approx(ring[r].y(), abs=1e-9)


def test_fill_labels_by_compass_in_a_geographic_crs(qgis_app, session, plan_layer):
    # A long thin site: the labels must come out the same from a UTM layer
    # read into a geographic "Corners in" (the cos(phi) rule).
    layer = plan_layer([QgsPointXY(*p) for p in SITE_CORNERS], crs="EPSG:32616")
    d = _geo_dialog(session)
    _select_sole_feature(qgis_app, d, layer)
    d.fill_from_polygon()
    assert d.corners_crs.crs() == WGS84
    assert [d.corner_source(r) for r in range(4)] == SITE_SOURCES


def test_the_cos_phi_rule_keeps_a_245_degree_vertex_south_west(qgis_app, session, plan_layer):
    # A vertex at true bearing 245 deg sits just inside SW. Read raw in
    # degrees at 36 N it would swing to ~249 deg and be called W.
    import math

    cx, cy = SITE.origin
    ring = [
        QgsPointXY(cx + 30 * math.sin(math.radians(b)), cy + 30 * math.cos(math.radians(b)))
        for b in (245, 335, 65, 155)
    ]
    layer = plan_layer(ring, crs="EPSG:32616")
    d = _geo_dialog(session)
    _select_sole_feature(qgis_app, d, layer)
    d.fill_from_polygon()
    labels = {d.corner_source(r).split()[0]: d.corner_source(r).split()[1] for r in range(4)}
    assert labels == {"v0": "SW", "v1": "NW", "v2": "NE", "v3": "SE"}


def test_fill_without_a_feature_reports_a_message(session):
    d = _geo_dialog(session)
    d.fill_from_polygon()
    assert d.fit_status.text() == "select a polygon feature first"


def test_the_feature_list_follows_the_layer_list_not_its_signal(qgis_app, session, plan_layer):
    # A polygon layer added while the window is open: the layer list selects
    # it on its own. QGIS 3.44 announces that as layerChanged(<the layer>);
    # QGIS 4.2 as layerChanged(None) (measured in qgis/qgis:4.2, PR #80's
    # CI), which left the feature list empty and Fill impossible. The
    # feature list must follow what the layer list shows, whatever the
    # signal carried.
    d = GridDialog(session)
    layer = plan_layer([QgsPointXY(*p) for p in SITE_CORNERS], crs="EPSG:32616")
    qgis_app.processEvents()
    assert d.layer_combo.currentLayer() is layer
    assert d.feature_picker.layer() is layer
    d.layer_combo.layerChanged.emit(None)  # what QGIS 4.2 sends
    assert d.feature_picker.layer() is layer


def test_fill_reports_an_empty_geometry(qgis_app, session, plan_layer):
    layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "plan", "memory")
    layer.dataProvider().addFeatures([QgsFeature()])
    QgsProject.instance().addMapLayer(layer)
    try:
        d = _geo_dialog(session)
        _select_sole_feature(qgis_app, d, layer)
        d.fill_from_polygon()
        assert d.fit_status.text() == "this feature has no rings to read corners from"
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_fill_refuses_a_five_corner_polygon(qgis_app, session, plan_layer):
    ring = _wgs84_ring()
    ring.insert(
        2, QgsPointXY((ring[1].x() + ring[2].x()) / 2 + 1e-5, (ring[1].y() + ring[2].y()) / 2)
    )
    layer = plan_layer(ring)
    d = _geo_dialog(session)
    d.set_corner(0, QgsPointXY(-86.0, 36.0), WGS84, "typed")
    _select_sole_feature(qgis_app, d, layer)
    d.fill_from_polygon()
    assert "expected four corners, got 5" in d.fit_status.text()
    assert [d.corner_point(r) for r in (1, 2, 3)] == [None, None, None]
    assert d.corner_point(0) == QgsPointXY(-86.0, 36.0)
    assert d.corner_source(0) == "typed"


def test_fill_does_not_fit(qgis_app, session, plan_layer):
    layer = plan_layer(_wgs84_ring())
    d = _geo_dialog(session)
    _select_sole_feature(qgis_app, d, layer)
    d.fill_from_polygon()
    assert (d.origin_x.value(), d.origin_y.value()) == (0.0, 0.0)


def test_fill_that_cannot_transform_leaves_the_rows_alone(qgis_app, session, plan_layer):
    ring = _wgs84_ring()
    ring[2] = QgsPointXY(ring[2].x(), 95.0)  # outside every CRS: the transform raises
    layer = plan_layer(ring)
    d = _utm_dialog(session)
    d.set_corner(0, QgsPointXY(*SITE_CORNERS[0]), UTM16, "typed")
    _select_sole_feature(qgis_app, d, layer)
    d.fill_from_polygon()
    assert d.fit_status.text() == "could not convert the polygon into EPSG:32616"
    assert d.corner_source(0) == "typed"
    assert d.corner_point(1) is None


def test_rotate_carries_polygon_labels(qgis_app, session, plan_layer):
    layer = plan_layer(_wgs84_ring())
    d = _geo_dialog(session)
    _select_sole_feature(qgis_app, d, layer)
    d.fill_from_polygon()
    d.rotate_corners()
    assert [d.corner_source(r) for r in range(4)] == ["v1 SE", "v2 NE", "v3 NW", "v0 SW"]


def test_set_polygon_feature_sets_both_combos_and_chosen_polygon_reads_them(
    qgis_app, session, plan_layer
):
    layer = plan_layer(_wgs84_ring())
    d = _geo_dialog(session)
    assert d.chosen_polygon() is None
    fid = next(layer.getFeatures()).id()
    d.set_polygon_feature(layer, fid)
    _pump(qgis_app, lambda: d.feature_picker.feature().id() == fid)
    assert d.layer_combo.currentLayer() == layer
    chosen = d.chosen_polygon()
    assert chosen is not None and chosen[0] == layer and not chosen[1].isNull()


def test_set_polygon_feature_refuses_a_layer_the_list_does_not_offer(qgis_app, session):
    # Task 3 review: chosen_polygon and Fill took the layer from the layer
    # combo and the fid from the feature picker. The combo lists only this
    # project's polygon layers; handed any other layer (a map pick can find
    # a canvas layer that is not in the project), its setLayer() quietly
    # drops the user's current choice instead, while the picker takes the
    # fid regardless -- the two lists then name different layers. A layer
    # the combo would refuse now changes neither, and the status line says
    # why.
    chosen = named_layer(
        "Polygon", "plots", {"a": [(0, 0), (9, 0), (9, 9)], "b": [(20, 0), (29, 0), (29, 9)]}
    )
    stray = named_layer("Polygon", "stray", {"s": [(50, 0), (59, 0), (59, 9)]})
    QgsProject.instance().addMapLayer(chosen)
    try:
        d = _utm_dialog(session)
        b = feature_id(chosen, "b")
        assert d.set_polygon_feature(chosen, b)
        assert _pump(qgis_app, lambda: d.feature_picker.feature().id() == b)

        assert not d.set_polygon_feature(stray, feature_id(stray, "s"))
        assert "stray" in d.fit_status.text()
        assert d.layer_combo.currentLayer() is chosen
        assert d.feature_picker.layer() is chosen
        picked = d.chosen_polygon()
        assert picked is not None and picked[0] is chosen
        assert picked[1].asWkt() == chosen.getFeature(b).geometry().asWkt()
    finally:
        QgsProject.instance().removeMapLayer(chosen.id())


def test_pick_on_map_only_emits(session, qgis_app):
    d = _geo_dialog(session)
    seen: list[int] = []
    d.pick_polygon_requested.connect(lambda: seen.append(1))
    d.pick_polygon_button.click()
    assert seen == [1]


# ---- the grid's CRS chooses itself (#62) ---------------------------------------


def _site_extent(crs: QgsCoordinateReferenceSystem) -> QgsRectangle:
    """An 800 x 600 m box around SITE.origin, in `crs` (a lon/lat box for 4326)."""
    ox, oy = SITE.origin
    if crs == UTM16:
        return QgsRectangle(ox - 400, oy - 300, ox + 400, oy + 300)
    c = QgsCoordinateTransform(UTM16, crs, QgsProject.instance()).transform(QgsPointXY(ox, oy))
    return QgsRectangle(c.x() - 0.004, c.y() - 0.003, c.x() + 0.004, c.y() + 0.003)


def _ready(d: GridDialog) -> GridDialog:
    d.id_edit.setText("A")
    d.velocity.setValue(0.08)
    return d


def test_a_usable_project_crs_is_kept(session, project_crs, real_canvas):
    project_crs(UTM16)
    d = GridDialog(session, canvas=real_canvas(UTM16, _site_extent(UTM16)))
    assert d.crs_widget.crs().authid() == "EPSG:32616"
    assert d.crs_is_auto()
    assert d.crs_hint.text() == ""


def test_a_4326_project_gets_the_canvas_centres_utm_zone(session, project_crs, real_canvas):
    project_crs(WGS84)
    d = GridDialog(session, canvas=real_canvas(WGS84, _site_extent(WGS84)))
    assert d.crs_widget.crs().authid() == "EPSG:32616"
    assert d.crs_is_auto()
    hint = d.crs_hint.text()
    assert "picked for you" in hint and "EPSG:4326" in hint and "degrees" in hint


def test_the_sites_crs_comes_first(session, project_crs, real_canvas):
    project_crs(UTM16)
    session.add_grid(Grid("B", (300_000.0, 4_000_000.0), 0.0, 10.0, 10.0, "EPSG:32617", 0.5))
    d = GridDialog(session, canvas=real_canvas(UTM16, _site_extent(UTM16)))
    assert d.crs_widget.crs().authid() == "EPSG:32617"
    assert d.crs_hint.text() == "picked for you: the CRS the site's other grids use"


def test_fit_moves_an_automatic_crs_to_the_corners_zone(session, project_crs, real_canvas):
    project_crs(UTM16)
    d = GridDialog(session, canvas=real_canvas(UTM16, _site_extent(UTM16)))
    d.corners_crs.setCrs(WGS84)
    for row, (dx, dy) in enumerate(((0, 0), (0.0002, 0), (0.0002, 0.0002), (0, 0.0002))):
        d.set_corner(row, QgsPointXY(-70.0 + dx, 36.0 + dy), WGS84, "typed")
    assert d.crs_widget.crs().authid() == "EPSG:32616"
    d.fit_corners()
    assert d.crs_is_auto()
    assert d.crs_widget.crs().authid() == "EPSG:32619"
    ox, oy = d.origin_x.value(), d.origin_y.value()
    ref = QgsCoordinateTransform(
        WGS84, QgsCoordinateReferenceSystem("EPSG:32619"), QgsProject.instance()
    )
    p = ref.transform(QgsPointXY(-70.0, 36.0))
    assert (ox, oy) == pytest.approx((p.x(), p.y()), abs=1e-3)


def test_a_hand_picked_crs_is_never_replaced(session, project_crs, real_canvas):
    project_crs(UTM16)
    d = _ready(GridDialog(session, canvas=real_canvas(UTM16, _site_extent(UTM16))))
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32619"))
    assert not d.crs_is_auto()
    for row, (e, n) in enumerate(SITE_CORNERS):
        d.set_corner(row, QgsPointXY(e, n), UTM16, "typed")
    d.fit_corners()
    assert d.crs_widget.crs().authid() == "EPSG:32619"
    assert not d.crs_is_auto()
    assert not d.ok_button.isEnabled()


def test_a_4326_polygon_in_a_4326_project_fits_in_the_right_utm_zone(
    qgis_app, session, project_crs, real_canvas, plan_layer
):
    project_crs(WGS84)
    d = GridDialog(session, canvas=real_canvas(WGS84, _site_extent(WGS84)))
    assert d.corners_crs.crs() == WGS84
    layer = plan_layer(_wgs84_ring())
    _select_sole_feature(qgis_app, d, layer)
    d.fill_from_polygon()
    d.fit_corners()
    assert d.crs_widget.crs().authid() == "EPSG:32616"
    assert d.origin_x.value() == pytest.approx(SITE.origin[0], abs=1e-3)
    assert d.origin_y.value() == pytest.approx(SITE.origin[1], abs=1e-3)
    assert d.azimuth.value() == pytest.approx(10.0, abs=1e-6)


def test_an_existing_grids_crs_is_never_changed(session, project_crs, real_canvas):
    project_crs(UTM16)
    session.add_grid(Grid("B", (300_000.0, 4_000_000.0), 0.0, 10.0, 10.0, "EPSG:32617", 0.5))
    d = GridDialog(session, grid=session.grid("B"), canvas=real_canvas(UTM16, _site_extent(UTM16)))
    assert not d.crs_is_auto()
    assert d.crs_widget.crs().authid() == "EPSG:32617"
    for row, (e, n) in enumerate(SITE_CORNERS):
        d.set_corner(row, QgsPointXY(e, n), UTM16, "typed")
    d.fit_corners()
    assert d.crs_widget.crs().authid() == "EPSG:32617"


def test_hand_picking_a_crs_converts_origin_and_azimuth(session, project_crs):
    project_crs(UTM16)
    d = GridDialog(session)
    d.origin_x.setValue(SITE.origin[0])
    d.origin_y.setValue(SITE.origin[1])
    d.azimuth.setValue(SITE.azimuth)
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32617"))
    assert not d.crs_is_auto()
    back = QgsCoordinateTransform(d.crs_widget.crs(), UTM16, QgsProject.instance())
    origin = back.transform(QgsPointXY(d.origin_x.value(), d.origin_y.value()))
    assert (origin.x(), origin.y()) == pytest.approx(SITE.origin, abs=1e-3)
    # 100 along +Y in the new CRS is not 100 m on the ground (32617 is ~0.3% off
    # here), so compare the direction: the point 100 m along it from the origin.
    az = np.radians(d.azimuth.value())
    ahead = back.transform(
        QgsPointXY(d.origin_x.value() + 100 * np.sin(az), d.origin_y.value() + 100 * np.cos(az))
    )
    step = np.array([ahead.x() - origin.x(), ahead.y() - origin.y()])
    rebuilt = np.array(SITE.origin) + 100 * step / np.hypot(*step)
    want = np.radians(SITE.azimuth)
    original = np.array(SITE.origin) + 100 * np.array([np.sin(want), np.cos(want)])
    assert rebuilt == pytest.approx(original, abs=1e-2)


def test_a_hand_pick_that_cannot_convert_puts_the_old_crs_back(session, project_crs):
    project_crs(UTM16)
    d = GridDialog(session)
    d.origin_x.setValue(1e8)  # outside UTM 16N's domain: the transform raises
    d.origin_y.setValue(1e8)
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32617"))
    assert d.crs_widget.crs().authid() == "EPSG:32616"
    assert "could not convert" in d.crs_hint.text()
    assert (d.origin_x.value(), d.origin_y.value()) == (1e8, 1e8)


def test_no_canvas_keeps_the_project_crs_and_says_what_will_happen(session, project_crs):
    project_crs(WGS84)
    d = _ready(GridDialog(session, canvas=None))
    assert d.crs_widget.crs().authid() == "EPSG:4326"
    assert not d.ok_button.isEnabled()
    hint = d.crs_hint.text()
    assert "metres" in hint and "a UTM zone will be picked when you fit corners" in hint


def test_off_by_is_blank_unless_the_grid_crs_is_usable_at_the_origin(session, project_crs):
    project_crs(UTM16)
    d = GridDialog(session)
    for row, (e, n) in enumerate(SITE_CORNERS):
        d.set_corner(row, QgsPointXY(e, n), UTM16, "typed")
    d.fit_corners()
    d.azimuth.setValue(11.0)
    assert all(o is not None for o in d.corner_offsets()[1:])
    for code in ("EPSG:4326", "EPSG:2264", "EPSG:3857"):  # degrees, US feet, 20% off
        d.crs_widget.setCrs(UTM16)  # the round trip must bring the grid back by itself
        d.crs_widget.setCrs(QgsCoordinateReferenceSystem(code))
        assert (d.origin_x.value(), d.origin_y.value()) != (0.0, 0.0), code
        assert d.corner_offsets() == [None] * 4, code


@pytest.mark.parametrize("via", ["EPSG:4326", "EPSG:2264", "EPSG:32617"])
def test_a_round_trip_through_any_crs_leaves_the_grid_where_it_was(session, project_crs, via):
    project_crs(UTM16)
    d = GridDialog(session)
    d.origin_x.setValue(SITE.origin[0])
    d.origin_y.setValue(SITE.origin[1])
    d.azimuth.setValue(SITE.azimuth)
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem(via))
    d.crs_widget.setCrs(UTM16)
    assert d.crs_widget.crs().authid() == "EPSG:32616"
    assert d.origin_x.value() == pytest.approx(SITE.origin[0], abs=1e-3)
    assert d.origin_y.value() == pytest.approx(SITE.origin[1], abs=1e-3)
    assert d.azimuth.value() == pytest.approx(10.0, abs=1e-6)


def test_a_hand_edit_in_a_non_metric_crs_wins_over_the_anchor(session, project_crs):
    project_crs(UTM16)
    d = GridDialog(session)
    d.origin_x.setValue(SITE.origin[0])
    d.origin_y.setValue(SITE.origin[1])
    d.azimuth.setValue(SITE.azimuth)
    d.crs_widget.setCrs(WGS84)
    lon, lat = d.origin_x.value(), d.origin_y.value()
    d.origin_x.setValue(lon + 0.01)  # about 0.9 km east: the user's own number
    d.crs_widget.setCrs(UTM16)
    want = QgsCoordinateTransform(WGS84, UTM16, QgsProject.instance()).transform(
        QgsPointXY(lon + 0.01, lat)
    )
    assert (d.origin_x.value(), d.origin_y.value()) == pytest.approx((want.x(), want.y()), abs=1e-3)
    assert abs(d.origin_x.value() - SITE.origin[0]) > 500
    assert d.azimuth.value() == pytest.approx(10.0, abs=1e-3)


def _site_dialog(session) -> GridDialog:
    d = GridDialog(session)
    d.origin_x.setValue(SITE.origin[0])
    d.origin_y.setValue(SITE.origin[1])
    d.azimuth.setValue(SITE.azimuth)
    return d


def test_moving_the_origin_in_feet_does_not_turn_the_grid(session, project_crs):
    project_crs(UTM16)
    d = _site_dialog(session)
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:2264"))
    feet = d.crs_widget.crs()
    here = QgsPointXY(d.origin_x.value(), d.origin_y.value())
    d.origin_x.setValue(here.x() + 10.0)  # 10 ft east in the state plane's own axes
    want = QgsCoordinateTransform(feet, UTM16, QgsProject.instance()).transform(
        QgsPointXY(here.x() + 10.0, here.y())
    )
    d.crs_widget.setCrs(UTM16)
    assert abs(want.x() - SITE.origin[0]) == pytest.approx(3.048, abs=0.05)  # the move is ~3 m
    assert d.origin_x.value() == pytest.approx(want.x(), abs=2e-3)
    assert d.origin_y.value() == pytest.approx(want.y(), abs=2e-3)
    assert d.azimuth.value() == pytest.approx(10.0, abs=1e-3)


def test_an_azimuth_nudge_and_undo_in_degrees_keeps_the_anchor(session, project_crs):
    project_crs(UTM16)
    d = _site_dialog(session)
    d.crs_widget.setCrs(WGS84)
    before = d.azimuth.value()
    d.azimuth.setValue(before + 1.0)
    d.azimuth.setValue(before)
    d.crs_widget.setCrs(UTM16)
    assert d.origin_x.value() == pytest.approx(SITE.origin[0], abs=1e-3)
    assert d.origin_y.value() == pytest.approx(SITE.origin[1], abs=1e-3)
    assert d.azimuth.value() == pytest.approx(10.0, abs=1e-3)


def test_without_an_anchor_the_azimuth_still_survives_a_trip_from_feet(session, project_crs):
    project_crs(UTM16)
    d = GridDialog(session)
    feet = QgsCoordinateReferenceSystem("EPSG:2264")
    d.crs_widget.setCrs(feet)  # no origin yet: nothing converted, no anchor
    d.origin_x.setValue(1_500_000.0)
    d.origin_y.setValue(300_000.0)
    d.azimuth.setValue(25.0)
    d.crs_widget.setCrs(UTM16)
    d.crs_widget.setCrs(feet)
    assert d.azimuth.value() == pytest.approx(25.0, abs=1e-3)
    assert d.origin_x.value() == pytest.approx(1_500_000.0, abs=2e-3)


# ---- the map overlay (#27, #28, spec 4.8) -------------------------------------


def _overlay_dialog(session, project_crs, real_canvas, crs=UTM16) -> GridDialog:
    project_crs(crs)
    d = GridDialog(session, canvas=real_canvas(crs, _site_extent(crs)))
    d.corners_crs.setCrs(UTM16)
    return d


def _close(_unused: Any, points: Any, expect: Any, tol: float = 1e-6) -> bool:
    return all(
        (p.x() == pytest.approx(e[0], abs=tol)) and (p.y() == pytest.approx(e[1], abs=tol))
        for p, e in zip(points, expect)
    )


def test_a_dialog_without_a_canvas_has_no_overlay(session):
    assert GridDialog(session).overlay is None


def test_overlay_tags_each_filled_corner(session, project_crs, real_canvas):
    d = _overlay_dialog(session, project_crs, real_canvas)
    _type_row(d, 0, *SITE_CORNERS[0])
    _type_row(d, 2, *SITE_CORNERS[2])
    c = d.overlay.corners
    assert [None if x is None else x[1] for x in c] == ["origin", None, "+X+Y", None]
    assert (c[0][0].x(), c[0][0].y()) == pytest.approx(tuple(SITE_CORNERS[0]), abs=1e-6)
    assert (c[2][0].x(), c[2][0].y()) == pytest.approx(tuple(SITE_CORNERS[2]), abs=1e-6)


def test_overlay_corners_are_in_the_canvas_crs(session, project_crs, real_canvas):
    d = _overlay_dialog(session, project_crs, real_canvas, crs=WGS84)
    _type_row(d, 0, *SITE_CORNERS[0])
    want = QgsCoordinateTransform(UTM16, WGS84, QgsProject.instance()).transform(
        QgsPointXY(*SITE_CORNERS[0])
    )
    got = d.overlay.corners[0][0]
    assert (got.x(), got.y()) == pytest.approx((want.x(), want.y()), abs=1e-9)


def test_overlay_tags_polygon_vertices_with_their_labels(
    qgis_app, session, project_crs, real_canvas, plan_layer
):
    d = _overlay_dialog(session, project_crs, real_canvas)
    ring = [QgsPointXY(*p) for p in SITE_CORNERS]
    _select_sole_feature(qgis_app, d, plan_layer(ring, crs="EPSG:32616"))
    d.fill_from_polygon()
    tags = [c[1] for c in d.overlay.corners]
    assert all(t.startswith(f"{role} · v") for t, role in zip(tags, ("origin", "+X", "+X+Y", "+Y")))
    assert tags[0] == f"origin · {d.corner_source(0)}"


def test_the_chosen_polygon_is_outlined(qgis_app, session, project_crs, real_canvas, plan_layer):
    d = _overlay_dialog(session, project_crs, real_canvas)
    assert d.overlay.polygon is None
    ring = [QgsPointXY(*p) for p in SITE_CORNERS]
    layer = plan_layer(ring, crs="EPSG:32616")
    _select_sole_feature(qgis_app, d, layer)
    assert d.overlay.polygon is not None
    pts = d.overlay.polygon
    assert _close(None, pts[:4], SITE_CORNERS)
    # choosing no feature clears it
    d.layer_combo.setLayer(None)
    _pump(qgis_app, lambda: d.overlay.polygon is None)
    assert d.overlay.polygon is None


def test_the_chosen_polygon_is_outlined_in_the_canvas_crs(
    qgis_app, session, project_crs, real_canvas, plan_layer
):
    d = _overlay_dialog(session, project_crs, real_canvas, crs=WGS84)
    _select_sole_feature(qgis_app, d, plan_layer(_wgs84_ring()))
    assert _close(None, d.overlay.polygon[:4], [(p.x(), p.y()) for p in _wgs84_ring()], 1e-9)


def test_overlay_outline_follows_the_form(session, project_crs, real_canvas):
    d = _overlay_dialog(session, project_crs, real_canvas)
    d.crs_widget.setCrs(UTM16)
    d.origin_x.setValue(SITE.origin[0])
    d.origin_y.setValue(SITE.origin[1])
    d.azimuth.setValue(SITE.azimuth)
    d.size_x.setValue(SITE.size_x)
    d.size_y.setValue(SITE.size_y)
    assert _close(None, d.overlay.grid, SITE_CORNERS)
    d.size_x.setValue(30.0)  # no Fit needed
    assert d.overlay.grid[1].x() != pytest.approx(SITE_CORNERS[1][0], abs=1e-3)
    want = Grid("_", SITE.origin, SITE.azimuth, 30.0, 20.0, "EPSG:32616", 0.5).to_world(
        np.array([[0, 0], [30, 0], [30, 20], [0, 20]], dtype=float)
    )
    assert _close(None, d.overlay.grid, want)


def test_overlay_grid_is_in_the_canvas_crs(session, project_crs, real_canvas):
    d = _overlay_dialog(session, project_crs, real_canvas, crs=WGS84)
    d.crs_widget.setCrs(UTM16)
    d.origin_x.setValue(SITE.origin[0])
    d.origin_y.setValue(SITE.origin[1])
    d.size_x.setValue(20.0)
    d.size_y.setValue(20.0)
    want = QgsCoordinateTransform(UTM16, WGS84, QgsProject.instance()).transform(
        QgsPointXY(d.origin_x.value(), d.origin_y.value())
    )
    assert (d.overlay.grid[0].x(), d.overlay.grid[0].y()) == pytest.approx(
        (want.x(), want.y()), abs=1e-9
    )


def test_overlay_hides_the_grid_until_it_can_be_drawn(session, project_crs, real_canvas):
    d = _overlay_dialog(session, project_crs, real_canvas)
    d.crs_widget.setCrs(UTM16)
    d.origin_x.setValue(SITE.origin[0])
    d.origin_y.setValue(SITE.origin[1])
    d.size_x.setValue(20.0)
    d.size_y.setValue(0.0)
    assert d.overlay.grid is None
    d.size_y.setValue(20.0)
    assert d.overlay.grid is not None
    d.size_x.setValue(0.0)
    assert d.overlay.grid is None
    d.size_x.setValue(20.0)
    d.origin_x.setValue(0.0)
    d.origin_y.setValue(0.0)
    assert d.overlay.grid is None
    d.origin_x.setValue(SITE.origin[0])
    d.origin_y.setValue(SITE.origin[1])
    assert d.overlay.grid is not None
    d.crs_widget.setCrs(WGS84)  # degrees: not usable for a metric grid
    assert d.overlay.grid is None


def test_overlay_and_off_by_agree_on_when_to_draw(session, project_crs, real_canvas):
    d = _overlay_dialog(session, project_crs, real_canvas)
    _type_site(d)
    d.fit_corners()
    assert d.overlay.grid is not None and d._offsets[0] is not None
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    assert (d.overlay.grid is None) == all(o is None for o in d._offsets)


def test_overlay_redraws_on_a_canvas_crs_change(session, project_crs, real_canvas):
    d = _overlay_dialog(session, project_crs, real_canvas)
    _type_row(d, 0, *SITE_CORNERS[0])
    before = d.overlay.corners[0][0]
    d.canvas.setDestinationCrs(WGS84)
    after = d.overlay.corners[0][0]
    want = QgsCoordinateTransform(UTM16, WGS84, QgsProject.instance()).transform(
        QgsPointXY(*SITE_CORNERS[0])
    )
    assert (after.x(), after.y()) == pytest.approx((want.x(), want.y()), abs=1e-9)
    assert (after.x(), after.y()) != pytest.approx((before.x(), before.y()))


def test_a_failed_transform_hides_that_element(session, project_crs, real_canvas, monkeypatch):
    d = _overlay_dialog(session, project_crs, real_canvas)
    _type_row(d, 0, *SITE_CORNERS[0])
    _type_row(d, 1, *SITE_CORNERS[1])
    from nsgeo_qgis.ui import grid_dialog
    from qgis.core import QgsCsException

    real = grid_dialog.QgsCoordinateTransform

    class Failing:
        def __init__(self, *a: Any) -> None:
            self._t = real(*a)

        def transform(self, p: Any, *rest: Any) -> Any:
            if abs(p.x() - SITE_CORNERS[1][0]) < 1e-6:
                raise QgsCsException()
            return self._t.transform(p, *rest)

    monkeypatch.setattr(grid_dialog, "QgsCoordinateTransform", Failing)
    d._refresh_overlay()
    assert d.overlay.corners[0] is not None
    assert d.overlay.corners[1] is None
    assert d.fit_status.text() == "the map cannot show the +X corner in EPSG:32616"


def test_a_clean_refresh_restores_the_fit_line_and_leaves_other_messages(
    session, project_crs, real_canvas, monkeypatch
):
    d = _overlay_dialog(session, project_crs, real_canvas)
    _type_site(d)
    d.fit_corners()
    fit_line = d.fit_status.text()
    assert fit_line
    from nsgeo_qgis.ui import grid_dialog
    from qgis.core import QgsCsException

    real = grid_dialog.QgsCoordinateTransform

    class Failing:
        def __init__(self, *a: Any) -> None:
            self._t = real(*a)

        def transform(self, p: Any, *rest: Any) -> Any:
            if abs(p.x() - SITE_CORNERS[0][0]) < 1e-6 or abs(p.x() - SITE_CORNERS[1][0]) < 1e-6:
                raise QgsCsException()
            return self._t.transform(p, *rest)

    monkeypatch.setattr(grid_dialog, "QgsCoordinateTransform", Failing)
    d._refresh_overlay()
    assert d.fit_status.text() == (
        "the map cannot show the origin and +X corners and the grid in EPSG:32616"
    )
    assert d._fit_line == fit_line  # never written into the Fit line
    monkeypatch.setattr(grid_dialog, "QgsCoordinateTransform", real)
    d._refresh_overlay()
    assert d.fit_status.text() == fit_line
    # another message showing: a clean refresh leaves it alone
    d.fit_status.setText("something else")
    d._refresh_overlay()
    assert d.fit_status.text() == "something else"


def test_a_non_finite_transform_is_reported_like_a_failed_one(
    session, project_crs, real_canvas, monkeypatch
):
    d = _overlay_dialog(session, project_crs, real_canvas)
    _type_row(d, 2, *SITE_CORNERS[2])
    from nsgeo_qgis.ui import grid_dialog

    class Nan:
        def __init__(self, *a: Any) -> None:
            pass

        def transform(self, p: Any, *rest: Any) -> Any:
            return QgsPointXY(float("inf"), 0.0)

    monkeypatch.setattr(grid_dialog, "QgsCoordinateTransform", Nan)
    d._refresh_overlay()
    assert d.overlay.corners[2] is None
    assert d.fit_status.text() == "the map cannot show the +X+Y corner in EPSG:32616"


def test_a_failure_while_drawing_leaves_the_overlay_as_it_was(
    session, project_crs, real_canvas, monkeypatch
):
    d = _overlay_dialog(session, project_crs, real_canvas)
    _type_row(d, 0, *SITE_CORNERS[0])
    assert d.overlay.corners[0] is not None
    monkeypatch.setattr(d, "_grid_outline", lambda: 1 / 0)
    _type_row(d, 2, *SITE_CORNERS[2])  # the refresh this triggers fails
    # an apply-as-you-go refresh would have drawn this corner before failing
    assert d.overlay.corners[2] is None
    assert d.overlay.corners[0] is not None
    # (the row change itself put the Fit line back over the message: R14)
    assert d._overlay_message.startswith("could not draw the map overlay")
    d._refresh_overlay()  # unchanged failure: label left alone
    assert not d.fit_status.text().startswith("could not draw")


def test_the_except_message_is_cleared_by_a_later_clean_refresh(
    session, project_crs, real_canvas, monkeypatch
):
    d = _overlay_dialog(session, project_crs, real_canvas)
    _type_site(d)
    d.fit_corners()
    fit_line = d.fit_status.text()
    monkeypatch.setattr(d, "_grid_outline", lambda: 1 / 0)
    d._refresh_overlay()
    assert d.fit_status.text().startswith("could not draw the map overlay")
    monkeypatch.undo()
    d._refresh_overlay()
    assert d.fit_status.text() == fit_line


def test_a_corners_crs_conversion_error_is_not_overwritten_by_the_overlay(
    session, project_crs, real_canvas
):
    d = _overlay_dialog(session, project_crs, real_canvas)
    d.corners_crs.setCrs(WGS84)
    _type_site(d)  # UTM numbers read as degrees: none can reach the canvas
    assert d.fit_status.text().startswith("the map cannot show")
    d.corners_crs.setCrs(UTM16)  # converting those "degrees" fails
    assert d.fit_status.text() == "could not convert the corners into EPSG:32616"
    assert d.corners_crs.crs() == WGS84


def test_a_persistent_overlay_failure_does_not_replace_the_fit_line(
    session, project_crs, real_canvas
):
    d = _overlay_dialog(session, project_crs, real_canvas)
    d.corners_crs.setCrs(WGS84)
    _type_row(d, 0, *SITE_CORNERS[0])  # persistent: cannot reach the canvas
    d._set_fit_line("rigid fit RMS 0.00 m")
    assert d._overlay_message.startswith("the map cannot show")
    d.fit_status.setText("an error")  # covers the Fit line
    _type_row(d, 0, SITE_CORNERS[0][0] + 1.0, SITE_CORNERS[0][1])  # a real edit: the line returns
    assert d.fit_status.text() == "rigid fit RMS 0.00 m"
    d.size_x.setValue(d.size_x.value() + 1.0)  # same failure: nothing replaced
    assert d.fit_status.text() == "rigid fit RMS 0.00 m"


def test_overlay_paints_its_marks(session, project_crs, real_canvas):
    from qgis.PyQt.QtGui import QColor, QImage, QPainter
    from qgis.PyQt.QtWidgets import QStyleOptionGraphicsItem

    d = _overlay_dialog(session, project_crs, real_canvas)
    _type_site(d)
    d.fit_corners()
    item = d.overlay.item
    image = QImage(800, 600, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    item.paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()
    colours = {image.pixelColor(x, y).name() for x in range(800) for y in range(0, 600, 2)}
    assert "#ff00ff" in colours  # the role tags and the arrow
    assert "#0050ff" in colours  # the grid outline


def test_overlay_paint_failure_is_caught(session, project_crs, real_canvas):
    from qgis.PyQt.QtGui import QImage, QPainter
    from qgis.PyQt.QtWidgets import QStyleOptionGraphicsItem

    d = _overlay_dialog(session, project_crs, real_canvas)
    _type_row(d, 0, *SITE_CORNERS[0])
    d.overlay.item.corners = [object()]  # a bad payload
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    d.overlay.item.paint(painter, QStyleOptionGraphicsItem(), None)  # must not raise
    painter.end()


def test_overlay_stays_while_the_dialog_is_hidden_mid_pick(real_iface, tmp_path, qgis_app):
    t = _pick_site(real_iface, tmp_path)
    _type_row(t.dialog, 0, 400.0, 300.0)
    item_count = _scene_count(qgis_app, t.canvas)
    t.dialog.pick_buttons[1].click()
    assert t.dialog.isHidden()
    assert _scene_count(qgis_app, t.canvas) == item_count
    assert not t.dialog.overlay.disposed
    assert t.dialog.overlay.item.isVisible()
    send_map_mouse(t.canvas.mapTool(), "move", (408, 300))
    send_map_mouse(t.canvas.mapTool(), "release", (408, 300))
    assert [None if c is None else c[1] for c in t.dialog.overlay.corners] == [
        "origin",
        "+X",
        None,
        None,
    ]
    t.dialog.reject()
    t.plugin.unload()


@pytest.mark.parametrize("how", ["ok", "cancel", "close mid-pick", "unload", "destroyed"])
def test_overlay_leaves_nothing_behind(real_iface, tmp_path, qgis_app, answer_modal, how):
    import nsgeo_qgis

    iface = real_iface(UTM16, QgsRectangle(0, 0, 800, 600))
    plugin = nsgeo_qgis.classFactory(iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    canvas = iface.mapCanvas()
    baseline = _scene_count(qgis_app, canvas)
    plugin.open_grid_dialog(None)
    dialog = plugin._grid_dialog
    dialog.corners_crs.setCrs(UTM16)
    overlay = dialog.overlay
    item = overlay.item
    _type_row(dialog, 0, 400.0, 300.0)
    assert _scene_count(qgis_app, canvas) == baseline + 1  # drawn
    if how == "ok":
        dialog.id_edit.setText("A")
        dialog.velocity.setValue(0.08)
        dialog.origin_x.setValue(400.0)
        dialog.origin_y.setValue(300.0)
        dialog.size_x.setValue(10.0)
        dialog.size_y.setValue(10.0)
        dialog.accept()
    elif how == "cancel":
        dialog.reject()
    elif how == "close mid-pick":
        dialog.pick_buttons[1].click()
        dialog.reject()
    elif how == "unload":
        dialog.pick_buttons[1].click()
        plugin.unload()
    else:
        dialog.setParent(None)
        dialog.deleteLater()
    qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if how == "unload":  # the plugin's own map-link items go too
        assert _scene_count(qgis_app, canvas) <= baseline - 1
    else:
        assert _scene_count(qgis_app, canvas) == baseline
    assert sip.isdeleted(item)
    overlay.dispose()  # idempotent
    if how == "ok":  # an accepted grid leaves unsaved changes to ask about
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.unload()
    elif how != "unload":
        plugin.unload()


def test_dispose_is_idempotent_and_setters_then_do_nothing(session, project_crs, real_canvas):
    d = _overlay_dialog(session, project_crs, real_canvas)
    d.overlay.dispose()
    d.overlay.dispose()
    _type_row(d, 0, *SITE_CORNERS[0])  # a late slot must not raise
    assert d.overlay.corners == [None] * 4
