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

