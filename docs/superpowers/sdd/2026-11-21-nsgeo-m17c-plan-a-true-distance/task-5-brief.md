### Task 5: Gap over in Edit lines, and the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/line_edit.py` (`TrackEdit`), `packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py` (column, bulk row), `packages/nsgeo-qgis/nsgeo_qgis/session.py` (`edit_lines` applies it; Task 2's re-attach covers the source), `docs/guide/getting-started.md`
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_line_edit.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_gps.py`

**Interfaces:**
- Consumes: Task 1's `gap_threshold`, `TrackPlacement.gap_m`; Task 2's re-attach in `edit_lines`; Task 4's `_trace_axis_for`.
- Produces:
  - `TrackEdit.gap_m: float | None = None` (None leaves it unchanged) and `TrackEdit.gap_auto: bool = False` (True returns the line to automatic); `placed()` applies them (`gap_auto` wins).
  - Edit lines: a `COL_GAP` column headed `Gap over (m)`, right after `COL_DESTAGGER`, editable on GPS rows, "—" on tape rows (typing there is ignored, as GPS rows ignore Offset). The header tooltip is `GAP_TIP`. Automatic shows `auto {v:.2f}` with `v = gap_threshold(line.distance_along(), None)`; a typed value shows `{v:.2f}`. An empty cell returns the row to automatic; a value that is not finite and above 0 is refused with `{text!r} is not a length above 0; unchanged`.
  - A bulk row under Destagger: label `Gap over (m)`, a spin box (0.01–10.00, 2 decimals, step 0.01, default 0.10), `Set` and `Automatic` buttons acting on the selected GPS rows; selected tape rows are left alone and the status line says `TAPE_SKIP`.
  - The guide's GPS profile paragraph says: profiles draw each trace at its true distance; a lift is one hatched gap with the lifted traces left out; Gap over in Edit lines tunes it, automatic at 6× the line's usual step.

- [ ] **Step 1: Write the failing tests.**
  - `test_pure_line_edit.py`: `test_a_track_edit_sets_gap_over_and_returns_to_automatic`.
  - `test_plugin_edit_lines_gps.py`: `test_a_gps_row_shows_its_automatic_gap_over` (a synthetic GPS line at 60 traces/m: `auto 0.10`); `test_typing_gap_over_sets_it_and_clearing_returns_to_automatic`; `test_a_bad_gap_over_is_refused`; `test_a_tape_row_shows_a_dash_for_gap_over`; `test_bulk_set_and_automatic_act_on_gps_rows_and_skip_tape_rows` (status text is `TAPE_SKIP` with the count); `test_gap_over_extremes_reach_the_profile` (OK with 0.01 m, then 100 m: the open profile's `transform.axis.gap_m` follows, and the line's source `gap_m` likewise); `test_gap_over_survives_save_and_reopen`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement**, then update the guide.
- [ ] **Step 4: Run** the touched QGIS files (`test_plugin_edit_lines_gps.py test_plugin_edit_lines_dialog.py test_plugin_edit_lines_measure.py test_plugin_session_gps_grids.py`), `-m real_data`, core+pure and lint. Expected: all pass. Fix any existing Edit lines test that counted columns by index, naming each in the report.
- [ ] **Step 5: Commit and push** (`feat(m17c): Gap over in Edit lines tunes where a GPS profile shows a gap (#134)`).
