# SDD ledger — plan: docs/superpowers/plans/2026-09-18-nsgeo-qgis-plan3-m7.md

Spec: docs/superpowers/specs/2026-09-18-nsgeo-qgis-plan3-design.md (binding authority)
      parent: docs/superpowers/specs/2026-09-10-nsgeo-qgis-plugin-design.md
Branch: nsgeo-m7 · worktree .worktrees/nsgeo-m7 · start commit 79401fd
Model tiers (user standing instruction): implementers sonnet; ALL reviews and
re-reviews opus. Subagent commits must NOT mandate a specific Co-Authored-By model name.

## Baseline before Task 1 (verified 2026-09-18, in this worktree)
pure+core 363 passed / 2 skipped · QGIS tier 372 passed · ruff clean
Both venvs built here; ten real DZT + DZX symlinked into
packages/nsgeo-core/tests/data/local/ (README.md there is TRACKED — do not symlink it).

## Pre-flight conflict scan

### Pairs sharing a file or an interface
| # | Tasks | Shared artifact | Produces → consumes | Finding |
|---|---|---|---|---|
| 1 | 1 → 2 | `session.py` → `ui/profile_dock.py` | `preview_changed(str,int)`, `preview_key`, `preview_trace`, `display_key` | Clean. Names match between T1's Produces block and T2's Consumes block, checked one by one. |
| 2 | 1 → 3 | `session.py` → `map_link.py` | `display_key`, `preview_key`, `preview_trace`, `current_trace`, `selection`, `is_open` | Clean. All six exist after T1 (four new, two pre-existing). |
| 3 | 1 → 4 | `session.py` → `map_link.py` | `set_preview(key, trace)`, `clear_preview()` | Clean. |
| 4 | 1 → 4 | `session.py` → `loader.py` | `preview_changed` | Clean. T4 connects it; signature `(str, int)` matches `_on_preview_changed(key, _trace)`. |
| 5 | 3 → 4 | `map_link.py` | T3 creates the module; T4 adds `QTimer` to the QtCore import, `_dwell`/`_last_point` to `__init__`, three slots | Clean — T4 Step 3 states the import edit explicitly rather than assuming it. |
| 6 | 3 → 4 → 5 | `map_link.py` `dispose()` | T3 writes it; T4 prepends `_dwell.stop()`; T5 rewrites it whole | Clean, but only because T5's version is a strict superset of T4's and T4 says so. Verified line by line. |
| 7 | 3 → 4,5 | `tests/qgis/test_plugin_map_link.py` | T3 creates the file and the `linked` fixture; T4 and T5 append and reuse it | Clean. T5's `_feature_id` helper takes `layers` from the same fixture tuple. |
| 8 | 1 → 5 | `preview_changed` vs. the no-orphan test | T1 declares it; T2/T3/T4 connect it | Clean by T5, which is when the test first exists. |
| 9 | 2 ↔ 3,4,5 | none | T2 touches only `profile_dock.py` | Clean — no shared file. |
| 10 | 5 alone | `plugin.py`, `README.md`, `test_plugin_loads.py`, `test_no_orphan_signals.py` | — | Clean. |

### Each task against itself
| Task | Finding |
|---|---|
| 1 | Clean. `line_for_key` verified to raise `KeyError` (session.py:383-388), which is what `test_preview_of_an_unknown_key_raises_and_changes_nothing` expects. |
| 2 | **Conflict — see Ruling 2.** `ProfileDock._pick` (profile_dock.py:578) emits `self.pick_requested.emit(self._key, ...)`, and T2 redefines `_key` as the DISPLAY key. |
| 3 | Clean. Teardown order (`link.dispose()` then `layers.detach()`) verified against `SiteLayers.detach`'s own idempotence. |
| 4 | **Conflict — see Ruling 1.** `test_the_tolerance_is_compared_against_a_squared_distance` is non-discriminating as written. |
| 5 | **Conflict — see Rulings 3 and 4.** The `ADOPTED_BY_M8` allowlist is wrong in both directions. |

### Rulings made before execution

Ruling 1 (Task 4): **The squared-distance test as written cannot fail.** The bug it
targets is comparing `closestVertexWithContext`'s squared distance against a raw
tolerance. I asserted a MISS at 3x the tolerance — but with `mapUnitsPerPixel()==1.0`
on the test canvas the tolerance is 12 map units, and 12 > sqrt(12), so the buggy
comparison is *stricter*, not looser: it rejects beyond 3.46 m where the correct one
rejects beyond 12 m. A miss test therefore passes under both. The discriminating
probe is a HIT in the band between sqrt(tol) and tol. Rewritten to hover at 0.8*tol
and assert a preview appears, with an explicit `assert tol > 1.0` so the test fails
loudly rather than silently degrading if the canvas scale ever changes.
Cost if wrong: the test is merely redundant with the hover tests, not harmful.

