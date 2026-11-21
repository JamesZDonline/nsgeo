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
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from nsgeo_qgis.ui.trace_axis import TraceAxis

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
    # A GPS line's metres-along-the-line layout; None keeps trace units linear.
    axis: TraceAxis | None = None

    def __post_init__(self) -> None:
        if self.axis is not None and self.axis.distance.size != self.n_traces:
            raise ValueError(
                f"ViewTransform axis has {self.axis.distance.size} traces, n_traces={self.n_traces}"
            )
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
        axis: TraceAxis | None = None,
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
            axis=axis,
        )

    @property
    def trace_bounds(self) -> tuple[float, float]:
        return (0.0, float(self.n_traces)) if self.bounds is None else self.bounds

    @property
    def t_end(self) -> float:
        return self.t0_ns + self.n_samples * self.dt_ns

    # ---- forward and inverse ------------------------------------------------
    def _walk_window(self) -> tuple[float, float]:
        assert self.axis is not None
        return (
            float(self.axis.walk_at(self.trace_lo)),
            float(self.axis.walk_at(self.trace_hi)),
        )

    def x_of_walk(self, w: float) -> float:
        """Local pixel of a position `w` metres along the line (axis only)."""
        wlo, whi = self._walk_window()
        span = whi - wlo
        if span <= 0.0:
            return 0.0
        if self.mirrored:
            return (whi - w) / span * self.width
        return (w - wlo) / span * self.width

    def walk_of_x(self, x: float) -> float:
        wlo, whi = self._walk_window()
        if self.mirrored:
            return whi - x / self.width * (whi - wlo)
        return wlo + x / self.width * (whi - wlo)

    def x_of_trace(self, i: float) -> float:
        if self.axis is not None:
            return self.x_of_walk(float(self.axis.walk_at(i)))
        span = self.trace_hi - self.trace_lo
        if span == 0.0:  # n_traces == 0: a valid, empty-axis ViewTransform (see M6)
            return 0.0
        if self.mirrored:
            return (self.trace_hi - i) / span * self.width
        return (i - self.trace_lo) / span * self.width

    def trace_of_x(self, x: float) -> float:
        if self.axis is not None:
            return float(self.axis.units_at_walk(self.walk_of_x(x)))
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

    def snap_row(self, time_ns: float) -> float:
        """Round a time to the nearest row top inside the record: where Time
        zero's line can sit (row 0 to the last row, which keeps one sample)."""
        m = round((time_ns - self.t0_ns) / self.dt_ns)
        return self.t0_ns + min(max(m, 0), self.n_samples - 1) * self.dt_ns

    def _column_at(self, x: float) -> int:
        """The trace column holding local pixel `x`, unclamped. Floor of the
        trace coordinate, or ceil - 1 when mirrored: either way a pixel on a
        column boundary belongs to the column on its screen-right side."""
        assert self.axis is None, "a trace axis has no linear columns; use trace_at_walk"
        t = self.trace_of_x(x)
        return math.ceil(t) - 1 if self.mirrored else math.floor(t)

    def trace_index_at(self, x: float) -> int:
        if self.axis is not None:
            return self.axis.nearest_drawn(self.walk_of_x(x))
        # max(0, ...) on the upper bound first: n_traces == 0 must clamp to 0,
        # never to -1, which would be numpy's "last trace" rather than "no trace".
        upper = max(0, self.n_traces - 1)
        return int(min(upper, max(0, self._column_at(x))))

    def trace_at(self, x: float) -> int | None:
        """The trace whose column holds `x`, or None past the data (blank
        space on the ruler): unlike `trace_index_at` it never snaps."""
        if self.axis is not None:
            return self.axis.trace_at_walk(self.walk_of_x(x))
        c = self._column_at(x)
        return c if 0 <= c < self.n_traces else None

    def traces_between(self, x0: float, x1: float) -> tuple[int, int] | None:
        """The data traces whose columns the pixel span touches, ascending and
        clamped into the data; None when the span misses the data."""
        if self.axis is not None:
            wa, wb = sorted((self.walk_of_x(x0), self.walk_of_x(x1)))
            lo, hi = self.axis.drawn()
            hit = np.flatnonzero((hi > lo) & (lo <= wb) & (hi > wa))
            return (int(hit[0]), int(hit[-1])) if hit.size else None
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

    def fit_width(self) -> ViewTransform:
        """Every trace across (the whole ruler when there is one); the time window is kept."""
        blo, bhi = self.trace_bounds
        return self.with_window(blo, bhi, self.time_lo, self.time_hi)

    def fit_height(self) -> ViewTransform:
        """The whole record down; the trace window is kept."""
        return self.with_window(self.trace_lo, self.trace_hi, self.t0_ns, self.t_end)

    def zoomed(self, factor: float, anchor_x: float, anchor_y: float) -> ViewTransform:
        """Scale both spans by 1/factor keeping the data point under the
        anchor pixel fixed. Clamped by with_window."""
        if self.axis is not None:
            return self._zoomed_walk(factor, anchor_x, anchor_y)
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
        if self.axis is not None:
            return self._panned_walk(dx_px, dy_px)
        dt = dx_px / self.width * (self.trace_hi - self.trace_lo)
        if not self.mirrored:
            dt = -dt
        ds = -dy_px / self.height * (self.time_hi - self.time_lo)
        return self.with_window(
            self.trace_lo + dt, self.trace_hi + dt, self.time_lo + ds, self.time_hi + ds
        )

    def with_walk_window(
        self, w_lo: float, w_hi: float, time_lo: float, time_hi: float
    ) -> ViewTransform:
        """`with_window` for a window given in metres along the line (axis only)."""
        assert self.axis is not None
        return self.with_window(
            float(self.axis.units_at_walk(w_lo)),
            float(self.axis.units_at_walk(w_hi)),
            time_lo,
            time_hi,
        )

    def _zoomed_walk(self, factor: float, anchor_x: float, anchor_y: float) -> ViewTransform:
        wlo, whi = self._walk_window()
        aw = self.walk_of_x(anchor_x)
        tt = self.time_of_y(anchor_y)
        w_span = (whi - wlo) / factor
        s_span = (self.time_hi - self.time_lo) / factor
        fx = anchor_x / self.width
        fy = anchor_y / self.height
        w_hi = aw + fx * w_span if self.mirrored else aw - fx * w_span + w_span
        return self.with_walk_window(
            w_hi - w_span, w_hi, tt - fy * s_span, tt - fy * s_span + s_span
        )

    def _panned_walk(self, dx_px: float, dy_px: float) -> ViewTransform:
        wlo, whi = self._walk_window()
        dw = dx_px / self.width * (whi - wlo)
        if not self.mirrored:
            dw = -dw
        ds = -dy_px / self.height * (self.time_hi - self.time_lo)
        return self.with_walk_window(wlo + dw, whi + dw, self.time_lo + ds, self.time_hi + ds)

    def paint_spans(self) -> list[tuple[float, float, float, float]]:
        """`(x0, x1, c0, c1)` for each visible run of equal columns: local
        pixels `[x0, x1)` (`x0 < x1`, clipped to the window) and the fractional
        source columns `[c0, c1)` in trace units (image columns at one column
        per trace) that those pixels show; `c` is linear in `x` within a run.
        Ascending in x. Unmirrored, `c0` is at `x0`; mirrored, the source runs
        the other way (`c1` at `x0`), so the caller flips each span's image.
        Gaps and left-out traces have no span. Axis only."""
        assert self.axis is not None
        wlo, whi = self._walk_window()
        out: list[tuple[float, float, float, float]] = []
        for first, last, r_lo, r_hi in self.axis.runs():
            lo, hi = max(r_lo, wlo), min(r_hi, whi)
            if hi <= lo:
                continue
            a, b = sorted((self.x_of_walk(lo), self.x_of_walk(hi)))
            if not b > a:
                continue
            per_m = (last - first + 1) / (r_hi - r_lo)
            out.append((a, b, first + (lo - r_lo) * per_m, first + (hi - r_lo) * per_m))
        return sorted(out)

    def resized(self, width: int, height: int) -> ViewTransform:
        # replace() carries mirrored and bounds along with the window.
        return replace(self, width=max(1, width), height=max(1, height))


