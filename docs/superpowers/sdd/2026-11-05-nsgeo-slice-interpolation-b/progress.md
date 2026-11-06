# SDD ledger — plan: docs/superpowers/plans/2026-11-05-nsgeo-slice-interpolation-b.md

Spec: docs/superpowers/specs/2026-11-02-nsgeo-slice-interpolation-design.md (§5.4, §7 amended 2026-11-05 by the user).
Branch nsgeo-slice-interpolation-b, start 4695b88 (main 617399e). Baseline core+pure 937/3 skipped, QGIS 1366.
Models: T1 opus (numerics), T2 sonnet (algorithm given), T3 opus (multi-file state machine), T4 sonnet, T5 sonnet; reviews opus (user tiers).

## Pre-flight scan

| Pair / task | Produces → consumes | Found |
|---|---|---|
| T1 → T2 | SolveStopped, plan_curvature (responsiveness test) | consistent |
| T1 → T3 | plan_fill("min_curvature") → CurvaturePlan; solve(values, should_stop); METHODS | consistent; T3's pure estimate test (1.5×96 B/cell for plan_fill+apply) measures T1's code → R2 |
| T2 → T3 | Refiner start/cancel/busy/shutdown; RefineJob.run(should_stop) ← PendingSolve | consistent; both edit slices_plan.py constants (sequential) |
| T3 → T4 | finish_is_slow, preview, pending_solve, stretch_solves, shared_limit(preview=), PendingSolve.land, dock.refiner | site stretch_solves window set ambiguous → R3 |
| T3 → T5 | dock.refiner.cancel(); engine._last_solve_ms in export test | consistent; both edit plugin.py and test_plugin_slice_export.py (sequential) |
| T4 → T5 | site export path | consistent |
| T1 self | tests vs algorithm (should_stop before each iteration; 0-target skip) | consistent |
| T2 self | busy semantics vs poll algorithm; error stops list; raising on_landed contained | consistent; timing test flagged report-don't-loosen |
| T3 self | tests force `_last_solve_ms` but a plan build resets it → R1 | |
| T4 self | `_wait_for_refine` copied from T3's test file (plan says copy) → R4; same reset trap → R1 | |
| T5 self | tests vs plugin changes | consistent |

## Rulings

- Ruling R1: tests that force `engine._last_solve_ms` must do so after the min_curvature plan exists (after a first draw/finish), because building a plan resets it to None by design (plan call 8) — carried into T3/T4 dispatch — cost if wrong: none; it only orders test setup.
- Ruling R2: T1's implementer must keep `plan_fill(..., "min_curvature")` + one `apply` within 1.5 × WEIGHT_BYTES_PER_CELL (144 B/cell) of tracemalloc peak on 0.5 m binned lines at 0.05 m (T3 pins it); report the number rather than loosen — cost if wrong: a T3 test fails and T1 is reopened.
- Ruling R3: SiteEngine.stretch_solves covers exactly what SiteEngine.shared_limit measures — the SITE axis's `limit_windows`, mapped to each ready grid with `window_on` — not each grid's own limit_windows — otherwise the final site stretch would still solve on the GUI thread — cost if wrong: site stretch stays provisional or solves synchronously.
- Ruling R4: `_wait_for_refine` is copied per test file as the plan says, matching the per-file `settle()` helper convention in tests/qgis — cost if wrong: one ~8-line helper duplicated.

