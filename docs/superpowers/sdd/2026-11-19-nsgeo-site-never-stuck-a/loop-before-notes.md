# before-loop (3ee3090) round 1 notes, 2026-11-19 ~14:30, 4 cores, load avg 16
- never_overlaps_preparations: 11/12 F at spin_until(grid_progress("B")==(1,4)) 20 s — narrow 0.2 s window missed under load (timing).
- leaving_the_site_waits_out_a_task_that_outlived_its_cancel: 3+ F at spin_until(counter.concurrent==1) — 0.15 s window (timing).
- moving_this_grids_grid_while_a_site_task_outlives_its_cancel_never_overlaps: F in copies 5, 8 after 1.7 s at
  `assert not dock.engine.is_running` right after replace_grid, with has_live_task asserted True just before.
  NOT a narrow-window spin: a real-state assertion. Candidate for Task 6 (f) — check how This grid's engine
  decides to re-prepare after a move while the site's cancelled task is live (_mark_grid_stale path).
  Read so far: _mark_grid_stale only sets _grid_prepare_pending; _run_pending_grid_prepare sets on_grid_moved=None only
  when site.has_live_task and _foreign_live() are both False. So engine.is_running True after the move means either
  (i) the dock engine was already running before the move (fixture's This-grid prep not finished? test doesn't assert
  is_prepared like never_overlaps does; concurrent==1 could then be the dock engine's own read), or (ii) on_grid_moved
  was None at the move. Untested hypotheses — hand to Task 6 (f) with this note.
## Round 1 complete (1582 s; 12 copies x 174 tests): 0 hangs ("did not finish preparing" never printed)
 11 never_overlaps_preparations (timing window) | 5 #196 window_left_behind | 3 waits_out (timing window) | 2 moving_this_grids_grid (state assert)
 copy 3: 174 passed (so the timing tests can pass under this load).
## Round 2 complete (1655 s): 0 hangs
 10 never_overlaps_preparations | 4 #196 | 2 moving_this_grids_grid | 2 waits_out ; copies 7 and 11 clean.
