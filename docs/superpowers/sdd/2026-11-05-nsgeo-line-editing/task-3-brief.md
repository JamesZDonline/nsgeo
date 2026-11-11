### Task 3: Slices see the new positions

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`: `_sync_included`, `rebuild_source` and `restore_cube`.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`, `test_plugin_slices_dock.py`, `test_plugin_site_scope.py`

**Interfaces:**
- Consumes: `SiteSession.edit_lines`, `move_lines` and `LineEdit` (Task 2).
- Produces, in `SliceEngine`:
  - `self._placements: dict[str, Any]` holds the placement of every site line, with `label` dropped (`dataclasses.replace(p, label=None)` for a `GridPlacement`). It is captured in `set_source` next to `_grid_fp`, and emptied wherever `_grid_fp` is reset (`set_source`'s reset, `clear()`).
  - `placements_changed(self, keys: Iterable[str]) -> bool`: True when any key that was a site line at the last `set_source` is still one and its label-free placement now differs.
  - `had_line(self, key: str) -> bool`: whether `key` was a site line at the last `set_source`.
  - `_on_lines_changed(self) -> None`: connected to `session.lines_changed` in `__init__`, right after `grids_changed`, and disconnected in `dispose()` beside it.
    - It returns when there is no choice, nothing captured or no site.
    - When `placements_changed(choice.line_keys)`, it works like `_on_grids_changed`'s move branch. With `on_grid_moved` set, it calls `_hand_over_the_move(grid_id)`. Otherwise it calls `set_source` with the choice narrowed to keys still on `choice.grid_id`, inside a guard that reports `could not re-prepare after a line moved: …`.
  - In `set_source`'s job loop, a key whose line is placed on another grid is not prepared. It is reported as `f"{key}: now on grid {other!r}, not {choice.grid_id!r}; left out of this source"`.
- Produces, in `SlicesDock`:
  - `_sync_included`'s explicit-choice prune keeps only the grid's own lines: `valid = set(self._default_included(grid_id))`.
  - `rebuild_source` gets a new `elif`, after the first-computation branch. When the scope is `"grid"`, `self._included_is_default` is set, `self.engine.choice` is not None and on the selected grid, and `any(self.engine.had_line(k) for k in self._included if k not in self.engine.choice.line_keys)` holds, it calls `self.prepare()`. That is a line moved onto a grid whose source takes every line. An imported line was never in the snapshot, so it keeps today's "stale" status.
  - `restore_cube`: a recipe key whose line is a site line on another grid is left out of `_included`. When any are, `self.error.emit(f"cube {cube_id!r}: {n} line(s) moved to another grid since it was saved and were left out: {labels}")`. A recipe left with nothing falls back to the default, as an empty one already does.

- [ ] **Step 1: Write the failing engine tests** in `test_plugin_slices_engine.py`, using `sourced` and `_prepare`:
  - `test_a_placement_edit_to_a_prepared_line_re_prepares`:
    - give the first key an offset of 1.5 with `edit_lines`, then `wait_for_preparation`;
    - `len(prepared) == count + 1`;
    - that key's `PreparedLine.coords` equal `session.line_for_key(k).trace_coords(session.site.frames)` to `abs=1e-9`.
  - `test_an_edit_to_a_line_outside_the_source_does_not_re_prepare`: prepare with the first three keys and edit the fourth. The count is unchanged and nothing is running.
  - `test_a_label_only_edit_does_not_re_prepare`.
  - `test_a_line_moved_to_another_grid_leaves_the_source`:
    - add `Grid("B", (600.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)` and `move_lines([k3], "B")`;
    - after the wait, `k3` is in neither `engine.choice.line_keys` nor `engine.prepared_lines`, and `errors == []`.
  - `test_with_a_grid_moved_hook_a_placement_edit_hands_over`: mirror `test_with_a_grid_moved_hook_a_move_clears_and_hands_over_instead_of_re_preparing`, with an offset edit in place of the grid move.
  - `test_a_grid_length_change_re_prepares_exactly_once`:
    - first add a reversed line at `start_along=6.0`;
    - `replace_grid` with `size_y=7.0` gives `len(prepared) == count + 1`, because the `lines_changed` that follows finds the snapshot already current.
  - `test_set_source_leaves_out_a_key_now_on_another_grid_and_says_so`: a choice naming a B line prepares the A lines only. `errors` holds `"now on grid 'B', not 'A'"`.
- [ ] **Step 2: Write the failing dock tests** in `test_plugin_slices_dock.py`, using `docked`:
  - `test_a_line_moved_off_the_grid_leaves_an_explicit_choice`: `set_included` the first two keys, wait, then move the second to a new grid B. `dock.included_keys()` is just the first key, and once the engine has waited, the status reads `prepared · 1 lines`.
  - `test_a_line_moved_onto_a_default_grid_re_prepares_it`:
    - add grid B with a line, wait for A;
    - `move_lines` that line onto A;
    - after the wait, it is in `engine.choice.line_keys` and the status is prepared.
  - `test_a_line_imported_onto_a_default_grid_still_shows_stale`: today's behaviour, pinned.
  - `test_restoring_a_cube_drops_a_line_now_on_another_grid_and_says_so`:
    - record a cube with every line, the way the existing restore tests do, then move one line to B and `restore_cube`;
    - `dock.included_keys()` lacks the moved line, and `error` carries `moved to another grid since it was saved`.
- [ ] **Step 3: Write the failing Whole site test** in `test_plugin_site_scope.py`: `test_a_placement_edit_re_prepares_only_that_grid_in_the_site_view`.
  - With `site3` showing in Whole site, edit one B line's offset.
  - B goes through `queued` and back to ready, and A and C are never re-queued. Record `dock.site_engine.grid_state(g)` for each grid from the site engine's `on_changed` notifications, the way that file's other re-queue tests do.
- [ ] **Step 4: Run all three files and see the new tests fail.** Expected: no re-preparation on a placement edit, `AttributeError` for `had_line`, and the moved key still in the choice.
- [ ] **Step 5: Implement** the engine and dock changes to the interfaces above. Each new slot body is guarded. Each new comment says why, citing `(line editing spec §4.5)`.
- [ ] **Step 6: Run the three files, then the whole QGIS tier.** Expected: all pass. The full slices dock and site scope files are the regression net for R-P5 and trap 1. Never let two preparations run at once.
- [ ] **Step 7: Lint, types, commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py
git commit -m "feat(slices): a source re-prepares when a line it holds moves, and drops a line that left its grid (#29, #64)"
git push origin nsgeo-line-editing
```

---

