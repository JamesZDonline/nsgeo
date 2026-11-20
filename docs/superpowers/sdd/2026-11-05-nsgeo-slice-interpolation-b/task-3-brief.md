### Task 3: This grid — the method, the preview, refining, the cache, the stretch

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`:
  - `METHOD_LABELS` gains `"min_curvature": "Minimum curvature"`.
  - Add `LIVE_SOLVE_BUDGET_MS`, `REFINE_REST_MS`, `SOLVED_SLICES_KEPT`, `PREVIEW_METHOD`, `PREVIEW_STATUS` and `REFINING_STATUS`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/finish_panel.py`: `_METHOD_TIP` gains the line *"Minimum curvature: the smoothest surface through the lines. It can overshoot beside a sharp change. It is slower, so at a fine cell you see kriging while the depth moves and minimum curvature once it rests."*
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`:
  - `PendingSolve`;
  - the plan and preview built together;
  - the solved-slice cache;
  - `last_solve_ms`, `finish_is_slow`, `preview`, `pending_solve` and `stretch_solves`;
  - `shared_limit(..., preview=)`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`:
  - `self.refiner = Refiner(self)`, the rest timer, and the provisional state in `refresh_slice`;
  - `_on_rest` and `_on_landed`;
  - the provisional stretch in `display_limit`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: `unload()` calls `self.slices_dock.refiner.shutdown()` before `dispose_site()`.
- Test: `tests/pure/test_pure_slices_plan.py`, `tests/qgis/test_plugin_slices_engine.py`, `tests/qgis/test_plugin_slices_dock.py`, `tests/qgis/test_plugin_slice_export.py`.

**Interfaces:**
- Consumes: Task 1's `plan_fill(..., "min_curvature", ...)` → `CurvaturePlan`, `SolveStopped` and `METHODS`; Task 2's `Refiner`.
- Produces, in `slices_engine.py`:
  ```python
  class PendingSolve:                 # a RefineJob
      key: bytes                      # the solved-slice cache key of its values
      solved: np.ndarray | None       # set by run(): the unsmoothed slice
      ms: float | None                # set by run(): the solve's own time
      def run(self, should_stop: Callable[[], bool]) -> None: ...   # worker thread
      def land(self) -> bool: ...     # GUI thread: into the engine's cache (and last_solve_ms) only if that
                                      # engine still holds the plan this job was made from; whether it did
  ```
- Produces, on `SliceEngine`:
  ```python
  @property
  def last_solve_ms(self) -> float | None: ...   # the last solve that ran on this plan; None after the plan is dropped
  def finish_is_slow(self, values, coverage, finish: SliceFinish) -> bool: ...   # plan call 5's "slow"; False for other methods
  def preview(self, values, coverage, finish: SliceFinish) -> np.ndarray: ...
      # min_curvature: kriging at the same distances and smoothing; any other method: finish(...)
  def pending_solve(self, values, coverage, finish: SliceFinish) -> PendingSolve | None: ...
      # None unless min_curvature and these values are uncached
  def stretch_solves(self, thickness_levels: int, finish: SliceFinish) -> list[PendingSolve]: ...
      # the uncached limit_windows; [] for other methods
  def shared_limit(self, thickness_levels, clip, finish, *, preview: bool = False) -> float: ...
      # min_curvature: over limit_windows, through finish() or, with preview=True, preview()
  ```
  - `finish()` keeps its signature and always returns the full result.
  - For `min_curvature`, `weights_cached(finish)` means the plan and the preview are both built.
  - `weights_nbytes` counts plan + preview + cache (plan call 9).
- Produces, on `SlicesDock`: `refiner: Refiner`, and `provisional: bool` (what is drawn is a preview).

