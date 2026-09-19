# M10 — the slice cube in nsgeo-core, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `nsgeo-core` everything needed to turn a grid of processed GPR lines into horizontal amplitude slices — frame, vertical axis, amplitude transforms, binning, streaming, filling, unipolar rendering and persistence — with no UI and no QGIS.

**Architecture:** Lines are prepared once (load, preset, transform) and cached by the caller; that tier is deliberately *not* in this plan. Everything here consumes already-prepared lines. Binning is a two-gather resample onto a common `ZAxis` followed by a `reduceat` segmented sum into a z-major `(nz, n_cells)` array of means plus a per-cell count. The same operation restricted to a level window is the streaming path, and the two must agree exactly. Filling between lines is an FFT convolution of the `mean × count` and `count` pairs with a radial kernel.

**Tech Stack:** Python ≥ 3.9, numpy only. pytest. No scipy, no matplotlib, no Qt, no QGIS.

**Spec:** `docs/superpowers/specs/2026-09-18-nsgeo-slices-design.md`

## Global Constraints

Every task's requirements implicitly include all of these.

- **Python floor is 3.9** (`requires-python = ">=3.9"`, ruff `target-version = "py39"`). Every module starts with `from __future__ import annotations`. No `X | Y` unions evaluated at runtime, no `match`, no `itertools.pairwise`.
- **numpy is the only runtime dependency of `nsgeo-core`.** No scipy, no matplotlib. `import qgis` or `PyQt` anywhere under `src/nsgeo/` fails `tests/test_boundary.py`.
- **ruff:** `line-length = 100`, lint rules `E, F, I, UP, B, SIM`. Run `ruff check .` and `ruff format --check .` from the repo root.
- **mypy:** `disallow_untyped_defs = true`. Every function you add needs annotations, tests included where the repo already annotates them (it mostly does not annotate test functions — follow the surrounding file).
- **A step name may be claimed exactly once** (`register` raises on a conflicting re-registration). The three names this plan adds are `amp_abs`, `amp_square`, `amp_envelope`.
- **Real data is the primary validation.** `packages/nsgeo-core/tests/data/local/` holds ten real GSSI files and is gitignored; tests over it must `pytest.mark.skipif` when absent, following `tests/test_real_files.py`.
- **Test commands**, from the repo root:
  - `python -m pytest packages/nsgeo-core/tests -v`
  - `ruff check . && ruff format --check .`
  - `mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src`
- **Commit messages** end with the trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Measured facts** this plan relies on, from the real files: 512 samples, 110.86 ns range, `dt = 0.2165 ns`, `t0 = -11.086 ns`, ε_r 14; after the four-step preset `time_zero → dewow → background_mean → gain_agc` the array is 463 × 608, and **463 is prime**.

## File Structure

| File | Responsibility |
|---|---|
| `src/nsgeo/slices/__init__.py` | Public surface of the slice package |
| `src/nsgeo/slices/frame.py` | `CubeFrame` (where cells are), `ZAxis` (what the vertical axis means) |
| `src/nsgeo/slices/cube.py` | `Provenance`, `SliceCube` — the stored product and its invariants |
| `src/nsgeo/slices/binning.py` | `PreparedLine`, `LinePlan`, `plan_line`, `build_cube`, `stream_slice` |
| `src/nsgeo/slices/fill.py` | `disc_kernel`, `fill` — the smear between lines |
| `src/nsgeo/slices/store.py` | `save_cube`, `load_cube` — the `.npz` on disk |
| `src/nsgeo/processing/amplitude.py` | `amp_abs`, `amp_square`, `amp_envelope` steps and `analytic_envelope` |
| `src/nsgeo/processing/base.py` (modify) | `is_unipolar` helper |
| `src/nsgeo/processing/stack.py` (modify) | `StepStack.output_unipolar` |
| `src/nsgeo/processing/__init__.py` (modify) | Import `amplitude` so the steps register |
| `src/nsgeo/render.py` (modify) | `UnipolarClip`, `to_index8_unipolar`, `to_rgba8`, unipolar colour tables |
| `src/nsgeo/project.py` (modify) | `cubes` in the survey JSON |
| `src/nsgeo/model/survey.py` (modify) | `Site.cubes` |

`slices/` is a package rather than one module because `frame`, `binning` and `fill` have genuinely separate reasons to change, and `binning.py` is the only one that needs to hold two algorithms in mind at once.

---

### Task 1: `CubeFrame` and `ZAxis`

The two coordinate objects a cube needs. A `CubeFrame` is deliberately **not** a `Grid`: a `Grid` is a survey frame with continuous extents, where a cube needs integer cell counts — and a cube must be constructible for lines belonging to no grid at all, because binning never learns that lines were parallel.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/__init__.py`
- Create: `packages/nsgeo-core/src/nsgeo/slices/frame.py`
- Test: `packages/nsgeo-core/tests/test_slices_frame.py`

**Interfaces:**
- Consumes: `nsgeo.geometry.grid.Grid` (fields `origin`, `azimuth`, `size_x`, `size_y`, `crs`), `nsgeo.velocity.VelocityModel.depth_at`.
- Produces:
  - `CubeFrame(origin: tuple[float, float], azimuth: float, cell: float, nx: int, ny: int, crs: str)`, frozen dataclass
  - `CubeFrame.n_cells -> int`, `.axes() -> tuple[np.ndarray, np.ndarray]`, `.to_local(world) -> np.ndarray`, `.cell_index(world) -> np.ndarray` (flat `iy * nx + ix`, `-1` outside)
  - `CubeFrame.for_grid(grid, cell) -> CubeFrame`, `CubeFrame.for_points(world, cell, crs, azimuth=0.0, margin=0.0) -> CubeFrame`
  - `ZAxis(t0_ns: float, dz_ns: float, nz: int)`, frozen dataclass, with `.times_ns()`, `.t_end_ns`, `.depths_m(velocity)`, `.from_range(t0_ns, t1_ns, dz_ns)`, `.level_range(top_ns, thickness_ns) -> tuple[int, int]`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_slices_frame.py`:

