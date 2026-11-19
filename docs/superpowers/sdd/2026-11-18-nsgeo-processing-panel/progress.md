# SDD ledger — plan: docs/superpowers/plans/2026-11-18-nsgeo-processing-panel.md

Spec: docs/superpowers/specs/2026-11-18-nsgeo-processing-panel-design.md (approved 2026-11-19).
Branch nsgeo-processing-panel, base 85cd441 (origin/main 9691c7b + spec + plan). Coordinator pushes after each task.
Models: implementers sonnet (multi-file), reviews opus (user rule), scoped re-reviews sonnet/opus by size.

## Pre-flight scan

| Pair / task | Shared file or interface | Finding |
|---|---|---|
| T1 × T4 | processing_dock.py: T1 adds `warnings` between list and form + `_check_refusal()` at the end of `rebuild()`; T4 adds `line_label` above the button row + `_update_line_label()` at the end of `rebuild()`; both edit `__init__` layout | No conflict: different layout slots; both tail calls in rebuild |
| T1 × T2 | profile_dock.py: T1 `_show_line` profiles branch, `_on_line_loaded`, `_show_steps_refused`; T2 relay signal in `__init__` + `show_gain_strip` docstring | No conflict |
| T1 × T3 | T1 §3.6 resets view axes from the header on a refusal; T3 `_sync_gain_strip` hides when `input_axis(row)` is None | No conflict (input_axis falls back to source on a refusal, logged) |
| T2 × T3 | T2 produces `DB_LIMIT`, `reset_requested`, `ProfileDock.gain_reset_requested`; T3 consumes `gain_reset_requested`, real test needs T2's clamp | Consistent names. T3 snap-back test feeds 130 dB via `set_points` (T2 clamps only gesture writes) — consistent |
| T1/T3/T4 guide | docs/guide/getting-started.md: three different paragraphs | No conflict |
| T2/T3 tests | test_plugin_gain_strip.py shared | Additive |
| T1/T4 tests | test_plugin_processing_dock.py, test_plugin_profile_dock.py shared | Additive |
| T1 self | core tests vs StepRefused(message, index, title); titles "Dewow"/"Bandpass" verified in code | Consistent (spec §3.2 order fixed to match, 85cd441) |
| T2 self | caption large-font test asserts middle None at 16 pt | Font-dependent across CI images → Ruling 1 |
| T3 self | slot-exception tests call slots directly; `_resync_gain_strip` needs the current key to get past its key filter | Consistent; note in dispatch |
| T4 self | #48, `_clear`, close-site tests are guards (pass on main) with mutation checks | Consistent with Global Constraints' guard rule |

Ruling 1: T2's large-font caption test must assert its own precondition (measured lo+dB+hi widths exceed width-4 at the chosen size) before asserting the middle is None; pick a size where that holds — the plan's "16 pt" is a suggestion — CI's QGIS 4.2 image has different fonts, so an unconditioned assertion could flake. Cost if wrong: one test edit.

