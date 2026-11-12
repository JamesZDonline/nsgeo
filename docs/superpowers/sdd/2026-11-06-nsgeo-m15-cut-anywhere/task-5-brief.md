### Task 5: Picks on cuts

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/layers.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`_on_pick_requested`)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (the pick overlay)
  - `packages/nsgeo-qgis/nsgeo_qgis/map_link.py` (`_jump_to_feature`, `on_info`)
- Test: Create `tests/qgis/test_plugin_cut_picks.py`

**Interfaces:**
- Consumes:
  - Task 3: `CutSection.columns`, `provenance_json`, `column_at`.
  - Task 2: `cut_velocity`.
  - Line editing: `SiteLayers.follow_lines`.
- Produces:
  - `SiteSession.add_cut_pick(key: str, column: int, distance_m: float, time_ns: float, stack_json: str) -> Pick`:
    - working key only, `ValueError` otherwise;
    - a finite time, on the cube's clock (spec call 18), never converted;
    - the distance clamped to `[0, length_m]`;
    - `zero_ns=None` on the `Pick` (#97's column left empty, plan call 13).
  - `SiteSession.derived_cut_pick_fields(key: str, distance_m: float, time_ns: float) -> tuple[float | None, float | None]`, giving depth and velocity, or `(None, None)` when the cut velocity raises `KeyError`.
  - `MapLink(..., on_info: Callable[[str], None] | None = None)`.

- [ ] **Step 1: Write the failing tests** (`test_plugin_cut_picks.py`, a plugin with a GeoPackage, a prepared grid, and an open cut)
  - `test_a_pick_on_a_cut_lands_on_the_cut_and_records_its_provenance` (spec test 5, call 2):
    - a pick at column 12 has `line_key == cut_key`, `trace == 12` and `distance_m == columns.distance_m[12]`;
    - its geometry is `grid.to_world(cut.point_at(distance_m))` in the package CRS;
    - `json.loads(stack_json)["kind"] == "cut"`, and its `time_base` names the cube's clock;
    - `time_ns` equals the clicked time as given, and the row's `zero_ns` is NULL;
    - depth equals `cut_velocity("A").depth_at([t])[0]`.
  - `test_selecting_a_cut_pick_reopens_the_cut_at_its_distance`: with another line working, selecting the pick opens the cut, and `current_trace == column_at(key, distance_m)`.
  - `test_renaming_the_cut_keeps_the_way_back`.
  - `test_deleting_the_cut_leaves_its_picks_and_selecting_one_says_so` (call 3): the row and its geometry are unchanged; selecting it calls `on_info(CUT_GONE_TEXT)`; `current_key` is unchanged.
  - `test_a_pick_on_a_never_saved_cut_behaves_the_same_after_reopening`: close without saving (answer Discard), reopen; the pick is there; selecting it says `CUT_GONE_TEXT`.
  - `test_a_crs_rebuild_keeps_the_cut_pick`.
  - `test_a_cell_change_reopens_the_pick_at_the_same_distance_and_time` (spec test 5, call 12): after changing the cell 0.25 → 0.2, the overlay's column is `column_at(key, distance_m)` under the new step, and `distance_m` is unchanged.
  - `test_a_moved_grid_moves_cut_picks_and_keeps_distance` (spec test 13): after `replace_grid` with a new origin, the geometry moves by the offset and `distance_m` is unchanged.
  - `test_a_grid_velocity_change_rederives_depth_and_a_line_override_does_not` (spec test 13).
  - `test_opening_a_site_rederives_cut_picks_with_no_engine_prepared` (spec test 13).
  - `test_removing_a_grid_keeps_its_cut_picks_on_the_map` (spec test 13): the prompt is answered Yes; the rows are unchanged.
  - `test_a_pick_past_a_shrunk_grid_edge_keeps_its_distance` (Review Focus 2).
  - `test_the_profile_overlays_cut_picks_at_their_columns`: at `(column_at(key, distance_m), time_ns)`, with no time conversion, even when the shown cube's preset sets a time zero.
  - `test_a_pick_made_on_another_clock_is_left_out_and_counted` (spec call 18):
    - make a cut pick under a preset without `time_zero`, then enable `time_zero` in the preset so the cube is rebuilt;
    - the pick is not in `view.set_picks`'s list, and the title ends ` · 1 picks on another clock`;
    - the row is unchanged;
    - turning `time_zero` off again brings it back.
  - `test_a_line_stack_change_never_rezeroes_cut_picks`: after editing the working line's stack so its zero moves, `follow_zero` rewrites that line's rows only, and the cut picks' `time_ns` and `zero_ns` are unchanged.
  - `test_a_preview_cannot_take_a_pick`: the existing preview refusal also holds for cuts.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - `add_cut_pick` and `derived_cut_pick_fields`.
  - In `_on_pick_requested`, a cut key reads the shown `CutSection`, then calls `add_cut_pick` with its `distance_m[trace]` and `provenance_json`. A message string means there is no section: put the reason on the message bar.
  - In `layers.py`:
    - `_pick_point` for a cut key is the cut's point at `distance_m`;
    - `write_pick` reports `no cut with key …`;
    - `follow_lines` takes cut keys: position from `distance_m` (never rewritten), depth and velocity from `derived_cut_pick_fields`;
    - a row whose cut is gone, or whose `distance_m` is NULL, is left alone.
  - The profile's `_refresh_picks` maps cut picks through `column_at`. It uses `time_ns` as stored, and leaves out, and counts, any pick whose provenance `time_base` differs from the section's (plan call 13).
  - `_jump_to_feature` opens a cut and sets its column. For a gone cut it calls `on_info(CUT_GONE_TEXT)`; the plugin passes the message bar.
- [ ] **Step 4: Run them and see them pass. Then run the touched QGIS files (including `test_plugin_layers.py`'s follow tests), core + pure, lint and types.**
- [ ] **Step 5: Commit and push:**
  `git commit -m "feat(cuts): picks on cuts — distance and time, provenance, following the grid (cut spec §4.5, §4.8)"`

---

