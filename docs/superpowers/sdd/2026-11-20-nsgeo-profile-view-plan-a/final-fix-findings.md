# Final review of Plan A: the fix wave's findings

These come from the whole-branch review of efbdc4e..87198d9. One fixer handles all of them. Each must be fixed and pinned by a test that fails before the fix, unless the item says otherwise.

The reviewer's probe script has useful setups: /tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/f533ded0-1c84-4028-92d1-2b1d7d17a25c/scratchpad/plan-a-final-review-probes.py

## I1. Picking Fit width or Fit height moves the 1:1 and Slice band buttons 56 px right

**Where:** `profile_dock.py:416–428` and `_on_fit_picked` (about :1982).

**What happens.** At 1361 px, picking Fit width or Fit height widens `fit_button` from 48 px to 104 px. That moves 1:1 from x 530 to 586 and Slice band from 576 to 632, and they stay there until the next pick. The user has objected before to buttons in this row shifting (M7 walkthrough).

**Fix:**
- After the menu is built, give `fit_button` a minimum width equal to its widest state. For example, set each action as the default in turn, take the largest `sizeHint().width()`, then restore Fit as the default.

**Tests:**
- 1:1's and Slice band's x positions don't change across picks of Fit, Fit width and Fit height (use `QTest.qWait(50)` before reading geometry).
- Re-measure `test_the_toolbar_minimum_width_is_back_to_pre_m7` (currently `<= 690`). Tighten it to the new measurement, rounded up to the next 10 px, and update the docstring.
- In `test_the_toolbar_fits_the_users_panel_in_the_worst_case`, measure with the widest button text: trigger `fit_height_action` first.
- In the same test, its `velocity_label.text() == <full text>` assert can't fail, because `ElidedLabel.text()` is always the full text. Replace it with something that can fail:
  - at a width where the label elides, assert `velocity_label.toolTip()` is the full text; or
  - when there is room, assert `QLabel.text(dock.velocity_label)` is the full text.
- Also fix the stale docstring at `test_plugin_profile_dock.py:~546`. It says "`fit_button.clicked` is wired straight to `ProfileView.fit`", but the click now runs the button's default action.

## I2. The trace↔metre helper pair is not yet the only route (spec §3.1, binding)

**Where:** `profile_view.py:~226` and `~237`. `set_axes` computes the ruler bounds with `bounds_on(ruler, distance)`, which calls `trace_units_at` directly.

**Why it matters.** Those bounds are `trace_bounds`, which is what Fit and Fit width show. Spec §3.1: "The bottom axis, the read-out, Fit width and 1:1 must all read position along the line from one helper, so M17c can swap traces for distance in one place."

**Fix:**
1. In `set_axes`, assign `self._distance` before the ruler block (after the `dt_ns` and shape checks).
2. Compute the bounds through the pair: `lo, hi = sorted(float(self.trace_units_at_metres(m)) for m in (ruler.lo_m, ruler.hi_m))`, inside the existing errstate.
   - Check that this equals what `bounds_on` gave. Read `bounds_on` in ui/ruler.py first: if it does more than convert the two ends, keep its extra logic but route the conversion through the pair.
   - Make sure the "non-finite or degenerate → drop the ruler" check still works.

**Tests:** strengthen `test_the_metre_helpers_are_the_only_road` (test_plugin_profile_view.py:~2141) and its sibling so the OUTPUTS follow a monkeypatched pair, not just the calls. For example, patch the pair to scale metres by 2 (and the inverse by 1/2), then show that:
- the tick labels change;
- `trace_bounds` on a fresh `set_axes` with a ruler follow the patched pair;
- `window_m` follows.

## m1. R12's header flag is too broad: a same-line take-down then render moves the window by the line's zero

**Where:** `profile_dock.py:~958` (`_take_down_picture` sets `_axes_from_header = True`) and `~679` (the clock rule).

**What happens.** `_take_down_picture(key)` can follow a successful render of the SAME key, for example through `_show_steps_refused`. In that case:
- the clock rule rightly fires, and the header axes keep the radar times;
- but the flag is then set True, so the next render skips the clock rule, and rule 2 re-applies the filed numbers onto the processed clock.

The probe: a line with time_zero (zero 1.906 ns), zoomed mid-record, then `_show_steps_refused`, then `_render`. The radar window went from (45.84, 55.84) to (47.75, 57.75).

**Fix.** Set `_axes_from_header = True` only when the take-down did NOT go through the clock rule. That is the case where the header axes came from another line or from nothing, not from carrying the same line's processed window. One way: `_set_axes_holding` records which rule fired. Another: `_take_down_picture` checks `self._axes_key == key and not self._axes_from_header` before its call.

**Test:** the probe's sequence. The radar window is unchanged after take-down and re-render of the same line. The existing `test_a_held_zoom_does_not_move_when_an_unloaded_lines_samples_arrive` must stay green.

## Pin before Plan B edits `_handle_mouse_press`: a strip press in velocity mode and in pick mode

Spec §4.6 says: in velocity mode, right-click inside the image still discards a point, and a press on the strips opens the menu.

Add view tests:
- **Velocity mode on, left press on the left strip:** `axis_menu_requested` is emitted, and no velocity point is requested (`velocity_point_requested` not emitted, no box started).
- **Velocity mode on, right press inside the image:** it still reaches the discard path (`velocity_point_discarded` for a nearby point), and no menu request.
- **Pick mode on, press on the right strip:** the menu is requested, and `pick_requested` is not emitted.

These pin current behaviour, so they may pass on the current code. If they do, say so in the report; they are guards. No production change is expected.

## m2. The read-out shows over a view with no image

**Where:** `profile_view.py:~616`, `readout_text`.

**What happens.** While "loading…", it read "-1.67 m along (trace 100) · 44.35 ns · 1.77 m deep" on the header (radar) clock. Spec §4.7: "It shows while the pointer is over the image."

**Fix:** return "" when `self._image is None`.

**Test:** set axes but no image, hover the middle, and assert "".

## m3. The greyed 1:1 tooltip is wrong on a flat stretch (ruling R1's case)

**Where:** `profile_dock.py:~148`.

**What happens.** When the line has metres and a velocity but the window's metre span is zero or not finite (the radar stood still), the tooltip says "True scale needs metres along the line and a velocity".

**Fix:** add a third tooltip for that case, e.g. "True scale needs some distance along the line in view: this stretch was recorded standing still". `_sync_true_scale_button` picks the right one. You may need a small view method that says which input is missing.

**Test:** extend the flat-run test to assert this tooltip.

## m5. The profile_view.py module docstring is stale

It doesn't mention:
- the read-out;
- the per-axis units;
- that a press on an axis strip opens a menu.

Update it briefly, in the docstring's own style.

## R14. The user guide still describes the old 1:1

**Where:** `docs/guide/getting-started.md:~145`. It says "**Fit** shows the whole grid length, and **1:1** shows one trace per screen pixel."

That is now wrong on main, and will be wrong for users once this branch merges. Rewrite that paragraph's toolbar part for Plan A's features, in the guide's own plain style. Keep it short: a sentence or two each.
- **Fit** is a button with a menu (Fit, Fit width, Fit height). The button repeats your last pick.
- **1:1** shows true scale: a metre down as long as a metre along the line, at the line's velocity.
- **Slice band** hides or shows the slice's depth window.
- Click an axis to show it in ns, samples or m.
- The read-out above the profile gives the position under the pointer.

Read the surrounding paragraphs first and match their voice. Don't add headings.

No test is needed. Check whether a docs test pins guide text (e.g. a release-docs test) and run it if so.
