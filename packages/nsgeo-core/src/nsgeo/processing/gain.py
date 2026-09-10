"""Gain steps.

Three separate steps rather than one with modes: they take different
parameters, and more than one may legitimately be applied at once.

Note the distinction from display gain, which lives in the front end: clip
percentile and colour range change how amplitude maps to colour, not the data,
and are never recorded in a stack.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from nsgeo.processing._util import running_mean
from nsgeo.processing.base import Radargram, register


@register
class GainAgc:
    """Automatic gain control: normalise by a running RMS in time."""

    name = "gain_agc"

    def __init__(self, window_ns: float = 20.0, target: float = 1.0, eps: float = 1e-12) -> None:
        self.window_ns = window_ns
        self.target = target
        self.eps = eps

    @property
    def params(self) -> dict[str, Any]:
        return {"window_ns": self.window_ns, "target": self.target, "eps": self.eps}

    def apply(self, rg: Radargram) -> Radargram:
        window = int(round(self.window_ns / rg.dt_ns))
        if window < 1:
            raise ValueError(f"window_ns={self.window_ns} is shorter than one sample")
        rms = np.sqrt(running_mean(np.asarray(rg.data, dtype=float) ** 2, window, axis=0))
        # eps guards all-zero traces, which are normal at the start of a line.
        return rg.replace(data=rg.data * (self.target / np.maximum(rms, self.eps)))


@register
class GainParametric:
    """Exponential or power-law gain as a function of two-way time."""

    name = "gain_parametric"

    def __init__(
        self, mode: str = "exponential", alpha: float = 0.05, exponent: float = 1.0
    ) -> None:
        self.mode = mode
        self.alpha = alpha
        self.exponent = exponent

    @property
    def params(self) -> dict[str, Any]:
        return {"mode": self.mode, "alpha": self.alpha, "exponent": self.exponent}

    def apply(self, rg: Radargram) -> Radargram:
        # Elapsed time from the first sample, so gain is 1.0 at the top
        # regardless of what t0 happens to be.
        elapsed = np.arange(rg.n_samples, dtype=float) * rg.dt_ns
        if self.mode == "exponential":
            g = np.exp(self.alpha * elapsed)
        elif self.mode == "power":
            g = (1.0 + elapsed) ** self.exponent
        else:
            raise ValueError(
                f"unknown gain_parametric mode {self.mode!r}; use 'exponential' or 'power'"
            )
        return rg.replace(data=rg.data * g[:, None])


@register
class GainCurve:
    """Manual gain curve: draggable (time_ns, dB) control points.

    Applied as 10 ** (dB / 20). One broadcast multiply, so dragging a control
    point is interactive at full resolution when this is the last step.
    """

    name = "gain_curve"

    def __init__(self, points: Sequence[Sequence[float]]) -> None:
        self.points: list[list[float]] = [[float(t), float(db)] for t, db in points]

    @property
    def params(self) -> dict[str, Any]:
        return {"points": [list(p) for p in self.points]}

    def apply(self, rg: Radargram) -> Radargram:
        if len(self.points) < 2:
            raise ValueError("gain_curve needs at least two control points")
        pts = sorted(self.points, key=lambda p: p[0])
        times = np.array([p[0] for p in pts], dtype=float)
        decibels = np.array([p[1] for p in pts], dtype=float)
        # np.interp holds the end values outside the control range, which is
        # the behaviour a user dragging a curve expects.
        # Absolute two-way time (times_ns includes t0), unlike gain_parametric's elapsed time:
        # control points are placed on the same axis the profile viewer draws.
        db = np.interp(rg.times_ns(), times, decibels)
        return rg.replace(data=rg.data * (10.0 ** (db / 20.0))[:, None])