```python
from __future__ import annotations

import math

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.slices.frame import CubeFrame, ZAxis
from nsgeo.velocity import VelocityModel


def frame(**kw):
    base = dict(origin=(0.0, 0.0), azimuth=0.0, cell=1.0, nx=4, ny=3, crs="EPSG:32633")
    base.update(kw)
    return CubeFrame(**base)


def test_n_cells_is_nx_times_ny():
    assert frame().n_cells == 12


def test_cell_index_is_row_major_iy_times_nx_plus_ix():
    f = frame()
    ids = f.cell_index(np.array([[0.5, 0.5], [3.5, 0.5], [0.5, 2.5]]))
    assert list(ids) == [0, 3, 8]


def test_cell_index_marks_points_outside_as_minus_one():
    """Outside is -1, never clipped: a trace that missed the frame is not
    evidence about its nearest edge cell."""
    f = frame()
    ids = f.cell_index(np.array([[-0.1, 0.5], [4.5, 0.5], [0.5, -2.0], [0.5, 3.5]]))
    assert list(ids) == [-1, -1, -1, -1]


def test_to_local_inverts_the_rotation():
    f = frame(origin=(100.0, 200.0), azimuth=30.0)
    x_hat, y_hat = f.axes()
    world = np.array([100.0, 200.0]) + 2.0 * x_hat + 5.0 * y_hat
    local = f.to_local(world[None, :])
    assert local[0, 0] == pytest.approx(2.0)
    assert local[0, 1] == pytest.approx(5.0)


def test_for_grid_covers_the_whole_grid():
    g = Grid(
        id="A", origin=(10.0, 20.0), azimuth=45.0, size_x=30.0, size_y=20.0,
        crs="EPSG:32633", default_spacing=0.5,
    )
    f = CubeFrame.for_grid(g, cell=0.25)
    assert (f.nx, f.ny) == (120, 80)
    assert f.origin == g.origin
    assert f.azimuth == g.azimuth
    assert f.crs == g.crs


def test_for_grid_rounds_a_ragged_extent_up_rather_than_dropping_it():
    g = Grid(
        id="A", origin=(0.0, 0.0), azimuth=0.0, size_x=10.1, size_y=10.0,
        crs="EPSG:32633", default_spacing=0.5,
    )
    assert CubeFrame.for_grid(g, cell=1.0).nx == 11


def test_for_points_contains_every_point_it_was_built_from():
    rng = np.random.default_rng(0)
    pts = rng.uniform(-5.0, 15.0, size=(200, 2))
    f = CubeFrame.for_points(pts, cell=0.5, crs="EPSG:32633", azimuth=17.0)
    assert (f.cell_index(pts) >= 0).all()


def test_for_points_rejects_an_empty_array():
    with pytest.raises(ValueError, match="non-empty"):
        CubeFrame.for_points(np.empty((0, 2)), cell=0.5, crs="EPSG:32633")


def test_frame_rejects_a_non_positive_cell():
    with pytest.raises(ValueError, match="cell must be positive"):
        frame(cell=0.0)


def test_z_axis_times_start_at_t0_and_step_by_dz():
    z = ZAxis(t0_ns=2.0, dz_ns=0.5, nz=4)
    np.testing.assert_allclose(z.times_ns(), [2.0, 2.5, 3.0, 3.5])
    assert z.t_end_ns == pytest.approx(3.5)


def test_z_axis_from_range_includes_the_end():
    z = ZAxis.from_range(0.0, 50.0, 0.5)
    assert z.nz == 101
    assert z.t_end_ns == pytest.approx(50.0)


def test_z_axis_depths_use_the_velocity_model():
    z = ZAxis(t0_ns=0.0, dz_ns=1.0, nz=3)
    v = VelocityModel.constant(0.08)
    np.testing.assert_allclose(z.depths_m(v), [0.0, 0.04, 0.08])


def test_level_range_is_half_open_and_covers_the_window():
    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=101)
    k0, k1 = z.level_range(top_ns=12.0, thickness_ns=4.0)
    assert (k0, k1) == (24, 32)
    assert z.times_ns()[k0] == pytest.approx(12.0)
    assert z.times_ns()[k1 - 1] == pytest.approx(15.5)


def test_level_range_clamps_to_the_axis_and_never_empties():
    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=10)
    assert z.level_range(top_ns=-99.0, thickness_ns=1.0)[0] == 0
    k0, k1 = z.level_range(top_ns=100.0, thickness_ns=4.0)
    assert k1 == 10 and k1 > k0


def test_z_axis_rejects_a_non_positive_dz():
    with pytest.raises(ValueError, match="dz_ns must be positive"):
        ZAxis(t0_ns=0.0, dz_ns=0.0, nz=5)


def test_azimuth_convention_matches_grid():
    """CubeFrame must turn the same way as Grid or cubes land rotated."""
    g = Grid(
        id="A", origin=(0.0, 0.0), azimuth=37.0, size_x=10.0, size_y=10.0,
        crs="EPSG:32633", default_spacing=0.5,
    )
    f = CubeFrame.for_grid(g, cell=1.0)
    gx, gy = g.axes()
    fx, fy = f.axes()
    np.testing.assert_allclose(gx, fx)
    np.testing.assert_allclose(gy, fy)
    assert math.isclose(f.azimuth, 37.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'nsgeo.slices'`.

- [ ] **Step 3: Create the package and implement the frame**

Create `packages/nsgeo-core/src/nsgeo/slices/__init__.py`:

```python
"""Time and depth slices: binning survey lines into a volume and cutting it.

Nothing here runs automatically. A cube is built from an explicitly chosen
preset, the same rule the step stack follows.
"""

from __future__ import annotations

from nsgeo.slices.frame import CubeFrame, ZAxis  # noqa: F401
```

Create `packages/nsgeo-core/src/nsgeo/slices/frame.py`:

