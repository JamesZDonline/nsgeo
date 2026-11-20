# Plan B final fix wave (#193): I1, M1-M4, D1-D4

Commit: the `fix(site): every ready grid's fill when the shared stretch needs it; one slice per tick; the flow lets go of landed fills (#193)` commit (single). Not pushed.

## Items
- **I1** `SiteEngine`: `_fill_targets`, `fills_missing`/`fill_jobs` take `every_grid` (every ready grid with an axis; a grid outside the shown window gets its coverage from its slice at the first stretch window that reaches it, `_coverage_for`). `SiteScope._fill_jobs` uses `every_grid=_shared_stretch_wanted()`; `display_limit` starts a fill request (`_request_fills`, stretch after it) when `weights_cached(finish)` is False instead of doing nothing. Tests (`_open_short_c`): `test_a_grid_above_the_shown_depth_gets_its_fill_and_the_stretch_follows` (C holds its fill after a cell edit made below its end; a thickness edit lands a stretch equal to the synchronous `stretch_limit`), `test_the_rest_builds_nothing_on_the_gui_thread_for_a_grid_above_the_depth` (records `threading.current_thread()` in `build_fill`: builds on the worker, none on main). Fail first on 661eeb8: `AssertionError: C has its fill for the new cell`; `AssertionError: a plan was built on the GUI thread`.
- **M1** `SiteEngine.sliced()` and `sliced=` on `fills_missing`/`fill_jobs`/`slice_at`; `refresh_slice` slices once. `test_a_site_tick_slices_each_grid_once`; fail first `AssertionError: [1, 1, 1, 1, 1, 1]` (6 slices, 3 grids).
- **M2** `FillFlow` drops `_fills` when the last fill lands (`_total` kept for the line). `test_the_flow_lets_go_of_landed_fills`; fail first `landed jobs (and the fills they hold) are kept`.
- **M3** `GAP_LIMIT_S = 0.3` (spec "about 250 ms"; the edit's own 0.2 s `settle` is seen by the gap timer, 0.203 s measured, so 100 ms of slack instead of 47). `MIN_SLOW_S` stays 1.0 s: 3.3 times the new limit, with `SLOW_CELL` 3.2 s here and about 1.5 s at CI's 0.47x; the settle window is deliberately NOT excluded, since the site's tick runs from the event loop and an inline fill there is what the test must still catch. Docstrings updated.
- **M4** Cancel tooltip: "Stop working out this fill. With a picture on screen its settings come back; without one nothing is drawn until you change the cell or the interpolation." `test_the_cancel_link_tooltip_fits_a_cancel_with_and_without_a_picture`; fail first on the old text.
- **D1** `_fill_jobs` omits the stretch job when `refine.stretch` is held for the current key. `test_a_held_stretch_is_not_replaced_when_only_a_fill_is_missing`; fail first `a current stretch was measured again`.
- **D2** the redundant `flow.working or` removed from both `display_limit`s. `test_a_stretch_request_never_cancels_the_fill_work` no longer asserted that `display_limit` asked while a fill ran; it now makes a `request_stretch` itself while the fill runs (its factory fails the test if called) and checks any asked-while-working call was refused and the fill still lands.
- **D3** `_assert_slow` and module docstrings carry the current constants (0.3 s limit, 0.47-0.65x).
- **D4** core `_reach`/`reach_mask` take `progress` (every 32 offsets, never 1.0), used by `plan_fill` (0 to 0.1) and `plan_curvature`; no arithmetic changed (`test_a_plan_with_stop_and_progress_is_bit_identical` and the plans compared with `_same_plan`). `test_the_reach_reports_progress_inside_its_tenth` (3 methods); fail first `assert 0 >= 2` against the old core.
- Also changed by the new behaviour: `test_a_grid_that_comes_into_range_gets_its_fill_on_the_next_request` now selects "this slice" first (with a shared stretch the grid outside the window is filled too, leaving nothing for a move into range).

## Verification
- `qgis_tests.sh test_plugin_fill_flow.py test_plugin_site_scope.py test_plugin_site_engine.py test_plugin_slices_dock.py test_plugin_stretch_jobs.py test_plugin_fill_jobs.py test_plugin_cut_sections.py` -> `2 failed, 596 passed in 664.64s` (the two above, adapted); `test_plugin_fill_flow.py` rerun -> `49 passed in 111.66s`. test_plugin_site_scope.py's tests were all in the 596.
- core `pytest packages/nsgeo-core/tests` -> `1686 passed, 5 skipped, 19 xfailed in 331.37s`; interpolate + curvature after the last edit -> `131 passed`.
- pure `396 passed, 4 skipped`; `-m real_data` (QGIS) `46 passed, 2948 deselected in 54.78s`; ruff check and format clean; CI mypy `no issues in 66 source files`.
- No tiny-budget rerun of the whole site_scope file this wave (the site_scope tests were unchanged and the new code path only adds jobs for grids outside the window); not re-proved.

## Residual R1
Commit: the `fix(site): the rest never builds a fill the flow is still working out (#193)` commit. Not pushed.

`SiteScope._on_rest` asks for `stretch_solves` only when `not dock.fill_flow.working` and `engine.weights_cached(finish)` (every grid, no `at`); the landing redraw or the provisional stretch landing arms the rest again, so nothing is lost. The stale "0.25 s" in the site-cell comment now reads 0.3 s.

Test `test_a_slider_move_mid_fill_never_makes_the_rest_build_the_grid_still_filling` (`_open_short_c`, minimum curvature, slider below C's end; cell edit to SITE_SLOW_CELL; after A and B landed with C still filling, a slider move and a rest that runs out): no `build_fill` on the main thread, C's job lands installed (`("C", True)` in the lands, never `("C", False)`), and C holds its fill. Fail first on 0ae9323: `AssertionError: the rest built a plan on the GUI thread`. Passes after: `1 passed, 49 deselected in 15.06s`.

Verification: `qgis_tests.sh test_plugin_fill_flow.py test_plugin_site_scope.py` -> `227 passed in 682.38s`; ruff check and format clean; CI mypy `no issues in 66 source files`. Scratch worktree removed; no background job left.
