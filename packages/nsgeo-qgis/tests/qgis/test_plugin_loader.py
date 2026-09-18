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


def _wait_for_task_finished(task, timeout_ms: int = 5000) -> bool:
    """Spin until `task`'s own on_finished callback has run *without
    raising*, or time out.

    Needed once a task is no longer "live" for its key (a stale task after
    site_closed, or one superseded by a fresh request for the same key --
    see loader.py's `finished()`): LineLoader no longer emits
    `loading_changed` for such a task's completion, by design, so this
    observes the callback directly instead of going through the loader's
    own signal.

    Review round 2, Finding 1: the callback finishing at all is not
    enough -- if it raised outright (nothing in loader.py catches an
    exception that escapes finished() entirely), QgsTaskWrapper.finished()
    (QGIS's own code) still swallows it completely, so this must not
    report success for that either. `raised` is tracked separately from
    `done` so a caller cannot mistake "the callback ran" for "the callback
    ran correctly".
    """
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    done = []
    raised = []
    original = task.on_finished

    def wrapped(*args: object, **kwargs: object) -> object:
        try:
            return original(*args, **kwargs)
        except Exception:
            raised.append(True)
            raise
        finally:
            done.append(True)
            loop.quit()

    task.on_finished = wrapped
    timer.start(timeout_ms)
    loop.exec()
    return bool(done) and not raised


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
    # Grabbed before site_closed clears the dict: the stale task is no
    # longer "live" for `key` once a fresh one is registered below, so
    # LineLoader no longer emits loading_changed for its completion (see
    # loader.py's finished()) -- wait on the task itself instead.
    stale_task = loader._tasks[key]

    session.close_site()
    site_b = tmp_path.parent / f"{tmp_path.name}_b"  # a sibling root, same "raw/..." layout
    site_b.mkdir()
    session.new_site(site_b)
    session.add_grid(GRID)
    q = synthetic_dzt(site_b / "raw", "FILE__001.DZT", n_traces=222)
    session.add_lines([Line.open(q, GridPlacement("A", "y", 0.0))])
    assert session.keys() == [key]  # same key string, a different site and file

    assert _wait_for_task_finished(stale_task)
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

    Review round 2, Finding 1: `_wait_for_task_finished` alone only
    catches the check escaping finished() entirely (the callback raising
    outright) -- it does *not* catch the check being evaluated eagerly
    but still inside finished()'s own `try`, since Finding 7's `except`
    absorbs that before it ever reaches the helper. The `on_error`
    recorder and `errors == []` below catch that half instead: an eager
    `key in self.session.keys()` raises `ProjectError`, caught internally
    and routed to on_error -- a spurious Critical message-bar entry on
    every site close with a load in flight, not a crash the helper would
    ever see.
    """
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    errors = []
    loader = LineLoader(session, on_error=lambda k, msg: errors.append((k, msg)))
    session.open_line(key)
    assert loader.is_loading(key)
    stale_task = loader._tasks[key]  # see the sibling test above for why

    session.close_site()
    assert _wait_for_task_finished(stale_task)
    assert errors == []


def test_a_stale_tasks_finished_does_not_clobber_a_live_tasks_bookkeeping(session, tmp_path):
    """Review round 1, Finding 1 (and, via the `task_b is not task_a`
    assertion below, Finding 5): a stale task's finished() must only ever
    touch _tasks/loading_changed for *its own* registration, never
    whatever the current live task for that key happens to be.

    Reproduced by controlling the interleaving directly rather than
    racing two real background reads: grab site A's task, close the site
    (task keeps running via _pending, but _tasks.clear() -- itself
    pinned by the `task_b is not task_a` assertion below -- frees `key`),
    open site B with the same relative key and register its own task
    under `key`, then invoke site A's *stale* on_finished callback
    directly, exactly as QGIS's own task manager would, but at a moment
    of our choosing: while site B's task is still genuinely in flight.
    """
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    loader = LineLoader(session)
    session.open_line(key)
    task_a = loader._tasks[key]

    session.close_site()
    site_b = tmp_path.parent / f"{tmp_path.name}_stale"
    site_b.mkdir()
    session.new_site(site_b)
    session.add_grid(GRID)
    q = synthetic_dzt(site_b / "raw", "FILE__001.DZT", n_traces=333)
    session.add_lines([Line.open(q, GridPlacement("A", "y", 0.0))])
    session.open_line(key)
    task_b = loader._tasks[key]
    # If _on_site_closed's _tasks.clear() were a no-op, request() would
    # have seen `key` still "in flight" above and skipped registering
    # task_b entirely -- this is what pins Finding 5.
    assert task_b is not task_a

    states = []
    loader.loading_changed.connect(lambda k, f: states.append((k, f)))

    task_a.on_finished(None, [])  # site A's stale task, reporting late

    assert loader.is_loading(key)  # task_b's registration must survive
    assert loader._tasks.get(key) is task_b
    assert states == []  # no spurious (key, False) for the still-running task_b

    assert loader.wait_for(key)  # let task_b actually finish
    assert session.stack_for(key).source.n_traces == 333


def test_removing_the_line_mid_load_is_not_written_back(session, tmp_path, monkeypatch):
    """The brief's headline race, and the one Task 6 built
    SiteSession.set_profiles's key-validates-first behaviour for: request
    a load, remove the line before it finishes, let the task complete
    clean (no exception). Dropping the `key in self.session.keys()` half
    of finished()'s check (keeping only the site-identity half, which
    does not change here -- the site stays open throughout) would call
    set_profiles on a key remove_line() already deleted from every
    session structure it touches.

    Review round 2, Finding 2: spy on the write directly rather than on
    the resulting error, so this pins "finished() must not attempt the
    write-back" on its own -- independent of whether attempting it would
    also have raised (it does today, via stack_for(), caught by Finding
    7's `except`; that is a separate, already-covered concern).
    """
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    loader = LineLoader(session)
    session.open_line(key)
    assert loader.is_loading(key)

    calls = []
    monkeypatch.setattr(session, "set_profiles", lambda k, v: calls.append(k))
    session.remove_line(key)

    assert loader.wait_for(key)
    assert calls == []


def test_wait_for_does_not_report_success_from_a_timeout_alone(session):
    """wait_for()'s contract is "key actually finished loading while this
    waited", not merely "key is no longer tracked afterwards" -- those
    happen together on every real path today only because finished()
    keeps its pop and its emit paired on purpose (see Finding 1's fix).
    Simulated here by taking the key out of _tasks without ever emitting
    for it -- standing in for that guarantee breaking -- via a QTimer
    that fires *during* wait_for's own event-loop spin.
    """
    loader = LineLoader(session)
    loader._tasks["ghost"] = object()

    def sabotage() -> None:
        loader._tasks.pop("ghost", None)  # removed, but nothing ever emits for it

    QTimer.singleShot(20, sabotage)
    assert loader.wait_for("ghost", timeout_ms=200) is False


def test_request_is_a_no_op_while_already_in_flight(session, tmp_path):
    """request() is public interface, reachable directly and not only via
    line_opened: calling it twice for the same still-loading key must
    start exactly one task. open_line()'s own early-return on an
    unchanged current key means the brief's four given tests exercise
    this guard only through a path (test_reopening_a_loaded_line_does_not_reload)
    that never actually reaches it while the first load is still running --
    calling request() directly does.
    """
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    loader = LineLoader(session)
    states = []
    loader.loading_changed.connect(lambda k, f: states.append((k, f)))

    loader.request(key)
    loader.request(key)

    assert states == [(key, True)]
    assert loader.wait_for(key)


def test_line_opened_empty_key_is_a_no_op(session, tmp_path):
    """close_site() emits line_opened("") when a line was current (see
    SiteSession.close_site's docstring) -- _on_line_opened's `if not key:
    return` guard exists specifically to ignore that, not route "" into
    request()/on_error as if it were a real key.
    """
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    errors = []
    loader = LineLoader(session, on_error=lambda k, msg: errors.append((k, msg)))
    session.open_line(key)
    assert loader.wait_for(key)

    session.close_site()  # had_current_line -> emits line_opened("")

    assert errors == []


def test_an_unexpected_failure_after_a_successful_load_is_reported_not_lost(
    session, tmp_path, monkeypatch
):
    """Nothing today makes set_profiles raise once finished()'s own
    site/key checks pass, but if it (or anything else on that path) ever
    did, QgsTaskWrapper.finished() (QGIS's own code, not this module's)
    swallows the exception completely -- no traceback, nowhere at all.
    finished()'s own `except` is the only thing standing between that and
    a load silently vanishing without a trace.
    """
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    errors = []
    loader = LineLoader(session, on_error=lambda k, msg: errors.append((k, msg)))

    def boom(key_: str, profiles: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(session, "set_profiles", boom)
    session.open_line(key)
    assert loader.wait_for(key)

    assert errors and errors[0][0] == key and "boom" in errors[0][1]


def test_a_task_the_manager_refuses_to_schedule_does_not_pin_the_key_forever(
    session, tmp_path, monkeypatch
):
    """addTask() returns 0 (never a real task ID) if it could not add the
    task at all -- and per loader.py's module docstring, nothing else
    keeps an un-added task alive either, so on_finished is never going to
    run for it. Without checking the return value, `key` would stay
    marked as loading forever: is_loading(key) stuck True, and every
    future request(key) a permanent no-op, with no way back short of
    restarting the process.
    """
    from qgis.core import QgsTaskManager

    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    errors = []
    loader = LineLoader(session, on_error=lambda k, msg: errors.append((k, msg)))

    monkeypatch.setattr(QgsTaskManager, "addTask", lambda self, task, priority=0: 0)

    session.open_line(key)

    assert not loader.is_loading(key)
    assert errors and errors[0][0] == key
