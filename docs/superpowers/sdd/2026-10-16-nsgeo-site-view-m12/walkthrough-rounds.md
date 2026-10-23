# M12 walkthrough rounds

The acceptance walkthrough page was https://claude.ai/artifact/34wPYN5oH2Rem2jojXS18M, with results stored in its db collection `results`. The user ran it on their own multi-grid survey data, which stays private and outside the repo, in QGIS 3.44 on Linux.

The build was deployed to a separate QGIS profile, `ns_geo_m12`, at the user's choice, so the `ns_geo` profile stayed on the help-pages walkthrough.

## Round 1: 2026-10-22, build `4b30da2`

The build was M12 with main merged in twice: M9/v0.1.0 at `146d3d0` and `b78379b`, then #31 and #59 at `4b30da2`.

**35 checks: 27 pass, 8 skipped, 0 fail.** Nothing blocks the merge.

| Check | Result | User's note |
|---|---|---|
| A1–A2 set up | pass | |
| B1 Whole site lists and prepares grids one at a time | pass | |
| B2 one slider moves every grid; per-grid depths; absent grids blank | pass | |
| B3 fill radius as × line spacing, tooltip in metres | pass | "honestly, I think I like this better, we may steal × line spacing for the This grid side as well." → **#72** |
| B4 status line | pass | |
| C1 seams with normalisation None | pass | |
| C2 Background / Edge / Histogram | pass | "for this site there isn't much variation, so none is fine. Background level seems to work pretty well at evening out what discrepancies do exist." |
| C3 per-grid gain, step 0.05, Reset | pass | |
| D1 re-tick re-prepares (ruling T5-a) | pass | "I think its good. its a way of doing memory management." → T5-a stands |
| D2 choose lines for one grid | pass | |
| D3 chooser applies to its own grid after the row changes (final-review M1) | pass | |
| E1 back to This grid | pass | "I think it would be good to have it switch to the row selected in the site list … make it a new issue." → **#70** (ruling F-3's question answered) |
| E2 back to Whole site, instant | pass | |
| E3 rapid scope flips mid-preparation | pass | |
| E4 This grid status shows site memory (F-4) | pass | "37 MB +340 MB held by the site view" |
| E5 layer rename vs scope switch (F-11) | skip | "not worried about this" → rename rule stands |
| F1 velocity edit: no re-prepare, no stall (final-review I2) | pass | |
| F2 move a grid: only it re-prepares | pass | |
| F3 open a profile while the site prepares | pass | |
| F4 remove lines from one grid (#31) | pass | |
| F5 time cutoff on one grid (#59) | skip | |
| G1 export greyed while preparing (T4-a) | pass | |
| G2 site GeoTIFF opens as one layer, bands step through depth | pass | |
| G3 gdalinfo metadata | skip | covered by the automated round-trip tests |
| G4 coverage companion | skip | covered by the automated tests |
| H1 site view survives save and reopen | pass | |
| H2 This grid remembers each grid's source (T2-a) | pass | "Preset, transform and selected lines all come back. the resolution settings unfortunately do not." → **#71** |
| I1 drag on the largest site (10 grids) | pass | "I have to scroll a little slowly for my 10 grids, but not too bad." → **#73** |
| I2 grids laid off north | pass | "none of the grids are laid at north bearing" |
| I3 memory | pass | "340 MB which I think seems reasonable. In the system monitor, QGIS is using 3.9 GB … within reason. I've got a lot loaded in!" |
| W1–W4 Windows | skip | → added to the hand check in **#50** |

### Follow-ups filed at the user's request ("make them all issues")

- **#70**: This grid should open the grid selected in the site list (E1).
- **#71**: remember each grid's resolution settings, as its preset and lines are (H2).
- **#72**: This grid's fill radius as × line spacing (B3).
- **#73**: Whole site drag lag on a 10-grid site laid off north (I1).
- **#74**: an empty remembered line choice is read as every line in This grid but no lines in Whole site. This is parked ruling F-8, now easier to reach through #31.
- **#75**: M12 review follow-ups, an umbrella for the deferred minors, including parked ruling F-9.
- Comment on **#41**: the flaky cancel-wait test failed again, on main's CI and on this branch's CI (QGIS 4.2).
- Comment on **#50**: Windows hand check of the Whole site preview, since W1–W4 were skipped.

No code changed in this round.
