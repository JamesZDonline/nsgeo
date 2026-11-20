# Task 6 report

## What changed
- `P/fill_jobs.py`: new `FootprintJob` (captures grid id, frame, lattice, transform-context copy; `run` calls `site_geometry.gather_footprint`; `land` -> `SiteEngine._land_footprint`, lets go when refused). `FillJob` gains `warm_north_up` (run warms the plan after the fill).
- `P/site_engine.py`: `footprints_missing(lattice)`, `footprint_jobs()` (context copy made on the GUI thread), `_land_footprint(job)` (refuses disposed / other lattice / grid no longer ready / frame moved). `_gather` now calls `site_geometry.gather_footprint` through the module (test seam).
- `P/ui/fill_flow.py`: FootprintJobs join the fill list (after fills, before the stretch/on_done); `_fill_count` so "grid n of total" counts the FillJobs only; footprints run silently on the last grid's line (footprint-only requests count themselves).
- `P/ui/site_scope.py`: `_fills_ready` also asks `footprints_missing`; `_fill_jobs` appends `footprint_jobs()`; new `_footprints_ready` routes a coverage draw (no fills needed) with missing footprints through the flow (key `(lattice, "footprints")`). Key semantics unchanged (never depends on window).
- `P/ui/slices_dock.py` `_fill_jobs`: sets `fill.warm_north_up = True` (This grid only; site grids do not use the plan).
- Core `display.py`: public `warm_north_up_plan(frame)`, exported from `nsgeo.slices`, listed in core README (public-API test requires it; the plugin boundary test requires the named API).

## Thread safety
Job `run` uses only the captured immutable frame/lattice and the QgsCoordinateTransformContext copy (value type; transforms are built inside `extent_in`, not QObjects). Landing and the engine's `_gathers` dict are touched on the GUI thread only. The north-up LRU is lock-guarded. A refused fill landing leaves the warmed plan as an extra LRU entry (acceptable).

## Fail-first
- `test_a_site_landing_builds_no_footprint_on_the_gui_thread`: failed with "a footprint was built on the GUI thread: [('MainThread', True) x3]".
- `test_a_footprint_for_a_stale_lattice_never_lands`: failed with AttributeError: SiteEngine has no `_land_footprint` (the seam did not exist; it asserts the worker ran, the first lattice never lands True, final gathers cover all grids).
- `test_this_grids_first_north_up_plan_is_built_on_the_worker`: failed with builds `[(0.03, 'MainThread')]`.

## Existing test changed
`test_a_slider_move_mid_fill_never_restarts_the_grid_in_flight` pinned `len(flow._fills) == 3`; now 3 FillJobs + 3 FootprintJobs = 6.

## Results
fill_flow+fill_jobs 67 passed; site_scope 177; site_engine 68; slices_dock 236 (these four before the last import tweak, fill_flow/fill_jobs rerun after); pure 396 passed; core 1685 passed after README fix (public-api rerun 17 passed); QGIS real_data 46 passed (core/pure real_data marker selects nothing); ruff check/format clean; CI mypy clean.

## Concerns
- The per-tick draw cost is untouched (out of scope).
- Coverage-mode first draw is routed through the flow too (not in the brief).

## Fix round 1
1. `SiteScope._footprints_ready` returns False while the flow is working (the running request ends with these footprints and `on_done` redraws), so a coverage tick never cancels a running list. Test `test_ticking_coverage_mid_fill_never_restarts_the_work` (the probe): failed first with "the coverage tick restarted the work" (`[] == [6 job ids]`) with the guard removed, passes with it.
2. Direct tests in test_plugin_site_engine.py: `footprints_missing` order/filter, lands when unmoved, refused for another lattice / grid no longer ready / moved frame / disposed engine (each: False, `job.footprint is None`, nothing in `_gathers`). Mutant `if self._disposed or job.footprint is None:` (detached scratch worktree, removed afterwards): 3 failed (lattice, not-ready, frame), 3 passed (the disposed case stays covered by the kept condition).
3. `warm_north_up_plan(frame, should_stop=None)`: builds outside the lock, re-checks `should_stop()` after the build and inserts nothing when stopped; `FillJob.run` passes its `should_stop`. Core test `test_a_stopped_warm_inserts_no_plan_and_a_warm_one_is_kept`. Comment corrected: a fill refused at landing still leaves its plan in an LRU slot until the next frame replaces it.
4. The lazy `warm_north_up_plan` import in `FillJob.run` moved to the module top.
Results: fill_flow 54, site_engine 74, site_scope 177, slices_dock 236, fill_jobs 14 passed; pure + core display/public-api 448 passed; ruff and CI mypy clean.

## Fix round 2
The lattice test now replaces only `site._lattice` (pixel doubled; frames asserted equal, readiness untouched); the not-ready test sets only `site._states["C"] = "preparing"` (lattice and frame asserted unchanged). Mutants in detached scratch worktrees (removed): deleting only the lattice check fails only `test_a_footprint_for_another_lattice_is_refused` (1 failed, 5 passed); deleting only the ready check fails only `test_a_footprint_for_a_grid_no_longer_ready_is_refused` (1 failed, 5 passed). site_engine 74 passed; ruff and CI mypy clean.
