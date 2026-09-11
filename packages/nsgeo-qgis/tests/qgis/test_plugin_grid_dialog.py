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


def _dispose(qgis_app: object, dialog: GridDialog) -> None:
    """Explicitly destroy a GridDialog that went through the digitise
    flow, instead of leaving it to Python's garbage collector.

    GridDialog connects its own digitise_requested signal to a lambda
    that captures the dialog itself (plugin.py's open_grid_dialog), and
    the plugin's done() callback connects a DigitiseGridTool's
    points_picked to a closure that captures the tool. Both are
    reference cycles that PyQt's QObject wrapper does not expose to
    Python's cyclic collector (confirmed with gdb: gc.collect() does not
    free them), so they survive until CPython's own shutdown-time
    cleanup -- by which point qgis_app's exitQgis() has already
    destroyed the QApplication, and destroying the leftover widgets then
    (QWidget::~QWidget -> clearFocus() -> QApplication::focusChanged on
    a gone QApplication) segfaults. Explicitly deleting the dialog while
    the QApplication is still alive sidesteps this rather than trying to
    avoid every such cycle in application code.
    """
    from qgis.PyQt.QtCore import QEvent

    dialog.deleteLater()
    qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_ok_is_blocked_until_id_and_velocity_are_set(session):
    d = GridDialog(session)
    assert not d.ok_button.isEnabled()
    d.id_edit.setText("A")
    assert not d.ok_button.isEnabled()  # velocity still 0 = required
    d.velocity.setValue(0.08)
    assert d.ok_button.isEnabled()


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


def test_digitise_flow_recovers_from_coincident_points(
    qgis_app, fake_iface, tmp_path, drive_dialog
):
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

    calls = drive_dialog(QDialog, "exec", driver)
    plugin.open_grid_dialog(None)
    plugin.unload()
    _dispose(qgis_app, calls[0])


def test_digitise_flow_through_the_plugin_fills_and_restores_the_dialog(
    qgis_app, fake_iface, tmp_path, drive_dialog, answer_modal
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
        dialog.accept()

    calls = drive_dialog(QDialog, "exec", driver)
    plugin.open_grid_dialog(None)
    assert len(calls) == 1
    grid = plugin.session.grid("D")
    assert grid.azimuth == pytest.approx(30.0, abs=1e-6)
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
    _dispose(qgis_app, calls[0])
