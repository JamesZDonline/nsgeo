# Qt 6 fix report
Changes: Q1 `_PopupFocusCombo.focusInEvent` (guarded, hands focus to table on PopupFocusReason, after super()); test now polls (processEvents + qWait, 1 s) for table focus (PyQt5 has no QTest.qWaitFor). Q2 `self._debounce.stop()` before `prepare()` in restore_cube. Q3 getting-started.md Edit lines sentence reworded (Grid box takes wheel only when reached with Tab).
Revert check: with both _give_back() calls turned into `pass`, the escape test FAILED (1 failed); restored, passes.
Tests: test_plugin_edit_lines_dialog.py + test_plugin_slices_dock.py: 267 passed (Qt 5, offscreen). ruff check/format clean.
Not verified: Qt 6 (CI 4.2 job).
