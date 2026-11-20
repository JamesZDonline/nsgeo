### Task 4: `SliceCube` and the binner

The resident build: prepared lines in, a z-major cube of means plus a per-cell count out.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/cube.py`
- Create: `packages/nsgeo-core/src/nsgeo/slices/binning.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py`
- Test: `packages/nsgeo-core/tests/test_slices_binning.py`

**Interfaces:**
- Consumes: `CubeFrame`, `ZAxis` from Task 1.
- Produces:
  - `Provenance(line_keys, preset_name, steps, transform, velocity, built_utc, core_version)`, frozen, with `.to_dict()` / `.from_dict()`
  - `SliceCube(frame, z, mean, count, provenance)`, frozen, with `.slice_levels(k0, k1) -> np.ndarray` (shape `(ny, nx)`) and `.coverage() -> np.ndarray` (shape `(ny, nx)`, int32)
  - `PreparedLine(key: str, data: np.ndarray, dt_ns: float, t0_ns: float, coords: np.ndarray)`
  - `LinePlan(z_index, z_weight, order, starts, cells, counts)`
  - `CoverageError(Exception)`
  - `plan_line(line: PreparedLine, frame: CubeFrame, z: ZAxis) -> LinePlan`
  - `build_cube(lines, plans, frame, z, provenance) -> SliceCube`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_slices_binning.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices.binning import CoverageError, PreparedLine, build_cube, plan_line
from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis


def frame(nx=4, ny=3, cell=1.0):
    return CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=cell, nx=nx, ny=ny, crs="EPSG:32633")


def axis(nz=5, dz=1.0, t0=0.0):
    return ZAxis(t0_ns=t0, dz_ns=dz, nz=nz)


def prov():
    return Provenance(
        line_keys=("a.dzt",), preset_name="p", steps=(), transform="amp_abs",
        velocity=None, built_utc="2026-09-18T00:00:00Z", core_version="0.1.0.dev0",
    )


def line(key="a.dzt", value=1.0, n_samples=8, xs=(0.5, 1.5, 2.5), y=0.5, dt_ns=1.0, t0_ns=0.0):
    data = np.full((n_samples, len(xs)), value, dtype=np.float32)
    coords = np.column_stack([np.asarray(xs, dtype=float), np.full(len(xs), y)])
    return PreparedLine(key=key, data=data, dt_ns=dt_ns, t0_ns=t0_ns, coords=coords)


def cube_of(lines, f=None, z=None):
    f = f or frame()
    z = z or axis()
    plans = [plan_line(ln, f, z) for ln in lines]
    return build_cube(lines, plans, f, z, prov())


def test_a_constant_line_bins_to_that_constant():
    cube = cube_of([line(value=7.0)])
    got = cube.slice_levels(0, 5)
    np.testing.assert_allclose(got[0, :3], 7.0)


def test_cells_with_no_traces_are_nan_not_zero():
    """Zero is an ordinary amplitude. Absence must be distinguishable."""
    cube = cube_of([line()])
    got = cube.slice_levels(0, 5)
    assert np.isnan(got[1, 0])
    assert np.isnan(got[0, 3])


def test_count_records_traces_per_cell():
    cube = cube_of([line(xs=(0.2, 0.4, 1.5))])
    cov = cube.coverage()
    assert cov[0, 0] == 2
    assert cov[0, 1] == 1
    assert cov[0, 2] == 0


def test_two_lines_in_one_cell_average_rather_than_sum():
    cube = cube_of([line(key="a", value=2.0), line(key="b", value=4.0)])
    np.testing.assert_allclose(cube.slice_levels(0, 5)[0, 0], 3.0)


def test_traces_outside_the_frame_are_dropped_not_clipped():
    """Clipping would pile an excluded line onto one border row."""
    cube = cube_of([line(xs=(0.5, 99.0))])
    assert cube.coverage()[0, 0] == 1
    assert cube.coverage().sum() == 1


def test_a_line_wholly_outside_the_frame_is_an_error():
    f, z = frame(), axis()
    with pytest.raises(CoverageError, match="no traces inside"):
        plan_line(line(xs=(50.0, 60.0)), f, z)


def test_a_line_whose_time_range_misses_the_window_is_rejected_by_name():
    """Rather than counting a zero-padded level as if it were data."""
    f = frame()
    z = ZAxis(t0_ns=0.0, dz_ns=1.0, nz=40)
    with pytest.raises(CoverageError, match="short.dzt"):
        plan_line(line(key="short.dzt", n_samples=8), f, z)


def test_resampling_interpolates_between_source_samples():
    ln = line(n_samples=4, dt_ns=1.0, xs=(0.5,))
    ln.data[:, 0] = np.array([0.0, 10.0, 20.0, 30.0], dtype=np.float32)
    f = frame()
    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=7)
    cube = build_cube([ln], [plan_line(ln, f, z)], f, z, prov())
    column = cube.mean[:, 0]
    np.testing.assert_allclose(column, [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0], rtol=1e-6)


def test_a_line_with_a_different_dt_lands_on_the_same_axis():
    """Files in one grid may differ in dt; the common axis is the point."""
    fine = line(key="fine", n_samples=16, dt_ns=0.5, xs=(0.5,), value=3.0)
    coarse = line(key="coarse", n_samples=8, dt_ns=1.0, xs=(1.5,), value=3.0)
    f, z = frame(), axis(nz=5, dz=1.0)
    plans = [plan_line(fine, f, z), plan_line(coarse, f, z)]
    cube = build_cube([fine, coarse], plans, f, z, prov())
    np.testing.assert_allclose(cube.slice_levels(0, 5)[0, :2], 3.0)


def test_slice_levels_averages_over_the_window():
    ln = line(n_samples=8, xs=(0.5,))
    ln.data[:, 0] = np.arange(8, dtype=np.float32)
    f = frame()
    z = ZAxis(t0_ns=0.0, dz_ns=1.0, nz=8)
    cube = build_cube([ln], [plan_line(ln, f, z)], f, z, prov())
    assert cube.slice_levels(2, 6)[0, 0] == pytest.approx(3.5)


def test_slice_levels_shape_is_ny_by_nx():
    assert cube_of([line()]).slice_levels(0, 2).shape == (3, 4)


def test_cube_rejects_a_mean_of_the_wrong_shape():
    with pytest.raises(ValueError, match="mean must be"):
        SliceCube(
            frame=frame(), z=axis(),
            mean=np.zeros((2, 2), dtype=np.float32),
            count=np.zeros(12, dtype=np.int32),
            provenance=prov(),
        )


def test_provenance_round_trips_through_a_dict():
    p = prov()
    assert Provenance.from_dict(p.to_dict()) == p
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest packages/nsgeo-core/tests/test_slices_binning.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'nsgeo.slices.binning'`.

