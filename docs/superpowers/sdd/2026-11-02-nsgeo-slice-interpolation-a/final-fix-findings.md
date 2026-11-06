# Final-review fix wave — findings and rulings (head 5a4d54e)

The whole-branch review returned "With fixes". This is the complete list to fix in one wave. Each item gives the finding (from the reviewer, file:line at 5a4d54e), the coordinator's ruling where one was needed, and what "done" means. The reviewer's probe scripts are in /tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/ac13f161-32cb-4b27-9f12-2ce0f0d8a39b/scratchpad/final-review/probes/ (read them; run them only as `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python <probe> <worktree-root>`).

## F1 [Critical] Default max distance stripes between lines at nominal spacing

**Finding.** `interpolate.py:128`/`:246`: the reach compares cell-centre distances against `max_distance_m + 1e-9`, with `DEFAULT_MAX_DISTANCE_SPACINGS = 0.5`. Binning puts each datum at its cell centre, up to half a cell from its line, so two lines `s` apart become data rows `floor(s/c)` or `ceil(s/c)` cells apart; when that is even, the middle cell is `ceil(s/c)·c/2 > s/2` from both and stays blank. Reproduced by the coordinator with `quantised_stripes.py` (kriging, defaults, straight lines at nominal offsets): 0.75 m @ 0.2 m cell → 20 of 26 gaps striped; 0.7 m @ 0.2 m → 14/28; 1.5 m @ 0.2 m → 6/12; 0.5 m @ 0.15 m → 13/39; 0.5 m @ 0.09 m → 22/39; 0.5 m and 1.0 m @ 0.2 m → 0. The 0.2.0 disc fill had none. The existing tests dodge it: the "lines" geometry and `test_the_limit_is_inclusive_so_the_midpoint_between_lines_fills` (test_slices_interpolate.py:93) put data rows a whole number of cells apart.

**Ruling.** Reach becomes `np.hypot(dy, dx) * cell <= max_distance_m + cell / 2 + DISTANCE_TOL_M`: a binned datum sits up to half a cell from its line, so distance to data is measured to the data cell's edge, not its centre. Keep the user's default (0.5 × spacing). Make sure the search radius used for the neighbourhood is never smaller than this reach (clamp inside `plan_fill` if needed), and that `max_distance_m == 0` still fills nothing (no offset satisfies `hypot·c <= c/2`). Name the half-cell allowance as a constant or a clearly commented expression citing (interpolation spec §5.2).

**Done means:**
- New core tests on binned geometry at defaults (use `CubeFrame.for_grid` + `cell_index` binning of straight lines as the probe does, or an equivalent populated mask built from line positions): 0.75 m lines @ 0.2 m cell and 0.5 m lines @ 0.15 m cell (and 0.7 m @ 0.2 m) have **no** blank row between the first and last line, for idw and kriging; a **skipped** line at 0.5 m @ 0.2 m still leaves a blank stripe; the existing wander test still stripes at 0.25 m and closes at 0.30 m (check, and adjust only if the arithmetic genuinely changed — say so).
- Existing tests whose oracle encodes the old rule (e.g. `test_cells_beyond_max_distance_are_blank_and_within_it_are_finite`, the one-line/single-cell disc test) updated to the new rule, not loosened: the oracle is `hypot·cell <= max + cell/2 + 1e-9`.
- `DISTANCE_TIP` (finish_panel.py:41) stays true: "Half a line spacing just closes the gap between neighbouring lines" — true again after the fix; check every word still is.
- The guide (docs/guide/getting-started.md ~:396) stays true likewise.
- The spec, docs/superpowers/specs/2026-11-02-nsgeo-slice-interpolation-design.md §5.2: add a short note recording the half-cell allowance, why (binning quantisation), and that it was a build-time call. The interpolate.py module docstring says the same.

## F2 [Important] plan_fill's transient memory ≈ 6× the estimate

**Finding.** `plan_peak.py` (wandering lines, kriging): 0.1 m on a 50 m grid peaks at 116 MB (466 B/cell); 0.05 m at 561 MB (561 B/cell), against `WEIGHT_BYTES_PER_CELL = 96` (slices_plan.py:169). At `MAX_FRAME_CELLS = 4M` that projects to ≈2.2 GB transient vs `DEFAULT_BUDGET_BYTES = 1.5 GB` while the estimate shows 384 MB — spec §7 says this must be warned about, not discovered as a crash. The cap's rationale (slices_plan.py:285-288, "the fill's FFT working set, ~64 B/cell") is now false. Main culprits: `rel` and its `np.where` copy as int64 (m, 12, 2) — 192 B/target each (interpolate.py:253-256) — plus the kriging `key`, `unique` and `out` stages.

