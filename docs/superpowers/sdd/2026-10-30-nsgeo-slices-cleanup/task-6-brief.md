### Task 6: Tidy-ups from #75 and #54

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (`_remember_source` docstring)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py` (module docstring, `_sweep` docstring)
- Test: `tests/qgis/test_plugin_slices_dock.py`, `tests/qgis/test_plugin_site_scope.py`, `tests/qgis/test_plugin_slice_export.py`, `tests/qgis/test_plugin_slice_layer.py`

Each item names its source, so the PR can tick the matching box.

- [ ] **Step 1: #75, Survey memory, "one case has no test".** Add `test_opening_a_survey_that_has_saved_cubes_stays_clean` to `test_plugin_slices_dock.py`. With `docked_two_grids`, save a cube (`_save_cube`) and save the survey. Reopen it in a new `SiteSession` and `SlicesDock`, wait for the preparation, and assert `not reopened.dirty` and that `cube_combo` lists the cube. Dispose of the second dock as the reopen test does. It should pass at once. If it fails, report it.
- [ ] **Step 2: #75, Survey memory, "the import pick-up test half-dodges its hazard".** Add two tests next to `test_a_default_line_choice_picks_up_a_line_imported_later`:
  - `test_a_default_line_choice_picks_up_an_import_after_save_and_reopen`. Leave A's lines as the default, `session.save()`, and reopen in a new session and dock. Import `_line(tmp_path, "A", "FILE__099", 9.0)` there, and assert the new key is in `dock2.included_keys()`.
  - `test_an_explicit_line_choice_does_not_pick_up_an_import_after_save_and_reopen`. Do the same after `dock.set_included(a_keys[:2])`, and assert the new key is not included and `dock2.included_keys() == a_keys[:2]`.
- [ ] **Step 3: #75, Whole site UI, "one assertion compares a value with itself".** In `test_the_readout_names_each_grids_depth_and_any_absent_grid`, replace `"C": dock.site_velocities()["C"]` with C's expected value, worked out independently: `plugin.session.resolved_velocity(<C's first line key>)`. Add an assert that it is neither `v_a` nor `v_b`.
- [ ] **Step 4: #75, Tooling and docs, "M11's export tests can crash on failure".** In `test_plugin_slice_export.py`, replace each of the seven `ds = None` closes with `try`/`finally: ds.Close()`, the way `_metadata` in `test_plugin_site_scope.py` does it, so a failing assert can't keep a GDAL dataset alive past `exitQgis()`.
- [ ] **Step 5: #54, Slice preview.**
  - Correct `_sweep`'s docstring: the code keeps both files, not either.
  - Correct the module docstring: stale files go at the end of the tick that supersedes them, not "on later ticks". Read `_sweep` and `update_north_up` before rewording either.
  - Add `test_a_persistently_failing_update_from_a_corrupt_file_keeps_the_scratch_folder_bounded` next to the faked one. Instead of replacing `_repoint`, make each tick's write produce a file GDAL cannot open: monkeypatch `SliceLayer._write` to write junk bytes to its path. Assert the folder holds at most the files the layer reads, and the layer still points at an existing file. Then confirm that removing either keep-guard in `_sweep` on its own makes one of the two tests fail. Try each removal by hand, revert it, and record what you saw in your report. Set `PYTHONDONTWRITEBYTECODE=1` while doing so: stale `.pyc` files fake survivors.
- [ ] **Step 6: #75, Survey memory, "a docstring is stale".** `_remember_source`'s docstring names two callers. `restore_cube` is a third. After Task 4, also say that it writes the source only, and that the resolution is remembered by `_on_resolution_edited` and `restore_cube`.
- [ ] **Step 7: Run all four verification commands and see them pass.**
- [ ] **Step 8: Commit.** `git commit -m "Slices: tidy-ups from the M12 and M9 reviews (#75, #54)"` and push.

---

