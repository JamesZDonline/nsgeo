"""Offscreen QGIS for tests that construct widgets and layers.

Skips the whole directory when `qgis` is not importable, so the normal CI
matrix (no QGIS) stays green while `.venv-qgis` and the Docker job run it.
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
qgis_core = pytest.importorskip("qgis.core")


@pytest.fixture(scope="session")
def qgis_app():
    from qgis.core import QgsApplication

    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    yield app
    app.exitQgis()


class FakeIface:
    """The parts of QgisInterface the plugin touches."""

    def __init__(self) -> None:
        from qgis.gui import QgsMapCanvas, QgsMessageBar
        from qgis.PyQt.QtWidgets import QMainWindow

        self._main = QMainWindow()
        self._canvas = QgsMapCanvas(self._main)
        self._main.setCentralWidget(self._canvas)
        self._bar = QgsMessageBar(self._main)
        self.docks: list = []
        self.toolbars: list = []
        self.menu_actions: list = []

    def mainWindow(self):
        return self._main

    def mapCanvas(self):
        return self._canvas

    def messageBar(self):
        return self._bar

    def addToolBar(self, name):
        from qgis.PyQt.QtWidgets import QToolBar

        tb = QToolBar(name, self._main)
        self._main.addToolBar(tb)
        self.toolbars.append(tb)
        return tb

    def addDockWidget(self, area, dock):
        self._main.addDockWidget(area, dock)
        self.docks.append(dock)

    def removeDockWidget(self, dock):
        self._main.removeDockWidget(dock)
        if dock in self.docks:
            self.docks.remove(dock)

    def addPluginToMenu(self, name, action):
        self.menu_actions.append((name, action))

    def removePluginMenu(self, name, action):
        self.menu_actions.remove((name, action))


@pytest.fixture
def fake_iface(qgis_app):
    return FakeIface()


@pytest.fixture(autouse=True)
def _no_unhandled_modals(monkeypatch):
    """Every test in this tier defaults to *forbidding* a real modal.

    QMessageBox.question()/warning()/information(),
    QFileDialog.getOpenFileName()/getOpenFileNames()/getExistingDirectory(),
    QInputDialog.getText(), QDialog.exec(), and QMenu.exec() all block
    indefinitely under QT_QPA_PLATFORM=offscreen -- there is no window
    manager to click a button, so a test that triggers one by accident
    would hang the whole suite rather than fail fast. A test that means to
    trigger one must use the `answer_modal` fixture
    (QMessageBox/QFileDialog/QInputDialog) or `drive_dialog` fixture
    (QDialog.exec, QMenu.exec) below, which override this guard for
    exactly the call they are told to expect.

    QMenu.exec() is listed separately from QDialog.exec() because it is a
    separate function: verified against this Qt build, `'exec' in
    QMenu.__dict__` is True, so QMenu defines its own and patching
    QDialog's does not cover it. That gap was real -- `SurveyDock.
    _on_context_menu` calls `menu.exec(...)`, the one reachable modal path
    the guard missed, so a test of the survey tree's context menu would
    have hung the suite instead of failing fast. Both `exec` and the
    PyQt5-only `exec_` spelling are forbidden for each class, because they
    are distinct objects (`QDialog.exec is QDialog.exec_` is False) and
    production code calling the other spelling would otherwise slip past.

    Raising is strictly stronger than the alternative of returning some
    default answer: nothing before this asserted that a prompt appeared
    at all, let alone with which buttons, so a silently-supplied default
    would mask exactly the kind of bug this guard exists to catch. This
    is also why QDialog.exec() is forbidden here rather than given a
    default DialogCode: a test that never drives the dialog would
    otherwise see it silently "Accepted" or "Rejected" and assert on
    fields nothing actually set.

    `QTest.mouseDClick` is forbidden here too, for an unrelated but
    similarly repo-wide reason: verified directly, it corrupts mouse state
    in this offscreen-QPA environment that outlives both the widget and
    the test -- a `QTest.mouseDClick` in one test reproducibly blocked a
    plain, buttonless `QTest.mouseMove` on a *different* widget in the
    *next* test, in a different file, with `mouseMoveEvent` silently never
    firing (see `plugin_testing.send_double_click` for the full account
    and the fix -- a shared helper any test in this tier can import,
    unlike a private one local to a single file). A hazard like that is
    worth making unrepresentable here, the same way a real modal already
    is, rather than trusting every future test in this tier to remember
    not to call it.
    """
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QInputDialog, QMenu, QMessageBox

    def _forbid(cls: type, name: str, reason: str = "unexpected modal") -> None:
        def _raise(*args: object, **kwargs: object) -> None:
            raise AssertionError(f"{reason}: {cls.__name__}.{name}{args!r}")

        monkeypatch.setattr(cls, name, staticmethod(_raise))

    for cls, name in (
        (QMessageBox, "question"),
        (QMessageBox, "warning"),
        (QMessageBox, "information"),
        (QFileDialog, "getOpenFileName"),
        (QFileDialog, "getOpenFileNames"),
        (QFileDialog, "getExistingDirectory"),
        (QDialog, "exec"),
        (QDialog, "exec_"),
        (QMenu, "exec"),
        (QMenu, "exec_"),
        (QInputDialog, "getText"),
    ):
        _forbid(cls, name)
    _forbid(
        QTest,
        "mouseDClick",
        reason="QTest.mouseDClick corrupts mouse state that outlives this test -- "
        "use plugin_testing.send_double_click instead",
    )


@pytest.fixture(autouse=True)
def _no_swallowed_slot_exceptions(monkeypatch):
    """Fail any test that let an exception escape a Qt slot.

    PyQt cannot propagate an exception raised inside a slot back to
    whatever emitted the signal: the emit came from C++, and there is no
    Python frame to unwind into. What it does instead is build-dependent,
    and that is the whole problem. This build (PyQt 5.15.10) hands the
    exception to `sys.excepthook`, prints a traceback to stderr, and
    carries on -- so the test still reports PASSED. The CI container's
    build routes the same exception to `qFatal()`, which calls `abort()`.
    That is exactly how two tests in `test_plugin_processing_dock.py`
    stayed green here for four tasks while job `plugin-qgis` died with
    `Aborted (core dumped)` at the first of them, taking every test after
    it down unrun.

    Recording the hook and failing the test turns that whole class of bug
    into a local red test instead of a CI-only abort -- including a
    `_no_unhandled_modals` AssertionError raised inside a slot, which is
    the one place that guard could otherwise be reported and ignored.
    `sys.unraisablehook` is covered for the same reason: an exception
    escaping a `__del__` or a weakref callback (Qt object teardown is full
    of both) never reaches `sys.excepthook` at all.

    There is deliberately no opt-out fixture. A test that means to provoke
    an exception inside a slot should assert on the observable consequence
    -- "a traceback was printed to stderr" is not something any test can
    assert on, which is precisely why this hole existed.
    """
    escaped: list[str] = []

    def _excepthook(exc_type: Any, exc: BaseException, tb: Any) -> None:
        escaped.append("".join(traceback.format_exception(exc_type, exc, tb)))

    def _unraisablehook(unraisable: Any) -> None:
        escaped.append(
            f"unraisable in {unraisable.object!r}:\n"
            + "".join(
                traceback.format_exception(
                    unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback
                )
            )
        )

    monkeypatch.setattr(sys, "excepthook", _excepthook)
    monkeypatch.setattr(sys, "unraisablehook", _unraisablehook)
    yield
    if escaped:
        pytest.fail(
            f"{len(escaped)} exception(s) escaped a Qt slot and were swallowed. "
            "This build prints them and carries on; the CI container turns the "
            "first one into qFatal() and aborts the whole job:\n\n" + "\n".join(escaped),
            pytrace=False,
        )


@pytest.fixture
def message_log(qgis_app):
    """Captured `QgsMessageLog` messages, for the life of this test only.

    `QgsApplication.messageLog()` is a session-scoped singleton, so a
    connection left dangling would keep accumulating every later test's
    messages into this one's list for the rest of the (also
    session-scoped) `qgis_app` fixture. Disconnected on teardown.

    Previously duplicated, with only the docstring differing, across
    `test_plugin_layers.py`, `test_plugin_profile_view.py`,
    `test_plugin_profile_dock.py`, and `test_plugin_param_form.py`;
    consolidated here so every test in this tier gets it for free, with
    no import needed, the same way `fake_iface`/`answer_modal` already are.
    """
    from qgis.core import QgsApplication

    log = QgsApplication.messageLog()
    messages: list[str] = []

    def _on_message(msg: str, tag: str, level: int) -> None:
        messages.append(msg)

    log.messageReceived.connect(_on_message)
    yield messages
    log.messageReceived.disconnect(_on_message)


@pytest.fixture
def answer_modal(monkeypatch):
    """Opt-in override of `_no_unhandled_modals` for one expected modal.

    `calls = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)`
    makes the next (and every later) call to `QMessageBox.question` in this
    test return that answer instead of raising, and appends each call's
    `(args, kwargs)` to the returned list -- so a test can supply the
    answer and still assert on what was actually shown (title, text,
    button set).
    """

    def _install(cls: type, name: str, value: object) -> list[tuple[tuple, dict]]:
        calls: list[tuple[tuple, dict]] = []

        def _fake(*args: object, **kwargs: object) -> object:
            calls.append((args, kwargs))
            return value

        monkeypatch.setattr(cls, name, staticmethod(_fake))
        return calls

    return _install


@pytest.fixture
def drive_dialog(monkeypatch):
    """Opt-in override of `_no_unhandled_modals` for `QDialog.exec()`.

    Unlike `answer_modal`'s targets, `QDialog.exec()` is an *instance*
    method, and a real dialog needs its fields set and its buttons
    clicked before it can be answered -- there is no single fixed
    "value" to return the way there is for `QMessageBox.question()`.

    `calls = drive_dialog(QDialog, "exec", lambda dialog: dialog.accept())`
    makes the next (and every later) call to `cls.exec` run
    `driver(dialog_instance)` -- so a test can set fields and click
    buttons on the real dialog, exactly as a user would -- and then
    return `dialog_instance.result()` (DialogCode.Accepted/Rejected,
    whichever `driver` chose) instead of blocking in a real modal event
    loop. Each call's dialog instance is appended to the returned list,
    so a test can still assert on which dialog was shown.
    """

    def _install(cls: type, name: str, driver: Any) -> list[object]:
        calls: list[object] = []

        def _fake(self: object, *args: object, **kwargs: object) -> int:
            calls.append(self)
            driver(self)
            return self.result()  # type: ignore[attr-defined]

        monkeypatch.setattr(cls, name, _fake)
        return calls

    return _install
