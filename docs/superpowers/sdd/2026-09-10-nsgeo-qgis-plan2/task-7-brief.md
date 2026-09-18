### Task 7: `lookup.py` — Qt-free import planning, nearest trace, polygon corners

Pure functions the dialogs and map tools call. Tested on the normal matrix without QGIS. Real-file import planning is validated against the ten local files.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/lookup.py`
- Create: `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`
- Modify: `.github/workflows/ci.yml` (mypy the plugin's pure modules)

**Interfaces:**
- Consumes: `read_header`, `trace_count`, `read_dzx`, `Line.open`, `GridPlacement`, `fit_grid_from_corners`
- Produces: `ImportOptions(grid_id, axis, spacing, first_offset=0.0, start_along=0.0, direction_mode="alternate", label_source="stem", grid_size_along=None)`; `ImportRow(path, label, offset, direction, start_along, n_traces, length_m, traces_per_metre, sidecar, include=True, offset_edited=False, note="")` with `.placeable`; `trailing_number(stem) -> int | None`; `sort_files(paths) -> list[Path]`; `plan_import(paths, options) -> list[ImportRow]`; `recompute_offsets(rows, options) -> None`; `rows_to_lines(rows, options) -> list[Line]`; `nearest_trace(coords_by_key, xy, tolerance) -> tuple[str, int, float] | None`; `PolygonCorners(local, world, size_x, size_y)`; `corners_from_polygon(vertices, origin_index, plus_y_index) -> PolygonCorners`; `identity_curve(t0_ns, dt_ns, n_samples) -> list[list[float]]`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.fit import fit_grid_from_corners
from nsgeo.geometry.grid import Grid

from nsgeo_qgis.lookup import (
    ImportOptions,
    corners_from_polygon,
    identity_curve,
    nearest_trace,
    plan_import,
    recompute_offsets,
    rows_to_lines,
    sort_files,
    trailing_number,
)

from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt

OPTS = ImportOptions(grid_id="A", axis="y", spacing=0.5, grid_size_along=11.0)


def test_trailing_number_and_vendor_neutral_sort(tmp_path):
    assert trailing_number("FILE__012") == 12
    assert trailing_number("DAT_0007") == 7
    assert trailing_number("LINE03") == 3
    assert trailing_number("notes") is None
    paths = [tmp_path / n for n in ("FILE__010.DZT", "FILE__002.DZT", "FILE__001.DZT", "extra.DZT")]
    assert [p.name for p in sort_files(paths)] == [
        "FILE__001.DZT",
        "FILE__002.DZT",
        "FILE__010.DZT",
        "extra.DZT",
    ]


@pytest.fixture
def three(tmp_path):
    return [synthetic_dzt(tmp_path, f"FILE__00{i}.DZT", n_traces=60 * (i + 1)) for i in (3, 1, 2)]


def test_plan_import_orders_offsets_alternates_direction_and_reads_headers(three):
    rows = plan_import(three, OPTS)
    assert [r.path.name for r in rows] == ["FILE__001.DZT", "FILE__002.DZT", "FILE__003.DZT"]
    assert [r.offset for r in rows] == [0.0, 0.5, 1.0]
    assert [r.direction for r in rows] == [1, -1, 1]
    assert [r.label for r in rows] == ["FILE__001", "FILE__002", "FILE__003"]
    assert [r.n_traces for r in rows] == [120, 180, 240]
    assert rows[0].length_m == pytest.approx(2.0)
    assert all(r.include and r.placeable and r.sidecar is None for r in rows)


def test_excluding_a_row_pulls_later_rows_into_its_slot(three):
    rows = plan_import(three, OPTS)
    rows[1].include = False
    recompute_offsets(rows, OPTS)
    assert [r.offset for r in rows if r.include] == [0.0, 0.5]
    assert [r.direction for r in rows if r.include] == [1, -1]


def test_hand_edited_offsets_survive_recompute(three):
    rows = plan_import(three, OPTS)
    rows[2].offset = 3.25
    rows[2].offset_edited = True
    rows[0].include = False
    recompute_offsets(rows, OPTS)
    assert [r.offset for r in rows if r.include] == [0.0, 3.25]


def test_direction_modes_and_line_number_labels(three):
    forward = ImportOptions("A", "y", 0.5, direction_mode="forward", label_source="number")
    rows = plan_import(three, forward)
    assert [r.direction for r in rows] == [1, 1, 1]
    assert [r.label for r in rows] == ["line 0", "line 1", "line 2"]
    reverse = ImportOptions("A", "y", 0.5, direction_mode="reverse", first_offset=2.0)
    rows = plan_import(three, reverse)
    assert [r.direction for r in rows] == [-1, -1, -1]
    assert rows[0].offset == 2.0


def test_time_triggered_files_are_flagged_and_excluded(tmp_path):
    good = synthetic_dzt(tmp_path, "FILE__001.DZT")
    bad = synthetic_dzt(tmp_path, "FILE__002.DZT", traces_per_metre=0.0)
    rows = plan_import([good, bad], OPTS)
    assert rows[1].placeable is False and rows[1].include is False
    assert "time-triggered" in rows[1].note
    assert rows[1].length_m is None
    lines = rows_to_lines(rows, OPTS)
    assert [ln.path.name for ln in lines] == ["FILE__001.DZT"]


def test_overrunning_the_grid_is_a_warning_note(tmp_path):
    long = synthetic_dzt(tmp_path, "FILE__001.DZT", n_traces=60 * 12)  # 12 m in an 11 m grid
    rows = plan_import([long], OPTS)
    assert "exceeds" in rows[0].note and rows[0].include


def test_rows_to_lines_builds_grid_placements(three):
    rows = plan_import(three, OPTS)
    lines = rows_to_lines(rows, OPTS)
    p = lines[1].placement
    assert (p.grid_id, p.axis, p.offset, p.direction, p.label) == ("A", "y", 0.5, -1, "FILE__002")


def test_nearest_trace_within_tolerance():
    a = np.column_stack([np.zeros(10), np.arange(10.0)])
    b = np.column_stack([np.full(10, 5.0), np.arange(10.0)])
    hit = nearest_trace({"a": a, "b": b}, (4.8, 3.2), tolerance=0.5)
    assert hit is not None
    key, idx, dist = hit
    assert (key, idx) == ("b", 3) and dist == pytest.approx((0.2**2 + 0.2**2) ** 0.5)
    assert nearest_trace({"a": a, "b": b}, (2.5, 3.0), tolerance=0.5) is None
    assert nearest_trace({}, (0.0, 0.0), tolerance=1.0) is None


def test_corners_from_polygon_yields_a_fittable_rectangle():
    grid = Grid("G", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)
    world = grid.to_world(np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 11.0], [0.0, 11.0]]))
    ring = [tuple(p) for p in world] + [tuple(world[0])]  # closed ring, as QGIS gives it
    corners = corners_from_polygon(ring, origin_index=0, plus_y_index=3)
    assert corners.size_x == pytest.approx(5.0) and corners.size_y == pytest.approx(11.0)
    fit = fit_grid_from_corners(corners.local, corners.world)
    assert fit.azimuth == pytest.approx(30.0, abs=1e-6)
    assert fit.residual_rms < 1e-9
    assert fit.origin == pytest.approx((500.0, 700.0))


def test_corners_from_polygon_rejects_non_adjacent_plus_y():
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    with pytest.raises(ValueError, match="adjacent"):
        corners_from_polygon(ring, origin_index=0, plus_y_index=2)
    with pytest.raises(ValueError, match="four"):
        corners_from_polygon(ring[:3], origin_index=0, plus_y_index=1)


def test_identity_curve_spans_the_time_axis_at_zero_db():
    assert identity_curve(-11.0, 0.5, 5) == [[-11.0, 0.0], [-9.0, 0.0]]


@needs_real_data
def test_real_files_plan_cleanly():
    rows = plan_import(REAL_DZT, OPTS)
    assert len(rows) == 10
    assert [r.n_traces for r in rows] == [608, 625, 629, 658, 613, 608, 635, 666, 653, 606]
    assert all(9.0 < r.length_m < 13.0 for r in rows)
    assert sum(r.sidecar is not None for r in rows) == 9
    by_name = {r.path.stem: r for r in rows}
    assert len(by_name["FILE__007"].sidecar.marks) == 1
    assert by_name["FILE__010"].sidecar is None
    assert "exceeds" in by_name["FILE__008"].note  # 11.10 m in an 11.0 m grid
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_lookup.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.lookup'`

