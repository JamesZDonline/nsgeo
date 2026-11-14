"""Folding sections of the Slices dock, remembered across sessions (#157 item 6).

Fold state is the user's, so it is kept under one settings group and read and
written only through `fold_settings()`, which tests replace.
"""

from __future__ import annotations

from collections.abc import Sequence

from qgis.core import QgsSettings
from qgis.gui import QgsCollapsibleGroupBox
from qgis.PyQt.QtCore import QSettings

from nsgeo_qgis.log import log as _log

FOLD_GROUP = "nsgeo/slices/folded"


def fold_settings() -> QSettings:
    """The only door to fold state; the test conftest swaps it for a temp file."""
    return QgsSettings()


def remember_folds(name: str, boxes: Sequence[QgsCollapsibleGroupBox]) -> None:
    """Fold `boxes` as one, from and into `FOLD_GROUP/name` (default unfolded).

    QGIS's own saving is turned off: it keys on the object name and the
    parent chain, which two panels in one dock would share.
    """
    key = f"{FOLD_GROUP}/{name}"
    busy = [False]
    for box in boxes:
        box.setSaveCollapsedState(False)
        box.setSaveCheckedState(False)
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
            fold_settings().setValue(key, bool(is_collapsed))
            for other in boxes:
                if other is not source and other.isCollapsed() != is_collapsed:
                    other.setCollapsed(is_collapsed)
        except Exception as exc:  # noqa: BLE001 -- a slot on collapsedStateChanged
            _log(f"could not keep the fold state {key}: {exc}")
        finally:
            busy[0] = False

    for box in boxes:
        box.collapsedStateChanged.connect(lambda state, source=box: on_changed(state, source))
