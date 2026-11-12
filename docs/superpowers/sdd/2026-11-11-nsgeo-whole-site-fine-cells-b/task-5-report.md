# Task 5 report

Status: DONE (one commit, 0e77de4, not pushed). Full QGIS tier: 1693 passed (16 min). Pure tier: 266 passed. ruff check, ruff format --check and the CI mypy line are clean. The full tier ran before one last edit to `_add_export_layer` (it now catches any exception from `write_style`); the dialog, task and export-dialog files (73 tests) were re-run after it and pass.

## Obligations
1. Snapshot: `site_export_spec` and `grid_export_spec` (with `site_export_job` and `grid_export_job` that also build the plans and the coverage companion) read engines and session once on the GUI thread. They hand over the engines' own `PreparedLine` objects, which a test pins by identity. This grid uses gain 1.0 and method "none". New `SiteEngine.lattice_at(cell, pixel)`.
2. Another CRS: `site_export.world_to_frame(source, target, context)` is a closure over two authids and a copied transform context. It builds a fresh `QgsCoordinateTransform` per call and raises if invalid. A QGIS-tier test exports with grid B in EPSG:32617 and compares to `slice_at`.
3. Every plan carries the export's own cell, pixel and lattice (`plan_site_export` takes `cell` and `lattice` as required arguments; `plan_export` takes `cell` and `pixel`).
4. Dialog: `cell_floor` is the largest ready grid's `smallest_safe_cell`. The `preview` callables (`export_flow.site_preview` and `grid_preview`) include the coverage companion in `file_bytes`. The dialog is modal (`exec`, `deleteLater` in `finally`) and titled "Export site GeoTIFF" for the site.
5. Replace: `layers_to_replace()` are removed before the task starts and the new layers added after. A test checks the old layer is gone while the task is held.
6. A second Export is refused plainly ("already running") both before the dialog and if `start_export` returns False.
7. Cancel: `site_closed` and `unload` call `_cancel_export`. It bumps `_export_epoch` first, so a queued cancel's synchronous `on_done` sees the site is gone. Unload also waits up to 5 s.
8. Late cancel: `on_done` compares the epoch and `session.is_open`. If the site changed, the file stays on disk, nothing is added, and a Warning says so.
9. On success: `write_style` for values (measured limit, panel colormap, source unipolar) and for the companion (its own limit, `CountsClip`, unipolar colormap), then the layer, then the temporal properties, then `exported {n} bands to {path} ({cell:g} m cell, {pixel:g} m pixels)`. A left-out grid gives the message at Warning. A companion failure is its own Warning. A failure gives a plain sentence at Critical (`plain_export_error`) and the raw text goes to the log. `on_done` never raises (it logs and shows a message).
10. Spy tests for This grid and the site: recorders on the live engines, site engine and session show nothing called off the GUI thread, and the writer ran on a worker thread.
11. R9: `test_a_live_cell_export_equals_the_live_slice_band_by_band`. Bands and factors match `slice_at` at 1e-5 and NaN positions agree.
12. R10: removed `export_slices`, `export_site`, `write_coverage`, `write_site_coverage`, both writers' `write`, `SliceWriter`, `SiteWriter`, `_export_progress`, `_bands_are_slow`, `_mtime_ns`, `_remove_partial`, and `SlicesDock.refining_paused` (grep showed no remaining caller). Their GUI-thread tests are deleted or rewritten onto the task.
13. R11: removed `SiteEngine.export_refusal`, `_export_refusal` and `slices_plan.site_export_refusal`, plus the tooltip's refusal half. `is_preview` is now "drawn lattice pixel differs from the full lattice's". `preview_note` still works.
14. A missing target folder is created with `mkdir(parents=True)`. If that fails, the plugin says so plainly at Critical.
15. `coverage_path(target)` is used wherever a companion path is needed.

## Tests rewritten
- WindowModal progress, `processEvents` cancel, wait cursor and the slow-first-band progress tests are deleted. Their behaviour is now the task: the live view stays usable, cancel from the task list, cancel on close/unload.
- The refine-paused test is now "an export leaves a running refine alone", for This grid and the site.
- The `_remove_partial` mtime-rule test is now "a cancelled export never removes a file it did not reach", with the old target untouched because writing goes to a partial.
- New tests:
  - a preview site exports at full detail;
  - a finer site export cell (0.25 to 0.125 on site3) names the cell and pixel and the file is twice the width and height;
  - This grid at a finer pixel is twice the width and height;
  - the coverage companion is written and styled;
  - a replaced target;
  - a held second export;
  - the dialog's default path and cell floor.
- Shared helpers (`drive_export_dialog`, `wait_for_export`, `ExportGate`) are in `tests/plugin_testing.py`.

## TDD evidence
- RED: I copied the new test files onto a clean worktree at HEAD (135682e). `test_plugin_site_export.py` and `test_plugin_slice_export.py` fail to collect (`ImportError: grid_export_job`). `test_this_grid_at_a_finer_pixel_is_twice_the_width_and_height` fails (no file is written; the old flow bypassed the dialog).
- GREEN: the focused files, then the full tier.
- Honest caveat: I wrote the snapshot builders before their tests, because the plan-level helpers depend on them. The R9 test passed on its first run.

