from __future__ import annotations

import time

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.maptools.digitise_tool import DigitiseGridTool
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.grid_dialog import GridDialog
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QMessageBox

TRUE = Grid("A", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)
LOCAL = np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 11.0], [0.0, 11.0]])


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    return s


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
    """Select `layer`'s only feature in `dialog`'s polygon tab, waiting
    out QgsFeaturePickerWidget's asynchronous population (see _pump)."""
    dialog.layer_combo.setLayer(layer)
    _pump(qgis_app, lambda: dialog.feature_picker.feature().isValid())
    fid = next(layer.getFeatures()).id()
    dialog.feature_picker.setFeature(fid)
    _pump(qgis_app, lambda: dialog.feature_picker.feature().id() == fid)


def test_ok_is_blocked_until_id_and_velocity_are_set(session):
    d = GridDialog(session)
    assert not d.ok_button.isEnabled()
    d.id_edit.setText("A")
    assert not d.ok_button.isEnabled()  # velocity still 0 = required
    d.velocity.setValue(0.08)
    assert d.ok_button.isEnabled()


def test_crs_guard_blocks_every_route_to_a_bad_crs(session):
    # Fix round 2, Finding 2: one guard in _validate() -- authid() and
    # not isGeographic() -- rather than a separate check bolted onto
    # every path that can set crs_widget's CRS. Four such paths, all
    # caught by the same guard:

    # 1. The fallback used when the project has no CRS of its own
    #    (GridDialog.__init__): EPSG:3857 -- has an authid, not
    #    geographic -- so this alone does not block OK.
    d = GridDialog(session)
    d.id_edit.setText("A")
    d.velocity.setValue(0.08)
    assert d.crs_widget.crs().authid() == "EPSG:3857"
    assert d.ok_button.isEnabled()
    assert d.crs_hint.text() == ""

    # 2. The *project's* own CRS, when it is geographic -- QGIS's
    #    out-of-the-box default for a brand-new project.
    original_project_crs = QgsProject.instance().crs()
    try:
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        d_project = GridDialog(session)
        d_project.id_edit.setText("A")
        d_project.velocity.setValue(0.08)
        assert not d_project.ok_button.isEnabled()
        assert "geographic" in d_project.crs_hint.text().lower()
    finally:
        QgsProject.instance().setCrs(original_project_crs)

    # 3. The digitise flow's canvas CRS (plugin.py's done() adopts
    #    canvas.mapSettings().destinationCrs() unconditionally --
    #    Concern 1 from round 1, confirmed geographic-canvas numbers in
    #    the round 2 report). Simulated directly: from crs_widget's
    #    point of view it is just another setCrs() call.
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    assert not d.ok_button.isEnabled()
    assert "geographic" in d.crs_hint.text().lower()

    # 4a. A CRS the user picks by hand that is valid but has no
    #     authority code (round 1, Finding 2).
    custom = QgsCoordinateReferenceSystem.fromProj(
        "+proj=omerc +lat_0=36 +lonc=15 +alpha=30 +k=1 +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs"
    )
    assert custom.isValid() and not custom.authid()  # the exact case this guards
    d.crs_widget.setCrs(custom)
    assert not d.ok_button.isEnabled()
    assert "authority" in d.crs_hint.text().lower()

    # 4b. ... or one the user picks that is geographic outright.
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    assert not d.ok_button.isEnabled()
    assert "geographic" in d.crs_hint.text().lower()

    # Recovering with an ordinary registered, projected CRS re-enables OK
    # and clears the hint.
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32616"))
    assert d.ok_button.isEnabled()
    assert d.crs_hint.text() == ""


