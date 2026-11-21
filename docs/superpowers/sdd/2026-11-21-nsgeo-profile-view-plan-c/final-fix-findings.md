# Plan C final review findings (opus a0695bd138d738ad2, range 773e84e..1db1f02) — ONE fix wave

Verdict: Ready to merge with fixes. Task 3 task-level: spec ❌ / Needs fixes (I1).

## I1 (Important) — the selection length vanishes when the drag leaves the image
profile_view.py:672 `readout_text` returns "" on `self._hover is None` BEFORE the W5 branch (:674). `_handle_mouse_move` sets `_hover = None` whenever the pointer is outside the image rect (:1224), while the selection drag keeps updating (traces_between clamps). Reviewer probes on head: drag from trace 20 to 15 px past the right edge → `_selection == (20, 199)`, read-out ""; drift 4 px up into the top strip → `(20, 77)`, read-out "".
Fix: keep `if t is None or self._image is None: return ""`, then the W5 branch, then `if self._hover is None: return ""` (and the existing stale-bounds check after it).
Test (write first, RED on head): on `_imaged`, drag from trace 20 to past the right edge → "2.98 m selected (trace 20–199)" (confirm the number the fixture really gives); drift up into the top strip mid-drag → still "… selected (trace 20–77)" (or whatever trace the pointer clamps to — read `_selection`); release outside the image → "".

## M1 (Minor, fix) — release doesn't repaint the read-out strip
profile_view.py:1366–1405: on the `_press` release branch, when `_dragging` was True, call `self.update(QRect(0, 0, self.width(), MARGIN_TOP))` (or whatever rect `_paint_readout` uses — check) so "… m selected" doesn't stay painted when no selection echo comes back (re-dragging the identical range; a previewed line). Test if practical: count/observe an update of the strip on release, or assert via a paint spy the existing tests use; if no clean way to test it, say so in the report.

## M2 (Minor, fix) — ragged wrap in docs/guide/getting-started.md:~152 ("length of the stretch while you drag a selection. The") — rewrap the paragraph to ~80 columns like its neighbours.

## Ledger minors (fix)
- Z1: pin the zero_ns term of the first-row guard in profile_dock.py current_radargram. A mutant comparing `bypass.t0_ns - received.t0_ns` only survives all tests. Reviewer's probe that kills it and passes on head: stack `[time_zero(sample=20), dewow, time_zero(sample=0)]`, `set_selected_step(0)`, assert `dock.image.rg.data` equals `stack.result_bypassing(0).data`. Add to test_plugin_profile_dock.py near the other bypass tests; prove it kills the mutant (apply, run, restore).
- Z2: `_scale_reference` docstring (profile_dock.py:~2281) still says "(just `result()` when there is none)": rewrite so it says the Time zero row is bypassed too while its bypass is drawn, and a fallback input view is its own scale.
- Z3: `test_the_line_shows_only_in_sample_mode_while_selected` docstring (test_plugin_profile_dock.py:~2967) "on the record it receives" → the bypass wording.
- Z4 (only because the file is touched): add `cutoff_ns ≈ 0`-style assertion (row 20 reads 0 on the drawn clock) to `test_a_cutoff_after_time_zero_still_draws_the_bypass`, using whatever the sibling test uses (transform t0 / shown_zero_ns).

## Done by the controller (not yours)
- M3 spec superseded notes: committed.

## Left (rulings)
- Cutoff end_ns above the line's zero: clamps, no crash, accepted by §4.14.
- Selection following the pointer after a lost left release: pre-dates Plan C.
