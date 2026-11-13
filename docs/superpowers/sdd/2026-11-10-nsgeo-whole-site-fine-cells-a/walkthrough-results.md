# Walkthrough results — whole site at fine cells, milestone A

Run 2026-11-10 by the author on the real ten-grid survey, QGIS profile `ns_geo_finecells` (a copy of `ns_geo` linked to this branch at 19edbcf). Page: https://claude.ai/artifact/GG3QQa5Jnqy8B2gimGUqpH (db collection `results`).

| Stage | Checks | Result |
|---|---|---|
| A Open | A1 | pass |
| B This grid, zoomed in | B1–B4 | pass |
| C Whole site at 0.05 m | C1–C3 pass, C4 skipped | C4 (0.025 m, optional and slow) not run |
| D Forced preview | D1–D6 | pass (D1 left unmarked; see below) |
| E This grid export | E1 | pass |

**D1.** The first attempt "nothing seemed to happen": the author had missed the step that changes the cell to 0.06 m, so the site was never rebuilt with the lowered limit. Following the step, a console check showed the preview drawn at 0.12 m and the note visible: "Preview at 0.12 m pixels: the grids are at 0.06 m, but the site (65 × 76 m) is too big to draw at full detail. It draws in full at a 0.11 m cell or coarser." No grid was named, because no single grid lifts the limit on this site.

**Answers and notes.**
- B3 (does the blend look right at the measuring zoom), B4 (is QGIS's colour blending acceptable on the coverage view), C2 (scrubbing at 0.05 m): passed with no comment.
- D2: the note is too long to read in the panel without hovering, and its place is questioned: "leave it for now". The author asked whether milestone B fixes it. It does in part: B's export can write a preview site at full detail, so the export refusal in the tooltip goes away. The preview note itself is not in B's scope as designed.
- D5: "I really don't know what coverage is supposed to be showing me... but that's not a problem for this set of work." D5's question (fix the edge-line gap at previews of 8× or coarser before merge?) was not answered, so it is treated as a follow-up unless the author asks for it before the merge.

The automated test that drives the same steps passes. A plain-language explanation of the coverage view belongs in the guide or the help pages.
