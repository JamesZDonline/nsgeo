# SDD ledger — plan: docs/superpowers/plans/2026-11-20-nsgeo-profile-view-plan-a.md

Spec: docs/superpowers/specs/2026-11-20-nsgeo-profile-view-design.md (approved 2026-11-20, aba76d5).
Branch nsgeo-profile-view, worktree .worktrees/nsgeo-profile-view. Plan commit efbdc4e.
Models: implementers sonnet; task reviewers opus; small fix rounds haiku/sonnet (user memory: subagent-model-tiers).

## Pre-flight scan

| Pair / task | Produces vs consumes | Finding |
|---|---|---|
| T1 / T2 | T1 puts slice_band_button after one_to_one_button (QPushButton); T2 turns fit/1:1 into QToolButtons, same order; T2's worst-case test reads slice_band_button | consistent |
| T1 / T3 | T1 makes every _refresh_velocity failure path clear velocity; T3 calls _sync_true_scale_button on every path | consistent; T3 must keep T1's clears |
| T1 / T4 | T4 consumes profile_settings, LEFT_AXIS_KEY, RIGHT_AXIS_KEY from T1 | consistent |
| T2 / T3 | T3 rewires T2's one_to_one_button QToolButton to view.true_scale | consistent |
| T3 / T5 | T5 consumes metres_at_trace_units | consistent |
| T3 / T4 | T3's new view tests use the `view`/`ruled` fixtures; T4 re-pins those fixtures' resize(800) to VIEW_W | consistent (T4 step 1 covers them) |
| T4 / T5 | T5 consumes axis_units, has_velocity, and the test helpers _sampled / VIEW_W that T4 adds to test_plugin_profile_view.py | consistent |
| T3 / T6 | both touch _take_down_picture (T3 adds the 1:1 sync call, T6 passes zero_ns=0.0) | consistent |
| T1 self | plugin-level "closing the Slices panel" test listed in the dock test file | see R2 |
| T2 self | tests vs code agree (setDefaultAction gives the button the action's text) | clean |
| T3 self | can_true_scale = transform + velocity + metres; a constant/zero metre span would divide by zero in metres_per_trace_unit | see R1 |
| T4 self | test press points: left strip x=10 -> local -46; right strip width-10 -> local > t.width; bottom press y=height-10 is below the image | clean |
| T5 self | expected strings checked by hand against the _sampled geometry (trace 100 -> 1.67 m, sample 40 -> 10.00 ns, 0.50 m deep; t0=-2 case -> -1.00 ns) | clean |
| T6 self | pure expectations checked: whole (0,92), top (0,15), middle radar (30,45) with zero -0.6 | clean |

Ruling R1: can_true_scale() is also False when the current window's metre span is zero or not finite (guards metres_per_trace_unit = 0) — spec §4.4 greys 1:1 "with no metres along the line"; a constant distance is no metres in effect — cost if wrong: 1:1 greyed on a degenerate line that has no usable scale anyway.
Ruling R2: T1's plugin-level test lives in test_plugin_profile_dock.py with a module-local `plugin` fixture copied from test_plugin_band_times_on_add.py — keeps the task's files as listed; cost if wrong: one fixture duplicated across two test files.

## Tasks
Task 1: dispatched (BASE efbdc4e, implementer a6bfeefa1591a2763, sonnet)
Task 1: implementer DONE_WITH_CONCERNS at 7a72d43 (pushed).
Ruling R3: the two pre-existing tests Task 1 breaks (test_the_toolbar_minimum_width_is_back_to_pre_m7: 766 vs 700; test_a_preview_starting_does_not_shift_the_toolbar_buttons: velocity label 153 < 180 at 900 px) are Task 2's to cure — its ElidedLabel removes the velocity label's text width from the row minimum, and its plan already re-pins the preview test; keep the 700 bound if the measured minimum allows, otherwise re-pin to the measurement with the reason — cost if wrong: one red CI run on 7a72d43 between tasks.
Ruling R4: test_closing_the_slices_panel_leaves_the_band passes on the old code by design (spec §4.2 pins existing behaviour: only the button decides); it stays as a regression guard — cost if wrong: none.
Task 1: review 1 (7a72d43): spec ❌ / Needs fixes — I1 branch red (2 toolbar pins + ruff I001/format); I2 (plan-mandated) band tests can't tell the new window from the old; M1 band persistence: "false"-string and overwrite-on-next-choice untested; M2 duplicated clear lines in _refresh_velocity's two excepts.
Ruling R5: fix ruff in Task 1; re-pin test_a_preview_starting_does_not_shift_the_toolbar_buttons in Task 1 using the plan's Task 2 wording (assert velocity_label.text() is the full text; buttons don't move) — Task 2 is told it's done; re-pin test_the_toolbar_minimum_width_is_back_to_pre_m7 to `<= 800` with a docstring citing spec §4.1 (measured 766 with the Slice band button), and Task 2 must re-measure and tighten it to its own measurement rounded up to the next 10 px — keeps the branch green and the guard meaningful — cost if wrong: one task with a loose bound.
Ruling R6 (plan-mandated I2): strengthen both band tests as the reviewer proposes (assert the shift of the drawn window: +12.0 for 18→30, +1.0 for 18→19; and the band is still drawn right after close(), before the second emit) — spec §4.2 singles out "keep storing while hidden"; the plan's width-only assertion can't detect losing that — cost: none.
Ruling R7: M1 enters the fix round, not deferred — the plan's Review Focus 4 requires "bad value overwritten on the next choice ... Task 1 for the band", so it is a missing plan requirement; add the stored-"false"-string → unchecked test and a toggle-writes-a-bool test.
Task 1: minor (deferred): M2 — _refresh_velocity's KeyError and Exception branches repeat the two clearing lines; the KeyError comment no longer fits ordinary lines.
Task 1: fix round 1/5 (4 addressed, 0 open — red branch, weak band tests, band persistence pins, #14 RED evidence; commits 7a72d43..02f4471)
Task 1: complete (commits efbdc4e..02f4471, review clean)
Task 2: dispatched (BASE 02f4471, implementer a81efede79d60a1ab, sonnet)
Task 2: implementer DONE at 198fb1d (toolbar min 684, bound 690)
Task 2: review (02f4471..198fb1d): ✅ spec, Approved; ⚠️ Qt6/CI and view-level RED unobserved (CI check below).
Task 2: minor (deferred): fit_menu tooltips hidden (QMenu.toolTipsVisible off) — spec §4.3 "tooltips say what each keeps"; one-line fix.
Task 2: minor (deferred): worst-case toolbar test's velocity_label.text() assert can't fail (ElidedLabel.text() is full_text); check toolTip when elided instead.
Task 2: minor (deferred): worst-case test and the 690 pin measure with "Fit" on the button, not the wider "Fit height".
Task 2: minor (deferred): stale docstring at test_plugin_profile_dock.py:546 ("fit_button.clicked is wired straight to ProfileView.fit").
Task 2: minor (deferred): no pure test for fit_height on a mirrored ruler or with negative t0.
Task 2: minor (deferred): ProfileView.fit_width/fit_height wired to QAction.triggered without try/except (fit() precedent).
Task 2: complete (commits 02f4471..198fb1d, review clean)
Task 3: dispatched (BASE 198fb1d, implementer aad78fd06913e57c3, sonnet; carries R1)
Task 3: implementer DONE_WITH_CONCERNS at 922a7be — real_data had skipped (worktree lacked the data links); controller linked packages/nsgeo-core/tests/data/local/* from the main checkout (as other worktrees do) and re-ran: 52 passed at 922a7be.
Note for later briefs: real-data now runs in this worktree.
Task 3: review 1 (922a7be): ❌ / Needs fixes — I1 (plan-mandated) clamp test reaches neither clamp; I2 1:1 enabled with no line / after clear (no sync in __init__ or _clear_view_only); I3 R1 non-finite half untested; I4 helper-pair docstring lacks the M17c sentence (§4.7).
Ruling R8 (I1, plan-mandated): replace the clamp test with the reviewer's two clamp-hitting cases asserting the spans equal the minimums (0.8 ns; 4.0 traces) — Review Focus 5 says the minimums win; the plan's inputs cancelled out — cost: none.
Ruling R9: pull the minor "1:1 goes stale after pan/zoom" into this round — it follows from R1 (can_true_scale now depends on the window); fix by syncing on view.view_changed — cost: one more connection.
Task 3: minor (deferred): true_scale (a slot) has no try/except; same precedent as fit_width/fit_height.
Task 3: minor (deferred): fallback narrowing uses the old window's average metres/trace — approximate on uneven GPS spacing; exact via trace_units_at_metres (M17c note).
Task 3: minor (deferred): set_axes still converts via bounds_on, outside the pair (§4.7 "every conversion").
Task 3: minor (deferred): helper-road tests only check calls, not that outputs follow; trace_units_at_metres for tick positions unpinned.
Task 3: minor (deferred): no view/dock-level test of the record-height fallback at Fit on a long line (§5).
Task 3: minor (deferred): mirrored view test doesn't check px/m agreement on the mirrored ruler.
Task 3: minor (deferred): 1% tolerance vs §5 "within one pixel"; helpers typed Any and return 0-d ndarray for scalars (Task 5 told); slope guard untested; can_true_scale docstring omits R1.
Task 3: fix round 1/5 (5 addressed, 0 open — clamp test, 1:1 greyed with no line, non-finite R1, M17c docstring, sync on view_changed; commits 922a7be..eeaa3b4)
Task 3: complete (commits 198fb1d..eeaa3b4, review clean)
Task 4: dispatched (BASE eeaa3b4, implementer aa13e03e44291060a, sonnet)
Task 4: implementer DONE_WITH_CONCERNS at c1803d5 (44683f6 re-pin, 2b46e34 feat, c1803d5 style); re-pinned test_depth_axis_uses_the_velocity_model per spec §4.6 (no depth ticks for t<0)
Task 4: review 1 (c1803d5): ❌ / Needs fixes — I1 axis menu tooltips invisible (QMenu.toolTipsVisible off), so §4.6's greyed-Depth "tooltip saying why" never shows; I2 test_depth_ticks_start_at_zero_on_a_shifted_clock passes on the old code (t0=-4 avoids the input).
Ruling R10: pull Task 2's deferred minor (fit_menu tooltips hidden) into this round — the same defect class as I1, a one-liner, and spec §4.3 "tooltips say what each one keeps" — cost: none.
Task 4: minor (deferred): strip presses skip _abandon_stale_cutoff_grab/_cancel_velocity_box (run them before the strip check).
Task 4: minor (deferred): _sample_ticks doesn't force whole-number ticks for records of <=3 samples.
Task 4: minor (deferred): stale "800x300"/"800px -> 1000px" comments in test_plugin_profile_view.py (:320, :1350).
Task 4: minor (deferred): test_a_velocity_click_on_the_axis_margin_adds_no_point now opens a real popup and never hides it; its comment names the wrong strip.
Task 4: minor (deferred): no test for a strip press in velocity or pick mode.
Task 4: fix round 1/5 (3 addressed, 0 open — axis menu tooltips, fit menu tooltips (R10), shifted-clock depth test; commits c1803d5..8335da5)
Task 4: complete (commits eeaa3b4..8335da5, review clean)
Task 2: minor (deferred) "fit_menu tooltips hidden" — FIXED in Task 4 round 1 (R10).
Task 5: dispatched (BASE 8335da5, implementer a9cd26fa7fa743a13, sonnet)
Task 5: implementer DONE at a6d72e3
Task 5: review 1 (a6d72e3): ❌ / Needs fixes (test-only) — I1 mirrored-line test expects the half-way metres, passes only by rounding; I2 cut test's greyed-1:1 assert never runs (cut has a velocity); I3 no test fails if the read-out isn't painted or painting raises (paintEvent swallows).
Ruling R11: pull M4 (clears-off-image test dodges the top/bottom-margin case that needs the inside check — user rule "tests that dodge the hazard"), M6 (stale hover after resize: re-check 0<=x<t.width in readout_text), M7 (one-line read-out part of the "monkeypatch the pair" test, spec §4.7), M8 (RuntimeWarning in test output from Task 3's inf-distance test: wrap the expected warning) and M5 (repaint only the top strip, and only when the read-out text changes) into this round — all small, each closes a spec or test-hygiene gap — cost: a slightly bigger fix round.
Task 5: fix round 1/5 (8 addressed, 0 open — mirrored metres, no-velocity cut, painted strip + log, off-image margins, stale hover, helper read-out, warning, narrow repaint; commits a6d72e3..0f1a2f7)
Task 5: complete (commits 8335da5..0f1a2f7, review clean)
Task 3: minor (deferred) M8-equivalent RuntimeWarning — FIXED in Task 5 round 1.
Task 6: dispatched (BASE 0f1a2f7, implementer a89793e8195cfe09e, sonnet)
Task 6: implementer DONE at 145135f (rule 1 also compares zero; no re-pins needed; top-stays-top test on an unruled line)
Task 6: review 1 (145135f): ✅ letter of §4.8 / Needs fixes — I1 (plan-mandated) a held zoom moves when an unloaded line's samples arrive: header-only axes (zero 0.0, radar clock) -> processed render hits the clock rule before rule 2, so the window lands by the line's zero, unlike an already-loaded line (probe: 39.35 vs 37.44).
Ruling R12 (I1, plan-mandated): accept — header-only axes are not a clock the user zoomed on (time zero spec §4.3 lists them as the wrong clock); add an internal flag set by _take_down_picture's call so the next _set_axes_holding from header-only axes skips the clock rule and falls through to rules 2/3 as before; signatures for Plan B unchanged; pin with the reviewer's probe as a test (first open of an unloaded line with time_zero, zoomed mid-record on a ruler, equals the already-loaded case) — cost if wrong: a header-only zoom that someone deliberately set would re-apply by numbers (today's behaviour).
Ruling R13: pull M1 (redundant `or 0.0` at the _render call) into the round — trivial, matches the brief.
Task 6: minor (deferred): the "whole record" test is written twice (carry_time_window and _file_window); a ViewTransform method would keep them in step.
Task 6: minor (deferred): rule 1's zero comparison has no test that fails without it (every new test also changes t0/n_samples).
Task 6: minor (deferred): the GPS test builds the bare fixture inline.
Task 6: note: channel switches on one key now keep radar times when channel zeros differ (consistent with §4.8; unverified whether channels share a key).
Task 6: fix round 1/5 (2 addressed, 0 open — header-only axes flag, rg.zero_ns; commits 145135f..87198d9)
Task 6: complete (commits 0f1a2f7..87198d9, review clean)
Task 6: minor (deferred): no test drives _show_steps_refused -> later render through the header flag.
Task 6: note (out of scope, pre-existing): unruled line after a header-only visit: rule 3 needs equal (n_samples, t0), so a record-changing step doesn't hold the zoom there.
All six tasks complete. Next: final whole-branch review (references/final-review.md).
Final review: dispatched (efbdc4e..87198d9, opus, ab20280be07db8838)
Final review (efbdc4e..87198d9): With fixes, no Critical. I1 picking Fit width/height widens fit_button and shifts 1:1 and Slice band 56 px; I2 set_axes's bounds_on bypasses the helper pair (spec §3.1: Fit width must read position from the one helper; plan gap). Minors m1 R12 flag too broad on a same-line take-down then render (probe 1.9 ns shift); m2 read-out shows over a view with no image; m3 greyed-1:1 tooltip wrong on a flat stretch; m4 read-out clipped from the left on narrow panels; m5 profile_view module docstring stale; m6 readout_text computed twice per move. Triage "fix before merge": the 690/worst-case measured at "Fit" (with I1), helper tests outputs-follow (with I2), strip press in velocity/pick mode test, m1.
Ruling R14: the user guide's 1:1 line is on main (docs/guide/getting-started.md, "1:1 shows one trace per screen pixel"), not only on nsgeo-help-pages as spec §3.1 assumed; F fixes that paragraph in this fix wave for Plan A's features (Fit menu, 1:1 true scale, Slice band, axis units, read-out) — otherwise main's guide is wrong once F merges — cost: a short doc edit.
Ruling R15: the fix wave takes I1, I2, m1, m2, m3, m5, the four "fix before merge" triage items, the stale docstring at test_plugin_profile_dock.py:546 and the worst-case tooltip assert (both in the I1 test file), and R14; m4 and m6 and the remaining "can wait" minors stay deferred — m4 doesn't bite at the user's 1361 px; m6 is measured cheap (110 µs) — cost if wrong: a narrow docked panel cuts the read-out's start.
Final fix wave: dispatched (base 87198d9, fixer afcd2d581af11a884, sonnet; findings in final-fix-findings.md)
Final fix wave: fixer DONE_WITH_CONCERNS (b908f70 I1, b036c03 I2, 9884a90 m2+guards+m5, 744dcb7 m3, 1ea1854 m1, f4bef8d R14 guide); toolbar minimum width 684 -> 740.
Ruling R16: accept the 740 px minimum — stable button positions across Fit picks (the user's M7 objection) outweigh 56 px of minimum width; the user's panel floats at 1361 and 740 is near the pre-M7 700 — cost if wrong: a docked Profile panel can't be squeezed below 740 px.
Final fix wave re-review (87198d9..f4bef8d): all findings ADDRESSED, no Critical/Important. Residual minors: (a) m1's rule-1 case — a same-line take-down that went through rule 1 (zero 0, same t0/n) still sets the header flag, so a following zero-changing edit moves the window (probe 39.35 -> 41.25); (b) Fit minimum width not recomputed on a font/style change (1:1 drifts 640->651->659 after a 1.25x font); (c) set_axes assigns _distance before ViewTransform.fit, which can raise on non-finite t0/dt (unreachable from real headers); (d) at 1361 px worst case the velocity label now always elides (306 of 316 px). Out of scope: bounds_on unused in production (second road, test-only now); true_scale_window_is_flat duplicates half of _true_scale_inputs.
Ruling R17: no second fix wave (skill rule); carry (a), (b), (c), bounds_on's removal and the shared metres-per-trace helper into Plan B as its first task ("Plan A follow-ups"), since Plan B edits the same dock/view code and builds on _set_axes_holding — cost if wrong: these stay open until Plan B's first task lands.
Ruling R18: (d) goes to the walkthrough as a question for the user (the full text is in the tooltip; the alternative is shortening the label) — cost if wrong: the label shows "v = 0.100 m/ns (Grid A, …" in the worst case.
Plan A: complete. CI and retirement next; Plan B to be written.
