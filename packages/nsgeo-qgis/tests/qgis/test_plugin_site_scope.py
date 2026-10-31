"""The Slices dock's Whole site scope, driven through the plugin (M12 Task 5).

Spec 4.1-4.5. `site3` (conftest) is three adjacent 6 x 6 m grids, A, B and
C, four lines each; the plugin opens it in its own session, as a user would.
"""

from __future__ import annotations

import dataclasses
import json
import re

import numpy as np
import pytest
from nsgeo.slices import plan_windows, window_depths_m
from nsgeo.velocity import VelocityModel
from nsgeo_qgis import plugin as plugin_module
from nsgeo_qgis import slices_engine
from nsgeo_qgis.slice_layer import LAYER_NAME, SITE_LAYER_NAME
from nsgeo_qgis.slices_plan import (
    DEFAULT_RADIUS_SPACINGS,
    NO_TRANSFORM,
    default_cell,
    format_bytes,
)
from osgeo import gdal
from plugin_testing import LoadCounter, spin_until
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

GRID_X = {"A": (500.0, 506.0), "B": (506.0, 512.0), "C": (512.0, 518.0)}


def _open(fake_iface, site, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.open_site(site.json_path)
    dock = plugin.slices_dock
    # This grid's automatic first preparation (A), as on any survey open.
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    return plugin


def _close(plugin, answer_modal):
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    dock = plugin.slices_dock
    if dock is not None:
        dock.site_engine.wait_until_idle(20_000)
        dock.engine.wait_for_preparation(20_000)
    plugin.unload()


@pytest.fixture
def plugin(fake_iface, site3, answer_modal):
    plugin = _open(fake_iface, site3, answer_modal)
    yield plugin
    _close(plugin, answer_modal)


@pytest.fixture
def open_plugin(fake_iface, answer_modal):
    """`plugin`, on a site of the test's own making (`site3_factory`)."""
    made = []

    def make(site):
        made.append(_open(fake_iface, site, answer_modal))
        return made[-1]

    yield make
    for p in made:
        _close(p, answer_modal)


def _events(n: int = 5) -> None:
    for _ in range(n):
        QCoreApplication.processEvents()


def settle(dock) -> None:
    """Wait for the site to finish preparing, then let its coalesced tick run."""
    assert dock.site_engine.wait_until_idle(60_000), "the site did not finish preparing"
    _events()


def whole_site(plugin):
    dock = plugin.slices_dock
    dock.site_scope_button.click()
    assert dock.scope() == "site"
    settle(dock)
    return dock


def columns(shown, grid_id):
    """The lattice columns inside a grid's footprint (site3's grids are side by side)."""
    lattice = shown.lattice
    x0, x1 = GRID_X[grid_id]
    first = int(round((x0 - lattice.x0) / lattice.pixel))
    last = int(round((x1 - lattice.x0) / lattice.pixel))
    return slice(first, last)


def _metadata(path) -> dict:
    """A GeoTIFF's dataset metadata, read with the dataset closed before any
    assert runs (final review D5): a failing assert's traceback otherwise
    keeps the dataset alive past `exitQgis()`, and the process dies with
    exit 139 instead of reporting the failure."""
    ds = gdal.Open(str(path))
    try:
        return dict(ds.GetMetadata())
    finally:
        ds.Close()


def _uniform_source(session, preset: str) -> None:
    for grid_id in "ABC":
        session.remember_slice_source(grid_id, preset=preset, lines=None)


# ---- the switch ----------------------------------------------------------------


def test_the_scope_switch_swaps_the_source_controls(plugin):
    dock = plugin.slices_dock
    assert dock.scope() == "grid"
    assert dock.grid_scope_button.isChecked() and not dock.site_scope_button.isChecked()
    assert not dock.source_group.isHidden()
    assert dock.site_panel.isHidden() and dock.normalisation_panel.isHidden()
    assert not dock.grid_radius_row.isHidden() and dock.radius_spacing_spin.isHidden()
    assert not dock.save_button.isHidden()
    assert dock.export_button.text() == "Export GeoTIFF…"
    assert dock.stretch_combo.itemText(0) == "shared across the cube"

    whole_site(plugin)
    assert dock.site_scope_button.isChecked() and not dock.grid_scope_button.isChecked()
    assert dock.source_group.isHidden()
    assert not dock.site_panel.isHidden() and not dock.normalisation_panel.isHidden()
    assert dock.grid_radius_row.isHidden() and not dock.radius_spacing_spin.isHidden()
    assert dock.save_button.isHidden()
    assert dock.export_button.text() == "Export site GeoTIFF…"
    assert dock.stretch_combo.itemText(0) == "shared across the site"
    assert dock.stretch_combo.currentIndex() == 0
    table = dock.site_panel.table
    headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
    assert headers == ["✓", "Grid", "Preset", "Lines", "State"]
    assert dock.site_panel.included() == ("A", "B", "C")  # every grid with lines
    assert [table.item(r, 3).text() for r in range(3)] == ["4 / 4"] * 3
    assert [table.item(r, 4).text() for r in range(3)] == ["ready"] * 3
    # Normalisation is off by default (spec 4.6).
    assert dock.normalisation_panel.method() == "none"
    spin = dock.radius_spacing_spin
    assert spin.suffix() == " × line spacing"
    assert (spin.minimum(), spin.maximum(), spin.singleStep(), spin.value()) == (0, 10, 0.25, 0.5)
    assert "A 0.75 m" in spin.toolTip()  # 0.5 x A's 1.5 m spacing (#81)

    dock.grid_scope_button.click()
    assert dock.scope() == "grid"
    assert not dock.source_group.isHidden() and dock.site_panel.isHidden()
    assert not dock.grid_radius_row.isHidden() and dock.radius_spacing_spin.isHidden()
    assert dock.export_button.text() == "Export GeoTIFF…"
    assert dock.stretch_combo.itemText(0) == "shared across the cube"


def test_whole_site_draws_one_layer_covering_every_grid(plugin):
    dock = whole_site(plugin)
    layer = plugin.slice_layer.layer
    assert layer is not None and layer.name() == SITE_LAYER_NAME
    extent = layer.extent()
    assert extent.xMinimum() == pytest.approx(500.0) and extent.xMaximum() == pytest.approx(518.0)
    assert extent.yMinimum() == pytest.approx(700.0) and extent.yMaximum() == pytest.approx(706.0)
    previews = [
        lyr
        for lyr in plugin.layers.project.mapLayers().values()
        if lyr.name() in (LAYER_NAME, SITE_LAYER_NAME)
    ]
    assert previews == [layer]
    shown = dock.current_site_slice()
    for grid_id in "ABC":
        assert shown.windows[grid_id] is not None
        assert np.isfinite(shown.array[:, columns(shown, grid_id)]).any(), grid_id

    # Both scopes drawn: switching renames the one layer in place.
    dock.grid_scope_button.click()
    assert plugin.slice_layer.layer.id() == layer.id()
    assert layer.name() == LAYER_NAME
    assert dock.current_site_slice() is None
    whole_site(plugin)
    assert plugin.slice_layer.layer.id() == layer.id()
    assert layer.name() == SITE_LAYER_NAME


def test_one_slider_moves_every_grid(plugin):
    dock = whole_site(plugin)
    dock.slice_slider.setValue(20)
    _events()
    first = dock.current_site_slice()
    dock.slice_slider.setValue(60)
    _events()
    second = dock.current_site_slice()
    for grid_id in "ABC":
        assert second.windows[grid_id].k0 - first.windows[grid_id].k0 == 40, grid_id
        region = columns(first, grid_id)
        assert not np.array_equal(
            first.array[:, region], second.array[:, region], equal_nan=True
        ), grid_id


def test_this_grid_names_the_memory_the_site_view_still_holds(plugin):
    """Final review M2: leaving Whole site keeps every prepared site grid
    held (Ruling 1), so This grid's status line says how much, by the
    site's own accounting -- here every engine streams, so its lines."""
    dock = plugin.slices_dock
    dock.slice_slider.setValue(5)
    _events()
    assert "held by the site view" not in dock.status_label.text()
    whole_site(plugin)
    site = dock.site_engine
    assert all(site.engine_for(g).mode == "streaming" for g in "ABC")
    held = sum(site.engine_for(g).estimate.lines_bytes for g in "ABC")
    assert site.held_bytes == held
    dock.grid_scope_button.click()
    _events()
    text = dock.status_label.text()
    assert text == f"{dock.engine.status_text()} · +{format_bytes(held)} held by the site view"


def test_switching_scope_keeps_the_window_time(plugin):
    dock = plugin.slices_dock
    # A coarser This-grid dz, so the same slider index is a different time
    # on the two axes: only carrying the time keeps the window.
    dock.dz_spin.setValue(dock.dz_spin.value() * 3)
    dock.flush_debounce()
    dock.slice_slider.setValue(30)
    grid_z = dock.engine.z
    grid_top = grid_z.t0_ns + 30 * grid_z.dz_ns

    whole_site(plugin)
    site_z = dock.site_engine.site_z
    assert site_z.dz_ns != pytest.approx(grid_z.dz_ns)
    site_top = site_z.t0_ns + dock.slice_slider.value() * site_z.dz_ns
    assert abs(site_top - grid_top) <= site_z.dz_ns / 2 + 1e-9
    lo = float(re.search(r"· ([-\d.]+)–", dock.readout.text()).group(1))
    assert lo == pytest.approx(site_top, abs=0.05)
    assert dock.thickness_spin.value() == pytest.approx(5.0)  # the thickness is shared too

    dock.slice_slider.setValue(dock.slice_slider.value() + 7)
    _events()
    site_top = site_z.t0_ns + dock.slice_slider.value() * site_z.dz_ns
    dock.grid_scope_button.click()
    assert dock.engine.z == grid_z, "This grid comes back at its own resolution"
    back_top = grid_z.t0_ns + dock.slice_slider.value() * grid_z.dz_ns
    assert abs(back_top - site_top) <= grid_z.dz_ns / 2 + 1e-9


# ---- the grid list --------------------------------------------------------------


def test_unticking_a_grid_removes_it_from_the_map(plugin):
    dock = whole_site(plugin)
    shown = dock.current_site_slice()
    assert np.isfinite(shown.array[:, columns(shown, "B")]).any()
    dock.site_panel.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    settle(dock)
    shown = dock.current_site_slice()
    assert "B" not in shown.windows
    assert np.isnan(shown.array[:, columns(shown, "B")]).all()
    assert np.isfinite(shown.array[:, columns(shown, "A")]).any()
    assert plugin.session.site_view()["grids"] == ["A", "C"]
    assert dock.site_panel.table.item(1, 4).text() == "not included"


def test_refreshing_the_grid_list_reads_each_line_once(plugin, monkeypatch):
    """Final review M3: the list is refreshed on every progress step, and
    it walked every line twice per grid (and twice more for the included
    set) each time. One pass over the survey now builds grid -> lines."""
    dock = whole_site(plugin)
    session = plugin.session
    real = session.line_for_key
    calls: list[str] = []

    def counted(key):
        calls.append(key)
        return real(key)

    monkeypatch.setattr(session, "line_for_key", counted)
    dock._site.refresh_rows()
    assert sorted(calls) == sorted(session.keys())  # noqa: SIM118 -- SiteSession.keys()
    table = dock.site_panel.table
    assert [table.item(r, 3).text() for r in range(3)] == ["4 / 4"] * 3
    assert [table.item(r, 4).text() for r in range(3)] == ["ready"] * 3
    assert "A 0.75 m" in dock.radius_spacing_spin.toolTip()


def test_the_list_shows_each_grids_progress_while_it_prepares(plugin, monkeypatch):
    """Ruling T3-d: spec 4.2's "preparing n of m" in the State column."""
    LoadCounter(monkeypatch, delay=0.05)
    dock = plugin.slices_dock
    seen: set[str] = set()
    dock.site_scope_button.click()

    def watch() -> bool:
        seen.update(dock.site_panel.table.item(r, 4).text() for r in range(3))
        return not dock.site_engine.is_running

    assert spin_until(watch, 60_000)
    assert {"preparing 1 of 4", "preparing 2 of 4"} <= seen, seen
    assert "queued" in seen


def test_choose_lines_acts_on_the_selected_grid_only(plugin, monkeypatch):
    dock = whole_site(plugin)
    session = plugin.session
    counter = LoadCounter(monkeypatch)
    this_grid = dock.included_keys()
    b_keys = dock.line_choice_keys("B")
    assert len(b_keys) == 4

    dock.site_panel.select_grid("B")
    assert dock.site_panel.choose_button.text() == "Choose lines for B…"
    assert dock.line_choice_grid() == "B"
    dock.site_panel.choose_button.click()
    dialog = plugin._line_choice_dialog
    assert dialog is not None and dialog.grid_id == "B"
    dialog.set_included(b_keys[0], False)
    dialog.accept()
    settle(dock)

    assert counter.calls == 3, "only B re-prepares, with its three lines"
    assert dock.included_keys() == this_grid, "This grid's own lines are not touched"
    assert session.slice_source("B")["lines"] == list(b_keys[1:])
    assert session.slice_source("A") is None
    assert dock.site_panel.table.item(1, 3).text() == "3 / 4"
    assert dock.site_engine.engine_for("B").line_count == 3


def test_a_line_choice_goes_to_its_grid_when_the_selection_moved_meanwhile(plugin, fake_iface):
    """Final review M1, flipping M11's Ruling Z for the site only. The
    chooser names its grid and `set_included_for` addresses that grid by
    id, so a row selected meanwhile does not throw the choice away: it is
    applied to the grid the chooser was opened for. This grid scope still
    drops it (`test_plugin_loads`)."""
    dock = whole_site(plugin)
    dock.site_panel.select_grid("B")
    plugin.open_line_choice_dialog()
    dialog = plugin._line_choice_dialog
    b_keys = dock.line_choice_keys("B")
    dock.site_panel.select_grid("C")
    dialog.set_included(b_keys[0], False)
    dialog.accept()
    settle(dock)
    assert plugin.session.slice_source("B")["lines"] == list(b_keys[1:])
    assert plugin.session.slice_source("C") is None
    assert dock.site_engine.engine_for("B").line_count == 3
    item = fake_iface.messageBar().currentItem()
    assert item is None or "grid changed" not in item.text()


def test_a_stale_transform_on_disk_falls_back_to_the_dock_s(plugin):
    """Ruling T2-c: `set_site_view` does not validate the transform, so a
    stored one that is no longer offered must not break the switch. The
    fallback is what This grid shows (here not the panel's own "none")."""
    dock = plugin.slices_dock
    dock.transform_combo.set_value("amp_envelope")
    assert dock.engine.wait_for_preparation(20_000)
    plugin.session.set_site_view(transform="amp_gone_since")
    whole_site(plugin)
    assert dock.site_panel.transform() == "amp_envelope"
    assert dock.site_engine.engine_for("A").choice.transform == "amp_envelope"


def test_the_site_starts_from_square_and_a_0_2_m_cell(plugin):
    """#81, in Whole site: with nothing stored the transform falls back to
    This grid's, which starts on Square, and the cell follows This grid's
    rule (site3's 1.5 m spacing does not clamp 0.2 m)."""
    dock = whole_site(plugin)
    assert dock.site_panel.transform() == "amp_square"
    assert dock.site_engine.engine_for("A").choice.transform == "amp_square"
    assert dock.cell_spin.value() == pytest.approx(0.2)


def test_a_remembered_none_transform_is_kept_over_the_default(plugin):
    """#81: a default only fills a gap. A site that remembers "none" keeps it."""
    plugin.session.set_site_view(transform="none")
    dock = whole_site(plugin)
    assert dock.site_panel.transform() == "none"
    assert dock.site_engine.engine_for("A").choice.transform == NO_TRANSFORM


def test_both_scopes_legends_name_the_transform_by_title(plugin):
    """#82: the legend under the slice reads as the Transform combo does, in
    This grid and in Whole site alike (the site's once showed the id)."""
    dock = plugin.slices_dock
    dock.transform_combo.set_value("amp_envelope")
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.legend_label.text().endswith("(Envelope)"), dock.legend_label.text()
    whole_site(plugin)
    dock.site_panel.transform_combo.set_value("amp_abs")
    settle(dock)
    assert dock.legend_label.text().endswith("(Absolute value)"), dock.legend_label.text()


def test_lines_chosen_in_the_site_for_this_grids_grid_are_what_this_grid_shows(plugin):
    """Spec 4.2: This grid reads and writes the same record the site does."""
    dock = whole_site(plugin)
    a_keys = dock.line_choice_keys("A")
    dock.site_panel.select_grid("A")
    dock.set_included_for("A", a_keys[:2])
    settle(dock)
    assert dock.site_engine.engine_for("A").line_count == 2
    dock.grid_scope_button.click()
    assert dock.included_keys() == a_keys[:2]
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.line_count == 2


def _a_row(dock, plugin):
    from nsgeo_qgis.ui import site_scope

    rows = site_scope.site_rows(
        plugin.session, dock.site_engine, site_scope.included_grids(plugin.session)
    )
    return next(r for r in rows if r.grid_id == "A")


def test_both_scopes_read_a_line_choice_that_left_the_grid_as_every_line(plugin, site3):
    """#74: remembered lines that have all left the grid mean every line, as
    This grid already read them; the site no longer shows `no lines`. The
    record is written while This grid shows B -- coming back to A would
    rewrite it as `lines: None`, which is the very reading under test."""
    from nsgeo_qgis.ui import site_scope

    dock = plugin.slices_dock
    dock.grid_combo.setCurrentText("B")
    plugin.session.remember_slice_source("A", preset="p", lines=("raw/gone/X.DZT",))
    dock = whole_site(plugin)
    assert site_scope.source_keys(plugin.session, "A") == site3.keys("A")
    assert dock.site_engine.engine_for("A").line_count == 4
    row = _a_row(dock, plugin)
    assert row.lines == "4 / 4"
    assert row.state != "no lines"
    dock.grid_scope_button.click()
    dock.grid_combo.setCurrentText("A")
    dock.rebuild_source()
    assert dock.line_choice_keys("A") == site3.keys("A")


def test_removing_every_remembered_line_reads_as_every_line_in_both_scopes(plugin, site3):
    from nsgeo_qgis.ui import site_scope

    dock = plugin.slices_dock
    gone = site3.keys("A")[:2]
    rest = site3.keys("A")[2:]
    dock.grid_combo.setCurrentText("B")
    plugin.session.remember_slice_source("A", preset="p", lines=gone)
    plugin.session.remove_lines(gone)
    dock = whole_site(plugin)
    assert site_scope.source_keys(plugin.session, "A") == rest
    assert dock.site_engine.engine_for("A").line_count == 2
    dock.grid_scope_button.click()
    dock.grid_combo.setCurrentText("A")
    dock.rebuild_source()
    assert dock.line_choice_keys("A") == rest


def test_a_live_choice_emptied_by_removal_reads_as_every_line_in_both_scopes(plugin, site3):
    """#74: the same removal with This grid ON A, holding an explicit choice.
    Its live set used to prune to `()` (no lines) while the site read every line."""
    from nsgeo_qgis.ui import site_scope

    dock = plugin.slices_dock
    session = plugin.session
    chosen = site3.keys("A")[:2]
    rest = site3.keys("A")[2:]
    assert dock.grid_combo.currentText() == "A"
    dock.set_included(chosen)
    record = session.slice_source("A")
    session.remove_lines(chosen)
    assert session.slice_source("A") == record  # the fall-back writes nothing
    assert site_scope.source_keys(session, "A") == rest
    assert dock.included_keys() == rest
    assert dock.line_choice_keys("A") == rest


def test_a_source_edit_after_emptying_does_not_change_what_the_site_prepares(plugin):
    dock = plugin.slices_dock
    dock.grid_combo.setCurrentText("B")
    plugin.session.remember_slice_source("A", preset="p", lines=("raw/gone/X.DZT",))
    dock = whole_site(plugin)
    before = dock.site_engine.engine_for("A").line_count
    dock.grid_scope_button.click()
    dock.grid_combo.setCurrentText("A")
    dock.preset_combo.setCurrentText("raw")  # rewrites the record as lines: None
    dock = whole_site(plugin)
    assert before == 4
    assert dock.site_engine.engine_for("A").line_count == before


# ---- normalisation and gain -------------------------------------------------------


def test_the_method_combo_changes_the_drawn_values(site3_factory, open_plugin):
    site = site3_factory(scale={"B": 4.0})
    _uniform_source(site.session, "raw")  # no AGC, so B stays four times as bright
    site.session.save()
    plugin = open_plugin(site)
    dock = whole_site(plugin)
    plain = dock.current_site_slice()
    assert all(f == (1.0, 0.0) for f in plain.factors.values())

    dock.normalisation_panel.method_combo.setCurrentIndex(1)  # Background level
    _events()
    evened = dock.current_site_slice()
    assert dock.normalisation_panel.method() == "background"
    assert plugin.session.site_view()["normalisation"] == "background"
    assert evened.factors["B"][0] < 0.5 < evened.factors["A"][0]
    region = columns(plain, "B")
    assert not np.array_equal(plain.array[:, region], evened.array[:, region], equal_nan=True)


def test_the_gain_spin_scales_only_the_selected_grid(plugin):
    dock = whole_site(plugin)
    panel = dock.normalisation_panel
    before = dock.current_site_slice().array.copy()
    assert not panel.gain_spin.isEnabled() or dock.site_panel.selected_grid() == "A"

    dock.site_panel.select_grid("B")
    assert panel.gain_spin.isEnabled() and panel.gain_spin.value() == 1.0
    panel.gain_spin.setValue(2.0)
    _events()
    after = dock.current_site_slice()
    for grid_id in "AC":
        region = columns(after, grid_id)
        assert np.array_equal(after.array[:, region], before[:, region], equal_nan=True), grid_id
    region = columns(after, "B")
    np.testing.assert_allclose(after.array[:, region], 2.0 * before[:, region], rtol=1e-6)
    assert plugin.session.grid_gain("B") == 2.0
    assert plugin.session.grid_gain("A") == plugin.session.grid_gain("C") == 1.0
    assert after.factors["B"] == (2.0, 0.0)

    panel.reset_button.click()
    _events()
    assert panel.gain_spin.value() == 1.0
    assert np.array_equal(dock.current_site_slice().array, before, equal_nan=True)


def test_the_gain_spin_steps_by_a_useful_increment(plugin):
    """Trap 7: M11 shipped spin boxes that stepped by Qt's default 1.0."""
    dock = whole_site(plugin)
    spin = dock.normalisation_panel.gain_spin
    assert spin.singleStep() == pytest.approx(0.05)
    assert spin.prefix() == "×" and spin.decimals() == 2
    assert (spin.minimum(), spin.maximum()) == (pytest.approx(0.10), pytest.approx(10.00))
    dock.site_panel.select_grid(None)
    assert not spin.isEnabled() and not dock.normalisation_panel.reset_button.isEnabled()
    dock.site_panel.select_grid("C")
    spin.stepUp()
    assert spin.value() == pytest.approx(1.05)
    assert plugin.session.grid_gain("C") == pytest.approx(1.05)


# ---- the readout -------------------------------------------------------------------


def test_the_readout_names_each_grids_depth_and_any_absent_grid(site3_factory, open_plugin):
    site = site3_factory(samples={"C": 128})  # C records a quarter of the time
    v_a = VelocityModel(layers=((0.0, 0.10),))
    v_b = VelocityModel(layers=((0.0, 0.06),))
    site.session.set_grid_velocity("A", v_a)
    site.session.set_grid_velocity("B", v_b)
    site.session.save()
    plugin = open_plugin(site)
    dock = whole_site(plugin)
    site_z = dock.site_engine.site_z
    dock.slice_slider.setValue(int(round((60.0 - site_z.t0_ns) / site_z.dz_ns)))
    _events()

    shown = dock.current_site_slice()
    assert shown.windows["C"] is None
    assert re.fullmatch(r"slice \d+ / \d+ · [-\d.]+–[-\d.]+ ns", dock.readout.text())
    parts = dock.site_depths_label.text().split(" · ")
    expected = []
    for grid_id, velocity in (("A", v_a), ("B", v_b)):
        z = dock.site_engine.engine_for(grid_id).z
        lo, hi = window_depths_m(z, shown.windows[grid_id], velocity)
        expected.append(f"{grid_id} {lo:.2f}–{hi:.2f} m")
    assert parts == [*expected, "C no data"]
    assert expected[0] != expected[1].replace("B", "A"), "each grid's own velocity"
    assert dock.site_velocities() == {"A": v_a, "B": v_b, "C": dock.site_velocities()["C"]}
    assert dock.velocity_label.isHidden() and not dock.site_depths_label.isHidden()


def test_the_profile_band_follows_the_site_window(plugin):
    dock = whole_site(plugin)
    windows: list[tuple[float, float]] = []
    dock.window_changed.connect(lambda lo, hi: windows.append((lo, hi)))
    dock.slice_slider.setValue(15)
    _events()
    site_z = dock.site_engine.site_z
    top = site_z.t0_ns + 15 * site_z.dz_ns
    assert windows and windows[-1][0] == pytest.approx(top)
    windows.clear()
    dock.reannounce_window()
    assert windows[-1][0] == pytest.approx(top)


def test_the_shared_stretch_is_measured_once_not_on_every_slider_move(plugin, monkeypatch):
    """Task 3 measured `shared_limit` at ~3 s on a large streaming site: it
    is cached by what it measures over, never by the slider."""
    dock = whole_site(plugin)
    site = dock.site_engine
    real = site.shared_limit
    calls: list[str] = []

    def counted(*args, **kwargs):
        calls.append(kwargs["method"])
        return real(*args, **kwargs)

    monkeypatch.setattr(site, "shared_limit", counted)
    for value in (3, 17, 40):
        dock.slice_slider.setValue(value)
        _events()
    assert calls == []
    dock.normalisation_panel.method_combo.setCurrentIndex(1)
    _events()
    assert calls == ["background"]
    dock.slice_slider.setValue(8)
    _events()
    assert calls == ["background"]


def test_a_velocity_edit_keeps_the_site_stretch_and_a_spacing_edit_re_measures_it(
    plugin, monkeypatch
):
    """Final review I2: the cached stretch goes only on a change to the
    values drawn. A velocity edit relabels depths; a spacing edit changes
    each grid's fill radius in cells and the seams."""
    dock = whole_site(plugin)
    session = plugin.session
    site = dock.site_engine
    real = site.shared_limit
    calls: list[str] = []

    def counted(*args, **kwargs):
        calls.append(kwargs["method"])
        return real(*args, **kwargs)

    monkeypatch.setattr(site, "shared_limit", counted)
    assert dock.stretch_combo.currentIndex() == 0  # shared across the site
    session.set_grid_velocity("B", VelocityModel.constant(0.09))
    _events()
    assert calls == [], "a velocity edit re-measured the stretch"
    assert dock.current_site_slice() is not None
    session.replace_grid(dataclasses.replace(session.grid("B"), default_spacing=3.0))
    _events()
    assert calls == ["none"]


# ---- coalescing (ruling T3-g) ----------------------------------------------------------


def test_a_burst_of_slider_moves_draws_once_with_the_last_value(plugin, monkeypatch):
    dock = whole_site(plugin)
    site = dock.site_engine
    real = site.slice_at
    tops: list[float] = []

    def counted(top_ns, *args, **kwargs):
        tops.append(top_ns)
        return real(top_ns, *args, **kwargs)

    monkeypatch.setattr(site, "slice_at", counted)
    for value in (5, 9, 14, 22, 31):
        dock.slice_slider.setValue(value)
    assert tops == [], "nothing is drawn until the event loop runs"
    _events()
    site_z = site.site_z
    assert tops == [pytest.approx(site_z.t0_ns + 31 * site_z.dz_ns)]
    assert dock.current_site_slice().windows["A"].k0 == 31


# ---- the site's resolution (spec 4.4, #75) -----------------------------------------------


def test_the_site_cell_seeds_from_the_finest_spaced_grid(site3_factory, open_plugin):
    """#75: spec 4.4 seeds the cell by M11's rule for the finest-spaced
    included grid, here B at 0.3 m against A's and C's 1.5 m."""
    site = site3_factory()
    site.session.replace_grid(dataclasses.replace(site.session.grid("B"), default_spacing=0.3))
    site.session.save()
    plugin = open_plugin(site)
    dock = whole_site(plugin)
    floor = dock.cell_spin.minimum()
    assert default_cell(0.3, floor) != pytest.approx(default_cell(1.5, floor))
    assert dock.cell_spin.value() == pytest.approx(default_cell(0.3, floor))


def test_the_site_includes_every_grid_with_lines_by_default(site3_factory, open_plugin):
    """#75: with nothing remembered, the site is every grid that has lines."""
    site = site3_factory()
    site.session.remove_lines(site.keys("C"))
    site.session.save()
    plugin = open_plugin(site)
    dock = whole_site(plugin)
    assert "grids" not in plugin.session.site_view()
    assert dock._site.included() == ("A", "B")


def test_the_site_cell_is_reseeded_only_when_the_included_grids_change(site3_factory, open_plugin):
    """#75: a change to the included grids seeds the cell again -- B's 0.3 m
    spacing seeds 0.15 m, and unticking B seeds A's and C's 0.2 m -- and a
    hand-set cell survives leaving the site and coming back. A hand-set cell
    is remembered (#71), so it is laid over every later seed as well, the
    seed an untick makes included."""
    site = site3_factory()
    site.session.replace_grid(dataclasses.replace(site.session.grid("B"), default_spacing=0.3))
    site.session.save()
    plugin = open_plugin(site)
    dock = whole_site(plugin)
    assert dock.cell_spin.value() == pytest.approx(default_cell(0.3, dock.cell_spin.minimum()))
    dock.site_panel.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)  # B
    settle(dock)
    assert dock.cell_spin.value() == pytest.approx(default_cell(1.5, dock.cell_spin.minimum()))

    dock.cell_spin.setValue(0.35)
    dock.flush_debounce()
    dock.grid_scope_button.click()
    whole_site(plugin)
    assert dock.cell_spin.value() == pytest.approx(0.35)
    dock.site_panel.table.item(2, 0).setCheckState(Qt.CheckState.Unchecked)  # C
    settle(dock)
    assert dock._site.cell_seeded_for == ("A",), "the untick seeded the cell again"
    assert dock.cell_spin.value() == pytest.approx(0.35), "the remembered cell outlives the seed"


