"""The Slices dock's Source group, and its Position/Resolution/Display groups."""

from __future__ import annotations

import dataclasses
import gc
import threading
import time
from typing import Any

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import retime_ns
from nsgeo.render import PercentileClip, UnipolarClip, colormap_names
from nsgeo.slices import SliceWindow, plan_fill, plan_windows, window_depths_m, window_times_ns
from nsgeo.velocity import VelocityModel
from nsgeo.velocity_source import SourceFit, VelocitySource
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slice_export import ViewSettings, cube_record
from nsgeo_qgis.slices_engine import solve_key
from nsgeo_qgis.slices_plan import (
    DEFAULT_BUDGET_BYTES,
    MEASURING_STRETCH_INDICATOR,
    PREVIEW_INDICATOR,
    REFINE_REST_MS,
    REFINING_SLICE_INDICATOR,
    Resolution,
    SliceFinish,
    level_limit_problem,
    limit_windows,
    old_cube_note,
    smallest_safe_cell,
    transform_names,
)
from nsgeo_qgis.ui import folds
from nsgeo_qgis.ui.slices_dock import COVERAGE_TIP, CanvasDepthScroll, SlicesDock
from nsgeo_qgis.ui.warnings_panel import REFUSAL, Entry
from nsgeo_qgis.velocity_records import line_label
from plugin_testing import (
    REAL_DZT,
    LayoutProbe,
    connect_message_log,
    layout_width,
    needs_real_data,
    propagate_wheel,
    slow_jobs,
    synthetic_dzt,
    wheel_event,
)
from qgis.PyQt.QtCore import QCoreApplication, QEvent, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QAbstractSlider, QApplication, QMessageBox, QScrollArea
from tests.real_data import GRID2_LINES

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [{"step": "dewow", "params": {}, "enabled": True}]


TIME_ZERO_PRESET = [{"step": "time_zero", "params": {}, "enabled": True}]


@pytest.fixture
def docked(qgis_app, tmp_path):
    yield from _docked_with(tmp_path, PRESET)


@pytest.fixture
def docked_zeroed(qgis_app, tmp_path):
    """The same three lines, prepared with a preset that sets time zero (#97)."""
    yield from _docked_with(tmp_path, TIME_ZERO_PRESET)


@pytest.fixture
def docked_banded(qgis_app, tmp_path):
    """Time-zero preset on lines whose flat bands sit at rows 40, 40 and 41:
    two lines on the earlier zero, one a sample later (the GPS survey's case)."""
    yield from _docked_with(tmp_path, TIME_ZERO_PRESET, band_rows=(40, 40, 41))


def _banded_dzt(folder, name, band_row):
    import zlib

    from tests.synthetic import write_dzt

    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    data = (rng.normal(size=(512, 60)) * 1e4).astype(np.int32)  # quiet: the band is the break
    data[band_row : band_row + 4, :] = 5_000_000
    write_dzt(folder / name, data)
    return folder / name


def _docked_with(tmp_path, preset, band_rows=None):
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = [
        Line.open(
            synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
            if band_rows is None
            else _banded_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", band_rows[i]),
            GridPlacement("A", "y", 1.0 + i, 0.0, 1, f"L{i}"),
        )
        for i in range(3)
    ]
    session.add_lines(lines)
    session.site.presets["p"] = list(preset)
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
    # starts building a new one. The refine worker first: it is joined, so
    # no solve outlives the test that started it.
    dock.refiner.shutdown()
    dock.engine.wait_for_preparation(20_000)
    dock.engine.dispose()
    dock.deleteLater()


def test_the_source_combos_are_filled_from_the_site_not_from_literals(docked):
    dock, session = docked
    assert [dock.grid_combo.itemText(i) for i in range(dock.grid_combo.count())] == ["A"]
    assert "p" in [dock.preset_combo.itemText(i) for i in range(dock.preset_combo.count())]
    offered = dock.transform_combo.values()
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


def _spy_on_the_estimate(monkeypatch):
    """Record every `estimate_memory` call the dock makes, then delegate.

    The label shows whole MB, and this fixture's cube rounds to "1 MB"
    whatever the covered count is, so the label cannot tell a packed figure
    from a dense one. The arguments can."""
    import nsgeo_qgis.ui.slices_dock as dock_module

    real = dock_module.estimate_memory
    calls: list[tuple[int, int, int, int, str]] = []

    def spy(prepared_samples, n_cells, nz, n_covered, *, method):
        calls.append((prepared_samples, n_cells, nz, n_covered, method))
        return real(prepared_samples, n_cells, nz, n_covered, method=method)

    monkeypatch.setattr(dock_module, "estimate_memory", spy)
    return calls


def _covered_by_the_included_lines(dock, session):
    from nsgeo.slices import covered_cells

    frame = dock.engine.frame
    assert frame is not None
    coords = [session.line_for_key(k).trace_coords(session.site.frames) for k in dock._included]
    return covered_cells(frame, coords), frame


def test_the_included_label_counts_only_covered_cells(docked, monkeypatch):
    """Before preparing, the label's figure counts the cells the included
    lines fall in, not every cell of the frame (#113)."""
    dock, session = docked
    dock.engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    calls = _spy_on_the_estimate(monkeypatch)
    dock._update_included_label()
    covered, frame = _covered_by_the_included_lines(dock, session)
    assert 0 < covered < frame.n_cells
    assert calls and calls[0][3] == covered
    assert dock.included_label.text().startswith("3 of 3 included")


def test_the_included_label_counts_the_method_chosen(docked, monkeypatch):
    """#148: minimum curvature holds its plan beside a kriging preview, so the
    over-budget warning counts the method the Interpolation panel shows, and
    choosing another method counts again."""
    dock, _ = docked
    calls = _spy_on_the_estimate(monkeypatch)
    combo = dock.grid_finish.method_combo
    combo.setCurrentIndex(combo.findData("min_curvature"))
    assert calls and calls[-1][4] == "min_curvature"
    del calls[:]
    combo.setCurrentIndex(combo.findData("idw"))
    assert calls and calls[-1][4] == "idw"


def test_the_checkbox_cost_before_preparing_is_the_packed_figure(docked, monkeypatch):
    """While no lines are prepared the engine's own estimate counts no cells
    (it reads 1 MB), so the checkbox shows the before-preparing figure the
    included label uses, and the two agree (#113)."""
    dock, session = docked
    dock.engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    monkeypatch.setattr(dock.engine, "_lines", [])  # the unprepared window
    assert not dock.engine.is_prepared
    calls = _spy_on_the_estimate(monkeypatch)
    shown: list[int] = []
    import nsgeo_qgis.ui.slices_dock as dock_module

    real_format = dock_module.format_bytes
    monkeypatch.setattr(
        dock_module, "format_bytes", lambda n: (shown.append(int(n)), real_format(n))[1]
    )
    dock._update_included_label()
    covered, frame = _covered_by_the_included_lines(dock, session)
    nz = dock.engine.z.nz
    cube_bytes = nz * covered * 4 + covered * 4 + covered * 8
    assert covered < frame.n_cells
    assert all(c[3] == covered for c in calls)
    assert cube_bytes in shown, "the checkbox must be sized from the packed count"
    assert dock.resident_check.text() == f"Keep the volume in memory ({real_format(cube_bytes)})"


def test_the_checkbox_does_not_show_the_old_line_sets_figure_while_re_preparing(
    docked, monkeypatch
):
    """`set_included` refreshes the label while the old lines are still in the
    engine, then `prepare()` empties them. The checkbox must be refreshed
    after that, from the before-preparing estimate of the NEW line set, not
    left on the old set's `engine.estimate` until `_on_prepared` (#113)."""
    dock, session = docked
    dock.engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.is_prepared
    import nsgeo_qgis.ui.slices_dock as dock_module

    shown: list[int] = []
    real_format = dock_module.format_bytes
    monkeypatch.setattr(
        dock_module, "format_bytes", lambda n: (shown.append(int(n)), real_format(n))[1]
    )
    # Hold the engine unprepared once `set_source` has emptied it.
    real_set_source = dock.engine.set_source

    def set_source_and_stay_empty(choice):
        real_set_source(choice)
        dock.engine._lines = []

    monkeypatch.setattr(dock.engine, "set_source", set_source_and_stay_empty)
    old_cube = dock.engine.estimate.cube_bytes
    fewer = tuple(session.keys())[:-1]
    shown.clear()
    dock.set_included(fewer)
    assert not dock.engine.is_prepared
    covered, _frame = _covered_by_the_included_lines(dock, session)
    nz = dock.engine.z.nz
    expected = nz * covered * 4 + covered * 4 + covered * 8
    assert expected != old_cube, "the fixture must tell the old and new figures apart"
    assert shown[-1] == expected, "the last refresh must be the new line set's figure"
    assert dock.resident_check.text() == f"Keep the volume in memory ({real_format(expected)})"


def test_a_line_whose_position_cannot_be_computed_is_left_out_of_the_count(docked, monkeypatch):
    """Preparation skips a line whose trace positions cannot be computed (for
    example `traces_per_metre <= 0`); the estimate skips it too, instead of
    raising inside a slot where QGIS would swallow it (#113)."""
    from nsgeo.slices import covered_cells

    dock, session = docked
    dock.engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    keys = list(dock._included)
    bad = session.line_for_key(keys[0])

    real_coords = type(bad).trace_coords

    def maybe_boom(self, frames):  # Line is frozen, so patch the class
        if self is bad:
            raise ValueError("traces_per_metre must be positive")
        return real_coords(self, frames)

    monkeypatch.setattr(type(bad), "trace_coords", maybe_boom)
    calls = _spy_on_the_estimate(monkeypatch)
    dock._update_included_label()  # must not raise
    frame = dock.engine.frame
    others = [real_coords(session.line_for_key(k), session.site.frames) for k in keys[1:]]
    assert calls
    assert calls[0][3] == covered_cells(frame, others)
    assert covered_cells(frame, others) > 0


def test_the_keep_resident_checkbox_wires_to_the_engine_and_shows_its_cost(docked):
    """Final review, Important 3 / Ruling AN. `SliceEngine.set_always_
    resident` existed with no caller anywhere but tests -- the override
    spec 9.2 itself describes had no control anywhere in the dock. Placed
    in the Display group (this plugin has no settings infrastructure to
    put it in), carrying spec 9.2's own wording and the actual cost the
    toggle buys (`engine.estimate.cube_bytes`, not the total -- the
    prepared lines are already held in memory in EITHER mode)."""
    dock, _ = docked
    _ready(dock)
    assert dock.engine.mode == "streaming"
    assert not dock.resident_check.isChecked()
    # Spec 9.2's wording lives on the control, but split: the short form
    # on the face and the full sentence in the tooltip. A QCheckBox cannot
    # elide or wrap, so its text IS its minimum width -- the full wording
    # measured a 555 px floor, which a dock passes straight on to the main
    # window (see `test_the_dock_minimum_does_not_force_the_main_window_
    # to_grow`). The cost stays on the face, where spec 9.2 wants it.
    assert "faster dragging" in dock.resident_check.toolTip()
    assert "memory" in dock.resident_check.text()
    assert "MB" in dock.resident_check.text() or "GB" in dock.resident_check.text()
    assert dock.resident_check.minimumSizeHint().width() <= 360

    dock.resident_check.setChecked(True)
    assert dock.engine.mode == "resident"
    dock.resident_check.setChecked(False)
    assert dock.engine.mode == "streaming"


def test_the_included_label_warns_over_the_default_budget(docked, monkeypatch):
    """Final review, Important 3 / Ruling AN. Spec 9.1/7.4's "warns and
    requires confirmation above the budget rather than hard-caps" was
    entirely unimplemented before this -- the label reported "about N MB"
    and never compared it to anything. Warns, never blocks: spec 7.4 is
    explicit that an over-budget cube degrades to streaming rather than
    failing, so nothing about what actually happens changes here -- only
    what the label says about it."""
    import nsgeo_qgis.ui.slices_dock as dock_module

    dock, _ = docked
    monkeypatch.setattr(dock_module, "DEFAULT_BUDGET_BYTES", 1)
    dock._update_included_label()
    assert "over the default budget" in dock.included_label.text()

    monkeypatch.setattr(dock_module, "DEFAULT_BUDGET_BYTES", DEFAULT_BUDGET_BYTES)
    dock._update_included_label()
    assert "over the default budget" not in dock.included_label.text()


def test_choosing_a_preset_that_carries_a_transform_is_refused_visibly(docked):
    """Ruling 2, surfaced. The engine raises; the dock must turn that into
    something the user can read and act on, not let it escape a slot."""
    dock, session = docked
    session.site.presets["bad"] = [{"step": "amp_abs", "params": {}, "enabled": True}]
    session.presets_changed.emit()
    seen: list[str] = []
    dock.error.connect(seen.append)
    dock.preset_combo.setCurrentText("bad")  # re-preparing is what refuses it
    # Named as the Processing list shows it, where the user goes to remove it.
    assert any("Absolute value" in msg for msg in seen), seen
    assert "Absolute value" in dock.source_status.text()
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


def test_accepting_the_line_chooser_on_an_empty_grid_does_not_latch_the_seed_flag(
    qgis_app, tmp_path
):
    """Final review, empty-grid latch. `set_included` used to clear
    `_included_is_default` UNCONDITIONALLY, so accepting the line chooser
    while the selected grid is still empty (`keys == () == self._included`
    already, so `changed` is `False` and nothing else here would notice)
    permanently latched it `False` -- which disables `_sync_included`'s
    "still default" retry branch for that grid, the same branch `_seed_
    dz_z_defaults` depends on to seed `dz`/`z0`/`z1` once a line actually
    arrives (`plugin.py` builds this dock before any site exists, so
    "grid added, still empty" is the ordinary flow, not an edge case).
    With the flag latched, a line imported afterwards left `z0_spin`
    stuck at its generic construction-time default (0.0) instead of the
    header's own (negative) `position_ns` -- silently asking `plan_line`
    to cover a two-way time the recording never reached, raising
    `CoverageError` on every slice with no visible route back."""
    session = SiteSession()
    dock = SlicesDock(session)
    try:
        session.new_site(tmp_path)
        session.add_grid(GRID)
        assert dock.included_keys() == ()

        # The line chooser accepted on the still-empty grid: a no-op in
        # every OTHER respect (`keys == self._included == ()`), which is
        # exactly why the unconditional clear went unnoticed.
        dock.set_included(())

        path = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
        line = Line.open(path, GridPlacement("A", "y", 1.0, 0.0, 1, "L0"))
        session.add_lines([line])

        assert dock.included_keys() == tuple(session.keys()), (
            "a line imported after an empty-grid Choose... must still become the default"
        )
        header = session.line_for_key(session.keys()[0]).header
        assert dock.z0_spin.value() == pytest.approx(header.position_ns), (
            "_seed_dz_z_defaults must still run for this grid, not stay stuck at its "
            "construction-time default of 0.0"
        )
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
    dock.transform_combo.set_value("amp_abs")
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
    dock.transform_combo.set_value("amp_abs")  # a genuine change -- prepare() must run

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