## Preview cost (obligation 4)
Ten-grid bench geometry (400 lines, `scripts/bench_site.py`), one `estimate_export` call:
- About 105 ms at every cell and pixel tried, over the ~100 ms threshold; the time is `covered_cells`.
- Fix: a `CoveredCache` (optional second argument of `estimate_export`) memoises the count per (grid, frame, lines), and the preview callables own one.
- Result: a pixel change at a known cell costs 1 ms; a new cell costs about 105 ms.
- Seven pixel steps at one cell took 111 ms in total.
- A pure test pins that the cache counts once per grid per cell and changes no figure.
- I did not time the snapshot builders on their own; they are `lattice_at` plus frame constructors.

## Concerns
- Other-CRS grids transform point by point (as `SiteEngine._transform` does), so a very fine export of such a grid is slow on the worker.
- A second `plugin.unload()` after an unload test runs through the existing fixture without trouble, but unload is not otherwise pinned as idempotent.
- `plan_export` keeps `cell` and `pixel` optional (defaulting to the live cell) for existing callers; the plugin always passes both.

## Files
- Source (`packages/nsgeo-qgis/nsgeo_qgis/`): `plugin.py`, `site_export.py`, `slice_export.py`, `site_engine.py`, `slices_plan.py`, `export_pipeline.py`, `ui/site_scope.py`, `ui/slices_dock.py`, new `export_flow.py`.
- Tests (`packages/nsgeo-qgis/tests/`): `plugin_testing.py`; pure `test_pure_slices_plan.py`, `test_pure_export_pipeline.py`; QGIS-tier `test_plugin_slice_export_dialogs.py`, `test_plugin_site_scope.py`, `test_plugin_slice_export.py`, `test_plugin_site_export.py`, `test_plugin_site_engine.py`.

---

# Fix report, round 1

## I1 (R20): replace removes only what this job writes, and puts it back on cancel or failure
- `_export_dialog` now removes only the layers whose source is the values file or its `.qml`, or the companion or its `.qml` when this job writes the companion. Each removed layer is remembered as (name, file) and never held as a layer, so no file stays open.
- New `_restore_layers`: on cancel, failure and the `start_export` False path it re-adds each removed layer from its unchanged file under the same name (a `.qml` beside it applies as the default style). The message says "... put back as before". It does nothing if the site has closed or changed since (epoch check), and does not run after success.
- Tests (`test_plugin_slice_export_dialogs.py`):
  - `test_a_coverage_off_re_export_keeps_the_companions_layer`
  - `test_a_cancelled_replace_puts_the_old_layers_back`
  - `test_a_failed_replace_puts_the_old_layers_back`
  - The last two check both layers are back in the group, the old file is unchanged, and the message says so.

## I2 (R21)
- `plan_export` now takes `cell` and `pixel` as required keyword-only arguments. The three tests that relied on the default now pass `engine.frame.cell`.

## I3
- New helpers `assert_styled_as` and `read_bands` in `tests/plugin_testing.py`. `assert_styled_as` checks the renderer type, the class range, the first and last colour stops against the named colour map, and the first and last stop values.
- This grid: the values layer's limit equals `limit_over_slices` with the panel's clip over the file's own bands, with the palette `amp_heat`. The companion is unipolar, spans 1 to the largest count, and uses the counts colour map.
- Site (`test_the_coverage_companion_is_written_styled_and_a_failure_of_it_is_its_own`): the same checks, with the dock's palette and source polarity.

## Commands and output
- `ruff check .`: All checks passed. `ruff format --check .`: 191 files already formatted. CI mypy line: Success, no issues found in 43 source files.
- Full QGIS tier, foreground in the background task, after the last edit: `1696 passed in 892.32s (0:14:52)`.

---

# Fix report, round 2 (restore path)

## Changes (`plugin.py`)
- `_restore_layers` puts each layer back in its own `try/except`, so one failure never stops the rest. The raw error goes to the QGIS log. It returns two lists: the names put back and the names that could not be (file missing, unreadable, or an error). A new `_restore_note` turns them into words: "X was put back; Y could not be put back; add it again from its file".
- The cancel and failure messages use that note. A cancel that lost a layer is shown at Warning, otherwise Info. A restore error no longer reaches the outer "could not be added to the map" message.
- "as before" is dropped: temporal properties and the layer's place in the group are not reapplied, and I only fixed the wording.
- The `start_export` False path uses the same note.

## Tests (`test_plugin_slice_export_dialogs.py`)
- `test_a_cancelled_replace_names_a_layer_whose_file_vanished`: the companion file is deleted mid-export; the cancel message names it as not put back, at Warning, and the other layer is back.
- `test_a_re_add_that_raises_still_restores_the_other_layer`: the raw error is logged, the other layer is restored, and the message is the cancel's.
- The earlier cancel and fail replace tests now expect "put back".

## Commands and output
- Export dialog, task, dialog, slice-export and site-export test files: 163 passed in 63 s.
- `test_plugin_site_scope.py`: 127 passed in 215 s.
- `ruff check .`: All checks passed. `ruff format --check .`: 191 files already formatted.
