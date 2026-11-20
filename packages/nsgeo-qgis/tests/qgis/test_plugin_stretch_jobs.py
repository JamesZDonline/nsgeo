"""The shared stretch measured by a job equals today's synchronous one (#193)."""

from __future__ import annotations

import gc
import weakref

import numpy as np
import pytest
from nsgeo.render import PercentileClip, UnipolarClip
from nsgeo.slices import SliceWindow, SolveStopped, plan_fill
from nsgeo_qgis import site_engine, slices_engine, stretch_jobs
from nsgeo_qgis.slices_plan import SliceFinish
from test_plugin_site_engine import FINISH, MC, prepared
from test_plugin_slices_engine import _prepare, sourced  # noqa: F401 -- fixture


def _count_builds(monkeypatch) -> list[int]:
    """Count every `build_fill`, the one fill rule, from any thread."""
    calls: list[int] = []
    real = slices_engine.build_fill
    monkeypatch.setattr(
        slices_engine, "build_fill", lambda *a, **k: calls.append(1) or real(*a, **k)
    )
    return calls


THICKNESS = 5  # levels: does not divide the 56-level axis, so a tail window is measured


def _slice_cases():
    return [
        pytest.param("idw", True, False, id="idw-resident"),
        pytest.param("kriging", False, False, id="kriging-streaming"),
        pytest.param("min_curvature", False, False, id="min-curvature-unsolved"),
        pytest.param("min_curvature", True, True, id="min-curvature-solved"),
    ]


@pytest.mark.parametrize(("method", "resident", "solve"), _slice_cases())
def test_this_grids_stretch_job_equals_stretch_limit(sourced, monkeypatch, method, resident, solve):  # noqa: F811
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.set_always_resident(resident)
    assert engine.mode == ("resident" if resident else "streaming")
    finish = SliceFinish(method=method)
    clip = PercentileClip()
    cold = engine.stretch_job(THICKNESS, clip, finish)  # nothing held: the job builds
    cold.run(lambda: False)
    if solve:
        for job in engine.stretch_solves(THICKNESS, finish):
            job.run(lambda: False)
            assert job.land()
    if not solve:  # hold the fill alone: nothing solved, so the preview stays provisional
        _, cov = engine.slice_at(SliceWindow(0, 1))
        held = engine.fill_job(cov, finish)
        held.run(lambda: False)
        assert held.land() is True
    builds = _count_builds(monkeypatch)
    warm = engine.stretch_job(THICKNESS, clip, finish)
    warm.run(lambda: False)
    assert builds == [], "a warm job must reuse the held fill, never build one"
    expected_limit, expected_final = engine.stretch_limit(THICKNESS, clip, finish)
    assert expected_final is (method != "min_curvature" or solve)
    assert warm.limit == expected_limit
    assert warm.final is expected_final
    if not solve:
        assert (cold.limit, cold.final) == (expected_limit, expected_final)
    if method == "min_curvature" and not solve:
        assert warm.limit == engine.shared_limit(THICKNESS, clip, finish, preview=True)
    assert warm.land() is True


NORMALISATIONS = ["none", "background", "edge"]


@pytest.mark.parametrize("method", NORMALISATIONS)
@pytest.mark.parametrize("finish", [FINISH, MC], ids=["idw", "min-curvature-unsolved"])
def test_the_sites_stretch_job_equals_stretch_limit(site3, make_site, method, finish):
    site, _ = prepared(make_site, site3)
    clip = UnipolarClip()
    tick = {"finish": finish, "method": method, "manual": {"B": 2.5}}
    job = site.stretch_job(2.0, clip, **tick)
    job.run(lambda: False)
    expected_limit, expected_final = site.stretch_limit(2.0, clip, **tick)
    assert job.limit == expected_limit
    assert job.final is expected_final
    assert expected_final is (finish is not MC)
    again = site.stretch_job(2.0, clip, **tick)  # now with fills held
    again.run(lambda: False)
    assert (again.limit, again.final) == (expected_limit, expected_final)


def test_a_site_stretch_job_over_solved_windows_is_final(site3, make_site):
    site, _ = prepared(make_site, site3)
    clip = UnipolarClip()
    tick = {"finish": MC, "method": "background", "manual": {"A": 1.5}}
    for job in site.stretch_solves(2.0, MC):
        job.run(lambda: False)
        assert job.land()
    job = site.stretch_job(2.0, clip, **tick)
    job.run(lambda: False)
    expected = site.stretch_limit(2.0, clip, **tick)
    assert expected[1] is True
    assert (job.limit, job.final) == expected


