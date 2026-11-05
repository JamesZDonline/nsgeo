# SDD ledger — plan: docs/superpowers/plans/2026-10-30-nsgeo-slices-cleanup.md

No spec file: the requirements are GitHub issues #74 #70 #72 #71 #75 #54 plus the plan's "Approved behaviour" (user-approved in chat 2026-10-30). Rulings below are made against that list.

## Pre-flight scan

| Pair / task | Produces → consumes | Found |
|---|---|---|
| T1 → T2 | `source_keys` (every line when the filter empties) → T2's remembered-source test on B | agrees |
| T1 / T3 / T4 `restore_cube` | T1 empty `line_keys` → default; T3 `apply_view(view, spacing_m=…)`; T4 remembers resolution after `apply_view` | agrees; order T1→T3→T4 is the plan's |
| T2 → T4 | `_switch_resumed_grid` runs `_sync_included` (grid-changed branch → `_seed_resolution_defaults`) → T4 lays remembered resolution after every seed | agrees: T2 gets resolution restore for free |
| T2 internal | `_switch_resumed_grid` mirrors `_on_source_changed` minus `_remember_source`/`prepare()` | `_on_source_changed` also clears `_pending_palette`; plan silent → Ruling 2 |
| T2 internal | F-9 test patches `_refresh_source_status`; today's no-target path calls it (slices_dock.py:2234) | agrees |
| T3 → T4 | `grid_radius_spin` → field `"radius_spacings"` | agrees |
| T3 → T5 | `show_scope_widgets` toggles `grid_radius_row` → T5 "grid_radius_spin hidden in site scope" | agrees |
| T3 file list | `plugin.py:916` docstring names `radius_spin` | not in plan's file list → Ruling 3 |
| T4 → T5 | `_on_resolution_edited` (site branch a no-op in T4), `site_resolution`/`remember_site_resolution` | agrees |
| T4 internal | `_seed_resolution_defaults` calls `_seed_dz_z_defaults`; both restore remembered → double restore on a grid change | idempotent, fine |
| T4 internal | leaving the site runs `restore_spins` → `set_spins_quietly` (signals blocked) | cannot read as a user edit; agrees |
| T5 internal | Step 1 pins "untick re-seeds the cell"; Step 4 lays a remembered cell over every seed | CONFLICT → Ruling 1 |
| T5 / T6 | both edit test_plugin_site_scope.py, different tests | agrees |
| T6 internal | Step 5 mutation check of `_sweep` keep-guards in the tree it commits from | hazard (memory: leaked mutant) → Ruling 4 |
| T7 | manual gate: deploy `ns_geo_slices` + walkthrough with the user | tracked below; not a subagent task |

