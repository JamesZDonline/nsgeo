# Task 1 report

Implemented `ui/wheel_guard.py` (`guard_wheel`), applied to the four Slices spins and the Edit lines Grid combos
(plus focus back to the table on `activated`), `set_spins_quietly` skip rules, `plugin_testing.wheel_event`, and the tests.

## Deviations (need review)
- `seed_z` in site_scope.py: `setSingleStep(dt)` now only when the step differs. Without it the half-typed test
  still failed: `setSingleStep` re-renders the box text ("0. ns" -> "0.2165 ns") even for an unchanged step.
- Offscreen Qt5: `QApplication.sendEvent(widget, wheel)` does not climb to parents (a label also did not scroll the
  area), so the brief's "panel scrolled" assertion after a wheel sent to a spin cannot hold. The test now asserts
  the event is not accepted (as the TimeSpinBox precedent does), values/engine unchanged, and that a notch sent to
  the scroll viewport scrolls. Qt-side propagation of ignored spontaneous events is unverified here.
- Tests run with `-p no:xonsh` (a broken xonsh pytest plugin in the venv).

## TDD
RED: wheel tests changed values / focus tests failed before implementation (first run showed 4 wheel failures and the
half-typed failure, then fixed test bugs and the singleStep cause). GREEN: new tests pass.

## Results
slices_dock 185 passed; edit_lines_dialog 51 passed; site_scope 164 passed; param_form -k wheel 1 passed; ruff check/format clean.

## Fix report (coordinator follow-up)
Added `plugin_testing.propagate_wheel(widget, dy)` (replays Qt's spontaneous climb; returns the accepting widget or None).
The unfocused-box test now asserts: event not accepted, `propagate_wheel(spin)` lands on the scroll area or its viewport,
scrollbar > 0, values and engine unchanged. seed_z comment now cites #105. ruff fixed (line length, import order).
Command: pytest -p no:xonsh test_plugin_slices_dock.py -k "wheel or lets_go or focus or thickness_box" -> 12 passed.

## Fix report (review round 1)
Changes: wheel_guard `_WheelFilter` now owns a guarded `let_go` method (connected to vertical AND horizontal bars; dies with the box);
edit_lines_dialog `_focus_table` guarded method replaces the lambda; tests: Edit lines wheel test checks every row after each notch + a
currentTextChanged spy; StrongFocus pinned for the four spins and the Grid combos, thickness stays WheelFocus; horizontal-bar let-go test;
let-go test now really types "0.75" via keyClicks.
Command: pytest -p no:xonsh test_plugin_edit_lines_dialog.py test_plugin_param_form.py -k "edit or wheel or grid or focus or lets_go" -> 59 passed;
test_plugin_slices_dock.py -k "wheel or lets_go or focus or thickness_box" -> 13 passed. ruff clean.
