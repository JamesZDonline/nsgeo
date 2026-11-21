# Task 4 report: vertical axes in ns / samples / m (#11)

Status: DONE_WITH_CONCERNS (one legitimate re-pin, below).

Commits: 44683f6 re-pin for MARGIN_RIGHT=56 (view file green, 108 passed, before new tests); then the feature commit.

Implemented: AXIS_UNITS, set_axis_units (ValueError), axis_units, has_velocity, _axis_ticks, _sample_ticks, axis_strip_at, axis_menu_requested (global pos via mapToGlobal), strip press returns before any gesture (left/right buttons only; middle pan untouched). _paint_axes draws each side from _axis_ticks with "unit ▾" caption. Dock: AXIS_DEPTH_GREYED_TIP, axis_menu, _on_axis_menu_requested (popup, checkable items, Depth disabled+tooltip without velocity), _set_axis_unit (saves key), settings read at construction with fallback.

RED (stubs for API, so failures are on assertions): 7 view failures (e.g. `assert ['x'] == ['0','50','100']`, `DID NOT RAISE ValueError`, `assert 'none' == 'left'`, `[] == ['left','right']`) and 4 dock failures (`'NoneType' has no attribute 'actions'`, `'feet' == 'sample'`).
GREEN: view 116 passed, dock 148, cut 17, velocity_fit 78, time_cutoff 13, pure 418 passed/4 skipped; ruff check and format clean.

Re-pinned: test_depth_axis_uses_the_velocity_model. Spec rule "depth ticks only for times >= 0" shrinks the depth range on that fixture (t0=-4) from [-0.2,3.0] to [0,3], so labels become 0,0.5..3 and ys 16.5..264 in 7 steps (values from y_of_time(20*d), independent of the code).
Added tests beyond the brief: ValueError refusal, depth ticks from time 0 on a shifted clock, strip boundaries, menu items/data, bad remembered unit overwritten on next choice.

Concerns: none beyond the re-pin. Existing _time_ticks/_depth_ticks kept; _axis_ticks dispatches to them.

## Fix round 1

1. `setToolTipsVisible(True)` on the axis menu and on `fit_menu` (profile_dock.py). Tests: toolTipsVisible assertion added to test_depth_is_greyed_in_the_menu_without_a_velocity; new test_the_fit_menu_shows_its_tooltips. RED before fix: `assert False where False = ...toolTipsVisible()` on both.
2. test_depth_ticks_start_at_zero_on_a_shifted_clock now uses t0 = -10 and asserts labels 0,0.2,0.4,0.6,0.8,1. RED with the `max(..., 0.0)` clamp removed: `['-0.5','0','0.5','1'] == ['0','0.2',...]`; clamp restored (git checkout).
GREEN: test_plugin_profile_view.py 116 passed; test_plugin_profile_dock.py 149 passed; ruff check and format --check clean.
