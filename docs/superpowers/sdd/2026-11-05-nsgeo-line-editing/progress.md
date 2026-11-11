# SDD ledger — plan: docs/superpowers/plans/2026-11-05-nsgeo-line-editing.md

Spec: docs/superpowers/specs/2026-10-30-nsgeo-line-editing-design.md (approved 2026-11-05).
Worktree: .worktrees/nsgeo-line-editing, branch nsgeo-line-editing.
Setup (2026-11-06): merged origin/main 61c2336 (bandpass fix #118, milestone B #122) → ac4e203, pushed.
Venvs built (.venv, .venv-qgis; freeze matches nsgeo-slice-interpolation). Real DZT + sunnyside.nsgeo.json copied into packages/nsgeo-core/tests/data/local (git-ignored).

## Baseline at ac4e203
- core + pure: 1004 passed, 3 skipped (all three: test_schema.py "required parameters by design" — no real-data skip)
- lint: clean; format: 170 files clean; types: clean (40 files)
- qgis: 1482 passed, 0 skipped (14 m 45 s)

## Pre-flight scan

| Pair / task | Produces → consumes | Finding |
|---|---|---|
| T1 ↔ T2 | T1 `derived_pick_fields`, `follow_lines` (runs on lines_changed) → T2's layers test of edit/move | consistent; both edit session.py, plugin.py, test_plugin_layers.py, sequentially |
| T2 ↔ T3 | T2 `edit_lines`, `move_lines`, `LineEdit`, replace_grid moving reversed lines → T3 engine/dock tests | consistent; T3's exactly-once test relies on T2's replace_grid change (ordered correctly) |
| T2 ↔ T4 | T2 `LineEdit`(placed/flipped/snapped/moved_to/shifted/changes), `Inset`, `EditOutcome`, `placement_note`, `same_placement`, `length_along`, `width_across`, `edit_lines(edits, grid_id=, order=)` → T4 dialog | consistent; dialog `move_to` vs LineEdit `moved_to` are distinct names on purpose |
| T4 ↔ T5 | T4 `open_edit_lines_dialog(grid_id, keys)`, test file test_plugin_edit_lines_dialog.py → T5 signal wiring + plugin move_lines test in that file | consistent |
| T2 ↔ T5 | `SiteSession.move_lines(keys, grid_id) -> EditOutcome` → plugin `move_lines` | consistent |
| T1 ↔ T5 | both edit docs/guide/getting-started.md (T1 §4 bullet; T5 panels bullet + new subsection) | different sections, no conflict |
| plugin.py | T1 (SiteLayers on_info), T2 (grid dialog message), T4 (opener, unload), T5 (signal connects, move_lines) | sequential edits, no conflict |
| T1 self | tests vs code: `_rows` keyed by line_key — every test uses distinct keys per pick; copy string fixed | agrees |
| T2 self | pure-test arithmetic checked by hand (REV→B 9.0 exact; typed 14.5→8.5; XREV snap 10.0/flip 0.5; STALE follow 15.0; note strings) | agrees |
| T3 self | dock test expects `prepared · 1 lines` — existing status format f"prepared · {n} lines" | agrees |
| T4 self | snap test highlight list [F,T,F,T,F,F] and "2 lines changed · 0 picks…" match fixture (row 5 already at 15.0; no pick store → 0) | agrees |
| T5 self | "Remove 2 lines from site" matches `_count_phrase` | agrees |
| Rubric | no plan-mandated assertion-free test or verbatim duplication (T1 says share `_pick_point`'s clamp) | none |

Ruling: milestone B is no longer a parallel branch — it merged to main (61c2336) and into this branch (ac4e203). The Global Constraint "Do not touch nsgeo-slice-interpolation-b" and the follow-up about reconciling with B are moot; Task 3 builds directly on B's slices code (refiner included) and must keep B's tests green — wrong only if B's refine flow needs its own hook on a placement re-prepare, which the full slices/refine test files will show.

## Tasks
Task 1: dispatched (BASE ac4e203, sonnet implementer a68733fe0843b0353; brief task-1-brief.md, report task-1-report.md, shared-context.md)
Task 1: implementer DONE_WITH_CONCERNS — 4abc351 (qgis 1493 passed/0 skipped; core+pure 1004/3 by-design). Concerns (observations): distance_along per pick; repeated unplaceable-line log; layers.py ~1800 lines; guide Step 6 "do not drag" bullet also rewritten (beyond brief, matches ruling).
Task 1: review dispatched (opus a5945a1a04ca696d1, package review-ac4e203..4abc351.diff)
Task 1: review — spec ✅ (one Important), quality Needs fixes. ⚠️ items resolved: 3 core skips are test_schema by-design (baseline); "move to a grid with another velocity" is Task 2's test; #55/issue closures are PR-time; real-data follow → walkthrough (incl. reopen twice: no second "updated N" message).
Task 1: minor (deferred): 1e-9 geometry tolerance ≈ 1 ulp at UTM northings (~4.3e6) — bit-identical recompute holds today; 1e-6 would remove fragility (layers.py:202,:655)
Task 1: minor (deferred): editing-mode note test doesn't assert the provider row already moved before commit (test_plugin_layers.py:2512-2526)
Task 1: minor (deferred): cut-key test doesn't assert the FILE__001 pick moved; duplicates _add_row body (test_plugin_layers.py:2434-2453)
Task 1: minor (deferred): "could not be placed" logged by both refill_lines and follow_lines (4x per replace_grid); wording says "left out of the map"
Task 1: minor (deferred): two provider writes not atomic (changeFeatures would be one call)
Task 1: minor (deferred): _bind/_unbind_picks_signals docstrings don't mention _on_picks_committed
Task 1: minor (deferred): follow is O(picks × traces) per refresh (distance_along + resolved_velocity per pick)
Task 1: minor (deferred): layers.py ~1800 lines, test_plugin_layers.py ~2600 (no split)
Task 1: fix round 1/5 dispatched (resumed implementer; Important 1: negative trace wraps in _pick_distance; FIX_BASE 4abc351)
Task 1: fix round 1 implementer DONE — ff2765a (layers+session files 178 passed; lint/types clean; new test not run red first → re-reviewer asked to verify it fails without the guard). Re-review dispatched (sonnet a0c8367dee86413d6, package review-4abc351..ff2765a.diff)
Task 1: fix round 1/5 (1 addressed, 0 open — negative trace; commits 4abc351..ff2765a; red check in scratch copy: new test fails without the guard)
Task 1: complete (commits ac4e203..ff2765a, review clean after 1 fix round)
Task 2: dispatched (BASE ff2765a, sonnet implementer a4e9982c3a8339d55; brief task-2-brief.md, report task-2-report.md)
Task 2: implementer returned NEEDS_CONTEXT, uncommitted (pure 11/11 incl. Sunnyside RAN; core+pure 1015/3; new QGIS tests pass targeted; full QGIS tier stalled ~14% and was killed). Resumed: finish 4-file rerun, full tier with -v to a log, hunt any hang (≈ end of grid_dialog tests), then commit/push/report.
Task 2: 4-file rerun green (442 passed) but printed 6× 'QBasicTimer::start: QBasicTimer can only be used with threads started with QThread' — baseline output not kept (tail -3), so unknown whether new; full -v tier running (t2-full.log).
Task 2: implementer DONE_WITH_CONCERNS — 5267218 (qgis 1511/0 skipped 13m41s; core+pure 1015/3; Sunnyside RAN; stall = contention). Concern: pure RED shown after writing module.
Task 2: full -v log had 0 QBasicTimer lines (only the 4-file subset printed them). Contention source: another session's full QGIS run in .worktrees/nsgeo-m14. Review dispatched (opus a1b8a6efde97c663a, package review-ff2765a..5267218.diff).
Task 2: review — spec ✅, quality Approved, no Critical/Important. ⚠️ count mismatch resolved: 1482 (ac4e203) + 12 (Task 1 incl. fix) + 17 (Task 2) = 1511. ⚠️ QBasicTimer noise: running the same 4 files at ff2765a in a scratch copy (qbt-base.log) to attribute it.
Task 2: minor (deferred): edit_lines with duplicate keys in `order` corrupts site.lines after placements are written (zip strict raises late; a later save drops a line) — no planned caller can pass duplicates; one-line ValueError check at session.py:719 closes it (session.py:766-778)
Task 2: minor (deferred): step 5 builds `on` from keys_on_grid while _lines_by_key is still in old order — a line moved INTO grid_id in the same call that orders grid_id is mis-slotted / spurious reordered; unreachable today (table only moves lines away) (session.py:767)
Task 2: minor (deferred): wrong spec citations — line_edit.py:78 (§4.3 → §3 call 8), session.py:796 move_lines (call 8 → call 7 + call 1), replace_grid cites call 6 for the rule (→ decision 4 / §4.3)
Task 2: minor (deferred): untested — GridEditReport.message() outside sentence, plugin Warning branch, session-level flip-twice/move-away-and-back via edit_lines, move-out combined with order on interleaved grids
Task 2: minor (deferred): flip twice + another field (e.g. label) writes Start drift 0.3000000000000007 to disk; fix in placed(): keep p.start_along when within SAME_M (line_edit.py:114-137)
Task 2: minor (deferred): plugin grid-dialog finished slot only catches ValueError/KeyError around replace_grid, which now does more (pre-existing narrowness) (plugin.py:1480-1496)
Task 2: ⚠️ QBasicTimer resolved — the same 4 files at ff2765a (scratch copy) print 4 such lines too (420 passed, 5 real-data skips because the copy has no local data): pre-existing teardown noise of that file subset, not Task 2's; the full tier prints none.
Task 2: complete (commits ff2765a..5267218, review clean)
Task 3: dispatched (BASE 5267218, sonnet implementer a6061fe554d453d2d; brief task-3-brief.md, report task-3-report.md)
Task 3: implementer DONE — de3529f (qgis 1523/0 skipped before a last import fix; slices files 323 passed after; core+pure 1015/3; RED by reverting impl: 8/12 new fail, 4 pinned negatives pass)
Task 3: review dispatched (opus aef4153f14667cffa, package review-5267218..de3529f.diff)
Task 3: review — spec ✅, quality Needs fixes (1 Important). ⚠️ full tier not re-run after the last import change → required in the fix round.
Ruling: the reorder→stuck-"stale" finding is routed into Task 3's fix loop, not Task 4 — it is slices-dock status/no-op-guard behaviour meeting Task 2's order=, and Task 4's OK (↑/↓ plus edits) would hit it immediately — wrong only if the fix belongs in session ordering, which would surface in Task 4's tests.
Task 3: minor (deferred): after an import leaves A stale, a later held-line edit dispatches narrowed choice then the dock dispatches again (set_source calls [3,4]); safe but a wasted cancel-wait, and quietly ends the pinned "import stays stale" behaviour (slices_dock.py:840-856, slices_engine.py:1123)
Task 3: minor (deferred): an explicit choice emptied by a move dispatches an empty preparation first ([0,2]); end state correct
Task 3: minor (deferred): hand-over error messages say "after grid {id} moved" when a line moved (slices_engine.py:1149,:1156)
Task 3: minor (deferred): citation "(spec §4.5)" lacks "line editing" (slices_engine.py:1064)
Task 3: minor (deferred): `_on_grid` has no docstring and drops a non-grid placement that set_source would keep (slices_engine.py:1069)
Task 3: minor (deferred): no test for a move between grids in Whole site, nor for an explicit choice emptied by a move (both work per reviewer probes)
Task 3: fix round 1/5 dispatched (resumed implementer; FIX_BASE de3529f)
Task 3: fix round 1 implementer DONE — 084d0f0 (binning order-independent: accumulate/build_cube/stream_slice sum into shared arrays → SourceChoice.same_source() compares key sets; used by dock status, prepare() no-op, SiteEngine.set_source; narrowing in survey order; qgis 1525 passed; core+pure 1015/3)
Task 3: fix round 1 re-review dispatched (sonnet a6b833665b26f6685, package review-de3529f..084d0f0.diff)
Task 3: fix round 1/5 (1 addressed, 0 open — reorder stuck stale; commits de3529f..084d0f0; full qgis tier 1525 passed)
Task 3: minor (deferred): after a reorder-only change engine.provenance().line_keys and the first-line velocity label keep the old order (slices_dock.py:2672) — cosmetic
Task 3: complete (commits 5267218..084d0f0, review clean after 1 fix round)
Task 4: dispatched (BASE 084d0f0, sonnet implementer a280ae2cb52169069; brief task-4-brief.md, report task-4-report.md)
Task 4: implementer DONE — 52e7a17 (qgis 1543/0 skipped incl. 18 new; core+pure 1015/3; RED by moving module aside after writing it). Concerns: typing Dir after Start recomputes Start (inset rule, by design); bulk title says '1 selected lines' (brief copy).
Task 4: review dispatched (opus a085abf8e72c92902, package review-084d0f0..52e7a17.diff)
Task 4: review — spec ❌ (1 Important: a row's target grid removed while open blocks OK, misnames the grid, can't move back). ⚠️ mock-up layout → walkthrough (file is in the main checkout's .lavish/); ⚠️ call 7 entries → Task 5.
Ruling: reviewer Minor 2 (`nan`/`inf`/`1e999` accepted in Offset/Start) enters the fix loop — it breaks the plan's Review Focus (4) ("text typed into a number cell is reverted") and would write NaN into the survey and the map — cost if wrong: one isfinite check.
Ruling: reviewer Minor 1 (double flip then a concurrent length edit → false "changed elsewhere" warning) enters the fix loop — Review Focus (1) says such a row reads as unchanged and is not written; store a blank edit once an edit no longer changes the line — cost if wrong: a few lines.
Ruling: the brief's copy `Change the {n} selected lines` and the header's `· {n} lines` are pluralised (`line(s)` by n) — the plan's intent is plain English and the status line beside them already pluralises — cost if wrong: two strings.
Task 4: minor (deferred): test gaps — Start-then-Dir (→ 14.50) not pinned, `abc` in Start untested, double-flip test never accepts, move-away-and-back untested in the dialog, one-table-per-grid test opens only grid A
Task 4: minor (deferred): Shift amount defaults to 0.5 (mock-up +0.000) — a stray Shift click moves every selected line 0.5 m (still only until OK, and highlighted); caption "Order here is the order in the Survey panel" missing; bulk rows unlabelled (edit_lines_dialog.py:177-185)
Task 4: minor (deferred): `edits: list[Any]` (:477), `# type: ignore[arg-type]` on seen (:121), `not min(rows)+delta >= 0` (:292), Dir parsing duplicated from ImportDialog (:435-447)
Task 4: fix round 1/5 dispatched (resumed implementer; FIX_BASE 52e7a17)
Task 4: fix round 1 implementer DONE — 3def5b9 (edit-lines file 28 passed; qgis 1553/0 skipped; lint/types clean)
Task 4: fix round 1 re-review dispatched (sonnet a0a300c6b9ce2f05d, package review-52e7a17..3def5b9.diff)
Task 4: fix round 1/5 (4 addressed, 0 open — removed target grid, non-finite numbers, double-flip false skip, plurals; commits 52e7a17..3def5b9; qgis 1553 passed)
Task 4: minor (deferred): editing Offset/Start/Label on a row whose move target was removed keeps the dead move, so OK still skips it; a Start typed after such a move is dropped with it; `_apply` can partially mutate selected rows if a KeyError hits mid-loop (pre-existing)
Task 4: complete (commits 084d0f0..3def5b9, review clean after 1 fix round)
Task 5: dispatched (BASE 3def5b9, sonnet implementer a1346ba98cee0731c; brief task-5-brief.md, report task-5-report.md)
Task 5: implementer DONE_WITH_CONCERNS — 0685f24 (qgis 1558 passed / 1 FAILED: test_plugin_grid_dialog.py::test_the_feature_list_follows_the_layer_list_not_its_signal, combo picked 'grids' not 'plan'; passes alone; core+pure 1015/3; 3 existing menu tests updated). Sent back before review: likely a project-layer leak from the new plugin test in test_plugin_edit_lines_dialog.py (runs just before grid_dialog); Tasks 1–4 full tiers all passed this test.
Task 5: leak confirmed (move_lines plugin test never unloaded; reproduced with edit-lines then grid-dialog files) and fixed in the test — 8767e22; qgis 1559 passed / 0 failed / 0 skipped; core+pure 1015/3.
Task 5: review dispatched (opus aab2c43886dc54ce3, package review-3def5b9..8767e22.diff)
Task 5: review — spec ✅ except 1 Important (Edit line… lambda runs _grid_of_key outside any guard, survey_dock.py:419). ⚠️ separator before Remove in the selection menu — ruled below.
Ruling: the selection menu gets a separator before "Remove N lines from site" — the brief's "separators as today, before the destructive entry" plus the existing "the destructive one stands apart" test read that way — cost if wrong: one separator.
Ruling: "Move 1 lines to grid" → use _count_phrase like Edit — same copy rule as Task 4's plural ruling — cost: one string.
Ruling: open_edit_lines_dialog (now a connected slot) gets its own guard — the global constraint says every connected slot guards its body — cost: a try/except.
Ruling: guide fixes enter the loop — the grid-menu list omits Edit lines… (the brief requires the bullet to name it), "change several lines … press Delete" is wrong (Delete only removes), "Set a **Start**" bolds the wrong word — spec §6 + the guide's "describe only what the software does" — cost: three sentences.
Ruling: add the any/all greying test (one line on A, one on B: both entries enabled) — it pins the brief's rule that a grid is disabled only when every selected line is on it — cost: one test.
Task 5: minor (deferred): Critical/Warning/Info levels of plugin move_lines not pinned (message_log records text only) (test_plugin_edit_lines_dialog.py:481)
Task 5: minor (deferred): survey_dock.py:76 cites §4.2 for the Survey entries (→ §3 call 7)
Task 5: minor (deferred): plugin.py:1904 str(KeyError) keeps quotes on the bar (`Move to B: "no grid with id 'B'"`)
Task 5: fix round 1/5 dispatched (resumed implementer; FIX_BASE 8767e22)
Task 5: fix round 1 implementer DONE — 3c21476 (survey dock + edit-lines files 83 passed; core+pure 1015/3; lint/types clean; also added Set velocity override… to the guide's line-menu list)
Task 5: fix round 1 re-review dispatched (sonnet a375294324edc6d8c, package review-8767e22..3c21476.diff)
Task 5: fix round 1/5 (7 addressed, 0 open — Edit line… guard, separator, singular Move, guarded opener, guide fixes, any/all test; commits 8767e22..3c21476)
Task 5: complete (commits 3def5b9..3c21476, review clean after 1 fix round)
Merge: origin/main 7fa0e96 (M14 migration #124) merged → 655fe0e, pushed. One conflict: test_plugin_slices_engine.py, both sides appended independent test blocks at EOF — kept both (no name clashes), ruff clean.
Merged head: core+pure 1059 passed, 4 skipped (all test_schema by design; migrate_fk is new from M14); lint/format/types clean. QGIS tier running.
Final review dispatched (opus ab29f0ff600c0e218, package review-7fa0e96..655fe0e.diff, 16 commits / 27 files; asked to triage every deferred minor and check every ruling)
Session restart (15:58): the final review and the merged-head QGIS run were stopped (run had reached 64% with no failures). Merged origin/main be2acee (README Roadmap, PR #135; README only) → 73ec451, pushed. Roadmap already lists line editing under "In progress" → move to Done in the PR. Re-running full QGIS tier on 73ec451; final reviewer resumed (same range 7fa0e96..655fe0e).
Final review: Ready to merge — With fixes. No Critical. Important 1: edit_lines with a duplicate key in `order` corrupts site.lines (probe-confirmed; deferred T2 minor promoted). Reviewer agreed with every ruling; triaged every other deferred minor as can-stay-deferred.
Ruling: the final fix wave also takes final-review Minor 1 (an Edit lines table outlives its site; same grid id after Open site… re-raises the old site's table and OK then refuses, losing edits) — a reasonable user would lose work — cost: a json_path check in the opener.
Ruling: picks on a line with no distance axis (or no grid frame) DO get depth_m/velocity_m_ns re-derived; position and distance stay as they are — the user's own decision 7 ("whenever a line's resolved velocity changes…") outranks my §4.4 wording, which was about position — cost if wrong: those picks' depths follow velocity edits, which is what decision 7 asks for.
Ruling: the fix wave also guards every Qt-invoked slot in edit_lines_dialog.py with a broad except (move_selected, _selection_changed, and the slots catching only KeyError/ProjectError/ValueError) — Global Constraint — cost: a few try blocks.
Ruling: add one real-DZT test of picks following (FILE__001–010 at a UTM-sized origin: grid edit, flip, move) and move the follow geometry tolerance from 1e-9 to 1e-6 m — real data is the user's primary validation, and 1e-9 is ~1 ulp at real northings — cost: one test, one constant.
Ruling: add the reviewer's two Whole site probes as tests (move B→C with the site idle; B→A while busy; no "now on grid" error, each grid ends with the right lines) — spec §7 hazard "a line moved while in a prepared source on each grid" — cost: two tests.
Ruling: cosmetic batch in the same wave — str(KeyError) quotes on the bar (plugin move_lines, use exc.args[0]); spec citations (line_edit.py:78, session.py:796 move_lines, replace_grid, slices_engine.py:1064, survey_dock.py:76) — cost: trivial.
Deferred to the walkthrough / later: Shift default 0.5 (user judges at walkthrough); Move to grid onto a narrower grid gives no outside-width warning (walkthrough check); grid-free lines in Survey menus and `_on_grid` (note on M17 #134).
Final fix wave dispatched (sonnet a2f71da2b60124487, FIX_BASE 73ec451; brief final-fix-brief.md, report final-fix-report.md)
Merged head 73ec451 QGIS tier: 1571 passed, 0 skipped (16 m 05 s)
Final fix wave DONE_WITH_CONCERNS — 2c13375 (pushed; qgis 1582/0 skipped; core+pure 1059/4; real-DZT test RAN but does not pin the 1e-6 tolerance; new _failed helper and opened_against property; Whole site 'busy' case is a queued unsettled engine; a stray 'git add -f .superpowers' was unstaged — verified nothing under .superpowers or tests/data/local in the commit)
Task 6: user said no Sunnyside backup is needed (plan Step 2 skipped on the user's instruction, 2026-11-06).
Task 6: deployed — profile ns_geo_lines = copy of ns_geo, nsgeo_qgis symlinked to this worktree (dev_link); ns_geo untouched (still → nsgeo-main). Headless smoke load from the profile path: plugin + core resolve to this worktree, classFactory present, EditLinesDialog imports.
Task 6: walkthrough page published https://claude.ai/artifact/2m5RRJAZ8emkzR5g3qdw4b (17 checks W01–W17 incl. reviewer additions; db collection 'results', doc per check id {status, notes, at}); store probe write/list/delete OK. Source: scratchpad/line-editing-walkthrough.html. Waiting on the fix-wave re-review before handing it over.
Final fix wave re-review (opus acf34f75802789e27): all 8 ADDRESSED, no new Critical/Important. Real-DZT test confirmed RUN (1 passed). The "busy" Whole site test does land on a live in-flight preparation (reviewer probe: B preparing, has_live_task).
Parked — follow coordinate tolerance unpinned both ways (1e-2 and 1e-12 both pass the layers tests) — Ruling: carry a ±(5e-7, 2e-6) pin into the first walkthrough fix round — a loosened tolerance would let sub-cm moves go unwritten, nothing ships before the walkthrough anyway.
Parked — distance_m left alone on an unplaceable line is unpinned (renamed test should assert 0.117) — Ruling: same, first walkthrough fix round — behaviour is correct on reading.
Parked — move_selected's own guard is unpinned; busy test asserts only != "ready" (should be == "preparing"); edit_lines docstring doesn't list the new ValueError; module docstring cites "§3 call 14" for the slot-guard rule (it's a plan Global Constraint) — Ruling: same — cosmetic/test-strength only.
Parked — a table for a grid id the new site lacks stays open until closed (OK refuses it, no data at risk); nothing closes tables on site close — Ruling: leave as is unless the walkthrough shows it bites — no data loss path.
Ruling: keep this plan's SDD workspace until the walkthrough is done and merged — Task 6 fix rounds need the ledger and briefs — cost: none (git-excluded scratch).
Final review: CLEAN after one fix wave (commits 73ec451..2c13375). Task 6 (human gate) open: walkthrough page handed to the user.
Task 6: walkthrough done by the user on ns_geo_lines (2026-11-06): 15 pass, 2 skip (W05 dragged pick, W17 guide), 0 fail. W12 note: "its a bit disorganized but its fine for this release. I want to spend some time working with it before I make any suggestions about modifications". W13 (Shift 0.5 m) and W16 (no width warning on Move to grid) passed as they are.
Task 6: complete — user: "good enough to merge"; asked for the PR, merge on green CI, and release 0.3.0 (covering M14 migration too) with a new zip. Parked test pins were not done before merge (user's go) and are listed in the PR as follow-ups.
Merged origin/main 522067b (#136 grids start collapsed) → 4c0c698; one conflict in test_plugin_survey_dock.py (both appended blocks; kept both); survey dock + edit-lines files 95 passed. Release commit 5c4c3f5 (0.3.0: versions, docs/releases/0.3.0.md, metadata changelog, README roadmap rows → 0.3.0, guide).