def test_the_readout_slice_count_agrees_with_the_export_band_count(docked):
    """Final review, Minor 5. `_update_readout` used to pass `window.
    n_levels` into `plan_windows` -- and `window` comes from `current_
    window()`, whose `n_levels` `ZAxis.level_range` CLAMPS at either end
    of the axis (trap 3, the same one the test just above pins for the
    time range itself). `export_geotiff` plans its bands from the
    UNCLAMPED `thickness_step_levels()[0]` instead, so near the deep end
    the readout's own "N / TOTAL" recomputed a smaller, WRONG total on
    every tick -- three different totals across three adjacent slider
    positions, for a source `plan_windows`'s own docstring says has one
    band count by construction."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    header = session.line_for_key(session.keys()[0]).header
    dock.dz_spin.setValue(header.dt_ns)
    dock.z0_spin.setValue(header.position_ns)
    dock.z1_spin.setValue(header.position_ns + (header.n_samples - 1) * header.dt_ns)
    dock.flush_debounce()
    z = dock.engine.z

    thickness_levels, step_levels = 23, 11
    dock.thickness_spin.setValue(thickness_levels * z.dz_ns)
    dock.step_spin.setValue(step_levels * z.dz_ns)
    assert dock.thickness_step_levels() == (thickness_levels, step_levels), (
        "fixture must round-trip to the intended level counts, or this test cannot "
        "discriminate the fix from the bug"
    )

    true_bands = len(plan_windows(z, thickness_levels, step_levels))

    totals = set()
    # The last 25 slider positions are where `level_range` clamps
    # `window.n_levels` below `thickness_levels` -- exactly where the bug
    # lived.
    for slider in range(max(0, z.nz - 25), z.nz):
        dock.slice_slider.setValue(slider)
        text = dock.readout.text()
        total = int(text.split("/")[1].split("·")[0].strip())
        totals.add(total)
    assert totals == {true_bands}, (
        f"the readout's own band totals {sorted(totals)} must all equal the export's "
        f"true band count {true_bands} (`plan_windows(z, {thickness_levels}, {step_levels})`)"
    )


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


def _set_finish(dock, **fields):
    """Set the Interpolation panel the way a user does (its widgets, so
    `edited` fires), then apply the debounced redraw immediately."""
    panel = dock.grid_finish
    if "method" in fields:
        panel.method_combo.setCurrentIndex(panel.method_combo.findData(fields["method"]))
    if "max_distance_spacings" in fields:
        panel.max_distance_spin.setValue(fields["max_distance_spacings"])
    if "smooth_x_m" in fields:
        panel.smooth_x_spin.setValue(fields["smooth_x_m"])
    if "smooth_y_m" in fields:
        panel.smooth_y_spin.setValue(fields["smooth_y_m"])
    dock._finish_debounce.stop()
    dock._on_finish_timeout()


def _finished_by_the_core(dock, window, *, method, max_distance_m, search_radius_m=None):
    """What the drawn slice must equal, from the core pipeline alone."""
    from nsgeo.slices import finish_slice

    engine = dock.engine
    values, coverage = engine.slice_at(window)
    settings = dataclasses.replace(
        engine.finish_settings(dock.slice_finish()),
        method=method,
        max_distance_m=max_distance_m,
        search_radius_m=max(search_radius_m or 0.0, 2.0 * 0.5, 2.0 * max_distance_m),
    )
    weights = plan_fill(
        coverage > 0, engine.frame.cell, method, max_distance_m, settings.search_radius_m
    )
    return finish_slice(values, weights, engine.frame.cell, settings)


def test_the_interpolation_group_replaces_fill_radius(docked_two_grids):
    """Interpolation spec §8: no "Fill radius" row for This grid, an
    Interpolation group in its place, visible in This grid and at the
    defaults after a seed."""
    dock, _ = docked_two_grids
    _ready(dock)
    form = dock._resolution_form
    labels = [
        form.itemAt(row, form.ItemRole.LabelRole).widget().text() for row in range(form.rowCount())
    ]
    assert "Fill radius" not in labels
    assert not hasattr(dock, "radius_spacing_spin")
    assert not hasattr(dock, "grid_radius_spin")
    assert dock.grid_finish.title() == "Interpolation"
    assert not dock.grid_finish.isHidden()
    _set_finish(dock, method="idw", max_distance_spacings=1.5)
    _switch(dock, "B")
    assert dock.grid_finish.value() == SliceFinish()
    assert dock.slice_finish() == SliceFinish()


def test_the_max_distance_is_a_distance_and_survives_a_cell_size_change(docked):
    """The default max distance is a multiple of the line spacing -- a
    distance (interpolation spec §8). The cell conversion happens underneath
    (the weights are planned at the frame's own cell), so halving the cell
    does not move the distance, and the drawn slice is the core pipeline's at
    the new cell."""
    dock, session = docked
    _ready(dock)
    assert dock.grid_finish.max_distance_spin.value() == pytest.approx(0.75)
    assert dock.engine.finish_settings(dock.slice_finish()).max_distance_m == pytest.approx(0.375)
    dock.cell_spin.setValue(0.125)
    dock.flush_debounce()
    assert dock.engine.frame.cell == pytest.approx(0.125)
    assert dock.grid_finish.max_distance_spin.value() == pytest.approx(0.75)
    assert dock.engine.finish_settings(dock.slice_finish()).max_distance_m == pytest.approx(0.375)
    np.testing.assert_array_equal(
        dock.current_values(),
        _finished_by_the_core(dock, dock.current_window(), method="kriging", max_distance_m=0.375),
    )


def test_this_grid_sets_the_max_distance_in_line_spacings(docked):
    """#72: This grid's distance reads like Whole site's, in line spacings,
    with the metres it comes to shown beside the box."""
    dock, _ = docked
    _ready(dock)
    spin = dock.grid_finish.max_distance_spin
    assert spin.suffix() == " × line spacing"
    assert spin.value() == pytest.approx(0.75)
    assert spin.singleStep() == 0.25
    assert dock.grid_finish.max_distance_metres.text() == "= 0.375 m"


def test_the_metres_beside_the_max_distance_follow_the_box(docked):
    dock, _ = docked
    _ready(dock)
    dock.grid_finish.max_distance_spin.setValue(1.5)
    assert dock.grid_finish.max_distance_metres.text() == "= 0.75 m"


def test_max_distance_follows_a_line_spacing_edit(docked):
    """Review Focus 2: the distance is in spacings, so a spacing edit moves
    the metres and the drawn slice with no grid switch and no change to the
    box (0.75 spacings of 1.0 m is 0.75 m)."""
    dock, session = docked
    _ready(dock)
    dock.refresh_slice()
    before = dock.current_values().copy()
    session.replace_grid(dataclasses.replace(GRID, default_spacing=1.0))
    assert dock.grid_finish.max_distance_spin.value() == pytest.approx(0.75)
    assert dock.grid_finish.max_distance_metres.text() == "= 0.75 m"
    assert dock.engine.finish_settings(dock.slice_finish()).max_distance_m == pytest.approx(0.75)
    # The drawn slice follows too, with no other refresh: export reads the
    # finish live, so the map must not show the old distance.
    np.testing.assert_array_equal(
        dock.current_values(),
        _finished_by_the_core(
            dock, dock.current_window(), method="kriging", max_distance_m=0.75, search_radius_m=2.0
        ),
    )
    assert np.isfinite(dock.current_values()).sum() > np.isfinite(before).sum()


def test_a_line_spacing_of_zero_does_not_abort_the_rebuild(docked):
    """Only a hand-edited survey holds a spacing <= 0, and `SliceFinish.in_metres`
    refuses it with ValueError. `_finish_moved` reads that as nothing to compare,
    as it reads a missing source, so `rebuild_source` runs on to its site
    follow-ups instead of stopping in its own guard."""
    dock, session = docked
    _ready(dock)
    dock.refresh_slice()
    messages: list[str] = []
    disconnect = connect_message_log(lambda msg, tag, level: messages.append(msg))
    try:
        session.replace_grid(dataclasses.replace(GRID, default_spacing=0.0))
        assert dock._finish_moved() is False
    finally:
        disconnect()
    assert not [m for m in messages if "could not rebuild the slice source controls" in m]


def test_a_coverage_view_is_not_redrawn_on_every_session_signal(docked):
    """#72's redraw on a spacing edit compares the finish in metres with the
    one the last draw used. A coverage draw left that unrecorded, so after a
    finish edit every session signal redrew the coverage view."""
    dock, session = docked
    _ready(dock)
    dock.coverage_check.setChecked(True)
    _set_finish(dock, max_distance_spacings=1.5)
    drawn: list[None] = []
    dock.slice_changed.connect(lambda: drawn.append(None))
    for _ in range(3):
        session.presets_changed.emit()
    assert drawn == []


def test_a_seeded_finish_announces_nothing(docked_two_grids):
    """The seed is not an edit: the memory hangs on `edited`."""
    dock, session = docked_two_grids
    _ready(dock)
    _set_finish(dock, max_distance_spacings=1.5)
    seen: list[tuple[str, object]] = []
    dock.grid_finish.edited.connect(lambda field, value: seen.append((field, value)))
    dock.grid_combo.setCurrentText("B")
    assert dock.grid_finish.value() == SliceFinish()
    assert seen == []


def test_with_no_grid_the_max_distance_reads_blank(qgis_app, tmp_path):
    session = SiteSession()
    dock = SlicesDock(session)  # no survey open
    try:
        assert dock.grid_finish.max_distance_metres.text() == ""
        assert dock.view_settings().radius_m == 0.0
        session.new_site(tmp_path)  # open, but no grid yet
        assert dock.grid_finish.max_distance_metres.text() == ""
        assert dock.view_settings().radius_m == 0.0
    finally:
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.deleteLater()


def test_a_finish_edit_redraws_and_is_remembered_for_the_grid(docked_two_grids):
    dock, session = docked_two_grids
    _ready(dock)
    session.save()
    window = dock.current_window()
    dock.grid_finish.method_combo.setCurrentIndex(dock.grid_finish.method_combo.findData("idw"))
    assert dock._finish_debounce.isActive()
    dock._finish_debounce.stop()
    dock._on_finish_timeout()  # the debounce, flushed
    np.testing.assert_array_equal(
        dock.current_values(),
        dock.engine.finish(*dock.engine.slice_at(window), SliceFinish(method="idw")),
    )
    assert session.slice_resolution("A")["method"] == "idw"
    assert session.slice_resolution("B") == {}
    assert session.dirty


def test_a_finish_edit_redraws_through_its_own_debounce(docked):
    """The timer, not only the flush: an edit starts `_finish_debounce`, and
    its timeout alone redraws."""
    from plugin_testing import spin_until

    dock, _ = docked
    _ready(dock)
    drawn: list[None] = []
    dock.slice_changed.connect(lambda: drawn.append(None))
    dock.grid_finish.smooth_x_spin.setValue(0.5)
    assert drawn == [] and dock._finish_debounce.isActive()
    assert spin_until(lambda: bool(drawn), 2000)
    assert not dock._finish_debounce.isActive()


def test_seeding_a_grid_resets_the_panel_and_remembers_nothing(docked_two_grids):
    dock, session = docked_two_grids
    _settle_sources(dock, session)
    _set_finish(dock, method="idw", max_distance_spacings=1.5, smooth_x_m=0.4)
    session.save()
    assert not session.dirty
    _switch(dock, "B")
    assert dock.slice_finish() == SliceFinish()
    assert dock.grid_finish.max_distance_metres.text() == "= 0.375 m"  # B's spacing is 0.5 too
    assert session.slice_resolution("B") == {}
    assert not session.dirty


def test_a_remembered_finish_is_restored_on_a_grid_switch(docked_two_grids):
    dock, session = docked_two_grids
    _ready(dock)
    wanted = SliceFinish(method="idw", max_distance_spacings=1.5, smooth_x_m=0.4, smooth_y_m=0.2)
    _set_finish(dock, **dataclasses.asdict(wanted))
    _switch(dock, "B")
    assert dock.slice_finish() == SliceFinish()
    _switch(dock, "A")
    assert dock.slice_finish() == wanted
    assert dock.grid_finish.max_distance_metres.text() == "= 0.75 m"
    assert dock.current_values() is not None
    window = dock.current_window()
    np.testing.assert_array_equal(
        dock.current_values(), dock.engine.finish(*dock.engine.slice_at(window), wanted)
    )


@pytest.mark.parametrize("radius_spacings", [0.5, 1.5])
def test_a_0_2_0_remembered_radius_is_ignored(docked_two_grids, radius_spacings):
    """Review Focus 3: a 0.2.0 survey remembers `radius_spacings` for a
    grid (0.2.0 seeded 0.5; the max distance's default is 0.75, so either
    value tells ignoring it from mapping it). This build opens it on the
    new defaults, with no holes, and does not mark the survey dirty. Put
    into the record directly: `remember_slice_resolution`
    no longer takes that keyword."""
    dock, session = docked_two_grids
    _settle_sources(dock, session)
    _set_finish(dock, method="none")
    _switch(dock, "B")
    session._update_source("A", resolution={"radius_spacings": radius_spacings})
    session.save()
    assert not session.dirty
    _switch(dock, "A")
    assert dock.slice_finish() == SliceFinish()
    assert not session.dirty
    assert session.slice_resolution("A") == {"radius_spacings": radius_spacings}  # left as found
    # No holes: the default fills between the lines.
    window = dock.current_window()
    values, coverage = dock.engine.slice_at(window)
    assert np.isfinite(dock.current_values()).sum() > (coverage > 0).sum()


def test_saving_a_cube_records_the_finish_and_radius_m(docked):
    dock, _ = docked
    _ready(dock)
    _set_finish(dock, method="idw", max_distance_spacings=1.5, smooth_x_m=0.4, smooth_y_m=0.2)
    view = dock.view_settings()
    assert view.finish == SliceFinish("idw", 1.5, 0.4, 0.2)
    # What 0.2.0 reads as its fill radius (interpolation spec §8): spacings x spacing.
    assert view.radius_m == pytest.approx(0.75)
    # Under None nothing is filled, so 0.2.0 is told to fill nothing too: it
    # shows that cube unfilled, as this build does, whatever the distance box holds.
    _set_finish(dock, method="none")
    view = dock.view_settings()
    assert view.finish == SliceFinish("none", 1.5, 0.4, 0.2)
    assert view.radius_m == 0.0


@pytest.mark.parametrize("radius_m", [0.0, 0.25, 0.5, 0.75])
def test_restoring_a_0_2_0_cube_record_shows_the_defaults(docked, radius_m):
    """Review Focus 3: a 0.2.0 cube record's `view` has only the six 0.2.0
    keys, `radius_m` among them. It opens on the defaults, never mapping the
    old radius onto the new controls."""
    dock, session = docked
    _ready(dock)
    record = _save_cube(dock, session, "A__r", dock.view_settings())
    record["view"] = {
        key: record["view"][key]
        for key in ("thickness_ns", "step_ns", "radius_m", "palette", "stretch", "coverage")
    }
    record["view"]["radius_m"] = radius_m
    _set_finish(dock, method="none", max_distance_spacings=3.0, smooth_x_m=0.5)
    dock.cube_combo.setCurrentText("A__r")
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.slice_finish() == SliceFinish()


def test_restoring_a_cube_restores_the_finish_and_remembers_it(docked):
    dock, session = docked
    _ready(dock)
    wanted = SliceFinish("idw", 1.5, 0.4, 0.2)
    _set_finish(dock, **dataclasses.asdict(wanted))
    _save_cube(dock, session, "A__f", dock.view_settings())
    _set_finish(dock, method="none", max_distance_spacings=0.25, smooth_x_m=0.0, smooth_y_m=0.0)
    dock.cube_combo.setCurrentText("A__f")
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.slice_finish() == wanted
    assert dock.grid_finish.max_distance_metres.text() == "= 0.75 m"
    remembered = session.slice_resolution("A")
    assert {k: remembered[k] for k in dataclasses.asdict(wanted)} == dataclasses.asdict(wanted)


def test_a_cube_saved_before_a_spacing_edit_follows_the_new_spacing(docked):
    """A cube records its max distance in line spacings (and the metres only
    for 0.2.0's sake), so after a spacing edit it restores the same spacings
    and the metres follow the grid's spacing now."""
    dock, session = docked
    _ready(dock)
    _set_finish(dock, max_distance_spacings=1.0)
    _save_cube(dock, session, "A__s", dock.view_settings())
    session.replace_grid(dataclasses.replace(GRID, default_spacing=1.0))
    dock.restore_cube("A__s")
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.grid_finish.max_distance_spin.value() == pytest.approx(1.0)
    assert dock.grid_finish.max_distance_metres.text() == "= 1 m"


def test_a_grid_starts_from_square_a_0_2_m_cell_and_the_default_interpolation(docked):
    """#81: what a grid's slices start from before anything is remembered
    for it. `GRID`'s spacing is 0.5 m, where 0.2 m is under half the
    spacing, so nothing is clamped here."""
    dock, _ = docked
    assert dock.transform_combo.value() == "amp_square"
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.choice.transform == "amp_square"  # what was prepared, not just shown
    assert dock.cell_spin.value() == pytest.approx(0.2)
    assert dock.slice_finish() == SliceFinish()  # kriging out to 0.75 x spacing, no smoothing


@pytest.mark.parametrize(("spacing", "cell"), [(0.25, 0.125), (1.0, 0.2)])
def test_the_default_cell_is_capped_at_half_the_spacing_and_never_grows_with_it(
    qgis_app, tmp_path, spacing, cell
):
    """#81: a fixed 0.2 m, capped at spec 4's half the line spacing -- so
    0.125 m on a 0.25 m-spaced grid, and still 0.2 m (not 0.4) at 1 m. The
    max distance is always half the grid's own spacing."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", spacing))
    dock = SlicesDock(session)
    try:
        assert dock.cell_spin.value() == pytest.approx(cell)
        assert dock.slice_finish() == SliceFinish()
    finally:
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.deleteLater()


def test_filling_reaches_between_the_lines_and_none_does_not(docked):
    """Spec 6.4: at realistic spacing about 80% of cells are empty, so the
    fill is most of the picture rather than a nicety."""
    dock, _ = docked
    _ready(dock)
    _set_finish(dock, method="none")
    unfilled = np.isfinite(dock.current_values()).sum()
    _set_finish(dock, method="idw", max_distance_spacings=2.0)  # 1 m on a 0.5 m spacing
    filled = np.isfinite(dock.current_values()).sum()
    assert filled > unfilled


def test_the_shared_stretch_follows_a_finish_change(docked):
    """The shared limit is measured over the finished slices, so a finish
    that changes them (smoothing flattens peaks) changes the limit: the cache
    is keyed on the finish in metres, not served stale."""
    dock, _ = docked
    _ready(dock)
    first = dock.display_limit()
    assert first > 0.0
    assert dock.display_limit() == first  # cached, unchanged
    _set_finish(dock, smooth_x_m=1.0, smooth_y_m=1.0)
    smoothed = dock.display_limit()
    assert smoothed != pytest.approx(first, rel=1e-6)
    clip = dock.engine.output_unipolar
    from nsgeo.render import PercentileClip, UnipolarClip

    expected = dock.engine.shared_limit(
        dock.current_window().n_levels,
        UnipolarClip() if clip else PercentileClip(),
        dock.slice_finish(),
    )
    assert smoothed == pytest.approx(expected)
    _set_finish(dock, smooth_x_m=0.0, smooth_y_m=0.0)
    assert dock.display_limit() == pytest.approx(first)


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


def test_the_coverage_toggle_pins_ruling_ab_in_this_slice_mode_too(docked):
    """Cheap cluster (final review): the test above only ever exercises
    the DEFAULT stretch ("shared across the cube") -- `display_limit()`
    checks `coverage_check` first, before branching on the stretch combo
    at all, but nothing pinned that the coverage branch actually wins
    over "this slice" too."""
    dock, _ = docked
    _ready(dock)
    dock.stretch_combo.setCurrentText("this slice")
    dock.coverage_check.setChecked(True)
    coverage = dock.current_values()
    assert np.nanmax(coverage) >= 1.0
    limit = dock.display_limit()
    assert limit == pytest.approx(float(np.nanmax(coverage)))
    assert dock.display_unipolar() is True


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
    `dewow`) carries no transform, and `transform_combo` then started on
    "none" (#81 moved it to amp_square) -- so without explicitly choosing
    a transform here, `engine.output_unipolar` was False right after
    `_ready()`, and the very first assertion below (expecting the UNIPOLAR
    list) failed against correct code. The name says "for a transformed
    source"; the test chooses one itself rather than lean on a default."""
    dock, _ = docked
    _ready(dock)
    dock.transform_combo.set_value("amp_abs")  # re-prepares on its own (spec 9.1)
    assert dock.engine.wait_for_preparation(20_000)
    offered = [dock.palette_combo.itemText(i) for i in range(dock.palette_combo.count())]
    assert set(offered) == set(colormap_names(unipolar=True))
    assert "seismic" not in offered

    dock.transform_combo.set_value("none")  # re-prepares on its own (spec 9.1)
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
    dock.transform_combo.set_value("amp_abs")  # re-prepares on its own (spec 9.1)
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
    assert dock.legend_label.text() != ""
    errors: list[str] = []
    changed: list[int] = []
    dock.error.connect(errors.append)
    dock.slice_changed.connect(lambda: changed.append(1))
    dock.z1_spin.setValue(200.0)  # past the line's own recorded window
    dock.flush_debounce()
    assert errors, "an out-of-range z1 must be reported"
    assert dock.current_values() is None
    assert dock.readout.text() != old_readout
    # Cheap cluster (final review): `legend_label` too -- it used to keep
    # the previous tick's number standing beside "error: ...".
    assert dock.legend_label.text() == ""
    assert changed, "the map must be told to clear, not left showing the stale slice"


def test_deleting_a_contributing_line_does_not_blank_a_still_valid_slice(docked):
    """Final review, Minor 6. A contributing line can be deleted while a source
    stays prepared, and the cube's own arrays are still entirely correct. The
    grid's velocity (`grid_depth_velocity`) is the grid's own velocity, else
    the first line left in survey order, so removing the first line moves the
    label to the new first line rather than raising. A `KeyError` escaping
    through `_update_readout` into `refresh_slice`'s broad `except` used to
    report `error: '<key>'` and clear the map for a still-good slice."""
    dock, session = docked
    _ready(dock)
    dock.slice_slider.setValue(5)
    assert dock.current_values() is not None
    removed_key = dock.engine.provenance().line_keys[0]

    errors: list[str] = []
    dock.error.connect(errors.append)
    session.remove_line(removed_key)  # emits lines_changed; does not itself refresh the slice

    dock.slice_slider.setValue(6)  # the next refresh_slice() is where the KeyError used to surface

    assert dock.current_values() is not None, "a still-valid slice must not be blanked"
    assert not dock.readout.text().startswith("error:"), dock.readout.text()
    assert not any(removed_key in e for e in errors), errors
    # The grid's velocity does not hang on the removed line: the label stays,
    # and names the grid's new first line.
    new_first = session.keys_on_grid("A")[0]
    epsr = session.line_for_key(new_first).header.epsr
    assert dock.velocity_label.text().endswith(
        f"(header ε {epsr:g}, {line_label(session.line_for_key(new_first))})"
    )


def _override_every_line(session, velocity=0.12):
    """The hazard input (spec 12): the grid's first line in survey order, and
    the first prepared line, each carry an override unlike the grid's velocity."""
    for key in session.keys():  # noqa: SIM118 -- SiteSession.keys(), not a dict
        session.set_line_velocity(key, VelocityModel.constant(velocity))


def _two_fit_record(session):
    members = [
        SourceFit(
            key,
            "fit-1",
            "2026-11-12T00:00:00+00:00",
            line_label(session.line_for_key(key)),
            20.0,
            0.09,
            0.002,
            0.0,
        )
        for key in session.keys_on_grid("A")[:2]
    ]
    return VelocitySource.from_fits(members, applied_at=None)


def test_slice_label_and_readout_use_the_grids_velocity(docked, message_log):
    dock, session = docked
    session.set_grid_velocity("A", VelocityModel.constant(0.09))
    _override_every_line(session)
    _ready(dock)
    dock.thickness_spin.setValue(4.0)
    dock.slice_slider.setValue(10)
    assert dock.velocity_label.text() == "v = 0.090 m/ns (Grid A)"
    window = dock.current_window()
    lo_m, hi_m = window_depths_m(dock.engine.z, window, VelocityModel.constant(0.09))
    text = dock.readout.text()
    assert f"{lo_m:.2f}" in text and f"{hi_m:.2f}" in text
    lo_o, hi_o = window_depths_m(dock.engine.z, window, VelocityModel.constant(0.12))
    assert f"{lo_o:.2f}–{hi_o:.2f} m" not in text
    assert message_log == []


def test_slice_label_names_the_grids_record(docked, message_log):
    dock, session = docked
    session.apply_grid_velocity("A", VelocityModel.constant(0.09), _two_fit_record(session))
    _override_every_line(session)
    _ready(dock)
    dock.slice_slider.setValue(10)
    assert dock.velocity_label.text() == "v = 0.090 m/ns (Grid A, average of 2 fits)"
    assert message_log == []


def test_a_live_grid_apply_relabels_the_prepared_slice(docked, message_log):
    """Final review, Important: `grids_changed` reached `rebuild_source`, which
    only refreshed a slice whose finish had moved, so a grid Apply left the
    label and the readout's metres standing while Export GeoTIFF (through
    `_resolved_velocity`) already used the new velocity."""
    dock, session = docked
    session.set_grid_velocity("A", VelocityModel.constant(0.09))
    _ready(dock)
    dock.thickness_spin.setValue(4.0)
    dock.slice_slider.setValue(10)
    assert dock.velocity_label.text() == "v = 0.090 m/ns (Grid A)"
    window = dock.current_window()

    def metres(v):
        lo, hi = window_depths_m(dock.engine.z, window, VelocityModel.constant(v))
        return f"{lo:.2f}-{hi:.2f} m"

    assert metres(0.09) in dock.readout.text()

    session.apply_grid_velocity("A", VelocityModel.constant(0.12), None)
    assert dock.velocity_label.text() == "v = 0.120 m/ns (Grid A)"
    assert metres(0.12) in dock.readout.text()
    assert metres(0.09) not in dock.readout.text()

    session.apply_grid_velocity("A", VelocityModel.constant(0.12), _two_fit_record(session))
    assert dock.velocity_label.text() == "v = 0.120 m/ns (Grid A, average of 2 fits)"
    assert message_log == []


def test_a_slice_survives_losing_every_line_of_a_grid_with_no_velocity(docked, message_log):
    """The `KeyError` guards in `_resolved_velocity` and `_update_velocity_label`:
    a grid with no velocity and no line has nothing to resolve, and that must
    neither blank a still-valid slice nor leave an old label standing."""
    dock, session = docked
    _ready(dock)
    dock.slice_slider.setValue(5)
    assert dock.current_values() is not None
    for key in list(session.keys_on_grid("A")):
        session.remove_line(key)
    dock.slice_slider.setValue(6)
    assert dock.current_values() is not None
    assert not dock.readout.text().startswith("error:"), dock.readout.text()
    assert "error:" not in dock.readout.text()
    assert dock.velocity_label.text() == ""
    # `_resolved_velocity` returns first on this path, so the label's own guard
    # is reached only when it is handed a velocity the grid can no longer name.
    dock.velocity_label.setText("stale")
    dock._update_velocity_label("A", VelocityModel.constant(0.1))
    assert dock.velocity_label.text() == ""
    assert message_log == []


def test_slice_label_without_a_grid_velocity_names_the_header_and_line(docked, message_log):
    dock, session = docked
    _override_every_line(session)
    _ready(dock)
    dock.slice_slider.setValue(10)
    first = session.line_for_key(session.keys_on_grid("A")[0])
    v = session.grid_depth_velocity("A").surface_velocity
    assert dock.velocity_label.text() == (
        f"v = {v:.3f} m/ns (header ε {first.header.epsr:g}, {line_label(first)})"
    )
    assert v != pytest.approx(0.12)
    assert message_log == []


def test_grid_velocity_label_covers_each_tier(docked):
    from nsgeo_qgis.ui.profile_dock import grid_velocity_label

    _, session = docked
    first = session.line_for_key(session.keys_on_grid("A")[0])
    assert (
        grid_velocity_label(session, "A") == f"header ε {first.header.epsr:g}, {line_label(first)}"
    )
    session.set_grid_velocity("A", VelocityModel.constant(0.09))
    assert grid_velocity_label(session, "A") == "Grid A"
    session.apply_grid_velocity("A", VelocityModel.constant(0.09), _two_fit_record(session))
    assert grid_velocity_label(session, "A") == "Grid A, average of 2 fits"
    one = VelocitySource.from_fits(_two_fit_record(session).members[:1], applied_at=None)
    session.apply_grid_velocity("A", VelocityModel.constant(0.09), one)
    assert grid_velocity_label(session, "A") == f"Grid A, fit on {one.members[0].line_label}"


def test_moving_the_slider_announces_the_window_it_averaged(docked):
    dock, _ = docked
    _ready(dock)
    seen: list[tuple[float, float]] = []
    dock.window_changed.connect(lambda lo, hi: seen.append((lo, hi)))
    dock.thickness_spin.setValue(4.0)
    dock.slice_slider.setValue(12)
    assert seen
    lo, hi = seen[-1]
    window = dock.current_window()
    assert (lo, hi) == pytest.approx(window_times_ns(dock.engine.z, window))


def test_step_slice_moves_by_the_step_not_by_one_level(docked):
    """Spec 6.6: thickness and step answer different questions. Stepping
    by one level would make shift+scroll take dozens of turns to cross a
    slice at native dz."""
    dock, _ = docked
    _ready(dock)
    dock.thickness_spin.setValue(5.0)
    dock.step_spin.setValue(2.5)
    start = dock.slice_slider.value()
    dock.step_slice(1)
    moved = dock.slice_slider.value() - start
    assert moved == round(2.5 / dock.engine.z.dz_ns)
    assert moved > 1


class _WheelStub:
    """The minimal `QWheelEvent`-shaped surface `eventFilter` reads.

    Not a real `QWheelEvent`: its constructor signature differs between
    Qt 5 and Qt 6 (the same reason `depth_scroll_steps` itself is a plain
    function tested without one), but `eventFilter`'s own body only ever
    calls `.type()`, `.modifiers()` and `.angleDelta().y()` on the event
    it is handed -- so a stub exposing exactly those three is a Qt-version-
    independent way to exercise the filter directly, the same way
    `depth_scroll_steps`'s own pure test needs no event at all.
    """

    def __init__(self, angle_delta_y: int, shift: bool) -> None:
        self._angle_delta_y = angle_delta_y
        self._shift = shift

    def type(self) -> QEvent.Type:
        return QEvent.Type.Wheel

    def modifiers(self) -> Qt.KeyboardModifier:
        return Qt.KeyboardModifier.ShiftModifier if self._shift else Qt.KeyboardModifier.NoModifier

    def angleDelta(self) -> Any:
        class _Delta:
            def __init__(self, y: int) -> None:
                self._y = y

            def y(self) -> int:
                return self._y

        return _Delta(self._angle_delta_y)


class _NonWheelStub:
    def type(self) -> QEvent.Type:
        return QEvent.Type.MouseMove


def test_canvas_depth_scroll_consumes_shift_wheel_and_leaves_plain_scroll_alone(fake_iface, docked):
    """Minor 3 (Task 5 review): `depth_scroll_steps` was pinned as a pure
    function, but nothing pinned `CanvasDepthScroll.eventFilter` itself --
    the thing that actually decides whether an event is consumed. A
    mutant that returns `True` before the `delta == 0` check would take
    the map's zoom away entirely (every wheel event on the canvas
    swallowed, shift or not) and would survive the whole suite without
    this test: `depth_scroll_steps`'s own test never touches the filter,
    and nothing else calls `eventFilter` at all.
    """
    dock, _ = docked
    _ready(dock)
    filt = CanvasDepthScroll(fake_iface.mapCanvas(), dock)
    try:
        start = dock.slice_slider.value()

        consumed = filt.eventFilter(None, _WheelStub(-120, shift=True))
        assert consumed is True
        assert dock.slice_slider.value() > start, "shift+wheel must actually step the slice"

        moved_to = dock.slice_slider.value()
        consumed = filt.eventFilter(None, _WheelStub(-120, shift=False))
        assert consumed is False, "plain scroll must stay the map's own zoom, not be consumed"
        assert dock.slice_slider.value() == moved_to, "plain scroll must not move the slice"

        consumed = filt.eventFilter(None, _NonWheelStub())
        assert consumed is False
        assert dock.slice_slider.value() == moved_to
    finally:
        filt.dispose()


def test_canvas_depth_scroll_moves_one_step_per_notch_of_a_hi_res_wheel(fake_iface, docked):
    """#109: one notch of the user's wheel arrives as two events of 60.
    The depth moves one Step for the notch, not one per event, and the
    first half is still consumed so that the map does not zoom by half a
    notch in between."""
    dock, _ = docked
    _ready(dock)
    filt = CanvasDepthScroll(fake_iface.mapCanvas(), dock)
    try:
        start = dock.slice_slider.value()
        step_levels = dock.thickness_step_levels()[1]

        assert filt.eventFilter(None, _WheelStub(-60, shift=True)) is True
        assert dock.slice_slider.value() == start, "half a notch must not move the depth"
        assert filt.eventFilter(None, _WheelStub(-60, shift=True)) is True
        assert dock.slice_slider.value() == start + step_levels
    finally:
        filt.dispose()


# ---- Task 7 fix round 1: restore_cube, driven through the real widgets ----


def _save_cube(dock, session, cube_id: str, view: ViewSettings, time_base: str = "radar") -> dict:
    """Build a record from the dock's own, already-prepared engine and
    drop it straight into `session.site.cubes`, then refresh the combo --
    no `.npz` needs to exist on disk for `restore_cube` to read the
    record back, since `recipe_from_record` never touches `array`."""
    record = cube_record(
        session,
        dock.engine.choice,
        dock.engine.frame,
        dock.engine.z,
        view,
        session.root / "slices" / f"{cube_id}.npz",
        line_keys=dock.engine.provenance().line_keys,
        time_base=time_base,
    )
    session.site.cubes[cube_id] = record
    dock.refresh_cube_combo()
    return record


def test_restore_cube_brings_every_control_back_ruling_al(docked):
    """Ruling AL: the layer neither `recipe_from_record`'s own tests nor
    the identical-slice test can see -- the widgets themselves.

    Also the regression test for Ruling AJ: `dz=0.2165, z0=2.0, z1
    (requested)=30.0` puts `z.t_end_ns` (`t0 + (nz-1)*dz`, what the
    record's `t1_ns` actually is) at 29.9285 -- a genuine 4th decimal
    digit that `z1_spin.setDecimals(3)` used to floor to 29.928 the
    moment `restore_cube` called `setValue` on it, silently narrowing the
    slider range and losing the deepest slice on the majority of
    plausible GSSI headers (measured at 43 of 90 swept combinations)."""
    dock, session = docked
    assert dock.engine.wait_for_preparation(20_000)
    dock.cell_spin.setValue(0.25)
    dock.dz_spin.setValue(0.2165)
    dock.z0_spin.setValue(2.0)
    dock.z1_spin.setValue(30.0)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    full = dock.included_keys()
    view = ViewSettings(
        thickness_ns=4.0,
        step_ns=2.0,
        radius_m=0.75,  # max_distance_spacings x this grid's spacing
        palette=dock.palette_combo.currentText(),
        stretch="this slice",
        coverage=True,
        method="idw",
        max_distance_spacings=1.5,
        smooth_x_m=0.4,
        smooth_y_m=0.2,
    )
    record = _save_cube(dock, session, "A__test", view)
    assert record["z"]["t1_ns"] == pytest.approx(29.9285)
    assert round(record["z"]["t1_ns"], 3) != record["z"]["t1_ns"], (
        "fixture must exercise a genuine 4th decimal digit, or this test cannot "
        "distinguish the fix from the bug"
    )

    # Perturb every restorable control so the restore is not a no-op:
    # a second preset, another transform (the cube was saved on #81's
    # default, amp_square), a narrower inclusion set, different
    # Resolution/view values.
    assert record["transform"] == "amp_square"
    session.site.presets["q"] = list(PRESET)
    session.presets_changed.emit()
    dock.preset_combo.setCurrentText("q")
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.transform_combo.set_value("none")
    assert dock.engine.wait_for_preparation(20_000)
    dock.set_included(full[:1])
    assert dock.engine.wait_for_preparation(20_000)
    dock.cell_spin.setValue(0.5)
    dock.z1_spin.setValue(10.0)
    dock.flush_debounce()
    dock.apply_view(
        ViewSettings(
            thickness_ns=1.0,
            step_ns=1.0,
            radius_m=0.0,
            palette=dock.palette_combo.currentText(),
            stretch="shared across the cube",
            coverage=False,
        ),
        spacing_m=GRID.default_spacing,
    )
    assert dock.cube_combo.currentText() == "(unsaved)", "perturbing must drop the claim"

    dock.restore_cube("A__test")
    assert dock.engine.wait_for_preparation(20_000)

    assert dock.grid_combo.currentText() == "A"
    assert dock.preset_combo.currentText() == "p"
    assert dock.transform_combo.value() == "amp_square"
    assert dock.included_keys() == full
    assert dock.z1_spin.value() == record["z"]["t1_ns"]  # Ruling AJ
    assert dock.z0_spin.value() == record["z"]["t0_ns"]
    assert dock.cell_spin.value() == record["cell"]
    # A record without colours (#180) leaves them as they were: the default.
    assert dock.view_settings() == dataclasses.replace(view, colours="nsgeo")


def test_restore_cube_refuses_a_missing_grid(docked):
    """Ruling AK: `grid_combo` is non-editable, so `setCurrentText` on a
    grid id no longer offered is a silent Qt no-op -- refused loudly
    instead, and the previous (unrelated) selection must survive intact."""
    dock, session = docked
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    record = _save_cube(
        dock,
        session,
        "A__gone",
        ViewSettings(1.0, 1.0, 0.0, "amp_black_high", "this slice", False),
    )
    record["grid_id"] = "does-not-exist"

    seen: list[str] = []
    dock.error.connect(seen.append)
    before = dock.grid_combo.currentText()
    # Driven through the combo itself, not a direct `restore_cube` call --
    # `_on_cube_changed` sets `cube_combo` to "A__gone" (synchronously
    # firing `restore_cube`) before this call even returns, so the
    # "(unsaved)" assertion below is testing the except handler's own
    # reset, not merely a value the combo already happened to hold.
    dock.cube_combo.setCurrentText("A__gone")

    assert any("grid" in m and "does-not-exist" in m for m in seen), seen
    assert "grid" in dock.source_status.text() and "does-not-exist" in dock.source_status.text()
    assert dock.grid_combo.currentText() == before, "a refusal must not partially restore"
    assert dock.cube_combo.currentText() == "(unsaved)"


def test_restore_cube_refuses_a_missing_preset(docked):
    dock, session = docked
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    record = _save_cube(
        dock,
        session,
        "A__gone",
        ViewSettings(1.0, 1.0, 0.0, "amp_black_high", "this slice", False),
    )
    record["preset"] = "does-not-exist"

    seen: list[str] = []
    dock.error.connect(seen.append)
    before = dock.preset_combo.currentText()
    dock.cube_combo.setCurrentText("A__gone")

    assert any("preset" in m and "does-not-exist" in m for m in seen), seen
    assert dock.preset_combo.currentText() == before
    assert dock.cube_combo.currentText() == "(unsaved)"


def test_restore_cube_refuses_a_missing_transform(docked):
    dock, session = docked
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    record = _save_cube(
        dock,
        session,
        "A__gone",
        ViewSettings(1.0, 1.0, 0.0, "amp_black_high", "this slice", False),
    )
    record["transform"] = "does-not-exist"

    seen: list[str] = []
    dock.error.connect(seen.append)
    before = dock.transform_combo.currentText()
    dock.cube_combo.setCurrentText("A__gone")

    assert any("transform" in m and "does-not-exist" in m for m in seen), seen
    assert dock.transform_combo.currentText() == before
    assert dock.cube_combo.currentText() == "(unsaved)"


def test_restoring_the_same_cube_after_a_no_op_prepare_does_not_leave_a_stale_palette(docked):
    """Minor (fix round 1): `prepare()`'s own no-op guard skips dispatch
    -- and therefore skips `_on_prepared` -- when the restored choice
    already equals `engine.choice` and the preset's steps still match, a
    state `restore_cube` itself can produce (restore, touch only
    something Resolution-shaped, reselect the SAME cube). Without
    clearing `_pending_palette` right there, it would sit stashed until
    some LATER, unrelated preparation applied it."""
    dock, session = docked
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    _save_cube(
        dock, session, "A__test", ViewSettings(1.0, 1.0, 0.0, "amp_black_high", "this slice", False)
    )

    dock.restore_cube("A__test")
    assert dock.engine.wait_for_preparation(20_000)
    assert dock._pending_palette is None  # consumed by the real _on_prepared

    # Reselecting the identical cube: `prepare()` is a no-op (same choice,
    # same steps), so no task is ever dispatched and `_on_prepared` never
    # runs -- the stash must be cleared here instead.
    dock.restore_cube("A__test")
    assert not dock.engine.is_running
    assert dock._pending_palette is None


@needs_real_data
def test_the_seeded_z_range_survives_a_preset_that_crops_the_sample_axis(qgis_app, tmp_path):
    """Regression, M11 walkthrough: a preset that crops rows off the FRONT
    of the radargram leaves every prepared line starting LATER than its own
    header says, and the dock seeded `z0`/`z1` from that raw header.

    On this repo's own real files `time_zero` drops 49 of 512 rows, so a
    prepared line spanned -0.476..99.561 ns (on the radar clock this was
    found on; since #97 the same line reads 0 to about 100 ns, measured from its
    first break) while the seeded cube asked for -11.086..99.546 -- and the
    first slice raised, verbatim:

        line 'FILE__001.DZT' spans -0.476..99.561 ns, which does not cover
        the cube's -11.086..99.546 ns; shrink the z range or exclude the line

    `time_zero` first is the ordinary preset an operator builds, not an
    edge case. The pre-existing real-data engine test dodged precisely this
    hazard -- "No `time_zero`: it crops rows off the front of the
    radargram, which would shrink the line's own t0_ns below the header's
    raw `position_ns` this test seeds `z0` from directly" -- which is why a
    green suite shipped a default that cannot slice.
    """
    session = SiteSession()
    session.new_site(tmp_path)
    grid = Grid("A", (0.0, 0.0), 0.0, 3.0, 12.0, "EPSG:32616", 0.5)
    session.add_grid(grid)
    lines = [
        Line.open(REAL_DZT[i], GridPlacement("A", "y", 0.5 + i * 0.5, 0.0, 1, REAL_DZT[i].stem))
        for i in range(4)
    ]
    session.add_lines(lines)
    session.site.presets["p"] = [
        {"step": "time_zero", "params": {}, "enabled": True},
        {"step": "dewow", "params": {}, "enabled": True},
    ]
    session.presets_changed.emit()

    dock = SlicesDock(session)
    errors: list[str] = []
    dock.error.connect(errors.append)
    try:
        assert dock.engine.wait_for_preparation(60_000)

        header = lines[0].header
        prepared = dock.engine.prepared_z_bounds()
        assert prepared is not None
        # The hazard is real on this data, and this test would notice if it
        # stopped being real: the crop must actually move the start.
        assert prepared[0] > header.position_ns + 1.0, (prepared, header.position_ns)

        # The fix: the seeded range lies inside what every prepared line
        # covers, so `plan_line` can bin it.
        assert dock.z0_spin.value() >= prepared[0]
        assert dock.z1_spin.value() <= prepared[1]

        # ... and the slice that used to raise now actually renders.
        assert dock.current_values() is not None
        assert not [m for m in errors if "does not cover" in m], errors
    finally:
        dock.engine.wait_for_preparation(60_000)
        dock.engine.dispose()
        dock.deleteLater()


def test_prepared_z_bounds_is_the_intersection_not_the_union(qgis_app, tmp_path):
    """Three lines whose time-zero lands on a different sample each -- the
    ordinary consequence of antenna coupling changing across a survey, and
    what `time_zero(mode="first_break")` is for. Each starts at 0 ns, but
    they END at three different times (each line's first break is cropped
    off its front), so the shared range is the earliest end.

    This repo's ten real DZT files are byte-identical in the sample axis
    (all -11.086..99.561 ns, 512 samples, and all cropped to exactly 463 by
    `first_break`), so on real data the union and the intersection of their
    coverage are the SAME two numbers and no real-data test can tell a
    correct `prepared_z_bounds` from one that takes `min`/`max` the wrong
    way round. Hence synthetic lines built to disagree.

    Pinned behaviourally rather than by recomputing the same `min`/`max`
    the method itself uses: the bounds must be plannable for EVERY line,
    and tight -- one `dz` wider at either end must break at least one line.
    """
    from nsgeo.slices import CoverageError, ZAxis, plan_line
    from tests.synthetic import write_dzt

    raw = tmp_path / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    # The flat band drives `first_break`; putting it at a different row in
    # each line makes each crop a different number of samples, so the three
    # prepared lines genuinely start at three different two-way times.
    for i, (band, range_ns) in enumerate(((40, 110.864), (70, 104.0), (100, 98.0))):
        data = (rng.normal(size=(512, 40)) * 1e6).astype(np.int32)
        data[band : band + 4, :] = 5_000_000
        write_dzt(raw / f"FILE__00{i + 1}.DZT", data, range_ns=range_ns)

    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    session.add_lines(
        [
            Line.open(
                raw / f"FILE__00{i + 1}.DZT",
                GridPlacement("A", "y", 1.0 + i, 0.0, 1, f"L{i}"),
            )
            for i in range(3)
        ]
    )
    session.site.presets["p"] = [{"step": "time_zero", "params": {}, "enabled": True}]
    session.presets_changed.emit()

    dock = SlicesDock(session)
    try:
        assert dock.engine.wait_for_preparation(60_000)
        prepared = list(dock.engine.prepared_lines())
        starts = {round(line.t0_ns, 6) for line in prepared}
        ends = {round(line.t0_ns + (line.data.shape[0] - 1) * line.dt_ns, 6) for line in prepared}
        # Every line reads 0 at its own first break (#97), so the starts
        # agree; what differs is where each line's zero sits on the radar
        # clock. Without three different zeros the test could pass on lines
        # that happen to agree, which is exactly how the real files hid it.
        assert starts == {0.0}, starts
        assert len({round(line.zero_ns, 6) for line in prepared}) == 3
        assert len(ends) == 3, ends

        bounds = dock.engine.prepared_z_bounds()
        assert bounds is not None
        low, high = bounds
        dz = max(line.dt_ns for line in prepared)

        # Plannable for every line: a union would hand back a range that
        # the latest-starting (or earliest-ending) line cannot cover.
        axis = ZAxis.from_range(low, high, dz)
        for line in prepared:
            plan_line(line, dock.engine.frame, axis)

        # ... and tight at both ends, so a needlessly timid range fails too.
        for wider in (
            ZAxis.from_range(low - 2 * dz, high, dz),
            ZAxis.from_range(low, high + 2 * dz, dz),
        ):
            with pytest.raises(CoverageError):
                for line in prepared:
                    plan_line(line, dock.engine.frame, wider)
    finally:
        dock.engine.wait_for_preparation(60_000)
        dock.engine.dispose()
        dock.deleteLater()


@pytest.mark.parametrize(
    ("value", "decimals", "upper"),
    [
        (-0.47636787593364716, 3, False),  # the real files' own prepared t0
        (99.56100623309612, 4, True),  # ... and their prepared end
        (-0.4766, 3, False),  # rounds the WRONG way without the correction
        (12.34565, 4, True),
        (-11.0864, 3, False),
        (0.001, 3, False),  # exact at the precision: must not drift a step
        (0.001, 3, True),
        (-2.5, 1, True),
        (-2.5, 1, False),
    ],
)
def test_snap_inside_never_leaves_the_bound_it_describes(value, decimals, upper):
    """`_snap_inside` exists because `QDoubleSpinBox.setValue` rounds to the
    box's own precision, and a bound rounded the wrong way is a bound
    escaped -- re-raising the very `CoverageError` the clamp is there to
    prevent, now only for certain headers and only in the fourth decimal
    place. Pins both halves: the result is ON the spin's grid, and on the
    legal side of `value`.
    """
    from nsgeo_qgis.ui.slices_dock import _snap_inside

    snapped = _snap_inside(value, decimals, upper=upper)
    assert snapped == round(snapped, decimals)  # lands on the spin's grid
    if upper:
        assert snapped <= value, (snapped, value)
    else:
        assert snapped >= value, (snapped, value)
    # Tight: never gives away more than one step of the spin's precision.
    assert abs(snapped - value) < 10.0**-decimals


def test_the_dock_minimum_does_not_force_the_main_window_to_grow(qgis_app):
    """A dock widget's minimum size is a HARD floor on the main window's:
    QGIS cannot shrink a dock area below it, so a tall dock drags the whole
    application window taller. Reported from the M11 walkthrough as "it
    messes up the width/height of the window", and measured in a real QGIS
    on this profile: this dock's minimum was 556 x 1013, against 449 x 239
    for Processing and 101 x 132 for Survey. 1013 px of hard floor does not
    fit a 1080p screen once QGIS's own chrome is accounted for.

    Four group boxes stacked cannot be made short, so the fix is that they
    no longer have to be: the dock scrolls. Pinned on both halves -- a
    small floor AND content that stays its natural size inside the scroll
    area rather than being crushed into it.
    """
    from qgis.PyQt.QtWidgets import QScrollArea

    dock = SlicesDock(SiteSession())
    try:
        minimum = dock.minimumSizeHint()
        assert minimum.height() <= 400, minimum.height()
        assert minimum.width() <= 360, minimum.width()

        scroll = dock.findChild(QScrollArea)
        assert scroll is not None
        assert scroll.widgetResizable()
        # The content keeps its own full height inside the scroll area --
        # a "fix" that merely let the groups be squashed would lose rows.
        assert scroll.widget().minimumSizeHint().height() >= 600

        # ... and the dock still OPENS at a usable width, so this is not
        # the degenerate fix of making everything collapsible to nothing.
        assert dock.sizeHint().width() >= 280
    finally:
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.deleteLater()


def test_no_sequence_of_arrow_clicks_can_reach_a_frame_that_cannot_be_drawn(qgis_app, tmp_path):
    """Walkthrough round 2, W7: "These also tick by 1 unit at a time, which
    is too much. It also leads to cell size going to .001 which then
    crashes qgis because it is too fine a grid."

    `cell_spin` spans 0.01-5.0 m and kept Qt's default `singleStep` of
    1.0, so ONE press of the down-arrow from the seeded 0.5 m clamped
    straight to the 0.01 m minimum -- and cell count goes as 1/cell**2.
    On the 300 m grid below that is 30000 x 30000: a frame no amount of
    streaming makes drawable, since the per-slice array alone is the
    problem.

    The claim pinned here is the one that matters to a user holding down
    an arrow key: NO number of clicks reaches a geometry that cannot be
    drawn. That is stronger than checking a step size, and it is what
    actually failed.
    """
    from nsgeo_qgis.slices_plan import MAX_FRAME_CELLS, frame_cells

    session = SiteSession()
    session.new_site(tmp_path)
    big = Grid("Big", (500.0, 700.0), 0.0, 300.0, 300.0, "EPSG:32616", 0.5)
    session.add_grid(big)
    lines = [
        Line.open(
            synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60),
            GridPlacement("Big", "y", 1.0 + i, 0.0, 1, f"L{i}"),
        )
        for i in range(2)
    ]
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()

    dock = SlicesDock(session)
    try:
        assert dock.engine.wait_for_preparation(20_000)
        seeded = dock.cell_spin.value()
        assert frame_cells(big.size_x, big.size_y, seeded) <= MAX_FRAME_CELLS

        # Hold the down-arrow. Far more presses than the range can absorb.
        for _ in range(500):
            dock.cell_spin.stepBy(-1)
            assert frame_cells(big.size_x, big.size_y, dock.cell_spin.value()) <= (
                MAX_FRAME_CELLS
            ), f"cell {dock.cell_spin.value()} on a 300 m grid cannot be drawn"

        # ... and one click is a usable increment, not a leap to the end
        # of the range. The old behaviour went 0.5 -> minimum in one.
        dock.cell_spin.setValue(seeded)
        dock.cell_spin.stepBy(-1)
        assert dock.cell_spin.value() < seeded
        assert seeded - dock.cell_spin.value() <= 0.1, "one arrow click must be a nudge"
    finally:
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.deleteLater()


def test_the_resolution_and_max_distance_spins_step_by_a_useful_increment(docked):
    """Walkthrough round 2, W5/W7: "the up/down amount skips by 1 m at a
    time, which is too big an increment."

    Qt's `QDoubleSpinBox` defaults `singleStep` to 1.0 whatever the range
    or the decimals, so every one of these shipped with an arrow click
    that moved a 0.75 m radius to 1.75 m (the box is in spacings now) and a 0.2165 ns dz to 1.2165.
    `dz`/`z0`/`z1` step by the file's OWN sample interval -- one sample
    per click is the only increment that means anything on a time axis.
    """
    dock, _ = docked
    assert dock.engine.wait_for_preparation(20_000)
    header = dock.session.line_for_key(dock.session.keys()[0]).header

    assert (
        dock.grid_finish.max_distance_spin.singleStep() == 0.25
    )  # a quarter spacing, not Qt's 1.0
    assert dock.cell_spin.singleStep() <= 0.1
    assert dock.dz_spin.singleStep() == pytest.approx(header.dt_ns)
    assert dock.z0_spin.singleStep() == pytest.approx(header.dt_ns)
    assert dock.z1_spin.singleStep() == pytest.approx(header.dt_ns)
    # Position is in ns over a ~110 ns window: 1 ns is a fifth of the
    # default thickness, which is a leap, not a nudge.
    assert dock.thickness_spin.singleStep() <= 0.5
    assert dock.step_spin.singleStep() <= 0.5


def test_the_resolution_controls_say_what_they_do(docked):
    """Walkthrough round 2, W5/W7: "Fill radius is also not a super
    intuitive label, what does it do?" and "Not sure what dz does?"

    Neither is a naming failure that renaming fixes -- both are terms of
    art with no shorter correct name -- so each carries the sentence that
    makes it actionable, on the control itself.
    """
    dock, _ = docked
    for spin, must_say in (
        (dock.grid_finish.max_distance_spin, "blank"),
        (dock.dz_spin, "sample"),
        (dock.cell_spin, "spacing"),
        (dock.coverage_check, "traces"),
    ):
        tip = spin.toolTip()
        assert tip, f"{spin.objectName() or spin} has no tooltip"
        assert must_say in tip.lower(), tip


def test_a_restored_cell_size_too_fine_to_draw_is_refused_not_attempted(qgis_app, tmp_path):
    """`cell_spin`'s floor stops the arrows reaching an undrawable frame,
    but a `Resolution` can arrive from a saved cube record too
    (`restore_cube`), written against a different grid and never passed
    through this spin box at all. That path gets a readable refusal
    naming a cell size that would work, and the engine's geometry is left
    exactly as it was.

    Refused and not warned-and-allowed on purpose: spec 7.4's "warn
    rather than hard-cap" is about memory BUDGETS, where the fallback is
    to degrade to streaming. There is no degraded mode here -- the
    per-slice array is itself what cannot be allocated.
    """
    session = SiteSession()
    session.new_site(tmp_path)
    big = Grid("Big", (500.0, 700.0), 0.0, 300.0, 300.0, "EPSG:32616", 0.5)
    session.add_grid(big)
    session.add_lines(
        [
            Line.open(
                synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60),
                GridPlacement("Big", "y", 1.0, 0.0, 1, "L0"),
            )
        ]
    )
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()

    dock = SlicesDock(session)
    errors: list[str] = []
    dock.error.connect(errors.append)
    try:
        assert dock.engine.wait_for_preparation(20_000)
        dock.flush_debounce()
        before = dock.engine.frame
        assert before is not None

        # Exactly what a restored record does: a value the spin's own
        # floor would never have allowed.
        dock.cell_spin.setMinimum(0.001)
        dock.cell_spin.setValue(0.001)
        dock.flush_debounce()

        entries = dock.warnings_panel.entries()
        assert [e.kind for e in entries] == [REFUSAL], entries
        assert "too many to draw" in entries[0].text
        assert "0.15" in entries[0].text, f"it must name a cell that works: {entries[0].text}"
        assert "Still showing" in entries[0].text
        assert errors == [], "one place only: the Warnings section, not a toast"
        assert dock.engine.frame is before, (
            "the engine must still hold the geometry it had, not a frame it cannot draw"
        )

        dock.cell_spin.setValue(0.25)
        dock.flush_debounce()
        assert dock.warnings_panel.entries() == ()
    finally:
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.deleteLater()