def test_corner_fit_fills_origin_azimuth_and_sizes(session):
    d = GridDialog(session, suggested_velocity=0.0801)
    world = TRUE.to_world(LOCAL)
    for row, (lo, wo) in enumerate(zip(LOCAL, world)):
        d.set_corner_row(row, lo[0], lo[1], wo[0], wo[1])
    d.fit_corners()
    assert d.origin_x.value() == pytest.approx(500.0, abs=1e-6)
    assert d.origin_y.value() == pytest.approx(700.0, abs=1e-6)
    assert d.azimuth.value() == pytest.approx(30.0, abs=1e-6)
    assert d.size_x.value() == pytest.approx(5.0) and d.size_y.value() == pytest.approx(11.0)
    assert "0.000" in d.residual_label.text()
    d.id_edit.setText("A")
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32616"))
    g = d.result_grid()
    assert g.id == "A" and g.crs == "EPSG:32616"
    assert g.velocity == VelocityModel.constant(0.0801)


def test_corner_tab_residual_caption_distinguishes_mirrored_from_not_square(session):
    # A data-entry blunder -- the +X and +Y world readings swapped, e.g.
    # because the field crew logged the two GNSS fixes in the wrong rows
    # -- is not "the grid wasn't surveyed square": fit_grid_from_corners
    # forbids reflection, so it still returns a plausible-looking origin
    # and azimuth, just with a large residual. The brief's caption ("0 =
    # square") would mislead a user staring at this into re-measuring a
    # perfectly good grid instead of checking which corner is which.
    d = GridDialog(session)
    world = TRUE.to_world(LOCAL)
    swapped_world = world[[0, 3, 2, 1]]  # +X and +Y world fixes swapped
    for row, (lo, wo) in enumerate(zip(LOCAL, swapped_world)):
        d.set_corner_row(row, lo[0], lo[1], wo[0], wo[1])
    d.fit_corners()
    text = d.residual_label.text()
    assert "0.000" not in text
    assert "mirror" in text.lower()


def test_corner_fit_places_control_points_not_anchored_at_the_local_origin(session):
    # Fix round 1, Finding 5 fixed the *size* (max() -> max() - min()) but
    # left fit.origin as-is: fit.origin is the world position of local
    # (0, 0) *in the control points' own local frame*, which is not the
    # same point as local (0, 0) of the fitted grid's own canonical
    # [0, size_x] x [0, size_y] rectangle when the control points are
    # offset (the origin stake is unreachable, so the crew surveys local
    # (100, 50) .. (137.5, 62.25) instead of (0, 0) .. (37.5, 12.25)).
    # Round 2, Finding 1: that left the *origin* 111.8 m from every one
    # of the four corners it was fitted to -- a correct azimuth and a
    # 0.000 m residual on a grid whose own outline no longer contains the
    # ground it was measured from. Fixed by translating fit.origin by
    # local.min(axis=0) along the fitted axes.
    #
    # True grid deliberately independent of this test's control points:
    # world corners come from true_grid.to_world() of its *own* canonical
    # rectangle, not of the offset local coordinates -- the offset is
    # only how the crew recorded distances, not a claim about where the
    # grid's own [0, size] rectangle sits.
    true_grid = Grid("B", (5000.0, 8000.0), 200.0, 37.5, 12.25, "EPSG:32616", 0.5)
    canonical = np.array([[0.0, 0.0], [37.5, 0.0], [37.5, 12.25], [0.0, 12.25]])
    world = true_grid.to_world(canonical)
    local_offset = np.array([[100.0, 50.0], [137.5, 50.0], [137.5, 62.25], [100.0, 62.25]])

    d = GridDialog(session)
    for row, (lo, wo) in enumerate(zip(local_offset, world)):
        d.set_corner_row(row, lo[0], lo[1], wo[0], wo[1])
    d.fit_corners()
    assert d.origin_x.value() == pytest.approx(5000.0, abs=1e-6)
    assert d.origin_y.value() == pytest.approx(8000.0, abs=1e-6)
    assert d.azimuth.value() == pytest.approx(200.0, abs=1e-6)
    assert d.size_x.value() == pytest.approx(37.5, abs=1e-6)
    assert d.size_y.value() == pytest.approx(12.25, abs=1e-6)
    assert "0.000" in d.residual_label.text()

    # The real test: does the *fitted grid's own rectangle* land back on
    # the four points it was surveyed from? (Round 1's fix alone put
    # this at 111.8 m on all four corners -- correct size, wrong origin.)
    fitted = Grid(
        "B",
        (d.origin_x.value(), d.origin_y.value()),
        d.azimuth.value(),
        d.size_x.value(),
        d.size_y.value(),
        "EPSG:32616",
        0.5,
    )
    own_canonical = np.array(
        [
            [0.0, 0.0],
            [d.size_x.value(), 0.0],
            [d.size_x.value(), d.size_y.value()],
            [0.0, d.size_y.value()],
        ]
    )
    distances = np.linalg.norm(fitted.to_world(own_canonical) - world, axis=1)
    assert distances == pytest.approx([0.0, 0.0, 0.0, 0.0], abs=1e-6)