def test_a_remembered_site_cell_below_the_floor_is_clamped_up_to_it(site3_factory, open_plugin):
    """#71 (approved behaviour 4): a remembered cell still respects the size
    floor. A 40 m grid floors the cell above the box's own 0.01 m. Checked on
    entry, before any slice of a frame that size is drawn."""
    site = site3_factory()
    grid = site.session.grid("A")
    site.session.replace_grid(dataclasses.replace(grid, size_x=40.0, size_y=40.0))
    site.session.set_site_view(grids=("A",))
    site.session.remember_site_resolution(cell=0.012)
    site.session.save()
    plugin = open_plugin(site)
    dock = plugin.slices_dock
    dock.site_scope_button.click()
    try:
        floor = dock.cell_spin.minimum()
        assert floor > 0.012
        assert dock.cell_spin.value() == pytest.approx(floor)
        assert plugin.session.site_resolution() == {"cell": 0.012}
        assert not plugin.session.dirty
    finally:
        dock.grid_scope_button.click()


def _resolution_spins(dock) -> tuple[float, float, float, float]:
    return dock.cell_spin.value(), dock.dz_spin.value(), dock.z0_spin.value(), dock.z1_spin.value()


def _snapped_ready_bounds(dock) -> tuple[float, float]:
    """The union of the ready grids' prepared bounds, as the z spins hold it."""
    from nsgeo_qgis.ui.site_scope import ready_z_bounds
    from nsgeo_qgis.ui.slices_dock import _snap_inside

    low, high = ready_z_bounds(dock.site_engine)
    return (
        _snap_inside(low, dock.z0_spin.decimals(), upper=False),
        _snap_inside(high, dock.z1_spin.decimals(), upper=True),
    )


