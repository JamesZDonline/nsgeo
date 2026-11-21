"""A GPS line laid out in metres along the line, with its gaps (M17c, #134). No Qt.

Trace `i` fills the column `[i, i + 1)` in trace units, centred on
`distance[i]`; `ruler.metres_at` / `trace_units_at` are the one road between the
two, and this class only adds a sign (so the walk always rises with the trace
index, whichever way the line was walked) and each trace's drawn extent.

A drawn trace reaches halfway to each neighbour, but never more than half a
usual step into a gap (the end traces likewise outward when that step is a
gap); the rest of a gap is the profile's no-data hatch. A trace left out
(`spacing.left_out`) has no extent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from nsgeo.geometry import check_gap_m, gap_steps, left_out, usual_step

from nsgeo_qgis.ui.ruler import metres_at, trace_units_at


@dataclass(frozen=True, eq=False)
class TraceAxis:
    distance: np.ndarray
    gap_m: float | None = None
    _lo: np.ndarray = field(init=False, repr=False)
    _hi: np.ndarray = field(init=False, repr=False)
    _runs: tuple[tuple[int, int, float, float], ...] = field(init=False, repr=False)
    _shown: np.ndarray = field(init=False, repr=False)

    @classmethod
    def from_distance(cls, distance: Any, gap_m: float | None = None) -> TraceAxis:
        return cls(np.array(distance, dtype=float), gap_m)

    def __post_init__(self) -> None:
        d = np.asarray(self.distance, dtype=float)
        if d.ndim != 1 or d.size < 2:
            raise ValueError("a trace axis needs a distance for at least 2 traces")
        if not np.all(np.isfinite(d)):
            raise ValueError("a trace axis needs finite distances")
        check_gap_m(self.gap_m)
        steps = np.diff(d)
        sign = 1.0 if d[-1] >= d[0] else -1.0
        if np.any(steps * sign < 0):
            raise ValueError("a trace axis needs a distance that never turns back")
        object.__setattr__(self, "distance", d)
        w = d * sign
        usual = usual_step(d)
        gaps = gap_steps(d, self.gap_m)
        out = left_out(d, self.gap_m)
        half = 0.5 * np.diff(w)
        # Reach toward the next trace (right) and the previous one (left).
        right = np.append(np.where(gaps, np.minimum(half, usual / 2), half), 0.0)
        left = np.insert(np.where(gaps, np.minimum(half, usual / 2), half), 0, 0.0)
        right[-1] = left[-1]  # the end traces reach outward as far as inward
        left[0] = right[0]
        lo, hi = w - left, w + right
        lo[out] = hi[out] = w[out]
        object.__setattr__(self, "_lo", lo)
        object.__setattr__(self, "_hi", hi)
        shown = hi > lo
        object.__setattr__(self, "_shown", np.flatnonzero(shown))
        object.__setattr__(self, "_runs", self._group(lo, hi, shown, usual))

    @staticmethod
    def _group(
        lo: np.ndarray, hi: np.ndarray, shown: np.ndarray, usual: float
    ) -> tuple[tuple[int, int, float, float], ...]:
        tol = 1e-6 * usual if usual > 0 else 1e-12
        runs: list[tuple[int, int, float, float]] = []
        first = prev = None
        for i in np.flatnonzero(shown):
            i = int(i)
            same = (
                prev is not None
                and prev == i - 1
                and abs(lo[i] - hi[prev]) <= tol
                and abs((hi[i] - lo[i]) - (hi[prev] - lo[prev])) <= tol
            )
            if not same:
                if first is not None:
                    runs.append((first, prev, float(lo[first]), float(hi[prev])))
                first = i
            prev = i
        if first is not None and prev is not None:
            runs.append((first, prev, float(lo[first]), float(hi[prev])))
        return tuple(runs)

    @property
    def sign(self) -> float:
        return 1.0 if self.distance[-1] >= self.distance[0] else -1.0

    def walk_at(self, units: Any) -> Any:
        """Metres along the line at trace `units`, rising with them."""
        return metres_at(self.distance, units) * self.sign

    def units_at_walk(self, walk: Any) -> Any:
        """The inverse of `walk_at`. Where a zero end step makes the end
        extrapolation blow up, it carries on at the usual step instead."""
        w = np.asarray(walk, dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            u = trace_units_at(self.distance, w * self.sign)
        if np.all(np.isfinite(u)):
            return u
        usual = usual_step(self.distance) or 1.0
        n = self.distance.size
        w0 = self.sign * self.distance[0]
        w1 = self.sign * self.distance[-1]
        fallback = np.where(w < w0, 0.5 + (w - w0) / usual, n - 0.5 + (w - w1) / usual)
        return np.where(np.isfinite(u), u, fallback)

    def drawn(self) -> tuple[np.ndarray, np.ndarray]:
        """Per trace, `[lo, hi)` in walk metres; `lo == hi` when left out."""
        return self._lo, self._hi

    def trace_at_walk(self, w: float) -> int | None:
        idx = self._shown
        if not idx.size:
            return None
        k = int(np.searchsorted(self._lo[idx], w, side="right")) - 1
        if k < 0:
            return None
        i = int(idx[k])
        return i if w < self._hi[i] else None

    def nearest_drawn(self, w: float) -> int:
        idx = self._shown
        if not idx.size:
            idx = np.arange(self.distance.size)
        gap = np.maximum(np.maximum(self._lo[idx] - w, w - self._hi[idx]), 0.0)
        return int(idx[int(np.argmin(gap))])

    def runs(self) -> list[tuple[int, int, float, float]]:
        """`(first, last, lo, hi)`: adjoining drawn traces of equal width."""
        return list(self._runs)
