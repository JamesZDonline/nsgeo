# Task 3 report: This grid's fill radius in line spacings (#72)

Commit d2a4715 "Slices: set This grid's fill radius in line spacings (#72)", pushed to origin nsgeo-slices-cleanup.

## Implemented
- `slices_dock.py`: `radius_spin` replaced by `grid_radius_spin` (0-10, 2 decimals, step 0.25, suffix " × line spacing", constructed at 0, tooltip reworded). New `grid_radius_metres` QLabel and `grid_radius_row` QWidget (HBox, zero margins). New `_grid_spacing()` and `_update_radius_metres()`. `radius_cells()` uses `radius_cells_for` (0 with no grid). `view_settings()` records metres. `apply_view(view, *, spacing_m)` converts metres to spacings with signals still blocked. `restore_cube` passes the record's grid's current spacing and refreshes the label after the grid is selected. The seed sets `DEFAULT_RADIUS_SPACINGS` (unchanged unguarded set, as radius_spin's was) then refreshes the label. `rebuild_source` refreshes the label. The spin's valueChanged goes to the shared debounce exactly as before, plus the label slot (guarded, logs).
- `site_scope.py`: toggles `grid_radius_row`.
- `slice_export.py`, `plugin.py` (export_geotiff docstring, ruling 3; no other mentions in plugin.py): docstrings name `grid_radius_spin`.
- `docs/guide/getting-started.md` Step 7 item 3 updated.
- Task 2 mechanisms untouched.

## TDD
RED: `pytest ...test_plugin_slices_dock.py ... -x -k "radius or fill or spin or ..."` -> `AttributeError: 'SlicesDock' object has no attribute 'grid_radius_spin'`, `1 failed, 2 passed, 123 deselected` (stopped by -x at the first failure).
GREEN: the three files together: `1 failed, 155 passed` (the failure was a direct `apply_view(...)` call in `test_restore_cube_brings_every_control_back_ruling_al` lacking the new `spacing_m`; fixed by passing `spacing_m=GRID.default_spacing`). Then full suite green below.

## Results
- core+pure: 808 passed, 3 skipped.
- qgis (full, `-p no:xonsh`): 1198 passed in 598 s.
- lint: ruff check and ruff format --check clean (155 files). mypy command: no issues in 36 files.

## Count discrepancy (needs coordinator attention)
The brief says baseline qgis was 1320. The suite now collects 1198. I added 9 tests (6 test functions, one parametrised x4), so HEAD fc68626 would collect 1189 by my count, which is 131 below 1320. I did not delete any test; `git diff --stat` on tests shows only the three files edited. I could not determine the cause (perhaps the 1320 baseline included something not collected by this command, or a different test directory). No test failed or skipped in my run.

## Files changed
slices_dock.py, site_scope.py, slice_export.py, plugin.py, docs/guide/getting-started.md, and tests test_plugin_slices_dock.py, test_plugin_site_scope.py, test_plugin_slice_export_dialogs.py.

## Existing tests rewritten
- `test_the_fill_radius_is_metres_and_survives_a_cell_size_change` renamed `..._is_a_distance_...`; asserts spin 0.5 spacings, cells unchanged.
- `test_a_grid_starts_from_...` and the spacing-parametrised default test: spin asserts 0.5 (spacings) instead of 0.5*spacing metres.
- `test_filling_reaches_between_the_lines...`: setValue(1.0 m) became 2.0 spacings (1 m at 0.5 spacing); 0.0 stays.
- step test: `singleStep() == 0.25` replaces `<= 0.1`.
- tooltip test: uses `grid_radius_spin` (tooltip still says "no line").
- `test_restore_cube_brings_every_control_back`: direct `apply_view` call gets `spacing_m=GRID.default_spacing`.
- site_scope: four visibility asserts (brief said three) now `grid_radius_row`.
- slice_export_dialogs: `setValue(0.5)` -> `setValue(1.0)` (0.5 m at this grid's 0.5 m spacing); 0.0 unchanged; docstring name updated.

## Self-review
Diff checked. Label refresh paths: spin edit, seed, restore, rebuild_source (spacing edit via grids_changed). No unguarded new programmatic sets.

## Concerns
- A spacing edit moves `radius_cells()` and the label but does not itself restart the debounce, so the displayed slice picks up the new radius only on the next resolution/slice refresh. The brief did not ask for it; say if you want a debounce start in `rebuild_source`.
- Baseline count mismatch above.
- I ran `ruff format` over `docs` by mistake; it rewrote 72 unrelated docs, which I reverted with `git checkout docs/superpowers` before committing. Only getting-started.md is changed in docs.

# Fix round 1

Commit: see `git log` ("Slices: seed the radius quietly and redraw on a spacing edit (#72)"), pushed.

1. Seed quiet: `grid_radius_spin.setValue(DEFAULT_RADIUS_SPACINGS)` in `_seed_resolution_defaults` is wrapped in blockSignals; label refresh stays explicit. `cell_spin` untouched. Test `test_a_seeded_radius_emits_no_value_changed` (docked_two_grids, spin 1.5, switch to B, no emission).
2. Redraw on spacing edit: `rebuild_source` calls `refresh_slice()` directly (the file's slider pattern; there is no resolution change to debounce) when scope is grid, `_resolution_owed` is unset, the engine is prepared and holds the combo's grid, and `radius_cells()` differs from the new `_filled_radius_cells` (recorded in `refresh_slice`'s fill branch). Does not fire in site scope or during Task 2's wait window (`_resolution_owed`, plus the engine-grid check). `test_the_radius_follows_a_line_spacing_edit` now asserts the finite-cell count grows with no other refresh.
3. Added `test_with_no_grid_the_radius_reads_zero_and_blank` (no survey, and open survey with no grid); fixed the stale `radius_spin` in the seed docstring; reworded the 0.75 m comment.

RED (impl reverted): `2 failed, 1 passed` (spacing-edit and seed tests failed; the no-grid test already held). GREEN: the three files in full `158 passed`. ruff check and format --check clean. Full qgis suite not re-run this round.
