### Task 3: `nsgeo.velocity` and velocity on `Grid` and `Line`

A layered velocity model stored per grid with an optional per-line override, per spec §3.3. The v1 UI exposes only the constant case, but the data shape is the list from day one so no schema migration is needed later.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/velocity.py`
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/grid.py` (add `velocity` field)
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (add `Line.velocity`, `Line.open(..., velocity=None)`)
- Modify: `packages/nsgeo-core/src/nsgeo/project.py` (serialise both)
- Create: `packages/nsgeo-core/tests/test_velocity.py`

**Interfaces:**
- Consumes: `Grid`, `Line`, `save_site`, `load_site`
- Produces: `VelocityModel(layers: tuple[tuple[float, float], ...])` with `constant(v)`, `from_dielectric(epsr)`, `depth_at(times_ns)`, `velocity_at(times_ns)`, `to_dict()`, `from_dict(doc)`, `is_constant`, `surface_velocity`; `C_M_PER_NS = 0.299792458`; `resolve_velocity(line, grid) -> VelocityModel`; `Grid.velocity: VelocityModel | None = None`; `Line.velocity: VelocityModel | None = None`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_velocity.py`:

```python
"""Layered velocity: boundaries in two-way time, depth by integration.

Depth is measured from time zero. Before a time_zero step a real SIR-4000
file (position -11.09 ns) therefore has negative depth at the top. That is
correct, and the last test pins it against a real header.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io.dzt import read_header
from nsgeo.model.survey import Line, Site
from nsgeo.project import load_site, save_site
from nsgeo.velocity import C_M_PER_NS, VelocityModel, resolve_velocity

from tests.synthetic import write_dzt

DATA = Path(__file__).parent / "data" / "local"
FILES = sorted(p for p in DATA.rglob("*") if p.suffix.lower() == ".dzt") if DATA.exists() else []


def test_constant_velocity_depth_is_half_v_t():
    m = VelocityModel.constant(0.1)
    np.testing.assert_allclose(m.depth_at(np.array([0.0, 20.0, 40.0])), [0.0, 1.0, 2.0])
    assert m.is_constant
    assert m.surface_velocity == 0.1


def test_negative_time_gives_negative_depth():
    m = VelocityModel.constant(0.1)
    assert m.depth_at(np.array([-11.0]))[0] == pytest.approx(-0.55)


def test_from_dielectric_matches_c_over_sqrt_epsr():
    m = VelocityModel.from_dielectric(14.0)
    assert m.surface_velocity == pytest.approx(C_M_PER_NS / 14.0**0.5)
    assert m.surface_velocity == pytest.approx(0.0801, abs=1e-4)
    with pytest.raises(ValueError, match="dielectric"):
        VelocityModel.from_dielectric(0.0)


def test_two_layers_integrate_piecewise():
    m = VelocityModel(layers=((0.0, 0.1), (20.0, 0.05)))
    np.testing.assert_allclose(m.depth_at(np.array([0.0, 10.0, 20.0, 40.0])), [0.0, 0.5, 1.0, 1.5])
    np.testing.assert_allclose(m.velocity_at(np.array([-5.0, 5.0, 20.0, 99.0])), [0.1, 0.1, 0.05, 0.05])
    assert not m.is_constant


def test_depth_is_monotone_for_any_valid_model():
    m = VelocityModel(layers=((0.0, 0.12), (15.0, 0.07), (60.0, 0.09)))
    d = m.depth_at(np.linspace(-10, 120, 400))
    assert np.all(np.diff(d) > 0)


def test_validation():
    with pytest.raises(ValueError, match="at least one"):
        VelocityModel(layers=())
    with pytest.raises(ValueError, match="0 ns"):
        VelocityModel(layers=((5.0, 0.1),))
    with pytest.raises(ValueError, match="increase"):
        VelocityModel(layers=((0.0, 0.1), (0.0, 0.2)))
    with pytest.raises(ValueError, match="positive"):
        VelocityModel(layers=((0.0, -0.1),))
    with pytest.raises(ValueError, match="positive"):
        VelocityModel.constant(0.0)


def test_layers_are_normalised_to_floats_and_immutable():
    m = VelocityModel(layers=((0, 1), (10, 2)))
    assert m.layers == ((0.0, 1.0), (10.0, 2.0))
    with pytest.raises(AttributeError):
        m.layers = ()  # type: ignore[misc]


def test_dict_round_trip():
    m = VelocityModel(layers=((0.0, 0.1), (20.0, 0.05)))
    doc = m.to_dict()
    assert doc == {"layers": [{"top_ns": 0.0, "v_m_ns": 0.1}, {"top_ns": 20.0, "v_m_ns": 0.05}]}
    assert VelocityModel.from_dict(doc) == m


@pytest.fixture
def line_and_grid(tmp_path):
    p = tmp_path / "L0.DZT"
    write_dzt(p, np.zeros((512, 30), dtype=np.int32))  # synthetic header has epsr 14
    grid = Grid("G", (0.0, 0.0), 0.0, 10.0, 10.0, "EPSG:32616", 0.5)
    line = Line.open(p, GridPlacement(grid_id="G", axis="y", offset=0.0))
    return line, grid


def test_resolution_order_is_line_then_grid_then_header(line_and_grid):
    line, grid = line_and_grid
    header_v = VelocityModel.from_dielectric(14.0)
    assert resolve_velocity(line, grid) == header_v
    assert resolve_velocity(line, None) == header_v
    grid_v = VelocityModel.constant(0.09)
    from dataclasses import replace

    grid2 = replace(grid, velocity=grid_v)
    assert resolve_velocity(line, grid2) == grid_v
    line2 = replace(line, velocity=VelocityModel.constant(0.07))
    assert resolve_velocity(line2, grid2) == VelocityModel.constant(0.07)


def test_project_round_trips_velocities_and_tolerates_their_absence(tmp_path, line_and_grid):
    line, grid = line_and_grid
    from dataclasses import replace

    grid = replace(grid, velocity=VelocityModel(layers=((0.0, 0.1), (20.0, 0.05))))
    line = replace(line, velocity=VelocityModel.constant(0.07))
    out = tmp_path / "survey.nsgeo.json"
    save_site(Site(grids=[grid], lines=[line]), out)
    back = load_site(out)
    assert back.grids[0].velocity == grid.velocity
    assert back.lines[0].velocity == VelocityModel.constant(0.07)

    bare = Site(grids=[replace(grid, velocity=None)], lines=[replace(line, velocity=None)])
    save_site(bare, out)
    text = out.read_text()
    assert "velocity" not in text
    back = load_site(out)
    assert back.grids[0].velocity is None and back.lines[0].velocity is None


@pytest.mark.skipif(not FILES, reason="no real DZT files in tests/data/local")
def test_real_header_suggestion_puts_the_top_of_the_record_below_zero_depth():
    h = read_header(FILES[0])
    m = VelocityModel.from_dielectric(h.epsr)
    top = float(m.depth_at(np.array([h.position_ns]))[0])
    assert -0.46 < top < -0.43  # -11.09 ns at 0.0801 m/ns
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_velocity.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.velocity'`

- [ ] **Step 3: Implement `velocity.py`**

Create `packages/nsgeo-core/src/nsgeo/velocity.py`:

```python
"""Layered velocity model: interval velocities bounded in two-way time.

