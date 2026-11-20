### Task 3: GPS rows in Edit lines

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_gps.py` (new); the existing Edit lines test files must still pass.

**Interfaces:**
- Consumes: `TrackEdit` and the `edit_lines` contract (Task 2).
- Produces: `EditLinesDialog.edit_for(key) -> LineEdit | TrackEdit`; `GPS_SKIP = "Left {n} GPS line(s) alone: {what} applies to tape lines only."` as a module constant.

- [ ] **Step 1: Write the failing tests** on a grid holding three tape lines and two GPS lines (`open_gps(..., grid_id="A")`):
  - The table lists all five in survey order. A GPS row's Offset, Dir, Start and Scale cells read `—`, are not editable and carry the copy's tooltip; Along reads `GPS`; Traces, Length (walked), Picks are filled.
  - Editing a GPS row's Label and Destagger, then OK, changes only those fields (`trace_coords` before/after differ only by the destagger's shift along the track).
  - Choosing another grid in a GPS row's Grid cell, then OK, moves it with its track unchanged.
  - Bulk Offset step, Flip, Start, Scale, Fit to grid edges on a selection of two tape and one GPS line: the tape rows change, the GPS row does not, and the status line reads `GPS_SKIP` with `n=1` and the right `{what}`. Bulk Destagger and Move to grid apply to all three.
  - Measure with GPS rows selected measures the tape rows only and says `GPS_SKIP` with `what="Measure"` (use the existing Measure test helpers; a GPS row is never handed to `destagger_job`).
  - Review Focus 5: with the dialog open, `session.set_travel_shift([gps_key], 0.2)`; OK skips that row as changed elsewhere (named on the status line, as for a tape row) and applies the rest.
  - Moving a GPS row up or down changes the survey order like a tape row's.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** Rows for `TrackPlacement` lines hold a `TrackEdit`. Every method that reads `placed(frames).offset/direction/start_along/scale/axis` branches on the edit type: render (`—`, read-only, tooltip), `_item_changed` (only Label, Destagger, Grid reach a `TrackEdit`), `_apply` callers for Offset/Dir/Start/Scale/Fit/Snap (skip and count GPS rows, then `_say(GPS_SKIP…)`), `set_destagger` and `move_to` (apply to both), `_measure_snapshot` (tape rows only), `_counts` and the dirty-cell colouring (compare a `TrackEdit` with `changes`). `Along` reads `GPS` for a GPS row; the header's axis summary ignores GPS rows.
- [ ] **Step 4: Run the new file and every `test_plugin_edit_lines*.py` file to pass**; lint, types.
- [ ] **Step 5: Commit and push** (`feat(m17b): GPS rows in Edit lines: label, destagger and grid (#134)`).

---

