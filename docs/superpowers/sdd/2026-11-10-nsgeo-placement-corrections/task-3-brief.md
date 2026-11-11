### Task 3: Edit lines (Scale, Destagger, Fit to grid edges) and the Survey panel

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py`
  - Columns become Label, Offset (m), Dir, Start (m), **Scale**, **Destagger (m)**, Grid, Along, Traces, Length (m), Picks, Note, with `COL_SCALE` and `COL_DESTAGGER` added to the constants.
  - `EDITABLE` gains both.
  - Add the two bulk rows (call 9) and the header tooltips.
  - Add cell parsing for both columns.
  - Change the dialog width to `resize(1100, 560)`.
  - Update the module docstring.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`, in `_line_item`, for the suffixes (call 10). Use `getattr(p, "scale", 1.0)` and `getattr(p, "travel_shift", 0.0)` as the existing code does for `direction`.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py`

**Interfaces:**
- Consumes: Task 2's `LineEdit.scale`, `LineEdit.travel_shift`, `LineEdit.fitted(span)` and `span_m`.
- Produces:
  - Widgets: `scale_spin`, `set_scale_button`, `fit_button`, `destagger_spin`, `set_destagger_button`.
  - Methods, each a guarded slot like `flip`:
    - `set_scale(value: float) -> None`
    - `fit_to_edges() -> None`
    - `set_destagger(value: float) -> None`
  - `set_scale` and `set_destagger` go through the existing `_apply`. `fit_to_edges` skips any row whose `span_m(...)` is `0.0` and names it, using the Global Constraints copy, on the status line. It still fits the others.
  - **Watch the name clash:** the existing `shift_button`, `offset_spin` and `shift_offset` move offsets *across* the grid. Leave them exactly as they are.

- [ ] **Step 1: Write the failing tests** in `test_plugin_edit_lines_dialog.py`, using the `table` fixture (Grid5 is 15 m; six 60-trace lines, so span is 59/60 m).
  - **`test_fit_to_grid_edges_puts_both_ends_of_every_selected_line_on_the_edges`**
    - **Action:** select all, then `fit_to_edges()`.
    - **Assert before OK:**
      - Every Scale cell reads `f"{15.0 / (59 / 60):.4f}"` and is highlighted (`CHANGED`).
      - Start reads `0.00` on forward rows and `15.00` on reversed rows.
      - The Note on every row carries the "stretches it by" text, because this scale is far from 1.
    - **Action:** `dialog.accept()`.
    - **Assert after OK:** each line's `distance_along()` has ends on 0 and 15 (abs 1e-9).
  - **`test_fit_skips_a_line_that_cannot_be_fitted_and_says_so`**
    - **Setup:** reuse the setup of `test_a_line_with_no_distance_axis_is_listed_and_editable` (a time-triggered line).
    - **Action:** select it and a normal row, then fit.
    - **Assert:**
      - The status line contains `has no recorded length to fit, so it was left as it is`.
      - The normal row's Scale changed and the time-triggered row's did not.
  - **`test_typing_a_scale_and_a_destagger_edits_only_that_row`**
    - **Action:** type `0.95` into row 2's Scale cell and `0.24` into its Destagger cell.
    - **Assert:**
      - Only row 2 is highlighted in those columns.
      - The cells read `0.9500` and `0.24`.
    - **Action:** OK.
    - **Assert:** the line's placement has `scale == 0.95` and `travel_shift == 0.24`.
  - **`test_a_scale_that_is_not_above_zero_is_refused`**
    - **Action:** parametrize `"0"`, `"-1"`, `"abc"` and `"nan"` into a Scale cell.
    - **Assert:**
      - The status line contains `is not a scale above 0; unchanged` (`abc` may give the existing "is not a number" text instead; pin whichever the code gives, but nothing is recorded).
      - The cell reverts.
  - **`test_set_scale_and_set_destagger_change_every_selected_row`**
    - **Action:** select rows 0 and 1. Set the scale spin to 0.97 and press Set. Set the destagger spin to 0.3 and press Set.
    - **Assert:**
      - Both rows show the values, and the other rows are untouched.
      - The status line counts 2 lines changed.
  - **`test_a_pending_fit_uses_the_grid_length_at_ok`**
    - **Action:** select the forward rows (0, 2, 4) and fit. Then `session.replace_grid(replace(GRID5, size_y=14.0))`, then OK.
    - **Assert:** the forward lines' last traces sit at 14.0.
  - **Extend** `test_every_slot_reports_an_unexpected_failure_and_does_not_raise` with a `"fit"` case: patch `_frames` to raise, then call `fit_to_edges()`.
  - **`test_plugin_survey_dock.py`, `test_a_corrected_line_shows_its_scale_and_destagger`:**
    - **Action:** edit a line to `scale=0.954` and `travel_shift=0.24` through `session.edit_lines`.
    - **Assert:**
      - Its item text contains `· ×0.954` and `· destagger +0.24 m`.
      - An uncorrected line's text contains neither `×` nor `destagger`.
- [ ] **Step 2: Run the two files and see the new tests fail.**
- [ ] **Step 3: Implement.** Highlighting: COL_SCALE and COL_DESTAGGER differ when the placed value is more than `SAME_M` away from `seen`'s.
- [ ] **Step 4: Run both files and the rest of the Edit lines and Survey tests; all pass.** Then run lint.
- [ ] **Step 5: Render the dialog offscreen to a PNG**, with a fitted, highlighted table and the panel enabled, and look at it. Check that no column is cut off, the bulk rows line up with the existing rows, and nothing overlaps. Write the PNG to the scratchpad, not the repo, and attach its path in the report.
- [ ] **Step 6: Commit** `feat(plugin): Scale, Destagger and Fit to grid edges in Edit lines; the Survey panel shows them (#3, #47)`, then push.

---

