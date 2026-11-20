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


def without_layer_flag(layer: Any, flag: Any) -> None:
    """Clear one `QgsMapLayer.LayerFlag` on a layer, on both QGIS majors.

    QGIS 4's `LayerFlag` is an `IntEnum`, so `layer.flags() & ~flag` is a plain
    int and `setFlags` refuses it. Going through int and back to the enum is
    accepted by QGIS 3 (a `LayerFlag` converts to `LayerFlags`) and by QGIS 4.
    """
    cls = type(flag)
    layer.setFlags(cls(int(layer.flags()) & ~int(flag)))