Boundaries are in time because that is what is visible on a radargram; depth
is the derived quantity. A constant velocity is the one-layer case, which is
all the v1 UI exposes, but the shape is a list from the start so adding
layers later changes no file format.

Depth is measured from time zero. Times before zero (a real SIR-4000 file
starts at -11.09 ns) give negative depths, which is correct.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

C_M_PER_NS = 0.299792458


@dataclass(frozen=True)
class VelocityModel:
    layers: tuple[tuple[float, float], ...]  # (top_ns, v_m_per_ns), tops increasing, first 0.0

    def __post_init__(self) -> None:
        if not self.layers:
            raise ValueError("a velocity model needs at least one layer")
        layers = tuple((float(t), float(v)) for t, v in self.layers)
        object.__setattr__(self, "layers", layers)
        tops = [t for t, _ in layers]
        if tops[0] != 0.0:
            raise ValueError(f"the first layer must start at 0 ns, got {tops[0]}")
        if any(b <= a for a, b in zip(tops, tops[1:])):
            raise ValueError(f"layer tops must strictly increase, got {tops}")
        if any(not (math.isfinite(v) and v > 0.0) for _, v in layers):
            raise ValueError("interval velocities must be positive and finite")

    @classmethod
    def constant(cls, v_m_per_ns: float) -> VelocityModel:
        return cls(layers=((0.0, v_m_per_ns),))

    @classmethod
    def from_dielectric(cls, epsr: float) -> VelocityModel:
        if not epsr > 0.0:
            raise ValueError(f"relative dielectric permittivity must be positive, got {epsr}")
        return cls.constant(C_M_PER_NS / math.sqrt(epsr))

    @property
    def is_constant(self) -> bool:
        return len(self.layers) == 1

    @property
    def surface_velocity(self) -> float:
        return self.layers[0][1]

    def _arrays(self) -> tuple[np.ndarray, np.ndarray]:
        tops = np.array([t for t, _ in self.layers], dtype=float)
        vs = np.array([v for _, v in self.layers], dtype=float)
        return tops, vs

    def _layer_index(self, tops: np.ndarray, times_ns: np.ndarray) -> np.ndarray:
        # Times below the first top belong to the first layer.
        return np.clip(np.searchsorted(tops, times_ns, side="right") - 1, 0, len(tops) - 1)

    def velocity_at(self, times_ns: np.ndarray) -> np.ndarray:
        tops, vs = self._arrays()
        return vs[self._layer_index(tops, np.asarray(times_ns, dtype=float))]

    def depth_at(self, times_ns: np.ndarray) -> np.ndarray:
        """Depth in metres: cumulative integral of v/2 over two-way time."""
        t = np.asarray(times_ns, dtype=float)
        tops, vs = self._arrays()
        depth_at_tops = np.concatenate([[0.0], np.cumsum(vs[:-1] / 2.0 * np.diff(tops))])
        idx = self._layer_index(tops, t)
        return depth_at_tops[idx] + vs[idx] / 2.0 * (t - tops[idx])

    def to_dict(self) -> dict[str, Any]:
        return {"layers": [{"top_ns": t, "v_m_ns": v} for t, v in self.layers]}

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> VelocityModel:
        return cls(layers=tuple((float(d["top_ns"]), float(d["v_m_ns"])) for d in doc["layers"]))


