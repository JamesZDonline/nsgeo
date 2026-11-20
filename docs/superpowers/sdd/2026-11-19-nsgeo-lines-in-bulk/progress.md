# SDD ledger — plan: docs/superpowers/plans/2026-11-19-nsgeo-lines-in-bulk.md

Spec: docs/superpowers/specs/2026-11-19-nsgeo-lines-in-bulk-design.md (binding).
Branch nsgeo-lines-in-bulk, worktree .worktrees/nsgeo-lines-in-bulk, plan commit f1006cd.
Models: implementers sonnet, task reviewers opus, final review opus (memory: subagent-model-tiers).

## Setup
- Worktree .venv built; nsgeo imports from the worktree. Real data linked (dir symlinks, README skipped).
- Baseline core+pure at f1006cd: 2046 passed, 9 skipped, 19 xfailed (18 min under load)

## Pre-flight scan

| Pair / task | Shared | Produces → consumes | Finding |
|---|---|---|---|
| T1 / T2 | survey_dock.py, plugin.py, test_plugin_survey_dock.py | T1 `selected_line_keys()`, `set_lines_velocity` → T2 | consistent |
| T1 / T3 | session.py, ui/preset_box.py, test_plugin_session_bulk.py | T1 `apply_preset_to`, `migration_note` → T3 | consistent (T1 creates preset_box.py with the function only) |
| T3 / T4 | ui/import_dialog.py, test_plugin_import_dialog.py | none | different functions; T4 after T3 |
| T2 / T3, T1 / T4, T2 / T4 | none | none | — |
| T1 self | | | test name says "mag or cut" but main has no mag: see R1. "one dirty_changed" can't be counted on an already-dirty site: R2 |
| T2 self | | | Step 1 is a measuring test that pins what it measured; layers.py edit allowed only if Step 1 needs it. Consistent |
| T3 self | | | core tests on core venv, the rest qgis tier; consistent |
| T4 self | | | `nsgeo_qgis/numbers.py` would shadow stdlib `numbers` if the package dir ever lands on sys.path: R3 |

Ruling R1: T1's test is `test_the_bulk_items_never_offer_a_cut_key` (cut only); mag keys are M19a's merge concern (spec §8) — main has no mag rows to test — if wrong, M19a's merge adds the mag case.
Ruling R2: session tests assert dirtiness by saving first and checking `session.dirty` afterwards, not by counting `dirty_changed` — it only fires on a transition — costs nothing.
Ruling R3: T4's module is `nsgeo_qgis/decimal_input.py` (not `numbers.py`), test `tests/pure/test_pure_decimal_input.py` — avoids shadowing stdlib `numbers` (numpy imports it) — cost: a rename.

