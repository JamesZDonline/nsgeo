# Task 4 report: the Cut tool and the map working on cuts

## Implemented
- `maptools/cut_tool.py`: `CutTool` (drawn(list), failed(str), idempotent dispose, Esc consumed with e.ignore(), Enter/right-click finish, Backspace, rubber band with moving segment, stays on for the next cut).
- `plugin.py`: Cut toolbar toggle (enabled whenever a site is open), `_toggle_cut_tool` (setMapTool, setFocus, hint, `iface.setActiveLayer(cuts)`), `_on_cut_drawn` (first grid in survey order containing the first point, canvas CRS -> grid CRS -> `Grid.to_local`; OUTSIDE_TEXT / TOO_FEW_TEXT; add_cut then open_line; tool stays on), `canvas.mapToolSet` unchecks Cut when another tool takes over, `iface.currentLayerChanged` and site open/close -> `map_link.set_cut_mode` (layer ids compared), `map_link.set_sections`.
- `map_link.py`: `cut_mode`, `set_cut_mode` (clears preview), `set_sections`, cut geometry cache (invalidated with lines cache and on cuts_changed), `_hit_test` branches on mode (line mode ignores cuts, cut mode ignores lines), pointer -> nearest point on cut -> canvas->grid CRS -> `Cut.locate` -> `column_at`; marker/band on cut keys from `columns.world` transformed to canvas CRS (cached per section); `selectionChanged` on cuts layer opens the cut; no column means preview without cursor.
- `tests/qgis/conftest.py`: FakeIface gains activeLayer/setActiveLayer/currentLayerChanged (kept a plain object; `_FakeSignal.emit` takes args).
- `tests/pure/test_no_orphan_signals.py`: `failed` is now declared by two classes, pinned in SHADOWED (declared 2, connects 2).

## TDD evidence
- RED for the tool: with cut_tool.py moved away, `test_cut_tool.py` -> `ModuleNotFoundError: No module named 'nsgeo_qgis.maptools.cut_tool'` (collection error).
- Honest note: for the plugin and map-link files I wrote implementation before running the new tests, so there is no recorded RED run for them; first runs went green except fixture/assumption fixes in the tests themselves (line reach on a short-lines grid, approx on nested tuples, picks featureCount -1 replaced by a picks_changed spy).
- GREEN: `test_cut_tool.py` 7, `test_plugin_cut_drawing.py` 7, `test_plugin_map_link_cuts.py` 11, existing `test_plugin_map_link.py` still green.

## Full verification
- core + pure: 1292 passed, 5 skipped (after pinning `failed` in SHADOWED; first run had 1 failure there).
- qgis full: 1756 passed in 971 s (log: task-4-qgis-full.log).
- ruff check and ruff format --check clean; mypy (CI list) clean.

## Files
packages/nsgeo-qgis/nsgeo_qgis/maptools/cut_tool.py (new), nsgeo_qgis/plugin.py, nsgeo_qgis/map_link.py, tests/qgis/conftest.py, tests/pure/test_no_orphan_signals.py, tests/qgis/test_cut_tool.py, test_plugin_cut_drawing.py, test_plugin_map_link_cuts.py (new).

## Self-review / concerns
- Pointer tracking and the hit test are strict per mode: a displayed cut is not tracked in line mode, a displayed line not in cut mode (my reading of "line mode ignores cuts").
- Cut hint reuses `_say_pick`/`_pop_pick_message` (one shared message slot); fine since map tools are exclusive.
- Esc with an empty path does nothing (does not leave the tool); toggle off is the exit.
- Marker/band call `sections.section(key, build_cube=False)` per refresh, which records a "waiting" entry for a cube-less preview (harmless, matches Task 3 behaviour).
- A single-column selection draws no band (needs a segment).

## Push
Commit b0c4e00 is local. `git push origin nsgeo-m15-cut-anywhere` failed: could not resolve host github.com (no network in this sandbox). Needs a re-push.

## Fix round 1
Changes:
1. cut_tool.py: Backspace and Enter/Return now `e.ignore()` (consumed, as Esc); docstring updated. Tests: `test_enter_finishes_and_backspace...` asserts `not isAccepted()`; new `test_the_keys_the_tool_handles_never_reach_the_canvas` sends real key events to the canvas and asserts `canvas.keyPressed` stays silent.
2. `test_cut_mode_previews_the_cut_even_when_a_line_is_nearer`: pointer on a line vertex 0.1-0.4 m from the cut; cut mode previews the cut with the projected column, line mode previews the line.
3. `test_dispose_...`: failed stays empty, `tool.points == []`, no `drawn`, old band `scene() is None`. This exposed a real defect (a disposed tool still collected points and emitted): disposed tool is now inert.
4. plugin.py `_cut_grid_and_vertices`: the first point alone picks the grid; the rest are transformed after (failure -> plain "cannot be placed" message). Shared `map_link.crs_transform` (None for same/invalid CRS, RuntimeError when no transform) used by the plugin and `MapLink._grid_transform`, so they agree. Test: `test_the_first_point_alone_chooses_the_grid`.
5. MapLink caches a failed grid transform (`_no_transform`, logged once, cleared in `_invalidate`); callers answer "no column". Test: `test_a_missing_transform_logs_once_not_on_every_move`.
6. `unload()` wraps `_drop_cut_tool()` in `contextlib.suppress(Exception)`.
Commands/output: ruff check clean; ruff format --check "194 files already formatted"; mypy "Success: no issues found in 46 source files"; pure tests 248 passed, 1 skipped; test_cut_tool + test_plugin_cut_drawing + test_plugin_map_link_cuts + test_plugin_map_link + test_plugin_loads: 98 passed. Full QGIS suite not re-run this round (only the files above).
