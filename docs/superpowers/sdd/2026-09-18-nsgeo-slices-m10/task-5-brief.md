### Task 5: Streaming, and the fill between lines

Streaming is the default residency: bin only the levels in the current window, hold no cube. It must agree with the resident path exactly, and a property test is what enforces that. The fill is the operation that makes a slice legible at all — at 0.5 m line spacing and 0.10 m cells, about 80% of cells start empty.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/fill.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/binning.py` (add `stream_slice`)
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py`
- Test: `packages/nsgeo-core/tests/test_slices_streaming.py`
- Test: `packages/nsgeo-core/tests/test_slices_fill.py`

**Interfaces:**
- Consumes: everything from Task 4.
- Produces:
  - `stream_slice(lines, plans, frame, z, k0, k1) -> tuple[np.ndarray, np.ndarray]` — `(values (ny, nx) float32 with NaN for empty, coverage (ny, nx) int32)`
  - `disc_kernel(radius_cells: int) -> np.ndarray`
  - `fill(values: np.ndarray, counts: np.ndarray, radius_cells: int, min_count: float = 0.5) -> np.ndarray`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_slices_streaming.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices.binning import PreparedLine, build_cube, plan_line, stream_slice
from nsgeo.slices.cube import Provenance
from nsgeo.slices.frame import CubeFrame, ZAxis


def prov():
    return Provenance(
        line_keys=(), preset_name="p", steps=(), transform="amp_abs",
        velocity=None, built_utc="2026-09-18T00:00:00Z", core_version="0.1.0.dev0",
    )


def make_survey(seed=0, n_lines=6, n_traces=40, n_samples=64):
    rng = np.random.default_rng(seed)
    lines = []
    for i in range(n_lines):
        data = rng.normal(size=(n_samples, n_traces)).astype(np.float32)
        xs = np.linspace(0.05, 5.95, n_traces)
        coords = np.column_stack([xs, np.full(n_traces, 0.25 + i * 0.5)])
        lines.append(
            PreparedLine(key=f"l{i}", data=np.abs(data), dt_ns=0.5, t0_ns=0.0, coords=coords)
        )
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=0.2, nx=30, ny=16, crs="EPSG:32633")
    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=n_samples)
    return lines, frame, z


def test_streaming_a_window_equals_slicing_a_resident_cube():
    """The load-bearing property: the two paths are one algorithm, so the
    default residency cannot quietly disagree with the pinned one."""
    lines, frame, z = make_survey()
    plans = [plan_line(ln, frame, z) for ln in lines]
    cube = build_cube(lines, plans, frame, z, prov())
    for k0, k1 in ((0, 1), (4, 12), (30, 64)):
        streamed, _ = stream_slice(lines, plans, frame, z, k0, k1)
        np.testing.assert_allclose(streamed, cube.slice_levels(k0, k1), rtol=1e-5, atol=1e-6)


def test_streaming_coverage_equals_the_cube_coverage():
    lines, frame, z = make_survey()
    plans = [plan_line(ln, frame, z) for ln in lines]
    cube = build_cube(lines, plans, frame, z, prov())
    _, cov = stream_slice(lines, plans, frame, z, 3, 9)
    np.testing.assert_array_equal(cov, cube.coverage())


def test_streaming_marks_empty_cells_nan():
    lines, frame, z = make_survey()
    plans = [plan_line(ln, frame, z) for ln in lines]
    values, cov = stream_slice(lines, plans, frame, z, 0, 4)
    assert np.isnan(values[cov == 0]).all()
    assert np.isfinite(values[cov > 0]).all()


def test_streaming_rejects_an_inverted_window():
    lines, frame, z = make_survey()
    plans = [plan_line(ln, frame, z) for ln in lines]
    with pytest.raises(ValueError, match="level window"):
        stream_slice(lines, plans, frame, z, 5, 5)
```

Create `packages/nsgeo-core/tests/test_slices_fill.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices.fill import disc_kernel, fill


def test_disc_kernel_is_round_and_odd_sized():
    k = disc_kernel(2)
    assert k.shape == (5, 5)
    assert k[2, 2] == 1.0
    assert k[0, 0] == 0.0  # the corner is outside the disc
    assert k[0, 2] == 1.0


def test_zero_radius_is_a_no_op():
    values = np.array([[1.0, np.nan], [3.0, 4.0]], dtype=np.float32)
    counts = np.array([[1, 0], [1, 1]], dtype=np.float32)
    out = fill(values, counts, radius_cells=0)
    np.testing.assert_array_equal(np.isnan(out), np.isnan(values))
    np.testing.assert_allclose(out[~np.isnan(out)], values[~np.isnan(values)])