## Progress
- Task 1: dispatched (BASE 4695b88, opus implementer a9a342eeee8f772bb)
- Task 1: implementer DONE_WITH_CONCERNS 6357aa1 (core+pure 981/3; 0.2 m full 69 ms, 0.1 m 0.90 s, 0.05 m 14.6 s; R2 peak 104 B/cell).
- Ruling R5 (T1 concern 1): the brief's one-line test (all cells within 1e-4 of sin(x) line values) was a plan defect — the exact thin-plate energy bends a varying line by up to 1.1e-2 (dense solve). Replaced by: a straight profile stays flat, and sin(x) is symmetric about the line (no tilt). — cost if wrong: a weaker pin on collinear data.
- Ruling R6 (T1 concern 2): extra CurvaturePlan fields `cell`, `max_distance_m` accepted (needed for plan call 10's re-plan around non-finite data). — cost: none.
- Ruling R7 (T1 concern 3): plan call 3's equal row/column average replaced by a 1/span-weighted average (measured 56→42 it at 0.2 m, 184→158 at 0.1 m; orientation-agnostic, unlike the spike's columns-only). float64 dots kept. — cost if wrong: a slightly worse start; the solution is the same within tolerance.
- Ruling R8 (T1 concern 4): float32 robustness extras accepted (diagonal from the off-diagonals; solve centred on the data mean). — cost: none.
- Note for T3 (T1 concern 5): slices_engine.py annotates plan_fill's result as FillWeights (lines ~237, ~1032); widen to SliceFill / the union.
- Note: at 0.2 m on the 50 m synthetic the solve (~57 ms after R7) exceeds LIVE_SOLVE_BUDGET_MS=50, so large grids take preview+refine at the default cell; small real grids (~5 ms) stay live. Walkthrough item.
- Task 1: R7 applied 24f99c6 (0.2 m 49 ms, 0.1 m 0.79 s, 0.05 m 12.2 s; peak 103 B/cell; core+pure 982/3). Review dispatched (opus af3112d3c8d8283d0) on 4695b88..24f99c6.
- Task 1: review Approved, spec ✅ (no Critical/Important). ⚠️ items resolved: timings/peak/counts are implementer measurements (R2 is pinned by T3's test; QGIS tier runs in T3).
- Task 1: minor (deferred): test_a_solve_stops_when_asked's no-mutation check uses float64 values, so it cannot catch in-place mutation of float32 input (the plugin's dtype); run it on float32 (reviewer verified a surviving mutant).
- Task 1: minor (deferred): a lone line near the frame edge solves with a small y-tilt (4e-4..3e-3 of range at 0.05 m) — the ε mode is below float32 resolution; tightening tol makes it worse. Document in curvature.py or file beside #111.
- Task 1: minor (deferred): a stalled solve (pq<=0 break or the iteration cap) returns silently; T3's cache cannot tell it from a converged one. Untested.
- Task 1: minor (deferred): rulings R5–R7 lived only in the ledger → FIXED by controller doc commit (plan amended).
- Task 1: minor (deferred): small test helpers (STEP, ROWS, lines, values) duplicated between test_slices_curvature.py and test_slices_interpolate.py.
- Task 1: complete (commits 4695b88..24f99c6, review clean)
- Task 2: dispatched (BASE 42c93a1, sonnet implementer ac6c2a1c1f155ecda)
- Task 2: implementer DONE 791d9f2 (refine 9/9, QGIS 1375, core+pure 982/3; responsiveness ticks 42-44 over 7 runs). Review dispatched (opus ad86c273464392e1b) on 42c93a1..791d9f2.
- Task 2: review Approved, spec ✅, 0 Critical/Important, 9 Minor.
- Ruling R9: Task 2 minors 1–6 and 9 (shutdown after parent deletion; a list ending without landing/error leaves busy True forever; empty error messages; pytest.fail as on_error escapes the slot; unbounded loop job can hang the suite; join not pinned; duplicate hooks fixture) are fixed now in one resumed round, not deferred — Task 3 builds directly on shutdown()/busy and copies these test patterns — cost: one small round.
- Task 2: minor (deferred): the responsiveness test's tick threshold (10) passes even for a GIL-holding pure-Python job (21 ticks); a ratio check (≥0.8× expected ticks) would pin "numpy releases the GIL" but may flake on CI — user's call; left as the brief specified.
- Task 2: minor (deferred): a job finishing just as it is cancelled can leave one stale entry (its values/result/plan) in the queue until the next non-empty start() drains it — bounded to ~1 entry.
- Task 2: note for T3: start([]) never calls on_landed (dock must treat an empty list as "ended"); after cancel(), busy is False although the worker may finish its current iteration.
- Task 2: fix round 1 (R9) a0a9e0d — 7 minors fixed, refine 12/12 ×5; scoped re-review dispatched (opus a207c22709472fae4) on 791d9f2..a0a9e0d.
- Task 2: fix round 1/5 (7 addressed, 1 open — new Important: the 5 s loop bound lets a shutdown-without-cancel mutant pass the shutdown test; commits 791d9f2..a0a9e0d)
- Task 2: minor (deferred → folded into round 2): the BaseException test used MemoryError (an Exception); thread found by name; poll.start unguarded after parent deletion.
- Task 2: minor (deferred): _describe keeps a non-empty but unhelpful message without the type name (KeyError('k') → 'k'); the brief's errors == ["no good"] expects the bare message.
- Task 2: minor (deferred): an exception whose __str__ raises would end a list silently with busy True (very unlikely).
- Task 2: fix round 2 3f5346c (shutdown timed <1 s + exited-on-stop; Fatal(BaseException) test; thread object; start guard) — refine 14/14 ×5; scoped re-review dispatched (opus a5b6a2634b0bb5c92) on a0a9e0d..3f5346c.
- Task 2: fix round 2/5 (3 addressed, 0 open; commits a0a9e0d..3f5346c). Shutdown timing: ~1 ms idle, ≤9 ms under 8-way CPU load (1 s bound).
- Task 2: minor (deferred): start()'s parent-deleted guard returns without cancelling a running list (busy stays True until shutdown); its log text names "shut down" for the parent-deleted path too.
- Task 2: minor (deferred): the re-raise of non-Exception BaseExceptions in _run_list is unobservable (the executor stores it on an unread future) — comment it or drop it.
- Task 2: complete (commits 42c93a1..3f5346c, review clean)
- Task 3: dispatched (BASE 3f5346c, opus implementer a9c153c0484a69061)
- Task 3: implementer DONE_WITH_CONCERNS c3d4459, 0c3eeeb (core+pure 990/3; QGIS 1406 full + 1 dock test after; extras: solve_key(), PendingSolve(copy=False), job dedupe, tooltip test; timing-margin flake risk flagged). Review dispatched (opus a6aacd5dcd1742e69) on 3f5346c..0c3eeeb.
- Task 3: review Approved, spec ✅, 0 Critical/Important, 9 Minor. ⚠️ "Ruling R2" not in reviewer's materials — it is in this ledger (estimate bound); counts are implementer-reported.
- Ruling R10: Task 3 minors 1 (2–3 BLAKE2b hashes per draw, 14–56 ms/tick at fine cells; stretch_solves used as an emptiness test), 2 (two stuck-provisional cases: _on_rest with no jobs; non-final stretch never re-armed after an error), 3 (rebuild holds old plan+preview+cache while building, ~0.86 GB at cap), 5 (estimate test's constant data never runs CG), 6 (unload test's global thread scan; rest test's wall-clock margins), 9 (display_limit docstring) are fixed now in one resumed round — Task 4 copies this state machine and Task 5's export triggers case 2 — cost: one round.
- Task 3: minor (deferred): switching min_curvature → kriging rebuilds kriging weights (~5.9 s at 0.05 m) although the held preview is the identical build; reuse is worth filing.
- Task 3: minor (deferred): the job.key == _refine_key check in _on_landed is unreachable by tests (kept as defence).
- Task 3 → T4 note: entering Whole site does not cancel This grid's running list (up to 13 solves keep running); Whole site currently offers Minimum curvature with synchronous solves and an unused preview per grid — Task 4 settles both.
- Task 3: fix round 1 (R10) e8a0d9e — 6 fixed (stretch_limit(n, clip, finish)->(value, final) instead of a readiness check; declined cached jobs touch LRU; no-job rest drops stale provisional stretch); QGIS 1411, core+pure 990/3. Scoped re-review dispatched (opus ab4c2a89d6d0d8883) on 0c3eeeb..e8a0d9e.
- Task 3: fix round 1/5 (6 addressed, 0 open; commits 0c3eeeb..e8a0d9e). Re-review: no idle loop (0 rests/redraws over 2 s idle), keys never paired with other arrays, stretch_limit final == shared_limit.
- Task 3: minor (deferred): display_limit docstring says the re-arm needs "no rest pending" but the fresh-measurement branch only checks refiner idle (harmless).
- Task 3: minor (deferred): the _job_for recency touch is untested (only speeds settling).
- Ruling R11: every rest calls stretch_solves (slices + hashes 12 windows on the GUI thread, ~84 ms at 1 M cells, ~340 ms at 4 M) even when the stored stretch is already final — Task 4 skips it when the stored stretch is final for the current key, in BOTH scopes (it edits slices_dock._on_rest too) — cost if wrong: a stale-final check could skip needed stretch solves; covered by a test.
- Task 3: complete (commits 3f5346c..e8a0d9e, review clean)
- Task 4: dispatched (BASE e8a0d9e, opus implementer a22740f76761c6070 — escalated from the planned sonnet: mirroring Task 3's state machine into the coalesced site tick needed an opus round plus a fix round in T3; carries R1, R3, R4, R11, scope-switch cancel)
- Task 4: implementer DONE_WITH_CONCERNS e203151 (QGIS 1426, core+pure 990/3; 11/11 mutants; new ui/refine_flow.py RefineFlow shared by both scopes; new keep rule: a preview waiting only on solves at the head of the running list keeps that list; extra API SiteSlice.previewed, pending_solves(drawn=), SiteEngine.stretch_limit, SliceEngine.is_solved/window_solve, PendingSolve.engine).
- Task 4: review dispatched (opus aa5f328fbbd63a507) on e8a0d9e..e203151.
- Task 4: review Needs fixes — spec ❌ (keep rule breaks plan call 5 on a finish edit), Important 1: the keep rule's identity (engine, key) omits the plan, so a max-distance/search-radius/spacing edit mid-refine keeps a list of dropped-plan jobs (5 stale in This grid, 39 in Whole site; minutes at 0.05 m); also keeps a list after a grid leaves (waits <= head). 3 Minor.
- Ruling R12: Task 4 minors 1 (site rest re-slices/re-hashes fully drawn grids), 2 (site cancels after building new plans — peak memory and CPU contention), 3 (keep rule pinned only through the site) folded into fix round 1 — same decision code — cost: a larger fix round.
- Task 4: departures accepted after review: ui/refine_flow.py RefineFlow (one state machine for both scopes); keep rule (a preview waiting only on the running list's head keeps it) — sound once identity includes the plan; extra API (SiteSlice.previewed, pending_solves(drawn=), SiteEngine.stretch_limit, SliceEngine.is_solved/window_solve, PendingSolve.engine).
- Task 4: fix round 1 dispatched (resume a22740f76761c6070).
- Task 4: fix round 1 ac4aab9 (holds(plan) keep-check, waits == head, before_draw(rebuilds=) cancels before building in both scopes, mixed-tick hashing, This-grid keep test; QGIS 1437, core+pure 990/3; stale solves 5→0 and 39→0). Scoped re-review dispatched (opus a8029b5d198e3aae3) on e203151..ac4aab9.
- Task 4: re-review a8029b5d198e3aae3 hit the 5-hour API limit mid-review; resumed on the user's 'continue'.
- Task 4: fix round 1/5 (4 addressed, 1 open — new Important N1: before_draw(rebuilds=not weights_cached) is True on every site tick while a ready grid has no window at this depth, so landing redraws cancel the other grids' solves; commits e203151..ac4aab9)
- Task 4: minor (deferred): weights_cached compares the key only, not the populated mask, so a mask-only rebuild in the site is caught after the build (by holds()).
- Task 4: minor (deferred/optional in round 2): finished jobs in _done and _run_list's job list keep dropped plans until the next drain / next should_stop.
- Task 4: fix round 2 dispatched (resume a22740f76761c6070).
- Task 4: fix round 2 85b08cf (weights_cached(at=(top, thickness)) counts only grids with a window there; one 'builds' flag drives before_draw and the wait cursor; landing test on site3 and short-C site; QGIS 1439). Optional plan release not taken (land() and the keep rule need job.plan).
- Task 4: fix round 2/5 (1 addressed, 0 open; commits ac4aab9..85b08cf). Cursor coverage verified on every build path; none on landing redraws.
- Task 4: minor (deferred): plain weights_cached(finish) (no at=) skips ready grids whose z is None; only display_limit's measurement uses it (harmless).
- Task 4: complete (commits e8a0d9e..85b08cf, review clean)
- Ruling R13: an export stops refining through the active scope's flow (This grid: dock._end_refine(); Whole site: dock._site.refine.stop()) and resets the status, not a bare refiner.cancel() — a bare cancel leaves the flow believing a list runs and the status saying "Refining…"; after the export (any outcome) the dock redraws once so a standing preview re-arms its rest; one dock helper used by both export paths — cost if wrong: a redraw after export that wasn't needed.
- Task 5: dispatched (BASE 85b08cf, sonnet implementer a134a19a9192fa0c1)
- Task 5: implementer DONE c13b7e9 (QGIS 1452, core+pure 990/3; R13 helper SlicesDock.refining_paused() context manager; shared _mtime_ns/_remove_partial; departure: 'file not reached' mtime test uses a stubbed exporter since the GDAL writer creates the file before band 1).
- Task 5: review dispatched (opus a2461452989a0026c) on 85b08cf..c13b7e9.
- Task 5: review Approved, spec ✅, 0 Critical/Important, 5 Minor.
- Task 5: minor (deferred): refining_paused()'s finally redraw runs inside the export's try; if refresh_slice ever raised after a good export the file would be deleted and reported as a failure (latent; both scopes' refresh paths are guarded today) — suppress+_log around the redraw.
- Task 5: minor (deferred, walkthrough item): at ~10 s/band (min curvature, 0.05 m) the UI freezes ~one band with no dialog/wait cursor, then the dialog sits unpainted until the next band (bands solve on the GUI thread per plan call 11); a wait cursor or one processEvents() after show would soften it; _export_progress docstring overstates event pumping.
- Task 5: minor (deferred): duplicated fake-progress-dialog test helpers (slice_export_dialogs vs site_scope) could live in plugin_testing.
- Task 5: minor (deferred): the site cancel test does not assert "no Critical" (the This grid test does).
- Task 5: minor (deferred): _export_progress types the dialog as Any; precomputed band total duplicates the plan's count.
- Task 5: complete (commits 85b08cf..c13b7e9, review clean)
- Final whole-branch review dispatched (opus a90eb093e3817aad9) on 617399e..c13b7e9 (414 KB package).
- Filed on the user's request (2026-11-05, side questions): #112 show the slice's pixel size next to the cell size (rotated → half pitch, 4× export pixels); #113 store only covered cells in a resident cube (5–10× less memory at fine cells).
- Final review: Ready with fixes. 0 Critical. Important: I-1 slow export shows no dialog/cursor/cancel for its first two bands (setValue only shows at band 1 and pumps from band 2; 20–64 s freeze at 0.05 m–cap); I-2 min-curvature overshoot is mostly past the outermost line/line ends/skipped-line sides (up to 1.6% cells outside data range on real lines, −0.51 on non-negative data), but the guide/spec say "between lines". Minor M-1..M-6. All departures accepted. Deferred-minor triage recorded in the reviewer report (fix-before-merge: Task 5 refining_paused guard + slow-band feedback, both folded into I-1).
- Ruling R14: the final fix wave takes I-1, I-2, M-1 (rest must not build a plan; defer to the debounced redraw), M-2 (Whole site judges slow per TICK: preview every uncached grid when the sum of their last solve times, None = slow, exceeds LIVE_SOLVE_BUDGET_MS), M-3 (rest-timing margin), M-5 (cancel the site list when ready_grids changes), M-6 (key= trust documented; CurvaturePlan arrays read-only). M-4 (uncounted transient memory, ~0.39 GB at the cap) goes to a follow-up issue — cost if wrong: one larger fix wave.
- Final fix wave dispatched (BASE c13b7e9, opus abe14616d55a886ea) with final-findings.md (I-1, I-2, M-1, M-2, M-3, M-5, M-6).
- Filed #114 (trace stacking step in the processing panel: running mean along traces, keeps the trace count). User declined rectangular (X≠Y) cells for now (2026-11-05): 0.05 m stacks only a little and stacking likely helps; revisit only with a concrete use case.
- Final fix wave DONE_WITH_CONCERNS db8b2f5, 21e51cf, 75d286e, 0a31911 (QGIS 1471, core+pure 991/3). Concerns: test_a_site_tick_hashes_each_grids_slice_once's quick case reworked for M-2; a quick min-curvature export shows no dialog before band 0 (only when last solves sum > 50 ms or untimed); Method tooltip still says only 'overshoot beside a sharp change' (deferred minor); M-3 no RED (timing margin).
- Final fix wave: scoped re-review dispatched (resumed final reviewer a90eb093e3817aad9) on c13b7e9..0a31911.
- Final: minor (deferred): the Method tooltip still says only 'overshoot beside a sharp change'; align with I-2's guide wording later.
- Final fix wave: scoped re-review — all 7 ADDRESSED, no new Critical/Important (c13b7e9..0a31911).
- Final: minor (deferred): after a Whole-site landing, M-2's shrinking per-tick cost can make the redraw full, solving the last grids on the GUI thread while the worker solves the same slices (bounded by the live budget; same result). Optional fix: treat a grid at the running list's head as still awaited.
- Final: minor (deferred): pending timers (finish debounce, site tick) can now fire from export band 0/1 and start a background list mid-export (CPU competition only). Optional: refining_paused() sets a flag the rest slots check.
- Final: minor (deferred, walkthrough item): R14 previews every grid in a mixed site (one slow grid makes small grids preview too); a finer rule would preview the slowest until the rest fit.
- Final: Method tooltip aligned with I-2 directly by the controller (cosmetic, per the user's right-size rule) (bc76e49).
- Deployed: new QGIS profile ns_geo_mincurv (copy of ns_geo_interp), nsgeo_qgis symlinked to this worktree (bc76e49). Walkthrough artifact https://claude.ai/artifact/3XELRcTA4YHKWWAfGBGzfR (db collection results, 31 checks, stages A–J; J = Surfer comparison, required). Human gates OPEN: walkthrough, Surfer comparison, follow-up filing. Workspace kept until after the walkthrough (decision record to be committed under docs/superpowers/sdd/ as milestone A did).
- Walkthrough round 1 (2026-11-06): 28/31 recorded — 21 pass, 5 skip (F3 grids all clipped at one depth; G4 kriging cancel; I1 close mid-refine; J1/J2 Surfer — REQUIRED gate not done), 2 unmarked with notes (C2 no meaningful seams; D1 wheel issue), H3 (optional) not recorded. User: kriging vs min curvature differences minimal at these settings except time; min curv "slightly cleaner"; no noticeable edge banding or seams; usual cell is 0.1 m; preview makes dragging feel smooth; #111 "not urgent but needs to happen".
- W1 (D1): with Minimum curvature, mouse-wheel over the depth slider gets taken over by the panel's scroll area. Measured cause (scratchpad label_heights.py): the word-wrapped status label at the dock's bottom changes height as states cycle (e.g. 400 px: normal 2 lines, preview 2, refining 1; 260 px: 2/3/2), re-laying out the scrolled dock so the slider moves from under the cursor; the next wheel event lands on the scroll area. Kriging never changes the status text, so it never happens there.
- W2 (E1/E2): the preview/refining status sits at the bottom of the dock, often off-screen from the slider, and its height jumps.
- W3 (E4): "Refining … (0 of 9)" — the count mixes the current slice with the stretch windows; unclear.
- User decisions 2026-11-06: Surfer comparison WAIVED for B (file as follow-up); W1–W3 fix = short fixed-height indicator beside the depth readout, bottom status back to memory only. Walkthrough fix round dispatched (BASE bc76e49, sonnet a447fb9470d204adf) with walkthrough-1-fixes.md.
- Walkthrough fix 364b236 (indicator 26 px fixed, min width 0; RED content 1227→1250 px, slider 352→329 px; QGIS 1478, core+pure 991/3). Departures: 'grids' wording by scope ("0 of 1 grids" possible); ElidedLabel subclass; LayoutProbe/slow_jobs helpers in plugin_testing.py.
- Walkthrough fix review dispatched (opus a83042231c138e606) on bc76e49..364b236.
- Walkthrough fix review: Needs fixes — Important: the Whole site layout test runs on a hidden dock (FakeIface main window never shown) and passes with the old wording restored. Minor: "Refining this slice…" over a final slice after moving back mid-refine; dock min-width assertion can't fail (scroll area pins 69 px); 260/400 px params identical (content min 475 px); ElidedLabel font-change height, clear(), tooltip; "(0 of 1 grids)"; ~37 s added test time.
- Ruling R15: all of the walkthrough-fix review's minors go into its fix round 1 with the Important — they are cheap and sit in the same lines — cost: a larger round.
- Walkthrough fix round 1 dispatched (resume a447fb9470d204adf).
- Walkthrough fix round 1 afec059 (site test on a visible dock, fault-applied RED fails at 260 px in both scopes; QGIS 1482). Note: the 560 px param passes under the fault (old line doesn't wrap there); 260 px is the proving width.
- Walkthrough fix round 1/5: re-review Approved (all addressed; Minor 3 and 6 partly). Controller applied the two residual one-liners directly (cosmetic/test-param, per the right-size rule) in 7f6175b: empty indicator carries no tooltip; wide layout param 560→520 px so it also fails on the original fault. 31 targeted tests pass. Push pending (DNS failure).
- Walkthrough fix: minor (deferred): `_ready` still runs twice/thrice in the slowed dock tests (harmless).
- Walkthrough fix: out-of-scope (check in real QGIS before filing): FinishPanel needs ~467 px offscreen ("Max distance to data" row), so docks narrower than ~490 px scroll sideways.
- Full QGIS suite on 7f6175b: 1482 passed in 813.06s (0:13:33). Walkthrough round 2 (K1–K4) added to the artifact; awaiting the user.
- Walkthrough round 2 (2026-11-06): K1–K4 all pass (wheel fixed). K2 note: the empty line under the readout looks like something missing; put the state on the readout's line with shorter texts ('Refining (x of y)', 'Colour stretch (k of n)'). Dispatched to the fixer (resume a447fb9470d204adf): one row [readout | indicator right-aligned, elided], texts Kriging preview / Refining… / Refining ({done} of {total})… / Colour stretch ({done} of {total})….
- Walkthrough round-2 fix 2046c21 (one row readout|indicator; shorter texts; fault-applied: 4 layout tests fail at 260/520 in both scopes; QGIS 1482).
- Round-2 fix review: Approved (readout keeps full width and priority; row height constant 26 px; fault fails all 4 layout tests).
- Round-2: minor (user's call): right-elision drops the stretch COUNT first at ordinary widths ("Colour stretch (0 …" at a 300 px dock with an 8pt font; full only from ~420 px). Option: a shorter form like "Stretch 0/5…".
- Round-2: minor (follow-up): below FinishPanel's minimum content width (~332 px realistic font, 475 px test font) the indicator is clipped by the scroll viewport rather than elided; root cause is FinishPanel's wide "Max distance to data" row (also causes sideways scrolling) — file after checking in real QGIS.
- Round-2: minor: the readout row's minimum is the readout's own plus 6 px spacing (harmless today).
- Round-2 look approved by the user ('looks great'); told to open a PR and merge if CI passes. Follow-ups filed 2026-11-06: #119 Surfer comparison (waived for B), #120 minimum-curvature follow-ups (all deferred minors), #121 FinishPanel width; comment on #111 with the walkthrough's verdict.