Ruling 2 (Task 2): **`_pick` must refuse to fire while previewing.** `ProfileDock._pick`
emits `pick_requested.emit(self._key, trace, time_ns)`, and Task 2 redefines `_key` as
the *displayed* line. Nothing consumes that signal today, so M7 ships no defect — but
M8 connects it to `session.add_pick`, and it would then author a pick on a line the
user only hovered. Spec §4.3 is explicit: "Picking targets the working line, never a
preview." Guarding it now is one line in the task that creates the hazard; leaving it
is a landmine planted for a milestone that will not be looking for it. Added to Task 2
as a step with its own test.
Cost if wrong: one unnecessary guard on a signal nothing yet consumes.

Ruling 3 (Task 5): **`pick_requested` comes OUT of the allowlist.** I assumed it was
unconsumed on the strength of spec §1's orphan table. It is not: `profile_dock.py:192`
connects `self.view.pick_requested` (ProfileView's signal of the same name). A
name-keyed check cannot tell the two apart, so `ProfileDock.pick_requested` — the one
that really is an orphan — is invisible to it and listing it makes the second test fail
outright. Replaced with a pinning assertion: exactly ONE `pick_requested.connect` may
exist in the package. M8 wiring ProfileDock's signal to `session.add_pick` makes that
two and trips the test, which is the notification the allowlist was meant to give.
**This also means spec §1's three-orphan table is wrong** and §6's "the three existing
orphans" should read differently — recorded here rather than edited mid-flight; the
final review report carries it back to the user.
Cost if wrong: the pinning count needs updating when M8 lands, which is the point.

Ruling 4 (Task 5): **Three orphans nobody knew about are allowlisted, not fixed.**
The scan found `SurveyDock.new_site_requested`, `open_site_requested` and
`save_requested` have zero consumers anywhere — plugin.py's toolbar actions do New,
Open and Save instead. They are dead API in a file M7 does not otherwise touch.
Deleting them is Plan 2 cleanup, not M7 work, and pulling it into this milestone is
exactly the scope creep the 3-6 task rule exists to prevent. Allowlisted with the
reason, and filed back to the user for an issue.
Cost if wrong: three dead signals survive one milestone longer.

Ruling 5 (process): **The ledger gets committed before the branch is finished.**
Plan 2's ledger lived only in a git-excluded worktree directory and nearly died with
it. This one goes to `docs/superpowers/sdd/` as part of finishing, not as an
afterthought.
Cost if wrong: none — it is a commit.

## Task 1 — the session's preview key
BASE c092017 · implementer sonnet (agent a0fa72f7168ee74c2) · reported DONE at eaa2a61
Implementer concern: wrote production code before tests, so never observed a red run.
Controller verification (not taken on report): reverted session.py to c092017 with the
new tests in place — 11 failed, 33 deselected. Restored, tree clean. The tests are not
vacuous. Second concern (commit trailer names Sonnet, not Opus) is correct behaviour:
this ledger forbids mandating a model name in a subagent's trailer.
Task 1: review (opus) — Spec ✅, Task quality NEEDS FIXES. 0 Critical, 2 Important, 2 Minor, 4 ⚠️.
  Both Importants are defects in the brief I wrote, verified by the reviewer against the
  live object, not inferred from the diff:
  I1 `remove_line` clears `_current_key` but not `_preview_key` → `display_key` names a
     deleted line, `line_for_key`/`stack_for` raise KeyError, nothing emitted. Task 3
     renders from `display_key` inside a `lines_changed` slot → qFatal in the LTR container.
  I2 `open_line`'s early return (key already current) never reaches the preview reset, so
     the brief's own claim "nothing is left stale" is false. Reachable via Task 5's
     `selectionChanged` promotion, which also fires from the attribute table.
Task 1: minor (deferred): `_install` resets current key/trace/selection but not the preview
  fields; correct today only because `_install` calls `close_site()` first. Asymmetry is a trap.
Task 1: minor (deferred): untested holes inherited from the brief — `set_preview(None)`
  branch, the `_selection`-untouched promise, preview-equals-current.

Ruling 6 (⚠️ resolution, Tasks 2-3): `preview_key == current_key` is reachable and emits.
Both consumers must treat it as NOT previewing. Task 2 already does (`_on_preview_changed`
routes `key == self._working_key` to `_exit_preview`). Task 3 does NOT as drafted:
`_refresh` tests `preview_key is not None`, so hovering the working line would blank its
selection band. Task 3's dispatch carries the corrected test
(`preview_key is not None and preview_key != current_key`). Rejected the alternative of
making `set_preview` collapse preview-equals-current into a clear: it would silently
discard the hovered trace index, which is the one thing a preview of the working line
could still usefully carry.
Cost if wrong: hovering your own working line blanks its selection band until corrected.

Ruling 7 (⚠️ resolution, Task 3): `close_site` resets the preview WITHOUT emitting
`preview_changed`, so a MapLink bound only to that signal would keep a stale marker. Task 3
as drafted already connects `site_closed` and guards `_refresh` on `session.is_open`, so it
is covered; no change needed, recorded so the final review does not re-raise it.
Task 1: fix round 1 dispatched (resumed a0fa72f7168ee74c2) — I1, I2 + 3 tests.
Task 1: fix round 1/5 (2 addressed, 1 new open — remove_line of a line that is BOTH
  current and previewed still emits `line_opened("")` with `_preview_key` still set, so
  `display_key` names the deleted line inside that slot: Finding 1's failure moved from
  `lines_changed` to `line_opened`. Verified by the re-reviewer against the live venv,
  not inferred. commits eaa2a61..a7692ee)
Task 1: minor (deferred): MapLink's `_set_marker`/`_set_band` use `.get(key)`, so the only
  planned `line_opened` consumer degrades to a stale marker rather than a crash — mitigates
  but does not remove the invariant break.
Task 1: fix round 2/5 (1 addressed, 0 open; commits a7692ee..a6cb247). Re-reviewer
  enumerated all four removal cases (neither/current/previewed/both) against a live
  session with probes on all three signals: no signal fires while any field still names
  the removed line. Both new tests proved discriminating by running them against two
  mutants — the round-1 ordering and the swapped-emission ordering; neither test alone
  catches both, together they do.
Task 1: minor (deferred): `close_site` resets the preview silently, so a listener bound
  only to `preview_changed` is never told. Pre-existing and brief-specified; Ruling 7
  covers the only consumer (MapLink connects `site_closed` and guards on `is_open`).
Task 1: complete (commits c092017..a6cb247, review clean)

## Task 2 — the profile shows the preview
BASE a6cb247 · implementer sonnet (agent a0fe8e8d52d0fd8f5) · reported DONE at 64573c7
pure 363/2 skipped · QGIS 399 (388 + 11 new) · ruff clean
Controller verification: reverted ui/profile_dock.py to a6cb247 with the new tests in
place → 9 failed / 28 passed. Nine of the eleven new tests are discriminating against a
null implementation. The two that still pass are
`test_a_hidden_gain_strip_stays_hidden_after_a_preview` and
`test_snap_back_restores_the_working_lines_cursor_and_selection` — both negative/
idempotence guards that hold trivially when nothing is implemented but do discriminate
against a real mutant (omitting the restore in `_exit_preview` leaves the cursor on the
preview's trace). Recorded, not adjudicated; the reviewer judges independently.
Implementer self-disclosed two deviations, both accepted on their face pending review:
a pre-existing test assigned `dock._key` directly (my brief's "two assignment sites"
count covered only profile_dock.py, not the test file), changed to `_working_key`;
and ruff reformatted whitespace before two inline comments in the brief's own test code.
Task 2: review (opus) — Spec ❌, Task quality NEEDS FIXES. 0 Critical, 3 Important, 2 Minor, 4 ⚠️.
  I1 `_channel_changed` writes `session.set_channel(self._key, ...)` and `set_channel` has
     NO current_key guard (unlike set_trace/set_selection) — so a preview IS a write target,
     which is the one thing §3.3 forbids. Verified live. New, caused by `_key` becoming the
     displayed line.
  I2 `show_gain_strip` has no preview guard, so hiding the strip is a transition, not an
     invariant. Reachable: plugin.py:353 `_resync_gain_strip` guards on current_key, so a
     `line_loaded` for the WORKING line arriving mid-preview puts its live curve over the
     previewed radargram — §3.3's named C2 configuration. Fix defers rather than drops,
     since the request can carry a new curve.
  I3 The `previewing` fixture never calls `set_profiles`, so `stack.source is None` and
     `_render()` returns immediately in ALL 11 new tests — nothing ever renders, and the
     hazard `_effective_difference_index` exists to stop is never executed. Defect in my
     brief. Reviewer confirmed the implementation is nonetheless correct by re-running with
     profiles loaded.
  Reviewer's verdict on the two non-discriminating tests: KEEP BOTH — each rules out a
  plausible wrong version of the new code (an unconditional `show()` in `_exit_preview`,
  and an `_exit_preview` that forgets to undo `_enter_preview`'s `clear_selection()`).
  They are weak only against "no implementation at all". Adopted.
Task 2: minor (deferred): no test exercises two consecutive `_enter_preview` calls (the
  capture guard's only reason to exist); verified working by reviewer probe.
Task 2: minor (deferred): `_enter_preview` sets `_preview_key` before `line_for_key` can
  raise; unreachable because `session.set_preview` validates first.

Ruling 8 (⚠️ resolution, Task 2): the processing dock's `diff_button` stays CHECKED during
a preview while no difference renders — a stale cue. Not fixed in M7. Fixing it means
`ProcessingDock` growing an awareness of preview state, and no M7 task owns that file;
`difference_cleared` must not fire (it would discard the mode permanently), so the cheap
fix is unavailable. The profile's own banner already says a preview is showing. Deferred
to the final review's triage and surfaced to the user.
Cost if wrong: a checked button claims a mode that is momentarily not rendering.

Ruling 9 (⚠️ resolution, Task 2): "nothing requests a background load for a previewed
line" is not a gap — Task 4 Step 4 connects `preview_changed` in `loader.py`. No action.
Task 2: fix round 1 dispatched (resumed a0fe8e8d52d0fd8f5) — I1, I2, I3 + 2 new tests.
Task 2: fix round 1/5 (3 addressed, 1 new open; commits 64573c7..027e8fa). QGIS 401, pure
  unchanged, ruff clean. Re-reviewer proved the strengthened difference test discriminating
  by mutating `_effective_difference_index` to return the stored index — it fails at
  `assert -1 == 0`. Implementer volunteered a correct deviation: `_open` must also re-enable
  `channel_combo`, because promotion ends a preview through `_open` and never runs
  `_exit_preview`. Verified right.
  NEW I4 `_deferred_strip` (state the fix itself introduced) is cleared only in
  `_exit_preview`, so it survives promotion and a site close. Probe-confirmed consequence,
  not theoretical: working A, preview B, mid-preview resync defers A's curve, promote B —
  the NEXT unrelated preview's exit replays A's curve over B, and a drag reaches
  `plugin.py:365 _on_gain_points`, which resolves through `session.current_key` (now B) and
  passes the `_gain_step` identity check whenever B's selected row is a curve step. A's
  curve silently written onto B's step. C2 exactly.

Ruling 10 (Task 2, round 2): the reviewer's out-of-scope Minor — a mid-preview
`show_gain_strip(None)` leaves `_strip_was_visible` stale, so exit re-shows a curve for a
step no longer selected — is folded into round 2 rather than deferred. It is one line
inside the very method round 2 already edits, and it is display-wrong in code we are
touching this round. This adds no round and extends no loop.
Cost if wrong: one extra line in a method already being changed.
Task 2: fix round 2 dispatched (resumed a0fe8e8d52d0fd8f5) — I4 + the folded minor + 3 tests.
Task 2: fix round 2/5 (2 addressed, 0 open; commits 027e8fa..35558d2). QGIS 404, pure
  unchanged, ruff clean. Re-reviewer reproduced the C2 leak by runtime-reverting `_open`'s
  clear — strip visible with A's curve and owner while current_key is B — then confirmed the
  fix closes it, including via `remove_line` of the current line. Replay safety proved by
  enumeration: `_working_key` has exactly two assignment sites, both now clearing, and every
  session path that moves `_current_key` emits `line_opened`/`site_closed` first, so the
  working line cannot change between deferral and replay.
Task 2: minor (deferred): `test_a_deferred_strip_is_dropped_when_the_site_closes` survives
  its nominal mutant — `close_site` emits `line_opened("")` first, so `_open` does the
  clearing and the test duplicates the promotion test. `_clear`'s own reset is correct
  defence in depth but untested. Fix is to close a site with no line ever opened.
Task 2: minor (deferred): `_strip_was_visible` is not reset in `_open`/`_clear`; a stale
  True survives promotion, harmless only because the next `_enter_preview` recaptures it —
  saved by an invariant nothing asserts.
Task 2: complete (commits a6cb247..35558d2, review clean)

## Task 3 — MapLink: the profile drawn onto the map
BASE 35558d2 · implementer sonnet (agent abd70fd6c5655a776) · reported DONE_WITH_CONCERNS at 7353057
pure 363/2 skipped · QGIS 415 (404 + 11 new) · ruff clean
Three self-disclosed deviations, all sent to review rather than accepted on their face:
  D1 (production) the brief's verbatim `_refresh()` left the marker invisible when hovering
     the working line's own trace, because that branch read `current_trace`, which stays -1
     until explicitly set. Changed the marker's trace source to prefer `preview_trace` when
     `preview_key == key`, leaving the band-protecting `previewing` condition alone.
  D2 (test) `test_the_geometry_cache_is_rebuilt_after_the_lines_change` asserted
     `_geoms is None` right after `remove_line`, but `_on_lines_changed` rebuilds the cache
     synchronously in the same call — the assertion was structurally unreachable. Loosened.
  D3 removed `REAL_DZT`, `needs_real_data`, `QgsGeometry` imports as dead (ruff-flagged).

Ruling 11 (Task 3 → Task 4): D3 is correct here and is MY planning error, not the
implementer's. I put the `REAL_DZT`/`needs_real_data` imports in Task 3's test module, where
nothing uses them; Task 4's real-data test is the first consumer. Ruff was right to flag
them and right to have them removed. Task 4's dispatch must therefore restate the import
line explicitly, because Task 4's brief adds the test but not the import.
Cost if wrong: Task 4 fails at collection with a NameError and loses one round.
Task 3: review (opus) — Spec ✅, Task quality NEEDS FIXES. 0 Critical, 2 Important, 4 Minor, 3 ⚠️.
  All three implementer deviations independently assessed and judged SOUND, each by mutation:
  reverting D1 fails only the marker assertion (band untouched, as claimed); stubbing
  `_invalidate()` to a no-op fails D2's replacement, so it still discriminates; D3 matches
  Ruling 11. Disposal verified genuinely correct (scene 1→3→1→1, idempotent, post-dispose
  signals don't raise, skipping the band fails the test).
  I1 `_transform` never checks `isValid()`. Verified live: an invalid transform returns
     Success(0) and leaves geometry unchanged — so marker and band draw at raw UTM metres in
     a degree canvas, off-screen and silent, and Task 4's canvas-unit tolerance would be
     compared against layer-unit distances. `SiteLayers._require_transform` already solves
     this in the sibling module. Also switched `QgsProject.instance()` → the injected project.
  I2 `test_geometries_are_transformed_into_canvas_crs` calls `_invalidate()` by hand, so the
     `destinationCrsChanged` connect is untested — deleting that line leaves all 11 tests
     green. Tasks 4 and 5 both rewrite `__init__`/`dispose`, which is exactly when such a
     line goes missing unnoticed.

Ruling 12 (Task 3 → Task 4): two D1 side-effect Minors are resolved in Task 4's DESIGN, not
patched in Task 3. While the pointer rests on the working line the marker stops following
`trace_changed`, and `set_preview(key)` with the default trace=-1 hides a marker whose
`current_trace` is valid. Both come from having two sources of truth for one line's cursor.
Task 4's hover therefore calls `session.set_trace(key, trace)` when the hovered line IS the
working line and `set_preview(key, trace)` only for other lines — so `preview_key` never
equals `current_key` in practice, `current_trace` stays the single source of truth for the
working line, and the map marker follows the profile again. Task 2's preview==working branch
becomes defensive rather than dead-wrong. Rejected patching precedence inside `_set_marker`:
it would need "which moved most recently" state, which is the wrong place for that question.
Cost if wrong: hovering the working line writes the cursor (not a destructive target — the
profile dock's own hover already does exactly this).
Task 3: minor (deferred): `__init__` never calls `_refresh()`, so a MapLink built over an
  already-open site draws nothing until the next signal. Unreachable in production (Task 5
  constructs it before a site can be open).
Task 3: minor (deferred): module docstring references `_on_selection`/`xyCoordinates`, which
  arrive in Tasks 4-5. Brief-sourced.
Task 3: fix round 1 dispatched (resumed abd70fd6c5655a776) — I1, I2 + the folded -1 fallback.
Task 3: fix round 1/5 (3 addressed, 0 open; commits 7353057..96e4ba0). QGIS 416, pure
  unchanged, ruff clean. Re-reviewer verified both implementer claims true:
  `QgsCoordinateTransform(EPSG:32616 -> ESRI:104905)` (an Earth/Mars pair, already used in
  test_plugin_layers.py) really is invalid — isValid() False, isShortCircuited() True,
  transform() returns 0 leaving the point unmoved — and reverting `_transform` fails only
  the new test. Finding 2's fix is now guarded by TWO tests: injecting a disconnect after
  __init__ fails `test_geometries_are_transformed_into_canvas_crs` with
  `assert (500.0 <= 180.0)`, i.e. untransformed coordinates. Recovery probed: after a failed
  transform `_geometries()` caches `{}` (never a half-transformed set), the marker hides,
  the band empties, and a valid CRS re-invalidates and fully restores both.
Task 3: minor (deferred): `geom.transform()` inside the build loop sits outside the try, so
  a QgsCsException there leaves `_geoms` None and re-logs once per signal; recovery needs an
  invalidating signal, so a transform-context-only change leaves `{}` stuck. The RuntimeError
  catch would also swallow a deleted-canvas wrapper error.
Task 3: complete (commits 35558d2..96e4ba0, review clean)

## Task 4 — ambient hover previews the line under the pointer
Plan patched first (commit 638a531) to carry Rulings 11 and 12 into the brief itself rather
than only into the dispatch: hover routes the working line through `set_trace`, other lines
through `set_preview`; the REAL_DZT/needs_real_data imports are restated where their first
consumer lives; two new tests cover the working-line hover route.
BASE 638a531 · implementer sonnet (agent ae0bdfd664a4356c7) · reported DONE at 8c40d68
pure 363/2 skipped · QGIS 428 (416 + 12 new) · ruff clean · real-data test RAN, not skipped
Controller verification: reverted map_link.py + loader.py to 96e4ba0 with the new tests in
place → 12 failed / 12 passed. All twelve new tests are discriminating.
Task 4: review (opus) — Spec ✅, Task quality NEEDS FIXES. 0 Critical, 2 Important, 2 Minor, 3 ⚠️.
  Reviewer independently confirmed hover reaches nothing destructive: across a full sweep
  `dirty` stayed False, `selection` and every StepStack identity unchanged, `current_key`
  unchanged. Squared comparison, `index < 0`, `isEmpty()`, empty cache and `""` sentinel all
  verified correct.
  I1 `dispose()` stops the dwell but leaves the `xyCoordinates` connection live, and
     `_on_dwell` has no disposal guard (unlike `_refresh`). Verified: after dispose(), one
     emission restarts the timer and the dwell set `current_trace` to 11 on a live session.
     After `unload()` every mouse move would keep repointing the cursor and issuing loader
     requests against a session the plugin has finished with.
  I2 (folded as a Minor fix) the `preview_key == current_key` branch comment describes the
     hover flow, which this task's routing made unreachable. Branch kept as defence; comment
     rewritten. A comment that confidently describes a dead path is worse than none.

Ruling 13 (Task 4): KEEP Ruling 12 despite a consequence I had not anticipated. Hovering the
working line mutates `current_trace` permanently with no snap-back, so panning or zooming
drags the pointer across it and silently moves the profile cursor with no user gesture.
Verified by the reviewer. Kept because ProfileDock's own hover already moves `current_trace`
and leaves it there — this is consistent, not novel — and because telling a pan-drag from a
hover needs a canvas event filter, which spec §3.2 rules out by name. Recorded as item 11 on
M7's manual acceptance checklist so the user judges it with a real site rather than my
guessing. Reversal if they dislike it is one branch in `_on_dwell`.
Cost if wrong: the profile cursor moves while panning; one-line revert.
Task 4: minor (deferred): `clear_preview()` + `set_trace()` gives two refreshes, so crossing
  from a preview onto the working line shows the old cursor for one frame.
Task 4: minor (deferred): `_hit_test` breaks exact distance ties by `getFeatures()` order —
  arbitrary but deterministic; untested.
Task 4: minor (deferred): `loading_changed` still has no consumer outside `loader.wait_for`,
  so §3.5's "M5's loading state covers it" is unwired for previews; ProfileDock renders via
  `line_loaded` instead, so a preview of an unloaded line shows axes then fills in.
Task 4: fix round 1 dispatched (resumed ae0bdfd664a4356c7) — I1 + the false comment.
Task 4: fix round 1/5 (2 addressed, 2 new open; commits 8c40d68..1a21862). QGIS 429, pure
  unchanged, ruff clean. `contextlib.suppress(TypeError)` assessed safe — the only TypeError
  reachable there is PyQt's "method object is not connected", disconnect invokes no user
  code, the slot is always a bound method.
  NEW I3 the fix made `dispose()` reach `self.canvas`, so a deleted canvas wrapper raises
     RuntimeError (not covered by suppress(TypeError)) and propagates BEFORE the scene-removal
     loop — marker and band stay on the scene, sentinels never arm. That is the Item I4 leak
     `dispose()` exists to prevent, and it makes the method's own docstring false ("does not
     assume the canvas is still alive"). Probed: pre-fix dispose() handled this; post-fix raises.
  NEW I4 `test_a_disposed_link_stops_tracking_the_pointer` pins only the disconnect half.
     With the `_on_dwell` guard reverted it still PASSES, because the disconnect means
     `_last_point` is never set and even the unguarded `_on_dwell` returns at `point is None`.
     An unpinned guard is one a later refactor deletes for free.
Task 4: minor (folded into round 2): `_on_dwell` checks `_marker` only where `_refresh`
  checks `_marker or _band` — two spellings of one sentinel will diverge.
Task 4: minor (deferred): `MapLink` still has no caller outside its own module; `unload()`
  does not reach `dispose()` until Task 5 wires it, so I1's production impact is anticipatory.
Task 4: fix round 2 dispatched (resumed ae0bdfd664a4356c7) — I3, I4 + the sentinel alignment.
Task 4: fix round 2/5 (3 addressed, 0 open; commits 1a21862..cf0d901). QGIS 431, pure
  unchanged, ruff clean. Re-reviewer exercised all four disposal failure modes directly
  (non-sip stub, genuinely sip.delete'd canvas, disconnect raising RuntimeError, double
  dispose): every one returns without raising, both items leave the scene, both sentinels
  clear. The `sip.isdeleted` TypeError branch judged sound — `self.canvas` is only ever
  assigned from __init__'s typed parameter, and a Python subclass of QgsMapCanvas is still a
  wrapper (verified: isdeleted False, disconnect runs), so no real object takes that branch.
  Test discrimination confirmed by mutation and the halves are genuinely different: the new
  queued-dwell test pins the `_on_dwell` guard (old test still passes without it), the
  canvas-gone test pins `dispose()`'s canvas guard.
Task 4: minor (deferred): the `sip.isdeleted` layer is redundant — `suppress(TypeError,
  RuntimeError)` alone passes all 27 tests including the stub. Three layers where one would
  do, plus 15 docstring lines explaining them.
Task 4: minor (deferred): `self._dwell.stop()` precedes the guard, so a deleted MapLink C++
  side would still abort before the loop. Pre-existing, not from this diff.
Task 4: complete (commits 638a531..cf0d901, review clean)

## Task 5 — selection promotes, plugin wiring, no new orphans
Ruling 14 (Task 5): the plan handed Task 5 a COMPLETE `dispose()` body, written before Tasks
3 and 4 hardened that method across four review rounds. Following it literally would drop the
canvas guards and reintroduce the Item I4 leak — a regression that already happened once
inside Task 4 and was caught only by a re-review. Plan patched (commit 373e96d) to say
"insert only the unbind, do not retype the method", with the insert given verbatim and
`contextlib.suppress` matching the surrounding style. Caught by reading Task 5's text against
the code as it now stands rather than as the plan imagined it.
Cost if wrong: none; the instruction is strictly narrower than what it replaced.
BASE 373e96d · implementer sonnet (agent a1d50a95b6fdd9774) · reported DONE at eb2e2a5
pure 366/2 skipped (363 + 3 orphan tests) · QGIS 441 · ruff + mypy clean
Controller verification: reverted map_link.py + plugin.py to 373e96d → 5 failed / 30 passed
across the two affected files.
Task 5: review (opus) — Spec ✅, Task quality NEEDS FIXES. 0 Critical, 2 Important, 3 Minor, 3 ⚠️.
  Both implementer judgement calls upheld: `contextlib.suppress` (SIM enabled in ruff.toml:9,
  idiom used twice in dispose()), `# noqa: SIM118` (nine byte-identical precedents,
  `keys()` really returns list[str]), and the `## Features` heading placement.
  `dispose()` verified INSERT-ONLY — zero deleted lines — with all four hardened failure
  modes still reaching the scene-removal loop. Ruling 14 held.
  I1 `_on_lines_changed` calls `_rebind_layer()` with no disposal sentinel, so a disposed
     link re-arms on any `lines_changed`/`site_opened` and promotes again — breaking the very
     promise `test_a_disposed_link_stops_promoting_on_selection` asserts.
  I2 the orphan check hides a SEVENTH orphan: `ParamForm.error` (param_form.py:40, emitted
     :222) has no consumer but is masked by `ProfileDock.error`'s connect at plugin.py:185.
     Identical mechanism to `pick_requested`, but unpinned and undocumented. Fix generalises
     the single pin into a shadowed-name table plus a test that EVERY duplicated signal name
     is listed — otherwise the next duplicate slips in the same way this one did.
  Reviewer confirmed the check does catch a plain injected orphan, and that the
  `pick_requested` pin would trip at 2.
Task 5: minor (folded): `_rebind_layer` suppresses only TypeError where dispose() suppresses
  TypeError+RuntimeError for the same disconnect; a RuntimeError aborts before `_invalidate()`
  AND leaves the new layer unbound, so promotion stops silently.
Task 5: minor (folded): `test_promotion_still_works_after_the_lines_layer_is_rebuilt` does not
  test what it claims — `SiteLayers.refresh()` does NOT replace the layer object
  (`ensure_tables` skips existing keys), so it passes without `_rebind_layer`. The real
  replacement path is a site reopen (detach + refresh). Both the commit message and
  `_rebind_layer`'s docstring name the wrong mechanism, which tells the next reader the
  guard is unnecessary.
Task 5: minor (folded): the AST walk handles `Assign` but not `AnnAssign`.
Task 5: fix round 1 dispatched (resumed a1d50a95b6fdd9774) — I1, I2 + 3 folded minors.
Task 5: fix round 1/5 (5 addressed, 1 new open; commits eb2e2a5..5cc1622). pure 367/2,
  QGIS 443, ruff + mypy clean. Re-reviewer injection-tested the rewritten orphan check in a
  scratch copy: (a) plain new orphan CAUGHT, (b) orphan colliding with a connected name —
  the ParamForm.error shape — CAUGHT by the new shadowed-table test, (c) a THIRD declaration
  of an already-pinned name NOT caught (4 passed). Counts verified correct in both directions.
  NEW I6 once a name is pinned, further classes declaring it are unguarded: the table records
     that a name is shadowed but not the shape it was verified against, so a new unconnected
     `error`/`pick_requested` on a third class ships silently — the exact failure mode
     Finding 2 existed to close, one level up. Fix pins declaration count as well as connect
     count.
Task 5: minor (deferred): shadow detection keys on class NAME only; two same-named classes in
  different modules would collide. No duplicate class names exist today.
Task 5: minor (deferred): `dispose()` leaves `canvas.destinationCrsChanged` and the session
  signals connected — harmless now that `_on_lines_changed` and `_refresh` both carry
  disposal sentinels, so tidiness rather than a leak.
Task 5: minor (deferred): eb2e2a5's commit message names the wrong layer-replacement
  mechanism; the corrected docstring is what people read, so history not rewritten.
Task 5: fix round 2 dispatched (resumed a1d50a95b6fdd9774) — I6.
Task 5: fix round 2/5 (1 addressed, 0 open; commits 5cc1622..fb693a0). Re-reviewer
  reproduced all five of the implementer's injection results byte-identically, then ran six
  constructions of its own against the three composed assertions: plain orphan, new orphan on
  a pinned name, new CONNECTED signal on a pinned name, a pinned name that stops being
  shadowed, and a third declaration on a class reusing an existing class name — all caught.
  One case correctly passes (orphan moved between classes, same shape, same single orphan).
  Assertion messages verified actionable: they name the drifted number as (expected, actual)
  and say what to do.
Task 5: minor (deferred): one construction still slips — delete the CONNECTED ProfileDock.error
  and add an unconnected `error` on a new class; declared stays 2 and connects stays 1 because
  the regex still matches the now-dangling connect at plugin.py:185. Requires leaving a
  dangling connect that raises AttributeError at plugin load, which the qgis tier catches.
Task 5: minor (deferred): class-name-keyed shadow detection still misses a same-named class in
  another module for UNPINNED names (confirmed: a second SurveyDock.add_grid_requested passes).
Task 5: minor (deferred): the `declared` comment says "how many classes" where the code counts
  declaration sites.
Task 5: complete (commits 373e96d..fb693a0, review clean)

## All five tasks complete
Controller-run final verification at fb693a0: pure 367 passed / 2 skipped; ruff check and
format clean (95 files); mypy clean (24 source files). QGIS tier running.
Branch range for the whole-branch review: 79401fd..fb693a0 (main is at 79401fd, the plan commit).
Task 5: QGIS tier confirmed 443 passed at fb693a0.

## Whole-branch review (opus, range 79401fd..fb693a0, 18 commits)
VERDICT: ready to merge. 0 Critical, 1 Important, 4 Minor. Reviewer traced every path from a
hover or preview to a write and found no C2 violation: all stack/preset/step writes resolve
through `ProcessingDock.key()` -> `session.current_key`; `set_trace`/`set_selection` reject a
non-current key in the session itself; `set_channel`, `pick_requested` and the gain strip are
guarded in the dock. Spec §3.1-§3.6 covered clause by clause, one ⚠️: §3.5's "M5's loading
state covers it" — the load happens but `loading_changed` still has no consumer.
Deferred-minor triage of all 27: MUST-FIX BEFORE MERGE: NONE. 3 obsolete, 5 unreachable by
construction, 8 test-strength items for the M8 backlog, 9 accepted trade-offs, 2 carried
forward (`loading_changed`; `.get(key)` masking a missing key).

## Final fix wave (single dispatch, 4 findings) — commit e09363a
pure 367/2 · QGIS 453 (443 + 10 new) · ruff + mypy clean
F1 preview stuck when the pointer left the canvas -> `QEvent.Leave` filter on
   `canvas.viewport()`, stopping the pending dwell in the same handler. NOT the click
   interception §3.2 forbids: that prohibition is about adjudicating mouse BUTTON events
   against the active tool, and a leave event competes with nothing.
F2 `remove_line(current)` while previewing another desynced dock from session.
F3 a comment claimed MapLink and ProfileDock agree about `preview_key == current_key`; they
   deliberately differ and the state is unreachable. Comment corrected, behaviour untouched.
F4 a preview lazily inserted an empty StepStack, so a save wrote `"stack": []` for a line
   that was only hovered.

Ruling 15 (final fix wave, F4): ACCEPT the implementer going beyond the scoped fix into
`SiteSession.set_profiles`. It proved by mutation that `current_radargram`'s `stack_for` call
is always a no-op re-fetch, so the scoped fix would have been inert — reverting `set_profiles`
alone leaves the empty stack planted. Re-reviewer verified all four sub-points I asked for:
the claim holds; a normally-opened working line is unaffected; no `"stack": []` after a hover
end-to-end; and a hovered line later promoted and edited still saves its stack (`['dewow']`
persisted across reload). A fix that does nothing is worse than a slightly wider one.
Cost if wrong: a core session method gained an `insert` kwarg, default-true.

## Fix-wave re-review (opus) — merge recommendation: YES
All four ADDRESSED, both implementer judgement calls sound. Judgement call 1 verified against
all three `line_opened` emitters (`close_site`, `remove_line`, `open_line`). `dispose()`
re-verified under three canvas doubles (viewport raising RuntimeError, raising TypeError, and
a non-sip `_Dead` double): all three still reach the scene loop with both items removed and
nulled. `eventFilter` proved unable to raise into Qt even with `clear_preview` monkeypatched
to raise. Fix interaction checked: F1 + F2 compose, and during the surviving-preview state
every write guard still blocks — §3.3's invariant holds.

Ruling 16 (residuals, adjudicated — no second fix wave): three Minor residuals PARKED.
(a) `test_a_disposed_link_still_removes_the_leave_filter_when_the_canvas_is_gone` is
    non-discriminating: the `_Dead` double makes `sip.isdeleted` raise TypeError so the whole
    block is skipped, and it duplicates the existing canvas-gone dispose test.
(b) flipping `eventFilter`'s `return False` to `return True` passes all 10 new tests. Latent:
    a True return would swallow Leave events from the viewport and could disturb QGIS's own
    hover behaviour. Currently correct, untested.
(c) `dispose()` aborts if `canvas.viewport()` returns None (AttributeError, unsuppressed).
    Unreachable for a real QgsMapCanvas, and the pre-existing `self.canvas.xyCoordinates`
    line carries identical exposure.
All three are test-strength or unreachable-path items on code the reviewer otherwise verified
by execution. The skill allows one fix wave and one re-review; spending a second on these
would buy less than it costs, and they are recorded here for M8's opening backlog.
Cost if wrong: (b) is the only one with teeth, and it is a one-line regression a future edit
would have to introduce deliberately.
