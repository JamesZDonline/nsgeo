# Task 3 report: building a surface (fill, files, fit, staleness)

Status: DONE. Commit a490aa3 on nsgeo-m16-b, pushed to origin (push worked with the sandbox off).

## Implementation
- `paraview_export.py`
  - `ParaViewExport.fill(grid_id, choice, *, progress) -> FilledGrid` (lines, prov, frame, z, velocity, read-only memmap `filled`, skipped_lines). It runs the frame/source checks, the `.npy.part` sweep, line preparation, "Down to" clipping (`_clip`, `_levels`, `_effective_t1`), the cache lookup/fill and the opened memmap, with the same cache keys as `run`, so an export and a build share one fill. `progress(done, nz)` counts fill levels; False raises `ParaViewExportCancelled`.
  - `run` now calls the private `_fill_grid(grid_id, choice, step, announce)` (the `announce` hook gives it the depth axis so its progress total, nz + 3 x slabs, is unchanged). `test_plugin_paraview_export.py` and the dialog tests pass unchanged apart from the fixture move.
  - One tiny difference: `run`'s frame/source refusals now fall inside its try, so a stale `<grid>.partial` is also removed when such a refusal fires (previously left until the next run). Nothing observable in the export's output.
  - `place_picks(rows, lines, prov, frame, velocity) -> list[PlacedPick | None]` and `PlacedPick`; `_write_picks` uses it. A pick is None when its line is not among the prepared lines or its depth is not finite.
  - Small public wrappers for `Surfaces`: `source_choice`, `fill_settings`, `effective_t1`.
- `session.py`: `slice_sources_changed = pyqtSignal(str)`, emitted by `_update_source` after a real change. Added to `KNOWN_UNCONSUMED` (comment names Task 4).
- `surface_plan.py` (pure, in mypy/CI list already): `INPUTS`, `STALE_REASONS`, `input_hash`, `stale_text`, `fit_rows`, `offset_text`, `outlier_line`, `built_message`, `empty_message`, `rebuild_refusal`, `mesh_2dm`, `mesh_dat`.
- `surfaces.py`: `SurfaceState`, `BuildReport`, `BuiltSurface`, and `Surfaces.folder/inputs/state/build/built/sweep`.
- Test support: `Dock`, `GRID`, `STEPS_ZERO/RADAR` moved to `tests/plugin_testing.py`; the `synth_site` fixture moved to `tests/qgis/conftest.py`; the export test file only imports them (plus ruff dropped its now-unused imports).

## Decisions
- Cancel exception: reuses `ParaViewExportCancelled` (no new class).
- Build progress is reported as `(percent, 100)`: fill 0-80, volume slabs 80-95, surfaces 95-100.
- Build computes every surface in memory first, then writes all `.part` -> final files, the jsons last. Any failure or cancel removes this build's new files and `.part`s; previous files and json are untouched.
- Build key (file suffix) is `uuid4().hex[:8]`, so a rebuild never overwrites files a layer may have open. `build` does NOT sweep; Task 4 should call `sweep(grid)` after swapping the layer (it only deletes nsgeo-pattern files `<32hex>(-<8hex>.npz|2dm|dat | .json)(.part)?` that no record's json names; unreadable json keeps everything of that id).
- Step 1 order follows the brief (`remember_volume` before the fill), so a build refused because slices prepare has already remembered the 3-D choice (a session change, no files written).
- json: the extra `offset_votes`, `offset_at_limit`, `offset_reliable` sit top-level beside `offset_m`; `fit` holds the six counts. Outlier `distance_m` is the pick's stored `distance_m` (may be null). `resolution` is `{cell, dz_ns}` only (the effective t1 is in the `resolution` input hash, ruling R3).
- Ruling R9: `build` raises ValueError "... too few to rebuild ..." before touching anything.
- Picks whose line is not prepared (e.g. the grid's remembered line choice excludes it), whose depth is not finite, or whose position is not finite go to `skipped` with a plain `why`.
- `fit_rows`: the "further" and "at the window's edge" counts appear only when non-zero (keeps the mockup's line for the usual case); the unreliable-offset sentence is appended to Offset. The Built row appends "UTC" (stored time is UTC). Cover says "all N cells; no holes" when nothing is a hole.
- `state()` for a built surface whose inputs cannot be read (no preset, no shared time range) reports `stale == ("source",)` instead of raising.

## Tests and results
- `tests/qgis/test_plugin_surface_build.py`: 22 tests (parametrised staleness over `INPUTS`, both clocks, build files + world coordinates incl. rotated grid, shared fill, cancel, R9, remembered choice, busy refusal, skipped picks, sweep, Down-to/t1 resolution input, no-export RuntimeError, member deleted by hand, blur/panel never stale).
- Pure tier additions: `test_stale_text_names_every_reason`, `test_fit_rows_match_the_mockup`, edge/unreliable rows, outlier lines and messages, mesh files.
- RED: before `Surfaces.build` etc. existed, 20 of 22 qgis tests failed (the 2 that passed were the staleness-free ones needing no new API). The pure tests were written after `surface_plan.py` and passed on first run (no separate RED for them).
- GREEN: surface_build + export + export dialog + membership + session + slices dock = 396 passed (3 min 30 s); pure tier 341 passed, 3 skipped; `ruff check`, `ruff format --check`, mypy (CI list) clean. The full 22-minute QGIS tier was not run.

## Self-review / concerns
- `surfaces.py` is now 660 lines (membership + building). Left as is per instructions; the build half (`inputs`..`_write`) could move to its own module if you want.
- `surfaces.py` imports `_safe` and `_slab_levels` (private) from `paraview_export`; trivial to publish if you prefer.
- `inputs()` calls `export.defaults`, whose transform fallback reads the dock's combo; after any build the transform is remembered, so the combo cannot make a built surface stale (tested).
- `state()` recomputes `inputs()` each call (reads one file for a time-zero probe at most, memoised); fine for a panel refresh, cheap but not free.
- The 2DM triangle winding follows `surface_mesh` (not re-checked against QGIS's loader here; Task 4 loads it).

## Fix round 1 (review findings)
- R10: a build remembers `t1_ns` explicitly after the fill: the end the fill used (`FilledGrid.t1_ns`), rounded up at 4 decimals so the next fill is clipped at nothing new and shares the cache. The `resolution` input reads the record's raw `t1_ns` with cell and dz; `effective_t1`, `_record_range` and the panel engine are out of `inputs()` (wrapper removed). Choice is remembered after the fill now (a refused or cancelled-during-fill build remembers nothing). The `inputs` are computed once after that and written to the json (`_write` recomputes nothing).
- Atomic multi-build: after a record's json replaces the old one, its files leave `made`; test with an OSError on B's json replace.
- `_fill_grid` calls `traceback.clear_frames` before unlinking the `.npy.part`; `run`'s own cleanup unchanged.
- `state()` never raises (KeyError/OSError/ValueError/RuntimeError): `stale=("unavailable",)`, with a `STALE_REASONS` entry. `sweep` keeps files of every record whose `_safe` folder matches. `stale_text` builds its set once. Skipped picks show in `fit_rows` ("Skipped" row) and `built_message`; skipping below 3 picks refuses with the reason. The why strings and the multi-grid refusal moved to `surface_plan`.
- Clock test now also checks a radar-clock pick and a from-zero pick against the cube clock's own depth (time-zero preset; asserts the line's zero is non-zero). Dropped the unused `dock.grid_id`.
- Tests: surface_build 27 pass (probes' three also pass), export + dialog + membership 95 pass, pure 341 pass, ruff and mypy clean.
