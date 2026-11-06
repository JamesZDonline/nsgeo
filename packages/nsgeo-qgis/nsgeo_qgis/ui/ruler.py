"""One ruler of metres along a grid, shared by every line on it. No Qt.

The Profile draws a reversed (zigzag) line mirrored, against the same ruler as
a forward line, so a reflection stays put as the user sweeps across lines.
For that the two must agree on where a ground position falls, and they only do
if each trace is placed at its column's *centre*: trace `i` fills the column
`[i, i + 1)` in `ViewTransform` units and its centre `i + 0.5` lies on
`distance[i]`. Placing the column's left edge on `distance[i]` instead would put
a forward and a reversed line one whole trace apart.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
from nsgeo.geometry import Grid


def trace_to_metres(distance: Any, traces: Any) -> Any:
    """Metres along the line at (possibly fractional) `traces`, read off the
    line's own distance array, so there is one trace-to-metre map. Beyond
    either end it extends by the end spacing."""
    d = np.asarray(distance, dtype=float)
    tr = np.asarray(traces, dtype=float)
    last = len(d) - 1
    inside = np.interp(tr, np.arange(len(d)), d)
    below = d[0] + tr * (d[1] - d[0])
    above = d[-1] + (tr - last) * (d[-1] - d[-2])
    return np.where(tr < 0, below, np.where(tr > last, above, inside))


def metres_to_trace(distance: Any, x_m: Any) -> Any:
    """The inverse of `trace_to_metres`, for a line whose distance runs
    either way along the axis."""
    d = np.asarray(distance, dtype=float)
    x = np.asarray(x_m, dtype=float)
    idx = np.arange(len(d), dtype=float)
    if d[-1] < d[0]:
        d, idx = d[::-1], idx[::-1]
    last = len(d) - 1
    inside = np.interp(x, d, idx)
    below = idx[0] + (x - d[0]) / (d[1] - d[0]) * (idx[1] - idx[0])
    above = idx[-1] + (x - d[-1]) / (d[-1] - d[-2]) * (idx[-1] - idx[-2])
    return np.where(x < d[0], below, np.where(x > d[last], above, inside))


def trace_units_at(distance: Any, metres: Any) -> Any:
    """The `ViewTransform` horizontal coordinate of a ground position:
    `metres_to_trace` plus half a column, since trace `i` is centred on
    `distance[i]`. Extrapolates past either end."""
    return metres_to_trace(distance, metres) + 0.5


def metres_at(distance: Any, trace_units: Any) -> Any:
    """The inverse of `trace_units_at`."""
    return trace_to_metres(distance, np.asarray(trace_units, dtype=float) - 0.5)


def is_reversed(distance: Any) -> bool:
    """True when the distance falls as traces rise, i.e. the line was walked
    toward the grid's low end. Read from the data, never from a flag."""
    return bool(distance[-1] < distance[0])


@dataclass(frozen=True)
class Ruler:
    grid_id: str
    axis: str
    lo_m: float
    hi_m: float

    @property
    def key(self) -> tuple[str, str]:
        return (self.grid_id, self.axis)


def ruler_for(grid: Grid, axis: str, distances: Iterable[np.ndarray]) -> Ruler:
    """The grid's extent along `axis`, widened to take in every line's columns
    (`[min - h, max + h]`, `h` half a trace spacing) so a line running past the
    grid edge is still wholly on the ruler. One-trace lines have no spacing and
    are ignored."""
    lo = 0.0
    hi = float(grid.size_x if axis == "x" else grid.size_y)
    for d in distances:
        if len(d) < 2:
            continue
        h = abs(float(d[1]) - float(d[0])) / 2.0
        lo = min(lo, float(np.min(d)) - h)
        hi = max(hi, float(np.max(d)) + h)
    return Ruler(grid.id, axis, lo, hi)


def bounds_on(ruler: Ruler, distance: Any) -> tuple[float, float]:
    """The ruler's two ends in this line's trace units, sorted ascending."""
    a = float(trace_units_at(distance, ruler.lo_m))
    b = float(trace_units_at(distance, ruler.hi_m))
    return (min(a, b), max(a, b))
