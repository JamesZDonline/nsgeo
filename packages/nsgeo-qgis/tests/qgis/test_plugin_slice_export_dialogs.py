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

import contextlib
import threading
import time

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.slices_plan import PREVIEW_INDICATOR, REFINING_SLICE_INDICATOR
from plugin_testing import drag_in_layers_panel, synthetic_dzt
from qgis.core import Qgis, QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication, Qt
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


def test_export_geotiff_adds_a_layer_to_the_slices_group(plugin, tmp_path, answer_modal):
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    # Keep this test focused on the layer-join claim, with a finish that does work.
    dock.grid_finish.max_distance_spin.setValue(1.0)  # 0.5 m on this grid's 0.5 m spacing
    dock._finish_debounce.stop()
    assert dock.slice_finish().method != "none"

    target = tmp_path / "slices" / "cube.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
    dock.export_button.click()
    assert target.exists()

    layer = next(
        (v for v in plugin.layers.project.mapLayers().values() if v.source() == str(target)),
        None,
    )
    assert layer is not None and layer.isValid()
    assert plugin.layers.group is not None
    assert plugin.layers.group.findLayer(layer.id()) is not None
    assert layer.temporalProperties().isActive()


def _export(plugin, tmp_path, answer_modal):
    _prepare(plugin)
    target = tmp_path / "slices" / "cube.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
    plugin.slices_dock.export_button.click()
    assert target.exists()
    return next(v for v in plugin.layers.project.mapLayers().values() if v.source() == str(target))


def test_an_export_joins_the_site_group_after_the_user_dragged_it(
    plugin, tmp_path, answer_modal, message_log
):
    """#68: a drag in the Layers panel replaces the group's node with a copy.
    The export still finds the group, and does not report a failure."""
    plugin, s = plugin
    project = plugin.layers.project
    root = project.layerTreeRoot()
    imagery = QgsVectorLayer("Polygon?crs=EPSG:32616", "imagery", "memory")
    project.addMapLayer(imagery)
    try:
        drag_in_layers_panel(project, plugin.layers.group, root, len(root.children()))

        layer = _export(plugin, tmp_path, answer_modal)

        assert plugin.layers.group.findLayer(layer.id()) is not None
        assert not any("could not export" in m for m in message_log)
    finally:
        project.removeMapLayer(imagery.id())


def test_an_export_after_the_user_deleted_the_site_group_still_shows(
    plugin, tmp_path, answer_modal, qgis_app
):
    """With the group gone, the exported layer goes on top of the Layers
    panel rather than into the project with no place in the panel."""
    plugin, s = plugin
    project = plugin.layers.project
    project.layerTreeRoot().removeChildNode(plugin.layers.group)
    qgis_app.processEvents()  # the project drops the group's layers on a queued call

    layer = _export(plugin, tmp_path, answer_modal)

    assert project.layerTreeRoot().children()[0].layerId() == layer.id()


def _export_levels(dock, tmp_path, answer_modal):
    """Export through the button and return the message levels pushed to the log."""
    from plugin_testing import connect_message_log

    levels: list[tuple[str, object]] = []
    disconnect = connect_message_log(lambda msg, tag, level: levels.append((msg, level)))
    try:
        target = tmp_path / "slices" / "cube.tif"
        target.parent.mkdir(parents=True, exist_ok=True)
        answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
        dock.export_button.click()
        assert target.exists()
    finally:
        disconnect()
    return target, levels


def test_exporting_a_rotated_grid_reports_no_fill_warning(plugin, tmp_path, answer_modal):
    """Ruling AE, reworked (interpolation spec §8): a rotated frame is
    resampled bilinearly at the cell, so it drops no cell and the success message
    is plain Info -- whatever the interpolation, `none` included. This
    replaces the radius-0 warning, which no longer has a condition."""
    from qgis.core import Qgis

    plugin, s = plugin
    s.replace_grid(Grid("A", (500.0, 700.0), 30.0, 6.0, 6.0, "EPSG:32616", 0.5))
    _prepare(plugin)
    dock = plugin.slices_dock
    assert dock.engine.frame.azimuth == 30.0
    dock.grid_finish.method_combo.setCurrentIndex(dock.grid_finish.method_combo.findData("none"))
    dock._finish_debounce.stop()
    assert dock.slice_finish().method == "none"

    _target, levels = _export_levels(dock, tmp_path, answer_modal)

    exported = [(m, lv) for m, lv in levels if m.startswith("exported ")]
    assert len(exported) == 1 and exported[0][1] == Qgis.MessageLevel.Info
    assert not any(lv == Qgis.MessageLevel.Warning for _m, lv in levels)