```python
"""Where a cube's cells are, and what its vertical axis means.

A CubeFrame is a raster frame -- integer cell counts and one cell size --
where a Grid is a survey frame with continuous extents and a line spacing.
They are separate types because a cube must exist for lines that belong to
no grid: binning consumes per-trace world coordinates and never learns that
the lines were parallel, so RTK-positioned paths need a frame no Grid
produced. `for_points` is that constructor.

Cells are square. A rectangular cell would let the along-line and
cross-line resolutions be tuned apart, which sounds useful and is not: it
bakes an acquisition artefact into the product, and the fill radius already
covers the real need.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Tuple

import numpy as np

if TYPE_CHECKING:
    from nsgeo.geometry.grid import Grid
    from nsgeo.velocity import VelocityModel


@dataclass(frozen=True)
class CubeFrame:
    """An affine raster frame in world coordinates.

    `azimuth` follows Grid exactly: degrees clockwise from CRS north to
    frame-local +Y. Sharing the convention is what lets `for_grid` copy it
    straight across.
    """

    origin: Tuple[float, float]
    azimuth: float
    cell: float
    nx: int
    ny: int
    crs: str

    def __post_init__(self) -> None:
        if not self.cell > 0.0:
            raise ValueError(f"cell must be positive, got {self.cell}")
        if self.nx < 1 or self.ny < 1:
            raise ValueError(f"nx and ny must be >= 1, got {self.nx} x {self.ny}")

    @property
    def n_cells(self) -> int:
        return self.nx * self.ny

    def axes(self) -> Tuple[np.ndarray, np.ndarray]:
        """Unit vectors of frame-local +X and +Y in world coordinates."""
        a = math.radians(self.azimuth)
        y_hat = np.array([math.sin(a), math.cos(a)])
        x_hat = np.array([math.cos(a), -math.sin(a)])
        return x_hat, y_hat

    def to_local(self, world: np.ndarray) -> np.ndarray:
        """(n, 2) world coordinates -> (n, 2) frame-local metres."""
        world = np.asarray(world, dtype=float)
        if world.ndim != 2 or world.shape[1] != 2:
            raise ValueError(f"expected (n, 2) world coordinates, got {world.shape}")
        x_hat, y_hat = self.axes()
        rel = world - np.asarray(self.origin, dtype=float)
        return np.column_stack([rel @ x_hat, rel @ y_hat])

    def cell_index(self, world: np.ndarray) -> np.ndarray:
        """(n, 2) world coordinates -> (n,) flat cell ids; -1 when outside.

        The flat id is `iy * nx + ix`, which is the column layout SliceCube
        stores. Points outside are -1 rather than clipped to the edge: a
        trace that missed the frame is not evidence about the nearest cell,
        and clipping would pile a whole excluded line onto one border row.
        """
        local = self.to_local(world)
        ix = np.floor(local[:, 0] / self.cell).astype(np.intp)
        iy = np.floor(local[:, 1] / self.cell).astype(np.intp)
        inside = (ix >= 0) & (ix < self.nx) & (iy >= 0) & (iy < self.ny)
        return np.where(inside, iy * self.nx + ix, -1)

    @classmethod
    def for_grid(cls, grid: Grid, cell: float) -> CubeFrame:
        """A frame covering `grid`, sharing its origin, azimuth and CRS.

        Extents round up, so a grid whose size is not a whole number of
        cells is fully covered rather than clipped short.
        """
        if not cell > 0.0:
            raise ValueError(f"cell must be positive, got {cell}")
        return cls(
            origin=grid.origin,
            azimuth=grid.azimuth,
            cell=cell,
            nx=max(1, int(math.ceil(grid.size_x / cell))),
            ny=max(1, int(math.ceil(grid.size_y / cell))),
            crs=grid.crs,
        )

    @classmethod
    def for_points(
        cls,
        world: np.ndarray,
        cell: float,
        crs: str,
        azimuth: float = 0.0,
        margin: float = 0.0,
    ) -> CubeFrame:
        """A frame covering scattered trace coordinates at a given azimuth.

        The constructor for lines that belong to no grid. `azimuth` is the
        caller's: choosing a good one for an arbitrary path is a separate
        problem, and defaulting to 0 gives an axis-aligned frame that is
        always correct if not always tight.
        """
        world = np.asarray(world, dtype=float)
        if world.ndim != 2 or world.shape[1] != 2 or world.shape[0] == 0:
            raise ValueError(f"expected a non-empty (n, 2) array, got {world.shape}")
        if not cell > 0.0:
            raise ValueError(f"cell must be positive, got {cell}")
        a = math.radians(azimuth)
        x_hat = np.array([math.cos(a), -math.sin(a)])
        y_hat = np.array([math.sin(a), math.cos(a)])
        px = world @ x_hat
        py = world @ y_hat
        lo_x = float(px.min()) - margin
        lo_y = float(py.min()) - margin
        hi_x = float(px.max()) + margin
        hi_y = float(py.max()) + margin
        origin = lo_x * x_hat + lo_y * y_hat
        # nextafter keeps a point exactly on the far edge inside the frame:
        # floor((hi - lo) / cell) would otherwise index one cell past the end.
        return cls(
            origin=(float(origin[0]), float(origin[1])),
            azimuth=azimuth,
            cell=cell,
            nx=max(1, int(math.floor((hi_x - lo_x) / cell)) + 1),
            ny=max(1, int(math.floor((hi_y - lo_y) / cell)) + 1),
            crs=crs,
        )


@dataclass(frozen=True)
class ZAxis:
    """The cube's vertical axis, in two-way travel time.

    Time, not depth, because that is what the instrument measures: depth is
    derived through a VelocityModel, so a cube built under one velocity
    relabels under another without rebinning. An elevation-referenced axis
    is designed for and not built -- nothing in the cube's shape assumes
    the axis is time, only this class does.
    """

    t0_ns: float
    dz_ns: float
    nz: int

    def __post_init__(self) -> None:
        if not self.dz_ns > 0.0:
            raise ValueError(f"dz_ns must be positive, got {self.dz_ns}")
        if self.nz < 1:
            raise ValueError(f"nz must be >= 1, got {self.nz}")

    @property
    def t_end_ns(self) -> float:
        return self.t0_ns + (self.nz - 1) * self.dz_ns

    def times_ns(self) -> np.ndarray:
        return self.t0_ns + np.arange(self.nz, dtype=float) * self.dz_ns

    def depths_m(self, velocity: VelocityModel) -> np.ndarray:
        return velocity.depth_at(self.times_ns())

    @classmethod
    def from_range(cls, t0_ns: float, t1_ns: float, dz_ns: float) -> ZAxis:
        if not dz_ns > 0.0:
            raise ValueError(f"dz_ns must be positive, got {dz_ns}")
        if not t1_ns > t0_ns:
            raise ValueError(f"t1_ns must exceed t0_ns, got {t0_ns} .. {t1_ns}")
        return cls(t0_ns=t0_ns, dz_ns=dz_ns, nz=int(math.floor((t1_ns - t0_ns) / dz_ns)) + 1)

    def level_range(self, top_ns: float, thickness_ns: float) -> Tuple[int, int]:
        """Half-open [k0, k1) for a window, clamped to the axis.

        Never returns an empty range: a window entirely off the end still
        yields one level, because a viewer asking for a slice needs a
        slice, not a zero-column array to special-case.
        """
        if not thickness_ns > 0.0:
            raise ValueError(f"thickness_ns must be positive, got {thickness_ns}")
        k0 = int(math.floor((top_ns - self.t0_ns) / self.dz_ns))
        k1 = k0 + max(1, int(round(thickness_ns / self.dz_ns)))
        k0 = max(0, min(k0, self.nz - 1))
        k1 = max(k0 + 1, min(k1, self.nz))
        return k0, k1
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the whole core suite and the linters**

Run:
```bash
python -m pytest packages/nsgeo-core/tests -q
ruff check . && ruff format --check .
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
```
Expected: all pass; `test_boundary.py` in particular still green.

- [ ] **Step 6: Commit**

```bash
git add packages/nsgeo-core/src/nsgeo/slices packages/nsgeo-core/tests/test_slices_frame.py
git commit -m "feat(slices): CubeFrame and ZAxis

A cube frame is a raster frame, not a survey frame, and is deliberately
separate from Grid so lines belonging to no grid can still be binned.
Azimuth follows Grid's convention exactly so for_grid can copy it across.
The z axis is two-way time, with depth derived through VelocityModel.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Amplitude transform steps

