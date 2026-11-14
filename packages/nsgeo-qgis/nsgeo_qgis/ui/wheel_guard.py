"""The wheel rule for boxes inside a scrolling panel (spec §2, #177, #176).

A box in a scroll area takes the wheel only once the user has clicked it.
Over an unfocused box a notch scrolls the panel; scrolling the panel by hand
lets go of a focused box. This is the `TimeSpinBox.wheelEvent` rule of
`param_form.py`, applied from outside so any spin box or combo can take it
with one call.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtWidgets import QAbstractScrollArea, QWidget

from nsgeo_qgis.log import log as _log


class _WheelFilter(QObject):
    def eventFilter(self, obj, event):  # noqa: N802 -- Qt override
        try:
            if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
                # Ignored and swallowed here: Qt hands an ignored wheel event
                # on to the parent, so the scroll area scrolls.
                event.ignore()
                return True
        except Exception as exc:  # noqa: BLE001 -- a Qt event filter
            _log(f"wheel guard failed: {exc!r}")
        return False


def guard_wheel(widget: QWidget, scroll_area: QAbstractScrollArea) -> None:
    """Make `widget` take the wheel only while focused, and drop its focus
    to `scroll_area` when the user scrolls that area.

    `StrongFocus` is needed because the default `WheelFocus` grants focus
    before the wheel is delivered. A scroll set in code, a range clamp or
    `ensureWidgetVisible` fires no `actionTriggered`, so it keeps focus.
    """
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.installEventFilter(_WheelFilter(widget))

    def _let_go(_action: int) -> None:
        try:
            if widget.hasFocus():
                scroll_area.setFocus()
        except Exception as exc:  # noqa: BLE001 -- a Qt slot
            _log(f"wheel guard failed: {exc!r}")

    scroll_area.verticalScrollBar().actionTriggered.connect(_let_go)
