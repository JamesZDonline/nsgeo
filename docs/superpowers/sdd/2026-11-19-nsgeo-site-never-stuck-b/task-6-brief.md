### Task 6: The first draw's one-off work in the background too (added 2026-11-20)

**Why.** The author decided this after the "after" measurement on the Sunnyside copy at 0.02 m. The fill and the stretch were off the GUI thread, but the picture's landing still blocked:
- **Whole site:** 2.56 s, of which 1.85 s was `SiteEngine._gather` building every grid's footprint on the new lattice (first draw only), and about 0.65 s was the per-tick draw.
- **This grid (Grid1):** 0.92 s, of which 0.53 s was the first `to_north_up` plan for the new frame, and about 0.3 s was the per-tick draw.

The author chose to move the one-off parts into the background job. The per-tick draw stays in the follow-up issue.

**Files:**
- Modify:
  - `P/site_engine.py`: a footprint job per grid, and its landing.
  - `P/fill_jobs.py` or a new small module: the footprint job.
  - `P/ui/site_scope.py`: request the footprints with the fills.
  - `P/fill_jobs.py`: This grid's `FillJob` also warms the north-up plan.
- Test: `T/qgis/test_plugin_fill_flow.py`, `T/qgis/test_plugin_site_engine.py`.

**Interfaces:**
- **Produces, on `SiteEngine`:**
  - `footprints_missing(lattice) -> list[str]`: the ready grids with a frame and no cached gather on the current lattice, in `ready_grids` order.
  - `footprint_jobs() -> list[FootprintJob]`: one per missing grid. Each job captures on the GUI thread:
    - the grid id;
    - the engine's frame;
    - the current lattice;
    - a copy of `QgsProject.instance().transformContext()`.

    Its `run(should_stop)` calls `site_geometry.gather_footprint(frame, lattice, context)`. That function is documented safe off the GUI thread when given a context copy, as `world_to_frame` already relies on in the export worker.
  - `_land_footprint(job) -> bool`: installs into `_gathers` only if the engine is not disposed, the grid is still ready, its engine's frame equals `job.frame`, and `self.lattice` equals `job.lattice`.
- **The site's request** (`SiteScope._fill_jobs` / `_request_fills`):
  - The `FootprintJob`s join the fill list, after the `FillJob`s and before `on_done`, so the landing draw finds every gather cached.
  - A draw whose fills are all held but whose footprints are missing also goes through the flow, so no first draw builds gathers inline.
  - The progress line keeps its wording. The footprint jobs may count within "grid n of total" or run silently after the last fill; say which.
- **This grid:** `FillJob.run`, after building the fill, warms the north-up plan for its frame with `nsgeo.slices.display._north_up_plan(frame)` (or a small public `warm_north_up_plan(frame)` in core `display.py`). The cache's lock makes the insert from the worker safe (Plan A Task 2). Its progress share is the builder's.

**Steps (TDD):**
- [ ] **Step 1: Write the failing tests.**
  - `test_a_site_landing_builds_no_footprint_on_the_gui_thread`: record `threading.current_thread()` in `site_geometry.gather_footprint`. After a cell edit's fills land and the picture draws, none ran on the main thread and every ready grid's gather is cached.
  - `test_a_footprint_for_a_stale_lattice_never_lands`: change the cell again while the footprints run. The first lattice's jobs land False and the picture is the second cell's.
  - `test_this_grids_first_north_up_plan_is_built_on_the_worker`: record the thread in `_build_north_up_plan`. After a This-grid cell edit lands and draws, the plan for the new frame was built on `nsgeo-fill`, and the landing draw built none.
  - The existing GUI-gap tests stay green.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** test_plugin_fill_flow.py, test_plugin_site_scope.py, test_plugin_site_engine.py, test_plugin_slices_dock.py, pure, `-m real_data`, ruff and CI's mypy command.
- [ ] **Step 5: Commit:** `feat(slices): the first draw's footprints and north-up plan are built in the background too (#193)`.
