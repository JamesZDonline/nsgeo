# Task 4 report: This grid draws, exports and remembers through the Interpolation panel

Commit 8f64637 on nsgeo-slice-interpolation, pushed to origin. Status: DONE_WITH_CONCERNS (concerns at the end are minor).

## What was implemented

- **Engine** (`slices_engine.py`): `finish_settings`, `weights_cached`, `finish`, `_weights_for`, `shared_limit(thickness, clip, finish)`. The cache is dropped in `_rebuild_geometry`, `set_source` and `clear`. The cell always comes from `frame.cell`.
  - Deviation from the brief, deliberate: the cache key is `(frame, method, max_distance_m, search_radius_m)`, not `(frame, settings)`. Smoothing is applied after the weights, so a smoothing drag no longer re-plans kriging (0.8 s at a 0.1 m cell on the 50 m grid). The "never serve the other setting's weights" rule still holds (tests below). `weights_cached` compares the key only; `finish` also checks `populated` with `np.array_equal`.
- **Dock** (`slices_dock.py`): grid_radius_spin / grid_radius_metres / grid_radius_row / `_update_radius_metres` / `radius_cells` / `_filled_radius_cells` removed. Added `grid_finish = FinishPanel(metres_label=True)` after `resolution_group`, `_finish_debounce` (120 ms, single-shot), `slice_finish()`, `_on_finish_edited` (guarded; remembers `{field: value}` unless `_updating`/`_seeding`/site scope, refreshes the label, starts the debounce), `_on_finish_timeout` (guarded), `_finish_moved()` (stale-redraw check, returns False with no source). `refresh_slice` wraps `engine.finish` in `busy_cursor()` when `not weights_cached` and records `_drawn_finish`. `display_limit`'s cache key now carries `engine.finish_settings(finish)` (metres, so a spacing edit invalidates it). Seed sets `SliceFinish()` quietly then `set_spacing`; restore lays `SliceFinish().updated(remembered)` over it (a 0.2.0 `radius_spacings` is ignored). `view_settings` writes the four fields plus `radius_m = max_distance_spacings x spacing`. `apply_view` sets the panel from `view.finish` (keyword `spacing_m` kept, used for the metres label). `restore_cube` remembers the four fields.
- **site_scope.py**: `show_scope_widgets` toggles `dock.grid_finish.setVisible(not site)`. The site's `radius_spacing_spin` is untouched.
- **slice_export.py**: `ExportPlan.finish: FinishSettings | None`; `plan_export(..., finish=None)`; `export_slices(..., finish: SliceFinish, *, writer=None)`; metadata `NSGEO_INTERPOLATION`, `NSGEO_MAX_DISTANCE_M`, `NSGEO_SMOOTH_X_M`, `NSGEO_SMOOTH_Y_M` (str(float)) plus `NSGEO_FRAME_AZIMUTH_DEG`; `NSGEO_FILL_RADIUS_CELLS` is gone; `write_coverage` passes `finish=None`.
- **plugin.py**: `export_geotiff` passes `dock.slice_finish()`, the radius-0 warning branch is deleted (message always plain), Ruling AE docstring rewritten.
- **slices_plan.py**: `format_status` counts `weights_bytes` in the held figure (carry-in 15).

## Carry-ins

- A1: `test_plugin_slice_export_dialogs.py` and `test_plugin_site_scope.py` updated to the panel (remembered per-grid radius became remembered per-grid finish field; `grid_radius_row` checks became `grid_finish`). The radius-0 warning test `test_export_geotiff_warns_when_fill_radius_is_zero` was REMOVED, superseded by `test_exporting_a_rotated_grid_reports_no_fill_warning`. Site `radius_spacing_spin` uses left alone.
- A2: `test_a_0_2_0_remembered_radius_is_ignored` puts `{"radius_spacings": 0.5}` through `session._update_source(...)`, saves, switches to A, asserts the panel is `SliceFinish()`, survey clean, record left as found, and no holes.
- A3: `test_a_rotated_export_is_at_half_pitch_and_keeps_every_cell` added (rotated 30 degree grid, method none, unique id per frame cell via a patched `slice_at`; `gt[1] == cell/2`, every id appears among finite pixels).
- B4: `test_no_orphan_signals.py` `edited` connects 1 -> 2 (comment updated: Task 5 raises it to 3).
- B5: both new slots guard their own bodies (`_log`).
- C10/C11/C12/C13: slice_export module docstring (cross-reference reworded, cost restated as 0.019 s vs 0.112 s, ~4.4 s over 39 bands), `ExportPlan`/`write` docstrings, plugin.py Ruling AE bullets, rotated-test docstring all rewritten.
- D14: `_edited_fields` annotation fixed (and `float()` on the remembered other bound so the comparison types).
- D15: done, with a pure test `test_the_status_line_counts_the_interpolation_weights_as_held`.
- E16: timings below.