def test_fit_corners_reports_bad_numeric_entry_without_crashing(session):
    # fit_corners() is a QPushButton.clicked slot; a hand-typed cell that
    # is not a number must surface as a message, not disappear into
    # stderr while the fields sit unchanged with no explanation (the
    # reference implementation's _corner_arrays() call sat outside its
    # own try/except, so this was not actually guarded).
    d = GridDialog(session)
    d.set_corner_row(0, 0.0, 0.0, 500.0, 700.0)
    d.set_corner_row(1, 1.0, 2.0, 3.0, 4.0)
    d.corner_table.item(1, 1).setText("not-a-number")
    d.fit_corners()  # must not raise
    assert "not-a-number" in d.residual_label.text()
    assert d.origin_x.value() == 0.0  # untouched: no crash, no silent wrong answer


def test_polygon_tab_reads_a_selected_feature(qgis_app, session):
    layer = _memory_layer(TRUE.to_world(LOCAL))
    QgsProject.instance().addMapLayer(layer)
    try:
        d = GridDialog(session)
        _select_sole_feature(qgis_app, d, layer)
        d.origin_combo.setCurrentIndex(0)
        d.plus_y_combo.setCurrentIndex(3)
        d.use_polygon()
        assert d.azimuth.value() == pytest.approx(30.0, abs=1e-6)
        assert d.size_y.value() == pytest.approx(11.0, abs=1e-6)
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_polygon_tab_rejects_the_mirrored_default_pick_and_the_other_corner_fixes_it(
    qgis_app, session
):
    # Same rectangle as above, but digitised with the opposite winding
    # (ring order v0, v3, v2, v1 instead of v0, v1, v2, v3). For *this*
    # winding, plus_y_combo's brief-specified default of index 3 names
    # the mirrored corner -- corners_from_polygon must reject it rather
    # than silently return a plausible-but-wrong grid, and the dialog
    # must recover cleanly when the user picks the other corner.
    rev_local = LOCAL[[0, 3, 2, 1]]
    layer = _memory_layer(TRUE.to_world(rev_local))
    QgsProject.instance().addMapLayer(layer)
    try:
        d = GridDialog(session)
        _select_sole_feature(qgis_app, d, layer)
        d.origin_combo.setCurrentIndex(0)
        assert d.plus_y_combo.currentIndex() == 3  # the brief's default

        d.use_polygon()
        assert "mirror" in d.polygon_status.text().lower()
        # A rejected pick must not silently write a wrong-but-plausible
        # grid: the fields stay at their untouched defaults.
        assert d.azimuth.value() == 0.0
        assert d.size_x.value() == 10.0 and d.size_y.value() == 10.0

        d.plus_y_combo.setCurrentIndex(1)  # the other corner adjacent to the origin
        d.use_polygon()
        assert d.azimuth.value() == pytest.approx(30.0, abs=1e-6)
        assert d.size_x.value() == pytest.approx(5.0, abs=1e-6)
        assert d.size_y.value() == pytest.approx(11.0, abs=1e-6)
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_use_polygon_without_a_selected_feature_reports_a_message_not_a_crash(session):
    d = GridDialog(session)
    d.use_polygon()  # no layer ever selected
    assert "polygon feature" in d.polygon_status.text().lower()
    assert d.azimuth.value() == 0.0  # untouched


