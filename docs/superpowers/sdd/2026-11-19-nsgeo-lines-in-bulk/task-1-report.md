# Task 1 report

Built: SiteSession.apply_preset_to / apply_stack_to / set_lines_velocity (one change, keys checked first);
ui/preset_box.py migration_note; SurveyDock bulk menu items (preset submenu, steps, set/clear velocity),
apply_preset_action / apply_steps_action / clear_velocity_action / selected_line_keys, signals
bulk_velocity_requested and report; _lost_with_lines_text + default button No when a fit would go (#221);
NsgeoPlugin.open_bulk_velocity_dialog and two connects.

TDD: RED `qgis_tests.sh tests/qgis/test_plugin_session_bulk.py` -> 8 failed, 1 passed (AttributeError on the
new methods; migration_note passed as I created preset_box.py first). GREEN after implementing -> 9 passed.
Dock tests written after implementation of the dock in one pass (not separately observed RED; the old menu
tests failing on the new items served as the RED for the menu). Final: test_plugin_survey_dock.py +
test_plugin_session_bulk.py -> 116 passed. ruff check/format clean.

Existing tests changed: six selection-menu tests that pinned exact menu texts now use
`_texts_before_bulk` (drops the new items) so they still pin the older items.

Self-review: slots guarded; no mag assumptions; plural/singular handled; Oxford comma only in the counts form.
Concerns: migration sentence uses saved=True for presets, saved=False for the open line's stack (my call).
Message-bar velocity uses 3 decimals (a 4-decimal value displays rounded). Core+pure result: see reply.

Core+pure: 2046 passed, 9 skipped, 19 xfailed (1087 s). Commit 2b54d63, pushed.
