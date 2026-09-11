"""Offscreen QGIS for tests that construct widgets and layers.

Skips the whole directory when `qgis` is not importable, so the normal CI
matrix (no QGIS) stays green while `.venv-qgis` and the Docker job run it.
"""

from __future__ import annotations

import os
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
    QFileDialog.getOpenFileName()/getExistingDirectory(), and
    QDialog.exec() all block indefinitely under QT_QPA_PLATFORM=offscreen
    -- there is no window manager to click a button, so a test that
    triggers one by accident would hang the whole suite rather than fail
    fast. A test that means to trigger one must use the `answer_modal`
    fixture (QMessageBox/QFileDialog) or `drive_dialog` fixture
    (QDialog.exec) below, which override this guard for exactly the call
    they are told to expect.

    Raising is strictly stronger than the alternative of returning some
    default answer: nothing before this asserted that a prompt appeared
    at all, let alone with which buttons, so a silently-supplied default
    would mask exactly the kind of bug this guard exists to catch. This
    is also why QDialog.exec() is forbidden here rather than given a
    default DialogCode: a test that never drives the dialog would
    otherwise see it silently "Accepted" or "Rejected" and assert on
    fields nothing actually set.
    """
    from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox

    def _forbid(cls: type, name: str) -> None:
        def _raise(*args: object, **kwargs: object) -> None:
            raise AssertionError(f"unexpected modal: {cls.__name__}.{name}{args!r}")

        monkeypatch.setattr(cls, name, staticmethod(_raise))

    for cls, name in (
        (QMessageBox, "question"),
        (QMessageBox, "warning"),
        (QMessageBox, "information"),
        (QFileDialog, "getOpenFileName"),
        (QFileDialog, "getExistingDirectory"),
        (QDialog, "exec"),
    ):
        _forbid(cls, name)


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
