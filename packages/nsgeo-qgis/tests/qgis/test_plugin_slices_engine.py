"""SliceEngine: preparation, the plan cache, residency, one slice per tick."""

from __future__ import annotations

import dataclasses
import threading
import time

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import Radargram
from nsgeo.render import PercentileClip, UnipolarClip
from nsgeo.slices import (
    CoverageError,
    CurvaturePlan,
    SliceWindow,
    finish_slice,
    limit_over_slices,
    plan_curvature,
    plan_fill,
    plan_windows,
    smooth,
)
from nsgeo.velocity import VelocityModel
from nsgeo_qgis import slices_engine
from nsgeo_qgis.line_edit import LineEdit
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_engine import PendingSolve, SliceEngine, solve_key
from nsgeo_qgis.slices_plan import (
    CURVATURE_PLAN_BYTES_PER_CELL,
    LIVE_SOLVE_BUDGET_MS,
    NO_TRANSFORM,
    SITE_LIMIT_WINDOWS,
    SOLVED_SLICES_KEPT,
    WEIGHT_BYTES_PER_CELL,
    Resolution,
    SliceFinish,
    SourceChoice,
    limit_windows,
)
from plugin_testing import REAL_DZT, needs_real_data, spin_until, synthetic_dzt
from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QCoreApplication, QEventLoop, QThread, QTimer

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


def test_the_estimate_follows_a_new_cell_size_and_a_new_line_set(sourced):
    """The checkbox and status figures count the covered cells, and follow a
    new cell size and a re-prepared line set rather than a cached count (#113)."""
    engine, session, errors, _ = sourced
    _prepare(engine, session)
    first = engine.estimate.cube_bytes
    assert first == engine.cube().nbytes

    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    second = engine.estimate.cube_bytes
    assert second == engine.cube().nbytes
    assert second != first

    keys = tuple(session.keys())[:-1]
    engine.set_source(
        SourceChoice(grid_id="A", preset="p", transform="amp_envelope", line_keys=keys)
    )
    assert engine.wait_for_preparation(20_000), "preparation did not finish"
    assert errors == []
    assert engine.line_count == 3
    assert engine.estimate.cube_bytes == engine.cube().nbytes


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
    with pytest.raises(ValueError, match="already contains the Absolute value step"):
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


def test_cube_refuses_when_no_lines_are_prepared(sourced):
    """Important 2 (Task 6 fix round 1): `cube()` used to have no
    zero-line guard, unlike `_slice`'s streaming path, which already
    checked `self._lines` before ever reaching `cube()`. `save_cube_npz`'s
    direct `engine.cube()` call bypassed that check entirely -- reachable
    for real during the window `set_source` clears `_lines` synchronously
    while a re-preparation is still in flight (`_frame`/`_z` are left
    alone), and it built a full-size, all-NaN `SliceCube` with no
    exception at all. Reproduced here without needing to hit that race:
    an EMPTY line selection (`line_keys=()`) reaches the identical state
    -- geometry present, no lines -- synchronously and legitimately
    (`SlicesDock`'s own "0 of 0" status text already treats it as
    ordinary, not a failure)."""
    engine, session, _, _ = sourced
    engine.set_source(SourceChoice(grid_id="A", preset="p", transform=NO_TRANSFORM, line_keys=()))
    assert engine.wait_for_preparation(20_000)
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    assert engine.frame is not None and engine.z is not None
    assert not engine.is_prepared
    with pytest.raises(RuntimeError, match="no lines are prepared"):
        engine.cube()


