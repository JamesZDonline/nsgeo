"""`plugin.py`'s two Task 6 dialogs: `save_cube`/`export_geotiff`, driven end to end.

Task 6 fix round 1, Important 4: nothing previously exercised `save_button`,
`export_button`, either signal, `plugin.save_cube`, `plugin.export_geotiff`, or
`QFileDialog.getSaveFileName` -- the throwaway smoke test that proved the
wiring worked was deleted before that task was committed. This file is the
permanent replacement, and covers exactly what the two findings that lived
here (Important 1, Important 2's `save_cube` half) needed: a dotted name
producing two distinct records, the save path validating before it writes,
the `<grid_id>__<name>` id contract, the dirty flag, and the exported layer
joining `layers.group`.
"""

from __future__ import annotations

import os
import threading
import time

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.export_task import running_export
from nsgeo_qgis.slices_plan import REFINING_SLICE_INDICATOR
from plugin_testing import (
    ExportGate,
    connect_message_log,
    drag_in_layers_panel,
    drive_export_dialog,
    synthetic_dzt,
    wait_for_export,
)
from qgis.core import Qgis, QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication, QEvent
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [
    {"step": "time_zero", "params": {}, "enabled": True},
    {"step": "dewow", "params": {}, "enabled": True},
    {"step": "gain_agc", "params": {}, "enabled": True},
]


