### Task 2: This grid opens the grid selected in the site list (#70, #75 F-9)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (`_resume_grid`, two new private helpers)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`

**Interfaces:**
- Consumes: `SiteSourcePanel.selected_grid() -> str | None` (`ui/site_panel.py`), and Task 1's `source_keys`.
- Produces: `SlicesDock._grid_to_resume(self) -> str | None`. The site panel's selected grid, when it is offered by `grid_combo` and differs from `grid_combo.currentText()`; otherwise `None`.
- Produces: `SlicesDock._switch_resumed_grid(self, grid_id: str) -> None`. Selects `grid_id` in `grid_combo` inside the `_updating` guard, so `_on_source_changed` does not fire. Then it runs `_sync_included()`, whose grid-changed branch re-seeds the resolution and restores the grid's remembered source, and calls `_mark_cube_unsaved()`, `_update_included_label()` and `_refresh_source_status()`. Finally it sets `_grid_prepared_away = False` and `_grid_prepare_pending = True`. It does not call `_remember_source` (Approved behaviour 2), and it does not restore `_grid_spins` or `_grid_palette`, which belong to the grid that was left.
- `_resume_grid(top)` keeps its signature. Its body is wrapped in `try`/`finally`, and the `finally` calls `self._run_pending_grid_prepare()` (#75 F-9). With a target grid it calls `_switch_resumed_grid`, then sets `_pending_top_ns = top` and `_sync_grid_slider()`. Without one it does exactly what it does today.

- [ ] **Step 1: Write the failing tests** in `test_plugin_site_scope.py`:
  - `test_this_grid_opens_the_grid_selected_in_the_site_list`. Enter `whole_site(plugin)`, `dock.site_panel.select_grid("B")`, note the site's top time, then `dock.grid_scope_button.click()`. Assert `dock.grid_combo.currentText() == "B"`, then `dock.engine.wait_for_preparation(20_000)`, `dock.engine.choice.grid_id == "B"`, and the slider's top time within `dz/2` of the site's, as `test_switching_scope_keeps_the_window_time` measures it. Also assert `not plugin.session.dirty`.
  - `test_this_grid_opens_the_selected_grid_with_its_remembered_source`. Before entering the site, `remember_slice_source("B", preset="raw", lines=site3.keys("B")[:2])`. Select B in the site and switch back. Assert the preset combo reads `"raw"` and `dock.included_keys() == site3.keys("B")[:2]`.
  - `test_with_this_grids_own_grid_selected_it_comes_back_as_it_was_left`. Leave the selection on A, which is the default on entering. Assert This grid's cell spin and palette are what they were before entering, and `dock.engine.choice.grid_id == "A"`.
  - `test_opening_the_selected_grid_waits_for_a_site_task_that_outlived_its_cancel`. Copy the set-up of `test_leaving_the_site_waits_out_a_task_that_outlived_its_cancel`: `_CANCEL_TIMEOUT_MS = 1`, a `LoadCounter` with `delay=0.15`. Select B, then click This grid. Assert `dock.site_engine.has_live_task` and `not dock.engine.is_running`, then that it settles prepared on B with `counter.max_concurrent == 1`.
  - `test_a_selected_grid_removed_meanwhile_falls_back_to_this_grids_own`. Select C in the site, then `plugin.session.remove_grid("C", with_lines=True)`. Read the call's exact signature in `session.py`. Click This grid. Assert the combo reads `"A"` and no error was emitted. Connect `dock.error` to a list.
  - `test_a_failure_inside_resume_still_hands_this_grids_moves_back`. Enter the site and let it settle. Monkeypatch `dock._refresh_source_status` to raise `RuntimeError` once. Call `dock.set_scope("grid")` inside `pytest.raises(RuntimeError)`. Assert `dock.engine.on_grid_moved is None`.

- [ ] **Step 2: Run them and see them fail.**
  Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py -q -p no:cacheprovider -p no:xonsh -k "selected or resume"`
  Expected: the B tests and the F-9 test fail. The "as it was left" and "removed meanwhile" tests may already pass. They pin today's path, so they stay.

- [ ] **Step 3: Implement** the two helpers and the new `_resume_grid`. Update `_resume_grid`'s docstring to the rule in Approved behaviour 2, and cite #70 and F-9.

- [ ] **Step 4: Run `test_plugin_site_scope.py` and `test_plugin_slices_dock.py` in full and see them pass.**

- [ ] **Step 5: Commit.** `git commit -m "Slices: This grid opens the grid selected in the site list (#70)"` and push.

---

