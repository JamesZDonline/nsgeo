# SDD ledger — plan: docs/superpowers/plans/2026-10-16-nsgeo-time-cutoff.md

Started 2026-10-21. Branch nsgeo-time-cutoff, worktree .worktrees/nsgeo-time-cutoff.
Spec: none as a file. The plan's "Design (approved in chat, 2026-10-16)" section is the spec; rulings against it are provisional to that extent.
Main merged in before Task 1: 69a50b6 (README-only changes from c4701e8).
Model tiers (user memory): implementers sonnet, reviews and re-reviews opus, quick fixes haiku.

## Pre-flight scan

| Pair / task | Produces → consumes | Finding |
|---|---|---|
| T1 ↔ T2 | none shared; T2 uses VelocityModel (exists) and its own ViewTransform method | no conflict |
| T1 ↔ T3 | T1 time_cutoff, "time" kind, StepStack.result_bypassing → T3 dock bypass render, ParamForm test, seeding | agree on names and signatures |
| T2 ↔ T3 | T2 set_cutoff / cutoff_ns / cutoff_dragged → T3 dock wiring; T2 may add a KNOWN_UNCONSUMED entry that T3 removes | agree; temporary orphan entry is planned on both sides |
| T3 ↔ T4 | T3 head → T4 deploy + walkthrough | no conflict |
| T1 self | 7 step tests match "Expected: 7 passed"; error text "would leave no samples" matches Step 3; test named "...must_be_a_finite_number" asserts only non-number | finding R1 |
| T2 self | pure snap tests match the snap formula; view fixture numbers (t0 -4, dt 0.5, 128 samples, 264-px rect) match the existing fixture | agrees |
| T3 self | Step 8 quotes the README bullet as it read at 6a7f112; main's README rewrite (merged 69a50b6) changed that sentence | finding R2 |
| T3 self | test fixtures named (opened, previewing, fake_iface, answer_modal) exist with the shapes the plan assumes | agrees |

Ruling R1: Task 1's TimeCutoff rejects a non-finite end_ns (NaN/inf) with ValueError matching "finite", and `test_end_ns_is_required_and_must_be_a_finite_number` asserts it — the test's name promises it, the ParamForm already refuses non-finite input, and a NaN from a hand-edited project would otherwise reach `math.ceil` and raise a cryptic "cannot convert float NaN to integer" — cost if wrong: one extra guard no other step has.
Ruling R2: Task 3's README edit goes into main's rewritten sentence ("The steps are time-zero, dewow, bandpass, three gains (...), background removal (...), and amplitude transforms (...)"), adding "a time cutoff you drag on the profile" — the plan's quoted text no longer exists after the merge — cost if wrong: a one-line README rewording.

