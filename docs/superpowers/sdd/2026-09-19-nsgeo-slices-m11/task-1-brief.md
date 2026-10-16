### Task 1: Core — the arithmetic a viewer and an exporter need

Everything M10 deferred for want of a caller, plus the fill speedup its own review asked for.
Pure numpy; no Qt, no GDAL, no QGIS.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/display.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/frame.py` (append `slice_extent`)
- Modify: `packages/nsgeo-core/src/nsgeo/slices/fill.py` (padding + kernel cache)
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` (re-exports)
- Test: `packages/nsgeo-core/tests/test_slices_display.py` (new)
- Test: `packages/nsgeo-core/tests/test_slices_fill.py` (append)
- Test: `packages/nsgeo-core/tests/test_slices_frame.py` (append)
- Test: `packages/nsgeo-core/tests/test_real_files.py` (append one test)

**Interfaces:**

- Consumes: `CubeFrame` (`origin`, `azimuth`, `cell`, `nx`, `ny`, `crs`, `axes()`, `cell_index()`,
  `n_cells`), `ZAxis` (`t0_ns`, `dz_ns`, `nz`, `times_ns()`, `level_range()`), `SliceCube`
  (`frame`, `z`, `mean`, `count`, `slice_levels(k0, k1) -> (ny, nx)`, `coverage()`),
  `VelocityModel.depth_at(times_ns)`, `nsgeo.render.Normalizer` (a Protocol with
  `limit(data) -> float`), `nsgeo.slices.fill.disc_kernel`.
- Produces, all importable from `nsgeo.slices`:
  - `SliceWindow(k0: int, k1: int)` — frozen; `.n_levels -> int`; rejects `k1 <= k0` or `k0 < 0`.
  - `plan_windows(z: ZAxis, thickness_levels: int, step_levels: int) -> tuple[SliceWindow, ...]`
  - `window_times_ns(z: ZAxis, window: SliceWindow) -> tuple[float, float]`
  - `window_depths_m(z: ZAxis, window: SliceWindow, velocity: VelocityModel) -> tuple[float, float]`
  - `window_label(z: ZAxis, window: SliceWindow, velocity: VelocityModel | None = None) -> str`
  - `limit_over_slices(slices: Iterable[np.ndarray], clip: Normalizer) -> float`
  - `shared_limit(cube: SliceCube, thickness_levels: int, clip: Normalizer) -> float`
  - `to_north_up(values: np.ndarray, frame: CubeFrame) -> tuple[np.ndarray, tuple[float, float, float, float, float, float]]`
  - `slice_extent(frame: CubeFrame) -> tuple[float, float, float, float]` (in `frame.py`)
  - `clear_kernel_cache() -> None` (in `fill.py`)

---

- [ ] **Step 1: Write the failing tests for `slice_extent`**

Append to `packages/nsgeo-core/tests/test_slices_frame.py`:

```python
def test_slice_extent_of_an_axis_aligned_frame_is_its_own_box():
    frame = CubeFrame(origin=(100.0, 200.0), azimuth=0.0, cell=0.5, nx=40, ny=20, crs="EPSG:32633")
    assert slice_extent(frame) == pytest.approx((100.0, 200.0, 120.0, 210.0))


def test_slice_extent_covers_all_four_corners_of_a_rotated_frame():
    """The mutant this exists to catch takes only the origin and the far
    corner, which is correct at azimuth 0 and wrong at every other angle:
    a rotated rectangle's bounding box is decided by the two corners the
    diagonal misses."""
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=30.0, cell=1.0, nx=10, ny=4, crs="EPSG:32633")
    xmin, ymin, xmax, ymax = slice_extent(frame)
    x_hat, y_hat = frame.axes()
    corners = np.array(
        [
            [0.0, 0.0],
            10.0 * x_hat,
            4.0 * y_hat,
            10.0 * x_hat + 4.0 * y_hat,
        ]
    )
    assert xmin == pytest.approx(corners[:, 0].min())
    assert ymin == pytest.approx(corners[:, 1].min())
    assert xmax == pytest.approx(corners[:, 0].max())
    assert ymax == pytest.approx(corners[:, 1].max())
    # The two-corner mutant would miss by this much, so the test is not vacuous.
    two_corner_ymin = min(0.0, float((10.0 * x_hat + 4.0 * y_hat)[1]))
    assert abs(two_corner_ymin - ymin) > 1.0


def test_slice_extent_is_wider_than_the_frame_when_rotated():
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=45.0, cell=1.0, nx=10, ny=10, crs="EPSG:32633")
    xmin, ymin, xmax, ymax = slice_extent(frame)
    assert xmax - xmin == pytest.approx(math.hypot(10.0, 10.0), rel=1e-9)
    assert ymax - ymin == pytest.approx(math.hypot(10.0, 10.0), rel=1e-9)
```

Add `import math` and `from nsgeo.slices.frame import slice_extent` to that file's imports (it
already imports `numpy as np`, `pytest`, and `CubeFrame`).

- [ ] **Step 2: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -q`
Expected: 3 errors — `ImportError: cannot import name 'slice_extent'`.

- [ ] **Step 3: Implement `slice_extent`**

Append to `packages/nsgeo-core/src/nsgeo/slices/frame.py`, after the `ZAxis` class:

```python
def slice_extent(frame: CubeFrame) -> tuple[float, float, float, float]:
    """The axis-aligned world bounding box of `frame`, as (xmin, ymin, xmax, ymax).

    All four corners, never two. A rotated rectangle's bounding box is set
    by the corners the origin-to-far-corner diagonal does not touch, so the
    cheap two-corner form is right only at azimuth 0 -- and silently wrong,
    by up to the frame's own width, at every other angle.

    This is what a north-up export resamples into: the box is in world
    units and is generally larger than `nx * cell` by `ny * cell`, because
    a rotated frame does not fill its own bounding box.
    """
    x_hat, y_hat = frame.axes()
    origin = np.asarray(frame.origin, dtype=float)
    span_x = frame.nx * frame.cell * x_hat
    span_y = frame.ny * frame.cell * y_hat
    corners = np.array([origin, origin + span_x, origin + span_y, origin + span_x + span_y])
    return (
        float(corners[:, 0].min()),
        float(corners[:, 1].min()),
        float(corners[:, 0].max()),
        float(corners[:, 1].max()),
    )