def test_fill_reaches_an_empty_cell_from_its_neighbours():
    values = np.full((5, 5), np.nan, dtype=np.float32)
    counts = np.zeros((5, 5), dtype=np.float32)
    values[2, 0] = 10.0
    counts[2, 0] = 1.0
    out = fill(values, counts, radius_cells=2)
    assert out[2, 1] == pytest.approx(10.0)
    assert np.isnan(out[2, 4])  # still beyond the radius


def test_fill_is_a_weighted_mean_not_a_sum():
    values = np.full((3, 3), np.nan, dtype=np.float32)
    counts = np.zeros((3, 3), dtype=np.float32)
    values[1, 0], counts[1, 0] = 2.0, 1.0
    values[1, 2], counts[1, 2] = 4.0, 1.0
    out = fill(values, counts, radius_cells=1)
    assert out[1, 1] == pytest.approx(3.0)


def test_fill_weights_by_count_so_a_busy_cell_counts_more():
    values = np.full((3, 3), np.nan, dtype=np.float32)
    counts = np.zeros((3, 3), dtype=np.float32)
    values[1, 0], counts[1, 0] = 2.0, 3.0
    values[1, 2], counts[1, 2] = 6.0, 1.0
    out = fill(values, counts, radius_cells=1)
    assert out[1, 1] == pytest.approx((2.0 * 3 + 6.0 * 1) / 4.0)


def test_fill_leaves_cells_beyond_every_observation_as_nodata():
    values = np.full((9, 9), np.nan, dtype=np.float32)
    counts = np.zeros((9, 9), dtype=np.float32)
    values[0, 0], counts[0, 0] = 1.0, 1.0
    out = fill(values, counts, radius_cells=1)
    assert np.isnan(out[8, 8])


def test_fill_preserves_a_fully_covered_slice():
    rng = np.random.default_rng(0)
    values = rng.random((8, 8)).astype(np.float32)
    counts = np.ones((8, 8), dtype=np.float32)
    out = fill(values, counts, radius_cells=0)
    np.testing.assert_allclose(out, values)


def test_fill_rejects_a_negative_radius():
    with pytest.raises(ValueError, match="radius_cells"):
        fill(np.zeros((3, 3)), np.ones((3, 3)), radius_cells=-1)


