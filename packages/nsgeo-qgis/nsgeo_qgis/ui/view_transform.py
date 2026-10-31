"""Trace/time <-> pixel mapping for the profile viewer. No Qt.

The visible window is [trace_lo, trace_hi) in trace-index units, within
`trace_bounds` (the data, or a wider ruler with blank space past its ends), and
[time_lo, time_hi) in two-way time. Widget size is the image area only; axis
margins are the widget's business. A mirrored transform draws `trace_hi` at
x = 0 and `trace_lo` at the right edge; the trace index stays the recorded one.
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
    mirrored: bool = False
    # None means (0.0, n_traces): the window may not leave the data.
    bounds: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        # Checked before the axes: a bad bounds must always name itself.
        if self.bounds is not None and not (
            math.isfinite(self.bounds[0])
            and math.isfinite(self.bounds[1])
            and self.bounds[0] < self.bounds[1]
        ):
            raise ValueError(f"ViewTransform bounds must be finite and ordered: {self.bounds}")
        # Every construction path -- fit(), a direct call, and the replace()
        # with_window/resized use internally -- runs __init__ and so lands
        # here. This matters specifically because fit() receives t0_ns/dt_ns
        # straight off a DZT header (Task 15 shows header-derived axes before
        # samples load), ahead of anywhere else that might reject a bad one.
        # with_window keeps its own finiteness check too: it fires earlier,
        # with a message describing the window change being attempted, before
        # replace() -- and this check -- are ever reached.
        if not all(
            math.isfinite(v)
            for v in (
                self.t0_ns,
                self.dt_ns,
                self.trace_lo,
                self.trace_hi,
                self.time_lo,
                self.time_hi,
            )
        ):
            raise ValueError(
                "ViewTransform requires finite axes: "
                f"t0_ns={self.t0_ns}, dt_ns={self.dt_ns}, "
                f"trace=[{self.trace_lo}, {self.trace_hi}), time=[{self.time_lo}, {self.time_hi})"
            )

    @classmethod
    def fit(
        cls,
        n_traces: int,
        n_samples: int,
        t0_ns: float,
        dt_ns: float,
        width: int,
        height: int,
        *,
        bounds: tuple[float, float] | None = None,
        mirrored: bool = False,
    ) -> ViewTransform:
        return cls(
            n_traces=n_traces,
            n_samples=n_samples,
            t0_ns=t0_ns,
            dt_ns=dt_ns,
            width=max(1, width),
            height=max(1, height),
            trace_lo=0.0 if bounds is None else bounds[0],
            trace_hi=float(n_traces) if bounds is None else bounds[1],
            time_lo=t0_ns,
            time_hi=t0_ns + n_samples * dt_ns,
            mirrored=mirrored,
            bounds=bounds,
        )

    @property
    def trace_bounds(self) -> tuple[float, float]:
        return (0.0, float(self.n_traces)) if self.bounds is None else self.bounds

    @property
    def t_end(self) -> float:
        return self.t0_ns + self.n_samples * self.dt_ns

    # ---- forward and inverse ------------------------------------------------
    def x_of_trace(self, i: float) -> float:
        span = self.trace_hi - self.trace_lo
        if span == 0.0:  # n_traces == 0: a valid, empty-axis ViewTransform (see M6)
            return 0.0
        if self.mirrored:
            return (self.trace_hi - i) / span * self.width
        return (i - self.trace_lo) / span * self.width

    def trace_of_x(self, x: float) -> float:
        span = self.trace_hi - self.trace_lo
        if self.mirrored:
            return self.trace_hi - x / self.width * span
        return self.trace_lo + x / self.width * span

    def y_of_time(self, t: float) -> float:
        span = self.time_hi - self.time_lo
        if span == 0.0:  # n_samples == 0: a valid, empty-axis ViewTransform (see M6)
            return 0.0
        return (t - self.time_lo) / span * self.height

    def time_of_y(self, y: float) -> float:
        return self.time_lo + y / self.height * (self.time_hi - self.time_lo)

    def snap_cutoff(self, time_ns: float) -> float:
        """Round a time to the nearest sample boundary, keeping at least one
        sample and never passing `t_end`: a cutoff line dragged anywhere
        lands on a boundary the `time_cutoff` step can actually express."""
        m = round((time_ns - self.t0_ns) / self.dt_ns)
        return self.t0_ns + min(max(m, 1), self.n_samples) * self.dt_ns

    def _column_at(self, x: float) -> int:
        """The trace column holding local pixel `x`, unclamped. Floor of the
        trace coordinate, or ceil - 1 when mirrored: either way a pixel on a
        column boundary belongs to the column on its screen-right side."""
        t = self.trace_of_x(x)
        return math.ceil(t) - 1 if self.mirrored else math.floor(t)

    def trace_index_at(self, x: float) -> int:
        # max(0, ...) on the upper bound first: n_traces == 0 must clamp to 0,
        # never to -1, which would be numpy's "last trace" rather than "no trace".
        upper = max(0, self.n_traces - 1)
        return int(min(upper, max(0, self._column_at(x))))

    def trace_at(self, x: float) -> int | None:
        """The trace whose column holds `x`, or None past the data (blank
        space on the ruler): unlike `trace_index_at` it never snaps."""
        c = self._column_at(x)
        return c if 0 <= c < self.n_traces else None

    def traces_between(self, x0: float, x1: float) -> tuple[int, int] | None:
        """The data traces whose columns the pixel span touches, ascending and
        clamped into the data; None when the span misses the data."""
        first, last = sorted((self._column_at(x0), self._column_at(x1)))
        a, b = max(first, 0), min(last, self.n_traces - 1)
        return (a, b) if a <= b else None

    def sample_index_at(self, y: float) -> int:
        s = math.floor((self.time_of_y(y) - self.t0_ns) / self.dt_ns)
        upper = max(0, self.n_samples - 1)
        return int(min(upper, max(0, s)))

    def _visible_data(self) -> tuple[float, float]:
        """The part of the window that lies on data, in trace units; empty
        (lo == hi) when the window is all blank."""
        lo = max(self.trace_lo, 0.0)
        hi = min(self.trace_hi, float(self.n_traces))
        return (lo, hi) if lo < hi else (min(max(self.trace_lo, 0.0), float(self.n_traces)),) * 2

    def source_rect(self) -> tuple[float, float, float, float]:
        """Visible data as (x, y, w, h) in image pixels: traces and samples.
        Only the part of the window on data; w is 0 when it is all blank."""
        y0 = (self.time_lo - self.t0_ns) / self.dt_ns
        y1 = (self.time_hi - self.t0_ns) / self.dt_ns
        lo, hi = self._visible_data()
        return (lo, y0, hi - lo, y1 - y0)

    def target_span(self) -> tuple[float, float]:
        """The ascending local x range that `source_rect()` lands on."""
        lo, hi = self._visible_data()
        xa, xb = self.x_of_trace(lo), self.x_of_trace(hi)
        return (min(xa, xb), max(xa, xb))

    # ---- window changes -----------------------------------------------------
    def with_window(
        self, trace_lo: float, trace_hi: float, time_lo: float, time_hi: float
    ) -> ViewTransform:
        blo, bhi = self.trace_bounds
        t_span = min(max(trace_hi - trace_lo, MIN_TRACE_SPAN), bhi - blo)
        s_span = min(
            max(time_hi - time_lo, MIN_SAMPLE_SPAN * self.dt_ns), self.n_samples * self.dt_ns
        )
        lo = min(max(trace_lo, blo), bhi - t_span)
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
        # Mirrored, the anchor sits fx of the way from the window's high end.
        t_hi = at + fx * t_span if self.mirrored else at - fx * t_span + t_span
        return self.with_window(
            t_hi - t_span,
            t_hi,
            tt - fy * s_span,
            tt - fy * s_span + s_span,
        )

    def panned(self, dx_px: float, dy_px: float) -> ViewTransform:
        """Drag by (dx, dy) pixels: positive dx moves the data right, i.e.
        the window moves to lower trace indices (higher ones when mirrored)."""
        dt = dx_px / self.width * (self.trace_hi - self.trace_lo)
        if not self.mirrored:
            dt = -dt
        ds = -dy_px / self.height * (self.time_hi - self.time_lo)
        return self.with_window(
            self.trace_lo + dt, self.trace_hi + dt, self.time_lo + ds, self.time_hi + ds
        )

    def one_to_one(self) -> ViewTransform:
        """One trace per pixel column, keeping the trace at the screen's left
        edge where it is: `trace_lo` normally, `trace_hi` when mirrored."""
        if self.mirrored:
            return self.with_window(
                self.trace_hi - self.width, self.trace_hi, self.time_lo, self.time_hi
            )
        return self.with_window(
            self.trace_lo, self.trace_lo + self.width, self.time_lo, self.time_hi
        )

    def resized(self, width: int, height: int) -> ViewTransform:
        # replace() carries mirrored and bounds along with the window.
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