## Tasks
Task 1: dispatched (BASE 85cd441, implementer sonnet a27920482943e1a55)
Task 1: implementer DONE (a2bab7b f8521ea 362bb5d 1677829; pushed). Note: full core+pure with real data linked takes ~36 min here. Reviewer opus a475ce989fde96f7e on review-85cd441..1677829.diff
Session restarted 2026-11-19 mid-review; branch CI on 1677829 passed; Task 1 reviewer resumed via SendMessage.
Task 1 review (opus): Needs fixes — Important: width guard test vacuous (dock never shown). Minors 1–6.
Ruling 2: Minor 3 (`_check_refusal` body only partly guarded on a slot path) enters the loop as Important — it conflicts with the Global Constraint "every Qt slot and override guards its own body" — cost if wrong: a few lines of try/except.
Ruling 3: Minor 1 (guide says the profile replaces the last picture whenever steps can't run) enters the loop — it contradicts spec §3.6 (a bad edit on the open line keeps the last picture), a user-facing inaccuracy in a deliverable — cost if wrong: one sentence.
Task 1: minor (deferred): two places write each row's text/tooltip (rebuild + _check_refusal) — row_label/resolved_velocity called twice per row
Task 1: minor (deferred): preview message recomputes line_label instead of passing _show_line's label; fixture labels equal stems so the test can't tell them apart
Task 1: minor (deferred): the add-a-full-stop branch is unpinned (bandpass Nyquist note not asserted exactly)
Task 1: minor (deferred): small test gaps — cleared colour should assert ForegroundRole is None; plain-ValueError test lacks match=; samples-arrive test reads private _lines_by_key
Task 1: minor (deferred): REFUSAL_COLOUR used on every palette (spec says light palette; dark left to builder)
Task 1: fix round 1 dispatched (bbf562c 61231e2 2a4ad48, pushed); re-review opus a59b1f0bec15570db on review-1677829..2a4ad48.diff
Task 1: fix round 1/5 (3 addressed, 1 new open — shown dock never cleaned up: focused runs segfault (exit 139); commits 1677829..2a4ad48)
Ruling 4: the width test's docstring overclaim (says wrap OR Ignored; only losing both fails) enters round 2 — it conflicts with the Global Constraint that a guard test names the mutation that makes it fail — cost if wrong: a docstring edit.
Task 1: fix round 2 commits 71555be ac83ef8 (pushed); re-review opus a5990dacf361b6cd2 on review-2a4ad48..ac83ef8.diff
Task 1: fix round 2/5 (2 addressed + cosmetic, 0 open; commits 2a4ad48..ac83ef8)
Task 1: minor (deferred): removing only setWordWrap(True) from WarningsPanel is caught by no test (Ignored policy keeps the width) — wrapping untested as a property
Task 1: complete (commits 85cd441..ac83ef8, review clean after 2 fix rounds)
Task 2: dispatched (BASE ac83ef8, implementer sonnet)
Task 2: implementer sonnet af5c2f879aa1300be
Task 2: implementer DONE_WITH_CONCERNS (6c7ef8d, pushed) — core+pure run unfinished (no core/pure files touched; CI covers); Reset button made compact (8 pt, stylesheet padding) to fit the 28 px margin, hides on a font where it can't fit
Task 2: reviewer opus a94b63cf91461f832 on review-ac83ef8..6c7ef8d.diff
Task 2 review (opus): Needs fixes — Important: (1) caption overprints on ordinary post-drag values (7–8 char :g ends; dB centred in strip not gap; large-font test passes by 0 px); (2) pinned ▼ and the record-end round handle sit partly under Reset (button top at edge+2; presses there go to Reset); (3) guard tests lack docstrings. Minors: vertical clip of caption text; Reset fixed 8 pt + hide-when-short; touched mouse overrides unguarded; `_limited` unreachable through the widget.
Ruling 5: caption — range ends snap to whole dB (floor/ceil) before the ±120 cap; "dB" centred in the gap between the numbers and dropped when it doesn't fit there; if low+high alone don't fit, the caption font shrinks until they do; draw with TextDontClip (Minor 1 folded in: spec §4.3 "digits are never cut") — cost if wrong: caption code only.
Ruling 6: Reset placement — off-record triangles draw inward (tip on the edge, body inside the record); Reset's top sits at least HANDLE_RADIUS + 2 px below the record's bottom edge and its height is capped to what remains of the band rather than hidden (hidden only if under 14 px remain); test asserts its precondition (fits) before visibility (Minor 2 folded in) — spec §4.4 puts Reset in the bottom margin; it must not steal presses meant for a handle — cost if wrong: a few px of layout.
Ruling 7: Minor 3 (edited mouseMoveEvent / mouseDoubleClickEvent unguarded) enters the loop — conflicts with the Global Constraint that every override guards its own body — cost if wrong: two try/except blocks.
Task 2: minor (deferred): `_limited` unreachable through the widget (backstop) — wants a comment saying so
Task 2: fix round 1 commit 8d5ad58 (pushed). Core+pure (on 6c7ef8d): 1961 passed, 1 failed — test_no_orphan_signals: gain_reset_requested has no consumer yet.
Ruling 8: leave gain_reset_requested unconsumed until Task 3 connects it (next task); Task 3's dispatch must run packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py and see it pass. Branch CI will be red on the Task 2 pushes for that one pure test — cost if wrong: a red CI run between two tasks.
Task 2: fix round 1 re-review opus a630b391bc3cd492f on review-6c7ef8d..8d5ad58.diff
Task 2: fix round 1/5 (4 addressed, 0 open; commits 6c7ef8d..8d5ad58)
Task 2: minor (deferred): no test pins off-record handles sitting inside the record (gain_strip.py:372 revert passes all tests)
Task 2: minor (deferred): pixel-sized fonts (pointSizeF −1) skip the caption shrink loop
Task 2: minor (deferred): caption height not shrunk — fonts above ~16 pt cut at the widget's top edge (spec §4.3 "digits never cut" holds horizontally only)
Task 2: minor (deferred): TextDontClip | AlignmentFlag on QGIS 4.2 untested locally — a type error would be swallowed by paint's except; check CI 4.2 / walkthrough
Task 2: minor (deferred): mousePressEvent / mouseReleaseEvent unguarded (not edited, but press calls the changed _drawn)
Task 2: minor (deferred): module docstring says the buttons() check is at the top of mouseMoveEvent; now at the top of _move
Task 2: complete (commits ac83ef8..8d5ad58, review clean after 1 fix round)
Task 3: dispatched (BASE 8d5ad58, implementer sonnet)
Task 3: implementer sonnet a9a09f09e70e44fdc
Task 3: implementer DONE (774d6e9, pushed) — core not run (no core file touched; CI covers); extra _replace_gain_step helper restores _gain_step when replace_step raises; real test uses 118 dB point; Reset question defaults to No
CI 8d5ad58: all jobs fail only on test_no_orphan_signals (known, Ruling 8); QGIS 3.44 and 4.2: 1 failed (that one), 3153 passed
Task 3: reviewer opus ad77b518b981c56a2 on review-8d5ad58..774d6e9.diff
Task 3 review (opus): Needs fixes — Important: test_reset_behind_time_zero_is_on_the_time_zero_clock passes on the base with no Reset (curve already starts at t0); report's RED claim wrong.
Ruling 9: Minor 1 (plan-mandated: _sync_gain_strip's input_axis(row) evaluates the stack, logging a Warning on every drag move when a step above refuses) enters the loop — the clock-known check becomes "samples loaded, or no enabled time_zero above the row", computed without evaluating the stack — spec §4.4's intent is "hide while the clock is unknown", not "evaluate the stack" — cost if wrong: one helper.
Ruling 10: Minor 4 (real-data test lacks a guard docstring; named mutation too loose) and Minor 5 (test_reset_answered_no_changes_nothing passes on the base) enter the loop — they conflict with the Global Constraints on guard tests and on bug tests failing first — cost if wrong: test edits.
Task 3: minor (deferred): Reset doesn't re-check the identity barrier after the modal question (theoretical window)
Task 3: minor (deferred): _replace_gain_step only tested through case order in the exception test; restoring `old` would be wrong if replace_step raised after mutating
Task 3: minor (deferred): test tidiness — `if hasattr(bar, "clearWidgets")` always true (clear unconditionally); `_curve_row_ctx` unused params; real-data test deleteLater()s a plugin-owned dock before unload()
Task 3: minor (deferred): no test shows the flat curve on the strip after Reset; none drives the release-path snap-back
Task 3: minor (deferred): _on_gain_reset repeats _on_gain_points' target lookup + identity barrier (~10 lines) — a _gain_target() helper
Task 3: fix round 1 commit 8702fae (pushed; tree clean, format clean after the implementer's accidental mass format was reverted)
Task 3: fix round 1 re-review opus a73f8b2d864c1d2c4 on review-774d6e9..8702fae.diff
Task 3: fix round 1/5 (4 addressed, 0 open; commits 774d6e9..8702fae)
Task 3: minor (deferred): real-data guard docstring says `_limited` alone is pinned by other strip tests — false (removing only `_limited` passes all 77; it is a near-equivalent backstop)
Task 3: minor (deferred): a drag write behind a refusing step toasts the refusal on every move (current_radargram → error → plugin.message); pre-existing on main; the new test's name "adds no log noise per write" covers only the input_axis message
Task 3: complete (commits 8d5ad58..8702fae, review clean after 1 fix round)
Task 4: dispatched (BASE 8702fae, implementer sonnet)
Task 4: implementer sonnet a581bfcd86af9d738
Task 4: implementer DONE_WITH_CONCERNS (c6b16ad 3332c87, pushed) — core+pure stopped at 54% (no core/pure files touched); label's Ignored policy not separately mutated; close-site guard not mutated
Task 4: reviewer opus a12e8fa98bf305bf2 on review-8702fae..3332c87.diff
Task 4 review (opus): Needs fixes — Important (plan-mandated): line label goes stale on move_lines / Edit lines rename (only rebuild + preview_changed update it; lines_changed not connected).
Ruling 11: connect session.lines_changed to the guarded _update_line_label (spec §7's cue must name the line's current name and grid; the plan's trigger list was incomplete) — cost if wrong: one connection + test.
Ruling 12: Minor 2 (width test docstring claims word wrap is pinned; it isn't) and Minor 5b (_on_rows_moved, changed by this task, unguarded) enter the loop — Global Constraints on guard docstrings and slot guards — cost if wrong: small.
Task 4: minor (deferred): a hovered cut gets no preview suffix (processing_dock.py `not is_cut_key(preview)`), undocumented — Ruling: leave for now; spec §7 speaks of a previewed line; record for the user at the walkthrough
Task 4: minor (deferred): escaping pinned for the working name only (grid id, previewed name unpinned)
Task 4: minor (deferred): #33 test doesn't check the label right after the multi-select
Task 4: minor (deferred): #48 pin landed in the fix commit, not the test commit; core+pure run not completed (test_release_docs passes)
Task 4: minor (deferred): module function line_label and self.line_label share a name
Task 4: fix round 1 commit 9aa4b32 (pushed)
Task 4: fix round 1 re-review opus a5c7f41fd6ee4feb8 on review-3332c87..9aa4b32.diff. #21 question put to the user (recommend narrow split as Task 5: step_inputs.py).
Task 4: fix round 1/5 (3 addressed, 0 open; commits 3332c87..9aa4b32)
Task 4: minor (deferred): width-test docstring missing an "or" between clauses
Task 4: complete (commits 8702fae..9aa4b32, review clean after 1 fix round)
User chose the #21 split (2026-11-19). Plan Task 5 added (98afdb7). Task 5: dispatched (BASE 98afdb7, implementer sonnet)
Task 5: implementer sonnet a000b8979ec68ed9e
Task 5: implementer DONE (bb1f8ff, pushed) — core+pure 1962 passed; real_data 46; time_axis now calls module input_axis, not the dock method
Task 5: reviewer opus ad946654b01b94287 on review-98afdb7..bb1f8ff.diff. CI 9aa4b32 (Task 4 head) success.
Task 5: minor (deferred): step_inputs.py docstring says "plain functions over a SiteSession" but clock_unknown takes a StepStack
Task 5: complete (commits 98afdb7..bb1f8ff, review clean)
Final review: opus a74ea6c8f9f98590c on review-9691c7b..bb1f8ff.diff
Final review (opus): With fixes. Important 1: #13 not closed across Time zero/cutoff — the profile re-renders with the old index on move_step, declines (toast naming a step the user didn't touch), and the dock never re-aims (↑/↓ had it on main too). Important 2: _check_refusal's stack.result() makes every edit in the Difference view cost ~3 s on FILE__007 with expensive steps below (28–44 ms without). Must-fix minor: T3 real-data guard docstring. Minors: strip on the wrong clock behind a refusal above the curve (drag writes off by ~0.48 ns on FILE__007; Reset writes raw-clock identity); preview suffix may wrap and jump the panel; note sentence false in Difference/cutoff views; doubled brackets.
Ruling 13: Important 1 — ProfileDock tracks the differenced step object; current_radargram follows it to its new index by identity after a move; when it is not found (replaced in place or removed) the index stands as today — fixes drag and ↑/↓ without coupling the docks — cost if wrong: Difference could follow a step the user meant to leave (only by moving it).
Ruling 14: Important 2 — while Difference is on with a row selected, the refusal check evaluates stack.intermediate(row) (the chain on screen), else result(); _emit_difference re-runs the check; spec §3.3 is amended to say so — a refusal below the differenced step is then noted when Difference goes off — cost if wrong: a refusal below is noted late.
Ruling 15: final-review Minor 1 (strip on the wrong clock behind a refusal above the curve) enters the fix wave — it writes wrong times to the step; hide the strip while processing_dock.refusal() names a row above the curve (no evaluation, fits Ruling 9) — cost if wrong: the strip hides until the refusal is fixed.
Final fix wave: dispatched (BASE bb1f8ff)
Final fix wave: implementer sonnet a75d55d769f2b9308
Final fix wave: DONE (fdd72d6 e190fcf 8e1fe36 ecc42a6, pushed); core not re-run (untouched)
Final fix wave: re-review opus a14794e6fcf51139e on review-bb1f8ff..ecc42a6.diff
Final fix wave re-review (opus): findings 1–4 ADDRESSED (Difference edit cost on FILE__007 now 14–18 ms). New Important in the fix diff: _on_current_row emits step_selected before _emit_difference re-runs the refusal check, so with Difference on, clicking a curve row below a refusing step shows the strip on the wrong clock and a drag writes wrong-clock times (Ruling 15 bypassed).
Ruling 16: residual load-bearing finding — it is a wrong-clock data write the fix wave itself opened, and the reviewer confirmed a one-call fix on a copy; resume the fix-wave implementer for exactly that (check before the emit when Difference is on) plus the reviewer's test, and the coordinator reads the small diff instead of a second review round (no second fix wave) — cost if wrong: an unreviewed ~5-line change, covered by its test and the walkthrough.
Ruling 16 fix 3a065f6 read by the coordinator: check before emit when Difference is on; slot guarded; test RED/GREEN. Final review complete.
Merged origin/main (M17a) as fb93c64: one test-file conflict, both blocks kept; pushed.
Post-merge local QGIS files (processing_dock, profile_dock, gain_strip, difference_presets, slices_width, map_link, param_form): 408 passed.
Deployed: profile ns_geo_processing (copy of ns_geo) → dev_link to this worktree. Walk copy ~/nsgeo-processing-walk (+ .pristine): campus site; FILE__007 gain curve points 3/4 set to ±112 dB; FILE__008 dewow 0.2 ns.
Walkthrough: https://claude.ai/artifact/KD1UtkmHy21zKRNuWVi41W (db collection `results`, W1–W12). Awaiting the user.
Walkthrough results (2026-11-19, on fb93c64): W1–W12 all pass, no notes; W11 confirms the #33 cue (multi-select opens nothing, the step lands on the named line). Record: walkthrough-results.md. CI fb93c64 success.
Ledger retired to docs/superpowers/sdd/2026-11-18-nsgeo-processing-panel (review diffs and plan-path left out).
