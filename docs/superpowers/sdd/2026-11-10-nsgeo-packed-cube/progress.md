# SDD ledger — plan: docs/superpowers/plans/2026-11-10-nsgeo-packed-cube.md

Spec: none separate — issue #113 + the plan's "Design (agreed with the user, 2026-11-10)" section is the authority. Rulings are made against that section.
Execution: subagent-driven, chosen by the user 2026-11-10. Models: implementers sonnet (Task 1 core format = judgment-heavy → sonnet, escalate opus at round 4), reviews opus.
Branch nsgeo-packed-cube, plan commit 068ac42. Baseline core+pure 1070 passed / 5 skipped; QGIS baseline running (scratchpad qgis-baseline.txt).

## Pre-flight scan

| Rows | Produces / consumes | Found |
|---|---|---|
| Task 1 ↔ Task 2 | T1 produces SliceCube.blocks, CubeBlock (cells int64), nbytes, build_cube one block; T2 consumes them (covered_cells == blocks[0].cells.size; estimate cube_bytes == nbytes) | consistent: nbytes = n·8 + nz·n·4 + n·4 = plan call 11 formula |
| Task 1 ↔ Task 2 (files) | both edit binning.py, __init__.py, test_slices_cube.py | sequential, disjoint regions (T1 accumulate/build_cube; T2 adds covered_cells) — no conflict |
| Task 1 self | tests (cube + store) vs plan calls 1–9; files list creates test_slices_cube.py, Step 7 adds packages/nsgeo-core | agrees. Watch: bit-identity could differ by 1 ulp in a 1-column degenerate case (numpy reduction order) — real-data tests have many columns |
| Task 2 self | tests vs plan calls 10–13; engine line refs 665/667/880/972/1725/1727 match current file | agrees; dock test needs a frame before preparing (plan says set resolution first if none) |
| Rubric | any plan-mandated defect (assert-nothing test, duplicated logic)? | none: Step 6 timing is a measurement, not a test, by design |

Scan clean; no rulings needed before Task 1.

