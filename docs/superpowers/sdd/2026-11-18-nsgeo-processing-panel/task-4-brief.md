### Task 4: The Difference view and the panel's line (#13, #48, #20 item 4, #33)

Spec §6 and §7.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (`_on_rows_moved`, a line label
  at the top, `preview_changed` and `rebuild` updating it)
- Modify: `docs/guide/getting-started.md` (one line in the Processing section)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py` (plugin fixture, two
  lines), `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`

**Interfaces:**
- Consumes: `velocity_records.line_label(line)`; `session.preview_key`; `session.preview_changed`
  (str, int); `session.grid_for_line(line)`.
- Produces:
  - `ProcessingDock.line_label: QLabel`;
  - `processing_dock.LINE_LABEL_TEXT = "<b>{name}</b>{grid}"`, with `grid` being `" · grid {id}"`
    or `""`;
  - `processing_dock.PREVIEW_SUFFIX = " · the profile is previewing {name}"`.
  - Names are escaped with `html.escape`.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_drag_reorder_reaims_the_difference_view` (#13; the plugin fixture):
    - add `dewow`, `background_mean` and `gain_agc`; select row 1; Difference on;
    - `pd.list.model().moveRow(QModelIndex(), 1, QModelIndex(), 3)`;
    - `pd.list.currentRow() == 2`;
    - `prd.difference_label.text() == "Difference: Background removal (mean)"`;
    - `prd.image.rg.data` equals `stack.difference(2).data`.
  - `test_selecting_time_zero_with_difference_on_shows_the_result` (#48, the issue's exact
    repro):
    - `time_zero(mode="sample", sample=40)`, then `dewow`; row 1; Difference on; then select
      row 0;
    - the button is unchecked and the label is empty;
    - `prd.image.rg.data` equals `stack.result().data`.

    It is a guard test: it passes on main. Its docstring says so, and says it fails when
    `current_radargram`'s `except ValueError` branch returns None after `_decline_difference`.
    Run that mutation once, and report it.
  - `test_clear_resets_the_difference_view` (#20 item 4; the `opened` profile-dock fixture with
    profiles and two steps):
    - `set_difference_index(1)`, then call `dock._clear()` directly;
    - `_difference_index == -1`, the label is empty, and `difference_cleared` fired once;
    - the docstring says no real path reaches it today, because `close_site` goes through
      `_open("")` first, and that it fails without the reset in `_clear`.
  - `test_closing_the_site_with_difference_on_unchecks_it` (the plugin fixture): Difference on,
    then `s.close_site()`; the button is unchecked and the label is empty.
  - `test_the_panel_names_its_line` (the processing `opened` fixture):
    - `dock.line_label.text()` contains `<b>FILE__001</b>` and `· grid A`;
    - after `session.close_site()` (no line open), it is empty.
  - `test_the_panel_names_the_previewed_line_too`:
    - `session.set_preview(keys[1], 3)`: the label ends with `PREVIEW_SUFFIX.format(name=
      "FILE__002")`;
    - `set_preview(None)`: the suffix is gone.
  - `test_a_line_name_is_escaped_and_never_widens_the_panel`:
    - a line whose label is `"<b>" + "x" * 300`;
    - the text holds `&lt;b&gt;`;
    - `minimumSizeHint().width()` is unchanged.
  - `test_steps_added_during_a_multi_selection_land_on_the_open_line` (#33; the plugin fixture):
    - select both line features on `plugin.layers.layers["lines"]` (copy `_feature_id` from
      `test_plugin_map_link.py`);
    - `pd.add_step("dewow")`: it is on `keys[0]`, and the label names `FILE__001`;
    - select only `keys[1]`'s feature: the list is empty and the label names `FILE__002`;
    - `s.stack_for(keys[0])` still holds the Dewow.
- [ ] **Step 2: Run them.** Expected:
  - the #13 test FAILS: the label says "Automatic gain control";
  - the label tests FAIL (`AttributeError: line_label`);
  - the #48, `_clear` and close tests pass (guards).
- [ ] **Step 3: Implement it** in `processing_dock.py`.
  - `_on_rows_moved` calls `self._emit_difference(True)` after `move_step` when
    `diff_button.isChecked()`.
  - `self.line_label` is a rich-text `QLabel` above the button row: word-wrapped, with an Ignored
    horizontal policy.
  - `_update_line_label()` runs at the end of `rebuild()` and on `session.preview_changed`
    (guarded):
    - it is empty with no line or on a cut key;
    - the preview suffix appears when `session.preview_key` is set and differs from the
      working key.
- [ ] **Step 4: Run the tests and the four whole files,** plus `test_plugin_slices_width.py` and
  `test_plugin_map_link.py`. Expected: PASS.
- [ ] **Step 5: Update the guide.** Add one line in the Processing section: the panel names, at
  its top, the line its steps belong to, and the line a map hover is previewing.
- [ ] **Step 6: Commit** `fix(processing): Difference follows a dragged step; the panel names its line (#13, #33)` and `test(…): pin #48 and #20 item 4`.

### After Task 4: #21

The coordinator reviews `processing_dock.py` as it now stands and recommends to the user whether
to split it (spec §9). If the user chooses a split, it becomes Task 5:
- no behaviour change;
- the existing tests are unchanged apart from imports;
- it is written as its own brief at that point.

Otherwise #21 gets a comment with the decision, or a follow-up issue.
