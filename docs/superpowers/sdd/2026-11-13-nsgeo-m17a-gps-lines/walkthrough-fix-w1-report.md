# W1 report

Commit: see git log (fix(m17a): rtk_gaps appears only on a site with GPS lines).

Changed (layers.py): `_has_gps_lines()`, `_drop_rtk_gaps()` (empties the table, then `_drop_loaded_layer`);
`ensure_tables` skips the rtk_gaps table and layer without GPS lines; `refresh` drops it first when none
(also in the no-grid/no-line/no-CRS early path); `refill_rtk_gaps` and `_style_rtk_gaps` return when absent.

New tests (test_plugin_layers_gps.py): tape-only site has no rtk_gaps (failed on old code: layer present);
first GPS line brings it between cuts and lines, last takes it away from group, project and layers.layers,
and a new one brings it back (failed: layer stayed); reopening tape-only site with existing table opens no
layer (failed); tape-only refresh logs no rtk_gaps message (passed before too, a guard). Existing
tape-only assertion `feature_count("rtk_gaps")==0` became `not in layers.layers`.
test_plugin_layers.py: five legend-order lists back to five names; tests that iterated TABLES/LEGEND_ORDER
on GPS-free sites use `_SITE_TABLES`/`_SITE_ORDER` (rtk_gaps removed), group layer count uses len(_SITE_TABLES).
LEGEND_ORDER constant test kept. Guide needed no change (already says "with GPS lines").

Runs: layers_gps 20 passed; layers 110 passed (after fixing the count line); survey_dock 92 passed;
gps_import_dialog 23 passed; core+pure 1766 passed, 5 skipped; ruff clean; mypy no issues in 58 files.

# W1 fix round 1

- I1: `test_reopening_a_tape_only_site_...` now removes the last GPS line while grid A still exists (the
  ordinary refresh path) and asserts: no `rtk_gaps` in `layers.layers` or the group, old layer id gone from the
  project, and 0 features in the on-disk table. Mutations in scratch worktrees (removed afterwards):
  A (delete `if not self._has_gps_lines(): self._drop_rtk_gaps()` in refresh) -> that test fails (line 452);
  B (`_refill("rtk_gaps", [])` -> `pass`) -> that test fails (`assert 1 == 0`, line 458).
- M2: `assert layer.readOnly()` added to the gap-table style test.
- M3: comments by `DERIVED`/`LEGEND_ORDER` and the module docstring say rtk_gaps exists only with GPS lines.
- M4: the early path calls `_drop_rtk_gaps()` before `_clear_derived_tables()`.
- Runs: layers_gps 20 passed; test_plugin_layers 110 passed; ruff check/format clean; mypy clean.