def test_the_coverage_legend_says_what_a_blank_cell_means(docked):
    """Walkthrough round 2, W6: "Don't know what this is doing. It does
    look gappy, not sure what legend you're talking about."

    The gappiness is correct -- coverage is deliberately NOT filled, so
    that the binned truth stays visible underneath the cosmetic step
    (spec 6.4) -- but the legend read `0 - 15 traces`, and zero is the one
    value the view never draws: a cell no line crossed is left blank, not
    coloured at the bottom of the ramp. So the legend named a scale that
    did not match the picture, on the one view whose entire job is to be
    read literally.
    """
    dock, _ = docked
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()

    dock.coverage_check.setChecked(True)
    legend = dock.legend_label.text()
    assert "traces" in legend, legend
    assert "blank" in legend.lower(), f"the legend must explain the gaps: {legend}"
    assert not legend.startswith("0 "), f"zero is never drawn in this view: {legend}"

    # And back: an amplitude legend still names its transform, and makes
    # no claim about blank cells, which the fill has covered over.
    dock.coverage_check.setChecked(False)
    amplitude = dock.legend_label.text()
    assert "traces" not in amplitude, amplitude
    assert "blank" not in amplitude.lower(), amplitude


def test_the_legend_label_wraps_rather_than_widening_the_dock(qgis_app):
    """A `QLabel`'s minimum width is its text width unless it wraps, and a
    dock's minimum width is a hard floor on the QGIS main window's -- the
    same mechanism that made this dock force a 556 px window in round 1.
    The coverage legend is the longest string this dock ever shows.
    """
    dock = SlicesDock(SiteSession())
    try:
        assert dock.legend_label.wordWrap()
        dock.legend_label.setText("1 – 15 traces per cell · blank = no line crossed")
        assert dock.legend_label.minimumSizeHint().width() <= 200
    finally:
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.deleteLater()


