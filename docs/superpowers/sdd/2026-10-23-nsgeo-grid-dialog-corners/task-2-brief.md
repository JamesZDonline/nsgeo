### Task 2: One corner table and Fit

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`
  - Remove `QTabWidget`, `_build_corner_tab`, `_build_digitise_tab`, `_build_polygon_tab`, `digitise_requested`, `set_digitised`, `use_polygon`, `set_corner_row`, `_corner_arrays`, `residual_label` and the module docstring's "three ways in".
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`. Remove the `digitise_requested.connect` line and `_start_digitise`. Leave `_finish_with_digitise_tool` and `finished`'s stranded-tool cleanup for Task 5.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py`

**Interfaces:**
- Consumes: Task 1's `CORNER_ROLES`, `corner_frame`, `rotate_roles`, and core's `fit_grid_from_corners` and `Grid.to_world`.
- Produces, on `GridDialog`:
  - **Column constants:** `COL_ROLE, COL_A, COL_B, COL_FROM, COL_PICK, COL_OFF = range(6)` at module level.
  - **Widgets:**
    - `corners_crs` (`QgsProjectionSelectionWidget`, starting on the project CRS, or EPSG:4326 when that is invalid)
    - `corner_table` (4 × 6; the headers read `lon`/`lat` when `corners_crs` is geographic, else `E`/`N`)
    - `pick_buttons: list[QPushButton]`, one cell widget per row, text `Pick`
    - `pick_all_button`, `rotate_button` (`⟳ Rotate`), `clear_button`, `fit_button`, `fit_status: QLabel`
    - `size_hint: QLabel` and `use_measured_button` (`Use these`), both hidden until relevant
  - **Signals:** `pick_requested = pyqtSignal(int)`, `pick_all_requested = pyqtSignal()`, `corners_changed = pyqtSignal()`. `corners_changed` is emitted after any row changes, including after Rotate and Clear.
  - **Methods:**
    - `corner_point(row: int) -> QgsPointXY | None` (in `corners_crs`)
    - `corner_source(row: int) -> str`
    - `set_corner(row: int, point: QgsPointXY, crs: QgsCoordinateReferenceSystem, source: str) -> bool`. It converts `crs` → `corners_crs`. On `QgsCsException` it writes `f"could not convert that point into {authid}"` to `fit_status`, leaves the row unchanged, and returns False.
    - `clear_corners() -> None`, `rotate_corners() -> None`, `fit_corners() -> None`, `use_measured_size() -> None`
    - `sizes_typed() -> tuple[bool, bool]`
    - `measured_size() -> tuple[float | None, float | None] | None` (`None` before any Fit)
    - `corner_offsets() -> list[float | None]` (metres, one per row)

- [ ] **Step 1: Delete the tests of removed UI.** Delete these tests; Tasks 3 and 5 add their replacements by name:
  - the polygon-tab and `use_polygon` tests (5)
  - `test_digitised_points_set_origin_and_azimuth`, `test_digitise_tab_instructions_mention_the_right_click_abort`, `test_set_digitised_rejects_coincident_points`
  - every `test_digitise_flow_*` and every test that clicks `digitise_button` (the stranded-tool, hidden-mid-pick, unload-mid-pick and three rubber-band tests)
  - `test_corner_tab_residual_caption_distinguishes_mirrored_from_not_square` (C14 now refuses instead)
  - `test_corner_fit_places_control_points_not_anchored_at_the_local_origin` (non-corner control points are a non-goal)

  Keep the three `test_digitise_tool_*` unit tests until Task 5. In `test_crs_guard_blocks_every_route_to_a_bad_crs`, delete route 2 (the digitise canvas); the rest stands.
