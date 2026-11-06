# Walkthrough results — slice interpolation, milestone B (minimum curvature)

The walkthrough ran in profile `ns_geo_mincurv`, a copy of `ns_geo_interp` with `nsgeo_qgis` linked to the branch. The user ran it on the Sunnyside survey:

- **Round 1**, at bc76e49, on 2026-11-06 (UTC). Results were read back from the walkthrough page's `results` collection.
- **Round 2**, at 7f6175b, the same day.
- **A look at 2046c21**, after the round 2 change, the same day.

**Round 1:** 31 checks: 21 passed, 5 were skipped, 2 were left unmarked with notes, and the optional H3 was not recorded.
**Round 2:** all 4 checks passed. The user then approved the round 2 change by looking at it ("looks great").

| Stage | Checks | Result |
|---|---|---|
| A Open | A1, A2 | pass |
| B The picture | B1, B2 | pass |
| C Where it overshoots | C1, C2 | pass (C2 unmarked, note: no meaningful seams) |
| D Your usual cell | D1, D2 | D1 unmarked (the wheel problem, W1), D2 pass |
| E A fine cell | E1–E6 | pass, with notes (W2, W3) |
| F Whole site | F1–F5 | pass; F3 skipped (every grid is clipped at the same depth) |
| G GeoTIFF export | G1–G4 | pass; G4 skipped |
| H Remembered settings and cubes | H1, H2 (H3 optional) | pass; H3 not recorded |
| I Closing mid-refine | I1 | skipped |
| J Against Surfer | J1, J2 | skipped; **waived for B by the user** |
| K Round 2: the refine line | K1–K4 | pass |

## The user's verdict

"The differences between kriging and min curv at these settings are pretty minimal except for how long it takes to process."

- **B1:** "The difference is pretty minor, but Minimum curvature is just slightly cleaner looking."
- **C1, C2:** no noticeable edge banding and no meaningful seams on this survey. The final review's concern, that values past the outermost lines go beyond the data range, did not show at these settings. Tension is not needed now.
- **D1:** the user's usual cell is 0.1 m. "The kriging preview works really well to make it feel smooth and the closeness of min-curvature and kriging means it isn't jarring when the min-curv lands."
- **E6:** 0.05 m is "usable but not super fun. 111 isn't urgent, but it does still need to happen."
- **J, the Surfer comparison:** waived for B (user, 2026-11-06), and filed as a follow-up. Spec §10.2 made it a gate for B.

## Findings and fixes

- **W1 (D1).** With Minimum curvature, the mouse wheel over the depth slider was taken over by the panel's scroll area.
  - **Cause:** the word-wrapped status line at the bottom of the panel changed height as the state moved through preview, refining and normal. That re-laid out the scrolled panel and moved the slider out from under the cursor. Measured: 2/2/1 lines at 400 px and 2/3/2 lines at 260 px.
  - **Fixed** in 364b236 and afec059: a fixed-height indicator, with the bottom status line showing memory only.
  - **Layout tests** in both scopes fail with the old status line restored.
- **W2 (E1, E2).** The refine state was off-screen at the bottom of the panel, and its line jumped. Fixed by the same indicator.
- **W3 (E4).** "Refining … (0 of 9)" mixed the slice with the stretch windows. The slice and the stretch now have separate texts and counts.
- **K2 (round 2).** "That empty line looks strange when there's no text there." In 2046c21 the state moved onto the readout's own line, with shorter texts:
  - "Kriging preview"
  - "Refining…"
  - "Refining (k of n)…"
  - "Colour stretch (k of n)…"

## Left for later

- **Colour-stretch count clipping.** Right-elision drops the stretch count first in panels narrower than about 420 px at QGIS's font. The user approved the line as it is.
- **FinishPanel width.** FinishPanel needs about 330 px: its "Max distance to data" row is wide. So narrower panels scroll sideways and clip the indicator. This is a follow-up issue.
