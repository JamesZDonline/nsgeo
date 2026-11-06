# Final-review fix wave — report (from 5a4d54e)

Status: DONE. F1 was revised mid-wave by the user (default 0.75 × spacing, no half-cell allowance); the half-cell version had been written and shown RED/GREEN but was never committed — it was reverted with `git checkout` before the revised F1 was built. All other items as ruled.

Probes and throwaway scripts: /tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/ac13f161-32cb-4b27-9f12-2ce0f0d8a39b/scratchpad/finalfix/ (nothing committed). "Before" code for timings and identity checks is `git archive 5a4d54e` in that folder's `base/` and `ref/`.

## F1 [Critical] Default max distance 0.75 × line spacing (revised ruling)

**Changed**
- packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py:150-159 — `DEFAULT_MAX_DISTANCE_SPACINGS = 0.75`, comment gives the quantisation reason and the skipped-line bound. `SliceFinish()`, `ViewSettings` defaults, both scopes follow it. `plan_fill`'s inclusive rule unchanged.
- packages/nsgeo-qgis/nsgeo_qgis/ui/finish_panel.py:41-46 — `DISTANCE_TIP` replaced with the exact copy given.
- docs/guide/getting-started.md (Max distance bullet, ~:394-404) — default 0.75, why (cells a line crossed can sit up to half a cell off it, so half a spacing striped), when to lower toward 0.5 or raise; wrapped.
- Spec: decision 12 reworded as given; §5.2's "Default" bullet now gives the quantisation reason, the `(s + c) / 2 ≤ 0.75 s` bound and the skipped-line case; the "inclusively" bullet no longer claims the default's midpoint sits on the limit; §8's table "Default 0.75 (§5.2)". No half-cell note (never committed).
- Plan Global Constraints row: `0.75` × line spacing (user, 2026-11-03).

**Tests**
- Core (packages/nsgeo-core/tests/test_slices_interpolate.py): `binned_lines` helper (`CubeFrame.for_grid` + `cell_index`, as the probe bins); `test_binned_lines_fill_at_three_quarters_of_a_spacing[idw|kriging × (0.75,0.2),(0.7,0.2),(0.5,0.15),(1.5,0.2)]` (also asserts both floor and ceil gaps occur); `test_half_a_spacing_stripes_binned_lines[idw|kriging]` (pins why 0.5 is not the default); `test_a_skipped_binned_line_leaves_a_blank_stripe_at_three_quarters_of_a_spacing[idw|kriging]` (exactly 2 blank rows at 0.5 m / 0.2 m). These pass `0.75 * spacing` to `plan_fill` explicitly, so they are characterisation of the unchanged rule: GREEN at once.
- Pure (packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py) — the genuine RED for the default: `test_the_default_max_distance_is_three_quarters_of_a_spacing[0.5|0.7|1.5]` (`SliceFinish().in_metres(s).max_distance_m == 0.75 * s`); `test_the_default_finish_closes_every_gap_between_binned_lines[idw|kriging × 5 geometries]` (the default finish, in metres, through `plan_fill` on rows binned by `y // cell`); `test_the_default_finish_leaves_a_skipped_line_blank[idw|kriging]`.
- RED: `pytest packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py` → 13 failed (test_slice_finish_defaults, the three `three_quarters` cases, the 8 non-trivial binned-gap cases, test_in_metres…); GREEN after the constant: 930 passed / 3 skipped core+pure. Tooltip: `test_the_tooltips_are_the_pinned_copy` RED (`- Three quarters … + Half a line spacing …`), GREEN after the copy.

