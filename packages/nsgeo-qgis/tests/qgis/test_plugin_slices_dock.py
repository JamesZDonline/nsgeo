"""The Slices dock's Source group, and its Position/Resolution/Display groups."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.render import colormap_names
from nsgeo.slices import window_depths_m, window_times_ns
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_plan import transform_names
from nsgeo_qgis.ui.slices_dock import SlicesDock
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [{"step": "dewow", "params": {}, "enabled": True}]


@pytest.fixture
def docked(qgis_app, tmp_path):
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = [
        Line.open(
            synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60),
            GridPlacement("A", "y", 1.0 + i, 0.0, 1, f"L{i}"),
        )
        for i in range(3)
    ]
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()
    dock = SlicesDock(session)
    yield dock, session
    # Fix round 1: Important 2's first-computation trigger means
    # construction ALREADY dispatched a real QgsTask here, and most tests
    # above never call wait_for_preparation() themselves. dispose() only
    # disconnects signals and drops this engine's own references -- it
    # does not cancel or wait for a task already handed to
    # QgsApplication.taskManager(), which is a session-scoped singleton
    # shared by every test in this file. Left unawaited, that orphaned
    # task keeps running in a real background thread for as long as it
    # takes, and a later test's OWN construction can dispatch a SECOND one
    # before the first finishes -- measured directly as a segfault (two
    # worker threads inside dewow's `running_mean` at once), not merely a
    # slow teardown. Waiting here, before dispose(), is what keeps every
    # test's background work finished before the next test's fixture ever
    # starts building a new one.
    dock.engine.wait_for_preparation(20_000)
    dock.engine.dispose()
    dock.deleteLater()


def test_the_source_combos_are_filled_from_the_site_not_from_literals(docked):
    dock, session = docked
    assert [dock.grid_combo.itemText(i) for i in range(dock.grid_combo.count())] == ["A"]
    assert "p" in [dock.preset_combo.itemText(i) for i in range(dock.preset_combo.count())]
    offered = [dock.transform_combo.itemText(i) for i in range(dock.transform_combo.count())]
    assert offered[0] == "none"  # spec 6.2 and GPRSLICE's xfrm_method=NONE
    assert offered[1:] == transform_names()


def test_adding_a_preset_updates_the_combo_without_a_reopen(docked):
    dock, session = docked
    session.site.presets["second"] = list(PRESET)
    session.presets_changed.emit()
    assert "second" in [dock.preset_combo.itemText(i) for i in range(dock.preset_combo.count())]


def test_the_included_summary_reads_as_a_fraction_of_the_grid(docked):
    dock, session = docked
    assert dock.included_label.text().startswith("3 of 3 included")
    dock.set_included(tuple(session.keys())[:2])
    assert dock.included_label.text().startswith("2 of 3 included")


def test_the_dock_reports_the_memory_before_committing_to_preparing_it(docked):
    """Spec 9.1: before committing the ~0.9 s the dock reports what the
    resulting memory will be, because it is decided by the line count and
    the chosen resolution -- and spec 7.4 warns rather than hard-caps.

    Fix round 1, M6: `"MB" in text` alone could never fail --
    `format_bytes` floors at 1 MB, so it reads "1 MB" whether 0 or 3 lines
    are actually included, which is exactly the state Important 1's bug
    produces. Asserting the fraction against the session's own line count
    (not the dock's) makes this test fail under that bug instead of
    passing beside it."""
    dock, session = docked
    text = dock.included_label.text()
    assert text.startswith(f"{len(session.keys())} of {len(session.keys())} included")
    assert "MB" in text or "GB" in text


def test_choosing_a_preset_that_carries_a_transform_is_refused_visibly(docked):
    """Ruling 2, surfaced. The engine raises; the dock must turn that into
    something the user can read and act on, not let it escape a slot."""
    dock, session = docked
    session.site.presets["bad"] = [{"step": "amp_abs", "params": {}, "enabled": True}]
    session.presets_changed.emit()
    seen: list[str] = []
    dock.error.connect(seen.append)
    dock.preset_combo.setCurrentText("bad")  # re-preparing is what refuses it
    assert any("amp_abs" in msg for msg in seen), seen
    assert "amp_abs" in dock.source_status.text()
    assert not dock.engine.is_prepared


def test_refilling_the_combos_does_not_re_prepare(docked):
    """Refilling a QComboBox emits currentTextChanged. Without the
    _updating guard the dock re-prepares on construction and on every
    grids_changed / lines_changed / presets_changed — ~0.9 s of work per
    unrelated session signal, which IS the "nothing runs automatically"
    the design forbids."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    prepared: list[int] = []
    dock.engine.on_prepared = lambda: prepared.append(1)
    session.site.presets["another"] = list(PRESET)
    session.presets_changed.emit()
    session.lines_changed.emit()
    assert dock.engine.wait_for_preparation(2_000)
    assert prepared == [], "refilling the combos must not have re-prepared"


def test_preparing_reports_progress_and_then_reports_prepared(docked):
    dock, session = docked
    dock.prepare()  # the dock prepares on construction too; this is the retry path
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.is_prepared
    assert dock.engine.line_count == 3
    assert "prepared" in dock.source_status.text().lower()


def test_changing_the_source_re_prepares_it_rather_than_waiting_to_be_asked(docked):
    """Spec 9.1, explicitly: changing the grid, preset or transform
    re-runs the preparation as a QgsTask. That is not a violation of
    "nothing runs automatically" -- the user chose a preset, and
    preparation is the execution of that choice, not an inference about
    it. A prepared source left standing after one of its three inputs
    changed would tell the user the screen matches a choice it does not."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.line_count == 3

    session.add_grid(Grid("B", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    dock.grid_combo.setCurrentText("B")  # no explicit prepare() call
    assert dock.engine.wait_for_preparation(20_000)
    # Grid B holds no lines, so the re-preparation really ran and really
    # used the new grid rather than leaving the old result in place.
    assert dock.engine.line_count == 0


def test_closing_the_site_empties_the_dock(docked):
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    session.close_site()
    assert dock.grid_combo.count() == 0
    assert not dock.engine.is_prepared


def test_a_single_grid_single_preset_source_prepares_without_being_asked(docked):
    """Fix round 1, Important 2. With one grid, one preset and transform
    'none' -- exactly this fixture's shape -- no combo can ever change
    again after construction, so `_on_source_changed` (the only other
    caller of `prepare()`) can never fire either. Without a first-
    computation trigger in `rebuild_source` itself, nothing here could
    ever reach 'prepared', which is the brief's own done-criterion for
    this dock. `dock.prepare()` is deliberately never called in this
    test -- calling it would defeat the point."""
    dock, session = docked
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.is_prepared
    assert dock.engine.line_count == 3


def test_construction_reports_not_prepared_before_the_first_task_finishes(docked):
    """Ruling R's first state. The first-computation trigger (Important 2)
    starts a QgsTask synchronously inside `rebuild_source`, but the task
    itself only finishes once the event loop is spun -- which nothing has
    done yet at this point -- so the status line must still say the
    honest thing about what is (not yet) prepared."""
    dock, _ = docked
    assert dock.source_status.text() == "not prepared"
    assert dock.engine.wait_for_preparation(20_000)  # let the fixture's own task finish cleanly


def test_lines_added_after_construction_are_picked_up_as_the_default(qgis_app, tmp_path):
    """Fix round 1, Important 1 / Ruling S. The real plugin order builds
    this dock at `initGui`, before any site exists: `grids_changed` fires
    while the grid is still empty (seeding the default to `()`), and a
    LATER `lines_changed`, with the same grid still selected, must still
    pick up the lines that arrive after that seed -- not leave it stuck
    at the count that existed the moment the grid first appeared. The
    `docked` fixture above builds the whole site before the dock, which
    never exercises this path at all."""
    session = SiteSession()
    dock = SlicesDock(session)
    try:
        assert dock.grid_combo.count() == 0  # no site yet
        session.new_site(tmp_path)
        session.add_grid(GRID)
        assert dock.included_label.text().startswith("0 of 0 included")
        lines = [
            Line.open(
                synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60),
                GridPlacement("A", "y", 1.0 + i, 0.0, 1, f"L{i}"),
            )
            for i in range(3)
        ]
        session.add_lines(lines)
        assert dock.included_label.text().startswith("3 of 3 included")
        assert len(dock.included_keys()) == 3
    finally:
        dock.engine.dispose()
        dock.deleteLater()


def test_accepting_the_line_chooser_reprepares_and_shows_stale_meanwhile(docked):
    """Fix round 1, Important 2's second half: accepting the line chooser
    is a choice made in this dock, the same as a combo change, so it must
    re-prepare on its own. Ruling R: between that choice and the retry
    finishing, `source_status` must say 'stale', not keep claiming the OLD
    count is still current."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.line_count == 3

    keys = tuple(session.keys())[:2]
    dock.set_included(keys)  # no explicit prepare() call
    assert dock.source_status.text().startswith("stale")
    assert "lines" in dock.source_status.text()

    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.line_count == 2
    assert "prepared" in dock.source_status.text().lower()


def test_deleting_the_selected_preset_shows_stale_not_a_wrong_name(docked):
    """Ruling R's spec gap, as widened by the review: `_refill` cannot
    restore a preset name that no longer exists, so the combo silently
    jumps to a fallback while `_updating` suppresses `_on_source_changed`.
    Without this check the dock would keep naming a preset the engine
    never actually prepared -- deleting the SELECTED preset must not
    quietly leave 'prepared · 3 lines' standing beside a combo that now
    reads something else entirely."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.line_count == 3

    del session.site.presets["p"]
    session.site.presets["only"] = list(PRESET)
    session.presets_changed.emit()

    assert dock.preset_combo.currentText() == "only"
    assert dock.source_status.text().startswith("stale")
    assert "preset" in dock.source_status.text()
    # Point 5's decision stands even here: no auto re-prepare from a
    # combo change forced by a refill, only from one the user drove.
    assert dock.engine.is_prepared
    assert dock.engine.line_count == 3


def test_editing_the_selected_preset_in_place_shows_stale_without_reprocessing(docked):
    """Point 5's decision, now with a visible consequence: editing the
    CONTENTS of the currently-selected preset (same name) does not
    re-prepare on its own -- Ruling K already freezes what a prepared
    source was actually built from, on purpose -- but the status line
    must stop claiming the screen matches a choice it no longer does."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.line_count == 3
    before = list(dock.engine.provenance().steps)

    session.site.presets["p"] = [{"step": "background_mean", "params": {}, "enabled": True}]
    session.presets_changed.emit()

    assert dock.source_status.text().startswith("stale")
    assert "preset" in dock.source_status.text()
    assert dock.engine.is_prepared
    assert dock.engine.line_count == 3
    assert list(dock.engine.provenance().steps) == before  # no re-prepare happened


def test_calling_prepare_again_after_an_in_place_edit_clears_the_staleness(docked):
    """Fix round 3, Ruling X. `prepare()`'s no-op guard used to compare
    only grid/preset-name/transform/line_keys, never the steps
    themselves -- so after an in-place edit to the selected preset, the
    documented retry path (calling `prepare()` again) silently did
    nothing, and with one grid and one preset the source was PERMANENTLY
    stale: the only recovery left was toggling the transform away and
    back, paying for two preparations and showing the wrong transform in
    between. The guard must still skip a GENUINELY unchanged choice
    (`test_refilling_the_combos_does_not_re_prepare` pins that half)."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.line_count == 3

    new_steps = [{"step": "background_mean", "params": {}, "enabled": True}]
    session.site.presets["p"] = list(new_steps)
    session.presets_changed.emit()
    assert dock.source_status.text().startswith("stale")

    dock.prepare()  # the documented retry path -- must NOT be a no-op here
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.is_prepared
    assert list(dock.engine.provenance().steps) == new_steps
    assert "prepared" in dock.source_status.text().lower()


def test_the_stale_wording_names_the_grid_when_only_the_grid_diverges(docked):
    """Fix round 3, Ruling Y's fourth finding: every non-`line_keys`
    divergence used to print 'the preset changed', even when the grid was
    what actually diverged. The combo is changed with signals blocked,
    bypassing the normal `_on_source_changed` -> `prepare()` path (which
    would immediately re-prepare against grid B and stop being stale) --
    isolating the wording `_refresh_source_status` itself picks for a
    grid-only divergence."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)

    session.add_grid(Grid("B", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    dock.grid_combo.blockSignals(True)
    dock.grid_combo.addItem("B")
    dock.grid_combo.setCurrentText("B")
    dock.grid_combo.blockSignals(False)

    dock._refresh_source_status()
    assert dock.source_status.text().startswith("stale")
    assert "grid" in dock.source_status.text()


def test_the_stale_wording_names_the_transform_when_only_the_transform_diverges(docked):
    """Fix round 3, Ruling Y's fourth finding, the transform half."""
    dock, _ = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)

    dock.transform_combo.blockSignals(True)
    dock.transform_combo.setCurrentText("amp_abs")
    dock.transform_combo.blockSignals(False)

    dock._refresh_source_status()
    assert dock.source_status.text().startswith("stale")
    assert "transform" in dock.source_status.text()


def test_a_failed_schedule_does_not_claim_lines_prepared(docked, monkeypatch):
    """Fix round 3, Ruling Y's fifth finding: `_on_engine_error` stopped
    writing into `source_status` directly in fix round 1 (routed through
    `_refresh_source_status` instead), so after a failed `addTask` the
    recomputed line read `prepared · 0 lines` -- a claim that something
    succeeded when scheduling itself failed outright."""
    dock, _ = docked
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.is_prepared

    class _FakeManager:
        def addTask(self, task: object) -> int:
            return 0

    class _FakeApp:
        @staticmethod
        def taskManager() -> _FakeManager:
            return _FakeManager()

    import nsgeo_qgis.slices_engine as engine_module

    monkeypatch.setattr(engine_module, "QgsApplication", _FakeApp)
    dock.transform_combo.setCurrentText("amp_abs")  # a genuine change -- prepare() must run

    assert not dock.engine.is_prepared
    assert dock.source_status.text() == "not prepared · every line failed"


def _ready(dock):
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    dock.z0_spin.setValue(2.0)
    dock.z1_spin.setValue(30.0)
    dock.dz_spin.setValue(0.5)
    dock.cell_spin.setValue(0.25)
    dock.flush_debounce()  # applies the pending Resolution change immediately


def test_the_seeded_default_resolution_actually_slices(docked):
    """Fix round 1, Important 6. Every other navigation test in this file
    runs through `_ready()`, which overwrites `z0_spin`/`z1_spin` with
    values that happen to sit inside the fixture's real recording
    window -- so nothing exercised `_seed_resolution_defaults`'s OWN
    z0/z1 formula. That is precisely how a `z0 = 0.0` seed (assuming a
    DZT's recorded window starts at time zero) reached Step 10 alive: it
    made every default-resolution `refresh_slice()` raise `CoverageError`
    silently (caught by `refresh_slice()`'s own guard), which looked like
    a suspiciously fast, do-nothing timing loop rather than a visible
    failure, and was only actually caught by timing it."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()  # apply the SEEDED default resolution, no overrides
    header = session.line_for_key(session.keys()[0]).header
    assert dock.z0_spin.value() == pytest.approx(header.position_ns)
    assert dock.current_values() is not None


def test_the_readout_states_the_window_that_was_actually_averaged(docked):
    """Spec 9.2: the control that moves the window and the statement of
    where the window now is are one unit, read together on every tick.
    Spec 6.6: always the full range, never the centre -- with overlapping
    slices, the extent of what is averaged is the thing a reader would
    otherwise mistake for vertical resolution.

    Fix round 1, Important 1: spec 9.2 fixes the text as BOTH units
    (`slice 14 / 40 · 12.0-16.0 ns · 0.60-0.80 m`) -- the brief's own
    draft only ever checked the ns half, which is why the readout could
    silently drop the m half entirely."""
    dock, session = docked
    _ready(dock)
    dock.thickness_spin.setValue(4.0)
    dock.slice_slider.setValue(10)
    text = dock.readout.text()
    window = dock.current_window()
    assert window is not None
    lo, hi = window_times_ns(dock.engine.z, window)
    assert f"{lo:.1f}" in text and f"{hi:.1f}" in text
    assert "ns" in text
    assert "/" in text and "slice" in text  # "slice 14 / 40"
    velocity = session.resolved_velocity(session.keys()[0])
    lo_m, hi_m = window_depths_m(dock.engine.z, window, velocity)
    assert f"{lo_m:.2f}" in text and f"{hi_m:.2f}" in text
    assert "m" in text


def test_the_readout_shrinks_with_the_window_at_the_end_of_the_axis(docked):
    """Trap 3. At either end `ZAxis.level_range` returns a genuinely
    thinner window than asked for, and spec 6.6 requires the readout to
    show what was actually averaged. A readout rebuilt from the slider
    position plus the thickness spin box claims a window the axis
    refused.

    Fix round 1, M1: asserting only `f"{hi:.1f}" in text` cannot
    discriminate a readout rebuilt from the raw request here, because at
    this clamped last window `lo == hi`, which coincides with the
    mutant's own top-of-window value at the same slider position. The
    added, parallel assertion pins the whole "lo-hi ns" substring, the
    same shape the fill-radius test already pins as an absolute value
    rather than only a relative one."""
    dock, _ = docked
    _ready(dock)
    dock.thickness_spin.setValue(8.0)
    dock.slice_slider.setValue(dock.slice_slider.maximum())
    window = dock.current_window()
    lo, hi = window_times_ns(dock.engine.z, window)
    assert hi <= dock.engine.z.t_end_ns + 1e-9
    assert hi - lo < 8.0  # thinner than requested, and the readout says so
    assert f"{hi:.1f}" in dock.readout.text()
    assert f"{lo:.1f}-{hi:.1f} ns" in dock.readout.text()


def test_moving_the_slider_emits_slice_changed_and_changes_the_values(docked):
    dock, _ = docked
    _ready(dock)
    seen: list[int] = []
    dock.slice_changed.connect(lambda: seen.append(1))
    dock.slice_slider.setValue(4)
    first = dock.current_values().copy()
    dock.slice_slider.setValue(30)
    second = dock.current_values()
    assert len(seen) >= 2
    both = np.isfinite(first) & np.isfinite(second)
    assert both.any()
    assert not np.allclose(first[both], second[both]), "a different depth must look different"


def test_the_fill_radius_is_metres_and_survives_a_cell_size_change(docked):
    """Spec 6.4's default is 1.5 x the line spacing -- a distance. The
    spin box is therefore in metres and the cell conversion happens
    underneath, so halving the cell size does not silently halve the
    smoothing.

    Strengthened from the brief's own draft: with this fixture's
    `GRID.default_spacing` of 0.5, the default radius is 0.75 m -- under
    1 cell wide before ANY conversion -- so `int(self.radius_spin.value())`
    (metres misread as an already-integer cell count, the exact mutant
    Step 10 names) truncates to 0 both before and after the cell change,
    and `before * 2 == 0` too, so the relative-doubling check alone passes
    even against that mutant (verified: all 37 tests in this file and
    `test_plugin_slice_layer.py` still passed with that mutant applied).
    The added absolute check pins the one number the mutant cannot also
    get right by accident."""
    dock, session = docked
    _ready(dock)
    assert dock.radius_spin.value() == pytest.approx(1.5 * GRID.default_spacing)
    before = dock.radius_cells()
    assert before == round(1.5 * GRID.default_spacing / 0.25)  # 0.25 m/cell, set by _ready()
    dock.cell_spin.setValue(0.125)
    dock.flush_debounce()
    assert dock.radius_spin.value() == pytest.approx(1.5 * GRID.default_spacing)
    assert dock.radius_cells() == pytest.approx(before * 2, abs=1)


def test_filling_reaches_between_the_lines_and_zero_radius_does_not(docked):
    """Spec 6.4: at realistic spacing about 80% of cells are empty, so the
    fill is most of the picture rather than a nicety."""
    dock, _ = docked
    _ready(dock)
    dock.radius_spin.setValue(0.0)
    dock.flush_debounce()
    unfilled = np.isfinite(dock.current_values()).sum()
    dock.radius_spin.setValue(1.0)
    dock.flush_debounce()
    filled = np.isfinite(dock.current_values()).sum()
    assert filled > unfilled


def test_the_coverage_toggle_shows_trace_counts_not_amplitudes(docked):
    """Spec 3: a zero that means 'no data' reading as 'no reflection' is
    the defect a count array exists to fix, and the coverage view is where
    a user sees it.

    Fix round 1, Important 2 (Ruling AB): checking only `current_values()`
    is exactly why nothing caught `display_limit()` ignoring the coverage
    view and returning the SHARED (amplitude) limit instead -- ~7.0e4 on
    this fixture, which maps every trace count to the shader's bottom
    stop and renders the whole view as one flat colour. The added
    assertions pin the limit itself, not just the array it is measured
    over."""
    dock, _ = docked
    _ready(dock)
    dock.coverage_check.setChecked(True)
    coverage = dock.current_values()
    assert np.nanmax(coverage) >= 1.0
    assert np.allclose(coverage[np.isfinite(coverage)] % 1.0, 0.0), "counts are whole traces"
    limit = dock.display_limit()
    assert limit == pytest.approx(float(np.nanmax(coverage)))
    assert dock.display_unipolar() is True, "a trace count is never negative"
    dock.coverage_check.setChecked(False)
    assert not np.allclose(np.nan_to_num(dock.current_values()), np.nan_to_num(coverage))
    assert dock.display_limit() != pytest.approx(limit)


def test_a_shared_stretch_holds_one_limit_across_depth_and_per_slice_does_not(docked):
    """Spec 8: comparability by default, legibility on demand."""
    dock, _ = docked
    _ready(dock)
    dock.stretch_combo.setCurrentText("shared across the cube")
    dock.slice_slider.setValue(4)
    shallow = dock.display_limit()
    dock.slice_slider.setValue(40)
    deep = dock.display_limit()
    assert shallow == pytest.approx(deep)

    dock.stretch_combo.setCurrentText("this slice")
    dock.slice_slider.setValue(4)
    shallow_own = dock.display_limit()
    dock.slice_slider.setValue(40)
    deep_own = dock.display_limit()
    assert shallow_own != pytest.approx(deep_own)


def test_the_palette_offers_unipolar_tables_for_a_transformed_source(docked):
    """Spec 8's rule: a bipolar table on unipolar data is a configuration
    error, not a style choice. The combo is where that rule is enforced.

    Fixed from the brief's own draft: `docked`'s preset ("p", a plain
    `dewow`) carries no transform, and `transform_combo` starts on its
    first item, "none" -- so without explicitly choosing a transform here,
    `engine.output_unipolar` is already False right after `_ready()`, and
    the very first assertion below (expecting the UNIPOLAR list) fails
    against correct code. The name says "for a transformed source"; the
    fixture needs to actually be one before that assertion runs."""
    dock, _ = docked
    _ready(dock)
    dock.transform_combo.setCurrentText("amp_abs")  # re-prepares on its own (spec 9.1)
    assert dock.engine.wait_for_preparation(20_000)
    offered = [dock.palette_combo.itemText(i) for i in range(dock.palette_combo.count())]
    assert set(offered) == set(colormap_names(unipolar=True))
    assert "seismic" not in offered

    dock.transform_combo.setCurrentText("none")  # re-prepares on its own (spec 9.1)
    assert dock.engine.wait_for_preparation(20_000)
    offered = [dock.palette_combo.itemText(i) for i in range(dock.palette_combo.count())]
    assert set(offered) == set(colormap_names(unipolar=False))
    assert "amp_heat" not in offered


def test_the_status_line_reports_what_is_held_and_how_fast(docked):
    dock, _ = docked
    _ready(dock)
    dock.slice_slider.setValue(8)
    text = dock.status_label.text()
    assert "lines held in memory" in text
    assert "slices redraw in" in text


def test_a_resolution_change_is_debounced_into_one_rebuild(docked):
    """Spec 7.2 and trap 4: a rebuild is 44 ms and even the improved fill
    is 32 ms at 600x600, so a slider emitting per-step would queue work
    faster than it can finish."""
    dock, _ = docked
    _ready(dock)
    rebuilds: list[int] = []
    dock.slice_changed.connect(lambda: rebuilds.append(1))
    for value in (0.2, 0.3, 0.4, 0.5):
        dock.cell_spin.setValue(value)
    assert rebuilds == [], "nothing should have rebuilt while the value was still moving"
    dock.flush_debounce()
    assert len(rebuilds) == 1


def test_a_preparation_triggers_exactly_one_rebuild_not_several(docked):
    """Fix round 1, M2: `_refill_palette_combo` used to `clear()` and
    `addItems()` a combo wired to `refresh_slice()` via
    `currentTextChanged`, producing up to two spurious rebuilds on top of
    the one `_on_prepared()` itself asks for -- and a logged "unknown
    colormap ''" error from the first, empty-string transition."""
    dock, _ = docked
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    seen: list[int] = []
    errors: list[str] = []
    dock.slice_changed.connect(lambda: seen.append(1))
    dock.error.connect(errors.append)
    dock.transform_combo.setCurrentText("amp_abs")  # re-prepares on its own (spec 9.1)
    assert dock.engine.wait_for_preparation(20_000)
    assert len(seen) == 1, "one preparation must mean exactly one rebuild, not several"
    assert not any("colormap" in e for e in errors), errors


def test_a_resolution_change_touching_dz_is_still_one_rebuild(docked):
    """Fix round 1, M3: `_apply_resolution` called `setRange()` then
    `setValue()` on the slider, each of which can emit `valueChanged` --
    wired to `refresh_slice()` -- before calling `refresh_slice()` itself.
    Invisible to `test_a_resolution_change_is_debounced_into_one_rebuild`
    because a CELL-only change leaves the slider's own clamped value
    untouched; a `dz`/`z0`/`z1` change generally does not."""
    dock, _ = docked
    _ready(dock)
    rebuilds: list[int] = []
    dock.slice_changed.connect(lambda: rebuilds.append(1))
    dock.dz_spin.setValue(1.0)
    dock.z0_spin.setValue(0.0)
    dock.z1_spin.setValue(50.0)
    dock.flush_debounce()
    assert len(rebuilds) == 1


def test_an_error_during_refresh_clears_the_stale_slice_and_readout(docked):
    """Fix round 1, M4: `refresh_slice`'s exception path used to leave
    `_values`, `_window` and the readout describing the previous, good
    tick -- an out-of-range `z1` (past what a prepared line actually
    covers) raised `CoverageError` from inside `engine.slice_at()`, and
    the message bar's warning appeared beside a map and readout that both
    still claimed the OLD window was on screen."""
    dock, _ = docked
    _ready(dock)
    dock.slice_slider.setValue(5)
    assert dock.current_values() is not None
    old_readout = dock.readout.text()
    errors: list[str] = []
    changed: list[int] = []
    dock.error.connect(errors.append)
    dock.slice_changed.connect(lambda: changed.append(1))
    dock.z1_spin.setValue(200.0)  # past the line's own recorded window
    dock.flush_debounce()
    assert errors, "an out-of-range z1 must be reported"
    assert dock.current_values() is None
    assert dock.readout.text() != old_readout
    assert changed, "the map must be told to clear, not left showing the stale slice"