Three registry steps, so the transform a cube is built from is one you can put on a profile and *see* rather than a hidden mode. They make the data unipolar, which the renderer must learn about — Task 3 consumes the flag this task adds.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/amplitude.py`
- Modify: `packages/nsgeo-core/src/nsgeo/processing/base.py` (add `is_unipolar`)
- Modify: `packages/nsgeo-core/src/nsgeo/processing/stack.py` (add `output_unipolar`)
- Modify: `packages/nsgeo-core/src/nsgeo/processing/__init__.py` (import `amplitude`, export `is_unipolar`)
- Test: `packages/nsgeo-core/tests/test_steps_amplitude.py`

**Interfaces:**
- Consumes: `ParamSpec`, `Radargram`, `register` from `nsgeo.processing.base`; `build_step`.
- Produces:
  - Steps registered as `"amp_abs"`, `"amp_square"`, `"amp_envelope"`, each taking no parameters and each carrying `unipolar = True`
  - `nsgeo.processing.amplitude.analytic_envelope(data: np.ndarray) -> np.ndarray`
  - `nsgeo.processing.base.is_unipolar(step: Any) -> bool`
  - `nsgeo.processing.stack.StepStack.output_unipolar -> bool`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_steps_amplitude.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.processing import StepStack, build_step
from nsgeo.processing.amplitude import analytic_envelope
from nsgeo.processing.base import Radargram, is_unipolar


def make(data, dt_ns=0.2165, t0_ns=0.0):
    return Radargram(data=np.asarray(data, dtype=float), dt_ns=dt_ns, t0_ns=t0_ns)


def test_amp_abs_removes_the_negative_side():
    rg = make([[-2.0, 3.0], [1.0, -4.0]])
    out = build_step("amp_abs").apply(rg)
    np.testing.assert_allclose(out.data, [[2.0, 3.0], [1.0, 4.0]])


def test_amp_square_is_energy():
    rg = make([[-2.0, 3.0]])
    np.testing.assert_allclose(build_step("amp_square").apply(rg).data, [[4.0, 9.0]])


def test_transforms_preserve_the_time_axis():
    rg = make(np.ones((10, 4)), dt_ns=0.5, t0_ns=-3.0)
    for name in ("amp_abs", "amp_square", "amp_envelope"):
        out = build_step(name).apply(rg)
        assert out.dt_ns == 0.5
        assert out.t0_ns == -3.0
        assert out.data.shape == (10, 4)


def test_envelope_of_a_sinusoid_is_its_amplitude():
    """The defining property: the envelope rides the peaks, not the wave."""
    n = 512
    t = np.arange(n)
    wave = 3.0 * np.sin(2.0 * np.pi * t / 16.0)
    env = analytic_envelope(wave[:, None])[:, 0]
    np.testing.assert_allclose(env[32:-32], 3.0, rtol=1e-6)


def test_envelope_is_never_negative():
    rng = np.random.default_rng(0)
    env = analytic_envelope(rng.normal(size=(97, 5)))
    assert (env >= 0.0).all()


def test_envelope_handles_an_odd_and_prime_length():
    """463 rows is what time_zero leaves on the real files, and it is prime
    -- the worst case for an FFT and the one we deliberately do not pad."""
    rng = np.random.default_rng(1)
    env = analytic_envelope(rng.normal(size=(463, 3)))
    assert env.shape == (463, 3)
    assert np.isfinite(env).all()


def test_envelope_is_not_the_zero_padded_approximation():
    """Padding to a fast length is 2.2x quicker and shifts the interior by
    ~1.3%. Pin the exact transform so that optimisation cannot reappear
    silently."""
    rng = np.random.default_rng(2)
    data = rng.normal(size=(463, 2))
    exact = analytic_envelope(data)
    padded = analytic_envelope(np.pad(data, ((0, 480 - 463), (0, 0))))[:463]
    assert not np.allclose(exact, padded, rtol=1e-3)


def test_all_three_transforms_declare_themselves_unipolar():
    for name in ("amp_abs", "amp_square", "amp_envelope"):
        assert is_unipolar(build_step(name)) is True


def test_ordinary_steps_are_not_unipolar():
    assert is_unipolar(build_step("dewow")) is False


def test_stack_output_unipolar_follows_the_last_enabled_step():
    stack = StepStack()
    stack.source = make(np.ones((8, 4)))
    stack.append(build_step("dewow"))
    assert stack.output_unipolar is False
    stack.append(build_step("amp_abs"))
    assert stack.output_unipolar is True
    stack.set_enabled(1, False)
    assert stack.output_unipolar is False


def test_empty_stack_is_not_unipolar():
    assert StepStack().output_unipolar is False


def test_transforms_take_no_parameters():
    for name in ("amp_abs", "amp_square", "amp_envelope"):
        step = build_step(name)
        assert step.params == {}
        assert step.schema() == ()


def test_unknown_parameter_is_rejected():
    with pytest.raises(ValueError, match="has no parameter"):
        build_step("amp_abs", window_ns=3.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest packages/nsgeo-core/tests/test_steps_amplitude.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'nsgeo.processing.amplitude'`.

- [ ] **Step 3: Implement the transforms**

Create `packages/nsgeo-core/src/nsgeo/processing/amplitude.py`:

```python
"""Amplitude transforms: what a slice is actually made of.

A slice averages amplitude over a time window, and averaging a bipolar
wiggle over a window close to one wavelength gives roughly zero wherever
the reflection is strongest. So the signed radargram is transformed first:
absolute value is the cheap default, squared amplitude is the energy
measure the archaeological literature uses, and the Hilbert envelope is
the quality option.

These are registry steps rather than a hidden mode inside the binner so
that the transform can be put on a profile and looked at -- you can see on
a radargram exactly what the cube will be built from.

All three make the data unipolar, which the renderer must know: a colour
table centred on zero would spend half its range on values that cannot
occur. `unipolar = True` is what `render` consults, through
`base.is_unipolar`.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from nsgeo.processing.base import ParamSpec, Radargram, register


def analytic_envelope(data: np.ndarray) -> np.ndarray:
    """Hilbert analytic-signal modulus along axis 0. numpy only, no scipy.

    The analytic signal is built by doubling the positive frequencies of a
    full FFT and zeroing the negative half; its modulus is the envelope.

    The FFT is taken at the array's own length and is **never zero-padded
    to a faster one**. After `time_zero` the real files leave 463 rows,
    which is prime and therefore the worst case for an FFT -- padding to
    480 is 2.2x faster and was measured and rejected, because the Hilbert
    transform is non-local: padding shifts the result by ~1.3% through the
    interior and ~13% in the last rows. This step runs once per line in the
    cached tier, so exactness is the better trade. (Reflect-padding is
    worse than zero-padding here, at ~2.6% interior, not better.)
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError(f"expected a 2-D radargram, got shape {data.shape}")
    n = data.shape[0]
    spectrum = np.fft.fft(data, axis=0)
    weights = np.zeros(n)
    weights[0] = 1.0
    if n % 2 == 0:
        weights[n // 2] = 1.0
        weights[1 : n // 2] = 2.0
    else:
        weights[1 : (n + 1) // 2] = 2.0
    return np.abs(np.fft.ifft(spectrum * weights[:, None], axis=0))


class _NoParams:
    """Shared shape for the three transforms: no parameters, no choices."""

    unipolar = True

    def __init__(self) -> None:
        pass

    @property
    def params(self) -> Dict[str, Any]:
        return {}

    @classmethod
    def schema(cls) -> Tuple[ParamSpec, ...]:
        return ()


@register
class AmpAbs(_NoParams):
    name = "amp_abs"

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=np.abs(rg.data))


@register
class AmpSquare(_NoParams):
    name = "amp_square"

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=rg.data * rg.data)


@register
class AmpEnvelope(_NoParams):
    name = "amp_envelope"

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=analytic_envelope(rg.data))
```

