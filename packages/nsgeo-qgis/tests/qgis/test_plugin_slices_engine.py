"""SliceEngine: preparation, the plan cache, residency, one slice per tick."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.render import UnipolarClip
from nsgeo.slices import CoverageError, SliceWindow
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import NO_TRANSFORM, Resolution, SourceChoice
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import QTimer

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [
    {"step": "time_zero", "params": {}, "enabled": True},
    {"step": "dewow", "params": {}, "enabled": True},
    {"step": "gain_agc", "params": {}, "enabled": True},
]


@pytest.fixture
def sourced(qgis_app, tmp_path):
    """A session with four parallel lines in one grid, and an engine on it."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(4):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", 1.0 + i * 1.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    errors: list[tuple[str, str]] = []
    prepared: list[int] = []
    engine = SliceEngine(
        session,
        on_prepared=lambda: prepared.append(1),
        on_error=lambda msg: errors.append(("error", msg)),
    )
    yield engine, session, errors, prepared
    engine.dispose()


def _prepare(engine, session, transform="amp_envelope", preset="p"):
    engine.set_source(
        SourceChoice(
            grid_id="A", preset=preset, transform=transform, line_keys=tuple(session.keys())
        )
    )
    assert engine.wait_for_preparation(20_000), "preparation did not finish"
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))


def test_preparation_applies_the_preset_and_appends_the_transform(sourced):
    engine, session, errors, prepared = sourced
    _prepare(engine, session)
    assert errors == []
    assert prepared == [1]
    assert engine.is_prepared
    assert engine.line_count == 4
    assert engine.output_unipolar is True
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    covered = values[coverage > 0]
    assert covered.size > 0
    assert np.isfinite(covered).all()
    assert (covered >= 0.0).all(), "an envelope is unipolar; a negative means it was not applied"


def test_no_transform_leaves_the_data_bipolar_and_says_so(sourced):
    engine, session, errors, _ = sourced
    _prepare(engine, session, transform=NO_TRANSFORM)
    assert engine.output_unipolar is False
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    covered = values[coverage > 0]
    assert (covered < 0.0).any(), "a signed mean of a signed radargram should reach below zero"


def test_a_preset_that_already_carries_a_transform_is_refused_by_name(sourced):
    """Ruling 2. The refusal must name the step, because the user's fix is
    to remove that specific step from that specific preset."""
    engine, session, errors, _ = sourced
    session.site.presets["bad"] = [
        {"step": "amp_abs", "params": {}, "enabled": True},
        {"step": "gain_agc", "params": {}, "enabled": True},
    ]
    with pytest.raises(ValueError, match="amp_abs"):
        engine.set_source(
            SourceChoice(grid_id="A", preset="bad", transform="amp_square", line_keys=("x",))
        )
    assert not engine.is_prepared


def test_changing_the_cell_size_re_plans_every_line(sourced):
    """The defect M10's final review called M11's first bug. A LinePlan is
    a function of (line, frame, z) and every Resolution control changes
    one of them; reusing a plan across that change bins every trace into
    the wrong cell. Before M10's guard existed it did so SILENTLY, with
    plausible coverage. The engine must drop its plans, not rely on the
    guard to raise."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    coarse, _ = engine.slice_at(SliceWindow(4, 14))
    assert coarse.shape == (24, 24)  # 6 m / 0.25 m

    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    fine, _ = engine.slice_at(SliceWindow(4, 14))  # must NOT raise
    assert fine.shape == (12, 12)

    # And a z-axis change, which the same plans would also survive by
    # length alone if nz happened to match.
    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.25, t0_ns=2.0, t1_ns=16.0))
    again, _ = engine.slice_at(SliceWindow(4, 14))
    assert again.shape == (12, 12)


def test_streaming_and_a_resident_cube_give_the_same_slice(sourced):
    """Spec 11's property, in the form a user could notice: the mode they
    are in must not change what they see."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.set_always_resident(False)
    assert engine.mode == "streaming"
    streamed, cov_s = engine.slice_at(SliceWindow(6, 18))

    engine.set_always_resident(True)
    assert engine.mode == "resident"
    resident, cov_r = engine.slice_at(SliceWindow(6, 18))

    np.testing.assert_array_equal(cov_s, cov_r)
    both = np.isfinite(streamed) & np.isfinite(resident)
    assert both.any()
    np.testing.assert_allclose(streamed[both], resident[both], rtol=1e-5, atol=1e-6)
    np.testing.assert_array_equal(np.isfinite(streamed), np.isfinite(resident))