```

- [ ] **Step 4: Run them and watch them pass**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -q`
Expected: PASS, and the file's pre-existing tests still pass.

- [ ] **Step 5: Prove the test discriminates**

Temporarily replace the `corners` array with the two-corner form
(`np.array([origin, origin + span_x + span_y])`), re-run, and confirm
`test_slice_extent_covers_all_four_corners_of_a_rotated_frame` and
`test_slice_extent_is_wider_than_the_frame_when_rotated` FAIL while the axis-aligned one still
passes. Revert. Record both numbers in the task report.

- [ ] **Step 6: Commit**

```bash
git add packages/nsgeo-core/src/nsgeo/slices/frame.py packages/nsgeo-core/tests/test_slices_frame.py
git commit -m "feat(slices): slice_extent, a frame's world bounding box

M10 Ruling B dropped it as dead code, to return with its caller. The
north-up GeoTIFF resample in display.py is that caller.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Write the failing tests for the window plan and its labels**

Create `packages/nsgeo-core/tests/test_slices_display.py`:

```python
"""Windows, labels, the shared stretch, and the north-up resample."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.render import PercentileClip, UnipolarClip
from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.display import (
    SliceWindow,
    limit_over_slices,
    plan_windows,
    shared_limit,
    to_north_up,
    window_depths_m,
    window_label,
    window_times_ns,
)
from nsgeo.slices.frame import CubeFrame, ZAxis
from nsgeo.velocity import VelocityModel


def _axis(nz: int = 100, dz: float = 0.5, t0: float = 0.0) -> ZAxis:
    return ZAxis(t0_ns=t0, dz_ns=dz, nz=nz)


def test_a_window_rejects_an_empty_or_reversed_range():
    with pytest.raises(ValueError):
        SliceWindow(5, 5)
    with pytest.raises(ValueError):
        SliceWindow(5, 4)
    with pytest.raises(ValueError):
        SliceWindow(-1, 3)


def test_abutting_windows_tile_the_axis_without_gaps_or_overlap():
    windows = plan_windows(_axis(nz=100), thickness_levels=10, step_levels=10)
    assert len(windows) == 10
    assert windows[0] == SliceWindow(0, 10)
    assert windows[-1] == SliceWindow(90, 100)
    for a, b in zip(windows, windows[1:]):
        assert b.k0 == a.k1


def test_overlapping_windows_match_the_specs_band_count_formula():
    """Spec 9.4: n_bands = (z_range - thickness) / step + 1. In levels,
    that is (nz - thickness) // step + 1 -- the count a GeoTIFF export
    turns into bands, so an off-by-one here is an off-by-one file."""
    nz, thickness, step = 100, 10, 5
    windows = plan_windows(_axis(nz=nz), thickness, step)
    assert len(windows) == (nz - thickness) // step + 1 == 19
    assert windows[1].k0 == 5  # 50% overlap: the second window starts mid-first
    assert windows[1].k1 == 15
    assert windows[-1].k1 == nz  # the last window still ends on the axis


def test_a_window_thicker_than_the_axis_becomes_the_whole_axis():
    assert plan_windows(_axis(nz=8), thickness_levels=20, step_levels=1) == (SliceWindow(0, 8),)


def test_plan_windows_rejects_a_non_positive_thickness_or_step():
    with pytest.raises(ValueError):
        plan_windows(_axis(), 0, 5)
    with pytest.raises(ValueError):
        plan_windows(_axis(), 5, 0)


def test_a_windows_time_span_is_n_minus_one_sample_intervals():
    """Levels are POINT samples -- plan_line resamples at each level's
    exact time by linear interpolation, it does not integrate a bin -- so
    n levels span (n - 1) * dz, not n * dz. The plausible wrong version
    (k1 * dz, i.e. n * dz) is off by one interval at every thickness, and
    at thickness 1 it reports a 0.5 ns window where the truth is a single
    sample."""
    z = _axis(nz=100, dz=0.5, t0=2.0)
    assert window_times_ns(z, SliceWindow(10, 20)) == pytest.approx((7.0, 11.5))
    assert window_times_ns(z, SliceWindow(10, 11)) == pytest.approx((7.0, 7.0))


def test_the_label_reports_what_level_range_actually_returned_not_what_was_asked_for():
    """Spec 6.6 and ZAxis.level_range's own docstring: at either end of the
    axis the returned window is genuinely thinner than requested. A label
    derived from (top_ns, thickness_ns) instead of from (k0, k1) claims a
    window that was never averaged."""
    z = _axis(nz=100, dz=0.5, t0=0.0)  # axis covers 0.0 .. 49.5 ns
    k0, k1 = z.level_range(top_ns=48.0, thickness_ns=8.0)  # asks for 8 ns, cannot have it
    assert (k0, k1) == (96, 100)
    lo, hi = window_times_ns(z, SliceWindow(k0, k1))
    assert (lo, hi) == pytest.approx((48.0, 49.5))
    assert hi - lo < 8.0  # the point: what was asked for is not what happened
    assert "48.0" in window_label(z, SliceWindow(k0, k1))
    assert "49.5" in window_label(z, SliceWindow(k0, k1))
    assert "56.0" not in window_label(z, SliceWindow(k0, k1))  # 48 + 8, the wrong answer


def test_the_label_carries_both_units_when_a_velocity_is_given():
    z = _axis(nz=100, dz=0.5, t0=0.0)
    v = VelocityModel.constant(0.08)  # m/ns; depth = v/2 * t
    lo_m, hi_m = window_depths_m(z, SliceWindow(30, 40), v)
    assert (lo_m, hi_m) == pytest.approx((0.6, 0.78))
    label = window_label(z, SliceWindow(30, 40), v)
    assert "ns" in label and "m" in label
    assert "15.0" in label and "19.5" in label  # the ns range
    # Without a velocity the depth half is simply absent, never invented.
    assert "m" not in window_label(z, SliceWindow(30, 40)).replace("ns", "")
```

- [ ] **Step 8: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'nsgeo.slices.display'`.

- [ ] **Step 9: Implement the window half of `display.py`**

Create `packages/nsgeo-core/src/nsgeo/slices/display.py`:

```python
"""What a slice viewer and a slice exporter need, and nothing a binner does.

