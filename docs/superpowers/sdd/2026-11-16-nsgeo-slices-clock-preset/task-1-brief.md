### Task 1: One rule for pending values, and the fallback preset (#162 item 2, #163 item 4, #102, #152)

Spec §2 and §5. Suggested implementer tier: opus (lifetime state).

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`. Change `rebuild_source`,
  `_sync_included`, `_on_source_changed`, `set_included` and `_switch_resumed_grid`, and add
  `_drop_restore_pending`.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`

**Interfaces:**
- Produces:
  - `SlicesDock._drop_restore_pending(self) -> None`: forgets what a restore still owes
    (`_pending_z_shift` set to its "nothing owed" value, `_pending_palette = None`). Tasks 2 and
    3 extend it.
  - `SlicesDock._sync_included(self, *, by_hand: bool = False) -> None`.
- **Test style for later tasks:** test `_pending_z_shift` by truthiness (`assert
  dock._pending_z_shift`, `assert not dock._pending_z_shift`). Task 3 changes its type from `bool`
  to `OwedShift | None`.

- [ ] **Step 1: Write the failing tests** (in `test_plugin_slices_dock.py` unless named otherwise)
  - `test_an_edit_while_a_restore_prepares_keeps_its_shift_and_note`, parametrized over
    `signal` in `("lines_changed", "grids_changed", "presets_changed")`, with `docked_zeroed`:
    1. `_prepared_with_owed_record(dock, session)` (engine cleared, so the restore dispatches);
    2. `dock.restore_cube("A__old")`, then `assert dock.engine.is_running`;
    3. `getattr(session, signal).emit()`;
    4. `wait_for_preparation`, then `_assert_shifted_once(dock, errors)`.
  - **Replace** `test_rebuilding_the_source_drops_an_owed_shift` with
    `test_rebuilding_the_source_keeps_what_a_restore_owes_on_the_same_site`: a real restore while
    preparing (as above, with a non-default palette in the record's view), then
    `dock.rebuild_source()`. Then `assert dock._pending_z_shift` and the palette is still pending.
  - `test_a_restored_palette_does_not_carry_into_the_next_survey` (`docked`):
    1. save a record whose `view.palette` is an offered palette other than the current default;
    2. `dock.engine.clear()`, then restore it and `assert dock.engine.is_running`;
    3. `session.save()`, then `session.close_site()`, then `assert dock._pending_palette is None`;
    4. open a second survey in `tmp_path / "second"` (the same grid, three synthetic lines and
       preset `p`), then `wait_for_preparation`;
    5. assert `dock.palette_combo.currentText()` is the default noted before step 1.
  - `test_a_grid_the_combo_falls_back_to_opens_on_the_preset_whole_site_draws_it_with`
    (`docked_two_grids`):
    1. pick `q` on A by hand;
    2. assert `session.slice_source("B")` is `None` or `{}`;
    3. `session.remove_grid("A", with_lines=True)`, then `wait_for_preparation`.

    Then:
    ```python
    assert dock.grid_combo.currentText() == "B"
    assert dock.preset_combo.currentText() == site_scope.default_preset(session, "B") == "p"
    assert dock.engine.choice.preset == "p"
    assert not session.slice_source("B")
    ```
  - `test_a_grid_picked_by_hand_still_carries_the_preset_over` (guard): A on `q`, pick B in the
    combo. B shows `q`, and `session.slice_source("B")["preset"] == "q"`.
  - `test_opening_a_survey_does_not_carry_a_same_named_preset_over`: the first survey shows `q`.
    The second has presets `p` and `q` and no record for its grid. It opens on `p`.
  - **Review Focus 1,** `test_removing_the_grid_while_its_restore_prepares_drops_the_restore`
    (`docked_two_grids`):
    1. save a record of A with a non-default palette;
    2. `dock.engine.clear()`, then restore it;
    3. while it is running, `session.remove_grid("A", with_lines=True)`, then
       `wait_for_preparation`.

    Then `dock._pending_palette is None`, `not dock._pending_z_shift`, and the palette is B's
    default.
  - In `test_plugin_site_scope.py`,
    `test_a_survey_opened_after_closing_one_in_whole_site_starts_at_its_first_slice(plugin, site3_factory)`:
    1. `whole_site(plugin)`, then move the slider to about 60% of its range and `_events()`;
    2. `plugin.session.save()`, then `plugin.session.close_site()` and `_events()`;
    3. assert `dock.scope() == "grid"`, `dock._pending_top_ns is None` and
       `not dock._resolution_owed`;
    4. `plugin.session.open_site(site3_factory().json_path)`, then `wait_for_preparation` and
       `_events()`;
    5. `assert dock.slice_slider.value() == 0`.

- [ ] **Step 2: Run them; every bug test fails, and both guard tests pass**

- [ ] **Step 3: Implement**
  - `_drop_restore_pending()`. Use it in place of the paired `_pending_palette = None` /
    `_pending_z_shift = False` lines in `_on_source_changed`, `set_included` and
    `_switch_resumed_grid`.
  - `rebuild_source`:
    - drop the unconditional clear at its top;
    - before anything else, `new_site = self.session.site is not self._site_seen`; if it is new,
      call `_drop_restore_pending()` first;
    - in the existing branch beside `self._site.forget()`, also set `_pending_top_ns = None` and
      `_resolution_owed = False`. The closing survey's switch back to This grid (`set_scope("grid")`
      → `_resume_grid`) set them in this same call.
  - `_sync_included(by_hand=False)`. In the grid-changed branch, when not `by_hand`:
    `_drop_restore_pending()`, then select `site_scope.default_preset(self.session, grid_id)` inside
    the `_updating` guard (skip it when that is `None` or not offered). Then go on as today.
    `_on_source_changed` passes `by_hand=True`.
  - The docstrings of `_pending_palette` and `_pending_z_shift` say when they are dropped: a new
    site, a source change (by hand, from the site list, or a fallback grid), or their own
    `_on_prepared`. Never a refresh that keeps the source.

- [ ] **Step 4: Run the task's tests, both whole files and the pure tier; all pass**

- [ ] **Step 5: Commit**

---

