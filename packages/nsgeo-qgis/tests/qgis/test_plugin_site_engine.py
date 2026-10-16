"""SiteEngine: one SliceEngine per grid, prepared one at a time, composed per tick."""

from __future__ import annotations

import dataclasses
import re
import time

import numpy as np
import pytest
from nsgeo.render import UnipolarClip
from nsgeo.slices import (
    NORMALISATION_METHODS,
    SiteLattice,
    SliceWindow,
    compose,
    fill,
    find_seams,
    limit_over_slices,
    normalise,
    window_on,
)
from nsgeo.velocity import VelocityModel
from nsgeo_qgis import slices_engine
from nsgeo_qgis.site_engine import SiteEngine
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import (
    MAX_FRAME_CELLS,
    NO_TRANSFORM,
    Resolution,
    SiteSource,
    SourceChoice,
    format_bytes,
    limit_windows,
    radius_cells_for,
)
from plugin_testing import LoadCounter, spin_until
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
)

#: M11's test resolution, with the z range widened to hold the whole site.
RES = Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=60.0)
TICK = {"radius_spacings": 1.5, "method": "none", "manual": {}}


@pytest.fixture
def make_site():
    """SiteEngines for one test, disposed (after any preparation ends) on teardown."""
    made: list[SiteEngine] = []

    def make(session, **kwargs) -> SiteEngine:
        engine = SiteEngine(session, **kwargs)
        made.append(engine)
        return engine

    yield make
    for engine in made:
        engine.wait_until_idle(20_000)
        engine.dispose()


def prepared(make_site, site3, source=None, resolution=RES, **kwargs):
    """A SiteEngine with every grid of `source` prepared and `resolution` set."""
    errors: list[str] = []
    site = make_site(site3.session, on_error=errors.append, **kwargs)
    site.set_source(source if source is not None else site3.source())
    assert site.wait_until_idle(60_000), "the site did not finish preparing"
    site.set_resolution(resolution)
    return site, errors


def grid_pixels(site: SiteEngine, grid_id: str) -> np.ndarray:
    """Lattice pixels whose centre falls inside a same-CRS grid's frame."""
    lattice = site.lattice
    frame = site.engine_for(grid_id).frame
    ids = frame.cell_index(lattice.pixel_centres())
    return (ids >= 0).reshape(lattice.height, lattice.width)


def expected_shown(site, session, top_ns, thickness_ns, *, radius_spacings, method, manual):
    """Each present grid's slice as spec 4.6 says it is shown, from public parts.

    Binned and unfilled for the statistics, then `a * fill(v) + b`.
    """
    binned = {}
    for g in site.ready_grids:
        engine = site.engine_for(g)
        window = window_on(engine.z, top_ns, thickness_ns) if engine.z is not None else None
        if window is not None:
            binned[g] = engine.slice_at(window)
    seams = ()
    if method == "edge":
        seams = find_seams(
            {g: site.engine_for(g).frame for g in binned},
            {g: cov for g, (_, cov) in binned.items()},
            {g: session.grid(g).default_spacing for g in binned},
        )
    factors = normalise(method, binned, seams, manual)
    shown = {}
    for g, (values, cov) in binned.items():
        a, b = factors[g]
        cell = site.engine_for(g).frame.cell
        radius = radius_cells_for(session.grid(g).default_spacing, radius_spacings, cell)
        shown[g] = a * fill(values, cov, radius) + b
    return shown, factors


def current_seams(site, session):
    frames = {g: site.engine_for(g).frame for g in site.ready_grids}
    coverages = {g: site.engine_for(g).slice_at(SliceWindow(0, 1))[1] for g in frames}
    spacings = {g: session.grid(g).default_spacing for g in frames}
    return [(s.a, s.b) for s in find_seams(frames, coverages, spacings)]


# ---- preparation: one at a time (trap 1) -----------------------------------


def test_two_engines_never_prepare_at_once(site3, make_site, monkeypatch):
    """Trap 1, and the most important test in M12: two line preparations
    at once segfaulted M11. The site's own engines must never overlap each
    other, nor the dock's This grid engine passed as `exclusive_with`
    (Ruling 1) -- here started at the same moment as the site -- and
    leaving site scope mid-way (`cancel()`) then coming back must not
    overlap the preparation it cancelled either."""
    counter = LoadCounter(monkeypatch, delay=0.05)
    session = site3.session
    peer = SliceEngine(session)  # the dock's This grid engine, as Task 5 passes it
    try:
        errors: list[str] = []
        site = make_site(session, on_error=errors.append, exclusive_with=[peer])
        peer.set_source(site3.choice("A"))
        site.set_source(site3.source())  # the same moment
        assert site.wait_until_idle(60_000)
        assert peer.wait_for_preparation(20_000)
        assert counter.calls == 16
        assert [site.grid_state(g) for g in "ABC"] == ["ready"] * 3

        # Later: re-prepare every grid under another transform, leave site
        # scope mid-way, and come back.
        site.set_source(site3.source(transform="amp_abs"))
        assert spin_until(lambda: site.grid_state("B") == "preparing")
        site.cancel()
        assert not site.is_running
        assert site.grid_state("A") == "ready"
        site.set_source(site3.source(transform="amp_abs"))
        assert site.wait_until_idle(60_000)

        assert counter.max_concurrent == 1, (
            f"two preparations ran at once (max_concurrent={counter.max_concurrent})"
        )
        assert [site.grid_state(g) for g in "ABC"] == ["ready"] * 3
        assert all(site.engine_for(g).choice.transform == "amp_abs" for g in "ABC")
        assert errors == [], errors
    finally:
        peer.dispose()