def test_an_export_after_a_refused_resolution_uses_the_frames_cell(plugin, tmp_path, answer_modal):
    """#104: a resolution the dock refuses (z1 <= z0) leaves the cell spin
    ahead of the engine's frame. The export used to take its fill radius in
    cells from the spin, so the fill was sized for a cell the array does not
    have. Now every band is finished at the frame's own cell, and the
    metadata's max distance is the grid's spacing times the setting."""
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

    target, _levels = _export_levels(dock, tmp_path, answer_modal)

    thickness_levels, step_levels = dock.thickness_step_levels()
    from nsgeo.slices import plan_windows

    windows = list(plan_windows(engine.z, thickness_levels, step_levels))
    finish = dock.slice_finish()
    ds = gdal.Open(str(target))
    try:
        assert ds.RasterCount == len(windows)
        assert float(ds.GetMetadataItem("NSGEO_MAX_DISTANCE_M")) == pytest.approx(
            SliceFinish().max_distance_spacings * 0.5
        )
        from nsgeo.slices import to_north_up

        for index, window in enumerate(windows, start=1):
            want, _gt = to_north_up(engine.finish(*engine.slice_at(window), finish), engine.frame)
            got = ds.GetRasterBand(index).ReadAsArray()
            np.testing.assert_array_equal(got, want)
    finally:
        ds.Close()


def test_the_plugin_exports_the_docks_finish(plugin, tmp_path, answer_modal):
    """`export_geotiff` must hand the dock's own finish to the exporter: the
    file's bands and metadata describe what the map shows, not the defaults.
    The oracle is the core pipeline, not `engine.finish`."""
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

    target, _levels = _export_levels(dock, tmp_path, answer_modal)

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
            np.testing.assert_array_equal(ds.GetRasterBand(index).ReadAsArray(), want)
    finally:
        ds.Close()


def test_export_geotiff_also_writes_coverage_when_checked(plugin, tmp_path, answer_modal):
    """Ruling AH: `write_coverage` had no caller anywhere in the plugin
    before this fix -- wired to the dock's own coverage toggle, the
    control spec 9.4's "when asked" already refers to."""
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    dock.coverage_check.setChecked(True)

    target = tmp_path / "slices" / "cube.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
    dock.export_button.click()

    coverage_path = tmp_path / "slices" / "cube_coverage.tif"
    assert coverage_path.exists()
    layer = next(
        (v for v in plugin.layers.project.mapLayers().values() if v.source() == str(coverage_path)),
        None,
    )
    assert layer is not None and layer.isValid()
    assert plugin.layers.group.findLayer(layer.id()) is not None


def test_a_failed_coverage_companion_does_not_report_the_main_export_as_failed(
    plugin, tmp_path, answer_modal, message_log, monkeypatch
):
    """Task 6 fix round 2, Minor 2. By the time the coverage companion is
    written, the main GeoTIFF already exists, has its temporal properties
    applied, and is already in `layers.group` -- a failure writing the
    companion (a full disk, a locked file) must not read as the main
    export having failed. Cheaply provoked with a monkeypatch (a real
    full-disk/locked-file condition is not practical to set up in a unit
    test) rather than left unverified."""
    import nsgeo_qgis.plugin as plugin_module

    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    dock.coverage_check.setChecked(True)

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(plugin_module, "write_coverage", _boom)

    target = tmp_path / "slices" / "cube.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
    dock.export_button.click()

    # The main export must stand: file on disk, valid layer, in the group.
    assert target.exists()
    layer = next(
        (v for v in plugin.layers.project.mapLayers().values() if v.source() == str(target)),
        None,
    )
    assert layer is not None and layer.isValid()
    assert plugin.layers.group.findLayer(layer.id()) is not None
    # No companion file, and no companion layer.
    assert not (tmp_path / "slices" / "cube_coverage.tif").exists()

    assert not any("could not export the GeoTIFF" in m for m in message_log)
    assert any("coverage companion" in m for m in message_log)
    assert any("disk full" in m for m in message_log)


# ---- progress, cancel and no partial files (interpolation spec §7, plan call 11) ---------


