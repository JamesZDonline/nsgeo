"""The few places Qt5 and Qt6 differ for this plugin.

Everything else is handled by importing through `qgis.PyQt` and using
scoped enums. Keep this file tiny; if it grows, the design is leaking.
"""

from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import QPointF


def event_pos(event: Any) -> QPointF:
    """Local position of a mouse or wheel event on both Qt majors."""
    if hasattr(event, "position"):
        return QPointF(event.position())
    return QPointF(event.pos())