# ---- M12 Task 2: each grid remembers its own slice source -------------------
GRID_B = Grid("B", (520.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)


def _line(tmp_path, grid_id, name, offset):
    return Line.open(
        synthetic_dzt(tmp_path / "raw", f"{name}.DZT", n_traces=60),
        GridPlacement(grid_id, "y", offset, 0.0, 1, name),
    )


@pytest.fixture
def docked_two_grids(qgis_app, tmp_path):
    """`docked`, plus a second grid "B" with its own synthetic lines and a
    second preset "q", so a grid switch has something to restore."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    session.add_grid(GRID_B)
    session.add_lines([_line(tmp_path, "A", f"FILE__00{i + 1}", 1.0 + i) for i in range(3)])
    session.add_lines([_line(tmp_path, "B", f"FILE__01{i}", 1.0 + i) for i in range(2)])
    session.site.presets["p"] = list(PRESET)
    session.site.presets["q"] = list(PRESET)
    session.presets_changed.emit()
    session.save()
    dock = SlicesDock(session)
    yield dock, session
    dock.engine.wait_for_preparation(20_000)
    dock.engine.dispose()
    dock.deleteLater()


def _grid_keys(session, grid_id):
    return tuple(
        k
        for k in session.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
        if getattr(session.line_for_key(k).placement, "grid_id", None) == grid_id
    )


def test_an_old_cube_record_without_lines_restores_every_line(docked_two_grids):
    """#74: an old record names no line list; it restores every line, as the
    remembered record (final review D4) already says."""
    dock, session = docked_two_grids
    a_keys = _grid_keys(session, "A")
    dock.set_included(a_keys[:2])
    assert dock.engine.wait_for_preparation(20_000)
    _save_cube(
        dock, session, "A__old", ViewSettings(1.0, 1.0, 0.0, "amp_black_high", "this slice", False)
    )
    del session.site.cubes["A__old"]["lines"]
    dock.cube_combo.setCurrentText("A__old")
    assert dock.included_keys() == a_keys
    assert session.slice_source("A")["lines"] is None
    assert dock.engine.wait_for_preparation(20_000)


def test_opening_a_site_does_not_mark_it_dirty(docked_two_grids):
    dock, session = docked_two_grids
    dock.engine.wait_for_preparation(20_000)
    assert not session.dirty
    assert session.slice_source("A") is None


def test_switching_grid_away_and_back_restores_that_grids_preset_and_lines(docked_two_grids):
    dock, session = docked_two_grids
    a_keys = _grid_keys(session, "A")
    dock.preset_combo.setCurrentText("q")
    dock.set_included(a_keys[:2])
    dock.grid_combo.setCurrentText("B")
    assert dock.included_keys() == _grid_keys(session, "B")
    # B shows "p" so A's "q" must genuinely be restored on the way back,
    # not merely still be showing.
    dock.preset_combo.setCurrentText("p")
    dock.grid_combo.setCurrentText("A")
    assert dock.preset_combo.currentText() == "q"
    assert dock.included_keys() == a_keys[:2]
    assert dock.engine.wait_for_preparation(20_000)


def test_a_default_line_choice_picks_up_a_line_imported_later(docked_two_grids, tmp_path):
    dock, session = docked_two_grids
    dock.grid_combo.setCurrentText("B")
    dock.grid_combo.setCurrentText("A")
    assert session.slice_source("A")["lines"] is None
    dock.grid_combo.setCurrentText("B")
    session.add_lines([_line(tmp_path, "A", "FILE__099", 9.0)])
    dock.grid_combo.setCurrentText("A")
    assert len(dock.included_keys()) == 4
    assert dock.engine.wait_for_preparation(20_000)


def _reopened_with_a_late_import(session, tmp_path):
    """Save the survey, reopen it in a new session and dock, and import a
    line for A there (#75: the pick-up must survive save and reopen)."""
    session.save()
    reopened = SiteSession()
    reopened.open_site(session.json_path)
    dock2 = SlicesDock(reopened)
    new_line = _line(tmp_path, "A", "FILE__099", 9.0)
    reopened.add_lines([new_line])
    return reopened, dock2


def _dispose(dock):
    dock.engine.wait_for_preparation(20_000)
    dock.engine.dispose()
    dock.deleteLater()


def test_a_default_line_choice_picks_up_an_import_after_save_and_reopen(docked_two_grids, tmp_path):
    dock, session = docked_two_grids
    a_keys = _grid_keys(session, "A")
    dock.grid_combo.setCurrentText("B")
    dock.grid_combo.setCurrentText("A")  # the round trip records `lines: None`
    assert session.slice_source("A")["lines"] is None
    reopened, dock2 = _reopened_with_a_late_import(session, tmp_path)
    try:
        assert reopened.slice_source("A")["lines"] is None  # loaded as stored null
        new_keys = set(_grid_keys(reopened, "A")) - set(a_keys)
        assert len(new_keys) == 1
        assert new_keys <= set(dock2.included_keys())
    finally:
        _dispose(dock2)


def test_an_explicit_line_choice_does_not_pick_up_an_import_after_save_and_reopen(
    docked_two_grids, tmp_path
):
    dock, session = docked_two_grids
    a_keys = _grid_keys(session, "A")
    dock.set_included(a_keys[:2])
    assert dock.engine.wait_for_preparation(20_000)
    reopened, dock2 = _reopened_with_a_late_import(session, tmp_path)
    try:
        new_keys = set(_grid_keys(reopened, "A")) - set(a_keys)
        assert len(new_keys) == 1
        assert not new_keys & set(dock2.included_keys())
        assert dock2.included_keys() == a_keys[:2]
    finally:
        _dispose(dock2)


def test_opening_a_survey_that_has_saved_cubes_stays_clean(docked_two_grids):
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    view = ViewSettings(1.0, 1.0, 0.0, "amp_black_high", "this slice", False)
    _save_cube(dock, session, "A__kept", view)
    session.save()

    reopened = SiteSession()
    reopened.open_site(session.json_path)
    dock2 = SlicesDock(reopened)
    try:
        assert dock2.engine.wait_for_preparation(20_000)
        assert not reopened.dirty
        items = [dock2.cube_combo.itemText(i) for i in range(dock2.cube_combo.count())]
        assert "A__kept" in items
    finally:
        _dispose(dock2)


def test_choosing_lines_remembers_them_for_that_grid_only(docked_two_grids):
    dock, session = docked_two_grids
    a_keys = _grid_keys(session, "A")
    dock.set_included(a_keys[:1])
    assert session.slice_source("A")["lines"] == list(a_keys[:1])
    assert session.slice_source("B") is None
    assert session.dirty


def test_a_remembered_line_that_left_the_grid_is_filtered_out(docked_two_grids):
    dock, session = docked_two_grids
    a_keys = _grid_keys(session, "A")
    dock.set_included(a_keys[:2])
    dock.grid_combo.setCurrentText("B")
    session.remove_line(a_keys[0])
    dock.grid_combo.setCurrentText("A")
    assert dock.included_keys() == (a_keys[1],)
    assert dock.engine.wait_for_preparation(20_000)


def test_reopening_a_survey_restores_a_remembered_source_without_dirtying_or_rewriting_it(
    docked_two_grids,
):
    dock, session = docked_two_grids
    a_keys = _grid_keys(session, "A")
    dock.preset_combo.setCurrentText("q")  # not the first preset
    dock.set_included(a_keys[1:])
    assert dock.engine.wait_for_preparation(20_000)
    session.save()
    stored = session.slice_source("A")
    assert stored == {"preset": "q", "lines": list(a_keys[1:])}

    reopened = SiteSession()
    reopened.open_site(session.json_path)
    dock2 = SlicesDock(reopened)
    try:
        assert dock2.grid_combo.currentText() == "A"
        assert dock2.preset_combo.currentText() == "q"
        assert dock2.included_keys() == a_keys[1:]
        assert dock2.engine.wait_for_preparation(20_000)
        assert not reopened.dirty
        assert reopened.slice_source("A") == stored
    finally:
        dock2.engine.wait_for_preparation(20_000)
        dock2.engine.dispose()
        dock2.deleteLater()


def test_picking_a_saved_cube_remembers_its_preset_and_lines_for_that_grid(docked_two_grids):
    dock, session = docked_two_grids
    a_keys = _grid_keys(session, "A")
    dock.preset_combo.setCurrentText("q")
    dock.set_included(a_keys[:2])
    assert dock.engine.wait_for_preparation(20_000)
    view = ViewSettings(
        thickness_ns=4.0,
        step_ns=2.0,
        radius_m=0.5,
        palette=dock.palette_combo.currentText(),
        stretch="this slice",
        coverage=False,
    )
    _save_cube(dock, session, "A__c", view)
    # Move A's remembered source elsewhere, so only the cube pick can bring q back.
    dock.preset_combo.setCurrentText("p")
    dock.set_included(a_keys[:1])
    assert dock.engine.wait_for_preparation(20_000)
    assert session.slice_source("A")["preset"] == "p"

    dock.cube_combo.setCurrentText("A__c")
    assert dock.engine.wait_for_preparation(20_000)
    dock.grid_combo.setCurrentText("B")
    dock.preset_combo.setCurrentText("p")
    dock.grid_combo.setCurrentText("A")
    assert dock.preset_combo.currentText() == "q"
    assert dock.included_keys() == a_keys[:2]
    assert dock.engine.wait_for_preparation(20_000)


@pytest.mark.parametrize("remembered", [(), ("raw/elsewhere/FILE__900.DZT",)])
def test_an_empty_remembered_line_set_is_the_default(docked_two_grids, tmp_path, remembered):
    """Final review D4: a remembered `lines` that leaves no line on the grid --
    an empty choice, or lines that have all left it -- is the default, every
    line, and stays the default: a line imported later is picked up."""
    dock, session = docked_two_grids
    a_keys = _grid_keys(session, "A")
    dock.grid_combo.setCurrentText("B")
    session.remember_slice_source("A", preset="p", lines=remembered)
    dock.grid_combo.setCurrentText("A")
    assert dock.included_keys() == a_keys
    session.add_lines([_line(tmp_path, "A", "FILE__099", 9.0)])
    assert len(dock.included_keys()) == 4
    assert dock.engine.wait_for_preparation(20_000)


def test_a_cube_record_with_no_lines_key_is_remembered_as_every_line(docked_two_grids):
    """Final review D4: an old-format cube record names no line list, so
    picking it remembers `lines=None` ("every line"), not an empty choice.
    The dock restores every line too (#74; it used to restore an empty set)."""
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    view = ViewSettings(1.0, 1.0, 0.0, "amp_black_high", "this slice", False)
    record = _save_cube(dock, session, "A__old", view)
    del record["lines"]  # written before cube records carried their lines
    dock.cube_combo.setCurrentText("A__old")
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.included_keys() == _grid_keys(session, "A")
    assert session.slice_source("A")["lines"] is None


# ---- #71: each grid remembers its own resolution ----------------------------
def _switch(dock, grid_id):
    """Pick `grid_id` in This grid's combo, then let the change land."""
    dock.grid_combo.setCurrentText(grid_id)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)


def _settle_sources(dock, session):
    """A combo pick remembers that grid's preset and lines (M12), which
    dirties the survey once. Done and saved first, so a later switch writes
    nothing and only a resolution write could dirty it."""
    assert dock.engine.wait_for_preparation(20_000)
    _switch(dock, "B")
    _switch(dock, "A")
    session.save()


def _snapped_bounds(dock):
    from nsgeo_qgis.ui.slices_dock import _snap_inside

    low, high = dock.engine.prepared_z_bounds()
    return (
        _snap_inside(low, dock.z0_spin.decimals(), upper=False),
        _snap_inside(high, dock.z1_spin.decimals(), upper=True),
    )


def test_a_resolution_edit_is_remembered_for_that_grid_only(docked_two_grids):
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    assert not session.dirty
    dock.cell_spin.setValue(0.1)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    assert session.slice_resolution("A") == {"cell": 0.1}
    assert session.slice_resolution("B") == {}
    assert session.dirty


def test_switching_grid_away_and_back_restores_that_grids_resolution(docked_two_grids):
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    seed_cell = dock.cell_spin.value()
    seed_dz = dock.dz_spin.value()
    dock.cell_spin.setValue(0.1)
    dock.dz_spin.setValue(seed_dz * 2)
    dock.grid_finish.max_distance_spin.setValue(1.5)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)

    _switch(dock, "B")
    assert dock.cell_spin.value() == pytest.approx(seed_cell)
    assert dock.dz_spin.value() == pytest.approx(seed_dz)
    assert dock.grid_finish.max_distance_spin.value() == pytest.approx(0.75)

    _switch(dock, "A")
    assert dock.cell_spin.value() == pytest.approx(0.1)
    assert dock.dz_spin.value() == pytest.approx(seed_dz * 2)
    assert dock.grid_finish.max_distance_spin.value() == pytest.approx(1.5)
    # On the engine too, not only in the boxes, and drawn.
    assert dock.engine.frame.cell == pytest.approx(0.1)
    assert dock.engine.z.dz_ns == pytest.approx(seed_dz * 2)
    assert dock.grid_finish.max_distance_metres.text() == "= 0.75 m"
    assert dock.current_values() is not None


