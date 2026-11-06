# Walkthrough rounds — #67

Page: https://claude.ai/artifact/1sUxpNcYLzmA3TTtBbDURF (db collection `results`, 18 checks).
Build: `nsgeo-grid-profiles` at 2ddd7f4, QGIS profile `ns_geo_zigzag`, the user's real Sunnyside site.

## Round 1 — 2026-10-31: 18 pass, 0 fail, 0 skip

The three "your call" questions (B3 hatch readable, D2 keep the sideways zoom when `time_zero`
changes, E2 Fit after a grid edit shows the new length) passed with no note, so the build's
behaviour stands.

B3 note: on Grid 5 the second (reversed) line started ~0.8 m in and overran the grid's far side by
~1 m. Diagnosis from the site file: all 15 reversed lines on Grid 5 have `start_along` 16.0 while
the grid is 15.0 m long (every other grid's reversed lines start exactly at its length). Forward
lines run 0 → 15.07–15.13 m; starting the reversed lines at 15 m would give them the same ~0.1 m
overshoot at 0, so 15 is right. A pre-existing placement error: the grid was most likely 16 m when
those lines were imported, and a line's start is stored as a fixed number that a grid edit doesn't
move. The new ruler made it visible; slices and the map lines use the same positions. The user
confirmed ("I just hadn't noticed") and asked for the PR and merge. Not a #67 defect; editing line
placements after import is #29.
