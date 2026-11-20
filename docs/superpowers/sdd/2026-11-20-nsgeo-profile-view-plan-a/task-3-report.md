# Task 3 report
Implemented true_scale_window (pure, view_transform.py; ViewTransform.one_to_one removed), ProfileView.metres_at_trace_units / trace_units_at_metres / can_true_scale / true_scale (_distance_ticks, window_m, set_window_m route through the pair), dock: 1:1 -> view.true_scale, _sync_true_scale_button called at end of _render, _refresh_velocity (every path), _take_down_picture, _draw_cut (both exits). R1: can_true_scale false when metres-per-unit is 0/non-finite (and slope non-positive); pinned by test_true_scale_needs_a_velocity_and_metres_and_a_nonzero_span.
Removed: test_one_to_one_keeps_the_screen_left_edge; one_to_one loop in test_traces_between_agrees_with_trace_at_on_column_boundaries (now iterates the plain and mirrored transforms). Rewritten: view test_true_scale_matches_metres_across_and_down_and_emits_view_changed, test_fit_and_true_scale_keep_the_ruler_and_the_mirror; dock test_the_one_to_one_button_shows_true_scale. Added the brief's pure/view/dock tests + R1 test.
RED: pure (stub raising NotImplementedError): 4 failed, 33 passed (all four true_scale tests NotImplementedError). View (source reverted): 5 failed (AttributeError true_scale / can_true_scale / metres_at_trace_units). Dock: 3 failed (greyed tests: `assert not True`; shows_true_scale: AttributeError on metres_at_trace_units, i.e. fails at the new helper not the old pixel behaviour assertion).
GREEN: pure 411 passed 11 skipped; dock 139 passed 3 skipped; view 106 passed 1 skipped; cut 17 passed; ruff check and format clean.
Real data: 52 skipped, 3151 deselected (real DZT not present/enabled here), no failures.
Self-review: clean; removed now-unused `d` local in _distance_ticks. plugin.py / slices_dock.py untouched.

## Fix round 1
1. Clamp test replaced (test_true_scale_at_the_clamps_hits_both_minimum_spans), asserts spans equal the minimums. RED with minimum spans disabled in with_window: `assert 0.5057 == 0.8 +- 8e-07`; restored.
2. _sync_true_scale_button now also in __init__ and end of _clear_view_only; test test_true_scale_is_greyed_with_no_line_and_after_the_view_is_cleared (RED on old dock: `assert not True`).
3. Non-finite distance test test_true_scale_is_off_where_the_metre_span_is_not_finite; RED with isfinite(per_unit) removed: `assert not True` (can_true_scale() True); restored.
4. Helper-pair docstring names M17c; can_true_scale docstring mentions non-zero finite span.
5. view.view_changed connected to _sync_true_scale_button; test_true_scale_greys_when_the_window_moves_onto_a_flat_run (RED on old dock: `assert not True`).
GREEN: pure 418 passed 4 skipped; dock 144 passed; view 108 passed; cut 17 passed; ruff check/format clean.
