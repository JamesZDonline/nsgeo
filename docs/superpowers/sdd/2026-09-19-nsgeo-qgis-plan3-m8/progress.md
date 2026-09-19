# SDD ledger — plan: docs/superpowers/plans/2026-09-19-nsgeo-qgis-plan3-m8.md

Spec: docs/superpowers/specs/2026-09-18-nsgeo-qgis-plan3-design.md §4 (binding authority)
      parent: docs/superpowers/specs/2026-09-10-nsgeo-qgis-plugin-design.md (§4.3 GeoPackage
      rules, §6 picking)
Prior milestone's ledger (required reading when code looks strange):
      docs/superpowers/sdd/2026-09-18-nsgeo-qgis-plan3-m7/progress.md — 16 numbered rulings.
Branch: nsgeo-m8 · worktree .worktrees/nsgeo-m8 · start commit 0202e42 (the plan commit)
Model tiers (user standing instruction): implementers sonnet; ALL reviews and re-reviews opus.
Subagent commits must NOT mandate a specific Co-Authored-By model name — the trailer names the
model that actually did the work.

## Baseline before Task 1 (verified 2026-09-19, in this worktree)
pure+core 367 passed / 2 skipped · QGIS tier 469 passed
Both venvs built here (`.venv`, `.venv-qgis --system-site-packages`, nsgeo-core installed
editable in each); ten real DZT + DZX symlinked into packages/nsgeo-core/tests/data/local/
(README.md there is TRACKED — do not symlink it). `.worktrees/nsgeo-m7` untouched: the ns_geo
QGIS profile's plugin symlink still points into it.

## Facts established by experiment BEFORE the plan was written
Not assumed. Probed in .venv-qgis against QGIS 3.44:
1. A GPKG point table accepts a feature with NO geometry; it reads back with
   `feature.geometry().isNull()` True.
2. `_rebuild_picks`'s migrate-by-field-name loop leaves `feature_id`/`seq` NULL on every
   pre-existing row with no code change — two old rows migrated with attributes and geometry
   intact.
3. Assigning Python `None` to a QgsFeature attribute writes NULL. Reading it back gives a
   QVariant where `value == NULL` is True and `value is None` is **False**. An empty string is
   NOT NULL; it reads back as `''`.
4. `stack_for(key, insert=False)` returns the STORED stack when one exists (session.py:554-562),
   so Task 2's `stack_json` picks up steps added by `append_step`. Only a fresh empty stack is
   withheld from `site.stacks`.

## Pre-flight conflict scan

### Pairs sharing a file or an interface
| # | Tasks | Shared artifact | Produces → consumes | Finding |
|---|---|---|---|---|
| 1 | 1 → 2 | `session.py` | `Pick`, `set_pick_store`, `pick_store`, `_pick_store` | Clean. T1 opens the `# ---- picks (spec §4) ----` section immediately before the preview banner; T2 appends `add_pick`/`_pick_distance`/`picks_for` after `set_pick_store` in that same section. No overlapping lines. |
| 2 | 1 → 2 | `layers.py` → `session.py` | `SiteLayers.write_pick(pick) -> None`, `SiteLayers.picks_for(key) -> list[Pick]` | Clean. Checked name by name against T2's `self._pick_store.write_pick(pick)` and `self._pick_store.picks_for(key)`. Return types agree (`None`, `list[Pick]`). |
| 3 | 2 → 3 | `session.py` → `plugin.py` | `add_pick(key, trace, time_ns)` — raises ValueError/RuntimeError | Clean. T3's `_on_pick_requested` wraps in `try/except Exception` and reports via `self.message`. T3 never connects `add_pick` to a signal directly, which is the hazard the Global Constraints name. |
| 4 | 2 → 4 | `session.py` → `profile_dock.py` | `picks_for(key) -> list[Pick]`, `picks_changed` (no args) | Clean. T4's `_refresh_picks` reads `p.trace`/`p.time_ns`; both are non-optional fields on `Pick`. |
| 5 | 2 → 5 | `session.py` → test fixtures | `session.add_pick` used to author picks in T5's map_link tests | Clean, and sequential: T5 runs after T1+T2, and `linked` builds a real `SiteLayers`, so the store is registered. |
| 6 | 3 ↔ 4 | `ui/profile_dock.py` | T3 adds `set_pick_mode` before `set_difference_index` and edits `_pick`'s preview branch; T4 adds `_on_picks_changed`/`_refresh_picks` beside `_on_stack_changed`, one `connect` in `__init__`, one line at the end of `_show_line` | Clean — disjoint methods and disjoint regions. Both add one line to `__init__`'s connection block; different signals, no conflict. |
| 7 | 3 ↔ 4 | `tests/pure/test_no_orphan_signals.py` | T3 edits `SHADOWED["pick_requested"]` 1→2 connects; T4 removes `"picks_changed"` from `KNOWN_UNCONSUMED` and updates the module docstring's NOTE | Clean — different dicts, and only T4 touches the docstring. Both edits are FORCED: the suite goes red at the end of each task if they are skipped, which is the notification the check exists to give. |
| 8 | 3 → 5 | `plugin.py` | T3 adds `act_pick`, `_toggle_pick_mode`, `_on_pick_requested`, and a `line_opened` → `_update_enabled` connect. T5 does not touch plugin.py | Clean, no shared file. |
| 9 | 1 → 5 | the `picks` layer | T5's `_jump_to_feature("picks", "trace")` reads rows T1's `write_pick` wrote | Clean. Both key off the field name `trace`; `_row_to_pick` and `_jump_to_feature` independently handle NULL via `== NULL`. |
| 10 | 5 alone | `map_link.py`, `README.md`, `test_plugin_map_link.py` | — | Clean. |

### Each task against itself
| Task | Finding |
|---|---|
| 1 | Clean. `_a_pick`'s default key `raw/FILE__001.DZT` exists in `populated` (FILE__001..003). The 59/60 m distance assertion matches the file's own existing `test_derived_tables_mirror_the_session`. `_log`'s "cannot be placed on the map" in `write_pick` is distinct from `_line_points`'s "could not be placed and was left out of the map"; the test asserts on the former substring, which appears in both — harmless, both are true. |
| 2 | Clean, after verifying Fact 4 above. `test_add_pick_derives_...` calls `append_step` (insert=True) then reads `stack_for(key, insert=False)`; that returns the stored stack, so `dewow` is in `stack_json`. Had `insert=False` always built fresh, the assertion would have been vacuous. |
| 3 | **Conflict found and fixed in the plan before execution — see Ruling 1.** The `view` fixture yields `(v, rg)`; the drafted test wrote `v = view`. |
| 4 | Clean. `dock_with_picks` constructs the dock BEFORE `open_line`, so the dock receives `line_opened`. `close_site` emits `line_opened("")` first (M7 ledger, Task 2 minor), and both that path and `_clear` reach `_clear_view_only` → `view.clear()` → `_picks = []`, so the clearing test holds either way. |
| 5 | **Conflicts found and fixed in the plan before execution — see Rulings 2 and 3.** The `linked` fixture yields `(link, session, layers, canvas, keys)`, link first; and it writes no DZX, so its `marks` table is empty. |

