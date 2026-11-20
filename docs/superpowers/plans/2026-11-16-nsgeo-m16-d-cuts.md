# M16 Plan D: Cuts in 3-D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Picks made on cuts join surfaces exactly like picks on lines. The ParaView export gains **walls**: every line, and every saved cut on the grid, standing as a curtain coloured like the Slices panel. Each wall is its own item, hidden when the scene opens.

**Architecture:**
- **Placing a cut pick.** A cut pick is a distance along its cut and a time on the cube's clock. Placing one means:
  - `cut.point_at(distance)` in grid metres;
  - then the world, through `grid.to_world`;
  - then the frame, through `frame.to_local`;
  - with the time used as it is, when the pick was made on the clock the grid's preset now uses.
- **`place_picks` and `pick_depths` learn that rule once,** and every consumer follows: surfaces, `picks.vtp` and the 3-D view.
- **Walls are new core code** (numpy only): a line wall samples the line's prepared traces, and a cut wall samples the filled cube along the cut. Both go onto the cube's levels.
- **A new core writer** puts each wall in its own VTK StructuredGrid file. The scene script opens one reader per wall.

**Tech Stack:**
- Python 3.9+ and numpy (core).
- QGIS 3.40 / 3.44 / 4.2 (plugin).
- pytest.
- ParaView 6.2.1's `pvpython` for one optional test.

**Spec:** `docs/superpowers/specs/2026-11-11-nsgeo-m16-3d-design.md`. Read these parts first:
- §5.2's file table (`walls.vts`) and its scene list;
- §5.5, cuts;
- §8, Plan D.

M15's cut spec, `docs/superpowers/specs/2026-10-30-nsgeo-cut-anywhere-design.md`, defines how cuts and cut picks are stored. Call 18 there says a cut pick's time is on the cube's clock.

**Builds after Plan C merges.** Branch `nsgeo-m16-d` off main once `docs/superpowers/plans/2026-11-16-nsgeo-m16-c-qgis-3d-view.md` is built and merged. Task 2 extends Plan C's `pick_depths` and `Scene3D`.

## Global Constraints

- **Run every test from the worktree root with `PYTHONPATH=packages/nsgeo-core/src`.** Below, `R=/home/jameszd/Documents/Github/archaeo_geophysics`.
  - **Core and pure:** `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`
  - **QGIS:** `PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen $R/.venv-qgis/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`. The whole tier takes about 37 minutes, so run single files while iterating.
- **Lint as CI does:** `ruff check .`, `ruff format --check .`, and the mypy command in `.github/workflows/ci.yml` (job `lint`). The new core module is already covered, because the list includes all of `packages/nsgeo-core/src/nsgeo`.
- **The core uses numpy only,** with a Python 3.9 floor: `from __future__ import annotations`, no `zip(strict=...)` and no `match`. No new dependency anywhere.
- **No ParaView code lives in a `.py` file inside `packages/`.** Scene code goes in `packages/nsgeo-qgis/nsgeo_qgis/paraview/open_scene.py.txt`.
- **Plugin boundary.** Arithmetic and message text live in the core, `surface_plan.py`, `paraview_scene.py` or `slices_plan.py`, never in widgets.
- **Qt rules as in Plan C:** fully qualified enums, guarded slots, and no orphan signals.
- **Authored data.**
  - **Picks:** a cut pick is never moved, retimed or rewritten. Joining or leaving a surface changes only its `feature_id`, as for line picks.
  - **Cuts:** `survey.nsgeo.json` is never written by this plan.
- **The export's rules hold:**
  - it states its size before writing, and the size now includes the walls;
  - it refuses when the disk is too full;
  - it writes into `<grid>.partial` and swaps it in only when complete, so a cancel or a failure leaves the previous export whole;
  - no second full copy of the cube is held.
- **No site coordinates, real survey files or site pictures are committed.**
- **Commits:**
  - every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - push each one to `origin nsgeo-m16-d` as you make it.

