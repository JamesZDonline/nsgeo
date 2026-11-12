# Task 1 report: cuts in the survey file, and the section maths

Commit 97fdfb9 on nsgeo-m15-cut-anywhere (pushed). Status: DONE_WITH_CONCERNS.

## Implemented
- `nsgeo/model/cut.py`: `Cut`, `cut_key`, `is_cut_key`, `CUT_KEY_PREFIX` (re-exported from `nsgeo.model`). `Site.cuts` plus two `validate` checks (duplicate ids, unknown grid).
- `Grid.to_local`.
- `project.py`: `CUTS_SCHEMA_VERSION = SCHEMA_VERSION + 1 = 2`, `READABLE_SCHEMA_VERSIONS = (1, 2)`. Cuts are saved/loaded; the version is 2 only when cuts exist. A malformed entry or an unknown grid is a `ProjectError` (load checks the grid itself, because `validate` raises ValueError).
- `nsgeo/slices/section.py` (re-exported): `SectionColumns` (`tap_cells` is a cached property), `section_columns`, `SectionCrop`, `section_crops`, `smoothing_reach_cells`, `finish_section`, `plan_section_curvature`, `solve_section_level`, the two constants. The module docstring records the spec §5 measurements.
- `render.section_rgba8`.
- README tables updated for every new public name (the public-API test requires it); `__all__` kept sorted.
- Column count: `ceil(length/step - 1e-9) + 1`. The 1e-9 stops a length of exactly N steps (30.000000000000004) growing a sliver column. Zig-zag test lengths are not near an integer, so `ceil(length/0.1)+1` still holds.
- Crops: pieces are runs of consecutive inside columns, cut again when a piece would exceed `piece_m` of distance. Each box is the nearest cells plus margin, widened to hold every positive-weight tap, then clipped to the frame. Zero-weight taps carry clipped id 0 and are ignored for the box.

## TDD evidence
- RED: `pytest tests/test_cut.py tests/test_grid.py` -> `ImportError: cannot import name 'CUT_KEY_PREFIX'`. `pytest tests/test_project.py` -> `ImportError: cannot import name 'CUTS_SCHEMA_VERSION'`. `pytest tests/test_slices_section.py tests/test_render.py` -> `ModuleNotFoundError: No module named 'nsgeo.slices.section'`.
- GREEN (focused): 174 passed, 6 xfailed across the six touched test files.

## Full verification
- core + pure: 1280 passed, 5 skipped, 6 xfailed.
- ruff check and format --check: clean. mypy (CI list): no issues in 46 files.

## CONCERN: the curvature crop tolerance fails on the ten real lines
The plan's 1e-3 tolerance with margin `ceil(SECTION_MARGIN_M/0.05)+1` = 21 cells is NOT met here (error as a share of the range, worst of levels 30/90/150, cell 0.05, max distance 0.25):

| path | 1 m margin | 2 m | 4 m |
|---|---|---|---|
| along x | 1.8-3.2% | 0.13-0.19% | about 1e-5 (measured at the level of the 81-cell check) |
| along y | 0.27-0.6% | 0.01-0.03% | |
| diagonal | 0.46-1.1% | 0.04-0.05% | |

At 0.2 m, 1 m margin: 0.14-0.64%. The spike's 0.0015% / 0.07% is not reproduced. The error is a crop-boundary effect: it falls monotonically with margin (along x, level 30: 21 cells 1.8%, 41 cells 0.13%, 81 cells 7.8e-6, 200 cells 4.5e-6), and a single piece with the same 21-cell margin gives the same error, so piece seams are not the cause. A window mean (`slice_levels(10, 28)`) gives the same error, so it is not single-level noise. Likely cause: these ten lines differ in level from line to line (row means 0.32-0.46), which excites a long-wavelength mode a 1 m box cuts off; Grid 1's data may be smoother. The machinery is right: with a 4 m margin both `smoothing` 0 and 0.1 agree within 1e-3 (test `test_curvature_on_wide_crops_matches_the_whole_frame`, passing).

I did not loosen the tolerance. The two brief tests (`test_curvature_on_crops_matches_the_whole_frame_solve`, `..._with_smoothing_...`, three paths each) are `xfail(strict=True)`, so they turn red when the margin or solver changes. Decision for the coordinator: raise `SECTION_MARGIN_M` (2 m passes at 0.2 m but along-x at 0.05 m is still 1.3-1.9e-3, so about 3 m), accept a looser tolerance, or reproduce the spike on Grid 1's real cube. Plan call 7's timing (0.10 s a level) was measured at 1 m and will grow with margin.

## Self-review
- Other tests as briefed all pass: anchor test (exact equality on cell-centre columns), blend-as-slice, every-level and window equalities at atol 1e-5 x range for none/idw/kriging x smoothing (0, 0.1), blank beyond max distance, crop coverage invariants.
- The blank-beyond-max-distance test uses IDW with a path at y = 1.0 (boundary between rows 4 and 5, no line row); I chose y and the method myself.
- `finish_section` with smoothing samples each crop with `Taps.take`, reusing one canvas; stale canvas cells outside the current crop are never read.
- `Cut.locate` offset is unsigned.
- `test_every_inside_column...` checks only positive-weight taps lie in the crop.

## Files
Created: packages/nsgeo-core/src/nsgeo/model/cut.py, packages/nsgeo-core/src/nsgeo/slices/section.py, packages/nsgeo-core/tests/test_cut.py, packages/nsgeo-core/tests/test_slices_section.py.
Modified: packages/nsgeo-core/README.md, src/nsgeo/{geometry/grid.py, model/__init__.py, model/survey.py, project.py, render.py, slices/__init__.py}, tests/{test_grid.py, test_project.py, test_render.py}.

## Fix report: crop margin in line spacings (coordinator ruling)
Commit: see `git log` (fix(core): crops for minimum curvature reach six line spacings).
Changed in section.py: `SECTION_MARGIN_M` -> `SECTION_MARGIN_SPACINGS = 6.0`; new `curvature_margin_cells(settings, cell, spacing_m)` = `max(ceil(6 * spacing / cell), smoothing_reach_cells) + 1`. Exports, README rows and docstring updated; spike rows that no longer applied (crop timing and crop-vs-whole) replaced by the measured margin table and per-level times.
Measured (worst of 3 levels x 3 paths, share of range, no smoothing): 0.2 m cells at 2/4/6/8 spacings 0.64% / 0.017% / 0.00016% / 0.00003%; 0.05 m cells 3.2% / 0.19% / 0.0022% / 0.0020%. 6.0 passes every case (max 2.2e-5), so the constant stays 6.0, not 8.0. Time a level at 6 spacings, 0.05 m: 0.18 s along x (12 m), 0.07 s along y, 0.20 s diagonal.
Tests: `test_curvature_margin_is_the_larger_of_the_spacings_and_the_smoothing_plus_one` (max and +1); the two curvature tests are now ordinary, parametrised over cell 0.05 and 0.2, three paths, with and without smoothing (12 cases), all at 1e-3. The strict xfails and the 4 m test were removed.
Command: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider` -> 1291 passed, 5 skipped. Section file alone: 43 passed. ruff check/format and mypy (CI list) clean.
Plan call 7's "within 0.0015%" and 0.10 s a level were spike numbers on Grid 1 and no longer stand as stated for these lines.