def test_use_polygon_reports_an_empty_geometry_without_crashing(qgis_app, session):
    # geometry.isNull() is False for an empty (zero-ring) polygon, so
    # use_polygon()'s "select a feature first" guard lets it through;
    # asPolygon() then returns [] and polygon[0] used to raise IndexError
    # straight out of a clicked slot.
    layer = QgsVectorLayer("Polygon?crs=EPSG:32616", "plan", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromPolygonXY([]))
    layer.dataProvider().addFeatures([f])
    QgsProject.instance().addMapLayer(layer)
    try:
        d = GridDialog(session)
        _select_sole_feature(qgis_app, d, layer)
        d.use_polygon()  # must not raise
        assert d.azimuth.value() == 0.0  # untouched
        assert d.polygon_status.text()  # some explanation, not blank
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_use_polygon_refuses_a_geographic_crs_layer(qgis_app, session):
    # Fix round 1, Finding 1: corners_from_polygon/fit_grid_from_corners
    # treat a ring's raw coordinates as metres. A geographic (degrees)
    # layer breaks that silently rather than loudly: size_x/size_y come
    # out as ~1e-3 (degrees), and a rigid fit of the ring to itself in
    # degree units still finds a near-zero residual at a *wrong*
    # azimuth (1 degree of longitude is not 1 degree of latitude in
    # metres, away from the equator) -- "rigid fit RMS 0.000 m" on a
    # frame that is actually several degrees off. Numerically verified
    # (see the fix-round report) with a true 200 x 80 m, 30 degree
    # grid at ~36N: before this fix, azimuth came back 26.31 degrees
    # (3.69 degrees / ~5 m of cross-track error at the far corner) with
    # residual_rms 6.45e-05 -- the caption's "0.000 m".
    proj_crs = QgsCoordinateReferenceSystem("EPSG:32633")
    true_grid = Grid("B", (500000.0, 3985000.0), 30.0, 200.0, 80.0, "EPSG:32633", 1.0)
    local = np.array([[0.0, 0.0], [200.0, 0.0], [200.0, 80.0], [0.0, 80.0]])
    world_proj = true_grid.to_world(local)
    geo_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    xform = QgsCoordinateTransform(proj_crs, geo_crs, QgsProject.instance())
    ring_geo = [QgsPointXY(*xform.transform(QgsPointXY(x, y))) for x, y in world_proj]

    layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "plan", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromPolygonXY([ring_geo]))
    layer.dataProvider().addFeatures([f])
    QgsProject.instance().addMapLayer(layer)
    try:
        d = GridDialog(session)
        crs_before = d.crs_widget.crs().authid()
        _select_sole_feature(qgis_app, d, layer)
        d.use_polygon()
        assert "geographic" in d.polygon_status.text().lower()
        assert d.azimuth.value() == 0.0  # untouched -- no wrong-but-plausible grid
        assert d.size_x.value() == 10.0 and d.size_y.value() == 10.0
        assert d.crs_widget.crs().authid() == crs_before  # not silently overwritten
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_use_polygon_success_still_gets_a_visible_crs_refusal(qgis_app, session):
    # Fix round 2, Finding 3, worst case: a layer in a valid, *non*
    # geographic custom CRS with no authority code. use_polygon()'s own
    # isGeographic() guard does not catch this (correctly -- the fit
    # itself is genuinely fine), so it proceeds, reports success, and
    # overwrites crs_widget with that CRS -- silently disabling OK
    # before this fix, with nothing in polygon_status (which still,
    # correctly, says the fit succeeded) explaining why.
    custom = QgsCoordinateReferenceSystem.fromProj(
        "+proj=omerc +lat_0=36 +lonc=15 +alpha=30 +k=1 +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs"
    )
    assert custom.isValid() and not custom.isGeographic() and not custom.authid()
    layer = _memory_layer(TRUE.to_world(LOCAL))
    layer.setCrs(custom)
    QgsProject.instance().addMapLayer(layer)
    try:
        d = GridDialog(session)
        d.id_edit.setText("A")
        d.velocity.setValue(0.08)
        assert d.ok_button.isEnabled()  # the EPSG:3857 fallback, still fine
        _select_sole_feature(qgis_app, d, layer)
        d.origin_combo.setCurrentIndex(0)
        d.plus_y_combo.setCurrentIndex(3)
        d.use_polygon()
        assert d.azimuth.value() == pytest.approx(30.0, abs=1e-6)  # the fit is genuinely correct
        assert "0.000" in d.polygon_status.text()
        assert not d.ok_button.isEnabled()  # but its CRS has no authority code
        assert "authority" in d.crs_hint.text().lower()
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_digitised_points_set_origin_and_azimuth(session):
    d = GridDialog(session)
    d.set_digitised(
        (500.0, 700.0), (500.0 + 5.0 * np.sin(np.radians(30)), 700.0 + 5.0 * np.cos(np.radians(30)))
    )
    assert (d.origin_x.value(), d.origin_y.value()) == (500.0, 700.0)
    assert d.azimuth.value() == pytest.approx(30.0, abs=1e-6)


