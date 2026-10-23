# SDD ledger — plan: docs/superpowers/plans/2026-10-22-nsgeo-display-gain.md

Spec: docs/superpowers/specs/2026-10-21-nsgeo-display-gain-design.md (reachable; binding).
User decisions at start (2026-10-22): spec call 1 confirmed ("sounds good. start the build").
Worktree .worktrees/display-gain-design, branch docs/display-gain-design, start head 61119b4 (main 87fcaa3 merged in).
Setup: .venv (nsgeo-core[dev], ruff 0.17.1, mypy 2.4.0, pytest 9.1.1) and .venv-qgis (--system-site-packages, pytest 9.1.1) built; real DZT files symlinked (10 .DZT); data/local/README.md restored after ln -sf clobbered it.
Baseline: core+pure 606 passed / 3 skipped (all three are test_schema "required parameters by design"; no real-data skip); ruff clean; mypy clean (33 files); qgis 777 passed, 0 skipped (6m23s).

## Pre-flight scan

| Rows | Produces → consumes / text checked | Found |
|---|---|---|
| T1 → T2 | `result_bypassing(*indices)` + memo kept on replace_step of a bypassed index → `_scale_reference`; T2 test 3 (reference identity across a curve edit) relies on the memo | consistent |
| T1 → T3 | `row_envelope(data, percentile, max_traces=2048)` → `_push_headroom` uses `row_envelope(rg.data, self.percentile)` | consistent |
| T2 ↔ T3 | both edit profile_dock.py; T3 reads `dock.image.limit`/`.rg`, calls `_push_headroom` at end of `_render` after `_show_cutoff`; T3 tests rely on T2's fixed limit (test 9) | consistent; T3 tests live in test_plugin_gain_strip.py but refer to FLAT/DEEP "as in Task 2" (defined in test_plugin_profile_dock.py) — see Ruling P3 |
| T1 self | stack tests vs memo rules: remove(2)/move(0,2) keep index 1 valid; replace-other drops {1}; LRU test sequence consistent; NaN test row values [1,0,1] consistent | `assert_array_equal` against np.percentile may break if all rows go through nanpercentile — Ruling P2 |
| T2 self | tests 1/6 assert identity with `stack.result()` — holds because `_scale_reference` returns the cached result object when no enabled curve; test 8 parametrised curve/no curve consistent with call 11; no existing test pins the limit under the cutoff (grep'd) | consistent |
| T3 self | strip geometry at W=96: x(0)=48, x(±2)=78.4/17.6, x(±10)=86/10; probes x=82 row150 (red) / row50 (bg) clear of curve (59.9 / 36.1); test 9 ratio 10^(30/20) at last row (t≈99.55 > 99) | consistent |
| Global | "no gain curve renders exactly as today except while cutoff row selected" vs call 11 | consistent |

- Ruling P1: execute subagent-driven — it was the recommendation and the user said "start the build" without picking — costs extra review seats if they wanted native.
- Ruling P2: row_envelope must use plain `np.percentile` when every sample is finite (nan-path only when needed), so the plan's exact-equality tests hold — if wrong, a test fails loudly at RED/GREEN, no silent cost.
- Ruling P3: Task 3 defines its own FLAT/DEEP constants in test_plugin_gain_strip.py with Task 2's values — trivial duplication of two literals across test files; cost if wrong: none.
- Ruling P4: keep branch name `docs/display-gain-design` though it now carries code — renaming means deleting a pushed remote branch; cost: a slightly misleading branch name on the PR.

Models: implementers sonnet (T1, T3), sonnet (T2, escalate to opus if it struggles); task reviews opus; final review opus.

## Progress
Task 1: dispatched (implementer sonnet, BASE 61119b4)
Task 1: implementer DONE_WITH_CONCERNS (ea5337d; core+pure 634/3). Push failed in sandbox (DNS); controller pushed. Implementer added a row_envelope line to packages/nsgeo-core/README.md (test_public_api requires public names documented) — accepted as necessary. Review dispatched (opus) on 61119b4..ea5337d.
Task 1: review (opus) — spec ✅, quality Approved; reviewer confirmed real-data row_envelope tests 10 passed / 0 skipped.
Task 1: minor (deferred): row_envelope on a zero-trace array raises IndexError instead of returning zeros (render.py:342-343).
Task 1: minor (deferred): test_row_envelope_validates_its_arguments' 100.5 case passes on numpy's own ValueError — add match= so all three cases bite (test_render.py:433-436).
Task 1: minor (deferred): result_bypassing duplicate indices untested (stack.py:164-198).
Task 1: minor (deferred): docstring hard-codes "two" beside _BYPASS_MEMO_SIZE (stack.py:57/~156).
Task 1: complete (commits 61119b4..ea5337d, review clean)
Task 2: dispatched (implementer sonnet, BASE ea5337d)
Task 2: implementer DONE (e891b73; qgis 791, core+pure 634/3; no existing test broke; difference-view test passed pre-change)
Task 2: review dispatched (opus) on ea5337d..e891b73
Task 2: review (opus) — spec ✅; quality Needs fixes: 1 Important — test_two_gain_curves_are_both_left_out_of_the_scale passes when only the last curve is bypassed (row 0 is FLAT = 0 dB no-op); fix: give row 0 a real gain.
Task 2: minor (deferred): _scale_reference's ValueError fallback untested (profile_dock.py:829-831).
Task 2: minor (deferred): real-data test recomputes intermediate(2).t0_ns instead of reusing t0 (test_plugin_profile_dock.py:1746).
Task 2: minor (deferred): tooltip test checks a substring, not the exact copy (test_plugin_profile_dock.py:1726).
Task 2: minor (deferred): module docstring "(spec 3, calls 1 and 4)" should be §3, and call 4 attaches to the wrong sentence (profile_dock.py:25).
Task 2: fix round 1 implemented (f77d7f1; sabotage run fails, restored 89 passed); scoped re-review dispatched (opus)
Task 2: fix round 1/5 (1 addressed, 0 open — two-curves test now discriminates; commits e891b73..f77d7f1)
Task 2: complete (commits ea5337d..f77d7f1, review clean)
Task 3: dispatched (implementer sonnet, BASE f77d7f1)
Task 3: implementer DONE (523d7f4; qgis 805, core+pure 634/3; render 53.2 ms on 6301-trace tiled real line, budget ~120). Notes: band/trace/limits painted unantialiased (probe tests); extra guards (non-positive limit = no headroom, mismatched trace ignored, non-finite zeroed).
Task 3: review dispatched (opus) on f77d7f1..523d7f4
Task 3: review (opus) — spec ✅, quality Approved.
Task 3: minor (deferred): 1 px double-painted seam at the limit columns — fractional clip rects overlap (gain_strip.py:340-341); round xl/xr.
Task 3: minor (deferred, plan-mandated call site): each curve drag move computes the envelope twice (_render push + show_gain_strip echo push), ~14 ms extra at 512x6301; within budget.
Task 3: minor (deferred): band polygon rebuilt on every repaint incl. cursor moves (gain_strip.py:337) — cheap at 512 rows.
Task 3: minor (deferred): untested — _exit_preview's _strip_was_visible push (profile_dock.py:654-656); the three extra guards; test 10 uses FLAT so can't tell displayed vs bypassed trace column.
Task 3: minor (deferred): Headroom is frozen dataclass holding ndarray — __eq__/__hash__ would raise; eq=False removes the trap (gain_strip.py:121-122).
Task 3: minor (deferred): nits — draw: Any could be Callable; x_of_amplitude relies on assert; report wrongly calls _push_trace self-guarded.
Task 3: complete (commits f77d7f1..523d7f4, review clean)
Final review: dispatched (opus) on 61119b4..523d7f4 (code range; 87fcaa3..61119b4 is the spec+plan docs)
Final review (opus): Ready to merge "With fixes". 1 Important: stale band/trace from the previous line on the strip while the next line loads (profile_dock.py:966-967, :458, :573). Minors 2-7. End-to-end drag timing 67.3 ms avg / 72.0 worst on 463x6301 (budget ~120).
- Ruling F1: fix wave = Important 1 + Minors 3, 4, 5, 6 + the two cosmetic deferrals (zero-trace guard in row_envelope; profile_dock docstring §3 citation) — reviewer's triage; cost if wrong: a few lines of extra churn.
- Ruling F2: Minor 6 — the plan's verbatim guide copy dropped spec §7's "works without AGC"; spec wins, add the clause — cost: one sentence the user may want reworded.
- Ruling F3: Minor 5 — keep the plan's +6 dB real-data test and add a separate real-data test raising only the deep point with a shallow-row pixel check (spec §8.2) — cost: one more real-data test (~seconds).
- Ruling F4: Minor 2 (cutoff drag now moves brightness, a consequence of spec call 11) goes to the walkthrough as an explicit check for the user to judge, not into the fix wave — cost if wrong: one walkthrough round if the user dislikes it.
- Ruling F5: Minor 7 (limit recomputed per drag move, 4.5 ms) and every other deferred minor the reviewer marked "can wait" stay deferred — within budget / cosmetic.
Final fix wave: dispatched (sonnet) from 523d7f4
Final fix wave: DONE (1b0ed5b; qgis 809, core+pure 635/3; sabotage proofs for items 1-3 and zero-trace; item 1 reproduced at dock level). Scoped re-review dispatched (opus).
Final fix wave: scoped re-review (opus) — all 6 findings ADDRESSED, no new breakage; reviewer's plugin-level probe confirms the stale-band fix through the assembled plugin.
Final fix wave: minor (deferred): the _show_line clear and the _push_headroom clear cover each other in test :1088 — deleting either alone stays green (only _clear_view_only's clear is pinned alone).
Out-of-scope from re-review: 1b0ed5b left test_plugin_gain_strip.py failing ruff SIM118 (`k in session.keys()`); the implementer's lint fix sat uncommitted in the working tree. Ruling F6: controller commits that 2-line working-tree change itself (lint-only, already exercised by the full qgis run) rather than dispatching — cost if wrong: none beyond a controller-authored test-helper line.
Final fix wave: lint fix committed ed92b2b (controller, Ruling F6). Verified at ed92b2b by controller: core+pure 635 passed / 3 skipped (schema by design), qgis 809 passed (5m17s), ruff + format + mypy clean. CI run 39892089149 (1b0ed5b) had failed on lint only; CI 39892630292 on ed92b2b running.
Final review: clean after one fix wave. Workspace KEPT (project convention: commit ledger + briefs/reports as the decision record before merge).
Deploy: new QGIS profile ns_geo_gain (cp -a of ns_geo, dev_link.py --profile ns_geo_gain → this worktree). ns_geo untouched (still → .worktrees/help-pages).
Walkthrough (HUMAN GATE, not yet run): https://claude.ai/artifact/KZxAQkht8Jj6EmooyPeAAe (db collection `results`, 24 checks A1–F1; E4 asks the user about Ruling F4). Store verified with one probe write/list/delete.
CI 39892630292 on ed92b2b: success (16 jobs green incl. plugin-qgis 3.44/4.2 and smoke 3.40/3.44/4.2; release job skipped)
Walkthrough round 1 (2026-10-23, build ed92b2b, profile ns_geo_gain): 6 of 24 checks marked, all pass (A1, B1, B2, C1, C2, C3); 18 unmarked incl. E4's question and E1 (the final-review fix). User: "I think we're ready for a pull request/merge". Decision record committed; PR opened; merge awaits the user's explicit go given the unmarked checks.
