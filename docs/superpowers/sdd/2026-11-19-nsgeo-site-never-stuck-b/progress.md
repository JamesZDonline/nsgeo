# SDD ledger — plan: docs/superpowers/plans/2026-11-19-nsgeo-site-never-stuck-b.md

Spec: docs/superpowers/specs/2026-11-18-nsgeo-site-never-stuck-design.md (Part 5) + the author's 2026-11-19 decision (stretch into Plan B), recorded in the plan header and Plan A's ledger.
Plan approved by the author 2026-11-19 ("Go with the plan"). Branch nsgeo-site-never-stuck, worktree .worktrees/nsgeo-site-never-stuck, Plan A built (ledger ../2026-11-19-nsgeo-site-never-stuck-a/). After-loop (Plan A head b21ea1e) is running in scratch loop-after; its results go to Plan A's ledger.
Models: implementers sonnet; reviews opus; quick fixes haiku. Implementers commit locally; controller pushes after each review.

## Pre-flight scan

| Pair / task | Produces vs consumes | Finding |
|---|---|---|
| T1–T2 | T1 plan_fill/plan_curvature(should_stop, progress), SolveStopped in stopping.py; T2 FillJob.run uses them | consistent |
| T2–T3 | T2 FillJob.fill/.preview/.grid_id; T3 StretchJob reads them at run time (same worker, after) | consistent |
| T2–T4 | fill_held/fill_job/fill_key, Refiner.settle, dock.fill_worker | consistent |
| T3–T4 | SliceEngine.stretch_job(thickness_levels, clip, finish, *, fill=), RefineFlow.held_stretch/land_stretch; FillFlow on_stretch(key, limit, final) | consistent |
| T4–T5 | FillFlow API, restore_site_resolution (made in T4), Protocol additions in site_scope.py (T4) | consistent |
| T2–T5 | removed/unticked/moved grid → _drop_engine→dispose→clear→_drop_fill bumps _fill_epoch → land False | consistent (epoch bumped by every _drop_fill) |
| T1 self | stop-inside-search test reads the stage split the builder chooses | OK: builder asserts against its own split, recorded in report |
| T2 self | fill_job drops then captures epoch after the drop | OK (epoch read after _drop_fill) |
| T3 self | "factor one pure function" + "today's paths keep their results" | consistent |
| T4 self | request/request_stretch states vs tests (stretch request never cancels fill) | consistent |
| T5 self | key = (lattice, missing, fill keys) vs ready_grids change restarting | consistent |

Rubric conflicts: none. Ruling (made in the plan, flagged to the author): one dock-owned fill worker for both scopes, not one per scope — scopes never draw at once and a scope switch stops it; costs a second Refiner if wrong.