@pytest.fixture
def plugin(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    lines = []
    for i in range(4):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", 1.0 + i * 1.0, 0.0, 1, p.stem)))
    s.add_lines(lines)
    s.site.presets["p"] = list(PRESET)
    # site.presets was set directly (bypassing whatever public API would
    # emit presets_changed), so the dock's preset_combo has not been
    # refilled with "p" yet -- force it, the same way a real
    # presets_changed would.
    plugin.slices_dock.rebuild_source()
    yield plugin, s
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
    # The export dialog is deleted later; the session's QgsApplication goes right after
    # the last test, and a dialog still alive then is destroyed against a dead one.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _prepare(plugin) -> None:
    dock = plugin.slices_dock
    dock.grid_combo.setCurrentText("A")
    dock.preset_combo.setCurrentText("p")
    dock.transform_combo.set_value("amp_envelope")
    assert dock.engine.wait_for_preparation(20_000), "preparation did not finish"
    dock.cell_spin.setValue(0.25)
    dock.dz_spin.setValue(0.5)
    dock.z0_spin.setValue(2.0)
    dock.z1_spin.setValue(30.0)
    dock.flush_debounce()


def test_buttons_are_disabled_until_prepared(plugin):
    plugin, _s = plugin
    dock = plugin.slices_dock
    assert not dock.save_button.isEnabled()
    assert not dock.export_button.isEnabled()
    _prepare(plugin)
    assert dock.save_button.isEnabled()
    assert dock.export_button.isEnabled()


def test_save_cube_refuses_a_click_before_preparation(plugin, message_log):
    """Important 2's `save_cube` half, reachable even with the button
    disabled: a direct call (or a stale enabled state mid-race) must not
    reach the engine at all."""
    plugin, s = plugin
    plugin.save_cube()
    assert any("prepare a slice source" in m for m in message_log)
    assert s.site.cubes == {}


def test_export_geotiff_refuses_a_click_before_preparation(plugin, message_log, tmp_path):
    plugin, s = plugin
    plugin.export_geotiff()
    assert any("prepare a slice source" in m for m in message_log)
    assert not any(tmp_path.glob("**/*.tif"))


def test_save_cube_with_dotted_names_produces_distinct_records(plugin, tmp_path, answer_modal):
    """Important 1: `store.npz_path`'s own hazard -- a user-typed name
    with a dot that is NOT an extension. The dialog string must be typed
    WITHOUT ".npz" for this to reproduce (`npz_path` appends it): typing
    "cube.v1" and "cube.v2" -- not "cube.v1.npz" -- is exactly the
    coordinator's own table. `Path("cube.v1").stem` is "cube" (pathlib
    treats ".v1" as the extension), so deriving the id from the RAW
    dialog string collided both saves onto "A__cube"; deriving it from
    `Path(npz_path).stem` (the file `npz_path` actually wrote,
    "cube.v1.npz") keeps them apart. A first version of this test typed
    the ".npz" suffix explicitly and passed against the pre-fix code too
    -- it never exercised the collision at all, since `path` and
    `npz_path` were then identical regardless of which one plugin.py
    read the stem from."""
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock

    target1 = tmp_path / "slices" / "cube.v1"  # no .npz -- npz_path appends it
    target1.parent.mkdir(parents=True, exist_ok=True)
    answer_modal(QFileDialog, "getSaveFileName", (str(target1), "nsgeo cube (*.npz)"))
    dock.save_button.click()
    written1 = target1.parent / "cube.v1.npz"
    assert written1.exists()
    assert "A__cube.v1" in s.site.cubes
    assert s.site.cubes["A__cube.v1"]["array"] == "slices/cube.v1.npz"
    # The recipe stores the transform's id, never the title the combo shows.
    assert s.site.cubes["A__cube.v1"]["transform"] == "amp_envelope"

    target2 = tmp_path / "slices" / "cube.v2"
    answer_modal(QFileDialog, "getSaveFileName", (str(target2), "nsgeo cube (*.npz)"))
    dock.save_button.click()
    written2 = target2.parent / "cube.v2.npz"
    assert written2.exists()
    assert "A__cube.v2" in s.site.cubes
    assert s.site.cubes["A__cube.v2"]["array"] == "slices/cube.v2.npz"

    # Both must survive as distinct records pointing at distinct files --
    # the exact case that used to collide.
    assert written1.exists() and written2.exists()
    assert set(s.site.cubes) == {"A__cube.v1", "A__cube.v2"}
    assert s.dirty


def test_save_cube_validates_the_destination_before_writing_anything(
    plugin, tmp_path, answer_modal, message_log
):
    """ "Also fold in" (Task 6 fix round 1): an out-of-tree destination
    must be refused before any work happens, not after the cube is built
    and compressed to disk."""
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    # `tmp_path.parent` is the whole pytest SESSION's shared temp root, not
    # this test's own -- a fixed "elsewhere/cube.npz" under it collides
    # with `test_plugin_slice_export.py`'s own out-of-tree test, which
    # writes there unconditionally (via save_cube_npz, before this test's
    # own assertion about non-existence would ever run). Qualified by
    # `tmp_path.name` (already unique per test) to avoid that collision.
    outside = tmp_path.parent / f"elsewhere-{tmp_path.name}" / "cube.npz"
    outside.parent.mkdir(parents=True, exist_ok=True)
    answer_modal(QFileDialog, "getSaveFileName", (str(outside), "nsgeo cube (*.npz)"))
    dock.save_button.click()
    assert not outside.exists(), "a refused save must not have written the cube first"
    assert s.site.cubes == {}
    assert any("project directory" in m or "portable" in m for m in message_log)


def _layer_for(plugin, path):
    return next(
        (v for v in plugin.layers.project.mapLayers().values() if v.source() == str(path)), None
    )


def _export(plugin, drive_dialog, target, **options):
    """Open the dialog from the Export button, answer it, and wait for the task."""
    shown = drive_export_dialog(drive_dialog, path=target, **options)
    plugin.slices_dock.export_button.click()
    wait_for_export()
    return shown


def _levels():
    """Message log entries `(text, level)` while the test runs; call `.stop()` after."""
    entries: list[tuple[str, object]] = []
    disconnect = connect_message_log(lambda msg, tag, level: entries.append((msg, level)))
    return entries, disconnect


def test_export_geotiff_adds_a_layer_to_the_slices_group(plugin, tmp_path, drive_dialog):
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    # Keep this test focused on the layer-join claim, with a finish that does work.
    dock.grid_finish.max_distance_spin.setValue(1.0)  # 0.5 m on this grid's 0.5 m spacing
    dock._finish_debounce.stop()
    assert dock.slice_finish().method != "none"

    target = tmp_path / "slices" / "cube.tif"
    shown = _export(plugin, drive_dialog, target)
    assert len(shown) == 1 and shown[0].windowTitle() == "Export GeoTIFF"
    assert shown[0].path_edit.text().replace("\\", "/").endswith("slices/cube.tif")
    assert "Grids" not in dict(shown[0].summary_rows()), "This grid has no Grids row"
    assert target.exists()

    layer = _layer_for(plugin, target)
    assert layer is not None and layer.isValid()
    assert plugin.layers.group is not None
    assert plugin.layers.group.findLayer(layer.id()) is not None
    assert layer.temporalProperties().isActive()


def test_an_export_joins_the_site_group_after_the_user_dragged_it(
    plugin, tmp_path, drive_dialog, message_log
):
    """#68: a drag in the Layers panel replaces the group's node with a copy.
    The export still finds the group, and does not report a failure."""
    plugin, s = plugin
    _prepare(plugin)
    project = plugin.layers.project
    root = project.layerTreeRoot()
    imagery = QgsVectorLayer("Polygon?crs=EPSG:32616", "imagery", "memory")
    project.addMapLayer(imagery)
    try:
        drag_in_layers_panel(project, plugin.layers.group, root, len(root.children()))
        target = tmp_path / "slices" / "cube.tif"
        _export(plugin, drive_dialog, target)
        layer = _layer_for(plugin, target)
        assert plugin.layers.group.findLayer(layer.id()) is not None
        assert not any("could not export" in m for m in message_log)
    finally:
        project.removeMapLayer(imagery.id())


def test_an_export_after_the_user_deleted_the_site_group_still_shows(
    plugin, tmp_path, drive_dialog, qgis_app
):
    """With the group gone, the exported layer goes on top of the Layers
    panel rather than into the project with no place in the panel."""
    plugin, s = plugin
    _prepare(plugin)
    project = plugin.layers.project
    project.layerTreeRoot().removeChildNode(plugin.layers.group)
    qgis_app.processEvents()  # the project drops the group's layers on a queued call

    target = tmp_path / "slices" / "cube.tif"
    _export(plugin, drive_dialog, target)
    layer = _layer_for(plugin, target)

    assert project.layerTreeRoot().children()[0].layerId() == layer.id()


def test_exporting_a_rotated_grid_reports_no_fill_warning(plugin, tmp_path, drive_dialog):
    """Ruling AE, reworked (interpolation spec §8): a rotated frame is
    resampled bilinearly at the cell, so it drops no cell and the success message
    is plain Info -- whatever the interpolation, `none` included."""
    plugin, s = plugin
    s.replace_grid(Grid("A", (500.0, 700.0), 30.0, 6.0, 6.0, "EPSG:32616", 0.5))
    _prepare(plugin)
    dock = plugin.slices_dock
    assert dock.engine.frame.azimuth == 30.0
    dock.grid_finish.method_combo.setCurrentIndex(dock.grid_finish.method_combo.findData("none"))
    dock._finish_debounce.stop()
    assert dock.slice_finish().method == "none"

    levels, disconnect = _levels()
    try:
        _export(plugin, drive_dialog, tmp_path / "slices" / "cube.tif")
    finally:
        disconnect()

    exported = [(m, lv) for m, lv in levels if m.startswith("exported ")]
    assert len(exported) == 1 and exported[0][1] == Qgis.MessageLevel.Info
    assert not any(lv == Qgis.MessageLevel.Warning for _m, lv in levels)


def test_an_export_after_a_refused_resolution_uses_the_frames_cell(plugin, tmp_path, drive_dialog):
    """#104: a resolution the dock refuses (z1 <= z0) leaves the cell spin ahead of
    the engine's frame. The dialog starts from the frame's own cell, every band is
    finished at it, and the metadata's max distance is the grid's spacing times the
    setting."""
    from nsgeo.slices import plan_windows, to_north_up
    from nsgeo_qgis.slices_plan import SliceFinish
    from osgeo import gdal

    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    engine = dock.engine
    frame_cell = engine.frame.cell
    dock.cell_spin.setValue(0.5)  # a different cell...
    dock.z1_spin.setValue(dock.z0_spin.value() - 1.0)  # ...and a range the dock refuses
    errors: list[str] = []
    dock.error.connect(errors.append)
    dock.flush_debounce()
    assert errors, "the dock must have refused this resolution"
    assert engine.frame.cell == frame_cell != dock.cell_spin.value()

    target = tmp_path / "slices" / "cube.tif"
    shown = _export(plugin, drive_dialog, target)
    assert shown[0].cell_spin.value() == frame_cell

    thickness_levels, step_levels = dock.thickness_step_levels()
    windows = list(plan_windows(engine.z, thickness_levels, step_levels))
    finish = dock.slice_finish()
    ds = gdal.Open(str(target))
    try:
        assert ds.RasterCount == len(windows)
        assert float(ds.GetMetadataItem("NSGEO_MAX_DISTANCE_M")) == pytest.approx(
            SliceFinish().max_distance_spacings * 0.5
        )
        for index, window in enumerate(windows, start=1):
            want, _gt = to_north_up(engine.finish(*engine.slice_at(window), finish), engine.frame)
            got = ds.GetRasterBand(index).ReadAsArray()
            np.testing.assert_allclose(got, want, atol=1e-5, rtol=1e-5, equal_nan=True)
    finally:
        ds.Close()


def test_the_plugin_exports_the_docks_finish(plugin, tmp_path, drive_dialog):
    """The export takes the dock's own finish: the file's bands and metadata describe
    what the map shows, not the defaults. The oracle is the core pipeline."""
    from nsgeo.slices import finish_slice, plan_fill, plan_windows, to_north_up
    from osgeo import gdal

    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    panel = dock.grid_finish
    panel.method_combo.setCurrentIndex(panel.method_combo.findData("idw"))
    panel.max_distance_spin.setValue(1.0)
    panel.smooth_x_spin.setValue(0.25)
    dock._finish_debounce.stop()
    spacing = GRID.default_spacing

    target = tmp_path / "slices" / "cube.tif"
    _export(plugin, drive_dialog, target)

    engine = dock.engine
    cell = engine.frame.cell
    settings = engine.finish_settings(dock.slice_finish())
    thickness_levels, step_levels = dock.thickness_step_levels()
    windows = list(plan_windows(engine.z, thickness_levels, step_levels))
    ds = gdal.Open(str(target))
    try:
        tags = ds.GetMetadata()
        assert tags["NSGEO_INTERPOLATION"] == "idw"
        assert tags["NSGEO_MAX_DISTANCE_M"] == str(1.0 * spacing)
        assert tags["NSGEO_SMOOTH_X_M"] == "0.25"
        assert tags["NSGEO_SMOOTH_Y_M"] == "0.0"
        for index, window in enumerate(windows, start=1):
            values, coverage = engine.slice_at(window)
            weights = plan_fill(
                coverage > 0, cell, "idw", settings.max_distance_m, settings.search_radius_m
            )
            want, _gt = to_north_up(finish_slice(values, weights, cell, settings), engine.frame)
            got = ds.GetRasterBand(index).ReadAsArray()
            np.testing.assert_allclose(got, want, atol=1e-5, rtol=1e-5, equal_nan=True)
    finally:
        ds.Close()


def test_this_grid_at_a_finer_pixel_is_twice_the_width_and_height(
    plugin, tmp_path, drive_dialog, message_log
):
    from osgeo import gdal

    plugin, s = plugin
    _prepare(plugin)
    cell = plugin.slices_dock.engine.frame.cell
    live = tmp_path / "slices" / "live.tif"
    fine = tmp_path / "slices" / "fine.tif"
    _export(plugin, drive_dialog, live)
    _export(plugin, drive_dialog, fine, pixel=cell / 2)
    sizes, md = {}, {}
    for name, path in (("live", live), ("fine", fine)):
        ds = gdal.Open(str(path))
        try:
            sizes[name] = (ds.RasterXSize, ds.RasterYSize)
            md[name] = ds.GetMetadata()
        finally:
            ds.Close()
    assert sizes["fine"] == (2 * sizes["live"][0], 2 * sizes["live"][1])
    assert float(md["fine"]["NSGEO_PIXEL_M"]) == cell / 2
    assert float(md["fine"]["NSGEO_CELL_M"]) == cell
    assert md["fine"]["NSGEO_RESAMPLING"] == "bilinear"
    assert any(f"({cell:g} m cell, {cell / 2:g} m pixels)" in m for m in message_log)


def test_this_grid_at_a_finer_cell_names_it_in_the_file(plugin, tmp_path, drive_dialog):
    from osgeo import gdal

    plugin, s = plugin
    _prepare(plugin)
    cell = plugin.slices_dock.engine.frame.cell
    target = tmp_path / "slices" / "fine.tif"
    _export(plugin, drive_dialog, target, cell=cell / 2)
    ds = gdal.Open(str(target))
    try:
        md = ds.GetMetadata()
    finally:
        ds.Close()
    assert float(md["NSGEO_CELL_M"]) == cell / 2 and float(md["NSGEO_PIXEL_M"]) == cell / 2


def test_export_geotiff_also_writes_coverage_when_checked(plugin, tmp_path, drive_dialog):
    """Ruling AH: the companion is written when the dock's coverage toggle is on, with
    its own style file, and is added to the group beside the values."""
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    dock.coverage_check.setChecked(True)

    target = tmp_path / "slices" / "cube.tif"
    _export(plugin, drive_dialog, target)

    coverage = tmp_path / "slices" / "cube_coverage.tif"
    assert coverage.exists()
    assert coverage.with_suffix(".qml").exists() and target.with_suffix(".qml").exists()
    layer = _layer_for(plugin, coverage)
    assert layer is not None and layer.isValid()
    assert plugin.layers.group.findLayer(layer.id()) is not None


def test_the_style_file_carries_the_measured_limit_and_the_panels_colours(
    plugin, tmp_path, drive_dialog
):
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    dock.palette_combo.setCurrentText("amp_heat")
    target = tmp_path / "slices" / "cube.tif"
    _export(plugin, drive_dialog, target)
    layer = _layer_for(plugin, target)
    renderer = layer.renderer()
    assert renderer.type() == "singlebandpseudocolor"
    assert renderer.classificationMax() > 0
    text = target.with_suffix(".qml").read_text()
    assert "singlebandpseudocolor" in text


def test_a_failed_coverage_companion_does_not_report_the_main_export_as_failed(
    plugin, tmp_path, drive_dialog, message_log, monkeypatch
):
    """By the time the companion is added, the main GeoTIFF already exists and is already in
    `layers.group`: a failure with the companion reads at Warning, naming it."""
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    dock.coverage_check.setChecked(True)
    real = plugin._add_export_layer

    def fail_for_the_companion(path, **kwargs):
        if path.name.endswith("_coverage.tif"):
            raise OSError("disk full")
        return real(path, **kwargs)

    monkeypatch.setattr(plugin, "_add_export_layer", fail_for_the_companion)
    target = tmp_path / "slices" / "cube.tif"
    _export(plugin, drive_dialog, target)

    layer = _layer_for(plugin, target)
    assert layer is not None and layer.isValid()
    assert plugin.layers.group.findLayer(layer.id()) is not None
    assert not any("could not export the GeoTIFF" in m for m in message_log)
    assert any("coverage companion" in m and "disk full" in m for m in message_log)


# ---- the task: running, held, cancelled, failed ------------------------------------------


def test_the_live_view_stays_usable_while_the_export_is_held(
    plugin, tmp_path, drive_dialog, monkeypatch
):
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    gate = ExportGate(monkeypatch)
    drive_export_dialog(drive_dialog, path=tmp_path / "slices" / "cube.tif")
    dock.export_button.click()
    gate.wait_entered()
    try:
        assert running_export() is not None
        ticks: list[int] = []
        dock.slice_changed.connect(lambda: ticks.append(1))
        dock.refresh_slice()
        assert ticks, "a slice tick must run while the export task is held"
        assert dock.readout.text()
    finally:
        gate.release.set()
        wait_for_export()


def test_a_second_export_while_one_runs_is_refused_plainly(
    plugin, tmp_path, drive_dialog, monkeypatch, message_log
):
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    gate = ExportGate(monkeypatch)
    shown = drive_export_dialog(drive_dialog, path=tmp_path / "slices" / "cube.tif")
    dock.export_button.click()
    gate.wait_entered()
    try:
        before = len(shown)
        dock.export_button.click()
        assert len(shown) == before, "no second dialog opens"
        assert any("already running" in m for m in message_log)
    finally:
        gate.release.set()
        wait_for_export()


def test_a_cancelled_export_leaves_no_file_and_adds_no_layer(
    plugin, tmp_path, drive_dialog, monkeypatch
):
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    gate = ExportGate(monkeypatch)
    target = tmp_path / "slices" / "cube.tif"
    drive_export_dialog(drive_dialog, path=target)
    before = set(plugin.layers.project.mapLayers())
    levels, disconnect = _levels()
    try:
        dock.export_button.click()
        gate.wait_entered()
        running_export().cancel()  # the task list's Cancel
        wait_for_export()
    finally:
        disconnect()
    assert not target.exists()
    assert not list(target.parent.glob("*.partial*"))
    assert set(plugin.layers.project.mapLayers()) == before
    assert ("export cancelled", Qgis.MessageLevel.Info) in [(m.lower(), lv) for m, lv in levels]
    assert not any(lv == Qgis.MessageLevel.Critical for _m, lv in levels)


def test_a_cancelled_export_never_removes_a_file_it_did_not_reach(
    plugin, tmp_path, drive_dialog, monkeypatch
):
    """The dialog may choose a file to replace. Until the export has committed over it,
    it is the user's: the new bands are written to a temporary name."""
    plugin, s = plugin
    _prepare(plugin)
    gate = ExportGate(monkeypatch)
    target = tmp_path / "slices" / "cube.tif"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"the user's own file")
    drive_export_dialog(drive_dialog, path=target)
    plugin.slices_dock.export_button.click()
    gate.wait_entered()
    running_export().cancel()
    wait_for_export()
    assert target.read_bytes() == b"the user's own file"