### Rulings made before execution

Ruling 1 (Task 3, plan defect): **the drafted `ProfileView` test could not run.** The `view`
fixture in `test_plugin_profile_view.py` yields a `(v, rg)` tuple; the plan's draft wrote
`v = view` and then re-set the axes the fixture had already set from a real radargram. Fixed in
the plan: unpack `v, _rg = view`, drop the redundant `set_axes`, and add an explicit
`assert r.left() >= 10 and r.top() >= 5` so the test fails loudly rather than silently degrading
to clicking inside the rect if `MARGIN_LEFT`/`MARGIN_TOP` ever change. A second test was added
for the same bound under pick MODE, not only Shift+click — with the mode on the whole widget is
a crosshair, so the margins are the easiest place to mis-click.
Cost if wrong: one more test than strictly needed on a guard that is one `if`.

Ruling 2 (Task 5, plan defect): **the `linked` fixture's tuple order was wrong in the draft.**
It yields `(link, session, layers, canvas, keys)`, not `(session, layers, canvas, link, keys)`.
Every drafted test would have bound `session` to a `MapLink`. Fixed in the plan for all nine
tests. Caught by reading the fixture rather than by assuming the shape M7's prose implied.
Cost if wrong: none; the correction is mechanical and verified against the file.

Ruling 3 (Task 5, plan defect): **`linked` writes no DZX, so `marks` is empty** — the drafted
mark tests asserted against features that could never exist. Rejected the alternative of adding
a sidecar to the shared `linked` fixture: that fixture is used by ~30 M7 tests, and giving it a
marks row changes what every one of them sees for no reason connected to their subject. Instead
the mark tests add a third line carrying its own DZX, which emits `lines_changed` and refills
`marks` locally. Same reasoning M7 used when it added `previewing` rather than changing `opened`.
Cost if wrong: three M8 tests build one extra line each.

Ruling 4 (architecture, the one thing spec §4 left open): **the pick write splits — the session
guards, `SiteLayers` writes.** Spec §4.1 names `session.add_pick(key, trace, time_ns)`, but
`SiteSession` holds no `QgsVectorLayer` and the parent spec §4.3 rule 2 forbids a second OGR
handle on a package QGIS already has open, so the session cannot do the write itself. Ruled:
`SiteLayers.__init__` registers itself via `session.set_pick_store(self)`; `add_pick` enforces
the working-line invariant, derives every field, and calls the store. The rejected alternative —
put the whole thing on `SiteLayers` and have `plugin.py` call it — needs no new coupling but
moves the C2 guard out of the session, away from `set_trace`'s and `set_selection`'s identical
refusals. M7's whole-branch review specifically credited that placement for why no preview could
reach a write. The cost is a session ⇄ layers reference cycle, which is safe: neither class
defines `__del__`, Python's cycle collector handles it, and `plugin.unload()` drops both.
Cost if wrong: a reference cycle and one extra indirection on the write path; the guard would
have to move if it proves wrong, which is a small, local change.

Ruling 5 (scope): **the `picks` layer gets NO code-applied style.** `lines` and `grids` are both
styled in `_style_lines`/`_style_grids`, which run on every refill — but `picks` is the one
authored, user-editable layer, and a style reapplied on every site open would silently discard
the user's own symbology. Spec §4 does not ask for one. Ruled out of M8; QGIS's default symbol
stands. Surfaced to the user as an open question in the plan review artifact — if they choose
"style once at table creation", it folds into Task 1 before dispatch.
Cost if wrong: picks render in a different random colour per site until a later milestone.

Ruling 6 (spec §4.3, beyond the letter): **`ProfileView` refuses a pick outside the image
rect.** Spec §4.3 says a click in the profile becomes a pick and says nothing about where. But
`mousePressEvent` runs for the whole widget including the 56px time-axis margin, `time_of_y`
does not clamp, and `add_pick` DOES clamp — so a Shift+click on an axis label would be written
as a plausible-looking pick at the top of the record. Hover already applies the same bound
(`_handle_mouse_move`'s `0 <= x < width`); this is that rule for the other axis and the other
gesture. Added to Task 3 rather than left for a walkthrough to find.
Cost if wrong: one `if` refuses a pick someone deliberately made in the margin, which is not a
gesture anyone makes on purpose.

Ruling 7 (spec §4.3 vs. §3.3, reading versus authoring): **a preview SHOWS the previewed line's
own picks.** §3.3 says `preview_key` drives the view "and nothing else, ever"; §4.3 says picking
targets the working line. Those are both about writes. Ruled that `_refresh_picks` reads from
`self._key` (the DISPLAYED line), because seeing what has already been interpreted on a line is
most of the point of glancing at it, and a read cannot violate an invariant about write targets.
`add_pick` still refuses a preview independently, so the two are not coupled.
Cost if wrong: hovering a line shows its picks when the user expected the working line's; one
line of `_refresh_picks` to change.

Ruling 8 (process): **the ledger and the plan are committed as the branch goes, not at the end.**
M7's Ruling 5, kept. The plan is already at 0202e42; this ledger goes to
`docs/superpowers/sdd/2026-09-19-nsgeo-qgis-plan3-m8/` as part of finishing.
Cost if wrong: none — it is a commit.

## Task 1 — the pick schema and the pick store
BASE 0202e42 · implementer sonnet (agent a258b3b3a3fa53c69) · reported DONE at 1e10fa5
pure 367/2 skipped · QGIS 479 (469 + 10 new) · ruff + ruff format + mypy clean
Implementer deviation, accepted: omitted the brief's `import datetime as _dt` (unused in Task 1,
would fail ruff F401; it is prep for Task 2). Verified: ruff.toml:9 selects F.
Task 1: review (opus) — Spec ✅, Task quality NEEDS FIXES. 0 Critical, 2 Important, 6 Minor, 3 ⚠️.
  Reviewer independently verified the migration rather than trusting the report: read
  `_read_picks_rows` and `_rebuild_picks` outside the diff and confirmed two APPENDED columns
  cannot lose, reorder or mislabel a row (name-keyed dicts, `if fname in new_field_names`,
  geometry carried, transform inert for a pure field-set change), that the `written !=
  len(old_rows)` gate still holds, and that `_recover_picks_backup` and the rename-back are
  indifferent to column count.
  I1 `_row_to_pick` reads `feature["feature_id"]`/`["seq"]` UNGUARDED while `write_pick` guards
     every attribute with `if name in names` for the same reason. Reachable entirely through
     existing code: a pre-M8 package whose `_rebuild_picks` raises for any of its five
     documented reasons is CAUGHT by `ensure_tables` (layers.py:389-395), logged Critical, and
     the still-pre-M8 table is opened anyway by the loop below. Every later `picks_for` then
     raises `KeyError: 'feature_id'` — the user sees NO picks on any line, in exactly the state
     where their unrecoverable table is already in trouble. Task 4 calls `picks_for` from a
     render slot, where a raise is a qFatal in the LTR container.
  I2 `write_pick` has no CRS guard where `_refill` has one (layers.py:733-748) with the same
     stated reason — "mislabelled data looks correct and is wrong". Same failed-rebuild state,
     reached via `replace_grid` changing a grid's CRS (the scenario `_ensure_table`'s own
     docstring names): new-CRS coordinates stored in a table declaring the old CRS. The argument
     is STRICTLY STRONGER than for the derived tables that already have the guard — they are
     regenerated next refresh, picks is not.