## Grep hits for removed names (all accounted for)

slices_dock.py: `grid_radius_spin` (construction, connects, seed, restore, view_settings, apply_view, `_on_resolution_edited` site branch, docstrings) all removed or rewritten to `grid_finish`; `grid_radius_metres`/`grid_radius_row` gone; `_update_radius_metres` calls replaced by `grid_finish.set_spacing(self._grid_spacing())` (rebuild_source, seed, restore, restore_cube); `radius_cells()` gone, uses replaced by `slice_finish()`; `_filled_radius_cells` became `_drawn_finish`; `radius_cells_for` import removed; `fill(` call became `engine.finish`. Remaining "radius" mentions are the site's `radius_spacing_spin`/`DEFAULT_RADIUS_SPACINGS` (Task 5). site_scope.py: `grid_radius_row` replaced. slices_engine.py: `fill(` uses in `shared_limit` replaced; two stale docstring mentions fixed. slice_export.py: `radius_cells` (plan field, param, metadata, `fill(`) replaced. plugin.py: `radius_cells()` and warning branch removed. `radius_cells_for` and `DEFAULT_RADIUS_SPACINGS` stay in slices_plan.py (site uses them).

## Tests and results

- Core + pure: 921 passed, 3 skipped (baseline 920/3; +1 new pure test).
- Full QGIS suite (before the final `_finish_moved` helper edit): **1346 passed, 0 skipped** (baseline 1324/0). After that edit I re-ran the five touched QGIS files: 285 passed. ruff check and format --check clean; mypy clean (39 files).
- New tests: engine (finish vs core pipeline; metres at spacing; weights built once across windows; rebuild on method/distance/cell, smoothing keeps cache; rebuild when populated differs; kriging->IDW->kriging equals fresh engine; source change drops weights; shared limit over finished slices, both residencies), dock (all brief names, plus `test_a_finish_edit_redraws_through_its_own_debounce`, `test_a_seeded_finish_announces_nothing`), export (all brief names plus metadata-follows-finish and half-pitch). Existing fill/radius tests rewritten to the new API keeping intent. `test_shared_limit_measures_the_filled_array_actually_displayed` now uses `max_distance_spacings=1.5` (the 0.75 m radius it was first measured at): at the new default 0.25 m the unfiltered/finished ratio was 1.046, under the test's 1.05 discrimination margin.

## TDD evidence

I wrote the production code before the tests (a process slip). RED was reconstructed honestly: the new/updated tests, run against a `git archive HEAD` copy of the old sources (scratchpad `red/`, PYTHONPATH-isolated), failed: engine+export+dialogs files 25 failed / 67 passed (e.g. `AttributeError: 'SlicesDock' object has no attribute 'slice_finish'`, `TypeError`/missing `finish`/`NSGEO_INTERPOLATION`); dock file 31 failed / 82 passed. GREEN: the same files in the worktree, 285 passed (engine, export, dialogs, dock, site_scope); full suite 1346 passed.

## Step 5 timing (median per window, this machine, `timing.py` in the scratchpad `task4/`, not committed)

Real data: four real lines, grid 3 m x 12 m, spacing 0.5, 23-level windows, amp_square, weights cached.

