# SDD ledger — plan: docs/superpowers/plans/2026-11-13-nsgeo-slices-wheel-notes.md

Spec: docs/superpowers/specs/2026-11-13-nsgeo-slices-wheel-notes-design.md (approved 2026-11-13).
Branch nsgeo-slices-wheel-notes; plan commit 3b34580. Real data symlinked into the worktree (gitignored).
Roadmap on main set to "Being built" (50708cf).
Models (user's tiers): implementers sonnet, reviews opus, quick fixes haiku; escalate when warranted.
Reviewers must not edit files in this worktree.

## Pre-flight scan

| Pair / task | Produces vs consumes | Finding |
|---|---|---|
| T1–T2 | both edit slices_dock.py, site_scope.py; T1's test helper `_short_and_active` used by T2's focus test | consistent; T2 dispatch told the helper exists |
| T1–T3 | T1 `set_spins_quietly` skip rules; T3 floor via `set_dz_floor` (separate) and seed_z values via set_spins_quietly | consistent: a floor raise is not skipped by the focus rule |
| T2–T3 | T2 Entry/REFUSAL/_grid_refusal/show_warnings/geometry_problem, `_set_cell_floor`; T3 consumes them, adds dz floor in restore_cube and per-grid TooManyLevels re-raise in SiteEngine._rebuild_geometry | consistent: a re-raised TooManyLevels sets geometry_problem and SiteScope.problem |
| T2–T4 | T4 asserts warnings_panel is not collapsible; T2 makes it QGroupBox | consistent |
| T2/T4–T5 | T5 measures the panel with Warnings and fold buttons | consistent (order matters: T5 last) |
| T1 self | Edit lines Key_Down emits activated (Linux/Fusion); half-typed test relies on "0." not emitting valueChanged | OK |
| T2 self | "clock warning listed after the REFUSAL and before the NOTE": REFUSAL (not drawn) and NOTE (drawn) never coexist | Ruling 1 |
| T3 self | message strings match the plan's format (t0=2 → "2", dz 0.5 → "0.5") | OK |
| T4 self | conftest autouse fixture and the never-touches test share tmp_path | OK |
| T5 self | site3 fixture lives in tests/qgis/conftest.py, usable from the new file | OK |

Ruling 1: the T2 clock-order test checks two cases: drawn → [WARNING, NOTE]; not drawn → [REFUSAL, WARNING] — the plan's single ordering can't occur, since warnings() shows the NOTE only while drawn and the REFUSAL only while not — cost if wrong: one test reworded.

## Tasks
Task 1: dispatched (implementer sonnet aa63b6f6ca9c3595f, BASE 3b34580)
Task 1: implementer DONE_WITH_CONCERNS (bee03f3). Concerns: (1) sendEvent wheel doesn't propagate; (2) seed_z setSingleStep only when it differs (re-renders text otherwise); (3) pytest needs `-p no:xonsh` in .venv-qgis.
Ruling 2: "panel scrolled" test uses a `propagate_wheel` helper replaying Qt's spontaneous propagation (synthesized wheel events reach only their receiver in Qt ≥5.12); real path checked in the walkthrough — cost if wrong: one helper.
Ruling 3: seed_z's setSingleStep-only-when-different accepted (needed for #105) — T3's dz floor must likewise set the minimum only when it differs.
Task 1: fix a6b545d (propagate_wheel). Review dispatched (opus acbab40e451f615d6) on 3b34580..a6b545d.
Task 1 review (a6b545d): spec ✅; Needs fixes — I1 Edit lines wheel test notches cancel (passes unguarded); I2 StrongFocus unpinned.
Ruling 4: Minor 1 (horizontal bar not connected) is a brief requirement ("scroll bars") → fixed in round 1 — cost: one connect.
Ruling 5: Minor 2 (closure outlives widget) → let-go becomes a guarded method of the filter QObject, round 1 — cheap hardening for boxes added later.
Ruling 6: Minor 3 (unguarded lambda, plan-mandated) → Global Constraint outranks the plan's literal line; guarded method — cost: a few lines in edit_lines_dialog (M19 clash still small).
Ruling 7: Minor 4 (setValue instead of typing) → real typing, per the user's "tests that dodge the hazard" rule — cost: test only.
Task 1: minor (deferred): propagate_wheel builds fresh accepted events per widget (docstring overstates fidelity).
Task 1: minor (deferred): wheel_event duplicates param_form's _wheel; param_form could use the shared helper.
Task 1: ⚠️ for walkthrough: real spontaneous wheel path; mouse pick from the popup then focus hand-back; Qt 6 run (CI).
Task 1: fix round 1 dispatched (resume aa63b6f6ca9c3595f), FIX_BASE a6b545d.
Task 1: round 1 fix cea5bb7; scoped re-review dispatched (opus ad43065bc9ff0e24b) on a6b545d..cea5bb7.
Task 1: fix round 1/5 (6 addressed, 0 open; commits a6b545d..cea5bb7)
Task 1: complete (commits 3b34580..cea5bb7, review clean)
Task 2: dispatched (implementer sonnet a45ac760cb07a74e6, BASE cea5bb7)
Task 2: controller session restarted mid-task; implementer resumed (a45ac760cb07a74e6) with work uncommitted in tree; asked to verify Ruling 1 order (drawn → [WARNING, NOTE]).
Task 2: implementer DONE_WITH_CONCERNS 01206ee (413 qgis + 301 pure passed). Concerns: geometry_problem also recorded by _rebuild_geometry_reporting; drawn requires geometry_problem None; RED not captured; Ignored-width labels.
Task 2: review dispatched (opus a52fb3d794a3eb4b0) on cea5bb7..01206ee.
Task 2 review (01206ee): spec ❌ on two pins — I1 width test races preparation (asserts nothing; policy unpinned); I2 focus test doesn't move the scroll value (passes under valueChanged mutation; part plan-mandated order). Production code judged correct; both deviations justified.
Ruling 8: restore_cube sets the cell floor even when the record has no resolution (spec §6.1 "as a grid change does") — round 1.
Ruling 9: drop the test-only duplicate geometry_problem record in _rebuild_geometry_reporting; test patches _rebuild_geometry_now — round 1.
Ruling 10: rename tests whose names contradict them (…not_only_a_toast, test_the_site_note_*) — round 1.
Ruling 11: assert clear() resets geometry_problem — round 1.
Task 2: minor (deferred): restore_cube's grid change doesn't clear _grid_refusal (transient until the post-prepare apply).
Task 2: ⚠️ Qt 6 wrapping/height-for-width of the Warnings labels unverified (Task 5's 4.2 run covers the dock file).
Task 2: fix round 1 dispatched (resume a45ac760cb07a74e6), FIX_BASE 01206ee.
Task 2: round 1 fix 36c5ecf; scoped re-review dispatched (opus a50eb946d07696e9b) on 01206ee..36c5ecf.
Task 2: fix round 1/5 (6 addressed, 0 open; commits 01206ee..36c5ecf)
Task 2: complete (commits cea5bb7..36c5ecf, review clean)
Task 2: minor (deferred): no test for ruling (a)'s case (record without resolution restored onto a higher-floor grid).
Task 2: minor (deferred): "value moved" assertion message reads as success text (test_plugin_slices_dock.py ~4340).
Task 3: dispatched (implementer sonnet a56790ad2bfbf8ebe, BASE 36c5ecf)
Task 3: implementer DONE_WITH_CONCERNS fc44964 (pure 305, engine 76, dock 195, site_scope 170, site_engine 58, slice_export 77). Concerns: site rebuild raises at first over-limit grid; set_dz_floor compares rounded floor; restore floor from first kept key in session.
Task 3: review dispatched (opus af483ec36b023305e) on 36c5ecf..fc44964.
Task 3 review (fc44964): ❌ — I1 (plan-mandated) mixed radars >2× apart refuse their own seeded default; I2 travel and restore-floor tests pass without their code (same-interval fixtures); I3 _level_problem swallows silently. Core mechanism judged correct.
Ruling 12: Whole site floor and arrow step = finest included interval; default dz seed (none remembered) = coarsest included interval, so no grid's seeded levels exceed its samples (spec §3.3 claim); a user-lowered dz can still refuse a coarser grid (correct, shown as Not drawn). Mixed-radar test moves to >2× ratio; add Whole site refusal test — cost if wrong: seed rule tweak.
Ruling 13: _level_problem keeps its guard but logs via _log.
Ruling 14: restore_cube's dz floor from self._included[0] after the fallback (covers records without lines; matches the seed).
Ruling 15: _apply_resolution clears _grid_refusal before set_resolution.
Ruling 16: correct set_dz_floor comment (setMinimum re-renders only when clamping); guard kept.
Ruling 17: shared first-header-per-grid helper for header_z_seed / site_dt_floor / coarsest.
Task 3: minor (deferred): SiteEngine names only the first over-limit grid (accepted).
Task 3: fix round 1 dispatched (resume a56790ad2bfbf8ebe), FIX_BASE fc44964.
Task 3: round 1 fix 9d81aad (dock 195, site_scope 171, engine 76, site_engine 58, pure 305). Flake noted: test_a_refine_for_a_window_left_behind_never_draws failed once under load, passed alone 3x.
Task 3: scoped re-review dispatched (opus a5521a34d37c065d5) on fc44964..9d81aad.
Task 3: fix round 1/5 (6 addressed, 0 open; minors left; commits fc44964..9d81aad)
Ruling 18: restore_cube floor from the first LIVE key of _included (KeyError skip dropped the floor for a stale first key) — round 2.
Ruling 19: seed dz from coarsest of the INCLUDED grids' first headers at all times (not coarsest ready) — corrects my round-1 wording; prevents a dz flip and one-tick self-healing refusal — round 2.
Ruling 20: _apply_resolution generic except path calls show_warnings() so no stale refusal beside the toast (completes Ruling 15) — round 2.
Ruling 21: tests for a record without lines (Ruling 14) and a stale first key (Ruling 18) — round 2.
Task 3: fix round 2 dispatched (resume a56790ad2bfbf8ebe), FIX_BASE 9d81aad.
Task 3: round 2 fix 093dfda (dock 198, site_scope 171, engine 76, site_engine 58, pure 305; ruff via ../../.venv/bin/ruff). Removed ready_dt; header_z_seed returns (z0, z1). Scoped re-review dispatched (opus ae19cd89b9fe9845c).
Task 3: fix round 2/5 (4 addressed, 0 open; commits 9d81aad..093dfda)
Task 3: complete (commits 36c5ecf..093dfda, review clean)
Task 3: minor (deferred → final wave): Resolution ValueError branch in _apply_resolution leaves a stale refusal beside its toast (spec §6.1 "a refusal stays until the value it refused changes"); also an exception before the clear at ~2574 re-shows the stale refusal.
Task 3: minor (deferred): no test pins that the site dz seed stays put while grids become ready (only start/end checked).
Task 3: minor (deferred): z_bound_never_chosen[nothing] compares against _coarsest_dt (repeats the formula); a literal would be stronger.
Task 4: dispatched (implementer sonnet a18774940170767d8, BASE 093dfda)
Task 4: implementer DONE_WITH_CONCERNS 41f1888 (388 passed + 1 flaky fail test_a_site_refine_for_a_window_left_behind_never_draws; pure 305). Coverage preview max-pools (tooltip stands). Concern: unfold on hidden site_finish doesn't carry back (QGIS ignores setCollapsed while hidden).
Task 4: review dispatched (opus ac9be6cf74982962b) on 093dfda..41f1888.
Flake check (controller): the two refine 'window left behind' tests run 6x concurrently at HEAD (41f1888) and at base 513867a: HEAD 2/6 runs with a failure, base 1/6 — pre-existing load-dependent flake, not introduced here. Mention in final report; offer to file.
Task 4 review (41f1888): ❌ — I1 Interpolation panels drift apart after both shown (QGIS applies setCollapsed only on first show; test dodged by never showing site_finish); I2 header click takes focus (QgsCollapsibleGroupBox StrongFocus). Coverage max-pool claim verified true.
Ruling 22: coverage test asserts the literal spec §7 text — round 1.
Ruling 23: restart tests check drawn height on a new shown dock; Normalisation test really restarts — round 1.
Ruling 24: re-wrap guide line 549 — round 1.
Ruling 25: fold slot syncs boxes before writing the setting — round 1.
Task 4: ⚠️ Qt 6 setCollapsed-while-hidden behaviour → Task 5's 4.2 docker run.
Task 4: fix round 1 dispatched (resume a18774940170767d8), FIX_BASE 41f1888.
Task 4: round 1 fix 6869186 (390 passed). Implementer found NoFocus alone doesn't keep focus (Qt hands a header click to the nearest click-focus ancestor, the QScrollArea) and added a focusChanged + 100 ms give-back.
Ruling 26: Important 2 misread spec §2 — "a section folding" means the fold's own movement must not count as a user scroll; a header click is a click elsewhere, and focus leaving the box is normal (and safer for the wheel hazard). Remove the give-back; keep NoFocus on the boxes (no extra Tab stops); test that a programmatic fold/unfold (with scroll-into-view) keeps dz focused, and NoFocus policy — cost if wrong: focus leaves a box on a header click, as on any other click.
Task 4: fix round 2 dispatched (resume a18774940170767d8), FIX_BASE 6869186.
Task 4: round 2 fix 813f65a (382 passed). Scoped re-review of rounds 1+2 dispatched (opus aeeb5579ed4cdc71c) on 41f1888..813f65a.
Task 4: fix round 2/5 (I1, I2-as-Ruling-26, R22, R23, R25 addressed; R24 open — guide line 549 still 119 chars; commits 41f1888..813f65a)
Ruling 27: drop the committed meta-test test_the_guard_would_let_go_on_a_value_change and its mutate param (tests a stand-in, not product code) — round 3.
Ruling 28: folds.py NoFocus comment made accurate (button is the box's focus proxy) — round 3.
Task 4: fix round 3 dispatched (resume a18774940170767d8), FIX_BASE 813f65a.
Task 4: round 3 fix 3925efa (12 fold tests passed). Scoped re-review dispatched (opus ac980a8f6d1fd0e01).
Task 4: fix round 3/5 (3 addressed, 0 open; commits 813f65a..3925efa)
Task 4: complete (commits 093dfda..3925efa, review clean)
Task 5: dispatched (implementer sonnet a2c4a0af032897996, BASE 3925efa)
Ruling 29: Task 5 Step 7's local 4.2 docker run is replaced by CI's qgis/qgis:4.2 job (whole suite, every push; green on every commit so far) — Docker Desktop daemon off, default daemon has no qgis image; pulling it is avoidable — cost if wrong: Qt 6 signal arrives after push instead of before.
Task 5: implementer DONE_WITH_CONCERNS b367c2e (width file 10 passed; whole QGIS suite 2760 passed; core+pure 1564). Concerns: legend_label changed to one-line ElidedLabel (wrapped legend changed height with the stretch, broke the W1 layout test); guard only on Qt 5 locally.
CI note: run 43554215852 (3925efa) failed plugin-qgis 3.44 only: test_a_site_mixing_radars_never_refuses_its_seeded_defaults[A] — "the site did not finish preparing" (60 s wait_until_idle) = known #166 intermittent Whole site hang; 4.2 green; prior runs green. Re-ran the failed job.
Task 5: review dispatched (opus a882062df58e31cc4) on 3925efa..b367c2e.
Task 5 review (b367c2e): ❌ (tests only) — I1 cube-combo cap unguarded (combo min cached before addItem); I2 opening test doesn't pin _OpensWideScrollArea (content slack). Production verified; legend elide justified (numbers lead; walkthrough at large font).
Ruling 30: guard carries a long Warnings entry (with an unbroken token) and long grid/preset names (spec §8.2) — round 1.
Ruling 31: elide test asserts the drawn text ends with "…" (current assertions tautological) — round 1.
Ruling 32: _OpensWideScrollArea docstring states what it does (stock hint + bar width) — round 1.
Task 5: minor (deferred): Interpolation row may flip 1↔2 lines when a Max distance edit changes the "= x m" text.
Task 5: fix round 1 dispatched (resume a2c4a0af032897996), FIX_BASE b367c2e.
CI: 3925efa re-run green (the 3.44 failure was #166's intermittent hang). b367c2e green on qgis 3.44 and 4.2 (Ruling 29's Qt 6 check for the width guard passed).
Task 5: round 1 fix c0fa0d1 (width file 11 passed x3; 43 layout-related passed). Scoped re-review dispatched (opus a87131d8a7d1a67b4) on b367c2e..c0fa0d1; named risk: re-set-after-show race.
Task 5: fix round 1/5 (I1, I2, R31, R32 addressed; R30 open — token too short; new minor: addItem on empty preset/cube combos starts a prepare/restore (race); commits b367c2e..c0fa0d1)
Ruling 33: add long names with signals blocked (no prepare/restore from the test), wait for the dock's own preparation before setting data text, one carry, fix docstring; token wide enough to beat the limit at the largest font — round 2.
Task 5: fix round 2 dispatched (resume a2c4a0af032897996), FIX_BASE c0fa0d1.
Task 5: round 2 fix 819423b (width 11 passed x3). Scoped re-review dispatched (opus a6950e39f50e09116) on c0fa0d1..819423b.
Task 5: fix round 2/5 (2 addressed, 0 open; commits c0fa0d1..819423b)
Task 5: complete (commits 3925efa..819423b, review clean)
Final review dispatched (opus a4e68e53c515fe8ea) on 513867a..819423b.
Final review (513867a..819423b): With fixes — I1 cross-seam regression (restore_cube flushes before prepare → level/frame refusal against the old grid, wrong cube drawn on mixed-radar sites); I2 Escape-dismissed Grid combo keeps the wheel (#176). Minors: M1 (ValueError branch stale refusal — fix), M2 (scope round trip; spec allows — leave), M3 (Warnings tooltip — fix), M4 (guide Edit lines sentence — fix). Deferred triage: T2 restore refusal folded into I1; T3 ValueError = M1; rest can wait.
Ruling 34: final fix wave = I1, I2, M1, M3, M4 (+ T2 no-resolution restore test if convenient); M2 left (spec §6.1 allows clearing on scope change) — cost if wrong: a refused value reappears after a scope trip without its refusal until the next apply.
Final fix wave dispatched (sonnet a35a1a085906db3e1), FIX_BASE 819423b.
Final fix wave: adcac6e (dock 213, edit_lines 54, warnings 2, site_scope 172, width 11). I1 by reorder (prepare before flush) + clear _grid_refusal in restore.
Final fix wave re-review dispatched (opus a047c521a365d1d56) on 819423b..adcac6e.
Final fix wave re-review (819423b..adcac6e): all findings addressed (I1, I2, M1, M3, M4 each pinned by a test that fails with its fix reverted); no new Critical/Important.
Ruling 35: parked — restore_cube's spin setValues arm the debounce before prepare(); if a preparation is running, set_source's nested cancel loop can fire the apply against the old grid (brief false refusal; in the _pending_z_shift branch the radar-clock range reaches the engine before the shift); both self-correct. One-line fix (stop the debounce before prepare) to ride with walkthrough fixes — cost if wrong: a brief false refusal flash during a restore while a preparation runs.
Ruling 36: parked — the "restore clears the old grid's refusal" test pins nothing from the wave; a sharper shift-branch test is described (refusal on A, old-clock record of B restored → Warnings empty right after restore_cube) — test only.
Ruling 37: parked — R-P5 deferral path (prepare deferred while a site task outlives its cancel, just after leaving Whole site) still applies the restored resolution against the old grid; on a mixed-radar site that draws the old resolution under a false refusal until the next resolution change. Narrow window; fix (set _resolution_owed and stop the debounce when prepare defers) with walkthrough fixes, or file — cost if wrong: that narrow case shows the wrong cube.
Ruling 38: parked — guide nit: Edit lines sentence says the Grid box takes the wheel "only after you click it"; after I2 a closed box only takes it when reached with Tab. Reword with walkthrough fixes.
Deploy: profile ns_geo_wheel (copy of ns_geo, plugin linked to this worktree); site copy a copy of the multi-grid survey under ~/nsgeo-wheel-walk/ (Grid1 remembers dz 0.1).
CI: adcac6e red on plugin-qgis (qgis/qgis:4.2) only: test_a_grid_popup_dismissed_with_escape_does_not_keep_the_wheel — table.hasFocus() False right after Escape (Qt 6 offscreen popup window; 2732 passed otherwise). Qt 5 green.
Ruling 39: CI red is load-bearing, so one targeted follow-up fix beyond the single final wave: Q1 (focusInEvent PopupFocusReason hand-back + test waits for focus), with parked Rulings 35 (debounce stop before prepare) and 38 (guide wording) riding along as one-liners in the same files; one scoped re-review; CI 4.2 checked after push — cost: one more small dispatch.
Qt 6 follow-up: b5bcc00 (edit_lines + dock 267 passed on Qt 5). Scoped re-review dispatched (opus a1b5fc50b143a80fc); CI run 43564014778 being watched.
Qt 6 follow-up re-review: all addressed, no new breakage (Qt 6 pending CI).
CI: b5bcc00 green everywhere (plugin-qgis 3.44 and 4.2, all OS matrices, smoke 3.40/3.44/4.2). Walkthrough next.
