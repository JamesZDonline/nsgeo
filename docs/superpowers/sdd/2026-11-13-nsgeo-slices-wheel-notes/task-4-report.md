# Task 4 report

Implemented: ui/folds.py (FOLD_GROUP, fold_settings, remember_folds with re-entry guard + logged guard); resolution_group, display_group, FinishPanel, NormalisationPanel.group are QgsCollapsibleGroupBox; folds wired after all panels exist; COVERAGE_TIP; autouse conftest fixture; guide edits (step 3 wheel/dz/folds, Warnings sentence, coverage preview sentence).

Step 1: compose_footprints (nsgeo/slices/site.py) max-pools counts (max_pool_counts) when cells_per_pixel > 1, so the preview takes the largest count. COVERAGE_TIP and the guide stand as written.

RED: pytest ... -k "fold or coverage_tooltip or real_settings or normalisation_section": 8 failed, 2 passed (the two passers: not-fold, and settings-file test whose conftest fixture was already in). Failures: no fold support, plain group boxes, tooltip old, no .group. (folds.py and COVERAGE_TIP constant existed at that run so collection worked.)
GREEN: same command, 10 passed.
Note: test_the_two_interpolation_panels_fold_together only checks grid->site direction; a hidden site_finish does not propagate an unfold back (QGIS ignores it while hidden).
Full: dock + site_scope + finish_panel: 388 passed, 1 failed (test_a_site_refine_for_a_window_left_behind_never_draws, timing; passed 3/3 alone, unrelated). Pure: 305 passed, 1 skipped. Ruff clean.

## Fix round 1

Changes (folds.py): `_ShowSync` event filter marks boxes synced while hidden and re-applies `setCollapsed(isCollapsed())` on their next Show (scroll-on-expand off meanwhile); box NoFocus; fold slot syncs others first, writes the setting second. Tests: interpolation test now uses real set_scope both directions and asserts drawn height; restart tests build a new dock and assert drawn height (Normalisation really restarts); literal coverage text; focus test added. Guide line re-wrapped.

Deviation (focus): NoFocus on the box alone did NOT keep focus. Qt hands a click on an unfocusable header to the nearest click-focus ancestor, the panel's QScrollArea (StrongFocus), so dz lost it (reproduced: focusChanged dz -> QScrollArea). Fix: the filter also records focusChanged and, on a header MouseButtonPress (box and its QToolButtons), gives focus back to the widget lost within 100 ms if focus landed on a scroll area or box. Also, the brief's test (click Resolution's button, assert dz focused) cannot hold: folding Resolution hides dz. The test clicks Display's button with dz focused.

Revert checks (each run: pytest -k "fold or normalisation_section or coverage_tooltip"):
- all fixes reverted (HEAD folds.py): interpolation test + focus test fail (197 px drawn open).
- no stale/show re-apply: interpolation test fails.
- no focus give-back: focus test fails.
- Restart and coverage tests pin existing behaviour; they pass on old code by nature (they check what is drawn, not new code).
GREEN: 11 passed. Whole files (slices_dock, site_scope, finish_panel): 390 passed. Ruff clean.

## Fix round 2 (ruling 26)

Removed the focusChanged recording, the 100 ms give-back and the button filters from folds.py; kept NoFocus on the boxes and the _ShowSync re-apply. Replaced the header-click test with: (a) test_a_section_folding_does_not_take_focus_from_dz (dz focused, Display folded, panel scrolled to top, Display unfolded; asserts the unfold moved the scroll value and dz kept focus); test_the_guard_would_let_go_on_a_value_change (in-process mutant: valueChanged -> scroll.setFocus; same scenario, asserts the scroll moved AND dz lost focus, so (a) fails under that mutation); (b) test_the_folding_boxes_are_not_tab_stops (NoFocus on all five boxes).
Commands: pytest -p no:xonsh -k "fold or normalisation_section or tab_stops or guard_would or does_not_take": 12 passed. Whole test_plugin_slices_dock.py + test_plugin_site_scope.py: 382 passed. Ruff check/format clean.

## Fix round 3

Reflowed guide lines 549-551 (<= 78 chars); dropped test_the_guard_would_let_go_on_a_value_change and the `mutate` parameter; corrected the NoFocus comment in folds.py (StrongFocus with the collapse button as focus proxy; NoFocus mainly sends a header click's focus to the scroll area; button still reachable by Tab). Proof of teeth for the focus test is the reviewer's mutant (real guard_wheel connected to valueChanged makes `assert kept` fail); `moved > 0` in the main test pins that the unfold scrolls.
Command: pytest -p no:xonsh slices_dock + site_scope -k "fold or normalisation_section or tab_stops or does_not_take or coverage_tooltip or real_settings": 12 passed. Ruff clean.
