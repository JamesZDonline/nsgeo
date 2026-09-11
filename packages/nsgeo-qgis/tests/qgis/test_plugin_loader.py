from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.loader import LineLoader
from nsgeo_qgis.session import SiteSession
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.PyQt.QtCore import QEventLoop, QTimer

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.add_grid(GRID)
    return s


def _wait_signal(signal, predicate, timeout_ms: int = 5000) -> bool:
    """Spin until `signal`'s args satisfy `predicate`, or time out. Used
    only where `LineLoader.wait_for` cannot apply -- see the cross-site
    test below, where the key has already stopped being tracked by the
    loader (site_closed cleared it) before the stale task actually finishes.
    """
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    matched = []

    def on_emit(*args: object) -> None:
        if predicate(*args):
            matched.append(args)
            loop.quit()

    signal.connect(on_emit)
    timer.start(timeout_ms)
    loop.exec()
    signal.disconnect(on_emit)
    return bool(matched)


def test_opening_a_line_loads_it_in_the_background(session, tmp_path):
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=200)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    loader = LineLoader(session)
    states = []
    loader.loading_changed.connect(lambda k, f: states.append((k, f)))
    loaded = []
    session.line_loaded.connect(loaded.append)

    session.open_line(key)
    assert loader.is_loading(key)
    assert loader.wait_for(key)
    assert not loader.is_loading(key)
    assert states == [(key, True), (key, False)]
    assert loaded == [key]
    assert session.stack_for(key).source.n_traces == 200


def test_reopening_a_loaded_line_does_not_reload(session, tmp_path):
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    q = synthetic_dzt(tmp_path / "raw", "FILE__002.DZT")
    session.add_lines(
        [Line.open(p, GridPlacement("A", "y", 0.0)), Line.open(q, GridPlacement("A", "y", 0.5))]
    )
    a, b = session.keys()
    loader = LineLoader(session)
    session.open_line(a)
    assert loader.wait_for(a)
    session.open_line(b)
    assert loader.wait_for(b)
    states = []
    loader.loading_changed.connect(lambda k, f: states.append((k, f)))
    session.open_line(a)
    assert states == [] and not loader.is_loading(a)


def test_a_corrupt_file_reports_instead_of_raising(session, tmp_path):
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    p.write_bytes(p.read_bytes()[:-7])  # non-integer trace count now
    errors = []
    loader = LineLoader(session, on_error=lambda k, msg: errors.append((k, msg)))
    session.open_line(key)
    assert loader.wait_for(key)
    assert errors and errors[0][0] == key and "trace count" in errors[0][1]
    assert session.profiles_for(key) is None


@needs_real_data
def test_real_line_loads(session):
    line = Line.open(REAL_DZT[0], GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    loader = LineLoader(session)
    session.open_line(key)
    assert loader.wait_for(key, timeout_ms=10_000)
    src = session.stack_for(key).source
    assert src.n_samples == 512 and src.t0_ns == pytest.approx(-11.09, abs=0.01)


def test_concurrent_loads_of_different_lines_do_not_cross_contaminate(session, tmp_path):
    """The sharp edge the brief calls out: several cold loads land on
    QgsTask worker threads at once and all contend on Line.load()'s
    lru_cache lock. That lock only serialises the cache bookkeeping, not
    the disk reads themselves (a miss releases it before calling the
    wrapped function) -- so this asserts on the thing that would actually
    reveal a mistake in *this* module: each key ends up with its own
    file's data, never another's."""
    lines = []
    sizes = (60, 61, 62, 63)
    for i, (offset, n) in enumerate(zip((0.0, 0.5, 1.0, 1.5), sizes)):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__{i:03d}.DZT", n_traces=n)
        lines.append(Line.open(p, GridPlacement("A", "y", offset)))
    session.add_lines(lines)
    keys = session.keys()
    loader = LineLoader(session)

    for key in keys:
        loader.request(key)
    assert all(loader.is_loading(k) for k in keys)

    for key in keys:
        assert loader.wait_for(key)

    for key, n in zip(keys, sizes):
        assert session.profiles_for(key) is not None
        assert session.profiles_for(key)[0].n_traces == n


def test_dropping_the_loader_reference_does_not_lose_an_in_flight_load(session, tmp_path):
    """Mirrors plugin.unload()'s `self.loader = None` with a load still in
    flight -- and, like unload() at that point, `session` (here: this
    test's own local) is still very much alive. Its signal connections to
    the loader's bound methods are what keep the loader (and, through
    `_pending`, the running task) reachable even though nothing named
    `loader` remains: dropping the plugin's reference must not orphan the
    load, crash the worker thread, or lose the result."""
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=77)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    loader = LineLoader(session)
    loaded = []
    session.line_loaded.connect(loaded.append)

    session.open_line(key)
    assert loader.is_loading(key)
    loader = None  # noqa: F841 -- simulate plugin.py's unload(): drop our reference

    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    session.line_loaded.connect(lambda k: loop.quit())
    timer.start(5000)
    loop.exec()

    assert loaded == [key]
    assert session.stack_for(key).source.n_traces == 77


def test_switching_sites_mid_load_does_not_write_into_the_new_site(session, tmp_path):
    """Keys are relative paths (nsgeo.project._line_key), so the same
    string can legitimately name a line in two different sites -- e.g. the
    same "raw/FILE__001.DZT" layout reused for a second survey. A load
    started against the first site must not land its result on the second
    site's identically-keyed but different line just because the key
    string happens to match: that would be silently wrong survey data
    attributed to the wrong place, not merely a missed update.
    """
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=111)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]  # "raw/FILE__001.DZT", relative to tmp_path (site A's root)
    loader = LineLoader(session)
    session.open_line(key)
    assert loader.is_loading(key)

    # loader.wait_for() cannot be used from here on for this key: closing
    # the site clears LineLoader's own bookkeeping immediately (see the
    # loader's site_closed connection), so `key` stops being tracked well
    # before the stale background task actually finishes. loading_changed
    # still fires when it does, regardless of what -- if anything -- it
    # wrote, so that is what this waits on instead.
    session.close_site()
    site_b = tmp_path.parent / f"{tmp_path.name}_b"  # a sibling root, same "raw/..." layout
    site_b.mkdir()
    session.new_site(site_b)
    session.add_grid(GRID)
    q = synthetic_dzt(site_b / "raw", "FILE__001.DZT", n_traces=222)
    session.add_lines([Line.open(q, GridPlacement("A", "y", 0.0))])
    assert session.keys() == [key]  # same key string, a different site and file

    assert _wait_signal(loader.loading_changed, lambda k, f: k == key and not f)
    assert session.profiles_for(key) is None  # the stale load did not land here

    session.open_line(key)
    assert loader.wait_for(key)
    assert session.stack_for(key).source.n_traces == 222


def test_closing_the_site_entirely_mid_load_does_not_crash_the_callback(session, tmp_path):
    """The other half of the site-identity guard above: closing the site
    with nothing reopened afterwards leaves `session.site` as None rather
    than a different object. `session.keys()` requires an open site and
    raises `ProjectError` otherwise, so `finished()` must short-circuit on
    the identity check *before* ever calling it -- not just happen to
    still work because some other site was opened in time.
    """
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    loader = LineLoader(session)
    session.open_line(key)
    assert loader.is_loading(key)

    session.close_site()
    assert _wait_signal(loader.loading_changed, lambda k, f: k == key and not f)
    assert not session.is_open