**Ruling.** Chunk `plan_fill`'s per-target stages (after `_neighbourhoods`) and narrow offsets to int32 (or int16 where the search radius in cells allows) so the transient peak comes near `nbytes`. Re-measure with `plan_peak.py` (tracemalloc) at 0.1 m and 0.05 m on the 50 m grid and record before/after. If the measured peak per cell still exceeds 96 B by more than ~50%, raise `WEIGHT_BYTES_PER_CELL` to the measured peak per cell (rounded up) and update the pinned pure test and its rationale. Rewrite the `MAX_FRAME_CELLS` comment (slices_plan.py:285-288) to name what now dominates.

**Done means:** output bit-identical to before for every existing test (chunking must not change a weight); before/after peak numbers in the report; estimate and cap comment consistent with the measurement.

## F3 [Important] Rotated preview tick is 4–5× slower, unmeasured

**Finding.** `SliceLayer.update` (slice_layer.py:141) runs `to_north_up` and writes a GeoTIFF every tick, now at half pitch (4× pixels). `northup_cost.py` at 10.497°: 50 m @ 0.2 m 12.8 → 60.7 ms; @ 0.1 m 62 → 294 ms; 20 × 30 m @ 0.2 m 3.0 → 12.1 ms (file write extra). The user's real grids are rotated, and live depth scrubbing is the point of precomputed weights.

