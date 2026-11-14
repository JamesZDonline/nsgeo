"""Background removal: separating horizontal banding from real reflectors.

Three methods because they fail differently. Full-line mean is the cheapest
and fails when the background drifts along the line. Sliding handles drift but
can eat genuine flat-lying features if the window is short. SVD removes
banding that is not perfectly flat, at higher cost.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from nsgeo.processing._util import refuse_non_finite, running_mean
from nsgeo.processing.base import ParamSpec, Radargram, register


@register
class BackgroundMean:
    """Subtract the mean trace over the whole line.

    Each row's mean is over its finite samples, so one NaN or inf damages only
    itself rather than its whole row. A row with no finite sample subtracts
    NaN, which touches only samples that were already bad.
    """

    name = "background_mean"
    title = "Background removal (mean)"
    group = "Background"
    order = 1

    @property
    def params(self) -> dict[str, Any]:
        return {}

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return ()

    def apply(self, rg: Radargram) -> Radargram:
        finite = np.isfinite(rg.data)
        total = np.where(finite, rg.data, 0.0).sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = total / finite.sum(axis=1, keepdims=True)
        return rg.replace(data=rg.data - mean)


@register
class BackgroundSliding:
    """Subtract a running mean along the trace axis."""

    name = "background_sliding"
    title = "Background removal (sliding)"
    group = "Background"
    order = 2

    def __init__(self, window_traces: int = 200) -> None:
        self.window_traces = window_traces

    @property
    def params(self) -> dict[str, Any]:
        return {"window_traces": self.window_traces}

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(
                name="window_traces", kind="int", label="Window", default=200, unit="traces", min=2
            ),
        )

    def apply(self, rg: Radargram) -> Radargram:
        if self.window_traces < 2:
            raise ValueError(f"window_traces must be >= 2, got {self.window_traces}")
        return rg.replace(data=rg.data - running_mean(rg.data, self.window_traces, axis=1))


@register
class BackgroundSvd:
    """Remove leading eigenimages.

    Banding that is strong and repeats across traces concentrates in the first
    few singular values, so dropping them removes it without assuming it is
    perfectly flat.
    """

    name = "background_svd"
    title = "Remove leading components (SVD)"
    group = "Background"
    order = 3

    def __init__(self, n_components: int = 1) -> None:
        self.n_components = n_components

    @property
    def params(self) -> dict[str, Any]:
        return {"n_components": self.n_components}

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(
                name="n_components",
                kind="int",
                label="Components removed",
                default=1,
                min=0,
                max=20,
            ),
        )

    def apply(self, rg: Radargram) -> Radargram:
        n = self.n_components
        if n < 0:
            raise ValueError(f"n_components must be >= 0, got {n}")
        if n == 0:
            return rg
        refuse_non_finite(rg.data, "the decomposition cannot run on them")
        rank = min(rg.n_samples, rg.n_traces)
        if n > rank:
            raise ValueError(f"n_components={n} exceeds the rank of this radargram ({rank})")
        u, s, vt = np.linalg.svd(rg.data, full_matrices=False)
        s = s.copy()
        s[:n] = 0.0
        return rg.replace(data=(u * s) @ vt)