Ruling 1: T5's characterisation test `test_the_site_cell_is_reseeded_only_when_the_included_grids_change` passes as written at Step 2 and is committed. After Step 4, a hand-set site cell is remembered and is laid over the re-seed on an untick (floored by the new floor), matching T4's "remembered values always land after the seed". The test's untick half is then re-pinned on a site with no remembered cell (re-seed observed), plus a new assertion that a remembered cell survives an untick. — The plan's own T5 interface says remembered values overlay every seed; Step 1's wording predates it. — Cost if wrong: a user who changes which grids are ticked keeps their own cell instead of a fresh seed; they type a new one.
Ruling 2: T2's `_switch_resumed_grid` also sets `_pending_palette = None`, as `_on_source_changed` does: the switch is a source change, not a restore, so it must not inherit a palette a pending `restore_cube` owed. — Cost if wrong: none visible; the palette refill on preparation picks the polarity default anyway.
Ruling 3: T3 also rewords `plugin.py`'s `export_geotiff` docstring mention of `radius_spin` (line ~916). — Cost if wrong: none.
Ruling 4: T6's keep-guard mutation check runs in place, by the implementer only, with `slice_layer.py` copied to the scratchpad first and restored + `diff`-verified before any commit; PYTHONDONTWRITEBYTECODE=1; the controller edits nothing meanwhile; the reviewer reads the `slice_layer.py` diff. — Cost if wrong: a leaked mutant; the task review's diff read is the net.
Ruling 5: implementers T1, T2, T3, T6 on sonnet; T4, T5 on opus (guard-completeness judgement across core, session and dock; the scope-switch code's defect history). Reviews on opus. — Cost if wrong: token cost only.

Manual gate: T7 walkthrough on profile ns_geo_slices — NOT YET RUN.

## Progress
Task 1: dispatched (BASE 6b0cac7, implementer agent ac71085faf491756f, sonnet)
Task 1: implementer DONE d118488 (reordered site tests so they fail first; corrected 3 tests pinning the old empty reading); review dispatched (opus, agent a2f4e9cc13ebf19e1)
Task 1: review — spec ❌ 1 Important (This grid's live prune branch in _sync_included leaves an explicit choice emptied by remove_lines as (), while the site reads every line; the new test parks on B and dodges it). ⚠️ items (commit names tests, pushed) checked by controller.
Task 1: minor (deferred): emptying test's comment credits the preset edit with the lines:None rewrite the grid switch already did; `assert before == 4` placed late
Task 1: minor (deferred): This-grid tails of the first two site tests pass without the fix (regression guards only)
Task 1: minor (deferred): test_an_old_cube_record_without_lines_restores_every_line and test_a_cube_record_with_no_lines_key_is_remembered_as_every_line assert the same facts
Task 1: minor (deferred): redundant session.lines_changed.emit() in the two rewritten export tests (remove_lines emits it)
Task 1: minor (deferred): restore_cube assigns _included then overwrites in the empty case; if/else clearer
Task 1: minor (deferred): test_ok_is_greyed_out_on_a_grid_with_no_lines has no docstring
Task 1: fix round 1/5 dispatched (resume implementer; FIX_BASE d118488)
Task 1: fix round 1 implementer DONE 68d637d (prune branch falls back to default when emptied); re-review dispatched (opus, agent a8b48084ffac34aad)
Task 1: fix round 1/5 (1 addressed, 0 open — live prune fallback; commits d118488..68d637d)
Task 1: minor (deferred): a re-imported line the explicit record still names → This grid (default after fallback) reads every line incl. it, site reads only it; same gap pre-exists in D4 `_restore_remembered_source` (kept empty → default). Remedy: "still default" branch re-filters a non-None record.
Task 1: minor (deferred): `_included_is_default` attribute comment (slices_dock.py:194-207) says the flag is set again only by a grid change — now out of date
Task 1: minor (deferred, out-of-scope): set_included with unchanged keys marks the choice explicit but writes no record (slices_dock.py:1027-1043) → after a remove + re-add, This grid and the site disagree
Task 1: complete (commits 6b0cac7..68d637d, review clean after fix round 1)
Task 2: dispatched (BASE 68d637d, implementer agent ab6cb79ef7d82d856, sonnet)
Task 2: implementer DONE_WITH_CONCERNS 7735174 (removed-grid test monkeypatches selected_grid since the panel reselects a neighbour; target path skips _on_prepared/refresh_slice); review dispatched (opus, agent a2850197bad27e5bc)
Task 2: review — Needs fixes: Important 1 (plan-mandated) the window time is placed via _sync_grid_slider on the LEFT grid's axis, clamped, then carried to B by the debounce (probe: B opened at 31.57 not 78.98 ns); test sits at slider 0 with shared t0 so cannot see it. Important 2 removal outcome depends on row position (last row → panel reselects neighbour → opens B; middle row → selection clears → A); test monkeypatches selected_grid.
Ruling 6: Important 1 is a plan defect in Task 2's call order. On the target path `_pending_top_ns` must survive until This grid's engine holds the selected grid's axis, and a pending carried-over time wins over a slider time read off the left grid's axis. — Approved behaviour 2 says "at the same window time"; the plan's order breaks it. — Cost if wrong: none beyond rework; the old path is unchanged.
Ruling 7: Important 2 — the rule is "the grid the site list shows selected at the moment of the switch". Both real outcomes are right: removing the selected last row leaves Qt's neighbour selection visible, so This grid opens that neighbour; removing a middle row clears the selection, so This grid comes back on its own grid. Pin both real flows without monkeypatching; keep the monkeypatched test only as the stale-id guard for `_grid_to_resume`'s "offered by grid_combo" check, renamed to say so. The panel's reselection is not changed. — Cost if wrong: a user who removes the selected last grid gets its neighbour in This grid instead of This grid's own; one combo pick away.
Ruling 8: review Minor 3 ("as it was left" assert cannot fail: the site's cell and palette equal A's defaults) upgraded to Important and fixed in round 1 — a test that cannot fail is the rubric's "asserts nothing". — Cost: none.
Task 2: minor (deferred): concern 3 mis-described — right after the click the layer still shows the site mosaic until the seeded debounce clears it (~120 ms); in the deferred case the debounce redraws A's slice at B's resolution while the combo says B
Task 2: minor (deferred): engine resolution after the switch depends on the debounce firing (only when a seed differs from the site's spins); fix round 1 asked to check whether Ruling 6's fix closes it
Task 2: minor (deferred): F-9 finally tested only on the old path; a raise inside _switch_resumed_grid after the combo moved leaves combo on B, engine on A, maybe no pending prepare
Task 2: fix round 1/5 dispatched (resume implementer; FIX_BASE 7735174; findings: window time axis, removal flows, unfailable as-left assert)
Task 2: fix round 1 implementer DONE ba54eab (_pending_top_ns kept on target path, _apply_resolution prefers it, new _resolution_owed flag; both removal flows pinned; as-left test non-default); re-review dispatched (opus, agent aed0cd8c619520b71)
Task 2: fix round 1/5 (3 addressed, 1 new open — stale _pending_top_ns hijacks later resolution changes after a survey close/reopen under Whole site; commits 7735174..ba54eab)
Ruling 9: round 2 also takes (a) the re-reviewer's new Minor — set_scope's top read ignores a pending time when engine.z is set — and (b) its "out-of-scope" observation that in the outlived-cancel wait window the seeded debounce applies B's resolution to an engine still prepared on A and emits a spurious CoverageError. (b) is outside the fix diff but inside Task 2's own diff (7735174) and shares the fix's mechanism (`_resolution_owed` → `_apply_resolution` defers). — Both are cheap and the loop is running anyway; leaving (b) ships a user-visible spurious error on the new path. — Cost if wrong: a slightly larger fix diff to re-review.
Task 2: minor (deferred): nit — tests set dock.plugin_for_test = plugin; pass plugin to the helper instead
Task 2: minor (deferred): no test isolates the case where no seeded spin differs from the site's spins (owed apply closes it by construction; probe confirmed)
Task 2: fix round 2/5 dispatched (resume implementer; FIX_BASE ba54eab; findings A stale pending top, B set_scope top read, C spurious error in outlived-cancel window)
Task 2: fix round 2 implementer DONE 1ef7c74 (_apply_resolution consumes pending top; set_scope prefers pending; defers while _resolution_owed; _on_prepared syncs slider; tests filter the legitimate 'did not stop in time' note); re-review dispatched (opus, agent af02b30d9df8bd389)
Task 2: fix round 2/5 (3 addressed, 0 Critical/Important open; new Minor: set_scope("site") clears _resolution_owed → engine keeps A's resolution after window→site→grid; commits ba54eab..1ef7c74)
Task 2: re-review out-of-scope (Task 2 code): (i) window time lost on the return path after re-entering the site inside the wait window (no-target _sync_grid_slider on the left axis); (ii) CoverageError when the switch lands on the grid the engine already holds (raw-header z0 re-seed, prepare() no-op so no clamp, owed apply pushes -11.086) — repeats on every edit until z0 fixed by hand; (iii) slider drag inside the window discarded at landing (by design)
Ruling 10: run fix round 3 for the new Minor plus out-of-scope (i) and (ii), instead of deferring them to the final wave. — Task 4 builds directly on this path (seeds, clamp, owed apply will carry remembered resolution), and (ii) is a persistent user-visible error; fixing it under Task 4's changes would mix two reviews. Breaks the "out-of-scope never extends the loop" rule on purpose. — Cost if wrong: one more round of tokens; cap still 5.
Task 2: minor (deferred): slider drag inside the outlived-cancel window is discarded at landing (pending time wins) — by design, note for walkthrough
Task 2: minor (deferred): theoretical stuck _resolution_owed if prepare() raises before the flag is consumed (consume before prepare would close it) — asked for in round 3 as a cheap hardening
Task 2: minor (deferred): the slider move in test_opening_the_selected_grid_waits_for_a_site_task_that_outlived_its_cancel lands after the window closed, so it does not exercise C (the other outlived test does)
Task 2: minor (deferred): after closing a survey while Whole site shows, the next survey's This grid opens at the closed survey's site time (cosmetic)
Task 2: fix round 3/5 dispatched (resume implementer; FIX_BASE 1ef7c74; owed flag kept across site, return-path time, clamp before owed apply, consume flag before prepare)
Task 2: fix round 3 implementer DONE fc68626 (5 new tests; owed flag kept across site; no-target path defers time while owed; clamp before owed apply on no-op prepare; flag consumed before prepare); re-review dispatched (opus, agent ab1da49d567b6acaf)
Task 2: fix round 3/5 (4 addressed + comment, 0 open; commits 1ef7c74..fc68626)
Task 2: minor (deferred, should fix in final wave): removal-in-window test (test_plugin_site_scope.py:1190-1195) catches the bug only by timing — wait for `not site_engine.has_live_task and not dock._resolution_owed` before asserting
Task 2: minor (deferred): a refused owed preparation (e.g. amplitude transform → engine.choice None) leaves the site mosaic layer on the canvas under This grid scope (error shown); pre-existing on the target path, now also on the no-target round trip
Task 2: complete (commits 68d637d..fc68626, review clean after fix round 3)
Task 3: dispatched (BASE fc68626, implementer agent af9bbb4eff498d6c2, sonnet)
Task 3: implementer DONE_WITH_CONCERNS d2a4715 (qgis 1198 vs plan's 1320; spacing edit updates label + radius_cells but does not restart the debounce; a stray `ruff format docs/` was reverted before commit)
Correction: the plan's qgis baseline "1320" was wrong. Controller collected 1165 tests at 6b0cac7 (temporary detached worktree, removed); 1198 at d2a4715 = 1165 + tasks 1-3's added tests. No tests lost.
Task 3: review dispatched (opus, agent a57bd3ecdec62244a)
Task 3: review — Needs fixes: Important 1 seed `grid_radius_spin.setValue(DEFAULT_RADIUS_SPACINGS)` (slices_dock.py:1739) unguarded on a grid switch, against the coordinator's ruling (Task 4 would remember it); Important 2 a line-spacing edit updates label + radius_cells but the map (and so an export) keeps the old fill until another redraw — introduced by #72; test checks label only.
Ruling 11: review Minor 3 (plan-mandated: a 2-decimal, 0–10 spacings box cannot hold every old metres radius — e.g. 0.127 m → 0 cells instead of 1; 6.0 m clamps to 10 spacings) is accepted and deferred, not fixed: the approved behaviour fixes 2 decimals and 0–10 to match Whole site, the old box stepped by 0.05 m which converts exactly at 0.25/0.5/1.0 m spacings, and the error is at most one cell at a rounding boundary. — Cost if wrong: an old cube with an odd hand-typed radius reopens one cell off; report it to the user in the final summary.
Task 3: minor (folded into fix round 1 as cheap, same lines): no test for the no-grid state; stale `radius_spin` in _seed_resolution_defaults docstring (:1714); awkward test wording (:852)
Task 3: fix round 1/5 dispatched (resume implementer; FIX_BASE d2a4715)
Task 3: fix round 1 implementer DONE 47e48ff (seed signal-blocked; rebuild_source redraws when radius cells changed, grid scope, prepared, not owed; no-grid test; docstring/comment); re-review dispatched (opus, agent ac7bf50b8b14c77a8)
Task 3: fix round 1/5 (2 Important + 3 cheap addressed, 0 open; commits d2a4715..47e48ff)
Task 3: minor (deferred, should fix in final wave): `_filled_radius_cells` is written only in refresh_slice's fill branch, so in coverage mode it goes stale and every unrelated rebuild_source (presets_changed…) redraws; also assigned before fill() runs. Fix: write it on every successful draw (after fill returns) or skip the elif while coverage is checked.
Task 3: minor (deferred): no test for "never in site scope" / "quiet in the wait window" on the spacing-edit redraw (guards evident in code)
Task 3: minor (deferred, pre-existing): radius_cells() reads cell_spin live, not the engine's applied cell — during the debounce or after a refused Resolution, slider redraws and export use a cell the frame doesn't have
Task 3: complete (commits fc68626..47e48ff, review clean after fix round 1)
Task 4: dispatched (BASE 47e48ff, implementer agent a95b64808c99ac8d5, opus per Ruling 5)
Task 4: implementer DONE_WITH_CONCERNS 88ba267 (clamp fallback also catches a user-typed reversed range at landing; pre-existing: removing This grid's grid while Whole site shows seeds/restores onto the site's spins; added 2 site-scope switch tests)
Task 4: review dispatched (opus, agent ac9abb74310e2671c)
Task 4: review — Spec ✅, Approved, 0 Critical/Important. Set-site audit verified.
Task 4: minor (deferred, should fix in final wave): the inner restore at the end of `_seed_dz_z_defaults` has no test (lines imported after the grid is picked — the ordinary new-survey flow); reviewer's probe probe71r confirms behaviour
Task 4: minor (deferred): floor test runs on a 6×6 m grid where the floor equals the box minimum, so it can't tell them apart (30 m probe confirms ordering)
Task 4: minor (deferred, should fix in final wave): `_clean_resolution` (project.py:234) and the existing gain cleaner raise OverflowError on a huge integer (10**400) → load_site fails instead of reading unset (Review Focus 2); try/except closes it
Task 4: minor (deferred): clamp fallback also turns a user-typed reversed pair still showing at landing into the prepared range; record keeps the typed values (accepted; brief wording covers it)
Task 4: minor (deferred): site-scope fallback test doesn't assert clean; placeholder comment cites "Task 5" not #71 (Task 5 replaces it)
Ruling 12: Task 5 also closes the site-scope bleed (Task 4 concern 2 + review Minor 4): while Whole site shows, This grid's `_sync_included` (grid removed → combo falls back; lines imported under a not-yet-seeded grid) seeds and restores This grid's values onto the shared Resolution spins the site is using, with signals live (old `_note_z_edit` even set z_custom). Fix: in site scope, This grid's seed/restore leave the shared spins alone and stay owed (`_dz_z_seeded_for` not marked); on return to This grid, if the combo's grid differs from the grid `_grid_spins` was captured for, seed + restore that grid instead of restoring the stale snapshot. — Pre-existing since M12 but widened by Task 4's restore, and in the code Task 5 rewrites. — Cost if wrong: extra scope in Task 5; if the design is wrong the site's spins still get clobbered in a rare flow.
Task 4: complete (commits 47e48ff..88ba267, review clean)
Ruling 13: Task 5 keeps capture_spins/restore_spins quiet (signal-blocked) — no change. — Cost: none.
Task 5: dispatched (BASE 88ba267, implementer agent a3fa270614639cef1, opus; carries Rulings 1, 12, 13)
Task 5: implementer DONE_WITH_CONCERNS f4e8930 (characterisation) 7ac9bf8 (feature + Ruling 1) 7887292 (Ruling 12); qgis 1227; in-place mutation run restored+cmp-verified, tree clean; concerns: seed briefly drops to headers when ready bounds match; one remembered z bound beyond headers → one Resolution error on entering before a grid is ready; site clamp only narrows
Task 5: review dispatched (opus, agent acd7715524582a34c)
Task 5: review agent stopped by a session restart; resumed via SendMessage (same agent acd7715524582a34c)
Task 5: review — Needs fixes: Important 1 (partly plan-mandated) a remembered site z field sets z_custom, so seed_z_from_ready only narrows from the current spins against the ready union-so-far → on reopen the range is cut to the first-ready grid's (probe: dz-only remembered → z1 16.41 instead of 99.56; remembered t1=60 never returns); tests use same-range site3 grids.
Ruling 14: the site's z bounds are custom per field, from the remembered record, not one `z_custom` flag. On every ready-set change: dz = remembered dz_ns if any, else the seed; z0 = clamp(remembered t0_ns, ready union) if remembered, else the ready union's low (header seed before any grid is ready); z1 likewise; if the clamped pair would be empty, both take the ready bounds (Review Focus 1). A hand edit is remembered at once, so the record is the source of truth; clamping starts from the remembered value, never from the current spin. — Approved behaviour 4 says "each field is remembered on its own"; the plan's single flag contradicted it, and the probe shows real data loss with mixed-range grids. — Cost if wrong: a site z range the user typed but whose record write failed would re-seed; none expected since remembering is synchronous.
Task 5: minor (folded into fix round 1, cheap): Ruling 1 assertion uses a re-tick, no floor check, no site-cell-floor test; no test that a remembered cell alone leaves z re-seeded; comment on Ruling 12's no-lines fallback
Task 5: minor (deferred): remembered site cell laid even when nothing is included (harmless); pre-existing ready seed falling to headers (concern 1); single remembered bound past the opposite seed → one error (concern 2, rare); uneven docstring wrap at slices_dock.py:1772-1775
Task 5: fix round 1/5 dispatched (resume implementer a3fa270614639cef1; FIX_BASE 7887292; Ruling 14 + cheap items)
Task 5: fix round 1 implementer DONE 4886510 (z_custom removed; SiteScope.seed_z per-field from the record; cheap items done)
Task 5: re-review dispatched (opus, agent a29c15d86faa1b25f)
Task 5: fix round 1/5 (1 Important + 2 cheap addressed, 0 open; commits 7887292..4886510)
Task 5: minor (deferred): set_spins_quietly calls setValue even when unchanged → a ready tick while the user is typing can reformat half-typed text (pre-existing for z0/z1, now also dz when remembered)
Task 5: minor (deferred, already in #75): an unchosen site dz follows the first-ready grid's dt
Task 5: note: the plan text still describes z_custom/seed_z_from_ready (plan lines ~219-224); Ruling 14 supersedes it
Task 5: complete (commits 88ba267..4886510, review clean after fix round 1)
Task 6: dispatched (BASE 4886510, implementer agent a1ca69a6a593bbbf8, sonnet; carries Ruling 4)
Task 6: implementer DONE_WITH_CONCERNS fb14a06 (qgis 1238; keep-guard M1 'keep self.path.name' SURVIVED both tests — redundant while the layer lives, matters only when the layer is gone after a good tick; M2 caught; ds = None already in finally, swapped for ds.Close(); corrupt-file assert allows sidecars)
Task 6: review dispatched (opus, agent a41aa4ce1bfd5fb2e)
Task 6: review — Needs fixes: Important 1 M1 is a real test gap (in the corrupt case self.path != live source; under M1 the last good file is deleted) — add `assert not sl.layer.isValid() and read != sl.path` and `assert sl.path.exists()` (probe m1probe confirms it kills M1); Important 2 the rewritten `_sweep` docstring says the two kept files differ when setDataSource raised — they are the same then.
Task 6: minor (folded into fix round 1, same docstring/test): `_sweep` summary line and "repoint or create succeeded" overstatement; default-choice reopen test never stores `"lines": null` (do a B→A round trip before saving)
Task 6: minor (deferred): velocity test shares resolve_velocity with the code under test (brief-prescribed)
Task 6: fix round 1/5 dispatched (resume implementer a1ca69a6a593bbbf8; FIX_BASE fb14a06)
Task 6: fix round 1 implementer DONE 8291686 (M1 and M2 now both caught; docstring corrected; reopen test stores lines: null)
Task 6: re-review dispatched (opus, agent a369f413c5845702b)
Task 6: fix round 1/5 (2 Important + 2 Minor addressed, 0 open; commits fb14a06..8291686)
Task 6: minor (deferred): corrupt-file test's docstring (test_plugin_slice_layer.py:171-173) still says "only what the layer reads"; _sweep docstring "still names the last good one" loose in a rare removed-layer + junk-create case
Task 6: complete (commits 4886510..8291686, review clean after fix round 1)
Final review: dispatched (opus, agent ae9de2bfa5c3918db; range 7069959..8291686; triage of deferred minors requested)
Final review: With fixes — Important 1: a hand-set z bound is lost after the empty-range fallback in both scopes (edit the other end → record holds t0 > t1 → restore snaps back; reopen drops the pair). Minors 1-7; deferred triage: Fix L47 L77 L90 L98 L100 (L132 optional); File L46 L48 L73 L78 L92 L118 + Minor 5; Leave the rest.
Ruling 15: Important 1 fix — in both branches of `_on_resolution_edited`, for t0_ns/t1_ns: if the record holds the other end and the pair would be empty, also remember the other end's SHOWN spin value in the same call (what the user sees is what they chose). Clamps still write nothing. — The user's edit made after a fallback is an edit against the shown range; Review Focus 1 never considered it. — Cost if wrong: one extra remembered bound the user never typed (but did see and accept).
Ruling 16: the final fix wave takes Important 1, Minors 1, 2, 3, 4, 6, 7 and L132 (docstrings). Issues to file (L46, L48, L73, L78, L92, L118, Minor 5) are held for the user's go — filing is outward-facing. — Cost if wrong: none; they're listed in the final message.
Final fix wave: dispatched (opus, agent af1f2ddee3797658d; FIX_BASE 8291686; brief final-fix-brief.md)
Final fix wave: DONE 1e09ca6 (Item 1, Ruling 15) 8a3fd0c (Items 2-6; Item 5 = record radius after a successful draw in both branches); qgis 1243, core+pure 823/3 skipped, lint+mypy clean
Final fix wave: re-review dispatched (opus, agent aa79980669ccd205a)
Final fix wave: re-review — all 6 findings ADDRESSED, no new Critical/Important (commits 8291686..8a3fd0c)
Ruling 17 (parked residual): keyboard tracking on the z spins means typing z1 passes through prefixes; a prefix at/below a remembered below-data z0 (clamped up) momentarily empties the pair and Ruling 15's extra write replaces the remembered z0 with the shown one (probe: bounds (35, 99.56), remembered t0 30, type "45" → record {t0: 35, t1: 45}). Parked, not fixed: no second fix wave by process; needs data starting at a positive time (real DZT starts near/below 0); the only loss is a below-data start that would return after a later crop. Fix later: also require the new value be non-empty against the shown other end, or setKeyboardTracking(False) on the z spins. — Cost if wrong: on positive-start data a remembered below-data z0 is replaced by the clamped value after typing z1.
Final review: complete (7069959..8a3fd0c)
Merged origin/main (8b7dc43): core+pure 842 passed 3 skipped, qgis 1309 passed, lint+mypy clean; pushed. Profile ns_geo_slices created (copy of ns_geo, plugin linked to this worktree).
Task 7: deployed — profile ns_geo_slices (copy of ns_geo; plugins/nsgeo_qgis -> this worktree; ns_geo untouched). Headless app launch (`QT_QPA_PLATFORM=offscreen qgis --profile … --code`) hung for EVERY profile here (ns_geo_fixes too), so no app-level smoke; import check through the profile link passed (file → this worktree, classFactory, new methods present). Walkthrough page https://claude.ai/artifact/PKBWF5xrSNJXhjun6zcCXZ (db `results`, 21 checks, empty on publish). Manual gate: NOT YET RUN — waiting on the user.
Task 7: walkthrough RUN 2026-10-31 — 17 pass, 1 skip (E2), C3 and E5 (optional) not marked; user: "walk done. looks good" and asked for PR + merge + release 0.2 + zip.
Release: 3126c0a bumps plugin+core to 0.2.0, docs/releases/0.2.0.md, metadata changelog, README, guide; check_tag('v0.2.0') passes. PR #99 opened; CI pending.
