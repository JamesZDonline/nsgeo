"""Layered velocity model: interval velocities bounded in two-way time.

Boundaries are in time because that is what is visible on a radargram; depth
is the derived quantity. A constant velocity is the one-layer case, which is
all the v1 UI exposes, but the shape is a list from the start so adding
layers later changes no file format.

Depth is measured from time zero. Times before zero (a real SIR-4000 file
starts at -11.09 ns) give negative depths, which is correct.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    # Only for type checking: `from __future__ import annotations` makes every
    # annotation in this module a string, so this import runs no code and
    # cannot join the runtime cycle that a real import would (both
    # `geometry.grid` and `model.survey` import `VelocityModel` from here).
    from nsgeo.geometry.grid import Grid
    from nsgeo.model.survey import Line

C_M_PER_NS = 0.299792458


@dataclass(frozen=True)
class VelocityModel:
    layers: tuple[tuple[float, float], ...]  # (top_ns, v_m_per_ns), tops increasing, first 0.0

    def __post_init__(self) -> None:
        if not self.layers:
            raise ValueError("a velocity model needs at least one layer")
        layers = tuple((float(t), float(v)) for t, v in self.layers)
        object.__setattr__(self, "layers", layers)
        tops = [t for t, _ in layers]
        if any(not math.isfinite(t) for t in tops):
            raise ValueError(f"layer tops must be finite, got {tops}")
        if tops[0] != 0.0:
            raise ValueError(f"the first layer must start at 0 ns, got {tops[0]}")
        if any(b <= a for a, b in zip(tops, tops[1:])):
            raise ValueError(f"layer tops must strictly increase, got {tops}")
        if any(not (math.isfinite(v) and v > 0.0) for _, v in layers):
            raise ValueError("interval velocities must be positive and finite")

    @classmethod
    def constant(cls, v_m_per_ns: float) -> VelocityModel:
        return cls(layers=((0.0, v_m_per_ns),))

    @classmethod
    def from_dielectric(cls, epsr: float) -> VelocityModel:
        if not epsr > 0.0:
            raise ValueError(f"relative dielectric permittivity must be positive, got {epsr}")
        return cls.constant(C_M_PER_NS / math.sqrt(epsr))

    @property
    def is_constant(self) -> bool:
        return len(self.layers) == 1

    @property
    def surface_velocity(self) -> float:
        return self.layers[0][1]

    def _arrays(self) -> tuple[np.ndarray, np.ndarray]:
        tops = np.array([t for t, _ in self.layers], dtype=float)
        vs = np.array([v for _, v in self.layers], dtype=float)
        return tops, vs

    def _layer_index(self, tops: np.ndarray, times_ns: np.ndarray) -> np.ndarray:
        # Times below the first top belong to the first layer.
        return np.clip(np.searchsorted(tops, times_ns, side="right") - 1, 0, len(tops) - 1)

    def velocity_at(self, times_ns: np.ndarray) -> np.ndarray:
        t = np.asarray(times_ns, dtype=float)
        tops, vs = self._arrays()
        resolved = vs[self._layer_index(tops, t)]
        # searchsorted sorts NaN to the end, which would otherwise resolve an
        # invalid time to the last layer's velocity as if it were a real,
        # very late time. Non-finite times carry no layer membership, so they
        # propagate as NaN instead of a plausible-looking real velocity.
        return np.where(np.isfinite(t), resolved, np.nan)

    def depth_at(self, times_ns: np.ndarray) -> np.ndarray:
        """Depth in metres: cumulative integral of v/2 over two-way time."""
        t = np.asarray(times_ns, dtype=float)
        tops, vs = self._arrays()
        depth_at_tops = np.concatenate([[0.0], np.cumsum(vs[:-1] / 2.0 * np.diff(tops))])
        idx = self._layer_index(tops, t)
        return depth_at_tops[idx] + vs[idx] / 2.0 * (t - tops[idx])

    def to_dict(self) -> dict[str, Any]:
        return {"layers": [{"top_ns": t, "v_m_ns": v} for t, v in self.layers]}

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> VelocityModel:
        return cls(layers=tuple((float(d["top_ns"]), float(d["v_m_ns"])) for d in doc["layers"]))


def resolve_velocity(line: Line, grid: Grid | None) -> VelocityModel:
    """Line override, then the grid's model, then the header's dielectric."""
    if line.velocity is not None:
        return line.velocity
    if grid is not None and grid.velocity is not None:
        return grid.velocity
    return VelocityModel.from_dielectric(line.header.epsr)
