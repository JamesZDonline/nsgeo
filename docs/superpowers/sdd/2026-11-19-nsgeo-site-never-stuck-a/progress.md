# SDD ledger — plan: docs/superpowers/plans/2026-11-19-nsgeo-site-never-stuck-a.md

Spec: docs/superpowers/specs/2026-11-18-nsgeo-site-never-stuck-design.md (approved 2026-11-18, d2615af).
Plan A approved 2026-11-19 (efa31cb). Branch nsgeo-site-never-stuck; main merged at 3104edb (M17a).
Worktree has its own .venv (core editable from this worktree) + real data symlinks (gitignored).
Models (user's tiers): implementers sonnet, reviews opus, quick fixes haiku.
Reviewers must not edit files in this worktree. Commit + push after each task.
Loop (#166): controller runs "before" loop after Task 1 in a detached scratch worktree; "after" loop after Task 6.

## Pre-flight scan

| Pair / task | Produces vs consumes | Finding |
|---|---|---|
| T1–T6 | T1 busy_report/pending_tasks/wait_for_site; T6 tests use wait_for_site, T6 detach nulls retiring callbacks | consistent: busy_report reads only running/has_live_task/pending_tasks |
| T1–T3 | both edit test_plugin_site_export.py (T1 waits; T3 moves make_site to conftest) | consistent; T1 must not move make_site |
| T1–T5 | T5 tests use wait_for_site | consistent |
| T2–T5 | T2 lean taps (north-up only); T5 gather_footprint uses full bilinear_taps | consistent: lean() only in display |
| T3–T4 | both edit plugin.py `_export_site` (T3 drops transform=, T4 adds busy refusal) | compatible |
| T3–T5 | both edit site_export.py (T3 plan_site_export/site_export_job; T5 world_to_frame) | disjoint functions |
| T5–T6 | both edit site_engine.py (T5 geometry helpers; T6 dispatch) | disjoint; T1's busy_report reads `_registration` (stays) |
| T1/T2/T6 | slices_engine.py: pending_tasks / status_text / detach | disjoint |
| T1 self | "grid A: preparing (0 of 4)" = dispatch progress (0, len(keys)); held load → no engine progress | OK |
| T2 self | sweep uses CRS/CubeFrame/SiteLattice already in test_slices_site.py | OK |
| T3 self | test drops `transform` from KW; export_site helper adapts | OK |
| T5 self | relative timing test (>=3x vs per-point in-test) | OK, load-robust by design |
| T6 self | (b) hangs before (a)'s fix by reading; (d) counts reports (one wait), no timing | OK |

Scan clean; no rulings needed.

## Tasks
Task 1: dispatched (BASE efa31cb, implementer sonnet)
Task 1: implementer DONE 3ee3090 (263 passed in 3 site files); before-loop started on 3ee3090 in scratch loop-before
Task 1: review (opus) Approved, 0 Critical/Important; Minor 1 (never-raises guard unexercised) + Minor 4 (docstring) sent back to implementer as a small follow-up; Minors 2-3 accepted (coverage breadth; 'unknown' state spelling unreachable)
Task 1: minor follow-up 97ce70c (raising-probe test; docstring) read by controller — test-only + docstring, exactly as asked; no fix loop was triggered (0 Critical/Important)
Task 1: complete (commits efa31cb..97ce70c, review clean)
Task 2: dispatched (BASE 97ce70c, implementer sonnet)
Session restart (2026-11-19 ~10:45): Task 2 implementer cut off with uncommitted work; resumed it. Before-loop round 1 was killed mid-way (logs in scratch loop-logs/killed-r1: tests #6 test_quick_site_finish_edits_redraw_once 12/12 F, #29 test_a_choice_made_before_any_preset_survives_a_record_that_names_no_lines 11/12 F, #8 test_whole_site_draws_one_layer_covering_every_grid 6/12 F — reasons unknown, the run never reached its summary). Loop restarted with an instafail plugin that prints each failure as it happens.
Session restart 2 (2026-11-19 ~14:15): implementer and loop killed again; user said "start again" and that gh is unavailable — work locally, no push/gh until they re-auth. Loop restarted (unbuffered, instafail to real stdout; the first restart's logs were empty — buffered). Task 2 re-dispatched to a fresh implementer (sonnet) to finish the uncommitted work.
Task 2: implementer DONE_WITH_CONCERNS db13d74 (local, push pending). Inherited diff complete; strengthened weak status test (600x600 rotated frame), added 2 README rows (outside brief; test_public_api demanded), __all__ order. Sweep misses before fix: 8x 8/64 phases, 16x 20/64, all four edges. Concern: test_hyperbola_trace_hand_fits largest-box timing 1.48 s > 1.0 s at load ~18, not checked on HEAD — controller to rerun when the loop ends.
Task 2: review (opus) dispatched on review-97ce70c..db13d74.diff
Before-loop rounds 1-2: 0 hangs in 24 copies; see scratch loop-notes.md.
Task 2: review (opus) Changes needed — Important 1: lean-equivalence test compared the exact path with itself (3 exact-path mutants survived). Minors: LRU recency untested; QGIS test left ~25 MB plan in the global cache (order-dependent status strings); status line lags one draw (slices_dock.py:2966 label set before slice_changed emit → to_north_up) — OUTSIDE brief, deferred as a follow-up candidate for the PR body; README row order; report said 4 lines lost per phase, actually 2 (totals right).
Task 2: controller fix 0cb2325 (test-only + README order): corner-rule reference test (kills all 3 mutants, checked in scratch src copy via PYTHONPATH), recency re-read (kills no-move_to_end mutant), finally-clear in QGIS test, README alphabetical. Verified: ruff clean; 4 core files 141 passed; QGIS north_up/status 2 passed. Hyperbola timing test: 3/3 pass at lower load (1.47-1.49 s incl. startup; was load).
Task 2: complete (97ce70c..0cb2325)
Before-loop FINISHED (3 rounds x 12 copies x 174 tests, 3ee3090): 0 hangs ("did not finish preparing" never printed). Failures: 26 never_overlaps_preparations (0.2 s window, timing), 12 #196, 6 moving_this_grids_grid_while_a_site_task_outlives_its_cancel_never_overlaps (state assert after 1.7 s — Task 6 (f) candidate, notes in scratch loop-notes.md), 5 waits_out (0.15 s window, timing). #166 NOT reproduced locally.
Task 3: dispatched (BASE 0cb2325, implementer sonnet)
Task 3: implementer DONE_WITH_CONCERNS 2891082 (local). Deviation: core pyproject mypy override qgis ignore_missing_imports (lint job has no QGIS) — sent to review; extra test for differing transforms (no fail-first, written after). Task 3: review (opus) dispatched on review-0cb2325..2891082.diff
Task 3: review (opus) Changes needed — Important I1: no-transform site lost NSGEO_SITE_TRANSFORM (engines hold "" , GDAL drops empty item; old caller passed "none"). Minors: mixed time-base test hand-built SiteEngine; differing-transforms guard unreachable publicly (comment); docstring. mypy override APPROVED by reviewer (no other file weakened; per-import ignore would break with warn_unused_ignores where QGIS is installed).
Task 3: controller fix 4d9501a: "none" spelling (new test failed first: assert None == 'none'), docstring, mixed test via prepared_site/make_site, comment. Verified: export+engine 94 passed; site_scope export subset 14 passed; ruff clean; CI mypy list clean (65 files).
Task 3: complete (0cb2325..4d9501a)
Task 4: dispatched (BASE 4d9501a, implementer sonnet)
gh auth back (2026-11-19 ~22:00): pushed 97ce70c..4d9501a; CI run 44624741910 on 4d9501a. Implementers keep committing locally; controller pushes after each review.
CI 44624741910 on 4d9501a: success (lint+mypy, smoke 3.40/3.44/4.2, core matrix, plugin-qgis 3.44 + 4.2)
Task 4: implementer DONE 77ba76c (local). Refusal placed before the ready_grids check. dz seeding: default dz = coarsest included interval (max(dts)), floor/step = finest — brief said 'finest'. Added test_a_re_sent_included_set_never_seeds_the_resolution_again (pinned). Protocol limits: dz_spin typed QDoubleSpinBox, bare pyqtBoundSignal, no QObject in Protocol; site_scope.py not on CI mypy. Task 4: review (opus) dispatched on review-4d9501a..77ba76c.diff
Task 4: review (opus) Changes needed — Important I1: refusal used site.is_running (includes a retiring unticked grid's live read) while the button uses busy(included); probe: untick C mid-prepare → button enabled, export refused (forever if the read hangs). Minors: window_levels test couldn't tell round from floor/ceil/int (3 mutants survived); 3rd rounding copy in site_engine._limit_windows_ns (→ added to Task 5 brief); dz note correct (default = coarsest per #177 093dfda; seeding tests from f4e8930); re-send test is a behaviour pin; Protocol unchecked by CI.
Task 4: controller fix 24987ad: SiteScope.export_busy() shared by the button and SlicesDock.site_export_busy() → _export_site; new test test_site_export_waits_only_for_the_included_grids failed first (refusal message logged), passes after; refusal test spins on site_export_busy; pure (1.4, 0.7, 0.5) == (3, 1).
Task 4: verified site_scope + slices_dock 413 passed; pure 396; ruff clean. Pushed 4d9501a..24987ad.
Task 4: complete (4d9501a..24987ad)
Task 5: dispatched (BASE 24987ad, implementer sonnet; brief has controller addendum M2)
Task 5: implementer DONE ce169d4 (local). Rebuild in grids_changed documented (not deferred: dock reads geometry right after remove_grid). Mixed-CRS + failure-path tests pinned (passed at once). site_engine 1535→1471. Context now transformContext() (was QgsProject.instance()). Task 5: review (opus) dispatched on review-24987ad..ce169d4.diff
Task 6 brief: controller addendum added (loop results; (f) = moving-grid state failure, bounded).
CI 44630766158 on 24987ad: success
Task 5: review (opus) Changes needed — Important 1: batched geometry.transform never raises; out-of-domain points come back inf (per-point raised QgsCsException) → extent_in all-inf → OverflowError in SiteLattice.covering shown to the user; gathers silently empty. Tests dodged it (all points in-domain). Minors: 1e-9 tolerance not enforced (default rtol 1e-7; float32 mutant survived); failure-path test can't tell first error from last (mutant survived); docstrings (reads→writes; module docstring's "never in the synchronous slot"); speed test single batched timing; reshape(-1,2) accepts (n,3). Not verified: PyQt6/4.2 fromWkb/asWkb — CI will.
Task 5: controller fix 3fa68ef: transform_points raises RuntimeError "N of M points lie outside where {target} is defined; check each grid's coordinate system ({source})" when a finite input comes back non-finite (NaN/inf inputs pass through); ValueError on non-(n,2) input; tests: out-of-domain n=1 and mixed n=3 (failed first: DID NOT RAISE), non-finite passthrough, shape refusal (failed first), rtol=0 atol=1e-9, fastest-of-3 batched timing; first-error test gives each line its own message — kills keep-last mutant (checked in a detached scratch worktree, removed); docstrings fixed.
Task 5: verified geometry+engine+export+site_scope 282 passed; real_data 46; CI mypy clean; ruff clean. Pushed 24987ad..3fa68ef.
Task 5: complete (24987ad..3fa68ef)
Task 6: dispatched (BASE 3fa68ef, implementer sonnet; brief has controller addendum: loop results + bounded (f))
CI 44634957768 on 3fa68ef: success (incl. plugin-qgis 4.2 — WKB transform path fine on PyQt6)
Task 6: implementer DONE fc51f96 + 7589f37 (local). (a)-(e) all failed first; (b) hung before the fix (busy report: preparing 'A' (moved since dispatch), queue [B,C], retry off). (f) root cause = the test (replace_grid's GUI-thread work 1.3-1.8 s under load outlasted the 0.8 s held line; site task ended inside it; no overlap, max_concurrent 1) → test now spies set_source while a site task is live; 48 loaded copies pass; mutant (drop has_live_task gate in dock.prepare) caught. Deviation: (a) undo notifies once. Task 6: review (opus) dispatched on review-3fa68ef..7589f37.diff
Task 6: review (opus) Changes needed (test only) — Important I1: test (d) couldn't tell detach disconnected anything (on_error=None silenced the second wait; no-disconnect mutant passed). Minor M1: (e) covered only _drop_engine. M2: nested-wait detach restores on_prepared (harmless; docstring). All production code judged correct; 7 mutants run, all caught except I1's. Reviewer note: (a)/(b) lost wakeups real but not reachable from today's dock on_changed; #166 stays open.
Task 6: controller fix 78c9dbe: (d) counts the retiring engine's wait_for_preparation calls (no-disconnect mutant → 2 == 1, caught) + engine.choice kept; reaper deletion checked via findChildren (reaper-dispose-only mutant → 3 == 2, caught); detach docstring. Engine files 156 passed; ruff clean. Pushed 3fa68ef..78c9dbe.
Task 6: complete (3fa68ef..78c9dbe). PLAN A BUILT.
CI 44639902100 on 78c9dbe (Plan A head, first CI with Task 6's production code): success, both QGIS majors.
Final whole-branch review (opus, read-only): Ready for Plan B on two conditions (CI on 78c9dbe — now green; after-loop recorded). No Critical/Important code defects. Process gaps: after-loop + 4.2 Docker round (spec Part 1) not yet done/recorded. Minors: plain_export_error didn't map Task 5's refusal; 5 bare site waits outside the 3 files; north-up cache comments contradict; Protocol not in CI mypy + SiteScope.session/engine Any (#75 comment: "added, not type-checked"); dispose() still one bounded wait per retiring engine (#75 comment: kept on purpose); PR-body leftovers: status line lags one draw, one-emission-one-grid documented not asserted.
Final-review fixes b21ea1e: plain_export_error maps "lie outside where"/"could not transform points" + test; 5 waits → wait_for_site; both cache comments.
MEASURE-FIRST (partial, under load 6-9 from other sessions' test suites; report measure-report.md): at 0.02 m Whole site fill 196.9 s, draw after landing 1.13/1.25 s, STRETCH AFTER LANDING 7.40/8.21 s; Grid1 (min_curv) fill 44.5 s, draw 0.31 s, stretch 2.46 s (provisional), first north-up 0.44 s; Grid6 fill 13.2 s, draw 0.04 s, stretch 0.49 s, first north-up 0.20 s. No 0.01 m numbers (fill never landed under load). Over the author's ~1 s threshold at 0.02 m (stretch; draw borderline) → Plan B NOT written; numbers taken to the author per their rule.
AUTHOR'S DECISION (2026-11-19, on the measurements): the shared stretch goes into Plan B too — worked out in the same background job right after the fill; the map keeps its current stretch until the new one lands. The ~1 s slider tick goes to the follow-up issue, re-measured on a quiet machine.
Final-review fixes verified: site_export+slices_dock+paraview+width 329 passed; core display 34 passed; ruff clean. Pushed. After-loop next at b21ea1e.
After-loop started at b21ea1e in scratch loop-after: 6 rounds x 6 copies (36 copies, same total as before; 6 at once, not 12, because other sessions' suites leave ~5 GB free and load ~8, so per-moment load is comparable). The rewritten (f) test is NOT on the monitor's known list.
Plan B written: docs/superpowers/plans/2026-11-19-nsgeo-site-never-stuck-b.md (16c1532), 5 tasks; awaiting the author's review.
After-loop STOPPED after round 1 of 6 (the author asked whether it still needed to run; it cannot change #166's outcome, since the before-loop never hung). Round 1 at b21ea1e: 6 copies x 177 tests, 0 hangs, 1 failure (never_overlaps_preparations, a timing window); the rewritten (f) test and #196 did not fail. Round 2 was killed mid-run with no hang logged. The 4.2 Docker round was not tried.