## Before Task 1 (coordinator)

- Create the worktree `.worktrees/nsgeo-m16-d` off main, after Plan C's merge. Link the real data into `packages/nsgeo-core/tests/data/local/` file by file, but not `README.md`, which is tracked.
- Record a baseline: the core and pure suites, then `test_plugin_surface_build.py`, `test_plugin_surfaces_membership.py`, `test_plugin_paraview_export.py`, `test_plugin_scene3d.py` and `tests/pure/test_paraview_scene.py`.
- `export NSGEO_PVPYTHON=/home/jameszd/Documents/Software/ParaView-6.2.1-MPI-Linux-Python3.12-x86_64/bin/pvpython`
- Before each task, run `git fetch && git merge origin/main`.

## Review Focus

These are the inputs the spec implies but none of its tests feed. Each is pinned by a test in the task named.

1. **A cut pick made on another clock.** The pick was made while the preset set time zero, and the preset no longer does, or the other way round.
   - The surface leaves it out and lists it as "made on another clock".
   - The export and the 3-D view leave it out.
   - It is never placed at the wrong depth.

   *Task 1:* `test_a_cut_pick_on_another_clock_is_reported_not_placed`.
2. **A surface holding picks on a cut that is then deleted.** The surface turns stale. A rebuild reports those picks as "their cut has been deleted", and nothing raises. *Task 1:* `test_a_deleted_cut_marks_its_surfaces_stale_and_is_reported`.
3. **A cut that leaves the grid's frame, or has a vertex outside the lines' coverage.** Its wall is NaN (transparent) where there is no data. A cut pick outside the frame is reported "on a hole", as for lines. *Task 3:* `test_a_cut_wall_is_nan_where_the_cube_has_no_data`. *Task 1:* `test_a_cut_pick_outside_the_frame_is_reported_on_a_hole`.
4. **A grid with many lines and long cuts.**
   - Each wall has at most 300 columns.
   - The stated size matches what is written, to within 2%.
   - The refusal for a full disk counts the walls.

   *Task 4:* `test_the_stated_size_includes_the_walls_and_matches_the_files`.
5. **A cut or line name with quotes, slashes or accents.** Wall files are named by index, never by name, and the scene still opens. *Task 4:* `test_wall_files_are_named_by_index_and_the_scene_opens`.

## Calls this plan makes (the spec left them to the builder)

1. **Walls go in `walls/<index>.vts`, one file per wall,** not a single `walls.vts`. A StructuredGrid file holds one grid, and one file per wall gives one ParaView item each (spec §5.5). The scene lists them from `export.json`'s `walls`. **Cost if wrong:** about 40 small files in place of one.
2. **Walls are coloured like the scene's slices** (Slices panel style, black is strong). They use the cube's `amplitude` array name and its colour scale `[0, amplitude p99]`, so a wall and a slice through it agree.
   - A line wall's values are the line's prepared traces (preset and transform applied, before the fill).
   - A cut wall's values are the filled cube's.

   The profile view's own percentile and colour map are not copied. **Cost if wrong:** a wall reads differently from the profile view, but the same as the slices.
