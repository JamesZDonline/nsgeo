# nsgeo site view, M12 — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an archaeologist explore a whole multi-grid site as one interpretation. One depth
slider moves every grid. Every grid sits on one colour scale. Grids that really differ can be
normalised by a method the user picks and can undo. The site exports as one GeoTIFF that records
what was done to its values.

**Architecture:** Five tasks over three layers, in build order:

- **Core** gains one pure-numpy module, `nsgeo.slices.site` (Task 1). It holds:
  - the site's common north-up pixel lattice and the arithmetic for composing grids onto it;
  - the one function that maps a site-wide time window onto a grid's own axis;
  - seam detection between grids;
  - the three normalisation methods.
- **The survey file** learns to remember each grid's slice source and the site view (Task 2).
- **The plugin side** has three parts:
  - a `SiteEngine` that owns one M11 `SliceEngine` per grid, prepares them strictly one at a time, and composes a normalised site slice per tick (Task 3);
  - a site GeoTIFF exporter (Task 4);
  - the Slices dock's *This grid / Whole site* scope switch, which consumes all of it and computes nothing (Task 5).

**Tech Stack:** Python 3.9+, numpy (core, and the plugin's Qt-free `slices_plan.py`),
`qgis.PyQt` (never `PyQt5`/`PyQt6` directly), QGIS 3.40+ API, GDAL 3.8 via `osgeo.gdal`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-nsgeo-site-view-design.md`. It is binding. §4 is this
milestone, and §6 (de-striping) is **out of scope** (issue #47). Read §2–§4 and §9 before starting.
M11's spec, `docs/superpowers/specs/2026-09-18-nsgeo-slices-design.md`, explains the one-grid
machinery this builds on. M11's decision record, `docs/superpowers/sdd/2026-09-19-nsgeo-slices-m11/`,
explains why `SliceEngine` and `SlicesDock` look the way they do. Read `walkthrough-rounds.md`
there before touching the dock.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python floor 3.9.** Every module starts `from __future__ import annotations`. Annotate with
  `tuple`/`dict`/`list` and `X | Y`, never `typing.Tuple`/`Dict`/`Union`. `ruff` selects `UP` and
  rejects the old forms.
- **`ruff.toml`:** line length 100, target py39, lint select `["E", "F", "I", "UP", "B", "SIM"]`.
  `ruff check .` and `ruff format --check .` must both pass.
- **Core is numpy-only.** No Qt, no QGIS, no GDAL, no scipy anywhere under
  `packages/nsgeo-core/src/nsgeo/`. CRS transforms are the plugin's job.
- **The plugin does no signal processing.** `tests/pure/test_plugin_boundary.py` enforces the
  import rules. Importing from `nsgeo.slices`, `nsgeo.render`, `nsgeo.project`, `nsgeo.model`,
  `nsgeo.geometry` and `nsgeo.velocity` is unrestricted. Use `qgis.PyQt.*` for all Qt.
- **Every new `pyqtSignal` must have a `connect`** (`tests/pure/test_no_orphan_signals.py`).
  Declare a signal in the task that also connects it.
- **Commit trailer:** a `Co-Authored-By:` line naming the model that wrote the commit.
- **Push each commit** to `origin/nsgeo-m12` as it is made.
- **Every test that pins a numeric or structural claim must be shown to discriminate.** Build the
  plausible wrong implementation the test exists to catch and run the test against it. Record in
  the task report that the test FAILS on the wrong version and PASSES on the real code. Each task
  names the mutants it must be proven against. Set `PYTHONDONTWRITEBYTECODE=1` while doing this,
  because stale `.pyc` files fake survivors.
- **Real data first.** Tests marked as needing the real files must run, not skip. A skip there
  means the symlinks are missing, so stop and fix them.
- **Units.** Times are two-way nanoseconds. Lengths, cells and radii are metres in the frame's
  CRS, never degrees.

### Test commands (from the worktree root)

```bash
./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py
```

`-p no:xonsh` is required. A system xonsh pytest plugin aborts collection otherwise. Report both
test tiers every time. **Reproduce and record the baseline before Task 1**, because `main` has
moved since M11 (#7's fix).

### A green local QGIS suite does not imply a green CI `plugin-qgis` job

An exception raised in a slot that Qt invoked from C++ shows up differently in each environment:

- Locally, it prints to stderr and the test **passes**.
- In CI's `qgis/qgis:ltr` container, it aborts the whole job.

`tests/qgis/conftest.py`'s autouse `_no_swallowed_slot_exceptions` fails any test that leaks one.
**Never disable it or work around it.** A test that means to provoke an exception asserts on its
observable consequence instead. Every slot added here guards its body with
`except Exception` and reports, like every slot already in `slices_dock.py`.

### Established traps (all measured in this codebase)

1. **At most one line-preparation `QgsTask` may run at a time.** Two at once segfaulted M11
   reproducibly (`faulthandler` showed two workers inside `dewow.apply` and `read_header`).
   `SliceEngine.set_source` cancels and waits for its *own* previous task. Nothing yet stops
   *two engines* overlapping. Task 3 owns that, and its invariant test is the most important
   test in this plan.
2. **`addTask()` keeps no strong reference.** It needs a `_pending` set. Also:
   - `addTask()` returning 0 means the task never ran, so undo the bookkeeping;
   - `QgsTaskWrapper.finished()` swallows exceptions silently.

   `SliceEngine` already handles all of this. Compose it rather than re-implementing it.
3. **Never reuse a `LinePlan` across a frame or z-axis change.** `SliceEngine.set_resolution`
   drops plans, and `stream_slice` raises on a stale one.
4. **The shared stretch is measured over filled windows at the displayed thickness**, never over
   raw levels (`SliceEngine.shared_limit`). A limit taken over raw levels renders every slice about
   a third as bright and looks like dim data.
5. **Derive every readout from the window actually used**, `(k0, k1)`, never from the requested
   top and thickness.
6. **`QDialog.exec()` is forbidden.** Every dialog is modeless. The qgis-tier conftest forbids
   modals outright; use `answer_modal` or `drive_dialog` to opt in for one expected call.
7. **Spin boxes need a useful `singleStep`.** M11 shipped `QDoubleSpinBox`es that stepped by
   1.0 m. One arrow click set the cell size to 0.001 m and crashed QGIS (walkthrough W7).
8. **A `QComboBox` refill emits `currentTextChanged`.** Guard refills the way
   `SlicesDock._updating` does, or a refill reads as a user choice and re-prepares.

---

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `packages/nsgeo-core/src/nsgeo/slices/site.py` | Site lattice and composition; site and grid time axes; `window_on`; seams; background level; the three normalisation methods |
| `packages/nsgeo-core/tests/test_slices_site.py` | Its tests, including the real-data split-and-perturb tests |
| `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py` | `SiteEngine`: one `SliceEngine` per grid, serial preparation, per-tick composition, the site stretch |
| `packages/nsgeo-qgis/nsgeo_qgis/site_export.py` | The site GeoTIFF: band plan, writer, provenance metadata, temporal properties, coverage companion |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/site_panel.py` | `SiteSourcePanel` (grid list, transform, choose-lines) and `NormalisationPanel` (method, per-grid gain). Widgets only |
| `packages/nsgeo-qgis/scripts/bench_site.py` | The responsiveness measurement (§4.8). Not a test |
| `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py`, `test_plugin_site_export.py`, `test_plugin_site_scope.py` | Their tests |

**Modified**

| File | Change |
|---|---|
| `packages/nsgeo-core/src/nsgeo/slices/__init__.py` | Re-export `site.py`'s public names |
| `packages/nsgeo-core/src/nsgeo/model/survey.py`, `project.py` | `Site.slice_sources`, `Site.site_view`; tolerant load, save when non-empty |
| `packages/nsgeo-qgis/nsgeo_qgis/session.py` | Accessors and mutators for both; `remove_grid` prunes them |
| `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py` | `SiteSource`, `radius_cells_for`, `limit_windows`, `SITE_LIMIT_WINDOWS` |
| `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py` | Public `cancel_preparation()` |
| `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py` | `update_north_up(...)`, which `update` delegates to; `SITE_LAYER_NAME` |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` | Remembers each grid's source (Task 2); scope switch and site scope (Task 5) |
| `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` | Site preview, line chooser for a site row, export routing, teardown |

---

## Rulings taken before execution

**Ruling 1: the site composes its own `SliceEngine`s; preparation is serialised by `SiteEngine`.**
`SiteEngine` owns one `SliceEngine` per included grid. These are separate from the dock's
*This grid* engine, which M11's code and tests construct and own. `SiteEngine` dispatches one
grid at a time. Before every dispatch it checks that none of its own engines, and none of the
`exclusive_with` peers, is running. If one is, it re-tries on a 50 ms `QTimer`. It never blocks.
The dock passes its *This grid* engine as that peer. Going back to *This grid* calls
`SiteEngine.cancel()`, which uses the new public `SliceEngine.cancel_preparation()`.
*Cost if wrong:* one grid's prepared lines can be held twice (tens of MB at real sizes). Sharing
one engine pool between scopes would avoid that, but would rewrite how M11's dock owns its engine.

**Ruling 2: the rotated-cell loss is fixed for the site by the lattice pitch.** This is the
re-examination spec §4.7 asks for. A backward nearest-neighbour gather loses cells only when a
frame is rotated against the lattice:

- **Axis-aligned frame, pixel = cell.** Each frame cell contains exactly one pixel centre,
  whatever the offset.
- **Rotated frame, pixel = cell / 2.** A square of side `c` at any angle contains a disc of
  diameter `c`, and any disc wider than `(c/2)·√2 ≈ 0.71c` contains a point of a `c/2` lattice.
  So no cell is lost.

`lattice_pixel(cell, azimuths)` therefore returns `cell` when every included frame's azimuth is a
multiple of 90°, and `cell / 2` otherwise. Task 1 proves both claims with tests.
*Cost:* a site with a rotated grid has four times the lattice pixels. The fill runs on grid-local
arrays, so it is unaffected. Only the gather, the preview write and the export grow.

**Ruling 3: seams.** The seam width is `SEAM_WIDTH_SPACINGS = 1.5` × the larger line spacing of
the pair. That guarantees at least one line on each side whenever lines start within 1.5 spacings
of the edge. A seam needs `MIN_SEAM_CELLS = 20` populated cells on **each** side. Seams are only
sought between frames in the same CRS. A grid with no same-CRS neighbour takes the background-level
gain (spec §4.6, isolated grids).

**Ruling 4: the site stretch is measured over at most `SITE_LIMIT_WINDOWS = 12` windows**,
evenly spread over the site axis and always including the first and last. Each window is fully
binned, filled, normalised and adjusted. For ten grids, measuring every window would cost seconds
per change, and a display percentile does not need every window. The window list is
`slices_plan.limit_windows`, so it is Qt-free and tested.

**Ruling 5: persistence.**
- `Site.slice_sources[grid_id]` is `{"preset": str, "lines": [keys] | null, "gain": float}`. Every
  key is optional. `lines: null` means "every line on the grid", so newly imported lines are
  picked up.
- `Site.site_view` is `{"grids": [ids], "transform": str, "normalisation": str}`.
- Both are saved only when non-empty and load tolerantly. A missing key is the default. An entry
  for an unknown grid is dropped on load. A wrong top-level type raises `ProjectError`, as `cubes`
  does.
- A source is remembered **only when the user chooses it**: a combo change, or accepting the line
  chooser. It is never remembered by the automatic first preparation, so opening a site never
  marks it dirty.
- The scope itself is not persisted. The dock always opens in *This grid*.

**Ruling 6: metadata key names** for the site GeoTIFF are fixed in Task 4, not left open.

**Ruling 7: coverage in site scope** is composed like values (the mean where grids overlap,
which only happens at a rotated corner). It is a display, and the export's companion is the same.

**Ruling 8: worktree.** Work in `.worktrees/nsgeo-m12`, on branch `nsgeo-m12`, created from
`docs/m12-site-design` after merging `origin/main` into it.
- It has its own `.venv` and `.venv-qgis`. Verify that `nsgeo` resolves to the worktree's own
  source.
- The ten real DZT files are symlinked into `packages/nsgeo-core/tests/data/local/` from the main
  checkout, as M11's worktree did.

The coordinator does this setup before Task 1.

---

## Review Focus

Spec §4 implies five things no task's main tests would exercise. These are the ones most likely
to bite someone using a real site. Each has its test in the owning task.

1. **Switching scope, or closing the site, while a grid is still preparing.** Expected: nothing
   crashes, no two preparations overlap, and the scope you land in finishes its own work.
   Tested in Task 3 (`test_two_engines_never_prepare_at_once`) and Task 5
   (`test_flipping_scope_mid_preparation_never_overlaps_and_settles`).
2. **A grid whose time range does not reach the current window**, for example a grid recorded at
   a shorter range. Expected: blank on the map, named in the readout, and `null` in the export's
   per-band metadata, never a stretched end level. Tested in Task 1 (`window_on` returns `None`),
   Task 3 (`test_a_grid_outside_the_window_is_nodata_and_named`) and Task 4
   (`test_an_absent_grid_is_null_in_the_band_metadata`).
3. **Editing a grid while the site view is open:** moving, resizing, removing, or changing
   velocity. Expected:
   - The moved grid re-prepares, and the lattice, gathers and seams are rebuilt.
   - A removed grid disappears from the list and the map.
   - A velocity edit only relabels depths.

   Tested in Task 3 (`test_moving_a_grid_rebuilds_the_lattice_and_seams`,
   `test_removing_a_grid_drops_it_from_the_site`).
4. **Normalising signed slices** (transform `none`, the combo's default). Expected: finite factors
   and a sensible picture. Tested in Task 1
   (`test_background_level_measures_magnitude_on_signed_data`) and Task 3
   (`test_normalising_a_signed_site_gives_finite_factors`).
5. **A grid with no lines, or with every line excluded.** Expected: listed as `no lines`, never
   blocking the other grids or raising. Tested in Task 3
   (`test_a_grid_with_no_lines_is_listed_and_skipped`).

---

### Task 1: Core — `nsgeo.slices.site`

All numpy, no I/O. It implements the spec's §4.3 window mapping, §4.6 normalisation, §4.6.1
seams and §4.7 lattice.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/site.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` (re-export every name below)
- Test: `packages/nsgeo-core/tests/test_slices_site.py`

**Interfaces:**
- Consumes: `CubeFrame` (`axes`, `to_local`, `cell_index`, `nx`, `ny`, `cell`, `crs`, `azimuth`),
  `slice_extent`, `ZAxis`, `SliceWindow`.
- Produces:
  - `NORMALISATION_METHODS = ("none", "background", "edge", "histogram")`,
    `BACKGROUND_FRACTION = 0.75`, `SEAM_WIDTH_SPACINGS = 1.5`, `MIN_SEAM_CELLS = 20`
  - `@dataclass(frozen=True) class SiteLattice: x0: float; y1: float; pixel: float; width: int;
    height: int; crs: str`. `x0` is the west edge and `y1` the north edge, both whole multiples of
    `pixel`. It provides:
    - properties `geotransform -> tuple[float, ...]`, which is `(x0, pixel, 0.0, y1, 0.0, -pixel)`,
      and `n_pixels -> int`;
    - `pixel_centres() -> np.ndarray`, shaped `(height * width, 2)`, row-major with row 0 at the
      north;
    - `@classmethod covering(extents: Sequence[tuple[float, float, float, float]], pixel: float,
      crs: str) -> SiteLattice`, where extents are `(xmin, ymin, xmax, ymax)` already in `crs`. It
      raises `ValueError` on an empty sequence or a non-positive pixel. Width and height use
      `to_north_up`'s scale-aware epsilon snapping (`display.py`), so no phantom row appears.
  - `lattice_pixel(cell: float, azimuths: Iterable[float]) -> float`, per Ruling 2. It counts an
    azimuth as a multiple of 90° within `1e-9` degrees.
  - `compose(lattice: SiteLattice, layers: Sequence[tuple[np.ndarray, np.ndarray]]) -> np.ndarray`.
    Each layer is `(ids, values)`, where:
    - `ids` is `(n_pixels,)` from `frame.cell_index(centres)`, with -1 outside the frame;
    - `values` is the frame's `(ny, nx)` array.

    It returns a `(height, width)` float32 array. Each pixel is the mean of the finite values that
    cover it, and NaN where none do.
  - `site_axis(bounds: Iterable[tuple[float, float]], t0_ns: float, t1_ns: float, dz_ns: float)
    -> ZAxis | None`. This is the union of the grids' `(start, end)` time bounds, clipped to
    `[t0_ns, t1_ns]`, built with `ZAxis.from_range`. It returns None when nothing remains.
  - `grid_axis(site_z: ZAxis, bounds: tuple[float, float]) -> ZAxis | None`. This returns the
    levels of `site_z` that lie inside `bounds`, on `site_z`'s own lattice: `t0 = site_z.t0_ns + k·dz`
    with `k = ceil((start − site_z.t0_ns)/dz − 1e-6)`, and the same tolerance on the far end.
    It returns None when no level is inside.
  - `window_on(z: ZAxis, top_ns: float, thickness_ns: float) -> SliceWindow | None`. This is
    **the one place a site window becomes a grid window**; lining up by depth after M13 replaces
    this body. It works as follows:
    - `k0 = floor((top_ns − z.t0_ns)/z.dz_ns + 1e-6)` and
      `k1 = k0 + max(1, round(thickness_ns / z.dz_ns))`.
    - It returns None when `k1 <= 0` or `k0 >= z.nz`.
    - Otherwise it returns `SliceWindow(max(0, k0), min(k1, z.nz))`.

    The `1e-6` snap matters: without it, a grid axis offset from the site axis by a whole number of
    levels floors one level low at some slider positions.
  - `@dataclass(frozen=True) class Seam: a: str; b: str; mask_a: np.ndarray; mask_b: np.ndarray`.
    The masks are boolean, shaped `(ny, nx)` for their own frame, and already restricted to
    populated cells. `a < b`.
  - `seam_masks(frame_a: CubeFrame, frame_b: CubeFrame, width_m: float) -> tuple[np.ndarray,
    np.ndarray]`. This is geometry only. It finds the cells whose centre lies within `width_m` of
    the other frame's footprint rectangle, with distance measured in the other frame's local
    coordinates (0 inside). It returns all-False when the CRSs differ.
  - `find_seams(frames: Mapping[str, CubeFrame], coverages: Mapping[str, np.ndarray],
    spacings: Mapping[str, float], *, width_spacings: float = SEAM_WIDTH_SPACINGS,
    min_cells: int = MIN_SEAM_CELLS) -> tuple[Seam, ...]`.
  - `background_level(values: np.ndarray, coverage: np.ndarray, mask: np.ndarray | None = None)
    -> float | None`. It takes `|values|` over cells where `coverage > 0` (and `mask`), keeps the
    weakest `BACKGROUND_FRACTION` of them, and returns their mean. It returns None when no cell
    qualifies or the result is not positive.
  - `edge_match_solve(levels: Mapping[str, float | None], seam_levels: Sequence[tuple[str, str,
    float, float, float]]) -> dict[str, float]`. Each seam term is `(a, b, S_ab, S_ba, weight)`. The
    function returns a gain for every key of `levels`.
  - `normalise(method: str, slices: Mapping[str, tuple[np.ndarray, np.ndarray]], seams:
    Sequence[Seam] = (), manual: Mapping[str, float] | None = None) -> dict[str, tuple[float,
    float]]`. `slices` maps grid id to `(values, coverage)`, binned and unfilled. The result is an
    affine `(a, b)` per grid, applied as `a·v + b`, with the manual multiplier `m` already folded in
    as `(m·a, m·b)`. Method `"none"` gives `(m, 0)`. An unknown method raises `ValueError`.

- [ ] **Step 1: Write the failing tests** in `test_slices_site.py`. Use synthetic frames and arrays
  unless marked real. The assertions:

```python
def test_lattice_is_anchored_on_whole_multiples_of_the_pixel():
    lat = SiteLattice.covering([(500.13, 700.07, 506.0, 706.2)], 0.25, "EPSG:32616")
    assert lat.x0 == 500.0 and lat.y1 == 706.25          # floor / ceil to the pixel
    assert lat.geotransform == (500.0, 0.25, 0.0, 706.25, 0.0, -0.25)
    assert (lat.width, lat.height) == (24, 25)

def test_lattice_covers_the_union_and_has_no_phantom_row_at_utm_scale(): ...
    # two extents 20 m apart at x ~ 5e5: width == exact span / pixel, no +1

def test_pixel_centres_run_row_major_from_the_north(): ...
    # centres[0] == (x0 + p/2, y1 - p/2); centres[width] == (x0 + p/2, y1 - 3p/2)

def test_an_axis_aligned_frame_loses_no_cell_at_pixel_equal_to_cell():
    # frame offset by (0.37 cell, 0.81 cell); every cell id appears in cell_index(centres)
def test_a_rotated_frame_loses_cells_at_pixel_equal_to_cell():
    # azimuth 33 deg: some ids missing -- documents why Ruling 2 exists
def test_a_rotated_frame_loses_no_cell_at_half_pitch():
    # azimuths 7, 33, 45, 78 deg: every id appears with lattice_pixel(cell, [az]) == cell / 2

def test_lattice_pixel_is_the_cell_for_right_angles_and_half_for_anything_else():
    assert lattice_pixel(0.25, [0.0, 90.0, 270.0]) == 0.25
    assert lattice_pixel(0.25, [0.0, 2.0]) == 0.125

def test_compose_averages_overlaps_and_leaves_uncovered_pixels_nodata(): ...
def test_compose_of_one_layer_is_that_layer_resampled(): ...

def test_site_axis_is_the_union_clipped_to_the_requested_range(): ...
def test_grid_axis_shares_the_site_lattice_of_levels(): ...
    # grid bounds start 7 levels in: grid_z.t0_ns == site_z.t0_ns + 7 * dz (to 1e-9)

def test_window_on_agrees_with_the_site_axis_at_every_slider_position():
    site = ZAxis(t0_ns=-3.1, dz_ns=0.2165, nz=400)
    grid = grid_axis(site, (site.t0_ns + 7 * 0.2165, site.t0_ns + 300 * 0.2165))
    for v in range(7, 300):
        w = window_on(grid, site.t0_ns + v * site.dz_ns, 4 * site.dz_ns)
        assert w is not None and w.k0 == v - 7

def test_window_on_is_none_only_when_no_level_overlaps():
    z = ZAxis(t0_ns=10.0, dz_ns=0.5, nz=20)                  # 10.0 .. 19.5 ns
    assert window_on(z, 7.0, 2.0) is None                   # ends before 10.0
    assert window_on(z, 9.0, 2.0) == SliceWindow(0, 2)      # overhangs the start: thinner
    assert window_on(z, 19.5, 2.0) == SliceWindow(19, 20)
    assert window_on(z, 20.0, 2.0) is None

def test_seam_masks_find_the_strips_either_side_of_a_shared_edge(): ...
    # A = [0,5]x[0,5], B = [5,10]x[0,5], cell 0.25, width 0.75: mask_a is exactly columns 17..19
def test_seam_masks_still_find_a_seam_two_degrees_off_parallel(): ...
def test_seam_masks_are_empty_for_frames_in_different_crs(): ...
def test_find_seams_needs_min_cells_on_both_sides(): ...
    # populate only 19 cells on B's side -> no seam; 20 -> one Seam("A", "B", ...)

def test_background_level_is_the_mean_of_the_weakest_three_quarters():
    v = np.arange(1, 9, dtype=float).reshape(2, 4); c = np.ones_like(v, dtype=int)
    assert background_level(v, c) == pytest.approx(np.mean([1, 2, 3, 4, 5, 6]))
def test_background_level_ignores_unpopulated_cells_and_is_none_when_empty(): ...
def test_background_level_measures_magnitude_on_signed_data():
    v = np.array([[-8.0, 1.0, -2.0, 3.0]]); c = np.ones_like(v, dtype=int)
    assert background_level(v, c) == pytest.approx(2.0)      # weakest 3 of |v| = 1, 2, 3

def test_background_gains_have_geometric_mean_one_and_recover_a_known_gain(): ...
def test_edge_match_recovers_known_gains_along_a_chain_and_agrees_with_pairwise(): ...
def test_edge_match_spreads_a_loop_closure_error_that_pairwise_dumps_on_the_last_seam():
    # 2x2 block A-B, B-D, D-C, C-A with seam ratios multiplying to 1.21 around the loop.
    # Global: max |residual| < 0.6 * the sequential chain's residual on the closing seam.
    # The sequential chain is written in the TEST (helper), not in production code.
def test_each_connected_group_is_anchored_to_the_site_background(): ...
def test_an_isolated_grid_takes_its_background_gain(): ...
def test_histogram_match_gives_every_grid_the_pooled_mean_and_std(): ...
def test_the_manual_multiplier_composes_with_every_method(): ...
    # for m in NORMALISATION_METHODS: normalise(m, s, seams, {"A": 2.0})["A"] == 2 x the m=1 result
def test_normalise_refuses_an_unknown_method(): ...

@needs_real_files
def test_real_split_background_and_edge_recover_a_depth_dependent_gain_exactly(): ...
@needs_real_files
def test_real_split_histogram_hits_the_pooled_moments(): ...
@needs_real_files
def test_real_halves_at_different_azimuths_compose_and_find_their_seam(): ...
    # spec §9 "mixed azimuths": B's frame and its lines rotated 2 deg about the shared corner
    # (real data, invented placement). find_seams still finds Seam("A", "B");
    # lattice_pixel(...) == cell / 2; compose places every populated cell of both frames.
```

  How the real-data tests are built:
  - Prepare all ten real lines the way `test_real_files.py::test_a_cube_binned_from_real_files_is_covered_and_finite`
    does: same five steps, lines along x, `y = 0.25 + i·0.5`.
  - Lines 0–4 go in frame A, `origin (0, 0)`, `ny = 13` at cell 0.2. Lines 5–9 go in frame B,
    `origin (0, 2.6)`, with their `y` shifted by 2.6.
  - Use one axis, `ZAxis.from_range(1.0, 40.0, 0.2165)`. For each of five windows `k`, bin both
    frames with `stream_slice`.
  - Multiply B's values by `g_k = 0.5 · exp(−k/4)` and find seams with `find_seams`.
  - For `"background"` and `"edge"`, assert
    `(a_B/a_A)_perturbed == (a_B/a_A)_unperturbed / g_k` with `rtol=1e-5`. A multiplicative
    perturbation scales every background statistic exactly, so the natural difference between the
    halves cancels.
  - For `"histogram"`, assert that each grid's populated mean and std after `a·v + b` equal the
    pooled values (`rtol=1e-5`).
  - `needs_real_files` is `pytest.mark.skipif(not FILES, ...)`, exactly as `test_real_files.py`
    defines it.

- [ ] **Step 2: Run them; every test fails on import.**
  Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_site.py -q`

- [ ] **Step 3: Implement `site.py`** to the Interfaces above. Most of the module follows directly
  from the signatures and tests. Two parts do not, and are spelled out here:

```python
# edge_match_solve: weighted least squares in log space, then per-group anchoring
ids = sorted(levels)
x = dict.fromkeys(ids, 0.0)
for group in connected_components(ids, seam_levels):        # singletons included
    terms = [s for s in seam_levels if s[0] in group]
    if terms:
        A, rhs, w = [], [], []
        for a, b, s_ab, s_ba, weight in terms:              # x_a + ln s_ab = x_b + ln s_ba
            row = {a: 1.0, b: -1.0}
            A.append([row.get(g, 0.0) for g in group]); rhs.append(log(s_ba) - log(s_ab))
            w.append(sqrt(weight))
        sol = lstsq(A * w[:, None], rhs * w)                # minimum-norm, gauge-free
        x.update(zip(group, sol))
    # anchor: the group's corrected backgrounds match the site's in the geometric mean
    known = [g for g in group if levels[g]]
    if known:
        shift = ln_b_site - mean(x[g] + log(levels[g]) for g in known)
        for g in group: x[g] += shift
# finally: renormalise so mean(x) over ids is 0 -> geometric mean gain 1
```

  Here `ln_b_site` is the mean of `log(level)` over grids whose level is known. A grid whose level
  is None, and which sits in a group with no known level, keeps gain 1.0. For `normalise("edge")`:
  - `levels` holds each grid's `background_level`;
  - each seam term holds the two strips' `background_level(values, coverage, mask)` and the weight
    `min(mask_a.sum(), mask_b.sum())`;
  - a seam whose strip level is None is dropped.

  Histogram: pool the values of every grid's populated cells, so the pooled mean and std are taken
  over all populated cells. Then `a_i = σ_p/σ_i` and `b_i = μ_p − a_i·μ_i`. A grid with `σ_i == 0`
  or no populated cells gets `(1, 0)`.

- [ ] **Step 4: Run the file, then the whole core and pure tier; all pass, and the two real-data
  tests run, not skip.**

- [ ] **Step 5: Prove discrimination.** Each test must fail against these mutants and pass again
  once the mutant is reverted:
  1. background over **all** populated cells (not the weakest 75%);
  2. `values` instead of `|values|`;
  3. arithmetic instead of geometric site mean;
  4. edge-solve sign flipped (`ln s_ab − ln s_ba`);
  5. group anchoring removed;
  6. `lattice_pixel` always returns `cell`;
  7. `covering` anchored at `min xmin` instead of a multiple of the pixel;
  8. `window_on` without the `1e-6` snap;
  9. `compose` keeps the first layer instead of averaging.

  Record each in the report.

- [ ] **Step 6: ruff, format and mypy clean; commit and push.**
  `feat(core): site lattice, window mapping, seams and normalisation`

---

### Task 2: The survey remembers each grid's slice source and the site view

The site view needs every grid's preset and line choice, and *This grid* scope reads and writes the
same record (spec §4.2, Ruling 5). After this task, *This grid* behaves differently: switching to a
grid and back restores what you chose for it instead of resetting to the defaults.

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (add the two fields, with a docstring
  giving the record shapes), `packages/nsgeo-core/src/nsgeo/project.py` (`save_site`, `load_site`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`, `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- Test: `packages/nsgeo-core/tests/test_project.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`

**Interfaces:**
- Produces (core):
  - `Site.slice_sources: dict[str, dict[str, Any]]`, default `{}`;
  - `Site.site_view: dict[str, Any]`, default `{}`.

  Both have the shapes in Ruling 5.
- Produces (session; each mutator marks the site dirty, and is a no-op that leaves dirty untouched
  when nothing changes):
  - `slice_source(grid_id: str) -> dict[str, Any] | None`, which returns a copy;
  - `remember_slice_source(grid_id: str, *, preset: str, lines: tuple[str, ...] | None) -> None`;
  - `grid_gain(grid_id: str) -> float` (1.0 when unset) and
    `set_grid_gain(grid_id: str, gain: float) -> None`, which raises `ValueError` unless
    `0 < gain`;
  - `site_view() -> dict[str, Any]`, which returns a copy, and
    `set_site_view(*, grids: tuple[str, ...] | None = None, transform: str | None = None,
    normalisation: str | None = None) -> None`, which merges and validates `normalisation` against
    `NORMALISATION_METHODS`.
  - `remove_grid` also deletes `slice_sources[grid_id]` and removes the id from
    `site_view["grids"]`.
- No new signal. Consumers read these when they need them, so there is no orphan to connect.
- Dock (*This grid* scope):
  - On a real grid change (`_sync_included`'s grid-changed branch), if the grid has a remembered
    source:
    - select its preset, inside the `_updating` guard, if the preset still exists;
    - set `_included` from `lines`, filtered to keys still on the grid, with
      `_included_is_default = False`;
    - if `lines` is None, use the default and set `_included_is_default = True`.
  - `_on_source_changed`, a real user change, remembers the source. So does `set_included` when
    the set actually changed. Both remember `lines=None if self._included_is_default else
    self._included`.
  - The first-computation path in `rebuild_source` never remembers anything.

- [ ] **Step 1: Write the failing tests.**

```python
# core, test_project.py
def test_slice_sources_and_site_view_round_trip(tmp_path): ...
def test_a_survey_without_them_loads_with_empty_defaults(tmp_path): ...
def test_a_wrong_top_level_type_is_a_project_error(tmp_path): ...    # "slice_sources": []
def test_an_entry_for_an_unknown_grid_is_dropped_on_load(tmp_path): ...
def test_empty_ones_are_not_written(tmp_path): ...                   # keys absent from the JSON

# qgis, test_plugin_session.py
def test_remembering_an_unchanged_source_does_not_mark_dirty(...): ...
def test_set_grid_gain_refuses_zero_and_negative(...): ...
def test_set_site_view_refuses_an_unknown_method(...): ...
def test_removing_a_grid_prunes_its_source_and_its_site_view_entry(...): ...

# qgis, test_plugin_slices_dock.py
def test_switching_grid_away_and_back_restores_that_grids_preset_and_lines(docked_two_grids): ...
def test_a_default_line_choice_picks_up_a_line_imported_later(docked_two_grids): ...
def test_opening_a_site_does_not_mark_it_dirty(...): ...
def test_choosing_lines_remembers_them_for_that_grid_only(docked_two_grids): ...
```

  `docked_two_grids` is a new fixture in the dock test file. It is the existing `docked` setup
  plus a second grid `"B"` with its own synthetic lines.

- [ ] **Step 2: Run them; all fail.** Then run the existing dock tests. If any existing test
  asserted that returning to a grid **resets** its lines, update it to the spec's new behaviour
  and name each one in the report. Change nothing else about M11's dock.

- [ ] **Step 3: Implement.** In `load_site`, apply `cubes`' type check and then drop unknown-grid
  entries. Copy on read and copy on write: never hand out the stored dict.

- [ ] **Step 4: Both tiers green.**

- [ ] **Step 5: Mutants.** Each must fail at least one test:
  1. remembering in the first-computation path;
  2. not filtering remembered keys to the grid's current lines;
  3. `remove_grid` not pruning;
  4. `remember_slice_source` marking dirty when nothing changed.

- [ ] **Step 6: Commit and push.**
  `feat: remember each grid's slice source and the site view in the survey`

---

### Task 3: `SiteEngine`

This is the engine behind *Whole site*. It owns one M11 `SliceEngine` per included grid and
prepares them one at a time (Ruling 1, trap 1). Each grid is drawn as soon as it is ready, and
each tick is composed into a normalised site slice. The task also measures responsiveness (spec
§4.8).

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`, `packages/nsgeo-qgis/scripts/bench_site.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`, `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py`,
  `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`

**Interfaces:**
- Consumes:
  - Task 1's `SiteLattice`, `lattice_pixel`, `compose`, `site_axis`, `grid_axis`, `window_on`,
    `find_seams`, `normalise`;
  - M11's `SliceEngine` (`set_source`, `set_resolution`, `slice_at`, `prepared_z_bounds`,
    `frame`, `z`, `is_running`, `is_prepared`, `choice`, `provenance`, `estimate`, `clear`,
    `dispose`) and `fill`, `slice_extent`, `limit_over_slices`;
  - `session.grid(grid_id)` for each grid's `default_spacing`, `crs` and frame. Manual gains
    arrive as the `manual` argument; the engine never reads them from the session.
- Produces (`slices_plan.py`, Qt-free, with pure-tier tests):
  - `@dataclass(frozen=True) class SiteSource: transform: str; grids: tuple[SourceChoice, ...]`.
    `__post_init__` raises `ValueError` if any `choice.transform != transform` or if a grid id
    repeats.
  - `radius_cells_for(spacing_m: float, radius_spacings: float, cell: float) -> int`, which is
    `max(0, round(radius_spacings · spacing_m / cell))`.
  - `SITE_LIMIT_WINDOWS = 12` and
    `limit_windows(z: ZAxis, thickness_levels: int, max_windows: int = SITE_LIMIT_WINDOWS) ->
    tuple[SliceWindow, ...]`. This takes `plan_windows(z, thickness, thickness)` plus
    `display.shared_limit`'s thinner tail window. If there are more than `max_windows`, it keeps
    an evenly spaced subset that always includes the first and the last.
- Produces (`slices_engine.py`): `SliceEngine.cancel_preparation() -> None`. It is public and
  wraps `_cancel_in_flight()`, and its docstring explains why it exists (Ruling 1). Afterwards
  `is_running` is False. The engine's lines are not trusted: the caller re-dispatches.
- Produces (`site_engine.py`):
  - `@dataclass(frozen=True) class SiteSlice: array: np.ndarray; lattice: SiteLattice; windows:
    dict[str, SliceWindow | None]; factors: dict[str, tuple[float, float]]`.
    - `array` is `(height, width)` float32, with NaN for nodata.
    - `windows` covers every ready grid, with None meaning absent at this time.
    - `factors` is the applied `(a, b)` for each grid present, with the manual gain included.
  - `class SiteEngine(QObject)`:
    - `__init__(session, on_changed: Callable[[], None] | None = None, on_error:
      Callable[[str], None] | None = None, exclusive_with: Sequence[SliceEngine] = (), parent:
      QObject | None = None)`. `on_changed` fires whenever a grid becomes ready, fails or is
      dropped, or the geometry is rebuilt. It connects `session.site_closed` to `clear` and
      `session.grids_changed` to a geometry rebuild.
    - `set_source(source: SiteSource) -> None`. It diffs against the current source:
      - unchanged grids keep their prepared lines;
      - changed grids are queued;
      - removed grids' engines are disposed;
      - a grid with no line keys is state `"no lines"` and is never dispatched.
    - `set_resolution(resolution: Resolution) -> None`. This stores the site resolution and
      re-derives the geometry. For the bounds of the ready grids:
      - `site_z = site_axis(...)`;
      - per ready grid, `gz = grid_axis(site_z, engine.prepared_z_bounds())`, then
        `engine.set_resolution(Resolution(res.cell, res.dz_ns, gz.t0_ns, gz.t_end_ns))`, or no
        resolution when `gz` is None;
      - the lattice: grid extents transformed to the site CRS, `lattice_pixel` over the ready
        grids' azimuths.

      It raises `ValueError` naming the pixel count when `lattice.n_pixels > MAX_FRAME_CELLS`, as
      spec §4.7's size guard requires.
    - Properties: `site_z -> ZAxis | None`, `lattice -> SiteLattice | None`,
      `ready_grids -> tuple[str, ...]`, `is_running -> bool`.
    - `grid_state(grid_id: str) -> str`, one of `"ready"`, `"preparing"`, `"queued"`,
      `"no lines"`, or `"failed: <message>"`.
    - `engine_for(grid_id: str) -> SliceEngine | None`, for read-only use: provenance, z, frame.
    - `slice_at(top_ns: float, thickness_ns: float, *, radius_spacings: float, method: str,
      manual: Mapping[str, float], coverage: bool = False) -> SiteSlice`.
    - `shared_limit(thickness_ns: float, clip: Any, *, radius_spacings: float, method: str,
      manual: Mapping[str, float]) -> float`.
    - `cancel() -> None`, `clear() -> None`, `dispose() -> None`, `status_text() -> str`, and
      `wait_until_idle(timeout_ms: int = 60_000) -> bool` for tests.

**One tick, `slice_at`:**
1. For each ready grid with a z, `w = window_on(engine.z, top_ns, thickness_ns)`. If `w` is
   None, the grid is absent.
2. `values, cov = engine.slice_at(w)`.
3. `factors = normalise(method, {g: (values, cov)}, seams, manual)`.
4. For each present grid, `shown = a·fill(values, cov, radius_cells_for(spacing_g,
   radius_spacings, cell)) + b`. In `coverage` mode, show the coverage with 0 as NaN, and skip
   normalisation.
5. `compose(lattice, [(gather_g, shown_g)])`.

Caches, each dropped on any resolution change, grid edit or source change:
- **Gathers:** computed once per (grid, frame, lattice). Lattice pixel centres are transformed
  with `QgsCoordinateTransform` into a frame's CRS when it differs from the site's.
- **Seams:** computed once per geometry, from each ready grid's coverage. Coverage does not depend
  on the window, so take it from any one slice. Spacings are each grid's `default_spacing`.

**Preparation (`_dispatch_next`):** if any own engine or `exclusive_with` peer `is_running`, do
`QTimer.singleShot(50, self._dispatch_next)` and return. Otherwise pop the queue head and call its
engine's `set_source(choice)`. The engine's `on_prepared` and `on_error` mark the grid's state,
call `on_changed`, re-derive geometry and dispatch the next grid. Every callback guards itself
(trap 2).

- [ ] **Step 1: Write the failing tests.** Pure tier: `SiteSource` validation,
  `radius_cells_for`, and `limit_windows` (count ≤ 12, first and last included, the tail
  included). The qgis tier uses a fixture `site3` with three adjacent 6 × 6 m synthetic grids,
  `"A"`, `"B"` and `"C"`, four lines each, in `EPSG:32616`.

```python
def test_two_engines_never_prepare_at_once(site3, monkeypatch):
    # Line.load patched to sleep 0.05 s under a lock-guarded counter (M11's
    # test_two_different_choices_back_to_back_never_run_concurrently pattern).
    # A peer SliceEngine passed as exclusive_with is set_source'd at the same moment as
    # SiteEngine.set_source(3 grids); later, cancel() then set_source again.
    assert max_concurrent == 1 and all(states == "ready")
def test_grids_prepare_in_order_and_each_is_drawn_as_soon_as_ready(site3): ...
    # after the first on_changed, slice_at returns finite pixels over A only
def test_changing_one_grids_preset_re_prepares_only_that_grid(site3, monkeypatch): ...
    # count Line.load calls: 4, not 12
def test_a_grid_with_no_lines_is_listed_and_skipped(site3): ...
def test_a_grid_outside_the_window_is_nodata_and_named(site3): ...
    # C's lines cropped to a shorter time range: windows["C"] is None, its pixels NaN
def test_background_normalisation_evens_out_a_grid_recorded_at_double_gain(site3): ...
    # B's synthetic data written x2: with "none" mean(B pixels) ~ 2 x mean(A); with "background" ~ equal (rtol 0.05)
def test_the_manual_gain_multiplies_only_that_grids_pixels(site3): ...
def test_normalising_a_signed_site_gives_finite_factors(site3): ...      # transform NO_TRANSFORM
def test_the_shared_limit_follows_normalisation(site3): ...
def test_a_grid_in_another_crs_lands_where_its_coordinates_say(site3): ...
    # B re-declared in EPSG:26916; the B cell centre transformed to 32616 holds B's value
def test_grids_too_far_apart_for_the_lattice_are_refused_by_pixel_count(site3): ...
def test_moving_a_grid_rebuilds_the_lattice_and_seams(site3): ...
def test_removing_a_grid_drops_it_from_the_site(site3): ...
def test_a_velocity_edit_does_not_re_prepare_or_change_the_slice(site3): ...
def test_closing_the_site_mid_preparation_clears_without_overlap(site3, monkeypatch): ...
```

- [ ] **Step 2: Run them; all fail.**

- [ ] **Step 3: Implement** `slices_plan.py`'s additions, `cancel_preparation`, then
  `site_engine.py`. `status_text` reads, for example,
  `3 grids · 62 lines held in memory, 74 MB · slices redraw in 11 ms`. The memory is the sum of the
  engines' `estimate.total_bytes`. The redraw time is the smoothed time of `slice_at`, using M11's
  `_REDRAW_SMOOTHING`.

- [ ] **Step 4: Both tiers green.** Run the concurrency test 20 times in a loop and record that it
  never fails.

- [ ] **Step 5: Mutants.** Each must fail at least one test:
  1. `_dispatch_next` ignores `exclusive_with`;
  2. it ignores its own other engines;
  3. `set_source` re-queues unchanged grids;
  4. gathers not transformed for another CRS;
  5. normalisation factors applied before `fill` with `b ≠ 0` (histogram): assert the composed
     values equal `a·fill(v) + b`;
  6. the shared limit measured on unnormalised slices.

- [ ] **Step 6: Measure (spec §4.8).** `scripts/bench_site.py` builds synthetic sites of ten grids,
  20 m and 50 m on a side, at 0.5 m line spacing and M11's default resolution. It runs in
  `.venv-qgis` offscreen, with no plugin or iface. It prints, for each size:
  - preparation time for the whole site;
  - median and 90th-percentile `slice_at` over 20 windows;
  - `shared_limit` time;
  - the M11 baseline: one 50 m grid's `SliceEngine.slice_at` plus `fill`.

  Put the table in the task report. **The coordinator then rules** whether Task 5's conditional
  step applies. The rule: it applies when the 10 × 50 m median `slice_at` exceeds 100 ms or 3 × the
  one-grid baseline, whichever is larger.

- [ ] **Step 7: Commit and push.**
  `feat(qgis): SiteEngine -- one engine per grid, prepared one at a time`

---

### Task 4: The site GeoTIFF

Spec §4.7: one file covering every included grid, with a band per slice, values as shown, and a
record of what was done. Built and tested against `SiteEngine` directly. Task 5 wires the button.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py`

**Interfaces:**
- Consumes:
  - Task 3's `SiteEngine` (`site_z`, `lattice`, `slice_at`, `engine_for`, `ready_grids`);
  - Task 1's `window_on`;
  - M11's `plan_windows`, `window_times_ns`, `window_depths_m`, `band_time_range`, and
    `GeoTiffSliceWriter.OPTIONS`, which is reused, not copied.
- Produces:
  - `@dataclass(frozen=True) class SiteGridRecord: grid_id: str; preset: str; velocity: dict[str,
    Any] | None; gain: float; line_spacing_m: float; azimuth_deg: float; crs: str`. `velocity` is
    `VelocityModel.to_dict()`, so layered models survive.
  - `@dataclass(frozen=True) class SiteBand: window: SliceWindow; description: str; depths:
    dict[str, tuple[float, float] | None]`. `window` is on `site_z`. The description reads, for
    example, `12.0-16.0 ns · A 0.60-0.80 m · B 0.52-0.70 m · C no data`, derived from each grid's
    actual `window_on` result (trap 5).
  - `@dataclass(frozen=True) class SiteExportPlan: lattice: SiteLattice; site_z: ZAxis; bands:
    tuple[SiteBand, ...]; transform: str; method: str; cell_m: float; radius_spacings: float;
    grids: tuple[SiteGridRecord, ...]`.
  - `plan_site_export(site_engine, thickness_levels: int, step_levels: int, *, transform: str,
    method: str, radius_spacings: float, gains: Mapping[str, float], velocities: Mapping[str,
    VelocityModel | None]) -> SiteExportPlan`.
  - `export_site(site_engine, path: str | Path, thickness_levels: int, step_levels: int, *,
    transform, method, radius_spacings, gains, velocities, writer: SiteWriter | None = None) ->
    SiteExportPlan`. It pulls one `slice_at` per band and holds no cube, as M11 does.
  - `class GeoTiffSiteWriter` with `write(path, plan, slices: Iterable[SiteSlice]) -> None`.
  - `apply_site_temporal_properties(layer: QgsRasterLayer, plan: SiteExportPlan) -> None`.
  - `write_site_coverage(site_engine, path: str | Path, plan: SiteExportPlan) -> Path`. This
    writes `<stem>_coverage.tif` with one band: the composed coverage at the first band's window.
  - Metadata keys (Ruling 6). Values are strings, and the JSON is compact.
    - Dataset: `NSGEO_SITE_TRANSFORM`, `NSGEO_SITE_NORMALISATION`, `NSGEO_SITE_CELL_M`,
      `NSGEO_SITE_PIXEL_M`, `NSGEO_SITE_FILL_RADIUS_SPACINGS`, `NSGEO_SITE_Z_UNIT` (`"ns"`), and
      `NSGEO_SITE_GRIDS` (a JSON list of the `SiteGridRecord`s as objects).
    - Per band, as band metadata: `NSGEO_WINDOW_NS` (`"lo,hi"`), `NSGEO_GRID_DEPTHS_M` (a JSON
      object, id → `[lo, hi]` or `null`), and `NSGEO_GRID_FACTORS` (a JSON object, id → `[a, b]`
      or `null`).

- [ ] **Step 1: Write the failing tests** (reuse Task 3's `site3` fixture; move it to
  `tests/qgis/conftest.py` if needed):

```python
def test_the_file_lands_on_the_site_lattice(site3, tmp_path): ...        # geotransform, size, CRS
def test_there_is_a_band_per_planned_window(site3, tmp_path): ...
def test_each_band_is_exactly_what_slice_at_shows(site3, tmp_path): ...    # normalised, filled
def test_the_dataset_records_transform_method_and_every_grid(site3, tmp_path): ...
def test_each_band_records_every_grids_factors_and_depths(site3, tmp_path): ...
def test_an_absent_grid_is_null_in_the_band_metadata(site3, tmp_path): ...
def test_band_descriptions_name_each_grids_depths(site3, tmp_path): ...
def test_temporal_ranges_follow_the_ns_windows(site3, tmp_path): ...
def test_export_never_builds_a_resident_cube(site3, tmp_path): ...          # stub writer
def test_the_coverage_companion_is_written_beside_it(site3, tmp_path): ...
```

- [ ] **Step 2: Run them; all fail.**
- [ ] **Step 3: Implement.** Follow `slice_export.GeoTiffSliceWriter.write` for GDAL exception
  handling, the band count probe after the loop, and NaN nodata. Unlike it, there is no resample:
  `SiteSlice.array` is already on the lattice.
- [ ] **Step 4: Green.**
- [ ] **Step 5: Mutants.** Each must fail at least one test:
  1. per-band factors taken from the first band;
  2. depths derived from the requested window instead of `window_on`'s;
  3. an absent grid written as `[1, 0]` instead of `null`.
- [ ] **Step 6: Commit and push.** `feat(qgis): the site GeoTIFF, which records what was done`

---

### Task 5: The Slices dock's *Whole site* scope

Spec §4.1–§4.5. The dock consumes Tasks 2–4 and computes nothing.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_panel.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`, `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py`,
  `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`, plus
  `test_plugin_slice_layer.py` for `update_north_up`

**Interfaces:**
- Consumes: everything above.
- Produces (`ui/site_panel.py`, widgets only):
  - `@dataclass(frozen=True) class SiteRow: grid_id: str; preset: str; lines: str; state: str;
    included: bool`.
  - `class SiteSourcePanel(QWidget)`:
    - signals: `included_changed = pyqtSignal(object)` (a tuple of grid ids),
      `transform_changed = pyqtSignal(str)`, `selected_changed = pyqtSignal(str)` and
      `choose_lines_requested = pyqtSignal(str)`;
    - methods: `set_rows(rows: Sequence[SiteRow])`, `selected_grid() -> str | None`,
      `included() -> tuple[str, ...]`, `set_transform(name: str)`.
    - The table has columns ✓ / Grid / Preset / Lines / State, and is refilled under a guard
      (trap 8).
    - The button reads `Choose lines for <grid>…` and is disabled with no selection.
  - `class NormalisationPanel(QWidget)`:
    - signals: `method_changed = pyqtSignal(str)` (a method id) and
      `gain_changed = pyqtSignal(str, float)`;
    - methods: `set_method(method: str)`, `method() -> str`, and
      `set_grid(grid_id: str | None, gain: float)`.
    - Combo labels map to method ids: `None` → none, `Background level` → background,
      `Edge match` → edge, `Histogram match` → histogram.
    - The gain spin has prefix `×`, range 0.10–10.00, step 0.05 (trap 7), 2 decimals, and default
      1.00. It is disabled with no grid selected. A `Reset` button sets it to 1.00.
- Produces (`slice_layer.py`):
  - `SITE_LAYER_NAME = "Site slice (live preview)"`;
  - `SliceLayer.update_north_up(array, geotransform, crs, *, limit, colormap_name, unipolar,
    subtitle, name: str = LAYER_NAME) -> None`. `update` now resamples and delegates to it, with
    unchanged behaviour. `name` renames the existing layer in place and does not rebuild it.
- Produces (`SlicesDock`):
  - `scope() -> str` (`"grid"` or `"site"`) and `set_scope(scope: str) -> None`;
  - the attributes `grid_scope_button`, `site_scope_button` (checkable, exclusive, at the top of
    the body), `site_engine`, `site_panel`, `normalisation_panel`, `radius_spacing_spin` and
    `site_depths_label`;
  - `current_site_slice() -> SiteSlice | None`;
  - `line_choice_grid() -> str | None` and `line_choice_keys(grid_id: str) -> tuple[str, ...]`;
  - `set_included_for(grid_id: str, keys: tuple[str, ...]) -> None`;
  - `site_velocities() -> dict[str, VelocityModel | None]`.
- Behaviour, scope by scope:
  - ***This grid*:** exactly M11, with Task 2's memory.
  - ***Whole site*, groups:**
    - `source_group` is hidden; `site_panel` and `normalisation_panel` are shown;
    - `radius_spin` is hidden and `radius_spacing_spin` shown (suffix ` × line spacing`, 0–10,
      step 0.25, default 1.5, with a tooltip giving each grid's radius in metres);
    - `save_button` is hidden; `export_button` reads `Export site GeoTIFF…`.
  - ***Whole site*, stretch:** item 0 of `stretch_combo` reads `shared across the site`. Its index
    meaning is unchanged.
  - ***Whole site*, resolution:**
    - the cell size is seeded by M11's rule applied to the finest-spaced included grid, only when
      the included set changes;
    - dz, z0 and z1 are seeded from the union of the ready grids' prepared bounds, with the
      first-ready clamp M11 uses;
    - the slider runs over `site_engine.site_z`.
  - ***Whole site*, readout:** `slice i / N · lo–hi ns`, with `site_depths_label` below it reading,
    for example, `A 0.60–0.80 m · B 0.52–0.70 m · C no data`. Each depth uses that grid's resolved
    velocity, the way M11's `_resolved_velocity` does per grid.
  - **Both scopes, profile band:** `window_changed(lo_ns, hi_ns)` is emitted from the window
    shown.
  - **Switching scope:**
    - It keeps the window's time. The new slider is set to the level nearest the old top time.
    - Leaving *Whole site* calls `site_engine.cancel()`.
    - Entering it builds a `SiteSource` from `session.site_view()` and each grid's
      `slice_source()`. Default included grids are every grid with lines. A grid's default preset
      is its remembered one, else the first preset.
  - **Persistence:** the included set, transform and method go to `session.set_site_view`; a gain
    edit goes to `session.set_grid_gain`.
  - **Normalisation is off by default** (spec §4.6). The panel starts at `None`, and a survey
    with no `site_view["normalisation"]` restores `None`.
- Plugin:
  - `_on_slice_changed` in site scope calls `slice_layer.update_north_up(site_slice.array,
    lattice.geotransform, lattice.crs, ..., name=SITE_LAYER_NAME)`. In grid scope it is M11's
    path, with the layer name restored.
  - `open_line_choice_dialog` uses `dock.line_choice_grid()` and `line_choice_keys()`, and commits
    through `set_included_for`. Ruling Z's check compares `line_choice_grid()` at `finished` with
    the grid at open time.
  - `export_geotiff` routes to a new `export_site_geotiff()` when `dock.scope() == "site"`. That
    method:
    - asks for a path, defaulting to `slices/site.tif`;
    - calls `export_site` with the dock's thickness and step levels, method, radius, gains and
      `site_velocities()`;
    - adds the layer to the site group and applies the temporal properties;
    - writes the coverage companion when the coverage toggle is on, following M11's
      `export_geotiff`, including the separate `try` for the companion (Ruling AH).
  - `unload` disposes `site_engine`.

- [ ] **Step 1: Write the failing tests** (`site3` from conftest, plus a `plugin` built with it):

```python
def test_the_scope_switch_swaps_the_source_controls(...): ...
def test_whole_site_draws_one_layer_covering_every_grid(...): ...       # SITE_LAYER_NAME, extent
def test_one_slider_moves_every_grid(...): ...
def test_switching_scope_keeps_the_window_time(...): ...
def test_unticking_a_grid_removes_it_from_the_map(...): ...
def test_the_method_combo_changes_the_drawn_values(...): ...
def test_the_gain_spin_scales_only_the_selected_grid(...): ...
def test_choose_lines_acts_on_the_selected_grid_only(...): ...
def test_the_site_view_survives_save_and_reopen(...): ...              # grids, transform, method, gains
def test_the_readout_names_each_grids_depth_and_any_absent_grid(...): ...
def test_export_routes_to_the_site_geotiff_in_site_scope(answer_modal, ...): ...
def test_flipping_scope_mid_preparation_never_overlaps_and_settles(..., monkeypatch): ...
def test_unload_with_the_site_scope_open_leaves_nothing_running(...): ...
def test_the_gain_spin_steps_by_a_useful_increment(...): ...           # singleStep == 0.05
def test_update_north_up_renames_the_layer_in_place(...): ...           # test_plugin_slice_layer.py
```

- [ ] **Step 2: Run them; all fail.** M11's whole dock suite must still pass unchanged, apart from
  any test Task 2 already updated.
- [ ] **Step 3: Implement `site_panel.py`, `update_north_up`, then the dock and plugin wiring.**
  Keep the site-scope logic in a few dock methods that delegate (`_refresh_site_slice`,
  `_site_source`, `_on_site_changed`, `_apply_site_resolution`), so `slices_dock.py` grows by
  composition, not by a second copy of M11's flow.
- [ ] **Step 4 (conditional on Task 3's ruling): drag degradation.** While
  `slice_slider.isSliderDown()`, site ticks call `slice_at(..., radius_spacings=0.0)`. Fill is
  skipped and normalisation still applies. `sliderReleased` triggers one full refresh. The test is
  `test_dragging_draws_unfilled_and_release_draws_full`. If the ruling is that it isn't needed,
  record that and skip this step.
- [ ] **Step 5: Both tiers green; ruff, format and mypy clean.**
- [ ] **Step 6: Mutants.** Each must fail at least one test:
  1. the scope switch not cancelling the site engine;
  2. the window not carried across scopes;
  3. the gain applied to every grid;
  4. `set_included_for` writing to the *This grid* inclusion in site scope.
- [ ] **Step 7: Commit and push.**
  `feat(qgis): the Slices dock's Whole site scope`

---

## After Task 5: whole-branch review, deploy, and the acceptance walkthrough

The tests cannot make this check, and the user must make it (spec §9). It follows the standing
procedure, as M11 did: build and walk through before any merge decision.

1. Run the whole-branch review, then fix and re-review until it is clean.
2. Deploy this worktree to the `ns_geo` profile for the walkthrough with
   `.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo`. Afterwards,
   re-point the profile's plugin symlink at `.worktrees/nsgeo-main`, the standing deploy target
   for `main`. Check `ls -la` on the profile's plugins directory before and after.
3. Build the walkthrough as an Artifact with persisted results. The user runs it **on their own
   multi-grid data, privately**; nothing from that data enters the repo. The steps are below.
   Phrase each one positively and only ask for what can be seen.
   - Open a survey with several grids. The Slices dock has *This grid* and *Whole site* buttons
     at the top.
   - Click *Whole site*. Every grid with lines is listed and ticked, and each prepares in turn.
     Each grid appears on the map as soon as its state reads *ready*.
   - Drag the depth slider. Every grid moves together. The readout gives the ns window, and the
     line below it gives each grid's depth range.
   - With Normalisation set to *None*, note any step in brightness at a seam. Switch to
     *Background level*, *Edge match* and *Histogram match* in turn. The map updates each time.
     Which method gives the most continuous site?
   - Select one grid and raise its gain to ×1.50. Only that grid brightens. *Reset* returns it.
   - Untick a grid. It leaves the map. Tick it again. It returns without re-preparing.
   - Choose lines for one grid. Only that grid re-prepares.
   - Switch to *This grid*. The same window is shown for the selected grid. Switch back. The site
     returns at the same window.
   - Export the site GeoTIFF. It opens as one layer covering every grid, and its bands step
     through depth. `gdalinfo` on the file lists `NSGEO_SITE_NORMALISATION` and each band's
     `NSGEO_GRID_FACTORS`.
   - Save, close and reopen the survey, then click *Whole site*. The same grids, transform, method
     and gains are restored.
   - Drag the slider continuously across the whole range on your largest site. It keeps up with
     the drag.
4. Record every finding in the decision record. Only then present the merge decision.
