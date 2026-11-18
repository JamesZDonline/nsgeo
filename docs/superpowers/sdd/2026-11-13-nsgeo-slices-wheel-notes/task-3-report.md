# Task 3 report: dz floor and level limit (#177)

Implemented: slices_plan (LEVELS_PER_SAMPLE, TooManyLevels, level_limit_problem); SliceEngine.set_resolution refuses before storing, _rebuild_geometry leaves frame/z None past the limit (no raise); SiteEngine per-grid re-raise as "Grid X: ..."; site_scope Spins.dz_min, set_dz_floor (no-op when minimum already equals the rounded floor, so a half-typed value survives ticks), site_dt_floor, seed_z sets floor; dock _seed_dz_z_defaults and restore_cube set the floor; _apply_resolution catches TooManyLevels into _grid_refusal + show_warnings (no toast).
Note: dz_spin has 4 decimals so setMinimum rounds 0.21653 to 0.2165; set_dz_floor compares against round(floor, decimals).

RED: with only slices_plan.py's additions applied, the 14 new QGIS tests give 12 failed, 2 passed (the clipped-in-Whole-site test and one pure-ish pin pass by design); with no source changes the test modules fail on import (level_limit_problem / TooManyLevels missing) and the pure file too.
GREEN: pure tier 305 passed 1 skipped; test_plugin_slices_engine 76, slices_dock 195, site_scope 170, site_engine 58, slice_export 77 passed. ruff check/format clean.
Mixed radars test rewrites B's DZT files to 1,024 rows over 110.864 ns and, for first=B, sorts site.grids; asserts included()[0] == first.
Concern: SiteEngine loop raises on the first over-limit grid, leaving later grids at their previous resolution (per brief).

## Fix round 1

Changes: Important 1 - Whole site floor and arrow step at the FINEST included interval, seeded dz (header_z_seed and ready_dt) from the COARSEST; shared `first_headers` helper behind header_z_seed and site_dt_floor. Mixed-radar test now has B at 512 samples over 25 ns (4.4x finer), both orders, asserting problem None, floor/step ~B, seeded dz ~A; new test_a_dz_the_coarse_grid_cannot_take_is_not_drawn_and_is_not_a_toast (one REFUSAL "Not drawn: Grid A: Too many levels", no toast).
Important 2 - travel and saved-cube tests moved to new fixture docked_fine_b (grid B 0.0488 ns). Mutation checks (each run on its own, then restored): removing set_dz_floor from restore_spins -> test_the_dz_floor_travels_with_the_scope FAILS; no-op'ing restore_cube's floor -> test_a_saved_cube_with_dz_below_the_floor_restores_at_the_floor FAILS; reverting to first/headers[0] dt -> mixing_radars[B] FAILS.
Important 3 - _level_problem logs via _log before returning None.
(a) restore_cube floor from self._included[0] after the fallback (KeyError suppressed). (b) _grid_refusal cleared before set_resolution. (c) set_dz_floor comment corrected.
Results: pure 305 passed 1 skipped; slices_engine 76, site_engine 58, slices_dock 195, site_scope 171 passed; ruff clean. One run of slices_dock showed test_a_refine_for_a_window_left_behind_never_draws failing under load while other test processes ran; it passed alone 3x and the whole file passed on re-run (looks like a timing flake, unrelated).

## Fix round 2

Changes: (1) restore_cube takes the floor from the first key of _included still in the session. (2) seed_z seeds dz from the coarsest included first header always (first_headers), ready or not; ready_dt removed (its one test now uses a header-based helper); header_z_seed now returns (z0, z1) only. The mixed-radar test asserts the coarsest dz right after entering Whole site, before settle. (3) _apply_resolution's generic except calls show_warnings() before the toast. (4) New tests: test_a_cube_record_without_usable_first_line_still_sets_its_grids_floor[none|stale_first] and test_a_failed_apply_clears_the_refusal_the_last_one_left.
Mutations (each restored): first-key-only floor -> [stale_first] FAILS; floor block disabled -> both [none] and [stale_first] FAIL; show_warnings removed from the except -> failed_apply FAILS; seed_z dz reverted to the first header -> mixing_radars[B] FAILS.
Results: pure 305 passed 1 skipped; site_engine 58, slices_engine 76, slices_dock 198, site_scope 171 passed. Ruff: <repo>/.venv/bin/ruff 0.16.7 (check and format clean); .venv-qgis has no ruff.