class _FakeDialog:
    """What `plugin._export_progress` returns as its dialog, when a test replaces it."""

    def close(self) -> None:
        pass

    def deleteLater(self) -> None:  # noqa: N802 -- Qt's name
        pass


def _progress_calling(hook):
    """A stand-in for `plugin._export_progress`: its callback runs `hook(done, total)`
    and carries on, unless the hook returns False."""

    def make(title, total, **_options):
        def callback(done, of):
            return hook(done, of) is not False

        return callback, _FakeDialog()

    return make


def _set_method(dock, method):
    panel = dock.grid_finish
    panel.method_combo.setCurrentIndex(panel.method_combo.findData(method))
    dock._finish_debounce.stop()
    dock._on_finish_timeout()


def _answer_target(answer_modal, tmp_path, name="cube.tif"):
    target = tmp_path / "slices" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
    return target


def _levels_of(messages_into):
    from plugin_testing import connect_message_log

    return connect_message_log(lambda msg, tag, level: messages_into.append((msg, level)))


def test_a_cancelled_export_leaves_no_file_and_adds_no_layer(plugin, tmp_path, answer_modal):
    from qgis.core import Qgis

    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    plugin._export_progress = _progress_calling(lambda done, of: done < 1)
    target = _answer_target(answer_modal, tmp_path)
    before = set(plugin.layers.project.mapLayers())
    levels: list = []
    disconnect = _levels_of(levels)
    try:
        dock.export_button.click()
    finally:
        disconnect()
    assert not target.exists()
    assert set(plugin.layers.project.mapLayers()) == before
    assert ("export cancelled", Qgis.MessageLevel.Info) in [(m.lower(), lv) for m, lv in levels], (
        levels
    )
    assert not any(lv == Qgis.MessageLevel.Critical for _m, lv in levels)


def test_a_cancelled_export_never_removes_a_file_it_did_not_reach(
    plugin, tmp_path, answer_modal, monkeypatch
):
    """The dialog may choose a file to replace. Until the export has written over
    it, it is the user's: the mtime rule (Ruling T4-b), shared by both exports."""
    import nsgeo_qgis.plugin as plugin_module
    from nsgeo_qgis.slice_export import ExportCancelled

    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    target = _answer_target(answer_modal, tmp_path)
    target.write_bytes(b"the user's own file")

    def cancelled_before_writing(*args, **kwargs):
        raise ExportCancelled()

    monkeypatch.setattr(plugin_module, "export_slices", cancelled_before_writing)
    dock.export_button.click()
    assert target.read_bytes() == b"the user's own file"


def test_a_failed_slice_export_leaves_no_file(
    plugin, tmp_path, answer_modal, monkeypatch, message_log
):
    import nsgeo_qgis.plugin as plugin_module
    from nsgeo_qgis.slice_export import GeoTiffSliceWriter

    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    real_export = plugin_module.export_slices

    class DiesAfterTheFirstBand:
        def write(self, path, plan, slices):
            def first_only():
                for index, band in enumerate(slices):
                    if index == 1:
                        raise OSError("disk full")
                    yield band

            GeoTiffSliceWriter().write(path, plan, first_only())

    def with_failing_writer(*args, **kwargs):
        return real_export(*args, writer=DiesAfterTheFirstBand(), **kwargs)

    monkeypatch.setattr(plugin_module, "export_slices", with_failing_writer)
    target = _answer_target(answer_modal, tmp_path)
    before = set(plugin.layers.project.mapLayers())
    dock.export_button.click()
    assert not target.exists()
    assert set(plugin.layers.project.mapLayers()) == before
    assert any("could not export the GeoTIFF" in m and "disk full" in m for m in message_log)


def test_a_minimum_curvature_export_records_its_method_and_never_writes_a_preview(
    plugin, tmp_path, answer_modal
):
    from nsgeo.slices import plan_windows, to_north_up
    from osgeo import gdal

    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    _set_method(dock, "min_curvature")
    engine = dock.engine
    engine._last_solve_ms = 500.0  # a slow solve, set once the plan exists (Ruling R1)
    target = _answer_target(answer_modal, tmp_path)
    dock.export_button.click()
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
            np.testing.assert_array_equal(ds.GetRasterBand(index).ReadAsArray(), full)
            previews_differ |= not np.array_equal(full, drawn, equal_nan=True)
        assert previews_differ, "the preview matched everywhere: this test would not tell"
    finally:
        ds.Close()


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