def _short_a_site(site3_factory, open_plugin, **remembered):
    """site3 with A's lines a quarter as long, the site's resolution as given,
    saved and reopened. A prepares first, so the first ready range the site
    sees is A's alone (Ruling 14)."""
    site = site3_factory(samples={"A": 128})
    if remembered:
        site.session.remember_site_resolution(**remembered)
    site.session.save()
    return open_plugin(site)


def _every_grid_shown(plugin):
    dock = whole_site(plugin)
    assert dock.site_engine.ready_grids == ("A", "B", "C")
    a_high = dock.site_engine.engine_for("A").prepared_z_bounds()[1]
    assert a_high < _snapped_ready_bounds(dock)[1] - 50.0, "A's range is the short one"
    return dock


@pytest.mark.parametrize(
    "remembered", [{}, {"dz_ns": 0.5}, {"cell": 0.35}], ids=["nothing", "dz", "cell"]
)
def test_a_z_bound_never_chosen_follows_every_ready_grid(site3_factory, open_plugin, remembered):
    """Ruling 14 (#71): z0 and z1 are the user's field by field. One never
    chosen is the union of the ready grids however they became ready; a
    remembered dz or cell does not hold it at the first grid's range."""
    from nsgeo_qgis.ui.site_scope import ready_dt

    plugin = _short_a_site(site3_factory, open_plugin, **remembered)
    dock = _every_grid_shown(plugin)
    assert (dock.z0_spin.value(), dock.z1_spin.value()) == _snapped_ready_bounds(dock)
    dz = pytest.approx(remembered.get("dz_ns", ready_dt(dock.site_engine)), abs=1e-4)
    assert dock.dz_spin.value() == dz  # the box holds 4 decimals
    applied = dock._site.res_applied
    assert (applied.dz_ns, applied.t1_ns) == (dz, dock.z1_spin.value())
    assert plugin.session.site_resolution() == remembered
    assert not plugin.session.dirty


