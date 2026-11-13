# SDD ledger — plan: docs/superpowers/plans/2026-11-12-nsgeo-grid-velocity-from-fits.md

Spec: docs/superpowers/specs/2026-11-12-nsgeo-grid-velocity-from-fits-design.md (approved 2026-11-12).
Branch nsgeo-grid-velocity, worktree .worktrees/nsgeo-grid-velocity, start d498a61 (on main 15dea4c).
Execution: subagent-driven, chosen by the author 2026-11-12. Implementers sonnet (opus for judgment-heavy), reviews opus.
Prerequisites: Task 4 needs piece 1 (PR #181) merged + main merged in. Task 5 needs #175 (MERGED b612f63) + main merged in.

## Pre-flight scan

| Pair / task | Produces → consumes | Found |
|---|---|---|
| T1 → T2 | VelocitySource, SourceFit, Line.velocity_source, Line.fit_serial, Line.velocity_from_fit property → session setters, ids, member_state | Consistent. But T1 turns `velocity_from_fit` from a field into a property, and session.py:878/893 and test_plugin_velocity_dialog.py:210 write it with dataclasses.replace. The QGIS tier breaks between T1 and T2 → Ruling R1. |
| T1 → T3 | weighted_mean, from_fits → dialog average, chosen_source | T3's test patches `velocity_dialog.weighted_mean`, so the dialog must import the name into its module namespace. Carried into T3's dispatch. |
| T1 → T4/T5 | summary() → Survey grid row, profile label, slice label | Consistent. |
| T2 → T3/T4 | apply_line_velocity, apply_grid_velocity, member_state, member_fit → dialogs, strip | Consistent. |
| T2 → T4 | set_velocity_from_fit kept → removed in T4 | Consistent. |
| T3 → T4 | velocity_dialog.py rows keyed by (line_key, fit_id); fits_at_line_zero → grid scope | Consistent. Both edit profile_dock.velocity_source (T3 line branch, T4 grid branch). |
| T4 → T5 | profile_dock: T4 grid branch, T5 grid_velocity_label; session: T4 removes set_velocity_from_fit, T5 renames cut_velocity | No overlap in lines. |
| T1 self | P1 says the "names" join EXPECTED_PUBLIC, but EXPECTED_PUBLIC lists modules | Ruling R2. |
| T2 self | Tests in test_plugin_session.py; consistent with Interfaces | ok |
| T3 self | The tick column moves `_FLAG_COLUMN`; tests use flag_text(row) | ok, the plan says so |
| T4 self | Prerequisite merge; tests in a new file and four existing ones | ok |
| T5 self | Prerequisite merge; `grep cut_velocity` check | ok |

- Ruling R1: Task 1 also makes the two session writers work against the new model, so the QGIS tier stays green.
  - set_velocity_from_fit builds a one-member record from the stored fit.
  - remove_velocity_fit stops writing the gone field and leaves any record alone. That is T2's rule anyway.
  - test_plugin_velocity_dialog.py:210's dangling pointer becomes a record naming a fit that is gone.
  - T1 runs test_plugin_velocity_dialog.py, test_plugin_velocity_fit.py and test_plugin_session.py as well as core+pure.
  - Why: a red CI on a pushed task commit hides real breakage.
  - Cost if wrong: T1 is slightly bigger and T2 slightly smaller.
- Ruling R2: the module `velocity_source` joins EXPECTED_PUBLIC (a module list). The core README names `VelocitySource`, `SourceFit` and `weighted_mean`.
  - Why: the test checks modules, not classes.
  - Cost if wrong: none.

## Tasks
Task 1: dispatched (sonnet, BASE d498a61), agent a14fd4b2aa98de20a
Prereq: piece 1 MERGED as PR #181 → main 5a65eb2 (2026-11-12). Merge origin/main into this branch after Task 3, before dispatching Task 4 (not while an implementer is running). QGIS profile ns_geo_velocity_fixes now points at this worktree (Ruling R3: the walkthrough uses it instead of the plan's ns_geo_grid_velocity — the author named it for the velocity work — cost if wrong: one profile rename).
Task 1: implementer DONE_WITH_CONCERNS (1949f6b; concerns: property can't check line_key; module written before its tests, RED by moving it aside; fixture label; set_line_velocity drop is T2). Review dispatched (opus, d498a61..1949f6b), agent a1d42812e251e1599
Task 1: complete (commits d498a61..1949f6b, review clean — Approved, 0 Critical/Important)
Task 1: minor (deferred): weighted_mean lets extreme finite σ (1e-170, 1e200) through to ZeroDivisionError/nan → carried into T2 (R4)
Task 1: minor (deferred): one fit does not average exactly to itself (0.09209999999999999); test loosened to approx → carried into T2 (R4)
Task 1: minor (deferred): a NaN in a hand-edited old fit migrates into a record that saves as NaN and then fails to load
Task 1: minor (deferred): a bad fit_serial (string/neg) silently becomes 0, untested
Task 1: minor (deferred): the label fallback to the file stem is untested
Task 1: minor (deferred): remove_velocity_fit docstring stale → carried into T2 (R4)
Task 1: minor (deferred): VelocitySource has no docstring; from_dict accepts method "fit" with several members
- Ruling R4: Task 2's implementer also fixes three Task 1 minors. The first two are in velocity_source.py: extreme σ gets the named error, and one fit returns exactly itself (exact test restored). The third is the remove_velocity_fit docstring.
  - Why: Task 3's one-tick Use average relies on an exact single-fit value (spec §6, "averages to itself"), and Task 2 is editing remove_velocity_fit anyway.
  - Cost if wrong: a slightly larger T2 diff.
Task 2: dispatched (sonnet, BASE 1949f6b, with R4), agent aee139f31830bc546
Task 2: implementer DONE (3a4fb3b; concerns: deleted-before-moved order; replace_grid also emits lines_changed; loose-line test uses SimpleNamespace placement)
Task 2: review dispatched (opus, 1949f6b..3a4fb3b), agent af9d7fe07a45cced9
Task 2: complete (commits 1949f6b..3a4fb3b, review clean — Approved, 0 Critical/Important)
- Ruling R5: a line removed and imported again reads "deleted", as the brief says, not "line removed".
  - Why: the fit the record names no longer exists on that line. "Deleted" is true, and the spec's grouping was descriptive.
  - Cost if wrong: one word in the dialog note.
Task 2: minor (deferred): the extreme-σ test regex "cannot be weighted" also matches the unnamed total-overflow message; parametrize the expected "fit i has σ s" (a mutant dropping isfinite(weight) survives)
Task 2: minor (deferred): the total-overflow branch (two σ=1e-154) is untested and names no fit
Task 2: minor (deferred): DRY: set_line_velocity duplicates apply_line_velocity (grid pair too); member_state and member_fit check presence two ways
Task 2: minor (deferred): fit-N parsing in two places (session._fit_number, project._FIT_ID)
Task 2: minor (deferred): add_velocity_fit docstring points to set_line_velocity and omits never-reuse; apply_grid_velocity docstring omits the lines_changed from replace_grid
Task 2: minor (deferred): test_plugin_session.py:1961 clears lines.calls and never asserts
Task 2: minor (deferred): no test that a grid record survives move_lines / remove_line / time-zero step (spec §7.3 "in every case")
Merged origin/main into the branch at 772b798 (piece 1 #181 + #175): core+pure 1537 passed / 5 skipped; QGIS session/velocity_fit/velocity_dialog/survey_dock run pending
Merge 772b798 pushed: QGIS session/velocity_fit/velocity_dialog/survey_dock 326 passed. Task 3: dispatching (BASE 772b798)
Task 3: dispatched (sonnet, BASE 772b798), agent aac9ec170d7ddcc0e
Task 3: implementer DONE (fbd3b30; concerns: single-fit record whose fit re-measures differently counts as a pick on open — existing #97 test expects it; zero-σ reason shown in average_text; disagreeing_fit_ids made generic)
Task 3: review dispatched (opus, 772b798..fbd3b30), agent a87bdbdc3a9cde0f3
Task 3: review NEEDS FIXES (3 Important: untouched Apply rewrites a single-fit record after a time-zero change, against spec §7.2 rule 1 / §7.3, pinned the other way by the #97 test; no message_log asserts in the new slot tests; the real tick → itemChanged path and the All box click are untested)
- Ruling R6: the spec wins over the pre-feature #97 test `test_the_dialog_flags_an_applied_velocity_its_fit_no_longer_measures`.
  - The behaviour: on open, the applied fit's row is selected for the highlight only. The box stays on the velocity in force, and the fill is "none", so an untouched Apply keeps the velocity and the record.
  - Adopting the re-measured number takes a deliberate pick. A click on the already-selected row must count, via `cellClicked`.
  - The #97 test is rewritten to: untouched Apply keeps; a row click then Apply adopts the new number with a fresh record.
  - Why: spec §7.2 rule 1 ("An untouched Apply changes nothing") and §7.3 ("the velocity and the record stay … What changes is how the dialog describes the record"). The flag already tells the user the number moved.
  - Cost if wrong: the author has to click the row once to adopt a re-measured velocity.
Task 3: minor → folded into fix round 1: a pick is forgotten when an unusable row is then selected (brief says remember the pick's ref and value)
Task 3: minor → folded into fix round 1: no test of time zero + Use average (members must be at-zero numbers)
Task 3: minor (deferred → carried into Task 4 dispatch): bare-fit-id keyed state (_unusable, _at_zero, _selected, _member's self._label) must move to Ref for grid scope
Task 3: minor (deferred): unmeasurable note has a colon the spec's wording lacks
Task 3: minor (deferred): overflow-σ message names "fit 2" by ticked-list index, not a row the user can see
Task 3: minor (deferred): the fallback at :478 keeps the old record when a changed fill ends equal to the velocity in force (rule 4 wording)
Task 3: minor (deferred): dead `noun` at :341; _outcome() runs twice per Apply; _dialog_without_record hides an assertion in a helper; velocity_dialog.py ~610 lines
Task 3: fix round 1/5 dispatched (resumed implementer aac9ec170d7ddcc0e; FIX_BASE fbd3b30; findings: R6 untouched Apply, message_log asserts, real tick path + All click, remembered pick, time zero + Use average test)
Task 3: fix round 1 implementer DONE (f948a6b; side effect: delete returns the box to the velocity in force); scoped re-review dispatched (opus, fbd3b30..f948a6b), agent af79ed0f5a9fd6e1d
Task 3: fix round 1/5 (5 addressed, 0 open; commits fbd3b30..f948a6b)
Task 3: complete (commits 772b798..f948a6b, review clean after 1 fix round)
Task 3: minor (deferred → carried into Task 4 dispatch): the tick-column exclusion in _on_cell_clicked (:543) is untested
Task 3: minor (deferred): selected_fit_id() has no production caller left; picking is mouse-only (no keyboard path to re-pick the selected row)
Task 4: dispatched (opus implementer — 6 files, Ref re-keying hazards, strip + Edit grid integration warrant the tier; BASE f948a6b), agent a87439bd20b815399
Task 4: implementer DONE_WITH_CONCERNS (14a1d53; concerns: starred note names all overridden lines incl. without fits; Delete warning names grid records in the line dialog; header-click sorting added per spec §4.3; line dialog spin no longer stretches; user guide not updated)
Task 4: review dispatched (opus, f948a6b..14a1d53), agent ad78d64f77dd969f3
Task 4: review NEEDS FIXES (1 Important: a real click in column 0 off the checkbox selects the row and picks it; in grid scope that silently turns an average into a one-fit record; the tests only emitted cellClicked, so they missed it)
Task 4: minor → folded into fix round 1: sort indicator moves to the tick column on a header click there; timing assert (opened < 5.0) contradicts P9; one-member record built in three places (timestamp format, P8 label rule); grid-scope tests for All across lines, rule 4 after Use average, reimport fit-1 (spec §12); line scope computes _line_text per row and discards it; the user guide does not describe the grid dialog
Task 4: minor (deferred): velocity_dialog imports busy_cursor from finish_panel (pulls in slices_plan); velocity_dialog.py is 896 lines
Task 4: fix round 1/5 dispatched (resumed implementer a87439bd20b815399; FIX_BASE 14a1d53; Important: real click off the tick box picks; minors folded: sort indicator, P9 timing assert, one shared record helper, grid-scope tests, line-scope leftover read, user guide paragraph)
Task 4: fix round 1 implementer DONE_WITH_CONCERNS (a2a4ef1; new module velocity_records.py; concerns: arrow keys don't pick while on the tick column; tick column 51 px = header minimum)
Task 4: scoped re-review dispatched (opus, 14a1d53..a2a4ef1), agent a55273031d8dd2842
Task 4: fix round 1/5 (7 addressed, 0 open; commits 14a1d53..a2a4ef1)
Task 4: complete (commits f948a6b..a2a4ef1, review clean after 1 fix round)
Task 4: minor (deferred): arrow keys no longer pick while the current column is the tick column (Tab focus lands on (0,0); quiet select on open) — nothing wrong is recorded; walkthrough note
Task 4: minor (deferred): tick cell 51 px (header minimumSectionSize) with the box at px 3–15; click_table_cell docstring says one pixel in, but it is two; `shown` fixture duplicated in two test files
Task 5: dispatched (sonnet, BASE a2a4ef1; README roadmap edit allowed for Step 5), agent a769083eb42f51f63
Task 5: implementer died mid-task on an API auth error (2026-11-13), leaving uncommitted work in 12 files (its last note: 'RED for the right reason. Now the other tests (dock, site scope, real)'). Resuming the same agent so it continues from its transcript.
Task 5: implementer DONE (ab0746e; changed the removed-first-line slices_dock test to assert the label names the grid's new first line instead of "")
Task 5: review dispatched (opus, a2a4ef1..ab0746e), agent a2c6ec505b8b8518f
Task 5: complete (commits a2a4ef1..ab0746e, review clean — Approved, 0 Critical/Important)
Task 5: minor (deferred, recommend fixing in final wave): the Slices label and readout do not refresh after a live grid Apply (grids_changed → rebuild_source calls refresh_slice only when _finish_moved). Pre-existing, but the grid velocity is now the main input.
Task 5: minor (deferred): the dock's kept KeyError guard has lost its only test (remove every line of a velocity-less grid while its slice stays prepared)
Task 5: minor (deferred): comments and docstrings still describe the first-line rule (slices_engine.py:1094, slices_dock.py:1331-1336, :2789-2790, the changed test's docstring)
Task 5: minor (deferred): grid_velocity_label re-implements grid_depth_velocity's fallback and velocity_source's "Grid {id}, {summary}" format — label can drift from the number
Task 5: minor (deferred): a frozen cube's provenance velocity can go stale on a header-fallback grid when the grid's first line changes (accepted by spec §10; worth a docstring line)
Task 5: minor (deferred): test gaps — engine test lacks errors == []; real-data readout checks lo_m only; an import inside a test; _override_every_line duplicated
Final review: dispatched (opus, 724cb0a..ab0746e, the branch's own work), agent a581f02c4ac834d48
Final review: WITH FIXES (0 Critical; Important: the Slices label and readout stay stale after a live grid Apply while the export already uses the new velocity; head CI red on qgis 4.2 only — #166's site_scope flake, re-run).
- Ruling R7: an untouched Apply on a line with no override must leave it with no override. Today it pins the grid's velocity, rounded to 4 dp, as a line override, against spec §7.2 rule 1. The fix goes in the final fix wave.
  - Why: same reasoning as R6, the spec wins over pre-feature behaviour. A pinned line also stops following the grid, which defeats the grid workflow.
  - Cost if wrong: an author who relied on Apply to pin the grid's number on one line has to type it.
- Ruling R8: an untouched Apply writes nothing: no signal, no dirty flag.
  - Why: a save prompt after a no-op contradicts "changes nothing".
  - Cost if wrong: none.
Final fix wave scope: Important 1 + its test; the KeyError-guard test; correct the stale first-line comments; R7 + test; R8 + test; real Grid 2 save/load of records; a test of the "cannot be measured at the current time zero" note line.
Walkthrough notes: R6 click-to-adopt; arrow keys from the tick column; an old-file migration under Time zero can give a record whose v differs from the velocity in force (final review Minor 2); the 0.4.0 refusal step is data-loss relevant.
Follow-ups to file at merge: §16 items (exports carry the source; Dix; line clock vs preset clock with #163); skip non-finite fits when migrating velocity_from_fit; plus the deferred minors marked can-wait.
Final fix wave: dispatched (sonnet, FIX_BASE ab0746e), agent aa160aca6c62cb94c
Final fix wave: DONE_WITH_CONCERNS (7c3706d; NOT YET PUSHED — github.com unreachable (DNS) for the agent and for the controller; concerns: typing the box's own number on a line with no override also yields no override; a killed git checkout -p, tree verified restored)
Final fix wave 7c3706d is on origin (push retry succeeded once DNS returned). Scoped re-review dispatched (opus, ab0746e..7c3706d), agent a5f2070a4bf89ad44
Final fix wave re-review: all 6 addressed, no new Critical/Important (commits ab0746e..7c3706d).
Final: parked — the grid-scope R8 test's record case builds the record before the loop, so it re-tests the bare-number case — Ruling: the code is correct by inspection (_outcome returns the grid's own objects). Fix the test in the first post-walkthrough round. Cost if wrong: a regression on the no-op grid-record Apply goes uncaught until then.
Final: parked — slices_dock.py:1351-1354's comment says provenance() raises KeyError, but it suppresses it — Ruling: comment-only; fold into the post-walkthrough round.
Final: parked — suppress(ValueError) at slices_dock.py:912 wraps all of _update_readout, not just the legend — Ruling: the impact is low (stale until the next tick, which reports it). Narrow it in the post-walkthrough round.
Final: parked — test docstring at test_plugin_slices_dock.py:1427 says "record" for "velocity"; _update_velocity_label's KeyError guard can't be reached in production — Ruling: nits; post-walkthrough round.
Merged origin/main (#89 line identity, roadmap) at 1eb2232 and pushed. Core+pure 1539 passed / 5 skipped; QGIS: velocity_dialog 84, grid_velocity_dialog 29, session 121, velocity_fit 77, survey_dock 80, grid_dialog 147, slices_dock 172, profile_dock 119 — all passed; ruff/mypy clean.
Deployed: profile ns_geo_velocity_fixes → this worktree; headless load probe: plugin loaded, open_grid_velocity_dialog present; profiles.ini unchanged.
Walkthrough published: https://claude.ai/artifact/WBbG6CkcbiYPtPNq6WxQsg (db collection "results", 24 checks, H2 data-loss relevant). Awaiting the author's results.
Walkthrough (2026-11-13): 23 pass, 1 skipped (D2, optional: no member line without a Time zero step), 0 fail. Author note on B9: a future issue — selecting a row in the fit table should show that hyperbola on its profile, so a suspicious fit can be reviewed.
Post-walkthrough round (controller, right-sized: tests/comments only): the grid-scope R8 test now applies its record inside the loop; the provenance KeyError comment is corrected; the relabel guard logs ValueError instead of suppressing it; a test docstring is fixed. grid_velocity_dialog 29 passed, slices_dock 172 passed, ruff clean.
