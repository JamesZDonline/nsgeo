"""Trace/time <-> pixel mapping for the profile viewer. No Qt.

The visible window is [trace_lo, trace_hi) in trace-index units and
[time_lo, time_hi) in two-way time. Widget size is the image area only;
axis margins are the widget's business.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

MIN_TRACE_SPAN = 4.0
MIN_SAMPLE_SPAN = 4.0


@dataclass(frozen=True)
class ViewTransform:
    n_traces: int
    n_samples: int
    t0_ns: float
    dt_ns: float
    width: int
    height: int
    trace_lo: float
    trace_hi: float
    time_lo: float
    time_hi: float

    @classmethod
    def fit(
        cls, n_traces: int, n_samples: int, t0_ns: float, dt_ns: float, width: int, height: int
    ) -> ViewTransform:
        return cls(
            n_traces=n_traces,
            n_samples=n_samples,
            t0_ns=t0_ns,
            dt_ns=dt_ns,
            width=max(1, width),
            height=max(1, height),
            trace_lo=0.0,
            trace_hi=float(n_traces),
            time_lo=t0_ns,
            time_hi=t0_ns + n_samples * dt_ns,
        )

    @property
    def t_end(self) -> float:
        return self.t0_ns + self.n_samples * self.dt_ns

    # ---- forward and inverse ------------------------------------------------
    def x_of_trace(self, i: float) -> float:
        return (i - self.trace_lo) / (self.trace_hi - self.trace_lo) * self.width

    def trace_of_x(self, x: float) -> float:
        return self.trace_lo + x / self.width * (self.trace_hi - self.trace_lo)

    def y_of_time(self, t: float) -> float:
        return (t - self.time_lo) / (self.time_hi - self.time_lo) * self.height

    def time_of_y(self, y: float) -> float:
        return self.time_lo + y / self.height * (self.time_hi - self.time_lo)

    def trace_index_at(self, x: float) -> int:
        # max(0, ...) on the upper bound first: n_traces == 0 must clamp to 0,
        # never to -1, which would be numpy's "last trace" rather than "no trace".
        upper = max(0, self.n_traces - 1)
        return int(min(upper, max(0, math.floor(self.trace_of_x(x)))))

    def sample_index_at(self, y: float) -> int:
        s = math.floor((self.time_of_y(y) - self.t0_ns) / self.dt_ns)
        upper = max(0, self.n_samples - 1)
        return int(min(upper, max(0, s)))

    def source_rect(self) -> tuple[float, float, float, float]:
        """Visible window as (x, y, w, h) in image pixels: traces and samples."""
        y0 = (self.time_lo - self.t0_ns) / self.dt_ns
        y1 = (self.time_hi - self.t0_ns) / self.dt_ns
        return (self.trace_lo, y0, self.trace_hi - self.trace_lo, y1 - y0)

    # ---- window changes -----------------------------------------------------
    def with_window(
        self, trace_lo: float, trace_hi: float, time_lo: float, time_hi: float
    ) -> ViewTransform:
        t_span = min(max(trace_hi - trace_lo, MIN_TRACE_SPAN), float(self.n_traces))
        s_span = min(
            max(time_hi - time_lo, MIN_SAMPLE_SPAN * self.dt_ns), self.n_samples * self.dt_ns
        )
        lo = min(max(trace_lo, 0.0), self.n_traces - t_span)
        tlo = min(max(time_lo, self.t0_ns), self.t_end - s_span)
        if not all(math.isfinite(v) for v in (lo, t_span, tlo, s_span)):
            # A NaN factor/delta (zoomed/panned) or a NaN argument here poisons
            # the min/max clamps above without raising -- Python's min/max keep
            # whichever operand happens not to be NaN, silently. Left unchecked,
            # the resulting window is only discovered broken on some *later*
            # call (trace_index_at raising ValueError, far from the real cause).
            # Fail here instead, at the one place all window changes pass
            # through, rather than let a half-corrupted transform propagate.
            raise ValueError(
                f"non-finite view window: trace=[{lo}, {lo + t_span}), time=[{tlo}, {tlo + s_span})"
            )
        return replace(self, trace_lo=lo, trace_hi=lo + t_span, time_lo=tlo, time_hi=tlo + s_span)

    def zoomed(self, factor: float, anchor_x: float, anchor_y: float) -> ViewTransform:
        """Scale both spans by 1/factor keeping the data point under the
        anchor pixel fixed. Clamped by with_window."""
        at = self.trace_of_x(anchor_x)
        tt = self.time_of_y(anchor_y)
        t_span = (self.trace_hi - self.trace_lo) / factor
        s_span = (self.time_hi - self.time_lo) / factor
        fx = anchor_x / self.width
        fy = anchor_y / self.height
        return self.with_window(
            at - fx * t_span,
            at - fx * t_span + t_span,
            tt - fy * s_span,
            tt - fy * s_span + s_span,
        )

    def panned(self, dx_px: float, dy_px: float) -> ViewTransform:
        """Drag by (dx, dy) pixels: positive dx moves the data right, i.e.
        the window moves to lower trace indices."""
        dt = -dx_px / self.width * (self.trace_hi - self.trace_lo)
        ds = -dy_px / self.height * (self.time_hi - self.time_lo)
        return self.with_window(
            self.trace_lo + dt, self.trace_hi + dt, self.time_lo + ds, self.time_hi + ds
        )

    def resized(self, width: int, height: int) -> ViewTransform:
        return replace(self, width=max(1, width), height=max(1, height))


def nice_ticks(vmin: float, vmax: float, target: int = 6) -> np.ndarray:
    """Round tick positions covering [vmin, vmax] at a 1-2-5 step."""
    if not vmax > vmin:
        return np.array([], dtype=float)
    raw = (vmax - vmin) / max(1, target)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 5.0, 10.0):
        step = m * mag
        if step >= raw:
            break
    first = math.ceil(vmin / step - 1e-9) * step
    ticks = np.arange(first, vmax + step * 1e-9, step)
    return np.round(ticks, 10)
