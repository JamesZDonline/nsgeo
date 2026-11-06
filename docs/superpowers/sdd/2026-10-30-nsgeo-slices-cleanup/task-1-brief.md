### Task 1: One reading of a grid's line choice (#74)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py` (`source_keys`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/line_choice_dialog.py` (`_refresh`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (`restore_cube`, and its docstring paragraph about `recipe.choice.line_keys`)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_line_choice_dialog.py`, `tests/qgis/test_plugin_site_scope.py`, `tests/qgis/test_plugin_slices_dock.py`

**Interfaces:**
- Produces: `site_scope.source_keys(session, grid_id, by_grid=None) -> tuple[str, ...]`, with the same signature. The remembered lines still on the grid, in survey order. If none is remembered (`None`), or the remembered list filters to nothing, it returns every line on the grid. That is the rule `SlicesDock._restore_remembered_source` already applies.
- Produces: `LineChoiceDialog.buttons.button(QDialogButtonBox.StandardButton.Ok)` is disabled exactly while `included_keys()` is empty, with the tooltip `"Tick at least one line."` while disabled and no tooltip while enabled.

- [ ] **Step 1: Write the failing tests.**
  - `test_plugin_line_choice_dialog.py`: `test_ok_is_greyed_out_while_no_line_is_ticked`. Open the dialog on a grid with lines, all ticked, and assert OK is enabled. Call `select_none()` and assert OK is disabled with the tooltip `"Tick at least one line."`. Tick one row through `set_included(key, True)` and assert OK is enabled. Also `test_ok_is_greyed_out_on_a_grid_with_no_lines`.
  - `test_plugin_site_scope.py`, using `plugin`/`site3`:
    - `test_both_scopes_read_a_line_choice_that_left_the_grid_as_every_line`. Call `plugin.session.remember_slice_source("A", preset="p", lines=("raw/gone/X.DZT",))`. Assert `dock.line_choice_keys("A")` in This grid equals `site3.keys("A")` once `rebuild_source()` has run and This grid has left and come back to A. Then `whole_site(plugin)`. Assert `site_scope.source_keys(plugin.session, "A") == site3.keys("A")`, `dock.site_engine.engine_for("A").line_count == 4`, and that the A row's `lines` column reads `"4 / 4"` and its state is not `"no lines"`. Read the row through `site_scope.site_rows(...)`, or the panel's model, whichever the existing tests use.
    - `test_removing_every_remembered_line_reads_as_every_line_in_both_scopes`. Remember A's first two keys as its lines, then `plugin.session.remove_lines(those two keys)`. Assert both scopes now use A's remaining two lines.
    - `test_a_source_edit_after_emptying_does_not_change_what_the_site_prepares`. Remember lines that have all left A. In This grid, change the preset to `"raw"`, which rewrites the record as `lines: None`. Then `whole_site(plugin)` and assert A's line count is 4, the same as before the edit.
  - `test_plugin_slices_dock.py`, using `docked_two_grids` and `_save_cube`: `test_an_old_cube_record_without_lines_restores_every_line`. Save a cube from a two-line choice, delete the `"lines"` key from `session.site.cubes[cube_id]`, pick it in `cube_combo`, and assert `dock.included_keys() == _grid_keys(session, "A")` and `session.slice_source("A")["lines"] is None`.

- [ ] **Step 2: Run them and see them fail.**
  Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_line_choice_dialog.py packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py -q -p no:cacheprovider -p no:xonsh -k "greyed or every_line or emptying or without_lines"`
  Expected: FAIL. OK is never disabled, the site reads the choice as `()`, and the old cube restores no lines.

- [ ] **Step 3: Implement.** In `source_keys`, return every line when the filtered tuple is empty. Update its one-line docstring. In `LineChoiceDialog._refresh`, set the OK button's enabled state and tooltip from `self._included` after the table is rebuilt. Every path that changes the ticks (`set_included`, `select_all`, `select_none`, an item click) already ends in `_refresh`. In `restore_cube`, after `self._included = recipe.choice.line_keys`, set `self._included = self._default_included(recipe.choice.grid_id)` and `self._included_is_default = True` when `recipe.choice.line_keys` is empty. Rewrite the docstring paragraph that defended the empty set: say that an old record names no line list, the remembered record already says every line (D4), and #74 makes This grid show what the record says.

- [ ] **Step 4: Run the three files in full and see them pass.** Any existing test that pinned the old empty-set reading is wrong under #74. Correct it, and name it in the commit message.

- [ ] **Step 5: Commit.** `git commit -m "Slices: read an emptied line choice as every line in both scopes (#74)"` and push.

---