**Ruling.** The gather (which frame cell each north-up pixel reads) depends only on the frame (slice_export.py's docstring already says so). Precompute it once per frame and reuse it: e.g. a small cached helper in `nsgeo/slices/display.py` keyed on the frozen `CubeFrame` (functools.lru_cache with a small maxsize, or an explicit dict cleared sensibly), returning the flat source ids (−1 for outside), the output shape and the geotransform; `to_north_up(values, frame)` then becomes one `take` + mask. Keep its signature and output byte-identical. The export's per-band resample benefits too.

**Done means:** all display/export/layer tests unchanged and green; a test that the cached plan is reused (e.g. two calls on equal frames give identical output and the second does not recompute — monkeypatch-count the builder) and that a different frame gets its own; before/after `northup_cost.py` numbers in the report.

## F4 [Important] Whole-site finish edits lost 0.2.0's debounce

**Finding.** site_scope.py:697 `_on_finish_edited` calls `schedule_refresh()` at once (the tick has a 0 ms interval); 0.2.0's site radius went through `dock._debounce` (120 ms). Each keystroke or arrow repeat re-plans every grid's weights (max distance) and re-measures the 12-window shared stretch. This grid has `_finish_debounce`.

**Done means:** a single-shot timer with the same interval as `dock._debounce`/`_finish_debounce` sits between `site_finish.edited` and `schedule_refresh()` (remembering the value and `refresh_rows()` may stay immediate — say which you chose and why); its timeout slot guards its own body; a test that two quick edits cause one refresh; `test_no_orphan_signals.py` counts updated if a connect is added.

## F5 [Important] The plugin's site export wiring is unpinned

**Finding.** plugin.py:1042 passes `finish=dock.site_finish.value()`; the only plugin-level site export test, `test_export_routes_to_the_site_geotiff_in_site_scope` (test_plugin_site_scope.py:1236), runs at the default finish, so a `SliceFinish()` mutant passes. Twin of Task 4's Important 1.

**Done means:** a test that sets `site_finish` to a non-default finish the way a user would (e.g. IDW, max distance 1.5 × spacing, smoothing Y 0.3 m), exports through the plugin's site export, and asserts `NSGEO_SITE_INTERPOLATION`, `NSGEO_SITE_MAX_DISTANCE_SPACINGS`, `NSGEO_SITE_SMOOTH_X_M`, `NSGEO_SITE_SMOOTH_Y_M` and at least one band against an oracle independent of the plugin (e.g. `site.slice_at(..., finish=that SliceFinish, ...)` composed north-up as the site writer does). Confirm it fails on the `SliceFinish()` mutant **in a scratch copy only**.

## F6 [Important, partial] Weights discarded on z-only edits

**Finding.** `_rebuild_geometry` drops the weights even when the frame is unchanged (slices_engine.py:826), so every dz/z0/z1 edit repays the build (10.5 s at 0.05 m on a 50 m grid). The key + populated-mask check already make reuse safe.

**Ruling.** Keep the synchronous build (plan call 2). Stop `_rebuild_geometry` discarding the cached weights when the frame is unchanged; keep clearing in `set_source` and `clear`, and when the frame changes. (Moving the build into a QgsTask is a follow-up decision for the user, not this wave.)

**Done means:** a test that a z-only resolution change (e.g. dz) does not call `plan_fill` again (monkeypatch counter) while a cell change does, and the drawn slice still equals a fresh engine's.

## F7 [Minor, fix now] Guide

- getting-started.md:392 "IDW for a quicker fill" is false (IDW is no faster: plan 0.09 vs 0.08 s, apply 2.1 vs 1.8 ms at 0.2 m). A truer reason to pick IDW: it never goes beyond the values around it (kriging can overshoot slightly near strong contrasts). Rewrite that sentence.
- :396 (132 chars) and :404 (106 chars) are unwrapped; wrap them like the rest of the list.
- The wait-cursor sentence (~:405) names "a fine cell or a new method"; a new max distance also rebuilds the weights (z edits no longer will, after F6). Make it accurate.

## F8 [Minor, fix now] Wrong spec section numbers

interpolate.py:5 cites §5.1 for max distance (it is §5.2); :9, `IDW_POWER` (:42) and `_kriging_weights` (:182) cite §5.2 where §5.1 (methods) or §7 (weights once) is meant; `MemoryEstimate.weights_bytes` and the site tick's busy-cursor comment cite §8 for §7. Check every "(interpolation spec §…)" citation in the branch's changed files against the spec's headings and correct each.

## F9 [Minor, fix now] Stale text

slices_plan.py:285-288 (see F2); nsgeo/model/survey.py:130 ("fill radius" in the cube `view` description); plugin.py:998 ("radius"); the "#104's panel" test docstring (test_plugin_slices_dock.py:667 — #104 is the export cell bug).

## F10 [Minor, fix now] ValueError in _finish_moved

slices_dock.py:2021 `_finish_moved` catches RuntimeError and KeyError but not the ValueError `SliceFinish.in_metres` raises on a spacing ≤ 0 (only a hand-edited survey reaches it), so `rebuild_source` aborts its site follow-ups. Catch it there too.

## F11 [Minor, fix now] radius_m under None

**Ruling.** Under method "none", `view_settings()` writes `radius_m = 0.0` (0.2.0 then shows that cube unfilled, as this build does); otherwise `max_distance_spacings × spacing` as now. Pin it in the existing cube-save test.

## Not in this wave (follow-ups, to be filed as issues)

Smoothing cost growing with σ/cell (FFT path for long kernels) and the shared-stretch re-measure per smoothing edit; plan_fill's non-finite distance validation; smooth() input checks; SMOOTH_TRUNCATE_SIGMAS unpinned; display test gaps (azimuth 270, approx vs ==); `_non_negative` vs core `_finite` duplication; redundant `ok.any` clause; `_disc_offsets`' unused return; SiteEngine.weights_cached all-vs-any and busy-cursor tests; site cursor shown in coverage mode; a site test with grids of different spacings; the site export test split mid-body; status line counting weight bytes two ways; test hygiene in Task 4's tests. Leave these alone unless your edit rewrites those exact lines anyway.

## F1 REVISED by the user (2026-11-03) — this supersedes F1's ruling above

The user decided: "set spacing default back to 0.75". So F1 is: `DEFAULT_MAX_DISTANCE_SPACINGS = 0.75`, and NO half-cell allowance — the reach keeps the as-built inclusive rule `np.hypot(dy, dx) * cell <= max_distance_m + DISTANCE_TOL_M` (combining both would fill a skipped line at 0.5 m lines / 0.2 m cell). Done means: binned-geometry tests at 0.75 × spacing — 0.75 m @ 0.2 m, 0.7 m @ 0.2 m, 0.5 m @ 0.15 m, 1.5 m @ 0.2 m have no blank row between first and last line (idw, kriging); a skipped line at 0.5 m @ 0.2 m still leaves a blank stripe; a pin that 0.5 × spacing does stripe at 0.75 m @ 0.2 m; every test that pinned the old 0.5 default updated (tests passing 0.5 explicitly as a setting stay); `DISTANCE_TIP` replaced with exactly:
"Cells farther than this from any line are left blank, so the edge of the survey or a missing line is never filled in.\nThree quarters of a line spacing closes the gap between neighbouring lines, with room for a line that wandered; lower it toward half a spacing to fill less, or raise it if a line strayed and left a blank stripe."
— and the site tooltip expectation that reuses it; the guide's Max distance text matches; spec decision 12 reads "Max distance defaults to 0.75 × line spacing (user, 2026-11-03; reverses 0.5 after binning quantisation striped nominal gaps)" and §5.2's reasoning is the quantisation one, with no half-cell note; the plan's Global Constraints "Default max distance" row reads 0.75 (user, 2026-11-03).
