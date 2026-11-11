# Task 1 report: the export pipeline, without Qt, plus the memory budget

Status: BLOCKED on one decision (the budget, step 4). Everything else is built and green.
Commit: 6483fbf `feat(export): a Qt-free export pipeline at any cell and pixel (budget decision pending)`
(not pushed; the subject differs from the brief's because the budget is not chosen).

## The block

The brief: choose band by band if it fits `DEFAULT_BUDGET_BYTES` (1.5 GB) at the three listed settings,
otherwise stop and report BLOCKED with the numbers (no grid-by-grid design). It fits at two of three and not at 0.025 m cell / 0.0125 m pixel.

Bench: `bench_site.py --export CELL PIXEL`, ten 20 m grids at 0.5 m spacing, 60 tr/m, eight at 4-10 deg and two at 90 deg, 65 x 84 m block,
edge match, 3 bands x 5 ns. Peak = tracemalloc over the whole run, prepared lines (246 MB) excluded.

| cell | pixel | method | lattice | first band incl. setup (s) | band (s) | peak (MB) | estimate (MB) |
|---|---|---|---|---|---|---|---|
| 0.05 | 0.05 | kriging | 1304 x 1687 | 14.4 | 0.4 | 294 | 305 |
| 0.05 | 0.05 | min curvature | 1304 x 1687 | 7.6 | 3.3 | 302 | 311 |
| 0.025 | 0.025 | kriging | 2607 x 3374 | 147.6 | 0.9 | 1204 | 1220 |
| 0.025 | 0.025 | min curvature | 2607 x 3374 | 44.0 | 22.0 | 1179 | 1243 |
| 0.025 | 0.0125 | kriging | 5214 x 6748 | 159.5 | 2.2 | 2768 | 2783 |
| 0.025 | 0.0125 | min curvature | 5214 x 6748 | 51.2 | 20.6 | 2743 | 2806 |

At 0.025/0.0125: taps 1575 MB (30 M covered pixels x 52 B; measured exactly: 1574 MB, built in 12 s for all ten grids), fill weights 614 MB, one band 401 MB.
Rebuilding taps per band does NOT help: compose needs every grid's taps at once. Options for the controller:
1. A bigger `EXPORT_BUDGET_BYTES` (about 3 GB covers the worst measured, 2.77 GB).
2. A strip-wise compose (compose_footprints on lattice row strips, taps built per strip): peak about weights + one strip. Still band by band, still core calls only, but a plan addition.
3. Refuse a pixel under half the cell (then the three settings fit at 0.025/0.025 = 1.2 GB).
`EXPORT_BUDGET_BYTES` is left at 1_500_000_000, marked PROVISIONAL in `slices_plan.py`; the module docstring records the table and "Decision: NOT MADE".

Other measurements: min curvature is about 2.1 s per grid per band at 0.025 m (spec worst case was 11 s). First band at 0.025 m kriging is dominated by building ten grids' fill weights (about 14 s a grid). Every grid streamed (48k traces a grid is under one frame).
Estimate vs measured: estimate >= peak in all six rows (0 to 6% over after adding a `gather` term of 56 B per pixel of the largest window, measured 37-51).

## What was implemented

- `nsgeo.slices.frame_lattice(frame, pixel) -> SiteLattice` in `display.py` (lazy import of `SiteLattice`: `site` imports `display`); `_build_north_up_plan` uses it; exported in `__init__`, README row added (alphabetical).
- `nsgeo_qgis/export_pipeline.py` (numpy, stdlib, `nsgeo.slices`, `nsgeo_qgis.slices_plan` only): `ExportCancelled` (moved here per R1; `slice_export.py` imports it, old imports work), `ExportGrid`, `ExportSpec`, `ExportEstimate`, `ExportBand`, `estimate_export`, `run_export`.
- `slices_plan.py`: `EXPORT_BUDGET_BYTES` (provisional), `export_refusal` with the exact copy.
- `bench_site.py --export CELL PIXEL` (repeatable) and `--export-bands`.
- `run_export`: setup once (plans, cube where residency says, taps, seams for edge); per band: `window_on` per grid, bin, `normalise` on BINNED values with the typed gains, finish per grid (`plan_fill` once per grid, kept; `CurvaturePlan.solve(values, should_stop)`, `SolveStopped` -> `ExportCancelled`; `smooth`), `compose_footprints(..., counts=coverage, cells_per_pixel)`.
  `should_stop` is checked before binning each grid, before finishing each grid, and inside the solve. `progress(band, n_bands, grid_id)` (band from 0) is called before each present grid is finished. Absent grids get no call.
- `world_to_frame` (R2) is called only in tap building. It is called TWICE per grid per export when set (concern 1).

## Tests and TDD

RED (implementation file moved aside): `pytest packages/nsgeo-qgis/tests/pure/test_pure_export_pipeline.py` ->
`ImportError: cannot import name 'export_pipeline' from 'nsgeo_qgis'`, `1 error during collection`. (Tests were written before the implementation but the implementation was drafted in the same sitting; the RED shown is the collection failure, and `frame_lattice` tests were run only after both existed, so no per-test RED for them.)
GREEN: `PYTHONPATH=packages/nsgeo-core/src .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_export_pipeline.py -q` -> `21 passed in 10.53s` (before the last edits); final full run:
`pytest packages/nsgeo-qgis/tests/pure/ packages/nsgeo-core/tests/` -> `1217 passed, 5 skipped in 58.31s` (with local real data symlinked into the worktree, git-ignored, so the real-data tests ran).
`ruff check .` clean, `ruff format --check .` clean, CI mypy line: `Success: no issues found in 43 source files`. QGIS `test_plugin_slice_export.py`: 45 passed (import of the moved `ExportCancelled`). The 14-minute QGIS tier was not run, as agreed.

Tests (pure): live-equality for edge/none/histogram, and minimum curvature; finer cell measures normalisation again (decision 3); manual gains (decision 11); coverage whole counts; absent grid; cube vs stream equal; cancel within one grid; progress order; stop inside the solve; another CRS (fake `world_to_frame`, equals the pre-shifted grid, called 0 times at spec time, same count each run); lattice missing the grid; estimate parts; resident cube counted by covered cells; refusal copy exact; never reads `cube.mean`; imports without Qt (subprocess); real data: ten local lines at 0.05 and 0.025 m, finite coverage. Core: `frame_lattice` x2.

## Files changed
- packages/nsgeo-core/src/nsgeo/slices/display.py, __init__.py; packages/nsgeo-core/README.md; packages/nsgeo-core/tests/test_slices_display.py
- packages/nsgeo-qgis/nsgeo_qgis/export_pipeline.py (new), slice_export.py, slices_plan.py
- packages/nsgeo-qgis/scripts/bench_site.py
- packages/nsgeo-qgis/tests/pure/test_pure_export_pipeline.py (new)

## Self-review and concerns
1. **`world_to_frame` is called twice per grid** (a coarse probe of at most 96 x 96 lattice points to find the grid's window, then the window's points), because only the output-to-frame direction is available and the window cannot be found otherwise. R2 says "once per grid". Alternative: add an optional `extent` field to `ExportGrid` (frame extent in the output CRS, computed by T5 like `SiteEngine._extent_in`) and call once. Cheap to switch; I did not change the specified interface.
2. **`held_bytes` excludes the prepared lines** (shared with the live engines, never copied; they are in `per_band["lines"]` for information). If the controller counts them, the walkthrough-scale lines add 0.25 GB here and more with 512 samples.
3. **Residency** is judged grid by grid against what the export has left of the budget, not against the full budget each, so ten grids that each fit are not all resident (a deviation from "choose_residency on that grid's estimate"; it still goes through `choose_residency`).
4. Memory estimate constants (`TAP_BYTES_PER_PIXEL` 52, `GATHER_BYTES_PER_PIXEL` 56, `BAND_BYTES_PER_CELL` 12, `STREAM_BYTES_PER_CELL` 12, `SOLVE_BYTES_PER_CELL` 36, compose 9) are calibrated on the bench only with all grids streaming; a resident-cube run was measured only through the equivalence test, not for memory.
5. Synthetic noisy data may make minimum curvature slower or faster than real data; the real-data test checks coverage, not time.
6. `export_pipeline.py` is not in the CI mypy list and mypy cannot analyse it without installed stubs for `nsgeo`; it is typed and ruff-clean.

## Fix report (controller ruling on the budget)
- `EXPORT_BUDGET_BYTES = DEFAULT_BUDGET_BYTES`, final (PROVISIONAL dropped) in `slices_plan.py`.
- Module docstring decision rewritten: band by band at 1.5 GB; 0.025/0.0125 refused with the finest fitting pixel; lifting the ceiling is a follow-up. Finest pixel that fits by `estimate_export`, 1 mm bisect, bench geometry: 0.021 m at a 0.025 m cell, 0.016 m at a 0.05 m cell.
- The one place-name mention (a test docstring) now says "the ten local lines"; grep of the commit and touched files finds none.
- Commit amended to `ee7ff34 feat(export): a Qt-free export pipeline at any cell and pixel, with a memory budget` (trailer kept, unpushed).
- Run: `pytest packages/nsgeo-qgis/tests/pure/` -> 255 passed, 1 skipped; `ruff check .` and `ruff format` clean; CI mypy line: Success, 43 files.