## Tasks
- Task 1: dispatched (BASE f1006cd, implementer sonnet, agent a6925e3e501206301)
- Task 1: session restarted mid-task; implementer resumed with its uncommitted work in the tree
- Task 1: implementer DONE_WITH_CONCERNS, commit 2b54d63 (observations only: menu-text helper in old tests, migration note wording per source, 3-decimal message, dock tests not seen RED). Reviewer opus dispatched (agent a11d15a5a7f633ab2).
- Task 1: review (opus) spec ✅, no Critical/Important; CI green on 2b54d63 incl. QGIS 4.2.
- Task 1: minor (deferred): M1 bulk velocity start value: the shared-override branch is redundant (resolved_velocity already returns the override); misleading test comment
- Task 1: minor (deferred): M2 typing 0 in the bulk velocity box gives a red "could not set the velocity" bar (min 0.0 but VelocityModel refuses 0); raise the minimum or refuse before the call
- Task 1: minor (deferred): M3 bulk velocity report rounds to 3 decimals while the box takes 4
- Task 1: minor (deferred): M4 new strings are inline literals, not module constants the tests import (globals ask for constants)
- Task 1: minor (deferred): M5 menu→action wiring triggered from the built menu only for Set velocity; preset submenu (n=name binding), Apply steps and Clear not triggered from the selection (spec §9 "reaches exactly the selected lines")
- Task 1: minor (deferred): M6 "Also removed" line built unguarded inside _remove (catches only KeyError/ValueError)
- Task 1: minor (deferred): M7 step count via getattr(..., "entries", ()) — use len(stack)
- Task 1: minor (deferred): M8 apply_stack_to plants an empty stack on a source that had none (insert=True); insert=False avoids it
- Task 1: minor (deferred): M9 Clear prompt reads "1 of these 1 line" for a one-line selection
- Task 1: minor (deferred): M10 test name test_a_mixed_selection_offers_only_removal is now stale
Task 1: complete (commits f1006cd..2b54d63, review clean)
- Task 2: dispatched (BASE 2b54d63, implementer sonnet, agent ac41bb14f9a3df40e)
- Task 2: implementer DONE_WITH_CONCERNS, commit ed23c6d. Measured: a refill emits no selectionChanged and leaves stale ids; no refill guard added, layers.py untouched; panel re-announces after every rebuild. Concerns: held-modifier immunity by construction, 3.44-only measurement (check 4.2 CI). Reviewer opus dispatched (agent a8093673a2a044fc7).
- Task 2: review (opus) spec ✅, no Critical/Important; CI green on ed23c6d (3.44 + 4.2 + smoke).
- Task 2: ⚠️ confirmed as a real gap → fix loop: the plugin supports QGIS 3.40 (metadata qgisMinimumVersion=3.40), where refill behaviour is unmeasured (3.40 only smoke-tested); spec §3.4 requires the selection to survive "whatever QGIS does" during a refill. Needs a refill bracket MapLink reads + stale-id safety in the announce path.
- Task 2: Minor 4 adjudicated as a spec deviation → fix loop: rebuilds re-unfold grids holding selected lines (overriding fold state on every rebuild); spec §3.1 unfolds only for a selection arriving from the map.
- Task 2: minor (deferred): m1 O(rows×selected) item_for_key lookups in select_lines/_restore_line_selection/_select_rows; per-feature getFeature in announce; select_lines reads geometry — one-pass key→item map, NoGeometry request
- Task 2: minor (deferred): m2 bare setCurrentItem in _select_rows doesn't move the Shift anchor while Shift is held (QGIS's add-to-selection modifier); pre-existing in _follow_current
- Task 2: minor (deferred): m3 select_lines makes present[0] (map id order) current; prefer the open line if among keys, else first in tree order
- Task 2: minor (deferred): m4b site root row never unfolded for a map selection
- Task 2: minor (deferred): m5 stale comments ("Twice on purpose" above a single call; "current line always wins" in _restore_selection)
- Task 2: minor (deferred): m6 _announce_selection failure logged as "could not open the selected line"
- Task 2: minor (deferred): m7 re-opening the already-open line (e.g. selecting a mark on it) leaves a multi-selection (open_line emits nothing for the current key)
- Task 2: fix round 1 implemented 5b28937 (refilling_lines depth counter in SiteLayers, _on_selection ignores refills, stale ids skipped; unfold only from select_lines). Re-review sonnet dispatched (agent af8e2973096754154).
- Task 2: fix round 1/5 (2 addressed, 0 open — F1 refill bracket + stale ids, F2 unfold only from the map; commits ed23c6d..5b28937)
- Task 2: minor (deferred): duplicated "# noqa: SIM118" comment in _announce_selection; `for item in items if unfold else []` one-liner; F1 test filters messages by text not level
Task 2: complete (commits 2b54d63..5b28937, review clean)
- Task 3: dispatched (BASE 5b28937, implementer sonnet, agent afc3ed514c3795adc)
- Task 3: implementer DONE_WITH_CONCERNS, commit 51cc315 (TDD lapse: session/PresetBox/dialog tests not seen RED; one failure of test_a_refine_for_a_window_left_behind_never_draws called a pre-existing flake). Reviewer opus dispatched (agent aea32b23a192c8fff), asked to judge both.
- Task 3: review (opus) spec ✅ on behaviour; Important: I1 CI lint red (ruff I001/E501 + format), I2 grid-over-site rule untested, I3 put-back path never run (duplicate-key check returns first). Flake claim upheld (slot returns at its guard throughout that test).
- Task 3: Minor 5 adjudicated as a real gap → fix loop: site_closed reads as "preset deleted" (false note); site_opened not connected, so after reopening the box stays greyed on None and imports with no preset.
- Task 3: Minor 7 adjudicated → fix loop: the plan-mandated "not for None" test proves nothing (set_slice_preset(gid, None) on an empty record is a no-op).
- Task 3: minor (deferred): m4 Slices note can go stale if the grid gains lines by another route while the dialog is open (no lines_changed/grids_changed refresh)
- Task 3: minor (deferred): m6 put-back with the Slices panel on the grid leaves {"lines": None} and the combo on P (nearly unreachable behind the duplicate-key check)
- Task 3: minor (deferred): m8 tests reassign d.preset_box._on_presets_changed after connect (no effect; misleading comment)
- Task 3: minor (deferred): m9 clash message and "Processing preset" label inline, not constants (gps_import.ALREADY_IN_SITE exists)
- Task 3: minor (deferred): m10 PresetBox(session: Any) — brief says SiteSession
- Task 3: minor (deferred): m11 the Slices slot's _scope/_updating guards untested
- Task 3: minor (deferred): m12 migration_note in _refresh_note outside a try (reached from unguarded set_grid via _grid_changed)
- Task 3: fix round 1 implemented b7b5408 (lint/format/mypy clean; I2 I3 F5 F7 tests). 51cc315 CI: only lint failed; 3.44 + 4.2 plugin jobs passed. Re-review sonnet dispatched (agent a6a0a89d7689951dd).
- Task 3: fix round 1/5 (5 addressed, 0 open — I1 lint, I2 grid-over-site test, I3 put-back test, F5 site close/open, F7 None outcome; commits 51cc315..b7b5408)
- Task 3: minor (deferred): GPS dialog's site-last path after a site reopens not pinned (same set_grid code); _on_site_opened failure logged twice
Task 3: complete (commits 5b28937..b7b5408, review clean)
- Task 4: dispatched (BASE b7b5408, implementer sonnet, agent a394f79ca43b943fd; R3 carried: decimal_input.py)
- Task 4: implementer DONE, commit 1523d29 (decimal_input.py per R3; RED shown for every new test; stash used tagged and dropped, stash list empty). Reviewer opus dispatched (agent aa5deae416077a5c8). CI on b7b5408 was cancelled by the 1523d29 push (superseded).
- Task 4: review (opus) spec ✅, no Critical/Important.
- Task 4: minor (deferred): M1 the re-entrancy test's label assertion checks nothing (fails only via the seen proxy); add `assert not d.rows[0].label_edited`
- Task 4: minor (deferred): M2 ParamForm picks its message assuming parse_decimal refuses only what float refuses or non-finite; choose with math.isfinite(float(text))
- Task 4: minor (deferred): M3 edit_lines_dialog.py:863/:872 still float(text.replace(",", ".")) — list in the PR beside the #16 files (M19a's file)
- Task 4: minor (deferred): M4 test name says "comma" but also runs nan/inf
Task 4: complete (commits b7b5408..1523d29, review clean)
- Final review: dispatched (opus, agent a5b3ba4cd0a7ee3ff) over f1006cd..1523d29 with deferred-minor triage
- Final review (opus): CI green on 1523d29 (all jobs). Important 1: selected_line_keys raises ProjectError (not KeyError) when another site opens with lines selected and none open → Critical "could not rebuild the survey tree". Minor 2 (Delete needs panel focus after a map gesture; walkthrough instructions), Minor 3 (bulk menu / Remove default assume non-cut keys are lines: breaks on M19a mag keys), Minor 4 (apply_preset_to / remember_import_preset unguarded in both accepts). Triage: all deferred minors can wait except T4 M3 (PR body: edit_lines_dialog comma parse).
- Ruling: the final fix wave takes Important 1 + Minor 3 (filter to keys the session knows as lines) + Minor 4 (guard the new writes in accept) + the stale "current line always wins" comment — all cheap and in files already touched; Minor 3 makes M19a's merge mechanical — cost if wrong: a slightly larger fix diff.
- Final fix wave: 7301cf3 (F1 site switch, F2 known-lines gate incl. destagger/Edit/Move, F3 preset_notice + messages, F4 comments). Concern: test_import_dialog::test_remove_and_reorder fails when run after survey_dock + line_selection in one process (passes alone) — investigating whether this branch causes it. Re-review sonnet dispatched.
- Final fix wave re-review (sonnet): F1–F4 ADDRESSED; no new Critical/Important. Residual minors (deferred): F3 failures reported via status/notice but not _log'ged; preset_notice surfacing through plugin.finished untested; remember_import_preset skipped when apply fails (undocumented).
- Order dependence traced: test_plugin_line_selection.py leaves Qt's remembered modifiers at Ctrl after its last Ctrl-click (survey_dock.py alone does not); a later selectRow adds instead of replacing, failing import_dialog::test_remove_and_reorder. Not hit in CI only because import_dialog sorts first. Ruling: fix in the new test file (autouse fixture releasing Ctrl + asserting NoModifier) — a test-only change caused by this branch — cost if wrong: none to product code. Dispatched haiku.
- Ctrl-leak fix 44de38e (haiku): autouse fixture releases Ctrl and asserts NoModifier; reproduce 1 failed → 11 passed. Its trailer names Haiku (allowed per memory subagent-model-tiers); the subagent's force-push to rewrite the trailer was denied by auto mode and NOT retried by me — no history rewrite; local == origin.
- Deploy: profile ns_geo_bulk (copy of ns_geo, plugin symlink → this worktree); sandbox ~/nsgeo-bulk-walk (+ .pristine) from hand-fits site-1 copy (Grid1 lines removed for GPS import, Grid3 emptied, Grid2 lines 41–60 removed), built by scratchpad walk/make_sandbox.py.
