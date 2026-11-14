"""Folding sections of the Slices dock, remembered across sessions (#157 item 6).

Fold state is the user's, so it is kept under one settings group and read and
written only through `fold_settings()`, which tests replace.
"""

from __future__ import annotations

from collections.abc import Sequence

from qgis.core import QgsSettings
from qgis.gui import QgsCollapsibleGroupBox
from qgis.PyQt.QtCore import QEvent, QObject, QSettings, Qt

from nsgeo_qgis.log import log as _log

FOLD_GROUP = "nsgeo/slices/folded"


def fold_settings() -> QSettings:
    """The only door to fold state; the test conftest swaps it for a temp file."""
    return QgsSettings()


class _ShowSync(QObject):
    """Redraws a box that was folded or unfolded while it was hidden.

    QGIS stores the flag of a hidden box but draws nothing, and re-applies it
    only on the box's first show. So a box synced while hidden is marked, and
    on its next Show its own flag is applied again.
    """

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.stale: set[int] = set()

    def eventFilter(self, obj, event):  # noqa: N802 -- Qt override
        try:
            if event.type() == QEvent.Type.Show and id(obj) in self.stale:
                self.stale.discard(id(obj))
                scroll = obj.scrollOnExpand()
                obj.setScrollOnExpand(False)
                try:
                    obj.setCollapsed(obj.isCollapsed())
                finally:
                    obj.setScrollOnExpand(scroll)
        except Exception as exc:  # noqa: BLE001 -- an event filter
            _log(f"could not redraw a folded section: {exc}")
        return False


def remember_folds(name: str, boxes: Sequence[QgsCollapsibleGroupBox]) -> None:
    """Fold `boxes` as one, from and into `FOLD_GROUP/name` (default unfolded).

    QGIS's own saving is turned off: it keys on the object name and the
    parent chain, which two panels in one dock would share.
    """
    key = f"{FOLD_GROUP}/{name}"
    busy = [False]
    sync = _ShowSync(boxes[0])
    for box in boxes:
        box.setSaveCollapsedState(False)
        box.setSaveCheckedState(False)
        # A header is not a Tab stop of its own; the collapse button keeps its
        # own Tab focus.
        box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        box.installEventFilter(sync)
    try:
        collapsed = bool(fold_settings().value(key, False, type=bool))
    except Exception as exc:  # noqa: BLE001 -- a bad settings store must not stop the dock
        _log(f"could not read the fold state {key}: {exc}")
        collapsed = False
    for box in boxes:
        box.setCollapsed(collapsed)

    def on_changed(is_collapsed: bool, source: QgsCollapsibleGroupBox) -> None:
        if busy[0]:
            return
        busy[0] = True
        try:
            for other in boxes:
                if other is not source and other.isCollapsed() != is_collapsed:
                    other.setCollapsed(is_collapsed)
                    if not other.isVisible():
                        sync.stale.add(id(other))
            fold_settings().setValue(key, bool(is_collapsed))
        except Exception as exc:  # noqa: BLE001 -- a slot on collapsedStateChanged
            _log(f"could not keep the fold state {key}: {exc}")
        finally:
            busy[0] = False

    for box in boxes:
        box.collapsedStateChanged.connect(lambda state, source=box: on_changed(state, source))