def test_a_window_with_other_covered_cells_gets_its_own_fill(sourced):  # noqa: F811
    """A held fill built for other covered cells (a line gone) is never reused for
    a window it does not match, nor replaced: the job builds its own."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.set_always_resident(False)
    finish = SliceFinish(method="idw")
    clip = PercentileClip()
    _, cov = engine.slice_at(SliceWindow(4, 14))
    narrowed = cov.copy()
    narrowed[:, : cov.shape[1] // 2] = 0
    assert (narrowed > 0).sum() < (cov > 0).sum()
    settings = engine.finish_settings(finish)
    held = plan_fill(
        narrowed > 0, engine.frame.cell, "idw", settings.max_distance_m, settings.search_radius_m
    )
    engine._weights = (engine._weights_key(engine.frame, settings), held, None)
    job = engine.stretch_job(THICKNESS, clip, finish)
    job.run(lambda: False)
    assert engine._weights[1] is held
    expected = engine.stretch_limit(THICKNESS, clip, finish)
    assert engine._weights[1] is not held  # today's path replaces it; the job did not
    assert (job.limit, job.final) == expected


def test_a_stretch_job_reads_its_fill_jobs_results(site3, make_site, monkeypatch):
    site, _ = prepared(make_site, site3)
    clip = UnipolarClip()
    tick = {"finish": FINISH, "method": "background", "manual": {}}
    for grid in site.ready_grids:  # every fill held, so only B's is the job's
        site.engine_for(grid).stretch_parts(FINISH)
    site.stretch_limit(2.0, clip, **tick)
    engine_b = site.engine_for("B")
    cov = engine_b.slice_at(SliceWindow(0, 1))[1]
    engine_b._drop_fill()
    fill_job = engine_b.fill_job(cov, FINISH)
    stretch = site.stretch_job(2.0, clip, **tick, fills={"B": fill_job})
    fill_job.run(lambda: False)
    builds = _count_builds(monkeypatch)
    stretch.run(lambda: False)
    assert builds == [], "B's fill is the fill job's, the others' are held"
    assert fill_job.land() is True
    expected = site.stretch_limit(2.0, clip, **tick)
    assert (stretch.limit, stretch.final) == expected


def test_a_stretch_job_whose_fill_landing_was_refused_measures_nothing(sourced):  # noqa: F811
    engine, session, _, _ = sourced
    _prepare(engine, session)
    finish = SliceFinish(method="idw")
    _, cov = engine.slice_at(SliceWindow(4, 14))
    fill_job = engine.fill_job(cov, finish)
    stretch = engine.stretch_job(THICKNESS, PercentileClip(), finish, fill=fill_job)
    fill_job.run(lambda: False)
    engine._drop_fill()  # the engine moved on: the landing is refused
    assert fill_job.land() is False
    assert fill_job.fill is None
    stretch.run(lambda: False)
    assert stretch.limit is None
    assert stretch.final is False


def test_a_stopped_stretch_job_raises(sourced):  # noqa: F811
    engine, session, _, _ = sourced
    _prepare(engine, session)
    job = engine.stretch_job(THICKNESS, PercentileClip(), SliceFinish(method="idw"))
    with pytest.raises(SolveStopped):
        job.run(lambda: True)
    assert job.limit is None


def test_a_stretch_job_leaves_its_inputs_alone(sourced):  # noqa: F811
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.set_always_resident(False)
    before = [line.data.copy() for line in engine._lines]
    job = engine.stretch_job(THICKNESS, PercentileClip(), SliceFinish(method="idw"))
    job.run(lambda: False)
    assert all(np.array_equal(b, line.data) for b, line in zip(before, engine._lines))


def test_a_cold_job_builds_the_fill_it_lacks(sourced, monkeypatch):  # noqa: F811
    engine, session, _, _ = sourced
    _prepare(engine, session)
    builds = _count_builds(monkeypatch)
    job = engine.stretch_job(THICKNESS, PercentileClip(), SliceFinish(method="idw"))
    job.run(lambda: False)
    assert builds == [1]  # one mask, built once
    assert engine._weights is None  # and never installed


@pytest.mark.parametrize("method", ["idw", "min_curvature"])
def test_a_stretch_job_uses_its_fill_jobs_fill_without_building(sourced, monkeypatch, method):  # noqa: F811
    """Reads `fill` (and, for minimum curvature, `preview`) from the fill job."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    finish = SliceFinish(method=method)
    _, cov = engine.slice_at(SliceWindow(0, 1))
    fill_job = engine.fill_job(cov, finish)
    stretch = engine.stretch_job(THICKNESS, PercentileClip(), finish, fill=fill_job)
    fill_job.run(lambda: False)
    builds = _count_builds(monkeypatch)
    stretch.run(lambda: False)
    assert builds == []
    assert fill_job.land() is True
    expected = engine.stretch_limit(THICKNESS, PercentileClip(), finish)
    assert (stretch.limit, stretch.final) == expected


