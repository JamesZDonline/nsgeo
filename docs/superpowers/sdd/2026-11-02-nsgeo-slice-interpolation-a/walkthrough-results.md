# Walkthrough results — slice interpolation, milestone A

Profile `ns_geo_interp` (a copy of `ns_geo` with `nsgeo_qgis` linked to the branch at 3d9116c). The user ran it from 2026-11-04 to 2026-11-05 on the Sunnyside survey. Results were read back from the walkthrough page's `results` collection on 2026-11-05.

**25 of the 26 checks passed. I1 was skipped** (the optional early Surfer comparison).

| Stage | Checks | Result |
|---|---|---|
| A Open | A1, A2 | pass |
| B Picture at defaults | B1–B4 | pass |
| C Smoothing | C1, C2 | pass |
| D Responsiveness | D1–D4 | pass, with notes |
| E This grid remembers | E1–E3 | pass |
| F Whole site | F1–F4 | pass |
| G Saved cubes | G1–G3 | pass |
| H GeoTIFF export | H1–H3 | pass |
| I Early Surfer read | I1 | skip |

## Answers to the walkthrough's questions

- **B2, Kriging or IDW:** "Kriging looks slightly less 'fuzzy' I think at least in this case it is better." Kriging stays the default.
- **B3, skipped lines:** no skipped line was filled in at the default 0.75 × spacing. The tooltip and guide wording stay as they are.
- **D2, the wait at a fine cell:** This grid at 0.05 m worked, and the wait was accepted. Weight building stays on the main thread, with no QgsTask follow-up.
- **D4, smoothing speed:** "Its fine on a small single grid, its a little slow on the whole site, but usable, and 0.5m smoothing is pretty extreme at these settings." Speeding up smoothing is not the next fix.

## Notes that became issues

- **D1:** Shift+wheel moves the depth by one Step (about two levels here), while dragging the slider moves one level. Filed as #109.
- **D2, Whole site at 0.05 m was refused.**
  - On Sunnyside the site lattice comes to 2,582 × 3,035 = 7.84 M pixels at the half pitch of 0.025 m. That is over the `MAX_FRAME_CELLS` limit of 4 M.
  - Without Grid8–10 it is 3.55 M pixels, which fits.
  - The limit was borrowed from the per-grid fill weights (site spec §4.7). Both the limit and the refusal were already in 0.2.0, so this is not a regression.
  - The user could not follow the toast's wording.
  - Filed as #107: a plain-language reason, a limit sized for the site lattice, and a coarser preview instead of a refusal.
  - Filed as #108: export at a finer cell than the preview, streamed, with a COG option, for sites of around 120 × 120 m.
  - A sparse lattice was declined, because big gaps between grids are expected to be uncommon.
