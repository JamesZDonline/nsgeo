"""Time cutoff: hide every sample at or after a two-way time.

The late-time counterpart of time-zero. Time-zero crops the top of the record
and moves `t0_ns`; this crops the bottom and leaves `t0_ns` alone, because the
first kept sample is still the first sample.
"""

from __future__ import annotations

import math
from typing import Any

from nsgeo.processing.base import REQUIRED, ParamSpec, Radargram, register


@register
class TimeCutoff:
    name = "time_cutoff"

    def __init__(self, end_ns: float) -> None:
        end = float(end_ns)
        # A NaN would fall through every comparison in `apply` and reach
        # math.ceil; an infinity would be a silent no-op or a crash there.
        # Neither is a time, so refuse at construction, where build_step and
        # a preset load both pass through.
        if not math.isfinite(end):
            raise ValueError(f"time_cutoff end_ns must be finite, got {end_ns!r}")
        self.end_ns = end

    @property
    def params(self) -> dict[str, Any]:
        return {"end_ns": self.end_ns}

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(
                name="end_ns",
                # "time" (not "float") is what tells a front end this value
                # lives on the radargram's own time axis and can be dragged
                # there; the step's name plays no part in that.
                kind="time",
                label="Cutoff",
                default=REQUIRED,
                unit="ns",
                help="Hide every sample at or after this two-way time. "
                "Drag the line on the profile to set it.",
            ),
        )

    def apply(self, rg: Radargram) -> Radargram:
        # The tolerance is a billionth of a sample. A boundary snapped to the
        # sample grid is t0 + m*dt, which is inexact in binary and can land a
        # hair above m*dt after the subtraction; without the slack ceil would
        # keep m + 1 rows and the snapped sample would survive.
        m = math.ceil((self.end_ns - rg.t0_ns) / rg.dt_ns - 1e-9)
        if m >= rg.n_samples:
            return rg
        if m <= 0:
            raise ValueError(
                f"time_cutoff at {self.end_ns:g} ns would leave no samples "
                f"(the record starts at {rg.t0_ns:g} ns)"
            )
        return rg.replace(data=rg.data[:m, :].copy())