def resolve_velocity(line: Any, grid: Any) -> VelocityModel:
    """Line override, then the grid's model, then the header's dielectric.

    Duck-typed on `.velocity` and `.header.epsr` so this module imports
    nothing from the model package and cannot create an import cycle.
    """
    if getattr(line, "velocity", None) is not None:
        return line.velocity  # type: ignore[no-any-return]
    if grid is not None and getattr(grid, "velocity", None) is not None:
        return grid.velocity  # type: ignore[no-any-return]
    return VelocityModel.from_dielectric(line.header.epsr)
```

- [ ] **Step 4: Add the fields to `Grid` and `Line`, and serialise them**

`geometry/grid.py`: add `from nsgeo.velocity import VelocityModel` and, as the last field of `Grid`:

```python
    velocity: VelocityModel | None = None
```

`model/survey.py`: add `from nsgeo.velocity import VelocityModel`; add `velocity: VelocityModel | None = None` as the last field of `Line`; change `Line.open` to

```python
    @classmethod
    def open(
        cls, path: Path, placement: Placement, velocity: VelocityModel | None = None
    ) -> Line:
        """Read the header and derive the trace count. Reads 1024 bytes plus
        a stat, regardless of file size."""
        path = Path(path)
        header = read_header(path)
        return cls(
            path=path,
            header=header,
            placement=placement,
            n_traces=trace_count(path, header),
            velocity=velocity,
        )
```

`project.py`: import `VelocityModel`; in `_grid_to_dict` add `if grid.velocity is not None: doc["velocity"] = grid.velocity.to_dict()` (restructure the literal into a local `doc` first); in `_grid_from_dict` pass `velocity=VelocityModel.from_dict(doc["velocity"]) if "velocity" in doc else None`; in `save_site`'s line loop add `if line.velocity is not None: entry["velocity"] = line.velocity.to_dict()`; in `load_site` pass `velocity=VelocityModel.from_dict(entry["velocity"]) if "velocity" in entry else None` to `Line.open`.

- [ ] **Step 5: Run the full core suite, lint, mypy**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo`
Expected: all PASS, clean. Existing `Grid(...)` and `Line.open(...)` calls are unaffected because the new fields default to `None`.

- [ ] **Step 6: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add a layered velocity model, stored per grid with a line override

Grids are the unit of completed fieldwork and conditions change between
them, so velocity lives on the grid; a line may override it. The model is
a list of (two-way time, interval velocity) layers even though v1 only
exposes the constant case, so adding layers later needs no migration.
None means unset: the core never invents a velocity, the header's
dielectric is a suggestion the UI shows. Depth before time zero is
negative, pinned against a real header."
```

---