def test_a_preparation_that_outlives_its_cancel_wait_holds_back_every_other(
    site3, make_site, monkeypatch
):
    """`cancel_preparation` waits a bounded time and then gives up, leaving
    the task running and `is_running` True. That is the one moment the
    site's own engines can be busy with nothing dispatched, so the
    dispatcher must check them -- not merely remember which grid it last
    started -- or the next grid (here the same one, re-asked) starts on
    top of the task still reading. The wait is shortened to 1 ms so the
    give-up branch is taken deterministically."""
    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 1)
    counter = LoadCounter(monkeypatch, delay=0.15)
    errors: list[str] = []
    site = make_site(site3.session, on_error=errors.append)
    site.set_source(site3.source())
    assert spin_until(lambda: counter.calls >= 1), "A's first line was never read"
    site.cancel()
    assert any("did not stop in time" in msg for msg in errors), errors
    assert site.is_running, "A's cancelled task is still reading a line"
    assert site.has_live_task and site.engine_for("A").has_live_task

    site.set_source(site3.source())
    assert site.wait_until_idle(60_000)
    assert counter.max_concurrent == 1, (
        f"a grid started while a cancelled task still ran (max={counter.max_concurrent})"
    )
    assert site.ready_grids == ("A", "B", "C")
    assert not site.has_live_task


def test_a_dropped_grid_whose_preparation_outlives_its_cancel_wait_holds_back_every_other(
    site3, make_site, monkeypatch
):
    """Ruling T3-b. Dropping a grid while it prepares cancels its engine;
    when that bounded wait gives up, the engine's task is still reading a
    line. Disposing the engine at once would run M11's `clear()`, which
    reports it not running, and forget it -- the next grid would then start
    beside the old task. It must stay where the dispatcher can see it (a
    retiring engine) until its task has really ended."""
    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 1)
    counter = LoadCounter(monkeypatch, delay=0.15)
    errors: list[str] = []
    site = make_site(site3.session, on_error=errors.append)
    site.set_source(site3.source())
    assert spin_until(lambda: counter.calls >= 1), "A's first line was never read"

    site.set_source(site3.source("BC"))  # A dropped mid-preparation
    assert site.engine_for("A") is None
    assert site.has_live_task, "A's abandoned task is still reading a line"
    assert site.wait_until_idle(60_000)

    assert counter.max_concurrent == 1, (
        f"a grid started beside a dropped grid's task (max={counter.max_concurrent})"
    )
    assert site.ready_grids == ("B", "C")
    assert [site.grid_state(g) for g in "BC"] == ["ready", "ready"]
    assert not site.has_live_task


def test_a_retry_inside_a_dropped_grids_cancel_wait_does_not_re_dispatch_it(
    site3, make_site, monkeypatch
):
    """Final review D1. Dropping a grid whose task is still live waits for
    that task inside `cancel_preparation`, a nested event loop, and the
    retry timer can fire in there. Were the dropped grid still queued, a
    retry after its task ended would find nothing live and dispatch it
    again -- on an engine about to be released, whose `_preparing` would
    then never clear, stalling every grid behind it. The retry is made to
    fire at exactly that moment: the grid must already be off the queue."""
    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 1)
    counter = LoadCounter(monkeypatch, delay=0.15)
    site = make_site(site3.session)
    site.set_source(site3.source())
    assert spin_until(lambda: counter.calls >= 1), "A's first line was never read"
    site.cancel()  # the 1 ms wait gives up: A's task still reads a line
    engine_a = site.engine_for("A")
    assert engine_a.has_live_task
    site.set_source(site3.source())  # resumed: A heads the queue, held back by its task
    assert site.grid_state("A") == "queued"

    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 5_000)
    real_cancel = engine_a.cancel_preparation

    def cancel_then_retry() -> None:
        real_cancel()  # A's task ends inside this wait ...
        site._dispatch_next()  # ... and the retry timer fires inside it too

    monkeypatch.setattr(engine_a, "cancel_preparation", cancel_then_retry)
    site.set_source(site3.source("BC"))  # A dropped
    assert site.wait_until_idle(10_000), "the queue stalled behind the dropped grid"
    assert site.ready_grids == ("B", "C")
    assert site.engine_for("A") is None and not site.has_live_task
    assert counter.max_concurrent == 1


