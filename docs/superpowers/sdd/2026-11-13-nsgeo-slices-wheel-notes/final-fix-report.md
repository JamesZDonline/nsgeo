# Final-fix report (commit adcac6e, pushed)

Status: DONE_WITH_CONCERNS (see end).

## I1 restore onto another grid
Change: `restore_cube` clears `_grid_refusal` (+ `show_warnings`) and calls `prepare()` BEFORE the flush
(`set_source` moves `engine.choice` synchronously, so the apply is checked against the cube's grid). The
`_pending_z_shift` path is unchanged (stops the debounce). No restructuring.
Tests (test_plugin_slices_dock.py): `test_restoring_a_deep_cube_onto_a_shallower_grid_draws_the_cube_unrefused`
(grid A 512 samples, B 2,048; B cube dz 0.0541, 1,664 levels; restore while A shows -> engine z equals the cube's,
Warnings empty, no toast), `test_restoring_a_fine_cell_cube_while_a_large_grid_shows_draws_it_unrefused`
(300 m grid shown, 6 m grid's 0.05 m cube), `test_a_restore_onto_another_grid_clears_the_refusal_of_the_one_left`
(also the deferred T2 floor check: record without `z`).
RED (fix reverted): deep: `assert 512 == 1664` (z = dz 0.2165, nz 512); fine: `assert 0.2 == 0.05`; the T2/refusal test
passed without the fix (guard only). GREEN: all pass.
Test used z1 = 90 ns, not 110.864: the prepare-time coverage clamp trims a range ending past ~99.7 ns to 1,844 levels
at base too, which is unrelated behaviour. `synthetic_dzt` gained an `n_samples=512` kwarg (same data for 512).

## I2 Escape keeps the wheel
Change (edit_lines_dialog.py): small `_PopupFocusCombo(QComboBox)`; `hidePopup` calls super then the dialog's
`_focus_table` (itself guarded; override also guarded, logs via QgsMessageLog). `activated` connection and
`guard_wheel` kept (keyboard Down on a closed combo emits no popup close).
Test: `test_a_grid_popup_dismissed_with_escape_does_not_keep_the_wheel` (click opens popup, Escape, table has focus,
wheel notch changes nothing). RED: `table.hasFocus()` False. GREEN.

## M1
`_apply_resolution` clears `_grid_refusal` after the `_resolution_owed` return; the Resolution ValueError branch calls
`show_warnings()`. Test `test_a_z_range_the_resolution_rejects_clears_the_last_refusal`. RED: refusal for 100,000 still
shown; GREEN.

## M3
`label.setToolTip(entry.text)` in warnings_panel.py. Test `test_each_entry_repeats_its_text_in_a_tooltip` (90-char
token, and a reused label). RED `['', '']`; GREEN.

## M4
One sentence added to docs/guide/getting-started.md (Edit lines section).

## Whole files (-p no:xonsh)
slices_dock 213 passed; edit_lines_dialog 54 passed; warnings_panel 2 passed; site_scope 172 passed (324 s);
slices_width 11 passed. ruff check and format clean.

Files: slices_dock.py, edit_lines_dialog.py, warnings_panel.py, getting-started.md, plugin_testing.py, and the
three test files above.

Concerns: none blocking. `_PopupFocusCombo` sits just above `EditLinesDialog` (a small merge-clash surface with M19a B).
