# M15 Cut Anywhere — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: run the failing test and see it fail before writing any production code.

**Goal:** The user draws a line on the map and the profile shows the cube's vertical section beneath it. Hover, select, cursor tracking and picks work as they do for a survey line. Each depth is finished exactly as a slice is. Under minimum curvature the cut shows kriging at once and is solved near the cut in the background. A cut moves with its grid, and its picks follow it.

**Architecture:**
- **Core.**
  - A `Cut` value (`nsgeo/model/cut.py`): an id, a name, a grid id, and vertices in grid-local metres. `Site.cuts` stores the cuts, and `survey.nsgeo.json` saves them.
  - `nsgeo/slices/section.py` turns a cut into columns (distance, world position, cell) and reads a finished section from a cube's levels.
    - IDW and kriging reuse the grid's weights.
    - Smoothing works on crops round the cut.
    - Minimum curvature is solved one depth at a time, on crops.
- **Session and storage.** `SiteSession` keeps cuts beside lines, under keys `cut:<id>`, and the same `open_line`, preview, trace and pick paths accept them. `SiteLayers` gains a derived, read-only `cuts` table. The Survey panel lists cuts under their grid, with Open, Rename and Delete.
- **Seeing a cut.** `CutSections` (`nsgeo_qgis/cut_sections.py`) finds the cube the Slices panel uses for a cut's grid in the scope on screen. It builds and caches the section and tells the profile when it changes. `ProfileDock` draws it in the Slices panel's palette, with its own title, axes and disabled controls.
- **The map.** `CutTool` draws a cut. `MapLink` works on cuts while the cuts layer is QGIS's current layer, and on lines otherwise.
- **Minimum curvature.** `CutSections` owns a second `Refiner` thread. When the working cut stands in with kriging, it solves the cut one depth per job and swaps rows in as they land.

**Tech Stack:** Python 3, numpy (core); PyQt through `qgis.PyQt`, QGIS map tools and rubber bands, and `concurrent.futures` through `Refiner` (plugin); pytest on two tiers: core and pure in `.venv`, QGIS in `.venv-qgis`.

**Spec:** `docs/superpowers/specs/2026-10-30-nsgeo-cut-anywhere-design.md`, approved 2026-10-30 and revised 2026-11-06 (`630d85d`). Read §3 (decisions and calls 1–17), §4 and §8 before any task. Where this plan and the spec disagree, the plan wins, because it records the decisions below.

## Plan calls (where the spec leaves the builder a choice)

1. **One code path, keyed.** A cut is not a `Line`.
   - The session's per-key API (`open_line`, `set_preview`, `set_trace`, `set_selection`, `resolved_velocity`) accepts `cut:<id>` keys.
   - Every consumer that needs a `Line` asks `is_cut_key(key)` first: the profile, the loader, the processing panel and the map link.
   - `keys()` stays lines-only, so line-only code (exports, slices, follow) is untouched. `cut_keys()` lists cuts.
2. **Keys and ids.**
   - A cut's id is `uuid.uuid4().hex` and its key is `"cut:" + id`.
   - Line keys are DZT paths ending in `.dzt` (any case), so the two cannot collide.
   - The id never changes; rename changes only `name`.
3. **The survey file.**
   - A site with cuts saves `"schema_version": 2` and a `"cuts"` list. A site without cuts still saves 1.
   - `load_site` accepts 1 and 2. 0.2.0 refuses a file with cuts and says so, rather than opening it and silently dropping the cuts on its next save. Sites without cuts stay readable by 0.2.0.
   - A cut entry is `{"id", "name", "grid_id", "vertices": [[x, y], …]}`. A malformed entry, or one on an unknown grid, is a `ProjectError`, as a line on an unknown grid is.
4. **Columns.**
   - Columns are `frame.cell / 2` apart along the cut, from 0, with a last column exactly at the cut's length.
   - Each column takes the value of the cell it falls in (spec call 11). Its cell comes from frame-local coordinates, so the ids match `CubeFrame.cell_index` of its world position (tested).
   - The session's "trace" for a cut is a column index. It is clamped only below (−1), because the column count belongs to the section, not the session. It is never the truth for a pick (spec call 12).
5. **Where the values come from.**
   - A section reads the engine's resident cube (`SliceEngine.cube()`, every level). A hover preview never builds one. If the engine holds no cube, the preview shows a message.
   - Opening a cut (select, Survey panel Open, finishing a drawing) builds the cube synchronously under a wait cursor. That meets §5's "must not freeze the canvas on hover", and a streaming engine's first cut pays the build once.
6. **Fills.**
   - The section asks the engine for its fills through a new public `SliceEngine.section_fills(finish)`. It returns what the engine holds when its key matches, and otherwise builds through the engine's own `_fill_for`. A cut never plans weights of its own (§5).
   - Minimum curvature's kriging stand-in is the engine's `PREVIEW_METHOD` weights.
7. **Crops.**
   - Smoothing crops reach the smoothing kernel's radius (`ceil(SMOOTH_TRUNCATE_SIGMAS · σ / cell)` cells) past the cut's cells, so a smoothed section equals the smoothed slice exactly.
   - Minimum-curvature crops reach `max(SECTION_MARGIN_M, the smoothing reach)`.
   - Pieces cover at most `SECTION_PIECE_M` of the cut. These are the spike's settings: ±1 m and 4 m pieces gave 0.002% at 0.25 s a level on Grid 1 at 0.05 m.