- [ ] **Step 3: Implement `cube.py`**

Create `packages/nsgeo-core/src/nsgeo/slices/cube.py`:

```python
"""The stored product: a volume of means, and how much data is under each cell.

Layout is z-major, `(nz, n_cells)`, and that is measured rather than
assumed. Cell-major builds 3-15% faster because each cell's column is
contiguous, but z-major extracts a slice 7x faster -- and a slice is
extracted on every thickness and depth change, where a rebuild happens only
when dz or the cell size moves. Paying 15% on the rare operation makes the
constant one free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np

from nsgeo.slices.frame import CubeFrame, ZAxis


@dataclass(frozen=True)
class Provenance:
    """What a reader needs in order to trust a cube.

    Kept as plain data so it survives a round trip through JSON without
    reaching back into the model: a cube outlives the session that built it
    and may be read by a front end that never loaded the site.
    """

    line_keys: Tuple[str, ...]
    preset_name: str
    steps: Tuple[Dict[str, Any], ...]
    transform: str
    velocity: Optional[Dict[str, Any]]
    built_utc: str
    core_version: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line_keys": list(self.line_keys),
            "preset_name": self.preset_name,
            "steps": [dict(s) for s in self.steps],
            "transform": self.transform,
            "velocity": self.velocity,
            "built_utc": self.built_utc,
            "core_version": self.core_version,
        }

    @classmethod
    def from_dict(cls, doc: Dict[str, Any]) -> Provenance:
        return cls(
            line_keys=tuple(doc["line_keys"]),
            preset_name=doc["preset_name"],
            steps=tuple(dict(s) for s in doc.get("steps", ())),
            transform=doc["transform"],
            velocity=doc.get("velocity"),
            built_utc=doc["built_utc"],
            core_version=doc["core_version"],
        )


@dataclass(frozen=True)
class SliceCube:
    """Binned amplitude over a frame and a z axis.

    `mean` is NaN wherever `count` is zero. `count` is per cell rather than
    per (level, cell), which is exact only because the binner rejects any
    line whose time range does not span the whole axis -- so a cell is
    either covered at every level or at none. That is what lets
    `slice_levels` use a plain mean instead of nanmean.
    """

    frame: CubeFrame
    z: ZAxis
    mean: np.ndarray
    count: np.ndarray
    provenance: Provenance

    def __post_init__(self) -> None:
        expected = (self.z.nz, self.frame.n_cells)
        if self.mean.shape != expected:
            raise ValueError(f"mean must be {expected}, got {self.mean.shape}")
        if self.count.shape != (self.frame.n_cells,):
            raise ValueError(
                f"count must be ({self.frame.n_cells},), got {self.count.shape}"
            )

    def slice_levels(self, k0: int, k1: int) -> np.ndarray:
        """Mean over the half-open level window, shaped (ny, nx).

        A plain mean, not nanmean: coverage does not vary with level, so a
        NaN column is NaN at every level and propagates correctly -- and
        nanmean over a mostly-empty slice costs far more.
        """
        if not 0 <= k0 < k1 <= self.z.nz:
            raise ValueError(
                f"level window must satisfy 0 <= k0 < k1 <= {self.z.nz}, got {k0}..{k1}"
            )
        flat = self.mean[k0:k1].mean(axis=0)
        return flat.reshape(self.frame.ny, self.frame.nx)

    def coverage(self) -> np.ndarray:
        """Traces contributing to each cell, shaped (ny, nx)."""
        return self.count.reshape(self.frame.ny, self.frame.nx)
```