def test_an_export_cancels_a_running_refine(plugin, tmp_path, answer_modal, monkeypatch):
    """R13: through the scope's flow, so the status line stops saying "Refining"
    and the flow stops believing a list runs; afterwards the panel redraws, so a
    preview that still stands re-arms its rest."""
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

    seen: list[tuple[bool, str]] = []

    def hook(done, of):
        if done == 0:
            seen.append((dock.refiner.busy, dock.refine_label.text()))
        if done == of:  # every band solved: the current slice is not one of them now
            dock.engine._solved.clear()
            dock.engine._last_solve_ms = 500.0

    plugin._export_progress = _progress_calling(hook)
    target = _answer_target(answer_modal, tmp_path)
    dock.export_button.click()

    assert target.exists()
    assert job.stopped_by_request
    busy, text = seen[0]
    assert busy is False
    assert not text.startswith("Refining"), text
    assert dock.provisional
    assert dock._grid_refine.rest.isActive()
    assert dock.refine_label.text() == PREVIEW_INDICATOR
    assert "Refining" not in dock.status_label.text()
    dock.refiner.cancel()


def test_the_progress_dialog_is_cancellable_and_window_modal(plugin):
    plugin, s = plugin
    callback, dialog = plugin._export_progress("Export GeoTIFF", 5)
    try:
        assert dialog.windowModality() == Qt.WindowModality.WindowModal
        assert dialog.minimumDuration() == 500
        assert dialog.maximum() == 5
        assert callback(0, 5) is True
        assert callback(3, 5) is True
        dialog.cancel()
        assert callback(4, 5) is False
    finally:
        dialog.close()
        dialog.deleteLater()


# ---- feedback during a slow export (final review I-1) ------------------------------------


def _spying_progress(plugin, monkeypatch):
    """`plugin._export_progress`, the real one, with its dialog kept and each
    `done` its callback is given recorded, in order."""
    real = plugin._export_progress
    made: dict = {"calls": []}

    def spying(title, total, **kwargs):
        callback, dialog = real(title, total, **kwargs)
        made["dialog"] = dialog

        def recorded(done, of):
            made["calls"].append(done)
            return callback(done, of)

        return recorded, dialog

    monkeypatch.setattr(plugin, "_export_progress", spying)
    return made


def test_a_cancel_during_a_slow_first_band_is_heard_before_the_second(
    plugin, tmp_path, answer_modal, monkeypatch
):
    """`QProgressDialog.setValue` processes events only once the dialog has
    been shown: the band-0 call starts a show timer that cannot fire while a
    band solves on the GUI thread, and the band-1 call shows the dialog but
    processes nothing. So a Cancel clicked during a slow first band went
    unheard, and nothing painted, until the band-2 call. The callback
    processes events once the dialog is visible: by the band-1 callback it is
    up, the Cancel is heard, and band 1 is never computed."""
    from qgis.PyQt.QtCore import QTimer
    from qgis.PyQt.QtWidgets import QPushButton

    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    made = _spying_progress(plugin, monkeypatch)
    queued: list[int] = []
    heard: list[tuple[int, bool]] = []  # (the callback's `done`, the dialog visible)
    real_finish = dock.engine.finish

    def slow_first_band(*args, **kwargs):
        if made["calls"] == [0] and not queued:
            queued.append(1)
            time.sleep(0.6)  # band 0 solving: no events are processed meanwhile
            dialog = made["dialog"]
            button = dialog.findChild(QPushButton)

            def click() -> None:
                heard.append((made["calls"][-1], dialog.isVisible()))
                button.click()

            QTimer.singleShot(0, click)  # the user's click, queued during band 0
        return real_finish(*args, **kwargs)

    monkeypatch.setattr(dock.engine, "finish", slow_first_band)
    target = _answer_target(answer_modal, tmp_path)
    levels: list = []
    disconnect = _levels_of(levels)
    try:
        dock.export_button.click()
    finally:
        disconnect()
    assert queued == [1]
    assert heard == [(1, True)], "the Cancel was not heard, visible, at the band-1 callback"
    assert made["calls"] == [0, 1], "band 1 was computed after the Cancel"
    assert not target.exists()
    assert ("export cancelled", Qgis.MessageLevel.Info) in [(m.lower(), lv) for m, lv in levels]