8. **Two worker threads, not one shared.** A cut's solve runs on its own `Refiner` (thread prefix `nsgeo-cut`).
   - Why: the slice's `Refiner.start` cancels whatever runs, so a shared thread would kill one list with the other. A second thread means the slice's refine never queues behind a cut (spec §4.7's fairness rule).
   - The jobs are one depth each. Depths are solved outward from the slice band's centre, so the depth the user is looking at improves first.
9. **The cursor and marker on a cut.**
   - The map link projects the pointer onto the cut (`closestSegmentWithContext` for the hit test). It converts that point to grid metres and uses `Cut.locate` for the distance, then `CutSections.column_at` for the column (spec call 14).
   - The marker goes at the column's world position.
   - With no section there is no column. The preview still opens, with no cursor.
10. **The current-layer switch.**
    - The plugin listens to `iface.currentLayerChanged` and calls `MapLink.set_cut_mode(layer is the cuts layer)`, comparing layer ids so a CRS rebuild's new layer object still counts.
    - Changing mode clears any preview.
    - Turning **Cut** on calls `iface.setActiveLayer(cuts layer)`.
11. **The guide step goes after "Build slices",** not straight after "Make a pick". A cut needs the grid prepared in the Slices panel, so it reads in that order. The old Step 8 becomes Step 9.
12. **Survey panel layout.** A grid with cuts gets a **Cuts** child item, placed before its lines and holding one item per cut in drawing order. Cut items have kind `"cut"` and id = key.

## Global Constraints

- **The core stays numpy-only, with no Qt.**
  - `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` stay green.
  - No scipy.
  - The plugin imports Qt only through `qgis.PyQt`.
- **Python 3.9 floor for the core:** no `zip(..., strict=...)`, no `match`, no `X | Y` outside annotations, no `dataclass(slots=..., kw_only=...)`.
- **Slots guard their bodies.** Every slot connected to a Qt signal or timer, and every Qt-invoked map-tool method, guards its own body. It reports through `_log`, a `failed`/`error` signal, or the message bar, and never raises. This includes `CutSections`' slots, `CutTool`'s events, and the plugin's `currentLayerChanged` slot.
- **No orphan signals.** `tests/pure/test_no_orphan_signals.py` stays green, so every new `pyqtSignal` is connected.
- **Picks are authored data.**
  - Writes go through the loaded layer's provider, as `write_pick` and `follow_lines` do.
  - Nothing here deletes a pick. Deleting a cut or removing a grid leaves its picks where they are.
- **Exact values:**

  | Name | Value |
  |---|---|
  | `CUT_KEY_PREFIX` | `"cut:"` |
  | Default cut name | `Cut {n}`, with n one more than the highest existing `Cut <n>` (so names are never reused while a higher one exists) |
  | `CUTS_SCHEMA_VERSION` | `2`. It is written only when `site.cuts` is non-empty. `load_site` reads `(1, 2)`. |
  | Column step | `frame.cell / 2` |
  | `SECTION_MARGIN_M` | `1.0` |
  | `SECTION_PIECE_M` | `4.0` |
  | Crop agreement with a whole-frame solve | ≤ `1e-3` of the level's finite data range, on the cut's columns |
  | `CUT_SOLVE_REST_MS` | `300` |
  | `CUT_REDRAW_MS` | `250` |
  | `CUT_THREAD_NAME_PREFIX` | `"nsgeo-cut"` |
  | `cuts` table | LineString; fields `cut_key` (str), `name` (str), `grid_id` (str), `length_m` (float) |
  | `LEGEND_ORDER` | `("picks", "marks", "cuts", "lines", "grids")` |
  | Cuts layer style | solid, 0.6 mm, `#e6550d`, labelled with `name` (lines are dashed and coloured by grid) |

- **Exact text** (one constant each, in the module that shows it):

  | Constant | Text |
  |---|---|
  | `NO_SOURCE_TEXT` | `{name} is on {grid}. Show {grid} in the Slices panel to see it.` |
  | `NO_CUBE_TEXT` | `Select {name} to build {grid}'s cube for it.` |
  | `OUTSIDE_TEXT` | `Start a cut inside a grid.` |
  | `TOO_FEW_TEXT` | `A cut needs two different points.` |
  | `CUT_HINT_TEXT` | `Cut: click to add points; right-click or Enter to finish; Backspace removes the last point; Esc cancels.` |
  | `VELOCITY_ON_CUT_TIP` | `Velocity fitting needs a recorded line: a cut at a slant widens hyperbolas and would give a wrong velocity.` |
  | `PALETTE_ON_CUT_TIP` | `A cut uses the Slices panel's palette.` |
  | `PROCESSING_ON_CUT_TEXT` | `Processing does not apply to a cut.` |
  | `CUT_GONE_TEXT` | `This pick's cut no longer exists. The pick stays where it was drawn.` |
  | Delete prompt | `Delete {name}?`, plus ` Its 1 pick stays on the map.` or ` Its {n} picks stay on the map.` |
  | Grid removal addition | ` Its {n} cut(s) are deleted too; their picks stay on the map.` (`cut`/`cuts` by count) |
  | Profile title | `nsgeo Profile · cut: {name} · {grid} · {length:.1f} m · {method}`, then ` · site view, not normalised` in Whole site scope, and the existing `PREVIEW: ` prefix on a preview. The `cut:` stays even after a rename, so the title always says a cut is showing (decision 11). |
  | `{method}` | `METHOD_LABELS[method]`. While kriging stands in: `Kriging preview (minimum curvature when opened)` on a preview, `Kriging preview · minimum curvature {done} of {total} depths` while solving, and `Minimum curvature` when done. |

- **Comments and docstrings** follow the file they are in. They say why, and cite the spec as `(cut spec §4.7)`.
- **Shared-worktree safety.** Reviewers and any mutation testing never edit this worktree; they work on a scratch copy. Set `PYTHONDONTWRITEBYTECODE=1` for every test run.

## Before Task 1 (coordinator)

1. **Wait for the dependencies.** Line editing (`nsgeo-line-editing`), and the roadmap's earlier item #107–#109, must be merged to main. Merge `origin/main` into `nsgeo-m15-cut-anywhere`. Confirm that `SiteLayers.follow_lines` and `SiteSession.derived_pick_fields` exist. Tasks 2 and 5 extend them, and the line numbers in this plan's sources were taken before that merge.
2. **Build both venvs** in the worktree (`.venv` for core + pure, `.venv-qgis` for QGIS), as for slice interpolation B.
3. **Copy the real files** from the main checkout's `packages/nsgeo-core/tests/data/local/` into the worktree's (gitignored).
4. **Record the baseline:** core + pure and QGIS counts, ruff and mypy.
5. **Keep the spike for reference.** It is in the session scratchpad (`cut_cost.py`, `band_cost.py`, `crop_cost.py`) and is not committed.

## Verification commands (exactly these, from the worktree root)

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`. About 11 minutes, so run single files while iterating.
- **lint:** `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- **types:** `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`

## Review Focus

These are the inputs most likely to hurt a user that the spec does not spell out. Each is pinned by a test in the task named.

1. **A canvas in another CRS from the grid** (a project in EPSG:4326, grids in UTM). Drawn vertices must land in grid metres, and hover must find the right column. Pinned by:
   - Task 4: `test_a_cut_drawn_on_a_geographic_canvas_lands_in_grid_metres`;
   - Task 4: `test_hover_on_a_geographic_canvas_finds_the_right_column`.
2. **A grid edited smaller after a cut was drawn,** so part of the cut lies outside it. The section shows blank columns there, the profile keeps working, and picks there keep their distance. Pinned by:
   - Task 3: `test_a_cut_past_a_shrunk_grid_edge_shows_blank_columns`;
   - Task 5: `test_a_pick_past_a_shrunk_grid_edge_keeps_its_distance`.
3. **Overlapping grids,** where the first click is inside two. The cut takes the first grid in survey order, and says which in its title. Pinned by Task 4: `test_a_first_click_inside_two_grids_takes_the_first_in_survey_order`.
4. **The Slices panel dropping the engine an open cut reads** (scope switch, grid change, source change, site closed). The cut must never read a disposed engine. It shows the message or redraws. Pinned by Task 3: `test_an_open_cut_shows_the_message_when_its_engine_goes_away`.
5. **Deleting the working cut, or closing the site, while its minimum curvature is being solved.** The worker stops, no row lands on another cut, and nothing raises. Pinned by Task 6:
   - `test_deleting_the_working_cut_mid_solve_stops_the_worker`;
   - `test_closing_the_site_mid_solve_stops_the_worker`.

---

### Task 1: Core — cuts in the survey file, and the section maths

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/model/cut.py`, `packages/nsgeo-core/src/nsgeo/slices/section.py`
- Modify:
  - `packages/nsgeo-core/src/nsgeo/model/survey.py` (`Site.cuts`, `validate`)
  - `packages/nsgeo-core/src/nsgeo/model/__init__.py`
  - `packages/nsgeo-core/src/nsgeo/geometry/grid.py` (`Grid.to_local`)
  - `packages/nsgeo-core/src/nsgeo/project.py`
  - `packages/nsgeo-core/src/nsgeo/slices/__init__.py`
  - `packages/nsgeo-core/src/nsgeo/render.py` (`section_rgba8`)
- Test:
  - Create: `packages/nsgeo-core/tests/test_cut.py`, `packages/nsgeo-core/tests/test_slices_section.py`
  - Modify: `packages/nsgeo-core/tests/test_project.py`, `test_grid.py`, `test_render.py`

**Interfaces:**
- Produces, in `nsgeo.model.cut` (re-exported from `nsgeo.model`):
  - `CUT_KEY_PREFIX: str`
  - `cut_key(cut_id: str) -> str`
  - `is_cut_key(key: str) -> bool`
  - `@dataclass(frozen=True) class Cut`:
    - fields: `id: str`, `name: str`, `grid_id: str`, `vertices: tuple[tuple[float, float], ...]` (grid-local metres, drawn order)
    - `key -> str`
    - `length_m -> float`
    - `point_at(distance_m: float) -> tuple[float, float]` (clamped to `[0, length_m]`)
    - `locate(local: tuple[float, float]) -> tuple[float, float]`, returning `(distance_m, offset_m)` of the nearest point on the path
    - `classmethod new(grid_id: str, vertices: Sequence[tuple[float, float]], name: str) -> Cut`. It gives a fresh id and drops consecutive duplicate vertices. It raises `ValueError` if fewer than two distinct vertices remain, or if any is non-finite.
- `Site.cuts: list[Cut]`.
- `Grid.to_local(world: np.ndarray) -> np.ndarray`: (n, 2) in, (n, 2) out, the inverse of `to_world`.
- In `nsgeo.project`: `CUTS_SCHEMA_VERSION = 2`, `READABLE_SCHEMA_VERSIONS = (1, 2)`.
- Produces, in `nsgeo.slices.section` (re-exported from `nsgeo.slices`):
  - `SECTION_MARGIN_M: float = 1.0`, `SECTION_PIECE_M: float = 4.0`
  - `@dataclass(frozen=True) class SectionColumns`, with fields:
    - `distance_m: np.ndarray`, shape (n,)
    - `local: np.ndarray`, shape (n, 2)
    - `world: np.ndarray`, shape (n, 2)
    - `cells: np.ndarray`, shape (n,), intp; −1 outside the frame
  - `section_columns(frame: CubeFrame, path_local: np.ndarray, step_m: float | None = None) -> SectionColumns`. `step_m` defaults to `frame.cell / 2`. It raises `ValueError` if the step is ≤ 0 or > `frame.cell / 2`, or if the path has fewer than 2 points or zero length.
  - `@dataclass(frozen=True) class SectionCrop`:
    - fields: `rows: tuple[int, int]`, `cols: tuple[int, int]` (half-open), `columns: np.ndarray` (indices into the `SectionColumns`)
    - `shape -> tuple[int, int]`
    - `flat_cells(nx: int) -> np.ndarray`
  - `smoothing_reach_cells(settings: FinishSettings, cell: float) -> int`
  - `section_crops(columns: SectionColumns, frame: CubeFrame, margin_cells: int, piece_m: float = SECTION_PIECE_M) -> tuple[SectionCrop, ...]`
  - `finish_section(levels: np.ndarray, fill: FillWeights, columns: SectionColumns, frame: CubeFrame, settings: FinishSettings) -> np.ndarray`. `levels` is the cube's `mean`, (nz, ny·nx). Returns (nz, n) float32. It raises `TypeError` for a `CurvaturePlan`.
  - `plan_section_curvature(populated: np.ndarray, crops: Sequence[SectionCrop], cell: float, max_distance_m: float) -> tuple[CurvaturePlan, ...]`
  - `solve_section_level(level: np.ndarray, columns: SectionColumns, crops: Sequence[SectionCrop], plans: Sequence[CurvaturePlan], settings: FinishSettings, cell: float, should_stop: Callable[[], bool] | None = None) -> np.ndarray`. `level` is (ny, nx); returns (n,) float32.
- Produces, in `nsgeo.render`: `section_rgba8(values: np.ndarray, percentile: float, lut: np.ndarray, *, unipolar: bool) -> np.ndarray`, giving (H, W, 4) uint8.

- [ ] **Step 1: Write the failing tests for `Cut` and `Grid.to_local`** (`test_cut.py`, `test_grid.py`)
  - `test_length_and_point_at_follow_the_drawn_order`: vertices `[(0,0),(3,0),(3,4)]` → `length_m == 7`, `point_at(5) == (3, 2)`, `point_at(-1) == (0, 0)`, `point_at(99) == (3, 4)`.
  - `test_locate_projects_onto_the_nearest_segment`: same cut, `locate((4, 2)) == (5.0, 1.0)` within 1e-12.
  - `test_new_drops_consecutive_duplicates_and_refuses_too_few`:
    - `Cut.new("A", [(0,0),(0,0),(1,0)], "Cut 1").vertices == ((0,0),(1,0))`;
    - `[(1,1)]` and `[(1,1),(1,1)]` raise `ValueError`;
    - a NaN vertex raises.
  - `test_keys_are_prefixed_and_never_a_dzt_path`:
    - `cut.key == "cut:" + cut.id`, `len(cut.id) == 32`;
    - `is_cut_key(cut.key)`;
    - `not is_cut_key("raw/FILE__001.DZT")`.
  - `test_to_local_inverts_to_world` at azimuth 10.497 and a UTM origin: round trip within 1e-6 m.
- [ ] **Step 2: Run them and see them fail.** Run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_cut.py packages/nsgeo-core/tests/test_grid.py -q -p no:cacheprovider`. Expected: import errors and `AttributeError: to_local`.
- [ ] **Step 3: Implement `nsgeo/model/cut.py` and `Grid.to_local`.**
  - `Cut.__post_init__` validates finiteness, at least two vertices, and a non-empty id and name.
  - `new` uses `uuid.uuid4().hex`.
- [ ] **Step 4: Write the failing survey-file tests** (`test_project.py`)
  - `test_cuts_round_trip_and_bump_the_schema_only_when_present`:
    - a site with one cut saves `schema_version == 2` and loads an equal `Cut`;
    - the same site with `cuts = []` saves 1 and has no `"cuts"` key.
  - `test_loads_schema_1_and_2_and_refuses_3`.
  - `test_a_malformed_cut_entry_is_a_project_error`: a missing `vertices`, a vertex that isn't a pair, a non-finite number, and a single vertex.
  - `test_a_cut_on_an_unknown_grid_is_a_project_error`.
  - `test_duplicate_cut_ids_fail_validate`.
- [ ] **Step 5: Run them and see them fail.**
- [ ] **Step 6: Implement** `Site.cuts`, the two `validate` checks, and `save_site`/`load_site` per plan call 3. Update `test_rejects_future_schema_version` to use 3.
- [ ] **Step 7: Write the failing section tests** (`test_slices_section.py`)
  - **Real data.** Use `tests.real_lines`: `prepared_lines(range(10), to_world)`, `plan_line`, `build_cube` and `AXIS`.
  - **Frames.** An axis-aligned frame is `CubeFrame((0, 0), 0, 0.2, 100, 25, crs)`. A rotated one is `CubeFrame.for_grid(Grid("G", (500000.0, 4000000.0), 10.497, 20.0, 5.0, crs, 0.5), 0.2)`, with `to_world = grid.to_world`. Each test uses `needs_real_files`.
  - **Tests:**
    - `test_columns_start_at_zero_end_at_the_length_and_step_at_half_a_cell`: a 3.05 m path at cell 0.2. `distance_m[0] == 0`, `distance_m[-1] == 3.05`, the inner steps equal 0.1, and the last step is ≤ 0.1.
    - `test_columns_land_in_the_cells_cell_index_finds` (spec test 2): on the rotated frame, an oblique path. `cells` equals `frame.cell_index(columns.world)`, and `frame.to_local(columns.world)` equals `columns.local` within 1e-9.
    - `test_columns_past_the_frame_edge_are_minus_one`: a path from (19, 2) to (23, 2). Columns beyond x = 20 give −1.
    - `test_a_step_over_half_a_cell_and_a_zero_length_path_are_refused`.
    - `test_a_hundred_vertex_cut_and_a_long_cut`: 100 vertices zig-zagging inside the frame give `len(distance_m) == ceil(length / 0.1) + 1`. A 1 km path gives columns that are almost all −1, with no error.
    - `test_every_inside_column_is_in_one_crop_and_crops_stay_in_the_frame`: for the diagonal and along-x paths, at margins 0 and 5 cells:
      - the union of `crop.columns` is exactly the inside columns, with no repeats;
      - every crop's span along the cut is ≤ `SECTION_PIECE_M`;
      - every crop lies within `[0, ny) × [0, nx)`;
      - every column's cell is inside its crop by at least `min(margin, distance to the frame edge)`.
    - `test_a_cut_along_a_recorded_line_reads_that_lines_cells` (spec test 1, the anchor): method `none`, a path along y = 0.25 + 3 · 0.5 from x = 0 to 20. At every level, the section equals `cube.mean[k][cells]` wherever `count > 0`.
    - `test_section_equals_the_finished_slice_at_every_level` (parametrised over `none`, `idw`, `kriging`, × smoothing `(0, 0)` and `(0, 0.1)`), on the rotated frame. For each level k, `finish_section(...)[k]` equals `finish_slice(cube.mean[k].reshape(ny, nx), fill, cell, settings).ravel()[cells]`, with `np.testing.assert_allclose(rtol=0, atol=1e-5 * range)` and `equal_nan=True`.
    - `test_window_average_of_a_section_equals_the_slice_window` (spec test 11) on the same parameters. For each `WINDOWS` entry `(k0, k1)`, `nanmean` over the section's rows `k0:k1` equals `finish_slice(cube.slice_levels(k0, k1)[0], …)` at the cells.
    - `test_blank_beyond_max_distance_and_outside_the_frame` (spec test 3):
      - a cut along a gap with max distance 0.1 m (below the half gap of 0.25 m) is NaN off the lines;
      - with 0.375 m it is finite;
      - the columns past the frame edge are NaN.
    - `test_finish_section_refuses_a_curvature_plan`.
    - `test_curvature_on_crops_matches_the_whole_frame_solve` (spec test 12a): at cell 0.05 on the axis-aligned frame, with max distance 0.25. For three paths (along x, along y, diagonal) and three levels, `solve_section_level` is within `1e-3 · (nanmax − nanmin)` of `plan_fill(..., "min_curvature", ...).solve(level)[0].ravel()[cells]`. Crops come from `section_crops(..., margin_cells=ceil(SECTION_MARGIN_M / 0.05))`.
    - `test_curvature_on_crops_with_smoothing_matches_the_whole_frame` at `smooth_y_m = 0.1`, same tolerance.
  - **Rendering**, in `test_render.py`: `test_section_rgba8_makes_blanks_transparent_in_both_polarities`.
    - `values = [[1.0, nan], [0.5, 2.0]]`. With `unipolar=True` and `False`, `alpha[0, 1] == 0` and the other alphas are 255.
    - An all-NaN array gives all-zero alpha, with no error.
    - An all-zero array does not raise.
- [ ] **Step 8: Run them and see them fail.**
- [ ] **Step 9: Implement `section.py` and `section_rgba8`.**
  - `finish_section`:
    - with no smoothing, it calls `fill.apply_at(level_2d, inside_cells)` per level;
    - with smoothing, it works per crop (margin = `smoothing_reach_cells`): `fill.apply_at(level_2d, crop.flat_cells(nx))`, then reshape, then `smooth`, then read the crop's columns.
  - `solve_section_level` runs, per crop, `plans[i].solve(level[r0:r1, c0:c1], should_stop)[0]`, then `smooth` with the settings, then reads the crop's columns. `SolveStopped` propagates.
  - `section_rgba8`:
    - The limit comes from `UnipolarClip` or `PercentileClip` over the finite values. A limit ≤ 0 or non-finite becomes 1.0.
    - It calls `to_rgba8(..., unipolar=unipolar)`.
    - Alpha is set to 0 wherever the value is not finite.
  - Add a module docstring in the style of `interpolate.py`, recording the spike's measurements from cut spec §5.
- [ ] **Step 10: Run the core + pure suite, lint and types.** Expected: all pass, baseline count + the new tests.
- [ ] **Step 11: Commit**, then push:
  `git commit -m "feat(core): cuts in the survey file, and sections finished as slices are (cut spec §3, §4.7)"`

---

### Task 2: Cuts in the session, the cuts layer and the Survey panel

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/layers.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`
- Test:
  - Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_session_cuts.py`
  - Modify: `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`, `test_plugin_survey_dock.py`, `test_plugin_loads.py`

**Interfaces:**
- Consumes (Task 1): `Cut`, `Cut.new`, `cut_key`, `is_cut_key`, `Site.cuts`, `Grid.to_world`.
- Produces on `SiteSession`:
  - `cuts_changed = pyqtSignal()`
  - `cut_keys() -> list[str]`, `cut_keys_on_grid(grid_id: str) -> list[str]` (drawing order)
  - `cut_for_key(key: str) -> Cut` (`KeyError`)
  - `add_cut(grid_id: str, vertices: Sequence[tuple[float, float]]) -> str`. Returns the key; raises `KeyError` for an unknown grid and `ValueError` from `Cut.new`.
  - `rename_cut(key: str, name: str) -> None` (`ValueError` when the stripped name is empty)
  - `remove_cut(key: str) -> None`
  - `cut_velocity(grid_id: str) -> VelocityModel` (spec call 16: `grid.velocity`, else `resolved_velocity(keys_on_grid(grid_id)[0])`; `KeyError` when neither exists)
- Produces on `SiteLayers`: `refill_cuts() -> None`, plus the `cuts` table.

- [ ] **Step 1: Write the failing session tests** (`test_plugin_session_cuts.py`, with the `session` and `_two_grids` helpers from `test_plugin_session.py`)
  - `test_add_cut_names_marks_dirty_and_announces`:
    - the first cut is named `Cut 1`;
    - after deleting `Cut 1` with a `Cut 2` present, the next is `Cut 3`;
    - `dirty` becomes True;
    - `cuts_changed` fires once per call.
  - `test_add_cut_refuses_an_unknown_grid_and_too_few_points`.
  - `test_rename_keeps_the_key_and_refuses_an_empty_name`.
  - `test_remove_grid_drops_its_cuts_and_keeps_the_others`.
  - `test_cut_velocity_is_the_grids_then_the_first_lines` (spec call 16):
    - grid velocity set → that velocity;
    - grid velocity None and the first line with a header dielectric → that line's resolved model;
    - an override on the *second* line changes nothing;
    - a grid with no velocity and no lines → `KeyError`.
  - `test_cuts_survive_save_and_reopen`: `save()`, then a new session loads the same cuts.
  - `test_keys_stay_lines_only`: `keys()` contains no cut key.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement the session additions.**
  - Load cuts in `_install`.
  - `remove_grid` drops its cuts and emits `cuts_changed` after `grids_changed`.
  - Dirty marking goes through `_set_dirty(True)`.
- [ ] **Step 4: Write the failing layer tests** (`test_plugin_layers.py`, with the `populated` fixture)
  - `test_cuts_table_has_the_declared_fields_and_is_read_only`: fields as in Global Constraints, and `layer.readOnly()`.
  - `test_legend_order_puts_cuts_between_marks_and_lines`.
  - `test_refill_cuts_places_a_cut_in_world_coordinates`: a cut `[(1,1),(6,1)]` on grid A has its first vertex at `GRID.to_world([[1,1]])` in the package CRS, and `length_m == 5`.
  - `test_a_moved_grid_moves_its_cuts` (spec §4.8): `replace_grid` with a new origin moves the cut layer's vertices by the same offset. The `Cut` vertices are unchanged.
  - `test_a_crs_rebuild_refills_the_cuts` (spec test 5, "A CRS rebuild"): after the CRS change that rebuilds tables, the cuts table has the cut.
  - `test_removing_the_last_grid_empties_the_cuts_table`.
- [ ] **Step 5: Run them and see them fail.**
- [ ] **Step 6: Implement the cuts table:**
  - add it to `TABLES`, `DERIVED` and `LEGEND_ORDER`;
  - add `refill_cuts` (`grid.to_world` of the vertices, then `_points`) to `refresh`'s refill loop;
  - add `_style_cuts`;
  - connect `session.cuts_changed` to `refresh`.
- [ ] **Step 7: Write the failing Survey panel tests** (`test_plugin_survey_dock.py`, with the `dock` fixture, `_right_click`, `_action` and `answer_modal`)
  - `test_a_grid_with_cuts_lists_them_under_a_cuts_item_before_its_lines`.
  - `test_rename_cut_asks_for_a_name_and_renames`: answer `QInputDialog.getText` with `("Lower line", True)`.
  - `test_delete_cut_asks_and_says_its_picks_stay`:
    - with 0 picks the text is `Delete Cut 1?`;
    - with 2 picks, stubbed through `session.picks_for`, it ends `Its 2 picks stay on the map.`;
    - a "No" answer keeps the cut.
  - `test_the_delete_key_on_a_cut_deletes_it_after_the_same_prompt`.
  - `test_removing_a_grid_with_cuts_says_so`: the prompt contains `Its 2 cuts are deleted too; their picks stay on the map.`
- [ ] **Step 8: Run them and see them fail.**
- [ ] **Step 9: Implement the Survey panel changes** (plan call 12):
  - rebuild on `cuts_changed`;
  - `item_for_key` finds cut items;
  - the cut context menu offers "Rename cut…", a separator, and "Delete cut" (Open arrives in Task 3);
  - extend `_remove` and `_removal_text` with cut keys.
- [ ] **Step 10: Write and pass the close-prompt test** (`test_plugin_loads.py`): `test_closing_with_an_unsaved_cut_prompts` (spec test 6). After `session.add_cut`, unloading or closing the site asks the existing save question.
- [ ] **Step 11: Run the QGIS files touched, then the full core + pure suite, lint and types.**
- [ ] **Step 12: Commit and push:**
  `git commit -m "feat(cuts): cuts in the session, a read-only cuts layer, and the Survey panel (cut spec §4.2, §4.8)"`

---

### Task 3: Seeing a cut — the section from the Slices panel, in the profile

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/cut_sections.py`
- Modify:
  - `session.py` (cut keys in `open_line`, `set_preview`, `set_trace`, `set_selection`, `resolved_velocity`)
  - `slices_engine.py` (`section_fills`)
  - `loader.py`
  - `ui/processing_dock.py`
  - `ui/profile_dock.py`
  - `ui/profile_view.py` (`set_message`)
  - `render/qimage.py` (`rgba_to_qimage`)
  - `ui/survey_dock.py` ("Open" on a cut)
  - `plugin.py` (build and wire `CutSections`; Velocity enabling)
- Test:
  - Create: `tests/qgis/test_plugin_cut_sections.py`, `tests/qgis/test_plugin_profile_cut.py`
  - Modify: `test_plugin_session_cuts.py`, `test_plugin_loader.py`, `test_plugin_slices_engine.py`, `test_plugin_processing_dock.py`, `test_plugin_survey_dock.py`

**Interfaces:**
- Consumes:
  - Task 1: `section_columns`, `finish_section`, `section_rgba8`.
  - Task 2: `cut_for_key`, `cut_velocity`, `cuts_changed`.
- Produces:
  - `SliceEngine.section_fills(finish: SliceFinish) -> tuple[SliceFill, FillWeights | None]`. Requires a cube. It is the engine's held fill and preview when the key matches, and otherwise builds through `_fill_for(cube.coverage(), frame, settings)`.
  - In `cut_sections.py`:
    - `@dataclass(frozen=True) class CutSource`:
      - `grid_id: str`
      - `scope: str` (`"grid"` or `"site"`)
      - `engine: SliceEngine`
      - `finish: SliceFinish`, `settings: FinishSettings`
      - `palette: str`, `unipolar: bool`
    - `@dataclass(frozen=True) class CutSection`:
      - `key: str`
      - `values: np.ndarray` (nz, n)
      - `z: ZAxis`
      - `columns: SectionColumns`
      - `method: str` (the method drawn)
      - `standing_in: bool`
      - `solved: tuple[int, int]`
      - `source: CutSource`
      - `provenance_json: str`
    - `class CutSections(QObject)`:
      - `section_changed = pyqtSignal(str)`
      - `__init__(self, session: SiteSession, slices_dock: SlicesDock, parent: QObject | None = None)`
      - `source_for(grid_id: str) -> CutSource | None`
      - `section(key: str, *, build_cube: bool) -> CutSection | str` (a `str` is the message to show)
      - `column_at(key: str, distance_m: float) -> int | None`
      - `dispose() -> None`
  - `ProfileDock.set_cut_sections(sections: CutSections) -> None`.
  - `ProfileView.set_message(text: str | None) -> None`.
  - `rgba_to_qimage(rgba: np.ndarray) -> QImage`.
  - `provenance_json` holds, as JSON (spec call 2):
    ```json
    {"kind": "cut", "cut_id": "...", "cut_name": "...", "grid_id": "...",
     "scope": "This grid" | "Whole site (not normalised)",
     "cube": "<Provenance.to_dict()>",
     "resolution": {"cell": 0.05, "dz_ns": 0.2165},
     "finish": {"method": "kriging", "max_distance_m": 0.25, "smooth_x_m": 0.0, "smooth_y_m": 0.1},
     "standing_in_for": "min_curvature"}
    ```
    `standing_in_for` appears only when kriging stands in.

- [ ] **Step 1: Write the failing session and tolerance tests**
  - In `test_plugin_session_cuts.py`:
    - `test_open_preview_trace_and_selection_accept_cut_keys`:
      - `open_line(cut_key)` emits `line_opened(cut_key)`;
      - `set_preview(cut_key, 7)` emits `preview_changed(cut_key, 7)`;
      - `set_trace(cut_key, 10_000)` keeps 10_000 (no upper clamp, plan call 4);
      - `set_trace(cut_key, -5)` gives −1.
    - `test_resolved_velocity_of_a_cut_is_its_grids` (call 16).
    - `test_removing_the_working_or_previewed_cut_clears_it`: `remove_cut` on the open cut leaves `current_key is None` and emits `line_opened("")`. On a previewed cut it emits `preview_changed("", -1)`.
  - In `test_plugin_loader.py`: `test_opening_or_previewing_a_cut_starts_no_load`.
  - In `test_plugin_processing_dock.py`: `test_a_cut_shows_that_processing_does_not_apply`: the list is empty and disabled, and the label is `PROCESSING_ON_CUT_TEXT`; reopening a line restores it.
- [ ] **Step 2: Run them and see them fail. Implement them. Run them and see them pass.**
- [ ] **Step 3: Write the failing engine test** (`test_plugin_slices_engine.py`, with the `sourced` fixture and `_prepare`): `test_section_fills_reuse_the_held_weights`.
  - After the dock-equivalent `finish(...)` call for the same `SliceFinish`, `section_fills` returns the identical fill object.
  - `plan_fill`, monkeypatched to count, is not called again.
  - Under `min_curvature` the second element is the kriging `FillWeights`.
- [ ] **Step 4: Run it and see it fail. Implement `section_fills`. Run it and see it pass.**
- [ ] **Step 5: Write the failing `CutSections` tests** (`test_plugin_cut_sections.py`)
  - **Fixtures.** Use a `docked_two_grids`-style fixture (a `SlicesDock` with grids A and B prepared at cell 0.25), plus the `site3` fixture for Whole site. Draw cuts with `session.add_cut`.
  - **Tests:**
    - `test_this_grid_scope_reads_the_shown_grids_engine` (call 10): a cut on the shown grid gives a `CutSection` with `source.scope == "grid"` and `source.engine is dock.engine`.
    - `test_this_grid_scope_gives_the_message_for_another_grid` (spec test 7): a cut on B while A is shown returns `NO_SOURCE_TEXT.format(name="Cut 1", grid="B")`, even though a site engine for B is still prepared.
    - `test_whole_site_reads_the_grids_site_engine_without_the_gain`: in site scope, `section.values[k]` equals `engine.finish(cube.mean[k].reshape(...), coverage, site_finish)` at the cut's cells for three levels. This is not `SiteEngine._shown`'s output. Patch `normalise` to return `(2.0, 5.0)` and assert that it does not change the section.
    - `test_a_preview_never_builds_a_cube`: on a streaming engine (`has_cube` False), `section(key, build_cube=False)` returns `NO_CUBE_TEXT…` and `has_cube` stays False. `build_cube=True` builds it and returns a section.
    - `test_settings_or_source_changes_redraw_an_open_cut` (spec §4.4): after a first `section(...)`, changing the method, the max distance, smoothing, the cell, or the palette, then letting `slice_changed` fire, emits `section_changed(key)` once. The next `section` reflects the change.
    - `test_an_open_cut_shows_the_message_when_its_engine_goes_away` (Review Focus 4): switching the shown grid, switching scope, and closing the site each give the message or an empty result. Nothing reads the old engine: `engine.cube` is patched to raise after `dispose`.
    - `test_a_cut_past_a_shrunk_grid_edge_shows_blank_columns` (Review Focus 2): a cut from x = 1 to x = 5 on a 6 m grid. After `replace_grid` with `size_x = 3`, the frame-outside columns are NaN, the rest are finite, and `section_changed` fired.
    - `test_minimum_curvature_stands_in_with_kriging` (call 12, before Task 6): with method `min_curvature`, the section has `method == "kriging"`, `standing_in is True`, and values equal to kriging's `finish_section`. `provenance_json` has `"standing_in_for": "min_curvature"`.
    - `test_provenance_names_the_cut_cube_and_finish` (call 2): parse the JSON and check every key in the Interfaces block. `cube.line_keys` equals the engine's prepared keys.
    - `test_column_at_is_the_nearest_column`: `column_at(key, 1.04)` at cell 0.25 (step 0.125) is 8, and it is `None` when there is no source.
- [ ] **Step 6: Run them and see them fail.**
- [ ] **Step 7: Implement `CutSections`.**
  - **The source.** It is resolved per call 10 from `dock.scope()`, `dock.engine` (prepared and `choice.grid_id` matches), `dock.site_engine.ready_grids` / `engine_for`, `dock.grid_finish.value()` / `dock.site_finish.value()`, `dock.palette_combo.currentText()` and `engine.output_unipolar`.
  - **The cache.** One entry per key, with a fingerprint of `(id(engine), engine.choice, engine.frame, engine.z, id(cube), settings, scope, palette, unipolar, the Cut, the grid)`.
  - **Redraws.** It listens to `slices_dock.slice_changed`, `session.cuts_changed`, `session.grids_changed` and `session.site_closed`. A cached key whose fingerprint changed is dropped and `section_changed(key)` is emitted.
  - **The wait cursor.** `build_cube=True` wraps `engine.cube()` in `QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)` / `restoreOverrideCursor` (in `try/finally`).
- [ ] **Step 8: Run them and see them pass.**
- [ ] **Step 9: Write the failing profile tests** (`test_plugin_profile_cut.py`; the dock wired to a `CutSections` over a prepared `SlicesDock`)
  - `test_opening_a_cut_draws_its_section_with_its_title_and_axes`:
    - the title is `nsgeo Profile · cut: Cut 1 · A · 5.0 m · Kriging`;
    - the view's `n_traces` equals the column count and `n_samples` equals `nz`;
    - the distance axis runs from 0 to 5.0, and the direction is +1 for a cut drawn east to west as well (call 5: never mirrored);
    - the ruler is `None`, and the `_held` windows are unchanged.
  - `test_whole_site_scope_says_not_normalised`: the title ends ` · site view, not normalised`.
  - `test_a_preview_has_the_preview_prefix_and_builds_nothing`.
  - `test_no_source_shows_the_message_in_the_view` (spec test 7): `view.set_message` gets `NO_SOURCE_TEXT…` and the image is `None`.
  - `test_a_squared_cube_draws_in_the_slices_palette_with_blank_columns_transparent` (call 17, spec test 8):
    - with `amp_square` and the panel's `amp_black_high`, the image's colour at a finite column matches `colormap("amp_black_high")` for that value;
    - a NaN column's pixels have alpha 0;
    - `colormap_combo` is disabled with `PALETTE_ON_CUT_TIP`;
    - opening a line re-enables it with its previous choice.
  - `test_the_percentile_slider_still_applies_to_a_cut`.
  - `test_the_slice_band_shows_on_a_cut` (call 13).
  - `test_velocity_is_greyed_on_a_cut_and_back_on_a_line` (spec test 8, plugin-level, with `_plugin_with_one_line`): `act_velocity` is disabled with `VELOCITY_ON_CUT_TIP` while a cut is current and enabled again for a line. Pick stays enabled.
  - `test_the_depth_axis_uses_the_cut_velocity`: `view._velocity` is `session.cut_velocity("A")`.
  - `test_a_section_change_redraws_the_shown_cut`: an emitted `section_changed(key)` re-renders; one for another key does not.
  - In `test_plugin_survey_dock.py`: `test_open_on_a_cut_opens_it`.
- [ ] **Step 10: Run them and see them fail.**
- [ ] **Step 11: Implement the profile side.**
  - `_show_line` branches to `_show_cut(key, *, is_preview)`.
  - Channels, difference, the cutoff handle, the gain strip and the velocity strip stay off or hidden while a cut shows, and come back for a line.
  - `_render` and `_display_changed` redraw a cut through `section_rgba8` → `rgba_to_qimage`.
  - In `plugin.py`, build `CutSections(self.session, self.slices_dock)` after the Slices panel and pass it to the profile with `set_cut_sections`. Dispose it in `unload`. Velocity's enable test is `has_line and not is_cut_key(current_key)`.
- [ ] **Step 12: Run the touched QGIS files, then core + pure, lint and types.**
- [ ] **Step 13: Commit and push:**
  `git commit -m "feat(cuts): a cut's section from the Slices panel's cube, drawn in the profile (cut spec §4.3, §4.4)"`

---

### Task 4: Drawing a cut, and the map working on cuts

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/maptools/cut_tool.py`
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (the Cut toggle, `_on_cut_drawn`, `currentLayerChanged`)
  - `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`
  - `packages/nsgeo-qgis/tests/qgis/conftest.py` (`FakeIface`)
