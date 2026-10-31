### Task 5: Whole site remembers its resolution (#71), and its seeding rules are pinned (#75)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py` (`SiteScope.__init__`, `enter`, `forget`, `seed_resolution`, `seed_z_from_ready`, `_on_radius_changed`; remove `_note_z_edit`; new `set_radius_quietly`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (`_on_resolution_edited`'s site branch)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`

**Interfaces:**
- Consumes: Task 4's `site_resolution()`, `remember_site_resolution(...)` and `_on_resolution_edited`.
- `_on_resolution_edited`, site branch: when `self._scope == "site"`, for `cell`, `dz_ns`, `t0_ns` and `t1_ns`, call `session.remember_site_resolution(**{field: value})`. For `dz_ns`, `t0_ns` and `t1_ns`, also set `self._site.z_custom = True`. This replaces `SiteScope._note_z_edit`, which is deleted with its three connections; it was the unguarded slot #75 names. `grid_radius_spin` is hidden in site scope, so its field never arrives here.
- `SiteScope._on_radius_changed`: still guarded. While `self.showing and not self.dock._updating`, it also calls `session.remember_site_resolution(radius_spacings=value)`. Every programmatic set of `radius_spacing_spin` goes through the new `set_radius_quietly(dock: Any, value: float) -> None` (signals blocked).
- `SiteScope.forget()` also resets the radius to `DEFAULT_RADIUS_SPACINGS` through `set_radius_quietly`. Today a second survey inherits the first one's radius.
- `SiteScope.enter()` applies a remembered `radius_spacings` through `set_radius_quietly` before `refresh_rows()`.
- `SiteScope.seed_resolution(included)`: the seed runs as today. Remembered values are then laid over it quietly: `cell` right after the cell seed, which the floor clamps. If any of `dz_ns`/`t0_ns`/`t1_ns` is remembered, those are set after the z seed and `z_custom` becomes True, so `seed_z_from_ready()` clamps them from then on and never re-seeds them.
- `seed_z_from_ready()`, when `z_custom` is set: if clamping would leave `z1 <= z0`, set both to the snapped bounds instead (the Task 4 rule, Review Focus 1).

- [ ] **Step 1: Pin the existing seeding rules first** (#75 "seeding rules are untested"). These are characterisation tests and should pass on the current code. If one fails, stop and report: it has found a bug, and fixing it is not this task's call.
  - `test_the_site_cell_seeds_from_the_finest_spaced_grid`. Use `site3_factory`, then before opening, `site.session.replace_grid(dataclasses.replace(site.session.grid("B"), default_spacing=0.3))` and `save()`. Assert the site's cell is `default_cell(0.3, floor)`.
  - `test_the_site_includes_every_grid_with_lines_by_default`. Remove all of C's lines before opening, and assert `dock._site.included() == ("A", "B")`.
  - `test_the_site_cell_is_reseeded_only_when_the_included_grids_change`. Change the cell by hand, leave the site and come back, and assert the hand value is kept. Untick a grid and assert the cell is re-seeded.
- [ ] **Step 2: Run them and see them pass on the unchanged code.** Commit them on their own: `git commit -m "Slices: pin the site's resolution seeding rules (#75)"`.
- [ ] **Step 3: Write the failing tests.**
  - `test_a_site_resolution_edit_is_remembered_in_the_site_view`. `whole_site(plugin)`, set the cell by hand, `dock.flush_debounce()`. Assert `plugin.session.site_resolution() == {"cell": <value>}` and `plugin.session.slice_resolution("A") == {}`.
  - `test_entering_the_site_never_remembers_its_seeded_resolution`. `whole_site(plugin)`. Assert `site_resolution() == {}` and not dirty.
  - `test_the_site_resolution_survives_save_and_reopen`. Follow `test_the_site_view_survives_save_and_reopen`: set the cell, `t0_ns` and a radius of 1.25, save, close, and reopen through `open_plugin`. Enter the site and assert all three come back and the survey is not dirty.
  - `test_a_remembered_site_z_range_is_clamped_not_reseeded`, and `test_a_remembered_site_z_range_wholly_outside_the_data_falls_back_to_the_ready_range` (Review Focus 1, site twin).
  - `test_a_different_survey_starts_the_site_radius_from_the_default`. Set the radius in one survey, then open a second one, built by `site3_factory`, in the same plugin. Assert the site radius reads `DEFAULT_RADIUS_SPACINGS`.
  - `test_a_hand_z_edit_in_the_site_is_clamped_from_then_on`. This replaces whatever pinned `_note_z_edit`, so check the file for such a test first and keep its intent.
- [ ] **Step 4: Run them, see them fail, and implement.**
- [ ] **Step 5: Run all four verification commands and see them pass.**
- [ ] **Step 6: Commit.** `git commit -m "Slices: Whole site remembers its resolution settings (#71)"` and push.

---