Three jobs, each deferred out of M10 because it had no caller there and
this plan gives it one:

* planning the set of windows a stack of slices is cut at, which is the
  one place spec 6.6's independent `(thickness, step)` pair becomes a
  finite list -- the dock's navigation and the exporter's bands are the
  same plan read at different steps;
* saying, in both units, what a window ACTUALLY averaged, derived from
  `(k0, k1)` and never from the `(top_ns, thickness_ns)` that produced
  them;
* the display stretch shared across a cube, and the north-up resample an
  export writes through.

Pure numpy, like the rest of the core.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from nsgeo.render import Normalizer
from nsgeo.slices.cube import SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis, slice_extent
from nsgeo.velocity import VelocityModel


@dataclass(frozen=True)
class SliceWindow:
    """A half-open level range `[k0, k1)`, the unit a slice is cut from.

    Levels, not nanoseconds: the conversion belongs to one `ZAxis`, and
    carrying times here would let a window outlive the axis that gave it
    meaning -- which is precisely the stale-plan hazard the binner's own
    guard exists for.
    """

    k0: int
    k1: int

    def __post_init__(self) -> None:
        if self.k0 < 0:
            raise ValueError(f"k0 must be >= 0, got {self.k0}")
        if self.k1 <= self.k0:
            raise ValueError(f"a window must hold at least one level, got {self.k0}..{self.k1}")

    @property
    def n_levels(self) -> int:
        return self.k1 - self.k0


def plan_windows(z: ZAxis, thickness_levels: int, step_levels: int) -> tuple[SliceWindow, ...]:
    """Every window of `thickness_levels`, starting every `step_levels`.

    Spec 6.6: thickness and step are independent and nothing assumes
    slices tile. `step == thickness` gives abutting windows; `step <
    thickness` gives the overlapping stack that is the standard practice
    and the default. The count is spec 9.4's band formula exactly --
    `(nz - thickness) // step + 1` -- so a GeoTIFF's band count and the
    dock's slice count are the same number by construction rather than by
    two agreeing implementations.

    Only whole windows: a trailing partial window would be thinner than
    every other band in the same file, and a reader comparing bands has no
    way to see that from the pixels.
    """
    if thickness_levels < 1:
        raise ValueError(f"thickness_levels must be >= 1, got {thickness_levels}")
    if step_levels < 1:
        raise ValueError(f"step_levels must be >= 1, got {step_levels}")
    if thickness_levels >= z.nz:
        return (SliceWindow(0, z.nz),)
    tops = range(0, z.nz - thickness_levels + 1, step_levels)
    return tuple(SliceWindow(k, k + thickness_levels) for k in tops)


def window_times_ns(z: ZAxis, window: SliceWindow) -> tuple[float, float]:
    """(first, last) two-way time of the levels the window averages.

    `(n_levels - 1) * dz` wide, not `n_levels * dz`: a level is a point
    sample, not a bin. `plan_line` resamples each level at its exact time
    by linear interpolation between the two nearest recorded samples, so
    averaging n of them averages n points spanning n-1 intervals. The
    off-by-one version overstates every window by one sample interval and,
    at thickness 1, claims a range where there is a single sample.
    """
    if window.k1 > z.nz:
        raise ValueError(f"window {window.k0}..{window.k1} exceeds the axis ({z.nz} levels)")
    return (z.t0_ns + window.k0 * z.dz_ns, z.t0_ns + (window.k1 - 1) * z.dz_ns)


def window_depths_m(z: ZAxis, window: SliceWindow, velocity: VelocityModel) -> tuple[float, float]:
    """The same window in metres, through the velocity model."""
    lo, hi = window_times_ns(z, window)
    depths = velocity.depth_at(np.array([lo, hi], dtype=float))
    return (float(depths[0]), float(depths[1]))


def window_label(z: ZAxis, window: SliceWindow, velocity: VelocityModel | None = None) -> str:
    """`12.0-16.0 ns / 0.60-0.80 m`, or the ns half alone with no velocity.

    Always the window's full range, never its centre: spec 6.6's reason is
    that with overlapping slices the extent of what is being averaged is
    the thing a reader would otherwise mistake for vertical resolution.
    Derived from `window`, which is what `ZAxis.level_range` returned --
    a label rebuilt from the requested top and thickness would claim a
    window the axis refused to give.
    """
    lo, hi = window_times_ns(z, window)
    text = f"{lo:.1f}-{hi:.1f} ns"
    if velocity is not None:
        lo_m, hi_m = window_depths_m(z, window, velocity)
        text += f" / {lo_m:.2f}-{hi_m:.2f} m"
    return text
```

- [ ] **Step 10: Run the window tests and watch them pass**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q`
Expected: 8 passed.

