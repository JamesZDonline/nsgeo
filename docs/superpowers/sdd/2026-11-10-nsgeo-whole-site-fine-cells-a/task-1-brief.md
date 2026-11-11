### Task 1: The bilinear rule in the core

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/resample.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` (export `Taps`, `bilinear_taps`,
  `sample`, `sample_counts`)
- Test: `packages/nsgeo-core/tests/test_slices_resample.py` (new)

**Interfaces:**
- Produces:
  - `Taps`, a frozen dataclass with `eq=False` and read-only arrays:
    - `nearest: np.ndarray`: `(n,)` int32, `frame.cell_index(world)` (-1 outside), so the outline
      rule is exactly today's nearest-cell rule;
    - `ix0`, `iy0`: `(n,)` int32, the lower corner of the 2×2 cell block around each point;
    - `tx`, `ty`: `(n,)` float32 in `[0, 1)`;
    - `nx: int`, `ny: int`;
    - `exact: bool`, True when every inside point sits on a cell centre (all `tx == ty == 0`);
    - property `inside -> np.ndarray` (`nearest >= 0`); property `n -> int`; property
      `nbytes -> int`; method `take(index: np.ndarray) -> Taps`.
  - `bilinear_taps(frame: CubeFrame, world: np.ndarray) -> Taps`. `world` is `(n, 2)` in the
    frame's CRS. With `f = frame.to_local(world) / frame.cell - 0.5`, `ix0 = floor(f_x)` and
    `tx = f_x - ix0`, likewise for y.
  - `sample(values: np.ndarray, taps: Taps) -> np.ndarray`: `values` is `(ny, nx)`, and the result
    is `(n,)` float32. Each point blends its four cells with bilinear weights. Corners outside the
    frame or non-finite are dropped and the remaining weights re-normalised. NaN where `nearest` is
    -1, or the nearest cell's value is non-finite. When `taps.exact`, return
    `values.ravel()[nearest]` directly (the fast path).
  - `sample_counts(counts: np.ndarray, taps: Taps) -> np.ndarray`: `(n,)` float32, the smallest
    value among the in-frame corners. NaN if `inside` is False or any in-frame corner is non-finite
    or ≤ 0. Coverage shows "count 0" as NaN, so a gap is never hidden. It can look up to a cell
    wider (spec §5.4).

- [ ] **Step 1: Write the failing tests** in `test_slices_resample.py`:

```python
import math
import numpy as np
import pytest
from nsgeo.slices import CubeFrame, bilinear_taps, sample, sample_counts
from nsgeo.slices.site import SiteLattice
from nsgeo.slices.frame import slice_extent

def frame(azimuth=0.0, nx=12, ny=10, cell=0.5):
    return CubeFrame((500_000.0, 4_000_000.0), azimuth, cell, nx, ny, "EPSG:32616")

def centres(f, pixel):
    return SiteLattice.covering([slice_extent(f)], pixel, f.crs).pixel_centres()

def test_cell_centres_reproduce_the_cells_exactly_and_take_the_fast_path():
    f = frame()
    x_hat, y_hat = f.axes()
    i, j = np.meshgrid(np.arange(f.nx), np.arange(f.ny))
    local = np.column_stack([(i.ravel() + 0.5) * f.cell, (j.ravel() + 0.5) * f.cell])
    world = np.asarray(f.origin) + local[:, :1] * x_hat + local[:, 1:] * y_hat
    values = np.arange(f.n_cells, dtype=float).reshape(f.ny, f.nx)
    taps = bilinear_taps(f, world)
    assert taps.exact
    np.testing.assert_array_equal(sample(values, taps), values.ravel().astype(np.float32))

def test_a_point_between_four_cells_is_their_bilinear_blend():
    f = frame()
    values = np.zeros((f.ny, f.nx)); values[2, 3] = 4.0  # one bright cell
    x_hat, y_hat = f.axes()
    # a quarter cell right of and above cell (3, 2)'s centre
    local = np.array([[(3.5 + 0.25) * f.cell, (2.5 + 0.25) * f.cell]])
    world = np.asarray(f.origin) + local[:, :1] * x_hat + local[:, 1:] * y_hat
    assert sample(values, bilinear_taps(f, world))[0] == pytest.approx(4.0 * 0.75 * 0.75)

