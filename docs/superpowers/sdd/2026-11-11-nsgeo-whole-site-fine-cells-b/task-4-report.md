# Task 4 report: export dialog (option B)

Status: DONE_WITH_CONCERNS. Commit: see `git log` (feat(export): the export dialog, with a summary, a memory check and a disk check).

## Implemented
- `slices_plan.py`: frozen `ExportPreview`, `summary_lines(preview)` (Bands, Picture, Grids, Slices, Normalisation, File; the dialog appends Disk), `finest_fits(held_at, cell, pixel, budget)` (1 mm grid; pixel by bisection in [pixel, cell]; cell by doubling 2x/4x/8x then bisection, None past 8x; O(log) calls).
- `ui/export_dialog.py`: `ExportDialog(preview, cell_floor, live_cell, default_path="", project=None, parent=None)`, `ExportChoice(path, cell, pixel)`, `targets_in_use(project, paths)`, `target_paths(path)`. Fields, debounce (150 ms), memory and disk refusals (exact copy), in-dialog Replace/Cancel strip, `layers_to_replace()`, `summary_rows()`, `refresh_now()`.
- Tests: 7 new pure (summary x3, finest_fits x4) and 20 QGIS in `tests/qgis/test_plugin_export_dialog.py`.

## Results
- New QGIS file: 20 passed. Pure tier (incl. test_no_orphan_signals): 262 passed, 1 skipped. ruff check, ruff format --check, CI mypy line: clean.
- RED: the dialog test file failed at collection with `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.export_dialog'` before the dialog existed. GREEN: 20 passed after implementing (and fixing three test/impl slips along the way).
- Honest note: the pure helpers were written before their pure tests, so those have no recorded RED run (one test then failed because my test had the monotonic direction inverted, fixed in the test).

## Decisions / things to know
- Pixel spin has 4 decimals (cell has 3): a 0.0125 m pixel (the half-cell case in the mock-up and ruling) cannot be typed at 3. finest_fits still answers on a 1 mm grid.
- Cell floor is rounded up to a millimetre (the spin box rounds to its decimals; rounding down could go below the safe cell).
- Pixel follows the cell until the user sets it finer; its maximum always equals the cell.
- Export is disabled while a debounce is pending (stale estimate) and when no path is set.
- Over-budget search runs `preview` (Task 5's held_at) only when over budget: about 2 x log2(range) calls (tests pin < 30).
- finest cell is strictly above the current cell (spec), so 0.025 m is reported as 0.026 m in the pinned example.
- Width rule: the Slices dock pins `minimumSizeHint().width() <= 360`; the dialog test pins the same.
- Several layers in use produce a plural variant of the copy ("A and B are open ... Replace them?"); the single-layer copy is exact.
- Test teardown: the `make` fixture must `deleteLater`, clear its list and flush DeferredDelete, else the dialog is destroyed after the session's `exitQgis()` and segfaults.
- Summary File row reads "about X before compression, plus a style file" (mock-up's "tiled with overviews" dropped: not true of small exports).

## Concerns
- Task 5 must pass `file_bytes` including the companion, and a `preview` cheap enough for the debounce on the GUI thread.
- Call site must use `deleteLater` in a `finally` and remove `layers_to_replace()` before starting the task.

## Fix round 1
1. R4a: `finest_fits` checks the current cell first; if it fits at pixel = cell, finest_cell is None. Tests: pure inclusive case `(None, 0.02)`, pure still-offered case, dialog tests updated (pixel sentence only) plus a cell-sentence case.
2. Low-disk copy now names 1.2 x the estimate as "needed"; test updated (720 MB).
3. `reason_label` moved inside the "What will be written" group (test pins its parent).
4. `coverage_path(target)` added beside `partial_path` in slice_export.py; `target_paths` uses it; tests for both (incl. .tif and .tiff targets).
Run: export_dialog + slice_export QGIS files 87 passed; pure tier 264 passed, 1 skipped; ruff check/format and CI mypy clean.