def test_the_shared_limit_agrees_between_the_two_modes(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    clip = UnipolarClip()
    engine.set_always_resident(False)
    streamed = engine.shared_limit(10, clip)
    engine.set_always_resident(True)
    resident = engine.shared_limit(10, clip)
    assert streamed == pytest.approx(resident, rel=1e-4)
    assert streamed > 0.0


def test_provenance_names_the_lines_that_were_actually_prepared(sourced):
    """Not the lines that were asked for. A line that failed to prepare is
    not in the cube and must not be claimed by its provenance -- that
    record is what a reader trusts the thing by."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    prov = engine.provenance()
    assert prov.line_keys == tuple(session.keys())
    assert prov.preset_name == "p"
    assert prov.transform == "amp_envelope"
    assert len(prov.steps) == len(PRESET)
    assert prov.core_version
    assert prov.built_utc.endswith("Z")


def test_provenance_excludes_a_line_that_failed_to_prepare(sourced, tmp_path):
    """Mutation check (Step 11.3): a fifth line added to the source that
    cannot be prepared must not appear in `provenance().line_keys`, even
    though it was named in the SourceChoice passed to set_source. This is
    the case that discriminates `self._choice.line_keys` (the mutant) from
    `tuple(line.key for line in self._lines)` (the real code): the request
    and the result differ only when a line fails, so a broken fifth line
    is required to see it at all."""
    engine, session, _, _ = sourced
    p = synthetic_dzt(tmp_path / "raw", "FILE__005.DZT", n_traces=60)
    broken = Line.open(p, GridPlacement("A", "y", 5.0, 0.0, 1, p.stem))
    session.add_lines([broken])
    broken_key = session.line_key(broken)
    p.unlink()  # header already read; load() will now fail on the worker

    engine.set_source(
        SourceChoice(
            grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(session.keys())
        )
    )
    assert engine.wait_for_preparation(20_000)
    assert engine.line_count == 4, "the broken line must not have been prepared"

    prov = engine.provenance()
    assert broken_key not in prov.line_keys
    assert len(prov.line_keys) == 4


def test_provenance_records_the_steps_that_were_applied_not_the_preset_as_it_stands_now(sourced):
    """`save_preset` overwrites a name in place and `delete_preset`
    removes it, both while a source stays prepared. The steps that were
    applied are a fact about the preparation, exactly as the line keys
    are -- and provenance is what a reader trusts the cube by."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    applied = engine.provenance().steps
    assert len(applied) == len(PRESET)

    session.site.presets["p"] = [{"step": "gain_agc", "params": {}, "enabled": True}]
    session.presets_changed.emit()
    assert engine.provenance().steps == applied, "provenance followed a preset edit"

    del session.site.presets["p"]
    session.presets_changed.emit()
    assert engine.provenance().steps == applied, "provenance lost its steps when the preset went"


def test_a_z_range_the_lines_do_not_cover_is_reported_with_the_line_named(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.5, t0_ns=0.0, t1_ns=400.0))
    with pytest.raises(CoverageError, match="FILE__001"):
        engine.slice_at(SliceWindow(0, 4))