- Test:
  - Create: `tests/qgis/test_cut_tool.py`, `tests/qgis/test_plugin_cut_drawing.py`, `tests/qgis/test_plugin_map_link_cuts.py`

**Interfaces:**
- Consumes:
  - Task 2: `add_cut`, `cut_for_key`.
  - Task 3: `open_line` on cut keys, `CutSections.section` / `column_at`, `SectionColumns.world`, `Cut.locate`, `Grid.to_local`.
- Produces:
  - `class CutTool(QgsMapTool)`:
    - `drawn = pyqtSignal(list)` (a list of `QgsPointXY` in canvas CRS, at least one point)
    - `failed = pyqtSignal(str)`
    - `dispose() -> None`
  - `MapLink.set_cut_mode(on: bool) -> None`, `MapLink.cut_mode -> bool`, `MapLink.set_sections(sections: CutSections) -> None`.
  - `FakeIface.activeLayer()`, `FakeIface.setActiveLayer(layer)` (emits `currentLayerChanged`), `FakeIface.currentLayerChanged`.

- [ ] **Step 1: Write the failing tool tests** (`test_cut_tool.py`, with `send_map_mouse` and `send_map_key` on `real_canvas`)
  - `test_left_clicks_add_points_and_right_click_finishes`: three left clicks then a right-click emit `drawn` once with 3 points.
  - `test_enter_finishes_and_backspace_removes_the_last_point`.
  - `test_esc_cancels_and_leaves_nothing_behind` (spec test 6): after two clicks and Esc, no `drawn`, and the rubber band is empty. The key is consumed (`e.ignore()`, per `pick_tool.py`'s trap).
  - `test_the_tool_stays_on_for_the_next_cut`: after one `drawn`, three more clicks and Enter emit again.
  - `test_an_exception_in_an_event_becomes_failed`.
- [ ] **Step 2: Run them and see them fail. Implement `CutTool`. Run them and see them pass.**
  - Follow `PickPointTool`'s structure: guarded events, `QgsRubberBand` for the drawn path plus a moving segment, and an idempotent `dispose`.
- [ ] **Step 3: Write the failing drawing-flow tests** (`test_plugin_cut_drawing.py`, a plugin on `real_iface` with one grid and lines)
  - `test_the_cut_toggle_follows_the_site_and_makes_the_cuts_layer_current` (decision 11):
    - Cut is disabled with no site;
    - after a site opens, checking it sets the map tool and makes `iface.activeLayer()` the cuts layer;
    - unchecking unsets the tool.
  - `test_drawing_a_cut_adds_marks_unsaved_refills_and_opens_it` (§4.1):
    - draw 2 points inside grid A;
    - then `session.cut_keys()` has one key, `dirty` is True, the cuts layer has one feature, `current_key` is that key, and the tool is still active.
  - `test_a_first_click_outside_every_grid_is_refused`: the message bar shows `OUTSIDE_TEXT`, and no cut is added.
  - `test_one_point_or_two_on_the_same_spot_is_refused` (spec test 4): `TOO_FEW_TEXT`.
  - `test_a_first_click_inside_two_grids_takes_the_first_in_survey_order` (Review Focus 3).
  - `test_a_cut_drawn_on_a_geographic_canvas_lands_in_grid_metres` (Review Focus 1): canvas in EPSG:4326, grid in EPSG:32616. The stored vertices equal `grid.to_local(transformed points)` within 1e-6 m.
  - `test_another_map_tool_unchecks_cut`.
- [ ] **Step 4: Run them and see them fail. Implement the plugin side** (`act_cut`, `_toggle_cut_tool`, `_on_cut_drawn`; plan call 10's `setActiveLayer`). **Run them and see them pass.**
- [ ] **Step 5: Write the failing map-link tests** (`test_plugin_map_link_cuts.py`)
  - **Fixture.** The `linked` fixture is extended with a `CutSections` over a prepared engine. The grid has lines 0.5 m apart, rotated 10.497°. A cut runs obliquely, within hover reach of a line along most of its length.
  - **Tests:**
    - `test_cut_mode_hover_previews_the_cut_not_the_nearby_line` (spec test 10): after settling 0.1 m from a line and on the cut, `preview_key` is the cut key and the column equals `column_at(key, Cut.locate(...)[0])`.
    - `test_line_mode_ignores_cuts`: the same spot previews the line, as today.
    - `test_changing_mode_mid_hover_leaves_no_stale_preview`: `set_cut_mode(False)` while previewing a cut clears the preview.
    - `test_the_working_cut_stays_open_when_another_layer_becomes_current` (§4.3): with a cut working, `set_cut_mode(False)` keeps `current_key`. Hovering a line then previews it, and selecting a line opens it.
    - `test_selecting_a_cut_opens_it`: select its feature in the cuts layer, and `current_key` is the cut key.
    - `test_tracking_works_both_ways_along_a_cut`:
      - map to profile: moving the pointer along the working cut calls `set_trace` with increasing columns;
      - profile to map: `session.set_trace(key, 20)` puts the marker at `columns.world[20]` in canvas CRS, within 1e-6 map units.
    - `test_the_marker_and_band_follow_a_selection_on_a_cut`.
    - `test_hover_on_a_geographic_canvas_finds_the_right_column` (Review Focus 1).
    - `test_hovering_a_cut_while_a_line_works_never_writes_to_the_cut` (spec test 9): with a line working and a cut previewed, a pick request for the cut key raises `ValueError` in the session, and no row is added.
    - `test_the_plugin_follows_the_current_layer` (plan call 10, with the extended `FakeIface`):
      - `setActiveLayer(cuts)` turns cut mode on, and any other layer turns it off;
      - after a CRS rebuild replaces the cuts layer object, setting the new one still turns it on.
- [ ] **Step 6: Run them and see them fail.**
- [ ] **Step 7: Implement the map-link changes** (plan calls 9 and 10):
  - a cut-geometry cache from the cuts layer (`cut_key`), invalidated with the lines cache and on `cuts_changed`;
  - `_hit_test` branches on `cut_mode`;
  - `_track_displayed_line`, `_set_marker` and `_set_band` handle cut keys;
  - `selectionChanged` on the cuts layer opens the cut;
  - in `plugin.py`, `iface.currentLayerChanged` → `map_link.set_cut_mode(...)`, also synced on `site_opened`.
- [ ] **Step 8: Run them and see them pass. Then run the touched QGIS files, core + pure, lint and types.**
- [ ] **Step 9: Commit and push:**
  `git commit -m "feat(cuts): the Cut tool, and the map working on cuts while the cuts layer is current (cut spec §4.1, §4.3, decision 11)"`

---

### Task 5: Picks on cuts

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/layers.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`_on_pick_requested`)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (the pick overlay)
  - `packages/nsgeo-qgis/nsgeo_qgis/map_link.py` (`_jump_to_feature`, `on_info`)
- Test: Create `tests/qgis/test_plugin_cut_picks.py`

**Interfaces:**
- Consumes:
  - Task 3: `CutSection.columns`, `provenance_json`, `column_at`.
  - Task 2: `cut_velocity`.
  - Line editing: `SiteLayers.follow_lines`.
- Produces:
  - `SiteSession.add_cut_pick(key: str, column: int, distance_m: float, time_ns: float, stack_json: str) -> Pick`:
    - working key only, `ValueError` otherwise;
    - a finite time;
    - the distance clamped to `[0, length_m]`.
  - `SiteSession.derived_cut_pick_fields(key: str, distance_m: float, time_ns: float) -> tuple[float | None, float | None]`, giving depth and velocity, or `(None, None)` when the cut velocity raises `KeyError`.
  - `MapLink(..., on_info: Callable[[str], None] | None = None)`.

- [ ] **Step 1: Write the failing tests** (`test_plugin_cut_picks.py`, a plugin with a GeoPackage, a prepared grid, and an open cut)
  - `test_a_pick_on_a_cut_lands_on_the_cut_and_records_its_provenance` (spec test 5, call 2):
    - a pick at column 12 has `line_key == cut_key`, `trace == 12` and `distance_m == columns.distance_m[12]`;
    - its geometry is `grid.to_world(cut.point_at(distance_m))` in the package CRS;
    - `json.loads(stack_json)["kind"] == "cut"`;
    - depth equals `cut_velocity("A").depth_at([t])[0]`.
  - `test_selecting_a_cut_pick_reopens_the_cut_at_its_distance`: with another line working, selecting the pick opens the cut, and `current_trace == column_at(key, distance_m)`.
  - `test_renaming_the_cut_keeps_the_way_back`.
  - `test_deleting_the_cut_leaves_its_picks_and_selecting_one_says_so` (call 3): the row and its geometry are unchanged; selecting it calls `on_info(CUT_GONE_TEXT)`; `current_key` is unchanged.
  - `test_a_pick_on_a_never_saved_cut_behaves_the_same_after_reopening`: close without saving (answer Discard), reopen; the pick is there; selecting it says `CUT_GONE_TEXT`.
  - `test_a_crs_rebuild_keeps_the_cut_pick`.
  - `test_a_cell_change_reopens_the_pick_at_the_same_distance_and_time` (spec test 5, call 12): after changing the cell 0.25 → 0.2, the overlay's column is `column_at(key, distance_m)` under the new step, and `distance_m` is unchanged.
  - `test_a_moved_grid_moves_cut_picks_and_keeps_distance` (spec test 13): after `replace_grid` with a new origin, the geometry moves by the offset and `distance_m` is unchanged.
  - `test_a_grid_velocity_change_rederives_depth_and_a_line_override_does_not` (spec test 13).
  - `test_opening_a_site_rederives_cut_picks_with_no_engine_prepared` (spec test 13).
  - `test_removing_a_grid_keeps_its_cut_picks_on_the_map` (spec test 13): the prompt is answered Yes; the rows are unchanged.
  - `test_a_pick_past_a_shrunk_grid_edge_keeps_its_distance` (Review Focus 2).
  - `test_the_profile_overlays_cut_picks_at_their_columns`.
  - `test_a_preview_cannot_take_a_pick`: the existing preview refusal also holds for cuts.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - `add_cut_pick` and `derived_cut_pick_fields`.
  - In `_on_pick_requested`, a cut key reads the shown `CutSection`, then calls `add_cut_pick` with its `distance_m[trace]` and `provenance_json`. A message string means there is no section: put the reason on the message bar.
  - In `layers.py`:
    - `_pick_point` for a cut key is the cut's point at `distance_m`;
    - `write_pick` reports `no cut with key …`;
    - `follow_lines` takes cut keys: position from `distance_m` (never rewritten), depth and velocity from `derived_cut_pick_fields`;
    - a row whose cut is gone, or whose `distance_m` is NULL, is left alone.
  - The profile's `_refresh_picks` maps cut picks through `column_at`.
  - `_jump_to_feature` opens a cut and sets its column. For a gone cut it calls `on_info(CUT_GONE_TEXT)`; the plugin passes the message bar.
- [ ] **Step 4: Run them and see them pass. Then run the touched QGIS files (including `test_plugin_layers.py`'s follow tests), core + pure, lint and types.**
- [ ] **Step 5: Commit and push:**
  `git commit -m "feat(cuts): picks on cuts — distance and time, provenance, following the grid (cut spec §4.5, §4.8)"`

---

### Task 6: Minimum curvature behind the kriging, and the guide

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/refine.py` (`thread_name_prefix`)
  - `packages/nsgeo-qgis/nsgeo_qgis/cut_sections.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (the title's progress)
  - `docs/guide/getting-started.md`
- Test:
  - Create: `tests/qgis/test_plugin_cut_refine.py`
  - Modify: `test_plugin_refine.py`

**Interfaces:**
- Consumes:
  - Task 1: `section_crops`, `plan_section_curvature`, `solve_section_level`, `smoothing_reach_cells`, `SECTION_MARGIN_M`.
  - Task 3: `CutSections`.
  - `Refiner.start` / `cancel` / `shutdown`.
- Produces:
  - `Refiner.__init__(self, parent: QObject, *, thread_name_prefix: str = THREAD_NAME_PREFIX)`.
  - In `cut_sections.py`:
    - `CUT_THREAD_NAME_PREFIX`, `CUT_SOLVE_REST_MS`, `CUT_REDRAW_MS`
    - `class CutLevelJob`, with `level: int`, `result: np.ndarray | None`, and `run(should_stop)`.

- [ ] **Step 1: Write the failing tests** (`test_plugin_cut_refine.py`, using `slow_jobs` and `spin_until` from `plugin_testing.py`; method `min_curvature` at cell 0.25)
  - `test_the_working_cut_is_solved_after_a_rest_and_replaces_kriging` (§4.7):
    - right after opening: `standing_in`, and the title is `Kriging preview · minimum curvature 0 of {nz} depths`;
    - after `spin_until` all depths land: `method == "min_curvature"`, `standing_in is False`, and the title ends `Minimum curvature`;
    - each row equals `solve_section_level` for that level;
    - `provenance_json` has no `standing_in_for`.
  - `test_depths_near_the_slice_band_are_solved_first`: the first landed job's level is the band's centre level.
  - `test_a_hover_preview_starts_no_solve`: no job runs, and the title is `Kriging preview (minimum curvature when opened)`.
  - `test_a_settings_change_discards_the_solve`: a change mid-solve cancels; no old row lands; a new solve starts after the rest.
  - `test_a_pick_while_kriging_stands_in_records_kriging`.
  - `test_the_slices_own_refine_lands_while_a_cut_is_solving` (fairness): with a slow cut list running, a slice refine started on the dock's `Refiner` lands before the cut list ends.
  - `test_the_cut_worker_thread_is_named_nsgeo_cut`.
  - `test_deleting_the_working_cut_mid_solve_stops_the_worker` (Review Focus 5).
  - `test_closing_the_site_mid_solve_stops_the_worker` (Review Focus 5).
  - `test_opening_another_item_cancels_the_solve`.
  - In `test_plugin_refine.py`: `test_a_custom_thread_name_prefix_names_the_thread`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - `Refiner`'s prefix.
  - In `CutSections`:
    - a second `Refiner(self, thread_name_prefix=CUT_THREAD_NAME_PREFIX)`, shut down in `dispose`;
    - a single-shot rest timer (`CUT_SOLVE_REST_MS`), restarted whenever the working cut's section is built or rebuilt while standing in;
    - jobs are one `CutLevelJob` per level, ordered by distance from the slice band's centre level (the dock's last `window_changed`, through `z.level_range`), with crops and plans built once per solve;
    - `on_landed` writes the row only if the fingerprint and working key still match;
    - a `CUT_REDRAW_MS` timer throttles `section_changed`;
    - `line_opened`, `cuts_changed`, `site_closed` and a fingerprint change cancel the solve.
  - The profile title follows the Global Constraints table.
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Update the guide** (`docs/guide/getting-started.md`, spec §7 and plan call 11):
  - **The toolbar table** gains **Cut**.
  - **New Step 8, "Draw a cut",** after Build slices. It covers:
    - drawing and reading a cut;
    - that a cut needs its grid shown in the Slices panel and uses the panel's interpolation settings and palette;
    - that under minimum curvature it shows kriging first, then the finished section;
    - that the map works on cuts while the cuts layer is current, and on lines otherwise;
    - picks on cuts.
  - The old Step 8 becomes Step 9.
  - **§4, Where your data lives:**
    - `survey.nsgeo.json` holds the cuts, and **Save site** writes them;
    - the **cuts** layer is redrawn from them and is read-only;
    - a cut moves with its grid, and its picks with it;
    - a pick on a deleted cut stays on the map;
    - a site with cuts does not open in nsgeo 0.2.0.
  - It is written for archaeologists, in the guide's existing voice.
- [ ] **Step 6: Measure on Grid 1** (`needs_sunnyside` from `plugin_testing.py`), and record the numbers in `cut_sections.py`'s module docstring (spec §5), at its remembered settings (0.05 m, minimum curvature, smoothing Y 0.1 m):
  - the first preview after the panel prepared the grid;
  - a repeat preview;
  - the redraw after a settings change;
  - the time until the walkthrough-length cut (about 12 m) is solved.

  If a hover under kriging takes over 100 ms, stop and report rather than ship.
- [ ] **Step 7: Run the full core + pure suite, the full QGIS suite, lint and types.**
- [ ] **Step 8: Commit and push:**
  `git commit -m "feat(cuts): minimum curvature solved near the cut behind a kriging preview; the guide (cut spec §4.7, §7)"`

---

## After Task 6 (coordinator)

These are the manual checkpoints from spec §8. Track them and report them; never pass them silently.

1. **Whole-branch review** (most capable model), then a fix wave if needed.
2. **Build and walkthrough.** Deploy to a fresh QGIS profile (`ns_geo_cuts`). Hold the walkthrough on Sunnyside Grid 1 at its remembered settings as an Artifact with a results db:
   - draw a cut along the lower line, through to the higher line;
   - watch it go from kriging to minimum curvature;
   - read its depth against the bowl;
   - check it against a slice at the line's depth where they cross;
   - pick it;
   - redraw it as a new cut, delete the old one, and confirm the old picks stay on the map;
   - also: the cuts-layer switch over the 0.5 m lines; Whole site scope with "not normalised"; a grid edit moving a cut and its picks; closing with an unsaved cut.
3. **The help-pages ledger.** Note the new **Cut** tool in the `nsgeo-help-pages` ledger (spec §7). The help-pages branch itself is not edited.
4. **README roadmap.** Move M15 to Done on merge, per the roadmap upkeep rule.
5. **File the deferred follow-ups** from review.
