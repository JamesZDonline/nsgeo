# M17b walkthrough results

Walked by the author on profile `ns_geo_m17b`, 2026-11-20 (UTC), on the two real GPS surveys, a
hand-on copy of the first one with two DZGs left out, and an M17a site with ten GPS lines on no grid.
Page: the M17b walkthrough artifact. Version 2 added the re-checks R1–R3 after the fix round.

| Check | Result | Note |
|---|---|---|
| W1 One Add data menu | pass | |
| W2 The first survey into a new grid, by GPS | pass | The Grid / GPS buttons widened and jumped when the GPS note hid → fix (R1). The fitted size was 29.8 × 31.8 m; typing a size (say 30 × 30, perhaps with "stretch or compress each line to grid length") might help — the author will experiment and report. Asked to choose the CRS, not only take the suggested one → #231. |
| W3 The new grid and its lines | **fail** | "I don't understand how the grid boundary was calculated. I think grow the grid to hold every trace. Why throw away data?" → fix (R2). |
| W4 Slices of the GPS grid | pass | Gaps fill by raising the maximum distance to data, as the author wants. |
| W5 The second survey into an existing grid | pass | Answer: from the toolbar, GPS mode should always start on New grid → fix (R3). |
| W6 Files GPS cannot place are handed on | pass | Answer: keep Direction and First line at hidden. Asked to draw where each line will go on the map and highlight the selected rows → #230. "Very slick though overall." |
| W7 The tape import through the same dialog | pass | |
| W8 GPS rows in Edit lines | pass | Asked for Measure stagger on GPS rows (the destagger work started from the GPS surveys) → moved into M17c. |
| W9 Editing the grid leaves GPS lines in place | pass | |
| W10 M17a's lines into grids | pass | |
| W11 Save, close and reopen | pass | Reversed GPS lines are not mirrored in the profile ("we need to fix it") → shared rulers moved into M17c. |
| R1 The switch stays put (W2) | pass | |
| R2 The fitted grid holds every trace (W3) | pass | |
| R3 GPS from the toolbar starts on New grid (W5) | pass | |

## Fixes after the walkthrough (1426aa7)

- **W2:** the mode switch keeps its place: a stretch after the GPS note, so the buttons never widen.
- **W3:** `fit_frame`'s cross edges sit half a spacing outside the outer along lines, or further where
  any trace lies beyond that, so every trace is inside and none is left out of the slices. The Fitted
  line reads "…, lined up with the lines, holding every trace" and has a tooltip saying how the
  rectangle is drawn. On the real surveys every trace is now inside: 29.83 × 31.93 m and
  30.08 × 31.08 m. Spec §6.3 and §16 carry the new rule.
- **W5:** Add data from the toolbar opens GPS mode on New grid; Grid mode still opens on the Survey
  panel's grid, and a grid's own Add GPR data… opens both modes on that grid. Spec decision 15
  carries the note.

## Decisions the author made during the walkthrough

Recorded in the spec (`docs/superpowers/specs/2026-11-06-nsgeo-gps-lines-design.md`, §9) and the
README roadmap:

- Shared rulers (mirrored reversed GPS lines, decision 8 / C8) and Measure for GPS lines move from
  M17d into M17c, beside true-distance profiles (51993c0). M17c may need two plans; M17d keeps
  outlines with holes and Place by GPS.
- Filed for the wishlist: #230 (Grid mode draws where each line will go on the map, highlighting the
  selected rows) and #231 (choose the coordinate system in GPS mode).
- Each mode keeps its own Target grid across a switch (the W2 question went unanswered; Ruling 12
  stands).
