# Milestone B walkthrough — results

Run by the author on 2026-11-11 (evening), on a copy of the ten-grid survey, profile
`ns_geo_export` linked to the branch at 551b237. Page: https://claude.ai/artifact/HSTEtjgo8v9VjV4W1VsLFp
(24 checks, results in its database).

## Results

| Check | Result | Author's note |
|---|---|---|
| A1 open | pass | |
| B1 the dialog | pass | "The Bands would be more useful in depth than in ns probably … (though I guess that's limited by the fact that different grids may have different velocities? nevermind...)" |
| B2 the memory refusal | fail → not a bug | "It says about 2.8GB … in the File description, but the export button still was clickable. At export pixel of .01 I get the warning and the export button block." |
| B3 limits on cell and pixel | pass | "Typing a 0.001 actually reverts back to whatever the existing value was, but that's fine." |
| C1 export at 0.025 m | pass | |
| C2 keep working meanwhile | pass | |
| C3 finished file | pass | "not sure there's a ton of difference now that we're doing bilinear interp" |
| C4 files on disk | pass | (Show coverage was off, so no companion was written; a later export with it on wrote one) |
| D1 live cell, finer pixel | pass | "It looks good, but I'm not sure how much difference it made" |
| E1 replace an open file | pass | |
| E2 cancel a replace | pass | |
| E3 Temporal Controller on the restored layer | skip | "I haven't had luck with the temporal controller. it seems like it isn't set up quite right somehow." |
| E4 re-export statistics | pass | |
| E5 close the site mid-export | pass | |
| E6 a second export refused | pass | |
| F1 fresh project, style file | pass | |
| F2 coverage zoomed out | pass | |
| F3 other GIS | skip | |
| G1–G3 a preview site exports | pass | |
| H1 This grid, rotated | pass | |
| Z1 120 m sites | pass | Accepted: follow-up #167 filed, spec decision A amended, README Wishlist line. |
| Z2 format keys | pass | `largest_count` and `NSGEO_WINDOW_NS` kept. |

### Stage T, after the fix rounds (2026-11-12)

Run by the author on the same profile, restarted on the branch at 111e999.

| Check | Result |
|---|---|
| T1 the Memory row | pass |
| T2 export: the Temporal Controller is on, one frame per band, in order | pass |
| T3 save, close, reopen: it steps the same, first band included | pass |
| T4 Add Raster Layer in a new project: it steps | pass |

## Findings

- **B2 is not a bug.** The 2.8 GB the author saw was the File row: 2,582 × 3,035 pixels at 0.025 m
  is 31.3 M pixels at 0.0125 m, × 17 bands × 4 bytes × 4/3 for overviews = 2.84 GB. The page's
  expected refusal quoted the synthetic bench (ten 20 m grids, about 4,000 m² of grids); the real
  site's grids cover about 1,400 m², so the memory estimate at 0.025/0.0125 is under 1.5 GB there
  and Export stays on; at 0.01 m it is refused, as seen. Fix: the summary now always shows a
  Memory row. The estimate at that near-limit setting is checked against a real run on the site
  (real-data memory report).
- **E3: the Temporal Controller.** Exports map 1 ns to 1 s; QGIS's controller starts off with a
  1-hour frame, so one frame covers every band and shows the last. Verified headlessly on QGIS
  3.44.7 (a 5 s step steps bands 1, 2, 3). Pre-existing since M11; the guide never explained it.
  Fix: the plugin sets the controller up after an export or a restore, one band per step, and the
  guide explains it (see the fix rounds below).
- **C3 / D1:** with bilinear drawing at the live 0.05 m cell, a finer export cell or pixel made
  little visible difference on this site.
- **B1:** bands in depth rather than ns — withdrawn by the author (grids can differ in velocity).

## Fix rounds

Ledger rulings R25–R32. Briefs, reports and reviews are beside this file.

- **Round 1** (7f0ce65..d2b8ba2): the Temporal Controller fitted after an export or restore; a
  Memory row in the summary; the seven parked minors. Review: three Important findings — the
  min-gap frame drifted on long small-step exports, a saved project did not reopen set up (QGIS
  saves band times at whole seconds and does not save the panel's mode), and the guide's by-hand
  set-up could not work. CI had been red since 551b237 (pytest 9.2 rejects a nested `approx`).
- **Round 2** (ae6bf88..50935c0): mean-step frames (0 failures in a 4,935-case sweep); band times
  read from the file's `NSGEO_WINDOW_NS` whenever a layer is added (export, restore, project open,
  Add Raster Layer) and the controller fitted again after a project opens, verified in the real
  QGIS 3.44 app at 17 and 200 bands; the guide rewritten; the pytest 9.2 fix. Re-review: all
  findings addressed; three Minors.
- **Round 3** (ccc944e, 15839db): a test that fails without the refit after a read; layers already
  open when the plugin starts are timed too; the guide says "installed and enabled" and covers
  re-pointed layers and projects opened without nsgeo. Checked by the controller.
- **Real-data memory check** (author's site, kriging, background normalisation, 17 bands, 3 run):
  0.025/0.0125 estimate 1,310 MB against a measured peak of 1,239 MB; 0.025/0.025 estimate 536 MB
  against 465 MB. Band 0 about 50 s (setup), later bands under 1 s. The minimum-curvature term was
  not measured on real data (the site uses kriging).
