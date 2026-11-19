# SDD ledger — plan: docs/superpowers/plans/2026-11-13-nsgeo-m17a-gps-lines.md

Spec: docs/superpowers/specs/2026-11-06-nsgeo-gps-lines-design.md (approved 2026-11-13; §15 = main's changes).
Branch nsgeo-m17-gps, worktree .worktrees/nsgeo-m17-gps. Plan commit cd8d98f. Author chose subagent-driven (2026-11-13).
Author's standing rule for this branch (2026-11-13): real-data-derived numbers may be committed as long as there are NO coordinates and NO site name.

## Pre-flight scan

| Pair / task | Produces → consumes | Finding |
|---|---|---|
| T1 → T2 | DzgLog, DzgFix, RTK_FIXED; tests/dzg_data.local_xy | consistent |
| T2 → T3 | TrackPlacement, TrackFix (NaN x/y for no-position fixes) | NaN breaks dataclass equality → T3 round-trip test already compares NaN fields with isnan; ok |
| T2/T3 → T4 | track_from_log ValueError words = refusal copy; site_crs/set_site_crs; end_runs | consistent |
| T3 ↔ T4 | both edit ui/grid_dialog.py (_site_crs; delegate to crs_rule) | sequential, ok |
| T3 ↔ T5 | both edit layers.py (crs(); gridless drawing) | sequential, ok |
| T4 → T5/T6 | plugin_testing.synthetic_gps_dzt | consistent |
| T5 → T6 | pick placement on GPS lines → T6 follow-destagger test | consistent |
| T3 ↔ T6 | session.py both | sequential, ok |
| T1 self | checksum/unpaired counts; 40→40 refused | consistent |
| T2 self | L-shape shift test: "0.24 m before the corner" is not a whole trace (0.1 m/trace) | RULING R1 |
| T2 self | FILE__011 walked length bound 29.5–30.6 m: fix-to-fix path ≈30.6 + start run ≈0.05 → can exceed 30.6 | RULING R2 |
| T3 self | Site.validate with GPS lines and no CRS at all is unspecified | RULING R3 |
| T4 self | first_fixed_lonlat(path): DZT or DZG path? | RULING R4 |
| T4 self | real-data walked bound 29.5–30.6 (same as T2) | RULING R2 |
| T5 self | RTK_GAP_COLOUR #e377c2 not in GRID_COLOURS nor CUT_COLOUR | ok |
| T6 self | velocity-fit wheel-spacing test needs a start run (first anchor after trace 1) | note for the brief |

## Rulings

- R1: T2's L-shape shift test uses trace 38 (0.2 m before the corner at trace 40) with travel_shift 0.24, expecting (3.0, 0.04) — the plan's wording named a non-integer trace — cost if wrong: one test value.
- R2: FILE__011's walked length bound is 29.5–31.0 m in T2 and T4 — the recon's fix-to-fix path is ~30.6 m before the start run is added — cost if wrong: a looser real-data bound.
- R3: Site.validate compares a GPS line's crs with the effective site CRS (site.crs, else the first grid's); when there is none, it refuses with "line {name} is placed in {a}, but the site has no CRS" — new copy, the only sensible reading of P9 — cost if wrong: one message.
- R4: gps_import.first_fixed_lonlat takes the DZT path and finds its DZG with dzg_for — matches plan_gps_rows, which takes DZT paths — cost if wrong: a signature tweak.

## Progress