- [ ] **Step 4: Add the `is_unipolar` helper**

In `packages/nsgeo-core/src/nsgeo/processing/base.py`, immediately after the `Step` protocol class, add:

```python
def is_unipolar(step: Any) -> bool:
    """Whether a step's output has no negative side.

    Read with `getattr` rather than declared on the `Step` protocol: every
    existing step is structurally a Step without the attribute, and adding
    a required one would break that silently at type-check time for no
    gain. Absent means bipolar, which is the correct default for every
    step that filters or gains a signed wiggle.
    """
    return bool(getattr(step, "unipolar", False))
```

- [ ] **Step 5: Add `StepStack.output_unipolar`**

In `packages/nsgeo-core/src/nsgeo/processing/stack.py`, change the import line to:

```python
from nsgeo.processing.base import Radargram, build_step, is_unipolar
```

and add this property in the `# ---- inspection ----` section, after `cache_size`:

```python
    @property
    def output_unipolar(self) -> bool:
        """Whether `result()` has no negative side.

        The last *enabled* step decides, because a disabled transform is
        not applied. Consulted by front ends choosing a colour table: a
        bipolar table on unipolar data wastes half its range.
        """
        for step, enabled in reversed(self._entries):
            if enabled:
                return is_unipolar(step)
        return False
```

- [ ] **Step 6: Register the module and export the helper**

In `packages/nsgeo-core/src/nsgeo/processing/__init__.py`, add `amplitude,` to the first import block (keeping alphabetical order, so it goes first) and `is_unipolar,` to the `base` import block (alphabetically, after `get_step`):

```python
from nsgeo.processing import (  # noqa: F401
    amplitude,
    background,
    bandpass,
    dewow,
    gain,
    timezero,
)
from nsgeo.processing.base import (  # noqa: F401
    REQUIRED,
    ParamSpec,
    Radargram,
    Step,
    available_steps,
    build_step,
    default_params,
    get_step,
    is_unipolar,
    nyquist_mhz,
    register,
    required_params,
)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest packages/nsgeo-core/tests/test_steps_amplitude.py -v`
Expected: all PASS.

- [ ] **Step 8: Run the whole core suite**

Run: `python -m pytest packages/nsgeo-core/tests -q`

Expected: all pass. Two existing tests in `tests/test_schema.py` iterate every registered step and must still hold — `test_schema_names_match_params_keys_in_order` (trivially true for an empty schema and empty params) and `test_only_the_two_known_steps_have_required_params` (still true, since none of the three declares a `REQUIRED` default). If either fails, the new steps are wrong, not the tests.

- [ ] **Step 9: Lint, type-check and commit**

```bash
ruff check . && ruff format --check .
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
git add packages/nsgeo-core/src/nsgeo/processing packages/nsgeo-core/tests/test_steps_amplitude.py
git commit -m "feat(processing): amp_abs, amp_square and amp_envelope steps

Registry steps rather than a mode inside the binner, so the transform a
cube is built from can be put on a profile and seen. The envelope is an
FFT analytic signal in numpy alone, taken at the array's own length: a
test pins it against the zero-padded approximation, which is 2.2x faster
and wrong by ~1.3% through the interior.

All three declare unipolar = True, read through base.is_unipolar and
surfaced as StepStack.output_unipolar for front ends choosing a palette.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Unipolar rendering

`render.py` maps amplitude symmetrically about zero, which is right for a radargram and wrong for a slice: `to_index8` puts 0 at index 128, so an `|A|` slice uses only the top half of every table and sits on a mid-grey floor. Slices also need genuine nodata, which a 256-entry index cannot express.

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/render.py`
- Test: `packages/nsgeo-core/tests/test_render.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `UnipolarClip(percentile: float = 99.0, max_samples: int = 200_000)` with `.limit(data) -> float`
  - `to_index8_unipolar(data: np.ndarray, limit: float) -> np.ndarray`
  - `to_rgba8(data, limit, lut, *, unipolar: bool) -> np.ndarray` — `(H, W, 4)` uint8, alpha 0 where the input is not finite
  - `UNIPOLAR_COLORMAPS: frozenset[str]`, and `colormap_names(unipolar: bool | None = None)`
  - New tables `"amp_black_high"`, `"amp_white_high"`, `"amp_heat"`

- [ ] **Step 1: Write the failing tests**

Append to `packages/nsgeo-core/tests/test_render.py`:

```python
def test_unipolar_index_puts_zero_at_the_bottom_not_the_middle():
    """The whole point: a bipolar table would floor an |A| slice at grey."""
    out = render.to_index8_unipolar(np.array([[0.0, 0.5, 1.0]]), limit=1.0)
    assert list(out[0]) == [0, 128, 255]


def test_unipolar_index_clips_above_the_limit():
    out = render.to_index8_unipolar(np.array([[2.0, -1.0]]), limit=1.0)
    assert list(out[0]) == [255, 0]


def test_unipolar_clip_uses_the_percentile_of_the_values_themselves():
    """Not of their magnitudes: the data is already non-negative, so a
    percentile over |x| would be the same number computed twice."""
    data = np.concatenate([np.zeros(99), [100.0]])[None, :]
    assert render.UnipolarClip(percentile=100.0).limit(data) == pytest.approx(100.0)
    assert render.UnipolarClip(percentile=90.0).limit(data) == 1.0  # median is 0 -> fallback


def test_unipolar_clip_ignores_nan_nodata():
    data = np.array([[1.0, np.nan, 3.0]])
    assert render.UnipolarClip(percentile=100.0).limit(data) == pytest.approx(3.0)


def test_unipolar_clip_falls_back_when_everything_is_nodata():
    assert render.UnipolarClip().limit(np.full((4, 4), np.nan)) == 1.0


def test_rgba_makes_nodata_transparent_and_data_opaque():
    """A slice cell with no traces under it must not paint as a value."""
    data = np.array([[0.0, np.nan]])
    lut = render.colormap("amp_black_high")
    out = render.to_rgba8(data, limit=1.0, lut=lut, unipolar=True)
    assert out.shape == (1, 2, 4)
    assert out[0, 0, 3] == 255
    assert out[0, 1, 3] == 0


def test_rgba_bipolar_path_matches_the_existing_rgb_mapping():
    data = np.array([[-1.0, 0.0, 1.0]])
    lut = render.colormap("seismic")
    rgba = render.to_rgba8(data, limit=1.0, lut=lut, unipolar=False)
    rgb = render.to_rgb8(data, limit=1.0, lut=lut)
    np.testing.assert_array_equal(rgba[..., :3], rgb)


def test_unipolar_colormaps_are_listed_separately():
    assert set(render.colormap_names(unipolar=True)) == set(render.UNIPOLAR_COLORMAPS)
    assert "seismic" not in render.colormap_names(unipolar=True)
    assert "amp_heat" not in render.colormap_names(unipolar=False)
    assert set(render.colormap_names()) >= set(render.UNIPOLAR_COLORMAPS)


