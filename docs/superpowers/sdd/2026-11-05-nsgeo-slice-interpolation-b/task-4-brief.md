### Task 4: Whole site with minimum curvature

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`:
  - `SiteSlice.provisional: bool = False`, as the last field;
  - `slice_at(..., preview: bool = False)`;
  - `pending_solves`;
  - `stretch_solves`;
  - `shared_limit(..., preview: bool = False)`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`: the same preview, rest and refine flow as Task 3's dock, using `dock.refiner`.
- Test: `tests/qgis/test_plugin_site_engine.py`, `tests/qgis/test_plugin_site_scope.py`.

**Interfaces:**
- Consumes: Task 3's `SliceEngine.finish_is_slow`, `preview`, `pending_solve`, `stretch_solves`, `shared_limit(..., preview=)` and `PendingSolve`; Task 2's `Refiner` through `dock.refiner`.
- Produces, on `SiteEngine`:
  ```python
  def slice_at(self, top_ns, thickness_ns, *, finish, method, manual, coverage=False,
               preview: bool = False) -> SiteSlice: ...
      # preview=True: each grid whose finish_is_slow shows engine.preview(...); provisional = any grid did
  def pending_solves(self, top_ns: float, thickness_ns: float, finish: SliceFinish) -> list[PendingSolve]: ...
      # every ready grid's uncached slice at this window, in ready_grids order
  def stretch_solves(self, thickness_ns: float, finish: SliceFinish) -> list[PendingSolve]: ...
      # every ready grid's uncached limit_windows
  def shared_limit(self, thickness_ns, clip, *, finish, method, manual, preview: bool = False) -> float: ...
  ```
  `SiteScope` gains `provisional: bool`.

- [ ] **Step 1: Write the failing tests.** `_wait_for_refine` is as in Task 3, copied into this file.
  - **`test_site_gains_commute_with_every_method`** gains `"min_curvature"`. For it, compare with `rtol=1e-4, atol=1e-4 * np.nanmax(np.abs(after))`.
  - **`test_a_slow_site_tick_previews_then_refines`**
    - With `min_curvature` and every grid engine's `_last_solve_ms` forced to 500, a slider move gives `scope.slice.provisional is True`.
    - `scope.slice.array` equals `slice_at(..., preview=True)` of that window.
    - After `_wait_for_refine`, `scope.slice.provisional is False` and the array equals a fresh `slice_at(...)`.
  - **`test_a_quick_site_tick_draws_minimum_curvature_at_once`**
    - At 5 ms on every engine, the first tick is final and the refiner never starts.
  - **`test_a_site_refine_for_a_window_left_behind_never_draws`** (Review Focus 2)
    - As Task 3's test, through `site_engine.pending_solves`.
  - **`test_the_site_stretch_with_minimum_curvature_uses_twelve_windows`**
    - `shared_limit` with `min_curvature` calls each engine's `finish` at most `len(limit_windows(...))` times per grid, counted.
    - The scope's limit is provisional, equal to `shared_limit(..., preview=True)`, until `stretch_solves` is empty. After that it equals `shared_limit(...)`.
  - **`test_a_site_with_minimum_curvature_exports_and_reopens`**
    - Export the three-grid fixture with `min_curvature`.
    - The file has `NSGEO_SITE_INTERPOLATION == "min_curvature"` and every band is finite on data cells.

- [ ] **Step 2: Run them and see them fail.** Run `test_plugin_site_engine.py` and `test_plugin_site_scope.py` with the QGIS command. Expected: FAIL. `preview=`, `provisional` and `pending_solves` don't exist.

- [ ] **Step 3: Implement.**
  - **`SiteEngine._shown`** takes `preview`. Per grid it uses `engine.preview(...)` when `preview and engine.finish_is_slow(...)`, and `engine.finish(...)` otherwise. It reports whether any grid previewed.
  - **`SiteScope`'s tick** calls `slice_at(..., preview=True)` when the method is `min_curvature`.
  - **The scope's state machine** is Task 3's, with these substitutions:
    - `pending_solves` for `pending_solve`;
    - the scope's own rest timer;
    - `dock.refiner`;
    - a redraw through `schedule_refresh()`.

    A landed job redraws when its key is among the current tick's job keys. A tick that is not `min_curvature` cancels the refiner and stops the scope's rest timer.
  - **`SiteScope.display_limit`** carries the provisional stretch exactly as the dock's `display_limit` does.

- [ ] **Step 4: Run the tests and see them pass**, then the full QGIS command.

- [ ] **Step 5: Commit and push.**
  ```bash
  git commit -m "feat(site): minimum curvature in Whole site — kriging preview and background refine"
  git push origin nsgeo-slice-interpolation-b
  ```

---

