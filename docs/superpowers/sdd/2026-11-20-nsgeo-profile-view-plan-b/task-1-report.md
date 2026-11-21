# Task 1 report
Implemented the five changes: header flag computed before `_set_axes_holding` (`from_processed`); `_FitButton` (QToolButton subclass, event() on FontChange/StyleChange, try/except+log) recomputes widest width; `set_axes` finite guard; `ProfileView._window_metres_per_trace_unit` used by `_true_scale_inputs` and `true_scale_window_is_flat`; `bounds_on` and its pure test removed; width pin replaced by `test_the_toolbar_minimum_width_holds_in_any_font` (two checks, docstring updated).
RED (qgis_tests.sh ... -k "rule_1 or font_change or non_finite or holds_in_any_font"): 3 failed, 2 passed.
- rule_1: window (32.59, 42.59) vs expected (39.35, 49.35): moved by the new zero.
- font_change: len(xs) == 3 (586, 597, 605).
- non_finite: ValueError ViewTransform requires finite axes: t0_ns=nan.
- width test (holds_in_any_font) and the 2nd pass-check passed first (they pin behaviour already holding); 2 passed = the width test plus the one other selected existing test.
GREEN: profile_dock+view+cut 309 passed; pure 432 passed, 4 skipped; real_data 54 passed; ruff check/format clean.
Note: first implementation left the Fit button with no default action (setDefaultAction(None)); caught by test_fit_button_restores_the_full_extent_after_a_zoom, fixed (restores to last action = Fit).
Probe scripts in scratchpad no longer existed; rule-1 test built from the brief's sequence.
Self-review: no concerns. Pure count 432 vs baseline 433 = removed bounds test.

## Fix round 1
1. Width pin: dock shown+resized, qWait after setText, liveness `after >= base + grown` added. Mutant (velocity_label = plain QLabel): FAIL `assert 4364 <= (750 + 885)`; real code: pass. Mutant reverted.
2. `_clock_carried` removed (init, reset, set).
3. `_FitButton.event` now calls super first, then recomputes; try/except+log kept.
4. Default action explicit: `set_actions(actions, default)` called with `fit_all_action`.
5. Comment reworded (rule 1 puts same transform back; clock rule carries).
Tests: dock+view+cut 309 passed (see run), pure 432 passed 4 skipped, ruff clean.
