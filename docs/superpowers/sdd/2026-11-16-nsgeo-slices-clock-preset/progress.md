# SDD ledger — plan: docs/superpowers/plans/2026-11-16-nsgeo-slices-clock-preset.md

Spec: docs/superpowers/specs/2026-11-16-nsgeo-slices-clock-preset-design.md (approved by the user 2026-11-16, "approved, write the plan"; build go "build it").
Worktree: /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-slices-clock-preset, branch nsgeo-slices-clock-preset, base origin/main 140f64e (+ spec b37be25, plan 768023f).
Baseline: CI green on main (140f64e, f5e14f1) and on the branch at 768023f. Local pure+core baseline 1682 passed / 5 skipped (before the session restart). Local QGIS-tier baseline did not finish (process restart); CI's green QGIS 3.44 + 4.2 jobs stand in.
Issue #201 filed for session K (grid-velocity clock warning). Roadmap In progress row f5e14f1.

## Model tiers (user memory: implementers by role, reviews opus)
T1 opus, T2 opus, T3 opus, T4 sonnet. Task reviews opus. Final review opus.

## Pre-flight scan

| Pair / task | Produces → consumes | Finding |
|---|---|---|
| T1 → T2 | `_drop_restore_pending()` (T1) extended by T2 to reset `_grid_notes` | consistent |
| T1 → T3 | `_drop_restore_pending()` sets `_pending_z_shift` to "nothing owed"; T3 changes that to `None` | consistent: T1 tests use truthiness, as the plan says |
| T2 → T3 | `_settle_z()`, `_grid_notes`, test helper `_notes(dock)`; T2's `_shift_z_by_median_zero` appends the note, T3 renames it `_shift_z_to_clock` | consistent |
| T1, T2, T3 share `test_plugin_slices_dock.py` | T1 adds tests that call `_assert_shifted_once(dock, errors)`; T2 re-points that helper at Warnings; T3 changes its `_pending_z_shift is False` to falsy | consistent, sequential |
| T1, T4 share `test_plugin_site_scope.py` | T1 adds the #102 test; T4 rewrites `test_grid_time_bases_reads_each_grids_preset` and adds a no-lines test | no overlap |
| T3, T4 share `slices_engine.py` | T3 adds `median_first_break`; T4 adds `prepared_steps` | no overlap |
| T1 self | tests vs code: the #102 test needs `_pending_top_ns`/`_resolution_owed` cleared after the scope switch; code step says beside `_site.forget()` | agrees |
| T2 self | the existing `test_an_old_recipe_keeps_its_shift_while_a_preparation_is_owed` sets `_grid_prepare_pending` by hand before `restore_cube`; the new deferral rule then also owes the resolution, and `_run_pending_grid_prepare` settles both | agrees (same end state) |
| T3 self | names a guard test `test_a_marked_record_on_its_own_clock_is_not_moved` but then says the two existing tests cover it and only gain `_notes == []` | see Ruling P1 |
| T4 self | Step 2 says the velocity test passes (a pin of today's code); the global rule allows a guard test that says so in its docstring, and the task asks for the mutation evidence | agrees |

Ruling P1: T3 adds no test named `test_a_marked_record_on_its_own_clock_is_not_moved`; it extends `test_a_marked_record_is_not_shifted` and `test_an_old_recipe_without_time_zero_restores_unchanged` with `_notes(dock) == []` — the plan's own sentence says the existing tests cover it — costs nothing if wrong (a reviewer can ask for the named test).

## Human gates
- G1: the walkthrough after the final review (spec §10). Not yet run.

## Tasks
Task 1: dispatched (opus) BASE 768023f, implementer agent abcf01520b6fdf07d
Task 1: implementer DONE_WITH_CONCERNS, commit 9c48217 (pushed).
Ruling T1-a: accept the extra `slice_slider.setValue(0)` (blocked) on a new site, and its This-grid twin test — spec §2/#102 ask that a new survey start at its own first slice; clearing `_pending_top_ns` alone left the slider index of the closed survey standing — costs a revert of one line if the author wants the old index kept.
Ruling T1-b: `test_opening_a_survey_does_not_carry_a_same_named_preset_over` is a guard, not a bug pin: `open_site` → `_install` closes the open survey first, which empties the preset combo. Spec §5's "opening carries a same-named preset over" is wrong about today; the fallback rule still covers a site open. Spec sentence to correct in a docs commit — costs nothing.
Task 1: review dispatched (opus) on 768023f..9c48217, reviewer a83d775ab0c7804e4
Task 1 review: ✅ spec, Approved, 0 Critical / 0 Important, 4 Minor. Spec corrected (§5 opening, §10 This-grid close) in a docs commit.
- Minor M1-1 (`_switch_resumed_grid` repeats the drop + default-preset work that `_sync_included`'s non-by-hand branch now does) and M1-2 (`_pending_top_ns` / `_resolution_owed` declaration comments don't say a site change drops them): carried into Task 2's dispatch, which edits the same file.
- Minor M1-3 (the walkthrough should show the This-grid close/open slider reset): added to spec §10.
- Minor M1-4 (`_second_survey` test helper leaves a second SiteSession undisposed): noted, no action (it holds no resources).
- ⚠️ test-output warnings: check at the coordinator's full-tier run.
Task 1: complete (commits 768023f..9c48217, review clean)
Task 2: dispatched (opus) BASE 3f892b9, implementer a0abff283818948d9 (M1-1, M1-2 folded in)
Task 2: implementer DONE_WITH_CONCERNS, commit d7a2d0c.
Ruling T2-a: accept D1 — a restore with no shift owed and no preparation running settles once (`_settle_and_push()`) instead of `flush_debounce()` + `_settle_and_push()`; two pushes would each drop the plans and the cube — costs one extra push if wrong.
Ruling T2-b: accept the `show_warnings()` in `restore_cube`'s except path (a failed restore must not leave the previous note standing) and the six note checks re-pointed at errors + Warnings.
Ruling T2-c: concern 4 (a restore that defers behind a live site task drops its saved palette: `if not self.engine.is_running: self._pending_palette = None` fires when `prepare()` deferred) is a correctness bug on the #200 path itself; fixed before review in a round with the same implementer, with a test that fails first — costs a few lines.
Task 2: pre-review fix 482b1db (deferred restore keeps its palette; plus a guard in _run_pending_grid_prepare clearing a palette no preparation will consume — Ruling T2-d: accepted, mirrors restore_cube's no-op clear). Pushed.
Task 2: review dispatched (opus) on 3f892b9..482b1db, reviewer a93b16de9f1020d2a
Task 2 review: ❌ 1 Important (I2-1: a restore note can outlive the Cube box leaving its cube — a refused restore's except path, or an edit during the preparation window / #200 wait, after which the late clock note returns and no edit clears it), 6 Minor.
Ruling T2-e (I2-1's open question): the late clock note may still appear after an edit made during the preparation — the shift moves the user's spins (their edit was on the saved clock they saw), and the note says why; the next edit must clear it. Fix: `_mark_cube_unsaved` clears and re-shows `_grid_notes` whenever any are present, whatever the combo text — costs a note shown once more than strictly needed if wrong.
Ruling T2-f (Minor 1, labelled plan-mandated: `_settle_and_push` still pushes the radar-clock range when a shift is owed and a preparation runs; no production caller, but the re-pointed helper test exercises it): fix in round 1 — spec §3 binds "no path pushes a range before its owed shift"; one line plus a push-recorder assertion in that test.
Task 2: minor (deferred): M2-2 `deferred = self._grid_prepare_pending` comment says a site task is live, also true when the flag was pre-set and the restore's own prepare dispatched — reword.
Task 2: minor (deferred): M2-3 no test drives `_run_pending_grid_prepare` dispatching a preparation for a restore owed a shift via a real live-site-task window (`_site_task_live` helper exists).
Task 2: minor (deferred): M2-4 no test shows a refusal and a note together.
Task 2: minor (deferred): M2-5 Save cube… under a new name (`refresh_cube_combo(select=...)`) leaves the previous restore's notes beside the new cube's name.
Task 2: minor (deferred): M2-6 `assert not dock._resolution_owed` in the Review Focus 2 test cannot fail (the retry consumes it); assert before the retry call.
Task 2: fix round 1 commit 1584a6b (pushed); scoped re-review dispatched (opus) on 482b1db..1584a6b, a3924c7ac47915b3c
Task 2: fix round 1/5 (2 addressed, 0 open — I2-1 note lifetime, M2-1 no push before an owed shift; commits 482b1db..1584a6b)
Task 2: minor (deferred): M2-7 (re-review out-of-scope) an owed shift outlives a restore that fails past its checks after its preparation dispatched; the late note then lands and the next edit clears it.
Task 2: complete (commits 3f892b9..1584a6b, review clean after 1 fix round)
Task 3: dispatched (opus) BASE 1584a6b, implementer a0456e686c62e3de3
Task 3: implementer DONE_WITH_CONCERNS, commits 1fcb491 34f4cb6 291768b (pushed). Measured: median zero campus −0.4764 ns, GPS −1.5590 ns (inside the bands); estimate gap read as prepared under amp_square +0.4331 ns (2 samples) on both; after 34f4cb6, 0 on both; amp_envelope −1 sample campus, 0 GPS.
Ruling T3-a: accept `median_first_break` picking with the public Time zero step (`build_step("time_zero").apply(rg).zero_ns`, skipping lines it refuses) instead of the private `_first_break_or_none`, which fails `test_plugin_boundary.py`'s named-core-API check — same values.
Ruling T3-b: accept 34f4cb6 (read an `amp_square` line through its square root, which returns |x| exactly, the quantity Time zero's rule averages). The four transforms are none / amp_abs / amp_square / amp_envelope: three pick exactly, the envelope within one sample. The alternative (pick each line's break before the transform during preparation, a new PreparedLine field from the worker) is exact for all but touches the preparation pipeline — costs a later change if a fifth transform arrives or the envelope becomes the default.
Task 3: review dispatched (opus) on 1584a6b..291768b, reviewer a4b15964219efdc71
Task 3 review: ✅ spec, Approved, 0 Critical / 0 Important, 5 Minor.
Task 3: minor (deferred): M3-1 `median_first_break` tests the literal "amp_square" (plugin rule: steps from the registry); a new non-|x|-like transform would be read as prepared silently — parametrize the engine test over `transform_names()`.
Task 3: minor (deferred): M3-2 the real-data fairness test doesn't assert its transform is amp_square (the square-root branch's real check could vanish if the default changed); its `band` parameter is unused.
Task 3: minor (deferred): M3-3 two array copies per line on the main thread in `median_first_break` (once per "lost" restore; ~3.6 MB per GPS line).
Task 3: minor (deferred): M3-4 no test restores a marked radar record against a radar preset; the two extended guard tests say "guard" in a comment, not their docstrings.
Task 3: minor (deferred): M3-5 `_shift_z_to_clock`'s bool return is unused; `clock_change_note` gives the "lost" wording for any `to` other than TIME_BASE_TIME_ZERO without a check.
Task 3: ⚠️ (reviewer) an in-place preset edit that toggles Time zero during a restore's preparation keeps the direction fixed at restore time — controller check: the in-flight preparation captured the same steps the direction was read from, so the shift matches the prepared cube; the edit then shows "stale" and re-prepares on the user's next change. Ledgered for the final review, not a Task 3 defect.
Task 3: complete (commits 1584a6b..291768b, review clean)
Task 4: dispatched (sonnet) BASE 291768b, implementer af161343fa054d7f2
Task 4: implementer DONE, commit ce5ec49. Velocity retime guard fails under mutation (22.36 vs 21.36) and was restored; the no-lines test is a guard (needs `site_engine.set_source` first). `grid_time_bases` had one production caller, which already passed the engine.
Ruling T4-a: the implementer's own concern — `_on_line_loaded` re-shows the form on any row whenever the shown line's profiles load, discarding uncommitted edits (a reload after a hover-cache eviction can fire it mid-edit) — is a correctness issue; fixed before review: re-show only a form built while the axis was unknown, with a test that a bounded form survives a second `line_loaded`.
Task 4: pre-review fix c48527d (re-show only a form built with the axis unknown). Pushed.
Task 4: review dispatched (opus) on 291768b..c48527d, reviewer a00a8857776e3b4cf
Task 4 review: Approved, 0 Critical / 0 Important; spec ❌ on one binding point (plugin.py `_resync_gain_strip` docstring still says ProcessingDock never reacts to `line_loaded`; the rewritten initGui comment's "so" follows the wrong clause) → fix round 1 (docs only).
Task 4: minor (deferred): M4-2 toggling a disabled Time zero on before the samples load leaves a radar-clock bound (`set_enabled` keeps the step object, so `_show_form` treats it as an echo); pre-existing on loaded lines too — widen the echo check to compare `input_axis(row)`, or file it.
Task 4: minor (deferred): M4-3 `test_a_grid_with_no_lines_has_no_clock` is a guard but its docstring doesn't say so.
Task 4: minor (deferred): M4-4 `test_a_saved_curve_is_drawn_on_the_shown_clock` uses the live fit, not a saved one (pin still holds).
Task 4: minor (deferred): M4-5 `SiteScope.warnings` docstring still says "the drawn grids", contradicting its new sentence.
Task 4: minor (deferred): M4-6 `time_axis` docstring still describes the header fallback, not the (0, dt, n) branch.
Task 4: minor (deferred): M4-7 `_show_form` is a slot on `step_selected` with no guard of its own (pre-existing).
Task 4: ⚠️ fix round re-ran only processing/param_form/time_cutoff + pure; the coordinator's full QGIS tier at c48527d (running) covers the rest; teardown "QGuiApplication::font() no instance" noise to compare against base.
Task 4: fix round 1 (docs) commit d87c927 pushed; scoped re-review (opus) a1e591143275fe422 on c48527d..d87c927
Task 4: fix round 1/5 (1 addressed, 0 open — plugin.py line_loaded comments; commits c48527d..d87c927)
Task 4: minor (deferred): M4-8 the plugin.py comment and docstring say ProcessingDock re-shows "a form built before the samples loaded: a time field has no clock until then" — too broad; only a time-field form with an enabled Time zero above it has no clock.
Task 4: complete (commits 291768b..d87c927, review clean after 1 docs round)
Final review: dispatched (opus) on 140f64e..d87c927, reviewer affa921968729adda
Final review: With fixes. 0 Critical, 1 Important (F-I1 = M2-5: after Save cube… the last restore's notes stand beside a cube they don't describe → clear notes in `refresh_cube_combo(select=...)`), 5 Minor. CI head d87c927 green on 3.44 + 4.2 (run 44028797204); c48527d's 4.2 red was #166's whole_site settle timeout (run 44027929704), passes at head. Local full-tier run killed to avoid contention with the fix wave (CI covers it).
Final-review triage: fix in the wave — F-I1, M2-3 test, docstrings M4-5/M4-6/M4-8, M3-1 tripwire, M3-2 transform assert, plus trivial M4-3 docstring and M2-6 assertion move. Can wait — M2-2, M2-4, M2-7, M3-3, M3-4, M3-5, M4-4, F-M4 (`_prepared_steps_match` / `save_cube` still read provenance().steps). Offer as issues (not filed; the user decides) — F-M1 deferred restore fixes its clock direction too early (a preset edit toggling Time zero during a site-task wait); M4-2 enabling a disabled Time zero leaves a radar-clock bound; M4-7 `_show_form` unguarded slot; #166 recurrence run 44027929704.
Fix wave: dispatched (opus) BASE d87c927
Fix wave: DONE, commits 9557a9b dfcb1df f53106d c2adcae (pushed). 538 passed across the four QGIS files; pure+core 1685/5; ruff clean.
Ruling FW-a: `refresh_cube_combo(select=...)` clears the notes whenever `select` is given, even for an id not in the list — its only caller is `plugin.save_cube` with the id it just recorded — costs nothing today.
Ruling FW-b: the transform tripwire checks within one sample of the rise row and allows the envelope 3 samples early on synthetic steps (real lines: campus −1, GPS 0) — accepted as a tripwire, not an accuracy gate; the real-data fairness test is the gate.
Fix wave: scoped re-review (opus) a10d2d4632e1640a4 on d87c927..c2adcae
Walkthrough prep (campus cubes made in ~/nsgeo-clock-walk/campus: A__new, A__old, A__gained, A__lost) exposed a load-bearing defect in Task 3's "lost" estimate. Probe on the 10 campus lines (scratchpad/probe_fb.py), median first break read off the prepared lines:
  [dewow] −0.4764 (exact) · [dewow, background_mean] −0.3681 · the author's real preset minus Time zero [dewow, background_mean, gain_agc, gain_curve] −0.0433 (2 samples late, nearly the whole −0.48 shift) — the same under amp_square and none, so the transform was never the main cause; the gain steps are. Raw records' first break: −0.4764 on every line (exact).
  Task 3's real-data fairness test used [dewow] only — a test that dodged the hazard.
Ruling PF-1: the "lost" estimate is the median of each line's first break picked on its RAW record (before any step), where Time zero runs in an ordinary preset — computed in the preparation worker from the radargram it already holds and stored on each PreparedLine; `median_first_break` reads those. This drops the amp_square square-root special case (T3-b, M3-1's literal). The real-data fairness test uses a realistic preset (the author's processing minus Time zero: dewow, background_mean, gain_agc, gain_curve; for GPS with time_cutoff too). Spec §4 amended: "picked by Time zero's own rule at its default threshold on each line's raw record" — the approved intent (option A) unchanged, the method corrected — costs one more field on PreparedLine (core) if wrong.
Fix wave re-review: all 6 items ADDRESSED, no new breakage. Out-of-scope (offer, not filed): Save cube… during a deferred restore saves the old engine's z/frame under the restored view, then the late note lands beside it.
Post-review fix PF-1: dispatched (opus) BASE c2adcae, implementer af6a114719e487988 (brief pf1-brief.md)
PF-1: DONE, commits cc4acef 7a526c2. Gaps before → after: campus (all 10 lines) +0.4331 ns (+2 samples) → 0.0; GPS (4 lines) +0.2165 (+1) → 0.0; synthetic gain preset +2 samples → 0 under every transform. Engine/dock/site-scope 506 passed; pure+core 1685/5; ruff + mypy clean.
Ruling PF-1a: accept all ten campus lines in the fairness test (on the first four the old code was already exact, so the test could not fail), the hand-placed synthetic gain curve with its guard, the spec §12 correction, and no replacement for the amp_square assert.
Ruling PF-1b: tighten the real-data fairness tolerance from one sample to dt/2 — the raw-record pick and Time zero's own median are the same rule on the same data (gap 0.0 on both surveys), and dt/2 makes GPS (exactly one sample off on c2adcae) a RED pin too — costs a flaky real-data test if a future line set lands a pick between samples (cannot with the same rule).
PF-1 follow-up: 4a7964c (dt/2; GPS + campus both RED on the old pick). Pushed.
PF-1: review dispatched (opus) a2c15915e6ffa728b on c2adcae..4a7964c
PF-1 review: Approved, 0 Critical / 0 Important, 4 Minor (deferred):
PF-1: minor (deferred): an engine test docstring says the envelope picked three rows early "under either preset" (−3 radar, −1 gained).
PF-1: minor (deferred): `PreparedLine.first_break_ns` (None for no signal) shares a name with core `first_break_ns` (row 0 for no signal); `median_first_break`'s docstring and spec §4's "(`first_break_ns`, 0.2)" read ambiguously.
PF-1: minor (deferred): `_raw_first_break` goes through `TimeZero.apply`, one extra record copy per line on the worker.
PF-1: minor (deferred): docstrings refer to `_gained_pick_lands_late`; the test is `test_gained_pick_lands_late`.
PF-1: complete (commits c2adcae..4a7964c, review clean)
Deployed: profile ns_geo_clock (copy of ns_geo; plugin symlink → this worktree; ns_geo untouched). Sandbox ~/nsgeo-clock-walk (campus: A__new, A__old stripped, A__gained, A__lost; gps: Grid1__old stripped, palette amp_heat) + ~/nsgeo-clock-walk.pristine. Expected values measured headless at 4a7964c (scratchpad/probe_walk_restores.py).
G1 walkthrough: READY https://claude.ai/artifact/CbuQJrHdf6hkbKGcCrELrF (db collection `results`, 13 checks R1–R6 G1 E1 S1 S2 W1 W2 F1) — NOT YET RUN.
G1 walkthrough round 1 (2026-11-17, read 2026-11-18): 12 pass (R1–R6 G1 S1 S2 W1 W2 F1), E1 not marked — the user asked what step 1 meant, what step 2 tested, and what "same as G1" meant. E1 rewritten on the page (version 2). Notes: G1 — opening a site should zoom to it → filed #205 at the user's request (roadmap 4aad1f1). S2 — Open site… could not be used until the preparation finished, so the hazard window was out of reach by hand; nothing carried over (the unit test covers it).
G1 walkthrough: E1 PASS (user, 2026-11-18) → 13/13 pass. S2 correction from the user: Open site… was not blocked; they could not get through the "are you sure" dialogs and the file picker before the preparation finished.
Merged origin/main (M16 A + B, roadmap commits) as 2ad4801: two conflicts in slices_dock.py (imports; the __init__ block where M16's foreign-preparation fields meet the _resolution_owed comment) — resolved by keeping both; pushed; local full suites + CI running.

## After the walkthrough

- 13/13 pass (2026-11-18). Follow-ups considered and NOT filed — the author judged none significant; recorded here so they are not lost:
  1. a restore deferred behind a live site task reads its preset's clock at restore time, so a Time zero toggle inside that sub-second window gives the wrong shift;
  2. ticking on a disabled Time zero above a selected time field leaves the field's bound on the radar's clock until the form is re-shown (also before this branch);
  3. `ProcessingDock._show_form` has no guard of its own — part of #15's slot-guard sweep;
  4. Save cube… inside a deferred restore's wait saves the old grid's range;
  5. the c48527d CI timeout (run 44027929704) was #166's whole_site settle hang.
- Filed from the walkthrough at the author's request: #205 (opening a site zooms the map to it).
- Deferred wording minors (PF-1 and task reviews) left as they are.
