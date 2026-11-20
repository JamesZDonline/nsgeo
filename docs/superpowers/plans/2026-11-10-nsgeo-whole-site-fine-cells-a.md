# Whole Site at Fine Cells, Milestone A (#107): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Whole site never refuses a fine cell. Every slice picture blends the four cells around
each pixel (bilinear) at the cell size, drawn smooth, and every reason a picture can't be drawn is
said plainly in the panel.

**Architecture:**
- **A new core module** `nsgeo/slices/resample.py` holds the bilinear rule: planned "taps" per
  output pixel, and two samplers, one for amplitudes and one for trace counts.
- **This grid** (`to_north_up`) and **Whole site** (`Footprint`/`compose_footprints`) both sample
  through it. Half pitch is removed.
- **`SiteEngine`** gets a whole-site pixel limit of its own. Past it, the site is drawn on a
  coarser preview lattice and explains why. The export refuses rather than write a preview.
- **Every slice layer** gets QGIS's zoomed-in bilinear resampling.

**Tech Stack:** Python 3.9+, numpy (core: numpy only), QGIS 3.40 / 3.44 / 4.2 (PyQt5 and PyQt6),
GDAL, pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-nsgeo-whole-site-fine-cells-design.md` (§5 is this
milestone; §3 lists the decisions). Read it before starting. Milestone B (#108, the finer streamed
export) is a later plan.

## Global Constraints

- **Run every test from the worktree root with `PYTHONPATH=packages/nsgeo-core/src`.** `.venv`'s
  editable `nsgeo` otherwise imports the *main checkout's* core, and the tests would check the wrong
  code. `R=/home/jameszd/Documents/Github/archaeo_geophysics` below.
  - Core and pure: `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`.
  - QGIS: `PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen $R/.venv-qgis/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`.
- **Lint as CI does:**
  - `$R/.venv/bin/ruff check .` and `$R/.venv/bin/ruff format --check .`, line length 100;
  - `$R/.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`.
- **The core is numpy only.** No new dependencies anywhere.
- **Plugin boundary rule.** Arithmetic and message text live in the core or `slices_plan.py`, never
  in widgets.
- **Qt.** Use fully qualified enums (Qt 5 and Qt 6). Every Qt-invoked slot or override guards its
  body with `try/except Exception`, because an escaping exception reaches `qFatal()` in CI.
- **Windows.** The preview still writes a fresh file every tick (`slice_layer.py` module docstring).
  Do not change that.
- **#113 is built alongside** (branch `nsgeo-packed-cube`). Do not touch `SliceCube`, `binning.py`,
  `store.py`, `estimate_memory` or `SliceEngine.estimate`. In `test_slices_display.py`, touch only
  the north-up tests, because #113 edits that file's cube tests. Expect a merge there.
- **Copy rule.** Text the user reads is plain words: no "lattice", no "Ruling", no issue numbers.
  Exact copy is given where it matters.
- **Commits.** Commit each task, push the branch as you go, and end each message with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (subagents may name their own model).

## Review Focus

1. **Blank or zero-count cells inside the data.** A blank cell stays blank. Its neighbours are not
   dimmed: the weights are re-normalised, not averaged with a zero. A zero-count cell is never
   hidden in coverage. Pinned in Task 1, and in Task 3 on the site.
2. **A grid in another CRS than the site's.** Its pixel centres are transformed before the taps are
   planned. Pinned in Task 3 by the existing cross-zone test.
3. **One outlying grid pushing the site over the limit.** The preview names it, and leaving it out
   returns to full detail. Pinned in Task 4.
4. **The note going stale.** Changing the cell or switching scope while a preview note shows never
   leaves stale text. Pinned in Task 5.
5. **Smooth drawing lost on repoint.** It survives the per-tick repoint (`setDataSource` can rebuild
   the layer's pipe), and exported layers get it too. Pinned in Task 6.

---

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

### Task 2: This grid draws and exports with the bilinear rule, at the cell size

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/slices/display.py`:
  - `to_north_up` (around line 192) and its docstring;
  - `_build_north_up_plan` (around line 265);
  - `_NORTH_UP_PLANS` and its comment.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py`: `SliceLayer.update` gains
  `counts: bool = False`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: `_on_slice_changed`'s This grid branch passes
  `counts=dock.coverage_check.isChecked()`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`: `GeoTiffSliceWriter.write` calls
  `to_north_up(values, plan.frame, counts=plan.finish is None)`. A coverage plan has
  `finish=None`.
