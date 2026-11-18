# M16 Plan B walkthrough — results

Run by the author on 2026-11-13/14 and 2026-11-16, on this machine, profile `ns_geo_m16b` (the plugin linked
to the branch's worktree), on a copy of the Sunnyside site. Branch at 27b64b5 (first session), 61b0192
(after walkthrough fix round 1) and c4f6ab1 (after fix round 2). Page:
https://claude.ai/artifact/F28g21EyShVcDjT4jHy9Kx (15 checks, results in its database).

The author's surfaces differed from the page's "Bowl": they built "Feature1" (90 picks), an "all" surface
from 163 picks, and "feature1_small".

## Results

| Check | Result | Author's note |
|---|---|---|
| S1 select the bowl picks and build | pass | First session: about 3 minutes with no kept fill; 54 of 88 within 2 cm, picks 3.7 cm above the strongest swing. |
| S2 the panel and the map | pass | |
| S3 an outlier leads to its pick | pass | "I don't see anything that looks wrong with the pick. What's a window mean in this context?" (answered in chat: the ±2 cm band around the shifted sheet in which the builder looks for the strongest swing). |
| S4 the other join | pass | Inverse distance: 49 of 90 within 2 cm on Feature1; back to smooth restores the fit. |
| S5 the two line features | skip | "the lines don't show up well. I may need to redo their picks" |
| E1 share a pick, delete a surface | pass | Rewritten after fix round 1 (a pick can be in several surfaces). |
| E2 selections that can't make a surface | pass | |
| E3 the scroll wheel leaves settings alone | pass | |
| T1 browsing slices doesn't make a surface stale | pass | |
| T2 exporting at the same settings doesn't either | pass | |
| T3 changing Grid1's 3-D settings does | skip | |
| P1 surfaces in the ParaView scene | pass | |
| A1 close without Save site, reopen | fail → fixed → pass | "they say stale now?" Fixed in round 2 (below); re-run at c4f6ab1 after rebuilding each surface once: pass. |
| A2 working speed | pass | |
| G1 the guide | skip | |

The author asked for the skipped checks (S5, T3, G1) to be left for this release; they will give feedback
after working with surfaces for a while.

## Fix round 1 — a pick in several surfaces (61b0192)

Building an "all" surface from 163 picks moved the bowl's picks out of Feature1 (Ruling R9: a pick belonged
to one surface). The author wanted to compare the bowl with the whole surface, so a pick may now belong to
several surfaces (Ruling R14: the picks table's `feature_id` holds a ";"-joined list). Build messages now
stay until closed. Reviewed (opus); one test that could not fail was fixed; re-review clean.

## Fix round 2 — A1, surfaces stale after a reopen without Save site (4eb2bec, c4f6ab1)

Both causes were confirmed on a copy of the author's site with a headless probe:

1. The `resolution` input hashed the grid's remembered 3-D record. A build remembers it in memory, but
   only Save site writes it to disk, so after a reopen without saving the record was empty and every
   surface read stale.
2. The `picks` input hashed each pick's stored time and time zero. #97 re-measures a line's older picks
   from its time zero when the line opens (19 picks on this site). That changes both numbers but not the
   radar time, so opening a line (A2, or S3's outlier click) made its surfaces stale.

Ruling R15: `resolution` hashes what a rebuild would use (`remembered_step`, `remembered_end`, shared with
the build), and `picks` hashes the radar time. One-time cost: each surface built before the fix reads "its
picks changed" once. Reviewed (opus): approved with fixes; a depth-step test was added (c4f6ab1). Whole QGIS
tier: 2586 passed.

Residual (offered as follow-ups, not filed):

- While a grid's 3-D record is unsaved, a reopen can still read stale if the Slices transform, the volume
  settings, or the panel's cell/step/end differ from the last build. A full fix stores each surface's 3-D
  choice and falls back to it when the grid's record is empty.
- The export dialog's cell spin keeps 3 decimals while a default cell can have more; building and then
  exporting with the dialog untouched then reads "resolution" stale. Grid1's 0.05 m cell is not affected.
