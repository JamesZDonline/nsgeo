# Task 2 report: This grid opens the grid selected in the site list (#70, #75 F-9)

Commit 7735174 "Slices: This grid opens the grid selected in the site list (#70)", pushed.

## Implemented (slices_dock.py)
- `_resume_grid` wrapped in try/finally; finally calls `_run_pending_grid_prepare()` (F-9).
- `_grid_to_resume()`: panel's selected grid if offered by grid_combo and different from current, else None.
- `_switch_resumed_grid(grid_id)`: clears `_pending_palette`, selects the grid under `_updating`, `_mark_cube_unsaved`, `_sync_included`, `_update_included_label`, `_refresh_source_status`, `_grid_prepared_away=False`, `_grid_prepare_pending=True`. No `_remember_source`, no `prepare()`.
- Target path skips spin/palette restore, `_follow_record_changed_in_site`, and the `_on_prepared`/`refresh_slice` branch (the engine still holds the left grid's data until B's preparation lands). Preparation runs from the finally via `_run_pending_grid_prepare`, so R-P5 holds.

## TDD
RED: `... pytest test_plugin_site_scope.py -k "selected or resume"` -> 4 failed, 4 passed. Failing: opens-selected-grid, remembered-source, waits-for-site-task, F-9 (`assert _mark_grid_stale is None`). Passing before the change, as the brief allowed: "as it was left" and "removed meanwhile".
GREEN: same command after the change -> 8 passed (after two test fixes below).
Full files: test_plugin_site_scope.py 46 passed; test_plugin_slices_dock.py 79 passed. Core+pure: 808 passed, 3 skipped. ruff check and format clean. Full qgis suite not run (single files only). mypy not run (the command does not cover these files).

## Test adaptations
- `remove_grid(grid_id, *, with_lines=False)` matches the brief.
- Removal test: removing C makes the panel rebuild and move its selection to B, so the real flow opens B, not A. I kept the real removal and monkeypatched `site_panel.selected_grid` to return the stale "C", so the `findText` guard is what is tested. Expect A and no error.
- Wait test: `is_prepared` was already true from A, so it waits for `is_prepared and choice.grid_id == "B"`. The has_live_task and not is_running asserts are as in the brief.

## Files
- packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py
- packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py

## Self-review
- No `engine.set_source` call and no `prepare()` outside the pending path.
- `_remember_source` is not called, so the survey is not dirtied (asserted).

## Concerns
- The panel's rebuild after removing the selected grid moves the selection to a neighbour. This is a panel behaviour, so This grid then opens that neighbour rather than A. The brief's "falls back to A" holds only for a stale name, which the guard handles.
- Between the switch and B's preparation landing, the engine and slice layer still show the left grid's data.

# Fix round 1

Commit: "Slices: carry the window time onto the opened grid's axis (#70)".

