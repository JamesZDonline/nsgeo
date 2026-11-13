# SDD ledger — plan: docs/superpowers/plans/2026-11-10-nsgeo-placement-corrections.md

Branch nsgeo-placement-corrections (worktree .worktrees/nsgeo-placement-corrections), off origin/main b55b2f0.
Plan commit 24d2b82 (pushed). No separate spec: the plan's Design section is the requirements (user opted out of design questions 2026-11-10, "start building"); rulings made against it are provisional.
Baseline core+pure: 1150 passed, 5 skipped. QGIS tier at b55b2f0: 1603 passed, 0 skipped (13 min).
Tooling: ../../.venv (core+pure, PYTHONPATH=worktree core src), ../../.venv-qgis (qgis), .venv-tools (ruff 0.17.1, mypy 2.4.0). Real data linked file by file.
Project convention: this workspace is committed as the decision record at merge (docs/superpowers/sdd/<name>/), not deleted; retire to .worktrees/_retired-ledgers before removing the worktree.

## Pre-flight scan

| Pair / task | Produces → consumes | Found |
|---|---|---|
| T1 → T2 | GridPlacement.scale, .travel_shift (keyword, after label) → LineEdit.placed, same_placement, is_fitted, replace_grid | consistent |
| T1 → T4 | GridPlacement(..., scale=) → rows_to_lines | consistent |
| T2 → T3 | LineEdit.scale/.travel_shift/.fitted(span), span_m, placement_note scale text → dialog columns, fit_to_edges, Note assertions | consistent; T3 Note test relies on T2 SCALE_NOTE copy |
| T2 → T4 | fit_scale, span_m → lookup.recompute_offsets | consistent (lookup imports line_edit; line_edit imports only nsgeo) |
| T2 replace_grid ↔ T3 pending-fit test | forward rows unfitted (scale 1) not refitted; reversed rows moved → CHANGED_ELSEWHERE at OK | consistent with line editing call 14 |
| T1 self | tests: bad scale/shift raise; JSON omit defaults; ProjectError wraps (KeyError, TypeError, ValueError) but unknown-type ProjectError passes through | consistent (ProjectError subclasses Exception only) |
| T2 self | pure tests: fitted→moved_to resolves Fit against B (size_y 9) ✓; is_fitted judges unshifted ends ✓; report copy ✓ | Step 5 layers/slices tests may pass on first run (pins for call 12) — see Ruling P1 |
| T3 self | Fit scale on 59/60 m span lines = 15.2542 (far from 1 → Note "stretches"); start fixed on stale rows ✓ | "abc" in Scale cell message left open in plan — see Ruling P2 |
| T4 self | campus ten: forward start 0→end 10; reversed start 10 (import rule start_along+L)→end 0 ✓ | consistent |

Ruling P1: Task 2's layers and slices tests are regression pins for call 12 and may pass on first run; only the session test (replace_grid refit) and the pure tests must be seen failing — they pin that no engine/layer code is needed — costs if wrong: a pin that never could fail; reviewer can mutate same_placement to check.
Ruling P2: a refused Scale cell (unparseable, non-finite, or <= 0) always shows `{text!r} is not a scale above 0; unchanged`; Destagger cells use the existing "is not a number; unchanged" path — one message per column keeps the test exact — costs if wrong: copy tweak.

## Manual checkpoints (tracked)
- After Task 3 Step 5: offscreen PNG render of the dialog (evidence, not a human check).
- After Task 4: deploy to new profile ns_geo_placement + walkthrough Artifact (db) — HUMAN GATE, stop for the user's results.

