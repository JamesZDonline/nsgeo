# Final-review fix wave — display gain (#6, #10)

Branch docs/display-gain-design, worktree /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/display-gain-design, head 523d7f4.
Spec: docs/superpowers/specs/2026-10-21-nsgeo-display-gain-design.md. Plan: docs/superpowers/plans/2026-10-22-nsgeo-display-gain.md (read its Global Constraints and Verification commands; they bind this work).

Fix every item below, test-first where it is a behaviour fix (write the test, see it fail, then fix). Do nothing else.

## 1. (Important) The strip shows the previous line's band and cursor trace under the new line's curve

`profile_dock.py:966-967`, with `:458` and `:573`. Reproduced at plugin level by the reviewer:
- The user balances line A with a curve row selected, applies the stack to the grid, then opens line B before B's profiles have loaded.
- `_show_line(B)` sets `self.image = None` and calls `set_axes` from the header, so a transform exists.
- `ProcessingDock.rebuild` keeps the selected row, so `_sync_gain_strip` → `show_gain_strip(B's points)` shows the strip.
- `_push_headroom` returns early because `self.image is None`, so the strip draws B's curve over A's envelope, limits, t0/dt and cursor trace. It corrects itself when B loads, but stays if B's load fails, and the stale state survives a site close or line removal and returns on the next show.

Fix:
- In `_push_headroom`, call `self.gain_strip.set_headroom(None)` when `self.image is None`, instead of returning silently.
- Also clear it wherever `self.image = None` is set (`_show_line`, `_clear_view_only`), so the fix holds whichever slot runs first (ProfileDock connects before ProcessingDock today, plugin.py:224 vs 230).
- Test: open a curve-stack line B that has no profiles while the curve row is selected on A; assert `dock.gain_strip.headroom is None`. Also cover site close: after `close_site`/`site_closed`, headroom is None.

## 2. The cursor-trace test can't tell displayed from bypassed data

`test_plugin_gain_strip.py:1027` (`test_the_cursor_trace_follows_the_session_cursor`). The curve is FLAT (0 dB), so the displayed column and the bypassed reference's column are identical; a `_push_trace` reading `image.reference` would pass. Replace the curve with DEEP before asserting (spec §4.2.2: "the displayed data's column"). Prove it: temporarily make `_push_trace` read `self.image.reference`, see the test fail, restore.

## 3. `_exit_preview`'s strip re-push is untested (spec §8.6)

`profile_dock.py:656`. Add a test: strip shown with a gain curve selected on the working line, enter a preview of another line, `percentile_slider.setValue(950)`, clear the preview (`session.set_preview(None)`), assert the strip's envelope equals `row_envelope(dock.image.rg.data, 95.0)`. Prove it: temporarily delete the `_push_headroom()` call there, see the test fail, restore.

## 4. Spec §8.2's shallow-pixel check is missing

Keep the existing real-data test as it is. Add `test_raising_only_the_deep_point_leaves_the_shallow_pixels_alone` (`@needs_real_data`, `REAL_DZT[0]`, same stack as the existing real-data test in test_plugin_profile_dock.py): curve flat at 0 dB down to 50 ns then rising; record the limit and `to_index8(stack.result().data[:k], dock.image.limit)` for the rows before the curve leaves 0 dB; raise only the deepest point by 12 dB; assert the limit is unchanged and those shallow rows' indices are identical.

## 5. The guide doesn't say the curve now works without AGC (spec §7)

`docs/guide/getting-started.md`, the `gain_curve` bullet. After its first sentence ("…lets you drag its control points."), add: "It works on its own, without `gain_agc` before it." Keep the line wrapping style of the surrounding bullet.

## 6. Two small cosmetic items

- `nsgeo/render.py` `row_envelope`: a zero-trace array (`np.empty((3, 0))`) raises IndexError; return `np.zeros(n_rows)` instead, with a test.
- `profile_dock.py:25` module docstring: "(spec 3, calls 1 and 4)" should cite "§3", and call 4 (the Difference view) belongs to the sentence about the Difference view.

## Verification

Run the covering test files while iterating, then the whole qgis tier once, core + pure, ruff, ruff format --check, and mypy (exact commands in the plan). Commit (one or more commits), push (if the network refuses, say so; don't loop).