def test_seeding_never_remembers_a_resolution(docked_two_grids):
    dock, session = docked_two_grids
    # B's own spacing seeds a different cell, so every switch below really
    # moves the box (and emits) rather than passing for want of a change.
    session.replace_grid(dataclasses.replace(GRID_B, default_spacing=0.3))
    _settle_sources(dock, session)
    seen: list[float] = []
    dock.cell_spin.valueChanged.connect(seen.append)
    _switch(dock, "B")
    _switch(dock, "A")
    assert len(seen) >= 2
    assert session.slice_resolution("A") == {}
    assert session.slice_resolution("B") == {}
    assert not session.dirty


def test_reopening_a_survey_restores_a_remembered_resolution_without_dirtying_it(
    docked_two_grids,
):
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    dock.cell_spin.setValue(0.1)
    dock.dz_spin.setValue(0.5)
    dock.z0_spin.setValue(2.0)
    dock.z1_spin.setValue(30.0)
    dock.grid_finish.max_distance_spin.setValue(1.5)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    session.save()
    stored = session.slice_source("A")
    assert stored["resolution"] == {
        "cell": 0.1,
        "dz_ns": 0.5,
        "t0_ns": 2.0,
        "t1_ns": 30.0,
        "max_distance_spacings": 1.5,
    }

    reopened = SiteSession()
    reopened.open_site(session.json_path)
    dock2 = SlicesDock(reopened)
    try:
        assert dock2.grid_combo.currentText() == "A"
        assert dock2.cell_spin.value() == pytest.approx(0.1)
        assert dock2.dz_spin.value() == pytest.approx(0.5)
        assert dock2.z0_spin.value() == pytest.approx(2.0)
        assert dock2.z1_spin.value() == pytest.approx(30.0)
        assert dock2.grid_finish.max_distance_spin.value() == pytest.approx(1.5)
        dock2.flush_debounce()
        assert dock2.engine.wait_for_preparation(20_000)
        # The restored values reached the engine and drew a slice.
        assert dock2.engine.frame.cell == pytest.approx(0.1)
        assert dock2.engine.z.t0_ns == pytest.approx(2.0)
        assert dock2.engine.z.dz_ns == pytest.approx(0.5)
        assert dock2.engine.z.t_end_ns == pytest.approx(30.0)
        assert dock2.current_values() is not None
        assert not reopened.dirty
        assert reopened.slice_source("A") == stored
    finally:
        dock2.engine.wait_for_preparation(20_000)
        dock2.engine.dispose()
        dock2.deleteLater()


def test_a_remembered_z_range_is_clamped_to_the_prepared_lines_but_kept(docked_two_grids):
    dock, session = docked_two_grids
    _settle_sources(dock, session)
    _switch(dock, "B")
    low, high = dock.engine.prepared_z_bounds()
    wide = {"t0_ns": low - 5.0, "t1_ns": high + 5.0}
    session.remember_slice_resolution("A", **wide)
    session.save()
    dock.grid_combo.setCurrentText("A")
    # Restored first; the clamp waits for A's lines to be prepared.
    assert dock.z0_spin.value() == pytest.approx(wide["t0_ns"], abs=1e-3)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    assert (dock.z0_spin.value(), dock.z1_spin.value()) == _snapped_bounds(dock)
    assert session.slice_resolution("A") == wide
    assert not session.dirty
    assert dock.current_values() is not None


def test_a_remembered_z_range_wholly_outside_the_data_falls_back_to_the_prepared_range(
    docked_two_grids,
):
    """Review Focus 1: clamping each end of a range that lies wholly past the
    data on its own leaves z1 below z0, and every slice would then fail."""
    dock, session = docked_two_grids
    errors: list[str] = []
    dock.error.connect(errors.append)
    _settle_sources(dock, session)
    _switch(dock, "B")
    _low, high = dock.engine.prepared_z_bounds()
    beyond = {"t0_ns": high + 10.0, "t1_ns": high + 50.0}
    session.remember_slice_resolution("A", **beyond)
    session.save()
    dock.grid_combo.setCurrentText("A")
    assert dock.z0_spin.value() == pytest.approx(beyond["t0_ns"], abs=1e-3)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    assert (dock.z0_spin.value(), dock.z1_spin.value()) == _snapped_bounds(dock)
    assert errors == []
    assert dock.current_values() is not None
    # The remembered values stand, for a later crop that frees the range.
    assert session.slice_resolution("A") == beyond
    assert not session.dirty


def test_a_bound_set_after_the_empty_range_fallback_keeps_the_range_shown(docked_two_grids):
    """Ruling 15 (#71): after the fallback the user edits against the range
    shown, not the one remembered. A hand z0, a time cutoff past it, then a
    hand z1 used to leave t0 > t1 in the record: the next restore snapped z1
    back to the data's end, and a reopen dropped the reversed pair."""
    dock, session = docked_two_grids
    _settle_sources(dock, session)
    low, high = dock.engine.prepared_z_bounds()
    dock.z0_spin.setValue(round(low + 0.6 * (high - low), 3))
    dock.flush_debounce()
    cutoff = {"step": "time_cutoff", "params": {"end_ns": round(low + 0.4 * (high - low), 3)}}
    session.site.presets["cut"] = [*PRESET, {**cutoff, "enabled": True}]
    session.presets_changed.emit()
    dock.preset_combo.setCurrentText("cut")
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    shown_z0 = _snapped_bounds(dock)[0]
    assert dock.z0_spin.value() == shown_z0, "the fallback shows the data's range"
    z1 = round(low + 0.3 * (high - low), 3)
    dock.z1_spin.setValue(z1)
    dock.flush_debounce()

    _switch(dock, "B")
    _switch(dock, "A")
    assert (dock.z0_spin.value(), dock.z1_spin.value()) == (shown_z0, z1)
    assert session.slice_resolution("A") == {"t0_ns": shown_z0, "t1_ns": z1}
    session.save()
    reopened = SiteSession()
    reopened.open_site(session.json_path)
    dock2 = SlicesDock(reopened)
    try:
        dock2.flush_debounce()
        assert dock2.engine.wait_for_preparation(20_000)
        assert reopened.slice_resolution("A") == {"t0_ns": shown_z0, "t1_ns": z1}
        assert (dock2.z0_spin.value(), dock2.z1_spin.value()) == (shown_z0, z1)
        assert dock2.engine.z.t0_ns == pytest.approx(shown_z0)
        assert dock2.current_values() is not None
        assert not reopened.dirty
    finally:
        _dispose(dock2)


def test_an_edit_after_a_clamp_that_left_the_range_usable_keeps_the_remembered_end(
    docked_two_grids,
):
    """Ruling 15 remembers the shown end only when the pair would be empty: a
    remembered z0 that a clamp only pulled up to the data is still the user's."""
    dock, session = docked_two_grids
    _settle_sources(dock, session)
    _switch(dock, "B")
    low, high = dock.engine.prepared_z_bounds()
    session.remember_slice_resolution("A", t0_ns=low - 5.0)
    _switch(dock, "A")
    assert dock.z0_spin.value() == _snapped_bounds(dock)[0]
    z1 = round(low + 0.5 * (high - low), 3)
    dock.z1_spin.setValue(z1)
    assert session.slice_resolution("A") == {"t0_ns": low - 5.0, "t1_ns": z1}


def test_a_hand_resolution_on_an_empty_grid_survives_its_lines_arriving(qgis_app, tmp_path):
    """#71, the ordinary new-survey flow: a grid picked before it has lines,
    dz and z1 set by hand, then the lines imported. dz/z0/z1 are seeded only
    once a line exists, after the grid change, so that late seed must lay
    what the user chose back over itself (`_seed_dz_z_defaults`' restore)."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()
    dock = SlicesDock(session)
    try:
        assert dock.grid_combo.currentText() == "A"
        dock.dz_spin.setValue(0.5)
        dock.z1_spin.setValue(30.0)
        remembered = {"dz_ns": 0.5, "t1_ns": 30.0}
        assert session.slice_resolution("A") == remembered
        session.add_lines([_line(tmp_path, "A", f"FILE__00{i + 1}", 1.0 + i) for i in range(3)])
        header = session.line_for_key(session.keys()[0]).header
        assert dock.z0_spin.value() == pytest.approx(header.position_ns, abs=1e-3), "seeded"
        assert (dock.dz_spin.value(), dock.z1_spin.value()) == (0.5, 30.0)
        assert dock.engine.wait_for_preparation(20_000)
        dock.flush_debounce()
        assert dock.engine.z.dz_ns == pytest.approx(0.5)
        assert dock.engine.z.t_end_ns == pytest.approx(30.0, abs=0.5)
        assert dock.current_values() is not None
        assert session.slice_resolution("A") == remembered
    finally:
        _dispose(dock)


def test_a_remembered_cell_below_the_grids_floor_is_clamped_to_it(docked_two_grids):
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    _switch(dock, "B")
    session.remember_slice_resolution("A", cell=0.001)
    _switch(dock, "A")
    assert dock.cell_spin.value() == dock.cell_spin.minimum()
    assert dock.engine.frame.cell == pytest.approx(dock.cell_spin.minimum())
    assert session.slice_resolution("A") == {"cell": 0.001}


def test_picking_a_saved_cube_remembers_its_resolution(docked_two_grids):
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    dock.cell_spin.setValue(0.1)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    _save_cube(dock, session, "A__res", dock.view_settings())
    dock.cell_spin.setValue(0.3)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    assert session.slice_resolution("A")["cell"] == pytest.approx(0.3)

    dock.cube_combo.setCurrentText("A__res")
    assert dock.engine.wait_for_preparation(20_000)
    remembered = session.slice_resolution("A")
    assert set(remembered) == {
        "cell",
        "dz_ns",
        "t0_ns",
        "t1_ns",
        "method",
        "max_distance_spacings",
        "smooth_x_m",
        "smooth_y_m",
    }
    assert remembered["cell"] == pytest.approx(0.1)
    _switch(dock, "B")
    _switch(dock, "A")
    assert dock.cell_spin.value() == pytest.approx(0.1)


# ---- minimum curvature: preview while the depth moves, refine once it rests --
# Plan calls 5 and 7 (interpolation spec §7). A solve's real duration never
# decides anything here: `_last_solve_ms` is set by hand, once the plan exists
# (Ruling R1: building one resets it).


def _pump_for(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.002)


def _pump_until(predicate, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() > deadline:
            pytest.fail("timed out waiting for the condition")
        QCoreApplication.processEvents()
        time.sleep(0.002)


def _wait_for_refine(dock, timeout_s: float = 30.0) -> None:
    """Let the depth rest (`REFINE_REST_MS` and a margin), then pump events
    until the refine worker has landed its list and no rest is pending."""
    start = time.monotonic()
    rested = start + (REFINE_REST_MS + 150) / 1000.0
    while time.monotonic() < rested or dock.refiner.busy or dock._grid_refine.rest.isActive():
        if time.monotonic() - start > timeout_s:
            pytest.fail("the refine did not finish")
        QCoreApplication.processEvents()
        time.sleep(0.002)


def _minimum_curvature(dock, last_solve_ms, stretch="this slice"):
    """The dock on minimum curvature at slider 10, that slice refined, and the
    last solve then said to have taken `last_solve_ms`."""
    _ready(dock)
    dock.stretch_combo.setCurrentText(stretch)
    dock.slice_slider.setValue(10)
    _set_finish(dock, method="min_curvature")
    _wait_for_refine(dock)
    assert not dock.provisional
    dock.engine._last_solve_ms = last_solve_ms


def _drawn_by_the_engine(dock, how):
    """`engine.preview` or `engine.finish` of the dock's current window."""
    engine = dock.engine
    values, coverage = engine.slice_at(dock.current_window())
    draw = engine.preview if how == "preview" else engine.finish
    return draw(values, coverage, dock.slice_finish())


def _starts(dock, monkeypatch) -> list[float]:
    """When the refiner was asked to start a list, by the monotonic clock."""
    times: list[float] = []
    real = dock.refiner.start

    def recording(*args, **kwargs):
        times.append(time.monotonic())
        return real(*args, **kwargs)

    monkeypatch.setattr(dock.refiner, "start", recording)
    return times


@pytest.mark.parametrize("move", ["slider", "step"])
def test_a_slow_slice_shows_the_preview_then_refines(docked, move):
    dock, _ = docked
    _minimum_curvature(dock, 500.0)
    if move == "slider":
        dock.slice_slider.setValue(20)
    else:
        dock.step_slice(1)
    window = dock.current_window()
    assert dock.provisional
    assert dock.refine_label.text() == PREVIEW_INDICATOR
    preview = dock.current_values()
    np.testing.assert_array_equal(preview, _drawn_by_the_engine(dock, "preview"))

    _wait_for_refine(dock)
    assert not dock.provisional
    assert dock.status_label.text() == dock._grid_status_text()
    assert dock.current_window() == window
    np.testing.assert_array_equal(dock.current_values(), _drawn_by_the_engine(dock, "finish"))
    assert not np.array_equal(dock.current_values(), preview, equal_nan=True)


def test_the_refine_waits_for_the_depth_to_rest(docked, monkeypatch):
    """Each move restarts the rest, and the refine starts only when it runs
    out. No events are processed between the moves, so a stalled process can
    only make the rest look later, never fire it between them."""
    dock, _ = docked
    _minimum_curvature(dock, 500.0)
    starts = _starts(dock, monkeypatch)
    moved = 0.0
    left: int | None = None
    for value in (15, 20, 25):
        # Taken before the move: the move starts the rest inside `setValue`,
        # then draws the preview, so a time taken after it would eat into the
        # 5% a coarse timer may fire early (final review M-3).
        moved = time.monotonic()
        dock.slice_slider.setValue(value)
        assert dock.provisional
        assert not dock.refiner.busy
        assert dock._grid_refine.rest.isActive()
        if left is not None:
            assert dock._grid_refine.rest.remainingTime() > left, "a move must restart the rest"
        time.sleep(0.1)  # the depth still moving: no events, so the rest cannot fire
        left = dock._grid_refine.rest.remainingTime()
        assert left < REFINE_REST_MS
    assert starts == [], "a refine started while the depth was still moving"
    _wait_for_refine(dock)
    assert len(starts) == 1
    # A coarse Qt timer may fire up to 5% early.
    assert starts[0] - moved >= 0.9 * REFINE_REST_MS / 1000.0
    assert not dock.provisional


def test_a_quick_solve_draws_minimum_curvature_at_once(docked, monkeypatch):
    dock, _ = docked
    _minimum_curvature(dock, 5.0)
    starts = _starts(dock, monkeypatch)
    dock.slice_slider.setValue(20)
    assert not dock.provisional
    assert not dock._grid_refine.rest.isActive()
    assert dock.status_label.text() == dock._grid_status_text()
    np.testing.assert_array_equal(dock.current_values(), _drawn_by_the_engine(dock, "finish"))
    _pump_for((REFINE_REST_MS + 150) / 1000.0)
    assert starts == []


