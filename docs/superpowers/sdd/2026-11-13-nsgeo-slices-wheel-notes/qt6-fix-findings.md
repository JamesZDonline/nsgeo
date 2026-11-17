# Follow-up fix (after the final wave): CI red on QGIS 4.2 / Qt 6, plus two parked one-liners

## Q1 (load-bearing: CI red). `test_a_grid_popup_dismissed_with_escape_does_not_keep_the_wheel` fails on qgis/qgis:4.2 (Qt 6, offscreen), passes on 3.44 (Qt 5).
CI job log (run on adcac6e), test_plugin_edit_lines_dialog.py:725:
    QTest.mouseClick(combo, LeftButton); assert combo.view().isVisible()
    QTest.keyClick(combo.view(), Key_Escape); assert not combo.view().isVisible()
>   assert dialog.table.hasFocus()        -> False
Captured stderr: "This plugin does not support propagateSizeHints()", "This plugin does not support raise()", "This plugin does not support grabbing the keyboard".
Likely cause: on Qt 6 the popup is its own top-level window; closing it re-activates the dialog asynchronously, and Qt's popup-close focus restore (QApplicationPrivate::closePopup → the active window's focusWidget gets focus with Qt::PopupFocusReason) can land after `_PopupFocusCombo.hidePopup`'s synchronous hand-back, or the dialog is simply not active yet when the test asserts (no events processed).
Fix (both halves):
 (a) Production, belt and braces: `_PopupFocusCombo` also hands focus back in a guarded `focusInEvent` override when `event.reason() == Qt.FocusReason.PopupFocusReason` (focus returning from its own popup), after calling super(). Keep the `hidePopup` hand-back. Keep the change inside `_PopupFocusCombo` (merge clash with M19a Plan B on this file).
 (b) Test: after Escape, wait for the outcome rather than asserting synchronously — `assert QTest.qWaitFor(lambda: dialog.table.hasFocus(), 1000)` (or a short spin with processEvents) — then the wheel notch must change nothing. Keep the test's teeth: it must still fail with the hand-back removed (both hidePopup and focusInEvent no-op'd).
We can't run Qt 6 locally (no qgis/qgis:4.2 image; Docker Desktop off). Run Qt 5 locally; the controller checks CI's 4.2 job after the push.

## Q2 (parked Ruling 35, one line). In `restore_cube` (slices_dock.py ~2164-2177), the restore's spin setValues arm `_debounce` before `prepare()`. If a preparation is running, `set_source`'s nested cancel loop (up to 250 ms, delivers timers) can fire `_apply_resolution` against the OLD grid (a brief false "Too many levels" refusal; in the `_pending_z_shift` branch the record's radar-clock range reaches the engine before the shift — the comment there forbids exactly that). Fix: `self._debounce.stop()` immediately before `self.prepare()` in `restore_cube`; the flush (or the shift branch's stop) after prepare stays as is. Existing restore tests must stay green.

## Q3 (parked Ruling 38, wording). docs/guide/getting-started.md ~337-338, the Edit lines sentence says the Grid box takes the wheel "only after you click it". After the popup fix, closing the list hands focus back to the table, so a Grid box only takes the wheel when you reach it with Tab (or right after clicking it, before its list opens… keep it simple and true). Reword in the file's style, lines under ~80 chars.
