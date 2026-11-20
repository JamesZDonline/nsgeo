### Task 6: #166, the lost wakeup, and #75's dispatch suspects

**Before starting:** read the "before" loop's results (see **The #166 loop**). Record in the report:
- the batches run;
- the hangs, each with the busy report it printed;
- any #196 flakes.

If a hang's report names a cause these items don't cover, find its root cause with
superpowers:systematic-debugging. Add a deterministic test that drives that interleaving, and fix
it in this task as item (f).

**Files:**
- Modify: `P/site_engine.py` (`_start_next`, `_on_engine_prepared`, `_on_engine_progress`,
  `_retire`, `_drop_engine`, `_reap_retired`)
- Modify: `P/slices_engine.py` (add `detach`)
- Test: `T/qgis/test_plugin_site_engine.py`

**Interfaces:**
- **Produces `SliceEngine.detach() -> None`.** It disconnects the engine from `session.site_closed`,
  `grids_changed` and `lines_changed`, and sets `on_error`, `on_prepared` and `on_progress` to
  `None`, with `on_grid_moved = _ignore`. It does NOT cancel, clear or touch `_pending`: a running
  task still ends, and `has_live_task` still turns False when its `finished` runs. It is safe to
  call twice. `SiteEngine._retire` calls it in place of its own three assignments.
- **Produces the deferred deletion of disposed engines.** Wherever `SiteEngine` calls
  `engine.dispose()` (`_drop_engine`, `_reap_retired`, `dispose`), it then calls
  `engine.deleteLater()`.

**The items, each with its test:**

- **(a) The gate is re-run after the progress notify, and the registration is re-captured after it.**
  - The fix: in `_start_next`, after `_notify_changed()`, set `_preparing_fp` again. If
    `_anything_live()` is now true, undo the dispatch:
    - the grid goes back to the head of the queue, as `"queued"`, with no progress;
    - `_preparing` is set to `None`;
    - `_retry.start()`, then return.
  - Test `test_a_peer_that_starts_during_the_preparing_notify_holds_the_dispatch`:
    - A fake peer object with a settable `has_live_task` is passed to `add_exclusive`. The site's
      `on_changed`, on the first notify where A reads `"preparing"`, sets
      `peer.has_live_task = True`.
    - Assert that A's engine's `set_source` (wrapped to count) is not called while the peer is
      live, over about 300 ms of pumping.
    - Then set the peer to `False`. `wait_for_site(site, 20_000)` returns, and A is ready.
- **(b) A move inside the preparing notify still finishes.**
  - Test `test_a_grid_moved_during_the_preparing_notify_still_prepares`. The site's `on_changed`, on
    the first notify where A reads `"preparing"`, moves A with `site3.session.replace_grid(
    dataclasses.replace(grid_a, origin=(x + 1.0, y)))`. `wait_for_site(site, 20_000)` returns, A is
    ready, and its engine's frame is at the new origin.
  - **By reading, this hangs today.** A's engine has no choice yet when the move arrives, so it
    never hands the move over. `_preparing_fp` holds the old place, so `_on_engine_prepared` returns
    early forever with `_preparing` set. Confirm it fails before (a)'s fix. The recapture in (a) is
    its fix. It is a real lost wakeup; whether it is the one CI hit is for the loop to say.
- **(c) The progress total never shifts.**
  - The fix: `_on_engine_progress` records `(done + max(0, n_keys - total), n_keys)`, where
    `n_keys = len(choice.line_keys)` is stored at dispatch. A key the engine skipped counts as done.
  - Test `test_the_progress_total_never_shifts`. A's choice carries A's four keys plus one of B's
    line keys. Record every `site.grid_progress("A")` seen in `on_changed`. Every total is 5, and
    the done values never decrease.
