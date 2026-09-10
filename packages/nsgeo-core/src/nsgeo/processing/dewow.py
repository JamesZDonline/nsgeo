"""Dewow: remove low-frequency drift by subtracting a running mean in time."""

from __future__ import annotations

from typing import Any

from nsgeo.processing._util import running_mean
from nsgeo.processing.base import Radargram, register


@register
class Dewow:
    name = "dewow"

    def __init__(self, window_ns: float = 4.0) -> None:
        self.window_ns = window_ns

    @property
    def params(self) -> dict[str, Any]:
        return {"window_ns": self.window_ns}

    def apply(self, rg: Radargram) -> Radargram:
        window = int(round(self.window_ns / rg.dt_ns))
        if window < 1:
            raise ValueError(
                f"window_ns={self.window_ns} is shorter than one sample "
                f"({rg.dt_ns} ns); nothing to remove"
            )
        return rg.replace(data=rg.data - running_mean(rg.data, window, axis=0))