def test_a_remembered_z1_comes_back_once_every_grid_is_ready(site3_factory, open_plugin):
    """Ruling 14: clamped from the remembered value each time, never from the
    spin, so a z1 the first ready grid cut short comes back with the rest."""
    plugin = _short_a_site(site3_factory, open_plugin, t1_ns=60.0)
    dock = _every_grid_shown(plugin)
    low, _high = _snapped_ready_bounds(dock)
    assert (dock.z0_spin.value(), dock.z1_spin.value()) == (low, pytest.approx(60.0))
    assert dock._site.res_applied.t1_ns == pytest.approx(60.0)
    assert plugin.session.site_resolution() == {"t1_ns": 60.0}
    assert not plugin.session.dirty


def test_a_remembered_range_wider_than_the_union_is_clamped_to_all_of_it(
    site3_factory, open_plugin
):
    remembered = {"t0_ns": -50.0, "t1_ns": 500.0}
    plugin = _short_a_site(site3_factory, open_plugin, **remembered)
    dock = _every_grid_shown(plugin)
    assert (dock.z0_spin.value(), dock.z1_spin.value()) == _snapped_ready_bounds(dock)
    assert plugin.session.site_resolution() == remembered
    assert not plugin.session.dirty


def test_a_remembered_range_past_the_first_ready_grid_comes_back_with_the_rest(
    site3_factory, open_plugin
):
    """Wholly past A's range, so A alone takes the fallback; inside the union,
    so the remembered range is what shows once B and C are ready."""
    remembered = {"t0_ns": 30.0, "t1_ns": 60.0}
    plugin = _short_a_site(site3_factory, open_plugin, **remembered)
    dock = _every_grid_shown(plugin)
    assert (dock.z0_spin.value(), dock.z1_spin.value()) == (30.0, 60.0)
    assert plugin.session.site_resolution() == remembered
    assert not plugin.session.dirty


def test_a_site_resolution_edit_is_remembered_in_the_site_view(plugin):
    """#71: the site's own resolution, apart from every grid's."""
    dock = whole_site(plugin)
    dock.cell_spin.setValue(0.35)
    dock.flush_debounce()
    assert plugin.session.site_resolution() == {"cell": 0.35}
    assert plugin.session.slice_resolution("A") == {}
    assert plugin.session.dirty


def test_entering_the_site_never_remembers_its_seeded_resolution(plugin):
    dock = whole_site(plugin)
    dock.grid_scope_button.click()
    whole_site(plugin)
    assert plugin.session.site_resolution() == {}
    assert not plugin.session.dirty


def test_the_site_resolution_survives_save_and_reopen(fake_iface, site3, answer_modal, open_plugin):
    """#71, as `test_the_site_view_survives_save_and_reopen`, in a plugin of
    its own the second time: nothing the first one held in memory helps."""
    first = _open(fake_iface, site3, answer_modal)
    try:
        dock = whole_site(first)
        dock.cell_spin.setValue(0.35)
        t0 = round(dock.z0_spin.value() + 5.0, 3)
        dock.z0_spin.setValue(t0)
        dock.radius_spacing_spin.setValue(1.25)
        dock.flush_debounce()
        settle(dock)
        assert first.session.site_resolution() == {
            "cell": 0.35,
            "t0_ns": t0,
            "radius_spacings": 1.25,
        }
        first.session.save()
    finally:
        _close(first, answer_modal)

    plugin = open_plugin(site3)
    dock = whole_site(plugin)
    assert dock.cell_spin.value() == pytest.approx(0.35)
    assert dock.z0_spin.value() == pytest.approx(t0)
    assert dock.radius_spacing_spin.value() == pytest.approx(1.25)
    assert "A 1.88 m" in dock.radius_spacing_spin.toolTip()  # 1.25 x 1.5 m
    applied = dock._site.res_applied
    assert (applied.cell, applied.t0_ns) == (pytest.approx(0.35), pytest.approx(t0))
    assert dock.current_site_slice() is not None
    assert not plugin.session.dirty


def test_a_remembered_site_z_range_is_clamped_not_reseeded(plugin):
    """#71 with M11's rule: a remembered range is the user's, so the ready
    grids only clamp it (z1 here), never re-seed it (dz and z0 stand), and
    the clamp writes nothing."""
    session = plugin.session
    low, high = plugin.slices_dock.engine.prepared_z_bounds()  # every site3 grid's
    remembered = {
        "dz_ns": round(plugin.slices_dock.dz_spin.value() * 2, 4),
        "t0_ns": round(low + 5.0, 3),
        "t1_ns": round(high + 5.0, 3),
    }
    session.remember_site_resolution(**remembered)
    session.save()
    dock = whole_site(plugin)
    assert dock.dz_spin.value() == pytest.approx(remembered["dz_ns"])
    assert dock.z0_spin.value() == pytest.approx(remembered["t0_ns"])
    assert dock.z1_spin.value() == _snapped_ready_bounds(dock)[1]
    assert dock.site_engine.site_z.dz_ns == pytest.approx(remembered["dz_ns"])
    assert dock.current_site_slice() is not None
    assert session.site_resolution() == remembered
    assert not session.dirty


