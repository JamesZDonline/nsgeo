### Task 3: This grid's fill radius in line spacings (#72)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (the Fill radius row, `radius_cells`, `view_settings`, `apply_view`, `restore_cube`, `_seed_resolution_defaults`, `rebuild_source`, the debounce wiring)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py` (`show_scope_widgets`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py` (module docstring mentions of `radius_spin`)
- Modify: `docs/guide/getting-started.md` (Step 7, item 3)
- Test: `tests/qgis/test_plugin_slices_dock.py`, `tests/qgis/test_plugin_site_scope.py`, `tests/qgis/test_plugin_slice_export_dialogs.py`

**Interfaces:**
- Consumes: `slices_plan.radius_cells_for(spacing_m, radius_spacings, cell) -> int` and `slices_plan.DEFAULT_RADIUS_SPACINGS`.
- Produces: `SlicesDock.grid_radius_spin: QDoubleSpinBox`, which replaces `radius_spin`. The rename is deliberate: every test and caller that read metres has to be revisited, not silently reinterpreted. Range 0.0–10.0, 2 decimals, single step 0.25, suffix `" × line spacing"`, constructed at 0.0, seeded to `DEFAULT_RADIUS_SPACINGS` on a grid change.
- Produces: `SlicesDock.grid_radius_metres: QLabel`, reading `f"= {metres:.3g} m"` for the selected grid, or empty with no grid. It sits beside the spin in one form row whose field is `SlicesDock.grid_radius_row: QWidget`, with no margins. `site_scope.show_scope_widgets` toggles `dock.grid_radius_row` where it toggled `dock.radius_spin`.
- Produces: `SlicesDock._grid_spacing(self) -> float | None`, the selected grid's `default_spacing`, or `None`.
- Produces: `SlicesDock.radius_cells(self) -> int`, which is `radius_cells_for(spacing, grid_radius_spin.value(), cell_spin.value())`, or 0 with no grid.
- Produces: `SlicesDock.apply_view(self, view: ViewSettings, *, spacing_m: float) -> None`. It sets `grid_radius_spin` to `view.radius_m / spacing_m` (0.0 when `spacing_m <= 0`), still with signals blocked. `restore_cube` passes the record's grid's current `default_spacing`, which is why the grid must be known before `apply_view` runs. `view_settings()` records `radius_m = grid_radius_spin.value() * spacing` (0.0 with no grid). `ViewSettings` and the cube record format are unchanged.
- The metres label is refreshed by `_update_radius_metres(self) -> None` on the spin's `valueChanged`, at the end of `_seed_resolution_defaults`, and in `rebuild_source`. `rebuild_source` runs on `grids_changed`, which a spacing edit emits. The spin's `valueChanged` still starts the shared debounce, as `radius_spin`'s did.

- [ ] **Step 1: Write the failing tests** in `test_plugin_slices_dock.py`. `GRID.default_spacing` is 0.5.
  - `test_this_grid_sets_the_fill_radius_in_line_spacings`. After the grid is seeded: `grid_radius_spin.suffix() == " × line spacing"`, `value() == 0.5`, `singleStep() == 0.25`, `grid_radius_metres.text() == "= 0.25 m"`, and `radius_cells() == round(0.25 / dock.cell_spin.value())`.
  - `test_the_metres_beside_the_radius_follow_the_box`. Set the spin to 1.5 and assert the label reads `"= 0.75 m"` and `radius_cells()` follows.
  - `test_the_radius_follows_a_line_spacing_edit` (Review Focus 3). `session.replace_grid(dataclasses.replace(GRID, default_spacing=1.0))`. Assert the label reads `"= 0.5 m"` and `radius_cells()` doubled, with the spin still at 0.5.
  - `test_a_saved_cube_records_its_radius_in_metres`. Spin at 1.5 on spacing 0.5 gives `dock.view_settings().radius_m == pytest.approx(0.75)`.
  - `@pytest.mark.parametrize("radius_m", [0.0, 0.25, 0.5, 0.75])` `test_an_old_cubes_radius_reopens_with_the_same_radius_in_cells`. Save a cube whose view has `radius_m`, move the spin elsewhere, pick the cube, and assert `grid_radius_spin.value() == pytest.approx(radius_m / 0.5)` and `radius_cells() == max(0, round(radius_m / cell))`.
  - `test_a_cube_saved_before_a_spacing_edit_keeps_its_radius_in_metres` (Review Focus 5). Save with `radius_m=0.5`, change A's spacing to 1.0, pick the cube, and assert the spin reads 0.5 and the label `"= 0.5 m"`.
  - Rewrite the existing `radius_spin` tests (lines ~638–700, ~1503, ~1524) in spacings. Their intent stays: the seeded default, the step size, and a radius of 0 showing the unfilled truth.
  - `test_plugin_site_scope.py`: in `test_the_scope_switch_swaps_the_source_controls`, the three `radius_spin` visibility asserts become `grid_radius_row` asserts.
  - `test_plugin_slice_export_dialogs.py`: `radius_spin.setValue(0.5)` and `(0.0)` become `grid_radius_spin` values that give the same metres on that test's grid spacing.

- [ ] **Step 2: Run the three files and see the new tests fail** (`AttributeError: grid_radius_spin`).

- [ ] **Step 3: Implement.** Write the tooltip for a radius in spacings: it fills cells no line crossed, within this many line spacings; the default is half a spacing, which just closes the gap between lines; 0 shows the unfilled truth. Update `slice_export.py`'s module docstring to name `grid_radius_spin`. Its construction default of 0 still means "unfilled".

- [ ] **Step 4: Update the guide.** In Step 7, item 3 of `docs/guide/getting-started.md`, say the Fill radius is set in line spacings, starts at 0.5, and shows its metres beside the box.

- [ ] **Step 5: Run the core + pure, qgis and lint commands, and see them pass.**

- [ ] **Step 6: Commit.** `git commit -m "Slices: set This grid's fill radius in line spacings (#72)"` and push.

---

