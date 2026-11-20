### Task 13: `ViewTransform` — the pure mapping behind the viewer

One frozen dataclass maps trace index and two-way time to widget pixels and back, given the visible window and the widget size. Axes, the cursor, drag-selection, picking, and the gain strip all go through it, so there is one place where "which trace is under the mouse" can be wrong. No Qt; tested on the normal matrix.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`
- Create: `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py`
- Modify: `.github/workflows/ci.yml` (add the module to the mypy line)

**Interfaces:**
- Consumes: numpy
- Produces: `ViewTransform(n_traces, n_samples, t0_ns, dt_ns, width, height, trace_lo, trace_hi, time_lo, time_hi)` frozen, with `fit(n_traces, n_samples, t0_ns, dt_ns, width, height)`, `t_end`, `x_of_trace(i)`, `trace_of_x(x)`, `y_of_time(t)`, `time_of_y(y)`, `trace_index_at(x) -> int`, `sample_index_at(y) -> int`, `source_rect() -> (x, y, w, h)` in image pixel units, `zoomed(factor, anchor_x, anchor_y)`, `panned(dx_px, dy_px)`, `resized(width, height)`, `with_window(trace_lo, trace_hi, time_lo, time_hi)`; `nice_ticks(vmin, vmax, target=6) -> np.ndarray`; `MIN_TRACE_SPAN = 4.0`, `MIN_SAMPLE_SPAN = 4.0`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from nsgeo_qgis.ui.view_transform import MIN_TRACE_SPAN, ViewTransform, nice_ticks

FIT = ViewTransform.fit(n_traces=608, n_samples=512, t0_ns=-11.09, dt_ns=0.2165, width=800, height=300)


def test_fit_maps_the_data_extent_onto_the_widget():
    assert FIT.x_of_trace(0) == 0.0
    assert FIT.x_of_trace(608) == 800.0
    assert FIT.y_of_time(-11.09) == 0.0
    assert FIT.y_of_time(FIT.t_end) == pytest.approx(300.0)
    assert FIT.t_end == pytest.approx(-11.09 + 512 * 0.2165)


def test_round_trips():
    for x in (0.0, 123.4, 799.0):
        assert FIT.x_of_trace(FIT.trace_of_x(x)) == pytest.approx(x)
    for y in (0.0, 57.2, 300.0):
        assert FIT.y_of_time(FIT.time_of_y(y)) == pytest.approx(y)


def test_index_lookups_clamp_to_the_data():
    assert FIT.trace_index_at(-50) == 0
    assert FIT.trace_index_at(800) == 607
    assert FIT.trace_index_at(400) == 304
    assert FIT.sample_index_at(-5) == 0
    assert FIT.sample_index_at(300) == 511
    assert FIT.sample_index_at(150) in (255, 256)  # exactly half the record; float rounding either side


def test_source_rect_is_the_visible_window_in_image_pixels():
    assert FIT.source_rect() == (0.0, 0.0, 608.0, 512.0)
    z = FIT.with_window(100.0, 300.0, 0.0, 20.0)
    x, y, w, h = z.source_rect()
    assert (x, w) == (100.0, 200.0)
    assert y == pytest.approx((0.0 + 11.09) / 0.2165)
    assert h == pytest.approx(20.0 / 0.2165)


def test_zoom_keeps_the_point_under_the_anchor_fixed():
    trace_before = FIT.trace_of_x(600.0)
    time_before = FIT.time_of_y(100.0)
    z = FIT.zoomed(2.0, anchor_x=600.0, anchor_y=100.0)
    assert z.trace_of_x(600.0) == pytest.approx(trace_before)
    assert z.time_of_y(100.0) == pytest.approx(time_before)
    assert (z.trace_hi - z.trace_lo) == pytest.approx(304.0)


def test_zoom_is_clamped_to_the_data_and_a_minimum_span():
    out = FIT.zoomed(0.5, 400.0, 150.0)  # zooming out past the data extent
    assert (out.trace_lo, out.trace_hi) == (0.0, 608.0)
    z = FIT
    for _ in range(40):
        z = z.zoomed(2.0, 400.0, 150.0)
    assert z.trace_hi - z.trace_lo == pytest.approx(MIN_TRACE_SPAN)
    assert 0.0 <= z.trace_lo and z.trace_hi <= 608.0


def test_pan_is_clamped_to_the_data():
    z = FIT.with_window(100.0, 300.0, 0.0, 20.0)
    p = z.panned(-100.0, 0.0)  # drag left by 100 px = 25 traces at 4 px/trace
    assert (p.trace_lo, p.trace_hi) == pytest.approx((125.0, 325.0))
    far = z.panned(-100_000.0, 0.0)
    assert (far.trace_lo, far.trace_hi) == (408.0, 608.0)
    up = z.panned(0.0, 100_000.0)
    assert up.time_lo == pytest.approx(-11.09)


def test_resized_keeps_the_window():
    r = FIT.with_window(100.0, 300.0, 0.0, 20.0).resized(400, 150)
    assert (r.width, r.height) == (400, 150)
    assert (r.trace_lo, r.trace_hi, r.time_lo, r.time_hi) == (100.0, 300.0, 0.0, 20.0)
    assert r.x_of_trace(300.0) == 400.0


def test_nice_ticks():
    np.testing.assert_allclose(nice_ticks(0.0, 10.13), [0, 2, 4, 6, 8, 10])
    np.testing.assert_allclose(nice_ticks(-11.09, 99.8), [0, 20, 40, 60, 80])
    np.testing.assert_allclose(nice_ticks(0.0, 4.0, target=8), [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0])
    assert nice_ticks(5.0, 5.0).size == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.view_transform'`

- [ ] **Step 3: Implement**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`:

```python
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
        return int(min(self.n_traces - 1, max(0, math.floor(self.trace_of_x(x)))))

    def sample_index_at(self, y: float) -> int:
        s = math.floor((self.time_of_y(y) - self.t0_ns) / self.dt_ns)
        return int(min(self.n_samples - 1, max(0, s)))

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
        return self.with_window(at - fx * t_span, at - fx * t_span + t_span, tt - fy * s_span, tt - fy * s_span + s_span)

    def panned(self, dx_px: float, dy_px: float) -> ViewTransform:
        """Drag by (dx, dy) pixels: positive dx moves the data right, i.e.
        the window moves to lower trace indices."""
        dt = -dx_px / self.width * (self.trace_hi - self.trace_lo)
        ds = -dy_px / self.height * (self.time_hi - self.time_lo)
        return self.with_window(self.trace_lo + dt, self.trace_hi + dt, self.time_lo + ds, self.time_hi + ds)

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
```

- [ ] **Step 4: Type-check and wire mypy**

Run: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`
Expected: clean. Add the module to the mypy line in `.github/workflows/ci.yml`.

- [ ] **Step 5: Run, lint, commit**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis .github/workflows/ci.yml
git commit -m "feat: ViewTransform, the pure trace/time to pixel mapping

One frozen dataclass behind axes, cursor, selection, picking and the
gain strip, so 'which trace is under the mouse' has exactly one
implementation and it is tested without Qt. Zoom keeps the anchored
data point fixed; zoom and pan are clamped to the data."
```

---

