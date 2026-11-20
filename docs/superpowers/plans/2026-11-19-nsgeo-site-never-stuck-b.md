# Session H Plan B: the fill and the stretch worked out in the background (#193)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fine cell never freezes QGIS. In Whole site and in This grid, the interpolation fill and then the shared colour stretch are worked out on a worker thread. The map keeps its last picture and its stretch until they land. There is progress and a Cancel.

**Architecture:**
- **Core:** the fill planners learn to stop and to report progress.
- **Engines:** they hand out jobs.
  - A `FillJob` builds one grid's fill from a mask taken on the GUI thread.
  - A `StretchJob` measures the shared stretch from slices, fills and solves captured on the GUI thread.
  - Each job lands only if the engine still wants what it built.
- **Scopes:** a `FillFlow`, shared by both scopes, runs the jobs on a new `nsgeo-fill` worker. It waits up to 0.2 s, so quick work draws in the same tick, and otherwise shows a working line with Cancel. It reverts or latches when cancelled.
- **One worker, not two.** The spec says each scope gets a fill worker. One dock-owned worker serves both, because the scopes never draw at once and a scope switch stops the work. It is separate from the refine worker, so fills and minimum-curvature solves never wait on each other.

**Tech Stack:** Python 3.12 plugin on QGIS 3.44 / 4.2 (PyQt5 / PyQt6), numpy-only core on Python 3.9+, pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-nsgeo-site-never-stuck-design.md` (Part 5).

**The author's decision on the measurements (2026-11-19, overrides Part 5 where they differ):**
- **The measurements:** on the Sunnyside copy at 0.02 m, Whole site's shared stretch took 7.4–8.2 s after the fill landed. One draw took 1.1–1.3 s. Both were measured under load.
- **The decision:** the shared stretch is worked out in the same background job, right after the fill. The map keeps its current stretch until the new one lands.
- **Out of scope:** the ~1 s slider tick goes into the follow-up issue, with cuts and the ParaView export.

**Plan A is built (78c9dbe…b21ea1e).** This plan starts from the branch head, in the same worktree and ledger folder (`.superpowers/sdd/2026-11-19-nsgeo-site-never-stuck-b/`).

## Global Constraints

**Paths:**
- `P` = `packages/nsgeo-qgis/nsgeo_qgis`, `T` = `packages/nsgeo-qgis/tests`,
  `C` = `packages/nsgeo-core/src/nsgeo`, `CT` = `packages/nsgeo-core/tests`.

**Tests:** run them as Plan A did.
- **Core and pure:** `./.venv/bin/python -m pytest packages/nsgeo-core/tests -q -p no:xonsh` (and `…/nsgeo-qgis/tests/pure`).
- **QGIS:** `packages/nsgeo-qgis/scripts/qgis_tests.sh <file>`.
  - Never run the whole QGIS tier locally.
  - Before committing, also run `-m real_data`.

**Fail first:** every new test must fail before its fix, for the stated reason. A test that avoids the input that breaks the code is a bug report.

**Code rules:**
- Every Qt slot and timer callback guards its whole body and never raises.
- No Qt, no session and no QGIS object is touched off the GUI thread. A job's `run` uses only numpy and the immutable objects captured when it was made.
- Core stays numpy-only and on Python 3.9.
- Run ruff check and format, and CI's mypy command from `.github/workflows/ci.yml`.

**Copy** (the builder may tighten the wording, in this register):
- Working, This grid: `Working out the fill at {cell} m: {percent}%`.
- Working, Whole site: `Working out the fill at {cell} m: grid {n} of {total}`.
- Working, stretch: `Working out the colour stretch…`.
- The Cancel link: `Cancel`.
- Warnings note when there is no picture: `The picture was not drawn: its fill was cancelled. Change the cell or the interpolation to draw it.`

**Values:**
- `FILL_BUDGET_S = 0.2`, the no-flicker wait.
- `FILL_POLL_MS = 100`, for refreshing the progress line.
- `FILL_THREAD_NAME_PREFIX = "nsgeo-fill"`.
- All three go in `P/slices_plan.py`.

**Process:**
- Implementers commit locally. The controller pushes after review.
- **#196 is not yours:** `test_a_site_refine_for_a_window_left_behind_never_draws` and its This grid twin fail under load at `assert finished_late.is_set()`.
- The two narrow-window site-scope timing tests are not yours either: `…never_overlaps_preparations` and `…waits_out_a_task_that_outlived_its_cancel`.

**Out of scope:**
- **Inline builds:** cuts (`section_fills`), the ParaView export and the GeoTIFF exports keep building inline. The exports already build on their task's thread.
- **The per-tick draw cost.**
- **The fill key has no search radius setting.** It is derived from the max distance (`SliceFinish.in_metres`), so "a fill setting" means cell, method and max distance.

## Review Focus

1. **A fill landing after its engine moved on:** a cell edit, a new source, a removed grid or `clear()`. It must never install. Pinned in Task 2, and by "a stale fill never lands" in Tasks 4 and 5.
2. **The background stretch must equal today's synchronous one exactly.** This covers both scopes, IDW and kriging, minimum curvature both unsolved (provisional) and fully solved (final), normalisation and manual gains, and resident and streaming sources. Pinned in Task 3.
3. **A streaming window whose covered cells differ from the held fill's.** For example an edge window where a short line ends. The stretch job builds its own fill for that window and leaves the held one alone. Pinned in Task 3.
4. **Closing the survey or unloading the plugin while a fill runs.** The worker is shut down, nothing lands on a disposed engine, and nothing raises. Pinned in Task 4.
5. **Cancel when the picture's own cell was slow.** Going back rebuilds it, so the working line shows again over the unchanged map. That second Cancel has nothing to go back to, so it latches. Pinned in Task 4.

---

### Task 1: Core, plans that can stop and say how far they are

**Files:**
- Create: `C/slices/stopping.py`. `SolveStopped` moves here; `curvature.py` and `nsgeo.slices` re-export it unchanged.
- Modify: `C/slices/interpolate.py`: `plan_fill`, `reach_mask`, `_reach`, `_neighbourhoods`, `_kriging_weights` and the plan-chunk loop.
- Modify: `C/slices/curvature.py`: `plan_curvature`, `_grow`, `_stencil`.
- Modify: `C/slices/multigrid.py`: `build_hierarchy`, checked once per level.
- Test: `CT/test_slices_interpolate.py`, `CT/test_slices_curvature.py`.

**Interfaces:**
- **Produces:**
  - `plan_fill(populated, cell, method, max_distance_m, search_radius_m, *, should_stop: Callable[[], bool] | None = None, progress: Callable[[float], None] | None = None) -> SliceFill`
  - `plan_curvature(populated, cell, max_distance_m, *, should_stop=None, progress=None) -> CurvaturePlan`
  - `reach_mask(populated, cell, max_distance_m, *, should_stop=None) -> ndarray`
- **When `should_stop()` returns True,** they raise `SolveStopped`. The checks sit:
  - between neighbour offsets in `_reach` and `_neighbourhoods`, at least every 32 offsets;
  - between plan chunks;
  - between kriging solve chunks;
  - between `plan_curvature`'s stages;
  - once per hierarchy level.

  `eigh` cannot be stopped and is left alone.
- **`progress`** receives non-decreasing fractions in [0, 1], ending with exactly `1.0` on success. The split between stages is the builder's.

- [ ] **Step 1: Write the failing tests**
  - `test_a_plan_with_stop_and_progress_is_bit_identical`: IDW, kriging and `min_curvature`, on the fixture of the existing `test_the_plan_does_not_depend_on_the_chunk_size`. With `should_stop=lambda: False` and a progress list, every array equals the plain call's (`np.array_equal`, including `CurvaturePlan.coefficients` and each hierarchy level). The progress list is non-decreasing, inside [0, 1], and ends at 1.0.
  - `test_a_plan_stops_when_asked`: for each method, `should_stop` returns True from its third call onward, and `pytest.raises(SolveStopped)`.
  - `test_a_plan_stops_inside_the_neighbour_search`: a fixture large enough that `_neighbourhoods` runs more than 64 offsets. `should_stop` flips once `progress` has reported any fraction above 0. Raises within the search, which the progress value at the raise shows below the weight stage's start.
  - `test_solve_stopped_is_one_class_everywhere`: `nsgeo.slices.SolveStopped is nsgeo.slices.curvature.SolveStopped is nsgeo.slices.stopping.SolveStopped`.
- [ ] **Step 2: Run them and see them fail.** Expected: a TypeError on the unknown keyword arguments, and an ImportError for `stopping`.
- [ ] **Step 3: Implement.** Thread `should_stop` and `progress` through without changing any arithmetic. Python 3.9 only: no `zip(strict=)` and no `match`.
- [ ] **Step 4: Run** the core suite and `ruff`. Expected: all pass.
- [ ] **Step 5: Commit:** `feat(slices): fill and curvature plans can stop and report progress (#193)`.

---

### Task 2: Fill jobs, landed only where still wanted, on their own worker

**Files:**
- Create: `P/fill_jobs.py` (`FillJob`).
- Modify:
  - `P/slices_engine.py`: `fill_held`, `fill_job`, `fill_key`, `_land_fill`, `_fill_epoch`.
  - `P/refine.py`: `Refiner.settle`.
  - `P/slices_plan.py`: the three constants.
  - `P/ui/slices_dock.py`: `self.fill_worker`.
  - `P/plugin.py`: `unload` shuts the fill worker down beside `refiner`.
- Test: `T/qgis/test_plugin_fill_jobs.py` (new), `T/qgis/test_plugin_refine.py`.

**Interfaces:**
- **Consumes:** Task 1's `plan_fill(..., should_stop=, progress=)` and `SolveStopped`.
- **Produces, on `SliceEngine`:**
  - `fill_key(finish: SliceFinish) -> tuple`: `_weights_key(frame, finish_settings(finish))`. Raises RuntimeError when there is no frame.
  - `fill_held(coverage: np.ndarray, finish: SliceFinish) -> bool`: `_held_fill(coverage > 0, …) is not None`. False when there is no frame or choice.
  - `fill_job(coverage: np.ndarray, finish: SliceFinish) -> FillJob`. It calls `_drop_fill()` first, as `_fill_for` does, so memory peaks are unchanged. It then captures a copy of `coverage > 0`, the frame, the `FinishSettings`, `choice.grid_id` and `_fill_epoch`.
  - `_fill_epoch: int`, incremented by every `_drop_fill()`.
  - `_land_fill(job) -> bool`: installs `(job.key, job.fill, job.preview)` only if the engine is not disposed, `job.epoch == _fill_epoch`, `job.frame == _frame` and `job.fill is not None`. Returns whether it did.
- **Produces `FillJob`:**
  - Attributes: `grid_id: str | None`, `key: tuple`, `frame`, `epoch`, `fill: SliceFill | None`, `preview: FillWeights | None`, `fraction: float`. The worker writes `fraction` and the GUI thread reads it.
  - `run(should_stop) -> None` builds `fill`. For `min_curvature` it also builds the kriging `preview`, at `PREVIEW_METHOD` with the same max distance and search radius, as `_fill_for` does. Progress is scaled over both.
  - `land() -> bool` calls `engine._land_fill(self)`.
- **Produces `Refiner.settle(timeout_s: float) -> bool`.** It blocks the calling GUI thread up to `timeout_s` for the running list to finish. If it has finished, it drains the queue now (`_drain()`), so `on_landed` and `on_error` run before it returns, and returns True. It returns False while the list still runs. With no list ever started, it returns True.
- **Produces `SlicesDock.fill_worker`:** `Refiner(self, thread_name_prefix=FILL_THREAD_NAME_PREFIX)`.

- [ ] **Step 1: Write the failing tests** in `test_plugin_fill_jobs.py`, on the `sourced` engine fixture of `test_plugin_slices_engine.py`, moved to conftest if it isn't shared already.
  - `test_a_fill_job_builds_what_fill_for_builds`: for IDW, kriging and `min_curvature`, a job run with `should_stop=lambda: False` and landed gives `engine.fill_held(cov, finish)`. `engine.finish(values, cov, finish)` then equals the result before the job (`np.array_equal`), and no build happens: wrap `plan_fill` to count calls after landing.
  - `test_a_fill_job_lands_nowhere_after_its_engine_moved_on`, parametrised over:
    - the frame changes (a cell `set_resolution`);
    - `set_source` to another choice;
    - `clear()`;
    - `dispose()`;
    - another `fill_job` made after it.

    Each time, `job.land()` is False and `fill_held` is False.
  - `test_a_stopped_fill_job_raises_and_holds_nothing`: `run(lambda: True)` raises `SolveStopped`, `job.fill is None`, and `land()` is False.
  - `test_the_fill_worker_names_its_threads`: a job run on `dock.fill_worker` records `threading.current_thread().name.startswith("nsgeo-fill")`.
- [ ] **Step 2: In `test_plugin_refine.py`, write**
  - `test_settle_drains_a_list_that_ends_in_time`;
  - `test_settle_returns_false_while_the_list_runs`: a gated job; `settle(0.05)` returns False, and `on_landed` has not run;
  - `test_settle_with_nothing_started_is_true`.
- [ ] **Step 3: Run them and see them fail.** Expected: AttributeError (`fill_job`, `settle`, `fill_worker`).
- [ ] **Step 4: Implement** the Interfaces block, and shut the worker down in `plugin.unload`.
- [ ] **Step 5: Run** both files, `test_plugin_slices_engine.py`, pure, `-m real_data` and ruff. Expected: all pass.
- [ ] **Step 6: Commit:** `feat(slices): fill jobs that land only where still wanted, on an nsgeo-fill worker (#193)`.

---

### Task 3: The shared stretch as a job, equal to today's

**Files:**
- Create: `P/stretch_jobs.py` (`StretchJob`, `WindowSource`).
- Modify:
  - `P/slices_engine.py`: `window_source`, `stretch_job`.
  - `P/site_engine.py`: `stretch_job`.
  - `P/ui/refine_flow.py`: `held_stretch`, `land_stretch`.
- Test: `T/qgis/test_plugin_stretch_jobs.py` (new), `T/qgis/test_plugin_refine_flow.py`.

**Interfaces:**
- **Consumes:** Task 2's `FillJob` (its `fill` and `preview`, read in `run`, after the fill jobs ahead of it on the same worker have run).
- **Produces `SliceEngine.window_source() -> WindowSource`.** It is a frozen snapshot taken on the GUI thread, after `_ensure_plans()` (and `cube()` in resident mode). It holds the frame, the z axis, and either the cube or the `(lines, plans)` lists.
  - `WindowSource.slice(window) -> (values, coverage)` is pure numpy, as `SliceEngine._slice`.
  - Read `binning.stream_slice` and `SliceCube.slice_levels`, and confirm neither writes its inputs. If one does, the snapshot copies what it writes. Say which in the report.
- **Produces `SliceEngine.stretch_job(thickness_levels: int, clip, finish: SliceFinish, *, fill: FillJob | None = None) -> StretchJob`.**
- **Produces `SiteEngine.stretch_job(thickness_ns: float, clip, *, finish, method, manual, fills: Mapping[str, FillJob] | None = None) -> StretchJob`.** It captures, on the GUI thread:
  - each ready grid's `WindowSource`;
  - its grid windows at `_limit_windows_ns`;
  - its `FinishSettings`;
  - its held fill and preview, or the grid's `FillJob` when one is given;
  - a copy of its solved cache;
  - the seams for `method == "edge"`, and the method, the manual gains and the clip.
- **Produces `StretchJob`:**
  - Attributes: `limit: float | None`, `final: bool`, `fraction: float`.
  - `run(should_stop)` measures exactly what `stretch_limit` measures today:
    - the same windows;
    - `normalise` on the binned values;
    - `a * draw + b`;
    - `limit_over_slices`.

    The draw is decided by method:
    - **Not minimum curvature:** `finish_slice` with the grid's fill. Final.
    - **Minimum curvature:** if every window's `solve_key` is in the captured solves, they are smoothed. Final.
    - **Minimum curvature, any window unsolved:** the kriging preview is used. Provisional, `final = False`.

    A window whose `coverage > 0` differs from the fill's `populated` gets a fill built inside the job, with `should_stop`, and never installed.
  - `land() -> bool` returns True. The scope stores the result.
- **Produces, on `RefineFlow`:**
  - `held_stretch(key) -> float | None`: the held limit for `key`. It arms the rest for a provisional stretch exactly as `stretch_limit` does today.
  - `land_stretch(key, limit, final) -> None`.

  `stretch_limit(key, measure)` stays for the callers out of scope.

- [ ] **Step 1: Write the failing tests.** In `test_plugin_stretch_jobs.py`, each compares `job.limit` and `job.final` with today's synchronous `stretch_limit`. `limit` is compared with `==` and must be bit-equal.
  - `test_this_grids_stretch_job_equals_stretch_limit`, parametrised over:
    - IDW resident;
    - kriging streaming;
    - `min_curvature` with nothing solved, which gives `final is False` and equals `shared_limit(..., preview=True)`;
    - `min_curvature` with every window solved through `stretch_solves`, which gives `final is True`.
  - `test_the_sites_stretch_job_equals_stretch_limit`, parametrised over normalisation `none` / `background` / `edge`, with manual gains `{"B": 2.5}`, and over IDW and `min_curvature` unsolved.
  - `test_a_window_with_other_covered_cells_gets_its_own_fill`: a streaming fixture where one line ends early, so the last window's coverage differs. Equal to `stretch_limit`, and afterwards the engine still holds the same fill object as before (`engine._weights[1] is held`).
  - `test_a_stretch_job_reads_its_fill_jobs_results`: a site with B's fill dropped. Run `[fill_job_B, stretch_job(fills={"B": fill_job_B})]` in order and get the same limit as the synchronous measure after B's fill is held.
  - `test_a_stopped_stretch_job_raises`.
- [ ] **Step 2: In `test_plugin_refine_flow.py`, write** `test_a_landed_stretch_is_held_for_its_key_only` and `test_a_provisional_landed_stretch_arms_the_rest`.
- [ ] **Step 3: Run them and see them fail.** Expected: AttributeError.
- [ ] **Step 4: Implement.** Factor the per-window measurement so today's `_measure` and `shared_limit` and the job share one pure function. A second copy would drift. Today's synchronous paths keep their results.
- [ ] **Step 5: Run** the two files, `test_plugin_site_engine.py`, `test_plugin_slices_engine.py`, `-m real_data` and ruff. Expected: all pass.
- [ ] **Step 6: Commit:** `feat(slices): the shared stretch measured by a job, equal to today's (#193)`.

---

### Task 4: FillFlow, and This grid never freezes

**Files:**
- Create: `P/ui/fill_flow.py` (`FillFlow`).
- Modify:
  - `P/ui/slices_dock.py`: `_finished` and `refresh_slice`, `display_limit`, `show_refine`, the Cancel link on `readout_row`, the cancel handling, and the latch.
  - `P/session.py`: `restore_slice_resolution`, `restore_site_resolution`.
  - `P/ui/site_scope.py`: only the Protocol gains what Task 5 will read.
- Test: `T/qgis/test_plugin_fill_flow.py` (new), `T/qgis/test_plugin_slices_dock.py`.

**Interfaces:**
- **Consumes:** Tasks 2 and 3 (`fill_held`, `fill_job`, `fill_key`, `stretch_job`, `held_stretch`, `land_stretch`, `settle`, `fill_worker`).
- **Produces `FillFlow(parent: QObject, worker: Refiner, *, on_done: Callable[[], None], on_stretch: Callable[[Hashable, float, bool], None], on_cancelled: Callable[[], None])`**:
  - **`request(key: Hashable, jobs: Sequence[Any], *, stretch_key: Hashable) -> bool`.** It answers whether to draw now. `jobs` is the `FillJob`s followed by one `StretchJob`.
    - **Same `key` as the fill work running:** the jobs are dropped, the flow keeps going and draws once on landing; returns False.
    - **Another key:** it cancels the running work, starts `jobs`, then calls `worker.settle(FILL_BUDGET_S)`. If every `FillJob` landed it returns True and shows no working state; otherwise it returns False and is `working`.
    - **Empty `jobs`:** returns True.
    - **Landing:**
      - Each `FillJob` landing calls `job.land()`.
      - When the last `FillJob` has landed, `working` goes False and `on_done()` runs: the scope draws at whatever the panel says then, with the stretch it holds.
      - The flow is then `stretching` until the `StretchJob` lands. That landing calls `on_stretch(stretch_key, job.limit, job.final)`, which the scope stores with `refine.land_stretch`. The scope then re-renders if that key is still current.
  - **`request_stretch(stretch_key: Hashable, job: StretchJob) -> None`.** It does nothing while fill work runs, or while a stretch for the same key is already running. Otherwise it starts `[job]`, and the landing goes to `on_stretch` as above. A different key cancels the stretch that is running.
  - **`working: bool`** (fills pending), **`stretching: bool`**, plus **`progress_text(cell_m: float, *, grids: bool) -> str`**, built from the copy in Global Constraints:
    - the running `FillJob`'s `fraction` (This grid);
    - landed and total `FillJob`s (site);
    - the stretch wording while `stretching`.

    A `QTimer` at `FILL_POLL_MS` calls the scope's `show_refine` while either is True.
  - **`cancel()`**, from the link or a scope switch. It cancels the worker and clears both states. For the link only, it calls `on_cancelled()`.
  - **`latched: bool`**, plus **`latch()`** and **`unlatch()`**.
  - **`stop()`**, for scope switches and survey close. It cancels without the callback and unlatches.
- **Produces, on `SiteSession`:**
  - `restore_slice_resolution(grid_id: str, record: dict | None) -> None`;
  - `restore_site_resolution(record: dict | None) -> None`.

  Each replaces the stored record exactly; `None` removes it, so "chosen or seeded" returns too. They mark the survey dirty and emit what `remember_*` emits.
- **The dock's draw (This grid):**
  - In `_finished`: if not `engine.fill_held(coverage, finish)`, it first calls `_grid_refine.before_draw(rebuilds=True)`, so a running refine list stops (spec: "still cancelled before a rebuild"). It then calls `flow.request(engine.fill_key(finish), [fill_job, stretch_job(fill=fill_job)], stretch_key=_stretch_key(...))`.
  - A False from `request` skips the draw: `_values` is not replaced, `slice_changed` is not emitted, and `show_refine()` runs.
  - `display_limit` uses `held_stretch(key)`. When nothing is held for the key, it calls `flow.request_stretch(key, engine.stretch_job(...))`. It returns the limit on the layer now, or the shown slice's own `limit_over_slices` when nothing has been drawn yet. When the stretch lands, the dock re-emits `slice_changed`, so the layer re-renders with the new limit.
- **The picture's settings:** at each completed draw the dock stores `(cell, SliceFinish, slice_resolution(grid_id) copy)`.
  - **Cancel with a picture:** puts the record back with `restore_slice_resolution`, and sets the cell spin and the `FinishPanel` back without remembering them (blocked signals / `set_value`). It applies the resolution, which can show the working line again.
  - **Cancel with no picture:** settings and the record stay. The Warnings NOTE from Global Constraints is added and `latch()` is called. While latched, `_finished` starts no job and draws nothing. A cell, method or max distance edit, a scope switch or a survey reopen calls `unlatch()`.
  - **A fill-setting edit while working** goes through `request` with the new key, which restarts. Any other edit only updates what the landing will draw.
- **The Cancel link:** a `QLabel` with `<a href="cancel">Cancel</a>` and `linkActivated` → `flow.cancel()`, beside `refine_label` on `readout_row`. It is visible only while `working`, the fill phase, and not while `stretching`: a stretch is not a setting to take back. The row keeps its one-line fixed height (W1).

- [ ] **Step 1: Write the failing tests** in `test_plugin_fill_flow.py`, on the This grid dock. Use a synthetic grid at a cell fine enough that kriging's `plan_fill` takes at least 2 s on CI. Calibrate the fixture size once, and assert the duration in the fixture, so the hazard can't silently shrink.
  - `test_this_grid_never_blocks_the_gui_during_a_slow_fill`: a 10 ms `QTimer` records gaps from the cell edit until the fill has landed (`spin_until(lambda: not flow.working)`). The largest gap is under 250 ms, the working line was shown with `%`, and the map layer changed only after landing.
  - `test_a_quick_fill_draws_in_the_same_tick`: a coarse cell edit. `flow.working` is never True (spy on it), and `slice_changed` is emitted within the same `refresh_slice` call.
  - `test_cancel_with_a_picture_puts_everything_back`. Edit the cell from 0.1 to the slow cell, then cancel. The cell spin reads 0.1, `slice_resolution("A") == ` the record before the edit (key presence included), the engine frame's cell is 0.1, and no new picture was drawn for the slow cell.
  - `test_cancel_with_no_picture_latches_until_a_fill_setting_changes`:
    1. Open with the slow cell saved, and cancel.
    2. The NOTE is in Warnings, and a slider move or a preparation landing starts no job (count `fill_job` calls).
    3. A method edit starts one.
  - `test_cancel_again_after_going_back_to_a_slow_picture_latches` (Review Focus 5).
  - `test_a_stale_fill_never_lands`: change the cell again mid-fill. The first job's `land` is never called with its key current, and the picture drawn is the second cell's.
  - `test_the_stretch_lands_after_the_picture_and_redraws`: the first draw at a new cell uses the previous limit. After the stretch lands, the layer's limit equals the synchronous `stretch_limit`.
  - `test_a_stretch_request_never_cancels_the_fill_work`: while a fill runs, `display_limit` and a thickness edit call `request_stretch`. The fill still lands, and the stretch for the current key lands after it.
  - `test_unloading_while_a_fill_runs_lands_nothing` (Review Focus 4): `plugin.unload()` mid-fill. Nothing raises, the worker's thread ends, and no `_land_fill` runs on a disposed engine.
- [ ] **Step 2: Run them and see them fail.** Expected: AttributeError or a large gap, because today the fill blocks.
- [ ] **Step 3: Implement** the Interfaces block.
- [ ] **Step 4: Run** `test_plugin_fill_flow.py`, `test_plugin_slices_dock.py`, `test_plugin_refine_flow.py`, pure, `-m real_data` and ruff. Expected: all pass. Some existing dock tests drew a slow fill synchronously and now see a working state; they wait with `spin_until(lambda: not dock.fill_flow.working)`. List each one changed in the report.
- [ ] **Step 5: Commit:** `feat(slices): This grid works out its fill and stretch in the background, with Cancel (#193)`.

---

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
