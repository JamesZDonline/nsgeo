# Task 2 report

## Implemented
- core `covered_cells(frame, coords)` in binning.py, exported from nsgeo.slices, listed in nsgeo-core/README.md (test_public_api requires it).
- `estimate_memory(prepared_samples, n_cells, nz, n_covered)`: cube_bytes = nz*c*4 + c*4 + c*8; docstring names packed layout.
- Engine: `_covered` cache + `_covered_count()` (uses covered_cells, never plan_line); reset at all four places that set `_plans = None` (set_source, _rebuild_geometry, clear; plus the one in the prepare-finished path) and on `self._lines = list(result)`.
- Dock `_update_included_label`: covered count over each included line's trace_coords, failures skipped, 0 with no frame.

## Tests
- core+pure: 1110 passed, 5 skipped. QGIS tier: 1599 passed (baseline 1597 + 2). ruff check/format clean, mypy clean.
- New: test_covered_cells_counts_a_shared_cell_once, test_covered_cells_equals_the_cubes_cell_count (real, 0.2 and 0.05), test_the_estimate_matches_the_cube_it_describes (pure; self-contained builders, no import from core tests), engine test_the_estimate_follows_a_new_cell_size_and_a_new_line_set, dock test_the_included_label_counts_only_covered_cells; dense assertion at pure line 90 replaced, other calls updated.

## TDD
RED: core/pure collection `ImportError: cannot import name 'covered_cells' from 'nsgeo.slices.binning'`; QGIS `-k "estimate_follows or counts_only_covered"` -> 2 failed (ImportError covered_cells). Expected.
GREEN: counts above.

## Self-review
Public-API test forced a __all__ order fix and README row. Pure line-159 call passes n_covered=120*120 to keep its streaming outcome.

## Fix round 1
- Finding 1: `test_the_included_label_counts_only_covered_cells` now spies on `slices_dock.estimate_memory` and asserts the `n_covered` passed equals `covered_cells` over the included lines (and < frame.n_cells). Mutant (dock passes frame.n_cells) fails it.
- Finding 2: new `_included_estimate()` on the dock holds the before-preparing count once; `_update_included_label` and `_update_resident_check_label(before=None)` both use it; the checkbox uses `engine.estimate.cube_bytes` only when `engine.is_prepared`. New test `test_the_checkbox_cost_before_preparing_is_the_packed_figure` asserts the exact packed byte count reaches format_bytes and the face text; mutant (checkbox reads engine.estimate) fails it.
- Command: dock + engine QGIS files: 213 passed; ruff and mypy clean. Both mutants were applied to the working file and restored before commit.
