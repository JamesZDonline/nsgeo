# SDD ledger — plan: docs/superpowers/plans/2026-11-20-nsgeo-profile-view-plan-b.md

Spec: docs/superpowers/specs/2026-11-20-nsgeo-profile-view-design.md (approved 2026-11-20). Plan A record: docs/superpowers/sdd/2026-11-20-nsgeo-profile-view-plan-a/ (rulings R1–R18).
Branch nsgeo-profile-view, worktree .worktrees/nsgeo-profile-view. Plan B commit 2cbd622; main merged in at 0a8776a (H #235, #227 #234), clean; pure 433, profile dock+view 287, ruff clean after the merge.
User approved R19 on 2026-11-20 ("merge main and then start B"): the no-seed message uses the Processing form's message line, not a toast.
Models: implementers sonnet; task reviewers opus; small re-reviews sonnet.
Real survey files are linked into this worktree (packages/nsgeo-core/tests/data/local/*).

## Pre-flight scan

| Pair / task | Produces vs consumes | Finding |
|---|---|---|
| T1 / T3 | both edit profile_dock.py: T1 `_take_down_picture` + the Fit button; T3 `current_radargram`, `_scale_reference`, `time_param_name`→`handle_spec`, `_cutoff_row`→`_handle_row` | no shared lines; consistent |
| T1 / T4 | T1 edits profile_view `set_axes` and the true-scale helpers; T4 edits the view's cutoff/handle code | disjoint; consistent |
| T2 / T3 | T3 consumes `param_visible` and the `row` kind | consistent |
| T2 / T4 | T4's "typed row moves the line" uses T2's RowSpinBox and `_on_form_committed` | consistent |
| T3 / T4 | T4 consumes `handle_spec`, `_handle_row`, the relabelled input (`relabel_onto`) | consistent |
| T1 self | width-pin rewrite: two font-proof checks; bounds_on removal + its pure tests | clean |
| T2 self | the form test's first assert `form.editors["threshold"].isVisible() is not False` is ill-formed (isVisible is False on an unshown form) | see RB1 |
| T2 self | the seed test asserts stack.zero_ns() unchanged across the switch: the seed = the first-break row, so the crop is the same | clean |
| T3 self | relabel numbers: FILE__007 t0 -11.086 - (-0.476) = -10.61; FILE__010 -9.53 | clean |
| T4 self | snap_row expectations checked by hand (-2.0, -1.5, 22.75); after a drag the line sits at 0.0 on the new clock (t0' + sample·dt = 0) | clean |

Ruling RB1: the form-visibility tests use `isVisibleTo(form)` throughout (the plan's `isVisible() is not False` is ill-formed on an unshown form) — cost: none.

## Tasks
Task 1: dispatched (BASE 0a8776a, implementer a66165d9989792e7a, sonnet)
Task 1: implementer DONE_WITH_CONCERNS at 02ff621 (push failed on DNS; controller re-pushed)
Task 1: review 1 (02ff621): ❌ / Needs fixes — I1 the width pin's first check reads a stale cached minimumSizeHint (dock never shown, layout not re-activated), so a plain-QLabel velocity label regression passes (probe: 750 -> 750 as written; 750 -> 4364 when shown).
Ruling RB2: pull Minors 1–4 into the round — dead _clock_carried; _FitButton.event recompute after super().event (Qt 6 safety); setDefaultAction(fit_all_action) explicit; the rule-1 comment — all small, and M2 guards the very drift the task fixes — cost: none.
Task 1: fix round 1/5 (5 addressed, 0 open — live width pin, _clock_carried removed, FitButton event order, explicit default, comment; commits 02ff621..fa46578)
Task 1: complete (commits 0a8776a..fa46578, review clean)
Task 1: minor (deferred): the width pin's `base + grown` is effectively an exact equality (>= and <=); a font-rounding difference on CI could trip it — watch CI on fa46578; loosen with a small tolerance if it does.
Task 2: dispatched (BASE fa46578, implementer acb2e52b9ec332bb9, sonnet; carries RB1, R19)
Task 2: implementer DONE_WITH_CONCERNS at 7f85468 — added public core name first_break_row_or_none (boundary test bars the private one); RowSpinBox's signal is row_stepped (no-orphan-signals test); ParamForm.show_row(name, value) added to refresh the spin after a seed.
Env note: the core venv imports nsgeo from the MAIN checkout; core tests from this worktree need PYTHONPATH=<worktree>/packages/nsgeo-core/src (later briefs carry it). The QGIS tier uses the worktree.
Task 2: review 1 (7f85468): ❌ / Needs fixes — I1 §4.9 "__post_init__ validates what it can" missing: when=("mode", ()) passes; a mis-shaped when fails with a bare unpack error naming nothing; I2 the threshold-seed test can't tell 0.2 from the step's threshold (both pick row 60).
Ruling RB3: pull M2 (RowSpinBox duplicates TimeSpinBox's wheel/step rules — the wheel rule is a recorded user preference, so one mixin), M3 (seed by the row spec whose `when` now matches, not by names; no in-place mutation), M4 (_on_form_committed gets the slot try/except), M5 (a hidden field that fails to parse falls back to its stored value, so it can't block a mode switch), M6 (_input_record helper), M7 (assert -> real check; drop the unused fixture arg) and M8 (tests for no-seed before load and with a refusing step above, and no seed on a first_break threshold edit) into the round — each is small, and M5 is a user-visible trap — cost: a larger fix round.
Task 2: minor (deferred): a REQUIRED row is half supported (add_step_with_dialog seeds a float time; the row editor turns REQUIRED into its minimum) — no step has one today.
Task 2: minor (deferred): the row branch of _parse_number is unreachable (the brief asked for it).
Task 2: fix round 1/5 (9 addressed, 0 open — when validation, threshold test, spinbox mixin, seed by visibility, slot guard, hidden-field fallback, _input_record, leftovers, no-seed tests; commits 7f85468..dd9ba85)
Task 2: complete (commits fa46578..dd9ba85, review clean)
Task 2: minor (deferred): _input_record has a production assert (type narrowing only; both callers check source first).
Task 3: dispatched (BASE dd9ba85, implementer a59ab346f676b66d6, sonnet)
Task 3: implementer DONE at e41b2dd (row handle hidden for now; _shows_row_handle helper; top/mid holding tests not shown RED)
Task 3: review 1 (e41b2dd): ✅ spec / Needs fixes — I1 no test covers _scale_reference's row-handle branch (deleting it stays green; the raw input would draw against the processed scale).
Ruling RB4: pull M1 (make the mid-record test bite: (time_lo, time_hi) unchanged on select; label the top test a guard), M2 (a refusing Time zero still gets its input view: fall back to the unrelabelled input when zero_ns() raises — it is what the user needs to fix the row), M3 (docstrings), M4 (handle_spec -> ParamSpec | None), M5 (one _handle_spec_at helper) into the round; M6 (the "next task" comment) is Task 4's to remove — cost: a larger round.
Task 3: fix round 1/5 (6 addressed, 0 open — scale pin, mid-record bite + top guard label, refusing Time zero draws input, docstrings, ParamSpec type, _handle_spec_at; commits e41b2dd..76b630a)
Task 3: complete (commits dd9ba85..76b630a, review clean)
Task 4: dispatched (BASE 76b630a, implementer a4f88b93ac38caddb, sonnet)
Task 4: implementer DONE_WITH_CONCERNS at 0217a72 (impl before tests, RED by revert; disabled Time zero: input on source clock, line at row; added: no row line while a valid Difference view is up)
Task 4: review 1 (0217a72): ✅ spec / Needs fixes — I1 the row handle's snap/clamp in the view is unguarded (mutant: always snap_cutoff -> 27 selected tests still pass; the end-clamp test calls snap_row itself; the view drag stays mid-record).
Ruling RB5: pull M2 ("-0.00 ns" in the drag tag: round(t, 2) or 0.0 — user-visible), M3 (Difference test through a real path: time_zero(sample=0) with Difference on), M4 (exact drag-tag assertions), M5 (typed-row test checks the line's screen y), M6 (set_cutoff refuses an unknown kind with a log; cutoff_ns docstring; set _cutoff_step after the Difference check), plus the two ⚠️ pins (a not-first Time zero seeds from intermediate(row-1); §4.13 migration pin also asserts the line is up) into the round — cost: a larger round. M7 (consolidating the copied plugin helpers into plugin_testing) is deferred: it would touch test_plugin_time_cutoff.py's imports.
Task 4: minor (deferred): _plugin_with_line/_unload copied a third time; move into plugin_testing in a later cleanup.
Task 4: fix round 1/5 (6 addressed, 1 open — M5 typed-row test can't detect a stale line/step: mutant S2 (skip redraw when the step changed) survives and silently drops the next drag; commits 0217a72..f084ce5). I1 bottom case verified guarded by the re-reviewer.
Task 4: fix round 2/5 (1 addressed, 0 open — typed-row test drags after the commit; S2 mutant now fails; commits f084ce5..8ac7ffa)
Task 4: complete (commits 76b630a..8ac7ffa, review clean)
All four tasks complete. Next: final whole-branch review (Plans A and B).
Final review: packages review-0a8776a..8ac7ffa.diff (Plan B) and review-5b6efd4..8ac7ffa.diff (whole branch vs main)
Final review (Plans A+B): dispatched (opus, a5cb404c902ba49e8; primary 0a8776a..8ac7ffa)
Final review (A+B, 8ac7ffa): Ready for deploy and walkthrough — Yes; no Critical/Important code bugs. I1 the guide has no Time zero by eye sentence (plan gap; before merge); M1 a hidden field that parses but is out of bounds still blocks a mode switch (RB3's fix covered only parse failures; before merge); M3 stale docstrings (cutoff_dragged, profile_view module docstring, _handle_row); M2 required row would crash Add step (latent; can wait); M4 seed generic in shape, Time-zero-specific in fact (can wait, #210 note). Rulings judged right.
Ruling RB6: one fix wave takes I1, M1, M3; M2 and M4 stay deferred (no step has a required row; Time zero is the only row step) — cost if wrong: a future required-row step crashes Add step until hardened.
Final fix wave: f8a2c51 (I1 guide line, M1 hidden out-of-bounds fallback, M3 docstrings); it exported param_problem from nsgeo.processing, which broke core test_public_api (README line missing) — controller found it running core with PYTHONPATH; fixer resumed to add the README line.
Walkthrough: profile ns_geo_profile_view (dev_link -> worktree), sandbox ~/nsgeo-profile-view-walk (Campus: FILE__007; Survey: with-dzg FILE__001-004; 0.1 m/ns; TZ+dewow+bg+AGC), artifact https://claude.ai/artifact/26aJGGXyEG9VAt9mo2HnQd (db "checks": W1–W13, Q1–Q4); checks collection empty at publish.
Final fix wave re-review (8ac7ffa..af52c9a): all findings addressed (I1 guide bullet, M1 hidden out-of-bounds fallback, M3 docstrings; param_problem export + README accepted); no new Critical/Important. Core 1739 passed with the worktree's core.
Plan B: complete. Next: walkthrough (artifact 26aJGGXyEG9VAt9mo2HnQd), then ask before merge.