def test_every_colormap_is_a_valid_table():
    for name in render.colormap_names():
        lut = render.colormap(name)
        assert lut.shape == (256, 3)
        assert lut.dtype == np.uint8


def test_amp_black_high_runs_white_to_black():
    lut = render.colormap("amp_black_high")
    assert tuple(lut[0]) == (255, 255, 255)
    assert tuple(lut[255]) == (0, 0, 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest packages/nsgeo-core/tests/test_render.py -v`
Expected: several FAIL with `AttributeError: module 'nsgeo.render' has no attribute 'to_index8_unipolar'`.

- [ ] **Step 3: Implement the unipolar path**

In `packages/nsgeo-core/src/nsgeo/render.py`, add after the `FixedRange` class:

```python
@dataclass(frozen=True)
class UnipolarClip:
    """Limit for data with no negative side: 0 maps to 0, limit to 255.

    Drop-in for PercentileClip, but the percentile is taken over the values
    themselves rather than their magnitudes, because they are already
    non-negative. NaN is nodata, not a value, and is excluded before the
    percentile so an unsurveyed corner cannot decide the stretch.
    """

    percentile: float = 99.0
    max_samples: int = 200_000

    def __post_init__(self) -> None:
        if not 0.0 < self.percentile <= 100.0:
            raise ValueError(f"percentile must be in (0, 100], got {self.percentile}")
        if self.max_samples < 1:
            raise ValueError(f"max_samples must be >= 1, got {self.max_samples}")

    def limit(self, data: np.ndarray) -> float:
        flat = np.asarray(data, dtype=float).ravel()
        if flat.size > self.max_samples:
            flat = flat[:: int(math.ceil(flat.size / self.max_samples))]
        finite = flat[np.isfinite(flat)]
        if finite.size == 0:
            return 1.0
        lim = float(np.percentile(finite, self.percentile))
        return lim if lim > 0.0 else 1.0
```

Add the unipolar tables next to `_seismic`:

```python
def _amp_grey(black_high: bool) -> np.ndarray:
    ramp = np.linspace(255.0, 0.0, 256) if black_high else np.linspace(0.0, 255.0, 256)
    g = np.round(ramp).astype(np.uint8)
    return np.stack([g, g, g], axis=1)


def _amp_heat() -> np.ndarray:
    """Black through red and orange to white: the unipolar table that reads
    as intensity rather than as a signed deviation."""
    t = np.linspace(0.0, 1.0, 256)
    r = np.clip(t * 3.0, 0.0, 1.0)
    g = np.clip(t * 3.0 - 1.0, 0.0, 1.0)
    b = np.clip(t * 3.0 - 2.0, 0.0, 1.0)
    return np.round(np.stack([r, g, b], axis=1) * 255.0).astype(np.uint8)
```

Extend the registry and the listing (replacing the existing `_COLORMAPS` dict and `colormap_names`):

```python
_COLORMAPS: dict[str, np.ndarray] = {
    "grey_black_high": _grey(black_high=True),
    "grey_white_high": _grey(black_high=False),
    "seismic": _seismic(),
    "amp_black_high": _amp_grey(black_high=True),
    "amp_white_high": _amp_grey(black_high=False),
    "amp_heat": _amp_heat(),
}

#: Tables meant for data with no negative side. Putting a bipolar table on
#: unipolar data is a configuration error, not a style choice: half of it
#: addresses values that cannot occur.
UNIPOLAR_COLORMAPS = frozenset({"amp_black_high", "amp_white_high", "amp_heat"})


def colormap_names(unipolar: bool | None = None) -> list[str]:
    """Table names; `unipolar` filters to (or away from) the slice tables."""
    if unipolar is None:
        return list(_COLORMAPS)
    if unipolar:
        return [n for n in _COLORMAPS if n in UNIPOLAR_COLORMAPS]
    return [n for n in _COLORMAPS if n not in UNIPOLAR_COLORMAPS]
```

Add the index and RGBA functions after `to_rgb8`:

```python
def to_index8_unipolar(data: np.ndarray, limit: float) -> np.ndarray:
    """Map 0..limit to 0..255, clipping outside.

    Non-finite samples land at 0 here and are handled properly by
    `to_rgba8`, which makes them transparent -- index 8 has no spare
    entry to mean "no data", so nodata is an alpha question.
    """
    if not limit > 0.0:
        raise ValueError(f"limit must be positive, got {limit}")
    scaled = np.asarray(data, dtype=np.float64) / limit
    scaled *= 255.0
    np.nan_to_num(scaled, copy=False, nan=0.0, posinf=255.0, neginf=0.0)
    np.clip(scaled, 0.0, 255.0, out=scaled)
    np.rint(scaled, out=scaled)
    return scaled.astype(np.uint8)


def to_rgba8(data: np.ndarray, limit: float, lut: np.ndarray, *, unipolar: bool) -> np.ndarray:
    """(H, W, 4) uint8 with alpha 0 where `data` is not finite.

    Slices need real nodata: a cell with no traces under it must not paint
    as an amplitude, and zero is a perfectly ordinary amplitude. A
    radargram has no nodata, so `unipolar=False` simply reproduces
    `to_rgb8` with a fully opaque alpha channel.
    """
    lut = np.asarray(lut)
    if lut.shape != (256, 3) or lut.dtype != np.uint8:
        raise ValueError(f"lut must be a (256, 3) uint8 table, got {lut.shape} {lut.dtype}")
    values = np.asarray(data, dtype=float)
    index = to_index8_unipolar(values, limit) if unipolar else to_index8(values, limit)
    rgb = lut.take(index, axis=0)
    alpha = np.where(np.isfinite(values), 255, 0).astype(np.uint8)
    return np.ascontiguousarray(np.concatenate([rgb, alpha[..., None]], axis=-1))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest packages/nsgeo-core/tests/test_render.py -v`
Expected: all PASS, existing tests included.

- [ ] **Step 5: Lint, type-check and commit**

```bash
python -m pytest packages/nsgeo-core/tests -q
ruff check . && ruff format --check .
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
git add packages/nsgeo-core/src/nsgeo/render.py packages/nsgeo-core/tests/test_render.py
git commit -m "feat(render): unipolar normaliser, tables and an RGBA path

to_index8 maps symmetrically about zero, which floors an |A| slice at
mid-grey and spends half the table on values that cannot occur. Adds
UnipolarClip, three unipolar tables, and to_rgba8 -- slices need genuine
nodata, and zero is an ordinary amplitude, so absence has to be alpha
rather than a reserved index.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

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

### Task 6: Persistence — the `.npz` and the survey JSON

A cube is derived, like the GeoPackage: the survey JSON records the recipe and points at the array, and a missing array is an offer to rebuild rather than an error. The core writes `.npz` because it has numpy and nothing else — GeoTIFF is the plugin's job, in M11.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/store.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py`
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (add `Site.cubes`)
- Modify: `packages/nsgeo-core/src/nsgeo/project.py` (persist `cubes`)
- Test: `packages/nsgeo-core/tests/test_slices_store.py`
- Test: `packages/nsgeo-core/tests/test_project.py` (append)

**Interfaces:**
- Consumes: `SliceCube`, `CubeFrame`, `ZAxis`, `Provenance`.
- Produces:
  - `save_cube(cube: SliceCube, path: str | Path) -> None`
  - `load_cube(path: str | Path) -> SliceCube`
  - `CubeStoreError(Exception)`
  - `Site.cubes: dict[str, dict[str, Any]]`, persisted under the JSON key `"cubes"`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_slices_store.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis
from nsgeo.slices.store import CubeStoreError, load_cube, save_cube


def make_cube():
    frame = CubeFrame(origin=(10.0, 20.0), azimuth=37.5, cell=0.1, nx=5, ny=4, crs="EPSG:32633")
    z = ZAxis(t0_ns=-1.5, dz_ns=0.2165, nz=6)
    rng = np.random.default_rng(0)
    mean = rng.random((6, 20)).astype(np.float32)
    count = rng.integers(0, 3, size=20).astype(np.int32)
    mean[:, count == 0] = np.nan
    prov = Provenance(
        line_keys=("a.dzt", "b.dzt"),
        preset_name="slice-standard",
        steps=({"step": "dewow", "params": {"window_ns": 4.0}, "enabled": True},),
        transform="amp_envelope",
        velocity={"layers": [{"top_ns": 0.0, "v_m_ns": 0.08}]},
        built_utc="2026-09-18T19:12:00Z",
        core_version="0.1.0.dev0",
    )
    return SliceCube(frame=frame, z=z, mean=mean, count=count, provenance=prov)


def test_round_trip_preserves_the_arrays_exactly(tmp_path):
    cube = make_cube()
    path = tmp_path / "grid-a.npz"
    save_cube(cube, path)
    back = load_cube(path)
    np.testing.assert_array_equal(np.isnan(back.mean), np.isnan(cube.mean))
    np.testing.assert_array_equal(
        back.mean[~np.isnan(back.mean)], cube.mean[~np.isnan(cube.mean)]
    )
    np.testing.assert_array_equal(back.count, cube.count)


def test_round_trip_preserves_the_frame_and_axis(tmp_path):
    cube = make_cube()
    path = tmp_path / "c.npz"
    save_cube(cube, path)
    back = load_cube(path)
    assert back.frame == cube.frame
    assert back.z == cube.z


def test_round_trip_preserves_provenance(tmp_path):
    cube = make_cube()
    path = tmp_path / "c.npz"
    save_cube(cube, path)
    assert load_cube(path).provenance == cube.provenance


def test_dtypes_survive_the_round_trip(tmp_path):
    """float64 would double a 331 MB cube for nothing."""
    cube = make_cube()
    path = tmp_path / "c.npz"
    save_cube(cube, path)
    back = load_cube(path)
    assert back.mean.dtype == np.float32
    assert back.count.dtype == np.int32


def test_loading_a_file_that_is_not_a_cube_fails_clearly(tmp_path):
    path = tmp_path / "junk.npz"
    np.savez(path, something=np.zeros(3))
    with pytest.raises(CubeStoreError, match="not a cube"):
        load_cube(path)


def test_loading_a_missing_file_fails_clearly(tmp_path):
    with pytest.raises(CubeStoreError, match="no cube file"):
        load_cube(tmp_path / "absent.npz")
```

Append to `packages/nsgeo-core/tests/test_project.py`:

```python
def test_cubes_round_trip_through_the_survey_json(tmp_path):
    site = Site()
    site.cubes = {
        "grid-a-standard": {
            "grid_id": "A",
            "preset": "slice-standard",
            "transform": "amp_envelope",
            "cell": 0.1,
            "array": "slices/grid-a-standard.npz",
        }
    }
    path = tmp_path / "survey.nsgeo.json"
    save_site(site, path)
    assert load_site(path).cubes == site.cubes


def test_a_site_with_no_cubes_writes_no_cubes_key(tmp_path):
    """Same rule presets already follow: absent, not an empty object."""
    path = tmp_path / "survey.nsgeo.json"
    save_site(Site(), path)
    assert "cubes" not in json.loads(path.read_text())


def test_an_older_file_without_cubes_still_loads(tmp_path):
    path = tmp_path / "survey.nsgeo.json"
    path.write_text(json.dumps({"schema_version": 1, "grids": [], "lines": []}))
    assert load_site(path).cubes == {}
```

If `json` and `Site`/`save_site`/`load_site` are not already imported at the top of `test_project.py`, add them to the existing imports rather than duplicating.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest packages/nsgeo-core/tests/test_slices_store.py packages/nsgeo-core/tests/test_project.py -v`
Expected: `ModuleNotFoundError: No module named 'nsgeo.slices.store'`, and `AttributeError: 'Site' object has no attribute 'cubes'`.

- [ ] **Step 3: Implement `store.py`**

Create `packages/nsgeo-core/src/nsgeo/slices/store.py`:

```python
"""The cube on disk.

`.npz` rather than GeoTIFF because the core has numpy and nothing else --
writing a georeferenced raster needs GDAL, which lives on the plugin side.
The plugin converts on the way to the map; this is the working format a
rebuild reads.

The metadata rides as a JSON string in a 0-d array, so the file loads with
`allow_pickle=False`. Pickle in a data file is a remote-code-execution
surface in exchange for nothing here: every field is a number or a string.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

import numpy as np

from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis

STORE_VERSION = 1


class CubeStoreError(Exception):
    """Raised when a cube file is missing, unreadable, or not a cube."""


def _meta(cube: SliceCube) -> Dict[str, Any]:
    return {
        "store_version": STORE_VERSION,
        "frame": {
            "origin": list(cube.frame.origin),
            "azimuth": cube.frame.azimuth,
            "cell": cube.frame.cell,
            "nx": cube.frame.nx,
            "ny": cube.frame.ny,
            "crs": cube.frame.crs,
        },
        "z": {"t0_ns": cube.z.t0_ns, "dz_ns": cube.z.dz_ns, "nz": cube.z.nz},
        "provenance": cube.provenance.to_dict(),
    }


def save_cube(cube: SliceCube, path: Union[str, Path]) -> None:
    """Write `cube` to `path`, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        mean=cube.mean.astype(np.float32, copy=False),
        count=cube.count.astype(np.int32, copy=False),
        meta=np.array(json.dumps(_meta(cube))),
    )


def load_cube(path: Union[str, Path]) -> SliceCube:
    """Read a cube written by `save_cube`."""
    path = Path(path)
    if not path.exists():
        raise CubeStoreError(f"no cube file at {path}")
    try:
        with np.load(path, allow_pickle=False) as bundle:
            if not {"mean", "count", "meta"} <= set(bundle.files):
                raise CubeStoreError(
                    f"{path} is not a cube: expected mean, count and meta, "
                    f"found {sorted(bundle.files)}"
                )
            mean = bundle["mean"].astype(np.float32, copy=False)
            count = bundle["count"].astype(np.int32, copy=False)
            meta = json.loads(str(bundle["meta"].item()))
    except CubeStoreError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise CubeStoreError(f"{path} could not be read as a cube: {exc}") from exc

    frame_doc = meta["frame"]
    z_doc = meta["z"]
    return SliceCube(
        frame=CubeFrame(
            origin=(float(frame_doc["origin"][0]), float(frame_doc["origin"][1])),
            azimuth=float(frame_doc["azimuth"]),
            cell=float(frame_doc["cell"]),
            nx=int(frame_doc["nx"]),
            ny=int(frame_doc["ny"]),
            crs=frame_doc["crs"],
        ),
        z=ZAxis(
            t0_ns=float(z_doc["t0_ns"]), dz_ns=float(z_doc["dz_ns"]), nz=int(z_doc["nz"])
        ),
        mean=mean,
        count=count,
        provenance=Provenance.from_dict(meta["provenance"]),
    )
```

Add to `packages/nsgeo-core/src/nsgeo/slices/__init__.py`:

```python
from nsgeo.slices.store import CubeStoreError, load_cube, save_cube  # noqa: F401
```

- [ ] **Step 4: Add `Site.cubes`**

In `packages/nsgeo-core/src/nsgeo/model/survey.py`, add the field to `Site` after `presets`:

```python
    #: Cube recipes, keyed by cube id, each pointing at a `.npz` beside the
    #: survey file. Plain dicts for the same reason `presets` are: the JSON
    #: is the definition, and the array it names is derived and rebuildable.
    cubes: dict[str, dict[str, Any]] = field(default_factory=dict)
```

- [ ] **Step 5: Persist `cubes`**

In `packages/nsgeo-core/src/nsgeo/project.py`, in `save_site`, after the existing `presets` block:

```python
    if site.cubes:
        doc["cubes"] = site.cubes
```

and in `load_site`, alongside where `presets` is read, add:

```python
    site.cubes = doc.get("cubes", {})
```

`SCHEMA_VERSION` stays at 1: `load_site` reads only the keys it knows, so a file with `cubes` loads in an older build (ignoring them) and a file without loads here. Bumping would force a migration for a purely additive, optional key.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest packages/nsgeo-core/tests/test_slices_store.py packages/nsgeo-core/tests/test_project.py -v`
Expected: all PASS.

- [ ] **Step 7: Add the real-data end-to-end check**

Append to `packages/nsgeo-core/tests/test_real_files.py`:

```python
def test_a_cube_binned_from_real_files_is_covered_and_finite(tmp_path):
    """End to end on real data: preset, transform, bin, slice, save, reload."""
    from nsgeo.slices.binning import PreparedLine, build_cube, plan_line, stream_slice
    from nsgeo.slices.cube import Provenance
    from nsgeo.slices.frame import CubeFrame, ZAxis
    from nsgeo.slices.store import load_cube, save_cube

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
        line_keys=tuple(p.key for p in prepared), preset_name="test", steps=(),
        transform="amp_envelope", velocity=None, built_utc="2026-09-18T00:00:00Z",
        core_version="0.1.0.dev0",
    )
    cube = build_cube(prepared, plans, frame, z, prov)

    assert cube.coverage().sum() == sum(p.data.shape[1] for p in prepared)
    covered = cube.slice_levels(10, 28)[cube.coverage() > 0]
    assert np.isfinite(covered).all()
    assert (covered >= 0.0).all()  # the envelope is unipolar

    streamed, _ = stream_slice(prepared, plans, frame, z, 10, 28)
    np.testing.assert_allclose(
        streamed[cube.coverage() > 0], covered, rtol=1e-4, atol=1e-5
    )

    out = tmp_path / "real.npz"
    save_cube(cube, out)
    assert load_cube(out).provenance == prov