- **(d) A retiring engine neither reports nor waits again.**
  - Test `test_a_retiring_engine_neither_reports_nor_waits_again`:
    1. Hold A's `Line.load` behind an `Event`, ignoring cancel, so the cancel wait runs out and the
       engine retires.
    2. `site3.session.remove_grid("A")`.
    3. Assert the site's `on_error` got exactly one "did not stop in time" message (one bounded
       wait, not two) and no "no longer exists" message. Today the retiring engine keeps its
       `on_error` and its session connections, so its own `_on_grids_changed` waits a second time
       and reports both.
    4. Release. `wait_for_site` returns, B and C are ready, and the retiring engine is gone after
       the reaper.
- **(e) Disposed engines don't pile up.**
  - Test `test_disposed_engines_do_not_pile_up_as_children`:
    1. Toggle B in and out of the source ten times, `wait_for_site` each time.
    2. Flush deferred deletes with `QCoreApplication.sendPostedEvents(None, <DeferredDelete>)`.
       Write the event type in a form PyQt5 and PyQt6 both accept, since CI runs both
       (`grep -rn DeferredDelete packages/nsgeo-qgis/tests` for the repo's form, if it has one).
    3. `len(site.findChildren(SliceEngine))` equals the number of grids with an engine.

- [ ] **Step 1: Write tests (a)–(e)** and any (f). Run each, and see (a), (c), (d) and (e) fail for
  their stated reasons. Record (b)'s result before the fix.

Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py -k "notify or progress_total or retiring or pile_up" -q`

- [ ] **Step 2: Implement** (a)–(e), and (f) if any.

- [ ] **Step 3: Run** `test_plugin_site_engine.py`, `test_plugin_site_scope.py`,
  `test_plugin_site_export.py`, `test_plugin_slices_engine.py` and `-m real_data`. Expected: all
  pass, except a #196 flake (note it).

- [ ] **Step 4: Commit and push:** `fix(site): the dispatch gate after the notify, a steady progress total, retiring engines detached, disposed engines deleted (#166, #75)`.

> **Controller, after Task 6 lands:** run the "after" loop at the branch head, the same way, and
> record both loops' numbers in the decision record. **#166 closes at merge only if** the "before"
> loop hung, its report named a cause, the fix addressed it, and the "after" loop showed no hang.
> Otherwise #166 gets a comment with what the report now says, and stays open.

---


**Controller's addendum (2026-11-19), the "before" loop's results.** Read
`.superpowers/sdd/2026-11-19-nsgeo-site-never-stuck-a/loop-before-notes.md` and the ledger's loop lines.
In short: 3 rounds × 12 copies × 174 tests of `test_plugin_site_scope.py` at 3ee3090 on a 4-core
machine (load ~16): **no hang** — "did not finish preparing" never printed, so no busy report
names a cause. #196 failed 12 times. Two tests failed on narrow timing windows (a 0.2 s / 0.15 s
state missed by polling under load): `test_editing_a_grid_in_site_scope_never_overlaps_preparations`
(26) and `test_leaving_the_site_waits_out_a_task_that_outlived_its_cancel` (5). Leave those alone.

**(f), bounded:** `test_moving_this_grids_grid_while_a_site_task_outlives_its_cancel_never_overlaps`
failed 6 of 36 copies after ~1.7 s at `assert not dock.engine.is_running, "This grid waits for the
site's task"` — a state assertion, not a polling window, right after `has_live_task` was asserted
True. That is either a weak test or a real overlap of This grid's preparation with a live site
task (R-P5 / final review D2). Investigate it with superpowers:systematic-debugging. The two
hypotheses in the notes are untested: (i) This grid's engine was still preparing when the test
began (the test never asserts `dock.engine.is_prepared` first, unlike its neighbour at ~1834), so
`counter.concurrent == 1` may have been This grid's own read; (ii) `on_grid_moved` was already
`None` at the move. Find which, using load (e.g. `stress-ng`/a CPU-burner, or several copies of
just that test with `-k`) to reproduce. Then:
- if it is the test (i), fix the test so it starts from a prepared This grid, and say so;
- if it is the code, add a deterministic test that drives the interleaving and fix it, provided
  the fix stays inside the site_engine / slices_engine / slices_dock hand-off;
- if it is bigger than that, stop at the root cause and report it for a follow-up issue.
Record which in the report. Do not spend more than about an hour of wall time on (f) before
reporting what you have.
