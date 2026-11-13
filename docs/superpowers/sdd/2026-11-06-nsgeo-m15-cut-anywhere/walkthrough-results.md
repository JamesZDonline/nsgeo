# Walkthrough results — M15, cut anywhere

Run by the user on 2026-11-12, profile `ns_geo_cuts`, page https://claude.ai/artifact/HSmPLnZSxt4FD1tGUQWEV2 (db `results`), at branch head 7c422f9.
Result: 13 pass, 2 skipped, no fails. Data: a copy of the Sunnyside site (`~/nsgeo-m15-walk/`, the two site files only), Grid 1 at 0.05 m, minimum curvature, max distance 0.5 line spacings, preset `try1`.

| Check | What | Result | Note |
|---|---|---|---|
| D1 | Draw a cut along the lower line; first preview | pass | Sign-off: the 0.9 s first preview (1.4 s after a settings change) accepted. |
| D2 | Kriging → minimum curvature in the background | pass | Asked whether this was before the solver speed-up. It is after: #111's multigrid is already in. Sign-off on 2026-11-12: "a bit slow, but we'll live with it for now. Make the issue though." → #169. |
| D3 | The lower line's depth against the bowl | pass | "It's at exactly the level" — the lower line ends at the level of the bowl's top. |
| D4 | The cut agrees with the slice and a crossing line | pass | |
| D5 | The current layer decides what the map follows | pass | |
| D6 | Backspace, Esc and Enter in the Cut tool | pass | |
| K1 | Picks on a cut | pass | |
| K2 | Redraw, delete the old cut, keep its picks | pass | "I'm wondering if a tool somewhere to 'delete orphaned cuts' would be useful. Not needed now" → #170. |
| T1 | The axis is on the cube's clock | pass | |
| T2 | A pick made on the other clock is left out and counted | skipped | The step "disable Time zero in preset try1" had no way to do it: editing the selected preset in place only marks Slices stale, with no button to prepare again. The page was rewritten to copy `try1` without Time zero and switch presets; not re-run. Covered by automated tests (Task 5b A6). |
| G1 | A grid edit moves the cut and its picks | pass | |
| G2 | Whole site and round trips | pass | |
| G3 | A CRS change keeps the cut and its picks | skipped | No note. |
| G4 | Open site… asks to save; save and reopen | pass | |
| G5 | main's build refuses a schema 2 site | pass | |

**After the walkthrough:** the author asked for a PR to start using cuts and decide later what to change. T2 and G3 were not run by hand.