def test_set_digitised_rejects_coincident_points(session):
    # atan2(0, 0) == 0.0 with no error: two clicks landing on the same
    # point (a fast double-click reading as two canvasClicked events)
    # would otherwise seed a plausible-looking but meaningless azimuth.
    d = GridDialog(session)
    with pytest.raises(ValueError):
        d.set_digitised((500.0, 700.0), (500.0, 700.0))
    assert d.azimuth.value() == 0.0  # untouched


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


def test_grid_dialog_exec_is_guarded_by_default(session):
    # Task 9's autouse guard forbids QMessageBox/QFileDialog modals so a
    # test that trips one fails fast instead of hanging under
    # QT_QPA_PLATFORM=offscreen. GridDialog is the plugin's first real
    # QDialog, so the same guard must now cover QDialog.exec() too.
    d = GridDialog(session)
    with pytest.raises(AssertionError):
        d.exec()


# ---- plugin wiring ---------------------------------------------------------


def test_open_grid_dialog_accepts_and_adds_a_new_grid(
    fake_iface, tmp_path, drive_dialog, answer_modal
):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)

    def driver(dialog: GridDialog) -> None:
        dialog.id_edit.setText("A")
        dialog.velocity.setValue(0.08)
        dialog.origin_x.setValue(10.0)
        dialog.origin_y.setValue(20.0)
        dialog.accept()

    drive_dialog(QDialog, "exec", driver)
    plugin.open_grid_dialog(None)
    grid = plugin.session.grid("A")
    assert grid.origin == (10.0, 20.0)
    assert grid.velocity == VelocityModel.constant(0.08)
    # Fix round 1, Finding 2: this never explicitly picked a CRS, and
    # this dialog previously wrote grid.crs == "" in that case (the
    # project's own CRS is invalid in this bare test harness -- see
    # GridDialog.__init__). It must never be "": the fallback used when
    # nothing else is available is still a valid, projected authority
    # string (round 2: EPSG:4326 would also now be refused as geographic).
    assert grid.crs == "EPSG:3857"
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_open_grid_dialog_cancel_leaves_the_session_untouched(fake_iface, tmp_path, drive_dialog):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)

    def driver(dialog: GridDialog) -> None:
        dialog.id_edit.setText("A")
        dialog.velocity.setValue(0.08)
        dialog.reject()

    drive_dialog(QDialog, "exec", driver)
    plugin.open_grid_dialog(None)
    assert plugin.session.site is not None and plugin.session.site.grids == []
    plugin.unload()


