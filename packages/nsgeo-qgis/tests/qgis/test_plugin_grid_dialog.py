from __future__ import annotations

import time
from typing import Any

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.maptools.digitise_tool import DigitiseGridTool
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.grid_dialog import COL_A, COL_B, COL_FROM, COL_ROLE, GridDialog
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtWidgets import QMessageBox

TRUE = Grid("A", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)
LOCAL = np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 11.0], [0.0, 11.0]])

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


def _open(plugin: Any, grid_id: str | None = None) -> GridDialog:
    """Call open_grid_dialog() and return the GridDialog it just showed.

    Fix round 4, Finding 1: GridDialog is modeless (plugin.py's
    open_grid_dialog() calls show(), not exec()) precisely so the
    digitise flow can reach the canvas at all -- exec()'s
    application-modal event loop terminates the instant the dialog is
    hidden, so _start_digitise()'s dialog.hide() would otherwise end it
    before a single canvas click landed (verified directly with a bare
    QDialog; see the fix-round report). That also means these tests
    never monkeypatch QDialog.exec (unlike `drive_dialog` in conftest.py,
    which no test in this file uses any more but which is kept for a
    future genuinely-modal dialog): open_grid_dialog() returns
    immediately with a real, already-shown dialog tracked on the plugin
    as `_grid_dialog`, and driving it -- typing into fields, clicking
    digitise_button, emitting real canvasClicked signals, calling
    accept()/reject() -- exercises the exact same code path a live QGIS
    session would.
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


def test_digitise_tool_emits_after_two_clicks(qgis_app, fake_iface):
    tool = DigitiseGridTool(fake_iface.mapCanvas())
    got = []
    tool.points_picked.connect(lambda a, b: got.append((a, b)))
    tool.canvasClicked.emit(QgsPointXY(1.0, 2.0), Qt.MouseButton.LeftButton)
    assert got == []
    tool.canvasClicked.emit(QgsPointXY(1.0, 5.0), Qt.MouseButton.LeftButton)
    assert len(got) == 1 and got[0][1].y() == 5.0


def test_digitise_tool_right_click_before_any_pick_cancels(qgis_app, fake_iface):
    # Fix round 1, Finding 4: a right-click is the universal QGIS "abort
    # this tool" gesture. Before this fix it was treated like any other
    # click -- it could set the origin outright.
    canvas = fake_iface.mapCanvas()
    tool = DigitiseGridTool(canvas)
    canvas.setMapTool(tool)
    cancelled, picked = [], []
    tool.cancelled.connect(lambda: cancelled.append(True))
    tool.points_picked.connect(lambda a, b: picked.append((a, b)))

    tool.canvasClicked.emit(QgsPointXY(1.0, 1.0), Qt.MouseButton.RightButton)
    assert cancelled == [True]
    assert picked == []
    assert canvas.mapTool() is None  # the abort deactivates the tool


def test_digitise_tool_right_click_after_origin_cancels_not_completes(qgis_app, fake_iface):
    # Worse than the no-op above: left-then-right used to *complete* the
    # pick, defining the grid's +Y edge wherever the cursor landed.
    canvas = fake_iface.mapCanvas()
    tool = DigitiseGridTool(canvas)
    canvas.setMapTool(tool)
    cancelled, picked = [], []
    tool.cancelled.connect(lambda: cancelled.append(True))
    tool.points_picked.connect(lambda a, b: picked.append((a, b)))

    tool.canvasClicked.emit(QgsPointXY(1.0, 2.0), Qt.MouseButton.LeftButton)
    tool.canvasClicked.emit(QgsPointXY(9.0, 9.0), Qt.MouseButton.RightButton)
    assert cancelled == [True]
    assert picked == []


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
    # canvas's one map tool during a digitise pick); it raises/
    # activates the existing one instead.
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
    # (round 1, Finding 3's dialog leak; the DigitiseGridTool leak noted
    # in plugin.py) becoming reachable only because this is the first
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


def _scene_bands(canvas: Any) -> list:
    """Every QgsRubberBand currently parked in the canvas's QGraphicsScene.

    Counted off the scene rather than off the tool deliberately: the band
    is a QgsMapCanvasItem, so the scene -- not the tool, and not Python --
    is what actually owns it. Dropping the tool's Python reference and
    collecting proves nothing; only the scene's own item list does.
    """
    from qgis.gui import QgsRubberBand

    return [item for item in canvas.scene().items() if isinstance(item, QgsRubberBand)]


def test_a_disposed_digitise_tool_is_disposable_again_and_still_usable(qgis_app, fake_iface):
    # Disposal has to be idempotent -- more than one finaliser can reach
    # the same tool -- and it must NOT live in deactivate(), which fires
    # on every tool switch and leaves the tool legitimately
    # reactivatable. A tool whose band is gone must therefore still
    # reset() and take clicks without raising: both touch self._band,
    # and an exception out of canvasClicked is swallowed by Qt.
    canvas = fake_iface.mapCanvas()
    tool = DigitiseGridTool(canvas)
    assert len(_scene_bands(canvas)) == 1

    tool.dispose()
    tool.dispose()  # idempotent
    assert _scene_bands(canvas) == []

    tool.reset()  # must not raise
    picked = []
    tool.points_picked.connect(lambda a, b: picked.append((a, b)))
    tool.canvasClicked.emit(QgsPointXY(1.0, 1.0), Qt.MouseButton.LeftButton)
    tool.canvasClicked.emit(QgsPointXY(2.0, 3.0), Qt.MouseButton.LeftButton)
    assert len(picked) == 1  # still a working tool, just without its band


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
    d.corner_table.item(0, COL_A).setText(f"{SITE_CORNERS[0][0]:.6f}")
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


def test_a_fit_that_is_not_square_says_so(session):
    d = _utm_dialog(session)
    for row, (e, n) in enumerate(SITE_CORNERS):
        _type_row(d, row, e + (0.05 if row == 2 else 0.0), n)
    d.fit_corners()
    text = d.fit_status.text()
    assert text.startswith("rigid fit RMS 0.0")
    assert not text.startswith("rigid fit RMS 0.000")
    assert text.endswith(" m from 4 corners · not quite square: see off by")
