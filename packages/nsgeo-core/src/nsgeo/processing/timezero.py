"""Time-zero correction: the row it lands on reads 0 ns.

Rows above the pick are cropped and the clock is relabelled: `t0_ns` becomes 0
and `zero_ns` records the radar-clock time of the pick, so every kept row keeps
its radar time.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np

from nsgeo.processing.base import ParamSpec, Radargram, register

TIME_BASE_TIME_ZERO = "time_zero"
TIME_BASE_RADAR = "radar"


def first_break_row(rg: Radargram, threshold: float = 0.2) -> int:
    """Row of the first arrival: the first where the trace-mean absolute
    amplitude reaches `threshold` of its peak. 0 when there is no signal.

    NaN and inf are left out of each row's mean, so one bad sample does not
    move the pick (#42)."""
    row = _first_break_or_none(rg, threshold)
    return 0 if row is None else row


def _first_break_or_none(rg: Radargram, threshold: float) -> int | None:
    """`first_break_row`, but None when there is no signal: no row holds a
    finite sample, or every finite sample is zero."""
    # Averaging across traces first means leading all-zero traces (recording
    # before the cart moves) dilute rather than dominate the pick. Each row's
    # mean is over its finite samples only: one NaN used to make the peak NaN
    # and cancel the crop, and one inf made its own row the peak.
    finite = np.isfinite(rg.data)
    total = np.where(finite, np.abs(rg.data), 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        envelope = total / finite.sum(axis=1)  # NaN on a row with no finite sample
    usable = np.isfinite(envelope)
    if not usable.any():
        return None
    peak = envelope[usable].max()
    if peak <= 0:
        return None
    above = np.flatnonzero(usable & (envelope >= threshold * peak))
    return int(above[0]) if above.size else 0


def _why_no_first_arrival(data: np.ndarray) -> str:
    finite = np.isfinite(data)
    if finite.all():
        return "every sample on this line is zero"
    if not finite.any():
        return "no sample on this line is a finite number"
    return "every sample on this line is zero or not a finite number"


def first_break_ns(rg: Radargram, threshold: float = 0.2) -> float:
    """Time of the first arrival (the row `first_break_row` picks) on `rg`'s own
    axis: radar time only when `rg.zero_ns == 0`."""
    return float(rg.t0_ns + first_break_row(rg, threshold) * rg.dt_ns)


def sets_time_zero(steps: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any entry is an enabled `time_zero` (a missing `enabled` counts
    as enabled)."""
    return any(d.get("step") == "time_zero" and d.get("enabled", True) for d in steps)


def time_base_of(steps: Iterable[Mapping[str, Any]]) -> str:
    return TIME_BASE_TIME_ZERO if sets_time_zero(steps) else TIME_BASE_RADAR


@register
class TimeZero:
    name = "time_zero"
    title = "Time zero"
    group = "Time"
    order = 1

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
                help=(
                    "Find the first arrival automatically, or give the row. That row becomes 0 ns."
                ),
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
            row = _first_break_or_none(rg, self.threshold)
            if row is None:
                # Cropping nothing would pass silently for a time zero.
                raise ValueError(
                    f"Time zero found no first arrival: {_why_no_first_arrival(rg.data)}."
                )
            return row
        raise ValueError(f"unknown time_zero mode {self.mode!r}; use 'sample' or 'first_break'")

    def apply(self, rg: Radargram) -> Radargram:
        k = self._pick(rg)
        if k >= rg.n_samples:
            raise ValueError(
                f"time_zero at sample {k} would leave no samples (radargram has {rg.n_samples})"
            )
        return rg.replace(
            data=rg.data[k:, :].copy(),
            t0_ns=0.0,
            zero_ns=rg.zero_ns + rg.t0_ns + k * rg.dt_ns,
            zero_set=True,
        )