- [ ] **Step 4: Implement `binning.py`**

Create `packages/nsgeo-core/src/nsgeo/slices/binning.py`:

```python
"""Turning prepared lines into a cube.

Two things are precomputed per line, because each changes only when its own
input changes: the source (index, weight) pair per target level, which
depends on the z axis and the line's own dt and t0; and the trace ordering
by cell, which depends on the cell size. With both in hand a rebuild is two
gathers, one `reduceat` and a scatter -- no Python loop over cells or
levels.

The inputs are already-prepared lines: loaded, run through a preset, and
transformed. That tier is the expensive one and the caller caches it; it is
deliberately not this module's business.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np

from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis


class CoverageError(Exception):
    """A line cannot contribute to the requested cube."""


@dataclass(frozen=True)
class PreparedLine:
    """One line, already processed and transformed, ready to bin.

    `data` is (n_samples, n_traces); `coords` is (n_traces, 2) in the
    frame's CRS. Trace index is the join between them, which is the same
    invariant the profile viewer relies on.
    """

    key: str
    data: np.ndarray
    dt_ns: float
    t0_ns: float
    coords: np.ndarray

    def __post_init__(self) -> None:
        if self.data.ndim != 2:
            raise ValueError(f"data must be 2-D, got {self.data.shape}")
        if self.coords.shape != (self.data.shape[1], 2):
            raise ValueError(
                f"line {self.key!r}: {self.data.shape[1]} traces but "
                f"{self.coords.shape} coordinates"
            )


@dataclass(frozen=True)
class LinePlan:
    """Everything about one line that does not change when the window moves."""

    z_index: np.ndarray
    z_weight: np.ndarray
    order: np.ndarray
    starts: np.ndarray
    cells: np.ndarray
    counts: np.ndarray


def plan_line(line: PreparedLine, frame: CubeFrame, z: ZAxis) -> LinePlan:
    """Precompute the resampling and grouping for one line.

    Raises CoverageError rather than zero-padding a line whose recording
    window is shorter than the cube's: a padded level would be counted as
    data and read as a dead zone at that depth.
    """
    n_samples = line.data.shape[0]
    if n_samples < 2:
        raise CoverageError(f"line {line.key!r} has {n_samples} samples; need at least 2")
    line_end = line.t0_ns + (n_samples - 1) * line.dt_ns
    tol = 1e-9
    if z.t0_ns < line.t0_ns - tol or z.t_end_ns > line_end + tol:
        raise CoverageError(
            f"line {line.key!r} spans {line.t0_ns:.3f}..{line_end:.3f} ns, which does "
            f"not cover the cube's {z.t0_ns:.3f}..{z.t_end_ns:.3f} ns; shrink the z "
            f"range or exclude the line"
        )

    position = (z.times_ns() - line.t0_ns) / line.dt_ns
    z_index = np.clip(np.floor(position).astype(np.intp), 0, n_samples - 2)
    z_weight = (position - z_index).astype(np.float32)[:, None]

    ids = frame.cell_index(line.coords)
    keep = np.flatnonzero(ids >= 0)
    if keep.size == 0:
        raise CoverageError(f"line {line.key!r} has no traces inside the cube frame")
    order = keep[np.argsort(ids[keep], kind="stable")]
    sorted_ids = ids[order]
    starts = np.flatnonzero(np.concatenate([[True], sorted_ids[1:] != sorted_ids[:-1]]))
    run_ends = np.concatenate([starts[1:], [sorted_ids.size]])
    return LinePlan(
        z_index=z_index,
        z_weight=z_weight,
        order=order,
        starts=starts,
        cells=sorted_ids[starts],
        counts=(run_ends - starts).astype(np.int32),
    )


def resample_window(line: PreparedLine, plan: LinePlan, k0: int, k1: int) -> np.ndarray:
    """(k1 - k0, n_kept) float32: the line's levels, in cell-sorted order."""
    index = plan.z_index[k0:k1]
    weight = plan.z_weight[k0:k1]
    lower = line.data[index][:, plan.order]
    upper = line.data[index + 1][:, plan.order]
    return (lower * (1.0 - weight) + upper * weight).astype(np.float32, copy=False)


def accumulate(
    total: np.ndarray,
    count: np.ndarray,
    line: PreparedLine,
    plan: LinePlan,
    k0: int,
    k1: int,
) -> None:
    """Add one line's contribution, in place."""
    block = resample_window(line, plan, k0, k1)
    total[:, plan.cells] += np.add.reduceat(block, plan.starts, axis=1)
    count[plan.cells] += plan.counts


def build_cube(
    lines: Sequence[PreparedLine],
    plans: Sequence[LinePlan],
    frame: CubeFrame,
    z: ZAxis,
    provenance: Provenance,
) -> SliceCube:
    """Bin every line into a resident cube."""
    if len(lines) != len(plans):
        raise ValueError(f"got {len(lines)} lines and {len(plans)} plans")
    total = np.zeros((z.nz, frame.n_cells), dtype=np.float32)
    count = np.zeros(frame.n_cells, dtype=np.int32)
    for line, plan in zip(lines, plans):
        accumulate(total, count, line, plan, 0, z.nz)
    mean = np.divide(
        total, count, out=np.full_like(total, np.nan), where=count > 0
    )
    return SliceCube(frame=frame, z=z, mean=mean, count=count, provenance=provenance)


def slice_extent(frame: CubeFrame) -> Tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) of the frame in its own local metres."""
    return (0.0, 0.0, frame.nx * frame.cell, frame.ny * frame.cell)
```