- Test: in `packages/nsgeo-core/tests/test_slices_display.py`, the north-up tests only (lines
  ~224–370).
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`:
  `test_a_rotated_export_is_at_half_pitch_and_keeps_every_cell` (~575).
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export_dialogs.py`: the docstring at
  ~262.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py`: run it, and update any
  assertion that pinned a half-pitch shape or a nearest-cell value. Name each one in the report.

**Interfaces:**
- Consumes: Task 1's `bilinear_taps`, `sample` and `sample_counts`.
- Produces: `to_north_up(values: np.ndarray, frame: CubeFrame, *, counts: bool = False) ->
  tuple[np.ndarray, tuple[float, ...]]`. Same return shapes as today. The pixel is `frame.cell` for
  every azimuth, anchored on the frame's own extent as today. The plan cached per frame is the
  frame's `Taps` plus the shape and geotransform.

- [ ] **Step 1: Rewrite the half-pitch tests in `test_slices_display.py`.**
  - `test_a_rotated_frame_is_resampled_at_half_the_cell` becomes
    `test_a_rotated_frame_is_resampled_at_the_cell`, asserting `gt[1] == frame.cell`.
  - `test_no_cell_is_dropped_on_a_rotated_frame` stays parametrised. It asserts that every cell
    feeds some finite pixel, by the single-bright-cell probe from Task 1.
  - Add `test_an_axis_aligned_frame_is_reproduced_exactly_at_the_cell`, with a random values array:
    `to_north_up(values, frame)[0]` equals `values[::-1]` as float32.
  - Add `test_coverage_counts_are_never_blended`: `to_north_up(counts, f30, counts=True)` holds
    only values present in `counts`.
  - Delete `test_a_hair_off_axis_frame_keeps_the_full_pitch` (the pitch no longer depends on the
    azimuth), or fold it into the at-the-cell test.
  - Keep the rest (row zero at the bottom, top-left anchor, masked corners, no invented values,
    plan once per frame). Update an expected number only where it came from half pitch.
- [ ] **Step 2: Rewrite the plugin pins.**
  - `test_a_rotated_export_is_at_half_pitch_and_keeps_every_cell` becomes
    `test_a_rotated_export_is_at_the_cell_and_keeps_every_cell`. Pixel == cell, and every frame
    cell with data reaches a finite pixel.
  - Add to `test_plugin_slice_export.py`: `test_a_coverage_export_holds_whole_counts`, where a
    rotated frame's coverage band holds only integers ≥ 1 or NaN.
- [ ] **Step 3: Run and see them fail.** Run the display tests (core command) and the two QGIS
  files.
- [ ] **Step 4: Implement.** `_build_north_up_plan` computes the box as today at
  `pixel = frame.cell`, then `bilinear_taps(frame, world)`. `to_north_up` applies `sample`, or
  `sample_counts` when `counts`. Remove the `lattice_pixel` and `snap_azimuth` import here.
  Update the docstring: the "Nearest neighbour, not bilinear" paragraph is replaced by the spec's
  reason, and "Ruling 2 / half the cell" goes.
- [ ] **Step 5: Measure one tick.** Time `to_north_up` on a 50 × 40 m frame at 0.05 m (1000 × 800
  cells) at azimuth 0 and 10.497, plan already cached, median of 20. Record both figures in the
  docstring next to the old ones (2 ms at 0.2 m, 8 ms at 0.1 m). If the rotated tick is over 50 ms,
  report it rather than optimising.
- [ ] **Step 6: Run** the display tests, `test_plugin_slice_export.py`,
  `test_plugin_slice_export_dialogs.py`, `test_plugin_slice_layer.py` and
  `test_plugin_slices_dock.py`, plus lint. All pass.
- [ ] **Step 7: Commit**: `feat(slices): This grid draws and exports bilinear at the cell size`.

---

### Task 3: Whole site composes with the bilinear rule; half pitch retires

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/slices/site.py`:
  - `Footprint` (~178), `footprint` (~208) and `compose_footprints` (~230);
  - delete `compose`, `lattice_pixel`, `snap_azimuth`, `AXIS_SNAP_CELLS` and
    `_RIGHT_ANGLE_TOL_DEG`;
  - update the module docstring.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` (exports).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`:
  - imports;
  - `_covering_lattice` (~711) uses `res.cell` as the pixel;
  - `_gather` (~831) builds taps;
  - `slice_at` passes `counts=coverage`;
  - the half-pitch sentence in `_rebuild_geometry`'s refusal goes. Task 4 replaces the refusal.