def test_a_moved_grid_whose_preparation_outlives_its_cancel_wait_is_held_back(
    site3, make_site, monkeypatch
):
    """Ruling T3-b, R-P2's path. A move clears the grid's engine (M11's
    `clear()`, which reports it not running even when its wait gave up)
    and hands the grid back to the queue at once. The dispatcher must see
    the abandoned task (`has_live_task`) and wait for it, or the grid is
    re-prepared beside its own old task."""
    monkeypatch.setattr(slices_engine, "_CANCEL_TIMEOUT_MS", 1)
    counter = LoadCounter(monkeypatch, delay=0.15)
    session = site3.session
    site = make_site(session)
    site.set_resolution(RES)
    site.set_source(site3.source())
    assert spin_until(lambda: counter.calls >= 1), "A's first line was never read"

    session.replace_grid(dataclasses.replace(session.grid("A"), origin=(500.0, 690.0)))
    assert site.wait_until_idle(60_000)

    assert counter.max_concurrent == 1, (
        f"the moved grid re-prepared beside its own old task (max={counter.max_concurrent})"
    )
    assert site.ready_grids == ("A", "B", "C")
    assert site.engine_for("A").frame.origin == (500.0, 690.0)


def test_a_moved_grid_re_prepares_through_the_queue_never_alongside_another(
    site3, make_site, monkeypatch
):
    """R-P2. M11's engine re-prepares itself when its grid moves -- a
    dispatch outside the site's queue. Moving A while C prepares must
    queue A behind C, and A must end ready at its new registration."""
    counter = LoadCounter(monkeypatch, delay=0.05)
    session = site3.session
    errors: list[str] = []
    site = make_site(session, on_error=errors.append)
    site.set_resolution(RES)
    site.set_source(site3.source())
    assert spin_until(lambda: site.grid_state("C") == "preparing")
    assert site.grid_state("A") == "ready"

    session.replace_grid(dataclasses.replace(session.grid("A"), origin=(500.0, 690.0)))
    assert site.wait_until_idle(60_000)

    assert counter.max_concurrent == 1, (
        f"the moved grid re-prepared beside another (max_concurrent={counter.max_concurrent})"
    )
    assert site.grid_state("A") == "ready"
    assert site.engine_for("A").frame.origin == (500.0, 690.0)
    assert counter.calls == 16
    assert errors == [], errors


def test_a_grid_moved_while_it_prepares_is_re_queued_not_failed(site3, make_site, monkeypatch):
    """The moved grid's own preparation is cancelled inside its engine's
    `clear()`, and that callback arrives before `on_grid_moved`. It must
    not read as a failure -- the grid goes back to the queue and ends
    ready at its new place."""
    counter = LoadCounter(monkeypatch, delay=0.05)
    session = site3.session
    states: list[str] = []
    errors: list[str] = []
    site = make_site(session, on_error=errors.append)
    site.set_resolution(RES)
    site.set_source(site3.source())
    site.on_changed = lambda: states.append(site.grid_state("A"))
    assert spin_until(lambda: counter.calls >= 2), "A's preparation never got going"
    assert site.grid_state("A") == "preparing"

    session.replace_grid(dataclasses.replace(session.grid("A"), origin=(500.0, 690.0)))
    assert site.wait_until_idle(60_000)

    assert not any(s.startswith("failed") for s in states), states
    assert site.grid_state("A") == "ready"
    assert site.engine_for("A").frame.origin == (500.0, 690.0)
    assert counter.max_concurrent == 1
    assert errors == [], errors


def test_closing_the_site_mid_preparation_clears_without_overlap(site3, make_site, monkeypatch):
    """`site_closed` mid-preparation, then the next site's preparation.

    Ruling T3-e: the close is prompt and silent -- the closed site's task
    ends its own confirm wait instead of leaving it to time out and report
    "did not stop in time"."""
    counter = LoadCounter(monkeypatch, delay=0.05)
    session = site3.session
    errors: list[str] = []
    site = make_site(session, on_error=errors.append)
    site.set_resolution(RES)
    site.set_source(site3.source())
    assert spin_until(lambda: site.grid_state("B") == "preparing")

    started = time.perf_counter()
    session.close_site()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert errors == [], errors
    assert elapsed_ms < slices_engine._CANCEL_TIMEOUT_MS, f"close took {elapsed_ms:.0f} ms"
    assert not site.is_running and not site.has_live_task
    assert site.ready_grids == ()
    assert site.lattice is None
    assert site.engine_for("A") is None

    session.open_site(site3.json_path)
    site.set_resolution(RES)
    site.set_source(site3.source())
    assert site.wait_until_idle(60_000)
    assert counter.max_concurrent == 1
    assert site.ready_grids == ("A", "B", "C")


def test_grids_prepare_in_order_and_each_is_drawn_as_soon_as_ready(site3, make_site):
    seen: list[tuple[str, ...]] = []
    first: dict[str, object] = {}

    def on_changed() -> None:
        seen.append(site.ready_grids)
        if site.ready_grids and "slice" not in first:
            first["slice"] = site.slice_at(20.0, 5.0, **TICK)

    site = make_site(site3.session, on_changed=on_changed)
    site.set_resolution(RES)
    seen.clear()
    site.set_source(site3.source())
    assert site.wait_until_idle(60_000)

    # (`on_changed` also fires as grids are queued and start: ready is still ().)
    assert list(dict.fromkeys(r for r in seen if r)) == [("A",), ("A", "B"), ("A", "B", "C")]
    drawn = first["slice"]
    assert set(drawn.windows) == {"A"}
    assert (drawn.lattice.x0, drawn.lattice.width, drawn.lattice.height) == (500.0, 24, 24)
    assert np.isfinite(drawn.array).any()