## Progress
Task 1: dispatched (BASE 24d2b82, implementer sonnet)
Task 1: implementer DONE a012644 (core+pure 1168/5; real FILE__008 test ran). Note: brief's `trace_count(path)` is really `trace_count(path, header)` — later briefs (Task 4 uses rows/plan_import, not trace_count) unaffected.
Task 1: review (opus) Approved, spec ✅, no Critical/Important.
Task 1: minor (deferred): test_scale_stretches_... uses scale 0.9 (compresses) — name only (plan wording)
Task 1: minor (deferred): test_trace_coords_use_the_corrected_distance compares to its own distance_along (plan-mandated) — literal values would stand alone
Task 1: minor (deferred): real-data test's header tpm==60 assert is a precondition, not proof the header is untouched (plan-mandated)
Task 1: minor (deferred): unknown-placement-type pass-through not pinned by a test (match="teleport" also matches a wrapped message)
Task 1: minor (deferred): "placement": null → AttributeError escapes the load wrap (pre-existing; velocity-fit wrap includes AttributeError)
Task 1: minor (deferred): validator accepts bool scale=True (harmless)
Task 1: ⚠️ resolved: LineEdit.placed / rows_to_lines drop scale+travel_shift until Tasks 2 and 4 — scheduled in their briefs; final review must confirm.
Task 1: for final review: layers.py:1711 map attribute length_m and line_choice_dialog.py:175 show RECORDED length (n/tpm) on scaled lines — recorded vs placed is an open question.
Task 1: complete (commits 24d2b82..a012644, review clean)
Task 2: dispatched (BASE a012644, implementer sonnet)
Task 2: implementer DONE 11cb6e7 (core+pure 1174/5; qgis files session 107, layers 90, slices_engine 68, edit_lines 36, grid_dialog 143 passed; layers/slices pins passed first run per P1). Implementer wrote code before RED, then reverted to show RED.
Task 2: review (opus) Approved, spec ✅; 9 mutants on a scratch copy all killed (same_placement, slices-only, span 0, placed drops fields, is_fitted+shift, refit start, tolerance, Fit vs seen grid).
Task 2: minor (deferred): placement_note docstring "Judges only the Start and the offset" stale (now scale too); replace_grid docstring has one ragged long line (session.py:527)
Task 2: minor (deferred): NaN passes the `<= 0` guards in span_m/fit_scale/LineEdit.fitted (span_m(100, nan) = nan) — carried to Task 3: fit_to_edges must treat `not span > 0` as unfittable
Task 2: minor (deferred): replace_grid can raise mid-way for a zero-length grid via fit_scale after site.grids[i] is replaced (API only; grid dialog blocks size 0)
Task 2: minor (deferred, plan-mandated, ASK AT WALKTHROUGH): a reversed fitted line counts in both moved and refitted, so the message names 3 lines when 2 changed
Task 2: minor (deferred): pure RED evidence was an ImportError after code-first (reviewer's mutants cover it)
Task 2: minor (deferred): session test's "third line unchanged" checks only (start_along, scale), not the whole placement
Task 2: complete (commits a012644..11cb6e7, review clean)
Task 3: dispatched (BASE 11cb6e7, implementer sonnet)
Task 3: implementer DONE 92c2507 (edit-lines + survey dock 106 passed; pure 237/1; ruff clean). PNG scratchpad/edit-lines-task3.png viewed by controller: layout aligned, but table shows only ~3.5 rows at 1100x560 with the two new bulk rows.
Ruling C1: Edit lines opens taller (resize(1100, 760)) and the table takes the layout's stretch, so ~10 rows show — real grids hold 30–60 lines and a 3.5-row table makes Fit/Destagger across a grid hard to check — costs if wrong: a taller window on small screens (user can resize).
Task 3: review (opus) Approved with 1 Important (plan-mandated): table shows ~3.5 rows at 560 px — same as Ruling C1 → fix round 1.
Task 3: minor (deferred): _live drops a Fit's Inset(0) but keeps scale=Fit when the move target grid is removed → contrived half-fit commit (start 16, scale 15.25); fix: keep Inset with Fit, or drop both
Task 3: minor (deferred): fit_to_edges duplicates _apply's loop/drop/guard; its drop branch untested; skip label repeats _drop_note's; Scale parse repeats number path
Task 3: minor (deferred): refused-Scale parametrize lacks inf/1e999/-0/comma; no test pins tooltip copy or spin ranges; survey test lacks scale-only/shift-only/negative shift
Task 3: minor (deferred, plan-mandated): Destagger cell .2f while spin takes 3 dp (0.245 shows 0.24); survey ×.3f shows ×1.000 for 1.0004
Task 3: minor (deferred): skip note replaces the "N lines changed · M picks" status (same as _apply drop notes)
Task 3: minor (deferred): Unicode minus "−0.24" refused in Destagger (pre-existing number path; Dir accepts −)
Task 3: minor (deferred): module docstring line 95 chars, paragraph not rewrapped
Task 3: fix round 1/5 (1 addressed, 0 open — table height per Ruling C1: resize(1100, 760) + table stretch 1; commits 92c2507..04dcecb)
Task 3: complete (commits 11cb6e7..04dcecb, review clean)
Task 4: dispatched (BASE 04dcecb, implementer sonnet)
Task 4: implementer DONE 2045e43 (core+pure 1178/5; import dialog 40 passed; ruff/mypy clean). QGIS test written alongside but first run green after implementation (no RED for it).
Task 4: review (opus) Needs fixes: 1 Important — import fit keeps Start along (0.5 → line runs 0.5→10.5, Note says fitted, is_fitted False), contradicting call 5 and Edit lines' Fit.
Ruling C2: with fitting on, import places forward rows at 0 and reversed rows at L (the same operation as Edit lines' Fit, so call 7's refit applies), and greys out Start along while the box is ticked so the ignored value is visible — Fit means "walked edge to edge", which a non-zero Start contradicts — costs if wrong: a user who wanted both an inset start and a stretch must set Scale by hand in Edit lines.
Task 4: minor (deferred): excluded row keeps a stale fitted note/scale after fit is turned off (harmless; same as other notes on excluded rows)
Task 4: minor (deferred): a placeable row with < 2 traces gets no note at import when fitting is on (call 5 says the table says so)
Task 4: minor (deferred): grid_size_along <= 0 makes fit_scale raise from the unguarded _replan slot / accept() (hand-edited file only; grid dialog refuses 0)
Task 4: minor (deferred): stale comments — "four placement-dependent note components" (now five), copied "A comma, not ;" comment, grid_size_along comment "for the over-length warning"
Task 4: minor (deferred): guide "setting Scale back to 1 undoes it" — after Fit, Start moved too; "undoes the stretch" is exact
Task 4: minor (deferred): the only QGIS checkbox test is @needs_real_data, so CI never covers toggled→_replan or options().fit_to_grid
Task 4: minor (deferred): 2045e43 trailer says Sonnet 5.5 not Opus 5.5 — left (no force-push)
Task 4: fix round 1/5 (1 addressed, 0 open — Ruling C2: fitted import rows start on the edge; Start along greyed while ticked; synthetic QGIS test; commits 2045e43..fd7ce55)
Task 4: minor (deferred): with the box ticked and no grid length, Start along is greyed but unfittable rows still use it (rows flagged "cannot be fitted"); unfittable-row fallback untested in the pure test
Task 4: complete (commits 04dcecb..fd7ce55, review clean)
Final review: dispatched (opus) on b55b2f0..fd7ce55
QGIS full tier started at 2045e43 (fd7ce55 landed mid-run, so mixed): 1618 passed in 811.67s (0:13:31) — re-run at final head required
Final review (opus): With fixes — 1 Important (refit message double-counts reversed fitted lines; plan defect), 7 Minor; ledger triage: only the double count is fix-before-merge, rest can wait.
Ruling F1: the grid length report counts a line once — `moved` = reversed lines that moved and were not fitted, `refitted` = fitted lines (either direction); the "both kinds" copy appears only when an unfitted reversed line also moved — the plan's n=1/m=2 expectation was a plan defect (a 4-line fitted zigzag read as 6 lines) — costs if wrong: message wording only.
Ruling F2: fold into the one fix wave: final Minor 1 (import note flags a fit more than 20% from 1: ", stretches it by N%" / ", compresses it by N%"), Minor 3 (guide states the three known limits), Minor 5 (Edit lines height clamped to 90% of the screen's available height), Minor 6 (pending-fit test also selects reversed rows and asserts they are skipped as changed elsewhere), and trivial fold-ins (placement_note / replace_grid docstrings; lookup.py stale comments; guide "undoes the stretch"; AttributeError in the load wrap with a test; session test compares the whole third placement) — each is a few lines and protects the walkthrough from known noise — costs if wrong: a slightly larger fix diff.
Ruling F3: final Minors 2 (velocity fits measured before a scale change keep their velocity) and 4 (a committed fitted line moved to a grid of another length is not refitted) are filed as issues at merge time, and raised at the walkthrough; Minor 7 (README Next item 5 duplicates In progress) is handled when the row moves to Done at merge — costs if wrong: none, both are recorded.
Final fix wave: DONE 5448674 (core+pure 1181/5; 3 QGIS files 197 passed; ruff/mypy clean)
Final fix wave re-review (opus): all 6 findings ADDRESSED (fd7ce55..5448674).
Final: parked — height clamp reads the screen at the virtual-desktop origin before the dialog has a window, so on a multi-monitor setup it can clamp against the wrong screen — Ruling: park; not a regression (single-screen case fixed), no second fix wave per the process; the walkthrough (B1: OK and Cancel on screen) shows whether it bites; one-line fix (`parent.screen()` first) if the user runs QGIS on a secondary monitor — costs if wrong: OK/Cancel below the taskbar on a short secondary screen.
Final: minor (deferred): GridEditReport docstring says `moved` = "reversed lines moved" without "unfitted"; guide's "fit before velocity" also applies to a typed Scale.
Deploy: NEW profile ns_geo_placement (cp -a ns_geo, dev_link → this worktree); headless probe: CORE_PATH = worktree core, GridPlacement has scale/travel_shift, Edit lines headers include Scale/Destagger.
Walkthrough data: ~/nsgeo-placement-check/ (campus/ and with-dzg/ = file symlinks to tests/data/local; Nashville_City_Cemetery/ = copies of survey.nsgeo.json + site.nsgeo.gpkg, DZTs on /mnt/DataStorage).
Walkthrough: https://claude.ai/artifact/UqkaRx9zTNJ4mRQhqyPHQt (db `results`, 24 checks A1–A4 B1–B4 C1–C6 D1 E1–E2 F1–F2 G1–G5); results collection empty at publish. HUMAN GATE — waiting for the user's marks.
QGIS full tier at 5448674: 1622 passed, 0 skipped (15m52s)
Walkthrough RESULT (2026-11-11): 24/24 pass. Notes: B3 — refused 0 reverts, user didn't find the status line (behaviour fine). C1 Nashville Grid 1, 14.9–19.7 ns / 0.6–0.79 m. C2 — fit shrank the wiggle, slightly present. C3 — fitted + destagger +0.15 got WORSE; scale 1 + destagger +0.15 much better (0.10 too little, 0.25 too much). F2 (with-dzg, fitted) — best destagger −0.15 ("looks fantastic"); +0.15 worse. → the sign of the needed destagger flips once lines are fitted; Measure (chunk B) must measure on the current placement, sign-free. User asked where the automatic destagger is: it is chunk B, not built.
CI fix: zip(strict=) in test_fit_at_import_ignores_start_along… failed py3.9 jobs at fd7ce55/5448674 → fixed directly (XS) in dea405f
Merge prep (2026-11-11, user: "make a PR and if ci passes then merge it"): origin/main (60531f6, incl. #153 #154 #155 #156) merged in at ad4c8d7 (README In progress conflict resolved: this row → Done, Next item 2 reworded to the automatic destagger); guide gains "fit before you destagger" with the walkthrough's sign flip; core+pure after the merge 1228 passed, 5 skipped. Filed #159 (automatic destagger, user's request). NOT filed: the G1 velocity-refit and G2 move-refit follow-ups — the issue-create call bundling them was denied by the permission classifier; listed in the PR's For later instead.
