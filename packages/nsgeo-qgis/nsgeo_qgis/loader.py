"""Load sample arrays off the main thread.

Header reads are 1 KB and stay synchronous; Line.load() reads megabytes and
runs on a QgsTask. The session is only touched from the main thread, in the
task's finished callback.

Two races matter here, both guarded in `finished()` below:

* the line is removed (or the whole site closed) while its load is still
  in flight -- `SiteSession.set_profiles` would raise `KeyError` for a key
  that no longer exists, so the key's continued membership in
  `session.keys()` is checked first.
* the site is closed and a *different* site is opened before the load
  finishes. Keys are relative paths, so the same string ("raw/FILE__001.DZT")
  can legitimately name a line in two different sites -- without also
  checking that `session.site` is still the exact object this request was
  made against, a slow load from the old site could land its profiles on
  the new site's identically-keyed (but different) line: not a crash, but
  silently wrong survey data attributed to the wrong place.

A third thing had to be verified directly rather than assumed:
`QgsApplication.taskManager().addTask()` does *not* keep its own strong
reference to a `QgsTask.fromFunction()` task. If nothing else in Python
references it, it is garbage-collected -- silently, with `on_finished`
never called -- as soon as the last reference goes. `_tasks` (keyed by
line, cleared on site_closed so a fresh request for a reused key is never
blocked by a stale entry) is therefore not enough on its own to keep a
task alive until it truly finishes; `_pending` below is the deliberate
keep-alive that is not tied to which site the task was requested against.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QEventLoop, QObject, QTimer, pyqtSignal

from nsgeo_qgis.session import SiteSession


class LineLoader(QObject):
    """Owns the in-flight `QgsTask` for each line key currently loading.

    One instance is meant to live for the plugin's whole session (see
    plugin.py), spanning any number of sites opened and closed in turn --
    hence the site-identity check in `finished()` rather than trusting the
    key alone.
    """

    loading_changed = pyqtSignal(str, bool)

    def __init__(
        self,
        session: SiteSession,
        on_error: Callable[[str, str], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.on_error = on_error
        self._tasks: dict[str, QgsTask] = {}
        # Every submitted task lives here, regardless of key or site, until
        # its own finished() below discards it -- see the module docstring:
        # this is what actually keeps a task alive long enough to finish
        # once _tasks (site-scoped bookkeeping) has forgotten about it.
        self._pending: set[QgsTask] = set()
        session.line_opened.connect(self._on_line_opened)
        session.site_closed.connect(self._on_site_closed)

    def _on_site_closed(self) -> None:
        # A load in flight for a line in the site being closed is not
        # cancelled: `_pending` keeps it running to completion regardless.
        # Only `_tasks` -- "is this key currently loading" -- is cleared
        # here, so a fresh request for the same key string against
        # whatever site opens next is never blocked by a stale entry; the
        # site-identity check in finished() is what keeps the eventual
        # result from landing on that new site instead.
        self._tasks.clear()

    def is_loading(self, key: str) -> bool:
        return key in self._tasks

    def _on_line_opened(self, key: str) -> None:
        # A slot on a pyqtSignal: an uncaught exception here would be
        # swallowed by Qt (emit() returns as if this had succeeded), so a
        # failure must still be reported through on_error rather than
        # vanish. In practice `key` here always names a line the session
        # just validated in open_line(), so this path is not expected to
        # raise -- the guard is defensive, matching every other slot in
        # this plugin.
        if not key:
            return
        try:
            self.request(key)
        except Exception as exc:  # noqa: BLE001 -- see the comment above
            if self.on_error is not None:
                self.on_error(key, str(exc))

    def request(self, key: str) -> None:
        """Start loading `key`'s samples in the background, unless a load
        for it is already in flight or its profiles are already cached on
        the session."""
        if key in self._tasks or self.session.profiles_for(key) is not None:
            return
        line = self.session.line_for_key(key)
        # Captured now, not re-read in finished(): identifies which site
        # this request was made against, so a stale result from a site
        # closed (or replaced) in the meantime is never written into
        # whatever site happens to be open when the task completes.
        requested_against = self.session.site

        def work(_task: QgsTask) -> Any:
            return line.load()

        def finished(exception: BaseException | None, result: Any = None) -> None:
            self._tasks.pop(key, None)
            self._pending.discard(task)
            try:
                if exception is not None:
                    if self.on_error is not None:
                        self.on_error(key, str(exception))
                else:
                    # Short-circuited on purpose: session.keys() requires an
                    # open site and raises otherwise, so it must never run
                    # once the site the request was made against is gone
                    # (closed outright, or replaced by a different one).
                    same_site = self.session.site is requested_against
                    still_present = same_site and key in self.session.keys()  # noqa: SIM118 -- not a dict
                    if still_present:
                        self.session.set_profiles(key, result)
            finally:
                # Always emitted, even if on_error or set_profiles above
                # misbehaves: a caller tracking per-key loading state (a
                # spinner, wait_for()'s own event loop) must see this
                # request end, not hang because a later step in an
                # otherwise-independent handler raised.
                self.loading_changed.emit(key, False)

        task = QgsTask.fromFunction(f"nsgeo: load {line.path.name}", work, on_finished=finished)
        self._tasks[key] = task
        self._pending.add(task)
        self.loading_changed.emit(key, True)
        QgsApplication.taskManager().addTask(task)

    def wait_for(self, key: str, timeout_ms: int = 5000) -> bool:
        """Spin the event loop until `key` finishes loading, or `timeout_ms`
        elapses. For tests. Returns whether the key is no longer loading --
        a hung load fails the caller's assertion instead of the suite."""
        if key not in self._tasks:
            return True
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def on_change(k: str, flag: bool) -> None:
            if k == key and not flag:
                loop.quit()

        self.loading_changed.connect(on_change)
        timer.start(timeout_ms)
        loop.exec()
        self.loading_changed.disconnect(on_change)
        return key not in self._tasks