- Modify: `packages/nsgeo-qgis/scripts/bench_site.py`: its docstring's half-pitch sentence.
- Test: `packages/nsgeo-core/tests/test_slices_site.py`: lines ~122–245 (lattice pixel, compose,
  footprint) and ~605.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py`: ~955–1035, and the cross-zone
  test at ~915.

**Interfaces:**
- Consumes: Task 1's `Taps`, `bilinear_taps`, `sample` and `sample_counts`.
- Produces:
  - `Footprint(row0: int, row1: int, col0: int, col1: int, taps: Taps)`, where `taps.n ==
    (row1 - row0) * (col1 - col0)`, row-major over the window.
  - `footprint(taps: Taps, rows: int, cols: int, row0: int = 0, col0: int = 0) -> Footprint`: the
    tight window around the points with `taps.inside`, built with `taps.take`. Empty when there are
    none, at `(row0, col0)`.
  - `compose_footprints(lattice: SiteLattice, layers: Sequence[tuple[Footprint, np.ndarray]], *,
    counts: bool = False) -> np.ndarray`: float32 `(height, width)`. Each layer is sampled with
    `sample`, or `sample_counts` when `counts`. Overlapping grids take the mean of their finite
    values, NaN where none. Accumulate in float32 with a uint8 count (spec §5.2). Raise
    `ValueError` for a window off the lattice, as today.

- [ ] **Step 1: Rewrite the core site tests.**
  - Delete `test_lattice_pixel_is_the_cell_for_right_angles_and_half_for_anything_else` and every
    `compose(`-based test.
  - Replace them with tests built from `bilinear_taps` over `lattice.pixel_centres()`:
    - `test_footprint_compose_samples_each_grid_bilinearly`: one rotated layer equals `sample`
      over the whole lattice, reshaped, to float32 tolerance 1e-6;
    - `test_footprint_compose_still_averages_overlapping_layers`;
    - `test_compose_counts_takes_whole_counts_within_a_grid` (with `counts=True`);
    - `test_a_footprint_is_the_tight_window_around_every_inside_point`;
    - keep `test_compose_footprints_refuses_a_window_off_the_lattice`.
  - Update `test_real_halves_at_different_azimuths_compose_and_find_their_seam` (~605) to build
    its footprints with taps.
- [ ] **Step 2: Rewrite the QGIS site-engine pins.**
  - `test_a_rotated_site_composes_exactly_as_whole_lattice_gathers_would` becomes
    `test_a_rotated_site_composes_each_grid_bilinearly`. Expected = the mean, over grids, of
    `sample(shown[g], bilinear_taps(frame_g, centres))`, compared with tolerance 1e-5 and NaNs in
    the same places. Assert `lattice.pixel == RES.cell`.
  - Delete `test_a_refusal_with_a_rotated_grid_names_the_half_cell_pitch` and
    `test_a_grid_a_hair_off_north_keeps_the_full_cell_pitch`.
  - Add `test_the_site_pixel_is_the_cell_at_any_bearing`, parametrised over B's azimuth in
    `[0, 1e-6, 2.0, 30.0]`.
  - Keep `test_grids_too_far_apart_for_the_lattice_are_refused_by_pixel_count` for now. Task 4
    rewrites it.
  - Add `test_coverage_on_the_site_is_whole_counts`: a coverage tick holds only values of the
    grids' own counts, or their overlap means.
  - The cross-zone test must still pass unchanged apart from pitch numbers.
- [ ] **Step 3: Run and see them fail.**
- [ ] **Step 4: Implement** per the interfaces.
  - `_gather` computes the window as today, at the cell pitch. The centres are transformed into the
    frame's CRS when it differs, then go to `bilinear_taps` and `footprint(taps, rows, cols, row0,
    col0)`.
  - `SiteEngine` keeps its gather cache keyed as today.
  - In `slice_at`: `compose_footprints(lattice, [...], counts=coverage)`.
- [ ] **Step 5: Run** `test_slices_site.py`, `test_plugin_site_engine.py`,
  `test_plugin_site_scope.py` and `test_plugin_site_export.py`, plus lint. All pass. Run `bench_site.py --azimuths 0 30` and note one tick's time at
  each bearing in the commit body.
- [ ] **Step 6: Commit**: `feat(site): compose bilinear at the cell size; retire half pitch`.

---

### Task 4: A whole-site limit, a coarser preview past it, and an export that refuses the preview

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`. Add `SITE_MAX_PIXELS` beside
  `MAX_FRAME_CELLS` (~337), and add `preview_note(...)`, `site_export_refusal(...)` and
  `name_list(...)`.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/site.py`. Add `fitting_lattice(...)` and
  `stretching_grids(...)`, and export them from `__init__.py`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`:
  - `_rebuild_geometry` (~643) never refuses for size;
  - new properties `full_lattice`, `is_preview`, `preview_note` and `export_refusal`;
  - a `max_pixels` attribute, defaulting to `SITE_MAX_PIXELS`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`: `plan_site_export` (~116) raises
  `RuntimeError(site_engine.export_refusal)` when it is set, before planning anything.
- Test: `packages/nsgeo-core/tests/test_slices_site.py`,
  `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py` and
  `packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py`.

**Interfaces:**
- Consumes: Task 3's site lattice at the cell.
- Produces:
  - Core:
    - `fitting_lattice(extents: Sequence[tuple[float, float, float, float]], cell: float, crs:
      str, max_pixels: int) -> SiteLattice`: `SiteLattice.covering` at `cell * 2**k` for the
      smallest `k >= 0` whose `n_pixels <= max_pixels`.
    - `stretching_grids(extents: Mapping[str, tuple[float, float, float, float]], pixel: float,
      crs: str, *, most: int = 3) -> list[str]`: the grid ids whose omission alone cuts the
      covering lattice's pixel count by at least 10%, largest cut first, at most `most`. Empty for
      a single grid.
  - Plugin (`slices_plan.py`, pure):
    - `SITE_MAX_PIXELS: int` (set in Step 5).
    - `name_list(names: Sequence[str]) -> str`: `"A"`, `"A and B"`, `"A, B and C"`.
    - `preview_note(pitch: float, cell: float, width_m: float, height_m: float, stretching:
      Sequence[str]) -> str`. Exact copy:
      `f"Preview at {pitch:g} m pixels: the grids are at {cell:g} m, but the area around them ({width_m:.0f} × {height_m:.0f} m) is too big to draw at full detail."`,
      then, when `stretching` is non-empty, `f" Leaving out {name_list(stretching)} would shrink it most."`
    - `site_export_refusal(cell: float, width_m: float, height_m: float, stretching:
      Sequence[str]) -> str`. Exact copy:
      `f"The site can't be exported at full detail yet: the area around the included grids ({width_m:.0f} × {height_m:.0f} m) is too big at a {cell:g} m cell. Choose a coarser cell"`,
      then `f", or leave out {name_list(stretching)}"` when non-empty, then `"."`.
  - `SiteEngine`:
    - `full_lattice: SiteLattice | None`, the lattice at the cell;
    - `lattice: SiteLattice | None`, the one drawn, possibly coarser;
    - `is_preview: bool`;
    - `preview_note: str | None`;
    - `export_refusal: str | None`, set exactly when `is_preview`.
    - `width_m`/`height_m` are `full_lattice.width * full_lattice.pixel` and the same for the
      height. `stretching` comes from the ready grids' extents in the site CRS (`_extent_in`).

- [ ] **Step 1: Write the failing tests.**
  - Core: `test_fitting_lattice_doubles_the_pitch_until_it_fits`, where 3 × 3 m at 0.1 m with
    `max_pixels=300` gives 0.2 m;
    `test_fitting_lattice_keeps_the_cell_when_it_fits`;
    `test_stretching_grids_names_the_outlier_first`, three abutting grids plus one 200 m away, so
    the outlier is named first, alone;
    `test_stretching_grids_is_empty_for_one_grid`.
  - Pure: exact-copy tests for `preview_note`, `site_export_refusal` and `name_list` (one, two and
    three names).
  - QGIS:
    - `test_grids_too_far_apart_draw_a_coarser_preview_and_say_why` replaces the refusal test. C
      at (5000, 5000); `site.max_pixels` lowered so the cell does not fit. Then
      `set_resolution(RES)` does not raise; `site.is_preview`; `site.lattice.pixel ==
      2**k * RES.cell` with `k >= 1`; `site.full_lattice.pixel == RES.cell`; `site.preview_note`
      contains `"Leaving out C"`; and `slice_at` returns an array on `site.lattice`.
    - `test_leaving_the_outlier_out_returns_to_full_detail`.
    - `test_a_site_that_fits_is_not_a_preview`: `site.preview_note is None` and
      `site.export_refusal is None`.
    - In `test_plugin_site_export.py`, `test_exporting_a_preview_site_refuses_and_writes_nothing`:
      `export_site` raises `RuntimeError` matching `"can't be exported at full detail"`, and the
      target path does not exist.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** `_rebuild_geometry` builds `full_lattice` at the cell. If its
  `n_pixels > self.max_pixels`, it draws `fitting_lattice(...)` and sets the note and refusal;
  otherwise `lattice = full_lattice` and both are None. Gathers and seams follow `lattice` as today.
  Remove the old `MAX_FRAME_CELLS` refusal for the lattice and its message. The per-grid frame cap
  is untouched.
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Measure, then set `SITE_MAX_PIXELS`.** Extend `bench_site.py` with
  `--lattice-scale N`, which spaces the ten grids out so the lattice reaches a given pixel count.
  Measure, at about 4, 8, 12, 16 and 24 M pixels at the cell, with kriging and no smoothing:
  - the median time of one `slice_at` compose;
  - the peak transient memory of the compose, with `tracemalloc` on `compose_footprints`.

  Set `SITE_MAX_PIXELS` to the largest of those sizes where the compose takes ≤ 250 ms and
  transient memory is ≤ 400 MB, capped at 16_000_000. Write the table and the choice in the
  constant's comment. If 16 M fails both, say so in the report rather than tune further.
- [ ] **Step 6: Run** `test_slices_site.py`, `test_pure_slices_plan.py`,
  `test_plugin_site_engine.py`, `test_plugin_site_export.py` and `test_plugin_site_scope.py`, plus
  lint. All pass.
- [ ] **Step 7: Commit**: `feat(site): its own pixel limit, a coarser preview past it, and an export that refuses the preview`.

---

### Task 5: Say it in the panel: the preview note, the reason nothing is drawn, the export's pixel size

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`. Add `self.site_note =
  ElidedLabel("")` directly under the readout row (around line 445). It is visible only in Whole
  site; its full text is in its tooltip (`set_hint`) and its height is fixed, kept when empty.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`:
  - `apply_resolution` (~832) keeps the reason when `set_resolution` raises, in
    `self.problem: str | None`, and clears it when it succeeds;
  - `refresh_slice` (~911) shows `engine.preview_note` while drawn, or `f"Not drawn: {problem}"`
    when nothing is drawn and a problem is known, else empty.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: both export success messages (~1013 and
  ~1193) gain the cell and pixel size (#112).
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`, and
  `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export_dialogs.py` (or wherever the export
  messages are asserted today).

**Interfaces:**
- Consumes: Task 4's `SiteEngine.preview_note`, `export_refusal`, `full_lattice` and `lattice`.
- Produces: `SlicesDock.site_note: ElidedLabel` and `SiteScope.problem: str | None`.
- The export message's exact copy is `f"exported {n} bands to {path} ({cell:g} m cell, {pixel:g} m pixels)"`.
  The site export takes the cell and pixel from `plan.cell_m` and `plan.lattice.pixel`; This grid's
  from `plan.frame.cell` and the written pixel, which is the cell after Task 2.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_preview_note_shows_in_the_panel_while_the_site_is_a_preview`: lower
    `max_pixels`, and `dock.site_note.text()` equals the engine's note. Its tooltip also holds the
    export refusal (`"can't be exported at full detail"`), so that refusal is in the panel before
    anyone clicks Export (spec §5.5).
  - `test_the_note_clears_when_the_site_fits_again`.
  - `test_the_note_clears_on_switching_to_this_grid`: `site_note` is hidden.
  - `test_a_failed_resolution_says_why_in_the_panel_not_only_a_toast`. Make `set_resolution`
    raise (monkeypatch); then `dock.site_note.text().startswith("Not drawn: ")` and the reason is
    in the tooltip.
  - `test_the_site_note_never_widens_the_dock`: set a 300-character note, and the dock's
    `minimumSizeHint().width()` is unchanged.
  - `test_export_messages_name_the_cell_and_the_pixel`, for both exports.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** Follow `refine_label`'s pattern for an `ElidedLabel` (fixed height,
  Ignored width). While the site is a preview, the label shows `preview_note`, and its hint is
  `preview_note + " " + export_refusal`. The site scope's existing show and hide on scope switch also covers `site_note`.
  `dock.error.emit` stays, so the toast still appears, but the panel is where the reason lives.
- [ ] **Step 4: Run** the three files and `test_plugin_site_engine.py`, plus lint. All pass.
- [ ] **Step 5: Commit**: `feat(slices): the panel says why: preview note, not-drawn reason, export pixel size`.

---

### Task 6: Drawn smooth, plus the docs

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py`. Add `apply_smooth_resampling(layer:
  QgsRasterLayer) -> None` and call it from `_apply_renderer` (~394), so it is re-applied after
  every repoint.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: `_add_exported_layer` (~1765) calls it, so it
  covers both exports and their coverage companions.
- Modify: `docs/guide/` wherever Slices or Whole site drawing is described (grep "Whole site",
  "Cell"). Add one short paragraph: pictures blend the cells around each pixel and are drawn
  smooth; past a size, Whole site draws a preview and says so.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/metadata.txt` changelog, under the next release, if that
  is where earlier changes were noted. Check the file first.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py` and an export test file.

**Interfaces:**
- Produces: `apply_smooth_resampling(layer)`, which sets the zoomed-in resampler to
  `QgsBilinearRasterResampler()` on `layer.resampleFilter()` and leaves zoomed-out as QGIS has it.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_slice_layer_is_drawn_smooth_after_every_repoint`: two `update` calls, then
    `layer.resampleFilter().zoomedInResampler().type() == "bilinear"`.
  - The same assertion for the site layer (`update_north_up`), and for an exported layer added
    through `_add_exported_layer`.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement**, then update the guide and changelog.
- [ ] **Step 4: Run the whole QGIS tier and the core tier once**, plus lint. All pass, apart from
  known skips and the Qt 6 dock-width xfail (#50).
- [ ] **Step 5: Commit**: `feat(slices): draw slice layers smooth when zoomed in; guide`.

---

## After the tasks (coordinator)

- **Review.** A whole-branch review (opus), then the fix wave.
- **Build and walkthrough before merge.** Deploy to a new QGIS profile and walk through spec §8.1
  on the real walkthrough site:
  - all ten grids at 0.05 m draw live;
  - zoomed in, edges are smooth;
  - a forced preview note is readable;
  - a refusal reads plainly;
  - This grid matches.

  This is a human gate: track it and report it, never pass it silently.
- **README roadmap**, in the PR: "Whole site at fine cells" moves to milestone A done (next release),
  and B stays in progress.