def test_a_failed_export_leaves_no_file_and_says_why_in_plain_words(
    plugin, tmp_path, drive_dialog, monkeypatch, message_log
):
    from nsgeo_qgis.slice_export import GeoTiffSliceWriter

    plugin, s = plugin
    _prepare(plugin)
    real = GeoTiffSliceWriter.write_bands

    def dies_after_the_first_band(self, path, plan, bands, **kwargs):
        def first_only():
            for index, band in enumerate(bands):
                if index == 1:
                    raise OSError(28, "No space left on device")
                yield band

        return real(self, path, plan, first_only(), **kwargs)

    monkeypatch.setattr(GeoTiffSliceWriter, "write_bands", dies_after_the_first_band)
    target = tmp_path / "slices" / "cube.tif"
    before = set(plugin.layers.project.mapLayers())
    levels, disconnect = _levels()
    try:
        _export(plugin, drive_dialog, target)
    finally:
        disconnect()
    assert not target.exists() and not list(target.parent.glob("*.partial*"))
    assert set(plugin.layers.project.mapLayers()) == before
    critical = [m for m, lv in levels if lv == Qgis.MessageLevel.Critical]
    plain = "could not export the GeoTIFF: there is not enough free disk space to finish it"
    assert critical and all(m.endswith(plain) for m in critical), critical
    assert any("No space left on device" in m for m, _lv in levels), "the raw text stays in the log"


