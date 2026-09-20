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

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from plugin_testing import synthetic_dzt
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
    dock.transform_combo.setCurrentText("amp_envelope")
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
    """Important 1: `store._npz_path`'s own hazard -- a user-typed name
    with a dot that is NOT an extension. The dialog string must be typed
    WITHOUT ".npz" for this to reproduce (`_npz_path` appends it): typing
    "cube.v1" and "cube.v2" -- not "cube.v1.npz" -- is exactly the
    coordinator's own table. `Path("cube.v1").stem` is "cube" (pathlib
    treats ".v1" as the extension), so deriving the id from the RAW
    dialog string collided both saves onto "A__cube"; deriving it from
    `Path(npz_path).stem` (the file `_npz_path` actually wrote,
    "cube.v1.npz") keeps them apart. A first version of this test typed
    the ".npz" suffix explicitly and passed against the pre-fix code too
    -- it never exercised the collision at all, since `path` and
    `npz_path` were then identical regardless of which one plugin.py
    read the stem from."""
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock

    target1 = tmp_path / "slices" / "cube.v1"  # no .npz -- _npz_path appends it
    target1.parent.mkdir(parents=True, exist_ok=True)
    answer_modal(QFileDialog, "getSaveFileName", (str(target1), "nsgeo cube (*.npz)"))
    dock.save_button.click()
    written1 = target1.parent / "cube.v1.npz"
    assert written1.exists()
    assert "A__cube.v1" in s.site.cubes
    assert s.site.cubes["A__cube.v1"]["array"] == "slices/cube.v1.npz"

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
    dock.radius_spin.setValue(0.5)
    dock.flush_debounce()
    assert dock.radius_cells() > 0  # keep this test focused on the layer-join claim

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


def test_export_geotiff_warns_when_fill_radius_is_zero(plugin, tmp_path, answer_modal, message_log):
    """Ruling AE: radius 0 is spec 6.4's honest unfilled truth and
    `radius_spin`'s own construction default -- refusing it would take
    away a view the spec calls valid, so the fix is a loud warning, not a
    refusal."""
    plugin, s = plugin
    _prepare(plugin)
    dock = plugin.slices_dock
    dock.radius_spin.setValue(0.0)
    dock.flush_debounce()
    assert dock.radius_cells() == 0

    target = tmp_path / "slices" / "cube.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
    dock.export_button.click()
    assert target.exists()
    assert any("fill radius 0" in m for m in message_log)


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
