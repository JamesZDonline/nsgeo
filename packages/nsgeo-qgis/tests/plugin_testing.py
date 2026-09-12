"""Helpers shared by both plugin test tiers. Imported as `plugin_testing`."""

from __future__ import annotations

import zlib
from pathlib import Path
from typing import Any

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
