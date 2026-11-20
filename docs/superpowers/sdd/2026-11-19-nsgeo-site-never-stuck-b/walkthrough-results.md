# Walkthrough results — session H (#193, #166, #75, #157)

The author's marks from the walkthrough page, read back from its database on
2026-11-20. Profile `ns_geo_site_stuck` (linked to the branch worktree), on a
copy of the Sunnyside survey; QGIS 3.44.

## First pass (branch head f09a418, 11:10–11:31)

| Check | Result | Note |
|---|---|---|
| ws-fine — Whole site at 0.02 m stays responsive | pass | The fill did not freeze anything; "Working out the colour stretch" froze the whole computer for about 60 s, then recovered. |
| ws-live — slider and thickness stay live mid-fill | pass | "They moved but didn't seem to affect the picture?" Expected: the picture is held until the landing, which draws at the depth and thickness the panel shows then. |
| ws-cancel — Cancel puts the picture's settings back | pass | |
| ws-floor — the 0.01 m floor | pass | |
| tg-kriging — This grid at 0.02 m (Grid6) | pass | |
| tg-mincurv — This grid at 0.02 m (Grid1) | pass | |
| no-picture — Cancel with nothing on the map | pass | |
| short-range — grids with a shorter time range | pass | |
| tick-untick — ticking grids while the site prepares | pass | |
| remove-mid — removing a grid mid-preparation | pass | |
| export — a fine-cell site export | **fail** | Export stayed enabled while an export ran; a click answered "an export is already running". The export itself ran, and the author cancelled it. |

### What the two notes turned out to be

- **The freeze.** The kernel log shows a global out-of-memory kill at the
  moment of the stretch: swap full, the desktop thrashing, until it killed
  `gvfsd-metadata` (2.5 GB, a GNOME leak). QGIS held 2.5 GB then. A memory
  probe on a copy at 0.02 m put the process peak in the colour stretch
  (1.40 → 2.04 GB), the same as before this branch: the site's stretch listed
  every window's slices, and `limit_over_slices` joined every finite value into
  one more array for clips that read 200 000 strided values. Fixed in 4a6f029:
  streamed, and the clip handed only the values it reads. Same limit (pinned);
  peak 1.81 GB.
- **Export.** Fixed in 7320f58: Export is greyed in both scopes while a
  GeoTIFF export runs, with a tooltip saying why, and comes back when it ends.

## Re-check (branch head 7320f58, after main was merged in)

| Check | Result | Note |
|---|---|---|
| rc-export — Export is greyed while an export runs | pass | |
| rc-stretch — the 0.02 m stretch | pass | No out-of-memory kill in the kernel log during the re-check. |