def test_open_grid_dialog_reports_a_duplicate_id_through_the_message_bar(
    fake_iface, tmp_path, drive_dialog, answer_modal
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

    def driver(dialog: GridDialog) -> None:
        dialog.id_edit.setText("A")
        dialog.velocity.setValue(0.08)
        dialog.accept()

    drive_dialog(QDialog, "exec", driver)
    plugin.open_grid_dialog(None)
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "already exists" in item.text()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_open_grid_dialog_edits_an_existing_grid(fake_iface, tmp_path, drive_dialog, answer_modal):
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

    def driver(dialog: GridDialog) -> None:
        assert dialog.id_edit.text() == "A" and not dialog.id_edit.isEnabled()
        dialog.azimuth.setValue(46.0)
        dialog.accept()

    drive_dialog(QDialog, "exec", driver)
    plugin.open_grid_dialog("A")
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


def test_digitise_flow_recovers_from_coincident_points(fake_iface, tmp_path, drive_dialog):
    # set_digitised() now rejects two clicks landing on the same point;
    # the plugin's done() callback must still hand control back to the
    # dialog (unset the map tool, show() it again) and tell the user why
    # nothing was filled in, rather than leave the map tool stuck active
    # with the dialog invisible and no explanation.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    canvas = fake_iface.mapCanvas()

    def driver(dialog: GridDialog) -> None:
        dialog.digitise_button.click()
        tool = canvas.mapTool()
        tool.canvasClicked.emit(QgsPointXY(1.0, 1.0), Qt.MouseButton.LeftButton)
        tool.canvasClicked.emit(QgsPointXY(1.0, 1.0), Qt.MouseButton.LeftButton)  # same point

        assert canvas.mapTool() is None  # control handed back regardless
        assert not dialog.isHidden()
        item = fake_iface.messageBar().currentItem()
        assert item is not None and "coincide" in item.text()
        assert dialog.azimuth.value() == 0.0  # untouched

        dialog.reject()

    drive_dialog(QDialog, "exec", driver)
    plugin.open_grid_dialog(None)
    plugin.unload()


def test_digitise_flow_through_the_plugin_fills_and_restores_the_dialog(
    fake_iface, tmp_path, drive_dialog, answer_modal
):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    canvas = fake_iface.mapCanvas()

    def driver(dialog: GridDialog) -> None:
        dialog.digitise_button.click()
        tool = canvas.mapTool()
        assert isinstance(tool, DigitiseGridTool)

        tool.canvasClicked.emit(QgsPointXY(500.0, 700.0), Qt.MouseButton.LeftButton)
        tool.canvasClicked.emit(
            QgsPointXY(500.0 + 5.0 * np.sin(np.radians(30)), 700.0 + 5.0 * np.cos(np.radians(30))),
            Qt.MouseButton.LeftButton,
        )

        assert canvas.mapTool() is None  # the tool hands control back
        assert not dialog.isHidden()  # and the dialog is restored
        assert dialog.origin_x.value() == pytest.approx(500.0)
        assert dialog.origin_y.value() == pytest.approx(700.0)
        assert dialog.azimuth.value() == pytest.approx(30.0, abs=1e-6)

        dialog.id_edit.setText("D")
        dialog.velocity.setValue(0.08)
        # done() adopts canvas.mapSettings().destinationCrs(), which is
        # invalid on this bare test canvas (no project/layer ever set
        # one) -- a real user's canvas has the project's CRS. Set one
        # explicitly so this test's accept() reflects a real usable
        # state rather than incidentally re-proving Finding 2 (crs="").
        dialog.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32616"))
        dialog.accept()

    calls = drive_dialog(QDialog, "exec", driver)
    plugin.open_grid_dialog(None)
    assert len(calls) == 1
    grid = plugin.session.grid("D")
    assert grid.azimuth == pytest.approx(30.0, abs=1e-6)
    assert grid.crs == "EPSG:32616"
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_digitise_flow_right_click_restores_the_dialog_without_a_pick(
    fake_iface, tmp_path, drive_dialog
):
    # Fix round 1, Finding 4: before this fix, a right-click meant to
    # cancel instead completed the pick (or set the origin), and there
    # was no way back short of killing QGIS if the pick was abandoned.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    canvas = fake_iface.mapCanvas()

    def driver(dialog: GridDialog) -> None:
        dialog.digitise_button.click()
        assert dialog.isHidden()
        tool = canvas.mapTool()
        tool.canvasClicked.emit(QgsPointXY(1.0, 1.0), Qt.MouseButton.LeftButton)
        tool.canvasClicked.emit(QgsPointXY(2.0, 2.0), Qt.MouseButton.RightButton)  # abort

        assert canvas.mapTool() is None
        assert not dialog.isHidden()  # restored -- without ever completing the pick
        assert dialog.azimuth.value() == 0.0  # untouched

        dialog.reject()

    drive_dialog(QDialog, "exec", driver)
    plugin.open_grid_dialog(None)
    plugin.unload()


def test_digitise_flow_switching_map_tools_restores_the_dialog(fake_iface, tmp_path, drive_dialog):
    # Fix round 1, Finding 4: switching to a completely different map
    # tool (e.g. Pan) mid-pick used to leave the dialog hidden forever,
    # since only done() (a successful two-click pick) ever restored it.
    import nsgeo_qgis
    from qgis.gui import QgsMapToolPan

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    canvas = fake_iface.mapCanvas()

    def driver(dialog: GridDialog) -> None:
        dialog.digitise_button.click()
        assert dialog.isHidden()
        canvas.setMapTool(QgsMapToolPan(canvas))
        assert not dialog.isHidden()
        dialog.reject()

    drive_dialog(QDialog, "exec", driver)
    plugin.open_grid_dialog(None)
    plugin.unload()


def test_open_grid_dialog_releases_a_stranded_map_tool_on_close(fake_iface, tmp_path, drive_dialog):
    # Fix round 2, Finding 4: dialog.exec() can return (accept, reject,
    # or the dialog closed outright) while a digitise pick is still in
    # progress, with neither done() nor the tool's own cancelled signal
    # ever having fired to release it -- e.g. a keyboard shortcut, or
    # (as simulated here) a caller that just gives up on the pick
    # without clicking the map or right-clicking to abort. Before this
    # fix that left a live DigitiseGridTool wired to a `dialog`
    # open_grid_dialog was about to delete; a later click on it raised
    # RuntimeError out of a signal-connected slot.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    canvas = fake_iface.mapCanvas()

    def driver(dialog: GridDialog) -> None:
        dialog.digitise_button.click()
        assert isinstance(canvas.mapTool(), DigitiseGridTool)
        dialog.reject()  # gives up on the pick entirely, tool still active

    drive_dialog(QDialog, "exec", driver)
    plugin.open_grid_dialog(None)  # must not raise
    assert canvas.mapTool() is None  # released, not left stranded
    plugin.unload()


def test_open_grid_dialog_seeds_velocity_from_the_header_dielectric(
    fake_iface, tmp_path, drive_dialog, answer_modal
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

    def driver(dialog: GridDialog) -> None:
        # velocity is a 4-decimal QDoubleSpinBox, so setValue() itself
        # rounds -- compare at that precision, not the raw float's.
        assert dialog.velocity.value() == pytest.approx(expected, abs=5e-5)
        assert "dielectric" in dialog.velocity_hint.text().lower()
        dialog.reject()

    drive_dialog(QDialog, "exec", driver)
    # grid_id=None and no grids yet: open_grid_dialog's "new grid" path,
    # which is the one that seeds the suggestion.
    plugin.open_grid_dialog(None)
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