def test_changing_one_grids_preset_re_prepares_only_that_grid(site3, make_site, monkeypatch):
    counter = LoadCounter(monkeypatch)
    site, errors = prepared(make_site, site3)
    assert counter.calls == 12
    a_line = site.engine_for("A").prepared_lines()[0]

    site.set_source(
        SiteSource(
            transform="amp_envelope",
            grids=(site3.choice("A"), site3.choice("B", preset="raw"), site3.choice("C")),
        )
    )
    assert site.wait_until_idle(60_000)
    assert counter.calls == 16, f"{counter.calls - 12} lines read again, not B's four"
    assert site.engine_for("A").prepared_lines()[0] is a_line
    assert site.engine_for("B").choice.preset == "raw"
    assert site.ready_grids == ("A", "B", "C")
    assert errors == [], errors


def test_dropping_a_grid_from_the_source_releases_it_and_keeps_the_rest(
    site3, make_site, monkeypatch
):
    counter = LoadCounter(monkeypatch)
    site, _ = prepared(make_site, site3)
    site.set_source(site3.source("AB"))
    assert site.wait_until_idle(60_000)
    assert counter.calls == 12
    assert site.ready_grids == ("A", "B")
    assert site.engine_for("C") is None
    assert site.lattice.width == 48


def test_each_grid_reports_its_progress_while_it_prepares(site3, make_site, monkeypatch):
    """Spec 4.2, ruling T3-d: the grid list shows "preparing n of m".
    `on_changed` fires when a grid starts and on each line it finishes."""
    LoadCounter(monkeypatch, delay=0.02)
    seen: list[tuple[str, tuple[int, int] | None]] = []
    site = make_site(site3.session)
    site.on_changed = lambda: seen.append((site.grid_state("B"), site.grid_progress("B")))
    site.set_source(site3.source())
    assert site.grid_progress("A") == (0, 4)
    assert site.grid_progress("B") is None  # queued
    assert site.wait_until_idle(60_000)

    preparing = [progress for state, progress in seen if state == "preparing"]
    assert preparing and preparing[0] == (0, 4), seen
    assert any(done >= 1 for done, _ in preparing), f"no progress step reported: {seen}"
    assert all(total == 4 and 0 <= done <= 4 for done, total in preparing), seen
    assert [done for done, _ in preparing] == sorted(done for done, _ in preparing)
    assert seen[-1] == ("ready", None)
    assert all(site.grid_progress(g) is None for g in "ABC")


def test_dropping_a_grid_or_emptying_its_lines_is_announced_even_before_it_is_ready(
    site3, make_site, monkeypatch
):
    """Ruling T3-f: the dock's grid list must hear about a drop, or a grid
    becoming "no lines", whether or not the grid was ready yet."""
    LoadCounter(monkeypatch, delay=0.05)
    changes: list[dict[str, str]] = []
    site = make_site(site3.session)
    site.on_changed = lambda: changes.append(
        {g: site.grid_state(g) for g in "ABC" if g in site._states}
    )
    site.set_source(site3.source())
    assert site.grid_state("C") == "queued"

    changes.clear()
    no_lines = SourceChoice(grid_id="B", preset="p", transform="amp_envelope", line_keys=())
    site.set_source(SiteSource(transform="amp_envelope", grids=(site3.choice("A"), no_lines)))
    assert changes, "dropping queued C and emptying queued B announced nothing"
    assert changes[-1].get("B") == "no lines" and "C" not in changes[-1]
    assert site.wait_until_idle(60_000)
    assert site.ready_grids == ("A",)


def test_a_grid_with_no_lines_is_listed_and_skipped(site3, make_site, monkeypatch):
    counter = LoadCounter(monkeypatch)
    no_lines = SourceChoice(grid_id="C", preset="p", transform="amp_envelope", line_keys=())
    site = make_site(site3.session)
    site.set_source(
        SiteSource(transform="amp_envelope", grids=(site3.choice("A"), site3.choice("B"), no_lines))
    )
    assert site.grid_state("C") == "no lines"
    assert site.wait_until_idle(60_000)
    assert counter.calls == 8
    assert site.grid_state("C") == "no lines"
    assert site.ready_grids == ("A", "B")
    assert site.engine_for("C") is None

    site.set_resolution(RES)
    drawn = site.slice_at(20.0, 5.0, **TICK)
    assert set(drawn.windows) == {"A", "B"}
    assert (drawn.lattice.x0, drawn.lattice.width) == (500.0, 48)