def test_a_remembered_site_z_range_wholly_outside_the_data_falls_back_to_the_ready_range(
    site3_factory, open_plugin
):
    """Review Focus 1, the site's twin: clamped end by end, a range wholly
    past the data leaves z1 below z0, and the site would draw nothing. The
    fallback is the union of every ready grid, not of the first (Ruling 14)."""
    beyond = {"t0_ns": 200.0, "t1_ns": 300.0}
    plugin = _short_a_site(site3_factory, open_plugin, **beyond)
    session = plugin.session
    errors: list[str] = []
    plugin.slices_dock.error.connect(errors.append)
    dock = _every_grid_shown(plugin)
    assert (dock.z0_spin.value(), dock.z1_spin.value()) == _snapped_ready_bounds(dock)
    assert errors == []
    assert dock.current_site_slice() is not None
    # The remembered values stand, for a later crop that frees the range.
    assert session.site_resolution() == beyond
    assert not session.dirty


def test_a_different_survey_starts_the_site_radius_from_the_default(plugin, site3_factory):
    dock = whole_site(plugin)
    dock.radius_spacing_spin.setValue(1.25)
    _events()
    plugin.session.save()
    other = site3_factory()
    plugin.session.open_site(other.json_path)
    assert dock.engine.wait_for_preparation(20_000)
    dock = whole_site(plugin)
    assert dock.radius_spacing_spin.value() == pytest.approx(DEFAULT_RADIUS_SPACINGS)
    assert plugin.session.site_resolution() == {}
    assert not plugin.session.dirty


def test_a_hand_z_edit_in_the_site_is_clamped_from_then_on(site3_factory, open_plugin):
    """#75: a dz/z0/z1 edit is the user's, so the ready grids clamp it from
    then on and never re-seed it. The edit now arrives through the dock's
    guarded `_on_resolution_edited`; the unguarded slot that saw it is gone.
    Field by field (Ruling 14): z1, never edited, follows every ready grid."""
    dock = _every_grid_shown(_short_a_site(site3_factory, open_plugin))
    dz = round(dock.dz_spin.value() * 2, 4)
    z0 = round(dock.z0_spin.value() + 5.0, 3)
    dock.dz_spin.setValue(dz)
    dock.z0_spin.setValue(z0)
    dock.flush_debounce()
    # A new transform re-prepares every grid, A first, and the ready grids
    # coming back re-seed a seeded range.
    dock.site_panel.transform_combo.set_value("amp_envelope")
    settle(dock)
    assert dock.site_engine.engine_for("A").choice.transform == "amp_envelope"
    assert dock.dz_spin.value() == pytest.approx(dz)
    assert dock.z0_spin.value() == pytest.approx(z0)
    assert dock.z1_spin.value() == _snapped_ready_bounds(dock)[1]
    assert dock.site_engine.site_z.dz_ns == pytest.approx(dz)
    assert dock.session.site_resolution() == {"dz_ns": dz, "t0_ns": z0}


# ---- Ruling 12: This grid's seeds stay off the site's spins (#71) ------------------------


def test_removing_this_grids_grid_while_the_site_shows_leaves_the_site_resolution(plugin):
    """This grid falls back to B when its grid A is removed under the site.
    B's seed and remembered resolution wait for This grid: they used to land
    on the spins the site shares, and mark the site's z range as hand-set.
    A is out of the site, so its removal changes no ready grid, and no tick
    re-seeds the site's z range over what landed."""
    session = plugin.session
    b_res = {"cell": 0.1, "dz_ns": 0.5, "t0_ns": 2.0, "t1_ns": 30.0, "radius_spacings": 1.5}
    session.remember_slice_resolution("B", **b_res)
    session.set_site_view(grids=("B", "C"))
    session.save()
    dock = whole_site(plugin)
    site_spins = _resolution_spins(dock)
    view = session.site_view()
    session.remove_grid("A", with_lines=True)
    settle(dock)
    assert dock.grid_combo.currentText() == "B"
    assert _resolution_spins(dock) == site_spins
    assert session.site_view() == view, "nothing is remembered for the site"
    assert session.slice_resolution("B") == b_res

    dock.site_panel.select_grid(None)  # This grid comes back on its own grid
    dock.grid_scope_button.click()
    assert dock.grid_combo.currentText() == "B"
    assert _resolution_spins(dock) == pytest.approx((0.1, 0.5, 2.0, 30.0))
    assert dock.grid_radius_spin.value() == pytest.approx(1.5)
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.engine.choice.grid_id == "B"
    assert dock.engine.frame.cell == pytest.approx(0.1)
    assert dock.engine.z.dz_ns == pytest.approx(0.5)
    assert dock.current_values() is not None
    assert session.slice_resolution("B") == b_res


def test_the_grid_this_grid_fell_back_to_under_the_site_comes_back_seeded(
    site3_factory, open_plugin
):
    """The same fall-back with nothing remembered for B: This grid comes back
    with B's own seed (its 0.3 m spacing's cell, the default radius), not with
    the values A had before the site."""
    site = site3_factory()
    site.session.replace_grid(dataclasses.replace(site.session.grid("B"), default_spacing=0.3))
    site.session.set_site_view(grids=("B", "C"))
    site.session.save()
    plugin = open_plugin(site)
    dock = plugin.slices_dock
    dock.grid_radius_spin.setValue(1.5)  # A's own, unlike B's seed
    dock.flush_debounce()
    assert dock.cell_spin.value() == pytest.approx(0.2)
    whole_site(plugin)
    plugin.session.remove_grid("A", with_lines=True)
    settle(dock)
    dock.site_panel.select_grid(None)
    dock.grid_scope_button.click()
    assert dock.grid_combo.currentText() == "B"
    assert dock.cell_spin.value() == pytest.approx(default_cell(0.3, dock.cell_spin.minimum()))
    assert dock.grid_radius_spin.value() == pytest.approx(DEFAULT_RADIUS_SPACINGS)
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.engine.choice.grid_id == "B"
    assert dock.engine.frame.cell == pytest.approx(0.15)
    assert dock.current_values() is not None
    assert plugin.session.slice_resolution("B") == {}


def test_importing_lines_under_this_grids_grid_while_the_site_shows_leaves_the_site_resolution(
    site3_factory, open_plugin
):
    """This grid shows C before C has lines. Lines imported under C while
    the site shows owe C's dz/z0/z1 seed to This grid, not to the site. C is
    kept out of the site, so no tick re-seeds the site's z range over it."""
    site = site3_factory()
    c_keys = site.keys("C")
    c_lines = [site.session.line_for_key(k) for k in c_keys]
    site.session.remove_lines(c_keys)
    site.session.set_site_view(grids=("A", "B"))
    site.session.save()
    plugin = open_plugin(site)
    session = plugin.session
    dock = plugin.slices_dock
    dock.grid_combo.setCurrentText("C")
    _events()
    session.save()
    dock = whole_site(plugin)
    site_spins = _resolution_spins(dock)
    record = session.slice_source("C")
    session.add_lines(c_lines)
    settle(dock)
    assert _resolution_spins(dock) == site_spins
    assert session.site_resolution() == {}
    assert session.slice_source("C") == record, "nothing is remembered for C"

    dock.grid_scope_button.click()
    assert dock.grid_combo.currentText() == "C"
    header = session.line_for_key(c_keys[0]).header
    assert dock.dz_spin.value() == pytest.approx(header.dt_ns, abs=1e-4)
    assert dock.z0_spin.value() == pytest.approx(header.position_ns, abs=1e-3)
    end = header.position_ns + (header.n_samples - 1) * header.dt_ns
    assert dock.z1_spin.value() == pytest.approx(end, abs=1e-4)
    assert dock.engine.wait_for_preparation(20_000)
    assert spin_until(lambda: dock.engine.choice is not None and dock.engine.is_prepared)
    assert dock.engine.choice.grid_id == "C"
    assert session.slice_source("C") == record


# ---- persistence -----------------------------------------------------------------------


def test_the_site_view_survives_save_and_reopen(plugin):
    dock = whole_site(plugin)
    session = plugin.session
    assert not session.dirty, "showing the site is not a change to the survey"
    dock.site_panel.table.item(2, 0).setCheckState(Qt.CheckState.Unchecked)  # C
    dock.site_panel.transform_combo.set_value("amp_envelope")
    dock.normalisation_panel.method_combo.setCurrentIndex(2)  # Edge match
    dock.site_panel.select_grid("B")
    dock.normalisation_panel.gain_spin.setValue(1.5)
    settle(dock)
    assert session.dirty
    session.save()

    session.open_site(session.json_path)
    assert dock.scope() == "grid", "the scope is not persisted"
    assert dock.engine.wait_for_preparation(20_000)
    dock = whole_site(plugin)
    assert not session.dirty
    assert dock.site_panel.included() == ("A", "B")
    assert dock.site_panel.transform() == "amp_envelope"
    assert dock.normalisation_panel.method() == "edge"
    dock.site_panel.select_grid("B")
    assert dock.normalisation_panel.gain_spin.value() == pytest.approx(1.5)
    assert dock.site_engine.ready_grids == ("A", "B")
    assert dock.site_engine.engine_for("A").choice.transform == "amp_envelope"
    assert dock.current_site_slice().factors["B"][0] != 1.0


# ---- export -----------------------------------------------------------------------------