def test_a_missing_target_folder_is_created(plugin, tmp_path, drive_dialog):
    plugin, s = plugin
    _prepare(plugin)
    target = tmp_path / "new" / "deeper" / "cube.tif"
    _export(plugin, drive_dialog, target)
    assert target.exists()


def test_an_export_that_finishes_after_the_site_closed_adds_nothing(
    plugin, tmp_path, drive_dialog, monkeypatch, message_log
):
    """A cancel can land after the task's last check, and the task still commits. The file
    stays on disk and no layer is added to a closed site (late-cancel re-check)."""
    plugin, s = plugin
    _prepare(plugin)
    gate = ExportGate(monkeypatch)
    target = tmp_path / "slices" / "cube.tif"
    drive_export_dialog(drive_dialog, path=target)
    before = set(plugin.layers.project.mapLayers())
    plugin.slices_dock.export_button.click()
    gate.wait_entered()
    plugin._export_epoch += 1  # the site closed (and the cancel was too late to stop the write)
    gate.release.set()
    wait_for_export()
    assert target.exists()
    assert set(plugin.layers.project.mapLayers()) == before
    assert any("after the site was closed" in m for m in message_log)


def test_closing_the_site_cancels_the_export_and_adds_no_layer(
    plugin, tmp_path, drive_dialog, monkeypatch, answer_modal
):
    plugin, s = plugin
    _prepare(plugin)
    gate = ExportGate(monkeypatch)
    target = tmp_path / "slices" / "cube.tif"
    drive_export_dialog(drive_dialog, path=target)
    plugin.slices_dock.export_button.click()
    gate.wait_entered()
    task = running_export()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    s.close_site()
    wait_for_export()
    assert task.isCanceled()
    assert not target.exists()
    assert not list(plugin.layers.project.mapLayers().values()) or all(
        v.source() != str(target) for v in plugin.layers.project.mapLayers().values()
    )


