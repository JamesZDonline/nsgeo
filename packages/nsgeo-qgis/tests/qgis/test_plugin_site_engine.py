"""SiteEngine: one SliceEngine per grid, prepared one at a time, composed per tick."""

from __future__ import annotations

import dataclasses
import re
import threading
import time

import numpy as np
import pytest
from nsgeo.model.survey import Line
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
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
)
from qgis.PyQt.QtCore import QCoreApplication, QEventLoop

#: M11's test resolution, with the z range widened to hold the whole site.
RES = Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=60.0)
TICK = {"radius_spacings": 1.5, "method": "none", "manual": {}}


class LoadCounter:
    """`Line.load`, counted -- and optionally slowed -- under a lock.

    M11's `test_two_different_choices_back_to_back_never_run_concurrently`
    pattern: the sleep widens the few milliseconds a real read holds a
    worker thread into a window long enough that a counter under a lock
    catches two preparations overlapping deterministically, which is
    stronger evidence than timing and safer than waiting for a segfault.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = 0
        self.concurrent = 0
        self.max_concurrent = 0
        lock = threading.Lock()
        real_load = Line.load

        def load(line: Line) -> list:
            with lock:
                self.calls += 1
                self.concurrent += 1
                self.max_concurrent = max(self.max_concurrent, self.concurrent)
            try:
                if self.delay:
                    time.sleep(self.delay)
                return real_load(line)
            finally:
                with lock:
                    self.concurrent -= 1

        monkeypatch.setattr(Line, "load", load)


def spin_until(predicate, timeout_ms: int = 20_000) -> bool:
    """Run the event loop until `predicate()` holds, or time out."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while not predicate():
        if time.monotonic() > deadline:
            return False
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 5)
        time.sleep(0.002)
    return True


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

    site.set_source(site3.source())
    assert site.wait_until_idle(60_000)
    assert counter.max_concurrent == 1, (
        f"a grid started while a cancelled task still ran (max={counter.max_concurrent})"
    )
    assert site.ready_grids == ("A", "B", "C")


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

    Errors are not asserted: M11's `SliceEngine.dispose()` reports "did not
    stop in time" twice when the site closes under a preparation, because
    its `finished` stays silent for a site that is gone and each confirm
    wait runs out (pre-existing; recorded in the M12 Task 3 report)."""
    counter = LoadCounter(monkeypatch, delay=0.05)
    session = site3.session
    site = make_site(session)
    site.set_resolution(RES)
    site.set_source(site3.source())
    assert spin_until(lambda: site.grid_state("B") == "preparing")

    session.close_site()
    assert not site.is_running
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

    assert list(dict.fromkeys(seen)) == [("A",), ("A", "B"), ("A", "B", "C")]
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


def test_the_status_line_counts_grids_lines_and_memory(site3, make_site):
    site, _ = prepared(make_site, site3)
    assert site.status_text().endswith("slices redraw in —")
    site.slice_at(20.0, 5.0, **TICK)
    text = site.status_text()
    held = sum(site.engine_for(g).estimate.lines_bytes for g in "ABC")
    assert all(site.engine_for(g).mode == "streaming" for g in "ABC")
    assert text.startswith(f"3 grids · 12 lines held in memory, {format_bytes(held)} · ")
    assert re.fullmatch(r".* · slices redraw in \d+ ms", text), text