- [ ] **Step 1: Write the failing tests.**
  - **Pure.** In `test_the_default_finish_closes_every_gap_between_binned_lines`, `test_the_default_finish_leaves_a_skipped_line_blank` and `test_the_weights_estimate_covers_building_them`, the parametrisation gains `"min_curvature"`.
    - For the estimate test, measure `plan_fill(...)` plus one `apply` together under `tracemalloc`.
    - The bound stays 1.5 × `WEIGHT_BYTES_PER_CELL`.
  - **Labels.** New pure test `test_method_labels_follow_methods`: `list(METHOD_LABELS) == list(METHODS)` and `METHOD_LABELS["min_curvature"] == "Minimum curvature"`. The panel's existing `test_the_panel_starts_at_the_defaults` then covers the combo.
  - **Engine.** "mc" is `SliceFinish(method="min_curvature")` on the synthetic fixture.
    - `test_minimum_curvature_finishes_through_the_engine`
      - `finish(values, coverage, mc)` equals `plan_curvature(coverage > 0, frame.cell, settings.max_distance_m).apply(values)`, then smoothed with the same settings.
    - `test_the_preview_is_kriging_at_the_same_max_distance`
      - `preview(v, cov, mc)` equals `finish(v, cov, SliceFinish(method="kriging"))` at the same distances and smoothing.
      - Its NaN mask equals that of `finish(v, cov, mc)`.
    - `test_a_repeated_solve_is_served_from_the_cache`
      - The second `finish` of the same values runs no solve: patch `CurvaturePlan.solve` with a counting wrapper, and expect 1 call.
      - A smoothing-only change also runs no solve.
    - `test_the_solved_slice_cache_never_serves_other_values` (Review Focus 4)
      - Two different value arrays at the same window and plan give two different results, each equal to a fresh solve.
    - `test_the_cache_keeps_at_most_sixteen_and_drops_with_the_plan`
      - After 17 distinct solves, `len(engine._solved) == 16`, and the first values solve again.
      - After `set_source(...)` or a cell change, the cache is empty and `last_solve_ms is None`.
    - `test_finish_is_slow_follows_the_last_solve`
      - Setting `engine._last_solve_ms` gives these results for uncached values:

        | `_last_solve_ms` | `finish_is_slow` |
        |---|---|
        | None | True |
        | 10 | False |
        | 80 | True |

      - Cached values give False, and kriging gives False.
    - `test_a_pending_solve_lands_in_the_cache`
      - Run `job = pending_solve(...)`, then `job.run(lambda: False)`; `job.land()` is True.
      - A following `finish` of those values runs no solve, and `last_solve_ms == job.ms`.
      - `pending_solve` of the same values is now None, and it is None for kriging.
    - `test_a_solve_for_a_dropped_plan_does_not_land` (Review Focus 3)
      - Make a job, then call `set_source(...)` or change the cell, then run the job.
      - `job.land()` is False, and the new plan's cache stays empty.
    - `test_the_minimum_curvature_stretch_is_measured_over_twelve_windows_at_most`
      - With `thickness_levels = 1` on an axis of more than 12 levels, `stretch_solves` returns `len(limit_windows(z, 1))` jobs.
      - After running and landing them, `shared_limit` runs no solve and equals `limit_over_slices` over those windows' finished slices.
      - `shared_limit(..., preview=True)` equals `limit_over_slices` over their previews.
    - `test_weights_nbytes_counts_the_plan_the_preview_and_the_cache`
      - After one solve it equals `plan.nbytes + preview.nbytes + solved.nbytes`.
  - **Dock.** Each dock test selects `min_curvature`, forces `engine._last_solve_ms` as named, and sets the stretch combo to `this slice` unless it says otherwise. `_wait_for_refine(dock)` pumps events for `REFINE_REST_MS` plus margin, then until `not dock.refiner.busy`, failing after 30 s.
    - `test_a_slow_slice_shows_the_preview_then_refines`
      - Parametrised over a slider move and `step_slice(1)`, at 500 ms.
      - Right after the move, `current_values()` equals `engine.preview(...)` of the new window, `dock.provisional` is True, and `status_label.text() == PREVIEW_STATUS`.
      - After `_wait_for_refine`, `current_values()` equals `engine.finish(...)` of that window, `dock.provisional` is False, and the status is the normal text.
    - `test_the_refine_waits_for_the_depth_to_rest`
      - At 500 ms, three moves 100 ms apart.
      - After each move, `dock.refiner.busy` is False and the rest timer is active.
      - The refiner starts only after the last move plus `REFINE_REST_MS`.
    - `test_a_quick_solve_draws_minimum_curvature_at_once`
      - At 5 ms, a move draws `engine.finish(...)` at once, the rest timer is not active, and the refiner never starts.
    - `test_kriging_never_previews`
      - Kriging: a move draws `finish`, the rest timer is not active, and the refiner never starts.
    - `test_a_refine_for_a_window_left_behind_never_draws` (Review Focus 2)
      - At 500 ms, rest on window A. Patch `engine.pending_solve` so A's job runs the real solve only after a `threading.Event` the test sets, and ignores `should_stop`, so it lands late on purpose.
      - Move to window B, then set the Event, then `_wait_for_refine`.
      - `dock.current_window() == B`, and `current_values()` equals B's full solve.
      - At no point after the move did `current_values()` equal A's solve. Record every array from `slice_changed` to check this.
    - `test_the_shared_stretch_is_provisional_until_its_windows_are_solved`
      - Stretch combo `shared`, at 500 ms.
      - After a move, `display_limit()` equals `engine.shared_limit(n, clip, mc, preview=True)`.
      - After `_wait_for_refine`, it equals `engine.shared_limit(n, clip, mc)`, `engine.stretch_solves(n, mc) == []`, and the slice was redrawn.
    - `test_a_landed_slice_does_not_cancel_the_stretch_solves`
      - Stretch `shared`. After the current slice lands and redraws, `dock.refiner.busy` is still True until the stretch windows land.
    - `test_unloading_mid_refine_stops_the_worker` (Review Focus 3)
      - Patch `engine.pending_solve` to return a job that loops until `should_stop()`, then rest.
      - `plugin.unload()` returns.
      - Within 2 s no `nsgeo-refine*` thread is alive, and nothing was logged to `sys.excepthook` or `sys.unraisablehook`.
  - **Saved records** (`test_plugin_slice_export.py`): parametrise `test_view_settings_round_trip_the_finish` and `test_a_record_from_this_build_still_loads_in_0_2_0` over every key in `METHODS`.

