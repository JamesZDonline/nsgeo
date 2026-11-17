# SDD ledger — plan: docs/superpowers/plans/2026-11-13-nsgeo-step-edges.md

Spec: docs/superpowers/specs/2026-11-13-nsgeo-step-edges-design.md (binding).
Worktree: .worktrees/nsgeo-step-edges, branch nsgeo-step-edges.
Plan approved by the user 2026-11-13 ("build it"). Execution: subagent-driven (user's brief).
Model tiers (memory): implementers sonnet, task reviews and re-reviews opus, quick fixes haiku; final review opus.
Baseline before Task 1 (processing/schema/project core tests): 421 passed, 4 skipped.

## Pre-flight scan

| tasks | shared file / interface | found |
|---|---|---|
| T1→T2, T1→T5 | `real_radargram(path)` in tests/real_data.py | consistent |
| T1 / T2 | test_steps_migration.py vs migration.py using `refuse_non_finite` with its existing message | consistent (test matches "not finite") |
| T2 / T3 | _util.py, background.py, bandpass.py, gain.py, test_steps_* | sequential edits to different functions; no contradiction |
| T3→T4 | `param_problem` reasons ("must be > 0.0", "must be a whole number", "must be one of [...]", "must be <= 1.0") used verbatim in T4's pinned notes | consistent |
| T3 / T5 | test_schema.py bounded set (T3 adds alpha, exponent; T5 adds trace_stack.window_traces) | consistent |
| T2→T5 | `running_mean` finite-skipping; window 1 returns copy | consistent with T5's NaN and identity tests |
| T2→T4 | Review Focus 2 runs a repaired preset on a random radargram (not all-zero) | consistent with T2's all-zero refusal |
| T1 self | Step 3 "at least the focus assertions must fail" at 0.6v | ambiguous: see ruling R1 |
| T2 self | tests vs implementation | consistent (Review Focus 5 NaN inside the 45 ns cutoff) |
| T3 self | one-sample message cases ("respectively" mapped 3 cases to 2 messages) | fixed in plan text, ruling R2 |
| T4 self | notes vs param_problem; QGIS summary for n>1 | consistent |
| T5 self | "window longer than the line averages the whole line" | FALSE for running_mean's edge rule: ruling R3 |

Rulings:
- Ruling R1: T1 Step 3's sabotage check passes when the parametrized test fails for both diffractions at 0.6v (any assertion) — focus(0.6v) on FILE__033 is 0.047, above the 0.04 literal, so the literal alone cannot be what fails — costs nothing if wrong (a check, not a test).
- Ruling R2: T3 one-sample tests: dewow 0.1 → "is shorter than one sample"; dewow 0.2 and AGC 0.2 → "is one sample at this line's 0.217 ns sampling; use 0.33 ns or more." Plan text corrected — the "respectively" mapped three cases onto two messages — none.
- Ruling R3: spec §6 claimed a window longer than the line averages the whole line; with the shrinking-edge rule (w capped at n, window [i-n//2, i-n//2+n)) it is the whole line only mid-line. Corrected spec §6 and T5's test to "capped at the line's length: window 10000 == window n_traces" — a factual correction, not a behaviour change — if wrong, one test.

## Tasks
- Task 1: dispatched (BASE 97eec8b, implementer sonnet)
- Ruling R4: Task 1's measured focus(v) (FILE__033 0.0794, FILE__032 0.0472) is right; the brief's 0.075/0.050 were the controller misreading the x0.9 column of its own velocity scan. Spec §7.2 and plan T1 numbers corrected (doc commit after b2001f1). Thresholds unchanged and still hold (032: 0.047 > 0.04, ≥ 2×0.0203) — if wrong, nothing: the test asserts thresholds, not these numbers.
- Task 1: complete (commits 97eec8b..b2001f1, review clean). Parked minors for the final fix wave: (m1) record measured values/margins beside the #125 assertions (032 focus 0.047 vs 0.04 floor; 033 at 0.6v 3% under the 2x bar); (m2) real_radargram skip message should name the survey folder, not just path.name; (m3) third copy of the DZT→Radargram load (real_lines.py, test_real_files.py) — out of scope.
- Task 2: dispatched (BASE ab466c0, implementer opus — running_mean accuracy/speed is judgment work)
- Ruling R5: Task 2 speed — background_sliding 200 went 14→30 ms (2.3x), dewow 14→25 ms; spec §4.1a makes speed a measurement with a ~100 ms aim, accuracy required. Accepted — if wrong, a perf follow-up, no correctness cost.
- Ruling R6: Task 2 SVD checks non-finite after its n=0 early return (0 components is the identity, so a bad sample stays bad, per decision 2) — accepted.
- Task 2: complete (commits ab466c0..432d735, review clean). Parked minors for the final fix wave: (m4) running_mean docstring overstates accuracy (three-tier dynamic range leaves ~eps² of the running total; 1.9e-13 on int32-scale tiers); (m5) test reference loop in test_processing_base.py:214-223 doesn't cap w at n; (m6) reference comparison covers only odd windows inside n — add even windows and window > n with bad samples; (m7) _util.py:43 overflow comment overclaims; (m8) `virtual` buffer reused for three quantities in two-sum; (m9) FILE__007-with-one-bad-sample setup repeated across four test files.
- Task 3: dispatched (BASE 432d735, implementer sonnet)
- Task 3: controller ran the full core suite on 01535a4 after the implementer's late bool tests: 1325 passed, 4 skipped.
- Task 3: review 1 → Needs fixes (1 Important: param_problem returns None for curve points that are not pairs / not iterable; build_step then fails inside the constructor without naming the setting, and Task 4's repair relies on param_problem).
- Task 3: minor (deferred): curve messages append the unit after the whole list ("got [[0.0, 0.0]] dB", base.py:405).
- Task 3: minor (deferred): dewow help text still says "must exceed one sample interval" (dewow.py:35) — user-facing, fix in final wave.
- Task 3: minor (deferred): ParamSpec(min_exclusive=True, min=None) silently ignored — __post_init__ could refuse.
- Task 3: minor (deferred): _REFUSED parametrisation has no ids (test_schema.py:316).
- Task 3: minor (deferred, plan-mandated): test_steps_bandpass.py:180 hard-codes 1024 and 0.21653e-9.
- Ruling R7 (plan-mandated minor): window_samples' ceil(150*dt) picks up FP error at some two-decimal dt (0.34 quotes 0.52, 0.51 accepted) — the quoted value is still accepted and FILE__007 is unaffected; fix in the final wave by ceiling a value rounded to ~9 decimals — costs one-cent-of-a-ns overstatement if never fixed.
- Ruling R8 (plan-mandated minor): bandpass quotes df with .2f (4.51 vs 4.51005) — accepted as is; a band exactly the quoted width can miss a bin only in a vanishing range of Low — negligible.
- Task 3: fix round 1/5 (1 addressed, 1 open — new breakage: dict/set points make param_problem raise KeyError/TypeError at base.py:322 instead of returning a reason; commits 01535a4..83898df)
- Task 3: minor (deferred): test_curve_points_that_are_not_pairs... asserts only "is not None", not the phrase.
- Task 3: minor (deferred, out of scope): dict points with int keys pass validation but build the wrong curve (not JSON-reachable); a generator is consumed by param_problem; scalar curve value message "got 5 dB".
- Task 3: fix round 2/5 (1 addressed + folded minor addressed, 0 open; commits 83898df..4d4ccc0)
- Task 3: minor (deferred): _validate_params appends the unit after the whole value on curve shape refusals ("got None dB", base.py:410).
- Task 3: complete (commits 432d735..4d4ccc0, review clean after 2 fix rounds)
- Task 4: dispatched (BASE 4d4ccc0, implementer sonnet)
- Ruling R9: Task 4 constructor-refusal note text '<where>: <Title> is removed. It could not be built: <exc>. Add it again with the settings you want.' accepted (brief gave none) — wording only.
- Task 4: review 1 → spec ❌ (2 partial deviations: removed-step notes name only the first refused/missing setting, against spec §5 "naming all of its refused settings"; a step already disabled in the file gets "stays on"/"is turned off" wording that ignores enabled:false) — quality Approved. Fix round 1 carries both plus minor 3 (note appended before the test-build → possible double note) and minor 6 (weak constructor-note assertion), same code.
- Task 4: minor (deferred): DRY — unknown-setting / missing-required checks copy _validate_params text (project.py ~111-120 vs base.py 395-398).
- Task 4: minor (deferred): note built by s.replace("Its ", f"{title}'s ") — fragile; `name in _STAYS_ON` tested three times.
- Task 4: minor (deferred): test gaps — preset notes checked by prefix only; n>1 plugin summary untested; Warning level not asserted; misnamed test_build_step_still_works_for_a_clean_stack; test_project_repair imports a private helper from tests.test_schema.
- Task 4: minor (deferred): each step built twice at load (harmless).
- Task 4: fix round 1/5 (2 spec gaps + 2 folded minors addressed, 0 open; commits 348649f..6b282de)
- Task 4: minor (deferred): reset-then-constructor-refusal note says only "It could not be built: x" and drops the refused setting's sentence.
- Task 4: minor (deferred): "(already off) had settings reset" is plural for one setting.
- Task 4: minor (deferred, spec gap): a removed step's note names only refused/missing settings, not the valid ones it held (spec §5 "records what it held, so the user can re-add it"); constructor-refusal note records nothing it held.
- Task 4: minor (deferred, doc): spec §5 "Every note ends by telling the user to check the step and turn it back on" is untrue for removed, Time zero and already-off notes — reword the spec line.
- Task 4: complete (commits 4d4ccc0..6b282de, review clean after 1 fix round)
- Task 5: dispatched (BASE 6b282de, implementer sonnet)
- Task 5: complete (commits 6b282de..df6dc4a, review clean). Minors (deferred): even window untested at step level; the two real lines looped instead of parametrized (a missing file hides partial coverage); no apply-level window guard (running_mean's "window must be >= 1" wording); TDD order faked by removing the import (process only).

## Final review (a3ca9f4..df6dc4a, opus) — Ready to merge: With fixes
Important: (I1) removed-step note doesn't record the settings it held (spec §5 "records what it held"); (I2) line notes can't say which grid (FILE__001.DZT repeats 7x in Nashville) — plan-shaped wording; (I3) guide getting-started.md menu list lacks Trace stack, its #40 Known-issues entry describes removed behaviour, README.md:51 step list lacks Trace stack.
Minor promoted into the fix wave: dewow help text; running_mean reference test even windows + window > n (cap the helper); #40 tests at 0.3 ns and AGC 0.1; parametrize the trace-stack real-line test; spec §5 "every note ends…" reword; folded cheap deferred minors m1 (#125 margins comment), m2 (skip message names the survey folder), "had settings reset" plural, reset-then-constructor-refusal note keeps the reset sentence.
- Ruling R10: line notes become "Line <file> (grid <grid_id>): …" when the line has a grid, else "Line <file>: …" — this changes the brief-pinned note strings; the final review showed the old wording can't tell grids apart on the user's own projects — if wrong, wording only.
- Ruling R11: the guide's #40 Known-issues entry is removed (the branch fixes it), not rewritten — a reader no longer meets the problem; the refusal message says what to do — if wrong, a doc paragraph.
- Ruling R12: in the rare reset-then-constructor-refusal note, 'It held …' lists the saved values including the reset one (e.g. Epsilon 0.0) — kept: the note's job is to record exactly what the file held so the step can be re-added — wording only.
- Final fix wave: 88002cb (df6dc4a..88002cb), re-review: all 10 findings ADDRESSED, no new Critical/Important.
- Ruling R13: residual Minor from the fix-wave re-review (guide sentence said a too-short saved window is turned off at open; the repair only applies settings-only rules) corrected by the controller in a doc-only commit, plus the spec §5 example gaining "(grid …)" — doc text only, read by eye, no second fix wave — if wrong, a sentence.
- Parked (pre-existing, out of scope): guide Step 5 says "four groups" while STEP_GROUPS has six (Migration and Amplitude unlisted); note values use repr (strings quoted, curve points as a Python list); spec §5 reworded line unwrapped.

## Walkthrough and merge prep
- Walkthrough 2026-11-16 at f0bd986 (https://claude.ai/artifact/4SSVqVU75JiWUGMkR4JmFG): 9 pass, 0 fail, E1 answered without a status — both gates passed. Results in walkthrough-results.md. E1 follow-up (a refused step's reason only reaches a 6 s message-bar toast) left unfixed at the user's request; offered as an issue.
- origin/main 5f1c105 (#191: 16-/8-bit DZT read as unsigned offset binary, two per-trace header samples zeroed) merged in as f3e48cf, no conflicts. Core suite on f3e48cf: all passed, 4 skipped; real-data #125 and Trace stack tests pass on the corrected samples; ruff clean.
- `nsgeo-hyperbola-tracer` not merged yet: this branch merges first, so the tracer reruns its hand-fit tests.
- Ruling R11 REVERSED 2026-11-16: CI on the PR (and every push since 88002cb, unnoticed) failed one test, `tests/pure/test_release_docs.py::test_known_issues_are_disclosed_in_notes_and_guide`, which pins #22, #23 and #40 in the guide's "Known issues in 0.4.0". 0.4.0 still has #40, so the entry was restored verbatim with one added sentence ("Versions after 0.4.0 refuse such a window and name the shortest one that works."). Lesson: the final verification ran core and the QGIS processing files but not `packages/nsgeo-qgis/tests/pure`; it passes now (301 passed, 1 skipped).
