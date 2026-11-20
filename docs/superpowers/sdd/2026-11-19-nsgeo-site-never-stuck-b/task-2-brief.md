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