def test_a_grid_that_cannot_be_prepared_is_failed_and_the_rest_continue(site3, make_site):
    session = site3.session
    session.site.presets["bad"] = [{"step": "amp_abs", "params": {}, "enabled": True}]
    errors: list[str] = []
    site = make_site(session, on_error=errors.append)
    site.set_source(
        SiteSource(
            transform="amp_envelope",
            grids=(site3.choice("A"), site3.choice("B", preset="bad"), site3.choice("C")),
        )
    )
    assert site.wait_until_idle(60_000)
    assert site.grid_state("B").startswith("failed: ")
    assert "amp_abs" in site.grid_state("B")
    assert site.ready_grids == ("A", "C")
    assert any(msg.startswith("B: ") for msg in errors), errors


# ---- one tick --------------------------------------------------------------


def test_a_grid_outside_the_window_is_nodata_and_named(site3_factory, make_site):
    site3 = site3_factory(samples={"C": 128})  # C's lines end near 16.4 ns
    site, errors = prepared(make_site, site3)
    assert (site.site_z.t0_ns, site.site_z.t_end_ns) == (2.0, 60.0)
    assert site.engine_for("C").z.t_end_ns < 17.0

    deep = site.slice_at(30.0, 2.0, **TICK)
    assert deep.windows["C"] is None
    assert deep.windows["A"] is not None and deep.windows["B"] is not None
    c = grid_pixels(site, "C")
    assert c.any() and np.isnan(deep.array[c]).all()
    assert np.isfinite(deep.array[grid_pixels(site, "A")]).any()

    shallow = site.slice_at(5.0, 2.0, **TICK)
    assert shallow.windows["C"] is not None
    assert np.isfinite(shallow.array[c]).any()
    assert errors == [], errors


def test_a_grid_overlapping_the_site_by_one_level_is_absent_not_an_error(site3_factory, make_site):
    """R-P3: `Resolution` needs t1 > t0, so a one-level grid axis would
    raise if handed to the engine. Such a grid has no resolution and is
    absent at every window."""
    site3 = site3_factory(samples={"C": 128})  # C ends at ~16.4 ns
    one_level = Resolution(cell=0.25, dz_ns=0.5, t0_ns=16.0, t1_ns=60.0)
    site, errors = prepared(make_site, site3, resolution=one_level)
    assert site.engine_for("C").z is None
    drawn = site.slice_at(16.0, 1.0, **TICK)
    assert drawn.windows["C"] is None
    assert drawn.windows["A"] is not None
    assert errors == [], errors


def test_background_normalisation_evens_out_a_grid_recorded_at_double_gain(
    site3_factory, make_site
):
    site3 = site3_factory(scale={"B": 2.0}, same_data=True)
    site, _ = prepared(make_site, site3, source=site3.source(preset="raw"))
    a, b = grid_pixels(site, "A"), grid_pixels(site, "B")

    plain = site.slice_at(20.0, 5.0, radius_spacings=1.5, method="none", manual={})
    evened = site.slice_at(20.0, 5.0, radius_spacings=1.5, method="background", manual={})

    plain_ratio = np.nanmean(plain.array[b]) / np.nanmean(plain.array[a])
    evened_ratio = np.nanmean(evened.array[b]) / np.nanmean(evened.array[a])
    assert plain_ratio == pytest.approx(2.0, rel=0.05)
    assert evened_ratio == pytest.approx(1.0, rel=0.05)


def test_the_manual_gain_multiplies_only_that_grids_pixels(site3, make_site):
    site, _ = prepared(make_site, site3)
    a, b, c = (grid_pixels(site, g) for g in "ABC")
    for method in ("none", "background"):
        plain = site.slice_at(20.0, 5.0, radius_spacings=1.5, method=method, manual={})
        gained = site.slice_at(20.0, 5.0, radius_spacings=1.5, method=method, manual={"B": 2.5})
        np.testing.assert_allclose(gained.array[b], 2.5 * plain.array[b], rtol=1e-5)
        np.testing.assert_array_equal(gained.array[a], plain.array[a])
        np.testing.assert_array_equal(gained.array[c], plain.array[c])
        assert gained.factors["B"][0] == pytest.approx(2.5 * plain.factors["B"][0])
        assert gained.factors["A"] == plain.factors["A"]


def test_normalising_a_signed_site_gives_finite_factors(site3, make_site):
    site, _ = prepared(make_site, site3, source=site3.source(transform=NO_TRANSFORM))
    for method in NORMALISATION_METHODS:
        drawn = site.slice_at(20.0, 5.0, radius_spacings=1.5, method=method, manual={})
        assert set(drawn.factors) == {"A", "B", "C"}
        for gain, shift in drawn.factors.values():
            assert np.isfinite(gain) and np.isfinite(shift) and gain > 0.0, (method, drawn.factors)
        finite = drawn.array[np.isfinite(drawn.array)]
        assert finite.size > 0 and (finite < 0.0).any(), method  # still signed