def test_kriging_never_previews(docked, monkeypatch):
    dock, _ = docked
    _ready(dock)
    starts = _starts(dock, monkeypatch)
    for stretch, value in (("this slice", 20), ("shared across the cube", 30)):
        dock.stretch_combo.setCurrentText(stretch)
        dock.slice_slider.setValue(value)
        assert not dock.provisional
        assert not dock._grid_refine.rest.isActive()
        np.testing.assert_array_equal(dock.current_values(), _drawn_by_the_engine(dock, "finish"))
    _pump_for((REFINE_REST_MS + 150) / 1000.0)
    assert starts == []


def test_a_refine_for_a_window_left_behind_never_draws(docked, monkeypatch):
    """Review Focus 2. Window A's solve is held until the person has moved on
    to B, and ignores the cancel, so it finishes late on purpose. It must not
    land, and nothing drawn after the move may be A's."""
    dock, _ = docked
    _minimum_curvature(dock, 500.0)
    engine = dock.engine
    gate, finished_late = threading.Event(), threading.Event()
    held: dict[str, bytes] = {}
    real = engine.pending_solve

    def gated(values, coverage, finish, **kwargs):
        job = real(values, coverage, finish, **kwargs)
        if job is not None and job.key == held.get("a"):
            run = job.run

            def run_late(should_stop):
                gate.wait(10)
                run(lambda: False)  # deaf to the cancel
                finished_late.set()

            job.run = run_late
        return job

    monkeypatch.setattr(engine, "pending_solve", gated)
    dock.slice_slider.setValue(20)
    a_values, a_coverage = engine.slice_at(dock.current_window())
    held["a"] = solve_key(a_values)
    _pump_until(lambda: dock.refiner.busy)  # A rested and its solve began
    drawn: list[np.ndarray] = []
    dock.slice_changed.connect(lambda: drawn.append(dock.current_values()))
    dock.slice_slider.setValue(30)
    b_window = dock.current_window()
    assert dock.provisional
    gate.set()
    _wait_for_refine(dock)

    assert finished_late.is_set()
    assert solve_key(a_values) not in engine._solved, "A's late result landed"
    assert dock.current_window() == b_window
    np.testing.assert_array_equal(dock.current_values(), _drawn_by_the_engine(dock, "finish"))
    a_full = engine.finish(a_values, a_coverage, dock.slice_finish())
    shown = [values for values in drawn if values is not None]
    assert len(shown) >= 2  # B's preview, then B
    assert not any(np.array_equal(values, a_full, equal_nan=True) for values in shown)


def test_the_shared_stretch_is_provisional_until_its_windows_are_solved(docked):
    dock, _ = docked
    _minimum_curvature(dock, 500.0)
    engine = dock.engine
    mc = dock.slice_finish()
    dock.stretch_combo.setCurrentText("shared across the cube")
    dock.slice_slider.setValue(20)
    n = dock.current_window().n_levels
    clip = UnipolarClip() if engine.output_unipolar else PercentileClip()
    assert engine.stretch_solves(n, mc) != []
    assert dock.display_limit() == pytest.approx(engine.shared_limit(n, clip, mc, preview=True))
    finals: list[Any] = []
    dock.slice_changed.connect(
        lambda: finals.append(dock._grid_refine.stretch and dock._grid_refine.stretch[2])
    )
    _wait_for_refine(dock)
    assert engine.stretch_solves(n, mc) == []
    assert dock.display_limit() == pytest.approx(engine.shared_limit(n, clip, mc))
    assert finals and finals[-1] is True, "the slice must be redrawn with the final stretch"


def test_a_landed_slice_does_not_cancel_the_stretch_solves(docked):
    dock, _ = docked
    _minimum_curvature(dock, 500.0)
    dock.stretch_combo.setCurrentText("shared across the cube")
    dock.slice_slider.setValue(20)
    states: list[tuple[bool, bool]] = []
    dock.slice_changed.connect(lambda: states.append((dock.provisional, dock.refiner.busy)))
    _wait_for_refine(dock)
    refined = [busy for provisional, busy in states if not provisional]
    assert refined, "the refined slice was never drawn"
    assert refined[0] is True, "the stretch windows must still be solving when the slice lands"
    assert refined[-1] is False
    n = dock.current_window().n_levels
    assert dock.engine.stretch_solves(n, dock.slice_finish()) == []


def test_a_failed_refine_is_reported_and_leaves_the_preview(docked, monkeypatch):
    dock, _ = docked
    _minimum_curvature(dock, 500.0)
    engine = dock.engine
    real = engine.pending_solve

    def failing(values, coverage, finish, **kwargs):
        job = real(values, coverage, finish, **kwargs)

        def run(should_stop):
            raise ValueError("no convergence")

        job.run = run
        return job

    monkeypatch.setattr(engine, "pending_solve", failing)
    seen: list[str] = []
    dock.error.connect(seen.append)
    dock.slice_slider.setValue(20)
    preview = dock.current_values()
    _wait_for_refine(dock)
    assert seen == ["minimum curvature failed: ValueError: no convergence"]
    assert dock.provisional, "the preview stays on screen"
    assert dock.current_values() is preview
    assert dock.status_label.text() == dock._grid_status_text()


def test_a_preview_solved_during_the_rest_is_drawn_at_the_rest(docked, monkeypatch):
    """Finding 2a: if the previewed slice is solved while the depth rests (an
    export solves every band), the rest makes no job, and must still replace
    the preview, since nothing would arm the rest for it again."""
    dock, _ = docked
    _minimum_curvature(dock, 500.0)
    starts = _starts(dock, monkeypatch)
    dock.slice_slider.setValue(20)
    assert dock.provisional
    engine = dock.engine
    engine.finish(*engine.slice_at(dock.current_window()), dock.slice_finish())
    _wait_for_refine(dock)
    assert starts == []
    assert not dock.provisional
    assert dock.status_label.text() == dock._grid_status_text()
    np.testing.assert_array_equal(dock.current_values(), _drawn_by_the_engine(dock, "finish"))


def test_a_provisional_stretch_left_by_a_failed_refine_is_retried_at_the_next_draw(
    docked, monkeypatch
):
    """Finding 2b: a refine that ends in an error leaves the shared stretch
    provisional with nothing armed; the next draw must arm the rest again."""
    dock, _ = docked
    _minimum_curvature(dock, 500.0)
    engine = dock.engine
    real = engine.stretch_solves
    calls: list[int] = []

    def failing_once(thickness_levels, finish):
        jobs = real(thickness_levels, finish)
        calls.append(len(jobs))
        if len(calls) == 1 and jobs:

            def run(should_stop):
                raise ValueError("no convergence")

            jobs[-1].run = run  # the others land first
        return jobs

    monkeypatch.setattr(engine, "stretch_solves", failing_once)
    errors: list[str] = []
    dock.error.connect(errors.append)
    dock.stretch_combo.setCurrentText("shared across the cube")
    _wait_for_refine(dock)
    assert errors == ["minimum curvature failed: ValueError: no convergence"]
    assert dock._grid_refine.stretch is not None and dock._grid_refine.stretch[2] is False
    assert not dock.refiner.busy and not dock._grid_refine.rest.isActive()

    dock.refresh_slice()  # the next draw, whatever prompts it
    assert dock._grid_refine.rest.isActive(), "the provisional stretch must arm the rest again"
    _wait_for_refine(dock)
    assert len(calls) == 2 and calls[1] == 1  # only the window that failed
    n = dock.current_window().n_levels
    assert dock._grid_refine.stretch is not None and dock._grid_refine.stretch[2] is True
    clip = UnipolarClip() if engine.output_unipolar else PercentileClip()
    assert dock.display_limit() == pytest.approx(engine.shared_limit(n, clip, dock.slice_finish()))


def test_a_draw_hashes_its_slice_once(docked, monkeypatch):
    """Finding 1: hashing a slice costs about 7 ms at a million cells, and a
    draw needs its key two or three times, so it is computed once and passed
    on, through the rest's job too."""
    from nsgeo_qgis import slices_engine
    from nsgeo_qgis.ui import slices_dock

    dock, _ = docked
    _minimum_curvature(dock, 500.0)
    hashes: list[int] = []

    def counting(values):
        hashes.append(1)
        return solve_key(values)

    monkeypatch.setattr(slices_engine, "solve_key", counting)
    monkeypatch.setattr(slices_dock, "solve_key", counting)
    dock.slice_slider.setValue(20)  # slow: the preview
    assert dock.provisional and len(hashes) == 1
    hashes.clear()
    _wait_for_refine(dock)  # the rest's job, then the redraw it lands
    assert not dock.provisional and len(hashes) == 1
    hashes.clear()
    dock.engine._last_solve_ms = 5.0
    dock.slice_slider.setValue(30)  # quick: solved at once
    assert not dock.provisional and len(hashes) == 1


def test_a_final_stretch_queues_no_stretch_solves_at_rest(docked, monkeypatch):
    """Ruling R11: a rest asks for the stretch's solves only while the stretch
    shown is provisional. Asking slices and hashes its twelve windows on the
    GUI thread (about 84 ms at a million cells), for nothing once it is final."""
    dock, _ = docked
    _minimum_curvature(dock, 500.0, stretch="shared across the cube")
    engine = dock.engine
    assert dock._grid_refine.stretch is not None and dock._grid_refine.stretch[2] is True
    asked: list[int] = []
    real = engine.stretch_solves

    def counted(thickness_levels, finish):
        asked.append(thickness_levels)
        return real(thickness_levels, finish)

    monkeypatch.setattr(engine, "stretch_solves", counted)
    starts = _starts(dock, monkeypatch)
    # A window off the stretch: the stretch's own were solved with it.
    n = dock.current_window().n_levels
    measured = set(limit_windows(engine.z, n))
    dock.slice_slider.setValue(
        next(k for k in range(15, engine.z.nz - n) if SliceWindow(k, k + n) not in measured)
    )
    assert dock.provisional
    _wait_for_refine(dock)
    assert len(starts) == 1
    assert asked == []
    assert not dock.provisional
    # A thickness not measured yet is provisional again, and its rest asks.
    dock.thickness_spin.setValue(dock.thickness_spin.value() * 2)
    _wait_for_refine(dock)
    assert asked
    assert dock._grid_refine.stretch is not None and dock._grid_refine.stretch[2] is True


def test_a_redraw_keeps_its_own_solve_but_a_new_plan_cancels_it(docked, monkeypatch):
    """The keep rule (`RefineFlow.previewed`) in This grid. A redraw of the
    slice still being solved (a palette change) waits for exactly the running
    list's head, on the plan held, so the solve runs on. A max distance edit
    rebuilds the plan but leaves the values, and so the solve key, as they
    were: that solve could never land, so it is cancelled before the new plan
    is built, and the rest restarts."""
    from nsgeo_qgis import slices_engine

    dock, _ = docked
    _minimum_curvature(dock, 500.0)
    engine = dock.engine
    starts = _starts(dock, monkeypatch)
    gate = threading.Event()
    held: list = []
    real = engine.pending_solve

    def gated(values, coverage, finish, **kwargs):
        job = real(values, coverage, finish, **kwargs)
        if job is not None and not held:
            held.append(job)
            run = job.run

            def run_held(should_stop):
                gate.wait(10)
                run(should_stop)

            job.run = run_held
        return job

    monkeypatch.setattr(engine, "pending_solve", gated)
    building: list[bool] = []
    real_fill = slices_engine.plan_fill

    def watching(*args, **kwargs):
        building.append(dock.refiner.busy)
        return real_fill(*args, **kwargs)

    monkeypatch.setattr(slices_engine, "plan_fill", watching)
    try:
        dock.slice_slider.setValue(20)
        _pump_until(lambda: dock.refiner.busy)  # rested; the solve is held
        combo = dock.palette_combo
        combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
        assert dock.provisional
        assert dock.refiner.busy, "a redraw of the slice being solved stopped its solve"
        assert not dock._grid_refine.rest.isActive()
        assert building == []
        _set_finish(dock, max_distance_spacings=dock.grid_finish.max_distance_spin.value() + 0.5)
        assert dock.provisional
        assert not dock.refiner.busy, "a solve on the dropped plan ran on"
        assert dock._grid_refine.rest.isActive()
        assert building and not any(building), "the old solve ran through the rebuild"
    finally:
        gate.set()
    _wait_for_refine(dock)
    assert len(starts) == 2
    assert not dock.provisional
    np.testing.assert_array_equal(dock.current_values(), _drawn_by_the_engine(dock, "finish"))


def test_a_rest_during_a_finish_edits_pause_builds_nothing(docked, monkeypatch):
    """Final review M-1. A finish edit waits out its pause (`_finish_debounce`)
    before it redraws, but the rest reads the panel live: a rest that ran out
    inside that pause built the new plan and its preview itself, in the rest's
    slot, with no wait cursor (about 6 s at 0.05 m). Such a rest does nothing:
    the edit's redraw rebuilds under the cursor and arms the rest again."""
    from nsgeo_qgis import slices_engine

    dock, _ = docked
    _minimum_curvature(dock, 500.0)
    starts = _starts(dock, monkeypatch)
    building: list[int] = []
    real_fill = slices_engine.plan_fill

    def watching(*args, **kwargs):
        building.append(1)
        return real_fill(*args, **kwargs)

    monkeypatch.setattr(slices_engine, "plan_fill", watching)
    dock.slice_slider.setValue(20)
    assert dock.provisional and dock._grid_refine.rest.isActive()
    spin = dock.grid_finish.max_distance_spin
    spin.setValue(spin.value() + 0.5)  # the edit's redraw now waits out its pause
    assert dock._finish_debounce.isActive()
    dock._grid_refine.rest.stop()
    dock._on_rest()  # the rest ran out inside that pause
    assert building == [], "the rest built the new plan itself"
    assert starts == [] and not dock.refiner.busy

    _wait_for_refine(dock)  # the edit's redraw rebuilds, and its rest refines
    assert building, "the edit's redraw built nothing"
    assert len(starts) == 1
    assert not dock.provisional
    np.testing.assert_array_equal(dock.current_values(), _drawn_by_the_engine(dock, "finish"))


class _Looping:
    """A refine job that runs until it is asked to stop, or 10 s pass."""

    key = b"looping"
    engine = None

    def __init__(self) -> None:
        self.started = threading.Event()
        self.thread: threading.Thread | None = None
        self.stopped_by_request = False

    def run(self, should_stop) -> None:
        self.thread = threading.current_thread()
        self.started.set()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if should_stop():
                self.stopped_by_request = True
                return
            time.sleep(0.001)

    def land(self) -> bool:
        return False


def test_unloading_mid_refine_stops_the_worker(fake_iface, tmp_path, answer_modal, monkeypatch):
    """Review Focus 3: closing QGIS mid-refine stops and joins the worker
    before any engine is disposed. Nothing may escape to `sys.excepthook` or
    `sys.unraisablehook` (conftest's autouse guard fails the test if it does)."""
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    unloaded = False
    try:
        session = plugin.session
        session.new_site(tmp_path)
        session.add_grid(GRID)
        session.add_lines(
            [
                Line.open(
                    synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60),
                    GridPlacement("A", "y", 1.0 + i, 0.0, 1, f"L{i}"),
                )
                for i in range(3)
            ]
        )
        session.site.presets["p"] = list(PRESET)
        session.presets_changed.emit()
        dock = plugin.slices_dock
        _ready(dock)
        job = _Looping()
        monkeypatch.setattr(dock.engine, "pending_solve", lambda *args, **kwargs: job)
        _set_finish(dock, method="min_curvature")  # a new plan's first draw is a preview
        assert dock.provisional
        _pump_until(job.started.is_set)
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.unload()
        unloaded = True
        assert job.stopped_by_request, "unload did not ask the solve to stop"
        # This dock's own worker, as the job saw it: other tests' refiners
        # may legitimately still have threads of the same name.
        worker = job.thread
        assert worker is not None and worker.name.startswith("nsgeo-refine")
        _pump_until(lambda: not worker.is_alive(), 2.0)
        gc.collect()
        _pump_for(0.05)
    finally:
        if not unloaded:
            answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
            plugin.unload()


# ---- the refine indicator (walkthrough round 1, W1-W3) ---------------------------


def _slow_unsolved(dock, monkeypatch):
    """Minimum curvature on a shared stretch with nothing solved yet and every
    solve slow, so a move runs preview, refine slice, measure stretch."""
    _ready(dock)
    _minimum_curvature(dock, 500.0, stretch="shared across the cube")
    engine = dock.engine
    engine._solved.clear()
    dock._grid_refine.stretch = None
    engine._last_solve_ms = 500.0
    slow_jobs(monkeypatch, engine, ("pending_solve", "stretch_solves"))


@pytest.mark.parametrize("width", ["narrow", "wide"])
def test_the_refine_states_do_not_move_the_panel_under_the_wheel(docked, monkeypatch, width):
    """W1: the content's height and the slider's place do not change as a slice
    goes normal, preview, refining the slice, measuring the stretch, final. The
    old bottom status line changed height between them (47, 70, 24 px)."""
    dock, _ = docked
    dock.setFloating(True)
    dock.resize(layout_width(dock, width), 700)
    dock.show()
    _slow_unsolved(dock, monkeypatch)
    probe = LayoutProbe(dock)
    baseline = probe.settle()
    probe.assert_indicator_shares_the_readouts_row()
    dock.slice_slider.setValue(20)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        probe.record()
        if not (dock.provisional or dock.refiner.busy or dock._grid_refine.rest.isActive()):
            break
        time.sleep(0.005)
    probe.record()
    texts = {text for text, _ in probe.seen}
    assert PREVIEW_INDICATOR in texts
    assert REFINING_SLICE_INDICATOR in texts
    assert any(t.startswith("Colour stretch (") for t in texts), texts
    assert probe.seen[-1][0] == ""
    assert {sample for _, sample in probe.seen} == {baseline}, probe.seen


def test_the_indicator_names_each_state_and_the_status_never_does(docked, monkeypatch):
    dock, _ = docked
    _slow_unsolved(dock, monkeypatch)
    assert dock.refine_label.text() == ""
    dock.slice_slider.setValue(20)
    assert dock.refine_label.text() == PREVIEW_INDICATOR
    stretch_total = len(
        dock.engine.stretch_solves(dock.current_window().n_levels, dock.slice_finish())
    )
    counts: list[str] = []
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        text = dock.refine_label.text()
        assert "Refin" not in dock.status_label.text()
        assert "preview" not in dock.status_label.text().lower()
        if text and (not counts or counts[-1] != text):
            counts.append(text)
        if text == "" and not dock.refiner.busy and not dock.provisional:
            break
        time.sleep(0.002)
    assert counts[0] == PREVIEW_INDICATOR
    assert counts[1] == REFINING_SLICE_INDICATOR
    measuring = [c for c in counts if c.startswith("Colour stretch")]
    # Counts the stretch windows only: the slice on screen is one of them and
    # is solved already, so the list holds one fewer than were unsolved.
    total = stretch_total - 1
    assert measuring[0] == MEASURING_STRETCH_INDICATOR.format(done=0, total=total)
    assert measuring[-1] == MEASURING_STRETCH_INDICATOR.format(done=total - 1, total=total)
    assert dock.refine_label.text() == ""


def test_the_indicator_never_raises_the_dock_minimum_width(docked):
    """Its text width is not a floor on the main window (the walkthrough's
    minimum-size trap). The scroll area pins the dock's own minimum, so the
    claim is on the scrolled content's: the longest text must not raise it."""
    dock, _ = docked
    _ready(dock)
    dock.setFloating(True)
    dock.show()
    probe = LayoutProbe(dock)
    probe.settle()
    content = probe.scroll.widget()
    before = content.minimumSizeHint().width()
    longest = MEASURING_STRETCH_INDICATOR.format(done=9999, total=9999) + " and then some " * 6
    dock.refine_label.setText(longest)
    probe.settle()
    assert content.minimumSizeHint().width() == before
    assert dock.refine_label.text() == longest
    assert dock.refine_label.toolTip() == longest, "an elided text is readable in the tooltip"


def test_the_dock_layout_probe_sees_the_width_it_is_given(docked):
    dock, _ = docked
    dock.setFloating(True)
    dock.show()
    probe = LayoutProbe(dock)
    widths = []
    for width in ("narrow", "wide"):
        dock.resize(layout_width(dock, width), 700)
        probe.settle()
        widths.append(probe.scroll.widget().width())
    assert widths[1] > widths[0], widths