```

Run: `python -m pytest packages/nsgeo-core/tests/test_real_files.py -v`
Expected: PASS locally where the real files are present; the module's `pytestmark` skips it in CI.

- [ ] **Step 8: Lint, type-check and commit**

```bash
python -m pytest packages/nsgeo-core/tests -q
ruff check . && ruff format --check .
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
git add packages/nsgeo-core
git commit -m "feat(slices): persist cubes as .npz and record them in the survey JSON

The core writes .npz because it has numpy and nothing else: a GeoTIFF
needs GDAL, which lives on the plugin side. Metadata rides as a JSON
string so the file loads with allow_pickle=False.

Site.cubes holds the recipes as plain dicts, exactly as presets do, and
SCHEMA_VERSION stays at 1 because load_site reads only keys it knows --
the addition is optional in both directions.

Also adds an end-to-end test over the real GSSI files: preset, envelope,
bin, slice, stream, save and reload.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## What M10 deliberately does not do

Named here so a reviewer does not flag them as gaps:

- **No line preparation.** Loading, running a preset and transforming are the caller's; `PreparedLine` is the boundary. The cache that makes everything else interactive is M11's, because it is a session concern and the core holds no session.
- **No GeoTIFF, no GDAL, no temporal encoding.** M11.
- **No directional de-striping** (spec §6.5) and **no site mosaic** (§10). M12.
- **No on-disk residency tier.** Spec §7.4 flags it as unmeasured; the spike runs before anything commits to memory-mapping, and nothing in this plan depends on it.

