# SDD ledger — plan: docs/superpowers/plans/2026-11-21-nsgeo-m17c-plan-a-true-distance.md

Branch nsgeo-m17c, worktree .worktrees/nsgeo-m17c. Plan commit 49f47a8. Spec: docs/superpowers/specs/2026-11-06-nsgeo-gps-lines-design.md (decision 16, §17). User said "Build it" 2026-11-21 (subagent-driven).
Constraints file for reviewers: global-constraints.md (this dir).
Models: implementers sonnet, reviews opus (memory: subagent-model-tiers).

## Pre-flight scan (2026-11-21)

| Pair / task | Produces vs consumes | Finding |
|---|---|---|
| T1 ↔ T2 | T1 spacing.py usual_step/gap_steps/left_out, TrackPlacement.gap_m → T2 adds resample_even/sample_back to the same file, consumes them | consistent |
| T1 ↔ T3 | gap_steps/left_out/usual_step → TraceAxis | consistent |
| T1 ↔ T5 | gap_threshold, TrackPlacement.gap_m → Edit lines "auto {v:.2f}" | consistent |
| T2 ↔ T5 | session.edit_lines re-attach on placement change → Gap over edit relies on it | consistent (gap change is a placement change) |
| T3 ↔ T4 | TraceAxis, ViewTransform(axis=), paint_spans → ProfileView/Dock | consistent |
| T4 ↔ T5 | _trace_axis_for → test_gap_over_extremes_reach_the_profile reads transform.axis.gap_m after OK | R4 below (axis must be rebuilt on the geometry-changed path) |
| T1 self | tests vs interface | clean; checked the arithmetic of every concrete test (medians, thresholds, left_out arrays) |
| T2 self | test_sample_back (exact on drawn traces) vs "0 more than half a step from both edge traces" | CONFLICT → R1 |
| T2 self | usual step 0 / majority-zero steps → step 0 grid | gap → R2 |
| T2 self | replace() keeps trace_x_m; does any step change n_traces? | checked: no step changes the trace count (trace_stack is a running mean; timecutoff crops rows) — clean |
| T2 self | other Radargram.from_profile sites (session:1243, paraview_export:508) | both are time-zero probes; migration does not move time zero → left on from_profile, clean |
| T3 self | "end traces reach half their own step outward" vs test_a_lift_at_the_first_step_draws_trace_0_half_a_step_wide | CONFLICT → R3 |
| T4 self | velocity_curve_points "evenly in metres" vs Global "tape lines unchanged by construction" | CONFLICT → R5 |
| T4 self | test_a_click_in_a_gap_picks_nothing asserts only a negative | rubric: could pass vacuously → R6 |
| T5 self | "Fix any existing Edit lines test that counted columns by index" vs Global "existing tests unmodified" | not a conflict: Global allows named+justified changes |

## Rulings
- R1: resample_even keeps every even column that is **less than one usual step** from the nearest drawn trace (interpolated across the gap from the two nearest drawn traces) and zeros the rest; test_nothing_is_invented_inside_a_gap asserts columns **at least one step** from both edge traces are 0. — why: with a half-step margin the column bracketing an edge trace on its gap side can be zero, so sample_back dims every lift-edge trace by up to 50 % after migration (a visible dark column at each lift) and the plan's own round-trip test fails; one step is the least margin that reads every drawn trace back exactly. The display's half-step cap (Global) is unaffected. — cost if wrong: up to half a step more interpolated data inside each gap in the intermediate grid only; changing the margin back is one constant.
- R2: MigrateFk.apply uses today's call (rg.dx_m) when usual_step(trace_x_m) is not finite and > 0. — why: a step of 0 makes an infinite grid. — cost if wrong: a degenerate line migrates at wheel spacing, as today.
- R3: an end trace reaches half its own step outward, capped at half a usual step (the gap cap applies outward too). With a lift at the first step, trace 0 is drawn one usual step wide (half a usual step each side); the test asserts that. — why: uncapped, trace 0 would stretch over half the lift outward. — cost if wrong: test name slightly loose; the hatched margin beyond the end is unchanged.
- R4: (T4) the TraceAxis is built on every path that calls set_axes for a line, including _on_geometry_changed after Edit lines, so a Gap over change reaches an open profile.
- R5: velocity_curve_points samples evenly in metres only for a line with a trace axis (GPS); tape lines and cuts keep today's sampling exactly, and points stay in ascending trace order. — why: Global "tape lines unchanged by construction". — cost if wrong: none visible (even lines sample identically either way).
- R6: test_a_click_in_a_gap_picks_nothing also clicks a drawn trace and asserts pick_requested fires there (positive control).