def test_the_indicator_follows_a_stylesheet_font_and_clear(qgis_app):
    from nsgeo_qgis.ui.slices_dock import ElidedLabel
    from qgis.PyQt.QtWidgets import QVBoxLayout, QWidget

    host = QWidget()
    QVBoxLayout(host).addWidget(label := ElidedLabel("Refining…"))
    host.setStyleSheet("* { font: 20pt; }")
    host.show()
    QCoreApplication.processEvents()
    QCoreApplication.processEvents()
    assert label.height() >= label.fontMetrics().height()
    label.clear()
    assert label.text() == ""
    host.close()


def test_a_list_for_a_slice_left_behind_does_not_name_it(docked, monkeypatch):
    """Moving back to a solved slice while the one left is still solving: the
    draw on screen is final, so the indicator must not say "Refining…"."""
    dock, _ = docked
    _ready(dock)
    _slow_unsolved(dock, monkeypatch)
    dock.slice_slider.setValue(20)
    deadline = time.monotonic() + 30.0
    while dock.provisional or dock.refiner.busy or dock._grid_refine.rest.isActive():
        assert time.monotonic() < deadline
        QCoreApplication.processEvents()
        time.sleep(0.002)
    dock.engine._last_solve_ms = 500.0
    dock.slice_slider.setValue(26)  # unsolved: a preview, then its refine
    deadline = time.monotonic() + 30.0
    while dock.refine_label.text() != REFINING_SLICE_INDICATOR:
        assert time.monotonic() < deadline
        QCoreApplication.processEvents()
        time.sleep(0.002)
    dock.slice_slider.setValue(20)  # solved: drawn in full at once
    QCoreApplication.processEvents()
    assert not dock.provisional
    assert dock.refine_label.text() != REFINING_SLICE_INDICATOR
    assert dock.refine_label.text() == "" or dock.refine_label.text().startswith("Colour stretch")
    deadline = time.monotonic() + 30.0
    while dock.refiner.busy:
        assert time.monotonic() < deadline
        QCoreApplication.processEvents()
        time.sleep(0.002)
    QCoreApplication.processEvents()
    # Nothing left to say, so neither the line nor its tooltip says anything.
    assert dock.refine_label.text() == ""
    assert dock.refine_label.toolTip() == ""


# ---- line editing (spec §4.5) ------------------------------------------------


def test_a_line_moved_off_the_grid_leaves_an_explicit_choice(docked_two_grids):
    dock, session = docked_two_grids
    a_keys = _grid_keys(session, "A")
    dock.set_included(a_keys[:2])
    assert dock.engine.wait_for_preparation(20_000)

    session.move_lines([a_keys[1]], "B")
    assert dock.included_keys() == (a_keys[0],)
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.source_status.text() == "prepared \u00b7 1 lines"


def test_a_line_moved_onto_a_default_grid_re_prepares_it(docked_two_grids):
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    b_key = _grid_keys(session, "B")[0]

    session.move_lines([b_key], "A")
    assert dock.engine.wait_for_preparation(20_000)
    assert b_key in dock.engine.choice.line_keys
    assert dock.engine.line_count == 4
    assert dock.source_status.text().startswith("prepared")


def test_a_line_imported_onto_a_default_grid_still_shows_stale(docked_two_grids, tmp_path):
    """Today's behaviour, pinned: an imported line was never in the engine's
    snapshot, so nothing re-prepares for it."""
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    session.add_lines([_line(tmp_path, "A", "FILE__099", 9.0)])
    assert not dock.engine.is_running
    assert dock.source_status.text().startswith("stale")


def test_restoring_a_cube_drops_a_line_now_on_another_grid_and_says_so(docked_two_grids):
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    a_keys = _grid_keys(session, "A")
    _save_cube(
        dock, session, "A__m", ViewSettings(1.0, 1.0, 0.0, "amp_black_high", "this slice", False)
    )
    session.move_lines([a_keys[2]], "B")
    assert dock.engine.wait_for_preparation(20_000)
    errors: list[str] = []
    dock.error.connect(errors.append)

    dock.restore_cube("A__m")
    assert dock.engine.wait_for_preparation(20_000)
    assert a_keys[2] not in dock.included_keys()
    assert any("moved to another grid since it was saved" in e for e in errors), errors


def test_a_reorder_alone_is_no_change_to_a_default_source(docked_two_grids):
    """Line editing spec §4.5: a cube is a sum over lines, so the survey
    order is not part of what it was built from. No re-preparation, and no
    false "stale" with no Prepare button to clear it."""
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    a_keys = _grid_keys(session, "A")
    before = dock.engine.choice
    count = []
    inner = dock.engine.on_prepared
    dock.engine.on_prepared = lambda: (count.append(1), inner())

    session.edit_lines([], grid_id="A", order=list(reversed(a_keys)))
    assert dock.included_keys() == tuple(reversed(a_keys))
    assert not dock.engine.is_running
    assert dock.engine.wait_for_preparation(2_000)
    assert count == []
    assert dock.engine.choice == before
    assert dock.source_status.text() == "prepared · 3 lines"


def test_a_reorder_with_an_offset_edit_re_prepares_once_and_reads_prepared(docked_two_grids):
    from nsgeo_qgis.line_edit import LineEdit

    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    a_keys = _grid_keys(session, "A")
    count = []
    inner = dock.engine.on_prepared
    dock.engine.on_prepared = lambda: (count.append(1), inner())

    session.edit_lines(
        [LineEdit(a_keys[0], session.line_for_key(a_keys[0]).placement, offset=1.5)],
        grid_id="A",
        order=list(reversed(a_keys)),
    )
    assert dock.engine.wait_for_preparation(20_000)
    assert count == [1]
    assert dock.engine.choice.line_keys == tuple(reversed(a_keys))
    assert dock.source_status.text() == "prepared · 3 lines"


# ---- #97: cubes on the time-zero clock ------------------------------------


def _owed_record(dock, session, cube_id="A__old", time_base=None, z=None):
    """A record as an earlier build wrote it: no `time_base`, z on the radar clock."""
    record = _save_cube(
        dock, session, cube_id, ViewSettings(1.0, 1.0, 0.0, "amp_black_high", "this slice", False)
    )
    record.pop("time_base", None)
    if time_base is not None:
        record["time_base"] = time_base
    record["z"] = z or {"t0_ns": 5.0, "t1_ns": 40.0, "dz_ns": 0.5}
    return record


def test_a_cube_built_with_time_zero_starts_at_zero(docked_zeroed):
    dock, _session = docked_zeroed
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.prepared_z_bounds()[0] == 0.0
    assert dock.z0_spin.value() == 0.0


def _prepared_with_owed_record(dock, session, clear=True, **kw):
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    _owed_record(dock, session, **kw)
    if clear:
        dock.engine.clear()


def _clock_start_record(dock, session, cube_id="A__old"):
    """An old record built the way the old clock saved it, with no `time_base`:
    z0 the latest-starting line's radar-clock start (below 0), z1 the radar-clock
    end every line shares (the line that crops the most rows ends first on the
    new clock, at `high`), slices one sample apart. Shifted by a median zero
    below the latest one, its end overshoots `high`, so only the clamp after
    the shift keeps the cube inside the data (final review residual R-a)."""
    keys = dock.engine.choice.line_keys
    zeros = [dock.engine.line_zero(k) for k in keys]
    low, high = dock.engine.prepared_z_bounds()
    dt = session.line_for_key(keys[0]).header.dt_ns
    z = {"t0_ns": low + max(zeros), "t1_ns": high + max(zeros), "dz_ns": dt}
    assert z["t0_ns"] < 0.0, z
    return _owed_record(dock, session, cube_id=cube_id, z=z)


def _assert_a_clean_old_restore(dock, errors):
    median = dock.engine.median_zero()
    assert not [m for m in errors if "does not cover" in m or "could not" in m], errors
    assert errors.count(old_cube_note(-median)) == 1, errors
    low, high = dock.engine.prepared_z_bounds()
    assert low - 1e-9 <= dock.engine.z.t0_ns < dock.engine.z.t_end_ns <= high + 1e-9
    assert dock.current_values() is not None


def test_a_realistic_old_record_restores_inside_the_bounds_when_the_engine_holds_its_source(
    docked_banded,
):
    dock, session = docked_banded
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    zeros = [dock.engine.line_zero(k) for k in dock.engine.choice.line_keys]
    assert len({round(z, 6) for z in zeros}) == 2, zeros  # one sample apart
    record = _clock_start_record(dock, session)
    errors: list[str] = []
    dock.error.connect(errors.append)

    dock.restore_cube("A__old")
    assert not dock.engine.is_running

    _assert_a_clean_old_restore(dock, errors)
    # The grid remembers the record's range moved onto the time-zero clock, not
    # its radar-clock one. Like any restore it remembers the record's range,
    # not the clamped one on show: the clamp is no edit (`_clamp_z_to_prepared`),
    # so a later change that frees the data brings the record's end back.
    median = dock.engine.median_zero()
    remembered = session.slice_resolution("A")
    spin = 5e-4  # the z spins hold three decimals
    for end in ("t0_ns", "t1_ns"):
        shifted = retime_ns(record["z"][end], 0.0, median)
        assert remembered[end] == pytest.approx(shifted, abs=spin)
    assert dock.z1_spin.value() < remembered["t1_ns"]  # the shifted end overshot


def test_a_realistic_old_record_restores_inside_the_bounds_when_a_preparation_runs(
    docked_banded,
):
    dock, session = docked_banded
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    _clock_start_record(dock, session)
    dock.engine.clear()
    errors: list[str] = []
    dock.error.connect(errors.append)

    dock.restore_cube("A__old")
    assert dock.engine.wait_for_preparation(20_000)

    _assert_a_clean_old_restore(dock, errors)


@needs_real_data
def test_a_real_data_old_record_restores_without_a_coverage_error(qgis_app, tmp_path):
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(Grid("A", (0.0, 0.0), 0.0, 3.0, 12.0, "EPSG:32616", 0.5))
    session.add_lines(
        [
            Line.open(REAL_DZT[i], GridPlacement("A", "y", 0.5 + i * 0.5, 0.0, 1, REAL_DZT[i].stem))
            for i in range(4)
        ]
    )
    session.site.presets["p"] = [
        {"step": "time_zero", "params": {}, "enabled": True},
        {"step": "dewow", "params": {}, "enabled": True},
    ]
    session.presets_changed.emit()
    dock = SlicesDock(session)
    try:
        assert dock.engine.wait_for_preparation(60_000)
        dock.flush_debounce()
        assert dock.engine.wait_for_preparation(60_000)
        _clock_start_record(dock, session)
        errors: list[str] = []
        dock.error.connect(errors.append)

        dock.restore_cube("A__old")
        assert dock.engine.wait_for_preparation(60_000)

        _assert_a_clean_old_restore(dock, errors)
    finally:
        dock.engine.wait_for_preparation(60_000)
        dock.engine.dispose()
        dock.deleteLater()


def test_the_owed_shift_survives_a_switch_to_whole_site_before_the_preparation_lands(
    docked_zeroed,
):
    dock, session = docked_zeroed
    _prepared_with_owed_record(dock, session)
    errors: list[str] = []
    dock.error.connect(errors.append)
    dock.restore_cube("A__old")
    assert dock._pending_z_shift is True
    dock._scope = "site"
    try:
        dock._on_prepared()  # the preparation lands while Whole site is showing
    finally:
        dock._scope = "grid"
    assert dock._pending_z_shift is True
    assert not errors.count(old_cube_note(-(dock.engine.median_zero() or 0.0)))

    assert dock.engine.wait_for_preparation(20_000)
    dock._on_prepared()  # This grid's preparation lands

    _assert_shifted_once(dock, errors)


def test_the_owed_shift_helper_steps_aside_while_a_preparation_runs(docked_zeroed):
    dock, session = docked_zeroed
    _prepared_with_owed_record(dock, session)  # engine cleared: the restore dispatches
    errors: list[str] = []
    dock.error.connect(errors.append)
    dock.restore_cube("A__old")
    assert dock.engine.is_running
    assert dock._pending_z_shift is True

    dock._apply_owed_z_shift()  # must not consume the flag or say anything

    assert dock._pending_z_shift is True
    assert not [m for m in errors if "first break" in m], errors
    assert dock.engine.wait_for_preparation(20_000)
    _assert_shifted_once(dock, errors)


def _assert_shifted_once(dock, errors):
    median = dock.engine.median_zero()
    assert median is not None
    assert dock.z0_spin.value() == pytest.approx(5.0 - median, abs=1e-3)
    assert dock.z1_spin.value() == pytest.approx(40.0 - median, abs=1e-3)
    # The engine, not just the spins: the slice and Save cube read this.
    assert dock.engine.z.t0_ns == pytest.approx(5.0 - median, abs=1e-3)
    assert errors.count(old_cube_note(-median)) == 1, errors
    assert dock._pending_z_shift is False


def test_an_old_recipe_with_time_zero_restores_its_range_moved_by_the_median_zero(docked_zeroed):
    dock, session = docked_zeroed
    _prepared_with_owed_record(dock, session)
    errors: list[str] = []
    dock.error.connect(errors.append)

    dock.restore_cube("A__old")
    assert dock.engine.wait_for_preparation(20_000)

    _assert_shifted_once(dock, errors)


def test_an_old_recipe_restores_shifted_when_the_engine_already_holds_its_source(docked_zeroed):
    """The ordinary case: `prepare()` is a no-op, so no `_on_prepared` follows."""
    dock, session = docked_zeroed
    _prepared_with_owed_record(dock, session, clear=False)
    errors: list[str] = []
    dock.error.connect(errors.append)

    dock.restore_cube("A__old")
    assert not dock.engine.is_running

    _assert_shifted_once(dock, errors)


def test_an_old_recipe_keeps_its_shift_while_a_preparation_is_owed(docked_zeroed):
    dock, session = docked_zeroed
    _prepared_with_owed_record(dock, session, clear=False)
    errors: list[str] = []
    dock.error.connect(errors.append)
    dock._grid_prepare_pending = True  # R-P5: a site task is still live
    dock.restore_cube("A__old")
    assert dock._pending_z_shift is True

    dock._run_pending_grid_prepare()  # the engine holds the source: a no-op prepare

    _assert_shifted_once(dock, errors)

    # Exactly once: a later unrelated preparation leaves a user-set range alone.
    for spin, value in ((dock.z0_spin, 20.0), (dock.z1_spin, 30.0)):
        spin.setValue(value)
    dock.flush_debounce()
    dock._on_prepared()
    assert dock.z0_spin.value() == pytest.approx(20.0, abs=1e-3)
    assert dock.z1_spin.value() == pytest.approx(30.0, abs=1e-3)
    assert errors.count(old_cube_note(-dock.engine.median_zero())) == 1


def test_rebuilding_the_source_drops_an_owed_shift(docked_zeroed):
    dock, _session = docked_zeroed
    dock._pending_z_shift = True
    dock.rebuild_source()
    assert dock._pending_z_shift is False


def test_a_failed_line_does_not_drop_the_shift(docked_zeroed, tmp_path):
    dock, session = docked_zeroed
    _prepared_with_owed_record(dock, session)
    next(iter(sorted((tmp_path / "raw").glob("*.DZT")))).rename(tmp_path / "raw" / "gone.x")
    errors: list[str] = []
    dock.error.connect(errors.append)

    dock.restore_cube("A__old")
    assert dock.engine.wait_for_preparation(20_000)

    assert dock.engine.line_count == 2
    _assert_shifted_once(dock, errors)


def test_a_marked_record_is_not_shifted(docked_zeroed):
    dock, session = docked_zeroed
    _prepared_with_owed_record(dock, session, time_base="time_zero")
    errors: list[str] = []
    dock.error.connect(errors.append)

    dock.restore_cube("A__old")
    assert dock.engine.wait_for_preparation(20_000)

    assert dock.z0_spin.value() == pytest.approx(5.0, abs=1e-3)
    assert dock.z1_spin.value() == pytest.approx(40.0, abs=1e-3)
    assert not [m for m in errors if "first break" in m], errors


def test_an_old_recipe_without_time_zero_restores_unchanged(docked):
    dock, session = docked
    _prepared_with_owed_record(dock, session)
    errors: list[str] = []
    dock.error.connect(errors.append)

    dock.restore_cube("A__old")
    assert dock.engine.wait_for_preparation(20_000)

    assert dock.z0_spin.value() == pytest.approx(5.0, abs=1e-3)
    assert dock.z1_spin.value() == pytest.approx(40.0, abs=1e-3)
    assert not [m for m in errors if "first break" in m], errors


def test_an_old_recipe_with_nothing_prepared_is_not_shifted(docked_zeroed, tmp_path, message_log):
    dock, session = docked_zeroed
    _prepared_with_owed_record(dock, session)
    for path in (tmp_path / "raw").glob("*.DZT"):
        path.rename(path.with_suffix(".gone"))
    errors: list[str] = []
    dock.error.connect(errors.append)

    dock.restore_cube("A__old")
    dock.engine.wait_for_preparation(20_000)

    assert dock.engine.median_zero() is None
    assert dock.z0_spin.value() == pytest.approx(5.0, abs=1e-3)
    assert not [m for m in errors if "first break" in m], errors
    assert dock._pending_z_shift is False
    assert not [m for m in message_log if "could not" in m], message_log


def test_the_slice_band_marks_the_same_samples_on_a_line_whose_stack_differs(
    docked_zeroed, qgis_app
):
    """The band is on the cube clock. A line with no steps (radar clock) draws
    it at (10 + line_zero, 12 + line_zero); a line with the cube's own time-zero
    step draws it at (10, 12), through `set_slice_band` and through a repaint."""
    from nsgeo.processing import build_step
    from nsgeo_qgis.ui.profile_dock import ProfileDock

    dock, session = docked_zeroed
    assert dock.engine.wait_for_preparation(20_000)
    profile = ProfileDock(session)
    profile.set_cube_zero_lookup(dock.line_zero_in_cube)
    try:
        key = session.keys()[0]
        zero = dock.line_zero_in_cube(key)
        assert zero is not None
        assert zero != 0.0
        session.set_profiles(key, session.line_for_key(key).load())
        session.open_line(key)
        assert profile._shown_radargram is not None
        assert profile.shown_zero_ns() == 0.0
        profile.set_slice_band(10.0, 12.0)
        lo, hi = profile.view._slice_band
        assert lo == pytest.approx(10.0 + zero)
        assert hi == pytest.approx(12.0 + zero)

        # The same line with the cube's own step: shown zero == cube zero.
        session.append_step(key, build_step("time_zero"))
        assert profile.shown_zero_ns() == pytest.approx(zero)
        profile.view._slice_band = None  # a repaint alone must redraw it
        profile._render()
        assert profile.view._slice_band == pytest.approx((10.0, 12.0))

        profile.clear_slice_band()
        profile._render()
        assert profile.view._slice_band is None
    finally:
        profile.hide()
        profile.deleteLater()


@pytest.mark.skipif(len(GRID2_LINES) < 3, reason="needs Grid 2 in tests/data/local/grid2")
def test_real_grid2_slice_depth_follows_the_grid_with_an_override_on_the_first_line(
    qgis_app, tmp_path, message_log
):
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(Grid("G2", (500.0, 700.0), 0.0, 2.0, 29.96, "EPSG:32616", 0.5))
    session.add_lines(
        [
            Line.open(p, GridPlacement("G2", "y", 0.25 + 0.5 * k, 0.0, 1, p.stem))
            for k, p in enumerate(GRID2_LINES[:3])
        ]
    )
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()
    session.set_grid_velocity("G2", VelocityModel.constant(0.09))
    session.set_line_velocity(session.keys_on_grid("G2")[0], VelocityModel.constant(0.12))
    dock = SlicesDock(session)
    try:
        _ready(dock)
        dock.thickness_spin.setValue(4.0)
        dock.slice_slider.setValue(10)
        assert dock.velocity_label.text() == "v = 0.090 m/ns (Grid G2)"
        assert dock.engine.provenance().velocity == VelocityModel.constant(0.09).to_dict()
        lo_m, hi_m = window_depths_m(
            dock.engine.z, dock.current_window(), VelocityModel.constant(0.09)
        )
        assert f"{lo_m:.2f}" in dock.readout.text()
        assert message_log == []
    finally:
        dock.engine.wait_for_preparation(60_000)
        dock.engine.dispose()
        dock.deleteLater()


# ---- #180: a saved cube carries This grid's colours ---------------------------------------