- [ ] **Step 11: Prove the window tests discriminate**

Two mutants, each applied alone, re-run, then reverted:

1. In `window_times_ns`, `(window.k1 - 1)` → `window.k1`. Expect
   `test_a_windows_time_span_is_n_minus_one_sample_intervals` and
   `test_the_label_reports_what_level_range_actually_returned_not_what_was_asked_for` to FAIL.
2. In `plan_windows`, `range(0, z.nz - thickness_levels + 1, step_levels)` →
   `range(0, z.nz, step_levels)`. Expect
   `test_overlapping_windows_match_the_specs_band_count_formula` and
   `test_abutting_windows_tile_the_axis_without_gaps_or_overlap` to FAIL (the last window would
   run past the axis).

Record the observed failure counts and messages in the task report.

- [ ] **Step 12: Commit**

```bash
git add packages/nsgeo-core/src/nsgeo/slices/display.py packages/nsgeo-core/tests/test_slices_display.py
git commit -m "feat(slices): window plans and window labels

(thickness, step) becomes a finite list in one place, so the dock's slice
count and a GeoTIFF's band count are the same number by construction. The
label is derived from (k0, k1), never from the requested top and
thickness -- spec 6.6.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 13: Write the failing tests for the shared stretch**

Append to `packages/nsgeo-core/tests/test_slices_display.py`:

```python
def _cube_with_varying_levels(seed: int = 0) -> SliceCube:
    """A cube whose LEVELS have much more spread than their window means.

    That gap is the whole subject: averaging 10 levels pulls the extremes
    in hard, so a limit measured on raw levels is far too large for the
    slices actually displayed. Built deliberately rather than sampled from
    real data so the effect is unambiguous.
    """
    rng = np.random.default_rng(seed)
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=1.0, nx=20, ny=20, crs="EPSG:32633")
    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=40)
    count = np.ones(frame.n_cells, dtype=np.int32)
    mean = np.abs(rng.standard_normal((z.nz, frame.n_cells))).astype(np.float32)
    prov = Provenance(
        line_keys=("a",),
        preset_name="p",
        steps=(),
        transform="amp_abs",
        velocity=None,
        built_utc="2026-09-19T00:00:00Z",
        core_version="0.1.0.dev0",
    )
    return SliceCube(frame=frame, z=z, mean=mean, count=count, provenance=prov)


def test_the_shared_limit_is_measured_over_displayed_slices_not_raw_levels():
    """The M10 final review's Important 3, now a test. A window mean has
    far lower variance than the levels it averages, so UnipolarClip().
    limit(cube.mean) is systematically too high -- and because the bias is
    uniform across depth, every slice renders dim IDENTICALLY at every
    depth, which reads as 'the data is dim' rather than as a bug. That is
    exactly why it needs a test rather than an eye."""
    cube = _cube_with_varying_levels()
    clip = UnipolarClip()
    over_levels = clip.limit(cube.mean)
    over_slices = shared_limit(cube, thickness_levels=10, clip=clip)
    assert over_slices < over_levels
    assert over_slices / over_levels < 0.8  # measured ~0.55 on this fixture
    # And it really is the limit of what gets shown: every displayed slice
    # sits at or below it apart from the percentile's own tail.
    windows = plan_windows(cube.z, 10, 10)
    shown = np.concatenate([cube.slice_levels(w.k0, w.k1).ravel() for w in windows])
    assert over_slices == pytest.approx(float(np.percentile(shown, clip.percentile)), rel=1e-6)


def test_the_shared_limit_covers_every_level_exactly_once():
    """Abutting windows, so no depth is weighted twice in the percentile.
    A step-1 implementation would weight the middle of the axis ~10x more
    than its ends and shift the limit."""
    cube = _cube_with_varying_levels()
    windows = plan_windows(cube.z, 10, 10)
    assert sum(w.n_levels for w in windows) == cube.z.nz
    assert [w.k0 for w in windows] == [0, 10, 20, 30]


def test_limit_over_slices_ignores_nodata_and_survives_an_all_nodata_slice():
    clip = PercentileClip(percentile=100.0)
    a = np.array([[1.0, np.nan], [np.nan, 3.0]])
    b = np.full((2, 2), np.nan)
    assert limit_over_slices([a, b], clip) == pytest.approx(3.0)
    assert limit_over_slices([b], clip) == 1.0  # the documented empty fallback, never 0 or NaN


def test_limit_over_slices_refuses_an_empty_sequence():
    with pytest.raises(ValueError):
        limit_over_slices([], PercentileClip())
```

- [ ] **Step 14: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q -k "limit or shared"`
Expected: FAIL — `ImportError` for `limit_over_slices` / `shared_limit`.

- [ ] **Step 15: Implement the stretch half**

Append to `display.py`:

