# Walkthrough results: a grid velocity from its fits

Walkthrough: https://claude.ai/artifact/WBbG6CkcbiYPtPNq6WxQsg. QGIS profile `ns_geo_velocity_fixes`,
branch `nsgeo-grid-velocity` at 1eb2232. Run by the author on 2026-11-13.

**23 passed, 1 skipped, 0 failed.**

| Check | Result | Note |
|---|---|---|
| A1 Measure fits across the grid | pass | |
| B1 It opens the grid's own velocity dialog | pass | |
| B2 Sorting by a column | pass | |
| B3 Ticking changes the average | pass | |
| B4 A click beside a tick box is not a pick | pass | |
| B5 Picking one fit | pass | |
| B6 Apply an average to the grid | pass | |
| B7 Reopening remembers the fits | pass | |
| B8 An untouched Apply changes nothing | pass | |
| B9 Fits that disagree | pass | Future issue: selecting a row should show that hyperbola on its profile, to review suspicious fits. |
| C1 Starred lines are left alone | pass | |
| C2 A line dialog opened and applied untouched | pass | |
| C3 Averaging one line's fits | pass | |
| D1 Deleting a fit the grid's velocity used | pass | |
| D2 A Time zero change on a member's line | skipped | Optional; the data did not allow it. Covered by tests. |
| E1 The Slices label names the grid's velocity | pass | |
| E2 The first line's own velocity does not reach the slice | pass | |
| E3 A new grid velocity relabels the slice at once | pass | |
| E4 Whole site follows each grid | pass | |
| F1 Apply to grid after Save remembers the fit | pass | |
| G1 Edit grid left open does not undo a newer velocity | pass | |
| G2 Typing a velocity in Edit grid | pass | |
| H1 The remembered fits survive save and reopen | pass | |
| H2 0.4.0 refuses the new file (data-loss relevant) | pass | |
| I1 Both dialogs at your usual window size | pass | |