def test_unloading_the_plugin_cancels_the_export(
    plugin, tmp_path, drive_dialog, monkeypatch, answer_modal
):
    plugin, s = plugin
    _prepare(plugin)
    gate = ExportGate(monkeypatch)
    target = tmp_path / "slices" / "cube.tif"
    drive_export_dialog(drive_dialog, path=target)
    plugin.slices_dock.export_button.click()
    gate.wait_entered()
    task = running_export()
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
    wait_for_export()
    assert task.isCanceled()
    assert not target.exists()


def test_replacing_a_target_removes_its_layer_first_and_adds_the_new_one_after(
    plugin, tmp_path, drive_dialog, monkeypatch
):
    plugin, s = plugin
    _prepare(plugin)
    target = tmp_path / "slices" / "cube.tif"
    _export(plugin, drive_dialog, target)
    old = _layer_for(plugin, target)
    old_id = old.id()
    gate = ExportGate(monkeypatch)
    drive_export_dialog(drive_dialog, path=target, replace=True)
    plugin.slices_dock.export_button.click()
    gate.wait_entered()
    try:
        assert old_id not in plugin.layers.project.mapLayers(), "removed before the task runs"
        assert target.exists(), "the old file is still there until the new one is ready"
    finally:
        gate.release.set()
        wait_for_export()
    new = _layer_for(plugin, target)
    assert new is not None and new.isValid() and new.id() != old_id
    assert plugin.layers.group.findLayer(new.id()) is not None


