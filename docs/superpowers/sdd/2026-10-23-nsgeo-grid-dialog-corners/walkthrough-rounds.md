# Walkthrough — grid dialog (#27, #28, #62, #63)

Page: https://claude.ai/artifact/2aTBdNxocttY9ZatJ5EBdF (db collection `results`, 36 checks in stages A–H).
Build: branch `nsgeo-grid-dialog` at `4c59f12` (main 6402d59, the #79 field fixes, merged in), deployed to a new
QGIS profile `ns_geo_grid` (a copy of `ns_geo`, symlinked to the worktree). A headless QGIS 3.44 run confirmed the
plugin loads in that profile. Linux, QGIS 3.44.

## Round 1 — 2026-10-23

Marked on the page: 24 of 36 — 23 pass, 1 skipped, 0 fail.

- **Pass (23):** A1–A3 (set-up, one table, CRS picked for a 4326 project), B1–B8 (picking with snapping, Pick all,
  points over vertices, free clicks, a double-click in Pick all, snapping latency, focus after a pick), C1–C5
  (Fit, rounding the size, a typed size surviving Fit, Use these, the saved grid lining up with the GPS points and
  overlays), D1–D7 (pick a polygon on the map, Fill, Rotate, Rotate on a non-square grid, comparing fits, mixing
  sources, picking inside an existing nsgeo grid).
- **Skipped (1):** E1 (a comma decimal in a cell).
- **Not marked (12):** E2–E4 (degrees typed under a UTM Corners in while editing an existing grid; a half-filled
  row; swapped rows), F1–F5 (the grid's CRS), G1–G3 (overlay look, closing, pan and zoom), H1 (save and reopen).
  E2, F3, F4 and H1 are tagged "could lose data"; E2–E4 and F3/F4 are pinned by the QGIS-tier tests and by the
  final review's probes re-run on the fix wave.
- No notes were written, so the "your call" questions (B6 double-click, B7 latency, B8 focus, D4 Rotate on a
  non-square grid, D5 fit comparison, D7 nsgeo's own layers, G1 overlay colours) have no answers beyond the pass
  marks. G1 was not marked: the overlay keeps its built colours.

The user's verdict: "walkthrough looks great. go ahead and make the pull request and merge. If I come across any
issues as I work with real data I'll make issues for them." Merged on that go.
