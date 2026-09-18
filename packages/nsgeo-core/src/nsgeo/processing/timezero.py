"""Time-zero correction: crop rows above the first arrival."""

from __future__ import annotations

from typing import Any

import numpy as np

from nsgeo.processing.base import ParamSpec, Radargram, register


@register
class TimeZero:
    name = "time_zero"

    def __init__(self, mode: str = "first_break", sample: int = 0, threshold: float = 0.2) -> None:
        self.mode = mode
        self.sample = sample
        self.threshold = threshold

    @property
    def params(self) -> dict[str, Any]:
        return {"mode": self.mode, "sample": self.sample, "threshold": self.threshold}

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(
                name="mode",
                kind="choice",
                label="Mode",
                default="first_break",
                choices=("first_break", "sample"),
                help="Pick the first arrival automatically, or crop at a fixed sample.",
            ),
            ParamSpec(
                name="sample",
                kind="int",
                label="Sample",
                default=0,
                min=0,
                help="Used when mode is 'sample'.",
            ),
            ParamSpec(
                name="threshold",
                kind="float",
                label="Threshold",
                default=0.2,
                min=0.0,
                max=1.0,
                help="Fraction of the peak mean amplitude.",
            ),
        )

    def _pick(self, rg: Radargram) -> int:
        if self.mode == "sample":
            return int(self.sample)
        if self.mode == "first_break":
            # Mean absolute amplitude across traces. Averaging first means
            # leading all-zero traces (recording before the cart moves) dilute
            # rather than dominate the pick.
            envelope = np.abs(rg.data).mean(axis=1)
            peak = envelope.max()
            if peak <= 0:
                return 0
            above = np.flatnonzero(envelope >= self.threshold * peak)
            return int(above[0]) if above.size else 0
        raise ValueError(f"unknown time_zero mode {self.mode!r}; use 'sample' or 'first_break'")

    def apply(self, rg: Radargram) -> Radargram:
        k = self._pick(rg)
        if k <= 0:
            return rg
        if k >= rg.n_samples:
            raise ValueError(
                f"time_zero at sample {k} would leave no samples (radargram has {rg.n_samples})"
            )
        return rg.replace(data=rg.data[k:, :].copy(), t0_ns=rg.t0_ns + k * rg.dt_ns)
