# SDD ledger — plan: docs/superpowers/plans/2026-11-11-nsgeo-auto-destagger.md

Spec: docs/superpowers/specs/2026-11-11-nsgeo-auto-destagger-design.md (approved 2026-11-11, "looks good. build it").
Branch nsgeo-auto-destagger, plan committed at 3ed3b49. Stop at the C14 checkpoint (human gate) after Task 2.

## Pre-flight
- .venv-tools built (ruff 0.17.1, mypy 2.4.0). Real data linked into packages/nsgeo-core/tests/data/local
  (campus files, with-dzg/, grid2/, mag-data/); git status clean.
- Baseline core+pure: 1228 passed, 5 skipped (43 s). Lint clean, types clean (44 files).
- Baseline qgis: see baseline-qgis.txt (running).

## Pre-flight scan

| Rows | Produces / consumes | Finding |
|---|---|---|
| T1 → T2 | measure.py, profiles.py (search_range_m, profile/curve helpers), destagger_data.lines_for(moved=, skew=) | Consistent. T1 must build lines_for's moved/skew though only T2 tests use them. |
| T1 → T3 | envelope_bins, MeasureLine, measure_destagger, DestaggerResult, LineStatus, MeasureStopped, AxisResult.lines_used | Consistent. |
| T2 → T3 | OWN/CHANGES/NO_MATCH statuses with destagger = value for the cell | Consistent. |
| T1 → C14 | nsgeo.destagger API for the pictures | Consistent. |
| T1 self | one-way test expects every line AXIS_FAILED, but each one-way line also has no opposite neighbour (NO_NEIGHBOUR) | Conflict → Ruling 1. |
| T2 self | Step 4 says leave an unmeetable-tolerance test failing | Conflicts with a green suite → Ruling 2. |
| T3 self | "no nsgeo-refine thread left alive" after reject(): other QGIS-tier tests' Refiners share the thread prefix | Ambiguous → Ruling 3. |
| T3 self | _update_panel reads self._measurer.busy, and __init__ calls _refresh() → _update_panel | Order: create the Refiner before _refresh() (carried in dispatch). |