def test_the_replace_prompt_declined_starts_nothing(plugin, tmp_path, drive_dialog):
    plugin, s = plugin
    _prepare(plugin)
    target = tmp_path / "slices" / "cube.tif"
    _export(plugin, drive_dialog, target)
    layer = _layer_for(plugin, target)
    mtime = os.stat(target).st_mtime_ns
    drive_export_dialog(drive_dialog, path=target, replace=False)
    plugin.slices_dock.export_button.click()
    assert running_export() is None
    assert layer.id() in plugin.layers.project.mapLayers()
    assert os.stat(target).st_mtime_ns == mtime


class _Looping:
    """A refine job that runs until it is asked to stop, or 10 s pass."""

    key = b"looping"
    engine = None

    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped_by_request = False

    def run(self, should_stop) -> None:
        self.started.set()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if should_stop():
                self.stopped_by_request = True
                return
            time.sleep(0.001)

    def land(self) -> bool:
        return False


def _pump_until(predicate, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() > deadline:
            pytest.fail("timed out waiting for the condition")
        QCoreApplication.processEvents()
        time.sleep(0.002)


def _set_method(dock, method):
    panel = dock.grid_finish
    panel.method_combo.setCurrentIndex(panel.method_combo.findData(method))
    dock._finish_debounce.stop()
    dock._on_finish_timeout()


def test_an_export_leaves_a_running_refine_alone(plugin, tmp_path, drive_dialog, monkeypatch):
    """The export no longer solves on this thread, so it has nothing to pause: the
    panel's refine keeps running while the export is held, and its indicator stays."""
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    job = _Looping()
    monkeypatch.setattr(dock.engine, "pending_solve", lambda *args, **kwargs: job)
    _set_method(dock, "min_curvature")  # a new plan's first draw is a preview
    assert dock.provisional
    _pump_until(job.started.is_set)
    assert dock.refiner.busy
    assert dock.refine_label.text() == REFINING_SLICE_INDICATOR

    gate = ExportGate(monkeypatch)
    drive_export_dialog(drive_dialog, path=tmp_path / "slices" / "cube.tif")
    dock.export_button.click()
    gate.wait_entered()
    try:
        QCoreApplication.processEvents()
        assert dock.refiner.busy
        assert not job.stopped_by_request
        assert dock.refine_label.text() == REFINING_SLICE_INDICATOR
    finally:
        gate.release.set()
        wait_for_export()
        dock.refiner.cancel()


def test_a_minimum_curvature_export_records_its_method_and_never_writes_a_preview(
    plugin, tmp_path, drive_dialog
):
    from nsgeo.slices import plan_windows, to_north_up
    from osgeo import gdal

    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    _set_method(dock, "min_curvature")
    engine = dock.engine
    target = tmp_path / "slices" / "cube.tif"
    _export(plugin, drive_dialog, target)
    assert target.exists()

    thickness_levels, step_levels = dock.thickness_step_levels()
    windows = list(plan_windows(engine.z, thickness_levels, step_levels))
    finish = dock.slice_finish()
    ds = gdal.Open(str(target))
    try:
        assert ds.GetMetadataItem("NSGEO_INTERPOLATION") == "min_curvature"
        assert ds.RasterCount == len(windows)
        previews_differ = False
        for index, window in enumerate(windows, start=1):
            values, coverage = engine.slice_at(window)
            full, _gt = to_north_up(engine.finish(values, coverage, finish), engine.frame)
            drawn, _gt = to_north_up(engine.preview(values, coverage, finish), engine.frame)
            got = ds.GetRasterBand(index).ReadAsArray()
            np.testing.assert_allclose(got, full, atol=1e-4, rtol=1e-4, equal_nan=True)
            previews_differ |= not np.allclose(full, drawn, equal_nan=True, atol=1e-4)
        assert previews_differ, "the preview matched everywhere: this test would not tell"
    finally:
        ds.Close()


def test_a_real_export_touches_no_live_engine_or_session_off_the_gui_thread(
    plugin, tmp_path, drive_dialog, monkeypatch
):
    """Review Focus 2: a recorder on the live engine and the session, then a real export
    through the plugin. Whatever the snapshot read, it read on this thread; nothing was
    read while the task ran, and the task did run on another thread."""
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    main = threading.current_thread()
    off_thread: list[str] = []

    def spy(owner, name):
        real = getattr(owner, name)

        def wrapper(*args, **kwargs):
            if threading.current_thread() is not main:
                off_thread.append(name)
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, name, wrapper)

    for name in (
        "slice_at",
        "finish",
        "_slice",
        "cube",
        "prepared_lines",
        "finish_settings",
        "provenance",
        "set_resolution",
    ):
        spy(dock.engine, name)
    for name in ("grid", "grid_gain", "keys", "line_key"):
        if hasattr(s, name):
            spy(s, name)
    gate = ExportGate(monkeypatch)
    drive_export_dialog(drive_dialog, path=tmp_path / "slices" / "cube.tif")
    dock.export_button.click()
    gate.wait_entered()
    gate.release.set()
    wait_for_export()
    assert (tmp_path / "slices" / "cube.tif").exists()
    assert off_thread == []
    assert gate.threads and gate.threads[0] != main.name