```python
def limit_over_slices(slices: Iterable[np.ndarray], clip: Normalizer) -> float:
    """`clip`'s limit measured over every finite value in `slices`.

    Nodata is dropped HERE rather than left to the normaliser, because
    `PercentileClip` and `UnipolarClip` both subsample with a plain stride
    BEFORE filtering non-finite values. On a slice that is ~80% nodata --
    the ordinary case at 0.5 m line spacing and 0.10 m cells, spec 6.4 --
    that would spend four fifths of the sampling budget on NaN and measure
    the percentile from what little survived.
    """
    finite: list[np.ndarray] = []
    for item in slices:
        flat = np.asarray(item, dtype=float).ravel()
        finite.append(flat[np.isfinite(flat)])
    if not finite:
        raise ValueError("limit_over_slices needs at least one slice")
    if all(part.size == 0 for part in finite):
        return clip.limit(np.array([], dtype=float))
    return clip.limit(np.concatenate(finite))


def shared_limit(cube: SliceCube, thickness_levels: int, clip: Normalizer) -> float:
    """One display limit for the whole cube, at the thickness being shown.

    Spec 8: shared across the cube by default so depths stay comparable.
    The thickness is an argument and not a detail, because the stretch is
    a property of `(cube, thickness)` and NOT of the cube: a window mean
    has far lower variance than the levels it averages, so measuring over
    `cube.mean` gives a limit that is systematically too high. On one
    realistic cube `UnipolarClip().limit(cube.mean)` returned 2.59 where
    the correct limit for the displayed 10-level slice was 0.87 -- every
    slice then renders at about a third of its intended brightness,
    identically at every depth, so it reads as dim data rather than as a
    wrong limit. M10 recorded this on `UnipolarClip` and shipped no
    helper, for want of a caller; this is the helper, and the caller is
    the Slices dock.

    Windows abut (`step == thickness`), so every level contributes exactly
    once and no depth is weighted more heavily than another.
    """
    windows = plan_windows(cube.z, thickness_levels, thickness_levels)
    return limit_over_slices((cube.slice_levels(w.k0, w.k1) for w in windows), clip)
```

- [ ] **Step 16: Run and watch them pass**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q`
Expected: 12 passed.

- [ ] **Step 17: Prove the stretch tests discriminate**

Mutate `shared_limit` to `return clip.limit(cube.mean)` — the exact wrong implementation M10's
review measured. Confirm `test_the_shared_limit_is_measured_over_displayed_slices_not_raw_levels`
FAILS. Then mutate `plan_windows(cube.z, thickness_levels, thickness_levels)` to
`plan_windows(cube.z, thickness_levels, 1)` and confirm
`test_the_shared_limit_covers_every_level_exactly_once` FAILS. Revert both; record the measured
ratio `over_slices / over_levels` in the task report.

- [ ] **Step 18: Commit**

```bash
git add packages/nsgeo-core/src/nsgeo/slices/display.py packages/nsgeo-core/tests/test_slices_display.py
git commit -m "feat(slices): shared_limit, the stretch for a cube at a thickness

M10's Important 3 as code: a limit taken over raw levels renders every
slice at ~1/3 brightness, identically at every depth, so it reads as dim
data rather than as a bug.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 19: Write the failing tests for the north-up resample**

Append to `packages/nsgeo-core/tests/test_slices_display.py`:

```python
def _ramp_frame(azimuth: float = 0.0) -> tuple[CubeFrame, np.ndarray]:
    """A frame and a values array whose rows are all different, so a
    vertical flip is visible. `values[0]` is frame-local y index 0."""
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=azimuth, cell=1.0, nx=4, ny=3, crs="EPSG:32633")
    values = np.array([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0], [9.0, 10.0, 11.0, 12.0]])
    return frame, values


def test_north_up_puts_frame_row_zero_at_the_BOTTOM_of_the_raster():
    """The single most likely defect in this function, and invisible in
    any symmetric test fixture. A raster's row 0 is its NORTHERN edge --
    the geotransform's y pixel size is negative -- while a CubeFrame's
    y index 0 is its SOUTHERN edge, because frame-local +Y points north
    at azimuth 0. Getting this wrong mirrors every exported slice
    vertically: the anomalies are all still there, in the wrong place,
    and nothing about the image says so."""
    frame, values = _ramp_frame()
    out, gt = to_north_up(values, frame)
    assert out.shape == (3, 4)
    np.testing.assert_allclose(out[0], [9.0, 10.0, 11.0, 12.0])  # north = frame's LAST row
    np.testing.assert_allclose(out[-1], [1.0, 2.0, 3.0, 4.0])
    np.testing.assert_allclose(out, values[::-1])


def test_north_up_geotransform_is_north_up_and_anchored_at_the_top_left():
    frame, values = _ramp_frame()
    _, gt = to_north_up(values, frame)
    origin_x, px_w, rot_x, origin_y, rot_y, px_h = gt
    assert (origin_x, origin_y) == pytest.approx((0.0, 3.0))  # top-left = (xmin, ymax)
    assert px_w == pytest.approx(1.0)
    assert px_h == pytest.approx(-1.0)  # negative: rows run south
    assert (rot_x, rot_y) == (0.0, 0.0)  # no rotation terms: that is the point of resampling


def test_north_up_of_a_rotated_frame_fills_a_larger_box_and_masks_the_corners():
    """A rotated rectangle does not fill its own bounding box, so the
    corners must come back as nodata rather than as the nearest in-frame
    value -- clamping there would smear a real edge across empty ground."""
    frame, values = _ramp_frame(azimuth=45.0)
    out, _ = to_north_up(values, frame)
    assert out.shape[0] > 3 and out.shape[1] > 4  # the box grew
    assert np.isnan(out[0, 0])  # a corner of the box the frame never reaches
    finite = out[np.isfinite(out)]
    assert finite.size > 0
    assert set(np.unique(finite)) <= set(values.ravel())  # only real cell values, never blended


def test_north_up_never_invents_a_value_outside_the_frame():
    frame, values = _ramp_frame(azimuth=30.0)
    out, _ = to_north_up(values, frame)
    assert np.isnan(out).any()  # there ARE outside cells at this azimuth
    assert np.isfinite(out).any()


def test_north_up_rejects_values_that_do_not_match_the_frame():
    frame, _ = _ramp_frame()
    with pytest.raises(ValueError):
        to_north_up(np.zeros((2, 2)), frame)


def test_north_up_carries_nodata_through_unchanged():
    frame, values = _ramp_frame()
    values = values.copy()
    values[1, 1] = np.nan
    out, _ = to_north_up(values, frame)
    assert np.isnan(out[1, 1])  # row 1 of 3 is its own mirror image
    assert np.isfinite(out[0]).all()
```