def test_histogram_factors_apply_to_the_filled_slice_as_a_gain_and_a_shift(site3, make_site):
    """Spec 4.6: measured on binned cells, applied to the displayed
    (filled) slice. Histogram match is the one method with a shift, so it
    pins the composition `a * fill(v) + b` exactly, manual gain included."""
    session = site3.session
    site, _ = prepared(make_site, site3)
    manual = {"C": 1.5}
    drawn = site.slice_at(20.0, 5.0, radius_spacings=1.5, method="histogram", manual=manual)
    shown, factors = expected_shown(
        site, session, 20.0, 5.0, radius_spacings=1.5, method="histogram", manual=manual
    )
    assert any(abs(shift) > 1e-3 for _, shift in factors.values()), factors
    for g in "ABC":
        assert drawn.factors[g] == pytest.approx(factors[g])
    lattice = drawn.lattice
    layers = [
        (site.engine_for(g).frame.cell_index(lattice.pixel_centres()), shown[g]) for g in shown
    ]
    np.testing.assert_allclose(drawn.array, compose(lattice, layers), rtol=1e-6, atol=1e-7)


def test_coverage_mode_shows_the_counts_without_normalising(site3, make_site):
    """Ruling 7: coverage is composed like values; nothing is normalised."""
    site, _ = prepared(make_site, site3)
    drawn = site.slice_at(
        20.0, 5.0, radius_spacings=1.5, method="background", manual={"B": 3.0}, coverage=True
    )
    a = grid_pixels(site, "A")
    _, coverage = site.engine_for("A").slice_at(drawn.windows["A"])
    counts = drawn.array[a]
    assert np.nanmin(counts) >= 1.0  # zero is NaN
    assert set(np.unique(counts[np.isfinite(counts)])) <= set(np.unique(coverage[coverage > 0]))
    assert all(f == (1.0, 0.0) for f in drawn.factors.values())


def test_the_shared_limit_follows_normalisation(site3_factory, make_site):
    """Spec 4.5: the site's shared stretch is measured over every grid's
    filled windows after normalisation and manual adjustment, so turning
    normalisation on cannot leave the stretch fitted to the uncorrected
    data. Thickness 2 ns gives 30 windows here, so Ruling 4's cap of 12
    is what is measured over."""
    site3 = site3_factory(scale={"B": 2.0}, same_data=True)
    session = site3.session
    site, _ = prepared(make_site, site3, source=site3.source(preset="raw"))
    clip = UnipolarClip()
    plain = site.shared_limit(2.0, clip, radius_spacings=1.5, method="none", manual={})
    evened = site.shared_limit(2.0, clip, radius_spacings=1.5, method="background", manual={})

    z = site.site_z
    windows = limit_windows(z, round(2.0 / z.dz_ns))
    assert len(windows) == 12
    slices = []
    for w in windows:
        shown, _ = expected_shown(
            site,
            session,
            z.t0_ns + w.k0 * z.dz_ns,
            w.n_levels * z.dz_ns,
            radius_spacings=1.5,
            method="background",
            manual={},
        )
        slices.extend(shown.values())
    assert evened == pytest.approx(limit_over_slices(slices, clip), rel=1e-6)
    assert abs(evened - plain) > 0.05 * plain

    gained = site.shared_limit(2.0, clip, radius_spacings=1.5, method="none", manual={"A": 3.0})
    assert gained > plain


def test_a_grid_in_another_crs_lands_where_its_coordinates_say(site3_factory, make_site):
    """Spec 4.7: for a grid in another CRS the lattice's pixel centres are
    transformed into that grid's CRS before `cell_index`. B is declared in
    EPSG:32615 (the next UTM zone) at the same place on the ground, so its
    own coordinates are some 160 km of easting away from the site's.

    The brief named EPSG:26916; measured here, QGIS's 26916 -> 32616
    operation is a null datum shift (1.6e-8 m at these coordinates,
    1e-4 m at realistic ones), so a gather that skipped the transform would
    pass. A zone change cannot be skipped."""
    site3 = site3_factory(crs={"B": "EPSG:32615"})
    site, errors = prepared(make_site, site3)
    drawn = site.slice_at(20.0, 5.0, radius_spacings=0.0, method="none", manual={})
    lattice = drawn.lattice
    frame_b = site.engine_for("B").frame
    assert frame_b.crs == "EPSG:32615" and lattice.crs == "EPSG:32616"

    values, coverage = site.engine_for("B").slice_at(drawn.windows["B"])
    shown_b = fill(values, coverage, 0)
    to_b = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:32616"),
        QgsCoordinateReferenceSystem("EPSG:32615"),
        QgsProject.instance(),
    )
    centres = lattice.pixel_centres()
    in_b = np.array(
        [(p.x(), p.y()) for p in (to_b.transform(QgsPointXY(x, y)) for x, y in centres)]
    )
    ids_b = frame_b.cell_index(in_b)
    only_b = ids_b >= 0
    for g in "AC":
        only_b &= site.engine_for(g).frame.cell_index(centres) < 0
    expected = shown_b.ravel()[ids_b[only_b]]
    assert np.isfinite(expected).sum() > 50
    np.testing.assert_array_equal(drawn.array.ravel()[only_b], expected)
    # And on the ground: between A and C, in the site's own coordinates.
    xs = centres[only_b & np.isfinite(drawn.array.ravel()), 0]
    assert xs.min() >= 506.0 and xs.max() <= 512.1
    assert errors == [], errors


