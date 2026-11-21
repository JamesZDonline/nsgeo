# Task 2 report
Implemented ViewTransform.fit_width/fit_height (via with_window), ProfileView.fit_width/fit_height, Fit split button (fit_button/fit_menu/three actions, last pick repeated, not persisted), 1:1 as QToolButton, velocity_label as ElidedLabel (deferred import, stretch 1, right-aligned; addStretch removed). Removed the old fit_button.clicked->view.fit connection (default action now fires it; keeping it would double-fire).
RED: pure `-k fit_` -> 3 failed, AttributeError: no attribute 'fit_width'/'fit_height'. Dock: 4 failed (AttributeError fit_width_action/fit_height_action; worst_case `assert 1388 <= 1361`). View test: failed (my first draft mis-unpacked the fixture tuple; fixed, then fails on missing fit_width before implementation by construction).
GREEN: dock file 137 passed 3 skipped; view file 103 passed 1 skipped; pure 408 passed 11 skipped; ruff check and format --check clean.
Measured toolbar minimum width: 684 px (was 766). Bound tightened 800 -> 690, docstring updated.
test_a_preview_starting... passes unchanged.
Files: ui/view_transform.py, ui/profile_view.py, ui/profile_dock.py, tests/pure/test_pure_view_transform.py, tests/qgis/test_plugin_profile_view.py, tests/qgis/test_plugin_profile_dock.py.
