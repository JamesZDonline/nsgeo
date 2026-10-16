# Task 3 report: the Slices dock and its Source group

## Summary

Implemented `LineChoiceDialog` (`packages/nsgeo-qgis/nsgeo_qgis/ui/line_choice_dialog.py`,
verbatim from the brief) and `SlicesDock` (`packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`,
written from the brief's prose since Step 7 gave requirements rather than code), wired both into
`plugin.py`, and added the plugin-level dock tests. All 14 new tests pass, plus the 2 new
`test_plugin_loads.py` tests (16 new tests total), on top of an unchanged 541/2-skipped core+pure
baseline.

## Tier counts

| Tier | Before | After |
|---|---|---|
| core+pure (`./.venv`, `packages/nsgeo-core packages/nsgeo-qgis/tests/pure`) | 541 passed, 2 skipped | 541 passed, 2 skipped (unchanged) |
| QGIS (`./.venv-qgis`, `packages/nsgeo-qgis/tests`) | 501 passed | 517 passed |

517 − 501 = 16 new QGIS-tier tests: 5 in `test_plugin_line_choice_dialog.py`, 9 in
`test_plugin_slices_dock.py`, 2 appended to `test_plugin_loads.py`.

Both baselines were measured directly before touching any file, confirming the brief's own stated
baseline (541/2 skipped, 501 QGIS) — but two numbers *later* in the brief are wrong and I did not
force them:

- Step 8 says "Expected: 8 passed" for `test_plugin_slices_dock.py`; the file as given literally
  contains 9 test functions, and 9 pass. I did not delete a test to hit 8.
- Step 11 says "Run both tiers. Expected: 481 + ~15 = ~496 QGIS passed" — but the brief's own
  baseline line at the top states 501, not 481, and 501 + 5 + 9 + 2 = 517, not ~496. I used the
  measured 501 baseline and got 517, not ~496.

## Mutation checks (Step 11)

**Mutant 1 — remove `prepare()`'s `try/except ValueError`.**
`test_choosing_a_preset_that_carries_a_transform_is_refused_visibly` FAILS, as expected — but as a
**plain `AssertionError`** (`assert any("amp_abs" in msg for msg in seen)` → `[]`), not via the
`_no_swallowed_slot_exceptions` fixture. Reason: `prepare()` is called from `_on_source_changed`,
which has its own outer `try/except Exception` (required by the "every slot guards its own body"
rule). That outer guard catches the `ValueError` first and routes it to `nsgeo_qgis.log.log`
instead of the `error` signal, so the exception never reaches Qt's C++ boundary at all — it is
caught one frame up from where `_no_swallowed_slot_exceptions` would see it. Reverted.

**Mutant 2 — `included_keys()` returns `tuple(self._included)` (set order) instead of survey
order.** Two tests fail, both by assertion (set iteration order for these tiny sets happened to
put the two remaining short keys first, then the reinserted middle one):
`test_every_line_in_the_grid_is_listed_and_included_by_default` and, per the brief's own
prediction, `test_excluding_a_line_removes_it_from_the_result_and_keeps_the_order`. Caught.
Reverted.

**Mutant 3 — replace `SlicesDock.rebuild_source`'s `self._updating` depth counter with a plain
bool.** Ran all 18 tests across `test_plugin_slices_dock.py`, `test_plugin_line_choice_dialog.py`
and `test_plugin_loads.py`: **all 18 still pass.** No test in this task's suite drives a nested
re-entry into `rebuild_source` while an outer call is still on the stack (nothing here, unlike
`processing_dock.py`'s parameter form, writes back into the session from inside a slot that
`rebuild_source` itself triggers). Grepped the rest of the QGIS test tier for any other construction
of `SlicesDock` — only these three files reference it, so no other test could catch it either. This
matches the brief's own prediction: **the counter is not pinned by any test in this task.** I kept
it as a counter anyway (not a bool), per the explicit instruction and for the same defence-in-depth
reason `processing_dock.py` gives — a later task adding a slot that writes back into the session
from a `rebuild_source`-triggered callback (Task 4's Position/Resolution controls are the obvious
future candidate) would silently reintroduce the early-clear bug a bool has, with nothing here to
stop it. Reverted the mutation; did not invent a test to manufacture false coverage.

## Point 5: does editing a preset's contents in place re-prepare?

**Decision: no.** Editing the *contents* of the currently-selected preset (e.g. re-saving the same
name from the Processing dock) does not, by itself, cause the Slices dock to re-prepare. The retry
path stays available (switching the preset combo away and back re-fires `_on_source_changed`
twice, unguarded each time; `prepare()` also stays public).

Reasoning:

1. **Ruling K, in `SliceEngine.set_source`, already freezes the preset's steps at dispatch time,
   on purpose** — `self._steps = tuple(dict(s) for s in steps)`, explicitly *not* a live read of
   `site.presets[name]`, specifically because `save_preset` overwrites a name in place while a
   source stays prepared, and a live read would describe a cube from steps it was never built
   from. If the intended behaviour were "the prepared source always tracks live edits to its
   preset", the engine would not bother freezing this at all — it would just read
   `site.presets[choice.preset]` in `provenance()`. Auto-re-preparing on every in-place edit works
   against the very reason that freeze exists: it would make the frozen snapshot and the live
   preset agree again half a second later, defeating the point of freezing it in the first place
   for anyone inspecting state mid-flight (a progress bar showing "preparing…" against a
   provenance that is about to be replaced out from under it).
2. **`presets_changed` carries no information about *which* preset changed or *how*.** Treating
   every emission as "the selected preset might have changed content, better recompute" would
   force a ~0.9 s task on *any* preset add/remove/edit anywhere in the site — including ones with
   no relationship at all to the grid/preset/transform currently chosen here — every time any dock
   in the plugin saves a preset. That is exactly the background churn spec 9.1's "nothing runs
   automatically" principle exists to rule out; it is a strictly worse violation than the one the
   `_updating` guard already prevents (refilling this dock's own combos), because it would fire for
   activity in a completely different dock.
3. Spec 9.1's own wording — "changing the grid, preset or transform re-runs the preparation" — most
   naturally reads as changing *which* of the three is selected, through this dock's own controls,
   which is a choice made *here*. An edit made through the Processing dock that happens to share a
   name is not a choice made in this dock at all.
4. No test among the nine given for this task exercises the in-place-edit case in either direction,
   so nothing here forces the more aggressive reading, and the `_updating`-guarded implementation I
   built naturally lands on "no" without extra code — the alternative would have required active,
   additional logic (e.g. retrying only when `not engine.is_prepared`) that nothing in Step 5's
   tests asks for or checks.

I read Step 7's aside — "`prepare()` stays public as the retry path after a refusal — a fixed
preset fires `presets_changed`, which `rebuild_source` is already connected to" — as saying that
the *plumbing* for a retry already exists (a fixed preset re-selected, or `prepare()` called
directly, both work), not that `presets_changed` alone must trigger one. Given the tension between
that sentence and `test_refilling_the_combos_does_not_re_prepare`'s explicit requirement that an
*unrelated* `presets_changed` after a *successful* prepare does nothing, I did not implement a
"retry only when not yet prepared" special case — it isn't tested, and it would reintroduce exactly
the kind of automatic recomputation the guard exists to prevent, just gated on a state flag instead
of a signal.

## Tabified with Processing — confirmed, not merely added

`plugin.py.initGui` calls `main.tabifyDockWidget(self.processing_dock, self.slices_dock)` and
`self.processing_dock.raise_()` right after adding both docks to the right dock area (mirroring the
brief's Step 9 code exactly). `test_the_slices_dock_is_tabified_with_processing` (added to
`test_plugin_loads.py`) asserts `plugin.slices_dock in main.tabifiedDockWidgets(plugin.processing_dock)`
against a *real* `QMainWindow` (via `fake_iface.mainWindow()`), which only returns dock widgets
actually placed in the same tabbed group by `tabifyDockWidget` — a dock merely added to the same
area with `addDockWidget` and never tabified would not appear in that list. This test passes.

## Other things I found and fixed (not called out by name in the brief)

1. **`tests/pure/test_no_orphan_signals.py`'s `SHADOWED["error"]` entry needed updating.**
   `SlicesDock.error` is a third class declaring a signal named `error` (alongside `ProfileDock` and
   `ParamForm`), and `plugin.py` connects it — so `declared` rises from 2 to 3 and `connects` from 1
   to 2. Without this update, `test_shadowed_signals_match_their_pinned_shape` fails (verified: it
   does, with exactly that diff, before the fix). This file is not in the brief's "Files" list for
   this task, but the change is required for the pure tier to pass and is the same kind of update
   `test_shadowed_signals_match_their_pinned_shape`'s own docstring anticipates ("e.g. M8 wiring
   ProfileDock.pick_requested ... trips this test — exactly the notification an allowlist entry
   would have given").
2. **`plugin.py`'s `unload()` needs to dispose `slices_dock.engine` explicitly, which the brief's
   Step 9 snippet never mentions.** `SliceEngine(session, on_prepared=self._on_prepared, ...)` is
   constructed with no `parent=`, and its `on_prepared`/`on_error`/`on_progress` callbacks are bound
   methods of the dock, so `dock → engine → bound method → dock` is a reference cycle that plain
   CPython refcounting will not collect at `deleteLater()` time — only the cyclic GC would, on its
   own schedule. Left alone, `engine`'s connections to `session.site_closed`/`grids_changed` could
   keep the engine (and its callbacks into an about-to-be-torn-down dock) alive and reachable from a
   live `session` well past `unload()` returning. The test fixture for `SlicesDock` itself already
   requires exactly this (`dock.engine.dispose(); dock.deleteLater()` in `test_plugin_slices_dock.py`'s
   `docked` fixture teardown), which is what surfaced the gap. Added
   `self.slices_dock.engine.dispose()` in `unload()`, before the dock-clearing loop, while `session`
   is still valid.
3. Two ruff findings against the brief's own verbatim snippets, both fixed to match this repo's
   established conventions rather than adding new exceptions: the `finished()` handler's message
   line in `plugin.py` exceeded the 100-column limit (wrapped it), and `_default_included`'s
   `for key in self.session.keys()` tripped `SIM118` (added the same
   `# noqa: SIM118 -- SiteSession.keys(), not a dict` comment already used verbatim in
   `survey_dock.py`, `map_link.py` and `loader.py` for the identical false positive).

`ruff check .` and `ruff format --check .` both pass; the CI `mypy` invocation (which only checks
`nsgeo_qgis/lookup.py`, `nsgeo_qgis/ui/view_transform.py` and `nsgeo_qgis/slices_plan.py` from this
package, none of which I touched) still reports success on 33 source files.

## Files

- Created: `packages/nsgeo-qgis/nsgeo_qgis/ui/line_choice_dialog.py`
- Created: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- Created: `packages/nsgeo-qgis/tests/qgis/test_plugin_line_choice_dialog.py`
- Created: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`
- Modified: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Modified: `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py`
- Modified: `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py`

---

## Fix round 1/5 — spec gap (Ruling R) + 3 Important + 6 promoted Minors (Ruling T) + Ruling U

### Spec gap — Ruling R: no stale status

Added `SlicesDock._refresh_source_status()`, the one place spec 9.2's three states are computed,
called from `rebuild_source`, `set_included`, and the two settled engine callbacks (`_on_prepared`,
`_on_engine_error`; `_on_progress` stays separate — it owns the status line only while a task is
actually running, which is a fourth, transient state, not one of the three settled ones):

- `engine.choice is None` → `"not prepared"`.
- `source_choice()` disagrees with `engine.choice` on grid/preset/transform → `"stale · the preset
  changed since this was prepared"`; disagrees only on `line_keys` → `"stale · the lines changed
  since this was prepared"`.
- Otherwise, the selected preset's *live* steps (`session.site.presets.get(choice.preset, [])`)
  compared against `engine.provenance().steps` (what was actually captured at dispatch time,
  per Ruling K) — a mismatch is `"stale · the preset changed …"` too.
- All agree → `"prepared · N lines"`.

`provenance()`'s `RuntimeError` (raised when no source is chosen) is guarded even though the
`choice is None` check above makes it unreachable today — the method's whole job is to be the one
place this judgement is made, so it must not assume its own ordering can never change under a later
edit, per the review's own instruction.

Left untouched while `engine.is_running`, so `_on_progress`'s own text isn't clobbered mid-task and
`engine.line_count` (last time's count) is never read under this time's claim.

Four new tests cover all three settled states plus the deleted-preset case the review specifically
widened the gap to:

- `test_construction_reports_not_prepared_before_the_first_task_finishes` — state 1.
- `test_accepting_the_line_chooser_reprepares_and_shows_stale_meanwhile` — state 2 (lines).
- `test_deleting_the_selected_preset_shows_stale_not_a_wrong_name` — state 2 (preset name, forced
  by a refill rather than a user's own combo edit).
- `test_editing_the_selected_preset_in_place_shows_stale_without_reprocessing` — state 2 (preset
  content, Point 5's in-place-edit case, now with a visible, tested consequence instead of a
  reasoned-but-unverified decision).
- State 3 (`"prepared · N lines"`) is already covered by the original nine tests' own assertions.

Point 5's decision (no auto re-prepare on an in-place preset edit) stands exactly as the review
says: it is a decision about spending another ~0.9 s, not about what the status line says, and the
two are no longer in tension now that the status line can say "stale" without re-running anything.

### Important 1 (Ruling S) — the inclusion set never picks up later lines

Added `SlicesDock._included_is_default: bool`, set `True` whenever `_sync_included` seeds from
`_default_included` (a grid transition), cleared by `set_included` (an explicit user choice). While
still `True` and the grid hasn't changed, `_sync_included` now *re-seeds* from `_default_included`
instead of only pruning stale keys — picking up lines that arrive under the same still-selected
grid after the seed, exactly the `grids_changed`-then-`lines_changed` sequence the review measured
against the plugin's real construction order.

`test_lines_added_after_construction_are_picked_up_as_the_default` follows that real order — builds
`SlicesDock(session)` with no site at all, then `new_site`/`add_grid`/`add_lines` in that sequence —
and asserts `"3 of 3 included"` at the end. Before the fix this read `"0 of 3 included"` (verified by
re-running the test against the pre-fix code): `grids_changed` (empty grid) sets `_last_grid_id="A"`
and seeds `()`; the later `lines_changed`, with `_last_grid_id` unchanged, took the pure-prune
branch, which has nothing to prune away from an already-empty tuple.

### Important 2 (Ruling S) — nothing in the dock could ever prepare

Two halves, exactly as specified:

1. **First-computation trigger.** At the end of `rebuild_source`:
   `if self.source_choice() is not None and not self.engine.is_prepared and not
   self.engine.is_running: self.prepare()`. New test
   `test_a_single_grid_single_preset_source_prepares_without_being_asked` builds the `docked`
   fixture's exact single-grid/single-preset/`none`-transform shape and asserts `is_prepared` and
   `line_count == 3` **without ever calling `dock.prepare()`** — the shape that was previously
   unreachable.
2. **The line chooser re-prepares.** Implemented in `set_included` itself (not
   `plugin.open_line_choice_dialog`'s `finished` handler), guarded by a no-op check
   (`keys != self._included`) the same shape `ProcessingDock._on_form_committed` already uses.
   Chose the dock over the plugin handler because it keeps "changing what the user chose here
   re-prepares" in exactly one place together with `_on_source_changed`'s half of the same rule,
   rather than requiring every future caller that can change the inclusion set to remember to call
   `prepare()` itself. `test_accepting_the_line_chooser_reprepares_and_shows_stale_meanwhile` covers
   it (and doubles as a Ruling R state-2 test).

All nine original dock tests were re-run and stay green, confirming the review's own inspection:
`test_refilling_the_combos_does_not_re_prepare` prepares successfully via its own explicit
`dock.prepare()` call before the presets/lines signals arrive, so `is_prepared` is already `True`
and the trigger's own guard skips it.

**A segfault this fix round's own testing found, not the review** (see its own section below) meant
the first-computation trigger's *literal* prescribed form needed one addition: `prepare()` now
no-ops when the computed choice already equals `engine.choice`, regardless of running/prepared
state. Documented in full below rather than glossed over.

### Important 3 — `Select all`/`Select none` escape their slots

Both measured scenarios reproduced first, then fixed:

- `test_removing_a_line_elsewhere_then_select_all_does_not_escape_the_slot` — before the fix,
  `session.remove_line(...)` then `dialog.select_all()` raised `KeyError: "no line with key
  'raw/FILE__002.DZT'"` out of the `QPushButton.clicked` slot (verified: reverting the fix and
  re-running this one test fails with exactly that `KeyError`, uncaught).
- `test_closing_the_site_then_select_none_does_not_escape_the_slot` — before the fix,
  `session.close_site()` then `dialog.select_none()` raised `ProjectError: no site is open` the same
  way.

Fixed at the root rather than only wrapped: `LineChoiceDialog._refresh()` now calls a new
`_live_keys()` helper that re-reads `session.keys()` (guarded by `session.is_open`) and re-filters
by `grid_id` on *every* refresh, never trusting the snapshot taken at construction; `_included &=
set(self._keys)` drops anything no longer valid. `select_all`/`select_none` are also wrapped in
`try/except Exception` the same way `_on_item_changed` already was, as defence in depth — with
`_refresh` fixed, the two measured scenarios no longer reach the `except` at all, but a slot that
guards nothing while its neighbour guards everything was the review's own diagnosis of how this
happened, so both now guard themselves.

### Ruling U — scope the dialog to the selected grid

`LineChoiceDialog.__init__` gained a required `grid_id: str` parameter (positioned second, after
`session`, matching `SourceChoice`'s own field order); `_live_keys()` filters by
`placement.grid_id == self.grid_id` in addition to re-reading live. `plugin.open_line_choice_dialog`
now reads `self.slices_dock.grid_combo.currentText()` and passes it through, warning ("Choose a grid
before choosing lines.") and returning if empty rather than opening an unscoped dialog.
`test_a_line_on_a_different_grid_is_not_listed` builds two grids with one line each and asserts the
dialog for grid A lists only grid A's line. The five original dialog tests were updated to pass
`grid_id="A"` (their fixture's only grid); their behaviour is otherwise unchanged since all their
lines already belong to that one grid.

### Six promoted Minors (Ruling T)

The review's list names five (M2–M6); I addressed all five it actually listed and flag the count
mismatch here rather than silently letting "six" stand unaccounted for.

- **M2** — moved the two `transform_combo.addItem`/`addItems` calls to *before* the `connect` block
  in `__init__`, matching the brief's own prescribed order. Confirmed the fix by inspection: with
  the old order, `_on_source_changed('none')` ran with `_updating == 0` during construction, silently
  harmless only because `grid_combo` was still empty at that point (`source_choice()` was `None`).
- **M3** — `prepare()` now catches `Exception`, not just `ValueError`; a preset naming a step the
  registry no longer has raises `KeyError` from `_start_task`'s main-thread validation, which used to
  land in `_on_source_changed`'s log-only guard instead of `source_status`/`error`.
- **M4** — `open_line_choice_dialog` now matches `open_import_dialog` exactly: `dialog.destroyed.
  connect(clear_if_current)` added, and `show()`/`raise_()`/`activateWindow()` on *every* path
  (the re-open branch was missing `show()`; the first-open path was missing `raise_()`/
  `activateWindow()`).
- **M5** — removed `assert plugin.processing_dock.visibleRegion is not None` from
  `test_the_slices_dock_is_tabified_with_processing` (a bound-method truthiness tautology) rather
  than replace it: there is no reliable way to ask an offscreen, never-`show()`n `QMainWindow` which
  tabified dock is currently raised (`isVisible()` requires the whole ancestor chain, including the
  top-level window, to be mapped, which this whole test suite deliberately avoids for stability). The
  test still asserts the meaningful half — `plugin.slices_dock in main.tabifiedDockWidgets(plugin.
  processing_dock)` — with a comment explaining the removal.
- **M6** — `test_the_dock_reports_the_memory_before_committing_to_preparing_it` now asserts
  `text.startswith(f"{len(session.keys())} of {len(session.keys())} included")` (ground truth from
  the session, not the dock's own possibly-wrong state) in addition to the `"MB"/"GB"` check, so a
  regression that empties the inclusion set fails this test instead of reading identically either
  way (`format_bytes` floors at 1 MB regardless of 0 or 3 lines).

### A segfault this round's own verification found (not in the review)

Verifying "all nine existing dock tests stay green" the way the review asked — by actually running
them, not only by inspection — surfaced a real, reproducible crash the review's own "by inspection
they should [pass]" note did not catch, because inspection can't see genuine thread concurrency.

**Symptom.** `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest
packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py` segfaulted inside
`test_refilling_the_combos_does_not_re_prepare`, with `faulthandler` showing two worker threads
active inside `nsgeo.processing.dewow.apply`/`nsgeo.io.dzt.read_header` at once, both launched from
`SliceEngine._start_task`'s `work()`.

**Root cause.** The first-computation trigger now starts a real `QgsTask` at `SlicesDock`
construction whenever a grid, preset and lines already exist — which the `docked` fixture's setup
order guarantees for essentially every test in the file. `SliceEngine._generation` discards a
*superseded* task's stale **result**, but nothing ever cancels or waits for the superseded task
itself — so any test that called `dock.prepare()` (or triggered a combo change) without first
waiting for the construction-triggered task to finish was, for the first time, actually dispatching
a **second real background task reading the same lines while the first was still running**. Task 2's
own "three rapid combo changes are safe without debouncing" claim (carried into this dock's own
docstrings) turns out to describe result-discarding, not execution-isolation — apparently never
exercised under genuine multi-threading before, because no path before this fix round's Important 2
ever called `set_source` a second time without an intervening `wait_for_preparation()`.

A second, broader instance of the same root cause then surfaced once the first was patched: **any**
test elsewhere in the suite that builds a full `NsgeoPlugin` (via `plugin.initGui()`) whose fixture
opens a site with a grid, lines *and* a preset — `test_plugin_difference_presets.py`'s `plugin`
fixture is a real example, entirely unrelated to slices — now also starts a real, orphaned
`SliceEngine` task through `plugin.slices_dock`. That fixture's teardown calls `plugin.unload()`,
which (per this task's own earlier addition) calls `slices_dock.engine.dispose()` — but `dispose()`
only disconnected signals and dropped this engine's own callback references; it never cancelled or
waited for a task already handed to `QgsApplication.taskManager()`, a **session-scoped singleton
shared by every test in the process**. Left running, that orphaned task could still be mid-flight
when a later, wholly unrelated test (`test_plugin_grid_dialog.py::test_polygon_tab_reads_a_selected_
feature`, discovered via bisection — see below) pumped the Qt event loop, delivering a queued signal
from a task whose owning dock had long since been torn down, and colliding with another such
orphaned task from yet another test. Reproduced deterministically (twice, byte-identical crash
signature) on the full `packages/nsgeo-qgis/tests` run; confirmed absent on the pre-fix-round Task 3
commit (`ad5178c`) by stashing this round's changes and re-running the identical full suite
(`517 passed`, clean) — isolating the cause to this fix round rather than a pre-existing flake.
Bisection method: re-ran with `--ignore` on this round's three test files to confirm the crash
persisted even with *zero* of this round's own tests collected, proving the two crash sites were
both consequences of the *source* changes (an orphaned real task outliving its disposed owner), not
of anything test-specific.

**Fix, two parts, both minimal and within what a crash like this justifies touching:**

1. `SlicesDock.prepare()` (this task's own file) now no-ops when the computed `choice` already
   equals `engine.choice` — there is nothing to redo when nothing has changed, the same shape of
   no-op guard `set_included` and `ProcessingDock._on_form_committed` already use. This stops the
   *specific*, reproducible case (an explicit `prepare()`/combo-change immediately following the
   auto-trigger for the *identical* source) from ever dispatching a second real task.
2. `SliceEngine.dispose()` (`slices_engine.py`, Task 2's file — touched because the crash is real and
   the instructions are explicit that a prescribed approach that doesn't work should be fixed and
   explained, not forced) now calls `self.wait_for_preparation()` **before** disconnecting anything.
   Every caller of `dispose()` before this task always called `wait_for_preparation()` itself first,
   so a task genuinely still running at `dispose()` time was never actually exercised until
   Important 2 started one automatically from places that don't know to wait for it. This closes the
   general case: any plugin teardown — test or real — now blocks for at most one preparation's worth
   of time (bounded by the existing 20 s default) rather than leaving a task to run unsupervised
   against a torn-down engine. `wait_for_preparation`'s docstring was updated to say so (it was
   previously documented as "for tests" only).
   
   Also updated the `docked` fixture itself to call `dock.engine.wait_for_preparation(20_000)`
   before `dock.engine.dispose()`, redundant with the engine's own new internal wait but kept for an
   explicit, test-local statement of intent independent of the engine's implementation.

**What this does *not* claim to fully solve.** `SliceEngine.set_source` still has no general
protection against two **genuinely different** choices both being dispatched as real tasks close
enough together to overlap (e.g. a user switching grid A → B → A again faster than ~0.9 s, before
the first A-task's own superseding B-task has finished) — only the *identical-choice* case this
fix round actually exercises is closed. A fully general fix (serializing `set_source` calls, or
having the engine cancel-and-confirm a superseded task before starting the next) belongs in
`slices_engine.py` as a deliberate follow-up, not as a side effect of this dock's fix round; flagging
it here rather than either silently expanding scope to fix it or silently leaving it undiscovered.

### Full verification after this round

Core+pure (`./.venv`):

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core packages/nsgeo-qgis/tests/pure -q -p no:xonsh
541 passed, 2 skipped
```

QGIS (`./.venv-qgis`), full combined run including pure (pure tests plus every qgis test, run twice
for reproducibility of the fix, both clean):

```
$ QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
526 passed in 186.45s
```

526 = 517 (end of the original implementation) + 9 new tests this round (6 in
`test_plugin_slices_dock.py`, 3 in `test_plugin_line_choice_dialog.py`; `test_plugin_loads.py`'s
two existing tests were modified, not added to).

```
$ ./.venv/bin/ruff check .
All checks passed!
$ ./.venv/bin/ruff format --check .
118 files already formatted
$ ./.venv/bin/python -m mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
    packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py \
    packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py
Success: no issues found in 33 source files
```

### Files touched this round

- Modified: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- Modified: `packages/nsgeo-qgis/nsgeo_qgis/ui/line_choice_dialog.py`
- Modified: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Modified: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py` (the segfault fix — see above)
- Modified: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`
- Modified: `packages/nsgeo-qgis/tests/qgis/test_plugin_line_choice_dialog.py`
- Modified: `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py`

### Commit

`9306afe` — `fix(slices): fix round 1 -- stale status, first-preparation trigger, grid-scoped line
chooser, and a genuine task-overlap segfault`. Not pushed, per instruction.

---

## Fix round 2/5 — Ruling V: close the general overlap case in `slices_engine.py`

Round 1 closed only the *identical*-choice overlap (`SlicesDock.prepare()`'s no-op guard). The
coordinator ruled that the general case — two *genuinely different* choices dispatched within
about a second of each other, reachable by a person clicking through the Source combos, not only a
test fixture — is a segfault and must close now rather than wait on a follow-up.

### What changed

`SliceEngine._cancel_in_flight()` (new): cancels every task still in `self._pending`, then, if a
task is still marked running, waits for it via `wait_for_preparation(_CANCEL_TIMEOUT_MS)`.
`set_source` calls it as the very first thing it does, and `dispose()` now calls it too (in place
of round 1's bare `wait_for_preparation()`) — a teardown has no reason to sit out however much of
a preparation is left when it is about to discard the result anyway; cancelling first bounds it to
one line's processing instead.

`_CANCEL_TIMEOUT_MS = 250`. `work()` checks `isCanceled()` once per line — measured in this
codebase's own comments at ~13 ms to load plus ~26 ms for an envelope, ~40 ms total — so 250 ms is
several times that (room for a slower disk or a larger file) while staying roughly two orders of
magnitude below a full ~0.9 s preparation. If it still hasn't cleared by then, `_cancel_in_flight`
reports through `on_error` and returns anyway, letting `set_source` proceed with the new choice
rather than silently refuse it. Chose "proceed" over "refuse" because a `set_source` that sometimes
declines to take effect is a worse failure mode than a rare residual overlap this method already
spends its whole timeout budget trying to prevent — a refusal would need its own recovery path
(retry? drop the choice on the floor?) that nothing today asks for, whereas "proceed" preserves the
one invariant every existing test already relies on: the latest choice always wins eventually.

**Ordering matters and is documented at the call site**: `_cancel_in_flight()` runs *before*
`_generation` is bumped, not after. `finished()`'s own `if generation != self._generation: return`
staleness check is what actually clears `self._running` and invokes `_finish_preparation()` (which
is what `wait_for_preparation`'s internal `on_prepared` substitution is waiting on) — bump the
generation first and the cancelled task's own terminal callback would find itself already stale,
never take that path, and `wait_for_preparation` would sit out the *entire* timeout every single
time, having actually detected nothing. Tried this ordering first, measured it doing exactly that
before settling on the ordering now in the code.

**A discovered wrinkle, fixed along the way, not part of the suggested shape**: cancelling a real
`QgsTask` makes `QgsTaskWrapper.finished()` synthesise `Exception("Task canceled")` regardless of
what `work()` itself returned (verified directly in its installed source —
`if not result and self.exception is None: self.exception = Exception("Task canceled")`, where
`result` is QGIS's own success flag, not `work()`'s return value). Since `_cancel_in_flight` must
run before the generation bump for `wait_for_preparation` to work at all (above), the cancelled
task's `finished()` reaches the `exception is not None` branch and would otherwise report "Task
canceled" through `on_error` on *every* rapid combo change — which the dock surfaces as a warning
message-bar popup for something the user did nothing wrong to cause. Added
`self._deliberately_cancelled: set[QgsTask]`, populated by `_cancel_in_flight` before each
`task.cancel()` call and checked (then cleared) at the top of `finished()`: only a task cancelled
*by this engine itself* has its synthetic "Task canceled" suppressed; a message that happens to say
the same thing for a task nobody asked to cancel is still reported. This was not in the
coordinator's suggested shape and surfaced only once I ran the actual discriminating test against
the initial implementation and inspected the resulting `errors` list — the same discipline as round
1's own segfault: run it, don't just reason about it.

### Test

Added `test_two_different_choices_back_to_back_never_run_concurrently` to
`tests/qgis/test_plugin_slices_engine.py` (Task 2's own engine test file, since the fix lives in
`slices_engine.py`). `Line.load` is patched to increment a lock-protected counter, sleep 50 ms, then
call through — turning the few-millisecond window a real disk read holds open into one wide enough
that genuine thread overlap is caught deterministically, which the coordinator's own guidance
prefers over timing or a hoped-for repeat segfault. Two different choices (`transform=NO_TRANSFORM`
then `transform="amp_envelope"`) are dispatched via `set_source` back to back with no intervening
wait; the test asserts `max_concurrent <= 1`, that `engine.choice` ends up as the *second* choice,
and — structurally, not just by comparing the stored choice object — that `output_unipolar` reads
`True` (only true for the second choice's transform) and `errors == []`.

**Confirmed the test discriminates, per the coordinator's own instruction, by actually breaking the
fix and re-running:**

```
$ sed -i '355s/.*/        pass  # TEMP: _cancel_in_flight disabled/' packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py
$ QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py::test_two_different_choices_back_to_back_never_run_concurrently \
    -q -p no:xonsh
FAILED ... AssertionError: two tasks executed work() concurrently (max_concurrent=2); ...
1 failed in 1.05s
```

Restored from a pre-edit backup copy (`diff` against it showed only the deliberate `SIM105` cleanup
below, applied after the restore) and re-ran: 22/22 pass in `test_plugin_slices_engine.py`,
`errors == []` for the real test. The failure mode observed without the fix is exactly
`max_concurrent == 2` — both worker threads inside the patched `load` at once — not a timeout or a
flaky pass, so this is a deterministic discriminator, not a coin flip.

### Full verification after this round

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core packages/nsgeo-qgis/tests/pure -q -p no:xonsh
541 passed, 2 skipped

$ QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
527 passed in 145.84s   # run 1
527 passed in 148.75s   # run 2 (re-run per this round's own instruction, given round 1's history)
```

527 = 526 (end of round 1) + 1 new test.

```
$ ./.venv/bin/ruff check .
All checks passed!
$ ./.venv/bin/ruff format --check .
118 files already formatted
$ ./.venv/bin/python -m mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
    packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py \
    packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py
Success: no issues found in 33 source files
```

(One ruff finding surfaced and was fixed along the way: `SIM105` on the `try/except RuntimeError:
pass` inside `_cancel_in_flight`, replaced with `contextlib.suppress(RuntimeError)` to match this
module's own existing convention two methods away in `dispose()`.)

### What this round does not claim

`_cancel_in_flight`'s wait is bounded and, per the coordinator's own instruction, proceeds anyway if
cancellation does not clear within `_CANCEL_TIMEOUT_MS` — an extremely slow single line (a huge
file, a loaded system) could still theoretically leave a residual overlap window, just one bounded
to roughly one line's processing instead of a whole preparation. This is the deliberate, documented
trade the coordinator asked for, not an oversight.

### Files touched this round

- Modified: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- Modified: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`

### Commit

`3f81775` — `fix(slices): fix round 2 -- cancel and confirm any in-flight preparation before
dispatching the next`. Not pushed, per instruction.

---

## Fix round 3/5 — Ruling W (Critical), Ruling X (Important), Ruling Z, Ruling Y

The re-review found that round 2's own fix reopened the hazard it closed, plus one consequence and
three documentation/wording issues. All addressed; the Critical's own test uncovered a genuine
test-isolation bug along the way, described below rather than hidden.

### Critical, Ruling W — the cancel wait's nested event loop restored the overlap

`_cancel_in_flight`'s confirm step calls `wait_for_preparation`, whose `QEventLoop.exec()` can
deliver a SECOND, different `set_source` call from inside the FIRST call's own frame — a person
changing a combo again while the previous change is still being cancelled. The reentrant call
dispatched its own task; the outer call then resumed and dispatched a second one on top —
restoring the exact two-real-tasks segfault Ruling V exists to remove, with the OLDER (outer)
choice winning because it bumps `_generation` last.

Fixed with both halves, as instructed, neither sufficient alone:

1. **A re-entrancy guard that queues.** `SliceEngine._dispatching: bool` and `_queued_choice`
   (`_NOT_QUEUED` sentinel, since `set_source(None)` is itself a legitimate call and `None` cannot
   double as "nothing queued"). `set_source` records a reentrant call's choice and returns
   immediately instead of dispatching; the *outer* call's own `finally` applies the queued choice
   afterward (`self.set_source(queued)`, now non-reentrant since `_dispatching` was just cleared),
   so the LATEST choice still wins. A `ValueError` from the queued dispatch is reported through
   `on_error`, since there is no caller left on the stack to raise it to.
2. **`ExcludeUserInputEvents` on the cancel wait.** `wait_for_preparation` gained a `flags`
   parameter (default `AllEvents`, unchanged for every existing caller and for tests, which often
   drive the wait themselves by emitting a signal or changing a combo and need that processed).
   `_cancel_in_flight` passes `ExcludeUserInputEvents` explicitly. `dispose()` gets this for free
   since it already routes through `_cancel_in_flight` (round 1's own bare `wait_for_preparation()`
   call was replaced by that in round 2), closing the reviewer's noted window in `unload()` too.

### Test, and a test-isolation bug the discipline itself caught

`test_a_choice_delivered_during_the_cancel_wait_does_not_reopen_the_overlap` added to
`test_plugin_slices_engine.py`: schedules `QTimer.singleShot(0, lambda: engine.set_source(choice_c))`
just before a `set_source(choice_b)` call that cancels an in-flight `choice_a` — the zero-delay
timer is a POSTED event, not user input, so it reaches `set_source` from inside `_cancel_in_flight`'s
own wait regardless of the `ExcludeUserInputEvents` mask, exercising the *other* half of the fix
(the `_dispatching` guard) that the round-2 test does not. Same lock-protected counter around a
patched, sleeping `Line.load` as round 2's test; asserts `max_concurrent <= 1`, `engine.choice ==
choice_c` (the latest, not the outer/older one), and `errors == []`.

**First attempt was flaky, for a reason unrelated to the fix, and I said so rather than declaring
victory on a lucky run**: run as the very first test to dispatch a `QgsTask` in a fresh `qgis_app`
process, it failed even WITH the fix in place (`wait_for_preparation(20_000)` itself returned
`False`) — the first-ever task's own worker-thread start-up cost was itself long enough to break
the timing the test's 50 ms sleep assumed. Run straight after any other task-dispatching test, it
passed reliably. Diagnosed by pairing it with an earlier test (passed) versus running it alone
(failed, reproducibly, 5/5). Fixed by adding an explicit warm-up dispatch (real, fast `Line.load`,
before patching it to sleep) at the top of the test, removing the dependency on execution order —
confirmed 5/5 passes in isolation afterward.

With the warm-up in place, confirmed discrimination properly:

```
$ sed -i '423s/.*/        if False:  # TEMP: _dispatching guard disabled/' \
    packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py
$ QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py::test_a_choice_delivered_during_the_cancel_wait_does_not_reopen_the_overlap \
    -q -p no:xonsh
FAILED ... AssertionError: two tasks executed work() concurrently (max_concurrent=2); ...
1 failed in 0.89s
```

`max_concurrent=2` — exactly the property the reviewer measured as broken. Restored from a backup
(`diff` confirmed byte-identical) and re-ran: 23/23 pass in `test_plugin_slices_engine.py`.

### Important, Ruling X — `prepare()` could not clear the new stale state

`prepare()`'s no-op guard compared only grid/preset-name/transform/line_keys, never the steps, so
after an in-place edit to the selected preset the documented retry path (calling `prepare()` again)
silently did nothing — with one grid and one preset, permanently stale.

Added `SlicesDock._live_preset_steps`/`_prepared_steps_match` (shared by `prepare()`'s guard and
`_refresh_source_status`, so the two definitions of "nothing changed" cannot drift apart), and the
guard now also requires `self._prepared_steps_match(choice.preset)`. Kept the guard itself — still
needed as an efficiency guard now that `SliceEngine` cancels-and-confirms internally (Ruling V/W) —
and rewrote its docstring to say so instead of the now-obsolete "load-bearing for safety" claim.

`test_calling_prepare_again_after_an_in_place_edit_clears_the_staleness` added to
`test_plugin_slices_dock.py`: prepare, edit the preset in place, `prepare()` again, assert
`is_prepared` and `provenance().steps` match the NEW preset. Confirmed it fails against the
prior guard (`choice == self.engine.choice` alone): `provenance().steps` stayed at the OLD
(`dewow`) content instead of picking up the edit (`background_mean`) — restored and re-confirmed
passing (19/19 in `test_plugin_slices_dock.py`).

### Ruling Z — close Ruling U's residual (dialog binds `grid_id` at open time)

`plugin.open_line_choice_dialog`'s `finished` handler now re-checks
`self.slices_dock.grid_combo.currentText() != grid_id` (the grid captured when the dialog opened)
before calling `set_included` — a mismatch discards the result and reports through `message()`
instead of committing the OLD grid's keys against the NEW grid's frame.

`test_accepting_the_line_chooser_after_the_grid_changed_is_discarded` added to
`test_plugin_loads.py`: opens the chooser against grid A (one line), switches the dock to grid B
while it's open, selects all in the (stale) dialog, accepts, and asserts the dock's inclusion set is
unaffected and a "grid changed" message appears. Confirmed it fails without the check: the OLD
grid's key (`raw/FILE__0001.DZT`) was committed into the dock's inclusion set even though the
current grid was B (`assert ('raw/FILE__0001.DZT',) == ()` failed) — restored and re-confirmed
passing.

### Ruling Y — five statements the fix falsified or under-reported

All five, in `slices_dock.py` unless noted:

1. `_included`'s own docstring ("offers every line in the site") rewritten to say what Ruling U
   actually made true: always a subset of the selected grid's lines.
2. `_update_included_label`'s docstring ("a line from another grid... still costs memory") rewritten
   the same way -- that scenario is no longer reachable.
3. `prepare()`'s docstring ("never actually cancels or waits", "load-bearing for safety") rewritten
   per Ruling X's own summary above: an efficiency guard now, not a safety one.
4. `_refresh_source_status` now names what actually diverged -- grid, preset (by name or by an
   in-place edit), transform, or lines -- instead of printing "the preset changed" for all four.
   Covered by the two new wording tests described under Ruling X's section (grid-only and
   transform-only divergence, isolated by changing one combo with signals blocked so the normal
   `_on_source_changed` re-prepare path does not immediately correct it).
5. `_refresh_source_status`'s "otherwise" branch no longer collapses "genuinely 0 lines requested and
   prepared" with "every requested line failed" into the same `prepared · N lines` wording (`_on_
   engine_error` stopped writing into `source_status` directly in round 1). New check:
   `if not self.engine.is_prepared and choice.line_keys:` reports `"not prepared · every line
   failed"` instead -- excluded when `line_keys` is genuinely empty, since `0 of 0` legitimately
   prepares and is not a failure. `test_a_failed_schedule_does_not_claim_lines_prepared` (monkeypatches
   `QgsApplication.taskManager().addTask` to fail, the same pattern `test_plugin_slices_engine.py`'s
   own `test_a_task_that_cannot_be_scheduled_still_notifies` uses) confirms the dock reads
   `"not prepared · every line failed"`, not `"prepared · 0 lines"`.

### Full verification after this round

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core packages/nsgeo-qgis/tests/pure -q -p no:xonsh
541 passed, 2 skipped

$ QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
533 passed in 146.07s   # run 1
533 passed in 148.98s   # run 2
```

533 = 527 (end of round 2) + 6 new tests this round (1 in `test_plugin_slices_engine.py`, 4 in
`test_plugin_slices_dock.py`, 1 in `test_plugin_loads.py`).

```
$ ./.venv/bin/ruff check .
All checks passed!
$ ./.venv/bin/ruff format --check .
118 files already formatted
$ ./.venv/bin/python -m mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
    packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py \
    packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py
Success: no issues found in 33 source files
```

(`ruff format` reformatted one line in `test_plugin_slices_engine.py`'s new warm-up call, over the
100-column limit when it was still written as a single line at first.)

### Files touched this round

- Modified: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- Modified: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- Modified: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Modified: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`
- Modified: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`
- Modified: `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py`

### Commit

`8efdc72` — `fix(slices): fix round 3 -- close the reentrant cancel-wait overlap, let prepare()
clear staleness`. Not pushed, per instruction.