| case | cell 0.2 (60x15) | cell 0.1 (120x30) |
|---|---|---|
| before: `fill(v, c, radius_cells_for(0.5, 0.5, cell))` | 0.14 ms | 0.30 ms |
| after: kriging default | 0.10 ms | 0.18 ms |
| after: IDW | 0.12 ms | 0.17 ms |
| after: none | 0.05 ms | 0.07 ms |
| after: kriging + smoothing 0.5/0.5 | 0.74 ms | 2.14 ms |
| first call (builds weights) kriging | 4.6 ms | 18 ms |

Synthetic 50 m grid, 0.5 m lines (via `plan_fill` + `finish_slice`):

| cell | old fill | kriging apply | IDW apply | kriging + smooth 0.5 | weights build |
|---|---|---|---|---|---|
| 0.2 (250x250) | 3.36 ms | 2.21 ms | 2.22 ms | 12.9 ms | 72 ms |
| 0.1 (500x500) | 21.5 ms | 11.3 ms | 11.4 ms | 118 ms | 780 ms |

Spec §7 gate met: cached cost is below the old fill in every case. Smoothing is the dominant per-slice cost at fine cells (about 107 ms at 500x500).

## Files changed

nsgeo_qgis: slices_engine.py, ui/slices_dock.py, ui/site_scope.py, slice_export.py, plugin.py, slices_plan.py. Tests: tests/pure/test_no_orphan_signals.py, tests/pure/test_pure_slices_plan.py, tests/qgis/test_plugin_slices_engine.py, test_plugin_slices_dock.py, test_plugin_slice_export.py, test_plugin_slice_export_dialogs.py, test_plugin_site_scope.py.

## Self-review findings (fixed)

- Added `_finish_moved()` guard so `rebuild_source` (a five-signal slot) can never raise from `finish_settings` when the survey closed or the grid vanished.
- Fixed three stale docstrings (engine `_grid_fingerprint`, `_mark_cube_unsaved`, `_drawn_finish` comment).
- Cache key narrowed (see above).

## Concerns

- The weights-bytes figure in `format_status` is the estimate (n_cells x 32 B), shown even before weights are built or under method none, as the carry-in asked.
- `FinishPanel.edited` raising receivers: dock slots guard themselves; the panel's own `set_spacing`/`_sync` path is unguarded but only does label text.
- `test_the_interpolation_group_replaces_fill_radius` allows one "Fill radius" label in the form, because the site's row remains until Task 5.
- Process: production code preceded tests (RED reconstructed against HEAD sources, as above).

## Fix round 1

Two test gaps from the task review; tests only, no production change.

1. `test_the_plugin_exports_the_docks_finish` (test_plugin_slice_export_dialogs.py): sets IDW, max distance 1.0, smoothing X 0.25 on `dock.grid_finish`, exports through the button, asserts the four metadata keys (`idw`, `str(1.0 x spacing)`, `"0.25"`, `"0.0"`) and every band against a core-pipeline oracle (`plan_fill` + `finish_slice` at `engine.frame.cell`, then `to_north_up`).
2. `test_a_0_2_0_remembered_radius_is_ignored` and `test_updated_lays_known_fields_over_and_ignores_the_rest` parametrised over radius_spacings [0.5, 1.5].

Mutant checks, in a scratch copy only (scratchpad `task4/mut/`, PYTHONPATH-isolated by running from the copy):
- Mutant A, `export_geotiff` passing `SliceFinish()` instead of `dock.slice_finish()`: only the new test fails (`assert 'kriging' == 'idw'`); the other 12 dialog tests pass, matching the reviewer's finding. (My first mutant attempt had a missing import and failed for the wrong reason, NameError; discarded and redone.)
- Mutant B, `SliceFinish.updated` mapping `radius_spacings` onto `max_distance_spacings`: the dock `[1.5]` case and the pure `[1.5]` case fail; the `[0.5]` cases pass, as predicted.

Slip, disclosed: before the correction message arrived I had briefly applied mutant A and B to the worktree's plugin.py and slices_plan.py. Both were restored from backups immediately, before any commit; `git status` shows only the three test files modified and no production file differs from 8f64637.

Verification: test_plugin_slice_export_dialogs.py + test_plugin_slices_dock.py 127 passed; test_pure_slices_plan.py 32 passed; ruff check and format --check clean.