## Finding 1 (Ruling 6)
Cause: `engine.set_source` does not clear `engine.z`, so the engine kept the left grid's axis after the switch. `_sync_grid_slider` clamped the time to A's range and consumed it.
Fix:
- The target path no longer calls `_sync_grid_slider`. `_pending_top_ns` stays set.
- `_apply_resolution` prefers `_pending_top_ns` over the slider-derived time.
- New `_resolution_owed` flag, set by `_switch_resumed_grid`. `_run_pending_grid_prepare` applies the spins' resolution after `prepare()` when it is set, then runs `_sync_grid_slider`.
- The no-target path is unchanged.
RED: both new time tests failed with top 31.5665 against a site time of 78.98 (the reviewer's probe values). They now pass. The outlived-cancel variant asserts `has_live_task` and `max_concurrent == 1`.
Minor 2: closed. B's preparation now always applies the spins' resolution through `_resolution_owed`, whether or not `valueChanged` fired. The first new test asserts the engine z equals `ZAxis.from_range` of the spins.

## Finding 2 (Ruling 7)
Panel untouched. Three tests, no monkeypatching in the first two:
- Removing the selected last grid (C): the panel shows B selected, and This grid opens B.
- Removing a selected middle grid (B): selection is empty, and This grid stays on A.
- The monkeypatched test is renamed `test_a_selection_naming_a_grid_this_grid_does_not_offer_is_ignored`. It uses a stale id "Z".
The two removal flows assert no error and not dirty. `remove_grid` itself dirties, so the helper calls `session.save()` first and asserts clean before the switch.

## Finding 3 (Ruling 8)
The "as it was left" test now doubles A's cell and picks a non-default palette before entering. It asserts the site shows a different cell, then that both come back.

## Results
- test_plugin_site_scope.py: 50 passed.
- test_plugin_slices_dock.py: 79 passed.
- Core+pure: 808 passed, 3 skipped.
- ruff check and format: clean.
- Commands are the constraints.md ones, run as single files.

# Fix round 2

Commit: "Slices: consume the carried window time once it is placed (#70)".

- A (stale pending time): `_apply_resolution` now clears `_pending_top_ns` once it has placed it on a non-None `new_z`. `_on_prepared` in This grid scope calls `_sync_grid_slider()` after the clamp. A reopened survey, which prepares with nothing owed, therefore consumes the time on landing. Test: `test_a_carried_time_never_overrides_a_later_resolution_change`. It failed before the fix and passes now.
- B (`set_scope` top read): `top` prefers `_pending_top_ns` whenever it is set. Test: `test_re_entering_the_site_inside_the_wait_window_keeps_the_window_time`. It failed before the fix and passes now.
- C (spurious "does not cover" error in the wait window): `_apply_resolution` returns early in This grid scope while `_resolution_owed` is set. The owed apply after `prepare()` does the work. `set_scope("site")` clears `_resolution_owed`, because the owed grid was never prepared. Both outlived-cancel tests now connect `dock.error`. The original one also drags the slider in the window. They assert no error from the click until B is prepared and after. The engine's own "did not stop in time" note, which the 1 ms cancel produces by design, is filtered by `_spurious()`.
- RED: with the source reverted, the original outlived-cancel test failed on the "does not cover" error, and the carried-time and re-entry tests failed. The time test for the outlived case passed anyway (it was already green for its time assertion).
- Nit: `plugin_for_test` is removed. The helper takes `plugin`.

Results (single files, `-p no:xonsh`):
- test_plugin_site_scope.py: 52 passed
- test_plugin_slices_dock.py: 79 passed
- core+pure: 808 passed, 3 skipped
- ruff check and format: clean

# Fix round 3

Commit: "Slices: keep the owed resolution and clamp across the wait window (#70)".

1. `set_scope("site")` no longer clears `_resolution_owed`. `_run_pending_grid_prepare` consumes both flags on the return.
2. `_resume_grid`'s no-target path, when a resolution is owed, leaves `_pending_top_ns` for the owed apply. It skips the slider sync and the redraw and only refreshes the status.
3. After `prepare()`, when a resolution was owed and the engine is already prepared (a no-op prepare), `_clamp_z_to_prepared()` runs before the owed apply. This fixes both repro sequences: select A again after the round trip, and `remove_grid("B")` in the window.
4. `_resolution_owed` is consumed before `prepare()`, so a raise cannot leave it stuck.
5. The wrong `_debounce.stop()` comment line is dropped.

New tests (all five failed with the source reverted):
- round trip keeps the owed resolution
- round trip keeps the window time
- landing on the grid the engine already holds clamps the seeded range
- a grid removed in the wait window clamps the fallback grid
- a raising `prepare` does not leave the flag stuck

The two clamp tests connect `dock.error`, filter only "did not stop in time", and assert a slice is drawn on A after a later edit.

Results (single files, `-p no:xonsh`):
- test_plugin_site_scope.py: 57 passed
- test_plugin_slices_dock.py: 79 passed
- core+pure: 808 passed, 3 skipped
- ruff check and format: clean
