# Final-review fix wave — findings to fix (from the whole-branch review of 513867a..819423b)

## I1 (Important, regression). Restoring a cube saved on another grid can silently draw the wrong cube under a false refusal.
slices_dock.py ~2169-2170: `restore_cube` calls `flush_debounce()` BEFORE `prepare()`, so `_apply_resolution` checks the restored resolution against the OLD grid still in `engine.choice`. On a mixed-radar site the level limit refuses a deep-record cube against the shallow grid's samples; the engine keeps the old resolution; `prepare()` then carries that old resolution to the cube's grid; `_on_prepared` clamps nothing so only `refresh_slice()` runs — nothing re-applies.
Reproduced at 819423b: grid A 512-sample lines, grid B 2,048 samples over the same 110.864 ns; B's cube saved at dz 0.0541 (2,049 levels), restored while A shows → grid B shown, spins read dz 0.0541, engine z is (0.2165, 512); Warnings shows "Too many levels: dz 0.0541 … this cube allows 1,024 (twice the 512 samples in each line)…" for a grid whose lines have 2,048; no toast; never clears. (At base 513867a the same flow ended on the cube's own axis, with a spurious "does not cover" toast.)
The frame-cap variant has the same cause: a large grid shown, a small grid's fine-cell cube restored → refusal naming a grid no longer shown.
The ledger's T2 minor "restore_cube's grid change doesn't clear _grid_refusal" is part of this (the refusal stands after preparation when nothing clamps).
Fix (either, your judgement — keep the existing restore behaviour otherwise, including the `_pending_z_shift` path and `_resolution_owed`): (a) in `restore_cube`, `prepare()` before the flush so the apply targets the cube's grid (also removes base's spurious toast); or (b) after a preparation lands, apply whenever the spins' `Resolution` differs from the engine's. Also make sure a restore onto another grid clears a refusal that belonged to the previous grid.
Tests: the mixed-radar scenario above — after restore + preparation, engine z equals the cube's (dz 0.0541, nz 2,049), Warnings is empty, no toast; plus the frame-cap variant (large grid shown, small grid's fine-cell cube restored → the cube draws at its own cell, no refusal, no toast). If convenient, add the deferred T2 test too: a cube record with no resolution restored onto a grid with a higher cell floor → cell floor becomes that grid's.

## I2 (Important; the PR closes #176). An Edit lines Grid combo dismissed with Escape keeps the wheel.
edit_lines_dialog.py ~223-224: focus is handed back to the table only on `activated`; Escape or a click-away emits none. Confirmed offscreen: click opens the popup, Escape → combo has focus → one wheel notch moves Grid5 → B, accepted.
Fix: hand focus to the table when the popup closes — e.g. a small QComboBox subclass whose `hidePopup` calls super() then `table.setFocus()` (guarded override; logs via the dialog's `_failed` or `_log`). Keep the change within the combo-setup lines (merge clash with M19a Plan B on this file).
Test: click (open popup) → Escape → a wheel notch → combo unchanged and the table has focus.

## M1 (fix before merge; spec §6.1). The `Resolution` ValueError branch of `_apply_resolution` leaves the last refusal standing.
slices_dock.py ~2575-2579: after z1 = 100,000 is refused, z1 = 1.0 (below z0) toasts "t1_ns must exceed t0_ns" while Warnings still shows the refusal for 100,000. Fix: clear `_grid_refusal` at the top of the apply (after the `_resolution_owed` return) and call `show_warnings()` in the ValueError branch. Test: refusal showing → z1 below z0 → Warnings empty, toast emitted.

## M3 (cheap). A Warnings entry with an unbroken token wider than the panel is clipped with no "…" and no tooltip (warnings_panel.py ~56).
Fix: `label.setToolTip(text)` on each entry label (spec §6.1 allows a tooltip that repeats the text). One assertion in test_plugin_warnings_panel.py.

## M4 (cheap). The user guide doesn't say the Edit lines Grid column takes the wheel only after a click (docs/guide/getting-started.md around line 334, the Edit lines section). Add one sentence in the file's style (~80-char lines).

## Not to change (ruled out)
- M2 (a scope round trip restores a refused value without its refusal): spec §6.1 allows clearing on a scope change; leave it.
