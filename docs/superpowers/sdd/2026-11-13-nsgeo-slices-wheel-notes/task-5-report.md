# Task 5 report: the panel fits Processing's minimum, opens without sideways scroll (#121, #50)

Commit b367c2e, pushed to origin/nsgeo-slices-wheel-notes.

## Step 1 measurements (offscreen, Noto Sans; site3 session, 60-char cube name, last slice, GB memory label with the over-budget suffix, long velocity text, all unfolded)

| Font | Processing min | Slices content min, grid | Slices content min, site | Rows over the rule (before) |
|---|---|---|---|---|
| 9 pt | 418 | 720 | 328 | grid: Source group 712 (included_label unwrapped), Position 395 inner (velocity_label) |
| 11 pt | 440 | 812 | 370 | same; Interpolation 419 (ok) |
| 14 pt | 480 | 1008 | 456 | same, plus grid Interpolation 514 > 480 (the "= x m" label beside the spin) |

Row widths (9 / 11 / 14 pt), grid scope: Source 712/804/1000, Position 199/221/266 (velocity_label row 395/466/610), Resolution 203/226/271, Interpolation 371/419/514, Display 293/329/399, status 55/63/80. Site scope: site_panel 268/299/373, Interpolation 320/362/448, Normalisation 233/247/286, Display 293/329/399. Site scope fit already; the cube combo was not counted in the unshown measure (AdjustToContentsOnFirstShow), but the shown guard test counts it.
Note: the Interpolation row did measure over, at 14 pt in grid scope only, so it was stacked (the brief's condition).

## Changes
- `slices_dock.py`: `included_label` and `velocity_label` word-wrap; Cube/Grid/Preset combos use `AdjustToMinimumContentsLengthWithIcon`, `setMinimumContentsLength(12)`; `legend_label` is now an `ElidedLabel` (a wrapped legend changed height with its text once the panel got narrower, which broke `test_the_refine_states_do_not_move_the_panel_under_the_wheel[wide]`); new `_OpensWideScrollArea` whose guarded `sizeHint` adds the vertical bar's width (#50).
- `finish_panel.py`: `form.setRowWrapPolicy(WrapLongRows)`, so a too-wide row stacks its label above its box.
- `test_plugin_slices_dock.py`: dropped `sizeHint().width() >= 280`; the legend wrap test became an elide test (min width, full text, tooltip).
- README: stale xfail sentence replaced.
- New `test_plugin_slices_width.py` with `width_fonts`, the fits guard (9/14 pt, both scopes, synthetic and real data; asserts the vertical bar is visible and maximum > 0, the dock width equals Processing's minimum, the long cube text and memory text are in the panel) and the opening test.

## TDD
RED (before any production change), `pytest test_plugin_slices_width.py`: 6 failed, 4 passed. Failing: grid scope at 9 and 14 pt (synthetic and real), and the opening test in both scopes (site: horizontal bar maximum 14 = the vertical bar's width, which is #50 itself; grid: 505). Site-scope fit passed already, as measured.
GREEN: 10 passed (real-data tests ran).
Mutation probes, each reverted: Interpolation wrap policy off -> 3 fail (grid 14 pt synthetic and real, opening grid); `included_label` wrap off -> 5 fail; `velocity_label` wrap off -> 5 fail; combo minimum contents 200 -> 5 fail. The scroll-area hint is covered by the opening test in site scope (RED above).

## Step 5 and suites
Step 5 existing layout tests green (minimum, indicator, refine_states, site_scope layout/width/wheel: 3 passed). Whole QGIS suite after the final edit: 2760 passed, 1 skipped (36 min under heavy machine load). Core plus pure: 1564 passed, 5 skipped (run before the last two test-only/legend edits, which touch no core or pure code). Ruff check and format clean. No refine flake appeared.
Step 7 skipped per Ruling 29; the controller checks CI Qt 6.

## Concerns
- `legend_label` is now elided rather than wrapped (cut at narrow widths, full text in tooltip); a small user-visible change beyond the brief's list, needed to keep the panel still under the wheel.
- The guard compares the dock at exactly Processing's minimum with the vertical bar showing; it passes on Qt 5 offscreen only so far (Qt 6 and CI font differences unverified).

## Fix round 1
Changes (tests plus one docstring):
- `test_plugin_slices_width.py`: after `addItem(LONG_NAME)` on the cube, grid and preset combos, a `StyleChange` event is sent to each so they measure it; a long Warnings entry (with a 40-character unbroken token) is set and the panel asserted visible; the data text is set again after show (a late real-data preparation rewrote the memory label once, flaky; now 3 clean repeats); new `test_the_opens_wide_scroll_area_makes_room_for_its_bar` (fixed-hint tall content, resize to `sizeHint`, no sideways scroll).
- `test_plugin_slices_dock.py` elide test: drops the vacuous `minimumSizeHint` assert; asserts `QLabel.text(label).endswith("…")` at 60 px, plus the tooltip.
- `slices_dock.py`: `_OpensWideScrollArea` docstring now says it adds the bar's width to the stock hint.
Revert checks (width file, 11 tests): cap removed entirely -> 5 fail (grid fit at 9 and 14 pt, synthetic and real, plus opening grid); minimum contents 200 -> same 5 fail; `sizeHint` override removed -> the new direct test fails (the premise assert, that a stock scroll area scrolls sideways, holds). All reverted.
Commands: `pytest -p no:xonsh` on the width file (11 passed, three times), and width + slices_dock + site_scope with `-k "width or legend or minimum or indicator or refine_states or layout or wheel or opens"` -> 43 passed. Ruff check and format clean.

## Fix round 2
- Warnings token 40 -> 90 characters (wider than the limit at 14 pt).
- Long names are added to the three combos with signals blocked (plus the StyleChange event), so the test starts no preparation or restore. The dock's own preparation is waited for (and the site engine in site scope) before any data text; one `_carry_data_text` at the end of `_loaded_dock`, the second carry after show dropped; its docstring fixed.
- Width file whole, three runs: 11 passed each. Elide test: 1 passed. Ruff clean.
- Revert check: Warnings labels set to `Preferred` -> 8 failed, 3 passed; reverted (tree clean except the test file).