def test_view_settings_carry_this_grids_colours(docked):
    dock, session = docked
    assert (dock.view_settings().colours, dock.view_settings().style) == ("nsgeo", None)
    session.set_slice_colours("grid", own=True, style="<qgis>mine</qgis>")
    session.set_slice_colours("site", own=False, style="<qgis>site</qgis>")
    view = dock.view_settings()
    assert (view.colours, view.style) == ("own", "<qgis>mine</qgis>")


def test_apply_view_restores_the_colours_and_an_older_record_leaves_them(docked):
    dock, session = docked
    view = dock.view_settings()
    dock.apply_view(
        dataclasses.replace(view, colours="own", style="<qgis>mine</qgis>"), spacing_m=0.5
    )
    assert session.slice_colours("grid") == {"own": True, "style": "<qgis>mine</qgis>"}
    assert dock.colours_combo.currentIndex() == 1 and not dock.stretch_combo.isEnabled()
    dock.apply_view(dataclasses.replace(view, colours=None, style=None), spacing_m=0.5)
    assert session.slice_colours("grid")["own"] is True
    dock.apply_view(dataclasses.replace(view, colours="nsgeo", style=None), spacing_m=0.5)
    assert session.slice_colours("grid") == {"own": False, "style": "<qgis>mine</qgis>"}
    assert dock.colours_combo.currentIndex() == 0 and dock.stretch_combo.isEnabled()


def test_the_colours_choice_needs_an_open_survey(qgis_app):
    dock = SlicesDock(SiteSession())
    try:
        assert not dock.colours_combo.isEnabled()
        assert not dock.own_colours_on() and dock.own_style() is None
    finally:
        dock.engine.dispose()
        dock.deleteLater()


def test_a_cube_saved_under_the_plugin_colours_keeps_no_style(docked):
    """Review finding 6: restoring it must not replace a style refined since."""
    dock, session = docked
    session.set_slice_colours("grid", own=False, style="<qgis>refined</qgis>")
    view = dock.view_settings()
    assert (view.colours, view.style) == ("nsgeo", None)
    dock.apply_view(view, spacing_m=0.5)
    assert session.slice_colours("grid") == {"own": False, "style": "<qgis>refined</qgis>"}


def test_the_symbology_button_is_off_while_coverage_shows(docked):
    """Review finding 5: an edit on the coverage colours would be lost."""
    dock, session = docked
    dock.colours_combo.setCurrentIndex(1)
    assert dock.symbology_button.isEnabled()
    dock.coverage_check.setChecked(True)
    assert not dock.symbology_button.isEnabled()
    assert "Show coverage" in dock.symbology_button.toolTip()
    dock.coverage_check.setChecked(False)
    assert dock.symbology_button.isEnabled()


# ---- the wheel rule (#177) ----

GUARDED = ("cell_spin", "dz_spin", "z0_spin", "z1_spin")


def _short_and_active(dock):
    """Floated short enough to scroll, shown and active, so focus is real."""
    dock.setFloating(True)
    dock.resize(420, 300)
    dock.show()
    dock.activateWindow()
    assert QTest.qWaitForWindowActive(dock)
    scroll = dock.findChild(QScrollArea)
    scroll.verticalScrollBar().setValue(0)
    return scroll


@pytest.mark.parametrize("name", GUARDED)
def test_the_wheel_over_an_unfocused_resolution_box_scrolls_the_panel_and_changes_nothing(
    docked, name
):
    dock, _ = docked
    _ready(dock)
    scroll = _short_and_active(dock)
    dock.slice_slider.setFocus()
    values = {n: getattr(dock, n).value() for n in GUARDED}
    z, frame = dock.engine.z, dock.engine.frame
    event = wheel_event(-120)
    QApplication.sendEvent(getattr(dock, name), event)
    assert not event.isAccepted()  # not swallowed: left for the parents
    taker = propagate_wheel(getattr(dock, name))
    QTest.qWait(200)  # past the 120 ms debounce
    assert taker in (scroll, scroll.viewport())
    assert scroll.verticalScrollBar().value() > 0  # the panel scrolled
    assert {n: getattr(dock, n).value() for n in GUARDED} == values
    assert dock.engine.z is z and dock.engine.frame is frame  # nothing re-prepared


def test_a_focused_resolution_box_still_takes_the_wheel(docked):
    dock, _ = docked
    _ready(dock)
    _short_and_active(dock)
    dock.dz_spin.setFocus()
    assert dock.dz_spin.hasFocus()
    before = dock.dz_spin.value()
    QApplication.sendEvent(dock.dz_spin, wheel_event(120))
    assert dock.dz_spin.value() == pytest.approx(before + dock.dz_spin.singleStep(), abs=1e-4)


def test_scrolling_the_panel_lets_go_of_the_box_you_typed_in(docked):
    dock, _ = docked
    _ready(dock)
    scroll = _short_and_active(dock)
    dock.dz_spin.setFocus()
    dock.dz_spin.selectAll()
    QTest.keyClicks(dock.dz_spin, "0.75")
    QApplication.sendEvent(scroll.viewport(), wheel_event(-120))
    assert not dock.dz_spin.hasFocus()
    assert dock.dz_spin.value() == 0.75
    assert scroll.verticalScrollBar().value() > 0
    QApplication.sendEvent(dock.dz_spin, wheel_event(-120))
    assert dock.dz_spin.value() == 0.75


def test_the_resolution_boxes_take_focus_only_by_click_or_tab(docked):
    dock, _ = docked
    for name in GUARDED:
        assert getattr(dock, name).focusPolicy() == Qt.FocusPolicy.StrongFocus
    # the rule reaches only the four: the thickness box keeps Qt's default
    assert dock.thickness_spin.focusPolicy() == Qt.FocusPolicy.WheelFocus


def test_the_panel_moving_on_its_own_keeps_the_focus(docked):
    dock, _ = docked
    _ready(dock)
    scroll = _short_and_active(dock)
    dock.dz_spin.setFocus()
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    scroll.ensureWidgetVisible(dock.display_group)
    assert dock.dz_spin.hasFocus()
    scroll.verticalScrollBar().triggerAction(QAbstractSlider.SliderAction.SliderSingleStepSub)
    assert not dock.dz_spin.hasFocus()  # a keyboard/arrow scroll is a user scroll


def test_the_thickness_box_keeps_todays_wheel(docked):
    dock, _ = docked
    _ready(dock)
    _short_and_active(dock)
    dock.slice_slider.setFocus()
    before = dock.thickness_spin.value()
    QApplication.sendEvent(dock.thickness_spin, wheel_event(120))
    assert dock.thickness_spin.value() != before


def test_a_restored_cube_below_its_grids_floor_comes_back_at_the_floor(qgis_app, tmp_path):
    session = SiteSession()
    session.new_site(tmp_path)
    big = Grid("Big", (500.0, 700.0), 0.0, 300.0, 300.0, "EPSG:32616", 0.5)
    session.add_grid(GRID)
    session.add_grid(big)
    session.add_lines([_line(tmp_path, "A", "FILE__001", 1.0)])
    session.add_lines([_line(tmp_path, "Big", "FILE__010", 1.0)])
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()
    session.save()
    dock = SlicesDock(session)
    errors: list[str] = []
    dock.error.connect(errors.append)
    try:
        dock.grid_combo.setCurrentText("Big")
        dock.prepare()
        assert dock.engine.wait_for_preparation(20_000)
        dock.flush_debounce()
        record = _save_cube(dock, session, "cube1", dock.view_settings())
        record["cell"] = 0.05
        dock.grid_combo.setCurrentText("A")
        dock.prepare()
        assert dock.engine.wait_for_preparation(20_000)
        dock.flush_debounce()

        dock.restore_cube("cube1")
        assert dock.engine.wait_for_preparation(20_000)
        dock.flush_debounce()

        assert dock.cell_spin.value() == pytest.approx(smallest_safe_cell(300.0, 300.0), abs=1e-3)
        assert dock.warnings_panel.entries() == ()
        assert errors == []
        assert session.site.cubes["cube1"]["cell"] == 0.05
    finally:
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.deleteLater()


def test_a_warning_coming_and_going_keeps_the_box_you_type_in(docked):
    dock, _ = docked
    _ready(dock)  # preparation done, so nothing clears the entries behind the test
    scroll = _short_and_active(dock)
    bar = scroll.verticalScrollBar()
    dock.warnings_panel.set_entries([Entry(REFUSAL, "x " * 200)])
    QApplication.processEvents()
    assert dock.warnings_panel.isVisibleTo(dock)
    bar.setValue(bar.maximum())
    assert bar.value() > 0
    dock.dz_spin.setFocus()
    dock.dz_spin.setValue(0.75)
    before = bar.value()
    dock.warnings_panel.set_entries([])  # the range shrinks under the value
    QTest.qWait(100)
    assert bar.value() != before, "the scroll value moved, so the hazard was exercised"
    assert dock.dz_spin.hasFocus()
    assert dock.dz_spin.value() == 0.75


def test_a_long_warning_never_widens_the_panel(docked):
    dock, _ = docked
    _ready(dock)
    dock.setFloating(True)
    dock.show()
    content = dock.findChild(QScrollArea).widget()
    QApplication.processEvents()
    before = content.minimumSizeHint().width()
    dock.warnings_panel.set_entries([Entry(REFUSAL, "x" * 400)])
    QApplication.processEvents()
    assert dock.warnings_panel.isVisibleTo(dock)
    assert content.minimumSizeHint().width() == before


# ---- #177: dz floors at the sample interval; a cube past twice its samples is refused ----


def _first_dt(session, grid_id=None):
    keys = session.keys() if grid_id is None else _grid_keys(session, grid_id)
    return session.line_for_key(keys[0]).header.dt_ns


def test_dz_cannot_go_below_the_sample_interval_in_this_grid(docked):
    dock, session = docked
    assert dock.engine.wait_for_preparation(20_000)
    dt = _first_dt(session)
    assert dock.dz_spin.minimum() == pytest.approx(dt, abs=1e-4)
    dock.dz_spin.setValue(0.001)
    assert dock.dz_spin.value() == dock.dz_spin.minimum()
    dock.dz_spin.stepBy(1)
    assert dock.dz_spin.value() == pytest.approx(dock.dz_spin.minimum() + dt, abs=1e-4)


def _assert_at_the_floor_and_built(dock):
    """The box shows the floor and the cube built within the level limit."""
    dock.flush_debounce()
    assert dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert dock.dz_spin.value() == dock.dz_spin.minimum()
    assert dock.dz_spin.value() > 0.2
    assert dock.engine.z is not None
    assert dock.engine.z.nz <= 1024
    assert dock.warnings_panel.entries() == ()


def test_a_remembered_dz_below_the_floor_comes_back_at_the_floor(docked_two_grids):
    dock, session = docked_two_grids
    assert dock.engine.wait_for_preparation(20_000)
    session.remember_slice_resolution("A", dz_ns=0.001)
    dock.grid_combo.setCurrentText("B")
    assert dock.engine.wait_for_preparation(20_000)
    dock.grid_combo.setCurrentText("A")
    _assert_at_the_floor_and_built(dock)
    assert session.slice_resolution("A")["dz_ns"] == 0.001, "the record stands"


@pytest.fixture
def docked_fine_b(qgis_app, tmp_path):
    """Grid A as `docked`, and grid B recorded finer: 512 samples over 25 ns
    (0.0488 ns), so the two grids' dz floors differ."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    session.add_grid(GRID_B)
    session.add_lines([_line(tmp_path, "A", f"FILE__00{i + 1}", 1.0 + i) for i in range(3)])
    session.add_lines(
        [
            Line.open(
                synthetic_dzt(tmp_path / "raw", f"FINE__0{i}.DZT", n_traces=60, range_ns=25.0),
                GridPlacement("B", "y", 1.0 + i, 0.0, 1, f"FINE__0{i}"),
            )
            for i in range(2)
        ]
    )
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()
    session.save()
    dock = SlicesDock(session)
    yield dock, session
    dock.engine.wait_for_preparation(20_000)
    dock.engine.dispose()
    dock.deleteLater()


def test_a_saved_cube_with_dz_below_the_floor_restores_at_the_floor(docked_fine_b):
    dock, session = docked_fine_b
    _ready(dock)
    view = ViewSettings(1.0, 1.0, 0.0, "amp_black_high", "this slice", False)
    record = _save_cube(dock, session, "A__low", view)
    record["z"]["dz_ns"] = 0.001
    dock.grid_combo.setCurrentText("B")
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.dz_spin.minimum() == pytest.approx(25.0 / 512, abs=1e-4), "B's finer floor"
    dock.restore_cube("A__low")
    assert dock.grid_combo.currentText() == "A"
    assert dock.dz_spin.minimum() == pytest.approx(_first_dt(session, "A"), abs=1e-4)
    _assert_at_the_floor_and_built(dock)
    assert record["z"]["dz_ns"] == 0.001
    assert session.slice_resolution("A")["dz_ns"] == 0.001, "the record is remembered as saved"


@pytest.mark.parametrize("lines", ["none", "stale_first"])
def test_a_cube_record_without_usable_first_line_still_sets_its_grids_floor(docked_fine_b, lines):
    """A record with no `lines` key, or whose first key left the site, restored
    while the finer grid is shown: the floor is the cube grid's own."""
    dock, session = docked_fine_b
    _ready(dock)
    view = ViewSettings(1.0, 1.0, 0.0, "amp_black_high", "this slice", False)
    record = _save_cube(dock, session, "A__lines", view)
    if lines == "none":
        del record["lines"]
    else:
        record["lines"] = ["GONE__999", *record["lines"]]
    dock.grid_combo.setCurrentText("B")
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.dz_spin.minimum() == pytest.approx(25.0 / 512, abs=1e-4), "B's finer floor"
    dock.restore_cube("A__lines")
    assert dock.grid_combo.currentText() == "A"
    assert dock.dz_spin.minimum() == pytest.approx(_first_dt(session, "A"), abs=1e-4)
    dock.engine.wait_for_preparation(20_000)


def test_a_failed_apply_clears_the_refusal_the_last_one_left(docked, monkeypatch):
    dock, session = docked
    _ready(dock)
    errors: list[str] = []
    dock.error.connect(errors.append)
    dock.z1_spin.setValue(100_000.0)
    dock.flush_debounce()
    assert [e.kind for e in dock.warnings_panel.entries()] == [REFUSAL]

    def fail(resolution):
        raise RuntimeError("the engine failed")

    monkeypatch.setattr(dock.engine, "set_resolution", fail)
    dock.z1_spin.setValue(30.0)
    dock.flush_debounce()
    assert dock.warnings_panel.entries() == ()
    assert errors == ["the engine failed"]


def test_the_dz_floor_travels_with_the_scope(docked_fine_b):
    from nsgeo_qgis.ui.site_scope import capture_spins

    dock, session = docked_fine_b
    assert dock.engine.wait_for_preparation(20_000)
    before = capture_spins(dock).dz_min
    assert before == pytest.approx(_first_dt(session, "A"), abs=1e-4)
    dock.site_scope_button.click()
    assert dock.scope() == "site"
    assert dock.site_engine.wait_until_idle(60_000)
    QCoreApplication.processEvents()
    assert dock.dz_spin.minimum() == pytest.approx(25.0 / 512, abs=1e-4), "the site's floor"
    dock.grid_scope_button.click()
    assert dock.engine.wait_for_preparation(20_000)
    assert capture_spins(dock).dz_min == before


def test_a_z_range_past_the_level_limit_is_refused_in_this_grid_and_the_map_stays(docked):
    dock, session = docked
    _ready(dock)
    z = dock.engine.z
    errors: list[str] = []
    dock.error.connect(errors.append)
    dock.z1_spin.setValue(100_000.0)
    dock.flush_debounce()
    assert dock.engine.z is z
    entries = dock.warnings_panel.entries()
    assert [e.kind for e in entries] == [REFUSAL]
    assert entries[0].text.startswith("Too many levels: dz 0.5 ns from 2 to 100,000 ns")
    assert errors == []
    dock.z1_spin.setValue(30.0)
    dock.flush_debounce()
    assert dock.warnings_panel.entries() == ()
    assert dock.engine.z is not None and dock.engine.z.nz <= 1024


@needs_real_data
def test_real_lines_floor_at_0_2165_and_allow_1024_levels(qgis_app, tmp_path):
    session = SiteSession()
    session.new_site(tmp_path)
    grid = Grid("A", (0.0, 0.0), 0.0, 3.0, 12.0, "EPSG:32616", 0.5)
    session.add_grid(grid)
    session.add_lines(
        [
            Line.open(REAL_DZT[i], GridPlacement("A", "y", 0.5 + i * 0.5, 0.0, 1, REAL_DZT[i].stem))
            for i in range(4)
        ]
    )
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()
    dock = SlicesDock(session)
    try:
        dock.prepare()
        assert dock.engine.wait_for_preparation(30_000)
        assert dock.dz_spin.minimum() == pytest.approx(0.2165, abs=1e-4)
        samples = [session.line_for_key(k).header.n_samples for k in session.keys()]  # noqa: SIM118 -- SiteSession.keys()
        assert set(samples) == {512}
        seeded = Resolution(
            dock.cell_spin.value(),
            dock.dz_spin.minimum(),
            dock.z0_spin.value(),
            dock.z1_spin.value(),
        )
        assert level_limit_problem(seeded, samples) is None
        deep = dataclasses.replace(seeded, t1_ns=100_000.0)
        assert "1,024 (twice the 512 samples in each line)" in level_limit_problem(deep, samples)
    finally:
        dock.engine.wait_for_preparation(20_000)
        dock.engine.dispose()
        dock.deleteLater()


# ---- #157 item 6: sections that fold, and the coverage view explained ----

FOLDING = ("resolution_group", "grid_finish", "display_group")


def _shown(dock):
    dock.setFloating(True)
    dock.resize(420, 900)
    dock.show()
    QCoreApplication.processEvents()


@pytest.mark.parametrize("name", FOLDING)
def test_each_settings_section_folds_and_unfolds(docked, name):
    from qgis.gui import QgsCollapsibleGroupBox

    dock, _ = docked
    _ready(dock)
    _shown(dock)
    box = getattr(dock, name)
    assert isinstance(box, QgsCollapsibleGroupBox)
    open_height = box.height()
    box.setCollapsed(True)
    for _ in range(5):
        QCoreApplication.processEvents()
    assert box.isCollapsed()
    assert box.height() < open_height
    box.setCollapsed(False)
    for _ in range(5):
        QCoreApplication.processEvents()
    assert not box.isCollapsed()
    assert box.height() == open_height


def test_source_position_and_warnings_do_not_fold(docked):
    from qgis.gui import QgsCollapsibleGroupBox

    dock, _ = docked
    for name in ("source_group", "position_group", "warnings_panel"):
        assert not isinstance(getattr(dock, name), QgsCollapsibleGroupBox)


def test_every_section_starts_unfolded(docked):
    dock, _ = docked
    _shown(dock)
    boxes = [getattr(dock, n) for n in FOLDING]
    boxes += [dock.site_finish, dock.normalisation_panel.group]
    assert all(not b.isCollapsed() for b in boxes)


def test_the_two_interpolation_panels_fold_together(docked):
    dock, _ = docked
    _shown(dock)
    dock.grid_finish.setCollapsed(True)
    QCoreApplication.processEvents()
    # site_finish is hidden in This grid; QGIS applies its fold when it shows.
    assert dock.site_finish.isCollapsed()
    dock.grid_finish.setCollapsed(False)
    QCoreApplication.processEvents()
    assert not dock.site_finish.isCollapsed()


def test_folds_are_remembered_across_a_restart(docked):
    dock, session = docked
    _shown(dock)
    dock.display_group.setCollapsed(True)
    QCoreApplication.processEvents()
    assert folds.fold_settings().value("nsgeo/slices/folded/display", type=bool) is True
    again = SlicesDock(session)
    try:
        assert again.display_group.isCollapsed()
        assert not again.resolution_group.isCollapsed()
    finally:
        again.refiner.shutdown()
        again.engine.wait_for_preparation(20_000)
        again.engine.dispose()
        again.deleteLater()


def test_fold_state_never_touches_a_real_settings_file(tmp_path):
    from pathlib import Path

    assert Path(folds.fold_settings().fileName()).parent == tmp_path


def test_the_coverage_tooltip_explains_what_and_how_a_preview_draws_it(docked):
    dock, _ = docked
    assert dock.coverage_check.toolTip() == COVERAGE_TIP
    assert "largest count" in COVERAGE_TIP