def test_the_shared_limit_agrees_between_the_two_modes(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    clip = UnipolarClip()
    engine.set_always_resident(False)
    streamed = engine.shared_limit(10, clip, SliceFinish())
    engine.set_always_resident(True)
    resident = engine.shared_limit(10, clip, SliceFinish())
    assert streamed == pytest.approx(resident, rel=1e-4)
    assert streamed > 0.0


@needs_real_data
def test_shared_limit_measures_the_filled_array_actually_displayed(qgis_app, tmp_path):
    """Final review, Important 1. `shared_limit` used to measure the shared
    stretch over the UNFILLED slice (`self._slice(w)[0]`), while what
    `refresh_slice()` actually displays is the finished slice -- so the
    default (shared) stretch measured something never drawn. Reproduced on
    this repo's real DZT files at thickness 23 levels (thickness_spin's
    default 5.0 ns at this dz), cell 0.25 m, and kriging out to 1.5 line
    spacings (interpolation spec §8).

    `reported` (what the engine returns) must equal `correct` (the same
    shared-stretch measurement, computed independently here by finishing
    every window through the core pipeline and calling `limit_over_slices`
    directly) -- and `unfilled` (the OLD measurement, over the raw arrays)
    must differ from it meaningfully, or this test could not tell the fix
    from the bug it replaces."""
    session = SiteSession()
    session.new_site(tmp_path)
    grid = Grid("A", (0.0, 0.0), 0.0, 3.0, 12.0, "EPSG:32616", 0.5)
    session.add_grid(grid)
    lines = [
        Line.open(REAL_DZT[i], GridPlacement("A", "y", 0.5 + i * 0.5, 0.0, 1, REAL_DZT[i].stem))
        for i in range(4)
    ]
    session.add_lines(lines)
    # No `time_zero`: it crops rows off the front of the radargram and
    # relabels the axis to read 0 at the first break, so the line's own
    # t0_ns would no longer equal the header's raw
    # `position_ns` this test seeds `z0` from directly (the dock's own
    # `_seed_dz_z_defaults` formula) -- `dewow`/`background_mean`/
    # `gain_agc` all leave the sample axis untouched, so `header.position_
    # ns`/`n_samples` stay the exact bounds the prepared line covers.
    session.site.presets["p"] = [
        {"step": "dewow", "params": {}, "enabled": True},
        {"step": "background_mean", "params": {}, "enabled": True},
        {"step": "gain_agc", "params": {}, "enabled": True},
    ]
    engine = SliceEngine(session)
    header = lines[0].header
    resolution = Resolution(
        cell=0.25,
        dz_ns=header.dt_ns,
        t0_ns=header.position_ns,
        t1_ns=header.position_ns + (header.n_samples - 1) * header.dt_ns,
    )
    thickness_levels = max(1, round(5.0 / header.dt_ns))
    # 1.5 spacings = the 0.75 m radius this test was first measured at: the
    # default half-spacing fills too few cells here to tell the two apart
    # by the 5% margin below.
    finish = SliceFinish(max_distance_spacings=1.5)
    assert thickness_levels == 23  # the dock's own seeded thickness, at this dz
    try:
        for transform, clip_cls in (
            ("amp_envelope", UnipolarClip),
            (NO_TRANSFORM, PercentileClip),  # transform_combo's "none"
        ):
            engine.set_source(
                SourceChoice(
                    grid_id="A", preset="p", transform=transform, line_keys=tuple(session.keys())
                )
            )
            assert engine.wait_for_preparation(20_000)
            engine.set_resolution(resolution)
            clip = clip_cls()
            reported = engine.shared_limit(thickness_levels, clip, finish)

            z = engine.z
            windows = list(plan_windows(z, thickness_levels, thickness_levels))
            if windows[-1].k1 < z.nz:
                windows.append(SliceWindow(windows[-1].k1, z.nz))
            settings = engine.finish_settings(finish)
            correct = limit_over_slices(
                (
                    finish_slice(
                        v,
                        plan_fill(
                            c > 0,
                            engine.frame.cell,
                            settings.method,
                            settings.max_distance_m,
                            settings.search_radius_m,
                        ),
                        engine.frame.cell,
                        settings,
                    )
                    for v, c in (engine._slice(w) for w in windows)
                ),
                clip,
            )
            unfilled = limit_over_slices((engine._slice(w)[0] for w in windows), clip)

            assert reported == pytest.approx(correct, rel=1e-9), (
                f"{transform!r}: engine reported {reported}, the finished measurement is {correct}"
            )
            assert unfilled / correct > 1.05, (
                f"{transform!r}: unfilled {unfilled} vs finished {correct} did not differ enough "
                "to discriminate the fix from the bug it replaces"
            )
    finally:
        engine.dispose()


def _core_finish(engine, values, coverage, finish):
    """The core pipeline, built independently of the engine's cache."""
    settings = engine.finish_settings(finish)
    weights = plan_fill(
        coverage > 0,
        engine.frame.cell,
        settings.method,
        settings.max_distance_m,
        settings.search_radius_m,
    )
    return finish_slice(values, weights, engine.frame.cell, settings)


def test_finish_matches_the_core_pipeline(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    for finish in (
        SliceFinish(),
        SliceFinish(method="idw", max_distance_spacings=1.0),
        SliceFinish(method="none", smooth_x_m=0.3, smooth_y_m=0.2),
    ):
        got = engine.finish(values, coverage, finish)
        want = _core_finish(engine, values, coverage, finish)
        np.testing.assert_array_equal(got, want)
    # The default really fills something here, or the comparison proves little.
    assert np.isfinite(engine.finish(values, coverage, SliceFinish())).sum() > (coverage > 0).sum()


def test_finish_settings_are_in_metres_at_the_grids_spacing(sourced):
    engine, session, _, _ = sourced
    with pytest.raises(RuntimeError):
        engine.finish_settings(SliceFinish())
    _prepare(engine, session)
    settings = engine.finish_settings(SliceFinish(max_distance_spacings=1.5, smooth_x_m=0.1))
    assert settings.max_distance_m == pytest.approx(0.75)  # GRID's spacing is 0.5 m
    assert settings.smooth_x_m == 0.1


def test_weights_are_built_once_and_reused_across_windows(sourced, monkeypatch):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    calls = []
    real = slices_engine.plan_fill

    def counting(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(slices_engine, "plan_fill", counting)
    finish = SliceFinish()
    assert not engine.weights_cached(finish)
    for window in (SliceWindow(0, 6), SliceWindow(6, 12), SliceWindow(12, 18)):
        engine.finish(*engine.slice_at(window), finish)
        assert engine.weights_cached(finish)
    assert len(calls) == 1


def test_a_new_cell_or_setting_rebuilds_the_weights(sourced, monkeypatch):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    calls = []
    real = slices_engine.plan_fill
    monkeypatch.setattr(
        slices_engine, "plan_fill", lambda *a, **k: calls.append(a) or real(*a, **k)
    )
    window = SliceWindow(4, 14)
    engine.finish(*engine.slice_at(window), SliceFinish())
    assert len(calls) == 1
    # Smoothing is applied after the weights, so a smoothing edit keeps them;
    # a method or a distance must rebuild.
    assert engine.weights_cached(SliceFinish(smooth_x_m=0.5, smooth_y_m=0.5))
    engine.finish(*engine.slice_at(window), SliceFinish(smooth_x_m=0.5, smooth_y_m=0.5))
    assert len(calls) == 1
    for finish in (SliceFinish(method="idw"), SliceFinish(max_distance_spacings=1.0)):
        assert not engine.weights_cached(finish)
        engine.finish(*engine.slice_at(window), finish)
        assert engine.weights_cached(finish)
    assert len(calls) == 3
    # A new cell is a new frame: the weights go, whatever the settings.
    assert engine.weights_cached(SliceFinish(max_distance_spacings=1.0))
    engine.set_resolution(Resolution(cell=0.2, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    assert not engine.weights_cached(SliceFinish(max_distance_spacings=1.0))
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    engine.finish(values, coverage, SliceFinish(max_distance_spacings=1.0))
    assert len(calls) == 4
    assert calls[-1][1] == pytest.approx(0.2)  # the frame's cell


def test_a_z_only_resolution_edit_keeps_the_weights(sourced, monkeypatch):
    """dz, z0 and z1 leave the frame as it was, so its weights stand: rebuilding
    them on every z edit cost seconds at a fine cell (10.5 s at 0.05 m on a 50 m
    grid, as measured by the final review). A new cell is a
    new frame and still rebuilds. The slice drawn from the kept weights equals
    a fresh engine's at the same resolution."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    calls = []
    real = slices_engine.plan_fill
    monkeypatch.setattr(
        slices_engine, "plan_fill", lambda *a, **k: calls.append(a) or real(*a, **k)
    )
    finish = SliceFinish()
    engine.finish(*engine.slice_at(SliceWindow(4, 14)), finish)
    assert len(calls) == 1
    edited = Resolution(cell=0.25, dz_ns=0.25, t0_ns=4.0, t1_ns=26.0)
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.25, t0_ns=2.0, t1_ns=30.0))
    engine.set_resolution(edited)
    assert engine.weights_cached(finish)
    window = SliceWindow(10, 30)
    drawn = engine.finish(*engine.slice_at(window), finish)
    assert len(calls) == 1

    fresh = SliceEngine(session)
    try:
        fresh.set_source(engine.choice)
        assert fresh.wait_for_preparation(20_000)
        fresh.set_resolution(edited)
        np.testing.assert_array_equal(drawn, fresh.finish(*fresh.slice_at(window), finish))
    finally:
        fresh.dispose()

    engine.set_resolution(Resolution(cell=0.2, dz_ns=0.25, t0_ns=4.0, t1_ns=26.0))
    assert not engine.weights_cached(finish)
    engine.finish(*engine.slice_at(window), finish)
    assert len(calls) == 3  # the fresh engine's build, then the new cell's


def test_the_weights_are_rebuilt_when_the_populated_cells_differ(sourced, monkeypatch):
    """`weights_cached` compares the key only, so `finish` itself must catch a
    coverage the held weights were not planned for."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    finish = SliceFinish()
    engine.finish(values, coverage, finish)
    other = coverage.copy()
    other[other > 0] = 0
    other[0, 0] = 1  # a different populated set, same frame and settings
    got = engine.finish(np.where(other > 0, 1.0, np.nan).astype(np.float32), other, finish)
    want = _core_finish(engine, np.where(other > 0, 1.0, np.nan).astype(np.float32), other, finish)
    np.testing.assert_array_equal(got, want)


def test_switching_method_back_gives_the_same_slice_as_from_scratch(sourced):
    """Review Focus 4: kriging -> IDW -> kriging must not serve the other
    setting's weights."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    kriging, idw = SliceFinish(method="kriging"), SliceFinish(method="idw")
    first = engine.finish(values, coverage, kriging)
    middle = engine.finish(values, coverage, idw)
    again = engine.finish(values, coverage, kriging)
    assert not np.array_equal(first, middle, equal_nan=True), "the two methods must differ here"
    np.testing.assert_array_equal(again, first)
    fresh_session = engine.session  # a second engine on the same prepared source
    other = SliceEngine(fresh_session)
    try:
        _prepare(other, fresh_session)
        np.testing.assert_array_equal(
            other.finish(*other.slice_at(SliceWindow(4, 14)), kriging), first
        )
    finally:
        other.dispose()


def test_a_new_source_drops_the_weights(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.finish(*engine.slice_at(SliceWindow(4, 14)), SliceFinish())
    assert engine.weights_cached(SliceFinish())
    engine.set_source(None)
    assert not engine.weights_cached(SliceFinish())


def test_shared_limit_measures_the_finished_slices(sourced):
    """The shared stretch is measured over what is drawn: the finished slices,
    smoothing included, in both residencies."""
    engine, session, _, _ = sourced
    _prepare(engine, session, transform=NO_TRANSFORM)
    clip = PercentileClip()
    finish = SliceFinish(method="idw", max_distance_spacings=1.0, smooth_x_m=0.5, smooth_y_m=0.5)
    windows = list(plan_windows(engine.z, 10, 10))
    if windows[-1].k1 < engine.z.nz:
        windows.append(SliceWindow(windows[-1].k1, engine.z.nz))
    correct = limit_over_slices(
        (_core_finish(engine, *engine._slice(w), finish) for w in windows), clip
    )
    unfinished = limit_over_slices((engine._slice(w)[0] for w in windows), clip)
    for resident in (False, True):
        engine.set_always_resident(resident)
        assert engine.shared_limit(10, clip, finish) == pytest.approx(correct, rel=1e-6)
    assert unfinished != pytest.approx(correct, rel=1e-3), "the finish must change the limit here"


# ---- minimum curvature: the plan and preview, the solved-slice cache --------
# Plan calls 5-9 (interpolation spec §7). Real solve timings never decide a
# result here: where "slow" matters, `_last_solve_ms` is set by hand, after
# the plan exists (Ruling R1: building one resets it).

MC = SliceFinish(method="min_curvature")


@pytest.fixture
def solves(monkeypatch):
    """Every `CurvaturePlan.solve`, counted on whichever thread runs it."""
    calls: list[int] = []
    real = CurvaturePlan.solve

    def counting(self, values, should_stop=None):
        calls.append(1)
        return real(self, values, should_stop)

    monkeypatch.setattr(CurvaturePlan, "solve", counting)
    return calls


def _curvature_finish(engine, values, coverage, finish):
    """Minimum curvature from the core alone, then the same smoothing."""
    settings = engine.finish_settings(finish)
    cell = engine.frame.cell
    solved = plan_curvature(coverage > 0, cell, settings.max_distance_m).apply(values)
    return smooth(solved, cell, settings.smooth_x_m, settings.smooth_y_m)


def test_minimum_curvature_finishes_through_the_engine(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    for finish in (MC, dataclasses.replace(MC, smooth_x_m=0.3, smooth_y_m=0.2)):
        got = engine.finish(values, coverage, finish)
        np.testing.assert_array_equal(got, _curvature_finish(engine, values, coverage, finish))
        np.testing.assert_array_equal(got, _core_finish(engine, values, coverage, finish))
    # It really fills something here, or the comparison proves little.
    assert np.isfinite(engine.finish(values, coverage, MC)).sum() > (coverage > 0).sum()


def test_the_preview_is_kriging_at_the_same_max_distance(sourced):
    """The preview's blanks are the full result's, so the picture does not
    change shape when the refine lands (plan call 5)."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    mc = SliceFinish("min_curvature", 1.0, 0.3, 0.2)
    preview = engine.preview(values, coverage, mc)
    full = engine.finish(values, coverage, mc)
    kriging = engine.finish(values, coverage, dataclasses.replace(mc, method="kriging"))
    np.testing.assert_array_equal(preview, kriging)
    np.testing.assert_array_equal(np.isnan(preview), np.isnan(full))
    assert not np.array_equal(preview, full, equal_nan=True), "the two must differ here"
    idw = SliceFinish(method="idw")
    np.testing.assert_array_equal(
        engine.preview(values, coverage, idw), engine.finish(values, coverage, idw)
    )


def test_a_repeated_solve_is_served_from_the_cache(sourced, solves):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    first = engine.finish(values, coverage, MC)
    again = engine.finish(values.copy(), coverage, MC)  # equal values, another array
    assert len(solves) == 1
    np.testing.assert_array_equal(again, first)
    # Smoothing is applied after the solve, so the cache holds the solve.
    smoothed = dataclasses.replace(MC, smooth_x_m=0.5, smooth_y_m=0.25)
    got = engine.finish(values, coverage, smoothed)
    assert len(solves) == 1, "a smoothing edit must not solve again"
    np.testing.assert_array_equal(got, _curvature_finish(engine, values, coverage, smoothed))


def test_the_solved_slice_cache_never_serves_other_values(sourced):
    """Review Focus 4: another preset or line set at the same window gives
    other values on the same plan, and they must be solved for themselves."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    # The same blanks, so the same plan; different values.
    other = np.where(coverage > 0, values * 2.0 + 1.0, np.nan).astype(np.float32)
    first = engine.finish(values, coverage, MC)
    second = engine.finish(other, coverage, MC)
    assert not np.array_equal(first, second, equal_nan=True)
    np.testing.assert_array_equal(first, _curvature_finish(engine, values, coverage, MC))
    np.testing.assert_array_equal(second, _curvature_finish(engine, other, coverage, MC))
    # The key is the values' bytes, shape and dtype: the same bytes read as
    # another shape or another dtype are other values.
    assert solve_key(values) == solve_key(values.copy())
    assert solve_key(values) != solve_key(other)
    assert solve_key(values) != solve_key(values.reshape(values.shape[0] // 2, -1))
    assert solve_key(values) != solve_key(values.view(np.uint32))


def test_the_cache_keeps_at_most_sixteen_and_drops_with_the_plan(sourced, solves):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    slices = [engine.slice_at(SliceWindow(k, k + 1)) for k in range(SOLVED_SLICES_KEPT + 1)]
    assert len({solve_key(values) for values, _ in slices}) == len(slices)
    for values, coverage in slices:
        engine.finish(values, coverage, MC)
    assert len(solves) == SOLVED_SLICES_KEPT + 1
    assert len(engine._solved) == SOLVED_SLICES_KEPT
    engine.finish(*slices[-1], MC)  # the newest is still held
    assert len(solves) == SOLVED_SLICES_KEPT + 1
    engine.finish(*slices[0], MC)  # the oldest went first
    assert len(solves) == SOLVED_SLICES_KEPT + 2
    # A z-only edit keeps the plan, so it keeps what was solved on it.
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=28.0))
    assert len(engine._solved) == SOLVED_SLICES_KEPT
    assert engine._last_solve_ms is not None
    # A new cell is a new plan: nothing solved on the old one is kept.
    engine.set_resolution(Resolution(cell=0.2, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    assert len(engine._solved) == 0
    assert engine._last_solve_ms is None
    engine.finish(*engine.slice_at(SliceWindow(4, 14)), MC)
    assert len(engine._solved) == 1
    assert engine._last_solve_ms is not None
    engine.set_source(engine.choice)
    assert len(engine._solved) == 0
    assert engine._last_solve_ms is None
    assert engine.wait_for_preparation(20_000)


def test_asking_for_a_solved_slice_s_job_keeps_it_cached(sourced, solves):
    """A list's stretch windows already solved make no job, and asking marks
    them recently used: what the list lands then evicts other slices, never
    the windows it is completing (#120)."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    slices = [engine.slice_at(SliceWindow(k, k + 1)) for k in range(SOLVED_SLICES_KEPT + 1)]
    for values, coverage in slices[:-1]:
        engine.finish(values, coverage, MC)
    assert len(engine._solved) == SOLVED_SLICES_KEPT
    assert engine.pending_solve(*slices[0], MC) is None  # solved: no job
    engine.finish(*slices[-1], MC)  # one more evicts the least recently used
    solved = len(solves)
    engine.finish(*slices[0], MC)
    assert len(solves) == solved, "the slice asked for must still be cached"
    engine.finish(*slices[1], MC)
    assert len(solves) == solved + 1, "the next oldest went instead"


def test_finish_is_slow_follows_the_last_solve(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    cached = engine.slice_at(SliceWindow(4, 14))
    fresh = engine.slice_at(SliceWindow(20, 30))
    assert engine.finish_is_slow(*fresh, MC), "no plan yet, so no solve is timed on it"
    engine.finish(*cached, MC)  # builds the plan (which resets the timing), then solves
    assert engine._last_solve_ms is not None
    for ms, slow in ((None, True), (10.0, False), (80.0, True)):
        engine._last_solve_ms = ms
        assert engine.finish_is_slow(*fresh, MC) is slow, ms
        assert engine.finish_is_slow(*cached, MC) is False, ms
    engine._last_solve_ms = LIVE_SOLVE_BUDGET_MS  # slow means over the budget
    assert engine.finish_is_slow(*fresh, MC) is False
    engine._last_solve_ms = 80.0
    assert engine.finish_is_slow(*fresh, SliceFinish(method="kriging")) is False
    assert engine.finish_is_slow(*fresh, SliceFinish(method="none")) is False


def test_a_pending_solve_lands_in_the_cache(sourced, solves):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    want = _curvature_finish(engine, values, coverage, MC)
    solves.clear()
    mine = values.copy()
    job = engine.pending_solve(mine, coverage, MC)
    assert isinstance(job, PendingSolve)
    assert job.key == solve_key(values)
    assert job.solved is None and job.ms is None
    mine[np.isfinite(mine)] = 0.0  # the job solves its own copy
    job.run(lambda: False)
    assert len(solves) == 1
    assert job.ms is not None
    np.testing.assert_array_equal(job.solved, want)
    assert job.land() is True
    drawn = engine.finish(values, coverage, MC)
    assert len(solves) == 1, "a landed solve must be served from the cache"
    assert engine._last_solve_ms == job.ms
    np.testing.assert_array_equal(drawn, job.solved)
    assert engine.pending_solve(values, coverage, MC) is None
    assert engine.pending_solve(values, coverage, SliceFinish(method="kriging")) is None
    assert engine.weights_cached(MC), "asking for another method's job built nothing"


@pytest.mark.parametrize("change", ["source", "cell"])
def test_a_solve_for_a_dropped_plan_does_not_land(sourced, change):
    """Review Focus 3: a solve that finishes after the plan it was made from
    was dropped must not land, even for the very same values."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    job = engine.pending_solve(values, coverage, MC)
    if change == "source":
        engine.set_source(engine.choice)
        assert engine.wait_for_preparation(20_000)
        engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    else:
        engine.set_resolution(Resolution(cell=0.2, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    engine.preview(*engine.slice_at(SliceWindow(4, 14)), MC)  # the new plan, nothing solved
    assert engine.weights_cached(MC)
    job.run(lambda: False)
    assert job.solved is not None
    assert job.land() is False
    assert len(engine._solved) == 0
    assert engine._last_solve_ms is None


def test_the_minimum_curvature_stretch_is_measured_over_twelve_windows_at_most(sourced, solves):
    """Plan call 7: at most twelve windows, each solved in the background;
    until they are, the same measurement over their previews stands in."""
    engine, session, _, _ = sourced
    _prepare(engine, session, transform=NO_TRANSFORM)
    z = engine.z
    windows = limit_windows(z, 1)
    assert z.nz > SITE_LIMIT_WINDOWS
    assert len(windows) == SITE_LIMIT_WINDOWS
    clip = PercentileClip()
    jobs = engine.stretch_solves(1, MC)
    assert len(jobs) == len(windows)
    assert len(solves) == 0, "handing out jobs solves nothing"
    previews = [engine.preview(*engine._slice(w), MC) for w in windows]
    provisional = engine.shared_limit(1, clip, MC, preview=True)
    assert provisional == pytest.approx(limit_over_slices(previews, clip))
    assert engine.stretch_limit(1, clip, MC) == (provisional, False)
    assert len(solves) == 0
    for job in jobs:
        job.run(lambda: False)
        assert job.land()
    ran = len(solves)
    assert engine.stretch_solves(1, MC) == []
    final = engine.shared_limit(1, clip, MC)
    assert len(solves) == ran, "the stretch must be measured over the landed solves"
    assert engine.stretch_limit(1, clip, MC) == (final, True)
    assert len(solves) == ran
    finished = [engine.finish(*engine._slice(w), MC) for w in windows]
    assert final == pytest.approx(limit_over_slices(finished, clip))
    assert engine.stretch_solves(1, SliceFinish()) == []
    kriging = SliceFinish()
    assert engine.stretch_limit(1, clip, kriging) == (engine.shared_limit(1, clip, kriging), True)


def test_a_rebuild_drops_the_old_plan_before_building_the_new(sourced, monkeypatch):
    """Holding the old plan, preview and solved slices while the new ones
    are built would double the peak: about 0.9 GB more at the cell cap."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    engine.finish(values, coverage, MC)
    assert engine.weights_nbytes > 0
    held_while_building: list[int] = []
    real = slices_engine.plan_fill

    def watching(*args, **kwargs):
        held_while_building.append(engine.weights_nbytes)
        return real(*args, **kwargs)

    monkeypatch.setattr(slices_engine, "plan_fill", watching)
    engine.finish(values, coverage, dataclasses.replace(MC, max_distance_spacings=1.0))
    assert held_while_building == [0, 0], "the plan, then its preview, built over nothing"


def test_weights_nbytes_counts_the_plan_the_preview_and_the_cache(sourced):
    """Plan call 9: what the status line names as held."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    engine.finish(values, coverage, MC)
    settings = engine.finish_settings(MC)
    cell, md, sr = engine.frame.cell, settings.max_distance_m, settings.search_radius_m
    plan = plan_fill(coverage > 0, cell, "min_curvature", md, sr)
    preview = plan_fill(coverage > 0, cell, "kriging", md, sr)
    solved = plan.apply(values)
    assert engine.weights_nbytes == plan.nbytes + preview.nbytes + solved.nbytes
    engine.finish(values, coverage, SliceFinish())  # kriging holds its weights alone
    assert engine.weights_nbytes == preview.nbytes


def test_the_estimate_counts_the_method_of_the_weights_held(sourced):
    """#148: once a minimum-curvature plan is held, the status line and the
    residency choice count it beside its kriging preview. The engine is handed
    a finish only when it draws, so before that it counts one set of weights."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    one_set = engine.frame.n_cells * WEIGHT_BYTES_PER_CELL
    assert engine.estimate.weights_bytes == one_set
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    engine.finish(values, coverage, MC)
    plan = engine.frame.n_cells * CURVATURE_PLAN_BYTES_PER_CELL
    assert engine.estimate.weights_bytes == one_set + plan
    engine.finish(values, coverage, SliceFinish(method="idw"))
    assert engine.estimate.weights_bytes == one_set


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
    """One way a chosen grid disappears out from under a prepared source:
    the lines are removed or reassigned first, THEN the now-empty grid is
    removed. The next test covers the other, the grid going with its
    lines in one step (#31)."""
    engine, session, errors, _ = sourced
    _prepare(engine, session)
    for key in list(session.keys()):
        session.remove_line(key)
    session.remove_grid("A")
    assert not engine.is_prepared
    assert any("A" in msg for _, msg in errors), errors


def test_removing_the_chosen_grid_with_its_lines_is_reported_too(sourced):
    engine, session, errors, _ = sourced
    _prepare(engine, session)
    session.remove_grid("A", with_lines=True)
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

    #41: `choice_b` is set only once `choice_a`'s task has really started.
    A task cancelled while still QUEUED is terminated synchronously, so
    no overlap could happen on that run and this test passed vacuously;
    that path has its own test, `test_cancelling_a_choice_still_queued_
    ends_it_at_once_and_the_new_choice_wins`.
    """
    engine, session, errors, _ = sourced
    concurrent = 0
    max_concurrent = 0
    lock = threading.Lock()
    started = threading.Event()
    real_load = Line.load

    def slow_load(self: Line) -> list:
        nonlocal concurrent, max_concurrent
        started.set()
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
    assert started.wait(5), "choice_a's task never started"
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
    iteration of the nested loop, long before the patched `load` lets the
    cancelled task actually clear, so the reentrant call is guaranteed to
    land INSIDE the wait, not after it -- PROVIDED
    `QgsApplication.taskManager()`'s thread pool is already warm. Measured
    directly: run as the first test to ever dispatch a `QgsTask` in a
    fresh `qgis_app` process, the very first task's own thread start-up
    latency is itself long enough to blow past that window and this test
    fails even against the fix (`wait_for_preparation(20_000)` itself
    returns `False`) -- a test-isolation artefact, not evidence against
    the fix (run straight after any other test in this file that
    dispatches one first, it passes reliably). The warm-up dispatch below
    removes that dependency on execution order.

    Final review: widened, not marked. This test flaked ONCE under
    concurrent CPU load (confirmed not a regression: 3/3 isolated, 2/2
    clean full-suite reruns) -- timing-dependent by construction, and CI
    runners are contended, which is the most likely source of an
    intermittent red build on this branch. The patched `load`'s sleep
    moved from 50 ms to 150 ms: `_CANCEL_TIMEOUT_MS` (250 ms) is the only
    other constant this test's timing is pinned against, and 150 ms still
    leaves it comfortable headroom (cancellation clears after roughly one
    slow `load` plus the cheap remainder of `work()`'s loop, so still well
    under 250 ms) while tripling the margin the zero-delay timer has to
    land inside the wait before contention could push it past that
    window. No assertion here was loosened -- `max_concurrent <= 1` and
    "the latest choice wins" are exactly as strict as before.

    #41, the actual cause of the intermittent failure: `choice_b` used to
    follow `choice_a` within microseconds, before a worker had picked
    `choice_a`'s task up. Cancelling a task that is still QUEUED
    terminates it synchronously, inside `cancel()` (probed on QGIS 3.44),
    so `_running` was already False, `_cancel_in_flight` never spun its
    nested loop, and the timer fired in the final `wait_for_preparation`
    instead. There its `set_source` finished `choice_b` (waking the wait)
    and dispatched `choice_c`, so the wait returned False at once: `True
    and not _running`. Not a hang (it failed in ~0.2 s) and not an engine
    bug -- `choice_c` still won, with no errors. Reproduced every time by
    occupying the task manager's workers so `choice_a` stays queued. The
    test now waits until `choice_a`'s task is really running, and checks
    the timer did fire inside the cancel wait.
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
    started = threading.Event()
    real_load = Line.load

    def slow_load(self: Line) -> list:
        nonlocal concurrent, max_concurrent
        started.set()
        with lock:
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
        try:
            # Final review: widened from 50 ms to 150 ms -- see the
            # docstring above for why this is still comfortably inside
            # `_CANCEL_TIMEOUT_MS` (250 ms).
            time.sleep(0.15)
            return real_load(self)
        finally:
            with lock:
                concurrent -= 1

    monkeypatch.setattr(Line, "load", slow_load)

    choice_a = SourceChoice(grid_id="A", preset="p", transform=NO_TRANSFORM, line_keys=keys)
    choice_b = SourceChoice(grid_id="A", preset="p", transform="amp_envelope", line_keys=keys)
    choice_c = SourceChoice(grid_id="A", preset="p", transform="amp_abs", line_keys=keys)

    fired_while_dispatching: list[bool] = []

    def deliver_c() -> None:
        fired_while_dispatching.append(engine._dispatching)
        engine.set_source(choice_c)

    engine.set_source(choice_a)
    assert started.wait(5), "choice_a's task never started"
    QTimer.singleShot(0, deliver_c)
    engine.set_source(choice_b)  # cancels choice_a; the timer fires during THIS wait
    assert fired_while_dispatching == [True], "choice_c must arrive inside the cancel wait"
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


def test_cancelling_a_choice_still_queued_ends_it_at_once_and_the_new_choice_wins(
    sourced, monkeypatch
):
    """#41: a task cancelled before any worker picked it up is terminated
    synchronously, inside `cancel()`, so its `finished` runs from inside
    `_cancel_in_flight`, which then has nothing left to wait for. Every
    worker is held busy here so `choice_a` is certainly still queued. It
    must never run, its cancel must not be reported, and `choice_b` wins."""
    engine, session, errors, _ = sourced
    keys = tuple(session.keys())
    loads = 0
    lock = threading.Lock()
    real_load = Line.load

    def counted_load(self: Line) -> list:
        nonlocal loads
        with lock:
            loads += 1
        return real_load(self)

    monkeypatch.setattr(Line, "load", counted_load)
    release = threading.Event()
    held: list[int] = []
    # Kept in this list until each one's `finished` has run: the task
    # manager holds no Python reference of its own.
    blockers = [
        QgsTask.fromFunction(
            f"nsgeo test: hold worker {i}",
            lambda task: release.wait(20),
            on_finished=lambda exception, result=None: held.append(1),
        )
        for i in range(QThread.idealThreadCount())
    ]
    choice_a = SourceChoice(grid_id="A", preset="p", transform=NO_TRANSFORM, line_keys=keys)
    choice_b = SourceChoice(grid_id="A", preset="p", transform="amp_envelope", line_keys=keys)
    try:
        for blocker in blockers:
            assert QgsApplication.taskManager().addTask(blocker)
        assert spin_until(
            lambda: all(b.status() == QgsTask.TaskStatus.Running for b in blockers), 5_000
        ), "could not occupy every worker"
        engine.set_source(choice_a)
        assert [t.status() for t in engine._pending] == [QgsTask.TaskStatus.Queued]
        engine.set_source(choice_b)
        assert engine.choice == choice_b
        assert len(engine._pending) == 1, "choice_a's task should be gone already"
    finally:
        release.set()
        assert spin_until(lambda: len(held) == len(blockers), 20_000)
    assert engine.wait_for_preparation(20_000)
    assert engine.choice == choice_b
    assert engine.output_unipolar is True
    assert loads == len(keys), "only choice_b's lines are read: choice_a never ran"
    assert errors == [], errors


def test_clear_during_a_live_preparation_cancels_and_waits_before_anything_else_runs(
    sourced, monkeypatch
):
    """Final review, Important 2. `clear()` used to set `_running = False`
    directly without ever cancelling `_pending`, and `_cancel_in_flight`'s
    own confirm-and-wait is gated on `if self._running` -- so the very
    NEXT call into it (the ordinary `site_closed -> clear()` then
    `site_opened -> ... -> set_source()` sequence, i.e. "File > Open
    site...") saw `_running` already `False` and skipped the wait
    entirely, even though a task genuinely dispatched before `clear()`
    was still executing on a worker thread. Reproduced directly: `clear()`
    while a real task is executing, immediately followed by a new
    `set_source()` -- the same `max_concurrent` discriminator
    `test_two_different_choices_back_to_back_never_run_concurrently` uses
    for the sibling hazard."""
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
    engine.set_source(SourceChoice(grid_id="A", preset="p", transform=NO_TRANSFORM, line_keys=keys))
    assert engine.is_running, "the fixture's own preparation must still be in flight"

    engine.clear()  # the site-closed path -- must not leave the task running unwaited
    assert engine._pending == set(), (
        "clear() must cancel and CONFIRM (wait for) any live preparation, not merely forget it"
    )

    engine.set_source(
        SourceChoice(grid_id="A", preset="p", transform="amp_envelope", line_keys=keys)
    )
    assert engine.wait_for_preparation(20_000)

    assert max_concurrent <= 1, (
        f"two tasks executed work() concurrently (max_concurrent={max_concurrent}); "
        "clear() must cancel and wait out any live preparation before returning"
    )
    assert engine.output_unipolar is True  # the new (amp_envelope) choice landed
    assert engine.line_count == len(keys)
    assert errors == [], errors


def test_provenance_survives_a_contributing_line_being_removed(sourced):
    """A line can be deleted from the survey while a source stays
    prepared. The cube's arrays are still correct, so provenance must
    keep working -- `cube()`, "Save cube..." and "Export GeoTIFF" all
    route through it, and a raw KeyError there blanks the map and breaks
    both exports for an ordinary survey edit."""
    engine, session, errors, _ = sourced
    _prepare(engine, session)
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))

    first = session.keys()[0]
    session.remove_line(first)

    prov = engine.provenance()  # must not raise
    assert prov.velocity is not None  # a surviving line supplied it
    assert engine.cube() is not None  # the path that actually broke


def test_provenance_velocity_is_none_when_all_prepared_lines_removed(sourced):
    """When all prepared lines are removed from the survey, provenance
    still works but velocity is None, which `window_label` omits from the
    depth LABEL -- the only honest consequence of losing all velocity
    sources."""
    engine, session, errors, _ = sourced
    _prepare(engine, session)
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))

    for key in list(session.keys()):
        session.remove_line(key)

    prov = engine.provenance()  # must not raise
    assert prov.velocity is None  # no lines left to supply it
    assert engine.cube() is not None  # arrays are still there


# ---- M12: the hooks the site engine composes this engine through ----------


def test_with_a_grid_moved_hook_a_move_clears_and_hands_over_instead_of_re_preparing(sourced):
    """R-P2 (M12). M11's self-dispatch on a grid move is a preparation
    started outside whatever serialises this engine against others (trap
    1). With `on_grid_moved` set, a move drops the stale lines -- which
    were binned at the old registration -- and hands the re-preparation to
    the owner, who queues it; this engine starts nothing itself."""
    engine, session, errors, prepared = sourced
    moved: list[int] = []
    engine.on_grid_moved = lambda: moved.append(1)
    _prepare(engine, session)
    count = len(prepared)

    session.replace_grid(Grid("A", (600.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    assert moved == [1]
    assert not engine.is_running, "the engine dispatched the re-preparation itself"
    assert not engine.is_prepared, "lines binned at the old registration were kept"
    assert engine.choice is None
    assert engine.frame is None
    assert engine.wait_for_preparation(2_000)
    assert len(prepared) == count
    assert errors == []

    # A velocity-only edit is still not a move.
    _prepare(engine, session)
    session.set_grid_velocity("A", VelocityModel.constant(0.09))
    assert moved == [1]
    assert engine.is_prepared


def test_a_raising_grid_moved_hook_is_reported_not_propagated(sourced):
    """The hook runs inside a slot on `grids_changed`; an exception there
    would escape into Qt (the CI container aborts on it). It is reported
    through `on_error` instead, and the engine is still cleared."""
    engine, session, errors, _ = sourced

    def _raise() -> None:
        raise RuntimeError("boom")

    engine.on_grid_moved = _raise
    _prepare(engine, session)
    session.replace_grid(Grid("A", (600.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    assert not engine.is_prepared
    assert any("boom" in msg for _, msg in errors), errors


def test_the_hook_can_be_given_to_the_constructor(qgis_app):
    """Task 5 sets it on the dock's engine as an attribute; the site
    engine passes it when it builds its own."""
    session = SiteSession()

    def hook() -> None:
        return None

    engine = SliceEngine(session, on_grid_moved=hook)
    try:
        assert engine.on_grid_moved is hook
        assert SliceEngine(session).on_grid_moved is None
    finally:
        engine.dispose()


def test_cancel_preparation_stops_the_task_and_keeps_nothing_else_running(sourced, monkeypatch):
    """Ruling 1 (M12): the site engine leaves site scope with `cancel()`,
    which must stop the one preparation in flight -- and confirm it
    stopped -- without the engine starting anything else."""
    engine, session, errors, _ = sourced
    real_load = Line.load

    def slow_load(self: Line) -> list:
        time.sleep(0.05)
        return real_load(self)

    monkeypatch.setattr(Line, "load", slow_load)
    keys = tuple(session.keys())
    engine.set_source(SourceChoice(grid_id="A", preset="p", transform=NO_TRANSFORM, line_keys=keys))
    assert engine.is_running
    engine.cancel_preparation()
    assert not engine.is_running
    assert engine._pending == set()
    assert errors == [], errors


def test_closing_the_site_mid_preparation_stops_promptly_and_silently(sourced, monkeypatch):
    """Ruling T3-e (M12). The task's `finished` used to return silently for
    a site that is gone, so the confirm wait in `clear()` (`site_closed`)
    never woke: it sat out the whole `_CANCEL_TIMEOUT_MS` and then reported
    "did not stop in time" about a task that had stopped. That edge is this
    request's own (any newer request bumps the generation first), so it
    must end the wait at once -- applying nothing and reporting nothing."""
    engine, session, errors, prepared = sourced
    real_load = Line.load

    def slow_load(self: Line) -> list:
        time.sleep(0.05)
        return real_load(self)

    monkeypatch.setattr(Line, "load", slow_load)
    keys = tuple(session.keys())
    engine.set_source(SourceChoice(grid_id="A", preset="p", transform=NO_TRANSFORM, line_keys=keys))
    assert engine.is_running
    started = time.perf_counter()
    session.close_site()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert errors == [], errors
    assert elapsed_ms < slices_engine._CANCEL_TIMEOUT_MS, f"close took {elapsed_ms:.0f} ms"
    assert not engine.is_running and not engine.has_live_task
    assert prepared == [], "a preparation for a closed site was reported as finished"


def test_has_live_task_outlasts_a_clear_whose_wait_gave_up(sourced, monkeypatch):
    """Ruling T3-b (M12). `clear()` sets `is_running` False even when its
    bounded wait gave up and the task is still reading a line -- the
    meaning M11's dock relies on. `has_live_task` is the truth a dispatcher
    needs: a task may still be executing until its `finished` has run."""
    engine, session, errors, _ = sourced
    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 1)
    real_load = Line.load
    reading = threading.Event()

    def slow_load(self: Line) -> list:
        reading.set()
        time.sleep(0.15)
        return real_load(self)

    monkeypatch.setattr(Line, "load", slow_load)
    keys = tuple(session.keys())
    engine.set_source(SourceChoice(grid_id="A", preset="p", transform=NO_TRANSFORM, line_keys=keys))
    assert reading.wait(5.0)
    engine.clear()
    assert not engine.is_running
    assert engine.has_live_task, "the abandoned task is still reading a line"
    deadline = time.monotonic() + 5.0
    while engine.has_live_task and time.monotonic() < deadline:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 5)
        time.sleep(0.002)
    assert not engine.has_live_task
    assert any("did not stop in time" in msg for _, msg in errors), errors


def test_residency_is_chosen_from_the_prepared_trace_count(sourced, monkeypatch):
    """Ruling T3-c (M12): the engine costs streaming from the traces it
    actually holds, not from its line count. With the per-trace rate
    raised so that these four 60-trace lines (240 traces) cost more than a
    frame, the engine goes resident; costed by four lines it would not."""
    from nsgeo_qgis import slices_plan

    engine, session, _, _ = sourced
    _prepare(engine, session)
    assert engine.mode == "streaming"  # 240 traces: far under a frame
    monkeypatch.setattr(slices_plan, "STREAM_MS_PER_TRACE", slices_plan.FRAME_BUDGET_MS / 200)
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    assert engine.mode == "resident"


# ---- line editing (spec §4.5): a source follows a line that moved ----------

GRID_B = Grid("B", (600.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)


def _edit(session, key, **changes):
    return session.edit_lines([LineEdit(key, session.line_for_key(key).placement, **changes)])


def test_a_placement_edit_to_a_prepared_line_re_prepares(sourced):
    engine, session, errors, prepared = sourced
    _prepare(engine, session)
    count = len(prepared)
    key = session.keys()[0]

    _edit(session, key, offset=1.5)
    assert engine.wait_for_preparation(20_000)
    assert len(prepared) == count + 1
    line = next(p for p in engine.prepared_lines() if p.key == key)
    expected = session.line_for_key(key).trace_coords(session.site.frames)
    assert np.asarray(line.coords) == pytest.approx(np.asarray(expected), abs=1e-9)
    assert errors == []


def test_a_scale_or_destagger_edit_to_a_prepared_line_re_prepares(sourced):
    engine, session, errors, prepared = sourced
    _prepare(engine, session)
    key = session.keys()[0]
    for change in ({"scale": 0.95}, {"travel_shift": 0.2}):
        count = len(prepared)
        _edit(session, key, **change)
        assert engine.wait_for_preparation(20_000)
        assert len(prepared) == count + 1
        line = next(p for p in engine.prepared_lines() if p.key == key)
        expected = session.line_for_key(key).trace_coords(session.site.frames)
        assert np.asarray(line.coords) == pytest.approx(np.asarray(expected), abs=1e-9)
    assert errors == []


def test_an_edit_to_a_line_outside_the_source_does_not_re_prepare(sourced):
    engine, session, errors, prepared = sourced
    keys = session.keys()
    engine.set_source(
        SourceChoice(grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(keys[:3]))
    )
    assert engine.wait_for_preparation(20_000)
    count = len(prepared)

    _edit(session, keys[3], offset=1.5)
    assert not engine.is_running
    assert engine.wait_for_preparation(2_000)
    assert len(prepared) == count
    assert errors == []


def test_a_label_only_edit_does_not_re_prepare(sourced):
    engine, session, errors, prepared = sourced
    _prepare(engine, session)
    count = len(prepared)

    _edit(session, session.keys()[0], label="the wall")
    assert not engine.is_running
    assert engine.wait_for_preparation(2_000)
    assert len(prepared) == count
    assert errors == []


def test_a_line_moved_to_another_grid_leaves_the_source(sourced):
    engine, session, errors, prepared = sourced
    session.add_grid(GRID_B)
    _prepare(engine, session)
    k3 = session.keys()[3]

    session.move_lines([k3], "B")
    assert engine.wait_for_preparation(20_000)
    assert k3 not in engine.choice.line_keys
    assert k3 not in [p.key for p in engine.prepared_lines()]
    assert engine.line_count == 3
    assert errors == []


def test_with_a_grid_moved_hook_a_placement_edit_hands_over(sourced):
    """Mirrors the grid-move hand-over: a re-preparation started from this
    slot would sit outside the owner's queue (trap 1, R-P5)."""
    engine, session, errors, prepared = sourced
    moved: list[int] = []
    engine.on_grid_moved = lambda: moved.append(1)
    _prepare(engine, session)
    count = len(prepared)

    _edit(session, session.keys()[0], offset=1.5)
    assert moved == [1]
    assert not engine.is_running, "the engine dispatched the re-preparation itself"
    assert not engine.is_prepared, "lines binned at the old placement were kept"
    assert engine.choice is None
    assert engine.wait_for_preparation(2_000)
    assert len(prepared) == count
    assert errors == []


def test_a_grid_length_change_re_prepares_exactly_once(sourced):
    """`replace_grid` moves the reversed lines, then emits `grids_changed`
    (the fingerprint moved: one re-preparation) and `lines_changed` (which
    finds the snapshot already current)."""
    engine, session, errors, prepared = sourced
    p = synthetic_dzt(session.root / "raw", "FILE__009.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 5.0, 6.0, -1, p.stem))])
    _prepare(engine, session)
    count = len(prepared)

    session.replace_grid(dataclasses.replace(GRID, size_y=7.0))
    assert engine.wait_for_preparation(20_000)
    assert len(prepared) == count + 1
    assert errors == []


def test_set_source_leaves_out_a_key_now_on_another_grid_and_says_so(sourced):
    engine, session, errors, prepared = sourced
    session.add_grid(GRID_B)
    keys = session.keys()
    session.move_lines([keys[3]], "B")

    engine.set_source(
        SourceChoice(grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(keys))
    )
    assert engine.wait_for_preparation(20_000)
    assert [p.key for p in engine.prepared_lines()] == list(keys[:3])
    assert any("now on grid 'B', not 'A'" in msg for _, msg in errors), errors


#: Migration in a preset. `sample` mode rather than `first_break` because
#: the synthetic's flat band sits at row 40, nine samples earlier than a
#: real first break (k=49 on every local line), which would leave t0 at
#: -2.43 ns -- outside migration's 2.0 ns tolerance. Sample 51 lands it at
#: -0.04 ns, which is where a real line's time zero ends up.
MIGRATING_PRESET = [
    {"step": "time_zero", "params": {"mode": "sample", "sample": 51}, "enabled": True},
    {"step": "migrate_fk", "params": {"velocity_m_ns": 0.0733}, "enabled": True},
]


def test_migration_reaches_the_cube_through_the_preset_alone(qgis_app, tmp_path):
    """Spec section 8: the slices engine needs no change at all.

    Two lines of DIFFERENT trace counts, one preset, one velocity. Each
    comes back migrated, at its own trace count and its own dx_m, with
    nothing carried from one `apply` call into the next.
    """
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    # Different trace counts AND different trace spacings: the aperture pad
    # migration derives is `vm * t_max / dx_m`, so a shared `dx_m` would let
    # one spacing stand in for both and the test would not notice.
    shapes = {"FILE__001.DZT": (60, 60.0), "FILE__002.DZT": (97, 40.0)}
    lines = []
    for i, (name, (n_traces, tpm)) in enumerate(shapes.items()):
        path = synthetic_dzt(tmp_path / "raw", name, n_traces=n_traces, traces_per_metre=tpm)
        lines.append(Line.open(path, GridPlacement("A", "y", 1.0 + i, 0.0, 1, path.stem)))
    session.add_lines(lines)
    assert sorted(round(Radargram.from_profile(line.load()[0]).dx_m, 6) for line in lines) == [
        round(1 / 60.0, 6),
        round(1 / 40.0, 6),
    ]
    session.site.presets["plain"] = [MIGRATING_PRESET[0]]
    session.site.presets["migrating"] = list(MIGRATING_PRESET)

    errors: list[str] = []
    engine = SliceEngine(session, on_prepared=lambda: None, on_error=errors.append)
    try:
        _prepare(engine, session, transform=NO_TRANSFORM, preset="plain")
        plain = {line.key: np.array(line.data) for line in engine.prepared_lines()}
        _prepare(engine, session, transform=NO_TRANSFORM, preset="migrating")
        migrated = {line.key: np.array(line.data) for line in engine.prepared_lines()}
    finally:
        engine.dispose()

    assert errors == []
    assert len(migrated) == 2
    for key, before in plain.items():
        after = migrated[key]
        assert after.shape == before.shape, "migration must not change the trace count"
        assert np.all(np.isfinite(after))
        assert not np.allclose(after, before), f"{key} came back unmigrated"
    # Each at its own trace count, so one preset really did serve two
    # differently shaped lines.
    assert sorted(a.shape[1] for a in migrated.values()) == [60, 97]


def test_section_fills_reuse_the_held_weights(sourced, monkeypatch):
    """A cut never plans weights of its own (cut spec §5): it takes the engine's."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    cube = engine.cube()
    krig = SliceFinish(method="kriging", max_distance_spacings=2.0)
    engine.finish(cube.level(3), cube.coverage(), krig)  # what the dock's draw does
    held = engine._weights[1]
    planned = []
    real = slices_engine.plan_fill

    def counting(*args, **kwargs):
        planned.append(args[2])
        return real(*args, **kwargs)

    monkeypatch.setattr(slices_engine, "plan_fill", counting)
    fill, preview = engine.section_fills(krig)
    assert fill is held and preview is None
    assert planned == []
    # Under minimum curvature the second element is the kriging stand-in.
    mc = dataclasses.replace(krig, method="min_curvature")
    engine.finish(cube.level(3), cube.coverage(), mc)
    planned.clear()
    plan, standin = engine.section_fills(mc)
    assert isinstance(plan, CurvaturePlan)
    assert standin is not None and standin is engine._weights[2]
    assert planned == []
    # A different finish builds through the engine's own path, and holds it.
    other = dataclasses.replace(krig, max_distance_spacings=1.0)
    fill2, _ = engine.section_fills(other)
    assert fill2 is engine._weights[1]


def test_section_fills_refuse_to_build_a_cube_and_the_generation_follows_it(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.drop_cube()
    assert not engine.has_cube
    with pytest.raises(RuntimeError):
        engine.section_fills(SliceFinish())
    assert not engine.has_cube  # nothing was built through it
    before = engine.cube_generation
    engine.cube()
    assert engine.cube_generation == before + 1
    engine.section_fills(SliceFinish())
    assert engine.cube_generation == before + 1  # reading the fills moves nothing
    # A rebuild with the same choice, frame and axis is another generation.
    choice, frame, z = engine.choice, engine.frame, engine.z
    engine.drop_cube()
    engine.cube()
    assert (engine.choice, engine.frame, engine.z) == (choice, frame, z)
    assert engine.cube_generation == before + 3