def test_export_routes_to_the_site_geotiff_in_site_scope(plugin, answer_modal, tmp_path):
    dock = whole_site(plugin)
    dock.normalisation_panel.method_combo.setCurrentIndex(1)
    _events()
    target = tmp_path / "out" / "site.tif"
    target.parent.mkdir()
    calls = answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
    assert dock.export_button.isEnabled()
    dock.export_button.click()

    assert calls[0][0][2].endswith("slices/site.tif"), calls[0]
    ds = gdal.Open(str(target))
    try:
        md = ds.GetMetadata()
        assert md["NSGEO_SITE_NORMALISATION"] == "background"
        assert md["NSGEO_SITE_TRANSFORM"] == "amp_square"  # #81's default
        assert float(md["NSGEO_SITE_FILL_RADIUS_SPACINGS"]) == 0.5
        assert [g["grid_id"] for g in json.loads(md["NSGEO_SITE_GRIDS"])] == ["A", "B", "C"]
        thickness, step = dock.thickness_step_levels()  # the dock's own, on the site axis
        assert ds.RasterCount == len(plan_windows(dock.site_engine.site_z, thickness, step)) > 1
        assert "B" in json.loads(ds.GetRasterBand(1).GetMetadataItem("NSGEO_GRID_FACTORS"))
    finally:
        ds.Close()  # final review D5: `ds = None` leaves the assert's temporaries holding it
    names = [lyr.name() for lyr in plugin.layers.project.mapLayers().values()]
    assert "site" in names
    assert plugin.layers.group.findLayer(
        next(lyr for lyr in plugin.layers.project.mapLayers().values() if lyr.name() == "site").id()
    )


def test_the_coverage_companion_is_written_and_a_failure_of_it_is_its_own(
    plugin, answer_modal, tmp_path, monkeypatch, fake_iface
):
    """M11's Ruling AH, for the site: the companion follows the coverage
    toggle, and its failure is reported on its own terms, after the main
    file has been written and added."""
    dock = whole_site(plugin)
    dock.coverage_check.setChecked(True)
    _events()
    target = tmp_path / "with_coverage.tif"
    answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
    dock.export_button.click()
    assert (tmp_path / "with_coverage_coverage.tif").exists()
    names = [lyr.name() for lyr in plugin.layers.project.mapLayers().values()]
    assert {"with_coverage", "with_coverage_coverage"} <= set(names)

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(plugin_module, "write_site_coverage", broken)
    second = tmp_path / "second.tif"
    answer_modal(QFileDialog, "getSaveFileName", (str(second), "GeoTIFF (*.tif *.tiff)"))
    dock.export_button.click()
    assert second.exists()
    assert "second" in [lyr.name() for lyr in plugin.layers.project.mapLayers().values()]
    texts = [
        fake_iface.messageBar().items()[i].text()
        for i in range(len(fake_iface.messageBar().items()))
    ]
    assert any("coverage companion" in t and "disk full" in t for t in texts), texts
    assert not any("could not export the site GeoTIFF" in t for t in texts), texts


def test_the_site_export_is_disabled_while_a_grid_prepares(plugin, monkeypatch):
    """Ruling T4-a: the file must not silently leave out a grid still preparing."""
    LoadCounter(monkeypatch, delay=0.05)
    dock = plugin.slices_dock
    dock.site_scope_button.click()
    enabled_while_busy: list[bool] = []

    def watch() -> bool:
        if dock.site_engine.is_running:
            enabled_while_busy.append(dock.export_button.isEnabled())
        return not dock.site_engine.is_running

    assert spin_until(watch, 60_000)
    _events()
    assert enabled_while_busy and not any(enabled_while_busy)
    assert dock.export_button.isEnabled()


def test_the_export_message_names_a_grid_left_out(
    plugin, site3, answer_modal, tmp_path, fake_iface
):
    """Ruling T4-a: an included grid with no lines is named in the success message."""
    session = plugin.session
    dock = whole_site(plugin)
    # A grid with no lines at all: an emptied line choice is every line (#74).
    # Ticked outright, since a grid with no lines is otherwise not offered.
    session.set_site_view(grids=("A", "B", "C"))
    session.remove_lines(site3.keys("C"))
    session.lines_changed.emit()  # the survey changed: the site follows
    settle(dock)
    assert dock.site_engine.grid_state("C") == "no lines"
    target = tmp_path / "left_out.tif"
    answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
    dock.export_button.click()
    assert target.exists()
    text = fake_iface.messageBar().currentItem().text()
    assert "exported" in text and "C (no lines)" in text, text


def test_the_site_file_records_an_included_grid_it_left_out(plugin, site3, answer_modal, tmp_path):
    """Final review M4 (Ruling F-2): the file itself names an included grid
    it does not hold, with its state, and says nothing when none is left out."""
    session = plugin.session
    dock = whole_site(plugin)
    whole = tmp_path / "whole.tif"
    answer_modal(QFileDialog, "getSaveFileName", (str(whole), "GeoTIFF (*.tif *.tiff)"))
    dock.export_button.click()
    assert "NSGEO_SITE_LEFT_OUT" not in _metadata(whole)
    session.set_site_view(grids=("A", "B", "C"))
    session.remove_lines(site3.keys("C"))  # no lines at all (#74)
    session.lines_changed.emit()
    settle(dock)
    part = tmp_path / "part.tif"
    answer_modal(QFileDialog, "getSaveFileName", (str(part), "GeoTIFF (*.tif *.tiff)"))
    dock.export_button.click()
    left = json.loads(_metadata(part)["NSGEO_SITE_LEFT_OUT"])
    assert left == {"C": dock.site_engine.grid_state("C")} == {"C": "no lines"}


def test_a_failed_site_export_leaves_no_file_and_adds_no_layer(
    plugin, answer_modal, tmp_path, monkeypatch, fake_iface
):
    """Ruling T4-b: a half-written GeoTIFF reads as valid zeros."""
    dock = whole_site(plugin)
    target = tmp_path / "broken.tif"

    def fail_part_way(site_engine, path, *args, **kwargs):
        path.write_bytes(b"II*\x00 the first band, then the disk filled")
        raise OSError("disk full")

    monkeypatch.setattr(plugin_module, "export_site", fail_part_way)
    before = set(plugin.layers.project.mapLayers())
    answer_modal(QFileDialog, "getSaveFileName", (str(target), "GeoTIFF (*.tif *.tiff)"))
    dock.export_button.click()
    assert not target.exists()
    assert set(plugin.layers.project.mapLayers()) == before
    text = fake_iface.messageBar().currentItem().text()
    assert "could not export the site GeoTIFF" in text and "disk full" in text


# ---- concurrency (trap 1, ruling R-P5) ------------------------------------------------------


def test_editing_a_grid_in_site_scope_never_overlaps_preparations(plugin, monkeypatch):
    """R-P5. SiteEngine waits for This grid's engine; nothing else made This
    grid's engine wait for the site. A grid moved while the site prepares
    would re-prepare This grid's engine from its own `grids_changed` slot
    (M11), and `rebuild_source` would auto-prepare it on the session signal
    -- either one a second preparation beside the site's."""
    counter = LoadCounter(monkeypatch, delay=0.2)
    dock = plugin.slices_dock
    session = plugin.session
    assert dock.engine.choice.grid_id == "A" and dock.engine.is_prepared
    dock.site_scope_button.click()
    # B has read one line and has three to go (about 0.6 s): a preparation
    # This grid's engine started now would overlap it. Measured: such a task
    # reads its first line ~0.2 s after it is dispatched, so a shorter
    # remainder let the overlap slip past the counter.
    assert spin_until(lambda: dock.site_engine.grid_progress("B") == (1, 4))

    session.replace_grid(dataclasses.replace(session.grid("A"), origin=(500.0, 690.0)))
    session.lines_changed.emit()
    settle(dock)
    assert counter.max_concurrent == 1, (
        f"two preparations ran at once (max_concurrent={counter.max_concurrent})"
    )
    assert dock.site_engine.ready_grids == ("A", "B", "C")
    assert not dock.engine.is_prepared and not dock.engine.has_live_task

    dock.grid_scope_button.click()
    assert spin_until(lambda: dock.engine.is_running or dock.engine.is_prepared)
    assert dock.engine.wait_for_preparation(20_000)
    assert counter.max_concurrent == 1
    assert dock.engine.is_prepared
    assert dock.engine.frame is not None and dock.engine.frame.origin == (500.0, 690.0)
    _events()
    assert dock.current_values() is not None, "This grid is drawn again"


def test_flipping_scope_mid_preparation_never_overlaps_and_settles(plugin, monkeypatch):
    counter = LoadCounter(monkeypatch, delay=0.04)
    dock = plugin.slices_dock
    # This grid starts a preparation of its own, and the site is asked for
    # straight after it: the site waits for it (Ruling 1).
    dock.transform_combo.set_value("amp_envelope")
    assert dock.engine.is_running
    dock.site_scope_button.click()
    assert spin_until(lambda: dock.site_engine.grid_state("A") == "preparing")
    dock.grid_scope_button.click()
    assert not dock.site_engine.is_running, "leaving the site stops its preparation"
    assert dock.site_engine.grid_state("B") == "queued"
    dock.site_scope_button.click()
    assert spin_until(lambda: dock.site_engine.grid_state("B") == "preparing")
    dock.grid_scope_button.click()
    assert not dock.site_engine.is_running
    dock.site_scope_button.click()
    settle(dock)

    assert counter.max_concurrent == 1, (
        f"two preparations ran at once (max_concurrent={counter.max_concurrent})"
    )
    assert dock.site_engine.ready_grids == ("A", "B", "C")
    assert dock.current_site_slice() is not None
    dock.grid_scope_button.click()
    assert dock.engine.is_prepared and dock.engine.choice.transform == "amp_envelope"


def test_leaving_the_site_waits_out_a_task_that_outlived_its_cancel(plugin, monkeypatch):
    """R-P5's other half: `set_scope("grid")` runs an owed This-grid
    preparation only once no site task is live. Here the site's cancel gives
    up (1 ms wait) with its task still reading a line."""
    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 1)
    counter = LoadCounter(monkeypatch, delay=0.15)
    dock = plugin.slices_dock
    session = plugin.session
    dock.site_scope_button.click()
    assert spin_until(lambda: counter.calls >= 1)
    # A moves: This grid's engine owes A again, and the site re-queues it.
    session.replace_grid(dataclasses.replace(session.grid("A"), origin=(500.0, 690.0)))
    assert spin_until(lambda: dock.site_engine.grid_state("A") == "preparing")
    assert spin_until(lambda: counter.concurrent == 1)
    dock.grid_scope_button.click()
    assert dock.site_engine.has_live_task, "the cancelled task is still reading"
    assert not dock.engine.is_running, "This grid waits for it"
    assert spin_until(lambda: dock.engine.is_prepared, 30_000)
    assert counter.max_concurrent == 1