@pytest.mark.parametrize(
    ("method", "last_solve_ms", "shown"),
    [
        ("min_curvature", 500.0, True),
        ("min_curvature", None, True),
        ("min_curvature", 5.0, False),
        ("kriging", None, False),
    ],
)
def test_a_slow_export_shows_its_progress_before_the_first_band(
    plugin, tmp_path, answer_modal, monkeypatch, method, last_solve_ms, shown
):
    """A slow first band would otherwise keep the dialog hidden for its whole
    solve. With minimum curvature over the live budget, or not timed yet, the
    dialog is shown, and painted, before band 0 is computed. A quick solve keeps
    plan call 11's rule: nothing shows for an export under 500 ms."""
    from qgis.PyQt.QtCore import QTimer

    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    _set_method(dock, method)
    dock.engine._last_solve_ms = last_solve_ms  # once the plan exists (Ruling R1)
    made = _spying_progress(plugin, monkeypatch)
    pumped: list[int] = []
    at_band_0: list[tuple[bool, list[int]]] = []
    real_finish = dock.engine.finish

    def first_band(*args, **kwargs):
        if made["calls"] == [0] and not at_band_0:
            at_band_0.append((made["dialog"].isVisible(), list(pumped)))
        return real_finish(*args, **kwargs)

    monkeypatch.setattr(dock.engine, "finish", first_band)
    real_paused = dock.refining_paused

    @contextlib.contextmanager
    def queueing():
        with real_paused():
            QTimer.singleShot(0, lambda: pumped.append(1))  # an expose, say
            yield

    monkeypatch.setattr(dock, "refining_paused", queueing)
    target = _answer_target(answer_modal, tmp_path)
    dock.export_button.click()
    assert target.exists()
    assert at_band_0 == [(shown, [1] if shown else [])]


def test_an_export_shows_the_wait_cursor_throughout(plugin, tmp_path, answer_modal, monkeypatch):
    """Every band is solved on the GUI thread, so the export says it is busy."""
    import nsgeo_qgis.plugin as plugin_module

    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    busy: list[int] = []
    real_cursor = plugin_module.busy_cursor

    @contextlib.contextmanager
    def counting():
        busy.append(1)
        with real_cursor():
            yield
        busy.append(-1)

    monkeypatch.setattr(plugin_module, "busy_cursor", counting)
    during: list[int] = []
    plugin._export_progress = _progress_calling(lambda done, of: during.append(sum(busy)))
    target = _answer_target(answer_modal, tmp_path)
    dock.export_button.click()
    assert target.exists()
    assert during and all(depth == 1 for depth in during), during
    assert busy == [1, -1]


@pytest.mark.parametrize("cancel", [False, True])
def test_a_failed_redraw_after_an_export_changes_nothing_it_reported(
    plugin, tmp_path, answer_modal, monkeypatch, cancel
):
    """`refining_paused` redraws once the export ends. A redraw that fails then
    is logged, never raised: it must not turn a good export into a deleted
    file, nor a cancel into a Critical."""
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    failed: list[int] = []
    real_refresh = dock.refresh_slice

    def failing_once() -> None:
        if failed:
            real_refresh()  # any redraw after the first is real
            return
        failed.append(1)
        raise RuntimeError("the redraw failed")

    monkeypatch.setattr(dock, "refresh_slice", failing_once)
    plugin._export_progress = _progress_calling(lambda done, of: not (cancel and done == 1))
    target = _answer_target(answer_modal, tmp_path)
    levels: list = []
    disconnect = _levels_of(levels)
    try:
        dock.export_button.click()
    finally:
        disconnect()
    assert failed == [1]
    assert not any(lv == Qgis.MessageLevel.Critical for _m, lv in levels), levels
    if cancel:
        assert not target.exists()
        assert ("export cancelled", Qgis.MessageLevel.Info) in [(m.lower(), lv) for m, lv in levels]
    else:
        assert target.exists()
        assert any("exported" in m and str(target) in m for m, _lv in levels), levels


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


def test_an_exported_layer_and_its_coverage_are_drawn_smooth(plugin, tmp_path, answer_modal):
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    dock.coverage_check.setChecked(True)
    target = tmp_path / "slices" / "cube.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
    dock.export_button.click()
    sources = {str(target), str(tmp_path / "slices" / "cube_coverage.tif")}
    found = [v for v in plugin.layers.project.mapLayers().values() if v.source() in sources]
    assert len(found) == 2
    for layer in found:
        assert layer.resampleFilter().zoomedInResampler().type() == "bilinear"
