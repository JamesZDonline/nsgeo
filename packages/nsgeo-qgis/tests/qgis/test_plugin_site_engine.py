"""SiteEngine: one SliceEngine per grid, prepared one at a time, composed per tick."""

from __future__ import annotations

import dataclasses
import math
import re
import time

import numpy as np
import pytest
from nsgeo.render import PercentileClip, UnipolarClip
from nsgeo.slices import (
    NORMALISATION_METHODS,
    SiteLattice,
    SliceWindow,
    bilinear_taps,
    find_seams,
    limit_over_slices,
    normalise,
    sample,
    sample_counts,
    window_on,
)
from nsgeo.velocity import VelocityModel
from nsgeo_qgis import slices_engine
from nsgeo_qgis.site_engine import SiteEngine
from nsgeo_qgis.slices_engine import SliceEngine, solve_key
from nsgeo_qgis.slices_plan import (
    NO_TRANSFORM,
    Resolution,
    SiteSource,
    SliceFinish,
    SourceChoice,
    format_bytes,
    limit_windows,
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
#: What the 1.5-spacing disc fill stood for: IDW reaching 1.5 line spacings.
FINISH = SliceFinish(method="idw", max_distance_spacings=1.5)
#: Binned cells as they are, the old radius 0.
NONE = SliceFinish(method="none")
TICK = {"finish": FINISH, "method": "none", "manual": {}}
#: Minimum curvature at the same reach (interpolation spec §5.4).
MC = SliceFinish(method="min_curvature", max_distance_spacings=1.5)


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


def expected_shown(site, session, top_ns, thickness_ns, *, finish, method, manual, draw="finish"):
    """Each present grid's slice as spec 4.6 says it is shown, from public parts.

    Binned and unfinished for the statistics, then `a * finish(v) + b`, the
    finish being each grid's own engine's (interpolation spec §8). `draw`
    "preview" gives each grid's kriging preview instead (plan call 5).
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
        shown[g] = a * getattr(site.engine_for(g), draw)(values, cov, finish) + b
    return shown, factors


def composed(site, shown, *, counts=False):
    """`shown` composed on the site lattice: the mean over grids of each grid's
    own bilinear (or whole-count) samples at every pixel centre."""
    lattice = site.lattice
    take = sample_counts if counts else sample
    total = np.zeros(lattice.n_pixels)
    n = np.zeros(lattice.n_pixels)
    for g in shown:
        got = take(shown[g], bilinear_taps(site.engine_for(g).frame, lattice.pixel_centres()))
        ok = np.isfinite(got)
        total += np.where(ok, got, 0.0)
        n += ok
    out = np.full(lattice.n_pixels, np.nan)
    np.divide(total, n, out=out, where=n > 0)
    return out.reshape(lattice.height, lattice.width)


def slow(site, ms: float = 500.0) -> None:
    """Every ready grid's last solve said to take `ms`. Only once its plan
    exists (Ruling R1): building a plan resets the timing."""
    for g in site.ready_grids:
        site.engine_for(g)._last_solve_ms = ms


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
    assert "Absolute value" in site.grid_state("B")  # by title, as the Processing list shows it
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

    plain = site.slice_at(20.0, 5.0, finish=FINISH, method="none", manual={})
    evened = site.slice_at(20.0, 5.0, finish=FINISH, method="background", manual={})

    plain_ratio = np.nanmean(plain.array[b]) / np.nanmean(plain.array[a])
    evened_ratio = np.nanmean(evened.array[b]) / np.nanmean(evened.array[a])
    assert plain_ratio == pytest.approx(2.0, rel=0.05)
    assert evened_ratio == pytest.approx(1.0, rel=0.05)


def test_the_manual_gain_multiplies_only_that_grids_pixels(site3, make_site):
    site, _ = prepared(make_site, site3)
    a, b, c = (grid_pixels(site, g) for g in "ABC")
    for method in ("none", "background"):
        plain = site.slice_at(20.0, 5.0, finish=FINISH, method=method, manual={})
        gained = site.slice_at(20.0, 5.0, finish=FINISH, method=method, manual={"B": 2.5})
        np.testing.assert_allclose(gained.array[b], 2.5 * plain.array[b], rtol=1e-5)
        np.testing.assert_array_equal(gained.array[a], plain.array[a])
        np.testing.assert_array_equal(gained.array[c], plain.array[c])
        assert gained.factors["B"][0] == pytest.approx(2.5 * plain.factors["B"][0])
        assert gained.factors["A"] == plain.factors["A"]


def test_normalising_a_signed_site_gives_finite_factors(site3, make_site):
    site, _ = prepared(make_site, site3, source=site3.source(transform=NO_TRANSFORM))
    for method in NORMALISATION_METHODS:
        drawn = site.slice_at(20.0, 5.0, finish=FINISH, method=method, manual={})
        assert set(drawn.factors) == {"A", "B", "C"}
        for gain, shift in drawn.factors.values():
            assert np.isfinite(gain) and np.isfinite(shift) and gain > 0.0, (method, drawn.factors)
        finite = drawn.array[np.isfinite(drawn.array)]
        assert finite.size > 0 and (finite < 0.0).any(), method  # still signed


def test_histogram_factors_apply_to_the_filled_slice_as_a_gain_and_a_shift(site3, make_site):
    """Spec 4.6: measured on binned cells, applied to the displayed
    (filled) slice. Histogram match is the one method with a shift, so it
    pins the composition `a * finish(v) + b` exactly, manual gain included."""
    session = site3.session
    site, _ = prepared(make_site, site3)
    manual = {"C": 1.5}
    drawn = site.slice_at(20.0, 5.0, finish=FINISH, method="histogram", manual=manual)
    shown, factors = expected_shown(
        site, session, 20.0, 5.0, finish=FINISH, method="histogram", manual=manual
    )
    assert any(abs(shift) > 1e-3 for _, shift in factors.values()), factors
    for g in "ABC":
        assert drawn.factors[g] == pytest.approx(factors[g])
    np.testing.assert_allclose(drawn.array, composed(site, shown), rtol=1e-5, atol=1e-6)


def test_site_slices_are_each_grids_finished_slice_times_its_gain(site3, make_site):
    """Interpolation spec §8: what a grid shows on the site is its own
    engine's finished slice (interpolated, smoothed), times the grid's gain."""
    finish = SliceFinish(method="idw", max_distance_spacings=1.5, smooth_x_m=0.2)
    site, _ = prepared(make_site, site3)
    drawn = site.slice_at(20.0, 5.0, finish=finish, method="none", manual={"B": 2.0})
    engine = site.engine_for("B")
    values, coverage = engine.slice_at(drawn.windows["B"])
    finished = engine.finish(values, coverage, finish)
    assert drawn.factors["B"] == (2.0, 0.0)
    only_b = grid_pixels(site, "B")
    for g in "AC":
        only_b &= ~grid_pixels(site, g)
    ids = engine.frame.cell_index(drawn.lattice.pixel_centres())[only_b.ravel()]
    expected = 2.0 * finished.ravel()[ids]
    assert np.isfinite(expected).sum() > 50
    np.testing.assert_allclose(drawn.array.ravel()[only_b.ravel()], expected, equal_nan=True)
    # It is the finish that was applied, not the binned values.
    assert not np.array_equal(finished, values)


@pytest.mark.parametrize("method", ["none", "idw", "kriging", "min_curvature"])
def test_site_gains_commute_with_every_method(site3, make_site, method):
    """Interpolation is linear in the data and smoothing a normalised average,
    so a gain and shift measured on the binned cells may be applied after the
    finish (spec 4.6). This is what lets the site finish once per grid.
    Minimum curvature is linear too, but solved iteratively to a relative
    residual, so it agrees to the solve's tolerance of the data's size."""
    finish = SliceFinish(method=method, max_distance_spacings=1.5, smooth_y_m=0.15)
    site, _ = prepared(make_site, site3)
    a, b = 1.7, -0.3
    engine = site.engine_for("A")
    window = window_on(engine.z, 20.0, 5.0)
    values, coverage = engine.slice_at(window)
    after = a * engine.finish(values, coverage, finish) + b
    before = engine.finish(np.where(coverage > 0, a * values + b, values), coverage, finish)
    atol = 1e-4 * np.nanmax(np.abs(after)) if method == "min_curvature" else 1e-5
    np.testing.assert_allclose(after, before, rtol=1e-4, atol=atol, equal_nan=True)


def test_site_shared_limit_measures_finished_slices(site3, make_site):
    """The site's stretch is measured over the slices as drawn, finish
    included (interpolation spec §7), so the settings move it."""
    site, _ = prepared(make_site, site3)
    clip = UnipolarClip()
    smoothed = SliceFinish(method="idw", max_distance_spacings=1.5, smooth_x_m=1.0, smooth_y_m=1.0)
    plain = site.shared_limit(2.0, clip, finish=NONE, method="none", manual={})
    finished = site.shared_limit(2.0, clip, finish=smoothed, method="none", manual={})
    z = site.site_z
    slices = []
    for w in limit_windows(z, round(2.0 / z.dz_ns)):
        shown, _ = expected_shown(
            site,
            site3.session,
            z.t0_ns + w.k0 * z.dz_ns,
            w.n_levels * z.dz_ns,
            finish=smoothed,
            method="none",
            manual={},
        )
        slices.extend(shown.values())
    assert finished == pytest.approx(limit_over_slices(slices, clip), rel=1e-6)
    assert finished != pytest.approx(plain, rel=1e-3)


# ---- minimum curvature: preview, background solves, the stretch ------------
# Plan calls 5-7 (interpolation spec §7). Real solve timings never decide a
# result here: where "slow" matters, `_last_solve_ms` is set by hand, once the
# plans exist (Ruling R1).


def test_a_live_site_tick_previews_each_slow_grid_until_its_solve_lands(site3, make_site):
    """A live tick draws each grid whose solve is slow as its kriging preview,
    normalised and composed as the full result is, and says which.
    `pending_solves` hands out exactly those grids' solves, in `ready_grids`
    order; once they land the same tick is final and the full result."""
    session = site3.session
    site, _ = prepared(make_site, site3)
    tick = {"finish": MC, "method": "histogram", "manual": {"C": 1.5}}
    first = site.slice_at(20.0, 5.0, **tick, preview=True)  # no plan yet, so no solve timed
    assert first.provisional and set(first.previewed) == set(site.ready_grids)
    slow(site)
    drawn = site.slice_at(20.0, 5.0, **tick, preview=True)
    assert drawn.provisional and list(drawn.previewed) == list(site.ready_grids)
    previews, _ = expected_shown(site, session, 20.0, 5.0, **tick, draw="preview")
    np.testing.assert_allclose(drawn.array, composed(site, previews), rtol=1e-6, atol=1e-7)

    jobs = site.pending_solves(20.0, 5.0, MC)
    assert [job.engine for job in jobs] == [site.engine_for(g) for g in site.ready_grids]
    for g, job in zip(site.ready_grids, jobs, strict=True):
        values, _ = site.engine_for(g).slice_at(drawn.windows[g])
        assert job.key == solve_key(values) == drawn.previewed[g].key
    # With the tick that previewed them, the same solves, from its slices and keys.
    again = site.pending_solves(20.0, 5.0, MC, drawn=drawn)
    assert [(j.engine, j.key) for j in again] == [(j.engine, j.key) for j in jobs]
    for job in jobs:
        job.run(lambda: False)
        assert job.land()
    assert site.pending_solves(20.0, 5.0, MC) == []

    final = site.slice_at(20.0, 5.0, **tick, preview=True)
    assert not final.provisional and final.previewed == {}
    full, _ = expected_shown(site, session, 20.0, 5.0, **tick)
    np.testing.assert_allclose(final.array, composed(site, full), rtol=1e-6, atol=1e-7)
    assert not np.allclose(final.array, drawn.array, equal_nan=True)
    # Without `preview` a tick is the full result; another method never previews.
    assert not site.slice_at(30.0, 5.0, **tick).provisional
    assert not site.slice_at(35.0, 5.0, **{**tick, "finish": FINISH}, preview=True).provisional
    assert site.pending_solves(40.0, 5.0, FINISH) == []


@pytest.mark.parametrize(("ms", "previewed"), [(30.0, True), (10.0, False)])
def test_a_live_site_tick_is_slow_by_its_grids_solves_together(site3, make_site, ms, previewed):
    """Final review M-2: a tick solves every grid it does not preview on the
    GUI thread, one after another, so "slow" is the tick's (plan call 5).
    Three grids at 30 ms each make a 90 ms tick, over the 50 ms budget: each
    is previewed, though each alone is inside it. At 10 ms each (30 ms) every
    grid is solved at once."""
    site, _ = prepared(make_site, site3)
    tick = {"finish": MC, "method": "none", "manual": {}}
    site.slice_at(20.0, 5.0, **tick, preview=True)  # builds every plan
    slow(site, ms)
    drawn = site.slice_at(30.0, 5.0, **tick, preview=True)
    assert len(site.ready_grids) == 3
    if previewed:
        assert drawn.provisional and list(drawn.previewed) == list(site.ready_grids)
    else:
        assert not drawn.provisional and drawn.previewed == {}
        assert site.pending_solves(30.0, 5.0, MC) == []


def test_a_live_site_tick_counts_only_the_grids_it_must_solve(site3, make_site):
    """A grid whose slice is solved already costs a tick nothing, so only the
    others' last solves are added up: two at 30 ms (60 ms) are previewed, the
    solved one drawn in full; one alone at 30 ms is solved at once. A grid not
    timed yet makes the tick slow whatever the others cost."""
    site, _ = prepared(make_site, site3)
    tick = {"finish": MC, "method": "none", "manual": {}}
    site.slice_at(20.0, 5.0, **tick, preview=True)  # builds every plan
    first, second, third = site.ready_grids
    for job in site.pending_solves(30.0, 5.0, MC):
        if job.engine is site.engine_for(first):
            job.run(lambda: False)
            assert job.land()
    slow(site, 30.0)
    drawn = site.slice_at(30.0, 5.0, **tick, preview=True)
    assert list(drawn.previewed) == [second, third]

    for job in site.pending_solves(35.0, 5.0, MC):
        if job.engine is not site.engine_for(third):
            job.run(lambda: False)
            assert job.land()
    slow(site, 30.0)
    drawn = site.slice_at(35.0, 5.0, **tick, preview=True)
    assert drawn.previewed == {}
    assert site.pending_solves(35.0, 5.0, MC) == []

    slow(site, 1.0)
    site.engine_for(third)._last_solve_ms = None
    drawn = site.slice_at(40.0, 5.0, **tick, preview=True)
    assert list(drawn.previewed) == [first, second, third]


def test_the_site_stretch_solves_cover_what_its_shared_limit_measures(site3_factory, make_site):
    """Ruling R3: the minimum-curvature stretch is measured over the SITE
    axis's `limit_windows`, each mapped onto every grid with `window_on`, as
    `shared_limit` measures it. Its solves are exactly those grid windows,
    never a grid's own `limit_windows` (C's axis ends early here, so the two
    differ); until they land the stretch is the provisional one over their
    previews, and once they have, the final one, equal to `shared_limit`."""
    site3 = site3_factory(samples={"C": 128})  # C's lines end near 16.4 ns
    site, _ = prepared(make_site, site3)
    clip = UnipolarClip()
    tick = {"finish": MC, "method": "background", "manual": {"A": 1.5}}
    z = site.site_z
    windows = limit_windows(z, round(2.0 / z.dz_ns))
    assert len(windows) == 12
    wanted = set()
    for w in windows:
        top, thickness = z.t0_ns + w.k0 * z.dz_ns, w.n_levels * z.dz_ns
        for g in site.ready_grids:
            engine = site.engine_for(g)
            grid_window = window_on(engine.z, top, thickness)
            if grid_window is not None:
                wanted.add((engine, solve_key(engine.slice_at(grid_window)[0])))
    c = site.engine_for("C")
    own = {solve_key(c.slice_at(w)[0]) for w in limit_windows(c.z, round(2.0 / c.z.dz_ns))}
    assert own != {key for engine, key in wanted if engine is c}
    jobs = site.stretch_solves(2.0, MC)
    assert {(job.engine, job.key) for job in jobs} == wanted
    provisional = site.shared_limit(2.0, clip, **tick, preview=True)
    assert site.stretch_limit(2.0, clip, **tick) == (provisional, False)
    for job in jobs:
        job.run(lambda: False)
        assert job.land()
    assert site.stretch_solves(2.0, MC) == []
    final = site.shared_limit(2.0, clip, **tick)
    assert site.stretch_limit(2.0, clip, **tick) == (final, True)
    # Any other method has no solves and is always final.
    kriging = {**tick, "finish": FINISH}
    assert site.stretch_solves(2.0, FINISH) == []
    assert site.stretch_limit(2.0, PercentileClip(), **kriging) == (
        site.shared_limit(2.0, PercentileClip(), **kriging),
        True,
    )


def test_the_site_reports_whether_every_grids_weights_are_built(site3, make_site):
    """`weights_cached` lets the scope show a wait cursor only when a tick
    will build weights (interpolation spec §7)."""
    site, _ = prepared(make_site, site3)
    assert not site.weights_cached(FINISH)
    site.slice_at(20.0, 5.0, finish=FINISH, method="none", manual={})
    assert site.weights_cached(FINISH)
    # Smoothing is not part of the weights; a different method or distance is.
    assert site.weights_cached(dataclasses.replace(FINISH, smooth_x_m=0.4))
    assert not site.weights_cached(dataclasses.replace(FINISH, method="kriging"))


def test_a_grid_with_no_window_at_a_tick_is_not_a_rebuild_there(site3_factory, make_site):
    """A grid whose axis misses a tick's window is not finished there, so it
    never builds weights for it. Asked for that window, `weights_cached`
    leaves it out: counted, it made every tick look like a rebuild, so the
    wait cursor showed on each and a running refine was cancelled by each."""
    site3 = site3_factory(samples={"C": 128})  # C's lines end near 16.4 ns
    site, _ = prepared(make_site, site3)
    deep, shallow = (40.0, 5.0), (5.0, 2.0)
    assert site.slice_at(*deep, **TICK).windows["C"] is None
    assert site.weights_cached(FINISH, at=deep)
    assert not site.weights_cached(FINISH, at=shallow)  # C is finished there
    assert not site.weights_cached(FINISH)  # every grid: C has built nothing
    site.slice_at(*shallow, **TICK)
    assert site.weights_cached(FINISH, at=shallow) and site.weights_cached(FINISH)


def test_the_sites_held_bytes_count_the_weights_it_built(site3, make_site):
    """The status line names what is held; the weights are held too."""
    site, _ = prepared(make_site, site3)
    before = site.held_bytes
    site.slice_at(20.0, 5.0, finish=FINISH, method="none", manual={})
    assert site.held_bytes > before


def test_coverage_mode_shows_the_counts_without_normalising(site3, make_site):
    """Ruling 7: coverage is composed like values; nothing is normalised."""
    site, _ = prepared(make_site, site3)
    drawn = site.slice_at(
        20.0, 5.0, finish=FINISH, method="background", manual={"B": 3.0}, coverage=True
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
    plain = site.shared_limit(2.0, clip, finish=FINISH, method="none", manual={})
    evened = site.shared_limit(2.0, clip, finish=FINISH, method="background", manual={})

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
            finish=FINISH,
            method="background",
            manual={},
        )
        slices.extend(shown.values())
    assert evened == pytest.approx(limit_over_slices(slices, clip), rel=1e-6)
    assert abs(evened - plain) > 0.05 * plain

    gained = site.shared_limit(2.0, clip, finish=FINISH, method="none", manual={"A": 3.0})
    assert gained > plain


def test_a_grid_in_another_crs_lands_where_its_coordinates_say(site3_factory, make_site):
    """Spec 4.7: for a grid in another CRS the lattice's pixel centres are
    transformed into that grid's CRS before `bilinear_taps`. B is declared in
    EPSG:32615 (the next UTM zone) at the same place on the ground, so its
    own coordinates are some 160 km of easting away from the site's.

    The brief named EPSG:26916; measured here, QGIS's 26916 -> 32616
    operation is a null datum shift (1.6e-8 m at these coordinates,
    1e-4 m at realistic ones), so a gather that skipped the transform would
    pass. A zone change cannot be skipped."""
    site3 = site3_factory(crs={"B": "EPSG:32615"})
    site, errors = prepared(make_site, site3)
    drawn = site.slice_at(20.0, 5.0, finish=NONE, method="none", manual={})
    lattice = drawn.lattice
    frame_b = site.engine_for("B").frame
    assert frame_b.crs == "EPSG:32615" and lattice.crs == "EPSG:32616"

    values, coverage = site.engine_for("B").slice_at(drawn.windows["B"])
    shown_b = site.engine_for("B").finish(values, coverage, NONE)
    to_b = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:32616"),
        QgsCoordinateReferenceSystem("EPSG:32615"),
        QgsProject.instance(),
    )
    centres = lattice.pixel_centres()
    in_b = np.array(
        [(p.x(), p.y()) for p in (to_b.transform(QgsPointXY(x, y)) for x, y in centres)]
    )
    taps_b = bilinear_taps(frame_b, in_b)
    only_b = taps_b.inside.copy()
    for g in "AC":
        only_b &= site.engine_for(g).frame.cell_index(centres) < 0
    expected = sample(shown_b, taps_b)[only_b]
    assert np.isfinite(expected).sum() > 50
    np.testing.assert_allclose(drawn.array.ravel()[only_b], expected, atol=1e-6, equal_nan=True)
    # And on the ground: between A and C, in the site's own coordinates.
    xs = centres[only_b & np.isfinite(drawn.array.ravel()), 0]
    assert xs.min() >= 506.0 and xs.max() <= 512.1
    assert errors == [], errors


def test_a_rotated_site_composes_each_grid_bilinearly(site3, make_site):
    """Each grid's taps are kept to its own window on the lattice and sampled
    there only. B laid at 30 degrees overlaps C at a corner, which must still
    average; the tick is the mean over grids of each grid's bilinear sample
    at every pixel centre, on a lattice one cell to the pixel."""
    session = site3.session
    session.replace_grid(dataclasses.replace(session.grid("B"), azimuth=30.0))
    site, errors = prepared(make_site, site3)
    lattice = site.lattice
    assert lattice.pixel == RES.cell
    drawn = site.slice_at(20.0, 5.0, **TICK)
    shown, _ = expected_shown(site, session, 20.0, 5.0, **TICK)
    centres = lattice.pixel_centres()
    taps = {g: bilinear_taps(site.engine_for(g).frame, centres) for g in shown}
    assert (taps["B"].inside & taps["C"].inside).sum() > 50, "B and C must overlap"
    assert not taps["B"].exact, "a rotated grid is blended, not copied"
    expected = composed(site, shown)
    np.testing.assert_allclose(drawn.array, expected, atol=1e-5, equal_nan=True)
    np.testing.assert_array_equal(np.isnan(drawn.array), np.isnan(expected))
    nearest = np.where(
        taps["B"].inside, shown["B"].ravel()[np.clip(taps["B"].nearest, 0, None)], np.nan
    )
    blend = sample(shown["B"], taps["B"])
    only_b = taps["B"].inside & ~taps["C"].inside & ~taps["A"].inside
    assert np.nanmax(np.abs(nearest - blend)[only_b]) > 1e-3, "nearest and blend must differ"
    assert errors == [], errors


@pytest.mark.parametrize("azimuth", [0.0, 1e-6, 2.0, 30.0])
def test_the_site_pixel_is_the_cell_at_any_bearing(site3, make_site, azimuth):
    session = site3.session
    session.replace_grid(dataclasses.replace(session.grid("B"), azimuth=azimuth))
    site, errors = prepared(make_site, site3)
    assert site.lattice.pixel == RES.cell
    assert errors == [], errors


def test_coverage_on_the_site_is_whole_counts(site3, make_site):
    """Coverage composes with counts=True: a rotated grid's tick holds only
    whole counts (or the mean of two overlapping grids' counts), never a
    bilinear blend of a count with its empty neighbours, and its thin
    lines (one cell wide, 1.5 m apart) show."""
    session = site3.session
    session.replace_grid(dataclasses.replace(session.grid("B"), azimuth=30.0))
    # Lines 1.5 m apart at a 0.25 m cell: one-cell-wide lines between empty cells.
    site, errors = prepared(make_site, site3)
    drawn = site.slice_at(20.0, 5.0, **TICK, coverage=True)
    counts = {g: site.engine_for(g).slice_at(drawn.windows[g])[1].astype(np.float32) for g in "ABC"}
    taps_b = bilinear_taps(site.engine_for("B").frame, site.lattice.pixel_centres())
    own_b = sample_counts(counts["B"], taps_b)
    shown_b = np.isfinite(own_b)
    assert shown_b.sum() > 50, "a rotated grid's thin lines must show"
    assert np.isfinite(drawn.array.ravel()[shown_b]).all()
    allowed = {float(v) for v in np.unique(np.concatenate([c[c > 0] for c in counts.values()]))}
    everywhere = drawn.array[np.isfinite(drawn.array)]
    assert set(np.unique(everywhere)) <= allowed | {(a + b) / 2.0 for a in allowed for b in allowed}
    expected = composed(site, counts, counts=True)
    np.testing.assert_allclose(drawn.array, expected, atol=1e-5, equal_nan=True)
    assert errors == [], errors


def far_site(site3, make_site, max_pixels):
    """A site whose grid C is 5 km away, with `max_pixels` too few for the cell."""
    session = site3.session
    session.replace_grid(dataclasses.replace(session.grid("C"), origin=(5000.0, 5000.0)))
    errors: list[str] = []
    site = make_site(session, on_error=errors.append)
    site.max_pixels = max_pixels
    site.set_source(site3.source())
    assert site.wait_until_idle(60_000)
    return site, errors


def test_grids_too_far_apart_draw_a_coarser_preview_and_say_why(site3, make_site):
    """The site no longer refuses a wide area: it draws at a coarser pixel,
    names the grids that stretch it, and slices still compose."""
    site, errors = far_site(site3, make_site, 1_000_000)
    extents = [(500.0, 700.0, 506.0, 706.0), (506.0, 700.0, 512.0, 706.0)]
    extents.append((5000.0, 5000.0, 5006.0, 5006.0))
    assert SiteLattice.covering(extents, RES.cell, "EPSG:32616").n_pixels > site.max_pixels
    site.set_resolution(RES)  # does not raise
    assert site.is_preview
    ratio = site.lattice.pixel / RES.cell
    k = round(math.log2(ratio))
    assert k >= 1 and site.lattice.pixel == 2**k * RES.cell
    assert site.lattice.n_pixels <= site.max_pixels
    assert site.full_lattice.pixel == RES.cell
    assert "Leaving out C" in site.preview_note
    assert site.export_refusal is not None
    drawn = site.slice_at(20.0, 5.0, **TICK)
    assert drawn.lattice == site.lattice
    assert drawn.array.shape == (site.lattice.height, site.lattice.width)
    assert errors == []


def test_leaving_the_outlier_out_returns_to_full_detail(site3, make_site):
    site, _ = far_site(site3, make_site, 1_000_000)
    site.set_resolution(RES)
    assert site.is_preview
    site.set_source(site3.source("AB"))
    assert site.wait_until_idle(60_000)
    site.set_resolution(RES)
    assert not site.is_preview
    assert site.lattice.pixel == RES.cell
    assert site.preview_note is None and site.export_refusal is None


def test_a_site_that_fits_is_not_a_preview(site3, make_site):
    site, _ = prepared(make_site, site3)
    assert not site.is_preview
    assert site.preview_note is None
    assert site.export_refusal is None
    assert site.lattice == site.full_lattice


def test_the_sites_held_bytes_count_the_gathers_taps(site3, make_site):
    site, _ = prepared(make_site, site3)
    before = site.held_bytes
    site.slice_at(20.0, 5.0, finish=FINISH, method="none", manual={})
    assert site._gathers
    taps = sum(f.taps.nbytes for f in site._gathers.values())
    weights = sum(e.weights_nbytes for e in site._engines.values() if e.is_prepared)
    assert taps > 0
    assert site.held_bytes - before == taps + weights


def test_moving_a_grid_rebuilds_the_lattice_and_seams(site3, make_site):
    session = site3.session
    site, errors = prepared(make_site, site3)
    assert current_seams(site, session) == [("A", "B"), ("B", "C")]
    before = site.slice_at(20.0, 5.0, finish=FINISH, method="edge", manual={})
    assert before.lattice.x0 == 500.0

    session.replace_grid(dataclasses.replace(session.grid("A"), origin=(490.0, 700.0)))
    assert site.wait_until_idle(60_000)
    assert site.grid_state("A") == "ready"
    assert site.engine_for("A").frame.origin == (490.0, 700.0)

    after = site.slice_at(20.0, 5.0, finish=FINISH, method="edge", manual={})
    assert (after.lattice.x0, after.lattice.width) == (490.0, 112)
    assert current_seams(site, session) == [("B", "C")]  # A no longer meets B
    _, factors = expected_shown(site, session, 20.0, 5.0, finish=FINISH, method="edge", manual={})
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
    tick = {"finish": FINISH, "method": "edge", "manual": {}}
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
    site.slice_at(20.0, 5.0, finish=FINISH, method="edge", manual={})
    gathers, seams = dict(site._gathers), site._seams
    session.replace_grid(dataclasses.replace(session.grid("C"), default_spacing=2.0))
    assert site.wait_until_idle(5_000)
    assert site._seams is None
    assert all(site._gathers.get(g) is gathers[g] for g in "ABC")
    site.slice_at(20.0, 5.0, finish=FINISH, method="edge", manual={})
    assert site._seams is not seams and site._seams is not None


def test_the_status_line_counts_grids_lines_and_memory(site3, make_site):
    site, _ = prepared(make_site, site3)
    assert site.status_text().endswith("slices redraw in —")
    site.slice_at(20.0, 5.0, **TICK)
    text = site.status_text()
    # The weights each engine built are held too.
    held = sum(site.engine_for(g).estimate.lines_bytes for g in "ABC")
    held += sum(site.engine_for(g).weights_nbytes for g in "ABC")
    assert all(site.engine_for(g).mode == "streaming" for g in "ABC")
    assert text.startswith(f"3 grids · 12 lines held in memory, {format_bytes(held)} · ")
    assert re.fullmatch(r".* · slices redraw in \d+ ms", text), text