Ruling 9 (Task 1, review round 1): **fold Minors 3 and 6 into the fix round.** Both sit inside
the very methods I1/I2 already change, and neither adds a round. Minor 3: `_as_float`/`_as_str`'s
NULL branches are never exercised — every written pick has non-null values, and the one row with
NULLs is discarded by the trace/time gate before a converter runs, so `_as_float` written as
`value if value is not None else float(value)` would pass all ten new tests and then raise on the
first hand-edited row with a trace and time but a blank distance. That is precisely the trap the
brief's Fact 3 names, in code being touched this round. Minor 6: `write_pick` can raise `KeyError`
from `line_for_key`, not the `RuntimeError` its own interface contract promises; one line, and
closing it here does not make the contract depend on a future task's discipline.
Cost if wrong: one extra test row and one `except KeyError` in a method already being edited.

Ruling 10 (Task 1, ⚠️ resolution): **the provider-write vs. open-edit-buffer interaction goes to
the acceptance walkthrough, not to code.** `picks` is the only non-read-only layer, and
`write_pick` goes straight through the data provider — so a pick authored while the user has
`Toggle Editing` on that layer writes a row the layer's edit buffer does not know about.
`_commit_pending_edits` already handles the reverse direction on detach/close. Judged a
visibility question (the new row may not appear until the edit session ends or the layer
reloads), not a corruption one: the provider write reaches disk either way and the buffer only
tracks its own changes. Cheaper and more honest to put a human on it than to guess at a fix, so
M8's acceptance walkthrough gains a step for exactly this.
Cost if wrong: a pick made mid-edit-session is invisible until the session ends, and we find out
in the walkthrough rather than from a user.

Ruling 11 (Task 1, ⚠️ resolution): **the unstaged plan edit the reviewer flagged is mine, not
stray work.** It is Ruling 1's correction to Task 3's `ProfileView` test (the `view` fixture
yields a tuple) plus Rulings 2-3's corrections to Task 5. The implementer was right to exclude it
from a task commit. Committed separately as docs so the task ranges stay clean.
Cost if wrong: none.

Task 1: minor (deferred): `write_pick`'s set-by-name loop + its hard-won "fid offset" comment
  duplicates `_rebuild_picks`'s (layers.py:826-845 vs 552-566). A `_set_by_name` helper would
  carry the logic and the explanation once. Real duplication, but the two call sites have
  different field-set sources and extracting it now would touch the migration path in the same
  round that changes the write path — the one combination worth not doing at once.
Task 1: minor (deferred): `_pick_point` clamps `pick.trace` into range, so a pick at trace 5000
  on a 60-trace line stores trace=5000 with trace 59's geometry. Consistent with `refill_marks`,
  which clamps identically — but a mark's scan is machine-read from a DZX while both halves of a
  pick are authored. Task 2's `add_pick` clamps the trace BEFORE constructing the Pick, so the
  disagreement is unreachable through the real path; revisit if a second writer appears.
Task 1: minor (deferred): the RED run was a single collection ImportError, so no individual new
  test was observed failing. The brief predicted exactly that; the reviewer read the assertions
  and confirmed none is vacuous. TDD-rigor note, not a defect in the result.
Task 1: minor (deferred): layers.py grew 855 → 1033 lines. Location is spec-mandated (§4.3 rule
  2 puts the write where the layer is); noted as the natural first split candidate.
Task 1: ⚠️ carried to Tasks 2-3: `write_pick`'s docstring promises `add_pick` will not emit
  `picks_changed` when it raises, and that plugin.py's relay surfaces the message. Both are
  planned; their own reviews must confirm them rather than assume.
Task 1: fix round 1 dispatched (resumed a258b3b3a3fa53c69) — I1, I2 + folded minors 3 and 6.
Task 1: fix round 1/5 (4 addressed, 0 open; commits f8f2baa..887467b). Focused file 45/45
  (41 prior + 4 new); ruff + format clean. Implementer proved the new tests discriminating by
  reverting layers.py and observing 3 of 4 fail (KeyError, DID NOT RAISE, unknown-key).
  Re-reviewer (opus) did NOT take the guards' presence for evidence: it traced that
  `_ensure_table`'s picks branch (layers.py:472-474) returns WITHOUT `_drop_loaded_layer` —
  which only runs on a SUCCESSFUL rebuild at layers.py:601 — so the stale layer genuinely stays
  in `self.layers["picks"]`, confirming both tests' preconditions are real rather than simulated.
  For I2 it traced the whole signal path `replace_grid → grids_changed → refresh → ensure_tables
  → _ensure_table("picks") → _rebuild_picks` and confirmed the monkeypatch is load-bearing.
  For minor 6 it checked the bare `except KeyError`'s blast radius: `grid_for_line` returns None
  via `frames.get`, `_line_points` catches ValueError, `_points`/`_require_transform` raise
  RuntimeError — so `line_for_key` is the only reachable KeyError and the message cannot
  mislabel a different failure.
  The ONE new test that passes against unfixed code was identified and adjudicated KEEP: it
  discriminates against the mutant Fact 3 names — verified in the venv that `float(NULL)` raises
  TypeError and `str(NULL) == 'NULL'`, so an `_as_float`/`_as_str` written with `is None`
  instead of `== NULL` fails it on both assertions. A coverage finding's fix is a test that
  passes against correct code and fails against that mutant; that is the requested outcome.