def test_fill_rejects_mismatched_shapes():
    with pytest.raises(ValueError, match="same shape"):
        fill(np.zeros((3, 3)), np.ones((4, 4)), radius_cells=1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest packages/nsgeo-core/tests/test_slices_streaming.py packages/nsgeo-core/tests/test_slices_fill.py -v`
Expected: `ImportError: cannot import name 'stream_slice'` and `ModuleNotFoundError: No module named 'nsgeo.slices.fill'`.

- [ ] **Step 3: Add `stream_slice` to `binning.py`**

Append to `packages/nsgeo-core/src/nsgeo/slices/binning.py`:

```python
def stream_slice(
    lines: Sequence[PreparedLine],
    plans: Sequence[LinePlan],
    frame: CubeFrame,
    z: ZAxis,
    k0: int,
    k1: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """One slice, binned straight from the lines, holding no cube.

    This is the default residency. It is the same algorithm as `build_cube`
    restricted to the levels in the window, and a property test asserts the
    two agree -- if they ever diverge, the mode a user is in would change
    what they see.

    Returns (values, coverage), both shaped (ny, nx); values is NaN where
    coverage is zero.
    """
    if len(lines) != len(plans):
        raise ValueError(f"got {len(lines)} lines and {len(plans)} plans")
    if not 0 <= k0 < k1 <= z.nz:
        raise ValueError(f"level window must satisfy 0 <= k0 < k1 <= {z.nz}, got {k0}..{k1}")
    n_levels = k1 - k0
    total = np.zeros(frame.n_cells, dtype=np.float32)
    count = np.zeros(frame.n_cells, dtype=np.int64)
    for line, plan in zip(lines, plans):
        block = resample_window(line, plan, k0, k1)
        total[plan.cells] += np.add.reduceat(block, plan.starts, axis=1).sum(axis=0)
        count[plan.cells] += plan.counts.astype(np.int64) * n_levels
    values = np.divide(
        total, count, out=np.full(frame.n_cells, np.nan, dtype=np.float32), where=count > 0
    )
    coverage = (count // n_levels).astype(np.int32)
    return (
        values.reshape(frame.ny, frame.nx),
        coverage.reshape(frame.ny, frame.nx),
    )
```

- [ ] **Step 4: Implement `fill.py`**

Create `packages/nsgeo-core/src/nsgeo/slices/fill.py`:

```python
"""Filling the space between lines.

At 0.5 m line spacing and 0.10 m cells about 80% of cells are empty, so
this is most of the picture rather than a cosmetic afterthought.

The fill is one operation: convolve the numerator (value x count) and the
denominator (count) with the same radial kernel, then divide. That single
form is GPRSLICE's oversized search box, and inverse-distance weighting
with a radius, and a uniform disc -- only the kernel differs. Because it
consumes the stored pair rather than replacing it, the radius stays a
slider and the unfilled truth is always still underneath.

numpy only: the convolution goes through rfft2, which needs no scipy.
"""

from __future__ import annotations

import numpy as np


def disc_kernel(radius_cells: int) -> np.ndarray:
    """A flat disc of the given radius, as a (2r+1, 2r+1) float array.

    A disc rather than a square: a box kernel is separable and faster, but
    it is anisotropic and prints square artefacts into the slice, which
    read as structure.
    """
    if radius_cells < 0:
        raise ValueError(f"radius_cells must be >= 0, got {radius_cells}")
    r = int(radius_cells)
    yy, xx = np.ogrid[-r : r + 1, -r : r + 1]
    return ((xx * xx + yy * yy) <= r * r).astype(float)


def fill(
    values: np.ndarray,
    counts: np.ndarray,
    radius_cells: int,
    min_count: float = 0.5,
) -> np.ndarray:
    """Smear (values, counts) with a disc and return the weighted mean.

    Cells whose weighted count stays below `min_count` remain NaN: beyond
    the radius there is no evidence, and inventing a value there is exactly
    the failure mode a coverage-aware design exists to avoid.
    """
    values = np.asarray(values, dtype=float)
    counts = np.asarray(counts, dtype=float)
    if values.shape != counts.shape:
        raise ValueError(
            f"values and counts must have the same shape, got {values.shape} and {counts.shape}"
        )
    if values.ndim != 2:
        raise ValueError(f"expected a 2-D slice, got shape {values.shape}")
    if radius_cells < 0:
        raise ValueError(f"radius_cells must be >= 0, got {radius_cells}")
    if radius_cells == 0:
        out = np.where(counts > 0, values, np.nan)
        return out.astype(np.float32)

    r = int(radius_cells)
    ny, nx = values.shape
    kernel = disc_kernel(r)
    numerator = np.where(np.isfinite(values), values, 0.0) * counts

    shape = (ny + 2 * r, nx + 2 * r)
    spectrum = np.fft.rfft2(kernel, s=shape)
    num = np.fft.irfft2(np.fft.rfft2(numerator, s=shape) * spectrum, s=shape)
    den = np.fft.irfft2(np.fft.rfft2(counts, s=shape) * spectrum, s=shape)
    num = num[r : r + ny, r : r + nx]
    den = den[r : r + ny, r : r + nx]

    out = np.divide(num, den, out=np.full((ny, nx), np.nan), where=den >= min_count)
    return out.astype(np.float32)
```

- [ ] **Step 5: Export from the package**

Add to `packages/nsgeo-core/src/nsgeo/slices/__init__.py`, keeping imports alphabetical:

```python
from nsgeo.slices.binning import (  # noqa: F401
    CoverageError,
    LinePlan,
    PreparedLine,
    build_cube,
    plan_line,
    stream_slice,
)
from nsgeo.slices.cube import Provenance, SliceCube  # noqa: F401
from nsgeo.slices.fill import disc_kernel, fill  # noqa: F401
from nsgeo.slices.frame import CubeFrame, ZAxis  # noqa: F401
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest packages/nsgeo-core/tests/test_slices_streaming.py packages/nsgeo-core/tests/test_slices_fill.py -v`
Expected: all PASS. If `test_streaming_a_window_equals_slicing_a_resident_cube` fails on tolerance rather than on shape, the two paths differ in summation order only — but do **not** loosen the tolerance without checking the difference is genuinely float noise and not an off-by-one in the window.

- [ ] **Step 7: Lint, type-check and commit**

```bash
python -m pytest packages/nsgeo-core/tests -q
ruff check . && ruff format --check .
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
git add packages/nsgeo-core/src/nsgeo/slices packages/nsgeo-core/tests/test_slices_streaming.py packages/nsgeo-core/tests/test_slices_fill.py
git commit -m "feat(slices): streaming slices and the fill between lines

Streaming is the default residency: bin only the levels in the window and
hold no cube. A property test asserts it equals slicing a resident cube,
because otherwise the residency mode would change what a user sees.

The fill convolves value x count and count with the same radial kernel and
divides -- one operation that is GPRSLICE's search box, IDW with a radius,
and a uniform disc at once. Cells with no evidence within the radius stay
NaN rather than being invented.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