def test_a_blank_neighbour_is_dropped_and_the_rest_reweighted_not_averaged_as_zero():
    f = frame()
    values = np.full((f.ny, f.nx), 2.0); values[2, 4] = np.nan
    x_hat, y_hat = f.axes()
    local = np.array([[(3.5 + 0.25) * f.cell, (2.5 + 0.25) * f.cell]])  # nearest is (3, 2)
    world = np.asarray(f.origin) + local[:, :1] * x_hat + local[:, 1:] * y_hat
    assert sample(values, bilinear_taps(f, world))[0] == pytest.approx(2.0)

def test_the_outline_does_not_move_blank_exactly_where_the_nearest_cell_is_blank():
    f = frame(azimuth=17.0)
    values = np.ones((f.ny, f.nx)); values[:, :5] = np.nan
    pts = centres(f, f.cell)
    got = sample(values, bilinear_taps(f, pts))
    ids = f.cell_index(pts)
    nearest_blank = (ids < 0) | ~np.isfinite(values.ravel()[np.clip(ids, 0, None)])
    np.testing.assert_array_equal(np.isnan(got), nearest_blank)

@pytest.mark.parametrize("azimuth", [10.497, 30.0, 45.0, 60.0, 89.9])
def test_every_cell_feeds_some_drawn_pixel_at_the_cell_pitch(azimuth):
    f = frame(azimuth=azimuth, nx=40, ny=32)
    for k in range(0, f.n_cells, 97):  # a spread of single bright cells
        values = np.zeros((f.ny, f.nx)); values.ravel()[k] = 1.0
        got = sample(values, bilinear_taps(f, centres(f, f.cell)))
        assert np.nanmax(got) > 0.0, k

def test_counts_take_the_smallest_corner_and_never_hide_a_zero():
    f = frame(azimuth=30.0, nx=20, ny=20)
    counts = np.full((f.ny, f.nx), 3.0); counts[10, 10] = np.nan  # an empty cell
    got = sample_counts(counts, bilinear_taps(f, centres(f, f.cell)))
    finite = got[np.isfinite(got)]
    assert set(np.unique(finite)) == {3.0}  # whole counts, never blended
    taps = bilinear_taps(f, centres(f, f.cell))
    hits = (taps.ix0 <= 10) & (taps.ix0 + 1 >= 10) & (taps.iy0 <= 10) & (taps.iy0 + 1 >= 10) & taps.inside
    assert hits.any() and np.isnan(got[hits]).all()

def test_points_outside_the_frame_are_blank_and_take_keeps_alignment():
    f = frame(azimuth=30.0)
    pts = centres(f, f.cell)
    taps = bilinear_taps(f, pts)
    got = sample(np.ones((f.ny, f.nx)), taps)
    assert np.isnan(got[~taps.inside]).all()
    idx = np.flatnonzero(taps.inside)[::3]
    np.testing.assert_array_equal(sample(np.ones((f.ny, f.nx)), taps.take(idx)), got[idx])
```

- [ ] **Step 2: Run them and see them fail**

  Run: `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_resample.py -q -p no:xonsh -p no:cacheprovider`.
  Expected: an ImportError on `bilinear_taps`.

- [ ] **Step 3: Implement `resample.py`** with the interfaces above.
  - `bilinear_taps` takes `nearest` from `frame.cell_index`, so points a few ulps outside the
    frame's outer edge at UTM scale behave exactly as nearest-cell does today.
  - Snap `f` to the nearest integer when within `64 * eps * max(1, |world|) / cell`, the same
    scale-aware margin `cell_index` uses, so a cell centre gives `tx == 0` exactly, not 0.9999999
    one cell over. Make the arrays read-only (`setflags(write=False)`).
  The module docstring states the rule and why: amplitudes are compared relatively (author,
  2026-11-06). It also says that this replaces half pitch, with the spec's measurements: 2.7% of
  cells dropped by nearest-cell at the cell size at 10.5°, and 23% of zoomed-in pixels showing a
  neighbour at half pitch.
- [ ] **Step 4: Run the tests and see them pass**, plus ruff and mypy as CI runs them.
- [ ] **Step 5: Commit**: `feat(slices): bilinear taps and samplers for north-up pictures`.

---