def test_the_status_line_follows_the_mode_and_the_line_count(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.slice_at(SliceWindow(4, 14))
    text = engine.status_text()
    assert text.startswith("4 lines held in memory")
    assert "slices redraw in" in text
    engine.set_always_resident(True)
    engine.slice_at(SliceWindow(4, 14))
    assert "whole volume" in engine.status_text()


def test_closing_the_site_releases_everything(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    assert engine.is_prepared
    session.close_site()
    assert not engine.is_prepared
    assert engine.line_count == 0
    assert engine.frame is None


def test_a_line_that_cannot_be_prepared_is_reported_by_name(sourced, tmp_path):
    engine, session, errors, _ = sourced
    key = session.keys()[0]
    session.line_for_key(key).path.unlink()  # the file goes away under us
    engine.set_source(
        SourceChoice(grid_id="A", preset="p", transform="amp_abs", line_keys=tuple(session.keys()))
    )
    assert engine.wait_for_preparation(20_000)
    assert any(key in msg for _, msg in errors), f"no error named {key}: {errors}"


def test_moving_the_grid_re_prepares_rather_than_slicing_at_the_old_registration(sourced):
    """`replace_grid` changes both the frame AND the coordinates every
    prepared line was binned from, and M10's stale-plan guard is
    structurally blind to it: `plan.frame` and the frame passed in are the
    same stale object. Measured before this fix: the grid moved 100 m
    east and `engine.frame` stayed at the OLD registration with no error
    of any kind -- the engine had not reacted to the change at all.

    The re-prepared slice's VALUES are not asserted against the old ones:
    `GridPlacement` positions a line relative to its grid (`trace_coords`
    round-trips world coordinates through the same grid's own origin and
    azimuth that `CubeFrame.for_grid` shares), so a rigid move of the
    grid is self-consistently invariant in the cube's own cell content --
    only the frame's registration (and, downstream, the map layer) moves.
    What must be observed instead is that a re-preparation actually ran.
    """
    engine, session, errors, prepared = sourced
    _prepare(engine, session)
    engine.slice_at(SliceWindow(4, 14))  # so a redraw timing exists before the move too
    count = len(prepared)
    assert engine.frame.origin == (500.0, 700.0)

    session.replace_grid(Grid("A", (600.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    assert engine.wait_for_preparation(20_000)
    assert len(prepared) == count + 1, "the grid move did not trigger a re-preparation"
    assert engine.frame.origin == (600.0, 700.0), "the engine kept the old registration"
    assert engine.is_prepared
    engine.slice_at(SliceWindow(4, 14))  # must not raise against the new geometry
    assert errors == []


def test_a_velocity_only_grid_edit_does_not_re_prepare(sourced):
    """Velocity relabels depths without rebinning, so paying 0.9 s for it
    would be waste. The fingerprint excludes it deliberately."""
    engine, session, _, prepared = sourced
    _prepare(engine, session)
    count = len(prepared)
    session.set_grid_velocity("A", VelocityModel.constant(0.09))
    assert engine.wait_for_preparation(2_000)
    assert len(prepared) == count, "a velocity change re-prepared"


def test_removing_the_chosen_grid_is_reported_rather_than_left_stale(sourced):
    """`remove_grid` refuses to remove a grid that still has lines
    (`ValueError`, `session.py`'s own guard) -- it does NOT remove them
    for you. So the reachable way a chosen grid disappears out from under
    a prepared source is: the lines are removed or reassigned first, THEN
    the now-empty grid is removed. This test drives it that way."""
    engine, session, errors, _ = sourced
    _prepare(engine, session)
    for key in list(session.keys()):
        session.remove_line(key)
    session.remove_grid("A")
    assert not engine.is_prepared
    assert any("A" in msg for _, msg in errors), errors


def test_an_exception_while_finishing_preparation_still_wakes_wait_for_preparation(sourced):
    """Every terminal path in `finished` must call `_finish_preparation`,
    or `wait_for_preparation` blocks for the whole timeout on a bug in
    the success path (here, a broken `_rebuild_geometry`) instead of
    waking promptly -- the same lesson `loader.py`'s own addTask-failure
    branch already draws for its own terminal path."""
    engine, session, errors, _ = sourced

    def _broken() -> None:
        raise RuntimeError("boom")

    engine._rebuild_geometry = _broken
    engine.set_source(
        SourceChoice(
            grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(session.keys())
        )
    )
    assert engine.wait_for_preparation(5_000), "a worker-side exception left preparation hanging"
    assert any("boom" in msg for _, msg in errors), errors


def test_a_task_that_cannot_be_scheduled_still_notifies(sourced, monkeypatch):
    """The addTask()-returned-0 branch is the same must-still-notify
    contract as the other terminal paths in `finished` -- loader.py's own
    version of this branch re-emits `loading_changed(key, False)` for
    exactly this reason."""
    engine, session, errors, prepared = sourced

    class _FakeManager:
        def addTask(self, task: object) -> int:
            return 0

    class _FakeApp:
        @staticmethod
        def taskManager() -> _FakeManager:
            return _FakeManager()

    import nsgeo_qgis.slices_engine as engine_module

    monkeypatch.setattr(engine_module, "QgsApplication", _FakeApp)

    engine.set_source(
        SourceChoice(
            grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(session.keys())
        )
    )
    assert prepared == [1], "the addTask-failure branch must still notify on_prepared"
    assert any("schedule" in msg for _, msg in errors), errors


def test_a_grid_move_before_any_resolution_still_re_prepares(sourced):
    """The ordering Task 3 actually uses: prepare, then set a resolution.
    With the fingerprint keyed to `_rebuild_geometry` it was None until a
    resolution existed, so a grid edit in that window left the frame built
    from the NEW grid against coords from the OLD one -- silent mis-binning
    at small offsets, since a stale-but-in-bounds cell id never raises."""
    engine, session, errors, prepared = sourced
    engine.set_source(
        SourceChoice(
            grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(session.keys())
        )
    )
    assert engine.wait_for_preparation(20_000)
    count = len(prepared)
    assert engine.frame is None  # no resolution yet

    session.replace_grid(Grid("A", (501.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    assert engine.wait_for_preparation(20_000)
    assert len(prepared) == count + 1, "a grid move before any resolution did not re-prepare"

    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    assert (coverage > 0).any(), "coords and frame disagree after the move"
    assert errors == []


def test_a_velocity_edit_drops_a_resident_cube_rather_than_serving_stale_provenance(sourced):
    """`provenance()` reads `resolved_velocity` LIVE, but `cube()` freezes
    a `Provenance` snapshot into the `SliceCube` the moment it is built --
    so a resident cube built before a velocity edit would export the
    STALE velocity forever if nothing dropped it (Ruling Q). Only the
    cube is dropped: the prepared lines and the plans do not depend on
    velocity at all, so dropping them would pay 0.9 s for nothing."""
    engine, session, _, prepared = sourced
    _prepare(engine, session)
    engine.set_always_resident(True)
    engine.slice_at(SliceWindow(4, 14))  # builds the resident cube
    assert engine.has_cube
    line_count = engine.line_count
    count = len(prepared)

    session.set_grid_velocity("A", VelocityModel.constant(0.09))
    assert engine.wait_for_preparation(2_000)
    assert len(prepared) == count, "a velocity edit re-prepared the lines"
    assert engine.line_count == line_count
    assert not engine.has_cube, "a velocity edit left a stale cube in place"


def test_a_raising_on_prepared_still_reports_and_does_not_hang(sourced):
    """`_finish_preparation` runs from `finished`'s own `finally`, OUTSIDE
    its `except` -- so a raising `on_prepared` (Task 3's dock rebuilds
    widgets there) must guard itself, or `QgsTaskWrapper.finished`
    (verified directly in its installed source) swallows it with no log
    and no traceback at all. The qgis-tier conftest's
    `_no_swallowed_slot_exceptions` fixture is the belt to this test's
    braces: it would fail this test outright if anything escaped."""
    engine, session, errors, _ = sourced

    def _raise() -> None:
        raise RuntimeError("boom")

    engine.on_prepared = _raise
    engine.set_source(
        SourceChoice(
            grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(session.keys())
        )
    )
    assert engine.wait_for_preparation(5_000), "a raising on_prepared left preparation hanging"
    assert engine.is_prepared
    assert any("boom" in msg for _, msg in errors), errors


def test_two_different_choices_back_to_back_never_run_concurrently(sourced, monkeypatch):
    """Fix round 2, Ruling V. `_generation` was already known to discard a
    SUPERSEDED task's result; what it does not do is stop the superseded
    task from still executing. Two GENUINELY DIFFERENT `set_source` calls
    with no intervening wait -- a person clicking through the Source
    combos, not only a test fixture -- used to dispatch two real
    `QgsTask`s that read the same lines at the same time, which segfaulted
    this plugin reproducibly (Task 3, fix round 1 closed only the
    identical-choice case).

    `Line.load` is patched to sleep, widening the window a real disk read
    only holds open for a few milliseconds into one long enough that a
    counter under a lock catches genuine thread overlap deterministically
    -- stronger evidence than timing, and than hoping for a repeat
    segfault. Confirmed this test actually discriminates: reverted
    `_cancel_in_flight()` to a no-op (commenting out its body) and re-ran
    just this test -- it failed with `max_concurrent == 2`, both threads
    inside the patched `load` at once, exactly the shape the fix removes.
    """
    engine, session, errors, _ = sourced
    concurrent = 0
    max_concurrent = 0
    lock = threading.Lock()
    real_load = Line.load

    def slow_load(self: Line) -> list:
        nonlocal concurrent, max_concurrent
        with lock:
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
        try:
            time.sleep(0.05)
            return real_load(self)
        finally:
            with lock:
                concurrent -= 1

    monkeypatch.setattr(Line, "load", slow_load)

    keys = tuple(session.keys())
    choice_a = SourceChoice(grid_id="A", preset="p", transform=NO_TRANSFORM, line_keys=keys)
    choice_b = SourceChoice(grid_id="A", preset="p", transform="amp_envelope", line_keys=keys)

    engine.set_source(choice_a)
    engine.set_source(choice_b)  # no intervening wait -- the discriminating call
    assert engine.wait_for_preparation(20_000)

    assert max_concurrent <= 1, (
        f"two tasks executed work() concurrently (max_concurrent={max_concurrent}); "
        "_cancel_in_flight() must confirm the first task actually stopped before "
        "the second one starts"
    )
    # The later choice is the one that lands -- checked structurally
    # (output_unipolar reads the CHOSEN transform, not a stored flag) so a
    # regression that silently kept choice_a's result would still be caught.
    assert engine.choice == choice_b
    assert engine.output_unipolar is True
    assert engine.line_count == len(keys)
    assert errors == [], errors


def test_a_choice_delivered_during_the_cancel_wait_does_not_reopen_the_overlap(
    sourced, monkeypatch
):
    """Fix round 3, Ruling W. `_cancel_in_flight`'s own confirm step spins
    a nested `QEventLoop`, which can deliver a SECOND, different
    `set_source` call from INSIDE the first call's own frame -- a person
    changing a combo again while the previous change is still being
    cancelled. Measured before this guard existed: the reentrant call
    dispatched its own task, then the OUTER call resumed and dispatched a
    second one on top -- two real tasks at once again, with the OLDER
    (outer) choice winning because it bumps `_generation` last.

    `QTimer.singleShot(0, ...)` is scheduled just BEFORE the discriminating
    `set_source` call specifically because a timer is a POSTED event, not
    user input -- `_cancel_in_flight`'s `ExcludeUserInputEvents` mask does
    not by itself stop it, so this exercises the OTHER half of the fix
    (`set_source`'s own `_dispatching` guard), not the event-mask half
    `test_two_different_choices_back_to_back_never_run_concurrently`
    already covers. The zero-delay timer reliably fires on the very first
    iteration of the nested loop, long before the ~50 ms patched `load`
    lets the cancelled task actually clear, so the reentrant call is
    guaranteed to land INSIDE the wait, not after it -- PROVIDED
    `QgsApplication.taskManager()`'s thread pool is already warm. Measured
    directly: run as the first test to ever dispatch a `QgsTask` in a
    fresh `qgis_app` process, the very first task's own thread start-up
    latency is itself long enough to blow past the 50 ms window and this
    test fails even against the fix (`wait_for_preparation(20_000)`
    itself returns `False`) -- a test-isolation artefact, not evidence
    against the fix (run straight after any other test in this file that
    dispatches one first, it passes reliably). The warm-up dispatch below
    removes that dependency on execution order.
    """
    engine, session, errors, _ = sourced
    keys = tuple(session.keys())
    # Warm-up: get `QgsApplication.taskManager()` past whatever it costs
    # to start its very first worker thread, using the REAL (fast) load --
    # before `Line.load` is patched to sleep below. Without this, running
    # this test first/alone in a fresh process is flaky for a reason
    # unrelated to the fix (see the docstring above).
    engine.set_source(SourceChoice(grid_id="A", preset="p", transform=NO_TRANSFORM, line_keys=keys))
    assert engine.wait_for_preparation(20_000), "warm-up preparation did not finish"
    errors.clear()

    concurrent = 0
    max_concurrent = 0
    lock = threading.Lock()
    real_load = Line.load

    def slow_load(self: Line) -> list:
        nonlocal concurrent, max_concurrent
        with lock:
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
        try:
            time.sleep(0.05)
            return real_load(self)
        finally:
            with lock:
                concurrent -= 1

    monkeypatch.setattr(Line, "load", slow_load)

    choice_a = SourceChoice(grid_id="A", preset="p", transform=NO_TRANSFORM, line_keys=keys)
    choice_b = SourceChoice(grid_id="A", preset="p", transform="amp_envelope", line_keys=keys)
    choice_c = SourceChoice(grid_id="A", preset="p", transform="amp_abs", line_keys=keys)

    engine.set_source(choice_a)
    QTimer.singleShot(0, lambda: engine.set_source(choice_c))
    engine.set_source(choice_b)  # cancels choice_a; the timer fires during THIS wait
    assert engine.wait_for_preparation(20_000)

    assert max_concurrent <= 1, (
        f"two tasks executed work() concurrently (max_concurrent={max_concurrent}); "
        "a choice delivered from inside the cancel wait must be queued, not dispatched "
        "from the reentrant call"
    )
    # The LATEST choice must win -- measured before this guard existed, the
    # OLDER (outer, choice_b) one did, because the outer frame bumps
    # `_generation` last regardless of dispatch order.
    assert engine.choice == choice_c
    assert engine.line_count == len(keys)
    assert errors == [], errors
