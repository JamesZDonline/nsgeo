# Task 6 report (#166 lost wakeup, #75 dispatch suspects)

## The before loop (from loop-before-notes.md and the controller's addendum)
3 rounds x 12 copies x 174 tests of test_plugin_site_scope.py at 3ee3090 (4 cores, load ~16).
- Hangs: none. "did not finish preparing" never printed, so no busy report named a cause.
- #196 flakes: 12 failures (5, 4, ... per round).
- Timing-window failures left alone: never_overlaps_preparations (26), waits_out_a_task_that_outlived_its_cancel (5).
- (f) candidate: moving_this_grids_grid_while_a_site_task_outlives_its_cancel_never_overlaps, 6 of 36 copies.

## Tests, with fail-first evidence
Command: `qgis_tests.sh test_plugin_site_engine.py -k "notify or progress_total or retiring or pile_up" -q` (5 failed before, 5 passed after).
- (a) test_a_peer_that_starts_during_the_preparing_notify_holds_the_dispatch: `assert started == []` -> `['preparing'] == []` (A's engine.set_source ran while the peer was live).
- (b) test_a_grid_moved_during_the_preparing_notify_still_prepares: HANGS before the fix, as the brief predicted. wait_for_site's busy report:
  ```
  the site did not finish preparing in 20000 ms
  active: True · preparing: 'A' (moved since dispatch) · queue: ['B', 'C']
  retry timer: off · reaper timer: off · in dispatch: False
  engine A: running False · live task False · pending tasks 0   (B, C likewise)
  grid A: preparing (4 of 4)   grid B: queued   grid C: queued
  ```
  A real lost wakeup: the engine finished, `_on_engine_prepared` returned early on the stale `_preparing_fp` for ever, no timer on. The recapture in (a) fixes it. Whether it is the one CI hit is not known (the loop never hung).
- (c) test_the_progress_total_never_shifts: `{4, 5} == {5}`, seen `[(0,5),(1,4),(2,4),(3,4),(4,4)]`.
- (d) test_a_retiring_engine_neither_reports_nor_waits_again: `assert 2 == 1` ("did not stop in time" twice), plus a "no longer exists" message.
- (e) test_disposed_engines_do_not_pile_up_as_children: `13 == 3`. Flush uses `QEvent.Type.DeferredDelete` (the repo's form, works on Qt5 and Qt6 enums).

## What changed
- `_start_next`: after the notify, `_preparing_fp` is captured again and the gate re-run. The engine's `set_source` is called only AFTER the notify, so the engine was never touched when the undo runs. The undo resets exactly this site's bookkeeping from the dispatch: `_preparing=None`, `_preparing_fp=None`, `_progress[grid]` popped, state "queued", grid re-inserted at queue head (if not already queued), one notify so the list stops saying "preparing 0 of n", `_retry.start()`. That is every field `_start_next` wrote before the notify (`_preparing`, `_preparing_fp`, `_states`, `_errors.pop` (nothing to restore), `_progress`, queue pop), so a later dispatch sees the pre-dispatch state. A move inside the notify needs no undo: the recapture picks up the new place.
- `_on_engine_progress`: records `(done + n_keys - total, n_keys)`; `n_keys` is the total stored at dispatch (never below the engine's total).
- `SliceEngine.detach()` (new; `_ignore` moved to slices_engine): disconnects `site_closed`, `grids_changed`, `lines_changed` (TypeError/RuntimeError suppressed, so twice is safe), `on_error/on_prepared/on_progress=None`, `on_grid_moved=_ignore`; touches no `_pending`. `SiteEngine._retire` calls it.
- `SiteEngine._release(engine)` = `dispose()` then `deleteLater()` (RuntimeError suppressed), used in `_drop_engine`, `_reap_retired`, `dispose`. Nothing touches the engine after it; SiteEngine.dispose twice is safe (dicts are empty the second time).

## (f) root cause: the test, not the code
Reproduced 2 of 12 and 3 of 16 copies under load with the real test. A scratch copy with tracing (deleted, not committed) showed:
- Hypotheses (i) and (ii) are both wrong: This grid was prepared and idle at the start, and its `on_grid_moved` was `_mark_grid_stale` at the move.
- `session.replace_grid` runs the whole grid change on the GUI thread (geometry rebuilds, the dock's `rebuild_source`). Under load that took 1.3 to 1.8 s wall, longer than the 0.8 s line the site task was held in. The site task ended during it (its `finished` ran in a nested wait), and only then did the dock's own `rebuild_source -> prepare()` call `engine.set_source`. `prepare()` gates on `site_engine.has_live_task` (slices_dock.py:1631), and it was False at that point. No overlap: counter.max_concurrent stayed 1.
- So `assert not dock.engine.is_running` asserted a wall-clock window, which the move itself can outlast.
Fix (test only, test_plugin_site_scope.py): a spy on `dock.engine.set_source` records any call made while `site_engine.has_live_task`; the test asserts none, and keeps the `not is_running` check only if the site's task is still live after the move. Verified: 48 copies under load, 0 failures (before: 2/12, 3/16); mutation (removing the `has_live_task` clause from `prepare()`) makes it fail with "This grid started beside the site's task". Mutation reverted.
No code change in the dock; no follow-up issue needed. The two narrow-window timing tests remain as the addendum said.

## Final counts
- test_plugin_site_engine.py: 68 passed (63 old + 5 new)
- test_plugin_site_scope.py: 177 passed (450 s) before the (f) test edit; the edited test re-run alone and in 48 loaded copies, all pass
- test_plugin_site_export.py: 33 passed; test_plugin_slices_engine.py: 88 passed; engine+slices_engine re-run after final edits: 156 passed
- `-m real_data`: 46 passed
- pure suite: 396 passed, 4 skipped
- ruff check, ruff format --check: clean; CI's mypy command: no issues in 65 files
- #196 flake did not occur in my runs.

## Deviations
- slices_dock.py and slices_engine's session wiring untouched except adding `detach`/`_ignore` to slices_engine.py. test_plugin_slices_dock.py not run (dock not touched).
- After the notify the undo also notifies once (the brief did not say to); without it the list would keep "preparing 0 of n" until the next dispatch.
