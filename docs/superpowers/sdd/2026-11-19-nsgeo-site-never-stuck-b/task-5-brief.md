### Task 5: Whole site never freezes

**Files:**
- Modify:
  - `P/site_engine.py`: `fills_missing`, `fill_jobs`.
  - `P/ui/site_scope.py`: `refresh_slice`, `display_limit`, `_run_tick`, `enter`/`leave`, the cancel handling against the site record.
- Test: `T/qgis/test_plugin_fill_flow.py`, `T/qgis/test_plugin_site_scope.py`.

**Interfaces:**
- **Consumes:** Task 4's `FillFlow` and `restore_site_resolution`, and Task 3's `SiteEngine.stretch_job`.
- **Produces, on `SiteEngine`:**
  - `fills_missing(top_ns: float, thickness_ns: float, finish: SliceFinish) -> list[str]`: the ready grids, in `ready_grids` order, whose fill for this window's coverage is not held. It slices through `_sliced`, which a draw does anyway.
  - `fill_jobs(top_ns, thickness_ns, finish) -> list[FillJob]`: one per missing grid, in the same order.
- **The site's draw:**
  - In `refresh_slice`, before `engine.slice_at`: if `fills_missing` is non-empty, it calls `refine.before_draw(rebuilds=True)` and then `flow.request(key, [*fill_jobs, engine.stretch_job(..., fills={job.grid_id: job for job in fill_jobs})], stretch_key=stretch_key(z))`.
    - `key` is `(lattice, tuple(missing), engine fill keys)`.
    - A False skips the draw: `SiteScope.slice` is kept, nothing is emitted and `show_refine()` runs.
  - The line reads `grid {n} of {total}`.
  - `display_limit` follows Task 4's non-blocking rule, with `refine.held_stretch` and a lone `StretchJob`.
- **Mid-fill changes:**
  - A change to `ready_grids` restarts the work, because the key moves: `_run_tick` already cancels the stretch there.
  - A grid removed, unticked or moved mid-fill gets its engine retired or cleared, so its job's `land()` is False (Task 2's epoch). The rest of the site still lands and draws.
- **Cancel:** as in Task 4, against `site_resolution()` and `restore_site_resolution`, the shared cell spin and `site_finish`.
- **Leaving:** leaving Whole site and closing the survey call `flow.stop()`.

- [ ] **Step 1: Write the failing tests** in `test_plugin_fill_flow.py`, on a three-grid site (`site3`) at a cell where the fills together take at least 2 s on CI (calibrated as in Task 4).
  - `test_whole_site_never_blocks_the_gui_during_a_slow_fill`: the largest gap is under 250 ms, the line read `grid 1 of 3` and later `grid 3 of 3`, and the layer changed only after landing.
  - `test_a_grid_unticked_mid_fill_never_lands_and_the_rest_draws`: untick B while A's job runs. B's job lands False or never runs, and the picture holds A and C.
  - `test_a_grid_removed_mid_fill_never_lands`: the same with `remove_grid("B")`.
  - `test_cancel_with_a_picture_puts_the_site_back`: the site record and the shared spins are restored exactly.
  - `test_a_quick_site_fill_draws_in_the_same_tick`.
  - `test_the_site_stretch_lands_after_the_picture_and_redraws`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `test_plugin_fill_flow.py`, `test_plugin_site_scope.py`, `test_plugin_site_engine.py`, `test_plugin_slices_dock.py`, pure, `-m real_data` and ruff. Expected: all pass. As in Task 4, list every existing test that now waits for the flow.
- [ ] **Step 5: Commit:** `feat(site): Whole site works out its fills and stretch in the background, with Cancel (#193)`.

---

## Controller, after Task 5

**Real data (spec, "Measure #193 before and after"):** on `~/nsgeo-site-walk/Sunnyside`, at 0.02 m, in both scopes:
- the largest GUI gap during the fill, using a 10 ms timer;
- the time from the edit to the picture;
- the time to the stretch.

The "before" numbers are in the ledger: 197 s blocked for Whole site and 13–45 s for This grid. Try 0.01 m too if the machine is quiet. Record everything in the decision record.

**Then:**
- the final whole-branch review;
- the deploy to `ns_geo_site_stuck`;
- the walkthrough artifact.

**File the follow-up issue:**
- cuts and ParaView fills still inline;
- the ~1 s Whole site slider tick at 0.02 m, re-measured quiet;
- This grid's status line lagging one draw;
- `site_scope.py` not on CI's mypy list;
- `SiteEngine.dispose`'s one bounded wait per retiring engine, kept on purpose.
