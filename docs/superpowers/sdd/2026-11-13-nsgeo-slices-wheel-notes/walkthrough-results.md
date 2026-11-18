# Walkthrough results: Slices panel wheel, typing, width and notes

Walkthrough: https://claude.ai/artifact/9NeVkfraXxnJf9sXHKb1a6. QGIS profile `ns_geo_wheel`,
branch `nsgeo-slices-wheel-notes`, with a copy of a multi-grid survey under `~/nsgeo-wheel-walk/`.
The author ran it in two rounds: round 1 on 2026-11-16 at the first built head, and round 2 on
2026-11-16/17 at d9e34bb, after the round 1 fixes.

**Round 2: every check passed except G1 (reading the guide), which was skipped.** Round 1 led to
three changes:

1. The click-first wheel rule was reversed (W1).
2. Cells now start at 0.1 m.
3. dz shows a note when it reaches its floor (D1).

The round 1 freeze (N1) was filed as #193.

| Check | Round 1 | Round 2 | Note |
|---|---|---|---|
| W1 Scroll past every box | pass | (R1) | "Having walked this behavior I've decided I don't like it. … re-enable scrolling by default, but keep the dropdown headers to hide it … set default cell size to .1m instead of .2m". Reversed: the Resolution boxes keep Qt's wheel (Ruling 40); the cell starts at 0.1 m (Ruling 41). |
| W2 Click, then wheel | pass | | |
| W3 Type a dz, then scroll the panel | pass | retired | Retired with the click-first rule. |
| W4 Tab into a box out of view | pass | retired | Retired with the click-first rule. |
| W5 Edit lines: the Grid column | pass | | "here the behavior feels right. Keep this!" Kept. |
| D1 The floor, and your remembered 0.1 | pass | (R2) | "at minimum, we should include a note about why it isn't allowed to go lower". Added *(sample interval)* beside dz at its floor (Ruling 42). |
| D2 A z range too deep, in This grid | fail | (D2b) | "Not under Warnings. Its in the toast and there's an error between the velocity". Could not be reproduced offscreen. Round 2's D2b asked for the toast's words. |
| D3 The same z1 in Whole site | pass | | The refusal ("Too many levels") showed under Warnings. |
| D4 Restore a saved cube from another grid | pass | | |
| T1 Type while the grids become ready | pass | | |
| N1 The preview note in full | froze | retired | "It froze QGIS." The freeze is older than this branch: about 105 s on the GUI thread working out the kriging fill for Whole site at a 0.02 m cell. The author chose to file it: #193. |
| N2 The clock warning | | pass | "We should make it so you can select the preset directly from the Source table on the whole site tab. That may be a new issue." Offered, not filed. |
| N3 Wheel a focused cell across the preview threshold | | retired | Retired with N1. |
| R1 The wheel is back on the Resolution boxes | | pass | |
| R2 dz says why it stops | | pass | |
| R3 A grid starts at a 0.1 m cell | | pass | |
| D2b D2 again: a z range too deep | | pass | The toast did not come back. |
| F1 Fold, switch scope, restart | | pass | |
| F2 A header click while typing | | pass | |
| P1 A narrow panel | | pass | |
| P2 Docked alone, and floating | | pass | |
| C1 The coverage tooltip | | pass | |
| G1 The guide | | skipped | The guide's Slices steps were not read by hand. |

After round 2, origin/main (f5fe6c7, carrying #194's processing step edge cases and Trace stack)
was merged into the branch. While checking the suite, #196 was filed: two refine tests that flake
under load, a fault in the tests and older than this branch.