## Pre-flight done
- Roadmap "M17a in progress" committed straight to main: cc9e51d (pushed); merged into the branch at 6529a71 (pushed).
- .venv-tools (ruff 0.17.1, mypy 2.4.0) created; real data linked: with-dzg/ and grid2/ as dir links, ten campus files file by file; grid2 readable (data disk mounted); git status clean.
- Baseline core+pure: 1560 passed, 5 skipped (one is "no Sunnyside survey"); lint clean; types clean (54 files). QGIS baseline running in background → baseline-qgis.txt.
- Task 1: dispatched (sonnet), BASE 6529a71
- Task 1: implementer DONE 0f3db54 (note: wrote code before tests; RED shown by moving dzg.py away — TDD order not followed literally)
- Task 1 review (opus): spec ✅; 1 Important (unpaired rules GSSIS→GSSIS, dropped-GGA orphaning/stale-pairing guard, EOF GSSIS, bad-RMC-between not pinned — mutants survive) → fix round 1.
- Task 1: minor (deferred): range test pins only the upper bound (negative trace accepted by a mutant).
- Task 1: minor (deferred): text.splitlines() splits on 0x85/0x0B/0x0C/0x1C–0x1E in latin-1 → a corrupted GGA can bypass its checksum; split on \r\n|\r|\n only.
- Task 1: minor (deferred): two different "is a GGA" tests (dzg.py:162 vs :174).
- Task 1: minor (deferred): a bad-checksum $GSSIS leaves an older pending GSSIS in place (two-fault stale pairing).
- Task 1: minor (deferred): unpaired counts differ between similar faults; undocumented.
- Task 1: minor (deferred): real-data test skips if EITHER list is empty.
- Task 1: minor (deferred): dzg_for near-verbatim copy of dzx.sidecar_for; its "path itself" branch untested and undocumented in README.
- Task 1: minor (deferred): DzgFix/DzgLog lack docstrings with the field meanings.
- Task 1: minor (deferred): no-position test does not assert utc_s; no test feeds a GGA without a checksum.
- Task 1: minor (deferred): int(given, 16) accepts 0x/+/_ forms (harmless).
- QGIS baseline: 2395 passed, 0 skipped, 1 warning, 20 min (baseline-qgis.txt).
- Task 1: fix round 1 dispatched → 07cf57c (5 tests, mutants M1 M2 M3 M4 M7 killed); scoped re-review (sonnet) running
- Task 1: fix round 1/5 (1 addressed, 0 open — unpaired rules pinned; commits 0f3db54..07cf57c)
- Task 1: complete (commits 6529a71..07cf57c, review clean)
- Task 2: dispatched (sonnet), BASE 07cf57c, with rulings R1 R2
- Task 2: implementer DONE 54073d9 (1606/5; 19 mutants killed). Ruling R5: a quality-4 fix with no position (NaN) is not an anchor and marks a bridge like any non-anchor — a position-less fix cannot anchor anything — cost if wrong: one rule.
- Task 2: review (opus) dispatched on 07cf57c..54073d9
- Task 2 review (opus): spec ✅; 1 Important (partly plan-mandated): placements holding a no-position fix are never equal/hash-equal (fresh NaN objects; dataclass eq) — profile_dock:661 compares placements; Task 3 round-trips.
- Ruling R6: TrackFix gets NaN-safe __eq__/__hash__ (NaN equals NaN field-wise), keeping the plan's NaN representation — robust to any NaN object (JSON loader, numpy floats), unlike relying on the math.nan singleton — cost if wrong: a small custom eq.
- Ruling R7: two Minors are unpinned STATED requirements with surviving mutants, so they are real gaps and join fix round 1 (tests only): (a) coincident positions / zero-length segments must not divide by zero (brief: "must not divide by zero"; anchors (20,0,0),(30,2,0),(40,2,0) at s=0 and +0.3 give NaN under mutants); (b) P5 "first anchor in trace order ≥1 m away" vs nearest-by-distance (a track that turns back) — cost if wrong: two extra tests.
- Task 2: minor (deferred): one-trace line ignores shift in trace_coords but not distance_along (unreachable with a validated log).
- Task 2: minor (deferred): track_from_log pairs via id(f) dict over non-strict zip; a to_xy returning the wrong length silently leaves NaN — add a shape check.
- Task 2: minor (deferred): real-data helper takes first quality-4 fix without checking finite lat/lon, uses literal 4 not RTK_FIXED.
- Task 2: minor (deferred): time-triggered end step collapses to 0 when the end segment's anchors coincide (P5 literal).
- Task 2: minor (deferred): _heading docstring says "nearest" where code (correctly) takes first in trace order.
- Task 2: fix round 1 → ac0f59f (R6 NaN-safe eq; R7a/R7b tests; mutants killed); scoped re-review (sonnet) running
- Task 2: fix round 1/5 (3 addressed, 0 open — NaN-safe eq, zero-length guards pinned, heading order pinned; commits 54073d9..ac0f59f)
- Task 2: minor (deferred): TrackFix NaN sentinel is the string "nan" (theoretical collision; fields numeric).
- Task 2: complete (commits 07cf57c..ac0f59f, review clean)
- Task 3: dispatched (sonnet), BASE ac0f59f, with ruling R3
- Checkpoint C1: mockup .lavish/m17a-gps-import.html (main checkout, gitignored, made-up data) opened in Lavish 2026-11-13; poll running in background. Task 4 waits on the answer (or a waiver).
- Task 3: implementer DONE e2a15d0 (core+pure 1631/5; qgis session 131, grid_dialog 147, layers 110, site_engine 58). Deviation to review: Site.effective_crs() = site.crs only with GPS lines or no grids, else first grid's (keeps a grid CRS edit live); saving GPS lines with no CRS raises ProjectError.
- Task 3 review (opus): ❌ P9 deviation; 2 Important — (1) effective_crs's has_gps_lines switch + load-time copy of grids[0].crs into site.crs make the site CRS jump to a stale value when the first GPS line arrives → site cannot be saved (probed); (2, partly plan-mandated) a gridded, never-reopened site's GPS lines are unpinned: editing the grid CRS afterwards flips the site CRS under them; core save_site does not validate.
- Ruling R9 (amends plan P9 and Task 3's test_an_older_site_takes_its_crs_from_its_first_grid): Site.crs stores only a PINNED CRS — the file's "crs", or the CRS fixed when the site gains its first GPS line, or set_site_crs on a grid-free site; load never copies the first grid's CRS into it. Site.effective_crs() = site.crs if set, else the first grid's, else None (no has_gps_lines condition); SiteSession.site_crs() returns it. SiteSession.add_lines pins site.crs = site_crs() before adding when any new line is a TrackPlacement and site.crs is None (ValueError when there is no CRS at all). save_site raises ProjectError for a GPS line whose crs differs from the effective CRS. The older-site test asserts effective_crs()==grids[0].crs and site.crs is None. — why: no stored copy can go stale, every path that adds a GPS line pins, tape-only sites behave as on main — cost if wrong: a contained rework of Site/session/project.
- Task 3: minor (deferred): track crs not checked to be text (bad file fails in validate as bare ValueError).
- Task 3: minor (deferred): int(row[0]) accepts 58.7/false; a fix past the DZT's end loads.
- Task 3: minor (deferred): alt_m/geoid_m NaN would be written as bare NaN token (types say None).
- Task 3: minor (deferred): "same JSON text" re-save checked at schema 1 and 2, not 3; stale test name test_version_3_loads_and_4_is_refused.
- Task 3: minor → carried to Task 4: grid_dialog note "the CRS the site's other grids use" wrong on a grid-free GPS site; fix when moving the rule into crs_rule.
- Task 3: fix round 1 → 4f460c8 (R9). Controller re-running core+pure + grid_dialog + site_engine (implementer skipped them after a boundary fix).
- Task 3: fix round 1/5 (2 addressed, 0 open — CRS pinned on first GPS add, save_site refuses mismatched GPS crs; commits e2a15d0..4f460c8)
- Task 3: minor (deferred): after the last GPS line is removed, the in-memory pin is not saved (crs written only with GPS lines) → reopened site follows its first grid; harmless, by R9.
- Task 3: minor → carried to Task 4: add_lines does not refuse GPS lines whose crs differs from site_crs() (fails later at validate/save) — fail fast when Task 4 wires the import.
- Task 3: minor (deferred): hand-edited schema-4 file with GPS lines and no "crs" loads unpinned.
- Task 3: minor (deferred): layers.py:15-16 docstring still says the package CRS is the first grid's.
- Task 3: controller verify at 4f460c8: core+pure 1633 passed / 5 skipped; grid_dialog 147; site_engine 58.
- Task 3: complete (commits ac0f59f..4f460c8, review clean)
- Task 4: waits on Checkpoint C1 (Lavish poll running).
- (session restarted 2026-11-13; resumed from this ledger; tree clean at 4f460c8)
- Checkpoint C1: APPROVED AS SHOWN by the author in chat (2026-11-13). Lavish session acknowledged. No copy changes for Tasks 4/6.
- Ruling R10: SiteSession.add_lines refuses (ValueError, nothing added) a GPS line whose crs differs from site_crs() after the pin — fail fast instead of failing later at validate/save (Task 3 carried minor) — Task 4 owns it, with a session test — cost if wrong: one check.
- Ruling R11: the plugin may import only names in a public module's __all__ (test_plugin_boundary), and END_LIMIT_M / ToXY live only in nsgeo.geometry.track; Task 4 adds "END_LIMIT_M" and "ToXY" to nsgeo.geometry.__all__ (sorted) and the plugin imports them from nsgeo.geometry — cost if wrong: two exports.
- Task 4: dispatched (sonnet), BASE 4f460c8, with R2 R4 R10 R11 and the carried grid_dialog note fix.
- Task 4: implementer DONE 4b485f1 (core+pure 1645/5; qgis crs_rule 10, gps_import_dialog 17, session 138, import_dialog 41, grid_dialog 147, loads 15). Concerns: built from the Copy without seeing the mockup; set_site_crs kept if add_lines then fails.
- Task 4: review (opus) dispatched on 4f460c8..4b485f1 (mockup path given for layout comparison)
- Task 4 review (opus): ❌ 2 Important — (1) approved C1 mockup's warning cues not built (amber/red cells, warning-level messages); (2) refusal of a DZG naming traces past its DZT unpinned (mutant survives).
- Ruling R12: the author approved the C1 mockup AS SHOWN, so its layout and cues are requirements: amber cells (Without RTK with a bridge; Ends with a run > END_LIMIT_M), red refused Status cells, every after-import message after the first at Warning level, "—" in empty cells of refused rows, an "already in the site" row still showing its counts and ends, the destagger text as an inline grey note beside the box (tooltip kept too), status line and Import/Cancel on one footer row, Coordinates as a form row under Destagger — cost if wrong: layout tweaks.
- Ruling R13: four Minors are real, cheap defects in the same files and join fix round 1: (m4) build the lines from the planned rows with dataclasses.replace before set_site_crs, never re-reading files at Import; (m5) the Coordinates line must show the CRS the import will use from the moment the dialog opens; (m6) check `usable` at the first RTK fix BEFORE projecting, so a far file gets "outside what X can place", with a direct test of lonlat_to_xy's NaN/exception path; (m8) remove the duplicate GridDialog._site_crs — cost if wrong: small.
- Task 4: minor (deferred): status sentence "The site's coordinates are now {X}; the table was planned again." and the core's "all lie at one point" refusal are wording outside the Copy; the GPS dialog note says "the CRS the site's other grids use".
- Task 4: minor (deferred): CRS strings compared as stored vs authid() (a hand-edited "epsg:32632" would replan forever).
- Task 4: minor (deferred): paths/rows can fall out of step if _plan_one raises.
- Task 4: fix round 1 → 01db3bf (cues, DZG-range test, R12, R13). Note: 'already in the site' now checked after placement (a taken file with no DZG shows 'no DZG beside it').
- Task 4: fix round 1/5 (6 addressed, 0 open — mockup cues, DZG-range test, R12 fidelity, R13 m4 m5 m6 m8; commits 4b485f1..01db3bf)
- Task 4: minor (deferred): a taken file with a bad DZG now reports "could not read it" instead of "already in the site" (loses the remove-first hint).
- Task 4: minor (deferred): footer test pins only status/buttons order, not the note placement; selected rows may override cell colours (unchecked).
- Task 4: complete (commits 4f460c8..01db3bf, review clean)
- Task 5: dispatched (sonnet), BASE 01db3bf
- Task 5: implementer DONE_WITH_CONCERNS 81305ea (core+pure 1647/5; layers_gps 14 incl. real FILE__039; map_link 54; pick_tool 17; layers 103 pass / 7 FAIL — tests asserting the old 5-table legend). Its sed edit of test_plugin_layers.py was DENIED by the permission classifier and it asked the controller to make the edit — refused (no laundering); surfaced to the user.
- Ruling R14 (plan defect): Task 5's "test_plugin_layers.py must stay green, unchanged" contradicts its own LEGEND_ORDER/DERIVED change; the 7 legend/table-count assertions are updated to include rtk_gaps (after cuts) and 6 tables — by the implementer with its normal Edit tool; if that is denied too, it reports BLOCKED and the author decides — cost if wrong: none (mechanical).
- Ruling R15: "rtk_gaps not selectable" = identify off + absent from MapLink's selection layers (QGIS 3.44 has no per-layer selectable flag) — cost if wrong: one flag.
- Note: the plan's test_plugin_pick_tool.py is really tests/qgis/test_pick_tool.py.
- Task 5: R14/R15 fix → 923c0c3 (layers 110, layers_gps 14, pick_tool 17; Edit tool was allowed).
- Task 5: review (opus) dispatched on 01db3bf..923c0c3
- Task 5 review (opus): ❌ 1 Important — _line_crs prefers the grid's CRS, so a GPS line carrying a grid_id (reachable now only by hand-edited file; M17c for real) is drawn from the wrong CRS when that grid is in another CRS.
- Ruling R16: per [[tests-that-dodge-the-hazard]] and the "tape lines unchanged" constraint, these Minors join fix round 1: (a) the three test dodges — older-package test must actually drop rtk_gaps first; a GPS line with non-zero travel_shift in the length_m/vertices test; a mixed site whose grid is in another CRS than the pinned site CRS; (b) add the "" "No grid" category only when a gridless line exists (tape-only sites' legend unchanged); (c) the stale _clear_derived_tables docstring and the module-docstring wrap — cost if wrong: small.
- Task 5: minor (deferred → file as follow-up at the PR): GPS-only sites get no zoom-out hiding (_hide_when_lines_crowd counts grid spacings only).
- Task 5: note for M17c: refill_lines hard-codes grid_id "" for every GPS line.
- Task 5: fix round 1 → c6fccf0 (_line_crs order; R16 tests and No grid row). No RED shown for the CRS test — re-reviewer asked to probe.
- Task 5: fix round 1/5 (6 addressed, 0 open — _line_crs order (probe: new test fails on old code), R16 tests, No grid row only with GPS lines, docstrings; commits 923c0c3..c6fccf0)
- Task 5: minor (deferred): renderer block duplicates setRenderer/triggerRepaint (cosmetic).
- Task 5: complete (commits 01db3bf..c6fccf0, review clean)
- Task 6: dispatched (sonnet), BASE c6fccf0
- Task 6: implementer DONE e07c91f (core+pure 1647/5; session 144, survey_dock 91, profile_dock 121, layers_gps 16). Concerns: GPS lines broke the Survey tree between Tasks 4–6 (fixed here); guide step titled 'Step 3a'; helpers moved to plugin_testing; destagger message shows on an unchanged value.
- Task 6 review (opus): ✅ Approved (P14 tests killed two probe mutants).
- Task 6: minor (deferred): Set destagger message shows on an unchanged OK (Copy says "after a change").
- Task 6: minor (deferred, LIKELY MUST-FIX — the author filed #109/#177 on wheel steps): the Destagger QInputDialog steps 1.0 m per arrow/wheel notch on a ±2 m box; the import dialog's box steps 0.01.
- Task 6: minor (deferred): guide "It needs an open site, and no grid." reads as "must have no grid"; greyed-out list lacks Import GPS lines…; GeoPackage row lacks rtk_gaps.
- Task 6: minor (deferred): "Set destagger for 1 GPS lines…" (Copy-mandated plural); stale comment and redundant condition at survey_dock.py:487-490.
- Task 6: complete (commits c6fccf0..e07c91f, review clean)
- All 6 tasks complete. Final whole-branch review (opus) dispatched on cc9e51d..e07c91f (main has only README commits since). Full QGIS tier running at e07c91f → qgis-full-e07c91f.txt.
- Final review (opus): With fixes. Important: (1) plan defect P14 — the velocity fit already uses per-trace distance (x_m = distance[trace]); the guide sentence about "wheel spacing" is false and the test pins an unused value; (2) Set destagger box steps 1.0 m (must fix). Minor: "Coordinates:" shown twice; guide wording/greyed list/GeoPackage row; rtk_gaps layer on every tape-only site (ask at walkthrough); set_site_crs not rolled back if add_lines fails (can wait). End-to-end probe passed (grid-free import, reopen without DZGs, destagger, grid added later, GPS removed → schema 1).
- Ruling R17: one fix wave for Important 1+2 and Minors 1+2, plus the cheap two-fault GSSIS guard (a dropped $GSSIS clears the pending trace) and the stale test rename; Minor 3 goes to the walkthrough as a question; Minor 4 parked (unreachable via UI). For M17b: the fit already measures along per-trace distance, so M17b's velocity-fit work is only the display; M17c: refill_lines hard-codes grid_id "" for GPS lines — cost if wrong: small.
- Final fix wave → 01ee458 (core+pure 1648/5; survey_dock 91, gps_import_dialog 23, profile_dock 121). Step fix exercised on PyQt5 only (CI's QGIS 4.2 job covers Qt 6).
- Final fix wave re-review (sonnet): all addressed, no new breakage. Final review CLEAN at 01ee458.
- Parked: set_site_crs is not rolled back if add_lines then fails — Ruling: real but unreachable through the UI (grid-free site, single-instance dialog); deferred — cost if wrong: a site pinned with no lines after a failed import.
- Full QGIS tier at e07c91f: 2475 passed, 1 warning (the baseline's GDAL FutureWarning); baseline was 2395.
- Checkpoint C2: deployed to NEW profile ns_geo_gps (copy of ns_geo; plugin symlink → this worktree; core resolves from this worktree — offscreen import smoke OK). Walkthrough Artifact https://claude.ai/artifact/1duVnrKB64A6rHAhorqjgD (db collection "checks", ids G1–G11; empty at publish). Awaiting the author's results; merging asks first. Keep this workspace until the walkthrough's fix rounds are done, then commit it as docs/superpowers/sdd/2026-11-13-nsgeo-m17a-gps-lines/ (decision record) before deleting.

Post-review, 2026-11-16 (user chat, before the walkthrough): R18 — the import's refusal "already in the site (remove it first to place it by GPS)" shortened to "already in the site". Removing a line drops its processing stack, velocity override and fits (`_drop_lines`), and the removal question does not say so, so the advice led to silent loss. Spec C9 revised to an in-place **Place by GPS** (M17c); spec decision 13 adds holes to the outline and requires the colour stretch to ignore masked cells. Copy change made by the controller (one string, three files; pure 14 passed, dialog 23 passed, ruff clean) — right-sized, no review dispatch.
- 2026-11-16: merged origin/main (419bb4d: #194 step edges + Trace stack, #192 DZT unsigned samples) into the branch → 57c275a, clean, no schema bump on main. core+pure 1766/5 skips (skips unchanged), ruff + mypy clean; full QGIS tier 2476 passed, 1 warning (GDAL FutureWarning baseline). Walkthrough results: none recorded yet (db 'checks' empty).
- 2026-11-17: walkthrough G1–G8 done (G7 skipped). User's decision 14 (Add data ▾ ▸ GPR…, Grid/GPS switch, GPS lines always into a grid, new grid fitted to lines' direction + half-spacing margin) → spec, milestones relettered (M17b GPS grids, M17c true distance, M17d outlines etc.); not in M17a. Spec c5d70db; README roadmap on main c558587.
- 2026-11-17: G9 answered — rtk_gaps only once a site has GPS lines (user agreed with my lean). Walkthrough fix W1 dispatched (sonnet implementer; brief walkthrough-fix-w1-brief.md; base ef53e2c). Review to follow (opus).
- W1 implemented 278fa2e (sonnet, DONE): layers.py _has_gps_lines/_drop_rtk_gaps; controller re-ran test_plugin_layers + _gps in full: 130 passed. Pushed. Review dispatched (opus) on review-ef53e2c..278fa2e.diff.
- W1 review (opus) on ef53e2c..278fa2e: spec ✅; CHANGES REQUESTED — I1 (tests never hit the main-path drop on a grid-backed site or the table emptying; mutations A/B survived). Minors M2 (readOnly pin), M3 (comments), M4 (double empty) folded into fix round 1. W1: minor (deferred): M1 — stale rtk_gaps rows can stay on disk if the layer was removed by hand right before the last GPS line goes, or after a Discard close; nothing in the plugin reads the table without its layer.
- W1: fix round 1/5 dispatched (resumed implementer) — I1 + M2 M3 M4.
- W1 fix round 1 → 6d3ecb1 (I1 test on grid-backed site, mutations A/B now fail it; M2 M3 M4). Pushed. Scoped re-review (sonnet) dispatched on review-278fa2e..6d3ecb1.diff.
- W1: fix round 1/5 (4 addressed, 0 open — I1, M2, M3, M4; commits 278fa2e..6d3ecb1). Re-review CLEAN (mutation A caught by asserts 1–3, B by the on-disk count; no teardown-crash risk added on unmutated code).
- W1: minor (deferred): `_drop_rtk_gaps` swallows a failed table-empty and still drops the layer (stale rows on disk, log only; untested fallback).
- W1: minor (deferred): refresh's try wraps `_has_gps_lines`/`_drop_rtk_gaps` with `ensure_tables`, so a drop failure logs as "could not prepare the site's tables".
- Full QGIS tier at 6d3ecb1: 2480 passed, 1 warning (GDAL FutureWarning baseline). Remaining before merge: user's G9 (import check), G10, G11; then decision record, PR, merge on the user's go.
- 2026-11-18: walkthrough DONE — G1–G6, G8–G10, G12 pass; G7 and G11 skipped; no fails. Notes: G1 wording (fixed in v2), G5 axis reads "m along line" (wording fixed), G10 asks what Open does and whether Move to grid / Measure come later (answer: M17b / M17d). G7's ground covered by core test_a_gps_line_round_trips_with_identical_positions_without_its_dzg + G12's save/close/reopen.
- CONTROLLER MISS: CI's plugin-qgis (qgis/qgis:4.2) job has FAILED on every branch push since 81305ea (Task 4) — 2 tests: gps_import_dialog `plain()` compares BrushStyle to int 0 (PyQt6 enum); layers_gps rtk_gaps still Identifiable on QGIS 4 (`flags() & ~LayerFlag.Identifiable`). I reported "everything automated is green" on 2026-11-16 from local QGIS 3 only, without checking branch CI. Fix W2 dispatched (sonnet, Docker 4.2), brief walkthrough-fix-w2-brief.md, base 6d3ecb1.
- W2 implemented 1fce783 (sonnet, DONE_WITH_CONCERNS): dialog test compares Qt.BrushStyle.NoBrush; qtcompat.without_layer_flag (LayerFlag(int(flags) & ~int(flag))) — on 4.2 LayerFlag is IntEnum, `& ~` gave int, setFlags raised TypeError. Docker 4.2: 152 passed 1 failed (see below); QGIS 3: 153 passed; core+pure 1766/5; ruff/mypy clean. Pushed; CI running. Review dispatched (opus).
- W2: minor (deferred, pre-existing tooling): in_qgis_docker.sh mounts only the dirs behind top-level local/* symlinks, so grid2's DZGs are missing in Docker and test_the_second_surveys_dropout_is_drawn fails there (passes locally; CI has no local data). Candidate follow-up issue.
- W2 review (opus): APPROVED. CI run 44237546856 on 1fce783 all green (4.2: 2764 passed, 32 skipped; 3.44 green). Minor 1 (test pins only Identifiable cleared) done by controller as a two-line assertion → adad164 (right-sized: QGIS 3 test passes; CI checks 4.2). Minor 2 (report's ~ list missed two Qt ItemFlag uses) — report-only, no code. W2: minor (deferred): refill failures (e.g. a style/flag error) go only to the Message Log (layers.py refresh loop), which is how the 4.2 defect stayed invisible to the user; pre-existing guard rule.
- 2026-11-18: merged origin/main (93 commits: M16 A/B, Session A, step edges, …) → 4b17fb5. Conflicts resolved by the controller (ci.yml mypy list keeps gps_import.py + surface_plan.py; guide greyed-out list and GeoPackage row keep both; plugin enables act_import_gps and act_surface; plugin_testing keeps GPS helpers + wheel_event). No schema bump on main (TRACK_SCHEMA_VERSION still 4). Local: core+pure 1882 passed, 8 skipped (the 3 new skips are main's paraview tests needing NSGEO_PVPYTHON; real-data skips unchanged), 1 xfailed (main's); full QGIS 2739 passed, 1 warning. CI on 4b17fb5: success (incl. qgis 4.2). Ledger committed as the decision record; PR next, merge on the author's go.