## Tasks
Task 1: dispatched (BASE 16c1532, implementer sonnet)
Task 1: implementer agent a204cc0b2368a9907
Task 1: implementer DONE 61d455b (local). Split IDW/kriging: reach 0-0.1, search 0.1-0.6, weights 0.6-1.0; min_curv: reach .1, grow .15, stencil .4, hierarchy+plan 1.0. Deviation: stop-inside-search test IDW/kriging only (min_curv has no neighbour search). Task 1: review (opus) dispatched
Task 1: review (opus) Needs fixes — I1 neighbour-search stop gap 0.75 s @1000x800, 1.6-2.9 s @1500x1200 (every-32 cadence); I1b level-0 _coarsen 1-3 s unchecked (plan-mandated "once per level"); I2 tests only prove first-check stops (first-check-only mutant passes all 10; _stencil/build_hierarchy checks untested). Minors: CT/test_slices_curvature.py got no test (folded into I2 fix); stop/report helper duplication; min_curv progress 0.4→1.0 jump (folded into ruling); Callable import inconsistency; no progress inside reach.
Ruling: level-0 coarsening check widened to per probe inside _coarsen — the spec binds "within a fraction of a second", the plan's "once per hierarchy level" is its argument — costs negligible extra checks if wrong. Progress per level folded in.
Task 1: minor (deferred): stop/report helper duplicated 7x + 2 closures (a check() helper in stopping.py would remove)
Task 1: minor (deferred): multigrid imports Callable from collections.abc, others from typing
Task 1: minor (deferred): no progress inside reach (0→0.1), cheap
Note: eigh unstoppable took 1.9-3.3 s on the loaded box (BLAS oversubscription likely); unloaded tens of ms — Task 4's GUI-gap tests run the fill on the worker so this is a cancel latency, not a freeze.
Task 1: fix round 1 dispatched (fresh implementer; the original was stopped) — findings in task-1-findings.md
Task 1: fix round 1/5 (3 addressed, 0 open — stop cadence every offset; per-probe _coarsen checks + per-level progress; tests prove mid-stage stops; commits 61d455b..3bcc230). Gap @1000x800: IDW 1.26→0.043 s, kriging 1.24→0.046 s, min_curv 0.88→0.30 s (eigh).
Task 1: minor (deferred): test_the_hierarchy_progress_never_falls_and_stays_below_one has an unused levels list / setup
Task 1: complete (commits 16c1532..3bcc230, review clean). Pushed.
Task 2: dispatched (BASE 3bcc230, implementer sonnet)
Task 2: implementer agent a3511189de3158bdb
Task 2: implementer DONE_WITH_CONCERNS f4eb493 (local). Epoch: _drop_fill always bumps; _rebuild_geometry restores the epoch when the frame is unchanged (z/dz edit) — pinned by a test. sourced fixture imported, not moved (as test_plugin_cut_picks does). min_curv progress 0.7 fill / 0.3 preview. Task 2: review (opus) dispatched
Task 2: review (opus) Needs fixes — I1 min_curv preview untested (no-preview mutant survives; would trip assert in engine.preview later). Minors: fill rule duplicated (_fill_for vs FillJob.run) — Ruling: folded into the fix as the root cause of I1; job keeps memory after land — Ruling: folded in (spec: memory peaks unchanged); progress split unpinned (folded with the helper); two landing guards never decisive (kept as defence, deferred); fill_key untested (deferred); fixtures don't join fill_worker — carried to Task 4's dispatch; extra .copy() nit (deferred); settle docstring should say callbacks run in the caller's frame (deferred). Named risks: settle re-entrancy is a Task 4-5 hazard (landing that redraws re-enters the draw) — carried to Task 4's dispatch.
Task 2: minor (deferred): _disposed/frame landing guards never decisive in tests (defence)
Task 2: minor (deferred): fill_key has no direct test
Task 2: minor (deferred): (coverage > 0).copy() extra copy
Task 2: minor (deferred): settle docstring: callbacks run in the caller's frame
Task 2: fix round 1 dispatched (resume implementer) — findings in task-2-findings.md
Task 2: fix round 1/5 (3 addressed, 1 new open — land() releases an installed fill, racing Task 3's StretchJob; commits f4eb493..c9b9c37)
Task 2: minor (deferred): progress-split test monkeypatches plan_fill by assignment, not monkeypatch
Task 2: fix round 2/5 (1 addressed, 0 open — an installed fill job keeps its fill; only a refused one lets go; commits c9b9c37..58b99f4)
Task 2: minor (deferred): an installed job keeps its mask while referenced (small)
Task 2: complete (commits 3bcc230..58b99f4, review clean). Pushed.
Carry to Task 3: build_fill(populated, cell, settings, *, should_stop, progress) -> (fill, preview) in slices_engine.py; FillJob keeps fill/preview after an installed landing, None after a refused one → StretchJob reads each job's fill into a local at run start; None = stale → measure nothing (limit None).
Carry to Task 4: Refiner.settle delivers landings synchronously inside the caller's frame (a landing that redraws re-enters the draw); test fixtures must also shut down dock.fill_worker.
Task 3: dispatched (BASE 58b99f4, implementer sonnet)
Task 3: implementer agent a5f5552faec8f78aa
Task 3: implementer DONE_WITH_CONCERNS b2b192a (local). Concerns: single-engine streaming coverage is window-invariant (mismatch tested via a held fill for other cells); only shared_windows/shown_window/limit_of shared, draw_window job-only; mismatched min-curv builds full build_fill; FillJob-given → provisional (solves dropped); job collects every window's slice in a list (today streams a generator). Task 3: review (opus) dispatched
Task 3: review (opus) Needs fixes — I1 fill reuse/fill-job read untested (M1 no-holds, M2 ignore-fill-job survive); I2 This grid job lists all windows' slices (peak 1.25-2.25× today's generator); I3 arming rule duplicated in refine_flow. Minors: draw_window re-expresses engine draws (pinned by ==; deferred); min-curv mismatch builds plan+preview with old fill alive — Ruling: docstring obligation folded (Task 4 passes FillJobs for every unheld grid); finished StretchJob keeps captures — Ruling: release in run's finally (folded); solved-cache recency not refreshed (deferred); dead test loop/false comment (deferred); coverage gaps site kriging / resident vs streaming site / min-curv mismatched plan / stop during own build (deferred); lazy imports, WindowSource not frozen, coverage() per window (deferred).
Task 3: minor (deferred): draw_window re-expresses finish/preview/solved draws (each one core call, pinned by ==)
Task 3: minor (deferred): stretch job doesn't refresh solved-cache recency (move_to_end) — solves may evict sooner
Task 3: minor (deferred): test_plugin_stretch_jobs.py ~829 dead loop + false "every fill held" comment
Task 3: minor (deferred): coverage gaps — site kriging, site resident vs streaming, min-curv mismatched held plan, stop during the job's own build
Task 3: minor (deferred): lazy imports of build_fill/solve_key; WindowSource not frozen; cube.coverage() rebuilt per window (~1 ms)
Carry to Task 4: StretchJob.land() returns True but limit may be None (stale) — never pass None to land_stretch; judge a landed stretch key current or stale; pass a FillJob for every grid with no held fill.
Task 3: fix round 1 dispatched (resume implementer) — task-3-findings.md
Task 3: fix round 1/5 (5 addressed, 0 open — build counter pins reuse + fill-job read (M1 6 failed, M2 3 failed); This grid streams windows; one arming rule; job releases captures in finally; fill-job obligation in docstrings; commits b2b192a..609cc4b)
Task 3: minor (deferred): a released StretchJob run twice would report the empty-site limit as final (no re-run path exists)
Task 3: complete (commits 58b99f4..609cc4b, review clean). Pushed.
Task 4: dispatched (BASE 609cc4b, implementer sonnet)
Task 4: implementer agent a481aefab0da13128
Task 4: implementer DONE_WITH_CONCERNS ef46f7d (local). Deviations: FillFlow on_tick/on_error kwargs; request/request_stretch accept factories (fill_job drops the held fill, so a job made for a same-key request would invalidate the running one); fill and stretch as two worker lists (so settle can land a quick fill in the same tick). Fixed a Task 3 breakage: test_plugin_cut_sections patched site_engine.normalise, moved to stretch_jobs (Task 3 never ran that file). Slow fixture at 0.017 m (0.02 m built in 1.17 s here), asserts ≥1.5 s. Task 4: review (opus) dispatched
Task 4: review (opus, 4 passes + 3 probes) Needs fixes — I1 no _picture for a preview draw (Cancel over min-curv preview reverts to the wrong method / latches with a picture shown); I2 stale stretch stored as final after a z0 edit mid-stretch (same _stretch_key); I3 Cancel restores the whole record but only cell/finish widgets (z0 panel 4.0 vs record 2.0). Deviations judged sound (factory, two lists, on_tick/on_error, cut_sections patch). Hazards 1-2 closed; 3 partly.
Ruling (I3, plan-mandated): the spec binds — Cancel restores only the fill fields (cell, method, max_distance_spacings) with key presence; the plan's whole-record copy is narrowed. Cost if wrong: other fields edited mid-fill survive a Cancel (the spec's intent).
Ruling: review Minors 1-10 folded into round 1 (same code; Task 5 reuses the picture/take-back/latch logic, so it moves beside FillFlow with one latch owner now rather than being copied into site_scope).
Task 4: fix round 1 dispatched (resume implementer) — task-4-findings.md
Task 4: fix round 1/5 (12 addressed, 0 open of the listed; re-review found 2 more Task-4-own issues → round 2; commits ef46f7d..4a382cc). Mutants M1/M2/M3a-c all caught.
Ruling: the re-review's "out-of-scope" site-scope timing headroom (This grid A's fill 174 ms vs the 200 ms budget; 3 tests fail at a 0.1 s budget, same at ef46f7d) is Task 4's own breakage, not out of scope → round 2 finding 13; latent site-scope drop_stretch (Task 5 shares the flow) → finding 14; FillFlow.stop's default unlatch → finding 15 (Task 5 builds on it).
Task 4: minor (deferred): key presence read at draw vs cell from frame — a draw inside the 120 ms cell debounce can make Cancel write a seeded cell back as chosen
Task 4: minor (deferred): a coverage draw is not recorded as a picture (by design: not a fill)
Task 4: minor (deferred): _assert_slow docstring "1.9 to 2.2 s" vs module "2.0 to 2.2 s"
Task 4: fix round 2 dispatched (resume implementer) — task-4-findings.md "## Round 2"
Task 4: fix round 2/5 (3 addressed, 0 open — site-scope tests wait via drawn(dock) (16 fail→0 at a 0.0001 s budget); site-scope _on_prepared clears only _grid_refine.stretch; FillFlow.stop never touches the latch, FillPicture sole owner; commits 4a382cc..0fb3898)
Task 4: complete (commits 609cc4b..0fb3898, review clean). Pushed.
Carry to Task 5: reuse P/ui/fill_picture.py FillPicture (site: site_resolution / restore_site_resolution) and FillFlow as built (read fill_flow.py for the actual API: factories, on_tick/on_error, request/request_stretch/drop_stretch/stop); leaving = flow.stop() + fill_picture.unlatch(); set_scope stops after the pending apply; site-scope _on_prepared clears only _grid_refine.stretch; site Cancel link currently hidden — show it; test helper drawn(dock) in test_plugin_site_scope.py; site3's This-grid fill ~174 ms at 0.1 m → site tests must wait, prove with a tiny budget in scratch.
Task 5: dispatched (BASE 0fb3898, implementer sonnet)
Task 5: implementer agent a37936316931a796b; CI 44670535405 on 0fb3898 running
CI 44670535405 on 0fb3898 (Tasks 1-4): FAILED both plugin-qgis jobs — test_plugin_fill_flow slow-cell calibration "the slow cell takes 1.25 s: shrunk" (CI ≈0.65× this machine; floor 1.5 s), 8 setup errors + 1 failure; on 4.2 also test_refine::test_shutdown_joins_the_worker (leaked nsgeo-refine_0, likely from fixtures whose setup assertion raised after building the dock → no teardown). Lint, smoke, core matrix green.
Ruling: MIN_SLOW_S → 1.0 (4× the 0.25 s gap limit — enough to make a GUI-thread fill unmissable), SLOW_CELL finer (~0.015) so CI lands 1.5-2 s; MID_CELL ≥ 0.55 s here; fixture teardown must run on a calibration failure. Sent to the Task 5 implementer as a separate commit (same file it is editing).
Task 5: implementer DONE_WITH_CONCERNS 5985aa1 (CI calibration + teardown) + b32f19f (Whole site). SITE_SLOW_CELL 0.06 (2.5 s here), SLOW_CELL 0.016, MID_CELL 0.022, floors 1.0 s. Tiny-budget site_scope 177/177 (old tree 39 fail). 15 existing tests changed + settle()/_wait_for_refine helpers; two count stretch_job instead of shared_limit. Unticking/removing mid-fill restarts the request for the grids left. Pushed early for CI while the review runs. Task 5: review (opus) dispatched
Task 5: review (opus, 4 passes + 2 probes) Needs fixes — I1 (plan-mandated) site fill key on tuple(missing) restarts the grid in flight on any slider move/redraw after the first landing (probe: 3 jobs/1 landed → 2 jobs/0 landed); I2 5985aa1 missed the leak's cause: gen.close() on _docked_with skips its teardown (probe: both workers alive). Strengths: FillFlow/FillPicture reused unchanged, every leaving path stops, Cancel restores the site record exactly, stretch key current-checked, no assertion weakened.
Ruling (I1): the spec binds — key on the wanted grids (ready with a window) + their fill keys + lattice, not the missing set. Cost if wrong: none found; the plan's key contradicted "slider ... only changes what is drawn when it lands".
Ruling: folded — no-drawing path keeps the latch (spec), latched site builds nothing when a grid becomes ready (spec, test), dead busy-cursor branch, SITE_SLOW_CELL finer (≥2 s on CI).
Task 5: minor (deferred): _fill_jobs adds a stretch job even when held_stretch(stretch_key) is current
Task 5: minor (deferred): display_limit's `flow.working or …` redundant
Task 5: minor (deferred): limit_shown survives a stretch-key change that rescales values (matches This grid; implementer flagged)
Task 5: minor (deferred): site_scope.py +135 lines to 1520, not on CI mypy (in the planned follow-up issue)
Task 5: fix round 1 dispatched (resume implementer) — task-5-findings.md
CI 44675680397 on b32f19f: 1 failure on both QGIS majors — test_quick_site_finish_edits_redraw_once [1, 1] == [1] (landing redraw counted); calibration fixtures held on CI (no slow-cell errors). Sent as item 7 of Task 5 round 1.
Task 5: round 1 fix 7d155bb (items 1-7; key = SiteEngine.fills_wanted; _docked_with teardown in try/finally; latch kept on no-drawing; SITE_SLOW_CELL 0.055; redraw-once test counts fill requests). Pushed; CI 44678398735 running; re-review (opus) dispatched.
Task 5: fix round 1/5 (6 addressed, 1 partly — the key still moves when the slider crosses a grid's axis end (my round-1 wording); commits b32f19f..7d155bb). Round 2: key on ready grids with an axis, not with a window. Fix round 2 dispatched (resume implementer).
CI 44678398735 on 7d155bb: 4.2 job failed — MID_CELL 0.35 s on CI < 0.4 s floor (CI ≈0.47× this machine this run); redraw_once now passes. Sent as item 9 of Task 5 round 2.
Task 5: round 2 fix 661eeb8 (key = lattice + ready grids with an axis + fill keys; pinning test crosses C's axis end; MID_CELL 0.018, SLOW_CELL 0.015, SITE_SLOW_CELL 0.05). Pushed; CI 44680997816; re-review (sonnet) dispatched.
Task 5: fix round 2/5 (2 addressed, 0 open — key on ready grids with an axis; CI-calibrated cells; commits 7d155bb..661eeb8)
Task 5: minor (deferred): thickness crossing an axis end covered by reasoning only; grid losing its axis (restart) untested; in-flight-move-then-landing sequence tested only via the idle path; fixture margins rest on one CI observation (0.47×)
Task 5: complete (commits 0fb3898..661eeb8, review clean). ALL PLAN B TASKS COMPLETE. Next: CI on 661eeb8 (lint to re-run: network error), then the final whole-branch review.
Final whole-branch review of Plan B (opus) dispatched on review-16c1532..661eeb8.diff
CI 44680997816 on 661eeb8: both plugin-qgis jobs (3.44, 4.2) GREEN; only lint failed (pip network error before any check). Re-ran the failed job.
CI 44680997816 lint re-run: [exited with code 0]
Final review (opus): With fixes. Strengths: tasks fit, thread-safe end to end, every leaving path stops, nothing draws in the caller's frame, cuts/exports intact, copy+W1 right, no assertion weakened. I1 (Important, cross-task): Whole site fills only grids with a window here, but the stretch/rest need every ready grid's fill → stale stretch that stays stale, a min-curv GUI-thread build via the rest, memory old+new (probes). Minors M1 double slicing per tick, M2 FillFlow keeps landed fills, M3 thin test margins (gap measured across settle; SLOW_CELL 1.5× floor), M4 Cancel tooltip. Deferred triage: none must-fix alone; fold D1-D4.
Final fix wave dispatched (one fixer: resume the Task 5 implementer) — final-findings.md
Final fix wave 0ae9323 (I1 every ready grid's fill when the shared stretch applies; M1 one slice/tick; M2 flow releases landed jobs; M3 GAP_LIMIT_S 0.3; M4 tooltip; D1-D4). Pushed; CI 44684986620; scoped re-review (opus) dispatched; controller running site_scope+slices_dock at FILL_BUDGET_S=0.0001 in scratch tiny/.
Tiny-budget run (FILL_BUDGET_S=0.0001) at 0ae9323: test_plugin_site_scope.py 177/177 pass; test_plugin_slices_dock.py 40 fail — those dock tests assume a quick fill draws in the same tick (docked grid fills 2-71 ms here vs the 0.2 s budget, ≥~3× headroom; CI runs faster). Accepted by design; deferred minor: dock tests' same-tick assumption could flake on a runner >3× slower than this machine.
Final fix wave re-review (opus): all addressed except I1(b) residual — the rest (_on_rest) still builds a grid's plan on the GUI thread when the slider moves mid-fill with a grid outside the window still filling (probe: GUI blocked ~2 s, memory doubled). New minors: the picture waits for out-of-window grids when a shared stretch applies (probe: 1.6 s extra on site3; only for grids with differing axes); status-line redraw time now omits slicing; Cancel of a display_limit-started fill latches with the wrong note; _coverage_for None vs weights_cached mismatch edge (converges); stale "0.25 s" comment.
Ruling: R1 (residual I1(b)) is fixed with the reviewer's one-condition gate in _on_rest plus its probe as a test, as a small targeted commit beyond the one-fix-wave rule — it is the spec's core promise ("never frozen", #193) and the walkthrough exercises fine cells; cost if wrong: one more small commit and a scoped check. The other residual minors go to the follow-up issue and the walkthrough checks.
Task R1: dispatched (resume the Task 5 implementer)
Deploy: profile ns_geo_site_stuck created (copy of ns_geo) with nsgeo_qgis linked to this worktree (plugin enabled). Sunnyside copy: site t1 45.2 ns ends before every grid's cutoff (Grid1/5/7/8/9 cut 46-50 ns, others none) — the walkthrough exercises I1 by setting the site's end time to ~60 ns.
CI 44684986620 on 0ae9323 (final fix wave): SUCCESS — all jobs incl. plugin-qgis 3.44 + 4.2.
R1 1d48977: _on_rest asks for stretch_solves only when the flow is idle and every ready grid holds its weights; probe test failed first ('the rest built a plan on the GUI thread'), passes; fill_flow+site_scope 227 passed. Pushed. Note for follow-up: if weights_cached(finish) stays False (the _coverage_for None edge), the min-curv final stretch is never armed (provisional stays).
Walkthrough published: https://claude.ai/artifact/H981i4nUyuM1cYhLZnM5Yz (db collection checks/<id>: result pass|fail|skip, note, at). 11 checks. Copy backed up at ~/nsgeo-site-walk/Sunnyside.orig. Profile ns_geo_site_stuck.
CI 44687841627 on 1d48977 (branch head): SUCCESS — all jobs.
MEASURE AFTER (measure-after-report.md): Whole site 0.02 m — edit→picture 95-104 s, stretch +1.0-1.2 s in background, p99 gap 12 ms, BUT the landing draw (on_done) blocks 2.7-3.1 s; Grid1 min-curv largest gap 1.0 s (landing); Grid6 0.27 s; Cancel 0.055 s. Over the author's ~1 s line → splitting the landing draw before bringing it to the author.
Landing split (load ~1): Whole site landing 2.56 s = 1.85 s SiteEngine._gather on the new lattice (first draw only) + ~0.65 s per tick (compose 0.34, _shown 0.20, _sliced 0.12, layer 0.04); later tick 0.61-0.67 s. Grid1 landing 0.92 s = 0.53 s first to_north_up plan (first draw only) + 0.25-0.4 s per tick. Bringing to the author per their >1 s rule.
AUTHOR'S DECISION (2026-11-20): move the first draw's one-off work (site footprints 1.85 s; This grid's first north-up plan 0.53 s) into the background job; per-tick draw stays in the follow-up. Plan B Task 6 added (fb8cd0b). Task 6: dispatched (implementer sonnet).
Task 6: implementer agent a8959b5520fc5e75f (BASE fb8cd0b)
Task 6: implementer DONE 4b229d0 (FootprintJobs join the fill list, silent after the fills; FillJob warms the north-up plan via new core warm_north_up_plan (exported + README); coverage-mode first draw also via the flow; one test's job count updated). Pushed for CI. Task 6: review (opus) dispatched.
Task 6: review (opus) Needs fixes — I1 coverage route (unrequested) cancels running site fills on a coverage tick (probe: 6 jobs → 0; base kept 3); I2 _land_footprint refusals unpinned (reduced-condition mutant passes). Strengths: thread-safe footprint build with a context copy, _gathers GUI-only, old gathers dropped first, no loop.
Ruling: minors 1 (stale warm insert after cancel) and 4 (lazy import) folded; minors 2 (failed gather wording), 3 (coverage working-line wording), 5 (This grid coverage first draw builds the plan inline) deferred to the follow-up.
Task 6: minor (deferred): a failed footprint gather reads "could not work out the fill" and keeps the old picture with no error readout
Task 6: minor (deferred): a coverage-only footprint request's line says "working out the fill"
Task 6: minor (deferred): This grid's coverage-mode first draw after a cell change still builds the north-up plan on the GUI thread
Task 6: fix round 1 dispatched (resume implementer) — task-6-findings.md
CI 44741437610 on 4b229d0 (Task 6): SUCCESS.
Task 6: round 1 fix 5e744dc (coverage waits while working; 6 direct footprint-landing tests, combined mutant fails 3; warm_north_up_plan re-checks should_stop after the build; lazy import moved). Pushed; CI 44744620333; re-review (sonnet) dispatched.
Task 6: fix round 1/5 (3 addressed, 1 partly — lattice / not-ready refusal tests not isolating; commits 4b229d0..5e744dc). Fix round 2 dispatched (resume implementer).
Task 6: fix round 2/5 (1 addressed, 0 open — refusal tests isolate their own checks; commits 5e744dc..f09a418). Task 6: complete (commits fb8cd0b..f09a418, review clean). Pushed. Next: re-measure the landing on Sunnyside.
AFTER TASK 6 (f09a418, load ≤1.2): Whole site largest gap 0.651 s (the landing draw = per-tick 0.58-0.65 s), p99 11 ms, edit→picture 92.5 s, →stretch 95.0 s, RSS 2.04 GB; Grid1 largest gap 0.449 s (tick 0.23-0.28 + GIL contention with the stretch job), →picture 22.2 s; _gather 1.85→0 s on GUI; first to_north_up 0.53→0.055 s; every gather_footprint (65) and _build_north_up_plan (2) on nsgeo-fill_0. Walkthrough page v2 adds these numbers.
CI 44744976508 on f09a418 (branch head): SUCCESS — all jobs.
WALKTHROUGH (author, 2026-11-20 11:10-11:31 CST): 9 pass + ws-fine pass-with-note + export FAIL. Notes: ws-fine — fill responsive, but "Working out the colour stretch" froze the whole computer ~60 s, recovered. ws-live — "they moved but didn't seem to affect the picture?" (expected: the picture is held until the landing, which draws at the panel's depth/thickness). export — "Export isn't greyed out, it throws a message when you click on it and doesn't open though."
ws-fine evidence: kernel global OOM 11:16:19 (swap 2 GB full, free swap 104 kB, file cache 12 MB → desktop thrash), killed gvfsd-metadata (2.5 GB, a GNOME leak). At the kill QGIS held 2.48 GB anon; total anon 12.9 GB (code 2.4, claude 2.0, chrome 1.1, gnome-software 0.9 ...). Walkthrough QGIS VmHWM 3.47 GB later.
Memory probe (test_zz_probe_mem.py.keep, scratch copy of Sunnyside.orig, 0.02 m Whole site): fill phase 0.93→1.19 GB, landing draw →1.43, STRETCH →2.04 GB peak (+0.64 GB, 3.9 s) = the process peak; same as before the branch (Plan A measure 2.05 GB). Cause: the site's stretch listed every window's shown slices (334 MB float64 at 0.02 m, 12 windows × 3.48 M cells) and limit_over_slices joined every finite value into one more copy, for clips that then read 200 000 strided values.
Ruling: stream the site's stretch (StretchJob and SiteEngine._measure) and have limit_over_slices hand a max_samples clip only the strided values it reads (one rule, render.sample_stride) — exact (pinned by equality tests over ragged NaN/inf parts and budgets 1/7/50/1000/200000, and the existing job-equals-stretch_limit tests), measured peak 2.04 → 1.81 GB. Done in-branch because the walkthrough hit it in this session's promise ("never frozen"); cost if wrong: one revertable commit. Further cuts would change which values the stretch samples (follow-up issue).
Export probes (test_zz_probe_export*.py.keep): button greyed correctly on open, untick/tick, This grid → Whole site; a 0.05 m site export completes in 10.6 s (16 bands). A second Export while an export runs: button enabled, message "an export is already running…", no dialog — reproduced. Author's copy: slices/ born 11:30:27 (dialog accepted, export started), emptied 11:31:25 (export ended with no file: cancelled or failed). Asking the author which message and what ended the export.
Stretch fix 4a6f029 pushed (affected QGIS files 575 passed; core 1722 + pure 424 pass). Main merged in c3da920 (clean; #234 etc.); CI 44790708802 on it.
AUTHOR (2026-11-20): export — "I started the export, clicked the export again and got the 'An export is running' message; a while later I cancelled the export because I didn't really need it." So the export worked and cancel worked; the fail is the button staying enabled while an export runs.
Ruling: grey Export while a GeoTIFF export runs, in both scopes (one rule: site_scope.offer_export, with a tooltip saying why; the plugin re-reads it when an export starts and in a finally after on_done); the entry's own refusal stays. Small, pinned by a This-grid and a Whole-site test. Cost if wrong: a disabled button the author did not want — one-line revert.
Walkthrough copy reset from Sunnyside.orig (cell 0.1). Page v3 adds a re-check section (rc-export, rc-stretch) and answers ws-live.
CI 44790708802 on c3da920 (merge of main + stretch fix): completed success
Export fix 7320f58: dock/site/fill/export files 613 passed locally. Pushed.
Walkthrough re-check: rc-export pass, rc-stretch pass (no OOM kill). Author: merge main if needed, push, PR, merge if CI passes.
