"""Trace stack: average each trace with its neighbours along the line.

Random noise differs from trace to trace and a reflector does not, so a short
centred mean lowers the noise and keeps the reflector. The trace count stays
the same, so the Difference view and every later step work across it.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing._util import running_mean
from nsgeo.processing.base import ParamSpec, Radargram, register


@register
class TraceStack:
    """Replace each trace by the mean of itself and its neighbours.

    The window is centred and shrinks at the line's ends, which average what
    is there. A window longer than the line is capped at the line's length.
    """

    name = "trace_stack"
    title = "Trace stack"
    group = "Filters"
    order = 3

    def __init__(self, window_traces: int = 3) -> None:
        self.window_traces = window_traces

    @property
    def params(self) -> dict[str, Any]:
        return {"window_traces": self.window_traces}

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(
                name="window_traces",
                kind="int",
                label="Window",
                default=3,
                unit="traces",
                min=1,
                help=(
                    "Averages each trace with its neighbours: this many traces in all, "
                    "centred on it. 1 leaves the line unchanged."
                ),
            ),
        )

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=running_mean(rg.data, self.window_traces, axis=1))