Task 1: minor (deferred): `picks_for` still reads `feature["line_key"]` directly
  (layers.py:915) — the one read in the pick path not routed through `_attr`. Unreachable in the
  state I1 names (a pre-M8 picks table HAS line_key); it only bites if a user drops or renames
  that column in QGIS AND the subsequent rebuild also fails.
Task 1: minor (deferred): `_ensure_table`'s picks branch returns without `_drop_loaded_layer`,
  which is WHY a failed rebuild leaves a stale layer open at all. Pre-existing structure, now
  defended at both the read and the write; flagged for the whole-branch review.
Task 1: complete (commits 0202e42..887467b, review clean)

## Task 2 — session.add_pick: the invariant and the derived fields
BASE 887467b · implementer sonnet (agent ab4e6d54bb291169a) · reported DONE at c707e0d
pure 367/2 skipped · QGIS 495 (483 + 12 new) · ruff + mypy clean
Two self-disclosed deviations, both sent to review rather than accepted on their face; both upheld.

Ruling 12 (Task 2, MY plan defect — caught by the implementer, not by me): **the brief's mutation
script mutated the wrong method.** `s.replace('        if key != self._current_key:\n', ..., 1)`
matches the FIRST of three identical occurrences in session.py — `set_trace` (754),
`set_selection` (763), `add_pick` (828) — so the mandatory Step 5 check silently mutated
`set_trace` and reported a false pass. The implementer noticed because 9/9 tests passed under it,
re-anchored on `add_pick`'s guard (which alone is followed by `raise ValueError(`), and observed
the real failure. The reviewer re-derived the collision statically and confirmed the corrected
run's evidence is self-consistent, and that the diff's +100/−0 stat proves the string-level
restore left no residue in `set_trace`. Plan patched so a rerun cannot repeat it: the needle is
now anchored on the following line with `assert s.count(guard) == 1`.
Cost if wrong: none now; had it gone unnoticed, the single most important test in this milestone
would have been unproven while looking proven — which is worse than having no mutation step.

Ruling 13 (Task 2, minor 2 — routed to the walkthrough, not to the loop): **a pick at the top of
a real record gets a NEGATIVE depth_m, and a human should decide whether that is wanted.** The
reviewer ran the real velocity model: the ten real GSSI files carry `position_ns = -11.0864` (the
record starts before time zero), so the lower clamp yields `depth_at([-11.0864]) = -0.444137 m`.
It does not raise and is not NaN — it follows correctly from "time is the truth, depth is
derived". But `tests/synthetic.py::write_dzt` has no `position_ns` parameter at all, so every
synthetic clamp assertion exercises a floor at t0 = 0 and depth 0, and the behaviour the
real-data test exists to catch is the one it does not assert. Ruled: this is a product question
(record it honestly, or floor it at zero?), not a defect, and it is cheaper to put the author in
front of it than to guess. Added as acceptance step 13.
Cost if wrong: picks made near the top of a record carry a negative depth until someone decides
otherwise; the value is recomputable from `time_ns`, so nothing is lost either way.

Task 2: review (opus) — Spec ✅, Task quality APPROVED. 0 Critical, 0 Important, 5 Minor, 1 ⚠️.
  Reviewer closed both cross-cutting risks by execution rather than by reading:
  - Raise/emit ordering: `picks_changed.emit()` (session.py:868) is the ONLY emit site in the
    entire plugin, and it sits strictly after `write_pick`. All four of `write_pick`'s failure
    branches raise; the one degraded path that returns normally (null geometry) still writes the
    row. No path to an announced-but-unwritten pick.
  - The clamp: checked `position_ns`/`n_samples`/`dt_ns` against all ten real files — window
    [-11.0864, 99.5610], well-formed, `lo < hi`, and the `lo, hi` swap makes a negative `dt_ns`
    harmless. Also confirmed `add_pick` is header-only (`n_traces`/`header` are eager dataclass
    fields), so a click never forces a sample load.
  Refusal test judged discriminating in BOTH directions: it fails under the corrected mutant, and
  a refuse-everything implementation would fail the other eight add_pick tests.
⚠️ resolved by controller: the commit trailer is `Co-Authored-By: Claude Sonnet 5` — the
  implementer's own model, not a copy of the plan's or the reviewer's. Checked at c707e0d and
  887467b both.
Task 2: minor (deferred): two definitions of "end of the record" now coexist one sample apart —
  `add_pick` clamps to `t0 + (n-1)*dt`, `ViewTransform.t_end` is `t0 + n*dt` (99.5610 vs 99.7775
  on real files). The session's choice errs inward, which is the safe direction, and a pick names
  a sample time — but nothing says so, and no test pins either definition. Wants one comment
  line so Task 4 does not "fix" one to match the other.
Task 2: minor (deferred): `add_pick(None, ...)` with no line open escapes both documented
  exception types — `key=None` passes the working-line guard when `_current_key` is also None,
  then dies in `line_for_key(None)` with KeyError. The annotation says `str` and every real
  caller passes one; Task 3's relay catches Exception, so it surfaces as `KeyError: None` on the
  message bar rather than escaping. One `key is None` clause would close it.
Task 2: minor (deferred): the brief's function-local imports duplicate module-level ones in the
  test file. Brief-mandated verbatim, harmless, and invisible to ruff because they are used.
Task 2: minor (deferred, cross-task): `SiteLayers.picks_for` reads `feature["line_key"]` directly
  rather than through `_attr` — the one uncaught raise path into a render slot. Already recorded
  against Task 1; the reviewer reached it independently, which raises its weight for the
  whole-branch review.
Task 2: complete (commits 887467b..c707e0d, review clean)

## Task 3 — pick mode, and the click that becomes a pick
BASE 03326b5 · implementer sonnet (agent ae3f0a79611992aa6) · reported DONE at 750ae41
pure 367/2 skipped · QGIS 504 (495 + 9 new) · ruff + format + mypy clean
Two self-disclosed deviations, both defects in MY brief, both verified by the reviewer and both
strengthening rather than weakening the tests.

Ruling 14 (Task 3, MY plan defect): **the preview-refusal test never entered a preview.** The
brief's `test_a_pick_while_previewing_is_refused_out_loud` takes the `previewing` fixture — but
that fixture supplies two LOADED lines and does not itself preview anything;
`ProfileDock._preview_key` is assigned only in `_enter_preview`, which the session's preview
signal drives. As written the test would have left `_preview_key is None`, taken `_pick`'s
ordinary path, and failed on `assert emitted == []` — the wrong failure mode, and one that could
have been "fixed" by loosening the assertion instead of adding the missing `set_preview`. The
implementer observed the wrong failure before fixing; the reviewer re-derived the fixture's end
state independently and confirmed no assertion was loosened and two were added. This is the test
that proves the preview guard SPEAKS, so a vacuous version of it would have been the worst
single outcome available in this task. Plan patched.
Cost if wrong: none now; undetected it would have shipped a guard nobody had watched fire.