Ruling 1: a line's own exclusion reason (NO_DISTANCE, TOO_SHORT, TIME_SETTINGS, NO_NEIGHBOUR) wins; AXIS_FAILED is only for lines that would otherwise have been measured. The one-way test asserts NO_NEIGHBOUR on every line and ONE_WAY on the axis. — the more specific reason tells the author more — cost if wrong: one reason string per line, cosmetic.
Ruling 2: a spec tolerance Task 2 cannot meet is marked `pytest.mark.xfail(strict=True, reason=<the measured numbers>)`, with the tolerance unchanged, and reported as DONE_WITH_CONCERNS for C14. — keeps the suite green without loosening the spec; strict xfail fails loudly once it is met — cost if wrong: none; the author still sees it at C14.
Ruling 3: the close test counts `nsgeo-refine` threads before the dialog opens and after reject(), and expects the same count. — other tests' Refiners may hold threads with the same prefix — cost if wrong: a weaker check of thread cleanup.
Task 1: dispatched (sonnet, implementer a81a73e1e7fee9588), BASE 3ed3b49
Task 1: implementer DONE_WITH_CONCERNS d4da994 (pushed by controller; subagent had no network). Grid values: G1 +0.162/-0.066, G2 +0.162/-0.061. Concerns: added MIN_CORRELATION 0.08 strength test (unrelated lines give a faint hump at the same lag as real grids, ~0.02/bin — something common to all lines feeds the grid value a little; raise at C14); window end = last bin > 1.25x noise floor; CLEAR_RATIO 0.8 untuned. Review dispatched (opus a7b80d3d39cb0600c), package review-3ed3b49..d4da994.diff
- Baseline qgis (at 3ed3b49): 1667 passed in 754.64s (0:12:34)
Task 1: review (opus) — spec ✅ with one plan-mandated Important; quality Needs fixes. Reviewer confirmed the port reproduces the spike exactly (G1 at 29.98 m +0.1517/-0.0652; G2 +0.1648/-0.0587).
Ruling 4: GRID1_LENGTH = 29.98 (the saved survey and the spike), not the spec's rounded "30 m" — spec §10 also says "as the spike did"; the +0.010 gap was entirely the 2 cm length — cost if wrong: none; the method is unchanged.
Ruling 5: reviewer Minor #2/#3 (lag_curves and the exclusion loops never call should_stop; the stop test reaches only the first check) is a Global Constraints violation ("at least once per line in every per-line loop") → enters the fix loop as a spec gap. Minor #6 (a test that asserts nothing) is Important by the rubric → enters the loop.
Task 1: minor (deferred → carried to Task 2 dispatch): MIN_CORRELATION depends on line length (curves divided by full axis n); along-halves will see peaks halved; make the strength test length-independent.
Task 1: minor (deferred): ffts cache holds every line's complex128 FFT (~100 MB Grid 1, ~0.7 GB for 200 lines x 50 m); float64 profiles. Bound it (sliding window, float32).
Task 1: minor (deferred): is_clear edge and CLEAR_RATIO branches untested (pure hand-made curves).
Task 1: minor (deferred): nits — `return failed(...)[0], out`; duplicate keys overwrite silently; P2 truncation untested; unused fixture in test_each_axis; constants placement; comment "0.14-0.25" vs measured 0.23-0.37.
Task 1: fix round 1/5 dispatched (resume implementer; FIX_BASE d4da994): GRID1_LENGTH 29.98 + report correction; should_stop in lag_curves + exclusion loops + per-stage stop test; drop assert-nothing test; return/fixture nits
Task 1: fix round 1 implementer DONE bc80ffb (G1 29.98: +0.1517/-0.0657; per-stage stop test caught a real gap). Re-review dispatched (opus a35dbb23303d4ebe3)
Task 1: fix round 1/5 (4 addressed, 0 open; commits d4da994..bc80ffb)
Task 1: minor (deferred): stop test does not pin the exact call count (361 on Grid 1) so stage placement is assumed, not enforced.
Task 1: minor (deferred): report's correction labels the wrong concern number (cosmetic, ledger has the truth).
Task 1: minor (deferred): cheap in-memory per-line passes without a stop check (_common_time_settings O(n^2), bin_medians, along_axis, neighbour_indices).
Task 1: complete (commits 3ed3b49..bc80ffb, review clean after 1 fix round)
Task 2: dispatched (opus, implementer a9e022ec3663e62ce), BASE bc80ffb; carried Task 1 deferred minors (MIN_CORRELATION length dependence, FFT-cache memory, is_clear branch tests); GRID1_LENGTH 29.98 ruling restated
Task 2: implementer DONE_WITH_CONCERNS edc6691 (pushed by implementer). 1280 passed, 5 skipped, 4 strict xfails (ruling 2): single +0.30 (0.052), single -0.50 (0.056), adjacent FILE__031 (0.070) — all FILE__031's hidden +0.052 base residual; G2u FILE__027 NO_MATCH (evidence: 027-028 pair reads -0.52, moving 028 alone lines up 027-030). Own values: G2u 045 +0.884, 028 +0.687; G2f 051 +0.173, 059 -0.288. Not-OWN shares G1 93/100%, G2 85/92%. Skew stable. New rule: shallow/deep split at half the grid's evidence. Concerns for C14: alternate-line blocks (G2u 032-034, 040-042; G1u 012-015), G1u 7 CHANGES, G1f 8/9 no own value.
Task 2: review dispatched (opus a248972c35abc5131), package review-bc80ffb..edc6691.diff
C14 prep: pictures rendered in scratchpad/c14 (grid{1,2}_fit{0,1}.png + zooms; script c14/panels.py calls nsgeo.destagger via tests/destagger_data.lines_for). Implementer's 027/028 trace plot scratchpad/t2/w_g2u_27.png supports '028 only'.
Task 2: review (opus) — spec ❌ only on items already flagged for C14 (FILE__031 xfails, honest cause independently confirmed: FILE__021/041 track their own residual too; 041 passes base-d by 4 mm); quality Needs fixes (Important 1: FILE__027 strict xfail can never XPASS — approx(None)).
Ruling 6: FILE__027 stays a strict xfail (pinned outcome, not a tolerance, so a stretch of Ruling 2) — the pin came from the prototype, the implementer's trace plot and pair reading contradict it, and only the author can drop a spec pin; decided at C14 — cost if wrong: one test changes after C14.
Ruling 7: grid-local metres in the spike note (027-030 reflector positions) are not site coordinates; allowed under "file names and metres only" — cost if wrong: one sentence to delete.
Ruling 8: reviewer Minor 2 (per-line loops without a stop check; solve-loop checks unpinned) is the same Global Constraints wording as Ruling 5 → enters the fix loop for consistency. Minors 1,3,4,5,7,8 are cheap and in files already open → included. Minor 6 (CHANGES needs decisive halves, not clear) → C14 item for the author.
Task 2: fix round 1/5 dispatched (resume implementer a9e022ec3663e62ce; FIX_BASE edc6691): I1 027 xfail can XPASS; M1 raises=AssertionError; M2 stop checks + pinned solve check; M3 did-not-settle branch + test; M4 bins/half; M5 docstring; M7 move is_clear tests; M8 comment
Task 2: fix round 1 implementer DONE 770c7e0 (1287 passed, 5 skipped, 4 xfailed; results unchanged; did-not-settle branch fixed, old code failed new test on FILE__028)
Task 2: re-review dispatched (opus afcc2c6ef3d73ed0e), package review-edc6691..770c7e0.diff
Task 2: re-review (opus) — all 8 findings ADDRESSED, no new Critical/Important; termination/determinism of the new did-not-settle loop checked by the reviewer.
Task 2: fix round 1/5 (8 addressed, 0 open; commits edc6691..770c7e0)
Task 2: minor (deferred → final review): did-not-settle test assumes result order == solver numbering (add own.size == solver.dirs.size); solve_run stop test pins presence not per-line placement, refine bound >= 4 loose; profiles.py:16 "search range" is in steps there, metres elsewhere.
Task 2: minor (deferred → final review): _common_time_settings O(n^2) and measure.py:247 result loop have no stop check, yet the test comment says "every loop"; test_destagger_lines.py:8 says "three" xfails, there are four.
Task 2: complete (commits bc80ffb..770c7e0, review clean after 1 fix round)
C14: reached — results re-rendered at 770c7e0 (unchanged); STOPPED for the author (human gate). Questions: per-line better? any wrong? FILE__031 target (residual-aware), FILE__027 pin, CHANGES chattiness (CHANGE_M 0.40 / decisive vs clear), alternate-line blocks.
C14 author answers (2026-11-11): Q1 per-line values "make them look better"; Q2 alternate-line blocks "look right"; Q3 drop the FILE__027 spec pin: yes. Q4 (FILE__031 target) and Q5 (CHANGES count) not understood → re-asked in plainer words. Measured for Q5: CHANGE_M 0.40 → G1u changes 002/024/048 (drops 008/009, the spike's known partway lines), G2f 049 only; own values unchanged.
C14 author decisions (2026-11-11, "Go with your recommendations"): Q4 injected-error target = grid − (d + r0), r0 the line's own pre-injection residual (own value corrects everything off on the line); Q5 CHANGE_M stays 0.30. Spec amended cc5635b (§10 target, FILE__027 → not pinned, C14 outcome paragraph, §8 illustration).
C14 follow-up: dispatched to the Task 2 implementer (resume a9e022ec3663e62ce), FIX_BASE cc5635b, brief task-2-c14.md: 3 FILE__031 xfails → residual-aware passing tests (tolerance 0.05 unchanged); FILE__027 xfail removed; test-file deferred minors (docstring count, own.size == solver.dirs.size); spike note C14 line.
C14 follow-up: implementer DONE 5c29322 (1290 passed, 5 skipped, 0 xfailed). r0 031 +0.0524, 032 +0.0053; misses +0.002 / -0.007 / pair -0.015, +0.042 (032 8 mm spare). Added _Solver.residual, used by classify/refine (results unchanged).
C14 follow-up: re-review dispatched (opus a856877c6557cad7e), package review-cc5635b..5c29322.diff
C14 follow-up: re-review (opus) all addressed, no new breakage; numbers reproduced. Watch: FILE__032 adjacent pair 8 mm spare; residual-shared offset would cancel in G1 injected tests (Grid 2 size pins catch it) — by design.
C14: complete (commits cc5635b..5c29322)
Task 3: dispatched (sonnet, implementer aa7dbd9b25ecf5b0b), BASE 5c29322; carried: Refiner before _refresh() in __init__; Ruling 3; Ruling 4 (real-survey test grid 29.98); statuses OWN/CHANGES/NO_MATCH from Task 2
Task 3: implementer DONE_WITH_CONCERNS 0214fd3 (8 pure + 14 QGIS new pass incl. real survey; combined core+pure not re-run after boundary fix; concerns: code before tests (RED reconstructed), all-axes-failed summary omits unreadable names per constraints, 'and n more' joining, 8 m synthetic for real-measure tests)
Task 3: review dispatched (opus afa3294767aa77c6e), package review-5c29322..0214fd3.diff; controller running core+pure and full QGIS tier at 0214fd3 (scratchpad t3-coreplus.txt, t3-qgis.txt)
Task 3: review (opus) — spec ❌ (Review Focus 1 second half "results land in rows selected at press" untested; guide paragraph placed before the fit-first paragraph); quality Needs fixes (Important 1 = that test; partly plan-mandated). Copy verbatim, land order, P5/P6/P8, thread safety, done() all confirmed.
Ruling 9: all-unreadable grid gets a leading sentence `Could not measure: no line could be read. Nothing was changed.` before the not-measured group — spec §8 leaves the words to the builder and "Nothing was changed" is the pattern of every other failure — cost if wrong: one string.
Ruling 10: reviewer Minor 11 (Stop drops the run's reads, so Measure after Stop re-reads) is deferred to the walkthrough as a known C8 gap — merging a cancelled job's half-written cache crosses threads — cost if wrong: a second Measure after Stop is as slow as the first.
Task 3: fix round 1/5 dispatched (resume implementer aa7dbd9b25ecf5b0b; FIX_BASE 0214fd3): I1 + guide placement + Minors 1-10 (brief task-3-fix-1.md)
Task 3: fix round 1 implementer DONE 26da304 (68 measure+dialog passed; core+pure 1301 passed 5 skipped; mutation proof for I1 reverted). Note: twice test accepts ±0.15 (sign unchecked) — named check for re-review.
Task 3: core+pure at 0214fd3: 1298 passed, 5 skipped. Re-review dispatched (opus a1be6516f6f9e9c80), package review-0214fd3..26da304.diff (named check: twice test sign)
Task 3: full QGIS tier at 0214fd3: 1681 passed in 14:48 (baseline 1667 + 14 new)
Task 3: re-review (opus) — I1, Spec 2, Minors 1,2,3,6,7,8,9,10 ADDRESSED; open: Minor 4 (reopen the SAME site, not a new folder), Minor 5 (twice test must pin the sign: expected ≈ −0.142, confirmed −0.141 by probe); new Minor: progress test ordering race (:451-453). Out of scope: all rows moved to another grid → empty job → Ruling 9 sentence wrongly says "no line could be read".
Ruling 11: Measure with no selected row on this grid (targets empty after the snapshot filter) starts nothing and shows the No-targets copy `Select the lines to fill, then press Measure.` — an empty job measures nothing, and the selection is what the author must change — cost if wrong: one string.
Task 3: fix round 1/5 (12 addressed, 2 open + 1 new minor; commits 0214fd3..26da304)
Task 3: fix round 2/5 dispatched (resume implementer aa7dbd9b25ecf5b0b; FIX_BASE 26da304; brief task-3-fix-2.md)
Task 3: fix round 2 implementer DONE 591e273 (70 QGIS + 11 pure passed)
Task 3: re-review round 2 dispatched (opus a6bf13d18e4ed08c3), package review-26da304..591e273.diff
Task 3: re-review round 2 (opus) — all 4 ADDRESSED, no new breakage (probes: path-vs-identity, sign flips ×3, sleep race, guard removal each fail exactly the intended test).
Task 3: fix round 2/5 (4 addressed, 0 open; commits 26da304..591e273)
Task 3: minor (deferred → final review): Ruling 11 test does not assert the Destagger box is unchanged.
Task 3: complete (commits 5c29322..591e273, review clean after 2 fix rounds)
Task 4: merged origin/main 414b6aa into the branch → 55fdc59 (README roadmap conflict resolved: M15 leads Next, #159 In progress 'Built; final review and walkthrough next'); lint clean; pushed
Task 4: deployed profile ns_geo_destagger (cp -a ns_geo + dev_link → this worktree, QGIS3); sandbox ~/nsgeo-destagger-check/Nashville_City_Cemetery (copy of ~/nsgeo-m4-check site json + gpkg); expected walkthrough values verified with core on the site copy (G1 +0.152 ±0.013 / -0.066; G2 +0.162 / -0.061; Grid4 one-way). Walkthrough page drafted (scratchpad walkthrough/), publish after the final review fix wave.
Final review (opus aa65b920bdb4c8c83): With fixes. Important 1: every line excluded before the neighbour stage → axis says TOO_FEW/ONE_WAY and the all-failed summary hides the per-line reasons (20 lines of 5 m → "too few lines walked in opposite directions"). Minors 1-9; #97 no interaction (checked); never-commit clean; deferred minors triaged (all resolved or can wait).
Ruling 12: when no line survives the exclusions, the axis fails with a new reason NO_LINES = "none of the grid's lines could be measured", and when every axis failed the summary still appends the "Not measured, left as they were:" group, leaving out NO_NEIGHBOUR lines (the axis reason already explains them) — spec goal 3 says lines are named with a reason — cost if wrong: one string and a longer failure message.
Ruling 13: the Destagger column keeps 2 decimals (author passed G5 "Destagger to the centimetre" in the placement walkthrough); asked again in this walkthrough's calls to confirm because Measure fills millimetres — cost if wrong: a one-character format change after the walkthrough.
Ruling 14: box_value takes the axis with the most lines_used among axes that measured, None only when none did (plan said "more lines_used; None if it failed") — serves the author when the larger axis fails — cost if wrong: the box shows the smaller axis's value.
Ruling 15: final-review Minor 3 → the status label's tooltip carries the uncapped summary (every name); P12 cap stays in the visible line — cost if wrong: a tooltip nobody reads.
Ruling 16: final-review Minors 5 (small-grid spread) and 6 (one short record cuts every window) → follow-up issue offered to the author, not fixed here — cost if wrong: a misleading ± on tiny grids until then.
Final fix wave dispatched (resume Task 3 implementer aa7dbd9b25ecf5b0b; FIX_BASE 55fdc59; brief final-fix.md): I1 (Ruling 12), M1 bootstrap order, M3 tooltip (R15), M4 stale-site guard, M7 box_value (R14), M8 mirror per-line test, M9 guide
Task 4: tiers at 55fdc59 (merged main): core+pure 1355 passed 5 skipped; QGIS 1756 passed in 14:47 (the fix wave started editing during the QGIS run; re-run after the wave)
Final fix wave: implementer DONE_WITH_CONCERNS d59f2b6 (also leaves AXIS_FAILED lines out of the all-failed group; exported NO_NEIGHBOUR and AXIS_FAILED from nsgeo.destagger for the plugin boundary). Re-review + full tiers next.
Final fix wave: re-review (opus) — all findings ADDRESSED, both judgement calls sound, no new breakage; spreads unchanged in natural order (±0.013 holds). Grid4 on the site copy checked: 60 × NO_NEIGHBOUR, summary exactly the one-way sentence.
Final review: minor (deferred → follow-up): path-keyed _bins untested (stale-site guard makes the cross-site case unreachable); _redraw-error tooltip nit.
Task 4: walkthrough published https://claude.ai/artifact/5rdHPYHA1xiog9AtxPHyPK (db collection results, 21 checks A1-A4 B1-B2 C1-C6 D1 E1-E8; empty at publish); README roadmap 24a94b9 'Built and reviewed; the walkthrough is next'. Waiting on full tiers at d59f2b6, then the author's walkthrough (human gate).
Task 4: tiers at d59f2b6: core+pure 1360 passed 5 skipped; QGIS 1758 passed in 15:45. Ready for the author's walkthrough.
Walkthrough results (2026-11-12, read from the artifact db): 17 pass, 3 skip (E2 no selected row on this grid, E3 no file readable, E7 NO_LINES — covered only by automated tests), C6 unmarked (question). Notes: A2 pass but the long status line widens the dialog until OK is hard to reach — must fix; A4 pass, fitted Grid1 SW blob wavy at 13.4-18.2 ns, comes together deeper (one shift per line at every depth is the author's own rule); B2 "looks great"; C6 asks why Measure reads the whole grid when 10 rows are selected (C5, my call, never confirmed) — discussion opened; D1 pass but asks why the files are read before the one-way check; E5 pass, dislikes long info in a tooltip ("fine for now"); E6 pass (Ruling 13 confirmed: 2 decimals).
Walkthrough fixes (inline, right-sized): A2 status QLabel setWordWrap(True) + QGIS test that minimumSizeHint width does not grow (canned 8 own values, and the real survey); D1 core one_way_result(placements) → DestaggerResult|None (same result as measure_destagger on a one-way grid, real Grid 1 forced one way both directions + lone line; None when any axis walked both ways), MeasureJob uses it so a one-way grid reads nothing (progress (0,0)); pure test + QGIS read count 0. Pure multi-channel test given a back-walked neighbour (a lone line is no longer read).
Walkthrough fixes committed 6d4733e (pushed): core+pure 1365 passed 5 skipped (1364 + public-API README row), Measure + Edit lines dialog QGIS files 73 passed incl. real survey; lint/types clean; Grid4 real one_way_result == full measure. Full QGIS tier left to CI. Author re-check of A2/D1 asked; C6 (C5 scope) put to the author with a recommendation to keep the whole grid.
C6: author accepted the recommendation (keep whole-grid measure; C5 confirmed). Tooltip + guide + spec wording → 871eee8, pushed; Measure QGIS file 25 passed. Selection-only option NOT filed (offered only). Still pending: author re-check of A2/D1 in QGIS, then merge ask.
Re-check (author, 2026-11-12): A2 wrap good, D1 Grid4 at once good, tooltip fine. Author: 'make a pr and iff it passes CI merge'. Ledger committed as decision record docs/superpowers/sdd/2026-11-11-nsgeo-auto-destagger/ (no review diffs) with walkthrough-results.md; README roadmap #159 → Done.
