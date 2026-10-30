# Final whole-branch review — grid dialog (21e0b5c..bd668a1)

Reviewer: opus, read in passes (lookup.py diff; grid_dialog.py, pick_tool.py and grid_overlay.py in full; plugin.py diff; test infrastructure and selected test sections; guide, README, metadata), with three probe scripts run against the real dialog. Verdict: **Ready to merge — with fixes.** No Critical findings.

## Important

- **I1. Degrees typed as metres fit perfectly.** Project in UTM 16N, Corners in left on EPSG:32616, the four site corners typed as lon/lat → `rigid fit RMS 0.000 m from 4 corners`, origin (−86.798, 36.151) in EPSG:32616, OK enabled whenever the sizes count as typed — so editing an existing grid and pressing OK would move it about 4000 km. Fill from a layer with no CRS did the same (a transform from an invalid CRS is identity). A regression on the spec's first anti-goal: on main a wrong-unit fit at least showed a large RMS; measuring the size from the corners lets a degree frame fit itself.
- **I2. A row whose text did not parse was dropped from Fit silently** (e.g. a comma decimal "518204,112"): the "not a number" message showed, the next good edit replaced it (R6), and Fit reported "from 3 corners" while the cells still showed the user's numbers. Review Focus #4 named this input.

## Minor

- M1 guide inaccuracies (CRS advice, snap order, unlabelled Layer/Feature, Rotate, the swapped-rows RMS sentence).
- M2 `_project_reason` had no "outside" branch ("off by 0.0% here").
- M3 stale comments (anchor "drops", "100 m along +Y").
- M4 a refused Fit still switched an automatic CRS; `_apply_auto_crs` discarded the conversion error.
- M5 metres typed under lon/lat gave a misleading refusal and flipped the automatic CRS.
- M6 "picked for you: the CRS the site's other grids use" shown even when that equals the project's CRS.
- M7 test hygiene (vacuous retype steps, a leaked plugin, an unused constant).

## Triage of the deferred minors

FINAL-REVIEW CANDIDATES: unparsed row (fix — I2); layer with an invalid CRS (fix — folds into I1); `_apply_auto_crs` discarding the error (fold into M4); no "outside" branch (fix — M2); no-canvas Fit→UTM test (leave); azimuth in a geographic grid CRS (leave — such a CRS can't be saved); double-click in Pick all (leave, file, walkthrough — Fit refuses "coincide"); guide errors (fix — M1); overlay message recorded when written (leave, file). The rest: resolved on the branch, trivial (stale comments), or leave/file per the reviewer's grouped list (recorded in progress.md).

## Declined to judge (ruled in R19)

"Usable" is a local scale test only; Rotate on a non-square grid; accepting comma decimals by locale; nsgeo's own layers in picks; dialog not activated after a pick; synchronous snap index; overlay colours; no 3.40 qgis test tier in CI; a core docstring mentioning digitising.

## Outcome

One fix wave (`final-fix-brief.md` → 6ef2762, `final-fix-report.md`) took I1, I2 and M1–M7 under rulings R15–R18; its scoped re-review found every item addressed and no new Critical/Important. Residuals parked under R20 (see progress.md).
