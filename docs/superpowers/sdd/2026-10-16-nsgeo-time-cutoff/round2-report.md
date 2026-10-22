# Round 2 report

## Changes
1. F1 label: `_cutoff_label_rect` now returns a tag sized to the text (`CUTOFF_TAG_PAD_X/Y`), right-aligned, above the line or below when no room, inside `r`. `_paint_cutoff` fills it with `CUTOFF_COLOUR` and draws white text. Line and dimming unchanged.
2. F3: module-level `needs_dialog(name)` in processing_dock.py. The menu label and `add_step_with_dialog`'s seeding branch both use it. `time_cutoff` and `gain_curve` show bare names; `bandpass` keeps "(needs values)".
3. B7/C6: `TimeSpinBox` (param_form.py) for the `"time"` kind. `validate` accepts any finite number as text (Intermediate for partials), `valueFromText` clamps to the range, `textFromValue` is `:g`, decimals 10, single step = dt, keyboard tracking off, `stepped` signal commits arrow steps. `ParamForm.set_step(..., time_range=None, time_step=None)`; no range = +-1e9. R3: `_shown` holds (spin value after setValue, exact value); an untouched spinbox reports the exact value. `ProcessingDock.input_axis(row)` (intermediate(row-1) or source, with the time_axis fallback and a log) feeds `_show_form`.

## TDD
RED then GREEN per cycle:
- Tag: 2 new tests failed (width == r.width()-4; pixel at the tag was black), 81 passed after.
- Menu: `assert "time_cutoff" in texts` failed (name carried "(needs values)"); passed after.
- Spinbox form tests: 10 failed (`set_step` had no `time_range`; the QLineEdit assertion), 35 passed after. Arrow-commit test failed (`got == []`), passed after `stepped`. The snap-text-at-limit test passed first time; it guards a Qt refresh edge.
- Dock range tests: 3 failed (+-1e9 vs the record range), passed after.
- R3 end-to-end pin (`test_a_dragged_cutoff_survives_...`) went RED mid-way: `setRange` rounds the limits, so an exact value on a limit compared outside the range and lost its exact copy. Fixed by testing the clamp distance rather than `min <= value`. Green after.
- Real-data/synthetic "typing past the end" tests were written after the spinbox existed, so they have no RED of their own. They cover the Enter and focus-out paths.

## Counts
- Pure+core: 606 passed, 3 skipped.
- Full QGIS tier: 726 passed (709 + 17 new).
- ruff check and format: clean. mypy: no issues in 33 files.
- `-s` runs of param_form, processing_dock, time_cutoff and profile_view files: no tracebacks.

## Files
nsgeo_qgis/ui/{param_form,processing_dock,profile_view}.py; tests/qgis/test_plugin_{param_form,processing_dock,profile_view,time_cutoff}.py.

## Concerns
- A REQUIRED time field with no default would show 0 in the spinbox (no blank state). No such step exists today, and the Add-step dialog seeds time params anyway.
- Typed unparseable text via `set_value` reverts rather than showing a form error, for the time kind only.
- A value exactly on a limit is restored exactly only to ~1e-9, the spinbox's rounding.

# Fix round 1

## Fixes
- Critical 1 / Important 2 (R10): `TimeSpinBox` tracks `touched` (textEdited or stepBy or `set_value`). An untouched spinbox reports the exact built-from value, in or out of the range. `valueFromText` ignores the display text unless text was actually typed (`_text_dirty`), so Return/focus-out on an untouched or arrow-stepped field no longer re-reads the 6-digit rounding. A typed value equal to the display is still an edit.
- Minor 4 (R11): the exact range is kept (`set_exact_range`); `exact_value()` returns the exact limit when `value()` equals the rounded min or max.
- Minor 6: tag left edge is clamped to `r.left()`.
- Minor 7: `textFromValue` and `valueFromText` are guarded and log.
- Minor 8: `time_axis()` delegates to `input_axis(len(entries))`. The fallback log now says `input_axis`, and `test_time_axis_logs_when_it_falls_back_to_source` was updated to match.
- Important 3: the focus-out test now moves the form into a shown, active host, asserts `spin.hasFocus()`, types, moves focus for real, then asserts `committed` fired once, `end_ns` unchanged, and no `stack_changed`. The earlier report's claim that the first round covered focus-out was wrong: its focus half was vacuous.

## TDD
- Form level, RED (before the fix): Return sweep gave -10.6533 vs exact; arrow then Return gave 10.3502 vs 10.350187763609892; stored 120 and -50 committed the limits 100 and -3.5; snap gave -10.8698612899 vs exact; the `textFromValue` guard raised ValueError; the tag left edge was -30 against 10. GREEN after the fix.
- Dock level: with the old param_form.py restored, `test_return_with_nothing_typed_writes_nothing` (synthetic and real) and `test_an_untouched_cutoff_above_its_range_survives_return_and_focus_out` failed. All pass with the fix.
- The focus-out commit test and the "typed display text is still an edit" test passed before the fix. They are guards, not RED.

## Counts
- Pure and core: 606 passed, 3 skipped.
- Full QGIS tier: exit 0, no failures (the collected count is in the reply).
- ruff and mypy clean. `-s` on param_form, profile_view and processing_dock: no traceback or Error lines. The time_cutoff file ran clean under `-s` as well.

# Fix round 2

## Fixes
- Teardown crash: `_unload` hands `dock.form` back to `dock.form_area`, then closes and deleteLater()s the host and runs processEvents. RED before the fix: the whole time_cutoff file exited 139. GREEN: the whole file exits 0 (11 passed). `test_typing_past_the_end_leaves_the_record_whole` alone exits 0. `test_an_untouched_cutoff_above_its_range_survives_return_and_focus_out` alone exits 0. The full QGIS tier exits 0 (748 collected).
- R12 (narrows R10): `touched` is set only when `valueFromText` parses text that differs from `textFromValue(value())`, or on a step. `textEdited`, `_text_dirty`, `_on_text_edited` and `_on_finished` are removed, so the unguarded-slot minor goes with them. `edit_text` no longer leaves a dirty flag.
- R13: `StrongFocus` policy; `wheelEvent` ignores the event when the field is not focused (guarded, logged), so the panel scrolls.
- Comment at test_plugin_time_cutoff.py:306 corrected to row 2's range (row 1's output).

## TDD
- RED: `test_a_gesture_that_changes_nothing_writes_nothing` (clear+Return, "-"+Return, digit+Backspace+Return, retype the display; each on the HS350 axis and a fine axis, dt 0.0117 with a float32 t0) failed 8 of 8, with the committed value the 10-decimal rounding or 6-digit text. The "-" then focus-out test failed. The wheel test failed: the unfocused wheel was accepted and stepped.
- To confirm the wheel test is real, I disabled the guard once and watched "not ev.isAccepted()" fail. A first failure of the wheel test was partly a test bug: the host gives the spinbox focus first, so leaving it committed. The test now clears `got` after moving focus.
- GREEN after the fix: 55 passed in param_form. The inverted "typing the displayed text" test was replaced by the gesture sweep. Real typed changes and snaps still commit (existing tests plus `test_a_real_typed_change_still_commits_after_the_r12_rule`).

## Verification
- Exit codes: all four covering files exit 0 under `-s` with 0 traceback/Error lines. The full QGIS tier exits 0 (748 collected). Pure and core: 606 passed, 3 skipped. ruff and mypy are clean.