## Tasks
Task 1: dispatched (BASE 69a50b6, implementer sonnet)
Task 1: implementer DONE_WITH_CONCERNS d5b1f70 (604 passed/3 skipped; extra skip is the required-params skip for time_cutoff, not real data); review dispatched (opus)
Task 1: review Approved (opus): spec ✅, no Critical/Important.
Task 1: minor (deferred): timecutoff.py:175-178 comment misstates what NaN/inf do without the guard (ceil raises ValueError/OverflowError, not a silent no-op).
Task 1: minor (deferred): snapped-boundary test stops at m=511; add m=n_samples on the HS350 axis asserting `is rg` (the value the front end seeds).
Task 1: minor (deferred): no test pins the `.copy()` in TimeCutoff.apply (np.shares_memory).
Task 1: minor (deferred): result_bypassing untested for index 0 with no source, and for bypassing an already-disabled step.
Task 1: minor (deferred): numeric kinds ("float","int","time") hard-coded in base.py:236 and twice in test_schema.py; the defaults-respect-bounds test (test_schema.py:318) skips "time".
Ruling R3: Task 3 makes ParamForm keep a parameter's exact value when its editor text is unchanged from what the form displayed — reviewer showed that the `:g` display (6 significant digits) round-trips 263 of 511 snapped HS350 cutoffs one row late, so tabbing through the cutoff field after a drag would silently move the cut; fixing it in the form (not the step's tolerance) also closes the same latent defect for every other float parameter — cost if wrong: a small ParamForm change outside the plan's listed edits.
Task 1: complete (commits 69a50b6..d5b1f70, review clean)
Task 2: dispatched (BASE d5b1f70, implementer sonnet)
Task 2: implementer DONE aa94550 (pure 606/3, qgis 679; cutoff_dragged added to KNOWN_UNCONSUMED for Task 3 to remove); review dispatched (opus)
Task 2: review Needs fixes (opus): spec ✅; 1 Important (plan-mandated) — in pick mode, hovering the line shows SizeVerCursor though a press there authors a pick.
Ruling R4: the brief's "set SizeVerCursor near the line" is overridden in pick mode — hover shows the pick cursor there, because press precedence (pick wins) is the brief's own rule and a resize cursor over a gesture that writes a pick misleads the user into an unintended data write — cost if wrong: none visible outside pick mode.
Ruling R5: reviewer Minor 1 (a stale grab from a lost release hijacks the next left press and emits cutoff_dragged on its release) is promoted into fix round 1 — it breaks the design's stated rule that a drag can never write silently; the fix is three lines at the top of the left-press branch — cost if wrong: a few lines in the press path.
Task 2: minor (deferred): label clipped when the line is within ~18 px of the image top (setClipRect), i.e. exactly while dragging to "keep one sample" — consider flipping it below the line.
Task 2: minor (deferred): clear() leaves SizeVerCursor set if the line closes while the pointer is on the line (mouseMoveEvent returns early with no transform).
Task 2: minor (deferred): mousePressEvent/mouseReleaseEvent remain unguarded overrides (pre-existing); this task adds logic to both, none of it reachable-raising.
Task 2: minor (deferred): snap_cutoff returns t0_ns for n_samples == 0 (empty axis), breaking "at least one sample"; no pure test.
Task 2: minor (deferred): coverage gaps — press at line y inside the axis margin; Shift-click on the line outside pick mode; line drag with horizontal drift > DRAG_THRESHOLD_PX; _cutoff_y clamp at the top (cutoff below t0).
Task 2: fix round 1 implemented 90d9843 (view file 73 passed); scoped re-review dispatched (opus)
Task 2: fix round 1/5 (2 addressed, 0 open; commits aa94550..90d9843)
Task 2: minor (deferred): after a lost release, the stale line is drawn where it was dragged but a press there is tested against the restored start position (abandon runs before _near_cutoff) — consequence of R5's ordering; walkthrough glance.
Task 2: minor (deferred): Shift-hover over the line still shows SizeVerCursor though Shift-press picks (hover never checks modifiers; pre-existing widget-wide).
Task 2: complete (commits d5b1f70..90d9843, review clean)
Task 3: dispatched (BASE 90d9843, implementer sonnet)
Task 3: implementer DONE d552871 (pure 606/3, qgis 694, real-data test ran; R2, R3 applied; KNOWN_UNCONSUMED entry removed); review dispatched (opus)
Task 3: review Approved (opus): spec ✅, no Critical/Important.
Task 3: minor (deferred): line→form direction of "kept in step" untested (drag, assert form text == f"{end:g}", unedited form.commit() fires no stack_changed) — would pin R3 end to end.
Task 3: minor (deferred): the unchanged-row guard in set_selected_step (one render per drag) is unpinned; deleting profile_dock.py:791 fails nothing.
Task 3: minor (deferred): vacuous assertions — `assert session.dirty` already true from setup (test_plugin_profile_dock.py:1369); `all(...)` over a possibly empty list (test_plugin_param_form.py:557); no-write drag tests can't tell a no-op from a logged crash (assert message_log clean).
Task 3: minor (deferred): real-data test could also pin the seeded cutoff changing nothing after time_zero and row 1 showing the whole zeroed record.
Task 3: minor (deferred): `_cutoff_row(row=None)` parameter never passed; set_selected_step reads `was` before assigning `_selected_row`; close/remove safety rests on dock construction order, undocumented.
Task 3: minor (deferred): with the difference view on, selecting the cutoff row draws the line over the previous row's difference image for one frame before the difference declines.
Task 3: minor (deferred): time_param_name duplicates plugin.py's _curve_param_name except the kind string; R3's `_shown` keeps the pre-commit pair after an echo (harmless).
Task 3: complete (commits 90d9843..d552871, review clean)
Final review: dispatched (opus), range c4701e8..d552871
Final review: With fixes (opus). 3 Important: I1 a grab jumps to the pointer (no offset, no threshold) so a press 4 px off the line + release at the press point writes 8 samples and dirties the session (Review Focus 5; plan defect in Task 2 Step 5); I2 _show_line's no-profiles branch never clears the cutoff, so the working line's cutoff stays drawn and draggable over an unloaded preview/opened line (Review Focus 4; test dodged with loaded lines); I3 Difference view + cutoff selection leaves a stale/misleading image in both orders (Task 3's "one frame" minor was misjudged; also affects time_zero). Minors m1 (disabled cutoff still veils), m2 (press/release unguarded), m3 (typed cutoff before record start, existing error path), m4 (_cutoff_row relies on dock construction order; add is_open guard), m5 ("(needs values)" label). All rulings R1–R5 judged correct.
Ruling R6: the cutoff grab keeps the press-to-line offset and does not move until the pointer passes DRAG_THRESHOLD_PX from the press; within it the start value is restored exactly — the plan's Task 2 Step 5 (pointer-absolute snap, no threshold) is a plan defect that breaks the design's "a click must not dirty the session" — cost if wrong: a 3-px dead zone before the line moves.
Ruling R7: in current_radargram the difference view gets its own try; on its ValueError/IndexError the dock declines the difference and falls through to the cutoff bypass / result path instead of returning None — fixes both orders of I3 and the pre-existing time_zero case — cost if wrong: one render path changes for every step whose difference is undefined.
Ruling R8: the single final fix wave carries I1–I3 plus the reviewer's riders (Task 1 NaN comment, label flip near the image top, cursor reset in clear(), m2 guards on press/release, m4 is_open guard, tightening the vacuous assertions in test_plugin_param_form.py:557 and the no-write drag tests) — all touch the same code as I1–I3 and are cheap; m1, m3, m5 go to the walkthrough as questions — cost if wrong: a slightly larger fix diff.
Final fix wave: dispatched on opus (not sonnet) — there is no second fix wave, residuals go straight to the user, and I3 is a subtle render-ordering change.
Final fix wave: DONE_WITH_CONCERNS b5dca3e, 0981d9d (pure 606/3, qgis 709; flags: duplicate-message suppression beyond R7, preview no longer clears working diff, stateless threshold); scoped re-review dispatched (opus)
Final fix wave: scoped re-review (opus) — I1, I2, I3, riders 1–6 and the R3 pin all ADDRESSED; no new Critical/Important. Implementer's flags judged: duplicate-message suppression correct (cannot hide a distinct error; probed); preview no longer clears the working difference — correct per spec §3.3 but unpinned; stateless threshold sound.
Final: parked — test_plugin_profile_view.py:810 calls monkeypatch.undo() mid-test, which also reverts the autouse modal guard and unraisable hook for the release half — Ruling: real test-hygiene defect, product code unaffected; no second fix wave per process; fix when the branch is next touched (split the test or use monkeypatch.context()) — cost if wrong: that one test's second half runs without the modal/unraisable nets.
Final: parked — preview-with-a-bad-step leaving the working line's difference view on is unpinned — Ruling: behaviour is correct (probed) and matches spec §3.3; add the pin when next touched — cost if wrong: a later regression there goes unnoticed.
Final: parked — R6's stateless ±3 px dead zone means the smallest single-drag move is one 4-px step (~8 samples / 1.7 ns at the dock's default geometry, 2 samples/px); fine moves need zoom or typing — Ruling: acceptable, it is what keeps "released where it started writes nothing" exact; put it to the user as a walkthrough question — cost if wrong: a coarse-feeling drag the walkthrough will surface.
Final verification at 0981d9d (controller, 2026-10-21): core+pure 606 passed / 3 skipped (skips are the three required-param schema skips, no real-data skips); qgis 709 passed (5m17s); boundary 7 passed; ruff + format clean; mypy clean (33 files); tree clean.
Task 4: deployed — new QGIS profile ns_geo_cutoff = copy of ns_geo (nsgeo_qgis=true) with plugins/nsgeo_qgis -> this worktree; ns_geo still -> help-pages, ns_geo_m12 untouched. Headless smoke (qgis --profile ns_geo_cutoff --code): plugin loaded from the profile symlink, time_cutoff registered with kind "time", Add menu lists it, ProfileDock.set_selected_step present.
Task 4: walkthrough page published https://claude.ai/artifact/4SK9JoZ6EzbLxRrRaAT8DA (db collection `results`, 24 checks A1–F3; empty store read back OK). HUMAN GATE — awaiting the user's results. Workspace kept (decision record convention) until committed.
Walkthrough round 1 (user, 2026-10-22): 22 pass, 0 fail, D4 skipped (close site with cutoff selected — covered by an automated test only), F3 unmarked with an answer. Answers: B4 zoom refit acceptable; B7 drag "great" + suggests a bounded spinbox for the number; C2 keep line/wash when the step is unticked; C6 wants a red message directly below the number for an invalid value; F1 magenta line easy to see but the magenta label text is very hard to read; F2 gain shift acceptable; F3 drop "(needs values)".
Walkthrough round 2: user ruled out-of-range cutoff snaps to the nearest limit, no message. Round-2 brief round2-brief.md (label tag, drop "(needs values)" for no-dialog steps, bounded spinbox). Ruling R9: no change to the form message colour for other steps — the user dropped the note — cost if wrong: C6 red message for other steps not done. Dispatched implementer sonnet, BASE 0981d9d.
Round 2: implementer DONE_WITH_CONCERNS 909f533 (qgis 726, pure 606/3; flags setRange rounding of limits ~1e-9, REQUIRED time field shows 0); review dispatched (opus) with the seeded-limit write as a named risk
Round 2: review Needs fixes (opus): Critical — Enter in an unedited time spinbox commits the :g display (QAbstractSpinBox::keyPressEvent interprets on Return), so the seeded value dirties the session and a dragged cutoff keeps one more sample (R3 regression; tests call form.commit() and never reach interpret()); Important — an unedited focus-out overwrites a stored value lying outside the range with the limit; Important — the "selecting another step" focus-out half of the real-data typing test is vacuous (nothing focused).
Ruling R10: an untouched time spinbox (no textEdited, no stepBy since it was built) reports exactly the value it was built from, even when that value lies outside the range — the snap is for what the user types or steps, R3 says an untouched editor never writes, and a stored out-of-range value then fails loudly at apply as before instead of being silently "repaired" — cost if wrong: a stale out-of-range cutoff stays until the user edits it.
Ruling R11: the fix round also takes Minors 4 (snap lands on the 10-decimal-rounded limit, which on fine dt keeps 2 samples instead of 1 — map value()==min/max back to the exact limits), 6 (clamp the tag's left edge to r), 7 (guard textFromValue and valueFromText's clamp) and 8 (time_axis() delegates to input_axis) — same functions, cheap — cost if wrong: a slightly larger fix diff.
Round 2: minor (deferred): a REQUIRED time field would show 0 and count as complete (no blank state); latent, no step pairs a time param with the dialog today.
Round 2: fix round 1/5 dispatched (resume implementer)
Round 2: fix round 1 implemented d7622da (qgis 738 collected exit 0, pure 606/3); scoped re-review dispatched (opus)
Round 2: fix round 1/5 (7 addressed, 1 new Important open — _show_form_with_other_field leaves a parentless top-level host alive, test_plugin_time_cutoff.py exits 139 at teardown alone; Minors: touched-but-reverted entry reports the 10-decimal rounding and dirties the session; edit_text leaves _text_dirty set; setValue from code ignored (latent); new slots unguarded; comment says row 1's range; commits 909f533..d7622da)
Ruling R12: R10 is narrowed — text equal to what the field displays for its current value is NOT an edit (it reports the exact current value); the field counts as touched only when valueFromText parses text that differs from that display, or on a step — the user cannot tell the exact value from its 6-digit display, so keeping the exact value is never wrong, and it closes the reverted-entry, type-then-delete and retype-the-same-text paths to a one-sample silent write in one rule — cost if wrong: retyping exactly the displayed digits does not round the value to them.
Ruling R13: the time spinbox ignores wheel events unless it has focus (StrongFocus policy) — reviewer showed scrolling the Processing panel with the pointer over the field steps and commits the cutoff — cost if wrong: one extra click before the wheel adjusts the field.
Round 2: minor (deferred): spin.setValue(x) from code after build is ignored by values() (no caller today).
Round 2: minor (deferred): arrow steps on fine float32 axes step from the 10-decimal-rounded value, so Down sometimes keeps the same sample count (dt 0.0117/0.0195; not HS350).
Round 2: fix round 2/5 dispatched (resume implementer)
Round 2: fix round 2 implemented ade0972 (qgis 748 collected exit 0; time_cutoff file exit 0 alone; pure 606/3); scoped re-review dispatched (opus)
Round 2: fix round 2/5 (6 addressed, 0 open; commits d7622da..ade0972). Re-reviewer probes: every gesture × every m on HS350 and two fine axes, 0 failures; time_cutoff file exits 0 alone.
Round 2: parked — the wheel test does not pin StrongFocus (a sendEvent wheel is non-spontaneous, so the test passes with WheelFocus restored) — Ruling: behaviour is correct by probe; add `assert spin.focusPolicy() == Qt.FocusPolicy.StrongFocus` when next touched — cost if wrong: a later regression to WheelFocus goes unnoticed.
Round 2: parked — a host-using test that fails before _unload can still exit 139 (no fixture finalizer) — Ruling: failure text still prints; harden with a fixture finalizer when next touched — cost if wrong: a failing run reports as a crash.
Round 2: complete (commits 0981d9d..ade0972)
Round 2 verification at ade0972 (controller): core+pure 606/3, qgis 748 passed exit 0, ruff/format/mypy clean, tree clean. Walkthrough page republished (v3) with stage G (G1-G7); round-1 marks kept in db.
Walkthrough round 2 (user, 2026-10-22): G1–G7 all pass — "it looks great". User: create the PR and merge it if mergeable. Decision record copied to docs/superpowers/sdd/2026-10-16-nsgeo-time-cutoff/.
