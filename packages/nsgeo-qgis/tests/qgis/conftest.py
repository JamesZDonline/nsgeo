"""Offscreen QGIS for tests that construct widgets and layers.

Skips the whole directory when `qgis` is not importable, so the normal CI
matrix (no QGIS) stays green while `.venv-qgis` and the Docker job run it.
"""

from __future__ import annotations

import os
import sys
import traceback
import zlib
from typing import Any

import numpy as np
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


class _FakeSignal:
    """Enough of a pyqtSignal for `FakeIface` to carry one.

    `FakeIface` is a plain object, not a QObject, so it cannot declare a
    real `pyqtSignal`; promoting it to QObject would change the lifetime
    of every fixture in this suite for one signal. Connect/emit is all the
    plugin asks of `initializationCompleted`, and `disconnect` raises on an
    unknown slot exactly as Qt's does, because the plugin's `unload()`
    suppresses precisely that.
    """

    def __init__(self) -> None:
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def disconnect(self, slot=None) -> None:
        if slot is None:
            self._slots.clear()
        else:
            self._slots.remove(slot)  # raises if never connected, as Qt does

    def emit(self) -> None:
        for slot in list(self._slots):
            slot()


class FakeIface:
    """The parts of QgisInterface the plugin touches."""

    def __init__(self) -> None:
        #: QGIS emits this when startup -- INCLUDING restoring the saved
        #: window layout -- is over. See `_tabify_slices_dock`.
        self.initializationCompleted = _FakeSignal()
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


def _real_canvas(fake_iface, crs, extent):
    """The FakeIface canvas, shown offscreen at 800 x 600 px, looking at
    `extent` (a QgsRectangle in `crs`), with its events processed.

    When the extent is 800 x 600 map units in a metric CRS the canvas must
    come out at exactly 1 m per pixel; that is asserted here so a pixel
    tolerance in a test cannot pass by accident. For any other extent
    (a lon/lat box, say) the caller asserts what it needs.
    """
    from qgis.core import Qgis, QgsApplication

    canvas = fake_iface.mapCanvas()
    fake_iface.mainWindow().show()
    # Fixed, not resize(): the main window's layout would otherwise win.
    canvas.setFixedSize(800, 600)
    QgsApplication.processEvents()
    # ... and the canvas's own frame takes a pixel or two off each side, so
    # grow the widget until the *map* is 800 x 600 px.
    inner = canvas.mapSettings().outputSize()
    canvas.setFixedSize(
        800 + canvas.width() - inner.width(), 600 + canvas.height() - inner.height()
    )
    QgsApplication.processEvents()
    assert (
        canvas.mapSettings().outputSize().width(),
        canvas.mapSettings().outputSize().height(),
    ) == (800, 600)
    canvas.setDestinationCrs(crs)
    canvas.setExtent(extent)
    QgsApplication.processEvents()
    metric = crs.mapUnits() == Qgis.DistanceUnit.Meters
    if metric and extent.width() == 800 and extent.height() == 600:
        assert canvas.mapUnitsPerPixel() == pytest.approx(1.0)
    return canvas


@pytest.fixture
def real_canvas(qgis_app):
    """`_real_canvas` as a fixture: each window it shows is closed after."""
    shown: list = []

    def make(crs, extent):
        iface = FakeIface()
        shown.append(iface)
        return _real_canvas(iface, crs, extent)

    yield make
    for iface in shown:
        iface.mainWindow().close()
        iface.mainWindow().deleteLater()


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

    `QFileDialog.getSaveFileName` joined the forbidden list below in
    Task 6 (M11), which is the first caller of it anywhere in this
    codebase (`plugin.py`'s "Save cube..." and "Export GeoTIFF..."
    handlers) -- closing the same gap for it, alongside the three
    `getOpen*`/`getExistingDirectory` calls already here, before some
    later test that never meant to trigger a real modal could hang the
    whole suite on it instead of failing fast.

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
        if not hasattr(cls, name):
            return  # PyQt6 has no `exec_`

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
        (QFileDialog, "getSaveFileName"),
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
    from plugin_testing import connect_message_log

    messages: list[str] = []
    disconnect = connect_message_log(lambda msg, tag, level: messages.append(msg))
    yield messages
    disconnect()


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


# ---- M12: a three-grid site -------------------------------------------------