**Existing tests changed (default pins; the new oracle is the 0.75 default)**
- test_pure_slices_plan.py: `test_slice_finish_defaults` (0.5 → 0.75); `test_in_metres_scales_by_the_spacing_and_sets_the_search_radius` (0.25 → 0.375; search radius 1.0 unchanged).
- test_plugin_finish_panel.py: `test_the_tooltips_are_the_pinned_copy` (new copy); `test_the_metres_label_follows_the_spacing` ("= 0.25 m" → "= 0.375 m"); `test_a_user_edit_emits_the_field_and_value` (it set 0.75, now the default and so no edit: 1.25 instead).
- test_plugin_slices_dock.py: `test_the_max_distance_is_a_distance_and_survives_a_cell_size_change` (0.5/0.25 m → 0.75/0.375 m, core oracle at 0.375 m); `test_this_grid_sets_the_max_distance_in_line_spacings` (0.75, "= 0.375 m"); `test_max_distance_follows_a_line_spacing_edit` (at 1.0 m spacing: 0.75, "= 0.75 m", oracle at 0.75 m); `test_seeding_a_grid_resets_the_panel_and_remembers_nothing` ("= 0.375 m"); `test_switching_grid_away_and_back_restores_that_grids_resolution` (B at 0.75); comment at :947; `test_a_0_2_0_remembered_radius_is_ignored` docstring (it claimed the default "is also 0.5").
- test_plugin_slice_export.py: `test_the_geotiff_carries_interpolation_metadata` (`NSGEO_MAX_DISTANCE_M` "0.25" → "0.375", docstring).
- test_plugin_site_scope.py: `test_the_scope_switch_swaps_the_source_controls`, `test_refreshing_the_grid_list_reads_each_line_once`, `test_the_max_distance_tooltip_gives_each_grids_metres` ("A 0.75 m" → "A 1.12 m": 0.75 × 1.5 m = 1.125 m at the tooltip's 2 dp); `test_export_routes_to_the_site_geotiff_in_site_scope` (`NSGEO_SITE_MAX_DISTANCE_SPACINGS` 0.5 → 0.75).
- Unchanged: the #104 test reads `SliceFinish().max_distance_spacings * 0.5`, so it follows the default; tests passing 0.5 as a setting stay.

**Stripe counts** (`quantised_stripes.py` as a scratch copy taking the multiple; kriging; 20 m grid; blank rows between first and last line / gaps)

| spacing @ cell (first line) | at 0.5 × spacing (5a4d54e default) | at 0.75 × spacing (now) |
|---|---|---|
| 0.5 @ 0.2 (0.25 / 0.0) | 0/39, 0/39 | 0/39, 0/39 |
| 0.5 @ 0.15 (0.25 / 0.0) | 13/39, 13/39 | 0/39, 0/39 |
| 0.5 @ 0.09 | 22/39 | 0/39 |
| 0.75 @ 0.2 (0.375 / 0.0) | 20/26, 19/26 | 0/26, 0/26 |
| 1.5 @ 0.2 | 6/12 | 0/12 |
| 1.0 @ 0.2 | 0/19 | 0/19 |
| 0.7 @ 0.2 | 14/28 | 0/28 |
| skipped line, 0.5 @ 0.2 (idw, kriging) | 2 blank rows | 2 blank rows |

## F2 [Important] plan_fill's transient memory

**Changed** — packages/nsgeo-core/src/nsgeo/slices/interpolate.py: `_PLAN_CHUNK = 8192`, `_SOLVE_CHUNK` 50 000 → 2048 (comment :49-58 with the measurements); new `_offsets` (int32 offsets, (0, 0) in empty slots); `plan_fill`'s stages after `_neighbourhoods` run per chunk into a preallocated float32 `weights` (:277-284); `_neighbourhoods`' `ty/tx/active` are int32 (:167-173). Kriging dedupes and solves per chunk. Module docstring timing table re-measured. `WEIGHT_BYTES_PER_CELL` stays 96 (measured peak 105-107 B a cell, +9-11%, under the ruling's ~50%); its comment records the measurement; `MAX_FRAME_CELLS`' comment (slices_plan.py:289-302) rewritten to name what dominates (weights ~95 B held / ~107 B peak, apply ~55 B, smoothing ~41 B a cell).

**Tests** — test_slices_interpolate.py: `test_the_plan_does_not_depend_on_the_chunk_size[idw|kriging]` (random mask, chunk 7 / solve 5 vs default, `array_equal` on targets, sources, weights); `test_planning_needs_little_more_memory_than_the_weights_it_returns[idw|kriging]` (tracemalloc peak ≤ 1.5 × `nbytes`, small chunks). test_pure_slices_plan.py: `test_the_weights_estimate_covers_building_them[idw|kriging]` (peak per cell ≤ 1.5 × `WEIGHT_BYTES_PER_CELL` at the default finish, 0.5 m lines at 0.05 m).
- RED: chunk test → `AttributeError: … has no attribute '_PLAN_CHUNK'`; memory test → `assert 22502723 <= (1.5 * 3784000)` (idw) / `23069366 <= …` (kriging). The pure test was written after the code; its RED was shown against 5a4d54e's interpolate.py in a scratch copy: `assert ((22505925 - 0) / 40000) <= (1.5 * 96)` and `23069327/40000 …`. GREEN: all pass.
- Bit-identity (chunking must not change a weight): scratch `bit_identity.py` compares the new `plan_fill` with 5a4d54e's on 17 geometries (the test "lines", random masks, binned rows at five spacings/cells, a skipped line, wandering lines 0.1 m@20 m and 0.05 m@15 m with 81 000 targets, a single cell) × idw/kriging × chunk configs (8192/2048, 7/5, 1000/3): 0 differences in targets, sources, weights, populated and dtypes, under numpy 2.5.4 and 1.26.4. Every existing interpolation test is unchanged and green.

**Numbers** (`plan_peak.py`, wandering lines, 50 m grid, tracemalloc)

| case | before (5a4d54e) | after |
|---|---|---|
| kriging 0.1 m | peak 116 MB, 466 B/cell | 26 MB, 105 B/cell |
| kriging 0.05 m | peak 561 MB, 561 B/cell | 105 MB, 105 B/cell |
| idw 0.1 m | 113 MB, 453 B/cell | 23 MB, 91 B/cell |
| idw 0.05 m | 545 MB, 545 B/cell | 97 MB, 97 B/cell |
| nbytes | 77 / 92 B/cell | same |

At the 0.75 default (kriging 0.05 m): nbytes 95 B/cell, peak 107 B/cell. Fixed working set over `nbytes` with the shipped chunks: 3.8-3.9 MB on line data, 17.9 MB on a 600×600 random mask where every kriging pattern is new. Plan time, straight 0.5 m lines over 50 m, quiet machine, before → after: 0.2 m 0.081/0.074 → 0.081/0.074 s (idw/kriging); 0.1 m 0.67/0.65 → 0.59/0.48 s; 0.05 m 6.5/6.4 → 5.4/5.4 s. Apply unchanged (code untouched; 0.05 m apply is noisy, 46-80 ms both before and after).

## F3 [Important] Rotated preview tick

**Changed** — packages/nsgeo-core/src/nsgeo/slices/display.py:238-312: `_build_north_up_plan(frame)` (the old extent/pitch/`cell_index` code, returning read-only int32 clipped ids, the inside mask, shape and geotransform) and `_north_up_plan = functools.lru_cache(maxsize=_NORTH_UP_PLANS=2)` keyed on the frozen `CubeFrame`; `to_north_up` keeps its signature and does the shape check, then `np.where(inside, values.reshape(-1)[safe], nan)`. Two plans because one at the 4M-cell cap is ~90 MB. packages/nsgeo-qgis/nsgeo_qgis/slice_export.py module docstring: the "not hoisted" note replaced (the export shares the plan).

**Tests** — test_slices_display.py `test_the_north_up_gather_is_planned_once_per_frame`: counts `_build_north_up_plan` via monkeypatch after `cache_clear`; an equal (not identical) frame reuses the plan and gives the same output for new values; a different frame builds its own. RED: `AttributeError: module 'nsgeo.slices.display' has no attribute '_north_up_plan'`; GREEN. All display/export/layer tests unchanged and green. Byte-identity: scratch `northup_identity.py`, 216 comparisons (9 azimuths incl. 0, 1e-7, 90, 180, 270 × 4 frame sizes incl. UTM origins × float32/float64/int64 × cold/cached) against 5a4d54e's function, `tobytes()` and geotransform equal, numpy 2.5.4 and 1.26.4.

**Numbers** (`northup_cost.py`, 10.497° rows; before = 5a4d54e, quiet)

| frame | before | after, each tick | after, first call on a frame |
|---|---|---|---|
| 100×150 @ 0.2 m rotated | 12.8 ms | 0.3 ms | 12.2 ms |
| 250×250 @ 0.2 m rotated (50 m) | 52.0 ms | 1.6-2.2 ms | 61.1 ms |
| 500×500 @ 0.1 m rotated | 265.1 ms | 7.4-7.8 ms | 287.4 ms |
| 250×250 @ 0.2 m axis-aligned | 8.5 ms | 0.3 ms | 8.9 ms |

(The reviewer's earlier run had 60.7 / 294 ms for the two big rotated cases on a busier machine.) The GeoTIFF write in `SliceLayer.update` is extra and untouched.

## F4 [Important] Whole-site finish debounce

**Changed** — packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py:477-486, 707-727, leave/dispose: `SiteScope.finish_debounce` (single-shot, `dock._finish_debounce.interval()` = 120 ms, = `dock._debounce`); `_on_finish_edited` remembers the value and calls `refresh_rows()` at once (as This grid remembers and relabels at once, so the tooltip metres and the saved record never lag), then starts the timer; `_on_finish_timeout` guards its body and calls `schedule_refresh()`; `leave()` and `dispose()` stop it. No pyqtSignal declared or connected, so test_no_orphan_signals is unaffected (pure tier green).

**Test** — test_plugin_site_scope.py `test_quick_site_finish_edits_redraw_once`: two max-distance edits with an event-loop pass between, `refresh_slice` counted: none during, exactly one after, value remembered and tooltip "A 1.88 m" at once. RED: `assert [1, 1] == []`; GREEN.

## F5 [Important] Plugin site export wiring

**Test** — test_plugin_site_scope.py `test_the_site_export_writes_the_finish_the_panel_shows`: sets IDW, 1.5 × spacing, smoothing Y 0.3 m through the panel's widgets, exports through `export_button`, asserts `NSGEO_SITE_INTERPOLATION == "idw"`, `NSGEO_SITE_MAX_DISTANCE_SPACINGS == 1.5`, `NSGEO_SITE_SMOOTH_X_M == 0.0`, `NSGEO_SITE_SMOOTH_Y_M == 0.3`, and the first two bands `array_equal` to `site_engine.slice_at(top, thickness, finish=SliceFinish("idw", 1.5, 0, 0.3), method=…, manual=…)`.array (the writer stores that array as it comes), plus that band 1 differs from the default finish's. Passes on the real code. Mutant (scratch copy only, `finish=SliceFinish()` at plugin.py:1042): `AssertionError: assert 'kriging' == 'idw'`; the old `test_export_routes_to_the_site_geotiff_in_site_scope` passed on the same mutant. Worktree plugin.py confirmed untouched (`git diff --quiet`).

## F6 [Important, partial] Weights kept on z-only edits

**Changed** — packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py `_rebuild_geometry` (:826-848): holds the weights across the rebuild and restores them only when the new frame equals the one they were keyed on; `set_source`, `clear` and a new frame (or no frame) still drop them; `_weights_for` still checks key + populated mask. Synchronous build kept.

**Test** — test_plugin_slices_engine.py `test_a_z_only_resolution_edit_keeps_the_weights`: after one build, a dz edit and a z0/z1 edit leave `weights_cached` true and `plan_fill` uncalled; the drawn slice `array_equal`s a fresh `SliceEngine`'s at the edited resolution; a cell change rebuilds. RED: `assert engine.weights_cached(finish)` → False; GREEN.

## F7 Guide
docs/guide/getting-started.md: IDW sentence rewritten (never goes beyond the values around it; kriging can overshoot a little beside a strong contrast); the unwrapped lines (:396 in F1's rewrite, :404) wrapped; the wait-cursor sentence now says the fill is prepared again for a new cell size, method or max distance and that stepping, smoothing and dz/z0/z1 reuse it (true after F6). No test (docs).

## F8 Spec citations
Every "(interpolation spec §…)" in the branch's changed .py files (38 files, citations split over comment lines included) checked against the headings. Corrected: interpolate.py :5 §5.1→§5.2, :9 §5.2→§7, IDW_POWER §5.2→§5.1, `_kriging_weights` §5.2→§5.1; finish.py and test_slices_finish.py §6→§4 (the pipeline order); slices_plan.py `Resolution` docstring §8→§4, `MemoryEstimate.weights_bytes` §8→§7, `format_status` §8→§7; site_scope.py tick busy cursor §8→§7; site_engine.py `a·finish+b` §8→§4, §8; test_plugin_site_engine.py shared-stretch and wait-cursor docstrings §8→§7. The rest were right. (interpolate.py's and slices_plan.py's went in with F2's commit, site_scope.py's with F4's.)

## F9 Stale text
slices_plan.py `MAX_FRAME_CELLS` comment (F2); survey.py:130 cube `view` description (the interpolation, `radius_m` still written); plugin.py:998 `export_site_geotiff` docstring (normalisation, `dock.site_finish`); test_plugin_slices_dock.py `test_the_interpolation_group_replaces_fill_radius` docstring (no longer "#104's panel").

## F10 ValueError in _finish_moved
slices_dock.py:2019-2030 `_finish_moved` catches `ValueError` too (docstring says why). Test `test_a_line_spacing_of_zero_does_not_abort_the_rebuild` (spacing 0 via `replace_grid`; `_finish_moved()` is False and no "could not rebuild the slice source controls" message). RED: `ValueError: line spacing must be positive, got 0.0`; with only the log assertion against the unfixed code (scratch): `assert not ['could not rebuild the slice source controls: line spacing must be positive, got 0.0', …]`; GREEN.

## F11 radius_m under None
slices_dock.py:1494-1520 `view_settings`: `radius_m = 0.0` under "none", else spacings × spacing. Pinned in `test_saving_a_cube_records_the_finish_and_radius_m` (extended: switch to None, `view.radius_m == 0.0`, finish otherwise kept). RED: `assert 0.75 == 0.0`; GREEN. Spec §8's `radius_m` paragraph notes it.

## Full suites (final tree)
Run on the final tree (3d9116c's content, from the worktree, nothing edited during the runs), with the globals.md commands:
- core + pure: **937 passed, 3 skipped** (baseline 903 / 3; +34 new tests; the 3 skips are test_schema's by-design ones).
- QGIS: **1366 passed, 0 skipped** in 11:20 (baseline 1362 / 0; +4 new tests: F4, F5, F6, F10).
- `ruff check .`: All checks passed. `ruff format --check .`: 164 files already formatted.
- mypy (globals.md command): Success, no issues found in 38 source files.
Intermediate commits, each from an export of the index (`git checkout-index`, so the two git-dependent build_zip tests fail/skip there by environment, not code): 0353aac core+pure 930 (928 + those 2), QGIS 1362 passed; 7862d54 core+pure 936, QGIS 1363 passed; 0abcec1 core+pure 937, QGIS slice_layer/slice_export/slice_export_dialogs/slices_dock 184 passed; e0799db core+pure 937, QGIS site_scope/site_engine/site_export 151 passed.

## Commits
Pushed to origin nsgeo-slice-interpolation (5a4d54e..3d9116c):
- 0353aac fix(slices): default max distance 0.75 x line spacing, so binned lines at nominal spacing leave no stripe (interpolation spec §5.2) — F1
- 7862d54 perf(slices): plan_fill in chunks near the memory it keeps; z-only edits keep the weights (interpolation spec §7) — F2, F6 (+ F8/F9 lines in interpolate.py and slices_plan.py)
- 0abcec1 perf(slices): plan the north-up gather once per frame, so a rotated preview tick is one gather (interpolation spec §8) — F3
- e0799db fix(slices): debounce the site's Interpolation redraw, and pin the plugin's site export finish (interpolation spec §8) — F4, F5 (+ F8 line in site_scope.py)
- 3d9116c fix(slices): guide, spec citations, stale text, a zero spacing and radius_m under None (final review) — F7, F8, F9, F10, F11
The first push of 3d9116c hit a transient DNS failure; the retry succeeded (origin = HEAD = 3d9116c).

## Could not do / concerns
- None blocking. Notes: the F1 core binned tests are characterisation (the rule they exercise did not change), so their RED is carried by the pure default tests. The F2 estimate test and the F5 test were written after their code; their RED is shown against the old code / a mutant in scratch copies, never in the worktree. Intermediate commits were checked with core+pure on an export of the index each time, the full QGIS suite on the F1 and F2+F6 trees, and the affected QGIS files on the F3 and F4+F5 trees; the full QGIS suite ran on the final tree.
- Cosmetic, for the walkthrough: at the 0.75 default the site tooltip shows site3's 1.125 m as "1.12 m" (2 dp, round-half-even); the format was left alone.
- Two judgement calls inside the rulings: kriging now dedupes per chunk (more duplicate solves, still faster overall), relying on each `np.linalg.solve` system being solved on its own — checked bit for bit, not assumed; and `_NORTH_UP_PLANS = 2` bounds the hidden cache at roughly 2 × 90 MB at the 4M-cell cap.