def carry_time_window(
    old: ViewTransform, new: ViewTransform, old_zero: float, new_zero: float
) -> ViewTransform:
    """`new` with the time window `old` was showing, carried across a change of
    clock or record on the same line (spec §4.8). The trace window is kept.

    A whole-record window stays whole; one that began at the old top begins at
    the new top with the same span; any other keeps its radar times, so it
    moves by the zero change (`retime_ns`) and the tick labels shift while the
    features stay where they were. Clamping is left to `with_window`.
    """
    half = old.dt_ns / 2
    top = old.time_lo <= old.t0_ns + half
    if top and old.time_hi >= old.t_end - half:
        lo, hi = new.t0_ns, new.t_end
    elif top:
        lo = new.t0_ns
        hi = lo + (old.time_hi - old.time_lo)
    else:
        shift = old_zero - new_zero
        lo, hi = old.time_lo + shift, old.time_hi + shift
    return new.with_window(old.trace_lo, old.trace_hi, lo, hi)


def true_scale_window(
    t: ViewTransform, metres_per_trace_unit: float, ns_per_metre: float
) -> ViewTransform:
    """The window in which a metre down is as long on screen as a metre along.

    Keeps the window's trace span and sets the time span to match when the
    whole record is deep enough to do so, centred on the window's middle time.
    Otherwise (a long line) keeps the whole record and narrows the trace span
    about the window's middle. `with_window` clamps at the minimum spans.
    """
    if t.axis is not None:
        return _true_scale_walk(t, ns_per_metre)
    across = t.width / ((t.trace_hi - t.trace_lo) * metres_per_trace_unit)  # px per metre along
    span = t.height / across * ns_per_metre  # ns that make px/m equal
    record = t.n_samples * t.dt_ns
    if span <= record:
        mid = (t.time_lo + t.time_hi) / 2
        return t.with_window(t.trace_lo, t.trace_hi, mid - span / 2, mid + span / 2)
    down = t.height / (record / ns_per_metre)  # px per metre down, whole record
    traces = t.width / down / metres_per_trace_unit
    mid = (t.trace_lo + t.trace_hi) / 2
    return t.with_window(mid - traces / 2, mid + traces / 2, t.t0_ns, t.t_end)


def _true_scale_walk(t: ViewTransform, ns_per_metre: float) -> ViewTransform:
    """`true_scale_window` on a trace axis: the metres across are the window's
    own, and the long-line branch narrows about the middle metre."""
    assert t.axis is not None
    wlo, whi = t._walk_window()
    if whi <= wlo:  # a stationary patch: no metres across to match
        return t
    across = t.width / (whi - wlo)  # px per metre along
    span = t.height / across * ns_per_metre
    record = t.n_samples * t.dt_ns
    if span <= record:
        mid = (t.time_lo + t.time_hi) / 2
        return t.with_window(t.trace_lo, t.trace_hi, mid - span / 2, mid + span / 2)
    down = t.height / (record / ns_per_metre)
    metres = t.width / down
    mid_w = (wlo + whi) / 2
    return t.with_walk_window(mid_w - metres / 2, mid_w + metres / 2, t.t0_ns, t.t_end)


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