## Progress
- Task 1: dispatched (BASE 49f47a8, implementer sonnet abf053125b2e30caf)
- Task 1: implementer DONE_WITH_CONCERNS d306e8d (push failed in sandbox; pushed by controller; TDD order note) → review
- Task 1 review (opus adb60776a7d920c10): spec ✅, Approved; 7 minors. Round 1 (optional minors 1-5: pin strict >, filterwarnings, left_out validates for any n, one check_gap_m helper, errstate on median) sent to implementer. Minor 6 (reconstructed RED) noted; minor 7 (dup real-data loader) accepted as brief-mandated pattern.
- Task 1 round 1 fix de3e54a (pushed); scoped re-review sonnet a71884c924d31f177 running
- Task 2: dispatched (BASE de3e54a, implementer sonnet ade52f2e9ee6d34af) with R1, R2 + facts (no step changes n_traces; 1243/508 are zero probes)
- Task 1 re-review: all 5 addressed, no new breakage
Task 1: complete (commits 49f47a8..de3e54a, review clean)
- Task 2: implementer DONE_WITH_CONCERNS ae83d64 (pushed). Concerns: set_travel_shift (bulk GPS destagger) does not re-attach sources (constant shift → migration unchanged, but source.trace_x_m goes stale) → R7 candidate; extra extrapolated column past last trace (design addition). Review opus a4e0a51613e244790 running.
- Task 2 review (opus a4e0a51613e244790): spec ✅ (deviations a–c accepted), Needs fixes: C1 Add step dialog probe `replace(data=data[:, :1])` raises on GPS lines (trace_x_m length guard); I1 unbounded extrapolation past last trace; I2 tests don't pin resampling (a: partly plan-mandated geometry) nor the R1 one-step margin (edges on-grid); I3 edit_lines emits stack_changed before _set_dirty and before order bookkeeping.
- Ruling R7: set_travel_shift re-attaches GPS sources like edit_lines (after dirty) — why: two paths for one change must leave one state — cost if wrong: a stack re-run on a bulk destagger.
- Ruling R8 (I2a plan-mandated): replace the alternating 0.015/0.025 geometry with one where ignoring trace_x_m fails (e.g. a monotone step ramp), and assert both that the real path focuses and that plain migrate_fk(dx=usual) on the same record does measurably worse — why: the plan's geometry cannot detect the regression it exists for — cost if wrong: one test's geometry.
- Task 2: minor (deferred): grid size bounded by length/step not trace count (a far GPS fix could allocate a big grid; real data ≤1.13×)
- Task 2: minor (deferred): a uniform destagger / grid-only move re-runs a GPS stack for an unchanged migration (ruling cost)
- Task 2 ⚠️ → Task 5: does `same_placement` (line_edit.py:104-114) see a TrackPlacement gap_m/travel_shift change so slices re-prepare? Carry into Task 5 dispatch.
- Task 2: fix round 1 dispatched to ade52f2e9ee6d34af (C1, I1, I2, I3, R7, minors 1-2)
- Task 2 round 1 fix 5dbae7c (pushed); re-review sonnet a248758fe953eb643 running
- Task 3: dispatched (BASE 5dbae7c, implementer sonnet af4d59ca246a2d408) with R3
- Task 2 re-review round 1: all 6 addressed, no new breakage. Task 2: fix round 1/5 (6 addressed, 0 open; commits ae83d64..5dbae7c)
- Task 2: minor (deferred): `assert near == apex_k` tautology in the ramp test (harmless)
- Ruling R9: no real-DZT migration test exists for a GPS line (memory: real data first) → Task 4 adds one to test_plugin_profile_true_distance.py (real_data): FILE__016 migrated through its source is finite, same shape, and the lift-edge traces 354/363 keep energy comparable to their drawn neighbours (no dark column) — cost if wrong: one more real-data test.
Task 2: complete (commits de3e54a..5dbae7c, review clean after 1 round)
- Task 3: implementer DONE_WITH_CONCERNS 44159ba (pushed): re-exported spacing names from nsgeo.geometry + README rows (boundary test); R3 read as 'cap outward only when the end step is a gap' (accepted: consistent with interior traces); paint_spans x clipped but first/last integer → Task 4 must re-derive fractional source (R10 candidate); with_window clamps in trace units (min 4 units). Full core+pure not re-run after its last fix → controller runs it.
- Controller ran core+pure at 44159ba: 2222 passed, 9 skipped, 19 xfailed. Task 3 review opus afaf75e7d80907c8b running.
- Task 3 review (opus afaf75e7d80907c8b): spec ❌ R3 reading; Needs fixes: I1 R3 cap only on gap; I2 window-edge-in-gap test never puts an edge in the gap. Minors 1-10.
- Ruling R3 amended: an end trace's outward reach is half its own step, capped at half a usual step only when that end step is a gap — why: interior traces run halfway to a neighbour across any non-gap step (a slip is drawn stretched), so the ends do the same; my "capped every time" wording was looser than intended — cost if wrong: a long non-gap end step draws up to 3 usual steps outward. Pin with a 3×-usual non-gap end-step test.
- Ruling R10: paint_spans returns (x0, x1, c0, c1): clipped local pixels and the FRACTIONAL source columns (trace units) they show, so Task 4 maps source→target exactly like today's source_rect/target_span — why: integer first/last forces Task 4 to re-derive the clip from drawn() — cost if wrong: one tuple's meaning.
- Task 3 fix round 1 dispatched to af4d59ca246a2d408: I1 (test only + docstring per amended R3), I2, R10, minors 2,3,4,5 (refuse zero-length axis; guard 1:1 division),6,7,8,9.
- Task 3: minor (deferred, walkthrough note): with a lift at the first step the Fit view opens with about half the lift hatched left of trace 0 (ruler's end extrapolation; one road) — judge at the walkthrough.
- Task 3 round 1 fix bf131db (pushed by controller); re-review sonnet aa378214e56960613 running. Fix-report concern: a lone capped trace beside a gap is stretched over its drawn extent, so paint c ≠ trace_of_x there (expected: one image column fills its drawn extent).
- Task 4: dispatched (BASE bf131db, implementer sonnet ad235f9e698835c9e) with R4, R5, R6, R9 + paint_spans R10 interface
- Task 3 re-review round 1: 11/11 addressed, no new breakage. Task 3: fix round 1/5 (11 addressed, 0 open; commits 44159ba..bf131db)
- Task 3: out-of-scope note: zero-length axis refusal → Task 4's _trace_axis_for must catch it (brief already says None on any failure, logged)
Task 3: complete (commits 5dbae7c..bf131db, review clean after 1 round)
- Task 4: implementer DONE f930a8f (pushed): 363 QGIS + 11 real_data + core+pure 2230 passed. Notes: no right-click pick removal in the view (velocity points only); FILE__028 has left-out traces 1268-1275 (test scoped to 830-849); selection band edges still in trace units; time-zero drag not exercised.
- Prep for Task 5: TrackEdit.changes (line_edit.py ~259) compares grid_id/label/travel_shift only → must include gap_m or a Gap-over-only edit is dropped. slices_engine.placements_changed uses TrackPlacement == (frozen eq dataclass) → sees gap_m, so slices re-prepare (resolves Task 2 ⚠️).
- Task 4 review (opus a84c0eec11eed3154): spec ✅, Approved, 0 Critical/Important. ⚠️ pick removal: view has right-click removal for velocity points only (picks removed via Surfaces dock) → substitute test accepted; cut test lives in test_plugin_profile_cut.py (fixtures) accepted; FILE__028 has left-out traces 1268-1275 (test scoped to the 841 lift); span seams → walkthrough.
- Task 4: minor (deferred → FINAL FIX WAVE): (1) GPS paint ~10 ms paint_spans + ~11 ms per 200-pt fit curve per repaint (ViewTransform recomputes _walk_window per scalar call → cache in __post_init__ / vectorise); (2) R5 keyed on placement type not on axis → zero-length GPS line collapses curve + RuntimeWarnings; (3) mirror-flip block duplicated + source_rect recomputed; (5) read-out test partly tautological; (6) hatched-gap test checks one side only; (7) 1:1 check can skip silently; (8) unused `shown` fixture in file016 migration test, FILE__028 test name overstates, no test for wrong-length axis drop / _trace_axis_for failure, warning logged on every set_axes for a degenerate GPS line.
- Task 4: minor (deferred, walkthrough): mirrored span path unreachable for GPS (no ruler until Plan B); selection band reaches into a gap (trace-unit edges, §17-consistent).
Task 4: complete (commits bf131db..f930a8f, review clean)
- Task 5: dispatched (BASE f930a8f, implementer sonnet a48434c516dd43e59) with TrackEdit.changes note, Destagger-bulk-row pattern, inf auto value handling
- Task 5: implementer DONE 0bb85d9 (pushed): 126 QGIS + 1 real_data + core+pure 2231 passed; 'auto —' when usual step 0; gap_threshold re-exported; guide edited (kept hyperbola-fit caveat minus 'until true-distance' clause).
- CI: f930a8f (Task 4) success; earlier runs cancelled by newer pushes; 0bb85d9 in progress (44918149566)
- Task 5 review (opus ac0a67b4bfcadc9f9): spec ❌ (extremes test lacks source gap_m; stale guide sentence "comes with true-distance profiles"), Needs fixes: I1, I2. Minors 1-8.
- Ruling R11: "auto —" (automatic Gap over infinite: usual step 0 or < 2 traces) is accepted copy — why: no number to show and "—" is the table's existing blank — cost if wrong: one string.
- Task 5: fix round 1 dispatched to a48434c516dd43e59: I1, I2, minors 1 (hyperbola caveat reason), 2 (bulk sentence + Gap over row in guide), 3 (test auto —), 4 (check_gap_m in the cell + join the elif chain), 6 (exact auto 0.60), 8 (tape "—" tooltip GAP_TIP).
- Task 5: minor (deferred): {v:.2f} shows a typed value below 0.005 as "0.00" (plan-mandated format; spin box min 0.01 so only typed cells reach it)
- Task 5 round 1 fix 1e637d4 (pushed)
- Task 5 re-review round 1: 8/8 addressed, no new breakage. Task 5: fix round 1/5 (8 addressed, 0 open; commits 0bb85d9..1e637d4)
Task 5: complete (commits f930a8f..1e637d4, review clean after 1 round)
- Walkthrough prep: profile ns_geo_m17c (cp -a ns_geo + dev_link → this worktree); sandbox ~/nsgeo-m17c-walk/ (survey1 = with-dzg copy, survey2 = grid2 copy, tape/ = ten campus tape lines). Lift facts: FILE__016 gap 6.15–8.24 m (355–362 left out); FILE__028 single 1.54 m step 14.46–16.00 m, lift 23.44–26.26 m (1268–1275 left out), single step at 26.6 m; FILE__011 has short gaps (0.15–0.34 m steps) at ~0.4 m, 12.7–13.6 m, 14.1 m (29, 652, 653 left out).
- FINAL REVIEW (opus a4ad43013f3d047d9, b79b24e..1e637d4): With fixes. I1 GPS paint 4–12× slower (19 ms bare, 63 ms with 3 fits on FILE__016; hover ~16 fps) → fix before walkthrough. M1 plan-mandated test_an_even_trace_axis_migrates_exactly_as_dx deleted in 5dbae7c unrecorded → restore. M2 _reattach_gps_sources fires on label/grid-only edits and on stacks with no source. M3 velocity-box tracer uses left-out traces. M4 re-attach after lines_changed → old record under new axis / double run on cold cache. Triage: all deferred minors can wait except T4(1)=I1. Seams: none on real lines. Privacy clean.
- Ruling R12: the new tape-line real-data test's another EPSG code → EPSG:32632 (the synthetic convention) — why: a UTM zone was scrubbed from the M17b record as site-identifying; a new test should not add another — cost if wrong: none (synthetic grid origin).
- Ruling R13: declined-to-judge items stay as built (Gap over column on tape-only grids; even GPS axis migrates at dx_m; gap read-out drops time; 4-unit zoom floor; migrated left-out traces carry smeared energy; bulk spin default 0.10) — plan-mandated or walkthrough's call — cost if wrong: walkthrough notes.
- Final fix wave dispatched (sonnet): I1, M1, M2, M3, M4, R12, + cheap deferred T4(7) assert can_true_scale and T2 grid guard (>4× trace count → plain path).
- Final fix wave 8a23e08 (pushed by controller): paint FILE__016 7.6/7.7/9.5 ms (was 19/21/63), FILE__002 11.3 (was 71); 2 existing tests changed (can_true_scale assert; EPSG 32632); MAX_EVEN_GROWTH=4; RED not observed for new spy tests.
- Final fix wave re-review (opus ac89be4216125cc42): 8/8 addressed, no new Critical/Important. Spy tests verified red on old code (1398 vs 10 calls per paint).
- Final: parked — set_travel_shift half of the re-attach-order test logs gap_m (unchanged by a destagger) so it doesn't pin the order — Ruling: code correct (re-review read it); tighten later — cost: a future regression of that order goes unseen.
- Final: parked — paint-count spy has only an upper bound (paintEvent swallows exceptions) — Ruling: probe showed 10 calls, no logged error; a pick test exercises the axis path outside paint — cost: a throwing paint could pass.
- Final: parked — a velocity box wholly over left-out traces becomes a one-trace box beside it and is refused "box too small" — Ruling: user gets a reason, nothing corrupted.
- CI 8a23e08 green (3.44, 4.2, smoke 3.40/3.44/4.2, all OS). Walkthrough page https://claude.ai/artifact/9zESYFKeoBoW29QKYtBXvx (db 'checks', W1–W12, questions on W4/W5/W8/W11), store read back empty. AWAITING THE USER. Do not delete this workspace until the decision record is copied into docs/superpowers/sdd/.
- 2026-11-22 walkthrough part-way (read from the checks db): W1 W2 W5 pass. W4 no status; note: the bigger FILE__011 gap looks real (the operator put a DZX mark there), unsure about the two smaller ones; asks where the squeezed-together traces are (can't judge slip vs hidden data without seeing them); proposes moving the gap and slip handling into the Processing panel as steps the user applies if wanted, and (maybe separately) drawing regions to drop from a profile, like time zero / cutoff but along distance. W3 and W6–W12 open.
- 2026-11-22 user travelling, continuing on a laptop: record snapshot committed to docs/superpowers/sdd/2026-11-21-nsgeo-m17c-plan-a-true-distance/; local state (all ledgers, memory, sandboxes, survey data) bundled at ~/nsgeo-travel/.
