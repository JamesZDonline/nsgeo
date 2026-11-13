### Task 2: Cuts in the session, the cuts layer and the Survey panel

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/layers.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`
- Test:
  - Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_session_cuts.py`
  - Modify: `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`, `test_plugin_survey_dock.py`, `test_plugin_loads.py`

**Interfaces:**
- Consumes (Task 1): `Cut`, `Cut.new`, `cut_key`, `is_cut_key`, `Site.cuts`, `Grid.to_world`.
- Produces on `SiteSession`:
  - `cuts_changed = pyqtSignal()`
  - `cut_keys() -> list[str]`, `cut_keys_on_grid(grid_id: str) -> list[str]` (drawing order)
  - `cut_for_key(key: str) -> Cut` (`KeyError`)
  - `add_cut(grid_id: str, vertices: Sequence[tuple[float, float]]) -> str`. Returns the key; raises `KeyError` for an unknown grid and `ValueError` from `Cut.new`.
  - `rename_cut(key: str, name: str) -> None` (`ValueError` when the stripped name is empty)
  - `remove_cut(key: str) -> None`
  - `cut_velocity(grid_id: str) -> VelocityModel` (spec call 16: `grid.velocity`, else `resolved_velocity(keys_on_grid(grid_id)[0])`; `KeyError` when neither exists)
- Produces on `SiteLayers`: `refill_cuts() -> None`, plus the `cuts` table.

- [ ] **Step 1: Write the failing session tests** (`test_plugin_session_cuts.py`, with the `session` and `_two_grids` helpers from `test_plugin_session.py`)
  - `test_add_cut_names_marks_dirty_and_announces`:
    - the first cut is named `Cut 1`;
    - after deleting `Cut 1` with a `Cut 2` present, the next is `Cut 3`;
    - `dirty` becomes True;
    - `cuts_changed` fires once per call.
  - `test_add_cut_refuses_an_unknown_grid_and_too_few_points`.
  - `test_rename_keeps_the_key_and_refuses_an_empty_name`.
  - `test_remove_grid_drops_its_cuts_and_keeps_the_others`.
  - `test_cut_velocity_is_the_grids_then_the_first_lines` (spec call 16):
    - grid velocity set → that velocity;
    - grid velocity None and the first line with a header dielectric → that line's resolved model;
    - an override on the *second* line changes nothing;
    - a grid with no velocity and no lines → `KeyError`.
  - `test_cuts_survive_save_and_reopen`: `save()`, then a new session loads the same cuts.
  - `test_keys_stay_lines_only`: `keys()` contains no cut key.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement the session additions.**
  - Load cuts in `_install`.
  - `remove_grid` drops its cuts and emits `cuts_changed` after `grids_changed`.
  - Dirty marking goes through `_set_dirty(True)`.
- [ ] **Step 4: Write the failing layer tests** (`test_plugin_layers.py`, with the `populated` fixture)
  - `test_cuts_table_has_the_declared_fields_and_is_read_only`: fields as in Global Constraints, and `layer.readOnly()`.
  - `test_legend_order_puts_cuts_between_marks_and_lines`.
  - `test_refill_cuts_places_a_cut_in_world_coordinates`: a cut `[(1,1),(6,1)]` on grid A has its first vertex at `GRID.to_world([[1,1]])` in the package CRS, and `length_m == 5`.
  - `test_a_moved_grid_moves_its_cuts` (spec §4.8): `replace_grid` with a new origin moves the cut layer's vertices by the same offset. The `Cut` vertices are unchanged.
  - `test_a_crs_rebuild_refills_the_cuts` (spec test 5, "A CRS rebuild"): after the CRS change that rebuilds tables, the cuts table has the cut.
  - `test_removing_the_last_grid_empties_the_cuts_table`.
- [ ] **Step 5: Run them and see them fail.**
- [ ] **Step 6: Implement the cuts table:**
  - add it to `TABLES`, `DERIVED` and `LEGEND_ORDER`;
  - add `refill_cuts` (`grid.to_world` of the vertices, then `_points`) to `refresh`'s refill loop;
  - add `_style_cuts`;
  - connect `session.cuts_changed` to `refresh`.
- [ ] **Step 7: Write the failing Survey panel tests** (`test_plugin_survey_dock.py`, with the `dock` fixture, `_right_click`, `_action` and `answer_modal`)
  - `test_a_grid_with_cuts_lists_them_under_a_cuts_item_before_its_lines`.
  - `test_rename_cut_asks_for_a_name_and_renames`: answer `QInputDialog.getText` with `("Lower line", True)`.
  - `test_delete_cut_asks_and_says_its_picks_stay`:
    - with 0 picks the text is `Delete Cut 1?`;
    - with 2 picks, stubbed through `session.picks_for`, it ends `Its 2 picks stay on the map.`;
    - a "No" answer keeps the cut.
  - `test_the_delete_key_on_a_cut_deletes_it_after_the_same_prompt`.
  - `test_removing_a_grid_with_cuts_says_so`: the prompt contains `Its 2 cuts are deleted too; their picks stay on the map.`
- [ ] **Step 8: Run them and see them fail.**
- [ ] **Step 9: Implement the Survey panel changes** (plan call 12):
  - rebuild on `cuts_changed`;
  - `item_for_key` finds cut items;
  - the cut context menu offers "Rename cut…", a separator, and "Delete cut" (Open arrives in Task 3);
  - extend `_remove` and `_removal_text` with cut keys.
- [ ] **Step 10: Write and pass the close-prompt test** (`test_plugin_loads.py`): `test_closing_with_an_unsaved_cut_prompts` (spec test 6). After `session.add_cut`, unloading or closing the site asks the existing save question.
- [ ] **Step 11: Run the QGIS files touched, then the full core + pure suite, lint and types.**
- [ ] **Step 12: Commit and push:**
  `git commit -m "feat(cuts): cuts in the session, a read-only cuts layer, and the Survey panel (cut spec §4.2, §4.8)"`

---