#: Three adjacent 6 x 6 m grids, west to east, in the site's CRS (A's, as
#: the first grid). Lines run along y at 1.5 m spacing, starting 0.8 m in
#: from each grid's west edge and ending 0.7 m short of its east edge, so
#: both sides of every shared edge have a line within the seam width
#: (`SEAM_WIDTH_SPACINGS` x 1.5 m = 2.25 m) and real seams are found.
SITE3_CRS = "EPSG:32616"
SITE3_SPACING = 1.5
SITE3_ORIGINS = {"A": (500.0, 700.0), "B": (506.0, 700.0), "C": (512.0, 700.0)}
SITE3_OFFSETS = (0.8, 2.3, 3.8, 5.3)
SITE3_PRESETS = {
    "p": [
        {"step": "time_zero", "params": {}, "enabled": True},
        {"step": "dewow", "params": {}, "enabled": True},
        {"step": "gain_agc", "params": {}, "enabled": True},
    ],
    # No gain step, so a grid recorded at a different gain still shows it.
    "raw": [
        {"step": "time_zero", "params": {}, "enabled": True},
        {"step": "dewow", "params": {}, "enabled": True},
    ],
}


class Site3:
    """`site3`'s session and the sources it is usually asked for."""

    def __init__(self, session: Any, json_path: Any) -> None:
        self.session = session
        #: Saved, so a test can close the site and open it again.
        self.json_path = json_path

    def keys(self, grid_id: str) -> tuple[str, ...]:
        return tuple(
            self.session.line_key(line)
            for line in self.session.site.lines
            if line.placement.grid_id == grid_id
        )

    def choice(self, grid_id: str, preset: str = "p", transform: str = "amp_envelope") -> Any:
        from nsgeo_qgis.slices_plan import SourceChoice

        return SourceChoice(
            grid_id=grid_id, preset=preset, transform=transform, line_keys=self.keys(grid_id)
        )

    def source(self, grids: str = "ABC", preset: str = "p", transform: str = "amp_envelope") -> Any:
        from nsgeo_qgis.slices_plan import SiteSource

        return SiteSource(
            transform=transform, grids=tuple(self.choice(g, preset, transform) for g in grids)
        )


@pytest.fixture
def site3_factory(qgis_app, tmp_path):
    """Build `site3`, optionally varied.

    `samples` gives a grid's lines fewer samples (a shorter time range at
    the same sample interval); `scale` multiplies a grid's recorded
    amplitudes; `crs` re-declares a grid in another CRS at the same place
    on the ground (its origin is transformed, its azimuth kept);
    `same_data` gives every grid's i-th line the same samples, so grids
    differ only by what `scale` does to them.
    """
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo_qgis.session import SiteSession
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsPointXY,
        QgsProject,
    )
    from tests.synthetic import write_dzt

    built = 0

    def build(
        *,
        samples: dict[str, int] | None = None,
        scale: dict[str, float] | None = None,
        crs: dict[str, str] | None = None,
        same_data: bool = False,
    ) -> Site3:
        nonlocal built
        built += 1
        root = tmp_path / f"site3_{built}"
        root.mkdir()
        session = SiteSession()
        session.new_site(root)
        lines = []
        for grid_id, origin in SITE3_ORIGINS.items():
            grid_crs = (crs or {}).get(grid_id, SITE3_CRS)
            if grid_crs != SITE3_CRS:
                transform = QgsCoordinateTransform(
                    QgsCoordinateReferenceSystem(SITE3_CRS),
                    QgsCoordinateReferenceSystem(grid_crs),
                    QgsProject.instance(),
                )
                moved = transform.transform(QgsPointXY(*origin))
                origin = (moved.x(), moved.y())
            session.add_grid(Grid(grid_id, origin, 0.0, 6.0, 6.0, grid_crs, SITE3_SPACING))
            n_samples = (samples or {}).get(grid_id, 512)
            gain = (scale or {}).get(grid_id, 1.0)
            for i, offset in enumerate(SITE3_OFFSETS):
                seed = f"{'A' if same_data else grid_id}{i}"
                rng = np.random.default_rng(zlib.crc32(seed.encode()))
                data = rng.normal(size=(n_samples, 60)) * 1e6
                data[40:44, :] = 5e6
                folder = root / "raw" / grid_id
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"FILE__00{i + 1}.DZT"
                write_dzt(
                    path,
                    (data * gain).astype(np.int32),
                    traces_per_metre=10.0,
                    range_ns=110.864 * n_samples / 512,
                )
                placement = GridPlacement(grid_id, "y", offset, 0.05, 1, path.stem)
                lines.append(Line.open(path, placement))
        session.add_lines(lines)
        for name, steps in SITE3_PRESETS.items():
            session.site.presets[name] = [dict(s) for s in steps]
        session.save()
        return Site3(session, session.json_path)

    return build


@pytest.fixture
def site3(site3_factory):
    """Three adjacent 6 x 6 m synthetic grids, A, B and C, four lines each."""
    return site3_factory()
