# Task 1 report (commit 7a72d43, pushed)

Implemented: profile_settings(), SLICE_BAND_KEY/LEFT_AXIS_KEY/RIGHT_AXIS_KEY, checkable QToolButton `slice_band_button` after 1:1
(initial state from the key; anything but "false" means shown), `_on_slice_band_toggled`, `_sync_slice_band_button` (also called at end of
__init__, set_slice_band, clear_slice_band), `_push_slice_band` returns when unchecked, `_refresh_velocity` clears axis + label on KeyError
and on generic Exception (generic still logs). conftest autouse `_profile_settings`. 9 new tests in test_plugin_profile_dock.py.

RED: `qgis_tests.sh .../test_plugin_profile_dock.py -q -k "slice_band or slices_panel or velocity_refresh or missing_velocity"` ->
collection ImportError "cannot import name 'SLICE_BAND_KEY'" (all tests, expected: names not yet defined). The #14 tests and the
plugin-level test were not individually run red (collection error stopped the file).
Note: test_closing_the_slices_panel_leaves_the_band passes on the old code too (band is shown by default, nothing hides it); it is a regression guard.

GREEN: whole test_plugin_profile_dock.py + test_plugin_profile_view.py: 231 passed, 4 skipped, 2 failed (see concern). Pure: 405 passed, 11 skipped.

Plugin fixture needed answer_modal(QMessageBox,"question",Discard) before unload (site open -> modal prompt -> segfault otherwise) and the tabify settings reset, as surface_plugin does.

CONCERN: two existing toolbar tests now fail because the extra button widens the toolbar:
- test_the_toolbar_minimum_width_is_back_to_pre_m7: minimumSizeHint 766 > 700.
- test_a_preview_starting_does_not_shift_the_toolbar_buttons: velocity_label width 153 < text width 180 at 900px.
Task 2 (ElidedLabel velocity label, re-pin of the second) is expected to cure both; the first test's 700 bound likely needs re-pinning there too (plan's worst-case test uses 1361).

## Fix round 1
Changes: ruff check --fix + format (import sort, SLICE_BAND_TIP join); re-pinned the two toolbar tests (preview test asserts the label's full text; min width <= 800, docstrings cite spec 4.1); strengthened the window-change and closing-the-panel tests (12 ns and 1 ns shifts); added pins for a stored "false" and for a bad value overwritten by the next choice.
RED against deliberately broken code (reverted):
- set_slice_band skipping the store while unchecked: test_a_window_change_while_hidden... FAILED "assert 0.0 == 12.0 +- 1.2e-05".
- set_slice_band storing only the first window: test_closing_the_slices_panel... "assert 0.0 == 1.0 +- 1.0e-06".
- old _refresh_velocity except branches restored: both #14 tests FAILED "assert ['0','1','2','3'] == []".
GREEN: test_plugin_profile_dock.py: 133 passed, 3 skipped; pure: 405 passed, 11 skipped; `ruff check .` clean; `ruff format --check .` 302 files formatted.
