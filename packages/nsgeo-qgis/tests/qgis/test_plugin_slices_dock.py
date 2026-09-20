"""The Slices dock's Source group."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
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