Ruling 15 (Task 3, MY plan defect): **three of the five new `test_plugin_loads.py` tests would
have hung or failed on a forbidden modal.** `_plugin_with_one_line` dirties the session and never
closes it, so `unload()` reaches `save_with_prompt(ask_first=True, allow_cancel=False)` →
`QMessageBox.question`, which the conftest forbids outright. The implementer added
`answer_modal(..., Discard)` to exactly the three that end dirty and correctly left the two that
call `close_site()` alone — the reviewer verified that `close_site` clears the dirty flag and the
site before emitting, so `unload()` short-circuits there. That "three of five, not five of five"
distinction is the part that shows it was reasoned rather than blanket-applied. Plan patched.
Cost if wrong: none; the narrower fix is the correct one and is now evidenced.

Task 3: review (opus) — Spec ✅, Task quality APPROVED. 0 Critical, 0 Important, 6 Minor, 1 ⚠️.
  All three named cross-cutting risks closed by direct inspection, not by reading the report:
  - **No fourth path from pointer to write.** Traced the whole route and proved that past
    `_pick`'s guard `self._key` is provably `_working_key` (`_key` is `_preview_key or
    _working_key`; `_working_key` is assigned at exactly two sites, both driven by `line_opened`,
    which the session emits only where `_current_key` actually changes). Both refusals intact and
    independent. `session.add_pick` has exactly ONE caller in the package and it is inside
    `_on_pick_requested`'s try.
  - **`_update_enabled` cannot re-enter or fire at a bad time.** `_toolbar_action` connects
    `triggered` only, so `setChecked(False)` emits `toggled`, which nothing listens to — the
    explicit `_toggle_pick_mode(False)` beside it is NECESSARY, not redundant, and does not
    double-fire. Also checked every site that clears `_current_key` (`_install`, `close_site`,
    `remove_line`) and confirmed each emits a signal `_update_enabled` is now connected to, so
    `act_pick` cannot be left enabled with no working line.
  - **The moved pin reflects two real, distinct connects** — declarations at profile_view.py:56
    and profile_dock.py:109, connects at profile_dock.py:210 and plugin.py:193; the regex finds
    exactly those two, not one double-counted.
  Reviewer also confirmed `unload()` enumerates `act_*` by name and that `self.act_pick = None`
  was added — the brief's Step 5 closing check, honoured.
⚠️ resolved by controller: reported suite numbers are internally consistent (495 + 2 + 2 + 5 =
  504; the pure tier gained no tests so it returns to baseline). Trailer verified `Claude Sonnet 5`.
Task 3: minor (deferred): the out-of-rect click tests exercise only the NEGATIVE bounds
  (`r.left() - 5`, `r.top() - 5`). The implemented guard also refuses `x >= width` / `y >= height`,
  which nothing covers — a regression dropping the upper half of the condition stays green. One
  point at `r.right() + 5` closes it. Worth the final review's attention: this guard is Ruling 6's
  addition beyond the spec, so it has no other coverage anywhere.
Task 3: minor (deferred): `test_set_pick_mode_reaches_the_view` asserts the cursor shape only, so
  a `set_pick_mode` implemented as a bare `setCursor` — leaving `_pick_mode` false and pick mode
  non-functional — would pass. ProfileView's own test covers the real effect separately, so this
  is a seam rather than a hole; asserting `dock.view._pick_mode` would close it.
Task 3: minor (deferred): no single test asserts the user-visible sentence end to end (toolbar
  toggle on → unmodified click → row in the picks table); it is covered in pieces.
Task 3: minor (deferred): the new preview-refusal test largely duplicates the pre-existing
  `test_a_shift_click_on_a_preview_authors_no_pick`. Keeping both is defensible — the old one now
  independently pins that the guard itself was not weakened — but the near-verbatim setup will
  drift without a cross-reference comment on each.
Task 3: minor (deferred): the brief-archaeology comments (13 lines in test_plugin_loads.py, 10 in
  test_plugin_profile_dock.py) explain what "the brief" got wrong; once merged the brief is gone
  and only the confusion remains. The load-bearing halves (why `answer_modal`, why `set_preview`)
  are worth keeping; the "the brief originally said" paragraphs are not.
Task 3: minor (deferred): `answer_modal` is installed for the whole test rather than just the
  unload prompt, so it would also silently answer an unexpected question raised by the body.
  Matches what sibling files already do; noted so the pattern is deliberate.
Task 3: observation carried forward: the orphan check's blind spot is now slightly wider and its
  own comment admits it — at {declared 2, connects 2} a name-keyed count cannot say WHICH of the
  two `pick_requested` declarations holds the connects, so swapping one for a second connect of
  the other would stay green. Structural, not introduced here; the `declared` dimension still
  catches a third class, and Step 7's injection targeted exactly that.
Task 3: observation carried forward: pick mode stays CHECKED and the crosshair stays on during a
  preview (`_update_enabled` is not connected to `preview_changed`), so every click is refused
  with a message. Accepted for now; relevant to the de-duplication question the author has open.
Task 3: complete (commits 03326b5..750ae41, review clean)

## Task 4 — picks on the profile
BASE f00a317 · implementer sonnet (agent afcb78b338fbcaf69) · reported DONE at 1e441fe
pure 367/2 skipped · QGIS 509 (504 + 5 new) · ruff + mypy clean
One self-disclosed deviation: the brief's Step 5 script needed `packages/nsgeo-core` on sys.path
(`plugin_testing` does `from tests.synthetic import write_dzt`). Reviewer verified all three legs
and confirmed it mirrors `tests/conftest.py:16-19`'s own setup. Scratch script, not committed.

**The pixel measurement held up under independent re-derivation, which is the whole point of it.**
Implementer: changed-pixel box x 446..456, y 128..137; `_pick_positions` reports widget (451.6,
137.0). Reviewer re-derived rather than accepting the arithmetic: read `_paint_picks`'s actual
`drawPolygon` (profile_view.py:312-316), confirmed "±5 wide, 9 above" IS the code, grepped for
`setRenderHint` and found ZERO — so antialiasing is off and Qt rasterizes by pixel-center
sampling — and computed the predicted box edge by edge (446.14→446, 457.14→456, 127.52→128,
137.52→137). **Exact on all four edges.** It then ran a check the implementer had not: local x
395.642 / image width 788 = 0.50208 = (120 + 0.5)/240, so the marker is at trace 120.5
specifically, not merely somewhere on screen — which is the check that would catch a wrong-trace
bug rather than an invisible-marker one. Verdict: the boxes genuinely agree and the implementer
under-claimed.

Task 4: review (opus) — Spec ✅, Task quality APPROVED. 0 Critical, 0 Important, 4 Minor.
  Both named cross-cutting risks closed by tracing, not by reading:
  - **Every display path ends with the picks matching it.** Checked the four that bypass
    `_show_line`: `_exit_preview` with no working line → `_clear_view_only` → `view.clear()`;
    `_clear` → same; `_open("")` with a surviving preview → early return leaving `_preview_key`
    intact, so `_key` still names the preview whose picks ARE on screen; and all four
    `remove_line` cases. Also checked the path it was most suspicious of — `_render()`
    re-renders without a refresh — and confirmed `_render` never calls `view.clear()`; the only
    `view.clear()` in the file is inside `_clear_view_only`. Picks survive re-renders.
  - **`_on_picks_changed` cannot leak.** `self._refresh_picks()` is its ENTIRE try body, so the
    `_key` property, `session.picks_for` and `view.set_picks` (which calls `update()` and can
    raise RuntimeError on a deleted C++ object) are all inside it. Signal arity matches.
  Reviewer also noted the implementer's NOTE rewrite deviated from the brief's looser wording by
  KEEPING `ParamForm.error` in the orphan list — and that the deviation is correct.

Ruling 16 (Task 4, cross-task observation — NOT a defect): **orphaned picks after `remove_line`
are deliberate, tested behaviour.** The reviewer noticed `session.remove_line` neither deletes
the removed line's picks nor emits `picks_changed`, and correctly scoped it out of this diff. I
checked before treating it as a backlog item: `test_refill_never_touches_the_picks_table`
(test_plugin_layers.py:95-106) does exactly `remove_line` and then asserts the pick SURVIVES, and
layers.py's module docstring rule 1 plus parent spec §4.3 both say the same — picks are authored,
the file is never deleted, and a derived table changing must not destroy them. A user who removes
a line and re-adds it gets their interpretation back. The missing `picks_changed` emission causes
no stale display either: the reviewer verified all four removal cases, and where the removed line
was displayed `line_opened("")` already clears the view. Ruled: correct as built, no backlog item.
Cost if wrong: a `picks` table can accumulate rows whose `line_key` names no current line — which
is the price of never destroying authored data, and is recoverable by hand.

Task 4: minor (deferred): the report attributes the sub-pixel edge residual to "anti-aliased
  fill", but antialiasing is off (no `setRenderHint` anywhere in profile_view.py) and the correct
  derivation gives an EXACT match, not an approximate one. Right verdict via an invented
  mechanism — the failure mode this step exists to prevent, so worth correcting in the report
  even though no code is affected.
Task 4: minor (deferred): `test_no_orphan_signals.py:23` still says `SHADOWED_CONNECT_COUNTS`
  where the dict is `SHADOWED` (line 62); the implementer's newly written line 31 spells it
  correctly. A stale identifier in the comment block that IS the authority for this check.
  FOLDED INTO TASK 5's dispatch rather than fixed here — Task 5 already owns the no-orphans
  story, so it costs no round.
Task 4: minor (deferred): four of `dock_with_picks`'s six local imports shadow module-level ones.
  Brief-mandated verbatim; noise, not a defect.
Task 4: minor (deferred): `layers` is unpacked in all five new tests and used in none — it must
  stay alive for the store to work, but nothing says so.
Task 4: complete (commits f00a317..1e441fe, review clean)

## Task 5 — selecting a pick or a mark jumps to it; marks confirmed; the milestone closes
BASE 1e441fe · implementer sonnet (agent a8c010c5565826573) · reported DONE at 47d4e69
pure 367/2 skipped · QGIS 517 passed / **1 skipped** · ruff + mypy clean
One self-disclosed deviation: the Step 5 disposal script needed `packages/nsgeo-core` on sys.path
(same as Task 4's). Scratch script, not committed.
Implementer also surfaced, rather than silently passing, that Step 7's own criterion was unmet —
see Ruling 18.
Task 5: review (opus) — Spec ❌ (one item), Task quality NEEDS FIXES. 0 Critical, 1 Important,
  4 Minor, 2 ⚠️.
  The lifetime code — the reason this task was flagged highest-risk — came through clean and was
  verified rather than read: `_rebind_layer` has exactly two call sites and the second sits AFTER
  the disposal sentinel, so no new path can re-arm a disposed link; the reviewer additionally
  checked that `layers.py:425` is the ONLY place a layer object enters the registry (inside
  `ensure_tables`, on the detach+refresh pair `site_opened` drives) and that a pick write goes
  through the provider, not a rebuild — so M8 introduces no new stale-binding path. It checked
  `NULL` semantics against the live build (`0 == NULL` → False, `None == NULL` → True,
  `int(NULL)` → TypeError), confirming a legitimate pick at trace 0 is not swallowed by the NULL
  branch. It judged the disposal script's DELTA-based assertions stronger than absolute counts.
  §4.4 fully discharged: renders, read-only, and navigable all asserted, with the
  `picks.readOnly() is False` counter-assertion that stops the test passing on a build where
  everything is read-only.
⚠️ resolved by controller: trailer at 47d4e69 is `Co-Authored-By: Claude Sonnet 5` — correct.
⚠️ carried, correctly: the 14-step manual QGIS walkthrough is an open HUMAN gate, not a gap in
  this task. It has not been performed and must precede any merge proposal.

Ruling 17 (Task 5, MY plan defect — the worst one in the milestone): **the real-data mark test
can never run, and reports as coverage while doing so.** I checked the data directly rather than
trusting either party: of nine real DZX sidecars, exactly ONE carries a mark — `FILE__007.DZX`,
a single WayPt at scan 634 — and `FILE__007.DZT` has 635 traces, so that mark sits on the last
trace. `REAL_DZT` is sorted, so the brief's `marked[:2]` is FILE__001 and FILE__002, both
markless; the test's own `pytest.skip` therefore fires on EVERY run. That is the `1 skipped`
against a baseline of zero. Severity: Important, not Minor — the test's docstring states that
only a real pair proves the scan a mark reports is the trace the profile lands on, and the
synthetic fixture hard-codes scan 27 against a 60-trace file so no clamp is exercised anywhere
in the milestone. A permanently-skipping real-data test is worse than none: it looks like the
validation the standing rule requires.
  The reviewer found a SECOND, latent flaw a naive fix would have left in place, which is the
  part worth recording: line 1001's `next(..., marks[0])` fallback means that if the marked file
  happens to be `keys[0]` — likely, with one marked file in the set — the key never has to move
  and `assert current_key == want_key` passes trivially. Fix must order the lines so the UNMARKED
  one is opened first, and drop the fallback.
Cost if wrong: mark navigation keeps zero real-data coverage and the suite keeps a permanent
skip; both are visible, neither corrupts anything.

Ruling 18 (Task 5, Step 7's gate): **`SiteSession.pick_store` stays, with its reason written
down.** The manual half of the no-orphans check requires every new public name to have a
production caller; `pick_store` has only a test. Rejected deleting it: it is the symmetric public
read half of a public setter, and it is what lets the registration test assert without reaching
into `session._pick_store` — a legitimate reason for a public accessor to exist. Rejected
deferring it to the branch review: that moves the same two-line decision without improving it.
Ruled: keep it, comment the property saying why, and record it in the report's no-orphans section
as a reasoned non-signal exemption. Spec §6's rule is mechanical; the honest close is to name the
exception, not to pretend the sweep was clean.
Cost if wrong: one public property with no production caller, documented as such.

Ruling 19 (Task 5, minor 2 folded): **`dispose()`'s new `KeyError` path is fixed this round even
though it is unreachable today.** The loop iterates `self.SELECTABLE` but looks the slot up in
the separate `self._selection_slots` literal, and `contextlib.suppress(TypeError, RuntimeError)`
does not cover `KeyError` — so a future fourth layer added without a slot-table entry makes
`dispose()` raise before `_marker`/`_band` leave the scene. That is Plan 2's Item I4 leak
exactly, in the one method whose entire contract is "nothing here may abort". The pre-M8 code
could not do this (`self._on_selection` was an attribute access), so M8 introduced the exposure.
Folded rather than deferred because the fix is nearly free — make the slot table the single
source of truth — and it is in code this round already touches.
Cost if wrong: two literals unified that could have stayed separate.

Task 5: minor (deferred): `_on_selection` and `_jump_to_feature` duplicate the selection guard
  near-verbatim, multi-selection comment included. Plan-mandated: the brief froze `_on_selection`
  because it was hardened across four M7 review rounds, and that reasoning stands. The cheap
  unification when someone next touches this is `_on_selection` delegating to
  `_jump_to_feature("lines", None)` with a None trace field meaning "line only".
Task 5: minor (deferred): the report's explanation of the `receivers()` baseline is wrong —
  `SiteLayers` has no `selectionChanged` connection; the extra receiver is QGIS's own, most
  likely QgsProject's aggregated signal. The evidence stands because every assertion is a delta;
  only the prose is wrong. Correction requested in the fix round.
Task 5: fix round 1 dispatched (resumed a8c010c5565826573) — I1 + folded minors 2 and 3.
Task 5: fix round 1/5 (4 addressed, 0 open; commits 47d4e69..68fb533). Focused file 54 passed /
  0 skipped; ruff + format clean; disposal script re-run with identical rows.
  Re-reviewer (opus) did not accept the mutant as proof of the whole finding, correctly: the
  `set_trace` mutant proves only the TRACE assertion bites. It established the KEY assertion
  separately and more strongly — by construction (`add_lines` preserves list order and
  `keys()` returns `list(self._lines_by_key)`, so `keys[0]` is the unmarked line) and by a new
  hard pre-assertion `assert session.current_key != marked_key` before the jump; then noted the
  mutant run's failure landed at line 1017, not 1016, which means the key assertion had already
  executed and passed. It also verified the parser only reads `./Profile/WayPt`, so the stray
  `<scan>0</scan>` present in every sidecar is not a mark and the one-marked-file premise holds.
  Arithmetic checked: 54 `def test_` today, RED 4+49+1 = 54, pre-fix 53+1 = 54, post-fix 54 — the
  previously-skipping test now RUNS; nothing was deleted to make the numbers work.
  Re-reviewer flagged that tier-level zero-skips was inference, not a run.
Controller verification at 68fb533 (both tiers run in full, not inferred):
  pure **367 passed / 2 skipped** (both pre-existing and unrelated — `test_schema.py:51`,
  bandpass and gain_curve have required parameters by design)
  QGIS **518 passed / 0 SKIPPED** — the tier-level claim Important 1 required, now measured.
  ruff check + ruff format clean (95 files); mypy clean (24 source files).
Task 5: complete (commits 1e441fe..68fb533, review clean)

## All five tasks complete
Branch range for the whole-branch review: 54a8682..68fb533 (main is at 54a8682), 11 commits,
15 files, +4317/-51.
Net test movement across the milestone: pure 367/2 → 367/2 (unchanged — M8 adds no pure tests);
QGIS 469 → 518 passed, 0 skipped.

## Whole-branch review (opus, range 54a8682..68fb533, 11 commits, 15 files, +4317/-51)
VERDICT: needs fixes before merge. 0 Critical, 3 Important, 10 Minor.
Spec §4 clause by clause: §4.1 MET (all three orphans adopted; one declared exception,
`SiteSession.pick_store`, documented in place per Ruling 18), §4.2 MET, §4.3 MET with one
map-side gap (I2), §4.4 MET.
**The C2 sweep found no fourth violation.** The reviewer traced eleven routes from pointer to
write to their terminus rather than reading a guard and stopping, including the genuine new
pointer-to-disk path, and specifically looked for a violation in the new selection bindings since
`_jump_to_feature` calls `open_line` — which DOES repoint every destructive operation — from a
signal slot. Cleared: `selectionChanged` on those layers only fires from a user selection or a
programmatic `selectByIds`, nothing in the plugin ever selects programmatically (grepped), and
`refill_*` truncates through the provider, which touches no selection set and emits no
`selectionChanged` — so a refresh cannot forge a jump.
I1 **the picks migration's safety gate is vacuous when the source read fails.**
   `_read_picks_rows` returned `[]` on `not old_layer.isValid()`; the `written != len(old_rows)`
   gate then compared 0 == 0, passed, renamed the real table out, renamed an empty one in, and
   DROPPED THE BACKUP. Total unrecoverable loss of the one table survey.nsgeo.json cannot
   regenerate, logged as success. Plus `_table_schema` conflating "absent" with "present but
   unopenable", whose absent branch ends in CreateOrOverwriteLayer. Pre-existing code — but this
   branch is what makes every package on disk take the path.
I2 **a pick's map position never follows a grid that moves.** `_pick_point` computes geometry at
   write time and nothing re-derives it, so `replace_grid` with a changed origin/azimuth/size
   moves lines and marks while picks stay put — whereas a CRS change DOES re-project them. Half
   of "the grid changed" handled, half silently not, and the unhandled half is the one an
   ordinary "Edit grid…" gesture reaches.
I3 **`profile_dock._pick`'s comment stated the opposite of the truth** — that nothing connects
   `pick_requested`, that `set_pick_mode` has no control, and that picks are authored with QGIS's
   own tools. All three false as of this branch, in the paragraph that itself describes a stale
   note having "sent a reader looking for a pick mode that was never built".

Ruling 20 (final review, I2 — the shape of the fix, not whether to fix): **document and warn; do
NOT add re-placement logic.** Re-placing a pick from `line_key`+`trace` on every refresh would
overwrite a pick the user moved by hand, which the README explicitly invites; and adding new
write logic to the one unrecoverable table inside a fix wave that gets exactly one re-review is
the wrong risk to take at this point in the milestone. It is also not a regression — before M8
the plugin could not author a pick at all. Ruled: a Warning when a placed grid actually moves, a
README paragraph, and a comment on `_pick_point` recording the asymmetry. The reviewer's
alternatives (re-place only picks still at their computed position; re-place and drop the
move-by-hand affordance) are both real options for a later milestone and are recorded here.
Cost if wrong: picks silently detach from a moved grid until a later milestone addresses it, with
a warning in the log and a note in the README saying so.

## Final fix wave (single dispatch, 3 Important + 6 Minor + 1 plan edit) — commit ad6e4ef
pure 367/2 · QGIS **520 passed, 0 skipped** (518 + 2 new) · ruff + mypy clean
Re-review (opus) — ALL ADDRESSED, no new Critical/Important breakage.
  I1(a): `_read_picks_rows` now RAISES; the re-reviewer verified the raise is load-bearing by
    position — `old_rows = self._read_picks_rows(...)` is the FIRST statement of
    `_rebuild_picks`, ahead of `_create_table`, `_drop_loaded_layer` and both renames. The new
    test keys its patch on `sys._getframe(1).f_code.co_name` so `_table_schema`'s textually
    identical probe still opens the table and `_rebuild_picks` is genuinely reached — patching
    `QgsVectorLayer.isValid` on the class would have blinded both and the migration would never
    have been entered. Rows asserted on disk through a FRESH unpatched layer.
  I1(b): three distinguishable states via a `_TABLE_UNREADABLE` sentinel, with the presence probe
    deliberately NOT going through `QgsVectorLayer` so it is not blinded by whatever broke the
    open. Raises for `picks` before any destructive call; folds to `None` for the regenerable
    tables.
  I2: re-reviewer confirmed the ruling was honoured — `_pick_point` still has exactly one caller
    and no new write path to `picks` appears anywhere in the diff.
  I3: false clauses gone, both load-bearing halves kept verbatim in substance.
  **The re-reviewer drove the untested warning mechanism itself** rather than accepting the
  implementer's disclosure, with a scratch script against a real package: move grid → warned=1,
  rotate → 1, plain refresh → 0, add grid → 0, remove grid → 0, velocity-only replace → 0,
  CRS-only change → 0 (and the pick survived, re-projected). Fires once per genuine move despite
  `replace_grid` driving two refreshes. Residual risk is a silent regression, not a data path.
  **Migration judged SAFER than the head the whole-branch review saw**, not merely unchanged:
  both refusals sit strictly upstream of every destructive operation, `_recover_picks_backup` now
  treats a present-but-unreadable backup as "try to restore" rather than "nothing there", and
  when a refusal fires the degradation is loud — `ensure_tables` Critical-logs, `picks` never
  enters the registry, and `write_pick` raises onto the message bar rather than dropping a pick.
Deferred-findings triage by the final reviewer: **MUST-FIX BEFORE MERGE: NONE from the ledger.**
  Three cheap ledger minors were folded into the fix wave anyway. The rest: accepted trade-offs
  (code-shape duplication, clamping/null handling, test-shape, the orphan check's structural
  blind spot) or obsolete (the RED-run process note, the antialiasing attribution, the
  SHADOWED_CONNECT_COUNTS identifier — verified fixed).
  One earlier triage REVISED on a whole-branch view: Task 3's "brief-archaeology comments" minor
  was withdrawn after the reviewer grepped and found `# the brief's ...` across at least seven
  test files from M4 onward — an established house convention, not an M8 regression. Removing it
  is a repo-wide decision, not a merge condition.
