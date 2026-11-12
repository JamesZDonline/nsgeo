# Merge origin/main into nsgeo-fine-cells-export

## Semantic fix
Main's #154 made `estimate_memory(..., *, method)` required; `export_pipeline._grid_estimate` called it without. Fixed in `_grid_estimate`.

## Double counting
`estimate_memory(method="min_curvature")` adds CURVATURE_PLAN_BYTES_PER_CELL (96) on top of WEIGHT_BYTES_PER_CELL (96) because the live engine holds a curvature plan beside a kriging preview. The export (`_GridState.finish`) calls `plan_fill` once per grid: for min_curvature that is a `CurvaturePlan` only, no kriging preview. So passing "min_curvature" straight through would count 192 B/cell, double. `_grid_estimate` now takes cube/lines from `estimate_memory(method="kriging")` and, for a min_curvature grid, sets weights_bytes = n_cells * CURVATURE_PLAN_BYTES_PER_CELL (counted once). Both constants are 96, so the export estimate is numerically unchanged (it was already 96/cell); SOLVE_BYTES_PER_CELL (36, working space) stays a separate term. Bench table therefore not re-run; estimate >= measured peak still holds (1243 vs 1179 MB at 0.025/0.025). A docstring note records this. EXPORT_BUDGET_BYTES untouched.

## Tests
- New `test_a_minimum_curvature_estimate_counts_the_curvature_plan_once` (weights == n_cells*96, below the live engine's 192).
- Existing test updated to pass `method="kriging"`.
- Other `estimate_memory(` callers all pass method (grep).

## Other breakage
#153 changed only site_scope remembered-lines logic and docs; engine API unchanged. `site_export_spec` and `grid_export_spec` still read `engine.prepared_lines()`, the engine's frame/z and the passed finish: correct. #156/#160 touch refine and placement, not export inputs.

## Results
Pure 281 passed/1 skipped; core 982 passed/4 skipped; ruff check, ruff format --check, CI mypy clean. QGIS tier 1741 passed (16m36s).
