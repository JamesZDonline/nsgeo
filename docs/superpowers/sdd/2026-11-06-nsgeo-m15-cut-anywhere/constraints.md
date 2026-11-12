# M15 shared context for every task (plan calls, global constraints, verification, review focus)

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
   - `load_site` accepts 1 and 2. Released builds (0.3.0 and earlier) refuse a file with cuts and say so, rather than opening it and silently dropping the cuts on their next save. Sites without cuts stay readable by them. (`SCHEMA_VERSION` is still 1 on main as of `d8acb01`; if #97 or anything else bumps it before M15, `CUTS_SCHEMA_VERSION` becomes that plus one and the same rule holds.)
   - A cut entry is `{"id", "name", "grid_id", "vertices": [[x, y], …]}`. A malformed entry, or one on an unknown grid, is a `ProjectError`, as a line on an unknown grid is.
4. **Columns.**
   - Columns are `frame.cell / 2` apart along the cut, from 0, with a last column exactly at the cut's length.
   - Each column takes the bilinear blend of the four finished cells around it, and is blank exactly where its nearest cell is (spec call 11, #107's pixel rule). The columns carry `nsgeo.slices.resample.bilinear_taps(frame, world)`, and a level's column values are `resample.sample(finished, taps)`. `cells` is `taps.nearest` (−1 outside), so it matches `CubeFrame.cell_index` of the column's world position (tested).
   - The finished values are needed only at the taps' cells: the union of `taps.ids` over inside columns. Fill a (ny, nx) NaN canvas at those cells and call `sample` on it. That equals sampling the whole finished slice, because `sample` reads only the nearest cell and the four taps.
   - The session's "trace" for a cut is a column index. It is clamped only below (−1), because the column count belongs to the section, not the session. It is never the truth for a pick (spec call 12).
5. **Where the values come from.**
   - A section reads the engine's resident cube (`SliceEngine.cube()`, every level). A hover preview never builds one. If the engine holds no cube, the preview shows a message.
   - Opening a cut (select, Survey panel Open, finishing a drawing) builds the cube synchronously under a wait cursor. That meets §5's "must not freeze the canvas on hover", and a streaming engine's first cut pays the build once.
6. **Fills.**
   - The section asks the engine for its fills through a new public `SliceEngine.section_fills(finish)`. It returns what the engine holds when its key matches, and otherwise builds through the engine's own `_fill_for`. A cut never plans weights of its own (§5).
   - Minimum curvature's kriging stand-in is the engine's `PREVIEW_METHOD` weights.
7. **Crops.**
   - Smoothing crops reach the smoothing kernel's radius (`ceil(SMOOTH_TRUNCATE_SIGMAS · σ / cell)` cells) plus one cell (the blend's far tap) past the columns' nearest cells, so a smoothed section equals the sampled smoothed slice exactly.
   - Minimum-curvature crops reach `curvature_margin_cells(settings, cell, spacing_m)` = `max(ceil(SECTION_MARGIN_SPACINGS · spacing_m / cell), the smoothing reach) + 1` cells. `spacing_m` is the cut's grid's `default_spacing` in both scopes, the same spacing `SliceEngine.finish_settings` uses. *(Ruling during Task 1, 2026-11-11: the reach is counted in line spacings. Minimum curvature through one-cell-wide lines couples across lines the way a spline couples across knots, so the 1 m the spike chose missed 0.1% by up to 3% on cuts along the lines.)*
   - Pieces cover at most `SECTION_PIECE_M` of the cut, and each piece's curvature plan (which now includes #111's multigrid hierarchy) is built once per solve, not per level.
   - Measured in Task 1 on the ten real lines at 6 spacings: worst error 2.2e-5 of the range, at 0.07–0.20 s a level at 0.05 m (0.20 s for a 12 m diagonal cut) and 0.02 s at 0.2 m. On Grid 1 a whole-frame solve is 0.30 s a level, so crops are now only about 1.5× faster there. They win on big grids, whose whole-frame solve grows with the grid while a crop does not. Task 6 measures Grid 1.
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
13. **The clock** (spec call 18, #97). These names are taken from `nsgeo-time-zero` `6e42814`; the coordinator confirms them after #97 merges.
    - A cut pick is written with `Pick.zero_ns = None`.
    - `SiteSession.line_zero(key)` returns `None` for a cut key without logging.
    - `SiteLayers._follow_key` returns at once for a cut key, so `follow_zero` never runs on one.
    - The profile's pick overlay, its slice band and its axes use a cut's times as they are, with no `retime_ns`, `shown_zero_ns` or `_cube_zero_lookup` conversion, since all three are already on the cube's clock.
    - A pick whose provenance `time_base` differs from the shown cube's `time_base_of(provenance.steps)` is left out of the overlay and counted in the title (` · {n} picks on another clock`).

## Global Constraints

- **The core stays numpy-only, with no Qt.**
  - `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` stay green.
  - No scipy.
  - The plugin imports Qt only through `qgis.PyQt`.
- **Python 3.9 floor for the core:** no `zip(..., strict=...)`, no `match`, no `X | Y` outside annotations, no `dataclass(slots=..., kw_only=...)`.
- **Slots guard their bodies.** Every slot connected to a Qt signal or timer, and every Qt-invoked map-tool method, guards its own body. It reports through `_log`, a `failed`/`error` signal, or the message bar, and never raises. This includes `CutSections`' slots, `CutTool`'s events, and the plugin's `currentLayerChanged` slot.
- **No orphan signals.** `tests/pure/test_no_orphan_signals.py` stays green, so every new `pyqtSignal` is connected.
- **The pixel rule** (#107): a column's value is `resample.sample` over `bilinear_taps`, never a hand-written blend and never nearest-cell alone.
- **The clock** (#97): every time on a cut is on its cube's clock. Code that converts a line's times (`retime_ns`, `Pick.radar_ns`, `line_zero`, `follow_zero`) is never applied to a cut key.
- **The cube is read only through its read path** (#113): `cube.level(k)` and `cube.slice_levels(k0, k1)` give a (ny, nx) slice, `cube.values_at(cells, k0, k1)` gives (k1 − k0, n) with NaN for −1 and for cells nothing landed in, and `cube.coverage()` gives (ny, nx). Code and tests never index `cube.blocks` or a block's `mean` or `count`. The resident cube stores only covered cells, one block per direction.
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
  | `SECTION_MARGIN_SPACINGS` | `6.0` (replaces `SECTION_MARGIN_M = 1.0`; ruling during Task 1) |
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
  | Grid removal addition | Appended to the grid question. ` Its 1 cut is deleted too` or ` Its {n} cuts are deleted too`, then `.` with no picks, or `; its 1 pick stays on the map.` / `; its {m} picks stay on the map.` (`their` for several cuts). `Their …` when several grids go at once. *(Ruling during Task 2: number agreement, plus the pick count spec §4.8 asks for.)* |
  | Profile title | `nsgeo Profile · cut: {name} · {grid} · {length:.1f} m · {method}`, then ` · site view, not normalised` in Whole site scope, then ` · {n} picks on another clock` when there are any (plan call 13), and the existing `PREVIEW: ` prefix on a preview. The `cut:` stays even after a rename, so the title always says a cut is showing (decision 11). |
  | `{method}` | `METHOD_LABELS[method]`. While kriging stands in: `Kriging preview (minimum curvature when opened)` on a preview, `Kriging preview · minimum curvature {done} of {total} depths` while solving, and `Minimum curvature` when done. |

- **Comments and docstrings** follow the file they are in. They say why, and cite the spec as `(cut spec §4.7)`.
- **Shared-worktree safety.** Reviewers and any mutation testing never edit this worktree; they work on a scratch copy. Set `PYTHONDONTWRITEBYTECODE=1` for every test run.

## Verification commands (exactly these, from the worktree root)

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`. About 11 minutes, so run single files while iterating.
- **lint:** `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- **types** (CI's list): `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`

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