- [ ] **Step 2: Run them and see them fail.**
  - Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py -q -p no:cacheprovider`
  - Then run the three QGIS files with the QGIS command, naming the files.
  - Expected: FAIL. The label is missing, and `PendingSolve`, `preview`, `finish_is_slow` and `refiner` don't exist.

- [ ] **Step 3: Implement the engine.**
  - **The plan and the preview.** For `min_curvature`, `_weights_for` builds the `CurvaturePlan` and a `PREVIEW_METHOD` `FillWeights` at the same max distance and search radius together, under the one key. Both are dropped wherever `_weights` is dropped today.
  - **The cache.** `_solved` is an `OrderedDict[bytes, np.ndarray]` used least-recently-used first. It and `_last_solve_ms` are emptied wherever the plan is dropped or rebuilt, and kept where it is kept.
  - **The digest.** `hashlib.blake2b(values.tobytes(), digest_size=16)` updated with `str(values.shape)` and `str(values.dtype)`.
  - **The `finish` path for `min_curvature`.** It is `smooth(solved, ...)`, where `solved` is the cached slice or a fresh `plan.solve(values)[0]`. That is equivalent to `finish_slice`, and it lets the cache hold the unsmoothed slice. A fresh solve's own time goes into `_last_solve_ms`.
  - **`PendingSolve`.** It holds:
    - the engine;
    - the plan it was made from (its identity is what `land()` checks);
    - a private `values.copy()`;
    - the key.

    `run` calls `plan.solve(values, should_stop)` and times it. `land` stores into `_solved` and `_last_solve_ms` only when `engine._weights` still holds that same plan object.

- [ ] **Step 4: Implement the dock** (plan calls 5 and 7). These are the parts the tests don't fully determine:

  ```text
  refresh_slice, This grid, a finish draw (not the coverage view):
      method min_curvature and engine.finish_is_slow(values, coverage, finish):
          refiner.cancel(); shown = engine.preview(...); provisional = True    # busy_cursor() if not weights_cached
          remember (values, coverage) and the current job key; status = PREVIEW_STATUS; rest.start()
      otherwise:
          shown = engine.finish(...); provisional = False                     # as today
          any method other than min_curvature: refiner.cancel(); rest.stop()
  _on_rest (guarded QTimer slot):
      jobs = [engine.pending_solve(remembered values, coverage, finish)] if provisional
      jobs += engine.stretch_solves(n_levels, finish) if the stretch combo is "shared"
      drop Nones; if jobs: refiner.start(jobs, _on_landed, report); status = REFINING_STATUS.format(done=0, total=len(jobs))
  _on_landed(job) (guarded):
      landed = job.land(); update REFINING_STATUS's count
      landed and provisional and job.key is the current job key → refresh_slice()   # a cache hit: the full slice
      not refiner.busy → if the stored stretch is provisional, drop it; refresh_slice()
  display_limit, shared branch, min_curvature:
      _shared_limit_cache becomes (key, value, final). A stored entry for the key is returned as today.
      engine.stretch_solves(...) non-empty → value = engine.shared_limit(..., preview=True), final = False,
          and rest.start() if the refiner is idle; otherwise value = engine.shared_limit(...), final = True
  ```

  - The early-return and `except` branches of `refresh_slice` also cancel the refiner and stop the rest timer.
  - An `on_error` from the refiner emits `error` with `minimum curvature failed: {message}`. It restores the normal status and leaves the preview on screen.
  - `plugin.unload()` calls `self.slices_dock.refiner.shutdown()` before `dispose_site()`.

- [ ] **Step 5: Run the tests and see them pass**, then the full core + pure command and the full QGIS command. Expected: all pass, at 1366 + the new QGIS tests.

- [ ] **Step 6: Commit and push.**
  ```bash
  git commit -m "feat(slices): minimum curvature in This grid — kriging preview, background refine, solved-slice cache"
  git push origin nsgeo-slice-interpolation-b
  ```

---

