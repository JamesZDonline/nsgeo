# Task 4 report: FillFlow, and This grid never freezes (#193)

Status: DONE_WITH_CONCERNS. Commit: ef46f7d (one commit, not pushed).

## What changed
- `P/ui/fill_flow.py` (new): `FillFlow(parent, worker, *, on_done, on_stretch, on_cancelled, on_tick=None, on_error=None)`; `request`, `request_stretch`, `cancel`, `stop`, `working`, `stretching`, `latched`/`latch`/`unlatch`, `progress_text`.
- `P/slices_plan.py`: `FILL_WORKING_INDICATOR`, `FILL_WORKING_GRIDS_INDICATOR`, `STRETCH_WORKING_INDICATOR`, `FILL_CANCEL_LINK`, `FILL_CANCELLED_NOTE` (copy as in Global Constraints).
- `P/session.py`: `restore_slice_resolution(grid_id, record|None)` (exact replace; None removes the `resolution` key, and drops the grid's entry if that leaves it empty; marks dirty, emits `slice_sources_changed`; no-op when unchanged), `restore_site_resolution(record|None)` (same; the site emits nothing, as `remember_site_resolution`).
- `P/ui/site_scope.py`: Protocol gains `fill_worker` and `fill_flow`.
- `P/plugin.py:unload`: `fill_flow.stop()` before `fill_worker.shutdown()`.
- `P/ui/slices_dock.py`:
  - `__init__`: `fill_flow`, `_picture`, `_shown_frame`, `_limit_shown`, `_fill_note`, `_latched_grid`; `cancel_link` QLabel (`<a href="cancel">Cancel</a>`, hidden, vertical size policy Ignored so the row stays one line high) after `refine_label` on `readout_row`.
  - `refresh_slice`: `_finished(...)` may return None (the map keeps its picture; `show_refine()`; no `slice_changed`, `_values`, `_window`, `_drawn_finish` change). The unprepared and error branches also `_stop_fill_work()` (cancels, keeps a latch).
  - `_finished(values, coverage, finish, window)`: if `not fill_held`: latched -> None; `before_draw(rebuilds=True)`; `flow.request(fill_key, factory, stretch_key=_stretch_key(window, finish))`; False -> None. Records `_picture = (grid, cell, finish, slice_resolution copy)` at each completed draw.
  - `display_limit`: `held_stretch(key)`, else `request_stretch(key, factory)` (only if working or `weights_cached`), returns `_limit_shown` (the limit the layer has) or, with none, `limit_over_slices` of the shown slice.
  - `current_frame()` returns the frame the picture was drawn at (`_shown_frame`), so the plugin never pairs an old array with a new frame while a fill runs.
  - `show_refine`: fill working line first, then the refine indicator, then the stretch wording; Cancel link visible only while `working` (not while stretching) and only in This grid.
  - Handlers: `_on_fill_done` (draws via `refresh_slice`), `_on_stretch_landed` (stores only if its key is still `_stretch_key(window, finish)`, then legend + `slice_changed`), `_on_fill_error`, `_on_cancel_link`, `_on_fill_cancelled`, `_take_back`.
  - Unlatch: user edits of cell (`_on_resolution_edited`) and method / max distance (`_on_finish_edited`), `set_scope` (also `flow.stop()`), a new survey in `rebuild_source` (also drops picture and `_limit_shown`), and a latch for another grid is dropped at the next draw.
  - `show_warnings` adds the NOTE while `_fill_note`.

## How FillFlow avoids re-entering the draw (hazard 1)
`request` sets `_requesting` around `start` + `settle(FILL_BUDGET_S)`. `Refiner.settle` delivers landings synchronously, so `_fill_landed` runs inside; it counts the landing, and when `_requesting` it neither draws nor calls `on_done`. `request` then returns True ("draw now") and starts the stretch. `on_done` runs only from the worker's own poll timer. Pinned by `test_a_landing_inside_the_wait_never_draws_inside_the_callers_frame` and `test_a_quick_fill_draws_in_the_same_tick` (exactly one `slice_changed`, flow never working).
Design note: the fills and the stretch run as two lists on the worker (stretch starts after the last fill lands, from `request` or from the poll path before `on_done`). One list would make `settle` wait on the stretch too, so a quick fill with a slow stretch would miss the budget and not draw in the same tick.

## Cancel: what is restored, and how remembering is suppressed
With a picture (`_values` not None, same grid, picture's `(cell, finish)` differs from the spins' now): `_take_back` stops both debounce timers, `session.restore_slice_resolution(grid, record or None)` (the record copied at the picture's draw, so key presence returns), sets `cell_spin` with `blockSignals` and `grid_finish.set_value` (quiet) inside `_seeding += 1` (so `_on_resolution_edited` / `_on_finish_edited` remember nothing), refreshes the metres label and included label, then `_apply_resolution()` (re-sets the engine's frame to the old cell and redraws; can show the working line again). Not restored: the cube combo ("(unsaved)") and the dirty flag.

## Latch rules as built
- Cancel with no picture, or with settings already equal to the picture's (second cancel after going back to a slow picture): settings and record stay, `_fill_note` + `latch()`, NOTE shown. While latched `_finished` starts nothing and draws nothing (also `request` refuses). Slider moves and `_on_prepared` therefore do nothing.
- Unlatch (and NOTE removed): user cell edit, method edit, max distance edit; `set_scope`; survey change in `rebuild_source`; a draw on another grid than the latched one.
- Smoothing or dz/z edits do not unlatch (not fill settings).

## Calibration of the slow fixture
`build_fill` alone (not `finish`): cell 0.02 took 1.17 s here (an earlier `engine.finish` timing of 2.1 s included applying the fill, which misled). Fixture uses `SLOW_CELL = 0.017` (about 1.9-2.2x of 0.02 by the ~cell^-4 scaling; measured at the fixture assert, it passes >= 1.5 s here; CI-class target 2 s). `_assert_slow` asserts `build_fill` takes >= 1.5 s on the fixture's own mask, once per run. `MID_CELL = 0.025` (~0.45 s) is the "working but cancellable" cell.

## Tests, with fail-first evidence
Written first and run on the old dock (module `fill_flow` existed only after, dock tests ran against the unchanged dock):
- `test_this_grid_never_blocks_the_gui_during_a_slow_fill`: `AssertionError: the GUI thread stood still for 2.11 s` (test_plugin_fill_flow.py:167).
- `test_a_quick_fill_draws_in_the_same_tick`: `AssertionError: the flow was never working` (:188; the module/attr were missing).
- `test_cancel_with_a_picture_puts_everything_back`, `test_cancel_with_no_picture_latches_until_a_fill_setting_changes`, `test_cancel_again_after_going_back_to_a_slow_picture_latches`, `test_a_stale_fill_never_lands`, `test_a_stretch_request_never_cancels_the_fill_work`: failed at their first `dock.fill_flow` wait (`assert False` at :202/:228/:260/:286, or `AttributeError: 'SlicesDock' object has no attribute 'fill_flow'`).
- `test_the_stretch_lands_after_the_picture_and_redraws`: `AssertionError: the first draw uses the previous limit` (:308; the old dock measured synchronously).
- `test_unloading_while_a_fill_runs_lands_nothing`: `AttributeError ... 'fill_flow'` (:369).
- Flow-only tests (8, plus the layout test) and 3 session tests are new code against new code; they passed on first sensible run after fixing my own test errors (a missing `answer_modal`, `stretch_limit` returns a tuple, a stretch-wording assertion).
- `test_the_cancel_link_keeps_the_readout_row_one_line_high[narrow|wide]`: new, passes.

## Existing tests changed, and why (no assertion weakened)
- All dock fixtures/sites that shut down `refiner`: now also `fill_worker.shutdown()` (test_plugin_slices_dock.py x2, test_plugin_cut_sections.py, test_plugin_map_link_cuts.py, test_plugin_paraview_export.py x3, test_plugin_slices_width.py, test_plugin_site_scope.py).
- `test_plugin_slices_dock.py`: `_docked_with(..., record=None)` seeds a remembered resolution before the dock exists; new helper `_limit(dock)` (asks, waits for the flow to idle, reads); used in `test_the_shared_stretch_follows_a_finish_change`, `test_a_shared_stretch_holds_one_limit_across_depth_and_per_slice_does_not`, `test_the_shared_stretch_is_provisional_until_its_windows_are_solved` because the shared limit is now measured on the worker; `test_the_refine_states_do_not_move_the_panel_under_the_wheel` loop also waits while `fill_flow.stretching`.
- `test_plugin_site_scope.py`: `test_entering_the_site_cancels_this_grids_refine` waits (`_pump_until(lambda: dock.provisional)`) for the preview, since the plan's fill is now background; `test_editing_a_grid_in_site_scope_never_overlaps_preparations` final draw check uses `spin_until` (a fill over the 0.2 s budget draws from the poll; it failed once under load, passed alone).
- `test_plugin_cut_sections.py::test_whole_site_reads_the_grids_site_engine_without_the_gain`: PRE-EXISTING failure from Task 3 (it patched `site_engine.normalise`, which moved to `stretch_jobs`); now patches `stretch_jobs.normalise`. Not caused by this task.

## Final counts
- QGIS: fill_flow + slices_dock + refine_flow + fill_jobs + stretch_jobs + slices_engine + session + cut_sections + slices_width + map_link_cuts: 598 passed (one failure, the cut_sections one above, fixed afterwards); last rerun of fill_flow + slices_dock + slices_width + cut_sections + session: 454 passed.
- test_plugin_site_scope.py whole: 175 passed, 2 failed, both then fixed/rerun green (see above).
- `-m real_data` (QGIS tier): 46 passed. Pure: 396 passed, 4 skipped. ruff check + format --check clean; CI's mypy command: no issues in 66 files. Core untouched, not rerun. test_plugin_paraview_export.py and test_plugin_map_link_cuts.py: only the shutdown line changed, map_link_cuts ran in the batch, paraview_export did not.

## Deviations from the brief
- `FillFlow` takes two extra optional keywords, `on_tick` (the show_refine poll) and `on_error`.
- `request` / `request_stretch` accept a factory (callable) as well as the jobs, built only when the work will start. Required because `engine.fill_job()` drops the held fill and bumps the epoch, which would invalidate the very job running if called for a same-key request. The dock always passes factories.
- Fill and stretch run as two lists (see above); the stretch is optional in `request` (absent under "this slice", own colours, coverage).
- Identity for "same fill key" is the brief's `engine.fill_key(finish)` only. A source change with the same frame and settings during a fill makes the running job land refused; the flow still calls `on_done`, the redraw finds no held fill and starts a new request, so it self-heals.
- Site progress text counts the grid being filled (`n = landed + 1`, capped at total); Task 5 may change it.
- Stretch wording shows only when no fill line or refine indicator is up (the existing indicator tests describe the refine states and kept their order).

## Concerns
- Every `display_limit` miss (thickness, finish, cell, transform changes) is now asynchronous: the legend and layer keep the last limit until the stretch lands, then `slice_changed` re-emits (layer file rewritten again). That is the brief's design; users will see one extra redraw per such edit.
- `test_plugin_site_scope.py` timing tests under load: `never_overlaps_preparations` failed once whole-file (an async draw it did not wait for, now waited) and passed alone; the remaining known flakes (#196 etc.) did not appear.
- Whole site is not wired yet (Task 5); `show_refine` hides the Cancel link there.
- Hazard 2 handled in `FillFlow._stretch_landed` (limit None is dropped) and in the dock (`_on_stretch_landed` checks the key is current before `land_stretch`/re-render). Hazard 1 and the test-fixture hazard 3 are done as above.
- The `quick`/`slow` fixtures take ~0.5 s each plus one-time calibration (~2 s); the file runs in about 55 s.

## Fix round 1

New `P/ui/fill_picture.py` (`FillPicture`, `FILL_FIELDS`) owns the picture, the take-back and the one latch (it drives `FillFlow.latch/unlatch`; `FillFlow.stop(keep_latch=False)` replaces the re-latching helper). The dock only wires callbacks (`_fill_record`, `_restore_fill_record`, `_set_fill_widgets`, `_apply_resolution`, `show_warnings`); Task 5 reuses it with `site_resolution` / `restore_site_resolution`.

Fail-first: the new tests were copied into a detached scratch worktree at ef46f7d (since removed): 9 failed there (e.g. `assert 'kriging' == 'min_curvature'`, `assert 1115800057937.92 == 1099329902346.24`, `a fill started by the apply must not run on`, `'FillFlow' object has no attribute 'drop_stretch'`). All 28 tests in test_plugin_fill_flow.py pass on the fix.

1. Preview picture: `_record_picture(finish)` runs where any drawn array is accepted in `refresh_slice` (preview or full). Tests: `test_cancel_goes_back_to_a_preview_that_is_on_the_map`, `test_cancel_with_only_a_preview_since_opening_does_not_latch`.
2. Stale stretch: `FillFlow.drop_stretch()` (cancels a running stretch, clears a waiting one); the dock's `_drop_stretch()` replaces the three `_grid_refine.stretch = None` sites (`_apply_resolution`, both in `_on_prepared`). Tests: `test_a_z_edit_mid_stretch_never_lands_a_stale_stretch` (landed limit equals a fresh synchronous `stretch_limit`), `test_dropping_the_stretch_cancels_a_running_and_a_waiting_one`.
3. Fill fields only: the picture keeps `cell`, `method`, `max_distance_spacings` as drawn plus which of them the record held; take-back removes those three from the CURRENT record, re-adds the held ones, and sets only those widgets (z, smoothing untouched). Test: `test_cancel_puts_back_only_the_fill_settings` (z0 and smoothing survive in panel, engine and record).
4. Picture records the frame's cell and the finish drawn (`_record_picture`), not the spins.
5. `set_scope` stops the flow and unlatches after applying a pending change. Test: `test_a_scope_switch_applies_a_pending_change_before_it_stops_the_work`.
6. `_clear_shown()` resets `_shown_frame`, `_limit_shown` and the picture wherever the map is cleared. Test: `test_clearing_the_map_forgets_the_limit_and_the_picture`.
7. Moved as above; `_picture`, `_fill_note`, `_latched_grid`, `_unlatch`, `_take_back` are gone from the dock.
8. `on_error(what, message)`: "could not work out the colour stretch: ..." Test: `test_a_failed_stretch_is_named_as_the_stretch`.
9. Every `dockN.engine.dispose()` teardown in tests/qgis now also shuts down `refiner` and `fill_worker` (23 sites in test_plugin_slices_dock.py, plus the earlier ones).
10. `_assert_slow` asserts SLOW_CELL build >= 1.5 s (comment says why) and MID_CELL >= 2 x FILL_BUDGET_S.
11. `test_closing_the_survey_while_a_fill_runs_lands_nothing` (no `_land_fill`, no slow-cell picture, not working). The unload test now checks this dock's own worker threads (a global thread-name check flaked once).
12. `display_limit` docstring updated (`RefineFlow.landed`, worker measurement); the quick-fill message reads "the flow was working, but a quick fill must not be".

Verification: fill_flow + slices_dock + refine_flow + fill_jobs + stretch_jobs + session + cut_sections + paraview_export + slices_width + map_link_cuts + slices_engine: `656 passed in 217.05s`; test_plugin_site_scope.py: `177 passed in 473.56s` on a clean run (an earlier run with pure tests/mypy running beside it had 4 load failures, all async-draw timing after a scope switch with 657 ms redraws, all passing alone and in the clean rerun); pure `396 passed, 4 skipped`; `-m real_data` below; ruff and the CI mypy command clean. No mutant checks were run beyond the scratch fail-first worktree.

## Fix round 2

13. Site-scope tests wait for the background draw. `test_plugin_site_scope.py` gains `drawn(dock)` (waits for `not fill_flow.working`); `_open` calls it after the first apply, and it follows the switch or preparation in `test_whole_site_draws_one_layer_covering_every_grid`, `test_this_grid_names_the_memory_the_site_view_still_holds`, `test_both_scopes_legends_name_the_transform_by_title`, and the two fell-back-grid tests (the "after a preparation" case). Proof, in a detached scratch worktree only (removed, never committed): `FILL_BUDGET_S` forced to 0.0001 s (stricter than 0.05; every fill goes to the worker). Before the fix, 16 site-scope tests failed there (the four above, the two fell-back tests, and ten own-colours / layer tests that need the layer after open). After: `177 passed in 476.12s`.
14. In site scope `_on_prepared` clears only `_grid_refine.stretch` (no `drop_stretch`), so a This-grid preparation never cancels the site's stretch on the shared flow. Test `test_a_this_grid_preparation_under_the_site_never_cancels_the_sites_stretch`: failed on the old code (`AssertionError: the site's stretch was cancelled`), passes now.
15. One latch path: `FillFlow.stop()` no longer touches the latch (`keep_latch` is gone); `FillPicture.latch/unlatch` (via `cancelled`/`unlatch`) is the only owner. Dock callers that must unlatch pair `stop()` with `fill_picture.unlatch()` (set_scope, new survey); `_stop_fill_work` is now a plain stop. Test `test_stop_never_touches_the_latch` (failed on the old code with `assert False`).

Verification at the normal budget: `pytest fill_flow slices_dock refine_flow site_scope`: `453 passed in 573.60s (0:09:33)`; ruff check and format clean; the CI mypy command: no issues.