def test_a_rotated_site_composes_exactly_as_whole_lattice_gathers_would(site3, make_site):
    """Final review I1: each grid's gather is kept to its own window on the
    lattice, and composed there only. B laid at 30 degrees halves the pitch
    (Ruling 2) and overlaps C at a corner, which must still average. The
    tick is bit-identical to `compose` over whole-lattice gathers."""
    session = site3.session
    session.replace_grid(dataclasses.replace(session.grid("B"), azimuth=30.0))
    site, errors = prepared(make_site, site3)
    lattice = site.lattice
    assert lattice.pixel == RES.cell / 2
    drawn = site.slice_at(20.0, 5.0, **TICK)
    shown, _ = expected_shown(site, session, 20.0, 5.0, **TICK)
    centres = lattice.pixel_centres()
    gathers = {g: site.engine_for(g).frame.cell_index(centres) for g in shown}
    assert ((gathers["B"] >= 0) & (gathers["C"] >= 0)).sum() > 50, "B and C must overlap"
    expected = compose(lattice, [(gathers[g], shown[g]) for g in shown])
    assert np.array_equal(drawn.array, expected, equal_nan=True)
    assert errors == [], errors


def test_grids_too_far_apart_for_the_lattice_are_refused_by_pixel_count(site3, make_site):
    """Spec 4.7: M11's cell cap applies to the lattice, which spans the
    grids' bounding box -- mostly empty for grids far apart."""
    session = site3.session
    session.replace_grid(dataclasses.replace(session.grid("C"), origin=(5000.0, 5000.0)))
    errors: list[str] = []
    site = make_site(session, on_error=errors.append)
    site.set_source(site3.source())
    assert site.wait_until_idle(60_000)
    extents = [(500.0, 700.0, 506.0, 706.0), (506.0, 700.0, 512.0, 706.0)]
    extents.append((5000.0, 5000.0, 5006.0, 5006.0))
    n_pixels = SiteLattice.covering(extents, RES.cell, "EPSG:32616").n_pixels
    assert n_pixels > MAX_FRAME_CELLS
    with pytest.raises(ValueError, match="pixels") as refused:
        site.set_resolution(RES)
    assert f"{n_pixels:,}" in str(refused.value)
    assert site.lattice is None


def test_a_refusal_with_a_rotated_grid_names_the_half_cell_pitch(site3, make_site):
    """Final review M5: a rotated grid puts the site on a half-cell pitch
    (Ruling 2) -- four times the pixels, and often the actual reason the
    lattice is refused -- so the message says so, and only then."""
    session = site3.session
    session.replace_grid(dataclasses.replace(session.grid("C"), origin=(5000.0, 5000.0)))
    site = make_site(session)
    site.set_source(site3.source())
    assert site.wait_until_idle(60_000)
    with pytest.raises(ValueError, match="pixels") as north_up:
        site.set_resolution(RES)
    assert "half-cell" not in str(north_up.value)

    session.replace_grid(dataclasses.replace(session.grid("C"), azimuth=30.0))
    assert site.wait_until_idle(60_000)
    with pytest.raises(ValueError, match="pixels") as rotated:
        site.set_resolution(RES)
    text = str(rotated.value)
    assert "at 0.125 m" in text
    assert "rotated grid puts the site on a half-cell pitch (0.125 m for a 0.25 m cell)" in text
    assert text.endswith("Choose a coarser cell or include fewer grids")


@pytest.mark.parametrize(
    ("azimuth", "pitch"),
    [(1e-6, 1.0), (90.0 + 1e-6, 1.0), (2.0, 0.5), (0.01, 1.0), (0.02, 0.5)],
)
def test_a_grid_a_hair_off_north_keeps_the_full_cell_pitch(site3, make_site, azimuth, pitch):
    """Final review D3 (Ruling F-5): a frame counts as axis-aligned when its
    deviation moves its far corner under 1% of a cell. B is 6 x 6 m, so its
    far corner is 8.49 m out: 0.01 degrees moves it 1.5 mm (under 2.5 mm,
    1% of 0.25 m) and 0.02 degrees 3.0 mm (over). Measured along one side
    (6 m) instead, 0.02 degrees would be 2.1 mm and wrongly snap."""
    session = site3.session
    session.replace_grid(dataclasses.replace(session.grid("B"), azimuth=azimuth))
    site, errors = prepared(make_site, site3)
    assert site.lattice.pixel == RES.cell * pitch
    assert errors == [], errors


def test_moving_a_grid_rebuilds_the_lattice_and_seams(site3, make_site):
    session = site3.session
    site, errors = prepared(make_site, site3)
    assert current_seams(site, session) == [("A", "B"), ("B", "C")]
    before = site.slice_at(20.0, 5.0, radius_spacings=1.5, method="edge", manual={})
    assert before.lattice.x0 == 500.0

    session.replace_grid(dataclasses.replace(session.grid("A"), origin=(490.0, 700.0)))
    assert site.wait_until_idle(60_000)
    assert site.grid_state("A") == "ready"
    assert site.engine_for("A").frame.origin == (490.0, 700.0)

    after = site.slice_at(20.0, 5.0, radius_spacings=1.5, method="edge", manual={})
    assert (after.lattice.x0, after.lattice.width) == (490.0, 112)
    assert current_seams(site, session) == [("B", "C")]  # A no longer meets B
    _, factors = expected_shown(
        site, session, 20.0, 5.0, radius_spacings=1.5, method="edge", manual={}
    )
    for g in "ABC":
        assert after.factors[g] == pytest.approx(factors[g]), g
    assert errors == [], errors


