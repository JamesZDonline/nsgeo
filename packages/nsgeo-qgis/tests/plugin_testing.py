"""Helpers shared by both plugin test tiers. Imported as `plugin_testing`."""

from __future__ import annotations

import threading
import time
import zlib
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pytest

CORE_DIR = Path(__file__).resolve().parent.parent.parent / "nsgeo-core"
LOCAL_DATA = CORE_DIR / "tests" / "data" / "local"
REAL_DZT = (
    sorted(p for p in LOCAL_DATA.rglob("*") if p.suffix.lower() == ".dzt")
    if LOCAL_DATA.exists()
    else []
)

needs_real_data = pytest.mark.skipif(not REAL_DZT, reason="no real DZT files in tests/data/local")


def synthetic_dzt(folder: Path, name: str, n_traces: int = 60, **kw) -> Path:
    """A small synthetic DZT with a visible pattern, written into `folder`."""
    from tests.synthetic import write_dzt

    folder.mkdir(parents=True, exist_ok=True)
    # crc32, not hash(): str hashing is salted per-process (PYTHONHASHSEED),
    # so the same `name` would otherwise seed different data every run.
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    data = (rng.normal(size=(512, n_traces)) * 1e6).astype(np.int32)
    data[40:44, :] = 5_000_000  # a flat band, so background removal has something to remove
    path = folder / name
    write_dzt(path, data, **kw)
    return path


def send_move_while_pressed(widget: Any, local_pos: Any, held_button: Any = None) -> None:
    """A mouse move sent *while a button is logically held* (between a
    `QTest.mousePress` and the matching `mouseRelease`) is not reliably
    delivered by `QTest.mouseMove` -- confirmed directly in this
    environment (offscreen QPA): the identical `QTest.mousePress(...)` +
    `QTest.mouseMove(...)` sequence a naive drag test would use never
    invokes `mouseMoveEvent` at all while a button is still down, though
    the exact same `QTest.mouseMove` call works fine with no button held.
    Building and sending the `QMouseEvent` directly bypasses `QTest`'s
    cursor-warp-based simulation and reaches the widget's real
    `mouseMoveEvent` every time, which is what a genuine OS-level drag
    actually delivers.

    Used by both `test_plugin_profile_view.py` (a drag-select) and
    `test_plugin_gain_strip.py` (a control-point drag) -- kept here, not
    duplicated in each, so the one subtle Qt workaround both rely on
    cannot drift between two copies. Qt-only imports are local to this
    function (not at module level): this module is also imported by the
    pure tier's `test_pure_lookup.py`, which runs with no QGIS/PyQt
    installed at all.

    `held_button` defaults to the left button; a Qt enum member cannot be
    a module-level-evaluated default (it would need `qgis.PyQt` imported
    at module level, which the pure tier cannot do), so `None` is resolved
    to it inside the function instead.
    """
    from qgis.PyQt.QtCore import QEvent, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent
    from qgis.PyQt.QtWidgets import QApplication

    button = held_button if held_button is not None else Qt.MouseButton.LeftButton
    local = QPointF(local_pos)
    glob = QPointF(widget.mapToGlobal(local_pos))
    ev = QMouseEvent(
        QEvent.Type.MouseMove,
        local,
        glob,
        Qt.MouseButton.NoButton,
        button,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, ev)


def send_hover(widget: Any, local_pos: Any) -> None:
    """A buttonless mouse move, sent directly as a `QMouseEvent`.

    `QTest.mouseMove` keeps cursor state that, on Qt 6, leaks across test
    files and can swallow a later hover (spec M9 3.2c); this reaches the
    widget's `mouseMoveEvent` every time. Qt imports are local, as above.
    """
    from qgis.PyQt.QtCore import Qt

    send_move_while_pressed(widget, local_pos, held_button=Qt.MouseButton.NoButton)


def connect_message_log(slot: Callable[[str, str, int], None]) -> Callable[[], None]:
    """Connect `slot(message, tag, int(level))` to the app's `QgsMessageLog`.

    QGIS 4 dropped the three-argument `messageReceived` for
    `messageReceivedWithFormat` (which adds a text-format argument, dropped
    here); QGIS 3 only has `messageReceived`. Returns the matching
    disconnect.
    """
    from qgis.core import QgsApplication

    log = QgsApplication.messageLog()

    def _on_message(msg: str, tag: str, level: Any, *_format: Any) -> None:
        slot(msg, tag, int(level))

    if hasattr(log, "messageReceivedWithFormat"):
        signal = log.messageReceivedWithFormat
    else:
        signal = log.messageReceived
    signal.connect(_on_message)
    return lambda: signal.disconnect(_on_message)


