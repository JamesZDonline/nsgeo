# Walkthrough results: #111 multigrid minimum curvature

Run by the author on 2026-11-10, on QGIS profile `ns_geo_multigrid` (this branch at
83a7459), with a second QGIS on the main-branch profile for side-by-side checks.
12 of 12 passed.

| Check | What | Result | Note |
|---|---|---|---|
| A1 | Let go of the depth slider at 0.05 m: sharp slice in under a second | pass | |
| A2 | Step one level | pass | |
| A3 | Colour stretch settles | pass | |
| A4 | Change a setting | pass | |
| B1 | Same slice side by side with main | pass | "They look the same" |
| B2 | Bowl and gaps, no artefacts | pass | "it looks great" |
| C1 | Export at 0.05 m, faster than main | pass | about 10 s (estimate, untimed) |
| C2 | Cancel an export | pass | |
| D1 | 0.1 m cell | pass | |
| D2 | 0.2 m cell still follows the depth live | pass | |
| E1 | Whole site with Grid 1 | pass | |
| E2 | Whole site at 0.2 m, side by side | pass | "It does show kriging preview for less than a second" |

E2 passing means the 1.4–2× slower solve at 0.2 m is accepted. The fallback to the old
solver at coarse cells is not needed.
