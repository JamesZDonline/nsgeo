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