def test_this_grid_opens_the_grid_selected_in_the_site_list(plugin):
    """#70: Whole site's selected row names the grid This grid opens."""
    dock = plugin.slices_dock
    whole_site(plugin)
    dock.site_panel.select_grid("B")
    site_z = dock.site_engine.site_z
    site_top = site_z.t0_ns + dock.slice_slider.value() * site_z.dz_ns
    dock.grid_scope_button.click()
    assert dock.grid_combo.currentText() == "B"
    assert dock.engine.wait_for_preparation(20_000)
    _events()
    assert dock.engine.choice.grid_id == "B"
    z = dock.engine.z
    back_top = z.t0_ns + dock.slice_slider.value() * z.dz_ns
    assert abs(back_top - site_top) <= z.dz_ns / 2 + 1e-9
    assert not plugin.session.dirty


def test_this_grid_opens_the_selected_grid_with_its_remembered_source(plugin, site3):
    plugin.session.remember_slice_source("B", preset="raw", lines=site3.keys("B")[:2])
    dock = whole_site(plugin)
    dock.site_panel.select_grid("B")
    dock.grid_scope_button.click()
    assert dock.grid_combo.currentText() == "B"
    assert dock.preset_combo.currentText() == "raw"
    assert dock.included_keys() == site3.keys("B")[:2]
    assert dock.engine.wait_for_preparation(20_000)


def test_with_this_grids_own_grid_selected_it_comes_back_as_it_was_left(plugin):
    dock = plugin.slices_dock
    # Non-default values, so skipping the restore would show.
    dock.cell_spin.setValue(round(dock.cell_spin.value() * 2, 3))
    dock.flush_debounce()
    names = [dock.palette_combo.itemText(i) for i in range(dock.palette_combo.count())]
    other = next(n for n in names if n != dock.palette_combo.currentText())
    dock.palette_combo.setCurrentText(other)
    cell, palette = dock.cell_spin.value(), dock.palette_combo.currentText()
    assert palette == other
    whole_site(plugin)
    assert dock.cell_spin.value() != pytest.approx(cell), "the site's own cell shows"
    dock.site_panel.select_grid("A")
    dock.grid_scope_button.click()
    assert dock.grid_combo.currentText() == "A"
    assert dock.cell_spin.value() == pytest.approx(cell)
    assert dock.palette_combo.currentText() == palette
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.choice.grid_id == "A"


def _spurious(errors):
    """Errors but the engine's own note that a 1 ms cancel gave up waiting."""
    return [e for e in errors if "did not stop in time" not in e]


def _narrow_a_then_site_mid_window(plugin):
    """A narrowed This-grid z range and a site time well inside the window: a
    time clamped to the left grid's axis would not survive (#70, Ruling 6)."""
    dock = plugin.slices_dock
    dock.z1_spin.setValue(dock.z0_spin.value() + (dock.z1_spin.value() - dock.z0_spin.value()) / 3)
    dock.flush_debounce()
    _events()
    whole_site(plugin)
    dock.slice_slider.setValue(int(dock.slice_slider.maximum() * 0.8))
    _events()
    return dock._site.shown_top()


def _assert_on_b_axis(dock, site_top):
    assert spin_until(lambda: dock.engine.is_prepared and dock.engine.choice.grid_id == "B", 30_000)
    spin_until(lambda: False, 400)  # any debounce runs on its own
    z = dock.engine.z
    top = z.t0_ns + dock.slice_slider.value() * z.dz_ns
    assert abs(top - site_top) <= z.dz_ns / 2 + 1e-9, (top, site_top)


def test_the_opened_grid_lands_on_the_site_time_not_the_left_grids_clamp(plugin):
    dock = plugin.slices_dock
    site_top = _narrow_a_then_site_mid_window(plugin)
    dock.site_panel.select_grid("B")
    dock.grid_scope_button.click()
    _assert_on_b_axis(dock, site_top)
    assert dock.engine.z == dock.engine.z.__class__.from_range(
        dock.z0_spin.value(), dock.z1_spin.value(), dock.dz_spin.value()
    ), "the engine holds the resolution the spins show"


def test_the_opened_grid_brings_its_remembered_resolution_to_the_engine(plugin):
    """#71 on #70's switch: the grid opened from the site list restores its
    remembered resolution, and the owed apply carries it to the engine. The
    switch is no choice, so nothing is written and the survey stays clean."""
    dock = plugin.slices_dock
    session = plugin.session
    session.remember_slice_resolution("B", cell=0.1, dz_ns=0.5, radius_spacings=1.5)
    session.save()
    stored = session.slice_source("B")
    whole_site(plugin)
    dock.site_panel.select_grid("B")
    dock.grid_scope_button.click()
    assert dock.grid_combo.currentText() == "B"
    assert dock.engine.wait_for_preparation(20_000)
    spin_until(lambda: False, 400)  # any debounce runs on its own
    assert dock.cell_spin.value() == pytest.approx(0.1)
    assert dock.dz_spin.value() == pytest.approx(0.5)
    assert dock.grid_radius_spin.value() == pytest.approx(1.5)
    assert dock.engine.choice.grid_id == "B"
    assert dock.engine.frame.cell == pytest.approx(0.1)
    assert dock.engine.z.dz_ns == pytest.approx(0.5)
    assert dock.current_values() is not None
    assert session.slice_source("B") == stored
    assert not session.dirty


def test_the_opened_grid_lands_on_the_site_time_when_a_site_task_outlived_its_cancel(
    plugin, monkeypatch
):
    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 1)
    dock = plugin.slices_dock
    site_top = _narrow_a_then_site_mid_window(plugin)
    errors: list[str] = []
    dock.error.connect(errors.append)
    counter = LoadCounter(monkeypatch, delay=0.3)
    dock.site_panel.select_grid("B")
    # Re-queue a site read so a task is live when the cancel gives up.
    dock.site_panel.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    dock.site_panel.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    spin_until(lambda: counter.concurrent == 1, 5_000)
    dock.grid_scope_button.click()
    assert dock.site_engine.has_live_task, "the cancelled task is still reading"
    spin_until(lambda: False, 300)  # the seeded spins' debounce fires in the window
    assert _spurious(errors) == []
    _assert_on_b_axis(dock, site_top)
    assert counter.max_concurrent == 1
    assert _spurious(errors) == []


def test_opening_the_selected_grid_waits_for_a_site_task_that_outlived_its_cancel(
    plugin, monkeypatch
):
    """#70 with R-P5: the switch owes B's preparation; it runs only once the
    site's task, which outlived its bounded cancel, has stopped."""
    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 1)
    counter = LoadCounter(monkeypatch, delay=0.15)
    dock = plugin.slices_dock
    errors: list[str] = []
    dock.error.connect(errors.append)
    dock.site_scope_button.click()
    assert spin_until(lambda: counter.concurrent == 1)
    dock.site_panel.select_grid("B")
    dock.grid_scope_button.click()
    assert dock.site_engine.has_live_task, "the cancelled task is still reading"
    assert not dock.engine.is_running, "This grid waits for it"
    spin_until(lambda: False, 300)  # the seeded spins' debounce fires in the window
    dock.slice_slider.setValue(dock.slice_slider.value() + 1)  # and a drag
    _events()
    assert _spurious(errors) == []
    assert spin_until(lambda: dock.engine.is_prepared and dock.engine.choice.grid_id == "B", 30_000)
    assert counter.max_concurrent == 1
    assert _spurious(errors) == []


def _remove_selected_and_switch(plugin, grid_id):
    dock = whole_site(plugin)
    errors: list[str] = []
    dock.error.connect(errors.append)
    dock.site_panel.select_grid(grid_id)
    plugin.session.remove_grid(grid_id, with_lines=True)
    _events()
    plugin.session.save()  # the removal itself dirties; the switch must not
    assert not plugin.session.dirty
    shown = dock.site_panel.selected_grid()
    dock.grid_scope_button.click()
    assert errors == []
    return dock, shown


def test_removing_the_selected_last_grid_opens_the_neighbour_the_panel_selects(plugin):
    """Ruling 7: the rule is the row the list shows selected at the switch."""
    dock, shown = _remove_selected_and_switch(plugin, "C")
    assert shown == "B"
    assert dock.grid_combo.currentText() == shown
    assert dock.engine.wait_for_preparation(20_000)
    assert not plugin.session.dirty


def test_removing_a_selected_middle_grid_leaves_no_selection_and_this_grid_stays(plugin):
    dock, shown = _remove_selected_and_switch(plugin, "B")
    assert shown is None
    assert dock.grid_combo.currentText() == "A"
    assert dock.engine.wait_for_preparation(20_000)
    assert not plugin.session.dirty


def test_a_selection_naming_a_grid_this_grid_does_not_offer_is_ignored(plugin, monkeypatch):
    """The `_grid_to_resume` guard itself, with a stale id the panel cannot make."""
    dock = whole_site(plugin)
    errors: list[str] = []
    dock.error.connect(errors.append)
    monkeypatch.setattr(dock.site_panel, "selected_grid", lambda: "Z")
    dock.grid_scope_button.click()
    assert dock.grid_combo.currentText() == "A"
    assert errors == []