- [ ] **Step 2: Write the failing tests.** "Type" a cell with `d.corner_table.item(row, COL_A).setText(...)`, which emits `itemChanged` just as an edit does. Tests set `crs_widget` and `corners_crs` to `UTM16` unless a test says otherwise.
  - `test_the_dialog_has_one_corner_table_and_no_tabs`:
    - `not hasattr(d, "tabs")`
    - `not hasattr(d, "digitise_requested")`
    - the role column reads `["origin", "+X", "+X+Y", "+Y"]`
  - `test_typed_corners_fit_the_grid`: type all four `SITE_CORNERS`, then `fit_corners()`.
    - the origin is within 1e-6 of `SITE.origin`
    - the azimuth is within 1e-6 of 10.0
    - both sizes are within 1e-6 of 20.0
    - `fit_status.text() == "rigid fit RMS 0.000 m from 4 corners"`
    - every offset is < 1e-6
    - every source is `"typed"`
  - `test_a_typed_size_survives_fit_and_the_grid_stays_pinned_at_the_origin`: set `size_x` to 18.0 first, type four corners, then Fit.
    - `size_x` is still 18.0; `size_y` is 20.0; the origin is within 1e-6 of `SITE.origin`
    - offsets are about `[0, 2, 2, 0]`
    - `size_hint` is visible and reads `"the corners measure 20.00 × 20.00 m · your size is kept"`
    - then `use_measured_size()` → `size_x` is 20.0, `sizes_typed()` is `(False, False)` and the hint is hidden
  - `test_fit_does_not_depend_on_typed_sizes`: Fit, note the origin and azimuth, type sizes 7 × 9, then Fit again → the same origin and azimuth.
  - `test_an_existing_grid_opens_with_both_sizes_typed` → `sizes_typed() == (True, True)`.
  - `test_off_by_follows_the_form_without_a_refit`: after Fit, `azimuth.setValue(11.0)`.
    - offsets for rows 1–3 are now > 0.1
    - `fit_status` is unchanged
    - a form origin of (0, 0) blanks every offset
  - `test_fit_refuses_coincident_corners` (the port of `test_digitise_flow_recovers_from_coincident_points`): rows 0 and 1 at one point → `"coincide"` in `fit_status`, and the origin is untouched.
  - `test_fit_refuses_mirrored_corners`: rows 1 and 3 swapped → `"mirrored"` in `fit_status`.
  - `test_fit_needs_a_metric_grid_crs`: `crs_widget` set to EPSG:4326 → `fit_status` contains `"metric CRS"` and nothing changes. Task 4 replaces this rule.
  - `test_a_non_number_cell_reports_and_leaves_the_row_empty`: type `"518204,112"` → `corner_point(0) is None`, and `fit_status` contains `"origin"` and `"not a number"`.
  - `test_changing_corners_in_converts_the_points`: type four rows, then set `corners_crs` to `WGS84`.
    - `corner_point(0)` equals the transform of `SITE_CORNERS[0]` within 1e-9°
    - the headers read `lon`, `lat`
    - setting it back restores the points within 1e-6 m
  - `test_rotate_carries_sources_and_swaps_typed_sizes`: type rows 0 and 2, and set sizes 30 and 20 by hand. Rotate.
    - `corner_point(1)` is the old row 2, and rows 0 and 2 are empty
    - `size_x == 20`, `size_y == 30`, `sizes_typed() == (True, True)`
  - `test_clear_empties_every_row_and_leaves_the_form`: Clear empties the table and keeps the form's values.
  - `test_corners_changed_fires_on_every_row_change`: one emission each for a typed cell, `set_corner`, Rotate and Clear.
- [ ] **Step 3: Run them and see them fail.**
- [ ] **Step 4: Implement.**
  - **Layout:** a **Corners** `QGroupBox` holding the "Corners in" row, the table, the button row and `fit_status`, above the existing form. Under the Size row, add a row holding `size_hint` and `use_measured_button`.
  - **Row state:** keep `self._corners: list[tuple[QgsPointXY, str] | None]` (point in `corners_crs`, source). The dialog writes cell text under a `_filling` guard, so its own writes never count as "typed".
  - **Typed sizes:** a `_typed = [False, False]` flag pair, set from `valueChanged` unless the dialog itself is writing the box (`_sizing` guard). `_prefill` marks both as typed.
  - **Fit:** follows spec §4.2, using the grid CRS as it stands. If that CRS has no authid or isn't in metres, write `"set a metric CRS for the grid first"` and stop.
  - **"off by" and the size hint:** recompute them from a temporary `Grid` built from the form whenever a row, the origin, the azimuth, a size, `crs_widget` or `corners_crs` changes.
  - **"Corners in" conversion:** remember the previous `corners_crs` so its change converts the old points into the new one.
- [ ] **Step 5: Run the file**, then the whole qgis tier, ruff and mypy. Expected: all green, with the counts recorded.
- [ ] **Step 6: Commit and push.** `feat(plugin): one corner table and Fit; typed sizes stick; live off-by (#63)`

---