Residual nits, all recorded, none blocking: `layers.py:414`'s unguarded trailing
  `_grid_placements` call (asymmetric with the guarded one at :390); the blanket `except
  Exception: present = True` also applying to `_PICKS_BACKUP` probes (effectively unreachable,
  and fails loudly not destructively); `_table_schema`'s return type widened to `tuple[Any, ...]`
  in a module mypy does not check; `picks_for` routing `line_key` through `_attr` converting a
  hypothetical KeyError into "this line has no picks"; and the plan document still describing
  `MapLink.SELECTABLE`, which Minor 5 deleted — the plan is a historical record, so no action.
Out-of-scope, pre-existing: `renameVectorTable` during a CRS rebuild emits GDAL stderr noise
  (`layer_styles` and a stale sqlite handle). Cosmetic; does not reach the QGIS message log.

## Controller final verification at ad6e4ef (both tiers run in full)
pure **367 passed / 2 skipped** (both pre-existing: test_schema.py:51, bandpass and gain_curve
have required parameters by design) · QGIS **520 passed / 0 skipped** · ruff check + ruff format
clean (95 files) · mypy clean (24 source files).
Net movement across the milestone: QGIS 469 → 520 passed, 0 skipped throughout.

## Open human gates — NOT discharged by any of the above
1. The 14-step acceptance walkthrough, including opening a pre-M8 package (exercises the
   migration on real authored rows) and the negative-depth and edit-buffer steps.
2. Ruling 13's negative `depth_m` decision — the final reviewer judged this BLOCKING: all ten
   real files carry `position_ns = -11.0864`, so a pick near the top of any real record writes a
   negative depth into an authored, unrecoverable table today. Decide before rows exist.
3. Ruling 10's edit-buffer step, now with an exit criterion: if the pick is invisible until the
   edit session ends, the fix is `write_pick` refusing while `layer.isEditable()`, not a doc note.
4. Ruling 5's pick-layer styling question. The final reviewer independently recommended the same
   middle option offered to the author ("style once at table creation"), arguing QGIS's random
   per-layer default is the difference between "renders" and "renders findably".
