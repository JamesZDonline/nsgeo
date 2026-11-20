### Task 4: This grid draws, exports and remembers through the panel (closes #104)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`:
  - add `finish_settings`, `weights_cached`, `finish` and the weights cache;
  - `shared_limit` takes a `SliceFinish`;
  - drop the cache in `_rebuild_geometry`, `set_source` and `clear`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`:
  - **Remove:** `grid_radius_spin`, `grid_radius_metres`, `grid_radius_row`, `_update_radius_metres`, `radius_cells` and `_filled_radius_cells`.
  - **Add:** `self.grid_finish = FinishPanel(metres_label=True)` directly after `resolution_group` in `outer`.
  - **Add:** `self._finish_debounce`, a single-shot QTimer with the same interval as `_debounce`, whose timeout calls `refresh_slice()`.
  - **Add:** `slice_finish() -> SliceFinish`.
  - **Rewire to the panel:** `refresh_slice`, `rebuild_source`'s stale-redraw check, `display_limit`'s cache key, the seed and restore paths, `_on_resolution_edited`, `view_settings`, `apply_view` and `restore_cube`'s remembered fields. Grep every `grid_radius` and `radius_cells`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`. `show_scope_widgets` toggles `dock.grid_finish`'s visibility in place of `grid_radius_row`. The site's `radius_spacing_spin` stays until Task 5.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`:
  - `ExportPlan.radius_cells` becomes `finish: FinishSettings | None`, resolved to metres;
  - `plan_export(..., finish: FinishSettings | None = None)`;
  - `export_slices(engine, path, thickness_levels, step_levels, velocity, finish: SliceFinish, *, writer=None)` hands `engine.finish_settings(finish)` to `plan_export` and yields `engine.finish(*engine.slice_at(band.window), finish)` per band;
  - the writer's metadata;
  - `write_coverage` passes `finish=None`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`, in `export_geotiff`:
  - pass `dock.slice_finish()`;
  - **delete** the radius-0 warning branch, so the message is always plain;
  - rewrite the Ruling AE docstring bullets near line 911.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`, `test_plugin_slices_dock.py`, `test_plugin_slice_export.py`. Update the existing fill and radius tests in these files to the new API rather than deleting their intent. For example, `test_shared_limit_measures_the_filled_array_actually_displayed` now measures the finished array.

**Interfaces:**
- Consumes:
  - `SliceFinish`, `FinishPanel` and `busy_cursor` (Task 3);
  - `FinishSettings` and `finish_slice` (Task 2);
  - `plan_fill` and `FillWeights` (Task 1).
- Produces, on `SliceEngine`:
  ```python
  def finish_settings(self, finish: SliceFinish) -> FinishSettings: ...
      # finish.in_metres(<chosen grid's default_spacing>); RuntimeError with no source
  def weights_cached(self, finish: SliceFinish) -> bool: ...
  def finish(self, values: np.ndarray, coverage: np.ndarray, finish: SliceFinish) -> np.ndarray: ...
      # finish_slice(values, <cached or new plan_fill(coverage > 0, frame.cell, ...)>, frame.cell, settings)
  def shared_limit(self, thickness_levels: int, clip: Any, finish: SliceFinish) -> float: ...
  ```
- **Cache rule.** The cache holds one `(key, FillWeights)` with `key = (frame, settings)`.
  - **Hit** only when the key matches **and** `np.array_equal(weights.populated, (coverage > 0).ravel())`.
  - `weights_cached` compares the key only, because lines changing goes through `set_source`, which clears the cache.
  - The cell always comes from `self.frame.cell`, never from a widget. That is #104's fix.
- **Metadata keys** on a values GeoTIFF:
  - `NSGEO_INTERPOLATION` (method key);
  - `NSGEO_MAX_DISTANCE_M`, `NSGEO_SMOOTH_X_M`, `NSGEO_SMOOTH_Y_M` (`str(float)`);
  - `NSGEO_FRAME_AZIMUTH_DEG`, as before.
  - The coverage companion carries none of the four. `NSGEO_FILL_RADIUS_CELLS` is gone.
- **Dock behaviour:**
  - **Redraw:** `refresh_slice` wraps `engine.finish(...)` in `busy_cursor()` when `not engine.weights_cached(finish)`. It records `self._drawn_finish = engine.finish_settings(finish)`.
  - **Stale redraw:** `rebuild_source` redraws when `engine.finish_settings(self.grid_finish.value()) != self._drawn_finish`. This happens when a spacing edit moved the metres.
  - **Metres label:** every place that called `_update_radius_metres()` now calls `self.grid_finish.set_spacing(self._grid_spacing())`. Those are the seed, a cube restore and `rebuild_source` on session signals.
  - **Edits:** `grid_finish.edited(field, value)` leads to: remember `{field: value}` for the grid, unless the dock is `_updating` or `_seeding`; refresh the metres label; start `_finish_debounce`.
  - **Seed:** a grid change sets `grid_finish` to `SliceFinish()` quietly, then lays the grid's remembered fields over it with `SliceFinish().updated(remembered)`, then calls `set_spacing(grid spacing)`.
  - **Saving a cube:** `view_settings()` writes the panel's four fields and `radius_m = max_distance_spacings × spacing`.
  - **Restoring a cube:** `apply_view` sets the panel from `view.finish`, and `restore_cube` remembers those four fields for the grid.

- [ ] **Step 1: Write the failing tests.**

  Engine (`test_plugin_slices_engine.py`):
  - `test_finish_matches_the_core_pipeline`: equals `finish_slice(v, plan_fill(c > 0, frame.cell, ...), frame.cell, engine.finish_settings(f))`.
  - `test_weights_are_built_once_and_reused_across_windows`: monkeypatch `plan_fill` with a counter; three windows give one call.
  - `test_a_new_cell_or_setting_rebuilds_the_weights`.
  - `test_switching_method_back_gives_the_same_slice_as_from_scratch` (Review Focus 4): kriging → IDW → kriging equals a fresh engine's kriging slice.
  - `test_shared_limit_measures_the_finished_slices`.

  Dock (`test_plugin_slices_dock.py`):
  - `test_the_interpolation_group_replaces_fill_radius`: there is no `"Fill radius"` label in the Resolution form; `grid_finish` is visible in This grid and starts at `SliceFinish()` after a grid seed.
  - `test_a_finish_edit_redraws_and_is_remembered_for_the_grid`: pick IDW and flush `_finish_debounce`. Then `current_values()` equals `engine.finish(*engine.slice_at(window), SliceFinish(method="idw"))`, and `session.slice_resolution("A")["method"] == "idw"`.
  - `test_seeding_a_grid_resets_the_panel_and_remembers_nothing`: not dirty.
  - `test_a_remembered_finish_is_restored_on_a_grid_switch`.
  - `test_max_distance_follows_a_line_spacing_edit` (Review Focus 2): edit grid A's spacing from 0.5 to 1.0. The label reads `"= 0.5 m"` and the drawn slice equals one finished at 0.5 m, with no grid switch.
  - `test_a_0_2_0_remembered_radius_is_ignored` (Review Focus 3): remember only `radius_spacings=0.5` for A, switch to A. The panel is at `SliceFinish()` and the survey is not dirty.
  - `test_restoring_a_0_2_0_cube_record_shows_the_defaults` (Review Focus 3): a cube record whose `view` has only the six 0.2.0 keys. The panel is at the defaults after `cube_combo` picks it.
  - `test_saving_a_cube_records_the_finish_and_radius_m`.
  - `test_restoring_a_cube_restores_the_finish_and_remembers_it`.
  - `test_the_shared_stretch_follows_a_finish_change`.

  Export (`test_plugin_slice_export.py`):
  - `test_the_geotiff_carries_interpolation_metadata`. It replaces `test_the_geotiff_carries_fill_radius_and_azimuth_metadata` and checks the exact keys and values for the defaults at spacing 0.5: `"kriging"`, `"0.25"`, `"0.0"`, `"0.0"`, and no `NSGEO_FILL_RADIUS_CELLS`.
  - `test_the_coverage_companion_carries_no_interpolation_metadata`.
  - `test_export_bands_equal_the_finished_slices`.
  - `test_an_export_after_a_refused_resolution_uses_the_frames_cell` (#104):
    - Set the cell spin to a different value, then make z1 ≤ z0 so `_apply_resolution` refuses.
    - Export: every band equals `engine.finish(*engine.slice_at(w), dock.slice_finish())` at `engine.frame.cell`, and `NSGEO_MAX_DISTANCE_M` equals `0.5 × spacing`.
  - `test_exporting_a_rotated_grid_reports_no_fill_warning`: the message bar gets an Info-level message, not a Warning.

- [ ] **Step 2: Run them and see them fail.** Run the three files with the QGIS command. Expected: FAIL. `finish` and `slice_finish` are missing, and the metadata is the old metadata.

- [ ] **Step 3: Implement.** Grep this task's files for `radius` and `fill(`. Every hit in This grid's path goes, except the site's `radius_spacing_spin` and its uses, which are Task 5's.

- [ ] **Step 4: Run the three files, then the whole QGIS suite, core + pure, ruff and mypy.**

- [ ] **Step 5: Measure, and record before and after.**
  - Real data, four real lines at the dock's defaults (the setup `test_shared_limit_measures_…` uses).
  - Before: the median per-window cost of `fill(v, c, radius_cells_for(0.5, 0.5, cell))`, measured on `main`'s code in a scratch checkout.
  - After: the median per-window cost of `engine.finish(v, c, SliceFinish())` and of `SliceFinish(method="idw")`, with weights cached.
  - Spec §7 requires the cached cost to be no slower than the old fill. Report the numbers. If it is slower, stop and report.

- [ ] **Step 6: Commit.**

  ```bash
  git commit -m "feat(slices): This grid interpolates, smooths and exports through the Interpolation panel; Fill radius goes (interpolation spec §7, §8; closes #104)"
  git push
  ```

---