def send_double_click(widget: Any, local_pos: Any, button: Any = None) -> None:
    """`QTest.mouseDClick` is not just unreliable the way plain
    `QTest.mouseMove` is (see `send_move_while_pressed` above) -- verified
    directly, it corrupts state in this offscreen-QPA environment that
    outlives both the widget and the test: a `QTest.mouseDClick` call in
    one test reproducibly blocked a plain, buttonless `QTest.mouseMove` on
    a *different* widget in the *next* test, in a different file, with
    `mouseMoveEvent` silently never firing; neither `hide()`/
    `deleteLater()` on the first widget nor a forced extra
    `QMouseEvent(MouseButtonRelease, ...)` afterwards cleared it (see
    `tests/qgis/conftest.py`'s `_no_unhandled_modals`, which forbids
    `QTest.mouseDClick` in this tier entirely and points here instead).

    Replacing `QTest.mouseDClick` with the same four events a real
    double-click actually delivers (press, release, dblclick, release --
    Qt turns the second physical press into a `MouseButtonDblClick`, not a
    second `MouseButtonPress`), sent directly via `QApplication.sendEvent`
    the same way `send_move_while_pressed` bypasses `QTest`, reaches
    `mouseDoubleClickEvent` correctly and was confirmed, in the same
    minimal reproduction, to leave no such trace behind.
    """
    from qgis.PyQt.QtCore import QEvent, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent
    from qgis.PyQt.QtWidgets import QApplication

    btn = button if button is not None else Qt.MouseButton.LeftButton
    local = QPointF(local_pos)
    glob = QPointF(widget.mapToGlobal(local_pos))

    def send(typ: QEvent.Type, buttons: Qt.MouseButton) -> None:
        QApplication.sendEvent(
            widget,
            QMouseEvent(typ, local, glob, btn, buttons, Qt.KeyboardModifier.NoModifier),
        )

    send(QEvent.Type.MouseButtonPress, btn)
    send(QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)
    send(QEvent.Type.MouseButtonDblClick, btn)
    send(QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)


class LoadCounter:
    """`Line.load`, counted -- and optionally slowed -- under a lock.

    M11's `test_two_different_choices_back_to_back_never_run_concurrently`
    pattern: the sleep widens the few milliseconds a real read holds a
    worker thread into a window long enough that a counter under a lock
    catches two preparations overlapping deterministically, which is
    stronger evidence than timing and safer than waiting for a segfault.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch, delay: float = 0.0) -> None:
        from nsgeo.model.survey import Line

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
    """Run the event loop until `predicate()` holds, or time out. qgis tier only."""
    from qgis.PyQt.QtCore import QCoreApplication, QEventLoop

    deadline = time.monotonic() + timeout_ms / 1000.0
    while not predicate():
        if time.monotonic() > deadline:
            return False
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 5)
        time.sleep(0.002)
    return True


# ---- driving a map tool (#63) -------------------------------------------------


def map_pixel(canvas: Any, x: float, y: float) -> Any:
    """The canvas pixel (a QPoint) showing map point (x, y), in the canvas CRS."""
    from qgis.core import QgsPointXY
    from qgis.PyQt.QtCore import QPoint

    p = canvas.getCoordinateTransform().transform(QgsPointXY(x, y))
    return QPoint(round(p.x()), round(p.y()))


def send_map_mouse(tool: Any, kind: str, at: Any, button: Any = None) -> Any:
    """Drive a QgsMapTool the way its canvas does, and return the event.

    `kind` is "move" or "release"; `at` is a pixel (a QPoint) or a map point
    as an (x, y) pair in the canvas CRS. The QgsMapMouseEvent is built at
    that pixel, so its map point is the canvas's own reading of the pixel,
    and handed straight to the tool's `canvasMoveEvent`/`canvasReleaseEvent`
    (spec plan, "Shared test geometry"). A release defaults to the left
    button. Qt imports are local: the pure tier imports this module too.
    """
    from qgis.gui import QgsMapMouseEvent
    from qgis.PyQt.QtCore import QEvent, QPoint, Qt

    canvas = tool.canvas()
    pixel = at if isinstance(at, QPoint) else map_pixel(canvas, *at)
    if kind == "move":
        event = QgsMapMouseEvent(canvas, QEvent.Type.MouseMove, pixel, Qt.MouseButton.NoButton)
        tool.canvasMoveEvent(event)
    elif kind == "release":
        btn = button if button is not None else Qt.MouseButton.LeftButton
        event = QgsMapMouseEvent(canvas, QEvent.Type.MouseButtonRelease, pixel, btn)
        tool.canvasReleaseEvent(event)
    else:
        raise ValueError(f"kind must be 'move' or 'release', not {kind!r}")
    return event


def send_map_key(tool: Any, key: Any) -> Any:
    """A key press handed straight to a map tool's `keyPressEvent`; returns the
    event. QgsMapCanvas hands a key press over already *accepted* (see
    pick_tool.py's module docstring), so this does too."""
    from qgis.PyQt.QtCore import QEvent, Qt
    from qgis.PyQt.QtGui import QKeyEvent

    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    event.accept()
    tool.keyPressEvent(event)
    return event


def named_layer(kind: str, name: str, features: dict[str, Any], crs: str = "EPSG:32616") -> Any:
    """A memory layer with a `name` field shown as its display expression.

    `kind` is "Point" or "Polygon"; `features` maps each feature's name to
    an (x, y) pair for a point or a list of (x, y) ring vertices for a
    polygon. Features are added in the dict's order.
    """
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

    layer = QgsVectorLayer(f"{kind}?crs={crs}&field=name:string", name, "memory")
    made = []
    for label, shape in features.items():
        f = QgsFeature(layer.fields())
        f.setAttribute("name", label)
        if kind == "Point":
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*shape)))
        else:
            f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(*p) for p in shape]]))
        made.append(f)
    layer.dataProvider().addFeatures(made)
    layer.setDisplayExpression('"name"')
    return layer


def feature_id(layer: Any, name: str) -> int:
    """The id of `layer`'s feature called `name`."""
    return next(f.id() for f in layer.getFeatures() if f["name"] == name)