## Tasks
Task 1: dispatched (BASE 068ac42, implementer sonnet, agent aee25e5380a7fbb4f)
Task 1: implementer DONE_WITH_CONCERNS at 94d2cf2 (core+pure 1102/5 skipped; packed slice+coverage 0.006 s vs dense 0.046 s; 2.9 MB vs 57.9 MB). Concerns: tests written after code (RED shown by reverting src); block checks shapes + integer kind, not exact dtypes (wide-dtype narrowing test needs it); CubeBlock row added to core README (test_public_api); stale `cube.mean` docstring mentions in render.py/display.py left.
Task 1: minor (deferred): TDD order slipped (tests after code; RED reproduced by reverting src) — process only, tests exist and failed for the right reason.
Baseline QGIS tier (started before Task 1, imports loaded at start): 1597 passed in 15.5 min.
Task 1: review dispatched (opus, package review-068ac42..94d2cf2.diff)
Task 1: review (opus) — Needs fixes. ⚠️ resolved by controller: timings are in the 94d2cf2 body; pushed (origin = 94d2cf2); real-data tests ran per report (files present). Sunnyside v1 hand check stays a coordinator gate after Task 2.
Task 1: Ruling: Important 1 (plan-mandated weak two-block test: shared lines carry identical means, so an unweighted mean of block means passes) — add the reviewer's crossing split (5 X lines vs 5 Y lines with different trace counts on a 27x27 frame at 0.75 m) as a third case — plan call 3 is what #47 relies on and the plan's test could not pin it — costs one more test if wrong.
Task 1: Ruling: Minor 2 promoted into the loop — a v2 file with float cells_0 loads truncated, contradicting plan call 9 ("every malformed v2 file raises CubeStoreError"); fix with kind checks in CubeBlock (mean kind f, count/cells kind i/u) + casting="same_kind" in the store + a damaged-file case. Exact dtypes are NOT enforced, so the brief's wide float64/int64 narrowing test still constructs — costs: a hand-built float64 block would hold 2x memory and nbytes would exceed the estimate; nothing in nsgeo builds one.
Task 1: minor (deferred): cube.py:190 "bit-identical" holds for blocks wider than one cell only (single column sums pairwise) — limit the docstring claim.
Task 1: minor (deferred): test_slices_store.py:396-399 dead setup (cube/good/save_cube unused).
Task 1: minor (deferred): store.py:145-150 v1 missing-mean/count branch untested; test_loading_a_file_missing_one_required_array_fails_clearly docstring stale.
Task 1: minor (deferred): stale `cube.mean` references in render.py:106,109, slices/display.py:151,153, tests/test_real_files.py:264,271 — reword to "every raw level".
Task 1: minor (deferred): cube.py:177 `_window` only validates — rename `_check_window`.
Task 1: minor (deferred): store.py:145-155 load_cube carries two branches' state across the with-block (None placeholders) — polish.
Task 1: fix round 1 implemented at 7f2b15a (crossing-split weighting case kills unweighted mutant; kind checks + same_kind cast + 3 new cases; core+pure 1106/5); scoped re-review dispatched (opus)
Task 1: fix round 1/5 (2 addressed, 0 open — weighting pinned on both read paths; kind checks + same_kind cast; commits 94d2cf2..7f2b15a)
Task 1: minor (deferred): same_kind casts on count_{i}/mean_{i} (store.py:107-108) unpinned — add "count_0 saved as float" damaged case.
Task 1: minor (deferred): same_kind still upcasts wrong-kind arrays before the block's kind checks (int32 mean_0 loads as float32, bool count_0 loads as 1, uint64 cells_0 loads) — lossless, but CubeBlock's mean-kind check is unreachable via load_cube; a dtype.kind check before the cast would refuse them.
Task 1: minor (deferred, pre-existing): int64 count_0 with values >= 2^32 wraps to int32 silently on load; save_cube cannot produce it.
Task 1: complete (commits 068ac42..7f2b15a, review clean)
Task 2: dispatched (BASE 7f2b15a, implementer sonnet, agent a40febaf7cf4d7d8a)
Coordinator gate (Review Focus 1) DONE at 7f2b15a: user's four Sunnyside v1 .npz (grid1cube, grid2cube, mincurv_cube, testcube) load as 1 block; coverage and 3 windows each assert_array_equal to the raw dense arrays; packed 2.6/1.2/14.9/9.6 MB vs dense 7.5/6.2/108.5/73.9 MB. Script in session scratchpad v1_check.py (not committed).
Task 2: implementer DONE at dd66f24 (core+pure 1110/5; QGIS 1599 = 1597+2; touched core README + __all__ for test_public_api; resets at set_source, prepare-finished _lines, _rebuild_geometry, clear)
Task 2: review dispatched (opus, package review-7f2b15a..dd66f24.diff)
Task 2: review (opus) — Needs fixes. ⚠️ resolved by controller: prepared coords ARE the pre-prep trace_coords (engine passes line.trace_coords(frames) into PreparedLine, which rejects a coords/trace-count mismatch), so the dock's and the engine's counts agree by construction.
Task 2: Ruling: Important 1 (plan-mandated weak dock test: the 6x6 m fixture rounds every figure to "1 MB", so the label assertion passes for any n_covered) — replace with a spy on nsgeo_qgis.ui.slices_dock.estimate_memory asserting the n_covered it receives equals the trace-coords count and is < n_cells — the plan's label-equality test could not fail — costs one monkeypatch if wrong.
Task 2: Ruling: Minor 2 promoted — the "Keep the volume in memory (N MB)" checkbox shows "(1 MB)" while a preparation runs (engine has no lines yet → covered 0), contradicting design item 5 ("the memory figure counts the covered cells, before preparing as well as after"); fix: while the engine is not prepared, the checkbox shows the dock's own before-preparing estimate's cube_bytes — costs a few lines in the dock if wrong.
Task 2: minor (deferred): MemoryEstimate docstring (slices_plan.py ~285-290) "cube memory grows with resolution and not with line count" is now false for a packed cube.
Task 2: minor (deferred): rotated UTM frame setup duplicated in test_slices_cube.py (~288-297 vs 103-110) — a _rotated_frame(cell) helper.
Task 2: minor (deferred): test_pure_slices_plan.py:160-162 n_covered=120*120 has no effect (choose_residency returns streaming from the trace-count branch first) — say it is a deliberate upper bound.
Task 2: minor (deferred): plan call 13 edge cases untested (a line whose trace_coords raises is skipped; no frame → 0); code implements both.
Task 2: fix round 1 implemented at c7bd8ce (dock test spies on estimate_memory; SlicesDock._included_estimate shared by label + checkbox; checkbox uses engine.estimate only when prepared; dock+engine files 213 passed). Stray pytest pid 87639 belongs to another session's worktree .worktrees/nsgeo-multigrid — not ours, left alone.
Task 2: fix round 1/5 (2 addressed, 0 open — dock spy test fails on n_cells/0 mutants; checkbox uses the before-preparing estimate until prepared; commits dd66f24..c7bd8ce)
Task 2: minor (deferred): during a RE-preparation the checkbox keeps the previous source's figure (labels refresh before prepare() calls set_source; nothing refreshes the checkbox until _on_prepared) — contradicts the new docstring "so the two never disagree" (slices_dock.py:1066-1068); one-line fix: call _update_resident_check_label() after engine.set_source(choice) in prepare() (~:1337).
Task 2: minor (deferred): on a grid change the included label counts the new grid's lines against the old frame until _on_prepared (refresh precedes set_source) — temporary.
Task 2: minor (deferred): no test distinguishes the checkbox's is_prepared branch from the before-preparing branch (figures agree once prepared).
Task 2: minor (deferred): fix report pastes no test output; implementer mutated the shared worktree in place (restored, tree clean) rather than a scratch copy.
Task 2: complete (commits 7f2b15a..c7bd8ce, review clean)
Final review dispatched (opus, review-ddebce6..c7bd8ce.diff, pointed at ledger minors). Full suites on c7bd8ce running in background (scratchpad branch-suite-c7bd8ce.txt).
Final review (opus): Ready with fixes — no Critical/Important. Minors: M1 checkbox stale during re-preparation (one-liner); M2 docstrings this branch made false (MemoryEstimate, format_status "quadruples the cube", cube.py bit-identical clause, cube.mean mentions in render.py/display.py/test_real_files.py); M3 site has no overall budget and packing makes more big grids resident (pre-existing per-grid cap; note on #107/#108); M4 plan call 13 skip path untested; M5 store test upkeep. All four rulings judged sound (two resolved plan defects). Declined: load_cube lets zlib.error/NotImplementedError escape on corrupt compression (pre-existing, follow-up issue).
Ruling: final fix wave = M1 (+ a test), M2 sweep, M4 skip-path test, M5 (dead setup, stale docstring, count_0-as-float damaged case), pure-test n_covered comment — the reviewer marked M1/M2 fix-before-merge and the rest are cheap test pins in files already touched — cost if wrong: a slightly larger fix diff. Left for later: _window rename, load_cube state polish, rotated-frame helper, same_kind upcast hardening, int64 count wrap, zlib escape (follow-up issue), site-wide budget (comment on #107/#108).
Full suites at c7bd8ce: core+pure 1110 passed/5 skipped; QGIS 1600 passed (15.3 min).
Merged origin/main d202230 into branch (clean, merge commit 89a6b4d); core+pure 1113/6 skipped (new skip = #141 with-dzg survey absent in this worktree), dock+engine QGIS 214 passed; pushed.
with-dzg now symlinked too (#141 fixed on main): core+pure 1114 passed/5 skipped.
Final fix wave dispatched (sonnet, final-fix-brief.md, base 89a6b4d).
Deployed: profile ns_geo_packed (copy of ns_geo) with nsgeo_qgis -> this worktree (dev_link).
Walkthrough prep: every Sunnyside grid streams by default (n_traces x 0.14/630 ms <= 16 ms up to ~72k traces; Grid1 has 55k), so the visible change is the "Keep the volume in memory" figure and the resident status line, not the default status line. Per-grid packed vs dense (nz 216): Grid1 0.1 m 4.8 vs 27.8 MB, 0.05 m 15.3 vs 111.1 MB.
Final fix wave DONE at 7a57676 (core+pure 1115/5; dock 149; F1/F3 tests confirmed failing on mutants, restored).
Final fix wave: scoped re-review dispatched (opus, review-89a6b4d..7a57676.diff); full QGIS tier on 7a57676 running.
Final fix wave re-review (opus): all four items ADDRESSED (F1 test fails without the call; F3 fails without the try/except; F4 float_counts fails with an unsafe cast), no new Critical/Important.
Final: parked — slices_dock.py:1068 "they agree whenever the engine holds no lines" overclaims (_apply_resolution refreshes only the checkbox) — Ruling: docstring-only, no behaviour; fix with any walkthrough follow-up commit — costs a misleading sentence until then.
Final: parked — cube.py:190-191 "can differ by one ulp" understates (measured up to ~10 ulp on a 181-level single-column window) — Ruling: docstring-only; reword to "the last few bits" with any walkthrough follow-up — costs an imprecise comment.
Final: parked — _update_resident_check_label docstring omits prepare() as a caller — Ruling: docstring-only, same follow-up.
Final: parked (out of scope) — prepare()'s refusal path clears engine lines but does not refresh the checkbox (rare: preset edited in place to carry the transform, then inclusion change) — Ruling: rare, self-corrects on next refresh; note for M18 cleanup.
Full suites at 7a57676: core+pure 1115/5, QGIS 1603, ruff+mypy clean. README In-progress row updated (walkthrough next).
Walkthrough published: https://claude.ai/artifact/Nkbu7L3jmBdntwQSYPK4MA (db collection results, empty at publish; 12 checks A1-E2). Awaiting user's walkthrough — HUMAN GATE before any merge.
Correction: the walkthrough has 11 checks (A1, B1-B4, C1-C3, D1, E1, E2), not 12.
Walkthrough 2026-11-11 (UTC): user marked all 11 checks PASS, no notes, no comment threads. HUMAN GATE PASSED.
Parked docstrings (ledger lines 70-72) fixed in a docs-only commit; ruff clean, test_slices_cube 28 passed. Next: finishing-a-development-branch (merge asks user).
Finish: user chose 'create a pull request and if ci passes, merge it'. Pre-merge suites at 27cecb9: core+pure 1115/5, QGIS 1603, ruff+mypy clean. README row moved to Done; In progress lists #111 and #107/#108; Next item 1 trimmed. Ledger copied to docs/superpowers/sdd/2026-11-10-nsgeo-packed-cube/.