def test_a_carried_time_never_overrides_a_later_resolution_change(plugin):
    """A reopened survey prepares with nothing owed; the site's time must not
    stay pending and replace the user's slider time at their next change."""
    dock = plugin.slices_dock
    session = plugin.session
    whole_site(plugin)
    dock.slice_slider.setValue(int(dock.slice_slider.maximum() * 0.8))
    _events()
    session.save()
    path = session.json_path
    session.open_site(path)
    _events()
    assert dock.engine.wait_for_preparation(20_000)
    spin_until(lambda: False, 400)
    dock.slice_slider.setValue(5)
    _events()
    z = dock.engine.z
    user_top = z.t0_ns + dock.slice_slider.value() * z.dz_ns
    dock.dz_spin.setValue(round(dock.dz_spin.value() * 2, 4))
    dock.flush_debounce()
    _events()
    z = dock.engine.z
    assert abs(z.t0_ns + dock.slice_slider.value() * z.dz_ns - user_top) <= z.dz_ns / 2 + 1e-9
    assert dock._pending_top_ns is None


def test_re_entering_the_site_inside_the_wait_window_keeps_the_window_time(plugin, monkeypatch):
    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 1)
    dock = plugin.slices_dock
    dock.dz_spin.setValue(dock.dz_spin.value() * 3)  # A's axis differs from the site's
    dock.flush_debounce()
    _events()
    whole_site(plugin)
    dock.slice_slider.setValue(int(dock.slice_slider.maximum() * 0.8))
    _events()
    site_top = dock._site.shown_top()
    counter = LoadCounter(monkeypatch, delay=0.6)
    dock.site_panel.select_grid("B")
    dock.site_panel.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    dock.site_panel.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    spin_until(lambda: counter.concurrent == 1, 5_000)
    dock.grid_scope_button.click()
    assert dock.site_engine.has_live_task
    dock.site_scope_button.click()
    _events()
    assert dock._site.shown_top() == pytest.approx(site_top, abs=0.5)


def _in_wait_window(plugin, monkeypatch):
    """B selected in the site, a site task outliving its cancel, This grid
    clicked: the dock is in the wait window (#70). Returns dock, errors, the
    site's time."""
    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 1)
    dock = plugin.slices_dock
    errors: list[str] = []
    dock.error.connect(errors.append)
    site_top = _narrow_a_then_site_mid_window(plugin)
    counter = LoadCounter(monkeypatch, delay=0.6)
    dock.site_panel.select_grid("B")
    dock.site_panel.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    dock.site_panel.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    spin_until(lambda: counter.concurrent == 1, 5_000)
    dock.grid_scope_button.click()
    assert dock.site_engine.has_live_task
    return dock, errors, site_top


def _round_trip_through_the_site(dock):
    dock.site_scope_button.click()
    _events()
    assert spin_until(lambda: not dock.site_engine.has_live_task, 20_000)
    spin_until(lambda: False, 300)
    dock.grid_scope_button.click()


def test_a_round_trip_through_the_site_in_the_wait_window_keeps_the_owed_resolution(
    plugin, monkeypatch
):
    dock, errors, _ = _in_wait_window(plugin, monkeypatch)
    dock.z0_spin.setValue(0.0)
    dock.z1_spin.setValue(60.0)
    _events()
    _round_trip_through_the_site(dock)
    assert spin_until(lambda: dock.engine.is_prepared and dock.engine.choice.grid_id == "B", 30_000)
    spin_until(lambda: False, 400)
    z = dock.engine.z
    assert z.t0_ns == pytest.approx(dock.z0_spin.value(), abs=z.dz_ns)
    assert z.t0_ns + (z.nz - 1) * z.dz_ns == pytest.approx(dock.z1_spin.value(), abs=z.dz_ns)
    assert dock.z1_spin.value() == pytest.approx(60.0)
    assert _spurious(errors) == []


def test_a_round_trip_through_the_site_in_the_wait_window_keeps_the_window_time(
    plugin, monkeypatch
):
    dock, errors, site_top = _in_wait_window(plugin, monkeypatch)
    _round_trip_through_the_site(dock)
    _assert_on_b_axis(dock, site_top)
    assert _spurious(errors) == []


def _assert_a_slice_is_drawn_on_a(dock, errors):
    assert spin_until(lambda: dock.engine.is_prepared and dock.engine.choice.grid_id == "A", 30_000)
    spin_until(lambda: False, 400)
    dock.z1_spin.setValue(dock.z1_spin.value() - 1)  # a later edit must not error either
    dock.flush_debounce()
    _events()
    assert _spurious(errors) == []
    assert dock.current_values() is not None


def test_landing_on_the_grid_the_engine_already_holds_clamps_the_seeded_range(plugin, monkeypatch):
    dock, errors, _ = _in_wait_window(plugin, monkeypatch)
    dock.site_scope_button.click()
    _events()
    assert spin_until(lambda: not dock.site_engine.has_live_task, 20_000)
    dock.site_panel.select_grid("A")
    dock.grid_scope_button.click()
    _assert_a_slice_is_drawn_on_a(dock, errors)


def test_landing_on_the_grid_the_engine_holds_falls_back_from_a_range_past_its_data(
    plugin, monkeypatch
):
    """#71, Review Focus 1, on #70's owed path: `prepare()` is a no-op (the
    engine still holds A), so `_run_pending_grid_prepare`'s own clamp is the
    one that meets A's remembered range lying wholly past A's data."""
    from nsgeo_qgis.ui.slices_dock import _snap_inside

    dock, errors, _ = _in_wait_window(plugin, monkeypatch)
    assert dock.engine.choice.grid_id == "A"
    _low, high = dock.engine.prepared_z_bounds()
    beyond = {"t0_ns": high + 10.0, "t1_ns": high + 50.0}
    plugin.session.remember_slice_resolution("A", **beyond)
    dock.site_scope_button.click()
    _events()
    assert spin_until(lambda: not dock.site_engine.has_live_task, 20_000)
    dock.site_panel.select_grid("A")
    dock.grid_scope_button.click()
    assert dock.engine.is_prepared and not dock.engine.is_running, "the no-op path"
    low, high = dock.engine.prepared_z_bounds()
    assert dock.z0_spin.value() == _snap_inside(low, dock.z0_spin.decimals(), upper=False)
    assert dock.z1_spin.value() == _snap_inside(high, dock.z1_spin.decimals(), upper=True)
    assert plugin.session.slice_resolution("A") == beyond
    _assert_a_slice_is_drawn_on_a(dock, errors)


def test_a_grid_removed_inside_the_wait_window_clamps_the_fallback_grid(plugin, monkeypatch):
    dock, errors, _ = _in_wait_window(plugin, monkeypatch)
    plugin.session.remove_grid("B", with_lines=True)
    _events()
    assert dock.grid_combo.currentText() == "A"
    _assert_a_slice_is_drawn_on_a(dock, errors)


def test_a_raising_prepare_does_not_leave_the_owed_resolution_stuck(plugin, monkeypatch):
    dock = whole_site(plugin)
    dock.site_panel.select_grid("B")
    monkeypatch.setattr(dock, "prepare", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    dock.grid_scope_button.click()
    assert dock._resolution_owed is False


def test_a_failure_inside_resume_still_hands_this_grids_moves_back(plugin, monkeypatch):
    dock = whole_site(plugin)
    real = dock._refresh_source_status
    calls = []

    def boom():
        if not calls:
            calls.append(1)
            raise RuntimeError("boom")
        real()

    monkeypatch.setattr(dock, "_refresh_source_status", boom)
    with pytest.raises(RuntimeError):
        dock.set_scope("grid")
    assert dock.engine.on_grid_moved is None


def test_moving_this_grids_grid_while_a_site_task_outlives_its_cancel_never_overlaps(
    plugin, monkeypatch
):
    """Final review D2 (trap 1). Leaving Whole site cancels the site's task;
    when the bounded wait gives up, the task is still reading a line. This
    grid's engine must go on handing a move to the dock (`_mark_grid_stale`)
    rather than re-preparing itself (M11) until no site task is live --
    else moving its grid inside that window starts a second preparation.
    A line takes 0.8 s here, so the window is wide."""
    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 1)
    counter = LoadCounter(monkeypatch, delay=0.8)
    dock = plugin.slices_dock
    session = plugin.session
    dock.site_scope_button.click()
    assert spin_until(lambda: counter.concurrent == 1)  # the site reads A's first line
    dock.grid_scope_button.click()
    assert dock.site_engine.has_live_task, "the cancelled task is still reading"
    session.replace_grid(dataclasses.replace(session.grid("A"), origin=(500.0, 690.0)))
    assert not dock.engine.is_running, "This grid waits for the site's task"
    assert spin_until(lambda: dock.engine.is_prepared, 30_000)
    assert counter.max_concurrent == 1, (
        f"two preparations ran at once (max_concurrent={counter.max_concurrent})"
    )
    assert dock.engine.frame is not None and dock.engine.frame.origin == (500.0, 690.0)
    assert dock.engine.on_grid_moved is None, "M11's own re-preparation, once the site stopped"


def test_leaving_an_idle_site_hands_this_grids_moves_straight_back(plugin):
    """Final review D2's other half: with no site task live, leaving Whole
    site gives This grid's engine M11's own re-preparation on a move back
    at once."""
    dock = whole_site(plugin)
    assert dock.engine.on_grid_moved is not None  # R-P5, while the site shows
    dock.grid_scope_button.click()
    assert not dock.site_engine.has_live_task
    assert dock.engine.on_grid_moved is None


def test_unload_with_the_site_scope_open_leaves_nothing_running(
    fake_iface, site3, answer_modal, monkeypatch
):
    LoadCounter(monkeypatch, delay=0.05)
    plugin = _open(fake_iface, site3, answer_modal)
    dock = plugin.slices_dock
    site_engine, engine = dock.site_engine, dock.engine
    dock.site_scope_button.click()
    assert spin_until(lambda: site_engine.grid_state("B") == "preparing")
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
    assert not site_engine.has_live_task and not engine.has_live_task
    assert spin_until(lambda: False, 300) is False  # let anything stray fire; nothing may raise
    assert not site_engine.has_live_task