- [ ] **Step 20: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q -k north_up`
Expected: FAIL — `ImportError: cannot import name 'to_north_up'`.

- [ ] **Step 21: Implement `to_north_up`**

Append to `display.py`:

```python
def to_north_up(
    values: np.ndarray, frame: CubeFrame
) -> tuple[np.ndarray, tuple[float, float, float, float, float, float]]:
    """Resample a grid-local slice into a north-up raster and its geotransform.

    Spec 3 keeps cells grid-local so a cell column draws from a consistent
    set of traces, and resamples north-up only on the way out, because
    rotated GeoTIFFs are second-class in GDAL and QGIS. This is that one
    resample.

    Returns `(array, geotransform)` where `array` is (h, w) float32 with
    NaN outside the frame, and `geotransform` is GDAL's six-tuple
    `(origin_x, pixel_w, 0, origin_y, 0, -pixel_h)` anchored at the box's
    TOP-LEFT corner.

    Two things to get right, in the order they bite:

    * **Row 0 is north.** A raster's rows run south (the geotransform's
      y pixel size is negative) while a `CubeFrame`'s y index 0 is its
      southern edge, because frame-local +Y is north at azimuth 0. The
      output is therefore the frame's rows reversed, exactly, for an
      axis-aligned frame. Getting this wrong mirrors every slice
      vertically and produces an image that looks entirely plausible.
    * **Outside is nodata, never the nearest cell.** A rotated frame does
      not fill its own bounding box; clamping the corners to the nearest
      in-frame value would smear a real edge out across ground that was
      never surveyed.

    Nearest neighbour, not bilinear: these values are already cell means
    over real traces, and `fill` (spec 6.4) is the one place smoothing is
    a decision the user makes with a radius they can see. Interpolating
    again here would invent structure below the cell size and do it
    invisibly.
    """
    values = np.asarray(values, dtype=float)
    if values.shape != (frame.ny, frame.nx):
        raise ValueError(
            f"values must be {(frame.ny, frame.nx)} to match the frame, got {values.shape}"
        )
    xmin, ymin, xmax, ymax = slice_extent(frame)
    cell = frame.cell
    width = max(1, int(math.ceil((xmax - xmin) / cell)))
    height = max(1, int(math.ceil((ymax - ymin) / cell)))

    # Cell CENTRES, so a sample lands in the middle of its output pixel
    # rather than on a boundary where round-off decides which cell it
    # reads -- the same reason `cell_index` has its own edge tolerance.
    xs = xmin + (np.arange(width, dtype=float) + 0.5) * cell
    ys = ymax - (np.arange(height, dtype=float) + 0.5) * cell  # row 0 is north
    grid_x, grid_y = np.meshgrid(xs, ys)
    world = np.column_stack([grid_x.ravel(), grid_y.ravel()])

    ids = frame.cell_index(world)
    flat = values.reshape(-1)
    # `ids` is -1 outside; clip only so the gather is in-bounds, and let
    # `where` discard those rows. Indexing with a raw -1 would silently
    # read the frame's LAST cell instead.
    gathered = flat[np.clip(ids, 0, flat.size - 1)]
    out = np.where(ids >= 0, gathered, np.nan).reshape(height, width)
    return out.astype(np.float32), (xmin, cell, 0.0, ymax, 0.0, -cell)
```

- [ ] **Step 22: Run and watch them pass**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q`
Expected: 18 passed.

- [ ] **Step 23: Prove the north-up tests discriminate**

Three mutants, one at a time:

1. `ys = ymax - (...)` → `ys = ymin + (...)` (the no-flip version). Expect
   `test_north_up_puts_frame_row_zero_at_the_BOTTOM_of_the_raster` to FAIL.
2. `np.where(ids >= 0, gathered, np.nan)` → `gathered` (clamp instead of mask). Expect
   `test_north_up_of_a_rotated_frame_fills_a_larger_box_and_masks_the_corners` and
   `test_north_up_never_invents_a_value_outside_the_frame` to FAIL.
3. `-cell` → `cell` in the returned geotransform. Expect
   `test_north_up_geotransform_is_north_up_and_anchored_at_the_top_left` to FAIL.

Record all three in the task report.

- [ ] **Step 24: Export the new names and commit**

In `packages/nsgeo-core/src/nsgeo/slices/__init__.py`, add to the existing imports (keeping the
`# noqa: F401` convention and alphabetical order within each line):

```python
from nsgeo.slices.display import (  # noqa: F401
    SliceWindow,
    limit_over_slices,
    plan_windows,
    shared_limit,
    to_north_up,
    window_depths_m,
    window_label,
    window_times_ns,
)
from nsgeo.slices.frame import CubeFrame, ZAxis, slice_extent  # noqa: F401
```

Run the whole core suite, `ruff`, and `mypy` before committing.

```bash
git add packages/nsgeo-core/src/nsgeo packages/nsgeo-core/tests/test_slices_display.py
git commit -m "feat(slices): to_north_up, the one resample out of the grid-local frame

Row 0 is north and outside is nodata; both are the defects a symmetric
fixture cannot see.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 25: Write the failing tests for the fill speedup**

Append to `packages/nsgeo-core/tests/test_slices_fill.py`:

```python
def test_smooth_size_is_never_smaller_than_asked_and_is_five_smooth():
    from nsgeo.slices.fill import _smooth_size

    for n in range(1, 400):
        m = _smooth_size(n)
        assert m >= n, f"_smooth_size({n}) = {m} would WRAP the convolution"
        rest = m
        for p in (2, 3, 5):
            while rest % p == 0:
                rest //= p
        assert rest == 1, f"_smooth_size({n}) = {m} is not 5-smooth"
    assert _smooth_size(1041) == 1080