- [ ] **Step 5: Export from the package**

Replace the import line in `packages/nsgeo-core/src/nsgeo/slices/__init__.py`:

```python
from nsgeo.slices.binning import (  # noqa: F401
    CoverageError,
    LinePlan,
    PreparedLine,
    build_cube,
    plan_line,
)
from nsgeo.slices.cube import Provenance, SliceCube  # noqa: F401
from nsgeo.slices.frame import CubeFrame, ZAxis  # noqa: F401
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest packages/nsgeo-core/tests/test_slices_binning.py -v`
Expected: all PASS.

- [ ] **Step 7: Lint, type-check and commit**

```bash
python -m pytest packages/nsgeo-core/tests -q
ruff check . && ruff format --check .
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
git add packages/nsgeo-core/src/nsgeo/slices packages/nsgeo-core/tests/test_slices_binning.py
git commit -m "feat(slices): SliceCube and the binner

Prepared lines in, a z-major cube of means plus a per-cell count out. The
layout is measured: cell-major builds 3-15% faster, z-major extracts a
slice 7x faster, and slices are extracted far more often than cubes are
built.

Empty cells are NaN rather than zero, because zero is an ordinary
amplitude. A line whose recording window is shorter than the cube's is
rejected by name rather than zero-padded, since a padded level would
count as data and read as a dead zone.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

