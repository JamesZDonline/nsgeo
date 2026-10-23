# Final whole-branch review: findings for the one fix wave

Range reviewed: 61119b4..523d7f4 (the code; 87fcaa3..61119b4 is the spec and plan). Reviewer: opus. Verdict: ready to merge with fixes. The reviewer re-ran the branch's own tests in a scratch worktree (235 core + pure, 219 QGIS, all passing) and timed a curve drag through the assembled plugin on REAL_DZT[0] tiled to 463 × 6301: 67.3 ms per move on average, 72.0 ms at worst, against the ~120 ms budget.

## I1. The strip showed the previous line's band and cursor trace under the new line's curve

- Where: `profile_dock.py` `_push_headroom`, with `_show_line` and `_clear_view_only`.
- How: balance line A with a curve row selected, Apply to grid, then open line B before its profiles load. `_show_line(B)` sets `self.image = None` and calls `set_axes` from the header, so a transform exists. `ProcessingDock.rebuild` keeps the selected row, so `show_gain_strip(B's points)` shows the strip. `_push_headroom` returned early on `self.image is None`, leaving A's envelope, limits, t0/dt and cursor trace under B's curve. It corrected itself when B loaded, stayed if B's load failed, and survived a site close or line removal.
- Fix (1b0ed5b): `_push_headroom` clears the headroom when there is no image, and `_show_line` and `_clear_view_only` clear it when they drop the image. Tests open a curve-stack line B with no profiles while the curve row is selected, and close the site. The re-reviewer confirmed it through the assembled plugin.

## Minors raised in the same review

2. A cutoff drag now changes the brightness as the line moves, because the limit follows the cut record (spec call 11). Measured on FILE__001: 1.088×, 1.202×, 1.391× as the cutoff moved from 90 % to 30 % of the record, with or without a gain curve. A spec question, not a defect: put to the user as walkthrough check E4 (Ruling F4).
3. The cursor-trace test used a 0 dB curve, so it could not tell the displayed column from the bypassed reference's. Fixed: DEEP, plus a sabotage proof.
4. Spec §8.6 was half-tested: `_exit_preview`'s strip re-push had no test. Fixed, with a sabotage proof.
5. Spec §8.2's shallow-pixel check was missing. Fixed: a second real-data test raises only the deep point and checks the shallow rows' colour indices are unchanged (Ruling F3).
6. The guide did not say the curve now works without AGC (spec §7). Fixed (Ruling F2).
7. The display limit is recomputed on every drag move (4.5 ms). Within budget; deferred (Ruling F5).

## Deferred-minor triage

Every `minor (deferred)` line in `progress.md` was triaged "can wait", except the two test gaps folded into the fix wave (items 3 and 4 above). Two cosmetic deferrals rode along: `row_envelope` returns zeros for a zero-trace array, and the profile-dock docstring cites §3 correctly.
