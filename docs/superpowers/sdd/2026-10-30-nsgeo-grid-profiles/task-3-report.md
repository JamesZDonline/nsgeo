# Task 3 report

Implemented in profile_dock.py: `_ruler_for`, `_set_axes_holding` (four ordered rules; `_render` and `_show_line`'s header-only branch both go through it), `_axes_key` (reset in `_clear_view_only`), `_on_geometry_changed` (guarded, swallows KeyError, connected to grids_changed and lines_changed), module docstring paragraph, guide bullet.

TDD: the 10 new tests were run first: 10 failed (e.g. assert None.grid_id on view.ruler), 3 existing passed. After implementation: all 101 in test_plugin_profile_dock.py passed (after the changes below). The real-data zigzag test ran (it failed in RED rather than skipping, and passes now).

Pre-existing tests changed:
- test_rerender_with_the_same_shape_keeps_the_current_zoom: the "really zoomed" sanity compared to 240 traces; now compares to the bounds span (ruler is wider than the line). Identity assertion unchanged and passes.
- test_fit_button_restores_the_full_extent_after_a_zoom: restated: after Fit the window equals transform.trace_bounds.
- test_one_to_one_button_sets_a_trace_per_pixel_window: restated: span == width and the screen-left trace (trace_lo, line is forward) is held, instead of 0.
- test_plugin_velocity_fit.py: GRID size_y 11 -> 1.0 (a grid sized to its 60-trace = 1 m lines, as an import would), 7 tests failed because x=40 fell in blank space. No assertions loosened.

Results: core+pure 827 passed, 3 skipped (the real-data tests are not among the skips; REAL_DZT is populated). QGIS tier: first full run 1186 passed, 7 failed (all velocity_fit fixture, above); after the fixture fix velocity_fit + profile_dock files rerun: 152 passed. (Full tier not rerun after the fixture fix; the fix touches only that file.) ruff check/format clean, mypy clean (37 files). test_no_orphan_signals is in the pure tier and passed.

Files: packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py, tests/qgis/test_plugin_profile_dock.py, tests/qgis/test_plugin_velocity_fit.py, docs/guide/getting-started.md.

Self-review: an accidental `ruff format packages docs` reformatted docs markdown; reverted with git checkout, only intended files committed. `_set_axes_holding` uses `self._key or ""` in _render (a key is always set when a radargram exists). Not checked: key removed from the session between _key read and line_for_key in _set_axes_holding (would raise inside the existing guarded callers).
Concerns: none blocking; the hatch/arrow visuals remain a walkthrough check.

## Fix round 1

Changes: (1) rule 3 now needs `ruler is None and old_ruler is None`; new tests for a same-shape unruled line after a ruled one (zoomed and not) and for two unruled same-shape lines keeping the window; stale docstring of test_switching_lines_does_not_inherit_the_previous_lines_window rewritten. (2) the no-distance test uses `message_log` and asserts it is empty. (3) `_held` per-ruler window, recorded in `_set_axes_holding` on leaving a ruled view, restored by rule 2, cleared in `_clear` only; docstrings updated; new test_the_hold_comes_back_after_a_glance_at_a_cross_line. Consequence: in test_a_line_without_distance_neither_mirrors_nor_holds, coming back to the ruled line now restores the held window (ruling 3 supersedes "starts at Fit"); assertion restated to window_m() == the zoomed window. (4) test_an_import_past_the_ruler_edge_widens_it_without_reopening; verified it fails with the lines_changed connection removed (file restored from a backup copy afterwards). (5) guide reworded. (6) docstrings made accurate (minimum span, time clamp).

RED (before the fix): `pytest test_plugin_profile_dock.py` -> 3 failed (test_a_same_shape_unruled_line_after_a_ruled_one_starts_clean[False], [True], test_the_hold_comes_back_after_a_glance_at_a_cross_line), 103 passed. The item 4 test passed before the fix (the lines_changed connection already existed); its guard value was shown by the disconnect check above (1 failed).
GREEN: dock + velocity_fit + profile_view files 259 passed; pure qgis-tests 174 passed; ruff check/format and mypy clean.

## Final-review fix wave

Changes: `_file_window`/`_apply_held` in profile_dock.py: the departing view is filed per ruler with None for an axis shown whole (time within half a sample of the record; horizontal within 0.5 trace of trace_bounds); a None part keeps the fresh fit. `_clear_view_only` files too; `_clear` resets `_held` after it. `ProfileView.set_axes` drops the ruler when `bounds_on` is not finite and ordered (constant distance axis). Docstrings: module hold paragraph, `_set_axes_holding`, `_selection_bounds`, "along the same axis", the switching-lines test.

RED (before the fix, `pytest test_plugin_profile_dock.py test_plugin_profile_view.py`): 7 failed: test_reselecting_the_cutoff_row_shows_the_whole_bypassed_record, test_removing_the_cutoff_step_shows_the_whole_record, test_a_horizontal_zoom_is_held_while_the_time_axis_stays_whole, test_a_longer_record_after_a_shorter_one_shows_its_full_record, test_a_view_at_fit_stays_at_fit_when_the_ruler_grows, test_a_removed_line_files_its_window_for_the_next_one, test_a_constant_distance_axis_drops_the_ruler_instead_of_raising. Already green before the fix (regression pins): test_a_time_zoom_is_still_held_across_lines, test_a_same_shape_unruled_pair_needs_the_same_trace_count (no mutant check run on this one), test_the_held_windows_are_forgotten_when_the_site_closes (pins the `_clear` ordering only once `_clear_view_only` files; no mutant check run).
GREEN: dock+view+time_cutoff+velocity_fit files 280 passed; core+pure 827 passed, 3 skipped; ruff check/format and mypy clean.