def _drawn_values(layer):
    """The finite pixel values the slice layer's provider holds."""
    block = layer.dataProvider().block(1, layer.extent(), layer.width(), layer.height())
    values = np.array(
        [[block.value(r, c) for c in range(block.width())] for r in range(block.height())]
    )
    return values[np.isfinite(values) & (values > -1e30)]


def test_the_plugin_draws_a_rotated_coverage_view_as_whole_counts(plugin, qgis_app):
    """The plugin passes the coverage check to the layer as `counts=`: the
    drawn counts are whole numbers, and the same view with coverage off is
    blended, not largest-count sampled. A hard-coded False at that call site would
    blend the counts; a hard-coded True would largest-count sample the amplitudes."""
    plugin, s = plugin
    s.replace_grid(Grid("A", (500.0, 700.0), 30.0, 6.0, 6.0, "EPSG:32616", 0.5))
    _prepare(plugin)
    dock = plugin.slices_dock
    assert dock.engine.frame.azimuth == 30.0

    dock.coverage_check.setChecked(True)
    qgis_app.processEvents()
    counts = _drawn_values(plugin.slice_layer.layer)
    assert counts.size > 0 and (counts >= 1).all()
    np.testing.assert_array_equal(counts, np.round(counts))

    dock.coverage_check.setChecked(False)
    qgis_app.processEvents()
    amplitudes = _drawn_values(plugin.slice_layer.layer)
    # Largest count among the in-frame positive-weight corners only ever
    # returns cell values; a blend does not only return cell values.
    cells = np.asarray(dock.current_values(), dtype=np.float32)
    assert not np.isin(amplitudes.astype(np.float32), cells).all()


def test_an_exported_layer_and_its_coverage_are_drawn_smooth(plugin, tmp_path, drive_dialog):
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    dock.coverage_check.setChecked(True)
    target = tmp_path / "slices" / "cube.tif"
    _export(plugin, drive_dialog, target)
    sources = {str(target), str(tmp_path / "slices" / "cube_coverage.tif")}
    found = [v for v in plugin.layers.project.mapLayers().values() if v.source() in sources]
    assert len(found) == 2
    for layer in found:
        assert layer.resampleFilter().zoomedInResampler().type() == "bilinear"
