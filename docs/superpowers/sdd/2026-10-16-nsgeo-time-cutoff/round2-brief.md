# Walkthrough round 2 — three changes the user asked for

The user ran the walkthrough on the time cutoff (22 pass, 0 fail) and asked for three changes. Build all three test-first on branch `nsgeo-time-cutoff`, head `0981d9d`. Each change gets a failing test that you run and see fail before you write the code.

## 1. The cutoff label is hard to read (F1)

The user's words: "magenta line is easy to see, the magenta text is very hard to read".

- **Now:** `ProfileView._paint_cutoff` (`packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`) draws `cutoff_label(...)` in magenta text, straight onto the radargram, inside `_cutoff_label_rect`.
- **Wanted:** white text on a small filled magenta tag (`CUTOFF_COLOUR`). Give the tag a few px of padding around the text, sized to the text rather than to a fixed width.
- **Unchanged:**
  - the line;
  - the dimming below it;
  - the label's position rules: right-aligned, above the line, moved below it when there is no room above;
  - the rule that the tag stays inside the image rect `r`.
- **Test:** the tag rect lies inside `r`, at the top edge and at a mid-record time. In a rendered grab, a pixel inside the tag but clear of the glyphs is the tag colour (red at least 150, green under 100). Factor the tag rect out if that makes the test pixel-free.

## 2. Drop "(needs values)" for steps that add without a dialog (F3)

The user's words: "drop needs values".

- **Now:** `ProcessingDock` builds the Add step menu with `f"{name}  (needs values)" if required_params(name) else name` (processing_dock.py:119).
- **The problem:** `add_step_with_dialog` adds `gain_curve` and `time_cutoff` without any dialog, because every required parameter they have is of kind `"curve"` or `"time"` and is seeded from the record. Only steps that really open the dialog should say "(needs values)".
- **Fix:** one helper decides whether a step opens the Add-step dialog. Name it, for example, `needs_dialog(name) -> bool`. Both the menu label and `add_step_with_dialog`'s seeding branch must use it, so the two can never disagree.
- **Test:** extend the existing menu test (`test_plugin_processing_dock.py` around line 37). `time_cutoff` and `gain_curve` read as their bare names. `bandpass` still carries "(needs values)". The existing assertion that menu names split back to `available_steps()` still holds.

## 3. A bounded spinbox for the cutoff number (B7, C6)

The user's words: "A bounded spinbox for the number might not go amiss". On an invalid number: "just have it snap to the nearest limit and no need for a note".

The cutoff field in the Processing panel (the `"time"` kind in `ParamForm`, `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py`) becomes a bounded number spinbox.

**Range**
- The range is the record as it reaches the cutoff step:
  - lower limit `t0 + dt`, so one sample is always kept;
  - upper limit `t0 + n*dt`, the record end, which is also where the step is seeded.
- `t0`, `dt` and `n` are those of the step's INPUT: `stack.intermediate(row - 1)`, or `stack.source` when the step is first.
  - So a `time_zero` above it moves the lower limit.
  - When the stack does not evaluate cleanly, fall back to `stack.source`, then to the line header, the way `ProcessingDock.time_axis()` already does, and log it the same way.
- `ProcessingDock._show_form` computes the range and hands it to the form. A reasonable shape is an optional `time_range: tuple[float, float] | None` argument on `ParamForm.set_step`. `ParamForm` stays generic and never learns about stacks.
- With no range given, as in the Add-step dialog, the spinbox is effectively unbounded.

**Snapping**
- A typed value outside the range snaps to the nearest limit when committed (Enter or focus out). There is no message.
- Typing such a value must be possible. A stock `QDoubleSpinBox` refuses the keystrokes for some out-of-range values, and by default reverts to the previous value rather than the nearest one. Typing `-20` or `500` and pressing Enter must end at the lower or upper limit.

**Spinbox behaviour**
- One arrow step is one sample (`dt`).
- The text shows the value the way the other number fields do (`f"{value:g}"`).
- A value inside the range is kept exactly as typed. Do not snap it to a sample.

**Keep Ruling R3 intact**
- R3: an editor whose value the user has not changed reports the exact value it was built from. `QDoubleSpinBox.setValue` rounds to `decimals()`, and the display is 6 significant digits, so this needs the same care the line edit got.
- The existing test `test_an_unedited_field_commits_the_exact_value_it_was_built_from` (HS350 axis: `dt_ns=0.21653111279010773`, `t0_ns=-11.086392402648926`, `end_ns = t0 + 2*dt`) must still pass against the spinbox, given a range that contains that value.
- The end-to-end R3 pin in `test_plugin_time_cutoff.py` must still pass: drag, then an unedited `form.commit()` emits no `stack_changed`.
- A value that was snapped to a limit is a real change and commits.

**Scope**
- Only the `"time"` kind gets the spinbox. Float and int parameters of other steps keep their line edits.
- Update `test_a_time_param_is_a_number_field_with_its_unit` (`test_plugin_param_form.py:531`), which asserts a `QLineEdit` today. Keep its unit-label and commit assertions.

**Tests**
- With a given range, typing below or above it and committing gives exactly the lower or upper limit.
- An arrow step moves by `dt`.
- An in-range typed value commits as typed.
- Through a real `ProcessingDock` on a line whose stack is `[time_zero, time_cutoff]`, selecting the cutoff row gives a spinbox whose range is the time-zeroed record's `(t0 + dt, t0 + n*dt)`.
- On the real-data line in `test_plugin_time_cutoff.py`: typing a value past the end, then selecting another step, leaves the stack's `end_ns` at the record end and the clipped profile unchanged.

## Constraints (as for the whole branch)

- Only `qgis.PyQt`.
- Every slot and Qt override guards its body and reports through `_log`.
- Assert on resulting state, because a slot exception prints and the test still passes.
- Match the house style.
- ruff 0.17.1 and mypy 2.4.0.
- The boundary tests (7) stay green.
