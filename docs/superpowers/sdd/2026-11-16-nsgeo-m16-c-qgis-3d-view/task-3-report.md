# Task 3 report
Implemented: SlicesDock.scope_changed (emitted at end of set_scope's real-change path), NsgeoPlugin.act_view3d ("3D view", BUTTON_TIP, in _update_enabled), scene3d built after slices_dock with export_for=_surface_export, open_view3d (ValueError/RuntimeError -> message-bar warning), guarded _close_view3d on session.site_closed, scope_changed + grid_combo.currentTextChanged -> request_refresh, unload disconnects and disposes scene3d first. Guide: toolbar row, greyed sentence, "The 3D view" section.
Tests: 8 new (7 in test_plugin_scene3d.py, 1 in test_plugin_panels_menu.py). RED: all 8 failed before implementation (no act_view3d). GREEN afterwards.
Whole QGIS tier: 2679 passed, 1 warning in 2037.79s (0:33:57). Pure: 357 passed, 4 skipped. ruff check/format clean; mypy list unaffected.
Concern: no test pins that the grid-combo change reaches the scene (needs a second grid in the plugin fixture); the scope_changed connection is covered by the orphan-signal test.

## Fix round 1
I1: open_view3d gains `except Exception` -> message(VIEW_FAILED.format(error=exc), Critical); VIEW_FAILED in scene3d_plan.py; test with scene3d.open raising OSError.
I2: scene3d dispose block moved above the docks' teardown in unload (before surfaces_dock.dispose / slices_dock.dispose_site); comment updated.
I3: new test steps the combo B->A->B->A (spin_until each) then Whole site + combo change keeps the grid. RED: with the currentTextChanged connection deleted by hand, it failed at the repeat-switch assertion; restored, passes. Scope test now also has a test checking the open view's refresh is scheduled and performed after set_scope.
R10: test_closing_the_site builds a surface from the fixture's picks, asserts renderer3D present while open, and gone after close_site.
Results: scene3d+panels_menu+slices_dock files 251 passed (140s); pure 357 passed, 4 skipped; ruff check/format clean; mypy scene3d_plan.py clean.