def test_this_grids_stretch_job_streams_its_windows(sourced, monkeypatch):  # noqa: F811
    """Peak memory as today's `shared_limit`: one finished window alive at a time."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    finish = SliceFinish(method="idw")
    drawn: list[int] = []
    real = stretch_jobs.draw_window
    monkeypatch.setattr(
        stretch_jobs, "draw_window", lambda *a, **k: drawn.append(1) or real(*a, **k)
    )
    ahead: list[int] = []
    real_limit = stretch_jobs.limit_over_slices

    def watching(slices, clip):
        assert not isinstance(slices, (list, tuple))
        consumed = 0

        def counted():
            nonlocal consumed
            for item in slices:
                consumed += 1
                ahead.append(len(drawn) - consumed)
                yield item

        return real_limit(counted(), clip)

    monkeypatch.setattr(stretch_jobs, "limit_over_slices", watching)
    job = engine.stretch_job(THICKNESS, PercentileClip(), finish)
    job.run(lambda: False)
    assert len(ahead) > 3
    assert max(ahead) == 0, "a window was finished before the last was consumed"
    assert job.limit == engine.shared_limit(THICKNESS, PercentileClip(), finish)


@pytest.mark.parametrize("synchronous", [False, True], ids=["job", "stretch_limit"])
def test_the_sites_stretch_streams_its_windows(site3, make_site, monkeypatch, synchronous):
    """One window's grids alive at a time, not every window's: listing them all
    first held a full copy of every measured slice, which on the walkthrough's
    0.02 m Whole site helped push a full machine into swap."""
    site, _ = prepared(make_site, site3)
    clip = UnipolarClip()
    tick = {"finish": FINISH, "method": "background", "manual": {"B": 2.5}}
    expected = site.stretch_limit(2.0, clip, **tick)
    ahead: list[int] = []
    drawn: list[int] = []
    real_shown = stretch_jobs.shown_window

    def counting_shown(binned, *a, **k):
        drawn.append(len(binned))
        return real_shown(binned, *a, **k)

    real_limit = stretch_jobs.limit_over_slices

    def watching(slices, clip):
        consumed = 0

        def counted():
            nonlocal consumed
            for item in slices:
                consumed += 1
                ahead.append(sum(drawn) - consumed)
                yield item

        return real_limit(counted(), clip)

    monkeypatch.setattr(stretch_jobs, "shown_window", counting_shown)
    monkeypatch.setattr(site_engine, "shown_window", counting_shown)
    monkeypatch.setattr(stretch_jobs, "limit_over_slices", watching)
    if synchronous:
        got = site.stretch_limit(2.0, clip, **tick)
    else:
        job = site.stretch_job(2.0, clip, **tick)
        job.run(lambda: False)
        got = (job.limit, job.final)
    assert len(drawn) > 2, "the site's stretch measured fewer than three windows"
    assert max(ahead) < max(drawn), "a later window was drawn before this one was consumed"
    assert got == expected


def test_a_finished_stretch_job_lets_go_of_what_it_captured(sourced):  # noqa: F811
    engine, session, _, _ = sourced
    _prepare(engine, session)
    finish = SliceFinish(method="idw")
    _, cov = engine.slice_at(SliceWindow(0, 1))
    hold = engine.fill_job(cov, finish)
    hold.run(lambda: False)
    assert hold.land() is True
    job = engine.stretch_job(THICKNESS, PercentileClip(), finish)
    ref = weakref.ref(engine._weights[1])
    job.run(lambda: False)
    assert job.limit is not None
    engine._drop_fill()
    del hold
    gc.collect()
    assert ref() is None, "the finished job still holds the fill it captured"
    assert job.land() is True


def test_a_stopped_stretch_job_lets_go_too(sourced):  # noqa: F811
    engine, session, _, _ = sourced
    _prepare(engine, session)
    job = engine.stretch_job(THICKNESS, PercentileClip(), SliceFinish(method="idw"))
    with pytest.raises(SolveStopped):
        job.run(lambda: True)
    assert job._grids == {}