- [ ] **Step 3: Implement `lookup.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/lookup.py`:

```python
"""Qt-free helpers behind the dialogs and map tools.

Import planning, the nearest-trace search the map link uses, polygon
corners for the grid dialog, and the identity gain curve. No Qt anywhere,
so all of it runs on the normal CI matrix.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io.dzt import read_header, trace_count
from nsgeo.io.dzx import DzxError, DzxInfo, read_dzx
from nsgeo.model.survey import Line

_TRAILING = re.compile(r"(\d+)\s*$")


def trailing_number(stem: str) -> int | None:
    """GSSI FILE__001, MALA DAT_0001, Sensors & Software LINE01 all end in
    a sequence number. Vendor-neutral by construction."""
    m = _TRAILING.search(stem)
    return int(m.group(1)) if m else None


def sort_files(paths: Sequence[str | Path]) -> list[Path]:
    ps = [Path(p) for p in paths]
    return sorted(ps, key=lambda p: (trailing_number(p.stem) is None, trailing_number(p.stem) or 0, p.name))


@dataclass(frozen=True)
class ImportOptions:
    grid_id: str
    axis: str  # the axis the lines run ALONG
    spacing: float  # across the other axis
    first_offset: float = 0.0
    start_along: float = 0.0
    direction_mode: str = "alternate"  # alternate | forward | reverse
    label_source: str = "stem"  # stem | number
    grid_size_along: float | None = None  # for the over-length warning


@dataclass
class ImportRow:
    path: Path
    label: str
    offset: float
    direction: int
    start_along: float
    n_traces: int | None
    length_m: float | None
    traces_per_metre: float
    sidecar: DzxInfo | None
    include: bool = True
    offset_edited: bool = False
    note: str = ""

    @property
    def placeable(self) -> bool:
        return self.traces_per_metre > 0 and self.n_traces is not None


def plan_import(paths: Sequence[str | Path], options: ImportOptions) -> list[ImportRow]:
    rows: list[ImportRow] = []
    for path in sort_files(paths):
        header = read_header(path)
        n = trace_count(path, header)
        spm = float(header.traces_per_metre)
        try:
            sidecar = read_dzx(path)
            note = ""
        except DzxError as exc:
            sidecar = None
            note = f"sidecar unreadable: {exc}"
        rows.append(
            ImportRow(
                path=Path(path),
                label=Path(path).stem,
                offset=options.first_offset,
                direction=1,
                start_along=options.start_along,
                n_traces=n,
                length_m=n / spm if spm > 0 else None,
                traces_per_metre=spm,
                sidecar=sidecar,
                include=spm > 0,
                note=note,
            )
        )
    recompute_offsets(rows, options)
    return rows


def recompute_offsets(rows: list[ImportRow], options: ImportOptions) -> None:
    """Offsets, directions, labels, and notes over the included rows in
    table order. A hand-edited offset is kept; everything else follows the
    slot index, so excluding a redone line pulls the next file into its
    place."""
    slot = 0
    for row in rows:
        notes: list[str] = []
        if not row.placeable:
            row.include = False
            notes.append("time-triggered (traces/m = 0): cannot be grid-placed")
        if not row.include:
            row.note = "; ".join(notes) or row.note
            continue
        if not row.offset_edited:
            row.offset = options.first_offset + slot * options.spacing
        if options.direction_mode == "alternate":
            row.direction = 1 if slot % 2 == 0 else -1
        elif options.direction_mode == "reverse":
            row.direction = -1
        else:
            row.direction = 1
        if options.label_source == "number":
            row.label = f"line {slot}"
        else:
            row.label = row.path.stem
        if (
            options.grid_size_along is not None
            and row.length_m is not None
            and row.length_m > options.grid_size_along + 1e-9
        ):
            notes.append(
                f"exceeds grid size along {options.axis} ({options.grid_size_along} m) "
                f"by {row.length_m - options.grid_size_along:.2f} m"
            )
        row.note = "; ".join(notes)
        slot += 1


def rows_to_lines(rows: Sequence[ImportRow], options: ImportOptions) -> list[Line]:
    return [
        Line.open(
            row.path,
            GridPlacement(
                grid_id=options.grid_id,
                axis=options.axis,
                offset=float(row.offset),
                start_along=float(row.start_along),
                direction=int(row.direction),
                label=row.label,
            ),
        )
        for row in rows
        if row.include and row.placeable
    ]


def nearest_trace(
    coords_by_key: Mapping[str, np.ndarray], xy: tuple[float, float], tolerance: float
) -> tuple[str, int, float] | None:
    """The (line key, trace index, distance) closest to `xy`, or None when
    nothing lies within `tolerance`. Plain numpy: ten lines are a few
    thousand points, no spatial index needed."""
    best: tuple[str, int, float] | None = None
    point = np.asarray(xy, dtype=float)
    for key, coords in coords_by_key.items():
        if len(coords) == 0:
            continue
        d = np.hypot(coords[:, 0] - point[0], coords[:, 1] - point[1])
        i = int(np.argmin(d))
        if d[i] <= tolerance and (best is None or d[i] < best[2]):
            best = (key, i, float(d[i]))
    return best


@dataclass(frozen=True)
class PolygonCorners:
    local: np.ndarray  # (4, 2) grid-local metres
    world: np.ndarray  # (4, 2) world coordinates
    size_x: float
    size_y: float


def corners_from_polygon(
    vertices: Sequence[tuple[float, float]], origin_index: int, plus_y_index: int
) -> PolygonCorners:
    """Turn a four-vertex ring into the control points a rigid fit wants.
    `plus_y_index` must neighbour `origin_index`; the other neighbour is +X
    and the remaining vertex is +X+Y."""
    pts = [tuple(map(float, v)) for v in vertices]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) != 4:
        raise ValueError(f"expected four corners, got {len(pts)}")
    o = origin_index % 4
    if plus_y_index % 4 not in ((o + 1) % 4, (o - 1) % 4):
        raise ValueError("the +Y corner must be adjacent to the origin corner")
    y = plus_y_index % 4
    x = (o - 1) % 4 if y == (o + 1) % 4 else (o + 1) % 4
    far = ({0, 1, 2, 3} - {o, x, y}).pop()
    world = np.array([pts[o], pts[x], pts[far], pts[y]], dtype=float)
    size_x = float(math.dist(pts[o], pts[x]))
    size_y = float(math.dist(pts[o], pts[y]))
    local = np.array([[0.0, 0.0], [size_x, 0.0], [size_x, size_y], [0.0, size_y]])
    return PolygonCorners(local=local, world=world, size_x=size_x, size_y=size_y)


def identity_curve(t0_ns: float, dt_ns: float, n_samples: int) -> list[list[float]]:
    """Two control points at 0 dB spanning the time axis: the identity, so
    seeding gain_curve with it is not a guess."""
    t_end = t0_ns + dt_ns * (n_samples - 1)
    return [[float(t0_ns), 0.0], [float(t_end), 0.0]]
```

- [ ] **Step 4: Type-check the pure module and wire it into CI**

Run: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py`
Expected: clean. Then add `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` to the mypy line in `.github/workflows/ci.yml`'s `lint` job (and to the verification set in this plan's Global Constraints when you run it).

- [ ] **Step 5: Run, lint, commit**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS (the real-file test runs because the worktree has the symlinks).

```bash
git add packages/nsgeo-qgis .github/workflows/ci.yml
git commit -m "feat: Qt-free import planning, nearest-trace search, polygon corners

Placement guesses come from the trailing number in the file stem, which
GSSI, MALA, and Sensors & Software all use, so nothing here is
vendor-specific. Excluding a redone line pulls later files into its
slot unless their offsets were hand-edited. Validated against the ten
real files, including the one that overruns an 11 m grid by 10 cm."
```

---