def test_removing_a_grid_drops_it_from_the_site(site3, make_site):
    session = site3.session
    changes: list[tuple[str, ...]] = []
    site = make_site(session, on_changed=lambda: changes.append(site.ready_grids))
    site.set_source(site3.source())
    assert site.wait_until_idle(60_000)
    site.set_resolution(RES)
    changes.clear()

    for key in site3.keys("C"):
        session.remove_line(key)
    session.remove_grid("C")

    assert site.ready_grids == ("A", "B")
    assert site.engine_for("C") is None
    with pytest.raises(KeyError):
        site.grid_state("C")
    assert changes and changes[-1] == ("A", "B")
    assert site.lattice.width == 48
    assert set(site.slice_at(20.0, 5.0, **TICK).windows) == {"A", "B"}


def test_a_velocity_edit_does_not_re_prepare_or_change_the_slice(site3, make_site, monkeypatch):
    counter = LoadCounter(monkeypatch)
    site, errors = prepared(make_site, site3)
    before = site.slice_at(20.0, 5.0, **TICK)
    calls = counter.calls

    site3.session.set_grid_velocity("B", VelocityModel.constant(0.09))
    assert site.wait_until_idle(5_000)
    assert counter.calls == calls
    assert site.ready_grids == ("A", "B", "C")
    np.testing.assert_array_equal(site.slice_at(20.0, 5.0, **TICK).array, before.array)
    assert errors == [], errors


def test_a_velocity_edit_keeps_every_other_grids_cube_and_every_cache(
    site3, make_site, monkeypatch
):
    """Final review I2. `grids_changed` fires for any grid's edit and says
    not which. A velocity edit to B used to drop every resident cube in the
    site, every gather and the seams, so the next tick rebuilt them all on
    the UI thread. Only B's own cube goes now (Ruling Q: a cube freezes the
    velocity it was built under); the slice is unchanged."""
    counter = LoadCounter(monkeypatch)
    site, errors = prepared(make_site, site3)
    for g in "ABC":
        site.engine_for(g).set_always_resident(True)
    tick = {"radius_spacings": 1.5, "method": "edge", "manual": {}}
    before = site.slice_at(20.0, 5.0, **tick)
    assert all(site.engine_for(g).has_cube for g in "ABC")
    gathers = dict(site._gathers)
    seams = site._seams
    assert set(gathers) == {"A", "B", "C"} and seams
    calls = counter.calls

    site3.session.set_grid_velocity("B", VelocityModel.constant(0.09))
    assert site.wait_until_idle(5_000)
    assert counter.calls == calls, "a velocity edit re-prepared"
    assert site.engine_for("A").has_cube and site.engine_for("C").has_cube
    assert not site.engine_for("B").has_cube, "Ruling Q: B's cube froze B's old velocity"
    assert all(site._gathers.get(g) is gathers[g] for g in "ABC"), "a gather was dropped"
    assert site._seams is seams, "the seams were dropped"
    after = site.slice_at(20.0, 5.0, **tick)
    assert np.array_equal(after.array, before.array, equal_nan=True)
    assert site.engine_for("B").has_cube, "B's cube is built again on use"
    assert errors == [], errors


def test_a_spacing_edit_drops_the_seams_but_no_gather(site3, make_site):
    """Final review I2's other half: a spacing edit changes the seam width
    (Ruling 3), so the seams go; it moves no frame, so every gather stays."""
    session = site3.session
    site, _ = prepared(make_site, site3)
    site.slice_at(20.0, 5.0, radius_spacings=1.5, method="edge", manual={})
    gathers, seams = dict(site._gathers), site._seams
    session.replace_grid(dataclasses.replace(session.grid("C"), default_spacing=2.0))
    assert site.wait_until_idle(5_000)
    assert site._seams is None
    assert all(site._gathers.get(g) is gathers[g] for g in "ABC")
    site.slice_at(20.0, 5.0, radius_spacings=1.5, method="edge", manual={})
    assert site._seams is not seams and site._seams is not None


def test_the_status_line_counts_grids_lines_and_memory(site3, make_site):
    site, _ = prepared(make_site, site3)
    assert site.status_text().endswith("slices redraw in —")
    site.slice_at(20.0, 5.0, **TICK)
    text = site.status_text()
    held = sum(site.engine_for(g).estimate.lines_bytes for g in "ABC")
    assert all(site.engine_for(g).mode == "streaming" for g in "ABC")
    assert text.startswith(f"3 grids · 12 lines held in memory, {format_bytes(held)} · ")
    assert re.fullmatch(r".* · slices redraw in \d+ ms", text), text