## Plan Self-Review

**Spec coverage.** §5.1 `CubeFrame` → Task 1. §5.2 `ZAxis` → Task 1. §5.3 `SliceCube`, z-major layout, per-cell count and the rejection rule → Tasks 4. §5.4 `.npz` and the JSON `cubes` list → Task 6. §6.2 transforms and the no-padding rule → Task 2. §6.3 binning and the precomputed plans → Task 4. §6.4 the fill → Task 5. §6.6 `slice_levels` and `level_range` → Tasks 1 and 4. §7.4 streaming → Task 5. §8 unipolar rendering → Task 3. §6.5, §9, §10 are M11/M12 and are listed above as out of scope for this plan.

**Type consistency, checked across tasks.** `CubeFrame.cell_index` returns flat `iy * nx + ix` in Task 1 and is consumed with that meaning by `plan_line` in Task 4 and `SliceCube.coverage`'s reshape in Task 4. `ZAxis.level_range` returns the half-open pair that `slice_levels` and `stream_slice` both validate as `0 <= k0 < k1 <= nz`. `PreparedLine.data` is float32 in Tasks 4–6. `Provenance.to_dict` / `from_dict` in Task 4 are what `store.py` calls in Task 6. `is_unipolar` is defined in Task 2 and consumed by `StepStack.output_unipolar` in the same task; `to_rgba8(..., unipolar=...)` in Task 3 takes the bool that property produces.

**One thing an implementer should know.** In Task 5, `stream_slice` accumulates `count` as int64 before dividing and only narrows to int32 on return. That is deliberate: `counts * n_levels` on a 230-level cube with a dense cell overflows int32 far sooner than it looks, and the bug would surface as a negative coverage rather than as an exception.