3. **Walls stand on the cube's own time levels,** with Z = −depth × stretch through the grid's velocity, so they meet the slices and surfaces. Each wall has at most `MAX_WALL_COLUMNS = 300` columns, evenly spaced along it. **Cost if wrong:** walls look coarser along a long line than the profile view; the constant can rise.
4. **Lines get walls only if they went into the cube.** Lines skipped from the cube (in `export.json`'s `skipped_lines`) get none. **Cost if wrong:** a skipped line has no wall, but it is already listed as skipped.
5. **The time base of a cut pick** is `json.loads(pick.stack_json)["time_base"]`, the section's provenance stored with the pick. A pick whose provenance has no `time_base` is treated as on the radar clock. **Cost if wrong:** an old cut pick is left out as "on another clock".
6. **Cut picks join surfaces through the same checks as line picks:**
   - one grid (the cut's);
   - saved;
   - at least three, not in a line.

   The "picks on cuts can join surfaces in a later version" refusal is removed. **Cost if wrong:** none; this is what spec §5.5 asks.

---

### Task 1: Picks on cuts join surfaces

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py` (`place_picks`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/surfaces.py` (`check`, `_grid_of`, `inputs`, the fit's skipped reasons)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/surface_plan.py` (`selection_refusal`, the new reasons)
- Modify: `docs/guide/getting-started.md`, the line "Picks on cuts cannot be used yet."
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_surface_build.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_surfaces_membership.py`, `packages/nsgeo-qgis/tests/pure/test_pure_surface_plan.py`

**Interfaces:**
- Consumes:
  - `nsgeo.model.cut.Cut` (`key`, `grid_id`, `vertices`, `point_at(distance_m)` in grid metres) and `is_cut_key`;
  - `session.cut_for_key(key)` (raises `KeyError`) and `session.cut_keys_on_grid(grid_id)`;
  - `Grid.to_world(local: np.ndarray) -> np.ndarray`;
  - `CubeFrame.to_local(world)`.
- Produces:
  - `place_picks(rows, lines, prov, frame, velocity, *, cuts: Mapping[str, Cut] | None = None, grid: Grid | None = None) -> list[PlacedPick | None]`. A cut pick is placed when its key is in `cuts`, `grid` is given, and its time base equals `time_base_of(prov.steps)`. Its `trace` is the stored column.
  - `cut_pick_base(pick) -> str` in `surface_plan.py`, implementing call 5.
  - `WHY_OTHER_CLOCK = "they were made on a cut on another clock"` and `WHY_NO_CUT = "their cut has been deleted"` in `surface_plan.py`.
  - `selection_refusal` loses its `on_cuts` parameter.

- [ ] **Step 1: Write the failing tests.**
  - Use the `built_site` fixture. Add a cut along line 0 with `session.add_cut(GRID, [(0.5, 0.5), (0.5, 11.5)])`. The fixture's preset sets time zero, so a placeable cut pick carries `"time_base": "time_zero"`.
  - Write cut picks with `layers.write_pick(Pick(line_key=cut_key, trace=col, distance_m=d, time_ns=t, zero_ns=None, stack_json=json.dumps({"time_base": base}), ...))`, as `conftest.surface_plugin` writes line picks.

```python
def test_a_cut_pick_lands_where_the_line_pick_under_it_lands(built_site):
    # A cut drawn along line 0 (x = 0.5): a cut pick at the same place and moment as a line pick
    # is placed at the same depth and, within half a cell, the same spot.
    ...
    a, b = place_picks([(line_key, line_pick), (cut_key, cut_pick)], got.lines, got.prov,
                       got.frame, got.velocity, cuts={cut_key: cut}, grid=session.grid(GRID))
    assert b.depth_m == pytest.approx(a.depth_m)
    assert math.hypot(b.x_m - a.x_m, b.y_m - a.y_m) <= got.frame.cell / 2

def test_a_surface_builds_from_line_and_cut_picks_together(built_site): ...
    # three line picks + two cut picks -> check() accepts; build -> fit counts five picks

def test_a_cut_pick_on_another_clock_is_reported_not_placed(built_site): ...
    # preset STEPS_ZERO, cut pick with time_base "radar" -> place_picks gives None; the build's
    # skipped list names WHY_OTHER_CLOCK for it; the other picks build

def test_a_deleted_cut_marks_its_surfaces_stale_and_is_reported(built_site): ...
    # build with a cut pick; session.delete_cut(cut_key) (the M15 delete) -> state(...).stale
    # contains "source"; rebuild -> skipped reason WHY_NO_CUT; no raise

def test_a_cut_pick_outside_the_frame_is_reported_on_a_hole(built_site): ...

def test_a_cut_picks_distance_not_its_column_is_its_identity(built_site): ...
    # changing only the stored column (trace) of a cut pick leaves the surface fresh; moving its
    # distance_m marks it stale ("picks")
```

  In `test_pure_surface_plan.py`, replace the cut-refusal assertion with:

```python
def test_cut_picks_are_no_longer_refused():
    assert "cut" not in (selection_refusal(...the same args without on_cuts...) or "")

def test_a_cut_picks_time_base_comes_from_its_provenance():
    assert cut_pick_base(_pick(stack_json='{"time_base": "time_zero"}')) == "time_zero"
    assert cut_pick_base(_pick(stack_json="")) == "radar"
    assert cut_pick_base(_pick(stack_json="not json")) == "radar"
```

  Spell each test out in full, with the asserts its comment names. Find the M15 call that deletes a cut by searching `session.py` for `cuts_changed` emitters.

- [ ] **Step 2: Run them; they fail.**

- [ ] **Step 3: Implement.**
  - **`place_picks`:**
    - a cut pick is placed as the Architecture section says;
    - the time is `p.time_ns`, never retimed;
    - the base comes from `cut_pick_base`, compared with `time_base_of(prov.steps)`;
    - a cut missing from `cuts` gives None.
  - **`Surfaces`:**
    - `_grid_of` answers a cut key with `session.cut_for_key(key).grid_id`, and with None on `KeyError`;
    - `check` stops counting `on_cuts`;
    - the build passes `cuts={k: session.cut_for_key(k) for the member cut keys that still exist}` and `grid=session.grid(grid_id)` to `place_picks`;
    - a None for a cut key gets a reason: `WHY_NO_CUT` when the cut is gone, `WHY_OTHER_CLOCK` when the base differs, else `WHY_NO_DEPTH`.
  - **`inputs()`:**
    - the `picks` entry for a cut pick is `[key, round(distance_m, 4), round(radar_ns, 6)]`;
    - `source` gains `"cuts": sorted([key, vertices or None] for each member cut key)`, so a deleted or redrawn cut marks the surface stale.
  - **The guide:** replace "Picks on cuts cannot be used yet." with a sentence saying picks on cuts join surfaces like picks on lines, as long as they were made on the clock the grid's preset uses now.

- [ ] **Step 4: Run the three test files; they pass.** Run `test_plugin_paraview_export.py` too, since `place_picks` changed, then the lint commands.

- [ ] **Step 5: Commit and push.**

```bash
git add -u packages/nsgeo-qgis docs/guide/getting-started.md
git commit -m "feat(surfaces): picks on cuts join surfaces, on the cube's clock (M16 D)"
git push origin nsgeo-m16-d
```

### Task 2: Cut picks in the export's picks and in the 3-D view

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py` (`_write_picks`, `_pick_counts`, `pick_depths`, `_record`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_scene.py` (`scene_record`: a defaulted `cuts` field)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/scene3d.py`, which reads the scene grid's cut picks too
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_scene3d.py`, `packages/nsgeo-qgis/tests/pure/test_paraview_scene.py`

**Interfaces:**
- Consumes: Task 1's `place_picks(..., cuts=, grid=)` and `cut_pick_base`.
- Produces:
  - **`picks.vtp`:**
    - it gains an int32 `cut` array: the pick's index in `export.json`'s `cuts`, or −1;
    - `line` is −1 for a cut pick.
  - **`export.json`** gains `cuts: [{"index": int, "key": str, "name": str}]`, one per saved cut on the grid, in key order. `scene_record` validates it and defaults it to `[]`.
  - **`pick_depths`** answers cut keys by Task 1's rule.

- [ ] **Step 1: Write the failing tests.**

```python
def test_cut_picks_are_in_picks_vtp_with_their_cut(built_site): ...
    # one cut with two picks on the grid -> picks.vtp has them with cut == 0 and line == -1,
    # true_depth_m equal to place_picks'; export.json["cuts"] == [{"index": 0, "key": ..., "name": "Cut 1"}]
    # summary(...).n_picks counts them

def test_a_cut_pick_on_another_clock_is_left_out_of_the_export(built_site): ...

def test_the_3d_view_shows_the_grids_cut_picks(scene): ...
    # Plan C's fixture + a cut pick -> one more point in the picks layer at -depth*stretch

def test_scene_record_validates_cuts():
    # pure: missing -> []; wrong keys or misnumbered -> ValueError
```

  Spell each test out in full, with the asserts its comment names.

- [ ] **Step 2: Run them; they fail.**

- [ ] **Step 3: Implement.**
  - `_write_picks` adds the rows of `session.picks_for(k)` for `k` in `session.cut_keys_on_grid(grid_id)`, after the lines' rows. It passes `cuts` and `grid` to `place_picks`, and fills `cut` and `line` as above.
  - `_pick_counts` counts the same rows.
  - `pick_depths` uses Task 1's rule for cut keys.
  - `Scene3D` reads the cut picks of the scene grid as well as the line picks. A cut pick's point is its map position on the picks layer.

- [ ] **Step 4: Run the test files; they pass.** Then run the lint commands.

- [ ] **Step 5: Commit and push.**

```bash
git add -u packages/nsgeo-qgis
git commit -m "feat(paraview,3d): cut picks in picks.vtp, export.json and the 3-D view (M16 D)"
git push origin nsgeo-m16-d
```

### Task 3: Walls in the core, and a StructuredGrid writer

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/walls.py`
- Modify: `packages/nsgeo-core/src/nsgeo/vtkxml.py`
- Modify: `packages/nsgeo-core/tests/vtk_reader.py`, which reads `.vts` too
- Test: `packages/nsgeo-core/tests/test_slices_walls.py`, `packages/nsgeo-core/tests/test_vtkxml.py` (or the file that tests the writers today)

**Interfaces:**
- Consumes:
  - `PreparedLine`;
  - `CubeFrame` (`to_local`, `axes`, `origin`, `cell`);
  - `ZAxis.times_ns()`;
  - `resample.bilinear_taps(frame, world)` and `resample.sample(level, taps)`.
- Produces, in `walls.py`:
  - `MAX_WALL_COLUMNS: int = 300`;
  - `@dataclass(frozen=True) class Wall: local: np.ndarray  # (n, 2) frame-local metres along the wall; values: np.ndarray  # (nz, n) float32, NaN where nothing was recorded`;
  - `def wall_columns(n: int) -> int`, which is `min(n, MAX_WALL_COLUMNS)` for n ≥ 2, and raises `ValueError` below 2;
  - `def line_wall(line: PreparedLine, frame: CubeFrame, z: ZAxis) -> Wall`:
    - traces at `np.linspace(0, n_traces - 1, wall_columns(n_traces))`, rounded and unique;
    - values linearly interpolated from the line's samples at `z.times_ns()`, the line's axis being the cube's clock, as in `plan_line`;
    - NaN outside the line's time range;
  - `def cut_wall(filled: np.ndarray, frame: CubeFrame, path_local: np.ndarray) -> Wall`:
    - `filled` is (nz, ny, nx);
    - `wall_columns(...)` points evenly spaced along the path by distance, where `n` is `ceil(length / (cell / 2)) + 1`;
    - `sample(filled[k], taps)` for each level `k`;
  - `def wall_points(wall: Wall, depth_m: np.ndarray, stretch: float) -> np.ndarray`, which returns (nz, n, 3) with z = `-depth_m[k] * stretch`.
- Produces, in `vtkxml.py`:
  - `def write_structured_grid(path: Path, points: np.ndarray, point_data: dict[str, np.ndarray]) -> int`:
    - `points` is (nj, ni, 3) and each array is (nj, ni);
    - it writes appended raw binary like the other writers, with `WholeExtent="0 ni-1 0 nj-1 0 0"`;
    - it returns the bytes written;
  - `def structured_grid_bytes(n_points: int, n_arrays: int) -> int`, which is exact, as `image_data_bytes` is.

- [ ] **Step 1: Write the failing tests.** Use the real lines from `tests/real_lines.py` (`prepared_lines`, `AXIS`), as the volume tests do.

```python
def test_a_line_wall_follows_the_line_at_the_cubes_levels():
    line = prepared_lines([0], to_world)[0]
    frame = CubeFrame.for_grid(GRID, CELL); z = AXIS
    wall = line_wall(line, frame, z)
    assert wall.values.shape == (z.nz, wall_columns(line.data.shape[1]))
    k = z.nz // 2; t = z.times_ns()[k]
    i = int(round((t - line.t0_ns) / line.dt_ns))
    assert wall.values[k, 0] == pytest.approx(line.data[i, 0], rel=0.05)  # near a sample
    assert np.allclose(wall.local[0], frame.to_local(line.coords[:1])[0])

def test_a_long_line_wall_is_capped_at_300_columns(): ...
def test_a_cut_wall_samples_the_filled_cube_along_the_cut(): ...
    # a filled cube with a known ramp in x -> the wall's values follow the ramp along a cut in x
def test_a_cut_wall_is_nan_where_the_cube_has_no_data(): ...
def test_wall_points_stand_at_stretched_depth(): ...
def test_structured_grid_round_trips_and_its_size_is_exact(tmp_path):
    pts = np.random.default_rng(0).random((4, 5, 3)); amp = np.arange(20.0).reshape(4, 5)
    n = write_structured_grid(tmp_path / "w.vts", pts, {"amplitude": amp})
    doc = read_vtk_xml(tmp_path / "w.vts")
    assert np.allclose(doc["points"].reshape(4, 5, 3), pts)
    assert np.allclose(doc["point_data"]["amplitude"].reshape(4, 5), amp)
    assert doc["WholeExtent"] == (0, 4, 0, 3, 0, 0)
    assert n == (tmp_path / "w.vts").stat().st_size == structured_grid_bytes(20, 1)
```

  Spell each test out in full, with the asserts its comment names.

- [ ] **Step 2: Run them; they fail.**

- [ ] **Step 3: Implement `walls.py`, `write_structured_grid` and `structured_grid_bytes`.** Teach `vtk_reader.read_vtk_xml` the `StructuredGrid` element (`WholeExtent`, points). Points and the `amplitude` array are written as float32.

- [ ] **Step 4: Run the core suite; it passes.** Then run the lint commands.

- [ ] **Step 5: Commit and push.**

```bash
git add packages/nsgeo-core
git commit -m "feat(core): line and cut walls on the cube's levels; a StructuredGrid writer (M16 D)"
git push origin nsgeo-m16-d
```

### Task 4: Walls in the export and the scene

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py` (`run`, `estimate`, `summary`, `_record`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_scene.py` (`scene_record`: a defaulted `walls` field; `ExportSummary` and `summary_rows` count walls)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview/open_scene.py.txt` and `paraview/README.md.txt`
- Modify: `docs/guide/getting-started.md` (Step 9's list of what is in the folder)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py`, `packages/nsgeo-qgis/tests/pure/test_paraview_scene.py`

**Interfaces:**
- Consumes: Task 3's `line_wall`, `cut_wall`, `wall_points`, `wall_columns`, `write_structured_grid` and `structured_grid_bytes`.
- Produces:
  - **`export.json`** gains `walls: [{"index": int, "name": str, "kind": "line" | "cut", "file": "walls/<index>.vts"}]`. Lines come first, in `source.line_keys` order, named by the line's file stem; cuts follow, in key order, named by the cut's name.
  - **`ExportSummary`** gains `n_walls: int` and `walls_bytes: int`. `export_bytes` includes `walls_bytes`.
  - **`summary_rows`** names the walls, for example "34 walls, about 76 MB".

- [ ] **Step 1: Write the failing tests.**

```python
@needs_real_data
def test_every_line_and_cut_gets_a_wall(site): ...
    # add a cut; run -> walls/0.vts..; export.json["walls"] lists 4 lines then the cut, files exist,
    # each .vts has an "amplitude" array, nz rows, <= 300 columns; z of row k == -depth_k * stretch

@needs_real_data
def test_the_stated_size_includes_the_walls_and_matches_the_files(site): ...
    # summary(...).export_bytes within 2% of the folder's total size after run; the refusal path
    # (monkeypatched free space between cube-only and cube+walls) refuses

def test_wall_files_are_named_by_index_and_the_scene_opens(synth_site): ...
    # a cut named 'a "quoted"/cut é' -> its file is walls/<n>.vts; under NSGEO_PVPYTHON the scene
    # script runs and registers "Cut: a "quoted"/cut é" (skipped without pvpython)

def test_a_cancelled_export_leaves_no_walls_behind(site): ...
    # cancel during the wall writes -> no .partial left, the previous export untouched

def test_scene_record_validates_walls():  # pure
```

  Spell each test out in full, with the asserts its comment names.

- [ ] **Step 2: Run them; they fail.**

- [ ] **Step 3: Implement.**
  - **In `run()`**, after `_write_lines`, write each wall into `partial / "walls"` while `got.lines` and `got.filled` are alive:
    - line walls are `line_wall(line, frame, z)`;
    - cut walls are `cut_wall(filled, frame, frame.to_local(grid.to_world(np.asarray(cut.vertices))))`;
    - depths come from `velocity.depth_at(z.times_ns())`;
    - points come from `wall_points`.
  - **Progress.** Each wall is one progress step, counted into `state["total"]` in `announce`.
  - **Size and refusal.** `estimate()` and the refusal in `run()` add `walls_bytes`: the sum over walls of `structured_grid_bytes(wall_columns(n) * nz, 1)`, where:
    - `n` is the line's trace count from its header, or the cut's `ceil(length / (cell / 2)) + 1`;
    - `nz` is the cube's level count.

    Put the arithmetic in `slices_plan.py` beside `export_size_bytes`.
  - **The scene template.** After the surfaces block, add one `XMLStructuredGridReader` per `INFO["walls"]` entry:
    - `registrationName` is `"Wall: " + name` for a line and `"Cut: " + name` for a cut, handed to ParaView as data, never as code;
    - it is shown coloured by `("POINTS", "amplitude")` with `amp_lut`, then hidden.

    `amp_lut` keeps being set last.
  - **The guide and the export's own README** gain one line: "Walls: every line and every cut, as a curtain coloured like the slices (black is strong), one item each, hidden at first."

- [ ] **Step 4: Run the test files.** Then run the whole QGIS tier once, the core and pure suites, and the lint commands. All pass.

- [ ] **Step 5: Commit and push.**

```bash
git add -u packages/nsgeo-qgis docs/guide/getting-started.md
git commit -m "feat(paraview): walls for every line and cut in the export and the scene (M16 D)"
git push origin nsgeo-m16-d
```

## After Task 4: the walkthrough (human gate)

Use a fresh profile, `ns_geo_m16d`, and a copy of the Sunnyside site. Write the walkthrough as an Artifact with a results database.

1. **Cut picks in a surface.**
   - Draw a cut across the bowl and pick the bowl's reflection on it.
   - Add those picks to Feature1, or build a new surface from line picks and cut picks.
   - The fit counts them, and the surface fills where only the cut had picks.
2. **Another clock.** Switch the grid's preset between time zero and none. The cut picks are reported "made on another clock" and are not used.
3. **Export Grid 1.** The dialog's size row counts the walls. In ParaView, each line and cut is an item under its own name, hidden at first.
   - Show a few.
   - They stand at the slices' depths, coloured like a depth slice.
   - The cut wall agrees with the cut in the profile view.
4. **Deleting the cut.** Delete the cut. Its surfaces turn stale, and a rebuild reports the picks.
5. **The 3-D view.** The cut picks show in the 3-D view.