def _unpadded_fill(values, counts, radius_cells, min_count=0.5):
    """M10's exact formula, at the exact minimum FFT size. The reference
    the padded implementation must agree with -- written out here rather
    than imported, so a change to the shipped one cannot quietly change
    the thing it is checked against."""
    import numpy as np
    from nsgeo.slices.fill import disc_kernel

    values = np.asarray(values, dtype=float)
    counts = np.asarray(counts, dtype=float)
    r = int(radius_cells)
    ny, nx = values.shape
    kernel = disc_kernel(r)
    finite = np.isfinite(values)
    numerator = np.where(finite, values, 0.0) * counts
    denominator = np.where(finite, counts, 0.0)
    shape = (ny + 2 * r, nx + 2 * r)
    spectrum = np.fft.rfft2(kernel, s=shape)
    num = np.fft.irfft2(np.fft.rfft2(numerator, s=shape) * spectrum, s=shape)[r : r + ny, r : r + nx]
    den = np.fft.irfft2(np.fft.rfft2(denominator, s=shape) * spectrum, s=shape)[
        r : r + ny, r : r + nx
    ]
    return np.divide(num, den, out=np.full((ny, nx), np.nan), where=den >= min_count).astype(
        np.float32
    )


@pytest.mark.parametrize(("ny", "nx", "radius"), [(37, 41, 3), (100, 100, 8), (213, 209, 10)])
def test_padding_to_a_smooth_size_does_not_change_the_answer(ny, nx, radius):
    """Zero-padding a linear convolution further can only add zeros past
    the end; the crop window is unmoved. If this ever fails, the crop
    offset is wrong, not the padding."""
    rng = np.random.default_rng(7)
    counts = (rng.random((ny, nx)) < 0.2).astype(float)
    values = np.where(counts > 0, rng.random((ny, nx)) * 10.0, np.nan)
    got = fill(values, counts, radius)
    want = _unpadded_fill(values, counts, radius)
    np.testing.assert_array_equal(np.isfinite(got), np.isfinite(want))  # identical nodata mask
    both = np.isfinite(got)
    np.testing.assert_allclose(got[both], want[both], rtol=1e-5, atol=1e-6)


def test_the_kernel_spectrum_cache_returns_the_same_answer_on_a_second_call():
    """A cached array handed out by reference would be corrupted by any
    caller that wrote into it. Nothing in `fill` does -- it only
    multiplies -- and this pins that: two identical fills either side of a
    different one must agree exactly."""
    rng = np.random.default_rng(11)
    counts = (rng.random((60, 60)) < 0.3).astype(float)
    values = np.where(counts > 0, rng.random((60, 60)), np.nan)
    first = fill(values, counts, 5)
    fill(values, counts, 7)  # a different radius, same shape family
    second = fill(values, counts, 5)
    np.testing.assert_array_equal(np.isfinite(first), np.isfinite(second))
    np.testing.assert_array_equal(first[np.isfinite(first)], second[np.isfinite(second)])


def test_clearing_the_kernel_cache_does_not_change_results():
    from nsgeo.slices.fill import clear_kernel_cache

    rng = np.random.default_rng(13)
    counts = (rng.random((50, 50)) < 0.3).astype(float)
    values = np.where(counts > 0, rng.random((50, 50)), np.nan)
    warm = fill(values, counts, 4)
    clear_kernel_cache()
    cold = fill(values, counts, 4)
    np.testing.assert_array_equal(warm[np.isfinite(warm)], cold[np.isfinite(cold)])
```

- [ ] **Step 26: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_fill.py -q`
Expected: 3 FAIL on `ImportError` for `_smooth_size` / `clear_kernel_cache`;
`test_padding_to_a_smooth_size_does_not_change_the_answer` PASSES already (the shipped fill *is*
the reference today) — that is expected and correct, it becomes the regression guard once padding
lands.

- [ ] **Step 27: Implement the padding and the cache**

In `packages/nsgeo-core/src/nsgeo/slices/fill.py`, add `from functools import lru_cache` to the
imports, and insert after `disc_kernel`:

```python
def _smooth_size(n: int) -> int:
    """The smallest integer >= n whose only prime factors are 2, 3 and 5.

    numpy's FFT is fastest at such lengths and slowest at large primes.
    Because a linear convolution padded further only gains trailing zeros,
    rounding the transform size up is free of any effect on the cropped
    result -- measured 1.1x to 3.2x faster across the sizes a slice
    actually reaches, with the worst case (1021x1019 at r=10) falling from
    361 ms to 114 ms.

    Must never return less than `n`: a short transform would WRAP the
    convolution and corrupt the edges of the slice, silently.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    candidate = n
    while True:
        rest = candidate
        for prime in (2, 3, 5):
            while rest % prime == 0:
                rest //= prime
        if rest == 1:
            return candidate
        candidate += 1


@lru_cache(maxsize=4)
def _kernel_spectrum(radius_cells: int, shape: tuple[int, int]) -> np.ndarray:
    """The disc's transform at a padded size, cached across calls.

    The radius is a live slider (spec 9.2), so the same kernel is
    transformed again on every tick at an unchanged slice shape. Bounded
    at four entries because each is a complex128 array of roughly
    `shape[0] * (shape[1] // 2 + 1) * 16` bytes -- 9.3 MB at the largest
    size measured here, so ~37 MB worst case, released by
    `clear_kernel_cache()`.

    The returned array is SHARED. `fill` only multiplies with it and never
    writes into it; any future caller must do the same or take a copy.
    """
    return np.fft.rfft2(disc_kernel(radius_cells), s=shape)


def clear_kernel_cache() -> None:
    """Drop the cached kernel spectra. Called when a slice source is
    closed, so a large cube's spectra do not outlive the session that
    needed them."""
    _kernel_spectrum.cache_clear()
```

Then in `fill`, replace the three lines

```python
    shape = (ny + 2 * r, nx + 2 * r)
    spectrum = np.fft.rfft2(kernel, s=shape)
```

with

```python
    shape = (_smooth_size(ny + 2 * r), _smooth_size(nx + 2 * r))
    spectrum = _kernel_spectrum(r, shape)
```

and delete the now-unused local `kernel = disc_kernel(r)` binding (`_kernel_spectrum` builds it).

- [ ] **Step 28: Run, and measure**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests -q`
Expected: the full core suite passes, with the four new fill tests.

Then time it and put the numbers in the task report:

```bash
./.venv/bin/python - <<'EOF'
import time
import numpy as np
from nsgeo.slices.fill import fill
rng = np.random.default_rng(0)
for ny, nx in ((300, 300), (600, 600), (1021, 1019)):
    counts = (rng.random((ny, nx)) < 0.2).astype(float)
    values = np.where(counts > 0, rng.random((ny, nx)) * 10, np.nan)
    fill(values, counts, 10)
    t = time.perf_counter()
    for _ in range(5):
        fill(values, counts, 10)
    print(f"{ny}x{nx} r=10: {(time.perf_counter() - t) / 5 * 1e3:.1f} ms")
EOF
```

Expected, on this machine: about 6 / 32 / 114 ms, against M10's 7 / 45 / 361 ms. Report what you
actually get; the point is the shape of the improvement, not the absolute numbers.

- [ ] **Step 29: Prove the fill tests discriminate**

Mutate `_smooth_size` to `return n - 1 if n > 1 else 1` — the wrap-the-convolution defect it
exists to prevent. Confirm `test_smooth_size_is_never_smaller_than_asked_and_is_five_smooth` FAILS
*and* that `test_padding_to_a_smooth_size_does_not_change_the_answer` FAILS at at least one
parametrisation (so the agreement test is genuinely load-bearing and not merely decorative).
Revert. Record both.

- [ ] **Step 30: Add the real-data test**

Append to `packages/nsgeo-core/tests/test_real_files.py`:

```python
def test_the_shared_stretch_on_a_real_cube_uses_most_of_the_colour_table():
    """The M10 measurement, against real GSSI data rather than a fixture.

    Real files are this project's primary validation (spec 11), and this
    is the one place the stretch a user actually sees is checked against
    data that came off an instrument."""
    from nsgeo.processing import build_step
    from nsgeo.render import UnipolarClip, to_index8_unipolar
    from nsgeo.slices.binning import PreparedLine, build_cube, plan_line
    from nsgeo.slices.cube import Provenance
    from nsgeo.slices.display import plan_windows, shared_limit
    from nsgeo.slices.frame import CubeFrame, ZAxis

    prepared = []
    for i, path in enumerate(FILES[:4]):
        header = read_header(path)
        rg = Radargram(
            data=np.asarray(read_samples(path, header)[0], dtype=float),
            dt_ns=header.dt_ns,
            t0_ns=header.position_ns,
        )
        for name in ("time_zero", "dewow", "background_mean", "gain_agc", "amp_envelope"):
            rg = build_step(name).apply(rg)
        n_traces = rg.data.shape[1]
        coords = np.column_stack(
            [np.linspace(0.0, 19.99, n_traces), np.full(n_traces, 0.25 + i * 0.5)]
        )
        prepared.append(
            PreparedLine(
                key=path.name,
                data=rg.data.astype(np.float32),
                dt_ns=rg.dt_ns,
                t0_ns=rg.t0_ns,
                coords=coords,
            )
        )
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=0.2, nx=100, ny=12, crs="EPSG:32633")
    z = ZAxis.from_range(1.0, 40.0, 0.2165)
    plans = [plan_line(p, frame, z) for p in prepared]
    prov = Provenance(
        line_keys=tuple(p.key for p in prepared),
        preset_name="test",
        steps=(),
        transform="amp_envelope",
        velocity=None,
        built_utc="2026-09-19T00:00:00Z",
        core_version="0.1.0.dev0",
    )
    cube = build_cube(prepared, plans, frame, z, prov)

    clip = UnipolarClip()
    thickness = 10
    correct = shared_limit(cube, thickness, clip)
    over_raw_levels = clip.limit(cube.mean)
    assert correct < over_raw_levels  # the direction M10 measured, on real data

    # What it means on screen: at the correct limit the displayed slices
    # span most of the 0-255 table; at the raw-level limit they do not.
    windows = plan_windows(z, thickness, thickness)
    shown = np.concatenate([cube.slice_levels(w.k0, w.k1).ravel() for w in windows])
    shown = shown[np.isfinite(shown)]
    assert np.median(to_index8_unipolar(shown, correct)) > 1.5 * np.median(
        to_index8_unipolar(shown, over_raw_levels)
    )
```

- [ ] **Step 31: Run the real-data test and confirm it is not skipping**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_real_files.py -q -k shared_stretch -v`
Expected: **1 passed, 0 skipped.** A skip here means the symlinked DZT files are missing and the
test validated nothing — stop and fix the symlink rather than proceeding.

Record the two measured limits and the two median indices in the task report.

- [ ] **Step 32: Full verification and commit**

```bash
./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
git add -A packages/nsgeo-core
git commit -m "perf(slices): smooth-size FFT padding and a cached kernel spectrum

The radius is a live slider in M11 and M10's fill built three uncached
FFTs per call at arbitrary padded sizes: 1021x1019 at r=10 falls from 361
ms to 114 ms, bit-comparable to the unpadded result. Still 32 ms at
600x600, so the slider debounces as well.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

**Task 1 is done when:** the core suite is green with ~22 new tests, `ruff` and `mypy` are clean,
every named mutant has been shown to fail its own test, the real-data test ran rather than
skipped, and the fill timings are recorded.

---

