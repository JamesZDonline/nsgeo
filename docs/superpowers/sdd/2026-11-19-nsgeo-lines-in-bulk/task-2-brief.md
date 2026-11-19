### Task 2: The map and the Survey panel share one line selection (#57)

**Files:**
- Modify: `map_link.py` (`lines_selected` signal, `select_lines`, a depth-counted guard; a few
  lines in `_on_selection`)
- Modify: `ui/survey_dock.py` (`line_selection_changed` signal, `select_lines`; `_capture_state`
  / `_restore_selection` / `_follow_current` each get a one-line call into new functions)
- Modify: `plugin.py` (two `connect` lines)
- Possibly modify: `layers.py`, only if Step 1 shows the refill needs bracketing (a depth counter
  `MapLink` can read; nothing else in `layers.py`)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_line_selection.py` (new: the wired plugin)

**Interfaces:**
- Consumes: `SurveyDock.selected_line_keys()` (Task 1), `SiteSession.set_lines_velocity` (Task 1).
- Produces: `MapLink.lines_selected = pyqtSignal(list)`, `MapLink.select_lines(keys: list[str]) -> None`;
  `SurveyDock.line_selection_changed = pyqtSignal(list)`, `SurveyDock.select_lines(keys: list[str]) -> None`.

- [ ] **Step 1: Find out what a refill does to the selection** (spec §3.4's hazard). Write
  `test_a_refill_keeps_or_clears_the_lines_selection_as_measured` in `test_plugin_map_link.py`
  (the `linked` fixture): select two features, count `selectionChanged` emissions and read
  `selectedFeatureIds()` across `session.set_line_velocity(...)` (a `lines_changed`). Record the
  measured behaviour in the test's docstring and in the task report; it decides Step 7's guard.
- [ ] **Step 2: Write the failing `MapLink` tests** in `test_plugin_map_link.py`:
  - `test_selecting_several_lines_announces_them_and_opens_nothing`: `lines_selected` carries the
    keys in any order; `current_key` unchanged. (Keep `test_selecting_several_lines_promotes_none`.)
  - `test_selecting_one_line_announces_it_and_opens_it`.
  - `test_deselecting_everything_announces_an_empty_selection_and_keeps_the_line_open`.
  - `test_select_lines_selects_those_features_and_neither_announces_nor_opens`: after
    `link.select_lines([k])`, the layer's selected feature is `k`'s, `lines_selected` did not
    fire and `current_key` did not change, also for exactly one key.
  - `test_select_lines_ignores_keys_with_no_feature` (an unplaced line's key).
- [ ] **Step 3: Implement them; run; pass.**
- [ ] **Step 4: Write the failing Survey panel tests** in `test_plugin_survey_dock.py`:
  - `test_select_lines_selects_exactly_those_rows_unfolds_their_grids_and_opens_nothing`.
  - `test_select_lines_does_not_announce_back`: `line_selection_changed` not emitted by it.
  - `test_a_ctrl_click_announces_the_new_line_selection`: `_click(dock, item, Ctrl)` emits the
    remaining keys in tree order; nothing opens, also when one line is left.
  - `test_a_grid_or_cut_selection_announces_no_lines`.
  - `test_the_line_selection_survives_a_rebuild`: select three lines, `set_lines_velocity` on
    them, still three selected; the open line stays the current item when among them.
  - `test_opening_a_line_makes_it_the_selection_and_announces_it` (`session.open_line` with three
    selected: one selected, announced).
  - `test_opening_a_cut_announces_an_empty_line_selection`.
- [ ] **Step 5: Implement them; run; pass.**
- [ ] **Step 6: Write the failing wired tests** in `test_plugin_line_selection.py`, through
  `NsgeoPlugin(fake_iface).initGui()` and a site with grid A's synthetic lines, one GPS line and
  one time-triggered (unplaced) line:
  - `test_a_rectangle_over_several_lines_selects_them_in_the_panel_and_opens_nothing`
    (`selectByIds` on the `lines` layer stands in for the rectangle).
  - `test_a_ctrl_click_in_the_panel_takes_the_line_off_the_map_and_opens_nothing` (down to one).
  - `test_clicking_empty_map_clears_both_and_the_open_line_stays_open`.
  - `test_gps_lines_select_like_tape_lines`.
  - `test_an_unplaced_line_stays_selected_in_the_panel_and_a_map_gesture_drops_it`.
  - `test_the_selection_survives_a_bulk_velocity_in_both_places` (Review Focus 1: six lines,
    `set_lines_velocity`, then the panel's and the layer's keys are both the six).
  - `test_delete_after_a_map_selection_removes_lines_only` (#31's rule, with the grid row swept
    into the selection).
  - `test_real_grid2_lines_select_from_the_map` (real data: `GRID2_LINES[:6]` imported into a grid
    sized for them; select four on the layer; the panel holds those four).
- [ ] **Step 7: Wire the two `connect` lines; add the refill guard Step 1 calls for; run; pass.**
- [ ] **Step 8: Run the three test files, `-m real_data`, and core+pure; all pass.**
- [ ] **Step 9: Commit and push.**
  `git commit -m "feat(map): the map and the Survey panel share one line selection (#57)"`

